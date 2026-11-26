"""Exporta a Excel las ventas cobradas por transferencia desde el 1 de octubre.

Regla importante: en las ventas MIXTAS solo se toma la pata de transferencia
(`monto_transferencia`), nunca el total de la venta ni el efectivo.

Uso (desde la carpeta del proyecto):
    python exportar_transferencias.py
    python exportar_transferencias.py --desde 2026-10-01 --hasta 2026-11-26
    python exportar_transferencias.py --salida C:/ruta/mi_reporte.xlsx
"""

import argparse
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta
from decimal import Decimal

import django

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.db.models import Q
from django.utils import timezone

from core.models import Venta

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


FORMATO_MONEDA = '#,##0.00'
FORMATO_FECHA = 'dd/mm/yyyy'
COLOR_ENCABEZADO = '6F53D9'


def _rango_local(desde, hasta):
    """Rango [desde, hasta] en fecha LOCAL de La Habana (no UTC)."""
    inicio = timezone.make_aware(datetime.combine(desde, time.min))
    fin = timezone.make_aware(
        datetime.combine(hasta + timedelta(days=1), time.min))
    return inicio, fin


def _obtener_ventas(desde, hasta):
    inicio, fin = _rango_local(desde, hasta)
    return (
        Venta.objects
        .filter(cancelada=False, fecha_venta__gte=inicio, fecha_venta__lt=fin)
        .filter(Q(metodo_pago='transferencia') | Q(metodo_pago='mixto'))
        .exclude(monto_transferencia__lte=0)
        .select_related('cajero', 'punto_venta')
        .order_by('fecha_venta', 'numero_venta')
    )


def _encabezado(ws, titulos, anchos):
    ws.append(titulos)
    for col, ancho in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(col)].width = ancho
    for celda in ws[1]:
        celda.font = Font(bold=True, color='FFFFFF')
        celda.fill = PatternFill('solid', fgColor=COLOR_ENCABEZADO)
        celda.alignment = Alignment(horizontal='center', vertical='center')
    ws.freeze_panes = 'A2'


def _totales(ws, fila, columna_monto, texto='TOTAL'):
    ws.cell(row=fila, column=1, value=texto).font = Font(bold=True)
    celda = ws.cell(row=fila, column=columna_monto)
    letra = get_column_letter(columna_monto)
    celda.value = f'=SUM({letra}2:{letra}{fila - 1})'
    celda.font = Font(bold=True)
    celda.number_format = FORMATO_MONEDA


def generar_excel(desde, hasta, salida):
    ventas = list(_obtener_ventas(desde, hasta))

    wb = Workbook()
    detalle = wb.active
    detalle.title = 'Transferencias'
    _encabezado(
        detalle,
        ['Fecha', 'No. Venta', 'Tipo de operación', 'Cajero',
         'Punto de venta', 'Monto transferencia'],
        [13, 18, 20, 24, 20, 22],
    )

    resumen = defaultdict(lambda: {
        'ventas': 0, 'puras': 0, 'mixtas': 0, 'total': Decimal('0'),
    })
    total_general = Decimal('0')

    for venta in ventas:
        dia = timezone.localtime(venta.fecha_venta).date()
        cajero = ''
        if venta.cajero_id:
            cajero = (venta.cajero.get_full_name() or venta.cajero.username)
        punto = venta.punto_venta.nombre if venta.punto_venta_id else ''
        monto = Decimal(venta.monto_transferencia or 0)
        es_mixta = venta.metodo_pago == 'mixto'

        detalle.append([
            dia,
            venta.numero_venta,
            'Mixto (solo transferencia)' if es_mixta else 'Transferencia',
            cajero,
            punto,
            float(monto),
        ])
        fila = detalle.max_row
        detalle.cell(row=fila, column=1).number_format = FORMATO_FECHA
        detalle.cell(row=fila, column=6).number_format = FORMATO_MONEDA

        datos = resumen[dia]
        datos['ventas'] += 1
        datos['mixtas' if es_mixta else 'puras'] += 1
        datos['total'] += monto
        total_general += monto

    if ventas:
        _totales(detalle, detalle.max_row + 1, 6)
        detalle.auto_filter.ref = f'A1:F{detalle.max_row - 1}'

    diario = wb.create_sheet('Resumen por día')
    _encabezado(
        diario,
        ['Fecha', 'Ventas con transferencia', 'Transferencias puras',
         'Mixtas', 'Total transferencia'],
        [13, 24, 22, 12, 22],
    )
    for dia in sorted(resumen):
        datos = resumen[dia]
        diario.append([
            dia, datos['ventas'], datos['puras'], datos['mixtas'],
            float(datos['total']),
        ])
        fila = diario.max_row
        diario.cell(row=fila, column=1).number_format = FORMATO_FECHA
        diario.cell(row=fila, column=5).number_format = FORMATO_MONEDA

    if resumen:
        _totales(diario, diario.max_row + 1, 5)
        diario.auto_filter.ref = f'A1:E{diario.max_row - 1}'

    wb.save(salida)
    return len(ventas), total_general


def main():
    hoy = timezone.localdate()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desde', default='2026-10-01',
                        help='Fecha inicial (YYYY-MM-DD). Defecto: 2026-10-01')
    parser.add_argument('--hasta', default=hoy.isoformat(),
                        help='Fecha final inclusiva (YYYY-MM-DD). Defecto: hoy')
    parser.add_argument('--salida', default=None,
                        help='Ruta del .xlsx. Defecto: en la carpeta del proyecto')
    args = parser.parse_args()

    try:
        desde = date.fromisoformat(args.desde)
        hasta = date.fromisoformat(args.hasta)
    except ValueError:
        parser.error('Las fechas deben tener formato YYYY-MM-DD.')
    if hasta < desde:
        parser.error('--hasta no puede ser menor que --desde.')

    salida = args.salida or os.path.join(
        BASE_DIR, f'transferencias_{desde.isoformat()}_a_{hasta.isoformat()}.xlsx')

    cantidad, total = generar_excel(desde, hasta, salida)
    print(f'Ventas con transferencia: {cantidad}')
    print(f'Total transferencias: ${total:,.2f}')
    print(f'Archivo guardado: {salida}')


if __name__ == '__main__':
    main()
