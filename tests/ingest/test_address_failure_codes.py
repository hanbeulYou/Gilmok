from ingest.building_on_demand import operational_error_code
from ingest.geocode import GeocodeStopped


def test_provider_failures_use_fixed_private_codes_without_response_text():
    assert operational_error_code(GeocodeStopped(
        'Juso transport failed; no automatic retry')) == 'juso_transport_failed'
    assert operational_error_code(GeocodeStopped(
        'Juso business error; not an address miss')) == 'juso_business_error'
    assert operational_error_code(GeocodeStopped(
        'Vworld coordinate request failed')) == 'vworld_coordinate_failed'
    assert operational_error_code(GeocodeStopped('unknown secret-bearing URL')) == 'geocode_stopped'
    assert operational_error_code(ValueError('private input')) == 'ValueError'
