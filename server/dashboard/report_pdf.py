"""Generazione del report PDF del Compendio sistema (lato server, fpdf2).

Approccio scelto: **fpdf2** (puro Python) con il font **PT Sans Narrow**
embeddato (TTF ottenuti dai woff2 gia' vendorizzati per la UI). Motivazione
documentata nel README (§Compendio / Report PDF): fpdf2 non richiede librerie di
sistema (a differenza di WeasyPrint, che su Windows/CI necessita di
pango/cairo/gdk-pixbuf), quindi il report e' generabile e verificabile davvero in
qualunque ambiente, test inclusi, restando coerente col resto della dashboard
grazie allo stesso identico carattere.

Cura estetica: intestazione col titolo, nome sistema e periodo; testo ben
leggibile (corpo 10-11pt, titoli 14-22pt); tabelle ordinate a righe alternate che
stanno nella pagina A4; badge di stato colorati; footer con data di generazione
(nel fuso locale) e numero di pagina. Gli oggetti sono dimensionati sulla
larghezza utile A4 (180 mm) per evitare elementi sproporzionati.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Mapping, Sequence

from fpdf import FPDF

from pulse_fe_common.datetimes import format_datetime

_FONT_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "static", "vendor", "fonts", "pt-sans-narrow",
)
_FONT_REGULAR = os.path.join(_FONT_DIR, "PTSansNarrow-Regular.ttf")
_FONT_BOLD = os.path.join(_FONT_DIR, "PTSansNarrow-Bold.ttf")
_FONT = "PTSN"

#: Colori di stato coerenti con la UI (badge b-* / grafici).
_STATUS_RGB: dict[str, tuple[int, int, int]] = {
    "ok": (25, 135, 84),
    "warn": (255, 193, 7),
    "error": (220, 53, 69),
    "down": (253, 126, 20),
    "unknown": (108, 117, 125),
}
_DARK_TEXT_STATUS = {"warn"}  # su giallo il testo va scuro per leggibilita'

_BRAND = (13, 71, 161)        # blu intestazione
_BAND = (233, 238, 246)       # sfondo tenue delle bande di sezione
_ROW_ALT = (245, 247, 250)    # riga alternata tabelle
_BORDER = (206, 212, 218)
_MUTED = (108, 117, 125)
_INK = (33, 37, 41)

_STATUS_LABEL = {
    "ok": "OK", "warn": "Warn", "error": "Error",
    "down": "Down", "unknown": "Sconosciuto",
}


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_ms(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.0f} ms"
    except (TypeError, ValueError):
        return "—"


def _fmt_int(value: Any) -> str:
    if value is None:
        return "0"
    try:
        return f"{int(value)}"
    except (TypeError, ValueError):
        return "0"


class _Report(FPDF):
    """PDF A4 verticale con intestazione/pie' di pagina ripetuti."""

    def __init__(self, system_name: str, generated_local: str) -> None:
        super().__init__(orientation="P", unit="mm", format="A4")
        self._system_name = system_name
        self._generated_local = generated_local
        self.set_auto_page_break(True, margin=18)
        self.set_margins(15, 14, 15)
        self.add_font(_FONT, "", _FONT_REGULAR)
        self.add_font(_FONT, "B", _FONT_BOLD)

    # -- intestazione ripetuta -------------------------------------------------
    def header(self) -> None:
        self.set_fill_color(*_BRAND)
        self.rect(0, 0, self.w, 20, style="F")
        self.set_xy(15, 5)
        self.set_text_color(255, 255, 255)
        self.set_font(_FONT, "B", 15)
        self.cell(0, 6, "Pulse — Compendio sistema", new_x="LMARGIN", new_y="NEXT")
        self.set_x(15)
        self.set_font(_FONT, "", 10)
        self.cell(0, 5, self._system_name, new_x="LMARGIN", new_y="NEXT")
        self.set_text_color(*_INK)
        self.set_y(26)

    # -- pie' di pagina ripetuto ----------------------------------------------
    def footer(self) -> None:
        self.set_y(-14)
        self.set_draw_color(*_BORDER)
        self.set_line_width(0.2)
        self.line(15, self.get_y(), self.w - 15, self.get_y())
        self.set_y(-12)
        self.set_font(_FONT, "", 8)
        self.set_text_color(*_MUTED)
        self.cell(0, 6, f"Generato il {self._generated_local}", align="L")
        self.set_y(-12)
        self.cell(0, 6, f"Pagina {self.page_no()} di {{nb}}", align="R")
        self.set_text_color(*_INK)


def _section_title(pdf: _Report, text: str) -> None:
    if pdf.get_y() + 20 > pdf.h - 18:
        pdf.add_page()
    pdf.ln(2)
    pdf.set_fill_color(*_BAND)
    pdf.set_text_color(*_BRAND)
    pdf.set_font(_FONT, "B", 12)
    pdf.cell(0, 8, text, new_x="LMARGIN", new_y="NEXT", fill=True)
    pdf.set_text_color(*_INK)
    pdf.ln(1.5)


def _badge(pdf: _Report, x: float, y: float, w: float, h: float,
           label: str, status: str) -> None:
    st = (status or "unknown").lower()
    rgb = _STATUS_RGB.get(st, _STATUS_RGB["unknown"])
    pdf.set_fill_color(*rgb)
    pdf.rect(x, y, w, h, style="F", round_corners=True, corner_radius=1.2)
    if st in _DARK_TEXT_STATUS:
        pdf.set_text_color(*_INK)
    else:
        pdf.set_text_color(255, 255, 255)
    pdf.set_xy(x, y)
    pdf.set_font(_FONT, "B", 9)
    pdf.cell(w, h, label, align="C")
    pdf.set_text_color(*_INK)


def _kv_table(pdf: _Report, rows: Sequence[tuple[str, str]]) -> None:
    """Tabella chiave/valore su due colonne (intestazione del compendio)."""
    label_w = 42.0
    value_w = pdf.w - 30 - label_w
    pdf.set_font(_FONT, "", 10)
    for key, value in rows:
        pdf.set_x(15)
        pdf.set_font(_FONT, "B", 10)
        pdf.set_text_color(*_MUTED)
        pdf.cell(label_w, 6.5, key, border=0)
        pdf.set_font(_FONT, "", 10)
        pdf.set_text_color(*_INK)
        pdf.multi_cell(value_w, 6.5, value, border=0, new_x="LMARGIN", new_y="NEXT")


def _kpi_grid(pdf: _Report, tiles: Sequence[tuple[str, str]]) -> None:
    """Griglia di KPI: riquadri uniformi, 4 per riga, ben dimensionati."""
    usable = pdf.w - 30
    cols = 4
    gap = 3.0
    tile_w = (usable - gap * (cols - 1)) / cols
    tile_h = 16.0
    x0 = 15
    # y FISSA per riga: si aggiorna solo quando inizia una nuova riga, così
    # tutti i riquadri della stessa riga sono allineati (niente "scaletta").
    row_y = pdf.get_y()
    for i, (label, value) in enumerate(tiles):
        col = i % cols
        if col == 0 and i:
            row_y += tile_h + gap
        x = x0 + col * (tile_w + gap)
        pdf.set_draw_color(*_BORDER)
        pdf.set_fill_color(255, 255, 255)
        pdf.set_line_width(0.2)
        pdf.rect(x, row_y, tile_w, tile_h, style="D", round_corners=True,
                 corner_radius=1.5)
        pdf.set_xy(x, row_y + 2.5)
        pdf.set_font(_FONT, "B", 14)
        pdf.set_text_color(*_BRAND)
        pdf.cell(tile_w, 7, value, align="C")
        pdf.set_xy(x, row_y + 9.5)
        pdf.set_font(_FONT, "", 8.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(tile_w, 5, label, align="C")
    # Posiziona il cursore sotto l'ultima riga di riquadri.
    pdf.set_text_color(*_INK)
    pdf.set_xy(x0, row_y + tile_h + 4)


def _row_fits(pdf: _Report, row_h: float) -> bool:
    return pdf.get_y() + row_h <= pdf.h - 18


def _table(pdf: _Report, headers: Sequence[str], widths: Sequence[float],
           rows: Sequence[Sequence[Any]], aligns: Sequence[str],
           status_col: int | None = None) -> None:
    """Tabella generica con header ripetuto ad ogni pagina e righe alternate.

    ``status_col`` (opzionale) indica la colonna renderizzata come badge di
    stato colorato (il valore della cella e' usato sia come testo sia come stato).
    """
    row_h = 7.0
    header_h = 7.5

    def _draw_header() -> None:
        pdf.set_x(15)
        pdf.set_fill_color(*_BRAND)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font(_FONT, "B", 9.5)
        for title, w, align in zip(headers, widths, aligns):
            pdf.cell(w, header_h, title, border=0, align=align, fill=True)
        pdf.ln(header_h)
        pdf.set_text_color(*_INK)

    _draw_header()
    pdf.set_font(_FONT, "", 9.5)
    for idx, row in enumerate(rows):
        if not _row_fits(pdf, row_h):
            pdf.add_page()
            _draw_header()
            pdf.set_font(_FONT, "", 9.5)
        y = pdf.get_y()
        pdf.set_x(15)
        if idx % 2:
            pdf.set_fill_color(*_ROW_ALT)
            pdf.rect(15, y, sum(widths), row_h, style="F")
        pdf.set_x(15)
        for col, (value, w, align) in enumerate(zip(row, widths, aligns)):
            if status_col is not None and col == status_col:
                st = str(value or "unknown").lower()
                _badge(pdf, pdf.get_x() + 1, y + 1, w - 2, row_h - 2,
                       _STATUS_LABEL.get(st, st), st)
                pdf.set_xy(pdf.get_x() + w, y)
                pdf.set_font(_FONT, "", 9.5)
            else:
                pdf.cell(w, row_h, str(value), border=0, align=align)
        pdf.ln(row_h)
    # bordo inferiore della tabella
    pdf.set_draw_color(*_BORDER)
    pdf.set_line_width(0.2)
    pdf.line(15, pdf.get_y(), 15 + sum(widths), pdf.get_y())
    pdf.ln(2)


def _line_chart(pdf: _Report, samples: Sequence[Mapping[str, Any]]) -> None:
    """Grafico a linee compatto del response_ms nel periodo (dimensionato A4)."""
    values = []
    for s in samples:
        v = s.get("response_ms")
        try:
            values.append(float(v))
        except (TypeError, ValueError):
            continue
    if len(values) < 2:
        pdf.set_font(_FONT, "", 9.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "Dati insufficienti per il grafico del tempo di risposta.",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)
        return
    box_w = pdf.w - 30
    box_h = 38.0
    if not _row_fits(pdf, box_h + 4):
        pdf.add_page()
    x0 = 15.0
    y0 = pdf.get_y()
    pdf.set_draw_color(*_BORDER)
    pdf.set_fill_color(255, 255, 255)
    pdf.set_line_width(0.2)
    pdf.rect(x0, y0, box_w, box_h, style="D")
    vmax = max(values)
    vmin = min(values)
    span = (vmax - vmin) or 1.0
    pad = 4.0
    plot_w = box_w - 2 * pad
    plot_h = box_h - 2 * pad
    n = len(values)
    pdf.set_draw_color(*_BRAND)
    pdf.set_line_width(0.4)
    prev = None
    for i, v in enumerate(values):
        px = x0 + pad + plot_w * (i / (n - 1))
        py = y0 + pad + plot_h * (1 - (v - vmin) / span)
        if prev is not None:
            pdf.line(prev[0], prev[1], px, py)
        prev = (px, py)
    pdf.set_font(_FONT, "", 8)
    pdf.set_text_color(*_MUTED)
    pdf.set_xy(x0 + 1, y0 + 0.5)
    pdf.cell(0, 4, f"max {vmax:.0f} ms")
    pdf.set_xy(x0 + 1, y0 + box_h - 4.5)
    pdf.cell(0, 4, f"min {vmin:.0f} ms")
    pdf.set_text_color(*_INK)
    pdf.set_y(y0 + box_h + 2)


def build_report_pdf(system: Mapping[str, Any], checks: Mapping[str, Any],
                     period: Mapping[str, Any], data: Mapping[str, Any],
                     *, now: datetime | None = None) -> bytes:
    """Costruisce il PDF del compendio e ne ritorna i byte (header ``%PDF``).

    ``system``/``checks`` sono le risposte del backend; ``period`` e ``data``
    provengono dalla vista Compendio (stessi dati mostrati a schermo).
    """
    tz_name = period.get("tz_name") or "Europe/Rome"
    generated = format_datetime(now or datetime.now(), tz_name)
    name = system.get("system_name") or system.get("system_id") or "Sistema"
    pdf = _Report(str(name), generated)
    pdf.alias_nb_pages()
    pdf.add_page()

    skind = (system.get("kind") or "http").lower()
    kind_label = "Connettività TCP" if skind == "tcp" else "HTTP heartbeat"
    _section_title(pdf, "Intestazione")
    _kv_table(pdf, [
        ("System ID", str(system.get("system_id") or "—")),
        ("Nome", str(system.get("system_name") or "—")),
        ("Tipo di controllo", kind_label),
        ("Sonda", str(system.get("probe_id") or "—")),
        ("Periodo", f"{period.get('from_local', '—')}  —  {period.get('to_local', '—')}"),
    ])

    overall = data.get("overall") or {}
    worst = data.get("worst") or "unknown"
    distribution = data.get("distribution") or []
    _section_title(pdf, "Stato complessivo nel periodo")
    y = pdf.get_y()
    _badge(pdf, 15, y, 42, 9, _STATUS_LABEL.get(worst, worst), worst)
    pdf.set_xy(60, y)
    pdf.set_font(_FONT, "", 10)
    pdf.set_text_color(*_MUTED)
    dist_txt = "  ·  ".join(
        f"{_STATUS_LABEL.get(d['status'], d['status'])}: {d['count']}"
        for d in distribution
    ) or "Nessun campione nel periodo."
    pdf.cell(0, 9, f"Uptime {_fmt_pct(overall.get('uptime'))}   |   {dist_txt}")
    pdf.set_text_color(*_INK)
    pdf.ln(12)

    _section_title(pdf, "Indicatori (KPI)")
    _kpi_grid(pdf, [
        ("Uptime", _fmt_pct(overall.get("uptime"))),
        ("Resp. medio", _fmt_ms(overall.get("avg_response_ms"))),
        ("Resp. minimo", _fmt_ms(overall.get("min_response_ms"))),
        ("Resp. massimo", _fmt_ms(overall.get("max_response_ms"))),
        ("Campioni", _fmt_int(overall.get("count"))),
        ("Check", _fmt_int(len(checks.get("items") or []))),
        ("Incidenti", _fmt_int((data.get("alarms") or {}).get("total"))),
        ("Stato peggiore", _STATUS_LABEL.get(worst, worst)),
    ])

    _section_title(pdf, "Dettaglio per check")
    per_check = data.get("per_check") or []
    widths = [42, 26, 24, 22, 22, 44]
    aligns = ["L", "C", "R", "R", "R", "L"]
    headers = ["Check", "Ultimo stato", "Uptime", "Avg", "Max", "Ultimo contatto"]
    if per_check:
        rows = []
        for c in per_check:
            aggs = c.get("aggs") or {}
            rows.append([
                c.get("check_name") or c.get("check_id") or "—",
                (c.get("last_status") or "unknown"),
                _fmt_pct(aggs.get("uptime")),
                _fmt_ms(aggs.get("avg_response_ms")),
                _fmt_ms(aggs.get("max_response_ms")),
                format_datetime(c.get("last_seen_at"), tz_name),
            ])
        _table(pdf, headers, widths, rows, aligns, status_col=1)
    else:
        pdf.set_font(_FONT, "", 9.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "Nessun check scoperto per questo sistema.",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)
        pdf.ln(1)

    alarms = (data.get("alarms") or {}).get("items") or []
    _section_title(pdf, "Allarmi / incidenti nel periodo")
    if alarms:
        a_widths = [30, 45, 45, 60]
        a_aligns = ["C", "L", "L", "L"]
        a_headers = ["Stato", "Aperto", "Riconosciuto", "Risolto"]
        rows = []
        for a in alarms:
            rows.append([
                (a.get("status") or "unknown"),
                format_datetime(a.get("opened_at"), tz_name),
                format_datetime(a.get("acknowledged_at"), tz_name),
                format_datetime(a.get("resolved_at"), tz_name),
            ])
        _table(pdf, a_headers, a_widths, rows, a_aligns, status_col=0)
    else:
        pdf.set_font(_FONT, "", 9.5)
        pdf.set_text_color(*_MUTED)
        pdf.cell(0, 6, "Nessun allarme nel periodo selezionato.",
                 new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(*_INK)
        pdf.ln(1)

    _section_title(pdf, "Andamento tempo di risposta")
    _line_chart(pdf, data.get("samples") or [])

    return bytes(pdf.output())
