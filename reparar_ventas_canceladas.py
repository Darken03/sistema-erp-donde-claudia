"""Elimina del submayor las ventas canceladas y recupera su stock.

Uso en el SERVIDOR (dentro del entorno del proyecto):

    python manage.py shell < reparar_ventas_canceladas.py

Por defecto APLICA. Solo simula con:  export REPARAR_DRY_RUN=1

Procesa los números de VENTAS y, si LIMPIAR_TODAS_CANCELADAS=True,
también TODA venta cancelada que todavía tenga movimientos o detalles.
"""
import os

DRY_RUN = os.environ.get('REPARAR_DRY_RUN', '') == '1'
VENTAS = ['VTA-010365', 'VTA-010276']
LIMPIAR_TODAS_CANCELADAS = True

from django.db.models import Q
from core.models import (
    Venta, DetalleVenta, Producto, MovimientoInventario,
    AlmacenMovimiento, AlmacenStock,
)

print('MODO:', 'SIMULACION (dry-run)' if DRY_RUN else 'APLICANDO CAMBIOS')

from django.db.models import Count

canceladas_con_mov = list(
    Venta.objects.filter(cancelada=True).annotate(
        n=Count('detalles'))
    .filter(Q(n__gt=0))
    .values_list('id', flat=True)
)
ids_con_mov_inv = set(
    MovimientoInventario.objects.filter(tipo='venta')
    .exclude(referencia_id__isnull=True)
    .values_list('referencia_id', flat=True))
ids_con_mov_alm = set(
    AlmacenMovimiento.objects.filter(tipo__in=('venta', 'traslado'))
    .exclude(referencia_id__isnull=True)
    .values_list('referencia_id', flat=True))
canceladas_con_mov = list(set(canceladas_con_mov) | ids_con_mov_inv | ids_con_mov_alm)

objetivos = []
for n in VENTAS:
    v = Venta.objects.filter(numero_venta=n).first()
    objetivos.append((n, v))
if LIMPIAR_TODAS_CANCELADAS:
    for vid in canceladas_con_mov:
        if any(v and v.id == vid for _, v in objetivos):
            continue
        v = Venta.objects.filter(pk=vid).first()
        if v:
            objetivos.append((v.numero_venta, v))

print(f'Ventas a procesar: {len(objetivos)}')


def fmt(cantidad, producto):
    u = producto.unidad_medida if producto else 'unidades'
    return f'{cantidad} {u}'


for numero, venta in objetivos:
    print('\n' + '=' * 70)
    print('VENTA', numero)
    vid = venta.id if venta else None
    if venta is None:
        print('  La venta NO existe en la BD (ya fue eliminada).')
    else:
        print(f'  id={venta.id} cancelada={venta.cancelada} pos={venta.punto_venta_id}')

    inv = MovimientoInventario.objects.filter(descripcion__icontains=numero)
    alm = AlmacenMovimiento.objects.filter(descripcion__icontains=numero)
    if vid:
        inv = (inv | MovimientoInventario.objects.filter(referencia_id=vid)).distinct()
        alm = (alm | AlmacenMovimiento.objects.filter(referencia_id=vid)).distinct()

    print(f'  Movimientos: inventario={inv.count()} almacen={alm.count()}')

    for m in inv:
        if m.tipo not in ('venta', 'devolucion'):
            continue
        neto = (-1 if m.tipo == 'venta' else 1) * abs(m.cantidad)
        print(f'    inv #{m.id} {m.tipo} {fmt(m.cantidad, m.producto)} -> ELIMINAR (neto {neto})')
        if not DRY_RUN:
            if neto > 0:
                p = m.producto
                p.stock = (p.stock or 0) + neto
                p.save(update_fields=['stock'])
            m.delete()

    for m in alm:
        if m.tipo not in ('venta', 'traslado', 'devolucion'):
            continue
        neto = (-1 if m.tipo in ('venta', 'traslado') else 1) * abs(m.cantidad)
        print(f'    alm #{m.id} {m.tipo} {fmt(m.cantidad, m.producto)} -> ELIMINAR (neto {neto})')
        if not DRY_RUN:
            if neto > 0:
                if m.almacen is not None:
                    stock = AlmacenStock.objects.filter(
                        producto=m.producto, almacen=m.almacen).first()
                    if stock is None:
                        stock = AlmacenStock.objects.create(
                            producto=m.producto, almacen=m.almacen, cantidad=0)
                    stock.cantidad = (stock.cantidad or 0) + neto
                    stock.save(update_fields=['cantidad'])
                else:
                    p = m.producto
                    p.stock = (p.stock or 0) + neto
                    p.save(update_fields=['stock'])
            m.delete()

    if venta is not None:
        ndet = venta.detalles.count()
        print(f'  Detalles: {ndet} -> se ELIMINAN')
        if not DRY_RUN:
            DetalleVenta.objects.filter(venta=venta).delete()
            if not venta.cancelada:
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
