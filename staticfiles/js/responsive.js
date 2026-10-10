/* ============================================================
   BizMaster — Mejoras responsive (NO POS)
   - Si existe .pos-shell / ticket / mostrador / impresión:
     marca body.is-pos y NO hace nada más (el POS queda intacto).
   - Tablas: añade data-rlabel a cada td desde su th y activa
     el modo tarjeta (.r-card) en S20.
   - Drawer: cierra el menú móvil al navegar; evita scroll del
     fondo cuando el drawer está abierto.
   ============================================================ */
(function () {
  'use strict';

  function isPosPage() {
    return !!(
      document.querySelector('.pos-shell') ||
      document.querySelector('[data-pos-root]') ||
      document.body.classList.contains('pos-page') ||
      /mostrador|pos[\/_-]?ticket|pos[\/_-]?sin[\/_-]?turno|venta[\/_-]?impresion|ipb[\/_-]?impresion/i.test(
        window.location.pathname || ''
      )
    );
  }

  document.addEventListener('DOMContentLoaded', function () {
    if (isPosPage()) {
      document.body.classList.add('is-pos');
      return; // <-- POS intacto: sin tablas-card ni drawer extra
    }

    var MOBILE_CARD = window.matchMedia('(max-width: 767.98px)');

    /* ---- 1. Tablas -> tarjetas ---- */
    function enhanceTables() {
      document
        .querySelectorAll('.table-responsive > table.table')
        .forEach(function (table) {
          if (table.closest('.pos-shell')) return;
          if (table.id === 'ipbTable') return; // IPB: vuelve a la normalidad, sin modo tarjeta
          var wrapper = table.closest('.table-responsive');
          var thead = table.querySelector('thead');
          if (!thead) return;
          var headers = Array.prototype.map.call(
            thead.querySelectorAll('th'),
            function (th) {
              return (th.textContent || '').trim().replace(/\s+/g, ' ');
            }
          );
          if (!headers.length) return;

          table.querySelectorAll('tbody > tr').forEach(function (tr) {
            var tds = tr.querySelectorAll(':scope > td');
            if (!tds.length) return;
            // Filas de estado (colspan / vacías / "No hay...") no se convierten
            var hasColspan = Array.prototype.some.call(tds, function (td) {
              return td.hasAttribute('colspan');
            });
            var text = (tr.textContent || '').trim();
            var isStatus =
              hasColspan ||
              tds.length === 1 ||
              /no (hay|se encontraron)|aún no|sin |vac[ií]o|sin resultados/i.test(text) ||
              tr.querySelector('tfoot');
            if (isStatus) {
              tr.classList.add('r-skip');
              return;
            }
            Array.prototype.forEach.call(tds, function (td, i) {
              var label = headers[i] || headers[Math.min(i, headers.length - 1)] || '';
              // Acciones ("", "Acciones", iconos solos) sin etiqueta
              var onlyActions =
                !label ||
                /^(acciones?)?\s*$/.test(label) ||
                (td.querySelector('.btn-group, .btn') &&
                  (td.textContent || '').trim().length === 0);
              if (onlyActions && !td.hasAttribute('data-rlabel')) {
                td.classList.add('r-no-label');
                return;
              }
              if (!td.hasAttribute('data-rlabel') && label) {
                td.setAttribute('data-rlabel', label);
              }
            });
          });

          // Pie de tabla (TOTALES del IPB y otros): etiquetar celdas
          // respetando colspan para que el modo tarjeta lo muestre bien.
          table.querySelectorAll('tfoot > tr').forEach(function (tr) {
            var tds = tr.querySelectorAll(':scope > td, :scope > th');
            if (!tds.length) return;
            var col = 0;
            Array.prototype.forEach.call(tds, function (td) {
              var span = parseInt(td.getAttribute('colspan') || '1', 10) || 1;
              var label = col === 0 && span > 1 ? 'Total' : headers[col] || '';
              var txt = (td.textContent || '').trim();
              var hasWidget = !!td.querySelector('.btn, .badge, input, select, a');
              if (!txt && !hasWidget) {
                td.classList.add('r-empty');
              } else if (label && !td.hasAttribute('data-rlabel')) {
                td.setAttribute('data-rlabel', label);
              }
              col += span;
            });
          });

          wrapper.classList.add('r-card');
          // Tablas anchas en tablet: modo compacto con scroll (solo scroll)
          if (headers.length >= 6) wrapper.classList.add('r-sticky-first');
        });
    }

    function applyCardMode() {
      // La clase .r-card vive siempre; el CSS solo la usa en <=767px.
      // Aquí solo re-evaluamos por si el DOM cambió (paginación AJAX, filtros).
      if (MOBILE_CARD.matches) {
        document.body.classList.add('r-mobile');
      } else {
        document.body.classList.remove('r-mobile');
      }
    }

    enhanceTables();
    applyCardMode();
    if (MOBILE_CARD.addEventListener) {
      MOBILE_CARD.addEventListener('change', applyCardMode);
    } else if (MOBILE_CARD.addListener) {
      MOBILE_CARD.addListener(applyCardMode);
    }
    // Reintentar tras renders tardíos (badges, tablas AJAX)
    setTimeout(enhanceTables, 800);

    /* ---- 2. Drawer móvil: cerrar al navegar ---- */
    var sidebar = document.getElementById('sidebar');
    var overlay = document.getElementById('sidebarOverlay');
    function closeDrawer() {
      if (!sidebar) return;
      sidebar.classList.remove('show');
      if (overlay) overlay.classList.remove('show');
      document.body.classList.remove('sidebar-open');
    }
    if (sidebar) {
      sidebar.querySelectorAll('a.nav-link, a.side-sub-link').forEach(function (a) {
        a.addEventListener('click', function () {
          if (window.matchMedia('(max-width: 991.98px)').matches) closeDrawer();
        });
      });
      // Evita que el fondo haga scroll mientras el drawer está abierto (iOS/Samsung)
      var drawerScrollLock = function () {
        if (sidebar.classList.contains('show')) {
          document.body.style.overflow = 'hidden';
        } else if (!document.body.classList.contains('modal-open')) {
          document.body.style.overflow = '';
        }
      };
      new MutationObserver(drawerScrollLock).observe(sidebar, {
        attributes: true,
        attributeFilter: ['class'],
      });
    }

    /* ---- 3. Tablas anchas: hint de scroll en S20 ---- */
    document.querySelectorAll('.table-responsive').forEach(function (w) {
      if (w.scrollWidth > w.clientWidth + 8 && !w.hasAttribute('tabindex')) {
        w.setAttribute('tabindex', '0');
        w.setAttribute('role', 'region');
        w.setAttribute('aria-label', 'Tabla desplazable horizontalmente');
      }
    });
  });
})();
