from unittest.mock import Mock

import psycopg
import pytest

from ingest.building_on_demand import process_one
from ingest.common import RawStore, Settings
from ingest.geocode import resolve_one
from ingest.juso import JusoCoordinates, resolve_address
from tests.ingest.test_building_on_demand import PNU, title
from tests.ingest.test_juso import item, search_response
from tests.integration.test_s3_auth import as_user, user

ADDRESS = "서울특별시 강남구 테스트로 88887"


class TransactionProxy:
    autocommit = True

    def __init__(self, db):
        self.db = db

    def execute(self, *a, **kw):
        return self.db.execute(*a, **kw)

    def transaction(self):
        return self.db.transaction()


def enqueue(db, *, coordinates=True):
    db.execute(
        """insert into ingest_private.building_address_requests
      (address,pnu,geom,coordinate_source,requested_at) values(%s,%s,
      case when %s then extensions.st_setsrid(extensions.st_makepoint(127.05,37.5),4326)
      end,%s,'1900-01-01')""",
        (
            ADDRESS,
            PNU if coordinates else None,
            coordinates,
            "registration" if coordinates else None,
        ),
    )


def test_registered_input_rpc_updates_held_job_and_is_auth_only(db):
    owner = user(db)
    db.execute(
        "insert into ingest_private.building_address_requests(address,status) "
        "values(%s,'needs_coord')",
        (ADDRESS,),
    )
    as_user(db, owner)
    result = db.execute(
        "select public.score_inputs(37.5,127.05,800,3,%s,%s)", (ADDRESS, PNU)
    ).fetchone()[0]
    assert result["meta"]["schema_version"] == "1.3"
    db.execute("reset role")
    job = db.execute(
        "select pnu,extensions.st_x(geom),extensions.st_y(geom),coordinate_source "
        "from ingest_private.building_address_requests where address=%s",
        (ADDRESS,),
    ).fetchone()
    assert job == (PNU, 127.05, 37.5, "registration")
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute("set local role anon")
        db.execute("select public.score_inputs(37.5,127.05,800,3,%s,%s)", (ADDRESS, PNU))


def test_worker_registered_input_skips_all_coordinate_calls(db, tmp_path, monkeypatch):
    enqueue(db)
    forbidden = Mock(side_effect=AssertionError("Coordinate API must never run"))
    monkeypatch.setattr("ingest.juso.batch_request_address", forbidden)
    monkeypatch.setattr("ingest.geocode.request_vworld", forbidden)
    t = {**title(), "newPlatPlc": ADDRESS}
    client = Mock(request_count=2)
    client.group.side_effect = [[t], [dict(t, flrGbCd="20", flrNo=3, area=173.68)]]
    result = process_one(
        TransactionProxy(db),
        tmp_path,
        geocoder=forbidden,
        client_factory=lambda _: client,
        store=RawStore(Settings(local_root=tmp_path / "raw")),
    )
    assert result["status"] == "ready"
    assert result["pnu"] == PNU
    assert result["register_calls"] == 2
    forbidden.assert_not_called()
    assert db.execute(
        "select status from ingest_private.building_address_cache where address=%s", (ADDRESS,)
    ).fetchone() == ("ready",)


def test_new_rpc_queue_insert_already_contains_registered_input(db):
    as_user(db, user(db))
    # Outside the current building load footprint, ensuring the normal RPC enqueues.
    db.execute("select public.score_inputs(37.65,127.03,800,3,%s,%s)", (ADDRESS, PNU))
    db.execute("reset role")
    assert db.execute(
        "select pnu,extensions.st_x(geom),extensions.st_y(geom),coordinate_source "
        "from ingest_private.building_address_requests where address=%s",
        (ADDRESS,),
    ).fetchone() == (PNU, 127.03, 37.65, "registration")


def test_existing_approved_cache_is_reused_without_new_coordinate_api(db, tmp_path, monkeypatch):
    db.execute(
        """insert into public.geocode_cache
      (address,provider,geom,geocode_failed,source,source_version)
      values(%s,'kakao',extensions.st_setsrid(extensions.st_makepoint(127.05,37.5),4326),
      false,'preserved approved snapshot','fixture')""",
        (ADDRESS,),
    )
    forbidden = Mock(side_effect=AssertionError("Existing coordinates must be reused"))
    monkeypatch.setattr("ingest.juso.batch_request_address", forbidden)
    assert (
        resolve_one(TransactionProxy(db), ADDRESS, key="", budget=1, journal=tmp_path) == "cached"
    )
    forbidden.assert_not_called()
    assert (
        db.execute(
            "select count(*) from ingest_private.geocode_requests where address=%s", (ADDRESS,)
        ).fetchone()[0]
        == 0
    )


def test_missing_coordinates_hold_without_api_or_cache(db, tmp_path, monkeypatch):
    enqueue(db, coordinates=False)
    monkeypatch.setenv("JUSO_COORD_ENABLED", "false")
    forbidden = Mock(side_effect=AssertionError("API must not run before approval"))
    monkeypatch.setattr("ingest.juso.batch_request_address", forbidden)
    monkeypatch.setattr("ingest.geocode.request_vworld", forbidden)
    result = process_one(TransactionProxy(db), tmp_path, client_factory=forbidden)
    assert result["status"] == "needs_coord"
    forbidden.assert_not_called()
    assert db.execute(
        "select status from ingest_private.building_address_requests where address=%s", (ADDRESS,)
    ).fetchone() == ("needs_coord",)
    assert (
        db.execute(
            "select count(*) from ingest_private.building_address_cache where address=%s",
            (ADDRESS,),
        ).fetchone()[0]
        == 0
    )


def test_monthly_new_address_is_held_idempotently_until_juso_approval(db, tmp_path, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("No coordinate call before approval"))
    monkeypatch.setattr("ingest.juso.batch_request_address", forbidden)
    for _ in range(2):
        assert (
            resolve_one(TransactionProxy(db), ADDRESS, key="", budget=1, journal=tmp_path)
            == "needs_coord"
        )
    forbidden.assert_not_called()
    assert (
        db.execute(
            "select count(*) from ingest_private.geocode_requests where address=%s "
            "and status='needs_coord'",
            (ADDRESS,),
        ).fetchone()[0]
        == 1
    )
    assert (
        db.execute(
            "select count(*) from public.geocode_cache where address=%s", (ADDRESS,)
        ).fetchone()[0]
        == 0
    )


def test_wrong_registered_pnu_address_cannot_poison_shared_cache(db, tmp_path):
    enqueue(db)
    client = Mock(request_count=1)
    client.group.return_value = [title()]  # different road address
    with pytest.raises(RuntimeError):
        process_one(
            TransactionProxy(db),
            tmp_path,
            client_factory=lambda _: client,
            store=RawStore(Settings(local_root=tmp_path / "raw")),
        )
    assert (
        db.execute(
            "select count(*) from ingest_private.building_address_cache where address=%s",
            (ADDRESS,),
        ).fetchone()[0]
        == 0
    )


def test_held_monthly_job_resumes_only_with_native_juso_approval(db, tmp_path, monkeypatch):
    selected = item(roadAddrPart1=ADDRESS, rn="테스트로", buldMnnm="88887")
    native_calls = []

    def native(connection, address, key, coordinate_key):
        assert coordinate_key == "native-key"
        native_calls.append(1)
        provider = JusoCoordinates(
            coordinate_key,
            lambda x, y: (127.05, 37.5),
            lambda *_: search_response(
                [dict(bdMgtSn=selected["bdMgtSn"], entX="958000", entY="1944000")]
            ),
        )
        return resolve_address(
            address, key, provider, search=lambda *_: search_response([selected])
        )

    monkeypatch.setattr("ingest.juso.batch_request_address", native)
    monkeypatch.setattr(
        "ingest.geocode.request_vworld",
        Mock(side_effect=AssertionError("Batch must not call Vworld")),
    )
    kwargs = dict(key="search-key", coordinate_key="native-key", budget=100000, journal=tmp_path)
    proxy = TransactionProxy(db)
    assert resolve_one(proxy, ADDRESS, **kwargs) == "needs_coord"
    assert not native_calls
    assert resolve_one(proxy, ADDRESS, **kwargs, coordinates_enabled=True) == "success"
    assert resolve_one(proxy, ADDRESS, **kwargs, coordinates_enabled=True) == "cached"
    assert native_calls == [1]
    provenance = db.execute(
        "select provenance from public.geocode_cache where address=%s and provider='juso'",
        (ADDRESS,),
    ).fetchone()[0]
    assert provenance["location"]["coordinate_provider"] == "juso"
    assert provenance["location"]["source_crs"] == "EPSG:5179"
