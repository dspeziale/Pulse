"""Test della sidebar a treeview collassabile (AdminLTE 4).

Verifica: i gruppi sono treeview (nav-treeview + nav-arrow), il gruppo che
contiene la pagina corrente e' auto-aperto (menu-open + parent active), il
gating per permesso (gruppo assente se l'utente non ha nessuna voce figlia).
Backend simulato (conftest).
"""
from __future__ import annotations

import re

#: Marcatore univoco dell'INTESTAZIONE di un gruppo treeview (evita falsi
#: positivi col testo dei contenuti di pagina).
def _group_hdr(title: str) -> str:
    return title + '<i class="nav-arrow'


def _dash(fake):
    fake.set("GET", "/dashboard/aggregate", {
        "systems_summary": {"ok": 0, "warn": 0, "error": 0, "down": 0,
                            "unknown": 0}, "active_alarms": 0, "probes": []})
    fake.set("GET", "/probes", {"items": []})
    fake.set("GET", "/alarms", {"items": []})


# -- Struttura treeview -------------------------------------------------------
def test_sidebar_uses_treeview(client, login):
    login(["dashboard.read"])
    html = client.get("/guida").get_data(as_text=True)
    assert 'data-lte-toggle="treeview"' in html
    assert "nav-treeview" in html
    assert 'class="nav-arrow' in html
    # gruppo di primo livello che apre/chiude (href="#")
    assert 'href="#" class="nav-link' in html


def test_groups_present_with_permissions(client, login, fake):
    login(["dashboard.read", "notifications.read", "users.read", "config.read",
           "scans.read"])
    _dash(fake)
    html = client.get("/dashboard").get_data(as_text=True)
    for title in ("Monitoraggio", "Notifiche", "Sicurezza", "Amministrazione",
                  "Sistema", "Aiuto / Account"):
        assert _group_hdr(title) in html


# -- Auto-apertura del gruppo attivo -----------------------------------------
def test_active_group_auto_open_monitoraggio(client, login, fake):
    login(["dashboard.read"])
    _dash(fake)
    html = client.get("/dashboard").get_data(as_text=True)
    # Il gruppo Monitoraggio (pagina corrente Dashboard) e' menu-open + active.
    assert re.search(r'nav-item menu-open">[\s\S]{0,160}<p>Monitoraggio'
                     r'<i class="nav-arrow', html)
    # e la voce figlia Dashboard e' evidenziata.
    assert re.search(r'nav-link active"[^>]*>\s*<i class="nav-icon bi '
                     r'bi-speedometer2"></i><p>Dashboard</p>', html)


def test_active_group_auto_open_aiuto_on_guida(client, login):
    login([])
    html = client.get("/guida").get_data(as_text=True)
    assert re.search(r'nav-item menu-open">[\s\S]{0,160}<p>Aiuto / Account'
                     r'<i class="nav-arrow', html)
    # Guida figlia attiva.
    assert 'href="/guida" class="nav-link active"' in html


def test_only_active_group_is_open(client, login, fake):
    """Un solo gruppo (quello della pagina) e' aperto alla volta."""
    login(["dashboard.read", "users.read"])
    _dash(fake)
    html = client.get("/dashboard").get_data(as_text=True)
    assert html.count("menu-open") == 1


# -- Gating per permesso ------------------------------------------------------
def test_group_hidden_without_child_permission(client, login, fake):
    login(["dashboard.read"])  # nessun permesso admin/sistema/notifiche/scansioni
    _dash(fake)
    html = client.get("/dashboard").get_data(as_text=True)
    assert _group_hdr("Amministrazione") not in html
    assert _group_hdr("Sistema") not in html
    assert _group_hdr("Notifiche") not in html
    assert _group_hdr("Sicurezza") not in html
    # Monitoraggio presente (ha Dashboard) e Aiuto sempre presente.
    assert _group_hdr("Monitoraggio") in html
    assert _group_hdr("Aiuto / Account") in html


def test_aiuto_group_always_present_without_permissions(client, login):
    login([])
    html = client.get("/guida").get_data(as_text=True)
    assert _group_hdr("Aiuto / Account") in html
    assert 'href="/guida"' in html
    # gruppi che richiedono permessi assenti
    assert _group_hdr("Monitoraggio") not in html
    assert _group_hdr("Amministrazione") not in html
