import copy
import json
import zipfile

import duckdb
import pandas as pd
import pytest

from ingest.building_footprints import (
    WfsClient,
    height_contract,
    normalize_shp,
    read_shp_zip,
)
from ingest.building_register import (
    RegisterClient,
    current_pk,
    normalize_floors,
    parse_page,
    pnu_parts,
)
from ingest.common import RawStore, Settings


@pytest.mark.parametrize(
    "height,floors,code,expected",
    [
        (12.5, 1, "03000", (12.5, "source", False)),
        (None, 3, "04000", (9.9, "floors_estimate", True)),
        (0, 1, "03000", (4, "floors_estimate", True)),
        (0, 1, "04000", (4, "floors_estimate", True)),
        (None, 1, "07000", (4, "floors_estimate", True)),
        (None, 1, "01000", (3.3, "floors_estimate", True)),
        (0, 0, "03000", (None, "unknown", False)),
        (None, None, None, (None, "unknown", False)),
    ],
)
def test_height_contract_preserves_sources_and_unknowns(height, floors, code, expected):
    actual, source, estimated = height_contract(height, floors, code)
    assert actual == pytest.approx(expected[0]) if expected[0] is not None else actual is None
    assert (source, estimated) == expected[1:]


@pytest.mark.parametrize("height,floors", [(-1, 3), (float("inf"), 3), (0, 1.5)])
def test_invalid_height_attributes_are_not_silently_estimated(height, floors):
    with pytest.raises(ValueError):
        height_contract(height, floors, "03000")


def test_exact_current_pk_and_parcel_mapping():
    assert current_pk("100244567") == "10241100244567"
    new = "1234567890123456789012"
    assert current_pk(int(new)) == new
    with pytest.raises(ValueError):
        current_pk(float(new))
    pnu = "11680" + "10300" + "2" + "0004" + "0007"
    assert pnu_parts(pnu) == {
        "sigunguCd": "11680",
        "bjdongCd": "10300",
        "platGbCd": "1",
        "bun": "0004",
        "ji": "0007",
    }
    with pytest.raises(ValueError, match="land type"):
        pnu_parts("1168010300600000003")


def shp_row():
    row = {f"A{i}": "" for i in range(29)}
    row.update(
        A0=1,
        A1="gis1",
        A2="1168010300100040007",
        A3="1168010300",
        A4="서울특별시 강남구 개포동",
        A8="03000",
        A9="제1종근린생활시설",
        A16=0,
        A19="12345",
        A22="2026-09-06",
        A23="11680",
        A26=1,
        A27=0,
        source_geometry_wkb=b"fixture-geometry",
    )
    return row


def test_only_complete_shp_duplicates_collapse():
    one = shp_row()
    two = one | {"A0": 2}
    normalized, report = normalize_shp(pd.DataFrame([one, two]))
    assert len(normalized) == 1
    assert normalized.iloc[0].height_m == 4
    assert report["complete_duplicates_removed"] == 1
    two["A26"] = 2
    with pytest.raises(ValueError, match="conflicting"):
        normalize_shp(pd.DataFrame([one, two]))


def page(number, total=105, group=None):
    group = group or {"sigunguCd": "11680", "bjdongCd": "10100", "platGbCd": "0"}
    rows = [
        group | {"rnum": i + 1, "mgmBldrgstPk": 1234567890123456789000 + i}
        for i in range((number - 1) * 100, min(number * 100, total))
    ]
    return {
        "response": {
            "header": {"resultCode": "00"},
            "body": {
                "items": {"item": rows},
                "totalCount": str(total),
                "numOfRows": "100",
                "pageNo": str(number),
            },
        }
    }


def test_page_cache_preserves_large_pk_and_proves_pagination(tmp_path):
    calls = []

    def fetch(operation, params):
        calls.append(params)
        return page(params["pageNo"])

    group = {"sigunguCd": "11680", "bjdongCd": "10100", "platGbCd": "0"}
    client = RegisterClient(tmp_path, "2026-09-20", fetch=fetch)
    rows = client.group("getBrTitleInfo", group)
    assert len(rows) == 105 and len(calls) == 2
    assert rows[0]["mgmBldrgstPk"] == "1234567890123456789000"
    assert client.group("getBrTitleInfo", group) == rows and len(calls) == 2
    changed = RegisterClient(
        tmp_path / "other",
        "2026-09-20",
        fetch=lambda op, p: page(p["pageNo"], 105 if p["pageNo"] == 1 else 106),
    )
    with pytest.raises(ValueError, match="changed"):
        changed.group("getBrTitleInfo", group)


def test_auth_failure_and_normal_empty_response_are_distinct(tmp_path):
    with pytest.raises(ValueError, match="unsuccessful"):
        parse_page({"response": {"header": {"resultCode": "22"}}})
    assert parse_page(page(1, total=0))[0] == []

    def denied(*_):
        raise ConnectionError("Register HTTP 429")

    client = RegisterClient(tmp_path, "2026-09-20", fetch=denied)
    with pytest.raises(ConnectionError):
        client.page("getBrTitleInfo", {"sigunguCd": "11680"}, 1)
    assert client.request_count == 1
    assert len(list(tmp_path.rglob("*.error.json"))) == 1
    assert not [p for p in tmp_path.rglob("*.json") if not p.name.endswith(".error.json")]


def test_floor_multi_use_rows_and_identical_multiplicity_are_preserved():
    one = {
        "mgmBldrgstPk": "1234567890123456789012",
        "sigunguCd": "11680",
        "bjdongCd": "10300",
        "platGbCd": "0",
        "bun": "0004",
        "ji": "0007",
        "flrGbCd": "20",
        "flrNo": 1,
        "mainPurpsCd": "03000",
        "area": 30.5,
    }
    raw = pd.DataFrame([one, one | {"mainPurpsCd": "04000"}, one])
    normalized = normalize_floors(raw)
    assert len(normalized) == normalized.id.nunique() == 3
    assert normalized.register_pk.nunique() == 1
    assert normalize_floors(raw.assign(rnum=[80, 81, 82])).id.tolist() == normalized.id.tolist()


def wfs_response(features, total=None):
    return {
        "type": "FeatureCollection",
        "features": features,
        "numberMatched": total if total is not None else len(features),
        "numberReturned": len(features),
    }


def test_wfs_subdivision_deduplicates_tiles_and_proves_complete_union(tmp_path):
    feature = {"id": "one", "properties": {"col_adm_se": "11680"}}
    second = {"id": "two", "properties": {"col_adm_se": "11680"}}
    calls = []

    def fetch(bbox):
        calls.append(bbox)
        return wfs_response([feature], 2) if len(calls) == 1 else wfs_response([feature, second])

    client = WfsClient(tmp_path, "2026-09-20", fetch=fetch)
    result, proof = client.collect((0, 0, 2, 2))
    assert len(result) == 2 and proof["leaf_tiles"] == 4 and len(calls) == 5
    assert client.collect((0, 0, 2, 2))[0] == result and len(calls) == 5
    with pytest.raises(ValueError, match="application error"):
        client.validate({"response": {"status": "ERROR"}})


def test_original_archive_is_published_without_changing_any_bytes(tmp_path):
    original = tmp_path / "original.zip"
    with zipfile.ZipFile(original, "w") as archive:
        archive.writestr("original.dbf", "강남구".encode("cp949"))
    store = RawStore(Settings(local_root=tmp_path / "raw-root"))
    result = store.publish_archive("gis_buildings_shp", "2026-09", original)
    assert (store.settings.local_root / result["key"]).read_bytes() == original.read_bytes()


def test_shp_reader_reads_cp949_inside_zip_without_extracting(tmp_path, monkeypatch):
    row = shp_row()
    row.pop("source_geometry_wkb")
    # This GDAL build lacks a CP949 encoder; write the exact DBF bytes via Latin-1.
    row = {
        k: v.encode("cp949").decode("latin1") if isinstance(v, str) else v for k, v in row.items()
    }
    frame = pd.DataFrame([row, row | {"A0": 2, "A23": "11710"}])
    path = tmp_path / "fixture.shp"
    with duckdb.connect() as connection:
        connection.execute("INSTALL spatial")
        connection.execute("LOAD spatial")
        connection.register("rows", frame)
        connection.execute(
            """
          copy (select *,ST_GeomFromText('POLYGON((200000 540000,200010 540000,
             200010 540010,200000 540010,200000 540000))') geom from rows)
          to $target (format GDAL,driver 'ESRI Shapefile',
                           layer_creation_options ('ENCODING=ISO-8859-1'))
        """,
            {"target": str(path)},
        )
    prj = (
        'PROJCS["Korea 2000 / Central Belt 2010",GEOGCS["Korea 2000",'
        'DATUM["Geocentric datum of Korea",SPHEROID["GRS 1980",6378137,298.257222101]],'
        'PRIMEM["Greenwich",0],UNIT["degree",0.0174532925199433]],'
        'PROJECTION["Transverse_Mercator"],PARAMETER["latitude_of_origin",38],'
        'PARAMETER["central_meridian",127],PARAMETER["scale_factor",1],'
        'PARAMETER["false_easting",200000],PARAMETER["false_northing",600000],'
        'UNIT["metre",1],AUTHORITY["EPSG","5186"]]'
    )
    archive_path = tmp_path / "input.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        for suffix in (".shp", ".shx", ".dbf"):
            archive.write(path.with_suffix(suffix), "fixture" + suffix)
        archive.writestr("fixture.prj", prj)
    # The input reader must work after all external source components have disappeared.
    for component in tmp_path.glob("fixture.*"):
        component.unlink()
    monkeypatch.setattr(zipfile.ZipFile, "extractall", lambda *_a, **_k: pytest.fail("extraction"))
    monkeypatch.setattr(zipfile.ZipFile, "extract", lambda *_a, **_k: pytest.fail("extraction"))
    raw, parquet, manifest = read_shp_zip(archive_path, tmp_path / "output")
    assert len(raw) == 1 and raw.iloc[0].A4 == shp_row()["A4"]
    assert manifest["original_rows"] == 2 and manifest["source_srid"] == 5186
    assert parquet.exists() and not list(tmp_path.rglob("*.shp"))
    wrong = copy.deepcopy(manifest)
    wrong["zip_sha256"] = "different"
    (tmp_path / "output/shp-manifest.json").write_text(json.dumps(wrong))
    with pytest.raises(ValueError, match="differs"):
        read_shp_zip(archive_path, tmp_path / "output")
