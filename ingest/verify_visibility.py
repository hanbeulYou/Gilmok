"""Read-only local S2-3 inputs; shared TypeScript engine produces score and field report."""
import json
import subprocess
import time

from ingest.common import ROOT
from ingest.refresh import target_database
from ingest.verify_scoring import local_http


def main():
    directory = ROOT / '.local/validation/s2-3'
    directory.mkdir(parents=True, exist_ok=True)
    rpc = local_http()
    candidate = dict(lat=37.5025724504279, lng=127.057585738094, floor=3, address='역삼로460')
    start = time.perf_counter()
    scene = rpc('visibility_inputs', {k: candidate[k] for k in ('lng', 'lat')})
    http_ms = (time.perf_counter() - start) * 1000
    scene['floor'] = candidate['floor']
    primary = rpc('score_inputs', dict(**candidate, radius_m=800))
    school = rpc('score_inputs', dict(**candidate, radius_m=1000))
    reference = rpc('score_reference_distribution', dict(
        requested_preset_id='academy_v0', requested_radius_m=800))
    assert scene['candidate_building_id'] == primary['building']['id']
    with target_database('local') as db:
        db.execute('set transaction read only')
        start = time.perf_counter()
        direct = db.execute('select public.visibility_inputs(%s,%s)',
                            (candidate['lng'], candidate['lat'])).fetchone()[0]
        db_ms = (time.perf_counter() - start) * 1000
        assert direct == {k: v for k, v in scene.items() if k != 'floor'}
        boundary = db.execute('''select extensions.st_asbinary(extensions.st_collect(
            extensions.st_exteriorring((part).geom))) from (
            select extensions.st_dump(extensions.st_unaryunion(extensions.st_collect(geom)))
            part from public.admin_dongs) city''').fetchone()[0]
        inside, distance = db.execute('''with point as (
            select extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326) p)
            select exists(select 1 from public.admin_dongs d where extensions.st_covers(d.geom,p)),
            extensions.st_distance(extensions.st_setsrid(extensions.st_geomfromwkb(%s),4326)
            ::extensions.geography,p::extensions.geography) from point''',
            (candidate['lng'], candidate['lat'], boundary)).fetchone()
    data = dict(scene=scene, primary=primary, school=school, reference=reference,
                candidate=candidate, context=dict(inside_seoul=inside,
                                                   seoul_boundary_distance_m=distance))
    input_path = directory / 'input.json'
    input_path.write_text(json.dumps(data, ensure_ascii=False) + '\n')
    (directory / 'scene.json').write_text(json.dumps(scene, ensure_ascii=False) + '\n')
    subprocess.run(['node', str(ROOT / '.local/scoring-build/ingest/visibility_report.js'),
                    str(input_path), str(directory / 'result.json'),
                    str(directory / 'field-report.md')], check=True)
    (directory / 'input-summary.json').write_text(json.dumps(dict(
        http_ms=http_ms, db_roundtrip_ms=db_ms, http_db_scene_equal=True,
        reference_snapshot=reference['snapshot'], sources=scene['sources'],
        building_meta=scene['building_meta'], candidate=candidate), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
