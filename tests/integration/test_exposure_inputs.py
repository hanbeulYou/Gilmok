import pytest

from tests.integration.test_buildings_database import frames, load


@pytest.mark.parametrize('role', ['anon', 'authenticated'])
def test_exposure_all_stations_within_1km_preserves_old_scene(db, role):
    load(db, frames(db))
    db.execute('delete from public.transit_boardings')
    db.execute('delete from public.transit_stops')
    for stop_id, distance in [('a', 500), ('b', 500), ('edge_in', 999.99), ('edge_out', 1000.01)]:
        db.execute('''insert into public.transit_stops(id,type,name,line,geom,source,source_version)
            values(%s,'subway','환승역',%s,extensions.st_project(extensions.st_setsrid(
              extensions.st_makepoint(127.062,37.496),4326)::extensions.geography,%s,0)
              ::extensions.geometry,'fixture','fixture')''', (stop_id, stop_id, distance))
    before = db.execute('select public.visibility_inputs(127.062,37.496)').fetchone()[0]
    with db.transaction():
        db.execute(f'set local role {role}')
        actual = db.execute('select public.exposure_inputs(127.062,37.496)').fetchone()[0]
    assert actual['schema_version'] == '0.2'
    assert 'station' not in actual
    assert [s['id'] for s in actual['stations']] == ['a', 'b', 'edge_in']
    assert all(s['distance_m'] <= 1000 for s in actual['stations'])
    assert actual['buildings'] == before['buildings']
    assert actual['schools'] == before['schools']
    assert actual['candidate_building_id'] == before['candidate_building_id']
    assert db.execute('select public.visibility_inputs(127.062,37.496)').fetchone()[0] == before
    db.execute('reset role')
    db.execute('delete from public.transit_stops')
    empty = db.execute('select public.exposure_inputs(127.062,37.496)').fetchone()[0]
    assert empty['stations'] == []


@pytest.mark.parametrize('role', ['anon', 'authenticated'])
def test_v021_1200m_stations_and_1230m_buildings_preserve_v02(db, role):
    load(db, frames(db))
    db.execute('delete from public.transit_boardings')
    db.execute('delete from public.transit_stops')
    for stop_id, distance in [('a', 500), ('b', 500), ('daechi', 1033.14),
                              ('edge_in', 1199.99), ('edge_out', 1200.01)]:
        db.execute('''insert into public.transit_stops(id,type,name,line,geom,source,source_version)
            values(%s,'subway','역',%s,extensions.st_project(extensions.st_setsrid(
              extensions.st_makepoint(127.062,37.496),4326)::extensions.geography,%s,0)
              ::extensions.geometry,'fixture','fixture')''', (stop_id, stop_id, distance))
    for building_id, distance in [('margin', 1220), ('outside', 1240)]:
        db.execute('''insert into public.buildings(id,source_id,pnu,source,source_version,
            register_link_status,geom,geometry_repaired,height_source,height_estimated)
            values(%s,%s,'1168010600109120013','gis_buildings_shp','fixture','missing_source_pk',
            extensions.st_multi(extensions.st_transform(extensions.st_buffer(extensions.st_transform(
              extensions.st_project(extensions.st_setsrid(extensions.st_makepoint(127.062,37.496),4326)
                ::extensions.geography,%s,0)::extensions.geometry,5186),1),4326)),false,'unknown',false)
            ''', (building_id, building_id, distance))
    old = db.execute('select public.exposure_inputs(127.062,37.496)').fetchone()[0]
    with db.transaction():
        db.execute(f'set local role {role}')
        actual = db.execute('select public.exposure_inputs_v021(127.062,37.496)').fetchone()[0]
    assert actual['schema_version'] == '0.2.1'
    assert actual['srid'] == 5186
    assert (actual['radius_m'], actual['station_radius_m'], actual['school_radius_m']) == (
        1230, 1200, 1000)
    assert [s['id'] for s in actual['stations']] == ['a', 'b', 'daechi', 'edge_in']
    assert actual['schools'] == old['schools']
    assert actual['candidate_building_id'] == old['candidate_building_id']
    ids = {b['id'] for b in actual['buildings']}
    assert 'margin' in ids and 'outside' not in ids
    assert 'margin' not in {b['id'] for b in old['buildings']}
    rpc = db.execute('select public.buildings_in_radius(127.062,37.496,1230)').fetchone()[0]
    assert ids == {f['id'] for f in rpc['features']}
    assert db.execute('select public.exposure_inputs(127.062,37.496)').fetchone()[0] == old
    db.execute('reset role')
    db.execute('delete from public.transit_stops')
    empty = db.execute('select public.exposure_inputs_v021(127.062,37.496)').fetchone()[0]
    assert empty['stations'] == []
