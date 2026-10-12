# Modos de Operación Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implementar los 3 modos de operación (solo-POS, POS+almacenes, multi-POS) seleccionables en Configuración, sin borrar datos al cambiar.

**Architecture:** Setting `ConfiguracionTienda.modo_operacion` + helper `modo_actual()` + decorador `requiere_modo()` condicionan navegación y vistas; nueva entidad `PuntoVenta` con FK a almacén; en multi-POS las ventas descuentan `AlmacenStock` del almacén asignado y `Venta`/`Turno` guardan `punto_venta`.

**Tech Stack:** Django 4.x templates + Bootstrap 5.3, SQLite, Django TestCase.

**Spec:** `docs/superpowers/specs/2026-10-10-modos-operacion-design.md`

## Global Constraints

- Cambiar de modo NUNCA borra datos; lo no aplicable se oculta por filtros y reaparece al volver.
- Modo por defecto `pos_almacenes` (comportamiento actual idéntico).
- Solo admin cambia el modo y gestiona POS; entradas directas solo admin en solo-POS.
- Sin lógica de precios/suscripción/SaaS en este ciclo.
- TDD: test falla antes, pasa después; commits frecuentes por tarea.

## Review Focus

- Cambiar a solo-POS con stock en almacenes debe ocultarlo sin borrarlo, y restaurarlo al volver.
- Venta en multi-POS sin almacén asignado al POS debe bloquearse con mensaje, no descontar nada.
- URL de almacén visitada en modo solo-POS debe redirigir con mensaje, no 500.
- Turno abierto en un POS no debe permitir vender en otro POS del mismo trabajador.
- IPB en multi-POS debe calcularse sobre el stock del almacén de cada POS, no sobre `Producto.stock`.

---

### Task 1: Setting modo + navegación condicional

**Files:**
- Modify: `core/models.py` (`ConfiguracionTienda.modo_operacion`), `core/views.py` (`modo_actual()`, `requiere_modo()`, `configuracion`), `templates/base.html` (grupo Almacén condicional), `templates/core/configuracion.html` (selector modo)
- Create: `core/migrations/00XX_modo_operacion.py`
- Test: `core/tests_modos.py`

**Interfaces:**
- Consumes: `ConfiguracionTienda.get_solo()`.
- Produces: `modo_actual() -> str`, `requiere_modo(*modos)` decorador, `ConfiguracionTienda.modo_operacion in ('solo_pos','pos_almacenes','multi_pos')`.

- [ ] **Step 1: Write the failing test**

```python
def test_modo_default_y_oculta_almacen_en_solo_pos():
    assert ConfiguracionTienda.get_solo().modo_operacion == 'pos_almacenes'
    set_modo('solo_pos')
    assert get('/almacen/').status_code == 302
    assert 'Almacén' not in sidebar_html('/dashboard/')
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_modos.TestModoBase -v 2`
Expected: FAIL (campo/modo no existen)

- [ ] **Step 3: Implement `modo_operacion`, `modo_actual()`, `requiere_modo()` y sidebar condicional**

Campo con default `pos_almacenes`; migración de datos lo fija. Sidebar muestra grupo Almacén solo si modo != `solo_pos`; muestra grupo POS solo si modo == `multi_pos`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_modos.TestModoBase core.tests_almacen -v 1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/models.py core/views.py core/migrations/ templates/base.html templates/core/configuracion.html core/tests_modos.py
git commit -m "feat: modo de operacion con navegacion condicional"
```

### Task 2: Modo solo-POS (entradas directas + ocultamiento)

**Files:**
- Modify: `core/views.py` (`entrada_crear`, `entrada_eliminar`, `entrada_lista`, filtros `AlmacenStock/Entrada/Traslado/Movimiento`), `core/urls.py`, `templates/core/entrada_form.html` (nuevo), `templates/base.html` (rol almacenero)
- Test: `core/tests_modos.py` (`TestSoloPos`)

**Interfaces:**
- Consumes: `modo_actual()`, `requiere_modo()` de Task 1.
- Produces: `entrada_crear(request)` / `entrada_eliminar(request, pk)` solo admin en modo `solo_pos`; entradas suman `Producto.stock` con `visible_pos=True`.

- [ ] **Step 1: Write the failing test**

```python
def test_entradas_directas_y_datos_ocultos_no_borrados():
    set_modo('solo_pos')
    post_entrada_directa(admin, prod, 5)
    assert prod.stock == 5 and prod.visible_pos
    assert cajero_cannot_post_entrada()
    set_modo('pos_almacenes')
    assert almacen_stock_intacto()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_modos.TestSoloPos -v 2`
Expected: FAIL (NoReverseMatch `entrada_crear`)

- [ ] **Step 3: Implement entradas directas y filtros por modo**

Restaura vistas de entrada directa (crear/eliminar solo admin + `requiere_modo('solo_pos')`); en solo-POS, vistas de almacén redirigen y listados excluyen datos de almacén sin borrarlos; almacenero redirige al POS con aviso.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_modos.TestSoloPos core.tests_almacen -v 1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/views.py core/urls.py templates/core/entrada_form.html templates/base.html core/tests_modos.py
git commit -m "feat: modo solo-POS con entradas directas"
```

### Task 3: Entidad PuntoVenta + turno con POS

**Files:**
- Modify: `core/models.py` (`PuntoVenta`, `Empleado.punto_venta`, `Turno.punto_venta`), `core/views.py` (CRUD POS en Configuración, apertura de turno con selector POS), `core/admin.py`
- Create: `core/migrations/00XX_puntoventa.py`
- Test: `core/tests_modos.py` (`TestPuntoVenta`)

**Interfaces:**
- Consumes: `Almacen`, `modo_actual()`.
- Produces: `PuntoVenta(nombre unique, almacen FK, activo)`, `Empleado.punto_venta FK nullable`, `Turno.punto_venta FK nullable`, apertura de turno exige POS en modo `multi_pos`.

- [ ] **Step 1: Write the failing test**

```python
def test_pos_requiere_almacen_y_turno_exige_pos():
    assert crear_pos_sin_almacen_falla()
    set_modo('multi_pos')
    assert abrir_turno_sin_pos_falla()
    assert abrir_turno_con_pos_ok()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_modos.TestPuntoVenta -v 2`
Expected: FAIL (modelo no existe)

- [ ] **Step 3: Implement `PuntoVenta` y selector de POS en apertura de turno**

Un POS ↔ un almacén (varios POS pueden compartir almacén); `Empleado.punto_venta` se fija al abrir turno; varios trabajadores pueden compartir POS en turnos propios.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_modos.TestPuntoVenta -v 1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/models.py core/views.py core/admin.py core/migrations/ core/tests_modos.py
git commit -m "feat: entidad PuntoVenta y turno con POS"
```

### Task 4: Ventas multi-POS desde el almacén

**Files:**
- Modify: `core/models.py` (`Venta.punto_venta`), `core/views.py` (`pos`, `pos_catalogo`, `pos_procesar_venta`, `pos_buscar_productos`), `templates/core/pos.html` (origen de stock)
- Test: `core/tests_modos.py` (`TestVentasMultiPos`)

**Interfaces:**
- Consumes: `PuntoVenta`, `Turno.punto_venta` de Task 3.
- Produces: ventas en multi-POS descuentan `AlmacenStock` del almacén del POS y guardan `Venta.punto_venta`; catálogo POS = existencias de ese almacén.

- [ ] **Step 1: Write the failing test**

```python
def test_venta_descuenta_almacen_asignado():
    vender_en_pos(pos1, prod, 2)
    assert stock(prod, almacen1) == 8 and prod.stock == 0
    assert venta.punto_venta == pos1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_modos.TestVentasMultiPos -v 2`
Expected: FAIL (descuenta `Producto.stock`)

- [ ] **Step 3: Implement descuento por almacén en `pos_procesar_venta` y catálogo por almacén**

En modo `multi_pos`: stock/disponibilidad desde `AlmacenStock` del almacén del turno; sin POS asignado se bloquea con mensaje; `Producto.stock` no se toca.

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_modos.TestVentasMultiPos core.tests -v 1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/models.py core/views.py templates/core/pos.html core/tests_modos.py
git commit -m "feat: ventas multi-POS desde almacen asignado"
```

### Task 5: IPB, ventas y traslados por POS

**Files:**
- Modify: `core/views.py` (`ipb`, `venta_lista`, `almacen_traslado_crear` bloqueo →POS en multi, `arqueos`), `templates/core/ipb.html`, `templates/core/venta_lista.html`
- Test: `core/tests_modos.py` (`TestReportesPorPos`)

**Interfaces:**
- Consumes: `Venta.punto_venta`, `Turno.punto_venta` de Tasks 3-4.
- Produces: IPB/ventas con filtro `?pos=` y cálculo sobre el almacén de cada POS; traslado→POS bloqueado en multi-POS.

- [ ] **Step 1: Write the failing test**

```python
def test_ipb_y_ventas_por_pos_y_sin_traslado_a_pos():
    assert ipb(pos1) != ipb(pos2)
    assert traslado_a_pos_bloqueado_en_multi()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_modos.TestReportesPorPos -v 2`
Expected: FAIL

- [ ] **Step 3: Implement filtros por POS y bloqueo de traslado→POS en multi**

IPB por almacén del POS; ventas/arqueos filtran por `punto_venta`; `destino_tipo=POS` rechazado en multi-POS (solo entre almacenes).

- [ ] **Step 4: Run test to verify it passes**

Run: `python manage.py test core.tests_modos -v 1`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add core/views.py templates/core/ipb.html templates/core/venta_lista.html core/tests_modos.py
git commit -m "feat: IPB y reportes por POS"
```

### Task 6: Migración final y suite completa

**Files:**
- Modify: solo fixes
- Test: suite completa

**Interfaces:**
- Consumes: Tasks 1-5.
- Produces: suite verde en los 3 modos + checklist responsive/dark.

- [ ] **Step 1: Write the failing test (cambio de modo ida y vuelta)**

```python
def test_ida_y_vuelta_conserva_todo():
    set_modo('solo_pos'); set_modo('pos_almacenes')
    assert todo_nivel_inicial()
```

- [ ] **Step 2: Run full suite to verify**

Run: `python manage.py test core -v 1`
Expected: PASS todo; manual por modo: menús, POS, IPB, Configuración

- [ ] **Step 3: Commit fixes (si los hay)**

```bash
git add -A
git commit -m "fix: pulido modos de operacion"
```
