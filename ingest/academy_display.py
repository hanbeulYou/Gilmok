"""Public institution display projection; explicit floors, never inferred room floors."""

import re

from ingest.copy_batches import chunked_copy

FLOORS = re.compile(
    r"(?<![\dA-Za-z-])(?P<base>지하|지상|B)?\s*"
    r"(?P<low>[1-9]\d?)\s*(?:[~∼～]\s*(?P<high>[1-9]\d?)\s*)?층"
)


def explicit_floor(*addresses):
    """Keep explicit expressions; absent/ambiguous sources are not guessed."""
    # A road building number must not join a leading comma in DADDR into a floor list.
    text = " | ".join(str(value) for value in addresses if value is not None)
    if re.search(r"층\s*[-~∼～]", text):
        return None, "ambiguous"
    if re.search(r"\d\s*[,·]\s*\d+\s*층", text):
        return None, "ambiguous"
    labels = []
    for match in FLOORS.finditer(text):
        low = int(match["low"])
        high = int(match["high"]) if match["high"] else low
        if high < low:
            return None, "ambiguous"
        prefix = "지하 " if match["base"] in {"지하", "B"} else ""
        label = f"{prefix}{low}" + (f"~{high}" if high != low else "") + "층"
        if label not in labels:
            labels.append(label)
    return (" · ".join(labels), "explicit") if labels else (None, "missing")


def prepare_display(raw, frame, revision, raw_sha256):
    by_id = raw.set_index("PEI_DSGN_NO")
    if not by_id.index.is_unique or set(frame.id) - set(by_id.index):
        raise ValueError("Display raw identities do not match academy source")
    rows = []
    for identity in frame.id:
        original = by_id.loc[identity]
        label, status = explicit_floor(original.get("ROAD_NM_ADDR"), original.get("DADDR"))
        rows.append((identity, label, status, revision, raw_sha256))
    return rows


def load_display(db, rows, *, revision, version, raw_sha256):
    """Strict derived source write in the caller's source/reference transaction."""
    if not rows or len({r[0] for r in rows}) != len(rows):
        raise ValueError("Empty/duplicate display rows")
    with db.transaction(), db.cursor() as cursor:
        expected = {r[0] for r in cursor.execute("select id from public.academies")}
        if expected != {r[0] for r in rows}:
            raise ValueError("Display rows must exactly cover current academies")
        if cursor.execute("""select count(*) from public.academies
            where geocode_provider is distinct from 'juso'""").fetchone()[0]:
            raise ValueError("Display release requires independent Juso provenance")
        cursor.execute("delete from app_private.academy_display")
        with chunked_copy(
            cursor,
            "copy app_private.academy_display "
            "(academy_id,floor_label,floor_status,source_revision,raw_sha256) "
            "from stdin",
        ) as stream:
            for row in rows:
                stream.write_row(row)
        cursor.execute(
            """insert into app_private.academy_display_release
            (singleton,source_revision,source_version,raw_sha256,row_count,coordinate_provider)
            values(true,%s,%s,%s,%s,'juso') on conflict(singleton) do update set
            source_revision=excluded.source_revision,source_version=excluded.source_version,
            raw_sha256=excluded.raw_sha256,row_count=excluded.row_count,
            coordinate_provider=excluded.coordinate_provider,ingested_at=now()""",
            (revision, version, raw_sha256, len(rows)),
        )


def display_enabled(db):
    if not db.execute("select to_regclass('app_private.academy_display_release')").fetchone()[0]:
        return False
    return db.execute(
        "select exists(select 1 from app_private.academy_display_release)"
    ).fetchone()[0]
