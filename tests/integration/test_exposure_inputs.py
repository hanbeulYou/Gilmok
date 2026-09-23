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
