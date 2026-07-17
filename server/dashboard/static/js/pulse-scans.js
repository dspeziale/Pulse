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

  function initList() {
    var root = document.querySelector("[data-scans-app]");
    if (!root || typeof window.DataTable === "undefined") { return; }
    var probe = document.getElementById("scan-probe");
    var summary = document.getElementById("scan-summary");
    var urlTmpl = root.getAttribute("data-dt-url");
    var colsEl = document.getElementById("scan-columns");
    var columns = JSON.parse((colsEl && colsEl.textContent) || "[]");

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
        }).done(function (json) { callback(json); updateSummary(json); })
          .fail(function () { callback(empty); updateSummary(empty); });
      }
    });

    if (probe) {
      probe.addEventListener("change", function () { table.ajax.reload(); });
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
