"""Independent PostGIS intersection oracle for the actual TypeScript rays."""
import json

from ingest.common import ROOT
from ingest.refresh import target_database


def main():
    directory = ROOT / '.local/validation/s2-3'
    data = json.loads((directory / 'input.json').read_text())
    result = json.loads((directory / 'result.json').read_text())['result']
    scene = data['scene']
    samples = [dict(id=s['id'], x=s['point'][0], y=s['point'][1],
                    tx=(s['target'] or s['point'])[0], ty=(s['target'] or s['point'])[1])
               for s in result['samples']]
    with target_database('local') as db:
        db.execute('set transaction read only')
        rows = db.execute('''with buildings as materialized (
            select id,render_height_m h,extensions.st_transform(geom,5186) g
            from public.buildings where id=any(%s)
        ), rays as materialized (
            select id,extensions.st_setsrid(extensions.st_makepoint(x,y),5186) eye,
            extensions.st_setsrid(extensions.st_makepoint(tx,ty),5186) target,
            extensions.st_setsrid(extensions.st_makeline(extensions.st_makepoint(x,y),
                extensions.st_makepoint(tx,ty)),5186) ray
            from jsonb_to_recordset(%s::jsonb) as s(
                id text,x double precision,y double precision,
                tx double precision,ty double precision)
        ), intersections as materialized (
            select r.id,r.ray,b.h,(extensions.st_dump(
                extensions.st_intersection(r.ray,b.g))).geom part
            from rays r join buildings b on b.g operator(extensions.&&) r.ray
            where b.id <> %s and extensions.st_intersects(r.ray,b.g)
                and not exists(select 1 from buildings e where extensions.st_covers(e.g,r.eye))
        ), endpoints as (
            select *,case when extensions.st_geometrytype(part)='ST_Point' then part
                else extensions.st_startpoint(part) end a,
                case when extensions.st_geometrytype(part)='ST_Point' then part
                else extensions.st_endpoint(part) end b from intersections
        ), heights as (
            select id,h,1.5+(%s-1.5)*extensions.st_linelocatepoint(ray,a) za,
                1.5+(%s-1.5)*extensions.st_linelocatepoint(ray,b) zb from endpoints
        ) select r.id,
            case when exists(select 1 from buildings b where extensions.st_covers(b.g,r.eye))
                then 'excluded'
                when exists(select 1 from heights z where z.id=r.id
                    and least(za,zb)<=h and greatest(za,zb)>=0) then 'blocked'
                else 'visible' end status,
            case when extensions.st_equals(r.eye,r.target) then null else
                extensions.st_distance(r.target,extensions.st_closestpoint(
                extensions.st_boundary((select g from buildings where id=%s)),r.eye))
                end target_error_m
            from rays r order by id''', (
            [b['id'] for b in scene['buildings']], json.dumps(samples),
            scene['candidate_building_id'], result['evidence']['values']['target_height_m'],
            result['evidence']['values']['target_height_m'], scene['candidate_building_id'],
        )).fetchall()
    expected = {s['id']: s['status'] for s in result['samples']}
    errors = [(i, status, expected[i]) for i, status, _ in rows if status != expected[i]]
    target_errors = [error for _, _, error in rows if error is not None]
    assert not errors, errors
    assert max(target_errors) < 1e-6
    proof = dict(samples=len(rows), classification_mismatches=len(errors),
                 max_target_error_m=max(target_errors))
    (directory / 'geometry-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
