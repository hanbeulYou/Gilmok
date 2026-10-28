import argparse
import gzip
import hashlib
import json
import time
from pathlib import Path

import psycopg
from psycopg.conninfo import conninfo_to_dict
from psycopg.types.json import Jsonb

parser = argparse.ArgumentParser(
    description="Read-only local academy payload estimate; no API or remote access"
)
parser.add_argument("--database-url", required=True)
parser.add_argument("--reviews", type=Path, required=True)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if conninfo_to_dict(args.database_url).get("host") not in {"127.0.0.1", "localhost", "::1"}:
    raise ValueError("Local database only")
A = Path(__file__).resolve().parents[1]
review_path = args.reviews
reviews = json.loads(review_path.read_text())
holds = {
    r["id"]: "movement_gt_500m" for r in reviews if r["kind"] == "academies" and r["over_500m"]
}
q = """with nearby as materialized (
 select a.id,a.name,a.field,a.geom,d.floor_label,d.floor_status,(%s::jsonb ? a.id) pending
 from public.academies a join app_private.academy_display d on d.academy_id=a.id
 where a.registration_status='개원' and extensions.st_dwithin(a.geom::extensions.geography,
 extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326)::extensions.geography,%s)
) select jsonb_build_object('schema_version','1.0','status','ready','reason',null,
 'center',jsonb_build_array(%s::float8,%s::float8),'radius_m',%s::int,'field',%s::text,
'collection',jsonb_build_object('type','FeatureCollection','features',coalesce(jsonb_agg(jsonb_build_object(
'type','Feature','id',id,'geometry',jsonb_build_object('type','Point','coordinates',jsonb_build_array(extensions.st_x(geom),extensions.st_y(geom))),
'properties',jsonb_build_object('name',name,'field',field,'floor_label',floor_label,'floor_status',floor_status,
 'coordinate_verification_pending',pending,'coordinate_review_reason',case when pending then
'movement_gt_500m' end,
 'coordinate_review_version',case when pending then '20261014-v3' end)) order by id),'[]'::jsonb)),
 'counts',jsonb_build_object('radius_all',count(*),'radius_same_field',count(*) filter(where
field=%s),
 'radius_pending',count(*) filter(where pending),'radius_same_field_pending',count(*) filter(where
pending and field=%s),
 'by_field',coalesce((select jsonb_object_agg(field,n) from (select field,count(*) n from nearby
group by field) f),'{}'::jsonb)),
 'meta',%s::jsonb)::text from nearby"""
with psycopg.connect(args.database_url) as db:
    db.execute("set transaction isolation level repeatable read read only")
    db.execute("set extra_float_digits=3")
    total, located = db.execute("select count(*),count(geom) from academies").fetchone()
    assert total == 25527
    source = db.execute("select score_internal.sources()->'academies'").fetchone()[0]
    revision, sha = db.execute(
        "select source_revision,raw_sha256 from app_private.academy_display_release"
    ).fetchone()
    meta = dict(
        crs="EPSG:4326",
        source=source,
        source_revision=revision,
        coordinate_provider="juso",
        review_version="20261014-v3",
        unlocated_count_seoul=total - located,
        quality_inventory=dict(academy=len(holds), school=2),
    )
    with gzip.open(A / "tests/scoring/fixtures/v040-inputs.json.gz", "rt") as f:
        cases = json.load(f)["cases"][:5]
    field = "입시.검정 및 보습"

    def measure(label, lat, lng, radius):
        text = db.execute(
            q, (Jsonb(holds), lng, lat, radius, lng, lat, radius, field, field, field, Jsonb(meta))
        ).fetchone()[0]
        value = json.loads(text)
        raw = text.encode()
        counts = value["counts"]
        n = counts["radius_all"]
        out = dict(
            label=label,
            lat=lat,
            lng=lng,
            radius_m=radius,
            **counts,
            raw_bytes=len(raw),
            gzip_bytes=len(gzip.compress(raw, mtime=0)),
            budget_fraction=len(raw) / 1572864,
            estimated_bytes_per_institution=round(len(raw) / n, 2) if n else None,
        )
        print(
            json.dumps({k: v for k, v in out.items() if k != "by_field"}, ensure_ascii=False),
            flush=True,
        )
        return out

    result = dict(
        db=conninfo_to_dict(args.database_url).get("dbname"),
        read_only=True,
        academies=total,
        located=located,
        source=source,
        source_revision=revision,
        review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest(),
        candidates=[],
        top_cells=[],
    )
    for label, case in zip("abcde", cases):
        p = case["candidate"]
        for radius in [800, 1000]:
            result["candidates"].append(measure(label, p["lat"], p["lng"], radius))
    began = time.monotonic()
    cells = db.execute("""with centers as materialized (select cell_id,
 extensions.st_transform(extensions.st_centroid(extensions.st_transform(geom,5179)),4326) p
 from public.population_cells where resolution_m=250),
 seoul as materialized(select * from centers),
 counts as (select cell_id,p,(select count(*) from public.academies a where
a.registration_status='개원' and
extensions.st_dwithin(a.geom::extensions.geography,s.p::extensions.geography,800)) n from seoul s)
 select cell_id,extensions.st_y(p),extensions.st_x(p),n,(select count(*) from seoul) from counts
order by n desc,cell_id limit 10""").fetchall()
    result["grid_query_seconds"] = time.monotonic() - began
    assert all(c[4] == 10127 for c in cells)
    result["grid_count"] = 10127
    for cell, lat, lng, n, _ in cells:
        item = measure(cell, lat, lng, 800)
        assert item["radius_all"] == n
        result["top_cells"].append(item)
    max_point = db.execute("""select max(octet_length(jsonb_build_object(
        'type','Feature','id',a.id,'geometry',jsonb_build_object('type','Point',
        'coordinates',jsonb_build_array(extensions.st_x(a.geom),extensions.st_y(a.geom))),
        'properties',jsonb_build_object('name',a.name,'field',a.field,
        'floor_label',d.floor_label,'floor_status',d.floor_status,
        'coordinate_verification_pending',true,'coordinate_review_reason','movement_gt_500m',
        'coordinate_review_version','20261014-v3'))::text))
        from public.academies a join app_private.academy_display d on d.academy_id=a.id
        where a.registration_status='개원' and a.geom is not null""").fetchone()[0]
    header = dict(
        schema_version="1.0",
        status="ready",
        reason=None,
        center=[129.99999999999999, 38.99999999999999],
        radius_m=1000,
        field=field,
        collection=dict(type="FeatureCollection", features=[]),
        counts=dict(
            radius_all=total,
            radius_same_field=total,
            radius_pending=total,
            radius_same_field_pending=total,
            by_field={f[0]: total for f in db.execute("select distinct field from academies")},
        ),
        meta={**meta, "unlocated_count_seoul": total},
    )
    header_bytes = db.execute("select octet_length(%s::jsonb::text)", (Jsonb(header),)).fetchone()[
        0
    ]
    assert header_bytes < 8192
    bound = (max_point + 2) * result["top_cells"][0]["radius_all"] + 8192
    result["all_cells_upper_bound"] = dict(
        max_point_bytes_assuming_pending_for_all=max_point,
        max_header_bytes_with_all_fields_and_counts_25527=header_bytes,
        header_allowance=8192,
        raw_upper_bound=bound,
        budget_fraction=bound / 1572864,
    )
    out = args.output
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print("saved", out, "grid_seconds", result["grid_query_seconds"], flush=True)
