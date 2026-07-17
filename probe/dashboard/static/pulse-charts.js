/*
 * pulse-charts.js — libreria di grafici minimale, self-contained.
 *
 * Motivazione (SCOSTAMENTO documentato nel README): il DOCUMENTO_API non impone
 * una libreria specifica e i requisiti vietano dipendenze CDN esterne. I template
 * originali usavano Chart.js via CDN: sostituito con questa micro-libreria locale
 * (nessuna rete richiesta) che espone un sottoinsieme compatibile dell'API Chart.js
 * (bar e line) sufficiente per le dashboard.
 *
 * Funzioni di leggibilita' (nessun CDN, solo canvas 2D):
 *   - titolo del grafico ed etichette/unita' degli assi (es. "ms", "%");
 *   - legenda automatica quando ci sono piu' serie;
 *   - gridlines orizzontali leggere e tick Y "arrotondati" con unita';
 *   - tick dell'asse tempo ridotti e formattati (HH:MM oppure dd/MM);
 *   - tooltip al passaggio del mouse con i valori del punto piu' vicino;
 *   - colori derivati dal tema corrente (chiaro/scuro via data-bs-theme).
 *
 * Uso:
 *   new Chart(canvasEl, {
 *     type: 'line'|'bar',
 *     data: { labels:[...], datasets:[{ label, data:[...], borderColor|backgroundColor }] },
 *     options: { title, yLabel, yUnit, xTime:true|false, legend:true|false }
 *   });
 */
(function (global) {
  "use strict";

  var PALETTE = ["#0d6efd", "#198754", "#dc3545", "#fd7e14", "#6f42c1", "#20c997"];

  function toArray(v, n, fallback) {
    if (Array.isArray(v)) return v;
    var out = [];
    for (var i = 0; i < n; i++) out.push(v || fallback);
    return out;
  }

  function niceMax(v) {
    if (!v || v <= 0) return 1;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    var n = v / mag;
    var step = n <= 1 ? 1 : n <= 2 ? 2 : n <= 5 ? 5 : 10;
    return step * mag;
  }

  // Colore derivato dal tema corrente (Bootstrap/AdminLTE, data-bs-theme):
  // così assi ed etichette restano leggibili sia in chiaro sia in scuro.
  function themeColor(varName, fallback) {
    try {
      var v = getComputedStyle(document.documentElement).getPropertyValue(varName);
      return (v && v.trim()) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function fmtNum(v) {
    if (v == null || isNaN(v)) return "";
    if (Math.abs(v) >= 1000) return Math.round(v).toLocaleString();
    return (Math.round(v * 100) / 100).toString();
  }

  function pad2(n) { return (n < 10 ? "0" : "") + n; }

  // Formatta un'etichetta temporale in modo leggibile. Se ``spanMs`` (durata
  // totale della serie) supera ~36h usa dd/MM, altrimenti HH:MM.
  function fmtTime(label, spanMs) {
    var dt = new Date(label);
    if (isNaN(dt.getTime())) return String(label).slice(0, 10);
    if (spanMs > 36 * 3600 * 1000) return pad2(dt.getDate()) + "/" + pad2(dt.getMonth() + 1);
    return pad2(dt.getHours()) + ":" + pad2(dt.getMinutes());
  }

  function normalizeDatasets(data) {
    var raw = (data && data.datasets) || [];
    return raw.map(function (ds, i) {
      var color = ds.borderColor ||
        (typeof ds.backgroundColor === "string" ? ds.backgroundColor : null) ||
        PALETTE[i % PALETTE.length];
      return {
        label: ds.label || ("Serie " + (i + 1)),
        values: (ds.data || []).map(function (x) { return Number(x) || 0; }),
        color: color,
        // per i bar a colori-per-barra (dashboard: distribuzione stati)
        barColors: Array.isArray(ds.backgroundColor) ? ds.backgroundColor : null,
      };
    });
  }

  function Chart(canvas, cfg) {
    if (typeof canvas === "string") canvas = document.getElementById(canvas);
    if (!canvas || !canvas.getContext) return;
    cfg = cfg || {};
    var opts = cfg.options || {};
    var type = cfg.type || "bar";
    var data = cfg.data || {};
    var labels = data.labels || [];
    var datasets = normalizeDatasets(data);
    var ctx = canvas.getContext("2d");

    // Rimuove un eventuale handler precedente (re-inizializzazione dello stesso canvas).
    if (canvas._pulseCleanup) { canvas._pulseCleanup(); }

    // --- Dimensioni + scaling per schermi HiDPI (nitidezza) ---
    var dpr = global.devicePixelRatio || 1;
    var cssW = canvas.clientWidth || 600;
    var cssH = parseInt(canvas.getAttribute("height"), 10) || canvas.height || 180;
    canvas.style.width = cssW + "px";
    canvas.style.height = cssH + "px";
    canvas.width = Math.round(cssW * dpr);
    canvas.height = Math.round(cssH * dpr);

    var axisColor = themeColor("--bs-border-color", "#ccd2da");
    var labelColor = themeColor("--bs-secondary-color", "#6c757d");
    var gridColor = themeColor("--bs-border-color-translucent", "rgba(0,0,0,0.08)");
    var bodyColor = themeColor("--bs-body-color", "#212529");
    var bodyBg = themeColor("--bs-body-bg", "#ffffff");

    var showLegend = opts.legend !== false && (datasets.length > 1 || opts.legend === true);
    var hasTitle = !!opts.title;

    // Massimo comune a tutte le serie.
    var allVals = [];
    datasets.forEach(function (d) { allVals = allVals.concat(d.values); });
    var max = niceMax(Math.max.apply(null, allVals.length ? allVals : [0]));

    // --- Layout ---
    var pad = {
      l: 46 + (opts.yLabel ? 14 : 0),
      r: 14,
      t: 10 + (hasTitle ? 18 : 0) + (showLegend ? 18 : 0),
      b: 30,
    };

    // Durata totale (per la formattazione dei tick temporali).
    var spanMs = 0;
    if (opts.xTime && labels.length > 1) {
      var t0 = new Date(labels[0]).getTime();
      var t1 = new Date(labels[labels.length - 1]).getTime();
      if (!isNaN(t0) && !isNaN(t1)) spanMs = Math.abs(t1 - t0);
    }

    function draw(hoverIndex) {
      var W = cssW, H = cssH;
      var plotW = W - pad.l - pad.r;
      var plotH = H - pad.t - pad.b;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, W, H);
      ctx.textBaseline = "alphabetic";
      ctx.font = "11px 'PT Sans Narrow',system-ui,Arial,sans-serif";

      // Titolo
      if (hasTitle) {
        ctx.fillStyle = bodyColor;
        ctx.textAlign = "left";
        ctx.font = "bold 12px 'PT Sans Narrow',system-ui,Arial,sans-serif";
        ctx.fillText(String(opts.title), pad.l, 12);
        ctx.font = "11px 'PT Sans Narrow',system-ui,Arial,sans-serif";
      }

      // Legenda (in alto a destra)
      if (showLegend) {
        var lx = W - pad.r, ly = hasTitle ? 12 : 10;
        ctx.textAlign = "right";
        for (var li = datasets.length - 1; li >= 0; li--) {
          var d = datasets[li];
          var tw = ctx.measureText(d.label).width;
          ctx.fillStyle = labelColor;
          ctx.fillText(d.label, lx, ly);
          ctx.fillStyle = d.color;
          ctx.fillRect(lx - tw - 16, ly - 8, 10, 10);
          lx -= tw + 22;
        }
      }

      // Gridlines orizzontali + tick Y (con unita')
      var yTicks = 4;
      ctx.textAlign = "right";
      for (var g = 0; g <= yTicks; g++) {
        var val = (max * g) / yTicks;
        var gy = pad.t + plotH - (plotH * g) / yTicks;
        ctx.strokeStyle = gridColor;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(pad.l, gy);
        ctx.lineTo(pad.l + plotW, gy);
        ctx.stroke();
        ctx.fillStyle = labelColor;
        var yt = fmtNum(val) + (opts.yUnit ? " " + opts.yUnit : "");
        ctx.fillText(yt, pad.l - 6, gy + 3);
      }

      // Assi
      ctx.strokeStyle = axisColor;
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(pad.l, pad.t);
      ctx.lineTo(pad.l, pad.t + plotH);
      ctx.lineTo(pad.l + plotW, pad.t + plotH);
      ctx.stroke();

      // Etichetta asse Y (verticale)
      if (opts.yLabel) {
        ctx.save();
        ctx.translate(12, pad.t + plotH / 2);
        ctx.rotate(-Math.PI / 2);
        ctx.textAlign = "center";
        ctx.fillStyle = labelColor;
        ctx.fillText(String(opts.yLabel), 0, 0);
        ctx.restore();
      }

      var n = 0;
      datasets.forEach(function (d) { n = Math.max(n, d.values.length); });
      var hitX = [];

      function yPix(v) { return pad.t + plotH - (plotH * v) / max; }

      if (type === "line") {
        function xPix(i) { return pad.l + (plotW * i) / Math.max(n - 1, 1); }
        for (var i = 0; i < n; i++) hitX.push(xPix(i));
        datasets.forEach(function (d) {
          ctx.strokeStyle = d.color;
          ctx.lineWidth = 2;
          ctx.beginPath();
          d.values.forEach(function (v, i) {
            var px = xPix(i), py = yPix(v);
            if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
          });
          ctx.stroke();
          // punti
          ctx.fillStyle = d.color;
          d.values.forEach(function (v, i) {
            ctx.beginPath();
            ctx.arc(xPix(i), yPix(v), n > 60 ? 0 : 2, 0, Math.PI * 2);
            ctx.fill();
          });
        });
      } else {
        // bar: una sola serie (per-barra) oppure gruppi affiancati
        var groups = n || 1;
        var slot = plotW / groups;
        var ds0 = datasets[0] || { values: [] };
        var bw = Math.min(slot * 0.6, 48);
        function xCenter(i) { return pad.l + slot * (i + 0.5); }
        for (var b = 0; b < groups; b++) hitX.push(xCenter(b));
        ds0.values.forEach(function (v, i) {
          var col = (ds0.barColors && ds0.barColors[i]) || ds0.color;
          ctx.fillStyle = col;
          var px = xCenter(i) - bw / 2;
          var py = yPix(v);
          ctx.fillRect(px, py, bw, pad.t + plotH - py);
        });
      }

      // Tick asse X (ridotti e formattati)
      ctx.fillStyle = labelColor;
      ctx.textAlign = "center";
      var maxTicks = Math.max(2, Math.min(8, Math.floor(plotW / 60)));
      var step = Math.max(1, Math.ceil(labels.length / maxTicks));
      labels.forEach(function (lab, i) {
        if (i % step !== 0 && i !== labels.length - 1) return;
        var txt = opts.xTime ? fmtTime(lab, spanMs) : String(lab).slice(0, 12);
        ctx.fillText(txt, hitX[i] || pad.l, H - 8);
      });

      // Tooltip
      if (hoverIndex != null && hoverIndex >= 0 && hitX[hoverIndex] != null) {
        var hx = hitX[hoverIndex];
        ctx.strokeStyle = axisColor;
        ctx.setLineDash([3, 3]);
        ctx.beginPath();
        ctx.moveTo(hx, pad.t);
        ctx.lineTo(hx, pad.t + plotH);
        ctx.stroke();
        ctx.setLineDash([]);

        var lines = [];
        var headLabel = labels[hoverIndex];
        lines.push(opts.xTime ? fmtTime(headLabel, spanMs) : String(headLabel));
        datasets.forEach(function (d) {
          if (d.values[hoverIndex] == null) return;
          lines.push(d.label + ": " + fmtNum(d.values[hoverIndex]) + (opts.yUnit ? " " + opts.yUnit : ""));
        });
        ctx.font = "11px 'PT Sans Narrow',system-ui,Arial,sans-serif";
        var tw2 = 0;
        lines.forEach(function (l) { tw2 = Math.max(tw2, ctx.measureText(l).width); });
        var boxW = tw2 + 14, boxH = lines.length * 15 + 8;
        var bx = Math.min(hx + 10, W - boxW - 4);
        var by = pad.t + 4;
        ctx.fillStyle = bodyBg;
        ctx.strokeStyle = axisColor;
        ctx.globalAlpha = 0.96;
        ctx.fillRect(bx, by, boxW, boxH);
        ctx.globalAlpha = 1;
        ctx.strokeRect(bx, by, boxW, boxH);
        ctx.textAlign = "left";
        ctx.fillStyle = bodyColor;
        lines.forEach(function (l, k) {
          ctx.font = (k === 0 ? "bold " : "") + "11px 'PT Sans Narrow',system-ui,Arial,sans-serif";
          ctx.fillText(l, bx + 7, by + 16 + k * 15);
        });
      }

      return hitX;
    }

    var hitX = draw(null);

    // --- Interattivita': tooltip al passaggio del mouse ---
    function onMove(ev) {
      if (!hitX || !hitX.length) return;
      var rect = canvas.getBoundingClientRect();
      var mx = ev.clientX - rect.left;
      var best = 0, bestD = Infinity;
      for (var i = 0; i < hitX.length; i++) {
        var dd = Math.abs(hitX[i] - mx);
        if (dd < bestD) { bestD = dd; best = i; }
      }
      draw(best);
    }
    function onLeave() { draw(null); }
    canvas.addEventListener("mousemove", onMove);
    canvas.addEventListener("mouseleave", onLeave);
    canvas._pulseCleanup = function () {
      canvas.removeEventListener("mousemove", onMove);
      canvas.removeEventListener("mouseleave", onLeave);
    };

    return this;
  }

  global.Chart = Chart;
})(window);
