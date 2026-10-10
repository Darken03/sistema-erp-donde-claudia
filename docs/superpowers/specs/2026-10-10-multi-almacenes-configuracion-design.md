# Spec: Módulo Configuración + Multi-Almacén — BizMaster ERP

Fecha: 2026-10-10
Estado: Aprobado por el cliente (diseño en 5 secciones)
Enfoque elegido: A — Entidad Almacén real

## 1. Entendimiento acordado

- **Objetivo:** permitir al cliente crear N almacenes con nombre propio desde un módulo de Configuración, sin romper el flujo actual cuando hay 1 solo almacén.
- **Restricción clave (cliente):** POS y almacén totalmente separados. Nada del almacén aparece en POS salvo por traslado → POS (mostrador/área de venta).
- **Creación:** uno por uno con nombre (no por número generador).
- **Configuración completa v1:** tienda (nombre, logo, teléfono, dirección) + almacenes + apariencia (color acento, tema por defecto) + regional (moneda, símbolo, impuesto, idioma).
- **Traslados:** almacén→POS y almacén→almacén.
- **Header:** botón gear de configuración al lado del selector modo oscuro.
- **Éxito:** con 1 almacén la UI/flujo es idéntica a hoy; con 2+ aparecen selectores origen/destino y filtros por almacén; logo/temas aplican globalmente.

## 2. Arquitectura y modelos

### 2.1 Nuevos / modificados

```python
class Almacen(models.Model):
    nombre = CharField(max_length=100, unique=True)
    descripcion = TextField(blank=True)
    activo = BooleanField(default=True)
    es_principal = BooleanField(default=False)
    fecha_creacion = DateTimeField(auto_now_add=True)
    # ordering = ['nombre']

class ConfiguracionTienda(models.Model):  # singleton (pk=1 forzado)
    nombre_tienda = CharField(default='Donde Clau')
    logo = ImageField(upload_to='tienda/', blank=True, null=True)
    telefono, direccion = CharField(blank=True)
    moneda = CharField(default='CUP')
    simbolo_moneda = CharField(default='$')
    impuesto_defecto = Decimal(default=0)
    color_acento = CharField(default='#6f53d9')
    tema_por_defecto = CharField(choices=['light','dark'], default='light')
    idioma = CharField(default='es')
```

Cambios:
- `AlmacenStock`: `producto OneToOne` → `producto FK + almacen FK`, `unique_together = (producto, almacen)`.
- `AlmacenEntrada`: + `almacen FK (destino)`.
- `AlmacenTraslado`: + `origen FK`, `destino_tipo choices(POS, ALMACEN)`, `destino_almacen FK nullable`.
- `AlmacenMovimiento`: + `almacen FK nullable` (para histórico previo).
- `Producto.stock` (POS) no se toca.

### 2.2 Regla 1 vs N

- `N_activos = Almacen.objects.filter(activo=True).count()`.
- Si `N == 1`: todos los formularios/listas filtran automático a ese almacén; sin selectores visibles (compatibilidad total).
- Si `N >= 2`: formularios exigen `origen`/`destino`; panel/stock/entradas/traslados/auditoría llevan filtro `?almacen=<id>` persistido en sesión.
- `modo_multi_almacen` es derivado (no setting manual) para evitar inconsistencia con el pedido original de "elegir número".

### 2.3 Migración de datos

- Data migration: crea `Almacen(nombre='Almacén Principal', es_principal=True, activo=True)` + `ConfiguracionTienda` default.
- Reasigna todo `AlmacenStock/Entrada/Movimiento` existente a Principal; `AlmacenTraslado` viejos → `origen=Principal, destino_tipo=POS`.
- Traslados viejos generaron `EntradaProducto(proveedor='Almacén')`; nuevos generan `proveedor='Almacén: <nombre>'` para trazabilidad IPB.

## 3. Módulo Configuración

- URLs (solo admin, `es_admin`):
  - `GET/POST /configuracion/` → tabs Tienda/Almacenes/Apariencia/Regional.
  - `POST /configuracion/almacenes/crear/`, `/<pk>/editar/`, `/<pk>/toggle/`.
- Tabs:
  - **Tienda:** nombre, logo upload, teléfono, dirección. Logo reemplaza `static/img/logo-donde-clau.png` en sidebar/login vía `config.logo.url` con fallback al estático.
  - **Almacenes:** tabla (nombre, estado, productos, valor, última actividad) + crear (nombre único obligatorio). No eliminar con stock/movimientos; desactivar bloqueado si tiene stock > 0 o si es el único activo; Principal no desactivable si único.
  - **Apariencia:** color acento (presets: morado #6f53d9, rosa, verde, azul + custom hex), tema por defecto light/dark (respeta llave `bizm_theme` existente; solo define default para primera visita). Aplica vía CSS var `--accent` override + `data-theme` default.
  - **Regional:** moneda CUP, símbolo $, impuesto defecto %, idioma es (preparado para i18n futuro).
- Template: `templates/core/configuracion.html` con patrón `card-hom`, `form-control-hom`, `form-select-hom`, pills de estado (DESIGN.MD §6-8). Sin estilos oscuros legacy.

## 4. Header / navegación

- Topbar (`base.html`): añadir junto a `#themeToggle`:
  ```html
  {% if request.user.perfil.es_admin %}
  <a class="theme-toggle" id="configBtn" href="{% url 'core:configuracion' %}" title="Configuración"><i class="bi bi-gear"></i></a>
  {% endif %}
  ```
  Mismo estilo `.theme-toggle`; POS no lleva selector.
- Sidebar: grupo Almacén conserva Panel/Existencias/Entradas/Traslados/Auditoría + filtro almacén (sesión) cuando N>1; nuevo item `Configuración` (gear) al final solo admin.
- Context processor: `configuracion_tienda` disponible en `base.html` (nombre, logo, acento) sin N+1.

## 5. Flujos multi-almacén

- **Entrada (`almacen_entrada_crear`):** destino obligatorio (oculto si N=1). Suma solo a `(producto, almacen)` + `AlmacenMovimiento(entrada, almacen)`. Respeta `visible_pos=False` al crear producto nuevo (tests existentes).
- **Traslado (`almacen_traslado_crear`):** origen obligatorio; destino = POS o almacén ≠ origen. Valida stock origen suficiente. Resta origen; si POS → `Producto.stock += cant` + `EntradaProducto(proveedor='Almacén: <nombre>')` + `visible_pos=True`; si almacén → suma a su `AlmacenStock`. Dos movimientos auditados (salida origen / entrada destino o POS vía EntradaProducto).
- **Cancelaciones (solo admin):** revierten el almacén correcto; si `entrada_generada` ya consumida por ventas (stock POS insuficiente), bloqueo con mensaje. Errores corrigen con `almacen_ajuste`.
- **Panel (`almacen_panel`):** si N=1 vista actual; si N>1 cards por almacén (valor, nº productos, últimos 5 movs) + resumen global.
- **Stock/Existencias:** tabla con columna Almacén + filtro; montos mono derecha, hover tint (DESIGN.MD §7).

## 6. Permisos y errores

- Configuración: solo `es_admin`. Almacenero: opera entradas/traslados/stock/auditoría (con selector si N>1) pero no crea/edita almacenes ni tienda/apariencia. Cajero/vendedor: sin acceso almacén/config (redirige como hoy).
- Validaciones con mensajes Django: stock insuficiente, origen==destino, almacén inactivo, nombre duplicado, desactivar con stock, cancelar imposible. Nunca bloquean el cobro POS (offline-first intacto).

## 7. Testing

- Extender `tests_almacen*.py`: stock por almacén aislado; traslado almacén→almacén no toca POS; traslado→POS solo suma al POS.
- Nuevo `tests_configuracion.py`: solo admin accede; crear/renombrar/desactivar con reglas; N=1 sin selector (POST sin almacén usa el único); N=2 exige selector; logo/acento persisten; migración asigna Principal.
- Manual: 375px/768px sin scroll horizontal; dark/light con acento custom; IPB muestra `Almacén: <nombre>`.

## 8. Fuera de alcance v1

- Contabilidad por almacén separada, costos distintos por almacén, sucursales con POS propio, i18n real, roles por almacén, API/websockets mostrador.
