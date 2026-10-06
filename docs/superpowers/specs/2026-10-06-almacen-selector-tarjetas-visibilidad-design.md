# Diseño: selector por tarjetas en Entrada + visibilidad POS solo tras traslado

Fecha: 2026-10-06
Estado: aprobado por el usuario (las 3 secciones)

## 1. Intento y éxito

- La Nueva Entrada del almacén selecciona producto con tarjetas visuales
  (foto, código, nombre, costo, existencia) en vez del `<select>` plano.
- El producto creado desde el almacén nace invisible para todo lo del
  punto de venta (POS, IPB, cierre/arqueo por vía del IPB, catálogo,
  conteos, deudas/donaciones de producto) hasta su primer traslado al POS.
- Sigue visible en Almacén (panel, existencias, entradas, traslados,
  auditoría, ajuste) y en Productos (admin).
- Éxito: crear desde almacén deja stock POS en 0 y no aparece en
  `pos_buscar`, catálogo ni IPB; trasladar lo publica y genera la entrada
  del IPB como hoy.

## 2. Enfoque elegido (A) y descartados

- A — Flag explícito `Producto.visible_pos` (default True), migración que
  deja True a todos los existentes, filtros en queries POS. Explícito y
  no cambia el comportamiento actual de ningún producto existente.
- B — Regla inferida (stock 0 y sin movimientos = oculto). Descartado:
  un producto normal agotado desaparecería del IPB histórico y del conteo.
- C — Reusar `activo=False`. Descartado: lo sacaría también del selector
  del almacén y de Productos, y pervierte "inactivo".

## 3. Sección 1 — Selector por tarjetas (solo `almacen_entrada_form.html`)

- Grid responsive de tarjetas: foto (`imagen_url` o placeholder con
  inicial), código (mono), nombre, costo actual, existencia en almacén y
  badge de unidad. Clic = seleccionar (borde acentuado + check).
- Buscador en vivo por código/nombre insensible a tildes, contador
  "X de Y", estado vacío con enlace "Crear el producto aquí" (solo admin).
- El `<select name="producto">` se conserva oculto y sincronizado: el POST
  y `views.almacen_entrada_crear` (core/views.py:2474) no cambian de
  contrato. `?producto=` preselecciona la tarjeta y enfoca cantidad.
- La vista pasa además `stock_json` (como ya hacen traslado/ajuste) para
  pintar existencias sin consulta extra.
- No se tocan traslado/ajuste (decisión del usuario).

## 4. Sección 2 — Visibilidad hasta el traslado

- Modelo (`core/models.py`, `Producto`, hoy ~línea 194): nuevo campo
  `visible_pos = models.BooleanField(default=True)`.
- Migración `core/migrations/0024_*`: crea el campo y con `RunPython`
  marca `visible_pos=True` a todos los productos existentes (sin cambios
  de comportamiento para lo ya creado).
- `producto_crear` (core/views.py:241): si el `next` apunta a `/almacen/`,
  guarda con `stock=0` y `visible_pos=False` + mensaje "nace solo en
  almacén; trasládelo para publicarlo". Sin `next` de almacén, igual que
  hoy (`visible_pos=True`).
- `almacen_traslado_crear` (core/views.py:2551): tras el traslado exitoso,
  `visible_pos=True` (`update_fields`) + mensaje "ahora visible en el POS".
- Filtros `visible_pos=True` (solo lectura/venta POS; admin y almacén
  intactos): `pos` (:1153), `pos_buscar_productos` (:1200),
  `pos_catalogo` (:1354) + categorías (:1357),
  `_sincronizar_inventario_dia` (:1674), inventarios del IPB (:1431),
  `catalogo` (:3620) + categorías (:3623), `deuda_crear` (:3236),
  `retiro_donacion_crear` (:2719), `conteo_contar` (:4150),
  `conteo_autosave` (:4224), `conteo_cerrar` (:4276).
- Defensa en `pos_procesar_venta` (:1258): rechazar ítem cuyo producto no
  esté activo y visible (además del control de stock ya existente).
- Sin tocar: `producto_lista/detalle`, `venta_crear/editar` (el stock 0 ya
  impide vender; el chequeo explícito queda solo en el procesador),
  `submayor`, `ajuste_inventario`, `dashboard`, `entrada_lista`,
  `mi_panel`/`arqueo` (no listan productos), todo `almacen_*`.

## 5. Sección 3 — Pruebas (TDD, RED antes de GREEN)

- Nuevo `core/tests_almacen_visibilidad.py`:
  1. crear con `next=/almacen/entradas/nueva/` deja `stock=0`,
     `visible_pos=False` y no sale en `pos_buscar` ni `catalogo` ni lo
     crea `_sincronizar_inventario_dia`.
  2. trasladar lo publica (`visible_pos=True`) y genera la entrada IPB.
  3. crear normal queda visible de inmediato.
  4. la migración deja `visible_pos=True` en productos preexistentes.
- Suite existente (`python manage.py test core`) debe seguir en verde.
- JS del selector: verificación manual en navegador (filtrado,
  preselección `?producto=`, envío del formulario).

## 6. Riesgos y límites

- Productos existentes: la migración los deja visibles; ningún cambio.
- El almacenero no puede crear productos (permiso actual de
  `producto_crear`); el botón solo se muestra al admin, igual que hoy.
- El grid renderiza todas las tarjetas y filtra en cliente (volumen
  actual de productos lo permite); si el catálogo creciera mucho, se
  pagina después, fuera de este alcance.
