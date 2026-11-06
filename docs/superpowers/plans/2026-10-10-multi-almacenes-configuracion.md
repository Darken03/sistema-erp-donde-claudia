# Multi-Almacén + Configuración Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar almacenes múltiples con nombre propio + módulo Configuración (tienda, almacenes, apariencia, regional) con botón en header, manteniendo flujo idéntico cuando hay 1 almacén.

**Architecture:** Nueva entidad `Almacen` + `AlmacenStock(producto, almacen)` único; `ConfiguracionTienda` singleton; vistas existentes ganan FK/filtro por almacén; si N=1 filtro automático sin selectores.

**Tech Stack:** Django 4.x templates + Bootstrap 5.3 + Bootstrap Icons, SQLite, pytest/Django TestCase, CSS vars (`--accent`, `data-theme`).

**Spec:** `docs/superpowers/specs/2026-10-10-multi-almacenes-configuracion-design.md`

## Global Constraints

- Stack: Django templates + Bootstrap 5.3 + Bootstrap Icons + `static/css/styles.css` (tokens DESIGN.MD).
- POS y almacén separados: nada de almacén aparece en POS salvo traslado → POS que genera `EntradaProducto(proveedor='Almacén: <nombre>')`.
- Con 1 almacén activo la UI/flujo es idéntica a hoy (sin selectores).
- Botón config `id=configBtn` clase `.theme-toggle` al lado de `#themeToggle`, solo admin.
- TDD: test falla antes, pasa después; commits frecuentes por tarea.
- No estilos oscuros legacy; usar `card-hom`, `form-control-hom`, `form-select-hom`, pills.

## Review Focus

- Traslado almacén→almacén con stock insuficiente en origen debe bloquear con mensaje y no mover nada.
- Desactivar el único almacén activo o con stock > 0 debe bloquearse con mensaje claro.
- Cancelar traslado a POS cuando el POS ya vendió parte debe bloquearse sin corromper stocks.
- Logo personalizado ausente/corrupto debe caer al logo estático sin romper sidebar/login.
- Acento custom + dark/light deben aplicarse sin flash y sin romper POS offline (`bizm_theme` intacto).

---

### Task 1: Modelos + migración Principal

**Files:**
- Modify: `core/models.py`
- Create: `core/migrations/00XX_multi_almacen_config.py` (schema + data)
- Test: `core/tests_configuracion.py`

**Interfaces:**
- Consumes: modelos actuales `AlmacenStock(producto OneToOne)`, `AlmacenEntrada`, `AlmacenTraslado`, `AlmacenMovimiento`.
- Produces: `Almacen(nombre unique, descripcion, activo, es_principal)`, `ConfiguracionTienda.get_solo() -> ConfiguracionTienda`, `Almacen.activos() -> QuerySet`, helpers `get_almacen_unico() -> Almacen|None`.

- [ ] **Step 1: Write the failing test**

```python
def test_migracion_crea_principal_y_stock_por_almacen():
    assert Almacen.objects.filter(es_principal=True, activo=True).count() == 1
    assert ConfiguracionTienda.get_solo().nombre_tienda == 'Donde Clau'
    # stock único por (producto, almacen)
    with assertRaises(IntegrityError):
        AlmacenStock.objects.create(producto=p, almacen=a1, cantidad=1)
        AlmacenStock.objects.create(producto=p, almacen=a1, cantidad=2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_configuracion.TestModelosMigracion -v 2`
Expected: FAIL (Almacen / ConfiguracionTienda no existen)

- [ ] **Step 3: Implement `Almacen`, `ConfiguracionTienda` y migración en `core/models.py` + `core/migrations/`**

Firmas exactas: `class Almacen(models.Model)` con `activos()` classmethod; `class ConfiguracionTienda` con `get_solo()`; `AlmacenStock` con `almacen = FK(Almacen, related_name='stocks')` + `unique_together=(producto, almacen)`; `AlmacenEntrada.almacen FK`, `AlmacenTraslado.origen FK + destino_tipo choices(POS/ALMACEN) + destino_almacen FK null`, `AlmacenMovimiento.almacen FK null`. Data migration crea Principal + Config default y reasigna filas existentes.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_configuracion.TestModelosMigracion core.tests_almacen -v 2`
Expected: PASS (tests viejos siguen verdes con N=1)

- [ ] **Step 5: Commit**

```bash
git add core/models.py core/migrations/ core/tests_configuracion.py
git commit -m "feat: modelos Almacen y ConfiguracionTienda con migracion Principal"
```

### Task 2: Configuración — backend + UI + header

**Files:**
- Create: `core/forms_config.py` (o añade a `core/forms.py`: `AlmacenForm`, `ConfigTiendaForm`, `ConfigAparienciaForm`, `ConfigRegionalForm`)
- Modify: `core/views.py` (añade `configuracion`, `almacen_crear/editar/toggle`), `core/urls.py`, `templates/base.html`, `templates/core/configuracion.html`
- Test: `core/tests_configuracion.py` (añade `TestPermisosConfig`, `TestCRUDAlmacen`)

**Interfaces:**
- Consumes: `Almacen`, `ConfiguracionTienda.get_solo()` de Task 1.
- Produces: `configuracion(request)`, `config_almacen_crear(request)`, `config_almacen_editar(request, pk)`, `config_almacen_toggle(request, pk)`, context processor `configuracion_tienda`.

- [ ] **Step 1: Write the failing test**

```python
def test_solo_admin_accede_y_crea_almacen_con_nombre():
    assert login(cajero, '/configuracion/') in (302, 403)
    login(admin, '/configuracion/')
    assert get('/configuracion/').status_code == 200
    post('/configuracion/almacenes/crear/', {'nombre': 'Secundario'})
    assert Almacen.objects.filter(nombre='Secundario').exists()
    # duplicado bloqueado
    assert post('/configuracion/almacenes/crear/', {'nombre': 'Secundario'}).status_code != 500
    assert Almacen.objects.filter(nombre='Secundario').count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_configuracion.TestPermisosConfig.TestCRUDAlmacen -v 2`
Expected: FAIL (urls/views 404)

- [ ] **Step 3: Implement vistas/urls/forms/template + botón header en `core/views.py`, `core/urls.py`, `templates/core/configuracion.html`, `templates/base.html`**

Rutas exactas: `configuracion`, `config_almacen_crear`, `config_almacen_editar`, `config_almacen_toggle`. Template con 4 tabs (Tienda/Almacenes/Apariencia/Regional) usando `card-hom`. Header: `<a id="configBtn" class="theme-toggle" href="{% url 'core:configuracion' %}"><i class="bi bi-gear"></i></a>` solo `es_admin` junto a `#themeToggle`. Sidebar item Configuración solo admin. Toggle bloquea: único activo, stock>0, nombre duplicado → messages.error.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_configuracion -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/views.py core/urls.py core/forms.py templates/base.html templates/core/configuracion.html core/tests_configuracion.py
git commit -m "feat: modulo Configuracion con CRUD almacenes y boton header"
```

### Task 3: Apariencia — logo, acento, tema default

**Files:**
- Modify: `templates/base.html`, `templates/core/login.html` (logo dinámico), `static/css/styles.css` (override `--accent` vía `data-accent` o style inline), `core/views.py` (context processor o `get_context`)
- Test: `core/tests_configuracion.py` (`TestApariencia`)

**Interfaces:**
- Consumes: `ConfiguracionTienda.get_solo()` (logo, color_acento, tema_por_defecto).
- Produces: variable template `TIENDA` con `nombre, logo_url, color_acento`; script head usa `bizm_theme` existente con fallback a `tema_por_defecto`.

- [ ] **Step 1: Write the failing test**

```python
def test_logo_y_acento_aplican():
    post_config(admin, {'color_acento': '#0ea5e9', 'tema_por_defecto': 'dark'})
    html = get('/configuracion/').content.decode()
    assert '#0ea5e9' in html
    # upload logo jpg válido persiste
    post_logo(admin, logo_jpg)
    assert ConfiguracionTienda.get_solo().logo
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_configuracion.TestApariencia -v 2`
Expected: FAIL

- [ ] **Step 3: Implement logo dinámico + acento + tema default en `templates/base.html`, `static/css/styles.css`**

Logo: `{% if TIENDA.logo_url %}{{ TIENDA.logo_url }}{% else %}{% static 'img/logo-donde-clau.png' %}{% endif %}` con try/exists. Acento: `<html style="--accent:{{ TIENDA.color_acento }}">` o bloque `<style>:root{--accent:...}</style>`. Tema: inline head `localStorage.getItem('bizm_theme') || '{{ TIENDA.tema_por_defecto }}'`. Reutiliza conversión HEIC/JPEG de `ProductoForm` si hace falta.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_configuracion.TestApariencia -v 2`
Expected: PASS + revisión manual 375px/768px y dark/light

- [ ] **Step 5: Commit**

```bash
git add templates/base.html static/css/styles.css core/views.py core/tests_configuracion.py
git commit -m "feat: logo, acento y tema por defecto de la tienda"
```

### Task 4: Entradas + ajuste multi-almacén

**Files:**
- Modify: `core/views.py` (`almacen_entrada_crear`, `almacen_entrada_lista`, `almacen_entrada_cancelar`, `almacen_ajuste`), `templates/core/almacen_entrada_form.html`, `almacen_entrada_lista.html`, `almacen_ajuste_form.html`
- Test: `core/tests_almacen_multi.py`

**Interfaces:**
- Consumes: `Almacen.activos()`, `get_almacen_unico()`, `AlmacenStock(producto, almacen)`.
- Produces: filtro `?almacen=<id>` persistido en sesión (`request.session['almacen_id']`); entradas filtran por almacén.

- [ ] **Step 1: Write the failing test**

```python
def test_entradas_aisladas_por_almacen():
    post_entrada(admin, prod, cantidad=25, almacen=a1)
    post_entrada(admin, prod, cantidad=10, almacen=a2)
    assert stock(prod, a1) == 25 and stock(prod, a2) == 10 and prod.stock == 0
    # N=1: POST sin almacen usa el único
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_almacen_multi.TestEntradas -v 2`
Expected: FAIL (sin columna almacen)

- [ ] **Step 3: Implement selector/filtro almacén en entradas y ajuste en `core/views.py` + 3 templates**

Si `N==1`: `almacen = get_almacen_unico()`, sin selector visible (input hidden). Si `N>=2`: `<select name="almacen">` obligatorio + filtro lista + `stock_map` por almacén. Cancelar revierte solo su almacén; si insuficiente → error (parte trasladada). Ajuste exige almacén + motivo.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_almacen_multi.TestEntradas core.tests_almacen -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/views.py templates/core/almacen_entrada_form.html templates/core/almacen_entrada_lista.html templates/core/almacen_ajuste_form.html core/tests_almacen_multi.py
git commit -m "feat: entradas y ajustes por almacen"
```

### Task 5: Traslados origen→(POS|almacén) + cancelaciones

**Files:**
- Modify: `core/views.py` (`almacen_traslado_crear`, `almacen_traslado_cancelar`, `almacen_traslado_lista`), `templates/core/almacen_traslado_form.html`, `almacen_traslado_lista.html`
- Test: `core/tests_almacen_multi.py` (`TestTraslados`)

**Interfaces:**
- Consumes: Task 4 (stocks por almacén), `EntradaProducto`, `ALMACEN_PROVEEDOR`.
- Produces: `almacen_traslado_crear(request)` con `origen`, `destino_tipo`, `destino_almacen`.

- [ ] **Step 1: Write the failing test**

```python
def test_traslado_almacen_a_almacen_y_a_pos():
    post_traslado(origen=a1, destino_tipo='ALMACEN', destino=a2, cantidad=5)
    assert stock(prod,a1)==20 and stock(prod,a2)==15 and prod.stock==0
    post_traslado(origen=a2, destino_tipo='POS', cantidad=4)
    assert stock(prod,a2)==11 and prod.stock==4
    assert EntradaProducto.objects.filter(proveedor='Almacén: Secundario').exists()
    # sin stock bloquea
    assert post_traslado(origen=a1, destino_tipo='POS', cantidad=999).status_code in (302,200)
    assert stock(prod,a1)==20
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_almacen_multi.TestTraslados -v 2`
Expected: FAIL

- [ ] **Step 3: Implement `almacen_traslado_crear/cancelar` con destino dual en `core/views.py`**

`transaction.atomic` + `select_for_update`: valida `origen != destino`, stock origen, destino activo. POS: crea `EntradaProducto(proveedor=f'Almacén: {origen.nombre}')` + `_registrar_movimiento` + `visible_pos=True`. Almacén: suma destino + 2× `AlmacenMovimiento`. Cancelar (admin): revierte el lado correcto; si POS sin stock o IPB cerrado → error. Form con `origen` + radio `destino_tipo` + `destino_almacen` (JS muestra/oculta).

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_almacen_multi.TestTraslados core.tests_almacen core.tests_almacen_visibilidad -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/views.py templates/core/almacen_traslado_form.html templates/core/almacen_traslado_lista.html core/tests_almacen_multi.py
git commit -m "feat: traslados almacen-POS y almacen-almacen"
```

### Task 6: Panel, existencias y auditoría por almacén

**Files:**
- Modify: `core/views.py` (`almacen_panel`, `almacen_stock`, `almacen_movimientos`), `templates/core/almacen_panel.html`, `almacen_stock.html`, `almacen_movimientos.html`
- Test: `core/tests_almacen_multi.py` (`TestPanelFiltros`)

**Interfaces:**
- Consumes: Tasks 4-5 (datos por almacén), sesión `almacen_id`.
- Produces: panel con cards por almacén + global; filtros `?almacen=` en las 3 vistas.

- [ ] **Step 1: Write the failing test**

```python
def test_panel_y_filtros_por_almacen():
    html = get('/almacen/?almacen=%s' % a1.pk).content.decode()
    assert 'Almacén Principal' in html and 'Secundario' in html
    assert get('/almacen/existencias/?almacen=%s' % a1.pk).status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_almacen_multi.TestPanelFiltros -v 2`
Expected: FAIL

- [ ] **Step 3: Implement filtros y cards por almacén en `core/views.py` + 3 templates**

`almacen_panel`: si N==1 contexto actual; si N>1 lista `almacenes` con (valor, nº productos, recientes) + global. `almacen_stock/movimientos/entradas/traslados`: `almacen_id` GET→sesión→único; columna Almacén visible solo si N>1. Tablas patrón §7 DESIGN.MD.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_almacen_multi core.tests_almacen core.tests_almacen_next -v 2`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/views.py templates/core/almacen_panel.html templates/core/almacen_stock.html templates/core/almacen_movimientos.html core/tests_almacen_multi.py
git commit -m "feat: panel y filtros por almacen"
```

### Task 7: Verificación final y pulido

**Files:**
- Modify: ninguno nuevo (solo fixes); verifica `static/css/responsive.css`, `static/js/main.js` (`toggleBizTheme` intacto)
- Test: suite completa

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: suite verde + checklist responsive/dark.

- [ ] **Step 1: Write the failing test (humo N=1 sin selectores)**

```python
def test_con_un_almacen_no_hay_selectores():
    html = get('/almacen/entradas/nueva/').content.decode()
    assert 'name="almacen"' not in html or 'type="hidden"' in html
```

- [ ] **Step 2: Run full suite to verify**

Run: `python manage.py test core -v 1`
Expected: PASS todo; manual: 375px/768px, dark/light, IPB con proveedor por almacén, POS offline intacto

- [ ] **Step 3: Commit fixes (si los hay)**

```bash
git add -A
git commit -m "fix: pulido multi-almacen y configuracion (responsive, dark, IPB)"
```
