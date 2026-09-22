"""Thin refresh adapters around the verified S1 collectors, normalizers and loaders."""

import hashlib
import json
import os
import shutil
import subprocess
from datetime import date
from pathlib import Path

import boto3
import duckdb
import pandas as pd
from dotenv import dotenv_values

from ingest import academies, schools, stores
from ingest.common import ROOT
from ingest.refresh import month_end, month_window
from ingest.seoul_transit import read_frame, write_frame
from ingest.verify_rent import publish_verified, read_published


def restore_object(store, key, destination, digest=None):
    if not key.startswith("raw/") or ".." in key.split("/") or "\\" in key:
        raise ValueError("Expected a raw object key")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    if store.settings.uses_r2:
        s = store.settings
        client = boto3.client(
            "s3",
            endpoint_url=f"https://{s.r2_account_id}.r2.cloudflarestorage.com",
            aws_access_key_id=s.r2_access_key_id,
            aws_secret_access_key=s.r2_secret_access_key,
        )
        client.download_file(s.r2_bucket, key, str(destination))
    else:
        shutil.copyfile(store._local_path(key), destination)
    if digest:
        with destination.open("rb") as f:
            if hashlib.file_digest(f, "sha256").hexdigest() != digest:
                raise ValueError("Manual input checksum mismatch")
    return destination


def assets(args, store):
    path = args.asset_manifest
    if args.asset_manifest_key:
        path = restore_object(store, args.asset_manifest_key, args.directory / "assets.json")
    if not path:
        return {}
    result = {}
    for name, entry in json.loads(Path(path).read_text()).items():
        if Path(name).name != name or not isinstance(entry, dict) or "sha256" not in entry:
            raise ValueError("Manual assets require basename and SHA256")
        result[name] = restore_object(store, entry["key"], args.directory / name, entry["sha256"])
    return result


class Publication:
    def __init__(self, args, store):
        self.args, self.store, self.objects = args, store, []

    def raw(self, source, month, path):
        result = publish_verified(self.store, source, month, path, snapshot=self.args.snapshot)
        self.objects.append({k: v for k, v in result.items() if k != "location"})
        return result

    def frame(self, source, month, frame):
        path = self.args.directory / (source + ".parquet")
        write_frame(frame, path)
        return self.raw(source, month, path)

    def reread(self, manifest):
        return read_published(self.store, [manifest])


def _population(args, pub, db, files):
    from ingest.population import fetch_month, normalize_residents
    from ingest.population_database import load_resident_snapshot

    path = files.get("residents.csv") or fetch_month(
        args.end_month, args.directory / "residents.csv"
    )
    raw = pd.read_csv(path, encoding="cp949", dtype=str, keep_default_na=False)
    original = pub.frame("resident_population", args.end_month, raw)
    reread = args.directory / "residents-reread.csv"
    pub.reread(original).to_csv(reread, encoding="cp949", index=False)
    frame = normalize_residents(reread, args.end_month)
    boundaries = db.execute("""select adm_cd,name,extensions.st_astext(geom),source,source_version
        from public.admin_dongs order by adm_cd""").fetchall()
    if not boundaries or len({(x[3], x[4]) for x in boundaries}) != 1:
        raise ValueError("One verified admin boundary snapshot required")
    rows = [dict(code=a, name=b, wkt=c) for a, b, c, _, _ in boundaries]
    pub.frame("resident_profile", args.end_month, frame)
    return month_end(args.end_month), lambda connection: load_resident_snapshot(
        connection,
        rows,
        frame.astype(object).where(pd.notna(frame), None).to_dict("records"),
        boundary_source=boundaries[0][3],
        boundary_version=boundaries[0][4],
        source="mois_resident_population",
        source_version=args.end_month,
    )


def _living(args, pub, db, files):
    from ingest.living_population import aggregate_window, fetch_month, prepare_month
    from ingest.population_database import load_living_population

    months = month_window(args.end_month, 3)
    paths = []
    for month in months:
        archive = files.get("living-" + month + ".zip") or fetch_month(
            month, args.directory / ("living-" + month + ".zip")
        )
        path = args.directory / ("living-" + month + ".parquet")
        prepare_month(archive, month, path)
        manifest = pub.raw("living_population", month, path)
        # Reaggregate the verified published bytes, not an unrelated in-memory frame.
        restored = restore_object(
            pub.store,
            manifest["key"],
            args.directory / ("verified-" + month + ".parquet"),
            manifest["sha256"],
        )
        paths.append(restored)
    start, end = date.fromisoformat(months[0] + "-01"), month_end(args.end_month)
    profile = args.directory / "living-profile.parquet"
    aggregate_window(paths, start, end, profile)
    manifest = pub.raw("living_profile", args.end_month, profile)
    frame = pub.reread(manifest)
    known = {
        r[0]
        for r in db.execute("select cell_id from public.population_cells where resolution_m=250")
    }
    if not set(frame.cell_id).issubset(known):
        raise ValueError("New cells require verified boundary refresh; previous profile retained")
    return end, lambda connection: load_living_population(
        connection,
        frame.astype(object).where(pd.notna(frame), None).to_dict("records"),
        source="seoul_living_population_250m",
        source_version=f"{start}/{end}",
    )


def _transit(args, pub, db, files):
    from ingest.seoul_transit import download
    from ingest.transit_database import load_snapshot, seoul_stops
    from ingest.verify_transit import SOURCES, aggregate_months, coverage, require_coverage

    months = month_window(args.end_month, 3)
    stops, counts, reports = [], [], {}
    for kind, (adapter, service, master_service) in SOURCES.items():
        m = pub.raw(
            kind + "_stops",
            args.snapshot[:4] + "-" + args.snapshot[4:6],
            download(master_service, "", args.directory),
        )
        master = adapter.stops(pub.reread(m))
        scoped = seoul_stops(db, master)
        normalized, checks = [], {}
        for month in months:
            m = pub.raw(
                kind + "_boardings",
                month,
                download(service, month.replace("-", ""), args.directory),
            )
            raw = pub.reread(m)
            frame = adapter.normalize(raw, master, month)
            check = coverage(raw, frame, set(scoped.stop_id))
            require_coverage(check)
            normalized.append(frame)
            checks[month] = check
        aggregate = aggregate_months(normalized, months)
        aggregate = aggregate[aggregate.stop_id.isin(set(scoped.stop_id))]
        stops.append(scoped)
        counts.append(aggregate)
        reports[kind] = dict(
            months=checks,
            coordinates=dict(retrieved_on=date.today().isoformat()),
            unit="persons_per_day",
            missing_lines=["Shinbundang not imputed"] if kind == "subway" else [],
        )
    start, end = months[0] + "-01", month_end(args.end_month)
    all_stops, all_counts = (
        pd.concat(stops, ignore_index=True),
        pd.concat(counts, ignore_index=True),
    )
    pub.frame("transit_profile", args.end_month, all_counts)
    return end, lambda connection: load_snapshot(
        connection,
        all_stops,
        all_counts,
        reports,
        start=start,
        end=str(end),
        coordinate_version=date.today().isoformat(),
    )


def _places(args, pub, db, files):
    from ingest.commerce_education_database import attach_geocodes, load_snapshot
    from ingest.geocode import resolve_one

    module = {"academies": academies, "schools": schools, "stores": stores}[args.source]
    if args.source == "stores":
        path = stores.extract_raw(files["stores.zip"], args.directory, args.end_month)
    else:
        path = module.fetch(args.directory)
    month = (
        args.end_month if args.source == "stores" else args.snapshot[:4] + "-" + args.snapshot[4:6]
    )
    manifest = pub.raw(args.source, month, path)
    raw = pub.reread(manifest)
    # Stores normalize is a parquet reader; the other adapters accept frames.
    restored = args.directory / "places-reread.parquet"
    write_frame(raw, restored)
    frame = module.normalize(restored if args.source == "stores" else raw)
    if args.source != "stores":
        env = {**dotenv_values(ROOT / ".env"), **os.environ}
        for address in sorted(set(frame.address) - {""}):
            resolve_one(
                db,
                address,
                key=env.get("KAKAO_REST_API_KEY", ""),
                budget=10000,
                journal=args.directory / "geocode",
            )
        frame = attach_geocodes(db, frame)
    version = args.end_month if args.source == "stores" else date.today().isoformat()
    pub.frame(args.source + "_profile", month, frame)
    report = dict(rows=len(frame), snapshot=args.snapshot)
    return (month_end(args.end_month) if args.source == "stores" else date.today()), (
        lambda connection: load_snapshot(
            connection,
            args.source,
            frame,
            source=("semas_stores" if args.source == "stores" else module.SOURCE),
            version=version,
            raw_key=manifest["key"],
            report=report,
        )
    )


def _trades(args, pub, db, files):
    from ingest.commercial_trades import collect_months, normalize_trades
    from ingest.rent_database import aggregate_trades, load_trade_snapshot

    months = month_window(args.end_month, 24)
    raw = collect_months(months[0].replace("-", ""), months[-1].replace("-", ""), args.directory)
    verified = []
    for month in months:
        m = pub.frame(
            "commercial_trades", month, raw[raw.request_month == month.replace("-", "")].copy()
        )
        verified.append(pub.reread(m))
    boundaries = pd.DataFrame(
        db.execute("""select code8,name,extensions.st_astext(geom),
        source,source_version from public.legal_dongs order by code8""").fetchall(),
        columns=["code8", "name", "wkt", "source", "source_version"],
    )
    if len(boundaries) != 14:
        raise ValueError("Verified Gangnam legal boundaries required")
    normalized = normalize_trades(
        pd.concat(verified, ignore_index=True), dict(zip(boundaries.name, boundaries.code8))
    )
    stats = aggregate_trades(normalized)
    pub.frame("commercial_trade_profile", args.end_month, stats)
    report = dict(eligible_count=int(normalized.eligible.sum()), raw_count=len(raw))
    return month_end(args.end_month), lambda connection: load_trade_snapshot(
        connection,
        boundaries,
        stats,
        period_start=months[0] + "-01",
        period_end=str(month_end(args.end_month)),
        source_version=args.snapshot,
        report=report,
    )


def _buildings(args, pub, db, files):
    from ingest.building_footprints import WfsClient, normalize_shp, normalize_wfs, read_shp_zip
    from ingest.building_register import normalize_floors, normalize_titles, pnu_parts
    from ingest.buildings_database import load_snapshot

    raw, path, _ = read_shp_zip(files["buildings.zip"], args.directory)
    shp, _ = normalize_shp(raw)
    extent = db.execute("""select extensions.st_xmin(g),extensions.st_ymin(g),
        extensions.st_xmax(g),extensions.st_ymax(g) from
        (select extensions.st_extent(geom) g from public.admin_dongs
        where left(adm_cd,5)='11680') q""").fetchone()
    if not extent or any(x is None for x in extent):
        raise ValueError("Verified Gangnam boundary required")
    with duckdb.connect() as spatial:
        spatial.execute("LOAD spatial")
        spatial.register("raw_shapes", raw)
        shape = spatial.execute("""select min(ST_XMin(g)),min(ST_YMin(g)),
            max(ST_XMax(g)),max(ST_YMax(g)) from (select
            ST_Transform(ST_GeomFromWKB(source_geometry_wkb),
                'EPSG:5186','EPSG:4326',always_xy:=true) g from raw_shapes) q""").fetchone()
    extent = (
        min(shape[0], extent[0]) - 0.00001,
        min(shape[1], extent[1]) - 0.00001,
        max(shape[2], extent[2]) + 0.00001,
        max(shape[3], extent[3]) + 0.00001,
    )
    version = date.today().isoformat()
    features, _ = WfsClient(args.directory / "wfs", version).collect(extent)
    wfs, _ = normalize_wfs(features, set(shp.gis_id), version, args.directory / "wfs.parquet")
    groups = [pnu_parts(p) for p in sorted(set(shp.pnu))]
    # Bulk registry collection may exceed one run's provider budget. Manual refresh
    # accepts the existing resumable collector's completed, checksum-verified artifacts.
    collected = json.loads(files["register-manifest.json"].read_text())
    if collected.get("groups") != groups:
        raise ValueError("Register manifest must cover every SHP parcel")
    raw_paths = dict(
        gis_buildings_shp=path,
        vworld_building_footprints=args.directory / "wfs.parquet",
        building_hub_titles=files["titles.parquet"],
        building_hub_floors=files["floors.parquet"],
    )
    for kind in ("titles", "floors"):
        if len(read_frame(files[kind + ".parquet"])) != collected[kind]["rows"]:
            raise ValueError("Register row count differs from completed manifest")
    month = version[:7]
    manifests = {name: pub.raw(name, month, p) for name, p in raw_paths.items()}
    pub.frame(
        "building_register_collection",
        month,
        pd.DataFrame([{"manifest_json": json.dumps(collected, ensure_ascii=False)}]),
    )
    titles = normalize_titles(pub.reread(manifests["building_hub_titles"]))
    floors = normalize_floors(pub.reread(manifests["building_hub_floors"]))
    # Preserve the original manual ZIP under a revision-specific source namespace too.
    archive = pub.store.publish_archive(
        "building_zip_" + args.snapshot.lower(), month, files["buildings.zip"]
    )
    from ingest.verify_buildings import verify_archive

    verify_archive(pub.store, archive)
    pub.objects.append(archive)
    return date.today(), lambda connection: load_snapshot(
        connection,
        pd.concat([shp, wfs], ignore_index=True),
        titles,
        floors,
        snapshot=version,
        raw_objects=manifests,
    )


def _rent(args, pub, db, files):
    from ingest.publish_rent_survey import build_scopes, quarter_dates
    from ingest.rent_database import load_survey_snapshot
    from ingest.rent_survey import collect_survey, normalize_survey

    if not args.quarter:
        raise ValueError("Manual rent refresh requires quarter")
    start, end = quarter_dates(args.quarter)
    if end >= date.today():
        raise ValueError("Only completed survey quarters")
    raw = collect_survey(args.quarter, args.directory / "rone")
    manifest = pub.frame("rent_survey", end.strftime("%Y-%m"), raw)
    raw = pub.reread(manifest)
    metadata = [
        item
        for name in (
            "rone-cls-office-names.json",
            "rone-cls-names.json",
            "rone-cls-small-names.json",
            "rone-cls-collective-names.json",
        )
        for item in json.loads(files[name].read_text())["data"]
    ]
    intersections = json.loads(files["rent-intersections.json"].read_text())
    scopes, areas = build_scopes(
        raw, intersections, metadata, quarter=args.quarter, snapshot=args.snapshot
    )
    surveys = normalize_survey(raw, scopes, source_version=args.snapshot)
    if areas.mapping_verified.any() or areas.wkt.notna().any():
        raise ValueError("Unverified rent geography must stay inactive")
    pub.frame("rent_profile", end.strftime("%Y-%m"), surveys)
    pub.frame(
        "rent_scope_evidence",
        end.strftime("%Y-%m"),
        pd.DataFrame(
            [
                {
                    "metadata_json": json.dumps(metadata, ensure_ascii=False),
                    "intersections_json": json.dumps(intersections, ensure_ascii=False),
                }
            ]
        ),
    )
    return end, lambda connection: load_survey_snapshot(
        connection,
        areas,
        surveys,
        source_version=args.snapshot,
        report=dict(
            quarter=args.quarter, activated_areas=0, period_start=str(start), period_end=str(end)
        ),
    )


def prepare_source(args, store, db):
    pub = Publication(args, store)
    files = assets(args, store)
    dispatch = dict(
        living=_living,
        population=_population,
        transit=_transit,
        academies=_places,
        schools=_places,
        stores=_places,
        trades=_trades,
        buildings=_buildings,
        rent=_rent,
    )
    period_end, loader = dispatch[args.source](args, pub, db, files)
    manifest = dict(
        source=args.source,
        snapshot=args.snapshot,
        period_end=str(period_end),
        contract_version="1.2",
        objects=pub.objects.copy(),
        git_commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
    )
    # Candidate manifest is immutable; only refresh_snapshots commits its active status.
    saved = pub.frame(
        "refresh_manifest_" + args.source,
        period_end.strftime("%Y-%m"),
        pd.DataFrame([dict(manifest_json=json.dumps(manifest, ensure_ascii=False))]),
    )
    manifest["manifest_key"] = saved["key"]
    return period_end, manifest, loader
