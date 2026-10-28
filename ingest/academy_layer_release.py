"""Strict metadata publication inside the source/display/reference transaction."""

import json
from collections import Counter

from psycopg.pq import TransactionStatus
from psycopg.types.json import Jsonb

from ingest.copy_batches import chunked_copy


def prepare_reviews(path, *, version, sources):
    """Project a pinned local review inventory; omit names and addresses."""
    rows = []
    for item in json.loads(path.read_text()):
        if not item["over_500m"]:
            continue
        kind = {"academies": "academy", "schools": "school"}[item["kind"]]
        revision, sha = sources[item["kind"]]
        rows.append((kind, str(item["id"]), revision, sha, version, "movement_gt_500m"))
    if len({(r[0], r[1]) for r in rows}) != len(rows):
        raise ValueError("Duplicate quality-review entity")
    return rows


def publish_layer_release(db, rows, *, review_version):
    if db.info.transaction_status != TransactionStatus.INTRANS:
        raise ValueError("Layer release requires the source/reference transaction")
    if not review_version or any(r[4] != review_version for r in rows):
        raise ValueError("Mixed quality-review versions")
    if len({(r[0], r[1]) for r in rows}) != len(rows):
        raise ValueError("Duplicate quality-review entity")
    display = db.execute(
        "select source_revision,raw_sha256,source_version from "
        "app_private.academy_display_release where singleton"
    ).fetchone()
    source = db.execute("select score_internal.sources()->'academies'").fetchone()[0]
    if not display or not source or display[2] != source["source_version"]:
        raise ValueError("Missing or mismatched display/source release")
    revision, sha, _ = display
    for kind in ("academy", "school"):
        ids = [r[1] for r in rows if r[0] == kind]
        table = "academies" if kind == "academy" else "schools"
        found = db.execute(f"select count(*) from public.{table} where id=any(%s)", (ids,))
        if found.fetchone()[0] != len(ids):
            raise ValueError("Quality-review IDs do not match source")
    if any(r[0] not in {"academy", "school"} for r in rows) or any(
        (r[2], r[3]) != (revision, sha) for r in rows if r[0] == "academy"
    ):
        raise ValueError("Quality-review provenance does not match academy display")
    with db.cursor() as cursor:
        cursor.execute(
            "delete from app_private.academy_coordinate_reviews where review_version=%s",
            (review_version,),
        )
        with chunked_copy(cursor, "copy app_private.academy_coordinate_reviews from stdin") as copy:
            for row in rows:
                copy.write_row(row)
        counts = Counter(r[0] for r in rows)
        cursor.execute(
            """insert into app_private.academy_layer_release values(true,%s,%s,%s,%s,%s,%s)
            on conflict(singleton) do update set source_revision=excluded.source_revision,
            raw_sha256=excluded.raw_sha256,academy_source=excluded.academy_source,
            review_version=excluded.review_version,
            reviewed_academy_count=excluded.reviewed_academy_count,
            reviewed_school_count=excluded.reviewed_school_count""",
            (revision, sha, Jsonb(source), review_version, counts["academy"], counts["school"]),
        )
