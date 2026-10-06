"""Fixed public-source subset for real SQL RPC/Worker E2E. Never includes owner/Auth/cache data."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

DIRECTORY = Path(__file__).parent / "fixtures" / "snapshot"
DB_URL = "postgresql://postgres:postgres@127.0.0.1:54322/postgres"
NEAR = (
    "extensions.st_dwithin(geom::extensions.geography,"
    "extensions.st_setsrid(extensions.st_makepoint(127.0575,37.5013),4326)"
    "::extensions.geography,1850)"
)
BUILDING_PKS = f"select register_pk from public.buildings where {NEAR}"
TABLES = [
    ("public.admin_dongs", "true"),
    ("public.population_age", "true"),
    ("public.population_cells", NEAR),
    (
        "public.living_pop",
        "(resolution_m,cell_id) in (select resolution_m,cell_id "
        f"from public.population_cells where {NEAR})",
    ),
    ("public.transit_stops", NEAR),
    ("public.transit_boardings", f"stop_id in (select id from public.transit_stops where {NEAR})"),
    ("public.stores", NEAR),
    ("public.academies", NEAR),
    ("public.schools", NEAR),
    ("public.building_registers", f"register_pk in ({BUILDING_PKS})"),
    ("public.buildings", NEAR),
    (
        "public.building_floors",
        (
            "register_pk in (select register_pk from public.buildings where "
            "pnu in "
            "('1168010600109120013','1168010600109380022','1168010600109670000'))"
        ),
    ),
    ("public.legal_dongs", "true"),
    ("public.commercial_trade_stats", "true"),
    ("public.rent_areas", "true"),
    ("public.rent_survey", "true"),
    ("public.score_reference_sets", "true"),
    ("public.score_reference", "true"),
    ("ingest_private.building_snapshots", "true"),
    ("ingest_private.place_snapshots", "true"),
    ("ingest_private.rent_snapshots", "true"),
    ("ingest_private.refresh_snapshots", "true"),
    ("ingest_private.transit_coverage", "true"),
]


def binary_digest(db, select):
    ordered = sql.SQL(
        'select * from ({}) fixed_source order by to_jsonb(fixed_source)::text collate "C"'
    ).format(select)
    digest = hashlib.sha256()
    with db.cursor().copy(
        sql.SQL("copy ({}) to stdout with (format binary)").format(ordered)
    ) as copy:
        for block in copy:
            digest.update(block)
    return digest.hexdigest()


def export(db):
    db.execute("set transaction read only")
    # Cluster default is 0; CSV would otherwise truncate float8 and break percentile ties.
    db.execute("set local extra_float_digits=3")
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    manifest = {
        "source": (
            "S2 fixed public snapshots; 1850m around Daechi, complete Seoul references/boundaries"
        ),
        "tables": [],
    }
    for table, predicate in TABLES:
        columns = [
            r[0]
            for r in db.execute(
                (
                    "select attname from pg_attribute where attrelid=%s::regclass and "
                    "attnum>0 and not attisdropped and attgenerated='' order by attnum"
                ),
                (table,),
            )
        ]
        select = sql.SQL("select {} from {} where {}").format(
            sql.SQL(",").join(map(sql.Identifier, columns)),
            sql.Identifier(*table.split(".")),
            sql.SQL(predicate),
        )
        count = db.execute(sql.SQL("select count(*) from ({}) s").format(select)).fetchone()[0]
        path = DIRECTORY / (table + ".csv.gz")
        with (
            gzip.open(path, "wb") as f,
            db.cursor().copy(
                sql.SQL("copy ({}) to stdout with (format csv)").format(select)
            ) as copy,
        ):
            for block in copy:
                f.write(block)
        manifest["tables"].append(
            {
                "table": table,
                "columns": columns,
                "rows": count,
                "file": path.name,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "binary_sha256": binary_digest(db, select),
                "bytes": path.stat().st_size,
            }
        )
    (DIRECTORY / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(
        json.dumps(
            {
                "tables": len(manifest["tables"]),
                "bytes": sum(t["bytes"] for t in manifest["tables"]),
            }
        )
    )


def load(db):
    db.execute("set local extra_float_digits=3")
    manifest = json.loads((DIRECTORY / "manifest.json").read_text())
    for t in manifest["tables"]:
        table = sql.Identifier(*t["table"].split("."))
        if db.execute(sql.SQL("select count(*) from {}").format(table)).fetchone()[0]:
            raise ValueError(
                "Snapshot loader requires empty source tables; never replaces existing local data"
            )
    for t in manifest["tables"]:
        path = DIRECTORY / t["file"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != t["sha256"]:
            raise ValueError("Snapshot digest mismatch")
        statement = sql.SQL("copy {} ({}) from stdin with (format csv)").format(
            sql.Identifier(*t["table"].split(".")),
            sql.SQL(",").join(map(sql.Identifier, t["columns"])),
        )
        with gzip.open(path, "rb") as f, db.cursor().copy(statement) as copy:
            while block := f.read(1024 * 1024):
                copy.write(block)
        table = sql.Identifier(*t["table"].split("."))
        count = db.execute(sql.SQL("select count(*) from {}").format(table)).fetchone()[0]
        select = sql.SQL("select {} from {}").format(
            sql.SQL(",").join(map(sql.Identifier, t["columns"])), table
        )
        if count != t["rows"] or binary_digest(db, select) != t["binary_sha256"]:
            raise ValueError(f"Snapshot binary round-trip mismatch: {t['table']}")
    db.execute("analyze")
    print("Fixed public snapshot loaded; Auth/owner rows untouched")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--export", action="store_true")
    p.add_argument("--db-url", default=DB_URL)
    args = p.parse_args()
    if conninfo_to_dict(args.db_url).get("host") not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("E2E fixture export/load is local only")
    with psycopg.connect(args.db_url) as db:
        (export if args.export else load)(db)
