"""Test dell'adattatore server-side DataTables (pulse_fe_common.datatables).

Modulo puro (nessuna dipendenza da Flask/backend): si testa il parsing dei
parametri DataTables, la mappatura verso i parametri API (page/page_size/q/sort),
la risposta nel formato DataTables e gli helper di markup delle celle.
"""
from __future__ import annotations

from markupsafe import Markup

from pulse_fe_common.datatables import (DataTablesQuery, DTColumn, DTTable,
                                        badge, bool_badge, build_params,
                                        parse_request, resolve_sort, serve,
                                        status_badge)


# -- markup helpers -----------------------------------------------------------
def test_status_badge_known():
    out = str(status_badge("ok"))
    assert 'class="badge b-ok"' in out and ">ok<" in out


def test_status_badge_unknown_value():
    out = str(status_badge("bizarre"))
    assert 'class="badge b-unknown"' in out and ">bizarre<" in out


def test_status_badge_none_and_empty():
    assert "—" in str(status_badge(None))
    assert 'b-unknown' in str(status_badge(None))
    assert "—" in str(status_badge("   "))


def test_status_badge_escapes():
    out = str(status_badge("<x>"))
    assert "<x>" not in out and "&lt;x&gt;" in out


def test_badge_and_bool_badge():
    assert 'text-bg-info' in str(badge("info", "text-bg-info"))
    assert 'b-ok' in str(bool_badge(True)) and "Sì" in str(bool_badge(True))
    assert 'b-off' in str(bool_badge(False)) and "No" in str(bool_badge(False))
    assert "Attivo" in str(bool_badge(True, yes="Attivo", no="Spento"))


# -- DTColumn / DTTable -------------------------------------------------------
def test_dtcolumn_to_js_orderable_and_class():
    c = DTColumn("name", lambda i: i["name"], sort="name", title="Nome",
                 class_="text-end")
    js = c.to_js()
    assert js == {"data": "name", "orderable": True, "className": "text-end"}


def test_dtcolumn_to_js_not_orderable_no_class():
    c = DTColumn("actions", lambda i: "x", title="Azioni")
    assert c.orderable is False
    assert c.to_js() == {"data": "actions", "orderable": False}


def test_dttable_meta():
    t = DTTable(
        columns=[DTColumn("a", lambda i: "", sort="a", title="A"),
                 DTColumn("b", lambda i: "", title="B", th_class="text-end")],
        order=(1, "desc"), default_length=50, length_menu=(10, 50), searching=False,
    )
    m = t.meta()
    assert m["columns"] == [{"title": "A", "th_class": ""},
                            {"title": "B", "th_class": "text-end"}]
    assert m["columnsJs"] == [{"data": "a", "orderable": True},
                              {"data": "b", "orderable": False}]
    assert m["order"] == [[1, "desc"]]
    assert m["lengthMenu"] == [10, 50]
    assert m["pageLength"] == 50
    assert m["searching"] is False


# -- parse_request ------------------------------------------------------------
def test_parse_request_defaults_empty():
    q = parse_request({})
    assert q.draw == 1 and q.start == 0 and q.length == 10
    assert q.search == "" and q.order_column is None and q.columns == []


def test_parse_request_full():
    args = {
        "draw": "7", "start": "20", "length": "10",
        "search[value]": " ciao ",
        "columns[0][data]": "name", "columns[1][data]": "status",
        "order[0][column]": "1", "order[0][dir]": "desc",
    }
    q = parse_request(args)
    assert q.draw == 7 and q.start == 20 and q.length == 10
    assert q.search == "ciao"
    assert q.columns == ["name", "status"]
    assert q.order_column == 1 and q.order_dir == "desc"


def test_parse_request_invalid_ints_fallback():
    q = parse_request({"draw": "x", "start": "-5", "length": "abc"})
    assert q.draw == 1 and q.start == 0 and q.length == 10


def test_parse_request_length_all_uses_fallback():
    assert parse_request({"length": "-1"}).length == 10


def test_parse_request_order_invalid_column():
    q = parse_request({"order[0][column]": "zz"})
    assert q.order_column is None


def test_parse_request_order_dir_defaults_asc():
    q = parse_request({"order[0][column]": "0"})
    assert q.order_column == 0 and q.order_dir == "asc"


# -- resolve_sort -------------------------------------------------------------
_COLS = [
    DTColumn("name", lambda i: "", sort="name"),
    DTColumn("actions", lambda i: "", sort=None),
    DTColumn("status", lambda i: "", sort="status"),
]


def test_resolve_sort_none_when_no_order():
    assert resolve_sort(parse_request({}), _COLS) is None


def test_resolve_sort_by_data_name_asc():
    q = parse_request({"order[0][column]": "0", "order[0][dir]": "asc",
                       "columns[0][data]": "name"})
    assert resolve_sort(q, _COLS) == "name"


def test_resolve_sort_by_data_name_desc():
    q = parse_request({"order[0][column]": "2", "order[0][dir]": "desc",
                       "columns[0][data]": "name", "columns[1][data]": "actions",
                       "columns[2][data]": "status"})
    assert resolve_sort(q, _COLS) == "-status"


def test_resolve_sort_non_orderable_column_returns_none():
    q = parse_request({"order[0][column]": "1", "order[0][dir]": "asc",
                       "columns[0][data]": "name", "columns[1][data]": "actions",
                       "columns[2][data]": "status"})
    assert resolve_sort(q, _COLS) is None


def test_resolve_sort_unknown_data_name_falls_back_to_index():
    q = parse_request({"order[0][column]": "0", "order[0][dir]": "asc",
                       "columns[0][data]": "sconosciuta"})
    # nome non riconosciuto -> ripiego per indice (colonna 0 = name)
    assert resolve_sort(q, _COLS) == "name"


def test_resolve_sort_index_fallback_without_columns():
    q = DataTablesQuery(draw=1, start=0, length=10, search="",
                        order_column=2, order_dir="asc", columns=[])
    assert resolve_sort(q, _COLS) == "status"


def test_resolve_sort_index_out_of_range():
    q = DataTablesQuery(draw=1, start=0, length=10, search="",
                        order_column=9, order_dir="asc", columns=[])
    assert resolve_sort(q, _COLS) is None


# -- build_params -------------------------------------------------------------
def test_build_params_page_and_size():
    q = parse_request({"start": "20", "length": "10"})
    p = build_params(q, _COLS)
    assert p["page"] == 3 and p["page_size"] == 10
    assert "q" not in p and "sort" not in p


def test_build_params_with_search_sort_filters():
    q = parse_request({"start": "0", "length": "25", "search[value]": "abc",
                       "order[0][column]": "0", "order[0][dir]": "desc",
                       "columns[0][data]": "name"})
    p = build_params(q, _COLS, extra_filters={"status": "active", "empty": "",
                                              "none": None})
    assert p["page"] == 1 and p["page_size"] == 25
    assert p["q"] == "abc" and p["sort"] == "-name"
    assert p["status"] == "active"
    assert "empty" not in p and "none" not in p


# -- serve --------------------------------------------------------------------
def _cols():
    return [
        DTColumn("name", lambda i: i.get("name"), sort="name"),
        DTColumn("status", lambda i: status_badge(i.get("status")), sort="status"),
        DTColumn("missing", lambda i: i.get("missing")),  # -> None -> segnaposto
    ]


def test_serve_full_flow():
    captured = {}

    def fetch(params):
        captured.update(params)
        return {"items": [{"name": "a", "status": "ok"}], "total": 42}

    args = {"draw": "3", "start": "0", "length": "10",
            "order[0][column]": "0", "order[0][dir]": "asc",
            "columns[0][data]": "name", "columns[1][data]": "status",
            "columns[2][data]": "missing"}
    out = serve(args, _cols(), fetch, extra_filters={"status": "ok"})
    assert out["draw"] == 3
    assert out["recordsTotal"] == 42 and out["recordsFiltered"] == 42
    row = out["data"][0]
    assert row["name"] == "a"
    assert 'badge b-ok' in row["status"]
    assert row["missing"] == "—"
    assert captured["page"] == 1 and captured["sort"] == "name"
    assert captured["status"] == "ok"


def test_serve_missing_total_and_empty_items():
    out = serve({"draw": "1"}, _cols(), lambda p: {"items": []})
    assert out["recordsTotal"] == 0 and out["data"] == []


def test_serve_non_mapping_response():
    out = serve({"draw": "2"}, _cols(), lambda p: None)
    assert out["draw"] == 2 and out["recordsTotal"] == 0 and out["data"] == []


def test_serve_non_int_total():
    out = serve({"draw": "1"}, _cols(),
                lambda p: {"items": [], "total": "not-a-number"})
    assert out["recordsTotal"] == 0
