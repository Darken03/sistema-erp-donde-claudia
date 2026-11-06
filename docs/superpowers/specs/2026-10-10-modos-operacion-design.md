# Spec: Modos de Operación (solo-POS / POS+almacenes / multi-POS) — BizMaster ERP

Fecha: 2026-10-10
Estado: Diseño aprobado por el cliente (5 secciones)
Alcance de este spec: DISEÑO COMPLETO de los 3 modos. Implementación posterior.
Enfoque elegido: A — setting `modo_operacion` + entidad `PuntoVenta`, navegación condicional.

## 1. Entendimiento acordado

- **Objetivo:** el sistema opera en 3 modos a elección del cliente, seleccionable en
  Configuración: `solo_pos`, `pos_almacenes` (comportamiento actual, por defecto),
  `multi_pos` (grandes empresas).
- **Regla de oro:** cambiar de modo NUNCA borra datos; lo no aplicable se oculta y
  reaparece intacto al volver (protege contra errores del usuario).
- **Futuro SaaS:** cada modo tendrá precio diferenciado, pero eso es posterior. El modo
  es un string en `ConfiguracionTienda` sin lógica de precios/bloqueo; el gating futuro
  se añade sin migrar datos.

## 2. Selección del modo

- Nuevo campo `ConfiguracionTienda.modo_operacion` choices
  `solo_pos|pos_almacenes|multi_pos`, default `pos_almacenes`, editable solo por admin
  en Configuración → Tienda/General, con texto que explica qué cambia en cada modo.
- Helper central `modo_actual()` (lee `ConfiguracionTienda.get_solo()`); sidebar, vistas
  y validaciones condicionan por modo. Decorador `requiere_modo(*modos)` para bloquear
  URLs fuera de modo (redirect + mensaje).

## 3. Modo solo-POS

- **Navegación:** el grupo Almacén desaparece del sidebar (admin y almacenero). El rol
  `almacenero` queda sin pantallas: al crear/editar empleado se sugiere reasignarlo a
  cajero; si existe, redirige al POS con aviso.
- **Entradas directas (solo admin):** se habilitan crear/eliminar `EntradaProducto` en
  Inventario → Entradas (hoy solo lectura). Cada entrada suma a `Producto.stock` y deja
  `visible_pos=True` de inmediato (entra directo al mostrador).
- **Datos de almacén:** `AlmacenStock/Entrada/Traslado/Movimiento` se excluyen de todas
  las listas (filtro por modo); filas intactas en BD. Al volver a un modo con almacén,
  todo reaparece.
- **IPB/ventas:** sin cambios (operan sobre `Producto.stock` como hoy).

## 4. Modo POS + almacenes (actual)

- Sin cambios de flujo: POS independiente del almacén; entradas a almacén; traslados
  almacén→POS (generan `EntradaProducto`) y almacén→almacén; al POS solo entra mercancía
  por traslado. Único cambio: el modo queda explícito en Configuración.

## 5. Modo multi-POS

- **Entidad `PuntoVenta`:** `nombre unique, almacen FK (único por POS: un POS ↔ un almacén;
  un almacén puede surtir a varios POS), activo`. El admin los crea uno por uno con
  nombre, igual que almacenes.
- **Asignación de personal:** `Empleado.punto_venta FK nullable`. Varios trabajadores
  pueden pertenecer a un POS. Al abrir turno, el trabajador selecciona a qué POS va a
  trabajar (un POS por turno; la asignación puede cambiar entre turnos).
- **Sin stock propio del POS:** el POS vende y descuenta directo del `AlmacenStock` del
  almacén asignado. Catálogo visible del POS = existencias de ese almacén
  (`visible_pos` deja de ser la fuente en este modo; `Producto.stock` no se usa).
- **Trazabilidad:** `Venta.punto_venta FK`, `Turno.punto_venta FK` (nullable para historia
  previa). Traslados hacia POS no existen en este modo; solo entre almacenes. Entradas
  siguen entrando a almacén (admin/almacenero).
- **Multi-IPB y multi-ventas:** IPB con filtro/sección por POS (cierre diario calculado
  sobre el stock del almacén de cada POS); módulo Ventas filtrado por POS; arqueos y
  reportes atribuidos por `punto_venta`. Cada POS opera su caja, turnos y cierres
  independientes.
- **Offline-first** se mantiene por POS (cola y catálogo locales por almacén asignado).

## 6. Permisos por modo

| Acción | solo-POS | POS+almacenes | multi-POS |
|---|---|---|---|
| Cambiar modo / gestionar POS | admin | admin | admin |
| Entradas directas | admin | — (no existen) | — |
| Entradas a almacén | — | admin/almacenero | admin/almacenero |
| Traslados →POS / entre almacenes | — | ambos / ambos | no / sí |
| Vender | cajero (stock POS) | cajero (stock POS) | cajero (stock almacén de su POS) |
| Rol almacenero | sin acceso | pleno almacén | pleno almacén |

## 7. Migración

- Data migration: `modo_operacion='pos_almacenes'` para todos (comportamiento idéntico al
  actual, cero cambios visibles). `Venta/Turno.punto_venta` nullable (historia sin POS).
- Sin borrados en ningún cambio de modo; toggles de visibilidad por consultas, no por
  datos.

## 8. Testing

- Navegación por modo: grupo Almacén visible/oculto; URLs fuera de modo redirigen.
- solo-POS: entradas directas solo admin; stock de almacén oculto y restaurado al volver.
- multi-POS: venta descuenta el almacén asignado (no `Producto.stock`); IPB/ventas
  filtrados por POS; turno exige POS; traslado→POS bloqueado.
- Suite existente verde en modo `pos_almacenes`.

## 9. Fuera de alcance (incluido SaaS)

- Precios por modo, suscripciones, gating/pagos, límites por plan, multi-negocio o
  multi-sucursal con contabilidades separadas.
