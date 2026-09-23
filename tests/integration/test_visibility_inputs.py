import json

import psycopg
import pytest

from tests.integration.test_buildings_database import frames, load


@pytest.mark.parametrize('role', ['anon', 'authenticated'])
def test_visibility_scene_reuses_building_contract_and_projects_metres(db, role):
    load(db, frames(db))
    lng, lat = db.execute('''select extensions.st_x(p),extensions.st_y(p) from
        (select extensions.st_pointonsurface(geom) p from public.buildings
        where id='fixture:0') q''').fetchone()
    before = db.execute('select public.buildings_in_radius(127.062,37.496,1000)').fetchone()[0]
    with db.transaction():
        db.execute(f'set local role {role}')
        scene = db.execute('select public.visibility_inputs(%s,%s)', (lng, lat)).fetchone()[0]
    assert scene['srid'] == 5186
    assert scene['radius_m'] == 1000
    assert scene['candidate_building_id'] == 'fixture:0'
    assert len(scene['buildings']) == 4
    assert {b['id'] for b in scene['buildings']} == {f['id'] for f in before['features']}
    for b in scene['buildings']:
        props = next(f['properties'] for f in before['features'] if f['id'] == b['id'])
        assert b['height_m'] == props['occlusion_height_m']
        assert b['source'] == props['source']
        geometry = json.dumps({'type': 'MultiPolygon', 'coordinates': b['polygons']})
        delta = db.execute('''select extensions.st_hausdorffdistance(
            extensions.st_setsrid(extensions.st_geomfromgeojson(%s),5186),
            extensions.st_transform(geom,5186)) from public.buildings where id=%s''',
            (geometry, b['id'])).fetchone()[0]
        assert delta < 1e-6
    after = db.execute('select public.buildings_in_radius(127.062,37.496,1000)').fetchone()[0]
    assert before == after
    with pytest.raises(psycopg.errors.InsufficientPrivilege), db.transaction():
        db.execute(f'set local role {role}')
        db.execute('delete from public.buildings')


def test_visibility_anchor_selection_and_candidate_absence(db):
    load(db, frames(db))
    db.execute('delete from public.transit_boardings')
    db.execute('delete from public.transit_stops')
    db.execute('delete from public.schools')
    for stop_id in ['z', 'a']:
        db.execute('''insert into public.transit_stops(id,type,name,line,geom,source,source_version)
            values(%s,'subway','same point','line',extensions.st_setsrid(
            extensions.st_makepoint(127.062,37.496),4326),'fixture','fixture')''', (stop_id,))
    db.execute('''insert into public.schools(id,name,level,school_type,address,geom,
        geocode_failed,source,source_version) values
        ('school','학교','elem','fixture','fixture',extensions.st_setsrid(
        extensions.st_makepoint(127.062,37.496),4326),false,'fixture','fixture'),
        ('unlocated','학교2','mid','fixture','fixture',null,true,'fixture','fixture')''')
    s = db.execute('select public.visibility_inputs(127.062,37.496)').fetchone()[0]
    assert s['station']['id'] == 'a'
    assert s['station']['distance_m'] == 0
    assert s['station']['point'] == s['candidate']
    assert [v['id'] for v in s['schools']] == ['school']
    distant = db.execute('select public.visibility_inputs(126.9,37.6)').fetchone()[0]
    assert distant['candidate_building_id'] is None
    assert distant['containing_building_count'] == 0
    assert distant['station'] is None
    assert distant['schools'] == []


@pytest.mark.parametrize('coords', [(None, 37.5), (127, None), (0, 0), (float('nan'), 37.5)])
def test_visibility_invalid_coordinates(db, coords):
    with pytest.raises(psycopg.errors.RaiseException), db.transaction():
        db.execute('select public.visibility_inputs(%s,%s)', coords)
