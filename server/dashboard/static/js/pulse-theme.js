/*
 * pulse-theme.js — preferenze UI locali (nessuna dipendenza esterna).
 *
 * Gestisce:
 *  - tema chiaro/scuro tramite l'attributo `data-bs-theme` (Bootstrap 5 /
 *    AdminLTE 4), predefinito CHIARO, persistente in localStorage;
 *  - dimensione del carattere dell'intera UI via font-size su <html> (rem),
 *    base 19px, con pulsanti A- / A+ e reset, persistente in localStorage.
 *
 * L'applicazione iniziale delle preferenze avviene il prima possibile (vedi
 * lo snippet inline in <head>) per evitare il "flash" al caricamento; qui si
 * aggiungono i gestori dei controlli e si rifà l'applicazione a DOM pronto.
 */
(function (global) {
  "use strict";

  var THEME_KEY = "pulse-theme";
  var FONT_KEY = "pulse-font-px";
  var DEFAULT_FONT = 19;
  var MIN_FONT = 13;
  var MAX_FONT = 30;
  var STEP = 1;

  function storage() {
    try {
      return global.localStorage;
    } catch (e) {
      return null;
    }
  }

  function getTheme() {
    var s = storage();
    var v = s && s.getItem(THEME_KEY);
    return v === "dark" ? "dark" : "light";
  }

  function applyTheme(theme) {
    document.documentElement.setAttribute("data-bs-theme", theme);
    var s = storage();
    if (s) s.setItem(THEME_KEY, theme);
    updateThemeButton(theme);
  }

  function toggleTheme() {
    applyTheme(getTheme() === "dark" ? "light" : "dark");
  }

  function getFontPx() {
    var s = storage();
    var v = parseInt(s && s.getItem(FONT_KEY), 10);
    if (isNaN(v)) return DEFAULT_FONT;
    return Math.min(MAX_FONT, Math.max(MIN_FONT, v));
  }

  function applyFontPx(px) {
    px = Math.min(MAX_FONT, Math.max(MIN_FONT, px));
    document.documentElement.style.fontSize = px + "px";
    var s = storage();
    if (s) s.setItem(FONT_KEY, String(px));
    var out = document.querySelector("[data-pulse-fontsize-value]");
    if (out) out.textContent = px + "px";
  }

  function stepFont(delta) {
    applyFontPx(getFontPx() + delta);
  }

  function resetFont() {
    applyFontPx(DEFAULT_FONT);
  }

  function updateThemeButton(theme) {
    var icon = document.querySelector("[data-pulse-theme-icon]");
    if (icon) {
      icon.className = theme === "dark" ? "bi bi-sun-fill" : "bi bi-moon-stars-fill";
    }
    var btn = document.querySelector("[data-pulse-theme-toggle]");
    if (btn) {
      btn.setAttribute(
        "title",
        theme === "dark" ? "Passa al tema chiaro" : "Passa al tema scuro"
      );
    }
  }

  function bind() {
    var t = document.querySelector("[data-pulse-theme-toggle]");
    if (t) t.addEventListener("click", function (e) { e.preventDefault(); toggleTheme(); });
    var dec = document.querySelector("[data-pulse-font-dec]");
    if (dec) dec.addEventListener("click", function (e) { e.preventDefault(); stepFont(-STEP); });
    var inc = document.querySelector("[data-pulse-font-inc]");
    if (inc) inc.addEventListener("click", function (e) { e.preventDefault(); stepFont(STEP); });
    var rst = document.querySelector("[data-pulse-font-reset]");
    if (rst) rst.addEventListener("click", function (e) { e.preventDefault(); resetFont(); });
    // Riapplica per aggiornare eventuali indicatori nel DOM.
    applyTheme(getTheme());
    applyFontPx(getFontPx());
  }

  // API minima riusabile e per lo snippet inline anti-flash.
  var PulseTheme = {
    THEME_KEY: THEME_KEY,
    FONT_KEY: FONT_KEY,
    DEFAULT_FONT: DEFAULT_FONT,
    applyEarly: function () {
      document.documentElement.setAttribute("data-bs-theme", getTheme());
      document.documentElement.style.fontSize = getFontPx() + "px";
    },
    toggleTheme: toggleTheme,
    stepFont: stepFont,
    resetFont: resetFont,
  };
  global.PulseTheme = PulseTheme;

  // Applica subito (in caso lo snippet inline non fosse presente) e collega i
  // controlli quando il DOM è pronto.
  PulseTheme.applyEarly();
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", bind);
  } else {
    bind();
  }
})(window);
