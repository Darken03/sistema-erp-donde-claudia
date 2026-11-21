"""Asocia al turno correcto las ventas del POS que quedaron sin turno.

Síntoma: la cajera hizo ventas, pero el arqueo/revisión del turno no las
contabiliza. Causa: la Venta se guardó con `turno=None` (por ejemplo porque
el empleado no tenía ficha de Empleado en ese momento, o se cerró y reabrió
el turno mientras se vendía).

Uso en el SERVIDOR (dentro del entorno del proyecto):

    python manage.py shell < reparar_turnos_ventas.py

Por defecto APLICA los cambios. Para simular sin modificar nada:

    export REPARAR_DRY_RUN=1
    python manage.py shell < reparar_turnos_ventas.py

Configuración (arriba del todo):
    USUARIO      -> None para revisar TODOS los cajeros, o 'islianet', etc.
    FECHA_INICIO / FECHA_FIN -> 'YYYY-MM-DD' (None = últimos 30 días locales)
"""
import os
from datetime import timedelta

from django.utils import timezone

DRY_RUN = os.environ.get('REPARAR_DRY_RUN', '') == '1'
USUARIO = None            # ej. 'islianet' o None para todos
FECHA_INICIO = None       # ej. '2026-11-01'
FECHA_FIN = None          # ej. '2026-11-30'

from django.contrib.auth.models import User
from core.models import Venta, Turno, Empleado

hoy = timezone.localdate()
fin = (timezone.datetime.strptime(FECHA_FIN, '%Y-%m-%d').date()
       if FECHA_FIN else hoy)
inicio = (timezone.datetime.strptime(FECHA_INICIO, '%Y-%m-%d').date()
          if FECHA_INICIO else fin - timedelta(days=30))

ini_dt, fin_dt = (
    timezone.make_aware(timezone.datetime.combine(inicio, timezone.datetime.min.time())),
    timezone.make_aware(timezone.datetime.combine(fin, timezone.datetime.max.time())),
)

print('MODO:', 'SIMULACION (dry-run)' if DRY_RUN else 'APLICANDO CAMBIOS')
print(f'Rango: {inicio} a {fin} | Usuario: {USUARIO or "TODOS"}')

ventas = Venta.objects.filter(
    turno__isnull=True,
    fecha_venta__gte=ini_dt,
    fecha_venta__lte=fin_dt,
).select_related('cajero', 'punto_venta')
if USUARIO:
    ventas = ventas.filter(cajero__username=USUARIO)
ventas = ventas.order_by('cajero__username', 'fecha_venta')

arregladas = 0
sin_turno = []

for v in ventas:
    try:
        empleado = v.cajero.empleado
    except Empleado.DoesNotExist:
        sin_turno.append((v, 'sin ficha de Empleado'))
        continue

    fecha_local = timezone.localtime(v.fecha_venta)
    # Turnos del empleado que cubren el momento de la venta.
    candidatos = Turno.objects.filter(
        empleado=empleado,
        fecha_apertura__lte=v.fecha_venta,
    )
    candidatos = [
        t for t in candidatos
        if t.fecha_cierre is None or t.fecha_cierre >= v.fecha_venta
    ]
    if not candidatos:
        sin_turno.append((v, 'ningún turno cubre la fecha'))
        continue
    # Si hay varios (turno reabierto), el más reciente antes de la venta.
    turno = max(candidatos, key=lambda t: t.fecha_apertura)
    print(f'  {v.numero_venta} {v.cajero.username} '
          f'{fecha_local:%d/%m/%Y %H:%M} -> turno #{turno.id} '
          f'({timezone.localtime(turno.fecha_apertura):%d/%m %H:%M})')
    if not DRY_RUN:
        v.turno = turno
        if v.punto_venta_id is None and turno.punto_venta_id:
            v.punto_venta = turno.punto_venta
        v.save(update_fields=['turno', 'punto_venta'])
    arregladas += 1

print(f'\nVentas a asignar: {arregladas}')
for v, motivo in sin_turno:
    print(f'  SIN TURNO: {v.numero_venta} {v.cajero.username} '
          f'{timezone.localtime(v.fecha_venta):%d/%m/%Y %H:%M} - {motivo}')
print('FIN.', 'No se aplicaron cambios.' if DRY_RUN else 'Cambios aplicados.')
