"""Adattatore server-side per DataTables.js (condiviso Server/Probe).

DataTables in modalita' ``serverSide`` invia paginazione, ordinamento e ricerca
via query string; questo modulo li traduce nei parametri delle API Pulse
(``page``, ``page_size``, ``q``, ``sort`` + filtri) e ricompone la risposta nel
formato atteso da DataTables:

    {"draw": N, "recordsTotal": T, "recordsFiltered": T, "data": [...]}

Le celle sono renderizzate LATO SERVER (badge/azioni/date identiche ai template
Jinja) tramite funzioni di rendering per-colonna: vedi ``dt.py`` di ciascuna
dashboard. Il modulo e' puro (nessuna dipendenza da Flask) e quindi testabile in
isolamento: riceve un ``Mapping`` dei parametri e una callable ``fetch`` che
esegue la chiamata al backend.

Mappatura DataTables -> API:
  - ``start`` / ``length``     -> ``page`` = start // length + 1, ``page_size`` = length
  - ``search[value]``          -> ``q``
  - ``order[0][column]``/``dir`` + ``columns[i][data]`` -> ``sort`` ('campo' o '-campo'),
    applicato SOLO se la colonna ordinata e' nella whitelist (``DTColumn.sort``)
  - filtri correnti (ajax.data: probe_id/kind/status/...) -> parametri omonimi
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional, Sequence

from markupsafe import Markup

#: page_size di ripiego quando ``length`` e' assente/non valido/"tutti" (-1).
_FALLBACK_LENGTH = 10

# --------------------------------------------------------------------------- #
# Markup condiviso: coerente con server|probe/dashboard/templates/_macros.html
# --------------------------------------------------------------------------- #
#: Stati noti mappati a una classe colore ``b-*`` (vedi pulse-theme.css).
_KNOWN_STATUS = {
    "ok", "warn", "error", "down", "unknown", "online", "offline", "pending",
    "sent", "failed", "retrying", "active", "acknowledged", "resolved",
    "success", "failure", "disabled",
}

#: Segnaposto per valori assenti (identico a datetimes.PLACEHOLDER).
PLACEHOLDER = "—"


def status_badge(value: Any) -> Markup:
    """Badge di stato: normalizza il valore e ripiega su ``b-unknown``.

    Replica ``_macros.html:status_badge`` (stessa classe, stesso segnaposto).
    """
    v = str(value).lower().strip() if value is not None else ""
    cls = ("b-" + v) if v in _KNOWN_STATUS else "b-unknown"
    text = value if (value is not None and v) else PLACEHOLDER
    return Markup('<span class="badge {}">{}</span>').format(cls, text)


def badge(value: Any, css_class: str) -> Markup:
    """Badge generico con classe esplicita (es. livelli di log ``text-bg-*``)."""
    return Markup('<span class="badge {}">{}</span>').format(css_class, value)


def bool_badge(value: Any, yes: str = "Sì", no: str = "No") -> Markup:
    """Badge Sì/No per campi booleani. Replica ``_macros.html:bool_badge``."""
    if value:
        return Markup('<span class="badge b-ok">{}</span>').format(yes)
    return Markup('<span class="badge b-off">{}</span>').format(no)


# --------------------------------------------------------------------------- #
# Modello colonna e parsing della richiesta DataTables
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class DTColumn:
    """Definizione di una colonna server-side.

    - ``data``:   nome logico della colonna (deve coincidere con ``columns[i].data``
      lato JS): usato come chiave nell'oggetto-riga e per risolvere l'ordinamento.
    - ``render``: callable ``(item) -> str/Markup`` che produce l'HTML della cella.
    - ``sort``:   nome del campo di ordinamento accettato dal backend (whitelist).
      ``None`` => colonna NON ordinabile (nessun ``sort`` inviato).
    - ``title``:  intestazione della colonna (``<th>``).
    - ``class_``: className applicata alle celle del corpo (``<td>``) da DataTables.
    - ``th_class``: classe dell'intestazione (``<th>``).

    ``title``/``class_``/``th_class`` alimentano SOLO la resa del template (thead +
    config JS ``columns``): un'unica sorgente evita disallineamenti tra header,
    colonne JS e rendering server-side.
    """

    data: str
    render: Callable[[Any], Any]
    sort: Optional[str] = None
    title: str = ""
    class_: str = ""
    th_class: str = ""

    @property
    def orderable(self) -> bool:
        return self.sort is not None

    def to_js(self) -> dict:
        """Config della colonna per l'init DataTables lato JS."""
        cfg: dict[str, Any] = {"data": self.data, "orderable": self.orderable}
        if self.class_:
            cfg["className"] = self.class_
        return cfg


@dataclass(frozen=True)
class DTTable:
    """Tabella server-side: colonne + opzioni di presentazione DataTables.

    Fornisce ``meta()`` con tutto cio' che serve al template per costruire, da
    un'unica sorgente, sia il ``<thead>`` sia l'init JS (columns/order/lengthMenu).
    """

    columns: Sequence[DTColumn]
    order: tuple = (0, "asc")
    length_menu: Sequence[int] = (10, 25, 50, 100)
    default_length: int = 25
    searching: bool = True

    def meta(self) -> dict:
        return {
            "columns": [
                {"title": c.title, "th_class": c.th_class} for c in self.columns
            ],
            "columnsJs": [c.to_js() for c in self.columns],
            "order": [[int(self.order[0]), self.order[1]]],
            "lengthMenu": list(self.length_menu),
            "pageLength": self.default_length,
            "searching": self.searching,
        }


@dataclass(frozen=True)
class DataTablesQuery:
    """Parametri DataTables normalizzati."""

    draw: int
    start: int
    length: int
    search: str
    order_column: Optional[int]
    order_dir: str
    columns: Sequence[str]


def parse_request(args: Mapping[str, Any]) -> DataTablesQuery:
    """Estrae i parametri DataTables da un ``Mapping`` (es. ``request.args``)."""

    def _int(name: str, default: int) -> int:
        try:
            return int(args.get(name, default))
        except (TypeError, ValueError):
            return default

    draw = _int("draw", 1)
    start = max(0, _int("start", 0))
    length = _int("length", _FALLBACK_LENGTH)
    if length <= 0:  # -1 = "tutti": non supportato lato API, si usa il ripiego.
        length = _FALLBACK_LENGTH

    search = (args.get("search[value]") or "").strip()

    columns: list[str] = []
    i = 0
    while True:
        key = f"columns[{i}][data]"
        if key not in args:
            break
        columns.append(args.get(key) or "")
        i += 1

    order_column: Optional[int] = None
    order_dir = "asc"
    raw_col = args.get("order[0][column]")
    if raw_col not in (None, ""):
        try:
            order_column = int(raw_col)
        except (TypeError, ValueError):
            order_column = None
        order_dir = "desc" if args.get("order[0][dir]") == "desc" else "asc"

    return DataTablesQuery(
        draw=draw, start=start, length=length, search=search,
        order_column=order_column, order_dir=order_dir, columns=columns,
    )


def resolve_sort(query: DataTablesQuery, columns: Sequence[DTColumn]) -> Optional[str]:
    """Traduce l'ordinamento DataTables nel parametro ``sort`` ('campo'/'-campo').

    Ritorna ``None`` se non c'e' ordinamento o se la colonna ordinata non e'
    nella whitelist (``DTColumn.sort is None``). La colonna e' individuata per
    ``columns[i][data]`` se presente, con ripiego sull'indice.
    """
    idx = query.order_column
    if idx is None:
        return None
    field: Optional[str] = None
    # 1) per nome logico (columns[i][data]) inviato da DataTables
    if 0 <= idx < len(query.columns) and query.columns[idx]:
        data_name = query.columns[idx]
        for col in columns:
            if col.data == data_name:
                field = col.sort
                break
        else:
            data_name = None  # nome non riconosciuto: si prova per indice
        if data_name is not None and field is None:
            return None  # colonna riconosciuta ma non ordinabile
    # 2) ripiego per posizione
    if field is None and 0 <= idx < len(columns):
        field = columns[idx].sort
    if not field:
        return None
    return ("-" + field) if query.order_dir == "desc" else field


def build_params(
    query: DataTablesQuery,
    columns: Sequence[DTColumn],
    extra_filters: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Costruisce i parametri per la chiamata API a partire dalla query DataTables."""
    params: dict[str, Any] = {
        "page": query.start // query.length + 1,
        "page_size": query.length,
    }
    if query.search:
        params["q"] = query.search
    sort = resolve_sort(query, columns)
    if sort:
        params["sort"] = sort
    if extra_filters:
        for key, value in extra_filters.items():
            if value not in (None, ""):
                params[key] = value
    return params


def _cell(value: Any) -> str:
    """Serializza una cella per il JSON (Markup/str -> str, None -> segnaposto)."""
    if value is None:
        return PLACEHOLDER
    return str(value)


def serve(
    args: Mapping[str, Any],
    columns: Sequence[DTColumn],
    fetch: Callable[[Mapping[str, Any]], Any],
    extra_filters: Optional[Mapping[str, Any]] = None,
) -> dict:
    """Esegue il ciclo completo dell'adattatore e ritorna il dict DataTables.

    - ``args``:    parametri DataTables (``request.args``).
    - ``columns``: colonne server-side (ordine = colonne DataTables lato JS).
    - ``fetch``:   callable ``(params) -> {"items": [...], "total": N}`` che chiama
      l'endpoint di lista del backend col token di sessione.
    - ``extra_filters``: filtri correnti da ajax.data (probe_id/kind/status/...).
    """
    query = parse_request(args)
    params = build_params(query, columns, extra_filters)
    data = fetch(params) or {}
    items = data.get("items", []) if isinstance(data, Mapping) else []
    try:
        total = int(data.get("total", 0) or 0) if isinstance(data, Mapping) else 0
    except (TypeError, ValueError):
        total = 0
    rows = [
        {col.data: _cell(col.render(item)) for col in columns}
        for item in (items or [])
    ]
    return {
        "draw": query.draw,
        "recordsTotal": total,
        "recordsFiltered": total,
        "data": rows,
    }
