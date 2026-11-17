# Selector por tarjetas + visibilidad POS tras traslado — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** La Entrada del almacén selecciona producto con tarjetas visuales, y el producto creado desde el almacén permanece invisible para el POS hasta su primer traslado.

**Architecture:** Flag explícito `Producto.visible_pos` (migración que preserva a los existentes), filtros en queries POS/IPB/catálogo/conteos, publicación en el primer traslado, y tarjetas en el form que sincronizan un `<select>` oculto sin cambiar el contrato POST.

**Tech Stack:** Django 5 + Bootstrap 5 + Bootstrap Icons (templates `templates/`, vistas `core/views.py`).

**Spec:** `docs/superpowers/specs/2026-10-06-almacen-selector-tarjetas-visibilidad-design.md`

## Global Constraints

- Comandos de verificación: `python manage.py check` y `python manage.py test core -v 1` (suite completa al final de cada tarea; parcial `python manage.py test core.tests_almacen_visibilidad -v 2` durante).
- TDD: test RED verificado que falla por la razón esperada antes de cada cambio de producción.
- No tocar: `producto_lista/detalle`, `submayor`, `ajuste_inventario`, `dashboard`, `entrada_lista`, `mi_panel`, `arqueo`, formularios de Traslado/Ajuste.
- El almacenero no crea productos: el botón "Nuevo producto" solo existe para admin (igual que hoy).
- No commitear `db.sqlite3` nunca.

## Review Focus

- Ítem del POS manipulado con `id` de producto oculto pero `stock > 0` (craft): el procesador debe rechazarlo aunque el stock alcance — test en Tarea 2.
- `?next=` malicioso (`//evil`, con espacios) en `producto_crear`: debe ignorarse y caer a `producto_lista` — test en Tarea 2.
- `?producto=<id inexistente>` en Entrada: no preselecciona nada ni rompe el grid — test en Tarea 3.
- Traslado de un producto ya visible: sigue funcionando igual (idempotente) — test en Tarea 2.
- Productos preexistentes tras migrar: todos `visible_pos=True` — test en Tarea 1.

---

### Task 1: Campo `visible_pos` + migración

**Files:**
- Modify: `core/models.py` (`Producto`, junto a `activo`)
- Create: `core/migrations/0024_*.py` (vía `makemigrations`, editar el `RunPython`)
- Test: `core/tests_almacen_visibilidad.py`

**Interfaces:**
- Consumes: nada (primera tarea).
- Produces: `Producto.visible_pos: bool` (default `True`); migración que deja `True` a filas existentes. Las Tareas 2–3 lo leen/escriben.

- [ ] **Step 1: Write the failing test**

```python
from django.test import TestCase
from django.contrib.auth.models import User
from .models import PerfilUsuario, Producto

class VisibilidadMigracionTest(TestCase):
    def test_productos_existentes_nacen_visibles(self):
        p = Producto.objects.create(nombre='Viejo', unidad_medida='unidades',
                                    precio_compra=1, precio_venta=2)
        p.refresh_from_db()
        self.assertTrue(p.visible_pos)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python manage.py test core.tests_almacen_visibilidad -v 2`
Expected: FAIL/ERROR con `AttributeError` o campo inexistente (no por typo en el test).

- [ ] **Step 3: Add `visible_pos = models.BooleanField(default=True)` a `Producto` en `core/models.py`**

Campo junto a `activo`, con comentario "False = solo existe en almacén hasta su primer traslado".

- [ ] **Step 4: Generar y completar la migración**

Run: `python manage.py makemigrations core`
Luego añadir `RunPython` que ponga `visible_pos=True` a todas las filas existentes (no-op de comportamiento) con su reverso `noop`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python manage.py test core.tests_almacen_visibilidad -v 2`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add core/models.py core/migrations/0024_*.py core/tests_almacen_visibilidad.py
git commit -m "feat(almacen): flag visible_pos con migracion que preserva existentes"
```

---

### Task 2: Crear-oculto, traslado-publica y filtros POS

**Files:**
- Modify: `core/views.py` (`producto_crear`, `almacen_traslado_crear`, filtros `pos`, `pos_buscar_productos`, `pos_catalogo` + categorías, `_sincronizar_inventario_dia`, inventarios IPB, `catalogo` + categorías, `deuda_crear`, `retiro_donacion_crear`, `conteo_contar`, `conteo_autosave`, `conteo_cerrar`, defensa en `pos_procesar_venta`)
- Test: `core/tests_almacen_visibilidad.py` (ampliar)

**Interfaces:**
- Consumes: `Producto.visible_pos` de la Tarea 1.
- Produces: regla "crear-desde-almacén ⇒ `stock=0, visible_pos=False`"; "primer traslado ⇒ `visible_pos=True`"; queries POS filtradas. La Tarea 3 consume `preseleccionado` + `stock_json` ya existentes en `almacen_entrada_crear`.

- [ ] **Step 1: Write the failing tests**

```python
def test_crear_desde_almacen_nace_oculto_y_sin_stock(self):
    next_url = reverse('core:almacen_entrada_crear')
    r = self.client.post(reverse('core:producto_crear') + f'?next={next_url}', {..., 'stock': '5', 'next': next_url, ...formset...})
    prod = Producto.objects.get(nombre='Nuevo Oculto')
    self.assertEqual(prod.stock, 0)
    self.assertFalse(prod.visible_pos)

def test_oculto_no_sale_en_pos_ni_catalogo_ni_ipb(self):
    # pos_buscar no lo devuelve; _sincronizar_inventario_dia no le crea fila
    ...

def test_traslado_publica_y_genera_entrada_ipb(self):
    # trasladar ⇒ visible_pos True + EntradaProducto proveedor 'Almacén'
    ...

def test_crear_normal_sigue_visible(self):
    # sin next ⇒ visible_pos True, stock respetado
    ...

def test_procesar_venta_rechaza_oculto(self):
    # POST a pos_procesar_venta con id oculto ⇒ 400 aunque el stock alcanzara
    ...

def test_next_malicioso_se_ignora(self):
    # next='//evil.com/x' ⇒ redirect a producto_lista, producto visible
    ...
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test core.tests_almacen_visibilidad -v 2`
Expected: FAIL en los nuevos (campo existe pero la lógica aún no).

- [ ] **Step 3: Implement en `producto_crear`**

Si el `next` seguro apunta a `/almacen/`: tras `form.save()`, forzar `producto.stock = 0` y `producto.visible_pos = False` (save `update_fields`) + mensaje informativo. Si no, `visible_pos = True` explícito. `next` malicioso se ignora (helper `_next_seguro` ya existe).

- [ ] **Step 4: Implement en `almacen_traslado_crear`**

Tras el traslado exitoso dentro del bloque atómico: si `not producto.visible_pos`, poner `True` y mensaje "ahora visible en el punto de venta".

- [ ] **Step 5: Añadir `visible_pos=True` a los filtros POS**

En `core/views.py`: `pos`, `pos_buscar_productos`, `pos_catalogo` (+ `productos__visible_pos=True` en sus categorías), `_sincronizar_inventario_dia`, query `inventarios` del IPB (`producto__visible_pos=True`), `catalogo` (+ categorías), `deuda_crear`, `retiro_donacion_crear`, `conteo_contar`, `conteo_autosave`, `conteo_cerrar`. Defensa en `pos_procesar_venta`: rechazar ítem si `not producto.activo or not producto.visible_pos`.

- [ ] **Step 6: Run tests to verify they pass**

Run: `python manage.py test core -v 1`
Expected: PASS la suite completa (25 existentes + nuevos).

- [ ] **Step 7: Commit**

```bash
git add core/views.py core/tests_almacen_visibilidad.py
git commit -m "feat(almacen): producto de almacen oculto hasta el traslado"
```

---

### Task 3: Selector por tarjetas en Nueva Entrada

**Files:**
- Modify: `templates/core/almacen_entrada_form.html` (bloque selector + CSS/JS inline)
- Modify: `core/views.py` (`almacen_entrada_crear` GET: añadir `stock_json`; ya pasa `preseleccionado` y `next_crear`)
- Test: `core/tests_almacen_visibilidad.py` (contexto de la vista)

**Interfaces:**
- Consumes: `preseleccionado`, `next_crear` (existentes) y `stock_json` (nuevo, mismo formato `{"id": "cantidad"}` que usan traslado/ajuste).
- Produces: grid de tarjetas que escribe el `<select name="producto">` oculto; el POST no cambia.

- [ ] **Step 1: Write the failing tests**

```python
def test_entrada_expone_stock_json_y_preseleccionado(self):
    r = self.client.get(reverse('core:almacen_entrada_crear') + f'?producto={prod.pk}')
    self.assertEqual(str(r.context['preseleccionado']), str(prod.pk))
    self.assertIn(str(prod.pk), r.context['stock_json'])

def test_entrada_con_producto_inexistente_no_preselecciona(self):
    r = self.client.get(reverse('core:almacen_entrada_crear') + '?producto=999999')
    self.assertEqual(r.status_code, 200)
    self.assertNotIn('selected', r.content.decode().split('productoSelect')[1][:2000])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python manage.py test core.tests_almacen_visibilidad -v 2`
Expected: FAIL (`stock_json` ausente en el contexto).

- [ ] **Step 3: Pasar `stock_json` en `almacen_entrada_crear`**

Igual que `almacen_traslado_crear`: `stock_map` desde `AlmacenStock` y `stock_json` con `json.dumps` (el `json` ya está importado en views).

- [ ] **Step 4: Reemplazar el bloque selector por el grid de tarjetas**

Tarjeta por producto: foto (`imagen_url` o placeholder con inicial), código mono, nombre, costo actual, existencia (de `stock_json`) y unidad. Clic ⇒ marca visual + `select.value = id` + dispara la lógica existente de costo/unidad/total. Buscador filtra tarjetas en vivo (código/nombre, sin tildes) con contador y estado vacío ("Crear el producto aquí" solo admin). `?producto=` marca la tarjeta al cargar. Sin fotos rotas: `onerror` oculta la `img`.

- [ ] **Step 5: Run tests + verificación manual del JS**

Run: `python manage.py test core -v 1`
Expected: PASS suite completa. Además abrir `/almacen/entradas/nueva/` y comprobar: filtrado, clic-selección, preselección `?producto=`, envío arma la Entrada.

- [ ] **Step 6: Commit**

```bash
git add core/views.py templates/core/almacen_entrada_form.html core/tests_almacen_visibilidad.py
git commit -m "feat(almacen): selector por tarjetas con foto en Entrada"
```
