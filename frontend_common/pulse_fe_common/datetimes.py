"""Formattazione delle date-ora per i frontend Pulse.

Le API restituiscono timestamp in UTC (ISO-8601, con 'Z' o offset esplicito).
Le dashboard devono mostrarli nel fuso orario configurato. Questo modulo offre
un helper puro e testabile in isolamento (nessuna dipendenza da Flask):

    format_datetime("2026-07-16T12:00:00Z", "Europe/Rome")  # -> "16/07/2026 14:00:00"

Regole:
  - valore vuoto/None -> segnaposto "—";
  - stringa non interpretabile -> ritorna il valore originale invariato;
  - datetime/stringa naive -> interpretata come UTC;
  - fuso orario sconosciuto -> ripiego su DEFAULT_TIMEZONE, poi su UTC.
"""
from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

#: Fuso orario di default (IANA) quando non configurato/non valido.
DEFAULT_TIMEZONE = "Europe/Rome"
#: Formato di default: 24h, giorno/mese/anno.
DEFAULT_FORMAT = "%d/%m/%Y %H:%M:%S"
#: Segnaposto per valori assenti.
PLACEHOLDER = "—"


def _parse_iso(text: str) -> datetime | None:
    """Interpreta una stringa ISO-8601 (con 'Z', offset o naive). None se fallisce.

    Chiamata solo da ``format_datetime`` con testo gia' non vuoto.
    """
    s = text.strip()
    candidate = (s[:-1] + "+00:00") if s[-1] in ("Z", "z") else s
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def _zone(tz_name: str):
    """ZoneInfo per tz_name, con ripiego su DEFAULT_TIMEZONE e infine su UTC."""
    for name in (tz_name, DEFAULT_TIMEZONE):
        try:
            return ZoneInfo(name)
        except Exception:  # tz sconosciuto / db assente
            continue
    return timezone.utc


def format_datetime(
    value,
    tz_name: str = DEFAULT_TIMEZONE,
    fmt: str = DEFAULT_FORMAT,
) -> str:
    """Formatta ``value`` (ISO-8601 UTC o datetime) nel fuso ``tz_name``.

    Vedi il docstring del modulo per le regole complete.
    """
    if value is None:
        return PLACEHOLDER
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value)
        if not text.strip():
            return PLACEHOLDER
        parsed = _parse_iso(text)
        if parsed is None:
            return value if isinstance(value, str) else text
        dt = parsed
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_zone(tz_name)).strftime(fmt)
