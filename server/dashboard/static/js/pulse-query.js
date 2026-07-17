/*
 * pulse-query.js — Interrogazione dati guidata (P-04).
 *
 * Coordina i filtri guidati (Sonda -> Sistema -> Check, Stato, Periodo) e la
 * tabella risultati DataTables server-side (adattatore /dt/heartbeats/<probe>).
 * Senza dipendenze/CDN: usa fetch per i proxy JSON e jQuery (gia' presente per
 * DataTables) solo per serializzare i parametri della richiesta ajax.
 *
 * Contratto DOM (elementi per id, dentro un contenitore [data-query-app]):
 *   q-probe, q-system, q-check, q-status, q-preset, q-from, q-to, q-custom,
 *   q-apply, q-only-problems, q-results (tabella), q-summary (riepilogo),
 *   q-presets (JSON preset), q-columns (JSON colonne DataTables).
 * Attributi del contenitore: data-systems-url, data-checks-url, data-hb-url
 *   (con segnaposto __PID__), data-tz-offset (minuti).
 */
(function (window) {
  "use strict";

  function byId(id) { return document.getElementById(id); }

  function getJson(url) {
    return fetch(url, { headers: { Accept: "application/json" } })
      .then(function (r) { return r.ok ? r.json() : { items: [] }; })
      .catch(function () { return { items: [] }; });
  }

  function fillSelect(sel, items, valueKey, labelFn, placeholder) {
    sel.innerHTML = "";
    var opt0 = document.createElement("option");
    opt0.value = "";
    opt0.textContent = placeholder;
    sel.appendChild(opt0);
    items.forEach(function (it) {
      var opt = document.createElement("option");
      opt.value = it[valueKey] || "";
      opt.textContent = labelFn(it);
      sel.appendChild(opt);
    });
  }

  function init() {
    var root = document.querySelector("[data-query-app]");
    if (!root || typeof window.DataTable === "undefined") { return; }

    var probe = byId("q-probe"), system = byId("q-system"),
        check = byId("q-check"), status = byId("q-status"),
        preset = byId("q-preset"), fromEl = byId("q-from"), toEl = byId("q-to"),
        custom = byId("q-custom"), applyBtn = byId("q-apply"),
        problemsBtn = byId("q-only-problems"), summary = byId("q-summary");

    var systemsUrl = root.getAttribute("data-systems-url");
    var checksUrl = root.getAttribute("data-checks-url");
    var hbTmpl = root.getAttribute("data-hb-url");   // contiene __PID__
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
      if (!probe.value) {
        summary.textContent = "Seleziona una Sonda per interrogare i dati.";
        return;
      }
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
        var pid = probe.value;
        var empty = { draw: data.draw, recordsTotal: 0, recordsFiltered: 0,
                      data: [] };
        if (!pid) { callback(empty); updateSummary(empty); return; }
        var range = currentRange();
        if (system.value) { data.system_id = system.value; }
        if (check.value) { data.check_id = check.value; }
        if (status.value) { data.status = status.value; }
        if (range.from) { data.from = range.from; }
        if (range.to) { data.to = range.to; }
        window.jQuery.ajax({
          url: hbTmpl.replace("__PID__", encodeURIComponent(pid)),
          data: data, dataType: "json"
        }).done(function (json) { callback(json); updateSummary(json); })
          .fail(function () { callback(empty); updateSummary(empty); });
      }
    });

    function reload() { table.ajax.reload(); }

    probe.addEventListener("change", function () {
      fillSelect(system, [], "system_id", function () { return ""; },
                 "Tutti i sistemi");
      fillSelect(check, [], "check_id", function () { return ""; },
                 "Tutti i check");
      if (probe.value) {
        getJson(systemsUrl + "?probe_id=" + encodeURIComponent(probe.value))
          .then(function (d) {
            fillSelect(system, d.items || [], "system_id", function (s) {
              return (s.system_id || "") +
                (s.system_name ? " — " + s.system_name : "");
            }, "Tutti i sistemi");
          });
      }
      reload();
    });

    system.addEventListener("change", function () {
      fillSelect(check, [], "check_id", function () { return ""; },
                 "Tutti i check");
      if (system.value && probe.value) {
        getJson(checksUrl + "?system_id=" + encodeURIComponent(system.value) +
                "&probe_id=" + encodeURIComponent(probe.value))
          .then(function (d) {
            fillSelect(check, d.items || [], "check_id", function (c) {
              return (c.check_id || "") +
                (c.check_name ? " — " + c.check_name : "");
            }, "Tutti i check");
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
        // L'endpoint heartbeat filtra un solo stato: si punta agli errori
        // (l'anomalia piu' grave). Stato/Check restano poi liberi per warn/down.
        status.value = "error";
        reload();
      });
    }

    // Stato iniziale: mostra/nasconde l'intervallo personalizzato e, se una
    // Sonda e' preselezionata (?probe_id=), popola subito i sistemi.
    custom.style.display = preset.value === "custom" ? "" : "none";
    if (probe.value) {
      getJson(systemsUrl + "?probe_id=" + encodeURIComponent(probe.value))
        .then(function (d) {
          fillSelect(system, d.items || [], "system_id", function (s) {
            return (s.system_id || "") +
              (s.system_name ? " — " + s.system_name : "");
          }, "Tutti i sistemi");
        });
    }
    updateSummary(null);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window);
