"""Repara ventas canceladas/eliminadas cuyo stock NO fue recuperado.

Uso en el SERVIDOR (dentro del entorno del proyecto):

    python manage.py shell < reparar_ventas_canceladas.py

Por defecto corre en modo SIMULACION (dry-run) y solo muestra qué haría.
Para aplicar los cambios, edita la variable DRY_RUN a False o define:

    $env:REPARAR_APLICAR='1'   # PowerShell
    python manage.py shell < reparar_ventas_canceladas.py

Qué hace para cada número de venta:
  1. Busca la Venta por numero_venta (incluye canceladas).
  2. Busca TODOS los movimientos de inventario/almacén asociados a esa
     venta (por referencia_id y/o por el número en la descripción).
  3. Invierte los movimientos de tipo 'venta':
       - tipo 'venta' -> 'devolucion'
       - cantidad negativa -> positiva
       - devuelve la existencia al stock correspondiente
         (AlmacenStock en multi-POS, Producto.stock en los otros modos).
  4. Si la venta existe, la marca cancelada=True y elimina sus detalles
     para que no siga apareciendo como vendida en reportes.
  5. No crea movimientos nuevos: reescribe los existentes, evitando
     duplicar devoluciones.
"""
import os
import django

DRY_RUN = os.environ.get('REPARAR_APLICAR', '') != '1'
VENTAS = ['VTA-010365', 'VTA-010276']

from core.models import (
    Venta, DetalleVenta, Producto, MovimientoInventario,
    AlmacenMovimiento, AlmacenStock,
)

print('MODO:', 'SIMULACION (dry-run)' if DRY_RUN else 'APLICANDO CAMBIOS')


def fmt(v):
    return f'{v} {v.producto.unidad_medida if v.producto_id else ""}'


for numero in VENTAS:
    print('\n' + '=' * 70)
    print('VENTA', numero)
    venta = Venta.objects.filter(numero_venta=numero).first()
    if venta is None:
        print('  La venta NO existe en la BD (ya fue eliminada).')
        vid = None
    else:
        vid = venta.id
        print(f'  Existe id={venta.id} cancelada={venta.cancelada} '
              f'pos={venta.punto_venta_id} turno={venta.turno_id}')

    # 1) Movimientos por referencia_id (si conocemos el id) y por número en la descripción
    mov_inv = MovimientoInventario.objects.filter(referencia_id=vid) if vid else MovimientoInventario.objects.none()
    mov_alm = AlmacenMovimiento.objects.filter(referencia_id=vid) if vid else AlmacenMovimiento.objects.none()
    mov_inv = mov_inv | MovimientoInventario.objects.filter(descripcion__icontains=numero)
    mov_alm = mov_alm | AlmacenMovimiento.objects.filter(descripcion__icontains=numero)
    mov_inv = mov_inv.distinct()
    mov_alm = mov_alm.distinct()

    print(f'  Movimientos de inventario: {mov_inv.count()} | almacén: {mov_alm.count()}')

    for m in mov_inv:
        if m.tipo != 'venta':
            print(f'    [omitido] inv #{m.id} tipo={m.tipo} {fmt(m)}')
            continue
        cantidad = abs(m.cantidad)
        print(f'    [INVERTIR] inv #{m.id} venta {fmt(m)} -> devolucion +{cantidad}')
        if not DRY_RUN:
            producto = m.producto
            producto.stock = (producto.stock or 0) + cantidad
            producto.save(update_fields=['stock'])
            m.tipo = 'devolucion'
            m.cantidad = cantidad
            m.descripcion = (m.descripcion + ' (reparado)')[:255]
            m.save(update_fields=['tipo', 'cantidad', 'descripcion'])

    for m in mov_alm:
        if m.tipo not in ('venta', 'traslado'):
            print(f'    [omitido] alm #{m.id} tipo={m.tipo} {fmt(m)}')
            continue
        cantidad = abs(m.cantidad)
        print(f'    [INVERTIR] alm #{m.id} {m.tipo} {fmt(m)} -> devolucion +{cantidad}')
        if not DRY_RUN:
            producto = m.producto
            almacen = m.almacen
            if almacen is not None:
                stock = AlmacenStock.objects.filter(
                    producto=producto, almacen=almacen).first()
                if stock is None:
                    stock = AlmacenStock.objects.create(
                        producto=producto, almacen=almacen, cantidad=0)
                stock.cantidad = (stock.cantidad or 0) + cantidad
                stock.save(update_fields=['cantidad'])
            else:
                producto.stock = (producto.stock or 0) + cantidad
                producto.save(update_fields=['stock'])
            m.tipo = 'devolucion'
            m.cantidad = cantidad
            m.descripcion = (m.descripcion + ' (reparado)')[:255]
            m.save(update_fields=['tipo', 'cantidad', 'descripcion'])

    if venta is not None:
        n_det = venta.detalles.count()
        print(f'  Detalles de la venta: {n_det}')
        if not DRY_RUN:
            DetalleVenta.objects.filter(venta=venta).delete()
            venta.cancelada = True
            venta.save(update_fields=['cancelada'])

print('\nFIN.', 'No se aplicaron cambios.' if DRY_RUN else 'Cambios aplicados.')
