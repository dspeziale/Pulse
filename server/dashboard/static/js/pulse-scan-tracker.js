/*
 * pulse-scan-tracker.js — indicatore GLOBALE delle scansioni NMAP in corso.
 *
 * Le scansioni sono asincrone lato Sonda: una volta avviate proseguono anche se
 * l'operatore cambia pagina. Questo modulo persiste in localStorage le scansioni
 * avviate/aperte e mostra un widget fisso su OGNI pagina della dashboard, con
 * polling periodico dello stato. Cosi' e' sempre possibile cambiare pagina e
 * "riprendere" (riaprire) una scansione ancora in corso, oppure sapere quando e'
 * terminata. Nessun CDN, nessuna dipendenza (solo fetch + localStorage).
 *
 * Registrazione: la pagina di dettaglio scansione espone [data-scan-track] con i
 * dati necessari; ogni scansione aperta viene tracciata finche' non termina.
 */
(function (window, document) {
  "use strict";

  var KEY = "pulse-active-scans";
  var POLL_MS = 5000;
  var MAX = 12;                 // cap difensivo sul numero di elementi tracciati
  var DONE_TTL_MS = 1800000;    // rimuovi le completate dopo 30 min

  // ---- persistenza ---------------------------------------------------------
  function load() {
    try {
      var v = JSON.parse(window.localStorage.getItem(KEY) || "[]");
      return Array.isArray(v) ? v : [];
    } catch (e) { return []; }
  }
  function save(list) {
    try { window.localStorage.setItem(KEY, JSON.stringify(list.slice(0, MAX))); }
    catch (e) { /* storage negato/pieno: ignora */ }
  }
  function keyOf(s) { return s.probeId + "/" + s.scanId; }

  function upsert(entry) {
    var list = load(), i;
    for (i = 0; i < list.length; i++) {
      if (keyOf(list[i]) === keyOf(entry)) {
        list[i].probeName = entry.probeName || list[i].probeName;
        list[i].target = entry.target || list[i].target;
        list[i].detailUrl = entry.detailUrl || list[i].detailUrl;
        list[i].pollUrl = entry.pollUrl || list[i].pollUrl;
        if (entry.status) { list[i].status = entry.status; }
        save(list);
        return;
      }
    }
    entry.status = entry.status || "running";
    list.unshift(entry);
    save(list);
  }
  function setStatus(k, status, finishedTs) {
    var list = load(), i;
    for (i = 0; i < list.length; i++) {
      if (keyOf(list[i]) === k) {
        list[i].status = status;
        if (finishedTs) { list[i].finishedTs = finishedTs; }
      }
    }
    save(list);
  }
  function removeKey(k) {
    save(load().filter(function (s) { return keyOf(s) !== k; }));
  }
  function prune() {
    var now = Date.now();
    save(load().filter(function (s) {
      if (s.status && s.status !== "running" && s.finishedTs) {
        return (now - s.finishedTs) < DONE_TTL_MS;
      }
      return true;
    }));
  }

  // ---- helpers -------------------------------------------------------------
  var RUNNING = { running: 1, pending: 1, queued: 1 };
  function isRunning(s) { return !!RUNNING[s]; }
  function esc(t) {
    var d = document.createElement("div");
    d.textContent = t == null ? "" : String(t);
    return d.innerHTML;
  }

  // ---- widget --------------------------------------------------------------
  var box = null;

  function ensureBox() {
    if (box) { return box; }
    box = document.createElement("div");
    box.className = "pulse-scan-tracker card shadow position-fixed bottom-0 end-0 m-3";
    box.style.zIndex = "1085";
    box.style.width = "22rem";
    box.style.maxWidth = "92vw";
    box.setAttribute("role", "status");
    box.setAttribute("aria-live", "polite");
    document.body.appendChild(box);
    return box;
  }

  function render() {
    var list = load();
    var running = list.filter(function (s) { return isRunning(s.status); });
    var done = list.filter(function (s) { return !isRunning(s.status); });

    if (!list.length) { if (box) { box.remove(); box = null; } return; }

    var b = ensureBox();
    var html = "";
    html += '<div class="card-header d-flex align-items-center justify-content-between py-2">';
    html += '<span class="fw-semibold">';
    if (running.length) {
      html += '<span class="spinner-border spinner-border-sm me-2 align-middle"></span>';
      html += 'Scansioni in corso (' + running.length + ')';
    } else {
      html += '<i class="bi bi-check2-circle text-success me-2"></i>Scansioni completate';
    }
    html += '</span>';
    html += '<button type="button" class="btn-close btn-sm" aria-label="Nascondi" data-scan-hide></button>';
    html += '</div>';
    html += '<ul class="list-group list-group-flush pulse-scan-tracker-list" style="max-height:15rem;overflow:auto">';

    function row(s) {
      var run = isRunning(s.status);
      var icon = run
        ? '<span class="spinner-border spinner-border-sm text-warning me-2"></span>'
        : (s.status === "failed" || s.status === "error"
            ? '<i class="bi bi-x-octagon text-danger me-2"></i>'
            : '<i class="bi bi-check-circle text-success me-2"></i>');
      var label = esc(s.target || s.scanId);
      var sub = esc(s.probeName || "");
      var action = run
        ? '<a class="btn btn-sm btn-primary" href="' + esc(s.detailUrl) + '"><i class="bi bi-arrow-right-circle me-1"></i>Riprendi</a>'
        : '<a class="btn btn-sm btn-outline-secondary" href="' + esc(s.detailUrl) + '">Vedi</a>';
      var dismiss = run ? "" :
        '<button type="button" class="btn btn-sm btn-link text-body-secondary px-1" title="Rimuovi" data-scan-dismiss="' + esc(keyOf(s)) + '"><i class="bi bi-x-lg"></i></button>';
      return '<li class="list-group-item d-flex align-items-center gap-2 py-2">' +
        icon +
        '<span class="flex-grow-1 text-truncate"><span class="d-block text-truncate">' + label + '</span>' +
        (sub ? '<small class="text-body-secondary d-block text-truncate">' + sub + '</small>' : '') +
        '</span>' + action + dismiss + '</li>';
    }

    running.forEach(function (s) { html += row(s); });
    done.forEach(function (s) { html += row(s); });
    html += '</ul>';
    if (done.length) {
      html += '<div class="card-footer py-1 text-end">' +
        '<button type="button" class="btn btn-sm btn-link text-body-secondary" data-scan-clear-done>Pulisci completate</button></div>';
    }
    b.innerHTML = html;
  }

  // ---- polling -------------------------------------------------------------
  var timer = null;
  function poll() {
    var running = load().filter(function (s) { return isRunning(s.status); });
    running.forEach(function (s) {
      if (!s.pollUrl) { return; }
      fetch(s.pollUrl, { headers: { Accept: "application/json" }, credentials: "same-origin" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          if (d && d.running === false) {
            setStatus(keyOf(s), d.status || "done", Date.now());
            render();
          }
        })
        .catch(function () { /* ritenta al prossimo tick */ });
    });
  }
  function schedule() {
    if (timer) { return; }
    timer = window.setInterval(function () {
      prune();
      var running = load().filter(function (s) { return isRunning(s.status); });
      if (!running.length) { render(); return; }
      poll();
    }, POLL_MS);
  }

  // ---- registrazione dalla pagina di dettaglio -----------------------------
  function registerFromPage() {
    var el = document.querySelector("[data-scan-track]");
    if (!el) { return; }
    var entry = {
      probeId: el.getAttribute("data-probe-id"),
      scanId: el.getAttribute("data-scan-id"),
      target: el.getAttribute("data-target"),
      probeName: el.getAttribute("data-probe-name"),
      detailUrl: el.getAttribute("data-detail-url") || window.location.pathname,
      pollUrl: el.getAttribute("data-poll-url"),
      status: el.getAttribute("data-running") === "true" ? "running" : "done"
    };
    if (!entry.probeId || !entry.scanId) { return; }
    if (entry.status === "running") {
      upsert(entry);
    } else {
      // terminata: se era tracciata, marca completata (con timestamp per il TTL).
      var list = load(), k = keyOf(entry), found = false, i;
      for (i = 0; i < list.length; i++) { if (keyOf(list[i]) === k) { found = true; } }
      if (found) { setStatus(k, entry.status, Date.now()); }
    }
  }

  // ---- eventi widget -------------------------------------------------------
  function onClick(e) {
    var hide = e.target.closest("[data-scan-hide]");
    if (hide) { if (box) { box.remove(); box = null; } return; }
    var dis = e.target.closest("[data-scan-dismiss]");
    if (dis) { removeKey(dis.getAttribute("data-scan-dismiss")); render(); return; }
    var clr = e.target.closest("[data-scan-clear-done]");
    if (clr) {
      save(load().filter(function (s) { return isRunning(s.status); }));
      render();
    }
  }

  function init() {
    registerFromPage();
    prune();
    render();
    if (load().length) { schedule(); }
    document.addEventListener("click", onClick);
    // Sincronizza tra schede/pagine aperte.
    window.addEventListener("storage", function (e) {
      if (e.key === KEY) { render(); }
    });
  }

  // API pubblica minima (per registrazione esplicita da altre pagine).
  window.PulseScanTracker = { register: function (entry) { upsert(entry); render(); schedule(); } };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})(window, document);
