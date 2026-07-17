"""P-18 Configurazione. REST: GET /config, PUT /config."""
from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from pulse_fe_common.auth import permission_required

from sdk import api_get, api_put

bp = Blueprint("config_bp", __name__)


# ---------------------------------------------------------------------------
# Raggruppamento dei parametri in schede (tab).
#
# Ogni gruppo e' definito da: id (usato per gli id HTML tab/pane), etichetta,
# icona bootstrap-icons, insieme di key esatte e un eventuale prefisso.
# L'ordine della lista e' l'ordine di rendering delle tab. Il gruppo "other"
# e' il FALLBACK: qualunque key non mappata vi confluisce, cosi' nessun
# parametro sparisce se in futuro il backend ne aggiunge di nuovi. La scheda
# "Altro" viene mostrata solo se contiene almeno un parametro (i gruppi vuoti
# non vengono emessi).
# ---------------------------------------------------------------------------
# Fusi orari IANA proposti nel <select> della UI (il valore corrente, se diverso,
# viene comunque aggiunto come opzione dal template così da non perderlo).
COMMON_TIMEZONES = [
    "Europe/Rome", "UTC", "Europe/London", "Europe/Paris", "Europe/Berlin",
    "America/New_York", "America/Los_Angeles", "Asia/Tokyo",
]

_GROUP_DEFS = [
    ("localization", "Localizzazione", "bi-globe",
     frozenset({"timezone"}), None),
    ("network", "Rete & porte", "bi-hdd-network",
     frozenset({"api_port", "probe_endpoint_port"}), None),
    ("auth", "Autenticazione", "bi-shield-lock",
     frozenset({"access_token_ttl_seconds", "refresh_token_ttl_seconds",
                "failed_login_threshold"}), None),
    ("probes", "Sonde", "bi-broadcast",
     frozenset({"probe_offline_timeout_seconds"}), None),
    ("retention", "Retention", "bi-clock-history",
     frozenset(), "retention_"),
    ("other", "Altro", "bi-three-dots",
     frozenset(), None),
]

# Etichette leggibili per i parametri noti. Per le key non presenti si ripiega
# su una versione "prettified" della key tecnica (vedi _prettify).
_LABELS = {
    "timezone": "Fuso orario",
    "api_port": "Porta API",
    "probe_endpoint_port": "Porta endpoint sonde",
    "access_token_ttl_seconds": "Durata access token",
    "refresh_token_ttl_seconds": "Durata refresh token",
    "failed_login_threshold": "Soglia login falliti",
    "probe_offline_timeout_seconds": "Timeout sonda offline",
    "retention_system_logs_days": "Retention log di sistema",
    "retention_notification_deliveries_days": "Retention invii notifiche",
    "retention_inbound_commands_days": "Retention comandi in ingresso",
    "retention_probe_rollups_days": "Retention rollup sonde",
}


def _prettify(key: str) -> str:
    """Etichetta di ripiego per una key non mappata: underscori -> spazi."""
    return key.replace("_", " ").strip().capitalize() or key


def _unit_for(key: str) -> str:
    """Unita' deducibile dal suffisso della key (hint accanto al campo)."""
    if key.endswith("_seconds"):
        return "secondi"
    if key.endswith("_days"):
        return "giorni"
    return ""


def _group_id_for(key: str) -> str:
    """Restituisce l'id del gruppo per una key, con fallback esplicito 'other'."""
    for gid, _label, _icon, keys, prefix in _GROUP_DEFS:
        if key in keys or (prefix and key.startswith(prefix)):
            return gid
    return "other"


def build_config_groups(items):
    """Raggruppa e arricchisce i parametri di configurazione per il template.

    Ritorna una lista ordinata di gruppi non vuoti:
      {"id", "label", "icon", "items": [<item arricchito con label/unit>]}
    Ogni item conserva i campi originari (key/value/type/sensitive/
    requires_restart/description) e aggiunge "label" (leggibile) e "unit".
    Nessun parametro viene perso: le key non mappate finiscono in "other".
    """
    buckets: dict = {gid: [] for gid, *_ in _GROUP_DEFS}
    for item in items or []:
        key = item.get("key", "")
        enriched = dict(item)
        enriched["label"] = _LABELS.get(key) or _prettify(key)
        enriched["unit"] = _unit_for(key)
        buckets[_group_id_for(key)].append(enriched)

    groups = []
    for gid, label, icon, _keys, _prefix in _GROUP_DEFS:
        if buckets[gid]:
            groups.append({"id": gid, "label": label, "icon": icon,
                           "items": buckets[gid]})
    return groups


@bp.route("/config")
@permission_required("config.read")
def show_config():
    data = api_get("/config")
    groups = build_config_groups(data.get("items") or [])
    return render_template("config/list.html", data=data, groups=groups,
                           common_timezones=COMMON_TIMEZONES)


@bp.route("/config", methods=["POST"])
@permission_required("config.update")
def update_config():
    items = []
    # I campi del form sono nominati "value:<key>".
    for field, value in request.form.items():
        if field.startswith("value:"):
            items.append({"key": field[len("value:"):], "value": value})
    result = api_put("/config", json={"items": items})
    updated = ", ".join(result.get("updated", [])) or "nessuno"
    flash(f"Parametri aggiornati: {updated}.", "success")
    if result.get("requires_restart"):
        flash("Alcuni parametri richiedono il riavvio del servizio.", "warning")
    return redirect(url_for("config_bp.show_config"))
