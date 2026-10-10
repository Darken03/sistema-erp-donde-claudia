# DESIGN.MD — Sistema de Diseño Homogéneo BizMaster / ERP

> Fuente visual: `pos.vue` de referencia (estilo "Refined Classic" / POS.html).
> Objetivo: un solo lenguaje visual para TODA la página (POS, dashboard, listas, formularios, modales).
> Stack actual: Django templates + Bootstrap 5.3 + Bootstrap Icons + CSS propio (`static/css/styles.css`).
> Este archivo es la especificación. `static/css/styles.css` es la implementación.

---

## 1. Principios

1. **Claro primero**: fondo gris muy claro, superficies blancas, texto oscuro. Nada de paneles oscuros grandes (el carrito oscuro anterior queda prohibido).
2. **Un solo acento**: morado `#6f53d9`. Todo lo clicable-primario, precios y foco usan este color.
3. **Monoespaciado para números**: precios, cantidades, SKUs, referencias, badges numéricos → `JetBrains Mono`.
4. **Texto normal**: `Inter` (fallback sistema).
5. **Bordes suaves**: radios 6–12px, borde fino `#e6e6ec`, sombras mínimas.
6. **Densidad POS**: alturas 28–40px, tipografía 11–14px. En admin/listas se permite 38–44px.
7. **Offline-first en POS**: vender nunca se bloquea por red. La cola offline es parte del diseño (pill + botón sync + banner).

---

## 2. Tokens (variables CSS)

Definidos en `:root` dentro de `static/css/styles.css`:

```css
:root {
  --accent: #6f53d9;
  --accent-strong: #5b3fd4;
  --accent-soft: #ece9fb;
  --accent-tint: #f5f3fd;
  --accent-shadow: rgba(111, 83, 217, 0.32);

  --bg: #f7f7fb;
  --bg-deep: #f1f1f6;
  --surface: #ffffff;
  --soft: #f3f3f7;

  --line: #e6e6ec;
  --line-strong: #d8d8e0;

  --ink: #1f1f2c;
  --ink-2: #54546a;
  --ink-3: #8d8da0;

  --success: #2fae5e;
  --success-dark: #1e7a44;
  --success-soft: #eaf7ef;

  --danger: #d64545;
  --danger-dark: #a83232;
  --danger-soft: #fdecec;
  --danger-soft-2: #fef2f2;

  --warning: #f59e0b;
  --info: #0ea5e9;

  --font-sans: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  --font-mono: 'JetBrains Mono', 'SFMono-Regular', Menlo, Consolas, monospace;

  --r-sm: 6px;
  --r-md: 8px;
  --r-lg: 10px;
  --r-xl: 12px;
  --r-pill: 99px;

  --shadow-sm: 0 2px 8px -4px rgba(20,20,40,.12);
  --shadow-md: 0 8px 24px rgba(20,20,40,.08);
  --shadow-accent: 0 4px 14px rgba(111,83,217,.32);
}
```

### Paleta funcional

| Uso | Token / valor |
|---|---|
| Fondo página | `--bg #f7f7fb` |
| Superficie (cards, header, modales) | `--surface #ffffff` |
| Superficie alternativa (hover fila, input search) | `--soft #f3f3f7` |
| Borde default | `--line #e6e6ec` |
| Borde hover/fuerte | `--line-strong #d8d8e0` |
| Texto principal | `--ink #1f1f2c` |
| Texto secundario | `--ink-2 #54546a` |
| Texto terciario / placeholder / iconos | `--ink-3 #8d8da0` |
| Primario / acento | `--accent #6f53d9` |
| Tinta sobre acento | `#ffffff` |
| Precio en cards producto | `--accent`, mono 14px bold |
| Éxito (OPEN, pagado, en turno) | fondo `--success-soft`, texto `--success-dark`, dot `--success` |
| Peligro (CLOSED, deuda, error) | fondo `--danger-soft`, texto `--danger-dark` |
| Offline | fondo `--danger-soft-2`, borde `#fecaca`, texto `--danger-dark` |
| Fondo degradado avatar | `linear-gradient(135deg,#6f53d9,#b65cd6)` |

### Tipografía

```css
body { font-family: var(--font-sans); color: var(--ink); background: var(--bg); }
.mono, .price, .qty, .sku, .badge-count { font-family: var(--font-mono); }
```

- Importar en `base.html`: Inter 400/500/600/700 + JetBrains Mono 400/500/600/700.
- Títulos card: 13–14px, 600, `letter-spacing: -0.01em`.
- Eyebrow / label pequeño: 9–11px, 700, `letter-spacing: .08em`, uppercase, color `--ink-3`.
- Precio grande (Total a pagar): 20px, 700, mono.
- SKU / stock: 10–11px, mono, color `--ink-3`.

---

## 3. Botones

### 3.1 Botón primario (Cobrar / Pay Now / Guardar)

```css
.btn-pay, .btn-primary-hom {
  height: 48px; padding: 0 28px;
  background: var(--accent); color: #fff; border: 0;
  border-radius: var(--r-lg); font-size: 15px; font-weight: 600;
  display: inline-flex; align-items: center; gap: 10px;
  box-shadow: var(--shadow-accent); cursor: pointer;
  transition: filter 120ms, box-shadow 120ms;
}
.btn-pay:hover:not(:disabled) { filter: brightness(1.05); box-shadow: 0 6px 18px rgba(111,83,217,.45); }
.btn-pay:disabled { opacity: .5; cursor: not-allowed; box-shadow: none; }
```

En móvil: `width:100%; justify-content:center; height:48px`.

### 3.2 Botón secundario / acción (Home, Reset, Drafts, Hold)

```css
.btn-action, .pos-shell-action-btn {
  height: 36px; padding: 0 14px;
  background: transparent; color: var(--ink);
  border: 1px solid var(--line); border-radius: var(--r-md);
  font-size: 13px; font-weight: 500;
  display: inline-flex; align-items: center; gap: 8px;
}
.btn-action:hover { background: var(--soft); border-color: var(--line-strong); }
.btn-action svg, .btn-action i { width:16px; height:16px; }
```

Variante móvil icon-only (≤480px): `width:38px; padding:0; span{display:none}`.

### 3.3 Botón icono cuadrado 32px (toolbar)

```css
.icon-btn {
  width:32px; height:32px; border-radius: var(--r-md);
  border:1px solid var(--line); background: var(--surface); color: var(--ink-2);
  display:inline-flex; align-items:center; justify-content:center; padding:0;
}
.icon-btn:hover { background: var(--soft); color: var(--ink); border-color: var(--line-strong); }
.icon-btn i { font-size:15px; }
```

Regla global: **ningún botón muestra outline feo** → `button:focus{outline:0; box-shadow:none}` excepto el search (anillo acento, ver §5).

### 3.4 Numpad (solo POS pago)

- Grid 3 columnas, gap 6px.
- Tecla: `height:44px; background:var(--soft); border:1px solid var(--line); border-radius:8px; font-family:mono; font-size:16px; font-weight:600`.
- Tecla acción (C / ⌫): fondo `--danger-soft`, texto `--danger-dark`.

---

## 4. Selects — el patrón homogéneo

Hay 3 sabores. **No mezclar estilos.**

### 4.1 Select nativo (formularios admin, modales gasto/deuda/donación)

```css
.form-select-hom, .form-select {
  height:38px; padding:0 32px 0 12px; font-size:13px; color:var(--ink);
  background-color: var(--surface); border:1px solid var(--line); border-radius: var(--r-md);
  appearance:none;
  background-image:url("data:image/svg+xml,...chevron...");
  background-repeat:no-repeat; background-position:right 10px center; background-size:14px;
  cursor:pointer;
}
.form-select:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-tint); outline:0; }
```

Altura: 38px en formularios, 32px en toolbar (`select.toolbar{height:32px;font-size:12px}`).

### 4.2 Trigger-chip (POS toolbar: almacén/cliente/categoría/marca)

No es un `<select>` nativo: es un botón que abre drawer/modal. Estructura:

```
[icon-chip] [eyebrow + label] [chevron]
```

```css
.select-trigger {
  display:inline-flex; align-items:center; gap:10px; height:40px; padding:0 10px 0 6px;
  border-radius:12px; border:1px solid var(--line); background:var(--surface);
  min-width:180px; max-width:240px; cursor:pointer;
}
.select-trigger .avatar { width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#6f53d9,#b65cd6);color:#fff;font-size:12px;font-weight:700;display:grid;place-items:center; }
.select-trigger .eyebrow { font-size:10px;font-weight:600;letter-spacing:.5px;text-transform:uppercase;color:var(--ink-3); }
.select-trigger .label { font-size:13px;font-weight:700;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis; }
```

- Cliente: borde `#fbe4ed`, fondo `linear-gradient(135deg,#fff5f8,#fff)`, eyebrow `#be185d`.
- Categoría/marca: icono 22px con fondo `rgba(111,83,217,.12)`, color acento.
- Estado activo: fondo `var(--accent-tint)`, label color acento.

### 4.3 Category-chip (filtros rápidos)

```css
.pos-chips { display:flex; flex-wrap:wrap; gap:6px; align-items:center; justify-content:flex-start; }
.category-chip {
  display:inline-flex; align-items:center; justify-content:center; flex:0 0 auto; width:auto; max-width:100%;
  white-space:nowrap; line-height:1.2;
  padding:6px 12px; border-radius:var(--r-pill); font-size:12px; font-weight:500;
  background:var(--surface); border:1px solid var(--line); color:var(--ink-2); cursor:pointer;
}
.category-chip:hover { border-color:var(--accent); color:var(--accent); }
.category-chip.active { background:var(--accent); border-color:var(--accent); color:#fff; font-weight:600; }
```

---

## 5. Inputs

### 5.1 Búsqueda (barra principal POS + listas)

```css
.search-wrap { position:relative; display:flex; align-items:center; height:40px; }
.search-wrap i { position:absolute; left:14px; color:var(--ink-3); pointer-events:none; }
.search-input {
  width:100%; height:40px; padding:0 12px 0 38px; font-size:13px; color:var(--ink);
  background:var(--surface); border:1px solid var(--line); border-radius:var(--r-md); outline:none;
}
.search-input:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-tint); }
.search-input::placeholder { color:var(--ink-3); }
```

En listas admin: misma clase, altura 38px.

### 5.2 Campo numérico con prefijo/sufijo (Tax / Discount / Shipping / montos)

```css
.field-charge { display:flex; align-items:center; height:32px; border:1px solid var(--line); border-radius:6px; background:var(--surface); overflow:hidden; }
.field-charge input { flex:1; border:0; height:100%; padding:0 8px; font-family:var(--font-mono); font-size:12px; color:var(--ink); background:transparent; outline:none; min-width:0; }
.field-charge .affix { padding:0 8px; color:var(--ink-3); font-family:var(--font-mono); font-size:12px; border-left:1px solid var(--line); height:100%; display:inline-flex;align-items:center; }
```

Label encima: eyebrow 9px uppercase (ver §2).

### 5.3 Cantidad (stepper carrito)

```css
.qty-stepper { display:inline-flex; align-items:center; border:1px solid var(--line); border-radius:5px; height:24px; background:var(--surface); }
.qty-stepper button { width:22px;height:22px;background:transparent;border:0;color:var(--ink-2);font-size:14px;cursor:pointer; }
.qty-stepper input { width:32px;height:100%;border:0;text-align:center;font-size:12px;font-family:var(--font-mono);background:transparent;color:var(--ink);outline:none; }
```

En táctil (≤1024px): altura 28px, botones 26px.

### 5.4 Formularios generales

```css
.form-control-hom { height:38px; border:1px solid var(--line); border-radius:var(--r-md); font-size:13px; padding:0 12px; }
.form-control-hom:focus { border-color:var(--accent); box-shadow:0 0 0 3px var(--accent-tint); }
```

---

## 6. Cards

### 6.1 Producto (grid POS y listas)

```css
.product-card { background:var(--surface); border:1px solid var(--line); border-radius:var(--r-xl); padding:10px; cursor:pointer; transition:border-color 120ms, box-shadow 120ms, transform 120ms; }
.product-card:hover { border-color:var(--accent); box-shadow:var(--shadow-sm); transform:translateY(-1px); }
.product-card .img-zone { margin:-10px -10px 8px; height:90px; border-radius:12px 12px 0 0; background:repeating-linear-gradient(135deg,#ece9fb,#ece9fb 8px,#f5f3fd 8px,#f5f3fd 16px); display:grid;place-items:center; overflow:hidden; }
.product-card .img-zone .initials { font-family:var(--font-mono); font-weight:700; font-size:18px; color:rgba(31,31,44,.55); }
.product-card .name { font-size:13px; font-weight:500; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.product-card .sku { font-size:10px; color:var(--ink-3); font-family:var(--font-mono); white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.product-card .price { font-size:14px; font-weight:700; font-family:var(--font-mono); color:var(--accent); }
.product-card .add-btn { width:24px;height:24px;background:#f0ecfb;color:var(--accent);border-radius:6px;display:grid;place-items:center; }
.product-card .add-btn:hover { background:var(--accent); color:#fff; }
.product-card .discount-badge { position:absolute; top:6px; left:6px; background:rgba(255,255,255,.9); border-radius:6px; padding:2px 6px; color:var(--danger); font-family:var(--font-mono); font-size:10px; font-weight:700; }
```

Grid: `repeat(auto-fill,minmax(160px,1fr))`, gap 8–12px. Tablet 3 cols, móvil ≤480px 2 cols, ≤360px 1 col.

### 6.2 Fila carrito

Grid 3 columnas: `32px 1fr auto`, gap 8px, padding 6–8px, radius 8px, hover `var(--soft)`.
- Thumb 32px radius 6px (círculo en móvil).
- Columna media: nombre 13px/600 → SKU 10px mono → controles (stepper + `× precio` mono 12px).
- Columna derecha: editar/eliminar (iconos 13px, color `--ink-3`, hover acento/rojo) arriba, subtotal mono 13px/600 abajo.

### 6.3 Card genérica admin

```css
.card-hom { background:var(--surface); border:1px solid var(--line); border-radius:16px; box-shadow:var(--shadow-sm); }
.card-hom .card-header-hom { padding:14px 20px; border-bottom:1px solid var(--line); display:flex; align-items:center; justify-content:space-between; }
```

---

## 7. Tablas

```css
.table-hom { font-size:13px; }
.table-hom thead th { font-size:11px; text-transform:uppercase; letter-spacing:.05em; color:var(--ink-3); font-weight:600; border-bottom:1px solid var(--line); white-space:nowrap; }
.table-hom td { vertical-align:middle; padding:10px 12px; border-bottom:1px solid var(--soft); }
.table-hom tbody tr:hover { background:var(--accent-tint); }
```

Montos en tablas: mono, alineados a la derecha.

---

## 8. Pills / badges / estados

```css
.pill { display:inline-flex; align-items:center; gap:6px; padding:4px 8px; border-radius:6px; font-size:11px; font-weight:600; text-transform:uppercase; }
.pill .dot { width:6px;height:6px;border-radius:99px;background:currentColor; }
.pill-open { background:var(--success-soft); color:var(--success-dark); }
.pill-closed { background:var(--danger-soft); color:var(--danger-dark); }
.pill-pending { background:#fef3c7; color:#92400e; }
.badge-count { background:var(--accent-tint); color:var(--accent); padding:3px 8px; border-radius:99px; font-size:11px; font-weight:600; font-family:var(--font-mono); }
.badge-offline { background:var(--danger); color:#fff; font-size:10px; font-weight:700; border-radius:99px; padding:1px 6px; font-family:var(--font-mono); }
```

Turno en POS: `Turno #id` + pill OPEN/CLOSED (botón que abre modal abrir/cerrar).

---

## 9. Header / toolbar POS

- Altura desktop 52px, fondo blanco, borde inferior `--line`.
- Orden: [Brand 28px logo] [Turno pill] [Categoría trigger] [búsqueda flex] [spacer] [Mis Ventas icon] [Sync/offline icon+badge] [Idioma?] [Usuario avatar 32px].
- Iconos: `.icon-btn` 32px (ver §3.3).
- Divisores verticales: `width:1px;height:24px;background:var(--line)`.
- Móvil (≤768px): header en wrap, triggers a 50%, búsqueda full-width, tab-bar inferior fija 60px.

---

## 10. Bottom pay-bar

```css
.pay-bar { display:flex; align-items:center; gap:8px; padding:8px 16px; background:var(--surface); border-top:1px solid var(--line); min-height:64px; }
.pay-bar .total-label { font-size:10px; color:var(--ink-3); font-weight:700; letter-spacing:.08em; text-transform:uppercase; }
.pay-bar .total-value { font-size:20px; font-weight:700; font-family:var(--font-mono); color:var(--ink); }
```

Izquierda: indicador Online (dot verde) / Offline (dot rojo + `N pendientes`). Centro: acciones secundarias. Derecha: total + botón Pay primario.

---

## 11. Modales / drawers

### Modal Bootstrap homogéneo

- `.modal-content{border:0;border-radius:18px;overflow:hidden;box-shadow:0 24px 60px -20px rgba(31,31,44,.35)}`
- Header éxito (venta completada): fondo degradado acento, texto blanco.
- Header info: fondo blanco, título 15px/700.
- Drawers (categoría izq / cliente centro): backdrop `rgba(15,15,30,.42)` + blur 2px; panel blanco radius 18–20px; header con degradado (categoría morado, cliente rosa `#be185d→#fb7185`); lista con iconos 36–40px y check de activo.

### Ticket

Ticket térmico 80mm centrado, fuente mono para montos, QR solo si existe. Botón Imprimir = secundario outline.

---

## 12. Offline (parte del diseño, no solo código)

- Indicador header + pay-bar: dot + texto `Online` / `Offline · N pendientes`.
- Botón sync con badge numérico rojo. Click → `syncOfflineQueue()` + toast.
- Banner offline (pay-bar y/o top): fondo `--danger-soft-2`, borde `#fecaca`.
- Ventas offline: mismo ticket pero con cinta `PENDIENTE DE SYNC` y referencia `OFF-xxxx`.
- Cola en `localStorage`: `bizm_offline_queue_v1` (array de payloads `pos_procesar`), `bizm_products_cache_v1` (último catálogo), `bizm_cart_v1` (carrito persistente).
- Al volver online: `window online` → toast + auto-sync (uno por uno a `pos_procesar`), luego refrescar catálogo y badge. Nunca se bloquea el cobro.

---

## 13. Responsive

| Breakpoint | Layout |
|---|---|
| >1280px | POS 2 col (carrito 380px + productos), grid 4–5 cols |
| 1025–1280px | igual, grid 4 cols |
| 481–1024px | header wrap, grid 3 cols, pay-bar compacta |
| ≤768px | página con scroll vertical, tab-bar fija, carrito debajo de productos, Pay full-width |
| ≤480px | grid 2 cols, botones acción icon-only, charges 2–3 cols |
| ≤360px | grid 1 col, charges 1 col |

---

## 14. Checklist para aplicar a una página existente

1. Fondo `var(--bg)`, cards `var(--surface)` + `border:1px solid var(--line)` + `radius:16px`.
2. Todos los `<select>` → clase patrón §4.1 (altura 38px, foco acento).
3. Todos los inputs búsqueda → patrón §5.1.
4. Botón principal → patrón §3.1; secundarios → §3.2; iconos toolbar → §3.3.
5. Números/precios → `font-family:var(--font-mono)`.
6. Estados → pills §8 (no badges Bootstrap de colores aleatorios).
7. Tablas → §7 (hover tint, montos mono derecha).
8. Modales → radius 18px, header según §11.
9. Probar 375px y 768px: sin scroll horizontal, tab-bar no tapa contenido (`padding-bottom:70px`).

---

## 15. Archivos

- Spec: `DESIGN.MD` (este archivo).
- Implementación global: `static/css/styles.css` (tokens + patrones).
- POS nuevo: `templates/core/pos.html` (consume los tokens, incluye offline queue).
- No usar estilos oscuros legacy (`.pos-cart` oscuro, `.sidebar` negro puro) en páginas nuevas; el sidebar ya es claro (blanco + acento).
- Aplicación global ya hecha: `base.html` (sidebar claro con logo morado, footer usuario con avatar) + bloque "TEMA HOMOGENEO" al final de `static/css/styles.css` que reestiliza topbar, cards (radius 16), tablas (hover tint), botones (primary = acento), badges (píldora), formularios (foco acento) y modales (radius 18) en TODAS las páginas sin tocar cada template.

## 16. Modo oscuro

- Llave única `localStorage: bizm_theme` (`light`/`dark`). Script inline en `<head>` de `base.html` la aplica a `<html data-theme>` antes del primer pintado (sin flash).
- Botón: arriba a la derecha en el topbar (`#themeToggle`, luna/sol) y en la toolbar del POS (`#themeTogglePos`). Ambos llaman a `window.toggleBizTheme()` (`static/js/main.js`) y persisten la misma llave, así que el POS y el resto del sistema siempre van sincronizados.
- Implementación: overrides `html[data-theme="dark"]` en `static/css/styles.css` (fondo `#14141c`, superficie `#1e1e2a`, tintas claras) + bloque `html[data-theme="dark"] .pos-shell` dentro de `pos.html` (el POS define sus propias vars locales y hay que re-mapearlas: inputs, numpad, cards, drawer, thumbs).
- Dashboard: usa vars (`--surface`, `--ink`, etc.) en sus clases propias, así que hereda el modo oscuro automáticamente.
