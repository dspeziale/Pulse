"""Test della pagina Compendio sistema (P-nuova) e dell'export PDF.

Backend simulato (FakeApiClient). Verificano: rendering della pagina col preset
default "Oggi", KPI e tabella per-check; risoluzione del periodo; la rotta PDF
restituisce Content-Type application/pdf con corpo non vuoto (header %PDF); e il
builder PDF (report_pdf) con tutti i rami di formattazione/impaginazione.
"""
from __future__ import annotations

import datetime as _dt

import report_pdf
from views import report as report_view
from conftest import ApiError

# --------------------------------------------------------------------------- #
# Dati di comodo
# --------------------------------------------------------------------------- #
_SYS = {
    "id": "00000000-0000-0000-0000-0000000000aa",
    "system_id": "crm-prod",
    "system_name": "CRM Produzione",
    "kind": "http",
    "probe_id": "11111111-1111-1111-1111-111111111111",
}
_CHECKS = {
    "items": [
        {"check_id": "home", "check_name": "Home page",
         "last_status": "ok", "last_seen_at": "2026-07-17T08:00:00Z"},
        {"check_id": "api", "check_name": "API",
         "last_status": "warn", "last_seen_at": "2026-07-17T08:01:00Z"},
    ],
    "total": 2,
}
_AGGS = {
    "aggregations": {
        "uptime": 99.5, "count": 120, "avg_response_ms": 123.4,
        "min_response_ms": 40.0, "max_response_ms": 512.0,
    },
    "items": [], "total": 120,
}
_COUNT = {"aggregations": {"count": 7}, "items": [], "total": 7}
_HB = {"items": [
    {"@timestamp": "2026-07-17T08:00:00Z", "response_ms": 100},
    {"@timestamp": "2026-07-17T08:05:00Z", "response_ms": 220},
    {"@timestamp": "2026-07-17T08:10:00Z", "response_ms": 150},
], "total": 3}
_ALARMS = {"items": [
    {"id": "a1", "status": "resolved", "opened_at": "2026-07-17T08:02:00Z",
     "acknowledged_at": "2026-07-17T08:03:00Z",
     "resolved_at": "2026-07-17T08:20:00Z"},
], "total": 1}


def _wire(fake):
    fake.set("GET", "/systems/sys1", _SYS)
    fake.set("GET", "/systems/sys1/checks", _CHECKS)
    fake.set("POST", "/probes/11111111-1111-1111-1111-111111111111/query", _AGGS)
    fake.set("GET", "/probes/11111111-1111-1111-1111-111111111111/heartbeats", _HB)
    fake.set("GET", "/alarms", _ALARMS)
    return fake


# --------------------------------------------------------------------------- #
# Pagina Compendio
# --------------------------------------------------------------------------- #
def test_compendio_renders_kpi_and_per_check(client, login, fake):
    _wire(fake)
    login(permissions=["systems.read", "probes.read", "workflows.read"])
    r = client.get("/systems/sys1/report")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Compendio" in body
    assert "CRM Produzione" in body
    # KPI e tabella per-check presenti
    assert "Uptime" in body
    assert "99.5%" in body
    assert "Home page" in body and "API" in body
    # grafico response_ms incluso (canvas)
    assert 'id="rt"' in body


def test_default_preset_is_today(client, login, fake):
    _wire(fake)
    login(permissions=["systems.read"])
    r = client.get("/systems/sys1/report")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    # l'opzione "Oggi" e' selezionata di default
    assert '<option value="today" selected>' in body


def test_custom_period_and_pdf_link(client, login, fake):
    _wire(fake)
    login(permissions=["systems.read"])
    r = client.get("/systems/sys1/report",
                   query_string={"preset": "custom",
                                 "from": "2026-07-01T00:00",
                                 "to": "2026-07-02T00:00"})
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert '<option value="custom" selected>' in body
    # il link PDF propaga il periodo personalizzato
    assert "report.pdf" in body
    assert "preset=custom" in body


def test_invalid_preset_falls_back_to_today(client, login, fake):
    _wire(fake)
    login(permissions=["systems.read"])
    # preset sconosciuto -> ripiego su "Oggi"
    r = client.get("/systems/sys1/report", query_string={"preset": "zzz"})
    assert r.status_code == 200
    assert '<option value="today" selected>' in r.get_data(as_text=True)
    # custom senza date valide -> ripiego su "Oggi"
    r2 = client.get("/systems/sys1/report", query_string={"preset": "custom"})
    assert r2.status_code == 200
    assert '<option value="today" selected>' in r2.get_data(as_text=True)


def test_compendio_no_probe_is_empty(client, login, fake):
    # Sistema senza probe/system_id: il compendio si rende senza metriche.
    fake.set("GET", "/systems/sys1", {"id": "x", "system_name": "Vuoto"})
    fake.set("GET", "/systems/sys1/checks", {"items": [], "total": 0})
    login(permissions=["systems.read"])
    r = client.get("/systems/sys1/report")
    assert r.status_code == 200
    body = r.get_data(as_text=True)
    assert "Nessun check scoperto" in body
    assert "Nessun campione nel periodo." in body


def test_compendio_alarms_permission_fallback(client, login, fake):
    _wire(fake)
    # /alarms nega (403): il resto del compendio deve comunque rendersi.
    fake.set("GET", "/alarms", ApiError(403, "forbidden", "Permesso negato"))
    login(permissions=["systems.read"])
    r = client.get("/systems/sys1/report")
    assert r.status_code == 200
    assert "Nessun allarme nel periodo" in r.get_data(as_text=True)


def test_compendio_requires_permission(client, login, fake):
    _wire(fake)
    login(permissions=["dashboard.read"])  # manca systems.read
    r = client.get("/systems/sys1/report")
    assert r.status_code == 403


def test_compendio_anonymous_redirects(client, fake):
    _wire(fake)
    r = client.get("/systems/sys1/report")
    assert r.status_code == 302
    assert "/login" in r.headers["Location"]


# --------------------------------------------------------------------------- #
# Rotta PDF
# --------------------------------------------------------------------------- #
def test_pdf_route_returns_pdf(client, login, fake):
    _wire(fake)
    login(permissions=["systems.read", "workflows.read"])
    r = client.get("/systems/sys1/report.pdf")
    assert r.status_code == 200
    assert r.headers["Content-Type"] == "application/pdf"
    body = r.get_data()
    assert body[:5] == b"%PDF-"
    assert len(body) > 1000
    cd = r.headers["Content-Disposition"]
    assert cd.startswith("attachment; filename=")
    assert "compendio_crm-prod_" in cd


def test_pdf_route_custom_period(client, login, fake):
    _wire(fake)
    login(permissions=["systems.read"])
    r = client.get("/systems/sys1/report.pdf",
                   query_string={"preset": "custom",
                                 "from": "2026-07-01T00:00",
                                 "to": "2026-07-02T00:00"})
    assert r.status_code == 200
    assert r.get_data()[:5] == b"%PDF-"
    assert "20260701_20260702" in r.headers["Content-Disposition"]


def test_pdf_filename_sanitized(client, login, fake):
    sys_weird = {**_SYS, "system_id": "@@@"}
    fake.set("GET", "/systems/sys1", sys_weird)
    fake.set("GET", "/systems/sys1/checks", {"items": [], "total": 0})
    login(permissions=["systems.read"])
    r = client.get("/systems/sys1/report.pdf")
    assert r.status_code == 200
    assert "compendio_sistema_" in r.headers["Content-Disposition"]


# --------------------------------------------------------------------------- #
# Helper puri di report.py
# --------------------------------------------------------------------------- #
def test_local_to_utc_variants():
    assert report_view._local_to_utc("", "Europe/Rome") is None
    assert report_view._local_to_utc("non-data", "Europe/Rome") is None
    # datetime-local completo (Europe/Rome estivo = UTC+2)
    assert report_view._local_to_utc("2026-07-01T12:00", "Europe/Rome") == \
        "2026-07-01T10:00:00Z"
    # con secondi
    assert report_view._local_to_utc("2026-07-01T12:00:30", "Europe/Rome") == \
        "2026-07-01T10:00:30Z"
    # solo data
    assert report_view._local_to_utc("2026-07-01", "Europe/Rome") == \
        "2026-06-30T22:00:00Z"
    # tz sconosciuto -> ripiego su default (Europe/Rome)
    assert report_view._local_to_utc("2026-07-01T12:00", "Nowhere/Bad") == \
        "2026-07-01T10:00:00Z"


def test_worst_status():
    assert report_view._worst_status([]) == "unknown"
    assert report_view._worst_status(
        [{"status": "ok", "count": 5}, {"status": "error", "count": 1},
         {"status": "warn", "count": 2}]) == "error"


# --------------------------------------------------------------------------- #
# Builder PDF (report_pdf) — rami di formattazione e impaginazione
# --------------------------------------------------------------------------- #
def test_fmt_helpers():
    assert report_pdf._fmt_pct(None) == "—"
    assert report_pdf._fmt_pct(99.5) == "99.50%"
    assert report_pdf._fmt_pct("x") == "—"
    assert report_pdf._fmt_ms(None) == "—"
    assert report_pdf._fmt_ms(120) == "120 ms"
    assert report_pdf._fmt_ms("x") == "—"
    assert report_pdf._fmt_int(None) == "0"
    assert report_pdf._fmt_int(3) == "3"
    assert report_pdf._fmt_int("x") == "0"


def _period():
    return {"tz_name": "Europe/Rome", "from": "2026-07-17T00:00:00Z",
            "to": "2026-07-17T23:59:59Z", "from_local": "17/07/2026 02:00:00",
            "to_local": "18/07/2026 01:59:59", "preset": "today"}


def test_build_pdf_full():
    data = {
        "overall": _AGGS["aggregations"],
        "distribution": [{"status": "ok", "count": 100},
                         {"status": "warn", "count": 5},
                         {"status": "error", "count": 2}],
        "per_check": [
            {"check_id": "home", "check_name": "Home", "last_status": "ok",
             "last_seen_at": "2026-07-17T08:00:00Z",
             "aggs": _AGGS["aggregations"]},
            {"check_id": "api", "check_name": None, "last_status": "warn",
             "last_seen_at": None, "aggs": {}},
        ],
        "samples": _HB["items"] + [{"@timestamp": "x", "response_ms": None}],
        "alarms": _ALARMS,
        "worst": "error",
    }
    out = report_pdf.build_report_pdf(
        {**_SYS, "kind": "tcp"}, _CHECKS, _period(), data,
        now=_dt.datetime(2026, 7, 17, 10, 0, 0))
    assert out[:5] == b"%PDF-"
    assert len(out) > 1500


def test_build_pdf_empty_sections():
    data = {"overall": {}, "distribution": [], "per_check": [],
            "samples": [], "alarms": {"items": [], "total": 0},
            "worst": "unknown"}
    out = report_pdf.build_report_pdf(
        {"system_id": None, "system_name": None, "kind": "http"},
        {"items": [], "total": 0}, _period(), data)
    assert out[:5] == b"%PDF-"


def test_section_title_page_break():
    pdf = report_pdf._Report("Sys", "gen")
    pdf.alias_nb_pages()
    pdf.add_page()
    before = pdf.page_no()
    pdf.set_y(pdf.h - 20)  # vicino al fondo -> forza il salto pagina
    report_pdf._section_title(pdf, "Titolo")
    assert pdf.page_no() == before + 1


def test_table_page_break_and_alternating():
    pdf = report_pdf._Report("Sys", "gen")
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_y(pdf.h - 30)  # poco spazio -> la tabella impagina
    rows = [[f"c{i}", "ok" if i % 2 else "error", "99%", "1 ms", "2 ms", "—"]
            for i in range(8)]
    report_pdf._table(
        pdf, ["Check", "Stato", "Uptime", "Avg", "Max", "Ultimo"],
        [42, 26, 24, 22, 22, 44], rows, ["L", "C", "R", "R", "R", "L"],
        status_col=1)
    assert pdf.page_no() >= 2


def test_line_chart_page_break():
    pdf = report_pdf._Report("Sys", "gen")
    pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_y(pdf.h - 30)  # forza add_page nel grafico
    report_pdf._line_chart(pdf, [{"response_ms": 10}, {"response_ms": 20},
                                 {"response_ms": 15}])
    assert pdf.page_no() >= 2
