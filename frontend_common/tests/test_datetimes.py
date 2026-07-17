"""Test dell'helper di formattazione date-ora (fuso orario)."""
from datetime import datetime, timezone

from pulse_fe_common import format_datetime
from pulse_fe_common.datetimes import DEFAULT_TIMEZONE, PLACEHOLDER


def test_utc_to_rome_summer():
    # 12:00 UTC in estate (DST) -> 14:00 Europe/Rome (UTC+2).
    assert format_datetime("2026-07-16T12:00:00Z", "Europe/Rome") == "16/07/2026 14:00:00"


def test_utc_to_rome_winter():
    # 12:00 UTC in inverno -> 13:00 Europe/Rome (UTC+1).
    assert format_datetime("2026-01-16T12:00:00Z", "Europe/Rome") == "16/01/2026 13:00:00"


def test_offset_input_is_respected():
    # Input gia' con offset: convertito correttamente a Rome.
    assert format_datetime("2026-07-16T12:00:00+00:00", "Europe/Rome") == "16/07/2026 14:00:00"


def test_utc_zone_identity():
    assert format_datetime("2026-07-16T12:00:00Z", "UTC") == "16/07/2026 12:00:00"


def test_naive_string_assumed_utc():
    assert format_datetime("2026-07-16T12:00:00", "Europe/Rome") == "16/07/2026 14:00:00"


def test_space_separated_and_date_only():
    assert format_datetime("2026-07-16 12:00:00", "UTC") == "16/07/2026 12:00:00"
    assert format_datetime("2026-07-16", "UTC") == "16/07/2026 00:00:00"


def test_datetime_aware_input():
    dt = datetime(2026, 7, 16, 12, 0, tzinfo=timezone.utc)
    assert format_datetime(dt, "Europe/Rome") == "16/07/2026 14:00:00"


def test_datetime_naive_input_assumed_utc():
    dt = datetime(2026, 7, 16, 12, 0)
    assert format_datetime(dt, "Europe/Rome") == "16/07/2026 14:00:00"


def test_none_and_empty_return_placeholder():
    assert format_datetime(None) == PLACEHOLDER
    assert format_datetime("") == PLACEHOLDER
    assert format_datetime("   ") == PLACEHOLDER


def test_unparsable_returns_original():
    assert format_datetime("non-una-data", "Europe/Rome") == "non-una-data"


def test_non_string_unparsable_returns_str():
    # Un intero non e' una data ISO: ritorna la sua rappresentazione testuale.
    assert format_datetime(12345, "UTC") == "12345"


def test_invalid_timezone_falls_back_to_default():
    # tz sconosciuto -> ripiego su DEFAULT_TIMEZONE (Europe/Rome).
    assert DEFAULT_TIMEZONE == "Europe/Rome"
    assert format_datetime("2026-07-16T12:00:00Z", "Mars/Olympus") == "16/07/2026 14:00:00"


def test_custom_format():
    assert format_datetime("2026-07-16T12:00:00Z", "UTC", "%Y-%m-%d %H:%M") == "2026-07-16 12:00"


def test_zone_db_unavailable_falls_back_to_utc(monkeypatch):
    # Se anche il default non e' risolvibile (db tz assente), si usa UTC.
    import pulse_fe_common.datetimes as dtmod

    def _boom(_name):
        raise KeyError("no tz db")

    monkeypatch.setattr(dtmod, "ZoneInfo", _boom)
    assert format_datetime("2026-07-16T12:00:00Z", "Europe/Rome") == "16/07/2026 12:00:00"
