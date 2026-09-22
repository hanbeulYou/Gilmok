from datetime import date

import pytest

from ingest.refresh import promote

SOURCE = "pr8_fixture"


def seed(db):
    db.execute("create temporary table pr8_values(value integer check(value>0)) on commit drop")
    db.execute("insert into pr8_values values(1)")
    promote(db, SOURCE, date(2026, 8, 31), "20260921T000000Z", {"old": True}, lambda db: None)


def test_failed_copy_preserves_data_and_active_manifest(db):
    seed(db)
    before = db.execute(
        "select * from ingest_private.refresh_snapshots where source=%s", (SOURCE,)
    ).fetchone()

    def broken(db):
        db.execute("delete from pr8_values")
        db.execute("insert into pr8_values values(0)")

    with pytest.raises(Exception):
        promote(db, SOURCE, date(2026, 9, 30), "20261001T000000Z", {"new": True}, broken)
    assert db.execute("select value from pr8_values").fetchall() == [(1,)]
    assert (
        db.execute(
            "select * from ingest_private.refresh_snapshots where source=%s", (SOURCE,)
        ).fetchone()
        == before
    )


def test_idempotence_and_stale_run_cannot_replace_latest(db):
    seed(db)

    def replacement(db):
        db.execute("update pr8_values set value=2")

    assert promote(db, SOURCE, date(2026, 9, 30), "20261001T000000Z", {}, replacement)
    assert not promote(db, SOURCE, date(2026, 9, 30), "20261001T000000Z", {}, lambda db: 1 / 0)
    with pytest.raises(ValueError):
        promote(db, SOURCE, date(2026, 8, 31), "20261002T000000Z", {}, replacement)
    assert db.execute("select value from pr8_values").fetchall() == [(2,)]


@pytest.mark.parametrize("role", ["anon", "authenticated"])
def test_active_manifest_is_private(db, role):
    db.execute(f"set local role {role}")
    with pytest.raises(Exception), db.transaction():
        db.execute("select * from ingest_private.refresh_snapshots")


def test_repository_dispatch_pending_to_ready_without_external_calls(db, tmp_path):
    from contextlib import contextmanager
    from unittest.mock import Mock

    from ingest.address_dispatch import drain, validate_event
    from ingest.building_on_demand import process_one
    from ingest.common import RawStore, Settings

    address = "서울특별시 강남구 테스트로 88888"
    db.execute(
        "insert into ingest_private.building_address_requests(address) values(%s)", (address,)
    )

    # Outer rollback keeps fabricated provider data out of the real local snapshot.
    # In production target_database is genuinely autocommit for durable claims.
    class TransactionProxy:
        autocommit = True

        def execute(self, *a, **kw):
            return db.execute(*a, **kw)

        def transaction(self):
            return db.transaction()

    @contextmanager
    def factory():
        yield TransactionProxy()

    parcel = dict(sigunguCd="11680", bjdongCd="10600", platGbCd="0", bun="0912", ji="0013")
    title = dict(
        parcel,
        mainAtchGbCd="0",
        newPlatPlc=address,
        mgmBldrgstPk="pr8-fixture",
        mainPurpsCd="04000",
        mainPurpsCdNm="제2종근린생활시설",
        grndFlrCnt=4,
        ugrndFlrCnt=1,
        heit=0,
        rideUseElvtCnt=0,
        emgenUseElvtCnt=0,
    )
    client = Mock(request_count=2)
    client.group.side_effect = [[title], [dict(title, flrGbCd="20", flrNo=3, area=173.68)]]
    response = dict(
        meta=dict(total_count=1),
        documents=[
            dict(
                x="127.05",
                y="37.5",
                address_type="ROAD_ADDR",
                road_address=dict(
                    road_name="테스트로",
                    main_building_no="88888",
                    sub_building_no="",
                    region_2depth_name="강남구",
                ),
                address=dict(
                    b_code="1168010600", main_address_no="912", sub_address_no="13", mountain_yn="N"
                ),
            )
        ],
    )
    store = RawStore(Settings(local_root=tmp_path / "raw"))
    # Prioritize only this fixture; any existing real pending job remains untouched.
    db.execute(
        "update ingest_private.building_address_requests set requested_at='2000-01-01' "
        "where address=%s",
        (address,),
    )
    validate_event("repository_dispatch", {"action": "gilmok_address_pending"})
    result = drain(
        factory,
        tmp_path / "worker",
        1,
        lambda connection, path: process_one(
            connection,
            path,
            geocoder=lambda _: response,
            client_factory=lambda _: client,
            store=store,
        ),
    )
    assert result["processed"] == 1
    assert db.execute(
        "select status from ingest_private.building_address_requests where address=%s", (address,)
    ).fetchone() == ("done",)
    cached = db.execute(
        "select status,expires_at-fetched_at,raw_key "
        "from ingest_private.building_address_cache where address=%s",
        (address,),
    ).fetchone()
    assert cached[0] == "ready" and cached[1].days == 30
    assert (tmp_path / "raw" / cached[2]).exists()
