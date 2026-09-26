"""Independent PostGIS intersection oracle for the actual TypeScript rays."""
import json

from ingest.common import ROOT
from ingest.refresh import target_database


def main():
    directory = ROOT / '.local/validation/exposure-v021'
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
        pushed = []
        for s in result['samples']:
            ox, oy = s['original_point']
            dx, dy = ox - scene['candidate'][0], oy - scene['candidate'][1]
            distance = (dx * dx + dy * dy) ** 0.5
            if not s['moved_m'] and s['status'] != 'excluded':
                continue
            assert distance > 0
            x, y = s['point']
            if s['status'] == 'excluded':
                x, y = ox + dx / distance * 30, oy + dy / distance * 30
            else:
                assert 0 < s['moved_m'] <= 30 + 1e-8
                assert abs((x - ox) * dy - (y - oy) * dx) / distance < 1e-6
                assert (x - ox) * dx + (y - oy) * dy > 0
            pushed.append(dict(id=s['id'], ox=ox, oy=oy, x=x, y=y))
        push_rows = db.execute('''with buildings as materialized (
            select extensions.st_transform(geom,5186) g
            from public.buildings where id=any(%s)
        ), paths as (
            select id,extensions.st_setsrid(extensions.st_makeline(
                extensions.st_makepoint(ox,oy),extensions.st_makepoint(x,y)),5186) line
            from jsonb_to_recordset(%s::jsonb) as s(id text,ox double precision,
                oy double precision,x double precision,y double precision)
        ) select p.id,extensions.st_length(extensions.st_difference(p.line,
            (select extensions.st_unaryunion(extensions.st_collect(b.g)) from buildings b
                where b.g operator(extensions.&&) p.line))) outside_m from paths p''',
            ([b['id'] for b in scene['buildings']], json.dumps(pushed))).fetchall()
        expected = {s['id']: s['status'] for s in result['samples']}
        errors = [(i, status, expected[i]) for i, status, _ in rows if status != expected[i]]
        target_errors = [error for _, _, error in rows if error is not None]
        assert not errors, errors
        assert max(target_errors) < 1e-6
        for sample_id, outside_m in push_rows:
            status = expected[sample_id]
            # A selected point is within 1mm of the first exit; an excluded path has no exit.
            assert outside_m <= (1e-6 if status == 'excluded' else .001001), (sample_id, outside_m)
            if status != 'excluded':
                assert outside_m > 0, sample_id
        statuses = {sample_id: status for sample_id, status, _ in rows}
        ring = [s for s in result['samples'] if s['group'] == 'ring']
        visible_weight = sum(100 / s['radius_m'] for s in ring if statuses[s['id']] == 'visible')
        valid_weight = sum(100 / s['radius_m'] for s in ring if statuses[s['id']] != 'excluded')
        assert abs(visible_weight / valid_weight - result['visible_ratio']) < 1e-12
        anchors = [dict(id=a['id'], group=g, x=a['point'][0], y=a['point'][1])
                   for g, key in [('station', 'stations'), ('school', 'schools')]
                   for a in scene[key]]
        approach_samples = [dict(anchor_id=s['anchor_id'], group=s['group'],
                                 x=s['point'][0], y=s['point'][1]) for s in result['samples']
                            if s['group'] != 'ring' and statuses[s['id']] == 'visible']
        distances = db.execute('''with anchors as (
            select id,g,extensions.st_makepoint(x,y) p from jsonb_to_recordset(%s::jsonb)
              a(id text,g text,x double precision,y double precision)
          ), samples as (
            select anchor_id,g,extensions.st_makepoint(x,y) p from jsonb_to_recordset(%s::jsonb)
              s(anchor_id text,g text,x double precision,y double precision)
          ), candidate as (select extensions.st_makepoint(%s,%s) p)
          select a.id,a.g,min(extensions.st_distance(a.p,s.p))
          from anchors a cross join candidate c left join samples s
          on a.id=s.anchor_id and a.g=s.g and extensions.st_distance(c.p,s.p)
            <=extensions.st_distance(c.p,a.p)+1e-6 group by a.id,a.g''',
            (json.dumps([{**a, 'g': a['group']} for a in anchors]),
             json.dumps([{**s, 'g': s['group']} for s in approach_samples]),
             *scene['candidate'])).fetchall()
        reported = {(a['anchor_id'], a['group']): a['first_exposure_distance_m']
                    for a in result['evidence']['values']['approach_distances']}
        for anchor_id, group, distance in distances:
            actual = reported[(anchor_id, group)]
            assert (actual is None) == (distance is None)
            if distance is not None:
                assert abs(actual - distance) < 1e-6
    proof = dict(samples=len(rows), classification_mismatches=len(errors),
                 max_target_error_m=max(target_errors), push_paths_verified=len(push_rows),
            max_open_distance_before_selected_m=max(v for _, v in push_rows),
            ring_only_visible_ratio=visible_weight / valid_weight,
            approach_distances_verified=len(distances))
    (directory / 'geometry-proof.json').write_text(json.dumps(proof, indent=2) + '\n')
    print(json.dumps(proof))


if __name__ == '__main__':
    main()
