"""Local analysis of downloaded school-location standard; no production loader."""

import argparse
import hashlib
import json
import math
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import duckdb

from ingest.academy_transition import write_json
from ingest.geocode import normalize_address
from ingest.verify_academy_transition import isolated


def road_key(value):
    text = normalize_address(value)
    found = re.search(r"서울(?:특별시)?\s+(\S+구)\s+(\S+(?:로|길))\s+(\d+(?:-\d+)?)", text)
    return found.groups() if found else None


def name_key(name, level):
    return re.sub(r"\s+", "", normalize_address(name)), level


def review(directory, transition, output, database_url):
    if output.exists():
        raise ValueError("Use a new immutable analysis directory")
    files = sorted(directory.glob("standard-page-*.json"))
    national = [row for file in files for row in json.loads(file.read_text())]
    expected = json.loads((directory / "columns.json").read_text())["totalCount"]
    if len(national) != expected or len({r["SCHOOL_ID"] for r in national}) != expected:
        raise ValueError("Missing/duplicate standard school rows")
    seoul = [r for r in national if r["CDDC_NM"] == "서울특별시교육청"]
    inventory = json.loads((transition / "inventory.json").read_text())
    ids = {r[0] for r in inventory["rows"]["schools"]}
    with duckdb.connect() as raw:
        neis = raw.read_parquet(str(transition / "raw" / "schools.parquet")).df()
    neis = neis[neis.SD_SCHUL_CODE.isin(ids)].to_dict("records")
    if len(neis) != len(ids):
        raise ValueError("NEIS inventory mismatch")
    with sqlite3.connect(f"file:{transition / 'journal.sqlite3'}?mode=ro", uri=True) as db:
        outcomes = {a: json.loads(r) for a, r in db.execute("select address,result from outcomes")}
    by_name = defaultdict(list)
    for row in seoul:
        if row["OPER_STTUS"] == "운영":
            by_name[name_key(row["SCHOOL_NM"], row["SCHOOL_SE"])].append(row)
    rows = []
    with isolated(database_url) as db:
        db.execute("set transaction read only")
        for row in neis:
            address = normalize_address(row["ORG_RDNMA"])
            old = outcomes[address]
            matches = by_name[name_key(row["SCHUL_NM"], row["SCHUL_KND_SC_NM"])]
            item = dict(
                neis_id=row["SD_SCHUL_CODE"],
                name=row["SCHUL_NM"],
                level=row["SCHUL_KND_SC_NM"],
                neis_address=address,
                juso_status=old["status"],
                name_matches=len(matches),
                status="name_missing" if not matches else "ambiguous",
                standard=None,
            )
            if len(matches) == 1:
                candidate = matches[0]
                item["standard"] = candidate
                matched = road_key(address) is not None and road_key(address) == road_key(
                    candidate["RDNMADR"]
                )
                item["status"] = "address_match" if matched else "address_diff"
                try:
                    lng, lat = float(candidate["LONGITUDE"]), float(candidate["LATITUDE"])
                    if not (
                        math.isfinite(lng)
                        and math.isfinite(lat)
                        and 124 <= lng <= 132
                        and 33 <= lat <= 39
                    ):
                        raise ValueError("Invalid standard coordinate")
                except (TypeError, ValueError):
                    item["status"] = "invalid_coordinate"
                else:
                    item["inside_seoul"] = db.execute(
                        """select exists(select 1 from public.admin_dongs
                        where extensions.st_covers(geom,extensions.st_setsrid(
                        extensions.st_makepoint(%s,%s),4326)))""",
                        (lng, lat),
                    ).fetchone()[0]
                    if old["status"] == "ready":
                        location = old["location"]
                        item["juso_lng"], item["juso_lat"] = location["lng"], location["lat"]
                        item["distance_m"] = db.execute(
                            """select extensions.st_distance(
                            extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326)::extensions.geography,
                            extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326)::extensions.geography)""",
                            (lng, lat, location["lng"], location["lat"]),
                        ).fetchone()[0]
            rows.append(item)
    accepted = [r for r in rows if r["status"] == "address_match" and r.get("inside_seoul")]
    if len({r["standard"]["SCHOOL_ID"] for r in accepted}) != len(accepted):
        raise ValueError("Crosswalk is not one-to-one")
    distances = sorted(r["distance_m"] for r in accepted if "distance_m" in r)
    summary = dict(
        national=len(national),
        seoul=len(seoul),
        neis=len(neis),
        direct_id_matches=len(ids & {r["SCHOOL_ID"] for r in seoul}),
        name_unique=sum(r["name_matches"] == 1 for r in rows),
        status_counts=dict(Counter(r["status"] for r in rows)),
        accepted=len(accepted),
        accepted_rate=len(accepted) / len(neis) * 100,
        identity_matches=sum(r["status"] == "address_match" for r in rows),
        old_missing=sum(r["juso_status"] != "ready" for r in rows),
        old_missing_matched=sum(r["juso_status"] != "ready" for r in accepted),
        missing_after_standard=len(neis) - len(accepted),
        combined_missing=sum(r["juso_status"] != "ready" and r not in accepted for r in rows),
        outside_seoul=sum(r.get("inside_seoul") is False for r in rows),
        blank_neis_code=sum(not r["neis_id"].strip() for r in rows),
        distance=dict(
            count=len(distances),
            median=distances[len(distances) // 2] if distances else None,
            p95=distances[math.ceil(len(distances) * 0.95) - 1] if distances else None,
            max=max(distances, default=None),
            over_100=sum(x > 100 for x in distances),
            over_500=sum(x > 500 for x in distances),
        ),
        reference_dates=dict(Counter(r["REFERENCE_DATE"] for r in national)),
        change_dates=dict(Counter(r["CHANGE_DATE"] for r in national)),
        files=[dict(name=f.name, sha256=hashlib.sha256(f.read_bytes()).hexdigest()) for f in files],
        mode="analysis_only_no_database_changes",
    )
    output.mkdir(parents=True)
    write_json(output / "rows.json", rows)
    write_json(output / "summary.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--transition", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(
        json.dumps(
            review(args.directory, args.transition, args.output, args.database_url),
            ensure_ascii=False,
        )
    )
