from uuid import uuid4

import psycopg
import pytest

from ingest.database import connect_database
from ingest.geocode import resolve_one
from ingest.juso import VworldCoordinates, resolve_address


def test_independent_lookup_cannot_fall_back_to_kakao(db):
    import pandas as pd
    from psycopg.types.json import Jsonb

    from ingest.commerce_education_database import attach_geocodes

    address = "서울특별시 강남구 전환검증로 1 " + uuid4().hex
    db.execute(
        """insert into public.geocode_cache
        (address,provider,geom,geocode_failed,source,source_version)
        values(%s,'kakao',extensions.st_setsrid(extensions.st_makepoint(127.05,37.5),4326),
        false,'test','test')""",
        (address,),
    )
    db.execute(
        """insert into public.geocode_cache
        (address,provider,geocode_failed,failure_reason,source,source_version,provenance)
        values(%s,'juso',true,'not_found','test','test',%s)""",
        (address, Jsonb(dict(coordinate_policy="juso_only"))),
    )
    frame = pd.DataFrame([dict(address=address)])
    assert not attach_geocodes(db, frame).geocode_failed.iloc[0]
    result = attach_geocodes(db, frame, require_juso=True)
    assert result.geocode_failed.iloc[0]
    assert result.geocode_provider.iloc[0] == "juso"
    assert result.lng.iloc[0] is None


def test_juso_label_with_vworld_location_does_not_pass_independent_gate(tmp_path):
    from psycopg.types.json import Jsonb

    from ingest.geocode import GeocodeStopped

    address = "서울특별시 강남구 전환검증로 2 " + uuid4().hex
    with connect_database(local_only=True) as db:
        db.autocommit = True
        try:
            db.execute(
                """insert into public.geocode_cache
                (address,provider,geom,geocode_failed,source,source_version,provenance)
                values(%s,'juso',extensions.st_setsrid(extensions.st_makepoint(127.05,37.5),4326),
                false,'test','test',%s)""",
                (address, Jsonb(dict(location=dict(coordinate_provider="vworld")))),
            )
            with pytest.raises(GeocodeStopped, match="Unapproved cached"):
                resolve_one(
                    db,
                    address,
                    key="fake",
                    budget=100000,
                    journal=tmp_path,
                    require_juso=True,
                    requester=lambda *_: pytest.fail("API called"),
                )
        finally:
            db.execute("delete from public.geocode_cache where address=%s", (address,))


def test_juso_batch_cache_provenance_and_durable_claim(tmp_path):
    address = "서울특별시 강남구 테스트로 460 (" + uuid4().hex + ")"
    item = dict(
        admCd="1168010600",
        rnMgtSn="116803122001",
        udrtYn="0",
        buldMnnm="460",
        buldSlno="0",
        mtYn="0",
        lnbrMnnm="912",
        lnbrSlno="13",
        bdMgtSn="1168010600109120013" + "000001",
        roadAddrPart1=address,
        rn="테스트로",
        sggNm="강남구",
        emdNm="대치동",
    )
    search = dict(results=dict(common=dict(errorCode="0", totalCount="1"), juso=[item]))
    coordinate = dict(
        response=dict(
            status="OK",
            result=dict(crs="EPSG:4326", point=dict(x="127.05", y="37.5")),
            refined=dict(structure=dict(level4L="테스트로", level5="460", level2="강남구")),
        )
    )
    calls = []

    def request(*_):
        calls.append(1)
        return resolve_address(
            address,
            "fake",
            VworldCoordinates("fake", lambda *_: coordinate),
            search=lambda *_: search,
        )

    with connect_database(local_only=True) as db:
        db.autocommit = True
        try:
            kwargs = dict(key="fake", budget=100000, journal=tmp_path, requester=request)
            assert resolve_one(db, address, **kwargs) == "success"
            assert resolve_one(db, address, **kwargs) == "cached"
            assert len(calls) == 1
            provider, provenance = db.execute(
                """select provider,provenance
                from public.geocode_cache where address=%s""",
                (address,),
            ).fetchone()
            assert provider == "juso"
            assert provenance["selection"]["pnu"] == "1168010600109120013"
            assert provenance["location"]["coordinate_provider"] == "vworld"
        finally:
            db.execute("delete from public.geocode_cache where address=%s", (address,))
            db.execute("delete from ingest_private.geocode_requests where address=%s", (address,))


@pytest.mark.parametrize("role", ["anon", "authenticated", "service_role"])
def test_shared_cache_cannot_be_written_with_application_role(db, role):
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("set local role " + role)
        db.execute("update public.geocode_cache set source=source where false")
