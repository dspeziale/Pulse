/* Pulse — inizializzazione condivisa DataTables (server-side).
 *
 * Nessun file di lingua da CDN: le stringhe italiane sono definite qui in
 * locale. `PulseDT.init(selector, opts)` applica i default comuni (serverSide,
 * processing, ordering, lengthMenu, lingua IT) e li fonde con le opzioni della
 * singola pagina (ajax/columns/order/pageLength/searching/lengthMenu...).
 */
(function (window) {
  "use strict";

  var LANG_IT = {
    processing: "Elaborazione...",
    search: "Cerca:",
    lengthMenu: "Mostra _MENU_ elementi",
    info: "Vista da _START_ a _END_ di _TOTAL_ elementi",
    infoEmpty: "Vista da 0 a 0 di 0 elementi",
    infoFiltered: "(filtrati da _MAX_ elementi totali)",
    loadingRecords: "Caricamento...",
    zeroRecords: "Nessun dato corrispondente ai filtri",
    emptyTable: "Nessun dato disponibile",
    paginate: {
      first: "Primo",
      previous: "Precedente",
      next: "Successivo",
      last: "Ultimo"
    },
    aria: {
      sortAscending: ": attiva per ordinare in modo crescente",
      sortDescending: ": attiva per ordinare in modo decrescente"
    }
  };

  function init(selector, opts) {
    var cfg = Object.assign(
      {
        serverSide: true,
        processing: true,
        ordering: true,
        searching: true,
        autoWidth: false,
        lengthMenu: [10, 25, 50, 100],
        pageLength: 25,
        language: LANG_IT
      },
      opts || {}
    );
    return new DataTable(selector, cfg);
  }

  window.PulseDT = { language: LANG_IT, init: init };
})(window);
