# Spec: Vitrina pública /store (Marketplace con existencias en tiempo real)

- Fecha: 2026-10-13
- Estado: aprobado en chat (diseño), pendiente revisión del archivo
- Convive con `/catalogo` (no se modifica ni redirige)

## 1. Objetivo y alcance

Dar a usuarios externos una URL pública `/store/` estilo Marketplace que liste
todos los productos del Punto de Venta con sus existencias exactas en tiempo
real, nutrida de la misma fuente que el POS y con estilos del panel admin
(tokens `DESIGN.MD`).

Dentro del alcance:
- Solo vitrina con stock (sin carrito, sin compra, sin pedido).
- Mostrar cantidad exacta (ej. `12`, `3.5 (lb)`) + semáforo
  Disponible / Pocas unidades / Agotado.
- Tiempo real por polling (~20 s) contra API JSON pública.
- Estilos similares al admin: fondo `--bg #f7f7fb`, acento `#6f53d9`,
  `Inter` + `JetBrains Mono`, patrones DESIGN.MD (búsqueda §5.1, chips §4.3,
  product-card §6.1, pills §8), dark mode con llave `bizm_theme`.

Fuera del alcance (YAGNI):
- Carrito, checkout, pagos, envíos, cuentas de cliente.
- Push instantáneo (WebSocket/SSE/Redis).
- Modificar `/catalogo`, `base.html` o `static/css/styles.css` global.

## 2. Contexto existente

- `core/views.py:1305` `pos()`: en `solo_pos`/`pos_almacenes` vende
  `Producto(activo, visible_pos, stock>0)`; en `multi_pos` vende stock del
  `AlmacenStock` del almacén del turno (`_turno_pos_almacen`, `_stock_map_para`).
- `core/views.py:1639` `pos_catalogo()`: payload interno del POS (no reutilizar
  tal cual en público: expone factores/ids y exige turno en multi-POS).
- `core/views.py:4944` `catalogo()`: vitrina pública actual, solo
  Disponible/Agotado, sin stock exacto ni refresco. Se conserva intacta.
- `core/models.py`: `Producto.stock` (base, 3 decimales),
  `fmt_cantidad_unidad()`, `PresentacionProducto`, `AlmacenStock`,
  `ConfiguracionTienda` (nombre/logo/moneda/símbolo/acento/tema).
- `DESIGN.MD` + `static/css/styles.css`: tokens y patrones homogéneos.
- Patrón de polling público ya probado: `mostrador_estado` (`views.py:4990`).

## 3. Arquitectura

```
visitante ──GET /store/──────────────▶ store(): HTML server-render (SEO + datos iniciales)
visitante ──GET /store/api/estado/ ──▶ store_api_estado(): JSON {productos, actualizado}
                 ▲ cada 20 s (fetch, actualiza solo precio/stock/badges)
POS/Admin ──vende / edita stock────▶ BD (Producto.stock / AlmacenStock) ──▶ lo lee el API
```

- Dos endpoints públicos nuevos, sin login, solo GET, en `core/urls.py`
  (`app_name='core'`, nombres `store` y `store_api`).
- Sin dependencias nuevas. Compatible con Passenger multiproceso
  (sin Redis/Channels, sin estado en memoria).

## 4. Datos

### 4.1 Helper `_stock_store()`

- Si `modo_actual() == 'multi_pos'`: suma `AlmacenStock.cantidad` por
  `producto_id` sobre almacenes activos (incluye filas legacy `almacen=NULL`
  solo si no hay propia, misma regla que `_stock_map_para`). Productos base:
  `Producto(activo=True)` (se ignora `visible_pos`, igual que el POS multi).
- En otro modo: `Producto(activo=True, visible_pos=True)`, `stock = p.stock`.
- Se listan también los agotados (`stock <= 0`) con badge rojo.

### 4.2 Item de vitrina

Por producto: `id, codigo, nombre, categoria (nombre), imagen_url`,
`precio` = presentación default o `precio_venta`, `etiqueta` = nombre de la
presentación o unidad, `stock` (Decimal exacto), `stock_fmt`
(`fmt_cantidad_unidad`), `disponible = stock > 0`,
`pocas_unidades = 0 < stock <= stock_minimo`.

El API devuelve por producto solo: `id, precio (str), stock (str), stock_fmt,
disponible, pocas_unidades`. NUNCA `precio_compra`, `stock_minimo`, proveedor.

### 4.3 Vista `store()`

- `cfg = ConfiguracionTienda.get_solo()` → nombre, logo_url, moneda, símbolo.
- Categorías distintas + productos ordenados por nombre (límite 2000).
- Agrupa por categoría + sección `Otros` (sin categoría), como `catalogo()`.
- Contexto: `grupos, total, tienda, simbolo_moneda, actualizado (now)`.

### 4.4 API `store_api_estado()`

- GET público. Respuesta: `{'productos': [...], 'actualizado': 'HH:MM:SS'}`.
- Siempre 200 con lista (vacía si no hay productos). Sin paginación v1
  (hasta 2000 filas, payload ~200 KB máx, aceptable cada 20 s en red local;
  si crece, v2 con `?ids=`).

## 5. UI (`templates/core/store.html`, archivo nuevo, standalone)

- No extiende `base.html` (pública, sin sidebar). `<style>` propio con `:root`
  de `DESIGN.MD §2` (respeta `TIENDA.color_acento` si está configurado).
- Header hero degradado morado + logo/nombre tienda + `N productos` +
  `Actualizado HH:MM:SS` + dot Online/Offline + toggle dark (`bizm_theme`).
- Toolbar sticky: búsqueda (debounce, insensible a tildes), chips categorías,
  checkbox "Solo disponibles", select orden (Nombre, Precio ↑↓, Stock ↓).
- Grid `repeat(auto-fill,minmax(170px,1fr))`, gap 12 px; responsive 2 cols en
  ≤480 px, 1 col en ≤360 px; `padding-bottom` para no tapar nada.
- Card (patrón §6.1): img 110 px (fallback iniciales mono), nombre 13 px,
  SKU mono 10 px, etiqueta pres 11 px, precio mono 17 px accent, fila stock:
  cantidad exacta mono + pill (`Disponible` success / `¡Solo X!` warning /
  `Agotado` danger).
- Footer: tienda + moneda + "Solo vitrina, sin compra en línea".
- JS: filtra en cliente; polling `fetch` 20 s actualiza por `data-id`;
  ante fallo mantiene última data + dot rojo "Sin conexión".
- Dark: `html[data-theme="dark"]` con superficies `#1e1e2a` / fondo `#14141c`.

## 6. Errores y seguridad

- API GET-only, sin login, sin parámetros que alteren BD. No expone costos.
- Template escapa todo (Django autoescape); imágenes por URL ya validada
  (`imagen_url`); `onerror` oculta imagen rota.
- Sin productos → empty state "Aún no hay productos publicados".
- Polling con `try/catch`: nunca rompe la página.

## 7. Verificación

- Manual: `/store` y `/store/api/estado` responden sin login; vender en POS
  se refleja en ≤25 s; filtros/búsqueda/orden; 375 px y 768 px sin scroll
  horizontal; dark persiste (`bizm_theme`).
- Auto: test `GET /store` 200 con stock exacto visible; test API 200 sin
  `precio_compra` en el payload; test multi-POS suma `AlmacenStock`.

## 8. Archivos

- Nuevo: `templates/core/store.html`.
- Editar: `core/urls.py` (+ `path('store/')`, `path('store/api/estado/')`),
  `core/views.py` (+ `store`, `store_api_estado`, helper `_stock_store`).
- No tocar: `catalogo.html`, `base.html`, `styles.css`, `DESIGN.MD`.
