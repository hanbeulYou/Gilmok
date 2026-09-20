"""Synthetic fixtures prove contracts; survey values are not actual R-ONE observations."""

import pandas as pd
import psycopg
import pytest

from ingest.legal_boundaries import GANGNAM_DONGS
from ingest.rent_database import load_survey_snapshot, load_trade_snapshot

DONG = "11680106"
POLYGON = "POLYGON((127.05 37.49,127.08 37.49,127.08 37.52,127.05 37.52,127.05 37.49))"
DISTRICT = "POLYGON((127.06 37.50,127.07 37.50,127.07 37.51,127.06 37.51,127.06 37.50))"


@pytest.fixture
def rent_db(db):
    db.execute("DELETE FROM public.commercial_trade_stats")
    db.execute("DELETE FROM public.legal_dongs")
    db.execute("DELETE FROM public.rent_survey")
    db.execute("DELETE FROM public.rent_areas")
    db.execute("DELETE FROM ingest_private.rent_snapshots")
    db.execute("""INSERT INTO public.legal_dongs(code8,name,geom,source,source_version)
        VALUES (%s,'synthetic dong',extensions.ST_Multi(extensions.ST_GeomFromText(%s,4326)),
                'synthetic fixture','test')""", (DONG, POLYGON))
    return db


def rpc(db, lng=127.065, lat=37.505, radius=500, floor=None, building_class=None):
    return db.execute("SELECT public.rent_inputs(%s,%s,%s,%s,%s)",
                      (lng, lat, radius, floor, building_class)).fetchone()[0]


def trade(db, kind, count, median, floor=None):
    db.execute("""INSERT INTO public.commercial_trade_stats(
      legal_dong_code,trade_kind,aggregation_level,floor,period_start,period_end,
      median_price_per_m2,sample_count,unknown_floor_count,area_basis,source,source_version)
      VALUES (%s,%s,%s,%s,'2024-09-01','2026-08-31',%s,%s,0,'building_area',
              'synthetic fixture','test')""",
               (DONG, kind, "all_floors" if floor is None else "floor", floor, median, count))


def area(db, code, *, level="district", verified=True, geom=DISTRICT):
    db.execute("""INSERT INTO public.rent_areas(
      area_code,area_name,level,gu_code,geom,valid_from,valid_to,mapping_verified,
      mapping_evidence,source,source_version)
      VALUES(%s,%s,%s,'11680',extensions.ST_Multi(extensions.ST_GeomFromText(%s,4326)),
             '2026-01-01','2026-12-31',%s,'synthetic official definition evidence',
             'synthetic fixture','test')""",
               (code, code, level, geom, verified))


def survey(db, code, *, building_class="office", rent=100, vacancy=7):
    db.execute("""INSERT INTO public.rent_survey(
      area_code,building_class,quarter,rent_per_m2,vacancy_rate,rent_statbl_id,rent_cls_id,
      vacancy_statbl_id,vacancy_cls_id,source,source_version)
      VALUES(%s,%s,'2026-Q2',%s,%s,'synthetic-rent','synthetic-code',
             'synthetic-vacancy','synthetic-code','synthetic fixture','test')""",
               (code, building_class, rent, vacancy))


def test_largest_sample_default_tie_and_five_sample_threshold(rent_db):
    db = rent_db
    trade(db, "general", 4, 900)
    trade(db, "collective", 3, 100)
    value = rpc(db)
    assert value["trade_building_type"] == "general"
    assert value["trade_sample_count"] == 4
    assert value["trade_median_per_m2"] is None
    assert value["meta"]["trade_missing_reason"] == "fewer_than_five_samples"
    db.execute("UPDATE public.commercial_trade_stats SET sample_count=5")
    value = rpc(db)
    assert value["trade_building_type"] == "collective"
    assert value["trade_sample_count"] == 5
    assert value["trade_median_per_m2"] == 100
    assert len(value["trade_by_building_type"]) == 2
    db.execute("UPDATE public.commercial_trade_stats SET sample_count=6 WHERE trade_kind='general'")
    assert rpc(db)["trade_building_type"] == "general"


def test_floor_is_exact_and_radius_does_not_redefine_dong_statistic(rent_db):
    db = rent_db
    trade(db, "general", 10, 900)
    trade(db, "collective", 5, 200, floor=-1)
    assert rpc(db, floor=-1)["trade_median_per_m2"] == 200
    assert rpc(db, floor=2)["trade_median_per_m2"] is None
    assert rpc(db, floor=2)["trade_sample_count"] is None
    a, b = rpc(db, radius=500), rpc(db, radius=1000)
    a.pop("meta")
    b.pop("meta")
    assert a == b


def test_exact_area_then_region_then_null_and_no_nearest_area(rent_db):
    db = rent_db
    area(db, "synthetic-market")
    area(db, "synthetic-region", level="region", geom=POLYGON)
    survey(db, "synthetic-market", rent=100)
    survey(db, "synthetic-region", rent=60)
    assert rpc(db)["rent_level"] == "district"
    assert rpc(db)["survey_rent_per_m2"] == 100
    # Outside market polygon, inside the verified region: no nearest-market substitution.
    outside = rpc(db, lng=127.075)
    assert outside["rent_level"] == "region"
    assert outside["survey_rent_per_m2"] == 60
    db.execute("DELETE FROM public.rent_survey WHERE area_code='synthetic-region'")
    assert rpc(db, lng=127.075)["rent_level"] is None
    assert rpc(db, lng=127.075)["survey_rent_per_m2"] is None


@pytest.mark.parametrize("invalidity", ["unverified", "expired", "ambiguous", "missing_rent"])
def test_unusable_market_falls_back_to_region(rent_db, invalidity):
    db = rent_db
    area(db, "synthetic-market", verified=invalidity != "unverified")
    area(db, "synthetic-region", level="region", geom=POLYGON)
    survey(db, "synthetic-market", rent=None if invalidity == "missing_rent" else 100)
    survey(db, "synthetic-region", rent=60)
    if invalidity == "expired":
        db.execute("UPDATE public.rent_areas SET valid_to='2026-05-31' "
                   "WHERE area_code='synthetic-market'")
    if invalidity == "ambiguous":
        area(db, "synthetic-overlap")
        survey(db, "synthetic-overlap")
    assert rpc(db)["rent_level"] == "region"
    assert rpc(db)["survey_rent_per_m2"] == 60


def test_survey_classes_are_not_silently_mixed(rent_db):
    db = rent_db
    area(db, "synthetic-region", level="region", geom=POLYGON)
    survey(db, "synthetic-region", building_class="office", rent=60)
    survey(db, "synthetic-region", building_class="small_retail", rent=80)
    value = rpc(db)
    assert value["rent_level"] is None
    assert value["survey_rent_per_m2"] is None
    assert set(value["survey_by_building_class"]) == {"office", "small_retail"}
    assert value["meta"]["survey_missing_reason"] is not None
    assert rpc(db, building_class="small_retail")["survey_rent_per_m2"] == 80


def test_no_unique_legal_boundary_never_selects_arbitrary_trade_or_survey(rent_db):
    db = rent_db
    trade(db, "general", 10, 900)
    area(db, "synthetic-region", level="region", geom=POLYGON)
    survey(db, "synthetic-region")
    assert rpc(db, lng=128)["trade_median_per_m2"] is None
    db.execute("""INSERT INTO public.legal_dongs(code8,name,geom,source,source_version)
      SELECT '11680101','synthetic overlap',geom,source,source_version FROM public.legal_dongs""")
    value = rpc(db)
    assert value["trade_median_per_m2"] is None
    assert value["survey_rent_per_m2"] is None
    assert value["meta"]["trade_missing_reason"] == "ambiguous_legal_boundary"


def test_anon_rpc_reads_but_cannot_mutate_or_access_ingest_metadata(rent_db):
    db = rent_db
    trade(db, "general", 5, 900)
    db.execute("SET LOCAL ROLE anon")
    assert rpc(db)["trade_median_per_m2"] == 900
    assert db.execute("SELECT count(*) FROM public.legal_dongs").fetchone()[0] == 1
    for sql in ("DELETE FROM public.commercial_trade_stats",
                "SELECT * FROM ingest_private.rent_snapshots"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
            db.execute(sql)
    db.execute("RESET ROLE")


def loader_frames():
    def geometry(index, code):
        if code == DONG:
            return POLYGON
        x = 127.2 + index * .002
        return (f"POLYGON(({x} 37.5,{x + .001} 37.5,{x + .001} 37.501,"
                f"{x} 37.501,{x} 37.5))")

    boundaries = pd.DataFrame([
        {"code8": code, "name": name, "wkt": geometry(index, code),
         "source": "synthetic fixture", "source_version": "test"}
        for index, (code, name) in enumerate(GANGNAM_DONGS.items())
    ])
    stats = pd.DataFrame([{"legal_dong_code": DONG, "trade_kind": "general",
                           "aggregation_level": "all_floors", "floor": None,
                           "median_price_per_m2": 123, "sample_count": 5,
                           "unknown_floor_count": 0, "area_basis": "building_area"}])
    return boundaries, stats


def load(db, boundaries, stats):
    return load_trade_snapshot(db, boundaries, stats, period_start="2024-09-01",
                               period_end="2026-08-31", source_version="test", report={})


@pytest.mark.parametrize("bad", ["empty", "duplicate", "unmatched", "invalid_value"])
def test_bad_snapshot_preserves_existing_data_and_metadata(rent_db, bad):
    db = rent_db
    trade(db, "general", 8, 777)
    boundaries, stats = loader_frames()
    if bad == "empty":
        stats = stats.iloc[:0]
    elif bad == "duplicate":
        stats = pd.concat([stats, stats], ignore_index=True)
    elif bad == "unmatched":
        stats.loc[0, "legal_dong_code"] = "11680199"
    else:
        stats.loc[0, "median_price_per_m2"] = -1
    with pytest.raises((ValueError, psycopg.Error)):
        load(db, boundaries, stats)
    assert rpc(db)["trade_median_per_m2"] == 777
    assert db.execute("SELECT count(*) FROM ingest_private.rent_snapshots").fetchone()[0] == 0


def test_valid_snapshot_replaces_current_window_idempotently(rent_db):
    db = rent_db
    trade(db, "general", 8, 777)
    boundaries, stats = loader_frames()
    load(db, boundaries, stats)
    assert rpc(db)["trade_median_per_m2"] == 123
    assert rpc(db)["trade_sample_count"] == 5
    load(db, boundaries, stats)
    assert db.execute("SELECT count(*) FROM public.commercial_trade_stats").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM public.legal_dongs").fetchone()[0] == 14
    assert db.execute("SELECT count(*) FROM ingest_private.rent_snapshots").fetchone()[0] == 1


def test_nullable_floor_dataframe_loads_integer_floor_without_float_text(rent_db):
    boundaries, stats = loader_frames()
    floor_row = stats.iloc[0].to_dict() | {"aggregation_level": "floor", "floor": 2.0}
    stats = pd.DataFrame([*stats.to_dict("records"), floor_row])
    stats["floor"] = stats["floor"].astype(float)
    load(rent_db, boundaries, stats)
    assert rpc(rent_db, floor=2)["trade_sample_count"] == 5
    assert rpc(rent_db, floor=2)["trade_median_per_m2"] == 123


def test_loader_rolls_back_failure_after_staging(rent_db, monkeypatch):
    import ingest.rent_database as module

    db = rent_db
    trade(db, "general", 8, 777)
    boundaries, stats = loader_frames()
    original = module._copy
    copied = []

    def fail_after_copy(*args, **kwargs):
        original(*args, **kwargs)
        copied.append(True)
        if len(copied) == 2:
            raise RuntimeError("synthetic failure after copying")

    monkeypatch.setattr(module, "_copy", fail_after_copy)
    with pytest.raises(RuntimeError, match="synthetic failure"):
        load(db, boundaries, stats)
    assert len(copied) == 2
    assert rpc(db)["trade_median_per_m2"] == 777
    assert db.execute("SELECT count(*) FROM public.legal_dongs").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM ingest_private.rent_snapshots").fetchone()[0] == 0


def test_district_rent_with_missing_vacancy_keeps_same_row_without_region_mixing(rent_db):
    db = rent_db
    area(db, "synthetic-market")
    area(db, "synthetic-region", level="region", geom=POLYGON)
    survey(db, "synthetic-market", rent=100, vacancy=None)
    survey(db, "synthetic-region", rent=60, vacancy=9)
    value = rpc(db)
    assert value["rent_level"] == "district"
    assert value["survey_rent_per_m2"] == 100
    assert value["survey_vacancy"] is None


def test_region_requires_verified_official_mapping(rent_db):
    db = rent_db
    area(db, "synthetic-region", level="region", geom=POLYGON, verified=False)
    survey(db, "synthetic-region", rent=60)
    value = rpc(db)
    assert value["rent_level"] is None
    assert value["survey_rent_per_m2"] is None
    assert value["survey_vacancy"] is None


def test_latest_quarter_missing_rent_never_uses_historical_district(rent_db):
    db = rent_db
    area(db, "synthetic-market")
    area(db, "synthetic-region", level="region", geom=POLYGON)
    survey(db, "synthetic-market", rent=100)
    db.execute("UPDATE public.rent_survey SET quarter='2026-Q1'")
    survey(db, "synthetic-market", rent=None)
    survey(db, "synthetic-region", rent=None)
    value = rpc(db, building_class="office")
    assert value["rent_level"] is None
    assert value["survey_rent_per_m2"] is None
    assert value["survey_by_building_class"] == {}


def survey_loader_frames():
    areas = pd.DataFrame([{
        "area_code": "synthetic-region", "area_name": "synthetic region",
        "level": "region", "gu_code": "11680", "wkt": POLYGON,
        "valid_from": "2026-01-01", "valid_to": "2026-12-31",
        "mapping_verified": True,
        "mapping_evidence": "synthetic official definition evidence",
        "source": "synthetic fixture", "source_version": "replacement",
    }])
    surveys = pd.DataFrame([{
        "area_code": "synthetic-region", "building_class": "office",
        "quarter": "2026-Q2", "rent_per_m2": 60, "vacancy_rate": 9,
        "rent_statbl_id": "synthetic-rent", "rent_cls_id": "synthetic-code",
        "vacancy_statbl_id": "synthetic-vacancy", "vacancy_cls_id": "synthetic-code",
        "source": "synthetic fixture", "source_version": "replacement",
    }])
    return areas, surveys


def test_survey_full_reload_removes_omitted_rows_and_preserves_other_sources(rent_db):
    db = rent_db
    area(db, "synthetic-market")
    survey(db, "synthetic-market", rent=100)
    area(db, "unrelated-market", geom=POLYGON)
    survey(db, "unrelated-market", building_class="collective", rent=80)
    db.execute("UPDATE public.rent_survey SET source='unrelated source' "
               "WHERE area_code='unrelated-market'")
    areas, surveys = survey_loader_frames()
    load_survey_snapshot(db, areas, surveys, source_version="replacement", report={})
    assert db.execute("SELECT count(*) FROM public.rent_survey "
                      "WHERE area_code='synthetic-market'").fetchone()[0] == 0
    assert db.execute("SELECT rent_per_m2 FROM public.rent_survey "
                      "WHERE source='unrelated source'").fetchone()[0] == 80
    value = rpc(db, building_class="office")
    assert value["rent_level"] == "region"
    assert value["survey_rent_per_m2"] == 60


def test_survey_reload_failure_restores_deleted_snapshot(rent_db, monkeypatch):
    import ingest.rent_database as module

    db = rent_db
    area(db, "synthetic-market")
    survey(db, "synthetic-market", rent=100)
    areas, surveys = survey_loader_frames()

    def fail_report(*args, **kwargs):
        raise RuntimeError("synthetic failure after survey replacement")

    monkeypatch.setattr(module, "_save_report", fail_report)
    with pytest.raises(RuntimeError, match="after survey replacement"):
        load_survey_snapshot(db, areas, surveys, source_version="replacement", report={})
    value = rpc(db, building_class="office")
    assert value["rent_level"] == "district"
    assert value["survey_rent_per_m2"] == 100
    assert db.execute("SELECT count(*) FROM public.rent_areas "
                      "WHERE area_code='synthetic-region'").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM ingest_private.rent_snapshots").fetchone()[0] == 0
