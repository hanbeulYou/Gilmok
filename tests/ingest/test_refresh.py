import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import Mock

import pytest

from ingest.address_dispatch import EVENT_TYPE, drain, validate_event
from ingest.living_population import monthly_files
from ingest.refresh import execute_refresh, last_complete_month, month_end, month_window


def test_calendar_rollover_and_leap_year_do_not_shorten_windows():
    assert month_window("2026-01", 3) == ["2025-11", "2025-12", "2026-01"]
    assert len(month_window("2026-08", 24)) == 24
    assert last_complete_month(date(2026, 1, 1)) == "2025-12"
    assert month_end("2024-02") == date(2024, 2, 29)
    with pytest.raises(ValueError):
        month_window("2026-8", 3)


def test_monthly_catalog_uses_published_ids_and_ignores_daily_files():
    html = """<span title="250_LOCAL_RESD_202608.zip" onclick="downloadFile('9999')"></span>
        <span title="250_LOCAL_RESD_20260901.zip" onclick="downloadFile('260901')"></span>"""
    assert monthly_files(html) == {"2026-08": "9999"}
    with pytest.raises(ValueError):
        monthly_files(html + html.replace("9999", "8888"))


def test_dispatch_accepts_only_named_event_and_ignores_untrusted_payload():
    validate_event(
        "repository_dispatch",
        dict(
            action=EVENT_TYPE,
            client_payload=dict(address="not used", ref="malicious-ref", command="not executed"),
        ),
    )
    with pytest.raises(ValueError):
        validate_event("repository_dispatch", dict(action="other"))
    validate_event("schedule", {})


def test_drain_is_bounded_and_does_not_log_addresses(tmp_path):
    db = Mock()
    db.execute.return_value.fetchone.return_value = (3,)

    @contextmanager
    def factory():
        yield db

    processor = Mock(return_value={"address": "private address"})
    result = drain(factory, tmp_path, 2, processor)
    assert processor.call_count == 2
    assert result == dict(processed=2, pending=3, needs_review=3)
    assert "address" not in json.dumps(result)
    processor = Mock(return_value=None)
    assert drain(factory, tmp_path, 2, processor)["processed"] == 0
    assert processor.call_count == 1


@pytest.mark.parametrize("failure", ["download", "schema", "r2"])
def test_prepare_failure_never_promotes_or_vacuums(monkeypatch, failure):
    db = Mock()
    db.execute.return_value.fetchone.return_value = (True,)

    @contextmanager
    def factory():
        yield db

    promote = Mock()
    monkeypatch.setattr("ingest.refresh.promote", promote)
    maintenance = Mock()

    def prepare(db):
        raise RuntimeError(failure)

    r = execute_refresh("schools", "20260922T010000Z", factory, prepare, maintenance=maintenance)
    assert r["status"] == "refresh_failed" and r["committed"] is False
    promote.assert_not_called()
    maintenance.assert_not_called()


def test_vacuum_failure_reports_committed_new_snapshot(monkeypatch):
    db = Mock()
    db.execute.return_value.fetchone.return_value = (True,)

    @contextmanager
    def factory():
        yield db

    loader = Mock()

    def promotion(*args):
        loader()
        return True

    monkeypatch.setattr("ingest.refresh.promote", promotion)
    maintenance = Mock(side_effect=RuntimeError("no secrets leaked"))
    r = execute_refresh(
        "schools",
        "20260922T010000Z",
        factory,
        lambda db: (date(2026, 9, 22), {}, loader),
        maintenance=maintenance,
    )
    assert r["status"] == "maintenance_failed" and r["committed"] is True
    loader.assert_called_once()
    assert "no secrets leaked" not in json.dumps(r)


def test_remote_target_rejects_unactivated_or_wrong_project(monkeypatch):
    from ingest.refresh import target_database

    monkeypatch.setattr("ingest.refresh.dotenv_values", lambda _: {})
    monkeypatch.setenv("INGEST_REMOTE_ENABLED", "false")
    with pytest.raises(ValueError), target_database("remote"):
        pass
    monkeypatch.setenv("INGEST_REMOTE_ENABLED", "true")
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "a" * 20)
    monkeypatch.setenv(
        "SUPABASE_DB_URL",
        "postgresql://postgres@db." + "b" * 20 + ".supabase.co/postgres?sslmode=require",
    )
    with pytest.raises(ValueError), target_database("remote"):
        pass


def test_vacuum_runs_outside_transaction_on_separate_connection():
    from ingest.refresh import maintain

    db = Mock()

    @contextmanager
    def factory():
        yield db

    maintain(factory, ("population_age",))
    assert db.autocommit is True
    db.transaction.assert_not_called()
    statements = [str(call.args[0]) for call in db.execute.call_args_list]
    assert any("vacuum (analyze)" in s for s in statements)
    assert not any("full" in s.lower() for s in statements)
