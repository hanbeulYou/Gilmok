"""Publish complete R-ONE facts; unproved survey geography remains disabled."""

import argparse
import calendar
import hashlib
import json
import math
import os
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from dotenv import dotenv_values

from ingest.common import ROOT, RawStore, Settings
from ingest.database import connect_database
from ingest.rent_database import load_survey_snapshot
from ingest.rent_survey import TABLES, collect_survey, normalize_survey, quarter_id
from ingest.seoul_transit import write_frame
from ingest.verify_rent import publish_verified, read_published

METHODOLOGY = "https://www.reb.or.kr/reb/cm/cntnts/cntntsView.do?cntntsId=1049&mi=9800"
METADATA_FILES = (
    "rone-cls-office-names.json", "rone-cls-names.json",
    "rone-cls-small-names.json", "rone-cls-collective-names.json",
)


def quarter_dates(quarter):
    quarter_id(quarter)
    year, last_month = int(quarter[:4]), int(quarter[-1]) * 3
    return (date(year, last_month - 2, 1),
            date(year, last_month, calendar.monthrange(year, last_month)[1]))


def load_scope_evidence(directory):
    """Read saved official classification metadata and measured boundary intersections."""
    directory = Path(directory)
    intersections = json.loads((directory / "boundary-intersections.json").read_text())
    metadata = []
    for filename in METADATA_FILES:
        path = directory / filename
        if path.exists():
            payload = json.loads(path.read_text())
            if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
                raise ValueError("Invalid official R-ONE classification metadata")
            metadata.extend(payload["data"])
    return intersections, metadata


def build_scopes(raw, intersections, metadata, *, quarter, snapshot):
    """Resolve table/class facts, never infer region coverage from Gangnam-gu."""
    start, end = quarter_dates(quarter)
    positive = set()
    for item in intersections:
        if (not isinstance(item, list) or len(item) != 4 or not isinstance(item[1], str)
                or type(item[3]) not in (float, int) or not math.isfinite(item[3])):
            raise ValueError("Invalid measured survey boundary intersection")
        if item[3] > 0:
            positive.add(item[1])
    official = {}
    table_classes = {}
    for item in metadata:
        path = item.get("viewItmFullnm")
        if not isinstance(path, str) or not path.startswith("서울>강남"):
            continue
        identity = str(item.get("itmId", ""))
        if not identity.isdigit() or len(identity) != 8:
            raise ValueError("Invalid official R-ONE geographic code")
        official.setdefault(path, set()).add(identity)
        table_key = (str(item.get("statblId")), str(item.get("datano")))
        table_classes.setdefault(table_key, set()).add(path)
    if any(len(codes) != 1 for codes in official.values()):
        raise ValueError("Ambiguous official geographic identity for survey hierarchy")
    scopes, areas, evidence_by_area = {}, {}, {}
    for row in raw.to_dict("records"):
        table, cls = str(row["STATBL_ID"]), str(row["CLS_ID"])
        if table not in TABLES:
            raise ValueError("Unexpected survey table")
        full_name = row.get("CLS_FULLNM")
        if not isinstance(full_name, str):
            continue  # No name guessing from classification number or nearby polygon.
        parts = full_name.split(">")
        if parts[:2] != ["서울", "강남"] or len(parts) not in (2, 3):
            continue
        if row.get("CLS_NM") != parts[-1]:
            raise ValueError("Survey hierarchy and leaf name disagree")
        expected = table_classes.get((table, cls))
        if expected is not None and expected != {full_name}:
            raise ValueError("Raw survey hierarchy disagrees with saved table metadata")
        if len(parts) == 2:
            if cls != "510004":
                raise ValueError("Unverified Gangnam statistical-region classification")
            code, level = "61029200", "region"
            if full_name in official and official[full_name] != {code}:
                raise ValueError("Gangnam official region code disagrees with metadata")
            reason = "official_region_definition_missing; Gangnam region is not Gangnam-gu"
        else:
            if parts[-1] not in positive:
                continue
            code = next(iter(official[full_name])) if full_name in official else f"rone:{full_name}"
            level = "district"
            reason = "2024_boundary_applicability_to_requested_quarter_unverified"
        evidence = {"table": table, "cls_id": cls, "full_name": full_name,
                    "official_area_code": code if not code.startswith("rone:") else None,
                    "missing_boundary_reason": reason, "methodology_url": METHODOLOGY}
        scope = {"area_code": code, "area_name": parts[-1], "level": level,
                 "building_class": TABLES[table][0],
                 "evidence": json.dumps(evidence, ensure_ascii=False, sort_keys=True)}
        key = (table, cls)
        if key in scopes and scopes[key] != scope:
            raise ValueError("Ambiguous table/class survey scope")
        scopes[key] = scope
        identity = (parts[-1], level)
        if code in areas and (areas[code]["area_name"], areas[code]["level"]) != identity:
            raise ValueError("Conflicting area identity")
        evidence_by_area.setdefault(code, {})[(table, cls)] = evidence
        areas[code] = {"area_code": code, "area_name": parts[-1], "level": level,
                       "gu_code": "11680", "wkt": None, "valid_from": start,
                       "valid_to": end, "mapping_verified": False,
                       "source": "R-ONE", "source_version": snapshot}
    if not scopes:
        raise ValueError("No evidenced Gangnam survey facts in complete response")
    for code, area in areas.items():
        area["mapping_evidence"] = json.dumps(
            list(evidence_by_area[code].values()), ensure_ascii=False, sort_keys=True
        )
    return scopes, pd.DataFrame(areas.values()).sort_values("area_code").reset_index(drop=True)


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n")


def run(args, *, store=None, database_factory=None):
    """All raw publication and comparison must succeed before any database connection."""
    datetime.strptime(args.snapshot, "%Y%m%dT%H%M%SZ")
    start, end = quarter_dates(args.quarter)
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    if not env.get("RONE_API_KEY"):
        raise ValueError("RONE_API_KEY is required before collecting rent survey facts")
    store = store or RawStore(Settings.from_env())
    directory = Path(args.directory)
    output = directory / args.snapshot
    output.mkdir(parents=True, exist_ok=True)
    intersections, metadata = load_scope_evidence(directory)
    raw = collect_survey(args.quarter, directory / "rone-authenticated")
    if raw.empty or set(raw.STATBL_ID.astype(str)) != set(TABLES):
        raise ValueError("Rent survey snapshot requires all eight complete source tables")
    if set(raw.WRTTIME_IDTFR_ID.astype(str)) != {quarter_id(args.quarter)}:
        raise ValueError("Rent survey snapshot contains an unexpected quarter")
    # Store all provider fields, including nationwide rows outside S1's query coverage.
    path = output / "rent-survey.parquet"
    write_frame(raw, path)
    manifest = publish_verified(store, "rent_survey", end.strftime("%Y-%m"), path,
                                snapshot=args.snapshot)
    reread = read_published(store, [manifest])
    scopes, areas = build_scopes(reread, intersections, metadata,
                                quarter=args.quarter, snapshot=args.snapshot)
    surveys = normalize_survey(reread, scopes, source_version=args.snapshot)
    if surveys.empty or areas.mapping_verified.any() or areas.wkt.notna().any():
        raise ValueError("Unproved geography must never be activated by publication")
    evidence = {"intersections": intersections, "classification_metadata": metadata,
                "scopes": [{"table": k[0], "cls_id": k[1], **v} for k, v in scopes.items()],
                "areas": areas.to_dict("records")}
    geometry_path = directory / "rone-seoul-boundaries.json"
    if geometry_path.exists():
        evidence["raw_geometry_response"] = json.loads(geometry_path.read_text())
    # Preserve taxonomy and the original provider shapes, including unactivated ones.
    evidence_json = json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str)
    scope_path = output / "rent-survey-scope.parquet"
    write_frame(pd.DataFrame([{"evidence_json": evidence_json}]), scope_path)
    scope_manifest = publish_verified(
        store, "rent_survey_scope", end.strftime("%Y-%m"), scope_path, snapshot=args.snapshot
    )
    scope_reread = read_published(store, [scope_manifest])
    if (len(scope_reread) != 1 or "evidence_json" not in scope_reread
            or json.loads(scope_reread.iloc[0].evidence_json) != json.loads(evidence_json)):
        raise ValueError("Published survey scope evidence differs from validated input")
    _write_json(output / "rent-survey-evidence.json", evidence)
    report = {"quarter": args.quarter, "snapshot": args.snapshot,
              "period_start": start.isoformat(), "period_end": end.isoformat(),
              "raw_manifest": manifest, "scope_manifest": scope_manifest,
              "raw_rows": len(reread), "survey_rows": len(surveys),
              "area_rows": len(areas), "activated_areas": 0,
              "rent_level_policy": ["district", "region", None],
              "region_definition_found": False,
              "missing_reason": "region_definition_and_district_quarter_geometry_unverified",
              "evidence_sha256": hashlib.sha256(
                  (output / "rent-survey-evidence.json").read_bytes()).hexdigest()}
    _write_json(output / "rent-survey-publication.json", report)
    factory = database_factory or (lambda: connect_database(local_only=True))
    with factory() as connection:
        report["database"] = load_survey_snapshot(
            connection, areas, surveys, source_version=args.snapshot, report=report
        )
    _write_json(output / "rent-survey-report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--quarter", default="2026-Q2")
    parser.add_argument("--directory", default=".local/validation/pr6")
    parser.add_argument("--snapshot", required=True, help="UTC YYYYMMDDTHHMMSSZ")
    args = parser.parse_args()
    report = run(args)
    print(json.dumps({"raw_rows": report["raw_rows"], "survey_rows": report["survey_rows"],
                      "activated_areas": report["activated_areas"]}))


if __name__ == "__main__":
    main()
