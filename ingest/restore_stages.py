"""Atomic stage checkpoints: data and completion proof share one transaction."""

import time

from psycopg import sql
from psycopg.types.json import Jsonb

from ingest.restore_provenance import table_signature

STAGES = (
    ("boundaries", ("admin_dongs", "legal_dongs")),
    ("population", ("population_age", "population_cells", "living_pop")),
    ("transit", ("transit_stops", "transit_boardings")),
    ("places", ("stores", "academies", "schools")),
    ("buildings", ("buildings", "building_registers", "building_floors")),
    ("rent", ("commercial_trade_stats", "rent_areas", "rent_survey")),
    ("reference", ("score_reference", "score_reference_sets")),
)


def execute_stage(factory, ordinal, digest, expected, loader):
    name, tables = STAGES[ordinal - 1]
    started = time.monotonic()
    skipped = False
    with factory() as db:
        if not db.execute("select pg_try_advisory_xact_lock(7412809)").fetchone()[0]:
            raise ValueError("Another restore stage is active")
        records = db.execute("""select ordinal,stage,manifest_sha256,row_counts,table_digests,
                                seconds from ingest_private.restore_stages
                                order by ordinal""").fetchall()
        if any(r[2] != digest for r in records):
            raise ValueError("Checkpoint manifest differs; refuse mixed snapshots")
        if [r[0] for r in records] != list(range(1, len(records) + 1)):
            raise ValueError("Checkpoint stages must form a completed prefix")
        for r in records:
            if r[1] != STAGES[r[0] - 1][0]:
                raise ValueError("Checkpoint stage order differs")
        existing = next((r for r in records if r[0] == ordinal), None)
        if existing:
            signatures = {t: table_signature(db, t) for t in tables}
            if (signatures != {t: expected[t] for t in tables}
                    or existing[3] != {t: s["rows"] for t, s in signatures.items()}
                    or existing[4] != {t: s["row_digest"] for t, s in signatures.items()}):
                raise ValueError("Completed stage data/checkpoint differs from manifest")
            skipped = True
            load_seconds = existing[5]
        else:
            if len(records) != ordinal - 1:
                raise ValueError("Previous restore stage is incomplete")
            if any(db.execute(sql.SQL("select exists(select 1 from public.{})").format(
                    sql.Identifier(t))).fetchone()[0] for t in tables):
                raise ValueError("Uncheckpointed stage contains data; refusing overwrite")
            loader(db)
            signatures = {t: table_signature(db, t) for t in tables}
            if signatures != {t: expected[t] for t in tables}:
                raise ValueError("Stage row/geometry/provenance digest differs: " + name)
            load_seconds = time.monotonic() - started
            db.execute("""insert into ingest_private.restore_stages
                       (stage,ordinal,manifest_sha256,row_counts,table_digests,seconds)
                       values(%s,%s,%s,%s,%s,%s)""",
                       (name, ordinal, digest, Jsonb({t: s["rows"] for t, s in signatures.items()}),
                        Jsonb({t: s["row_digest"] for t, s in signatures.items()}), load_seconds))
    # Only report success after the transaction context has committed successfully.
    return dict(name=name, status="skipped" if skipped else "committed",
                seconds=round(time.monotonic() - started, 3),
                load_seconds=round(load_seconds, 3), tables=signatures)
