// BizMaster - JavaScript

document.addEventListener('DOMContentLoaded', function() {
    console.log('BizMaster: Inicializando...');
    
    const sidebarToggle = document.getElementById('sidebarToggle');
    const sidebar = document.getElementById('sidebar');
    const sidebarOverlay = document.getElementById('sidebarOverlay');
    const DESK = window.matchMedia('(min-width: 992px)');
    const SIDE_KEY = 'bizm_side';

    function isDesktop() { return DESK.matches; }

    // Aplica el estado guardado (solo escritorio: visible u oculto)
    function applySavedSide() {
        if (!sidebar) return;
        var hidden = false;
        try { hidden = localStorage.getItem(SIDE_KEY) === 'hidden'; } catch(e){}
        document.body.classList.toggle('side-hidden', hidden && isDesktop());
    }

    // Drawer móvil (overlay)
    function toggleMobileDrawer() {
        if (!sidebar) return;
        sidebar.classList.toggle('show');
        if (sidebarOverlay) {
            sidebarOverlay.classList.toggle('show');
        }
        document.body.classList.toggle('sidebar-open');
    }

    function closeMobileDrawer() {
        if (!sidebar) return;
        sidebar.classList.remove('show');
        if (sidebarOverlay) {
            sidebarOverlay.classList.remove('show');
        }
        document.body.classList.remove('sidebar-open');
    }

    if (sidebarToggle) {
        sidebarToggle.addEventListener('click', function(e) {
            e.preventDefault();
            if (isDesktop()) {
                // Escritorio: mostrar / ocultar el menú lateral
                var hidden = document.body.classList.toggle('side-hidden');
                try { localStorage.setItem(SIDE_KEY, hidden ? 'hidden' : ''); } catch(err){}
            } else {
                toggleMobileDrawer();
            }
        });
    }

    if (sidebarOverlay) {
        sidebarOverlay.addEventListener('click', closeMobileDrawer);
    }

    // Al cambiar de tamaño, limpiar el estado del otro modo
    if (DESK.addEventListener) {
        DESK.addEventListener('change', function(){
            closeMobileDrawer();
            applySavedSide();
        });
    }

    applySavedSide();

    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            closeMobileDrawer();
        }
    });

    // Auto-dismiss alerts after 5 seconds
    const alerts = document.querySelectorAll('.alert-dismissible');
    alerts.forEach(function(alert) {
        setTimeout(function() {
            const bsAlert = bootstrap.Alert.getOrCreateInstance(alert);
            if (bsAlert) {
                bsAlert.close();
            }
        }, 5000);
    });

    // Tema claro / oscuro global (persistente, afecta tambien al POS)
    function currentTheme() {
        return document.documentElement.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
    }
    function paintThemeIcon() {
        var icon = document.getElementById('themeToggleIcon');
        if (!icon) return;
        var dark = currentTheme() === 'dark';
        icon.className = dark ? 'bi bi-sun' : 'bi bi-moon-stars';
        var btn = document.getElementById('themeToggle');
        if (btn) btn.title = dark ? 'Cambiar a modo claro' : 'Cambiar a modo oscuro';
    }
    window.toggleBizTheme = function() {
        var next = currentTheme() === 'dark' ? 'light' : 'dark';
        try { localStorage.setItem('bizm_theme', next); } catch(e){}
        document.documentElement.setAttribute('data-theme', next);
        paintThemeIcon();
        var posBtn = document.getElementById('themeTogglePosIcon');
        if (posBtn) posBtn.className = next === 'dark' ? 'bi bi-sun' : 'bi bi-moon-stars';
    };
    var themeBtn = document.getElementById('themeToggle');
    if (themeBtn) themeBtn.addEventListener('click', function(e){ e.preventDefault(); window.toggleBizTheme(); });
    paintThemeIcon();

    // Confirm delete actions
    const deleteForms = document.querySelectorAll('form[data-confirm]');
    deleteForms.forEach(function(form) {
        form.addEventListener('submit', function(e) {
            if (!confirm(form.dataset.confirm)) {
                e.preventDefault();
            }
        });
    });
    
    console.log('BizMaster: Inicializado');
});