"""S2-2 local real-data contract verification; no rankings or external source API calls."""

import json
import subprocess
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from ingest.common import ROOT
from ingest.refresh import target_database
from ingest.score_reference import fingerprint, source_state
from ingest.verify_commerce_education import POINTS


def local_http():
    settings = json.loads(
        subprocess.run(
            ["supabase", "status", "-o", "json"], capture_output=True, text=True, check=True
        ).stdout
    )
    if urlparse(settings["API_URL"]).hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Verification must use local Supabase")

    def rpc(name, args):
        request = Request(
            settings["API_URL"] + "/rest/v1/rpc/" + name,
            data=json.dumps(args).encode(),
            headers={
                "apikey": settings["ANON_KEY"],
                "Authorization": "Bearer " + settings["ANON_KEY"],
                "Content-Type": "application/json",
            },
        )
        with urlopen(request, timeout=30) as response:
            return json.load(response)

    return rpc


def main():
    directory = ROOT / ".local/validation/s2-2"
    directory.mkdir(parents=True, exist_ok=True)
    rpc = local_http()
    references = {
        r: rpc(
            "score_reference_distribution",
            {
                "requested_preset_id": "academy_v0",
                "requested_radius_m": r,
            },
        )
        for r in (800, 1000)
    }
    historical = json.loads(
        (ROOT / "docs/validation/pr7-building-all-floors-20260922.json").read_text()
    )
    cases, precision_rows = [], 0
    with target_database("local") as db:
        db.execute("set transaction isolation level repeatable read read only")
        current = fingerprint(source_state(db))
        for radius, reference in references.items():
            assert reference["preset"]["version"] == "0.1.2"
            assert reference["inputs_schema_version"] == "1.3"
            assert reference["source_fingerprint"] == current
            rows = (
                db.cursor(binary=True)
                .execute(
                    """select axis_key,raw_value from public.score_reference
                where preset_id='academy_v0' and radius_m=%s and raw_value is not null
                order by axis_key,raw_value""",
                    (radius,),
                )
                .fetchall()
            )
            actual = [
                (d["key"], value) for d in reference["distributions"] for value in d["values"]
            ]
            assert actual == rows, "HTTP reference precision differs from stored doubles"
            precision_rows += len(rows)
        boundary = db.execute("""select extensions.st_asbinary(extensions.st_collect(
          extensions.st_exteriorring((part).geom))) from (
          select extensions.st_dump(extensions.st_unaryunion(extensions.st_collect(geom))) part
          from public.admin_dongs) city""").fetchone()[0]
        names = dict(db.execute("select code8,name from public.legal_dongs").fetchall())

        def add(name, lat, lng, floor, radius, address=None):
            args = dict(lat=lat, lng=lng, radius_m=radius, floor=floor, address=address)
            primary = db.execute(
                "select public.score_inputs(%(lat)s,%(lng)s,%(radius_m)s,%(floor)s,%(address)s)",
                args,
            ).fetchone()[0]
            school = db.execute(
                "select public.score_inputs(%s,%s,1000,%s,%s)", (lat, lng, floor, address)
            ).fetchone()[0]
            inside, distance = (
                db.cursor(binary=True)
                .execute(
                    """with point as (
              select extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326) p)
              select exists(select 1 from public.admin_dongs d
                  where extensions.st_covers(d.geom,p)),
              extensions.st_distance(extensions.st_setsrid(extensions.st_geomfromwkb(%s),4326)::extensions.geography,
              p::extensions.geography) from point""",
                    (lng, lat, boundary),
                )
                .fetchone()
            )
            case = dict(
                name=name,
                primary=primary,
                school=school,
                reference=references[radius],
                candidate=dict(
                    lat=lat,
                    lng=lng,
                    floor=floor,
                    address=address,
                    exclusive_area_m2=None,
                    deposit_krw=None,
                    monthly_rent_krw=None,
                    maintenance_krw=None,
                ),
                context=dict(
                    inside_seoul=inside, seoul_boundary_distance_m=distance, legal_dong_names=names
                ),
            )
            cases.append(case)
            return primary

        for name, lat, lng in POINTS:
            for radius in (800, 1000):
                add(name, lat, lng, 2, radius)
        for path in ("footprint", "address_cache"):
            for floor in (3, 4):
                old = historical[path][str(floor)]
                result = add("역삼로460 " + path, old["lat"], old["lng"], floor, 800, "역삼로460")
                assert result["building"]["gross_area"] == 849.97
                assert result["building"]["register_pk"] == "1024123872"
        # Exact anonymous HTTP input values match SQL too (ignore per-call timing metadata).
        for c in cases[:6]:
            a = c["candidate"]
            http = rpc(
                "score_inputs",
                dict(
                    lat=a["lat"],
                    lng=a["lng"],
                    radius_m=c["primary"]["meta"]["radius_m"],
                    floor=a["floor"],
                ),
            )
            for key in ("demand", "flow", "transit", "market", "compete", "building", "rent"):
                assert http[key] == c["primary"][key], f"HTTP input bundle differs: {key}"
    input_path, output_path = directory / "cases.json", directory / "results.json"
    input_path.write_text(json.dumps(cases, ensure_ascii=False))
    subprocess.run(
        [
            "node",
            str(ROOT / ".local/scoring-build/ingest/score_candidates.js"),
            str(input_path),
            str(output_path),
        ],
        check=True,
    )
    results = json.loads(output_path.read_text())
    for c in results[6:]:
        building = next(a for a in c["result"]["axes"] if a["key"] == "building")
        assert building["normalized"] == (100 if c["candidate"]["floor"] == 3 else 90)
    summary = dict(
        reference_snapshot=references[800]["snapshot"],
        reference_version="0.1.2",
        inputs_schema_version="1.3",
        http_binary_reference_values=precision_rows,
        http_precision_mismatches=0,
        actual_cases=len(results),
        floor_checks=4,
        slider_invariance=True,
    )
    (directory / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n"
    )
    (directory / "v13-example.json").write_text(
        json.dumps(cases[6]["primary"], ensure_ascii=False, indent=2) + "\n"
    )
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
