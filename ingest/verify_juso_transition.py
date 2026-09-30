"""Three-address T1 collection only; read-only local DB, no shared cache/R2 promotion.

uv run python -m ingest.verify_juso_transition
pnpm score:reference:build
node ingest/verify_juso_transition.mjs
Saved responses are reused so restarting the report never repeats coordinate requests.
"""

import argparse
import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path

from dotenv import dotenv_values

from ingest.common import ROOT
from ingest.database import connect_database
from ingest.juso import parse_geocode, request_address
from ingest.score_reference import fingerprint, source_state

BASELINE = ROOT / ".local/validation/s2-4-v03-20260926/inputs.json"
DEFAULT_DIRECTORY = ROOT / ".local/validation/s3-2-a0-juso"


def collect(directory):
    env = {**dotenv_values(ROOT / ".env"), **os.environ}
    if not env.get("JUSO_API_KEY") or not env.get("VWORLD_API_KEY"):
        raise ValueError("JUSO_API_KEY and VWORLD_API_KEY required; no requests issued")
    baseline = json.loads(BASELINE.read_text())
    directory.mkdir(parents=True, exist_ok=True)
    cases, spatial, responses = [], [], []
    with connect_database(local_only=True) as db:
        db.execute("set transaction isolation level repeatable read read only")
        current_fingerprint = fingerprint(source_state(db))
        if current_fingerprint != baseline["reference"]["source_fingerprint"]:
            raise ValueError("Background source fingerprint changed; T1 comparison stopped")
        for old in baseline["cases"][:3]:
            candidate = deepcopy(old["candidate"])
            address = candidate["address"]
            path = directory / (old["key"] + "-response.json")
            if path.exists():
                envelope = json.loads(path.read_text())
            else:
                envelope = request_address(address, env["JUSO_API_KEY"],
                                           coordinate_key=env["VWORLD_API_KEY"])
                path.write_text(json.dumps(envelope, ensure_ascii=False, indent=2) + "\n")
            status, lng, lat = parse_geocode(envelope, address)
            if status != "success":
                raise ValueError(f"{old['key']}: address result {status}; no DB/cache writes")
            pnu = envelope["selection"]["pnu"]
            old_pnu = old["primary"]["building"]["pnu"]
            rows = db.execute("""with p as (select extensions.st_setsrid(
                extensions.st_makepoint(%s,%s),4326) geom)
                select b.id, extensions.st_covers(b.geom,p.geom),
                  extensions.st_distance(b.geom::extensions.geography,p.geom::extensions.geography),
                  extensions.st_y(extensions.st_transform(extensions.st_centroid(
                    extensions.st_transform(b.geom,5186)),4326)),
                  extensions.st_x(extensions.st_transform(extensions.st_centroid(
                    extensions.st_transform(b.geom,5186)),4326)),
                  extensions.st_distance(p.geom::extensions.geography,extensions.st_setsrid(
                    extensions.st_makepoint(%s,%s),4326)::extensions.geography)
                from public.buildings b,p where b.pnu=%s order by b.id""",
                (lng, lat, candidate["lng"], candidate["lat"], pnu)).fetchall()
            match = len(rows) == 1 and rows[0][1] and pnu == old_pnu
            spatial.append(dict(key=old["key"], old_lat=candidate["lat"], old_lng=candidate["lng"],
                                lat=lat, lng=lng, old_pnu=old_pnu, pnu=pnu, passed=bool(match),
                                shapes=[dict(zip(("id", "covers", "distance_m", "centroid_lat",
                                                  "centroid_lng", "movement_m"), row))
                                        for row in rows],
                                coordinate_provider=envelope["location"]["coordinate_provider"]))
            responses.append(dict(key=old["key"], path=path.name,
                                  sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            if not match:
                continue  # Report all three; never snap or enqueue a write from this collector.
            candidate.update(lat=lat, lng=lng)
            primary, school = [db.execute("select public.score_inputs(%s,%s,%s,%s,%s)",
                               (lat, lng, radius, candidate["floor"], address)).fetchone()[0]
                               for radius in (800, 1000)]
            scene = db.execute("select public.exposure_inputs_v022(%s,%s)",
                               (lng, lat)).fetchone()[0]
            scene["floor"] = candidate["floor"]
            if (primary["building"]["id"] != rows[0][0]
                    or scene["candidate_building_id"] != rows[0][0]):
                raise ValueError("RPC candidate building differs from selected PNU footprint")
            inside, distance = db.execute("""with p as (select extensions.st_setsrid(
                extensions.st_makepoint(%s,%s),4326) geom), boundary as (
                select extensions.st_boundary(extensions.st_unaryunion(
                    extensions.st_collect(geom))) geom from public.admin_dongs)
                select exists(select 1 from public.admin_dongs d where
                    extensions.st_covers(d.geom,p.geom)),
                    extensions.st_distance(boundary.geom::extensions.geography,
                                           p.geom::extensions.geography) from p,boundary""",
                                         (lng, lat)).fetchone()
            if not inside:
                raise ValueError("Candidate outside Seoul")
            context = dict(old["context"], inside_seoul=inside, seoul_boundary_distance_m=distance)
            cases.append(dict(old, candidate=candidate, primary=primary, school=school, scene=scene,
                              context=context))
    manifest = dict(stage="T1", baseline_sha256=hashlib.sha256(BASELINE.read_bytes()).hexdigest(),
                    source_fingerprint=current_fingerprint, responses=responses, spatial=spatial,
                    full_recompute=False, database_writes=False, preset_version="0.3")
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    if not all(row["passed"] for row in spatial):
        raise ValueError("PNU/footprint check failed; see manifest, scoring stopped")
    output = dict(baseline, cases=cases, metadata=dict(baseline["metadata"], stage="T1"))
    (directory / "inputs.json").write_text(json.dumps(output, ensure_ascii=False)+"\n")
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    args = parser.parse_args()
    collect(args.directory)


if __name__ == "__main__":
    main()
