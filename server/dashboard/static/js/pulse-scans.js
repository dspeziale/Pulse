/*
 * pulse-scans.js — Scansioni NMAP: elenco (DataTables server-side) e polling
 * del dettaglio. Nessuna dipendenza/CDN (usa jQuery, gia' presente, per l'ajax
 * DataTables e fetch per il polling).
 *
 * INDEX ([data-scans-app]): la tabella #scan-results carica /dt/scans/<probe>
 * dove <probe> = valore di #scan-probe; al cambio Sonda ricarica. Senza Sonda
 * mostra tabella vuota.
 *
 * DETTAGLIO ([data-scan-poll]): se la scansione e' in corso, interroga l'URL
 * JSON ogni 4s e ricarica la pagina quando termina (done/failed).
 */
(function (window) {
  "use strict";

  var POLL_MS = 4000;
  var LIST_REFRESH_MS = 5000;   // auto-refresh elenco mentre ci sono scansioni in corso
  var LAST_PROBE_KEY = "pulse-scans-last-probe";

  function initList() {
    var root = document.querySelector("[data-scans-app]");
    if (!root || typeof window.DataTable === "undefined") { return; }
    var probe = document.getElementById("scan-probe");
    var summary = document.getElementById("scan-summary");
    var urlTmpl = root.getAttribute("data-dt-url");
    var colsEl = document.getElementById("scan-columns");
    var columns = JSON.parse((colsEl && colsEl.textContent) || "[]");
    var refreshTimer = null;

    function hasRunning(json) {
      // L'elenco e' renderizzato server-side: lo stato "running" compare come
      // testo del badge. Rileva se serve continuare l'auto-refresh.
      try { return JSON.stringify(json.data || []).indexOf("running") !== -1; }
      catch (e) { return false; }
    }
    function scheduleRefresh(json) {
      if (refreshTimer) { window.clearTimeout(refreshTimer); refreshTimer = null; }
      if (probe && probe.value && hasRunning(json)) {
        refreshTimer = window.setTimeout(function () { table.ajax.reload(null, false); },
                                         LIST_REFRESH_MS);
      }
    }

    function updateSummary(json) {
      if (!summary) { return; }
      if (!probe || !probe.value) {
        summary.textContent = "Seleziona una Sonda per vederne le scansioni.";
        return;
      }
      var n = (json && json.recordsTotal) || 0;
      summary.textContent = n === 0
        ? "Nessuna scansione per questa Sonda."
        : (n + " scansioni.");
    }

    var table = window.PulseDT.init("#scan-results", {
      searching: false,
      ordering: false,
      pageLength: 25,
      columns: columns,
      ajax: function (data, callback) {
        var pid = probe ? probe.value : "";
        var empty = { draw: data.draw, recordsTotal: 0, recordsFiltered: 0,
                      data: [] };
        if (!pid) { callback(empty); updateSummary(empty); return; }
        window.jQuery.ajax({
          url: urlTmpl.replace("__PID__", encodeURIComponent(pid)),
          data: data, dataType: "json"
        }).done(function (json) { callback(json); updateSummary(json); scheduleRefresh(json); })
          .fail(function () { callback(empty); updateSummary(empty); });
      }
    });

    if (probe) {
      probe.addEventListener("change", function () {
        try {
          if (probe.value) { window.localStorage.setItem(LAST_PROBE_KEY, probe.value); }
          else { window.localStorage.removeItem(LAST_PROBE_KEY); }
        } catch (e) { /* storage negato: ignora */ }
        table.ajax.reload();
      });
      // Ripristina l'ultima Sonda selezionata se la pagina non ne impone una
      // (cosi', tornando alle Scansioni, si rivedono subito le sue scansioni).
      if (!probe.value) {
        var last = null;
        try { last = window.localStorage.getItem(LAST_PROBE_KEY); } catch (e) { last = null; }
        if (last && probe.querySelector('option[value="' + (window.CSS && CSS.escape ? CSS.escape(last) : last) + '"]')) {
          probe.value = last;
          table.ajax.reload();
        }
      }
    }
    updateSummary(null);
  }

  function initPoll() {
    var root = document.querySelector("[data-scan-poll]");
    if (!root || root.getAttribute("data-running") !== "true") { return; }
    var url = root.getAttribute("data-poll-url");
    var timer = window.setInterval(function () {
      fetch(url, { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.running === false) {
            window.clearInterval(timer);
            window.location.reload();
          }
        })
        .catch(function () { /* silenzioso: ritenta al prossimo tick */ });
    }, POLL_MS);
  }

  function init() { initList(); initPoll(); }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
