"""Test della sidebar treeview della dashboard PROBE (coerente col server)."""
from __future__ import annotations

import re


def _group_hdr(title: str) -> str:
    return title + '<i class="nav-arrow'


def _prep_dashboard(fake):
    fake.set("GET", "/status", {"opensearch_healthy": True, "version": "1.0"})
    fake.set("GET", "/systems", {"items": []})
    fake.set("GET", "/query/heartbeats", {"items": [], "total": 0})


def test_sidebar_uses_treeview(client, login, fake):
    login()
    _prep_dashboard(fake)
    html = client.get("/dashboard").get_data(as_text=True)
    assert 'data-lte-toggle="treeview"' in html
    assert "nav-treeview" in html and 'class="nav-arrow' in html
    assert _group_hdr("Monitoraggio") in html
    assert _group_hdr("Sonda") in html


def test_dashboard_is_first_toplevel(client, login, fake):
    login()
    _prep_dashboard(fake)
    html = client.get("/dashboard").get_data(as_text=True)
    # Dashboard e' voce di primo livello, PRIMA del primo gruppo treeview.
    dash_pos = html.find("<p>Dashboard</p>")
    tree_pos = html.find("nav-treeview")
    assert dash_pos != -1 and tree_pos != -1 and dash_pos < tree_pos
    # su /dashboard nessun gruppo e' aperto (Dashboard e' fuori dai gruppi).
    assert html.count("menu-open") == 0


def test_active_group_sonda_on_status(client, login, fake):
    login()
    fake.set("GET", "/status", {"version": "1.0"})
    fake.set("GET", "/health/ready", {"status": "ready"})
    html = client.get("/status").get_data(as_text=True)
    assert re.search(r'nav-item menu-open">[\s\S]{0,160}<p>Sonda'
                     r'<i class="nav-arrow', html)
    assert 'href="' in html and "Stato" in html
