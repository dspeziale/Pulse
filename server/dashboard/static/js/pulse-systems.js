/*
 * pulse-systems.js — auto-popolamento dei Sistemi in base alla Sonda.
 *
 * Riutilizzabile e senza dipendenze/CDN. Si aggancia a ogni <select> di Sonda
 * marcato con data-probe-source (URL della rotta proxy /systems-by-probe) e,
 * al cambio di Sonda, ripopola il target indicato da data-systems-target con i
 * soli sistemi di quella Sonda.
 *
 * Modalità (data-systems-mode):
 *   - "select"   : ripopola le <option> di un <select> (mantiene placeholder e,
 *                  se possibile, la selezione corrente indicata da
 *                  data-systems-current).
 *   - "datalist" : ripopola le <option value> di un <datalist> (suggerimenti per
 *                  un <input> con list=...). Additivo: l'input resta editabile.
 *   - "list"     : ricostruisce un elenco <ul>/<ol> di <li> descrittivi.
 *
 * Fallback: se il JS è disabilitato, resta valido il rendering server-side
 * eventualmente già presente nel target (non viene toccato finché non cambia
 * la Sonda).
 */
(function () {
  "use strict";

  function esc(v) {
    return v === null || v === undefined ? "" : String(v);
  }

  function fillSelect(target, items) {
    var current = target.getAttribute("data-systems-current") || target.value || "";
    var placeholder = target.getAttribute("data-systems-placeholder");
    target.innerHTML = "";
    if (placeholder !== null) {
      var opt0 = document.createElement("option");
      opt0.value = "";
      opt0.textContent = placeholder;
      target.appendChild(opt0);
    }
    items.forEach(function (s) {
      var opt = document.createElement("option");
      opt.value = esc(s.system_id);
      opt.textContent = esc(s.system_id) +
        (s.system_name ? " — " + esc(s.system_name) : "");
      if (opt.value && opt.value === current) {
        opt.selected = true;
      }
      target.appendChild(opt);
    });
  }

  function fillDatalist(target, items) {
    target.innerHTML = "";
    items.forEach(function (s) {
      var opt = document.createElement("option");
      opt.value = esc(s.system_id);
      if (s.system_name) {
        opt.label = esc(s.system_name);
      }
      target.appendChild(opt);
    });
  }

  function fillList(target, items) {
    target.innerHTML = "";
    if (!items.length) {
      var li = document.createElement("li");
      li.className = "text-body-secondary";
      li.textContent = target.getAttribute("data-systems-empty") ||
        "Nessun sistema per questa Sonda.";
      target.appendChild(li);
      return;
    }
    items.forEach(function (s) {
      var li = document.createElement("li");
      var code = document.createElement("code");
      code.textContent = esc(s.system_id);
      li.appendChild(code);
      if (s.system_name) {
        li.appendChild(document.createTextNode(" — " + esc(s.system_name)));
      }
      target.appendChild(li);
    });
  }

  function populate(target, mode, items) {
    if (mode === "select") {
      fillSelect(target, items);
    } else if (mode === "datalist") {
      fillDatalist(target, items);
    } else {
      fillList(target, items);
    }
    // Dopo il primo caricamento la "selezione corrente" è consumata.
    target.removeAttribute("data-systems-current");
  }

  function wire(select) {
    var source = select.getAttribute("data-probe-source");
    var targetSel = select.getAttribute("data-systems-target");
    if (!source || !targetSel) {
      return;
    }
    var target = document.querySelector(targetSel);
    if (!target) {
      return;
    }
    var mode = select.getAttribute("data-systems-mode") || "select";

    function refresh() {
      var probeId = select.value || "";
      if (!probeId) {
        populate(target, mode, []);
        return;
      }
      var url = source + (source.indexOf("?") === -1 ? "?" : "&") +
        "probe_id=" + encodeURIComponent(probeId);
      fetch(url, { headers: { Accept: "application/json" } })
        .then(function (r) { return r.ok ? r.json() : { items: [] }; })
        .then(function (data) {
          populate(target, mode, (data && data.items) || []);
        })
        .catch(function () { /* silenzioso: resta il contenuto precedente */ });
    }

    select.addEventListener("change", refresh);

    // Popolamento iniziale opt-in (data-systems-init): utile quando una Sonda è
    // già selezionata al caricamento e il target non è reso lato server.
    if (select.hasAttribute("data-systems-init") && select.value) {
      refresh();
    }
  }

  function init() {
    var selects = document.querySelectorAll("[data-probe-source]");
    Array.prototype.forEach.call(selects, wire);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
