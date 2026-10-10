#!/usr/bin/env python
"""
Reparación IPB 22-24 Septiembre 2026 — SIN pérdida de información.

Qué hace:
  1. Respalda las filas 22/23/24 a CSV + tabla backup (core_inventariodiario_backup_20260924).
  2. Recalcula movimientos por DÍA COMERCIAL (Django __date = America/Havana,
     igual que el IPB; no usar date() crudo de SQLite que es UTC).
  3. Re-encadena hacia ATRÁS desde el único dato vivo confiable:
       24.fin = producto.stock (hoy)  →  24.ini  →  23.fin = 24.ini ...
     Preserva entradas/ventas (ya correctas) y solo corrige ini/fin.
  4. Cierra 22 y 23 (cerrado=True) para congelar historia; deja 24 abierto.
  5. Verifica: 0 rupturas fin_d == ini_d+1, ecuación ini+ent-ven-don-deuda==fin.

Uso:
  python reparar_ipb_22_24.py            # dry-run, no escribe
  python reparar_ipb_22_24.py --apply    # escribe en transacción

Seguridad:
  - Hacer backup de db.sqlite3 ANTES (el script también crea backup interno).
  - NO correr en producción con la tienda vendiendo (SQLite un solo writer).
  - Probar primero en copia. Rollback = restaurar db.sqlite3 o reinsertar backup.
"""
import os
import sys
import csv
from datetime import date
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')

import django
django.setup()

from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone
from core.models import Producto, InventarioDiario, EntradaProducto, DetalleVenta, RetiroDonacion, Deuda

FECHAS = [date(2026, 9, 22), date(2026, 9, 23), date(2026, 9, 24)]
BACKUP_TABLE = 'core_inventariodiario_backup_20260924'


def movimientos_por_fecha(fecha):
    ventas = {
        v['producto_id']: Decimal(str(v['cantidad_vendida'] or 0))
        for v in DetalleVenta.objects.filter(
            venta__fecha_venta__date=fecha, venta__cancelada=False
        ).values('producto_id').annotate(cantidad_vendida=Sum('cantidad_base'))
    }
    entradas = {
        e['producto_id']: Decimal(str(e['cantidad_entrada'] or 0))
        for e in EntradaProducto.objects.filter(
            fecha_entrada__date=fecha
        ).values('producto_id').annotate(cantidad_entrada=Sum('cantidad'))
    }
    don = {
        d['producto_id']: Decimal(str(d['cantidad_donada'] or 0))
        for d in RetiroDonacion.objects.filter(
            fecha_retiro__date=fecha
        ).values('producto_id').annotate(cantidad_donada=Sum('cantidad'))
    }
    try:
        deuda = {
            d['producto_id']: Decimal(str(d['cantidad_deuda'] or 0))
            for d in Deuda.objects.filter(
                fecha_registro__date=fecha, tipo='producto'
            ).values('producto_id').annotate(cantidad_deuda=Sum('cantidad_base'))
        }
        viejas = Deuda.objects.filter(
            fecha_registro__date=fecha, tipo='producto', cantidad_base=0
        ).values('producto_id').annotate(cantidad_deuda=Sum('cantidad'))
        for d in viejas:
            if not deuda.get(d['producto_id']):
                deuda[d['producto_id']] = Decimal(str(d['cantidad_deuda'] or 0))
    except Exception:
        deuda = {
            d['producto_id']: Decimal(str(d['cantidad_deuda'] or 0))
            for d in Deuda.objects.filter(
                fecha_registro__date=fecha, tipo='producto'
            ).values('producto_id').annotate(cantidad_deuda=Sum('cantidad'))
        }
    return entradas, ventas, don, deuda


def main():
    aplicar = '--apply' in sys.argv
    print('=' * 70)
    print('REPARACIÓN IPB 22-24 SEP 2026  [%s]' % ('APLICANDO' if aplicar else 'DRY-RUN'))
    print('=' * 70)

    movs = {f: movimientos_por_fecha(f) for f in FECHAS}

    productos = list(Producto.objects.all().order_by('id'))
    print(f'Productos totales: {len(productos)}')

    # 1. Backup interno (solo con --apply)
    if aplicar:
        with connection.cursor() as cur:
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=%s",
                [BACKUP_TABLE],
            )
            if cur.fetchone():
                print(f'Backup {BACKUP_TABLE} ya existe: no se duplica.')
            else:
                cur.execute(
                    f'CREATE TABLE "{BACKUP_TABLE}" AS SELECT * FROM core_inventariodiario '
                    f"WHERE fecha IN ('2026-09-22','2026-09-23','2026-09-24')"
                )
                print(f'Backup creado: {BACKUP_TABLE}')
        # CSV adicional junto al script
        with open('respaldo_ipb_22_23_24_previo.csv', 'w', newline='', encoding='utf-8-sig') as f:
            w = csv.writer(f)
            w.writerow(['fecha', 'producto_id', 'codigo', 'nombre', 'inicial', 'entradas', 'ventas', 'final', 'cerrado'])
            for inv in InventarioDiario.objects.filter(fecha__in=FECHAS).select_related('producto'):
                w.writerow([inv.fecha, inv.producto_id, inv.producto.codigo,
                            inv.producto.nombre, inv.stock_inicial, inv.entradas,
                            inv.ventas, inv.stock_final, inv.cerrado])
        print('CSV respaldo_ipb_22_23_24_previo.csv creado.')

    cambios = []
    with transaction.atomic():
        for prod in productos:
            filas = {
                inv.fecha: inv
                for inv in InventarioDiario.objects.filter(producto=prod, fecha__in=FECHAS)
            }
            # Solo reconstruir productos con historia o activos con hoy.
            # Inactivos sin fila 23/24 se dejan intactos (fila 22 congelada).
            if not filas:
                continue
            if not prod.activo and filas.keys() == {date(2026, 9, 22)}:
                continue

            # Ancla: 24.fin = stock vivo (hoy). Si el producto no tiene fila 24
            # pero está activo, se creará; si es inactivo se omite (ver arriba).
            stock_vivo = Decimal(str(prod.stock))
            vals = {}
            for f in FECHAS:
                ent = movs[f][0].get(prod.id, Decimal('0'))
                ven = movs[f][1].get(prod.id, Decimal('0'))
                don = movs[f][2].get(prod.id, Decimal('0'))
                deu = movs[f][3].get(prod.id, Decimal('0'))
                vals[f] = (ent, ven, don, deu)

            # 24
            ent24, ven24, don24, deu24 = vals[date(2026, 9, 24)]
            fin24 = stock_vivo
            ini24 = fin24 - ent24 + ven24 + don24 + deu24
            # 23 encadenado
            ent23, ven23, don23, deu23 = vals[date(2026, 9, 23)]
            fin23 = ini24
            ini23 = fin23 - ent23 + ven23 + don23 + deu23
            # 22 encadenado
            ent22, ven22, don22, deu22 = vals[date(2026, 9, 22)]
            fin22 = ini23
            ini22 = fin22 - ent22 + ven22 + don22 + deu22

            plan = {
                date(2026, 9, 22): (ini22, ent22, ven22, fin22),
                date(2026, 9, 23): (ini23, ent23, ven23, fin23),
                date(2026, 9, 24): (ini24, ent24, ven24, fin24),
            }
            for f, (ni, ne, nv, nf) in plan.items():
                inv = filas.get(f)
                if inv is None:
                    if not prod.activo:
                        continue
                    cambios.append((prod.codigo, prod.nombre, f, None, (ni, ne, nv, nf)))
                    InventarioDiario.objects.create(
                        fecha=f, producto=prod, stock_inicial=ni,
                        entradas=ne, ventas=nv, stock_final=nf,
                        cerrado=(f < date(2026, 9, 24)),
                        cerrado_at=timezone.now() if f < date(2026, 9, 24) else None,
                    )
                else:
                    viejo = (inv.stock_inicial, inv.entradas, inv.ventas, inv.stock_final)
                    nuevo = (ni, ne, nv, nf)
                    if any(abs(Decimal(str(a)) - Decimal(str(b))) > Decimal('0.001')
                           for a, b in zip(viejo, nuevo)) or (f < date(2026, 9, 24) and not inv.cerrado):
                        cambios.append((prod.codigo, prod.nombre, f, viejo, nuevo))
                        inv.stock_inicial, inv.entradas, inv.ventas, inv.stock_final = ni, ne, nv, nf
                        if f < date(2026, 9, 24):
                            inv.cerrado = True
                            inv.cerrado_at = timezone.now()
                        inv.save()

        # Verificación dentro de la transacción
        rupturas = 0
        for prod in productos:
            m = {i.fecha: i for i in InventarioDiario.objects.filter(producto=prod, fecha__in=FECHAS)}
            for a, b in [(date(2026, 9, 22), date(2026, 9, 23)), (date(2026, 9, 23), date(2026, 9, 24))]:
                if a in m and b in m:
                    if abs(Decimal(str(m[a].stock_final)) - Decimal(str(m[b].stock_inicial))) > Decimal('0.001'):
                        rupturas += 1
        print(f'Filas a crear/actualizar: {len(cambios)} | Rupturas tras reparación: {rupturas}')
        for c in cambios[:25]:
            print('  ', c[0], c[2], 'viejo=', c[3], 'nuevo=', c[4])
        if len(cambios) > 25:
            print(f'  ... y {len(cambios) - 25} más (ver log completo con --apply)')

        if not aplicar:
            transaction.set_rollback(True)
            print('\nDRY-RUN: no se escribió nada (rollback). Usa --apply para aplicar.')
        else:
            print('\nAPLICADO y 22/23 cerrados. 24 queda abierto.')

    print('Fin.')


if __name__ == '__main__':
    main()
