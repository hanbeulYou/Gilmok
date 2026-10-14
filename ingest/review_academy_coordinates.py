"""Read-only local quality review of a frozen transition; no provider requests."""

import argparse
import csv
import gzip
import hashlib
import json
import sqlite3
from collections import Counter
from pathlib import Path

import duckdb
import pandas as pd

from ingest.academy_transition import write_json
from ingest.juso import matches_address
from ingest.verify_academy_transition import isolated


def classify(address_matches, old_buildings, new_buildings):
    """Geometry proves point membership, not the correctness of a parcel register.

    A changed containing building alone does not prove the new geocoder is wrong:
    the old coordinate may be wrong instead. Only an address identity mismatch is
    a confirmed rejection here. Unresolved cases must remain explicit.
    """
    if not address_matches:
        return "다른 건물", True, "source_road_identity_mismatch"
    if set(old_buildings) & set(new_buildings):
        return "같은 건물", False, "same_loaded_footprint_contains_both_points"
    if old_buildings and new_buildings:
        return "다른 건물", False, "different_footprints_correct_location_unresolved"
    return "판단 불가", False, "building_identity_not_proven"


def read_gzip(path):
    with gzip.open(path, "rt") as stream:
        return json.load(stream)


def raw_sources(directory):
    output = {}
    for kind, key, name, road, detail in (
        ("academies", "PEI_DSGN_NO", "PEI_NM", "ROAD_NM_ADDR", "DADDR"),
        ("schools", "SD_SCHUL_CODE", "SCHUL_NM", "ORG_RDNMA", "ORG_RDNDA"),
    ):
        with duckdb.connect() as connection:
            frame = connection.read_parquet(str(directory / "raw" / f"{kind}.parquet")).df()
        if frame[key].duplicated().any():
            raise ValueError("Duplicate raw institution identity")
        for row in frame.to_dict("records"):
            output[(kind, str(row[key]))] = {
                "name": row[name],
                "source_road": row[road],
                "source_detail": row[detail] if pd.notna(row[detail]) else "",
            }
    return output


def review(url, directory, output, seoul_footprints=None):
    if output.exists():
        raise ValueError("Use a new immutable review directory")
    inventory = json.loads((directory / "inventory.json").read_text())
    originals = {(kind, str(r[0])): r for kind, rows in inventory["rows"].items() for r in rows}
    with sqlite3.connect(f"file:{directory / 'journal.sqlite3'}?mode=ro", uri=True) as journal:
        outcomes = {
            a: json.loads(r) for a, r in journal.execute("select address,result from outcomes")
        }
    spatial = {(r["table"], r["id"]): r for r in read_gzip(directory / "spatial-rows.json.gz")}
    conflicts = {(r[0], r[1]): r for r in read_gzip(directory / "pnu-conflicts.json.gz")}
    far = {key for key, r in spatial.items() if (r.get("move_m") or 0) > 500}
    source = raw_sources(directory)
    rows = []
    with isolated(url) as db:
        # No writes even to local source tables. Index a transaction-local copy.
        db.execute(
            "create temp table quality_buildings on commit drop as "
            "select id,pnu,extensions.st_transform(geom,5186) geom,"
            "source,floors_above,main_use_name from public.buildings"
        )
        if seoul_footprints:
            # Reuse the preserved Seoul SHP, without widening production coverage.
            # Gangnam retains the actual loaded/repaired shapes and WFS supplements.
            db.execute("""create temp table quality_raw(
                id text,pnu text,wkb bytea,floors_above integer,main_use_name text)
                on commit drop""")
            with duckdb.connect() as raw, db.cursor() as cursor:
                data = raw.execute(
                    "select 'shp:'||A1,A2,source_geometry_wkb,A26,A9 "
                    "from read_parquet(?) where A23 <> '11680'",
                    [str(seoul_footprints)],
                )
                with cursor.copy("copy quality_raw from stdin") as copy:
                    while batch := data.fetchmany(5000):
                        for row in batch:
                            copy.write_row(row)
            db.execute("""insert into quality_buildings
                select id,pnu,extensions.st_makevalid(extensions.st_geomfromwkb(wkb,5186)),
                'gis_buildings_shp',floors_above,main_use_name from quality_raw""")
        db.execute("create index on quality_buildings using gist(geom)")
        db.execute("analyze quality_buildings")

        def containing(lng, lat):
            if lng is None or lat is None:
                return []
            return db.execute(
                """select id,pnu from quality_buildings
                where extensions.st_covers(geom,extensions.st_transform(extensions.st_setsrid(
                extensions.st_makepoint(%s,%s),4326),5186)) order by id""",
                (lng, lat),
            ).fetchall()

        for key in sorted(far | set(conflicts)):
            kind, identity = key
            original = originals[key]
            result = outcomes[original[1]]
            selected, location = result["selection"], result["location"]
            old = containing(original[5], original[6])
            new = containing(location["lng"], location["lat"])
            matched = matches_address(selected, original[1])
            category, rejected, reason = classify(matched, [r[0] for r in old], [r[0] for r in new])
            building_details = db.execute(
                "select id,source,pnu,floors_above,main_use_name from quality_buildings "
                "where id=any(%s) order by id",
                ([r[0] for r in old + new],),
            ).fetchall()
            rows.append(
                dict(
                    kind=kind,
                    id=identity,
                    **source[key],
                    normalized_address=original[1],
                    old_lng=original[5],
                    old_lat=original[6],
                    new_lng=location["lng"],
                    new_lat=location["lat"],
                    provider="juso",
                    move_m=spatial[key]["move_m"],
                    over_500m=key in far,
                    other_pnu=key in conflicts,
                    selection=selected,
                    road_identity_matches=matched,
                    old_buildings=old,
                    new_buildings=new,
                    building_details=building_details,
                    classification=category,
                    rejected=rejected,
                    reason=reason,
                    effective_status="invalid" if rejected else result["status"],
                    caution="동일 주소 단지·캠퍼스의 개별 동은 미확정"
                    if key in far
                    else "PNU 충돌의 원인·현행 필지 정합성은 이 분류로 확정하지 않음",
                )
            )
    missing = []
    for key, original in sorted(originals.items()):
        result = outcomes[original[1]]
        if key[0] == "schools" and result["status"] != "ready":
            missing.append(
                dict(
                    id=key[1],
                    **source[key],
                    normalized_address=original[1],
                    status=result["status"],
                    vworld="not_called_storage_restriction",
                )
            )
    rejected_addresses = sorted({r["normalized_address"] for r in rows if r["rejected"]})
    summary = dict(
        source_fingerprint=inventory["source_fingerprint"],
        journal_sha256=hashlib.sha256((directory / "journal.sqlite3").read_bytes()).hexdigest(),
        seoul_footprints_sha256=hashlib.sha256(seoul_footprints.read_bytes()).hexdigest()
        if seoul_footprints
        else None,
        reviewed_rows=len(rows),
        over_500m=dict(
            rows=len(far),
            addresses=len({r["normalized_address"] for r in rows if r["over_500m"]}),
            classifications=dict(Counter(r["classification"] for r in rows if r["over_500m"])),
        ),
        other_pnu=dict(
            rows=len(conflicts),
            addresses=len({r["normalized_address"] for r in rows if r["other_pnu"]}),
            classifications=dict(Counter(r["classification"] for r in rows if r["other_pnu"])),
        ),
        rejected_addresses=rejected_addresses,
        unresolved_schools=len(missing),
        missing_addresses=sum(r["status"] != "ready" for r in outcomes.values()),
        vworld_requests=0,
        vworld_hold="official_geocoder_no_storage_clause",
        school_total=len(inventory["rows"]["schools"]),
        school_ready=len(inventory["rows"]["schools"]) - len(missing),
    )
    output.mkdir(parents=True)
    write_json(output / "summary.json", summary)
    write_json(output / "review.json", rows)
    write_json(output / "unresolved-schools.json", missing)
    write_json(
        output / "rejections.json", {a: "source_road_identity_mismatch" for a in rejected_addresses}
    )
    write_tables(output, rows, missing)
    return summary


def write_tables(output, rows, missing):
    headers = [
        "종류",
        "ID",
        "기관명",
        "원문 도로명",
        "원문 상세",
        "이전 경도/위도",
        "새 경도/위도",
        "이동m",
        "검토 사유",
        "Juso 도로명",
        "Juso 지번",
        "Juso 건물명",
        "PNU",
        "건물관리번호",
        "이전 도형 ID/PNU",
        "새 도형 ID/PNU",
        "분류",
        "미확보 전환",
        "판정 근거",
        "한계",
    ]
    values = []
    for r in rows:
        s = r["selection"]
        values.append(
            [
                r["kind"],
                r["id"],
                r["name"],
                r["source_road"],
                r["source_detail"],
                f"{r['old_lng']},{r['old_lat']}",
                f"{r['new_lng']},{r['new_lat']}",
                r["move_m"],
                "+".join(
                    x for yes, x in [(r["over_500m"], ">500m"), (r["other_pnu"], "다른 PNU")] if yes
                ),
                s["roadAddrPart1"],
                s["jibunAddr"],
                s["bdNm"],
                s["pnu"],
                s["bdMgtSn"],
                json.dumps(r["old_buildings"], ensure_ascii=False),
                json.dumps(r["new_buildings"], ensure_ascii=False),
                r["classification"],
                r["rejected"],
                r["reason"],
                r["caution"],
            ]
        )
    with (output / "review.csv").open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(values)

    def table(h, rs):
        def line(row):
            return (
                "| " + " | ".join(str(x).replace("|", "\\|").replace("\n", " ") for x in row) + " |"
            )

        return "\n".join([line(h), line(["---"] * len(h)), *(line(r) for r in rs)])

    (output / "review.md").write_text(
        "# 좌표 품질 검토 (로컬 보관)\n\n"
        "같은 건물은 두 점을 포함하는 동일 적재 도형 ID가 확인된 경우다. "
        "원천 주소·현행 PNU가 옳다는 판정과는 다르다. "
        "서로 다른 도형이어도 이전 좌표가 틀렸을 가능성이 있어 "
        "새 결과의 오매칭으로 자동 확정하지 않는다. "
        "개별 건물 증거가 없는 단지·캠퍼스 대표점은 판단 불가로 남긴다.\n\n"
        + table(headers, values)
        + "\n"
    )
    (output / "unresolved-schools.md").write_text(
        "# 미확보 학교\n\nVworld 재시도는 공식 저장 제한으로 호출 전 보류.\n\n"
        + table(
            ["ID", "학교명", "원문 주소", "원문 상세", "사유"],
            [
                [r["id"], r["name"], r["source_road"], r["source_detail"], r["status"]]
                for r in missing
            ],
        )
        + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seoul-footprints", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            review(args.database_url, args.directory, args.output, args.seoul_footprints),
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
