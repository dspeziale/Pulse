"""Test della paginazione delle liste (macro + wiring delle viste).

Verifica che:
- la macro renda i controlli quando total > page_size e li nasconda altrimenti;
- i link di paginazione preservino i filtri correnti (q, status, ...);
- le viste calcolino page/page_size (il backend NON li restituisce: le risposte
  di lista contengono solo items + total) e li usino per la paginazione;
- la navigazione a pagina 2 chiami il backend con page=2.

Il backend REST e' simulato da FakeApiClient (vedi conftest). Le risposte
mockate rispecchiano quelle REALI del backend: {items: [...], total: N} — SENZA
page/page_size (che il backend non ritorna).
"""
from __future__ import annotations

import pytest

# Ogni voce: (permessi, path della lista, endpoint backend, nome rotta)
LISTS = [
    (["audit.read"], "/audit", "/audit", "audit.list_audit"),
    (["syslog.read"], "/logs", "/logs", "logs.list_logs"),
    (["workflows.read"], "/alarms", "/alarms", "alarms.list_alarms"),
    (["notifications.read"], "/notifications/history", "/notifications/history",
     "notifications.history"),
    (["notifications.read"], "/notification-channels", "/notification-channels",
     "notifications.list_channels"),
    (["users.read"], "/users", "/users", "users.list_users"),
    (["roles.read"], "/roles", "/roles", "roles.list_roles"),
    (["workflows.read"], "/notification-workflows", "/notification-workflows",
     "workflows.list_workflows"),
    (["probes.read"], "/probes", "/probes", "probes.list_probes"),
]


def _row(i: int = 1) -> dict:
    """Una riga generica navigabile da tutti i template di lista."""
    return {
        "id": str(i), "username": f"u{i}", "name": f"n{i}", "status": "active",
        "roles": [], "permissions": [], "enabled": True, "is_builtin": False,
        "trigger": "status_changed", "type": "email", "system_id": "s1",
        "probe_id": "p1", "opened_at": "x", "timestamp": "x", "actor_type": "user",
        "actor_id": "a", "action": "x", "entity_type": "e", "outcome": "success",
        "component": "server", "level": "info", "logger": "l", "message": "m",
        "channel_id": "c1", "recipient": "r", "created_at": "x",
        "systems_count": 0, "last_seen_at": None, "kind": "http",
        "heartbeat_url": "http://x", "full_name": "F", "email": "e@x",
        "description": "d", "inbound_enabled": False,
    }


def _paged(total: int) -> dict:
    """Risposta di lista REALISTICA: solo items + total (niente page_size)."""
    return {"items": [_row(1), _row(2)], "total": total}


def _prep(fake, endpoint):
    """La lista sistemi carica anche /probes per il filtro."""
    fake.set("GET", "/probes", {"items": []})


@pytest.mark.parametrize("perms,url,endpoint,route", LISTS)
def test_pagination_shown_when_more_than_one_page(client, login, fake, perms,
                                                  url, endpoint, route):
    """Con total > page_size (default 20) la paginazione compare nell'HTML."""
    login(perms)
    _prep(fake, endpoint)
    fake.set("GET", endpoint, _paged(total=45))  # default page_size=20 -> 3 pagine
    r = client.get(url)
    assert r.status_code == 200
    html = r.data.decode()
    # Marcatori Bootstrap effettivamente serviti
    assert "pagination" in html
    assert "page-link" in html
    assert "Successivo" in html
    assert "Precedente" in html
    assert "Pagina 1 di 3" in html
    assert "45 totali" in html
    # Link a pagina 2 costruito con l'endpoint corretto
    assert "page=2" in html


@pytest.mark.parametrize("perms,url,endpoint,route", LISTS)
def test_pagination_hidden_on_single_page(client, login, fake, perms, url,
                                          endpoint, route):
    """Con total <= page_size nessun controllo, solo il conteggio totale."""
    login(perms)
    _prep(fake, endpoint)
    fake.set("GET", endpoint, _paged(total=2))
    r = client.get(url)
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" not in html
    assert "Successivo" not in html
    assert "Precedente" not in html
    assert "Totale: 2" in html


def test_pagination_links_preserve_filters(client, login, fake):
    """I link di pagina devono conservare i filtri correnti (q, status)."""
    login(["users.read"])
    fake.set("GET", "/users", _paged(total=60))
    r = client.get("/users?q=alice&status=active")
    assert r.status_code == 200
    html = r.data.decode()
    # I filtri correnti sono propagati al backend...
    assert fake.params[("GET", "/users")].get("q") == "alice"
    assert fake.params[("GET", "/users")].get("status") == "active"
    # ...e conservati nei link di paginazione.
    assert "q=alice" in html
    assert "status=active" in html
    assert "page=2" in html


def test_view_forwards_page_to_backend(client, login, fake):
    """La navigazione a pagina 2 richiama il backend con page=2."""
    login(["audit.read"])
    fake.set("GET", "/audit", _paged(total=45))
    r = client.get("/audit?page=2&outcome=success")
    assert r.status_code == 200
    params = fake.params[("GET", "/audit")]
    assert params.get("page") == "2"
    assert params.get("outcome") == "success"
    # La pagina corrente (calcolata dalla view) e' evidenziata
    assert "Pagina 2 di 3" in r.data.decode()


def test_custom_page_size_preserved_in_links(client, login, fake):
    """Un page_size custom nella query string e' usato e mantenuto nei link."""
    login(["roles.read"])
    fake.set("GET", "/roles", _paged(total=30))
    r = client.get("/roles?page_size=5")
    assert r.status_code == 200
    html = r.data.decode()
    # Il page_size custom e' propagato al backend...
    assert fake.params[("GET", "/roles")].get("page_size") == "5"
    # ...usato per il calcolo delle pagine (30/5 = 6)...
    assert "Pagina 1 di 6" in html
    # ...e conservato nei link.
    assert "page_size=5" in html


def test_macro_renders_first_last_and_ellipsis(client, login, fake):
    """Con molte pagine e pagina centrale: prima/ultima ed ellissi."""
    login(["audit.read"])
    fake.set("GET", "/audit", _paged(total=200))  # default 20 -> 10 pagine
    r = client.get("/audit?page=5")
    assert r.status_code == 200
    html = r.data.decode()
    assert "Pagina 5 di 10" in html
    assert "…" in html
    assert "page=1" in html
    assert "page=10" in html


def test_pagination_hidden_when_total_missing(client, login, fake):
    """Difensivo: risposta priva di total -> nessun controllo, nessun crash."""
    login(["audit.read"])
    fake.set("GET", "/audit", {"items": [_row(1)]})
    r = client.get("/audit")
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" not in html
    assert "Totale: 0" in html


def test_invalid_page_param_falls_back(client, login, fake):
    """Un ?page non numerico non deve rompere il rendering (fallback a 1)."""
    login(["audit.read"])
    fake.set("GET", "/audit", _paged(total=45))
    r = client.get("/audit?page=abc")
    assert r.status_code == 200
    assert "Pagina 1 di 3" in r.data.decode()


def test_invalid_page_size_param_falls_back(client, login, fake):
    """Un ?page_size non numerico ripiega sul default (20)."""
    login(["audit.read"])
    fake.set("GET", "/audit", _paged(total=45))
    r = client.get("/audit?page_size=xyz")
    assert r.status_code == 200
    # default 20 -> 3 pagine
    assert "Pagina 1 di 3" in r.data.decode()


# -- Dettaglio Sonda: paginazione "Heartbeat recenti" (page_size default 50) --
def _prep_probe_detail(fake, hb_total: int):
    fake.set("GET", "/probes/1", {"id": "1", "name": "p"})
    fake.set("GET", "/probes/1/status", {"status": "online"})
    fake.set("GET", "/dashboard/probe/1", {"systems": [], "generated_at": "x"})
    hb = {"@timestamp": "t", "system_name": "S", "check_name": "C",
          "status": "ok", "response_ms": 5}
    fake.set("GET", "/probes/1/heartbeats", {"items": [hb, hb], "total": hb_total})


def test_probe_detail_heartbeats_pagination_shown(client, login, fake):
    """total > page_size (default 50) -> paginazione heartbeat visibile."""
    login(["probes.read"])
    _prep_probe_detail(fake, hb_total=120)  # default 50 -> 3 pagine
    r = client.get("/probes/1?window=7d&system_id=s1&status=ok")
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" in html
    assert "Pagina 1 di 3" in html
    assert "120 totali" in html
    # I link puntano alla rotta /probes/1 e conservano window + filtri hb
    assert "/probes/1?" in html
    assert "page=2" in html
    assert "window=7d" in html
    assert "system_id=s1" in html
    assert "status=ok" in html


def test_probe_detail_heartbeats_pagination_hidden(client, login, fake):
    """total <= page_size (default 50) -> nessun controllo, solo il totale."""
    login(["probes.read"])
    _prep_probe_detail(fake, hb_total=10)
    r = client.get("/probes/1")
    assert r.status_code == 200
    html = r.data.decode()
    assert "page-link" not in html
    assert "Totale: 10" in html


def test_probe_detail_heartbeats_forwards_page(client, login, fake):
    """Navigazione a pagina 2 -> backend heartbeats chiamato con page=2."""
    login(["probes.read"])
    _prep_probe_detail(fake, hb_total=120)
    r = client.get("/probes/1?page=2")
    assert r.status_code == 200
    assert fake.params[("GET", "/probes/1/heartbeats")].get("page") == "2"
    assert "Pagina 2 di 3" in r.data.decode()


# -- Selettore "quanti item per pagina" sul dettaglio Sonda -------------------
def test_probe_detail_page_size_selector_options_and_current(client, login,
                                                             fake):
    """Il selettore rende 10/25/50/100 con quella corrente selezionata."""
    login(["probes.read"])
    _prep_probe_detail(fake, hb_total=120)
    r = client.get("/probes/1?page_size=25")
    assert r.status_code == 200
    html = r.data.decode()
    assert 'name="page_size"' in html
    for opt in (10, 25, 50, 100):
        assert f'<option value="{opt}"' in html
    assert '<option value="25" selected' in html
    # page_size custom usato per il calcolo pagine (120/25 = 5) e inoltrato.
    assert "Pagina 1 di 5" in html
    assert fake.params[("GET", "/probes/1/heartbeats")].get("page_size") == "25"


def test_probe_detail_page_size_selector_preserves_and_resets(client, login,
                                                             fake):
    """Il form preserva i filtri (hidden) e non riemette `page`."""
    login(["probes.read"])
    _prep_probe_detail(fake, hb_total=120)
    r = client.get("/probes/1?window=7d&system_id=s1&status=ok&page=3")
    assert r.status_code == 200
    html = r.data.decode()
    assert '<input type="hidden" name="window" value="7d">' in html
    assert '<input type="hidden" name="system_id" value="s1">' in html
    assert '<input type="hidden" name="status" value="ok">' in html
    assert '<input type="hidden" name="page"' not in html
    assert '<input type="hidden" name="page_size"' not in html
    # L'action del form punta alla rotta /probes/1 (probe_id nel path).
    assert 'action="/probes/1' in html


def test_probe_detail_page_size_default_selected(client, login, fake):
    """Senza page_size in query il default 50 e' preselezionato."""
    login(["probes.read"])
    _prep_probe_detail(fake, hb_total=120)
    r = client.get("/probes/1")
    assert r.status_code == 200
    assert '<option value="50" selected' in r.data.decode()


# -- Test unitari della macro page_size_selector -----------------------------
_PS_TPL = (
    '{% from "_macros.html" import page_size_selector %}'
    "{{ page_size_selector(current, endpoint, args) }}"
)


def _render_ps(app, **kwargs):
    from flask import render_template_string
    with app.test_request_context("/"):
        return render_template_string(_PS_TPL, **kwargs)


def test_ps_macro_marks_current_selected(app):
    out = _render_ps(app, current=25, endpoint="audit.list_audit", args={})
    assert '<option value="25" selected' in out
    assert '<option value="50"' in out
    assert 'selected' not in out.split('value="50"')[1].split('>')[0]


def test_ps_macro_injects_custom_size(app):
    """current fuori dalle opzioni viene aggiunto e ordinato."""
    out = _render_ps(app, current=42, endpoint="audit.list_audit", args={})
    assert '<option value="42" selected' in out


def test_ps_macro_emits_filters_but_not_paging(app):
    out = _render_ps(app, current=50, endpoint="audit.list_audit",
                     args={"q": "x", "page": "3", "page_size": "50"})
    assert '<input type="hidden" name="q" value="x">' in out
    assert 'name="page"' not in out.replace('name="page_size"', "")
    # page_size non deve comparire come hidden (viene dal select).
    assert '<input type="hidden" name="page_size"' not in out


# -- Test unitari della macro (indipendenti dai template chiamanti) -----------
_MACRO_TPL = (
    '{% from "_macros.html" import pagination %}'
    "{{ pagination(page, page_size, total, endpoint, args) }}"
)


def _render_macro(app, **kwargs):
    from flask import render_template_string
    with app.test_request_context("/"):
        return render_template_string(_MACRO_TPL, **kwargs)


def test_macro_unit_shows_controls_when_total_gt_page_size(app):
    out = _render_macro(app, page=1, page_size=20, total=45,
                        endpoint="audit.list_audit", args={})
    assert "Successivo" in out
    assert "Pagina 1 di 3" in out
    assert "page=2" in out


def test_macro_unit_hidden_when_total_le_page_size(app):
    out = _render_macro(app, page=1, page_size=20, total=20,
                        endpoint="audit.list_audit", args={})
    assert out.strip() == ""


def test_macro_unit_coerces_non_int_values(app):
    """Valori non interi (stringhe) sono coercizzati senza errori."""
    out = _render_macro(app, page="2", page_size="10", total="35",
                        endpoint="audit.list_audit", args={"q": "x"})
    assert "Pagina 2 di 4" in out
    assert "q=x" in out


def test_macro_unit_clamps_page_over_last(app):
    """Una pagina oltre l'ultima viene riportata all'ultima per l'etichetta."""
    out = _render_macro(app, page=99, page_size=10, total=35,
                        endpoint="audit.list_audit", args={})
    assert "Pagina 4 di 4" in out
