"""Paginazione + selettore "quanti item per pagina" della dashboard PROBE.

Verifica (backend probe-agent simulato da FakeApiClient, vedi conftest):
- la macro `pagination` compare quando total > page_size (default 50) e resta
  nascosta altrimenti, sia sulla dashboard (dashboard.index) sia sul dettaglio
  sistema (dashboard.system_detail);
- la view ricostruisce page/page_size dalla query string (il proxy /query/
  heartbeats ritorna solo {items, total}) e inoltra il page_size scelto al
  backend;
- il selettore `page_size_selector` rende le opzioni 10/25/50/100 con quella
  corrente selezionata, preserva i filtri correnti (hidden input) e RESETTA la
  pagina (nessun input `page` -> submit riparte da page=1).
"""
from __future__ import annotations

_HB = {"@timestamp": "t", "system_name": "S", "check_name": "C",
       "status": "ok", "response_ms": 5}


def _paged(total: int) -> dict:
    return {"items": [_HB, _HB], "total": total}


def _prep_index(fake, hb_total: int):
    fake.set("GET", "/status", {"opensearch_healthy": True, "version": "1.0",
                                "systems_polled": 1})
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", _paged(hb_total))


def _prep_system(fake, hb_total: int):
    fake.set("GET", "/query/heartbeats", _paged(hb_total))
    fake.set("POST", "/query", {"items": [], "aggregations": {"uptime": 99}})


# -- dashboard.index ---------------------------------------------------------
def test_index_pagination_shown(client, login, fake):
    """total > page_size (default 50) -> paginazione heartbeat visibile."""
    login()
    _prep_index(fake, hb_total=120)  # 50 -> 3 pagine
    r = client.get("/dashboard?system_id=s1&status=ok")
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" in html
    assert "Pagina 1 di 3" in html
    assert "120 totali" in html
    # I link puntano a /dashboard e conservano i filtri.
    assert "page=2" in html
    assert "system_id=s1" in html
    assert "status=ok" in html


def test_index_pagination_hidden(client, login, fake):
    """total <= page_size -> nessun controllo, solo il conteggio totale."""
    login()
    _prep_index(fake, hb_total=10)
    r = client.get("/dashboard")
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" not in html
    assert "Totale: 10" in html


def test_index_forwards_page(client, login, fake):
    """Navigazione a pagina 2 -> backend chiamato con page=2."""
    login()
    _prep_index(fake, hb_total=120)
    r = client.get("/dashboard?page=2")
    assert r.status_code == 200
    assert fake.params[("GET", "/query/heartbeats")].get("page") == "2"
    assert "Pagina 2 di 3" in r.data.decode()


def test_index_page_size_selector_options_and_current(client, login, fake):
    """Il selettore rende le opzioni con quella corrente selezionata."""
    login()
    _prep_index(fake, hb_total=120)
    r = client.get("/dashboard?page_size=25")
    assert r.status_code == 200
    html = r.data.decode()
    assert 'name="page_size"' in html
    for opt in (10, 25, 50, 100):
        assert f'<option value="{opt}"' in html
    # 25 e' l'opzione selezionata; il calcolo pagine usa 25 (120/25 = 5).
    assert '<option value="25" selected' in html
    assert "Pagina 1 di 5" in html
    # page_size custom inoltrato al backend.
    assert fake.params[("GET", "/query/heartbeats")].get("page_size") == "25"


def test_index_page_size_selector_preserves_filters_and_resets_page(
        client, login, fake):
    """Il form del selettore preserva i filtri e non riemette `page`."""
    login()
    _prep_index(fake, hb_total=120)
    r = client.get("/dashboard?system_id=s1&status=ok&page=3")
    assert r.status_code == 200
    html = r.data.decode()
    # Filtri correnti presenti come hidden input del form GET...
    assert '<input type="hidden" name="system_id" value="s1">' in html
    assert '<input type="hidden" name="status" value="ok">' in html
    # ...ma non `page` (submit riparte da page=1)...
    assert '<input type="hidden" name="page"' not in html
    # ...ne' `page_size` (viene dal <select>).
    assert '<input type="hidden" name="page_size"' not in html


def test_index_custom_page_size_not_in_options(client, login, fake):
    """Un page_size fuori dalle opzioni standard resta selezionabile."""
    login()
    _prep_index(fake, hb_total=120)
    r = client.get("/dashboard?page_size=30")
    assert r.status_code == 200
    html = r.data.decode()
    assert '<option value="30" selected' in html


def test_index_invalid_page_falls_back(client, login, fake):
    """?page non numerico -> fallback a 1 (nessun crash)."""
    login()
    _prep_index(fake, hb_total=120)
    r = client.get("/dashboard?page=abc")
    assert r.status_code == 200
    assert "Pagina 1 di 3" in r.data.decode()


def test_index_invalid_page_size_falls_back(client, login, fake):
    """?page_size non numerico -> fallback al default 50 (3 pagine su 120)."""
    login()
    _prep_index(fake, hb_total=120)
    r = client.get("/dashboard?page_size=xyz")
    assert r.status_code == 200
    assert "Pagina 1 di 3" in r.data.decode()


# -- dashboard.system_detail -------------------------------------------------
def test_system_pagination_shown(client, login, fake):
    """total > page_size -> paginazione visibile sul dettaglio sistema."""
    login()
    _prep_system(fake, hb_total=120)
    r = client.get("/systems/s1?from=a&to=b")
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" in html
    assert "Pagina 1 di 3" in html
    # I link puntano alla rotta /systems/s1 (system_id nel path).
    assert "/systems/s1?" in html
    assert "page=2" in html


def test_system_pagination_hidden(client, login, fake):
    login()
    _prep_system(fake, hb_total=10)
    r = client.get("/systems/s1")
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" not in html
    assert "Totale: 10" in html


def test_system_forwards_page_size(client, login, fake):
    """page_size scelto -> inoltrato al backend e usato per il calcolo pagine."""
    login()
    _prep_system(fake, hb_total=120)
    r = client.get("/systems/s1?page_size=25&page=2")
    assert r.status_code == 200
    params = fake.params[("GET", "/query/heartbeats")]
    assert params.get("page_size") == "25"
    assert params.get("page") == "2"
    assert params.get("system_id") == "s1"
    assert "Pagina 2 di 5" in r.data.decode()


def test_system_page_size_selector_present(client, login, fake):
    login()
    _prep_system(fake, hb_total=120)
    r = client.get("/systems/s1")
    assert r.status_code == 200
    html = r.data.decode()
    assert 'name="page_size"' in html
    assert '<option value="50" selected' in html  # default 50
