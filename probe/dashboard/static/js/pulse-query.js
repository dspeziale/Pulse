/*
 * pulse-query.js (Sonda) — Interrogazione diretta guidata (PP-04).
 *
 * Coordina i filtri guidati (Sistema -> Check, Stato, Periodo) e la tabella
 * risultati DataTables server-side (adattatore locale /dt/heartbeats). Senza
 * dipendenze/CDN: fetch per il proxy dei check, jQuery (gia' presente per
 * DataTables) per serializzare i parametri della richiesta ajax.
 *
 * A differenza del Server, la Sonda e' unica: i Sistemi sono resi lato server
 * nel <select> #q-system; il Check e' un input con datalist (suggerimenti dai
 * check distinti del sistema + testo libero, dato che la Sonda non espone un
 * endpoint dedicato ai check).
 *
 * Contratto DOM (id, dentro [data-query-app]): q-system, q-check,
 * q-check-options, q-status, q-preset, q-from, q-to, q-custom, q-apply,
 * q-only-problems, q-results, q-summary, q-presets (JSON), q-columns (JSON).
 * Attributi contenitore: data-checks-url, data-hb-url, data-tz-offset (minuti).
 */
(function (window) {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  function getJson(url) {
    return fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .catch(function () { return { items: [] }; });
  }

  function init() {
    var root = document.querySelector("[data-query-app]");
    if (!root || typeof window.DataTable === "undefined") { return; }

    var system = byId("q-system"), check = byId("q-check"),
        checkOpts = byId("q-check-options"), status = byId("q-status"),
        preset = byId("q-preset"), fromEl = byId("q-from"), toEl = byId("q-to"),
        custom = byId("q-custom"), applyBtn = byId("q-apply"),
        problemsBtn = byId("q-only-problems"), summary = byId("q-summary");

    var checksUrl = root.getAttribute("data-checks-url");
    var hbUrl = root.getAttribute("data-hb-url");
    var offsetMin = parseInt(root.getAttribute("data-tz-offset"), 10) || 0;
    var presets = JSON.parse((byId("q-presets") || {}).textContent || "{}");
    var columns = JSON.parse((byId("q-columns") || {}).textContent || "[]");

    function toUtc(local) {
      if (!local) { return ""; }
      var d = new Date(local + ":00Z");            // ora "di parete" come UTC
      if (isNaN(d.getTime())) { return ""; }
      d.setMinutes(d.getMinutes() - offsetMin);    // -> UTC reale
      return d.toISOString().replace(/\.\d{3}Z$/, "Z");
    }

    function currentRange() {
      if (preset.value === "custom") {
        return { from: toUtc(fromEl.value), to: toUtc(toEl.value) };
      }
      var p = presets[preset.value];
      return p ? { from: p.from, to: p.to } : {};
    }

    function updateSummary(json) {
      if (!summary) { return; }
      var n = (json && json.recordsTotal) || 0;
      summary.textContent = n === 0
        ? "Nessun heartbeat per i filtri selezionati."
        : (n + " heartbeat trovati.");
    }

    var table = window.PulseDT.init("#q-results", {
      searching: false,
      pageLength: 50,
      order: [[0, "desc"]],
      columns: columns,
      ajax: function (data, callback) {
        var range = currentRange();
        if (system.value) { data.system_id = system.value; }
        if (check.value) { data.check_id = check.value; }
        if (status.value) { data.status = status.value; }
        if (range.from) { data.from = range.from; }
        if (range.to) { data.to = range.to; }
        window.jQuery.ajax({ url: hbUrl, data: data, dataType: "json" })
          .done(function (json) { callback(json); updateSummary(json); })
          .fail(function () {
            var empty = { draw: data.draw, recordsTotal: 0,
                          recordsFiltered: 0, data: [] };
            callback(empty); updateSummary(empty);
          });
      }
    });

    function reload() { table.ajax.reload(); }

    system.addEventListener("change", function () {
      check.value = "";
      checkOpts.innerHTML = "";
      if (system.value) {
        getJson(checksUrl + "?system_id=" + encodeURIComponent(system.value))
          .then(function (d) {
            (d.items || []).forEach(function (c) {
              var opt = document.createElement("option");
              opt.value = c.check_id || "";
              if (c.check_name) { opt.label = c.check_name; }
              checkOpts.appendChild(opt);
            });
          });
      }
      reload();
    });

    [check, status].forEach(function (el) {
      el.addEventListener("change", reload);
    });
    preset.addEventListener("change", function () {
      custom.style.display = preset.value === "custom" ? "" : "none";
      reload();
    });
    [fromEl, toEl].forEach(function (el) {
      el.addEventListener("change", reload);
    });
    if (applyBtn) {
      applyBtn.addEventListener("click", function (e) {
        e.preventDefault(); reload();
      });
    }
    if (problemsBtn) {
      problemsBtn.addEventListener("click", function (e) {
        e.preventDefault();
        status.value = "error";  // l'endpoint filtra un solo stato: gli errori
        reload();
      });
    }

    custom.style.display = preset.value === "custom" ? "" : "none";
    updateSummary(null);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
