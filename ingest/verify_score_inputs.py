"""Local-only, read-only S1 acceptance: real data, nested SQL plans and anonymous HTTP."""

import argparse
import copy
import json
import math
import re
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from psycopg import sql
from psycopg.types.json import Jsonb

from ingest.common import ROOT
from ingest.database import connect_database
from ingest.verify_commerce_education import POINTS

QUERY = (ROOT / "ingest/sql/score_inputs.sql").read_text()
BUNDLES = ("demand", "flow", "transit", "market", "compete", "building", "rent")
TABLES = (
    "admin_dongs",
    "population_age",
    "population_cells",
    "living_pop",
    "transit_stops",
    "transit_boardings",
    "stores",
    "academies",
    "schools",
    "buildings",
    "building_registers",
    "building_floors",
    "legal_dongs",
    "commercial_trade_stats",
    "rent_areas",
    "rent_survey",
)
# Skip quoted SQL text; substitute only the exact parameter identifiers of SQL functions.
TOKENS = re.compile(r"'(?:[^']|'')*'|[a-zA-Z_][a-zA-Z_0-9]*(?:\.[a-zA-Z_][a-zA-Z_0-9]*)?")


def percentile(values, quantile=0.95):
    if not values or not 0 < quantile <= 1 or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("Nonempty observations and quantile in (0,1] required")
    return sorted(values)[math.ceil(len(values) * quantile) - 1]


def cases():
    return [
        dict(name=name, lat=lat, lng=lng, radius_m=radius, floor=2)
        for name, lat, lng in POINTS
        for radius in (500, 1000)
    ]


def stable_payload(payload):
    payload = copy.deepcopy(payload)
    for key in ("computed_at", "bundle_ms", "sources_ms", "total_ms"):
        payload["meta"].pop(key)
    return payload


def equivalent(actual, expected):
    if isinstance(actual, bool) or isinstance(expected, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(actual, int) and isinstance(expected, int):
        return actual == expected
    if isinstance(actual, dict) and isinstance(expected, dict):
        return actual.keys() == expected.keys() and all(
            equivalent(actual[k], expected[k]) for k in actual
        )
    if isinstance(actual, list) and isinstance(expected, list):
        return len(actual) == len(expected) and all(
            equivalent(a, b) for a, b in zip(actual, expected, strict=True)
        )
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return math.isclose(actual, expected, rel_tol=1e-10, abs_tol=1e-8)
    return actual == expected


def bind_body(body, replacements):
    return TOKENS.sub(lambda m: replacements.get(m[0], m[0]), body)


def plan_nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from plan_nodes(child)


def scan_summary(plan):
    return [
        {
            k: node[k]
            for k in (
                "Node Type",
                "Relation Name",
                "Index Name",
                "Actual Rows",
                "Actual Loops",
                "Rows Removed by Filter",
                "Hash Batches",
                "Sort Method",
                "Shared Hit Blocks",
                "Shared Read Blocks",
                "Temp Read Blocks",
                "Temp Written Blocks",
            )
            if k in node
        }
        for node in plan_nodes(plan)
    ]


def database_state(db):
    return {
        "rows": {
            table: db.execute(
                sql.SQL("select count(*) from public.{}").format(sql.Identifier(table))
            ).fetchone()[0]
            for table in TABLES
        },
        "database_bytes": db.execute("select pg_database_size(current_database())").fetchone()[0],
        "version": db.execute("select version()").fetchone()[0],
        "postgis": db.execute("select extensions.postgis_full_version()").fetchone()[0],
    }


def body(db, name):
    row = db.execute(
        """select p.prosrc from pg_proc p join pg_namespace n on n.oid=p.pronamespace
        where n.nspname='score_internal' and p.proname=%s""",
        (name,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Missing internal function: {name}")
    return row[0]


def nested_plans(db, case, result):
    """Supabase forbids LOAD auto_explain: explain the exact stored SQL, not copied queries."""
    point = f"extensions.st_setsrid(extensions.st_makepoint({case['lng']},{case['lat']}),4326)"
    replacements = dict(
        p=point,
        point=point,
        radius_m=str(case["radius_m"]),
        requested_floor="2",
        covered="true",
        available="true",
    )
    replacements["circle"] = (
        f"extensions.st_buffer(extensions.st_transform({point},5186),{case['radius_m']},32)"
    )
    replacements["sources"] = sql.Literal(Jsonb(result["meta"]["sources"])).as_string(db)
    plans = {}
    for name in BUNDLES[:-1]:
        query = bind_body(body(db, name), replacements)
        value = db.execute(query).fetchone()[0]
        if name == "flow":
            value.pop("_coverage")
        if name == "building":
            value = value["data"]
        if not equivalent(value, result[name]):
            raise AssertionError(f"Extracted {name} SQL differs from actual RPC")
        plan = db.execute("explain(analyze,buffers,format json) " + query).fetchone()[0][0]
        plans[name] = dict(plan=plan, nodes=scan_summary(plan["Plan"]), result_matches=True)
        if plan["Plan"]["Actual Rows"] != 1:
            raise AssertionError(f"{name} does not aggregate to one row")
    # PR 6's preserved PL/pgSQL helper has three data queries. Extract each verbatim.
    rent = body(db, "rent_inputs")
    dong = rent[rent.index("select count(*),min(d.code8)") : rent.index("if dong_count <>")]
    dong = dong.replace("into dong_count,dong_code", "")
    trades = rent[rent.index("select jsonb_agg(to_jsonb(t)") : rent.index("-- collection sorts")]
    trades = trades.replace("into by_type", "")
    survey = rent[rent.index("with latest_quarters") : rent.index("class_values := coalesce")]
    survey = survey.replace("into class_values", "")
    replacements.update(
        {
            "dong_code": sql.Literal(result["meta"]["legal_dong_code"]).as_string(db),
            "rent_inputs.floor": "2",
            "rent_inputs.building_class": "null::text",
        }
    )
    legacy = db.execute(
        "select public.rent_inputs(%(lng)s,%(lat)s,%(radius_m)s,2,null)", case
    ).fetchone()[0]
    for label, query in [
        ("rent.legal_dong", dong),
        ("rent.trades", trades),
        ("rent.survey", survey),
    ]:
        query = bind_body(query, replacements)
        value = db.execute(query).fetchone()
        if label == "rent.trades" and not equivalent(
            value[0] or [], legacy["trade_by_building_type"]
        ):
            raise AssertionError("Extracted rent trade SQL differs")
        if label == "rent.survey" and not equivalent(
            value[0] or {}, legacy["survey_by_building_class"]
        ):
            raise AssertionError("Extracted rent survey SQL differs")
        plan = db.execute("explain(analyze,buffers,format json) " + query).fetchone()[0][0]
        plans[label] = dict(plan=plan, nodes=scan_summary(plan["Plan"]), result_matches=True)
    return plans


def independent_comparisons(db, case, result):
    """Existing read-only queries remain independent oracles; no production SQL calls them."""
    market = db.execute(
        (ROOT / "ingest/sql/commerce_education_radius.sql").read_text(),
        {**case, "radius": case["radius_m"]},
    ).fetchone()[0]
    assert equivalent(
        market["market"], {k: v for k, v in result["market"].items() if k != "estimated"}
    )
    assert equivalent(
        market["compete"], {k: v for k, v in result["compete"].items() if k != "estimated"}
    )
    assert equivalent(market["schools"], result["demand"]["schools"])
    transit = db.execute(
        (ROOT / "ingest/sql/transit_radius.sql").read_text(),
        (case["lng"], case["lat"], case["radius_m"]),
    ).fetchone()
    for i, key in enumerate(("nearest_subway_m", "bus_stops", "subway_boardings_golden")):
        assert equivalent(transit[i], result["transit"][key])
    buildings = db.execute(
        "select public.buildings_in_radius(%(lng)s,%(lat)s,%(radius_m)s)", case
    ).fetchone()[0]
    quality = result["meta"]["height_quality"]
    assert buildings["meta"]["total_buildings"] == quality["observed_buildings"]
    assert equivalent(buildings["meta"]["unknown_ratio"],
                      quality["observed_unknown_buildings"] / quality["observed_buildings"]
                      if quality["observed_buildings"] else None)
    eligible = db.execute("""select count(*),count(*) filter(where height_source='unknown')
        from public.buildings b left join public.building_registers r
        on r.register_pk=b.register_pk
        where extensions.st_dwithin(b.geom::extensions.geography,
        extensions.st_setsrid(extensions.st_makepoint(%(lng)s,%(lat)s),4326)
        ::extensions.geography,%(radius_m)s)
        and extensions.st_area(extensions.st_transform(b.geom,5186))>=30
        and coalesce(nullif(b.main_use_name,''),r.main_use_name,'') !~ '(부속|창고)'""",
        case).fetchone()
    assert eligible == (quality["total_buildings"], quality["unknown_buildings"])
    assert equivalent(quality["unknown_ratio"], eligible[1]/eligible[0] if eligible[0] else None)
    legacy = db.execute(
        "select public.rent_inputs(%(lng)s,%(lat)s,%(radius_m)s,2,null)", case
    ).fetchone()[0]
    for key in (
        "trade_median_per_m2",
        "trade_sample_count",
        "trade_building_type",
        "survey_rent_per_m2",
        "survey_vacancy",
        "rent_level",
    ):
        assert equivalent(legacy[key], result["rent"][key])
    candidate = result["building"]
    if candidate["id"] is not None:
        row = db.execute(
            """select b.height_m,b.floors_above,r.passenger_elevators,
            r.emergency_elevators from public.buildings b left join public.building_registers r
            on r.register_pk=b.register_pk where b.id=%s""",
            (candidate["id"],),
        ).fetchone()
        assert equivalent(
            list(row),
            [
                candidate["height_m"],
                candidate["floors_above"],
                candidate["elevators"]["passenger"],
                candidate["elevators"]["emergency"],
            ],
        )
        uses = db.execute(
            """select jsonb_agg(jsonb_build_object('use_code',use_code,
            'use_name',use_name,'other_use',other_use,'area_m2',area,
            'main_attached_code',main_attached_code) order by id)
            from public.building_floors where register_pk=%s and floor_kind='20' and floor_no=2""",
            (candidate["register_pk"],),
        ).fetchone()[0]
        assert equivalent(uses, candidate["floor_use"])
    # Straight spatial intersection oracles intentionally omit the optimized bounding-box path.
    circle = db.execute(
        """select extensions.st_astext(extensions.st_buffer(
        extensions.st_transform(extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326),5186),
        %s,32))""",
        (case["lng"], case["lat"], case["radius_m"]),
    ).fetchone()[0]
    populations = db.execute(
        """with pieces as (
      select a.age_band,a.population,
       extensions.st_area(extensions.st_intersection(extensions.st_transform(d.geom,5186),
        extensions.st_geomfromtext(%s,5186))) /
        extensions.st_area(extensions.st_transform(d.geom,5186)) weight
      from public.admin_dongs d left join public.population_age a using(adm_cd))
      select age_band,case when count(population)=count(*) then sum(population*weight) end
      from pieces where weight>0 group by age_band""",
        (circle,),
    ).fetchall()
    for age, value in populations:
        assert equivalent(
            float(value) if value is not None else None, result["demand"]["pop_" + age]
        )
    flow = db.execute(
        """with weights as materialized (
      select resolution_m,cell_id,extensions.st_area(extensions.st_intersection(
        extensions.st_transform(geom,5186),extensions.st_geomfromtext(%s,5186))) /
        extensions.st_area(extensions.st_transform(geom,5186)) weight
      from public.population_cells where resolution_m=250), observed as (
      select d,h,l.total,w.weight from (values('weekday'),('weekend')) days(d)
      cross join generate_series(0,23) hours(h) cross join weights w
      left join public.living_pop l on l.cell_id=w.cell_id and l.resolution_m=w.resolution_m
        and l.dow_type=d and l.hour=h where w.weight>0)
        select d,h,sum(total*weight),count(total),count(*),
        count(total)::numeric/nullif(count(*),0)
      from observed group by d,h order by d,h""",
        (circle,),
    ).fetchall()
    for day, hour, value, valid, expected, ratio in flow:
        assert equivalent(value, result["flow"][day]["hourly"][hour])
        coverage = result["meta"]["flow_coverage"][day]
        assert coverage["valid_cells"][hour] == valid
        assert coverage["expected_cells"] == expected
        assert equivalent(coverage["coverage_ratio"][hour],
                          float(ratio) if ratio is not None else None)
    assert result["flow"]["low_coverage"] == any((r[5] or 0) < .8 for r in flow)
    return {name: "matched" for name in BUNDLES}


def positive_building_proof(db):
    """Supplement the fixed station points with a real uniquely matched floor-2 building."""
    points = db.execute("""select b.id,extensions.st_x(p),extensions.st_y(p)
      from public.buildings b cross join lateral
        (select extensions.st_pointonsurface(b.geom) p) q
      where b.source='gis_buildings_shp' and b.register_pk is not null and b.height_m>0
        and exists(select 1 from public.building_floors f where f.register_pk=b.register_pk
                   and f.floor_kind='20' and f.floor_no=2)
      order by b.id limit 20""").fetchall()
    for building_id, lng, lat in points:
        case = dict(name="actual_building_supplement", lng=lng, lat=lat, radius_m=500, floor=2)
        result = db.execute(QUERY, case).fetchone()[0]
        if result["building"]["id"] == building_id and result["building"]["floor_use"]:
            independent_comparisons(db, case, result)
            return {
                **case,
                "building": result["building"],
                "source_comparison": "matched",
                "excluded_from_six_case_performance": True,
            }
    raise AssertionError("No real uniquely matched building with floor 2 verified")


def check_measurements(records):
    keys = ("name", "lat", "lng", "radius_m", "floor")
    if len(records) != 6 or {tuple(r[k] for k in keys) for r in records} != {
        tuple(r[k] for k in keys) for r in cases()
    }:
        raise ValueError("Exactly six distinct cases required")
    for r in records:
        if r["floor"] != 2 or len(r["db_ms"]) != 30 or percentile(r["db_ms"]) >= 1000:
            raise ValueError("Each floor-2 case needs 30 DB samples and p95 < 1000ms")


def measure_http(records):
    status = subprocess.run(
        ["supabase", "status", "-o", "json"], capture_output=True, text=True, check=True
    )
    settings = json.loads(status.stdout)
    if urlparse(settings["API_URL"]).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("HTTP verification is local-only")
    for r in records:
        args = {k: r[k] for k in ("lat", "lng", "radius_m", "floor")}
        times = []
        for _ in range(30):
            request = Request(
                settings["API_URL"] + "/rest/v1/rpc/score_inputs",
                data=json.dumps(args).encode(),
                headers={
                    "apikey": settings["ANON_KEY"],
                    "Authorization": "Bearer " + settings["ANON_KEY"],
                    "Content-Type": "application/json",
                },
            )
            started = time.perf_counter()
            try:
                with urlopen(request, timeout=30) as response:
                    raw = response.read()
                    payload = json.loads(raw)
            except Exception:
                raise RuntimeError("Local anonymous score_inputs HTTP request failed") from None
            times.append((time.perf_counter() - started) * 1000)
            if not equivalent(stable_payload(payload), stable_payload(r["result"])):
                raise AssertionError("HTTP and DB payloads differ")
        r.update(
            http_ms=times,
            http_p50_ms=percentile(times, 0.5),
            http_p95_ms=percentile(times),
            http_max_ms=max(times),
            http_bytes=len(raw),
            http_matches=True,
        )


def run(directory: Path):
    directory.mkdir(parents=True, exist_ok=True)
    report = {
        "measured_at": datetime.now(UTC).isoformat(),
        "warmups": 3,
        "runs_per_case": 30,
        "p95_method": "nearest rank (29th of 30)",
        "role": "anon",
        "http_connections": "urllib requests, no explicit connection pool",
        "nested_plan_method": "stored function SQL extraction; auto_explain LOAD denied",
    }
    records = []
    with connect_database(local_only=True) as db:
        db.execute("set transaction isolation level repeatable read read only")
        report["before"] = database_state(db)
        for case in cases():
            db.execute("set local role anon")
            for _ in range(3):
                db.execute(QUERY, case).fetchone()
            times, bundle_times = [], {k: [] for k in BUNDLES}
            for _ in range(30):
                plan = db.execute("explain(analyze,buffers,format json) " + QUERY, case).fetchone()[
                    0
                ][0]
                times.append(plan["Execution Time"])
                payload = db.execute(QUERY, case).fetchone()[0]
                for k in BUNDLES:
                    bundle_times[k].append(payload["meta"]["bundle_ms"][k])
            record = {
                **case,
                "db_ms": times,
                "db_p95_ms": percentile(times),
                "result": payload,
                "bundle_p95_ms": {k: percentile(v) for k, v in bundle_times.items()},
                "bundle_samples_note": "30 adjacent calls; separate from EXPLAIN samples",
            }
            record["plans"] = nested_plans(db, case, payload)
            db.execute("reset role")
            source_plan = db.execute("explain(analyze,buffers,format json) " + body(db, "sources"))
            source_plan = source_plan.fetchone()[0][0]
            record["plans"]["sources"] = dict(
                plan=source_plan, nodes=scan_summary(source_plan["Plan"])
            )
            record["independent_comparisons"] = independent_comparisons(db, case, payload)
            records.append(record)
        report["positive_building_proof"] = positive_building_proof(db)
        report["after"] = database_state(db)
    if report["before"]["rows"] != report["after"]["rows"]:
        raise AssertionError("Existing data row counts changed")
    check_measurements(records)
    measure_http(records)
    report["cases"] = records
    (directory / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for r in records:
        print(r["name"], r["radius_m"], "DB p95", r["db_p95_ms"], "HTTP p95", r["http_p95_ms"])
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--directory", type=Path, default=ROOT / ".local/validation/pr7/20260921")
    run(parser.parse_args().directory)
