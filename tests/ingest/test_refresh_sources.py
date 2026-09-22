"""Prove scheduled adapters reuse the real normalizers and preserve complete windows."""

import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock
from zipfile import ZipFile

import pandas as pd
import pytest

from ingest import academies, schools
from ingest.common import RawStore, Settings
from ingest.refresh_sources import Publication, _places, _rent, _trades
from ingest.seoul_transit import write_frame


@pytest.fixture
def args(tmp_path):
    return SimpleNamespace(
        directory=tmp_path,
        end_month="2026-08",
        snapshot="20260922T063000Z",
        quarter="2026-Q2",
        source="academies",
    )


@pytest.fixture
def publication(args):
    return Publication(args, RawStore(Settings(local_root=args.directory / "store")))


@pytest.mark.parametrize("source", ["academies", "schools"])
def test_places_refresh_uses_only_selected_source(args, publication, monkeypatch, source):
    from test_places import academy

    args.source = source
    frame = (
        pd.DataFrame([academy()])
        if source == "academies"
        else pd.DataFrame(
            [
                dict(
                    ATPT_OFCDC_SC_CODE="B10",
                    SD_SCHUL_CODE="001",
                    SCHUL_NM="학교",
                    SCHUL_KND_SC_NM="초등학교",
                    ORG_RDNMA="서울 삼성로 212",
                )
            ]
        )
    )
    raw = args.directory / "fixture.parquet"
    write_frame(frame, raw)
    monkeypatch.setattr(academies if source == "academies" else schools, "fetch", lambda _: raw)
    monkeypatch.setattr("ingest.geocode.resolve_one", Mock(return_value="cached"))

    def geocodes(db, frame):
        return frame.assign(lng=127.05, lat=37.5, estimated=False, geocode_failed=False)

    monkeypatch.setattr("ingest.commerce_education_database.attach_geocodes", geocodes)
    loader = Mock()
    monkeypatch.setattr("ingest.commerce_education_database.load_snapshot", loader)
    end, load = _places(args, publication, Mock(), {})
    assert end == date.today()
    load("db")
    assert loader.call_args.args[1] == source
    assert len(loader.call_args.args[2]) == 1
    assert len(publication.objects) == 2


def test_manual_store_archive_preserves_source_only_fields_outside_db(
    args, publication, monkeypatch
):
    args.source = "stores"
    args.end_month = "2026-06"
    archive = args.directory / "stores.zip"
    with ZipFile(archive, "w") as z:
        z.writestr(
            "소상공인_서울_202606.csv",
            "상가업소번호,시도코드,상권업종대분류코드,상권업종중분류코드,상권업종소분류코드,"
            "층정보,경도,위도,상호명,도로명주소,표준산업분류코드\n"
            "001,11,P1,P105,P10501,,127.05,37.5,원문상호,주소,P85501\n",
        )
    loader = Mock()
    monkeypatch.setattr("ingest.commerce_education_database.load_snapshot", loader)
    _, load = _places(args, publication, Mock(), {"stores.zip": archive})
    load("db")
    assert loader.call_args.args[1] == "stores"
    assert "상호명" not in loader.call_args.args[2].columns


def test_trade_adapter_retrieves_all_24_months_and_publishes_only_aggregates_to_loader(
    args, publication, monkeypatch
):
    from test_commercial_trades import row

    from ingest.legal_boundaries import GANGNAM_DONGS
    from ingest.refresh import month_window

    months = month_window(args.end_month, 24)
    raw = pd.DataFrame(
        [
            row(
                dealYear=m[:4],
                dealMonth=str(int(m[5:])),
                request_month=m.replace("-", ""),
                request_page=1,
                request_row=i,
                floor="2",
            )
            for m in months
            for i in range(5)
        ]
    )
    collect = Mock(return_value=raw)
    monkeypatch.setattr("ingest.commercial_trades.collect_months", collect)
    db = Mock()
    db.execute.return_value.fetchall.return_value = [
        (code, name, "MULTIPOLYGON EMPTY", "verified", "v") for code, name in GANGNAM_DONGS.items()
    ]
    loader = Mock()
    monkeypatch.setattr("ingest.rent_database.load_trade_snapshot", loader)
    _, load = _trades(args, publication, db, {})
    load("db")
    assert collect.call_args.args[:2] == ("202409", "202608")
    stats = loader.call_args.args[2]
    assert len(stats) < len(raw) and "dealAmount" not in stats
    assert loader.call_args.kwargs["report"]["eligible_count"] == 120
    assert len(publication.objects) == 25


def test_rent_refresh_preserves_unverified_mapping(args, publication, monkeypatch):
    from test_rent_publication import INTERSECTIONS, metadata, source_rows

    monkeypatch.setattr("ingest.rent_survey.collect_survey", lambda *_: source_rows())
    files = {}
    for name in (
        "rone-cls-office-names.json",
        "rone-cls-names.json",
        "rone-cls-small-names.json",
        "rone-cls-collective-names.json",
    ):
        path = args.directory / name
        path.write_text(json.dumps({"data": metadata()}))
        files[name] = path
    path = args.directory / "intersections.json"
    path.write_text(json.dumps(INTERSECTIONS))
    files["rent-intersections.json"] = path
    loader = Mock()
    monkeypatch.setattr("ingest.rent_database.load_survey_snapshot", loader)
    end, load = _rent(args, publication, Mock(), files)
    load("db")
    assert end == date(2026, 6, 30)
    areas = loader.call_args.args[1]
    assert not areas.mapping_verified.any() and areas.wkt.isna().all()
    assert len(publication.objects) == 3


@pytest.mark.parametrize("known_cells", [True, False])
def test_living_uses_three_published_months_and_blocks_unknown_cells(
    args, publication, monkeypatch, known_cells
):
    from ingest import living_population
    from ingest.refresh_sources import _living

    months = []

    def prepare(archive, month, path):
        months.append(month)
        write_frame(pd.DataFrame([dict(month=month, total=10)]), path)

    def aggregate(paths, start, end, destination):
        from ingest.seoul_transit import read_frame

        assert [read_frame(p).month.iloc[0] for p in paths] == months
        assert str(start) == "2026-06-01" and str(end) == "2026-08-31"
        write_frame(pd.DataFrame([dict(cell_id="fixture", total=10, age_15_19=None)]), destination)

    monkeypatch.setattr(living_population, "fetch_month", lambda month, dest: dest)
    monkeypatch.setattr(living_population, "prepare_month", prepare)
    monkeypatch.setattr(living_population, "aggregate_window", aggregate)
    loader = Mock()
    monkeypatch.setattr("ingest.population_database.load_living_population", loader)
    db = Mock()
    db.execute.return_value = [("fixture",)] if known_cells else []
    if not known_cells:
        with pytest.raises(ValueError, match="New cells"):
            _living(args, publication, db, {})
        loader.assert_not_called()
        return
    end, promote = _living(args, publication, db, {})
    promote(db)
    assert months == ["2026-06", "2026-07", "2026-08"]
    assert end == date(2026, 8, 31)
    assert loader.call_args.kwargs["source"] == "seoul_living_population_250m"
    assert loader.call_args.args[1][0]["age_15_19"] is None


def test_transit_keeps_calendar_days_and_both_modes(args, publication, monkeypatch):
    from test_transit import bus_row, hourly

    from ingest import seoul_transit
    from ingest.refresh_sources import _transit
    from ingest.verify_transit import SOURCES

    master = {
        "subway": dict(BLDN_ID="0001", BLDN_NM="환승역", ROUTE="2호선", LAT="37.5", LOT="127"),
        "bus": dict(
            STOPS_NO="100000001",
            STOPS_NM="정류장",
            XCRD="127",
            YCRD="37.5",
            NODE_ID="01001",
            STOPS_TYPE="일반",
        ),
    }
    requests = []

    def download(service, month, directory):
        requests.append((service, month))
        for kind, (_, counts_service, stops_service) in SOURCES.items():
            if service == stops_service:
                frame = pd.DataFrame([master[kind]])
                break
            if service == counts_service:
                row = (
                    dict(USE_MM=month, SBWY_ROUT_LN_NM="2호선", STTN="환승역", **hourly(30))
                    if kind == "subway"
                    else bus_row(USE_YM=month, **hourly(30))
                )
                frame = pd.DataFrame([row])
                break
        else:
            raise AssertionError(service)
        path = directory / (service + month + ".parquet")
        write_frame(frame, path)
        return path

    monkeypatch.setattr(seoul_transit, "download", download)
    monkeypatch.setattr("ingest.transit_database.seoul_stops", lambda db, stops: stops)
    loader = Mock()
    monkeypatch.setattr("ingest.transit_database.load_snapshot", loader)
    end, promote = _transit(args, publication, Mock(), {})
    promote(Mock())
    assert end == date(2026, 8, 31)
    assert len(requests) == 8
    counts = loader.call_args.args[2]
    assert counts.boarding.eq(90 / 92).all()
    assert set(counts.stop_id) == {"subway:0001", "bus:100000001"}
    assert loader.call_args.kwargs["start"] == "2026-06-01"
