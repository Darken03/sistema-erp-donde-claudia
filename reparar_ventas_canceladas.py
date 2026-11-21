"""Elimina del submayor las ventas canceladas y recupera su stock.

Síntoma: ventas canceladas/eliminadas siguen apareciendo como "venta" en el
submayor del producto y su stock nunca se recuperó.

Uso en el SERVIDOR (dentro del entorno del proyecto):

    python manage.py shell < reparar_ventas_canceladas.py

Por defecto APLICA los cambios directamente. Si solo quieres simular:

    export REPARAR_DRY_RUN=1
    python manage.py shell < reparar_ventas_canceladas.py

Para cada número de venta:
  1. Busca la Venta (puede estar cancelada o ya eliminada).
  2. Localiza sus movimientos por referencia_id y por el número en la
     descripción (MovimientoInventario y AlmacenMovimiento).
  3. Calcula el neto pendiente de recuperar (ventas − devoluciones ya
     hechas) y lo suma al stock correspondiente (AlmacenStock en multi-POS,
     Producto.stock en los otros modos).
  4. ELIMINA todos esos movimientos para que no aparezcan nunca más en el
     submayor, y elimina los detalles de la venta si todavía existe.
"""
import os

DRY_RUN = os.environ.get('REPARAR_DRY_RUN', '') == '1'
VENTAS = ['VTA-010365', 'VTA-010276']

from django.db.models import Q
from core.models import (
    Venta, DetalleVenta, Producto, MovimientoInventario,
    AlmacenMovimiento, AlmacenStock,
)

print('MODO:', 'SIMULACION (dry-run)' if DRY_RUN else 'APLICANDO CAMBIOS')


def fmt(cantidad, producto):
    u = producto.unidad_medida if producto else 'unidades'
    return f'{cantidad} {u}'


for numero in VENTAS:
    print('\n' + '=' * 70)
    print('VENTA', numero)
    venta = Venta.objects.filter(numero_venta=numero).first()
    vid = venta.id if venta else None
    if venta is None:
        print('  La venta NO existe en la BD (ya fue eliminada).')
    else:
        print(f'  Existe id={venta.id} cancelada={venta.cancelada} '
              f'pos={venta.punto_venta_id}')

    inv = MovimientoInventario.objects.filter(descripcion__icontains=numero)
    alm = AlmacenMovimiento.objects.filter(descripcion__icontains=numero)
    if vid:
        inv = (inv | MovimientoInventario.objects.filter(referencia_id=vid)).distinct()
        alm = (alm | AlmacenMovimiento.objects.filter(referencia_id=vid)).distinct()

    print(f'  Movimientos: inventario={inv.count()} almacen={alm.count()}')

    for m in inv:
        if m.tipo not in ('venta', 'devolucion'):
            continue
        signo = -1 if m.tipo == 'venta' else 1
        neto = signo * abs(m.cantidad)
        print(f'    inv #{m.id} {m.tipo} {fmt(m.cantidad, m.producto)} '
              f'-> neto {neto}; se ELIMINA')
        if not DRY_RUN:
            if neto > 0:
                p = m.producto
                p.stock = (p.stock or 0) + neto
                p.save(update_fields=['stock'])
            m.delete()

    for m in alm:
        if m.tipo not in ('venta', 'traslado', 'devolucion'):
            continue
        signo = -1 if m.tipo in ('venta', 'traslado') else 1
        neto = signo * abs(m.cantidad)
        print(f'    alm #{m.id} {m.tipo} {fmt(m.cantidad, m.producto)} '
              f'-> neto {neto}; se ELIMINA')
        if not DRY_RUN:
            if neto > 0:
                almacen = m.almacen
                if almacen is not None:
                    stock = AlmacenStock.objects.filter(
                        producto=m.producto, almacen=almacen).first()
                    if stock is None:
                        stock = AlmacenStock.objects.create(
                            producto=m.producto, almacen=almacen, cantidad=0)
                    stock.cantidad = (stock.cantidad or 0) + neto
                    stock.save(update_fields=['cantidad'])
                else:
                    p = m.producto
                    p.stock = (p.stock or 0) + neto
                    p.save(update_fields=['stock'])
            m.delete()

    if venta is not None:
        print(f'  Detalles: {venta.detalles.count()} -> se ELIMINAN')
        if not DRY_RUN:
            DetalleVenta.objects.filter(venta=venta).delete()
            venta.cancelada = True
            venta.save(update_fields=['cancelada'])

print('\nVERIFICACION FINAL:')
for numero in VENTAS:
    q = MovimientoInventario.objects.filter(descripcion__icontains=numero).count() + \
        AlmacenMovimiento.objects.filter(descripcion__icontains=numero).count()
    v = Venta.objects.filter(numero_venta=numero).first()
    print(f'  {numero}: movimientos restantes={q} | '
          f'venta={"cancelada" if v and v.cancelada else ("existe" if v else "eliminada")}')
print('FIN.', 'No se aplicaron cambios.' if DRY_RUN else 'Cambios aplicados.')
