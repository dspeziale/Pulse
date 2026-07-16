/*
 * pulse-charts.js — libreria di grafici minimale, self-contained.
 *
 * Motivazione (SCOSTAMENTO documentato nel README): il DOCUMENTO_API non impone
 * una libreria specifica e i requisiti vietano dipendenze CDN esterne. I template
 * originali usavano Chart.js via CDN: sostituito con questa micro-libreria locale
 * (nessuna rete richiesta) che espone un sottoinsieme compatibile dell'API Chart.js
 * (bar e line) sufficiente per la dashboard.
 *
 * Uso: new Chart(canvasEl, { type, data:{labels, datasets:[{data, backgroundColor, borderColor, label}]} });
 */
(function (global) {
  "use strict";

  function toArray(v, n, fallback) {
    if (Array.isArray(v)) return v;
    var out = [];
    for (var i = 0; i < n; i++) out.push(v || fallback);
    return out;
  }

  function niceMax(v) {
    if (!v || v <= 0) return 1;
    var mag = Math.pow(10, Math.floor(Math.log10(v)));
    return Math.ceil(v / mag) * mag;
  }

  // Colore derivato dal tema corrente (Bootstrap/AdminLTE, data-bs-theme):
  // così assi ed etichette restano leggibili sia in chiaro sia in scuro.
  function themeColor(varName, fallback) {
    try {
      var v = getComputedStyle(document.documentElement)
        .getPropertyValue(varName);
      return (v && v.trim()) || fallback;
    } catch (e) {
      return fallback;
    }
  }

  function Chart(canvas, cfg) {
    if (typeof canvas === "string") canvas = document.getElementById(canvas);
    if (!canvas || !canvas.getContext) return;
    cfg = cfg || {};
    var ctx = canvas.getContext("2d");
    var W = canvas.width = canvas.clientWidth || 600;
    var H = canvas.height || 180;
    canvas.height = H;
    var pad = { l: 40, r: 12, t: 12, b: 24 };
    var data = cfg.data || {};
    var labels = data.labels || [];
    var ds = (data.datasets && data.datasets[0]) || { data: [] };
    var values = (ds.data || []).map(function (x) { return Number(x) || 0; });
    var type = cfg.type || "bar";
    var plotW = W - pad.l - pad.r;
    var plotH = H - pad.t - pad.b;
    var max = niceMax(Math.max.apply(null, values.length ? values : [0]));

    var axisColor = themeColor("--bs-border-color", "#334155");
    var labelColor = themeColor("--bs-secondary-color", "#94a3b8");

    ctx.clearRect(0, 0, W, H);
    // assi
    ctx.strokeStyle = axisColor;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.l, pad.t);
    ctx.lineTo(pad.l, pad.t + plotH);
    ctx.lineTo(pad.l + plotW, pad.t + plotH);
    ctx.stroke();
    ctx.fillStyle = labelColor;
    ctx.font = "10px system-ui,Arial,sans-serif";
    ctx.fillText(String(max), 2, pad.t + 8);
    ctx.fillText("0", 2, pad.t + plotH);

    if (!values.length) return this;

    function x(i) { return pad.l + (plotW * (i + 0.5)) / values.length; }
    function y(v) { return pad.t + plotH - (plotH * v) / max; }

    if (type === "line") {
      ctx.strokeStyle = ds.borderColor || "#38bdf8";
      ctx.lineWidth = 2;
      ctx.beginPath();
      values.forEach(function (v, i) {
        var px = pad.l + (plotW * i) / Math.max(values.length - 1, 1);
        var py = y(v);
        if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
      });
      ctx.stroke();
    } else {
      var colors = toArray(ds.backgroundColor, values.length, "#38bdf8");
      var bw = plotW / values.length * 0.6;
      values.forEach(function (v, i) {
        ctx.fillStyle = colors[i] || "#38bdf8";
        var px = x(i) - bw / 2;
        var py = y(v);
        ctx.fillRect(px, py, bw, pad.t + plotH - py);
      });
    }
    // etichette asse X
    ctx.fillStyle = labelColor;
    labels.forEach(function (lab, i) {
      if (labels.length > 12 && i % Math.ceil(labels.length / 12) !== 0) return;
      var px = x(i);
      var txt = String(lab).slice(0, 10);
      ctx.fillText(txt, px - txt.length * 2.5, H - 6);
    });
    return this;
  }

  global.Chart = Chart;
})(window);
