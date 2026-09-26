"""S2-4 frozen-preset validation inputs; reuse saved exact-address responses, local DB only."""
import hashlib
import json
import random

from ingest.building_on_demand import address_parcel
from ingest.common import ROOT
from ingest.refresh import target_database
from ingest.score_reference import fingerprint, source_state
from ingest.verify_scoring import local_http

DIRECTORY = ROOT / '.local/validation/s2-4-20260926'
ADDRESSES = [('a', '역삼로 460', 3), ('b', '도곡로 409', 2), ('c', '역삼로 546', 3)]
SEED = 20260926


def main():
    DIRECTORY.mkdir(parents=True, exist_ok=True)
    rpc = local_http()
    reference = rpc('score_reference_distribution', dict(
        requested_preset_id='academy_v0', requested_radius_m=800))
    cases = []
    with target_database('local') as db:
        db.execute('set transaction isolation level repeatable read read only')
        assert reference['source_fingerprint'] == fingerprint(source_state(db))
        assert reference['preset']['version'] == '0.1.2'
        stored = db.cursor(binary=True).execute('''select axis_key,raw_value
            from public.score_reference where preset_id='academy_v0' and radius_m=800
            and raw_value is not null order by axis_key,raw_value''').fetchall()
        assert stored == [(d['key'], v) for d in reference['distributions'] for v in d['values']]
        boundary = db.execute('''select extensions.st_asbinary(extensions.st_collect(
            extensions.st_exteriorring((part).geom))) from (select extensions.st_dump(
            extensions.st_unaryunion(extensions.st_collect(geom))) part
            from public.admin_dongs) city''').fetchone()[0]
        names = dict(db.execute('select code8,name from public.legal_dongs').fetchall())

        def add(key, lat, lng, floor, address=None, resolution=None):
            candidate = dict(lat=lat, lng=lng, floor=floor, address=address,
                             exclusive_area_m2=None, deposit_krw=None,
                             monthly_rent_krw=None, maintenance_krw=None)
            primary = db.execute('select public.score_inputs(%s,%s,800,%s,%s)',
                                 (lat, lng, floor, address)).fetchone()[0]
            school = db.execute('select public.score_inputs(%s,%s,1000,%s,%s)',
                                (lat, lng, floor, address)).fetchone()[0]
            scene = rpc('exposure_inputs_v021', dict(lng=lng, lat=lat))
            assert scene == db.execute('select public.exposure_inputs_v021(%s,%s)',
                                       (lng, lat)).fetchone()[0]
            scene['floor'] = floor
            for radius, expected in [(800, primary), (1000, school)]:
                actual = rpc('score_inputs', dict(lat=lat, lng=lng, radius_m=radius,
                                                  floor=floor, address=address))
                for k in ('demand', 'flow', 'transit', 'market', 'compete', 'building', 'rent'):
                    assert actual[k] == expected[k], (key, radius, k)
            inside, distance = db.execute('''with point as (
                select extensions.st_setsrid(extensions.st_makepoint(%s,%s),4326) p)
                select exists(select 1 from public.admin_dongs d
                  where extensions.st_covers(d.geom,p)),
                extensions.st_distance(extensions.st_setsrid(extensions.st_geomfromwkb(%s),4326)
                ::extensions.geography,p::extensions.geography) from point''',
                (lng, lat, boundary)).fetchone()
            assert inside
            if resolution:
                assert primary['building']['pnu'] == resolution['pnu']
                assert primary['building']['id'] == resolution['building_id']
                assert primary['building']['location_basis'] == 'footprint'
                assert scene['candidate_building_id'] == resolution['building_id']
            cases.append(dict(key=key, candidate=candidate, primary=primary, school=school,
                              scene=scene, address_resolution=resolution, context=dict(
                                  inside_seoul=inside, seoul_boundary_distance_m=distance,
                                  legal_dong_names=names)))

        for key, short, floor in ADDRESSES:
            address = '서울특별시 강남구 ' + short
            path = ROOT / '.local/validation/pr4/geocode-responses' / (
                hashlib.sha256(address.encode()).hexdigest() + '.json')
            saved = json.loads(path.read_text())
            assert saved['address'] == address
            parcel = address_parcel(saved['response'], address)
            assert parcel['status'] == 'ready'
            shapes = db.execute('''select b.id,b.register_pk,r.name,
                extensions.st_covers(b.geom,extensions.st_setsrid(
                  extensions.st_makepoint(%s,%s),4326)),
                extensions.st_y(extensions.st_transform(extensions.st_centroid(
                  extensions.st_transform(b.geom,5186)),4326)),
                extensions.st_x(extensions.st_transform(extensions.st_centroid(
                  extensions.st_transform(b.geom,5186)),4326))
                from public.buildings b left join public.building_registers r using(register_pk)
                where b.pnu=%s order by b.id''',
                (parcel['lng'], parcel['lat'], parcel['pnu'])).fetchall()
            assert len(shapes) == 1 and shapes[0][3], (address, shapes)
            row = shapes[0]
            document = saved['response']['documents'][0]
            resolution = dict(pnu=parcel['pnu'], building_id=row[0], register_pk=row[1],
                              register_name=row[2], covers_geocoded_point=row[3],
                              centroid_lat=row[4], centroid_lng=row[5],
                              parcel_address=document['address']['address_name'],
                              geocoder_building_name=document['road_address']['building_name'],
                              response_path=str(path.relative_to(ROOT)),
                              response_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
            add(key, parcel['lat'], parcel['lng'], floor, address, resolution)

        cells = db.execute('''select cell_id,extensions.st_y(p),extensions.st_x(p) from
            (select cell_id,extensions.st_transform(extensions.st_centroid(
                extensions.st_transform(geom,5179)),4326) p
              from public.population_cells where resolution_m=250) g
            where exists(select 1 from public.admin_dongs d where extensions.st_covers(d.geom,p))
            order by cell_id''').fetchall()
        selected = random.Random(SEED).sample(cells, 5)
        for cell_id, lat, lng in selected:
            add(cell_id, lat, lng, 2)
        metadata = dict(seed=SEED, population_size=len(cells), random_cells=selected,
                        population_sha256=hashlib.sha256(json.dumps(cells).encode()).hexdigest(),
                        sampling='Python random.Random(seed).sample(sorted inside-Seoul cells, 5)',
                        reference_snapshot=reference['snapshot'],
                        binary_values_verified=len(stored),
                        preset_version='0.2.1', reference_version='0.1.2',
                        prior_order=['b', 'a', 'c'])
    (DIRECTORY / 'inputs.json').write_text(json.dumps(dict(
        metadata=metadata, reference=reference, cases=cases), ensure_ascii=False) + '\n')
    # Native browser harness consumes exactly the same scenes as the Node verifier.
    (DIRECTORY / 'worker-harness.html').write_text('''<!doctype html><meta charset="utf-8">
<script type="module">
import {createVisibilityClient} from '/.local/visibility-browser/lib/visibility/client.js';
const worker=new Worker('/.local/visibility-browser/workers/visibility.worker.js',{type:'module'});
const client=createVisibilityClient(worker);
globalThis.verification=(async()=>{
 const {cases}=await (await fetch('./inputs.json')).json(); const runs=[];
 for(const c of cases){const start=performance.now();
   const r=await client.request(c.scene).response;
   if('error' in r) throw new Error(r.error);
   runs.push({key:c.key,result:r.result,computeMs:r.computeMs,roundtripMs:performance.now()-start});}
 return {runs,userAgent:navigator.userAgent};
})().finally(()=>{client.dispose();worker.terminate();});
</script>''')
    print(json.dumps(metadata, ensure_ascii=False))


if __name__ == '__main__':
    main()
