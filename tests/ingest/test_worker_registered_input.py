from unittest.mock import MagicMock, Mock

import pytest

from ingest.building_on_demand import process_one
from ingest.common import RawStore, Settings
from tests.ingest.test_building_on_demand import ADDRESS, PNU, title


def queue_job(*, coordinates=True, source='registration'):
    return dict(address=ADDRESS, pnu=PNU if coordinates else None,
                lng=127.057585444512 if coordinates else None,
                lat=37.5025724246771 if coordinates else None,
                coordinate_source=source if coordinates else None)


def client():
    result = Mock(request_count=2)
    result.group.side_effect = [[title()], [dict(title(), flrGbCd='20', flrNo=3, area=173.68)]]
    return result


@pytest.mark.parametrize('source', ['registration', 'juso'])
def test_queue_coordinates_skip_all_geocoders_and_only_fetch_registers(
    monkeypatch, tmp_path, source
):
    monkeypatch.setattr('ingest.building_on_demand.claim', lambda db: queue_job(source=source))
    forbidden = Mock(side_effect=AssertionError('Coordinate API must not be called'))
    monkeypatch.setattr('ingest.juso.batch_request_address', forbidden)
    monkeypatch.setattr('ingest.geocode.request_vworld', forbidden)
    register = client()
    db = MagicMock(autocommit=True)
    result = process_one(db, tmp_path / 'journal', geocoder=forbidden,
                         client_factory=lambda directory: register,
                         store=RawStore(Settings(local_root=tmp_path / 'raw')))
    forbidden.assert_not_called()
    assert [call.args[0] for call in register.group.call_args_list] == [
        'getBrTitleInfo', 'getBrFlrOulnInfo']
    assert result['status'] == 'ready'
    assert result['pnu'] == PNU
    assert result['register_calls'] == 2
    sql = [call.args[0] for call in db.execute.call_args_list]
    assert any('insert into ingest_private.building_address_cache' in q for q in sql)
    assert any("status='done'" in q for q in sql)


def test_missing_coordinates_stay_on_hold_even_with_a_registered_key(monkeypatch, tmp_path):
    monkeypatch.setattr('ingest.building_on_demand.claim', lambda db: queue_job(coordinates=False))
    monkeypatch.setenv('JUSO_COORD_API_KEY', 'test-key-not-approval')
    monkeypatch.setenv('JUSO_COORD_ENABLED', 'false')
    forbidden = Mock(side_effect=AssertionError('No external API before rollout approval'))
    monkeypatch.setattr('ingest.juso.batch_request_address', forbidden)
    db = MagicMock(autocommit=True)
    result = process_one(db, tmp_path, client_factory=forbidden)
    assert result == dict(status='needs_coord', register_calls=0, coordinate_calls=0)
    forbidden.assert_not_called()
    assert db.execute.call_count == 1
    assert "status='needs_coord'" in db.execute.call_args.args[0]


def test_registered_pnu_address_mismatch_cannot_publish_or_query_floors(monkeypatch, tmp_path):
    monkeypatch.setattr('ingest.building_on_demand.claim', lambda db: queue_job())
    register = Mock(request_count=1)
    register.group.return_value = [dict(title(), newPlatPlc='서울특별시 강남구 역삼로 462')]
    db = MagicMock(autocommit=True)
    with pytest.raises(RuntimeError, match='Address worker failed'):
        process_one(db, tmp_path, client_factory=lambda directory: register)
    assert register.group.call_count == 1
    assert db.execute.call_count == 1
    assert "status='failed'" in db.execute.call_args.args[0]


def test_new_monthly_address_holds_without_coordinate_approval(monkeypatch, tmp_path):
    from ingest.geocode import resolve_one

    forbidden = Mock(side_effect=AssertionError('Monthly hold must not call a provider'))
    monkeypatch.setattr('ingest.juso.batch_request_address', forbidden)
    db = MagicMock(autocommit=True)
    db.execute.return_value.fetchone.return_value = None
    result = resolve_one(db, ADDRESS, key='search-key', coordinate_key='coordinate-key',
                         coordinates_enabled=False, budget=10, journal=tmp_path)
    assert result == 'needs_coord'
    forbidden.assert_not_called()
    statements = [call.args[0] for call in db.execute.call_args_list]
    assert any("'needs_coord'" in q and 'insert into' in q for q in statements)
    assert not any('insert into public.geocode_cache' in q for q in statements)
    assert list(tmp_path.iterdir()) == []
