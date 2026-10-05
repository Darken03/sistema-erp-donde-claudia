"""
Limpieza de BD para despliegue: borra TODO excepto usuarios y roles.
Conserva: auth_user, core_perfilusuario (+ grupos/permisos de Django).
Borra: productos, presentaciones, categorías, turnos, empleados, ventas,
  deudas, gastos, entradas, donaciones, movimientos, inventarios diarios,
  arqueos, conteos, mostrador, sesiones y log de admin.
Uso: python limpiar_bd.py
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from django.contrib.admin.models import LogEntry
from core.models import (
    Producto, Categoria, Empleado, Turno, Venta, DetalleVenta, Gasto,
    EntradaProducto, RetiroDonacion, MovimientoInventario, InventarioDiario,
    Deuda, AbonoDeuda, Deudor, PresentacionProducto, MostradorEstado,
    ArqueoTurno, ConteoCiego, ConteoCiegoLinea,
)

# Hijos primero (PROTECT/CASCADE), padres al final.
ORDEN = [
    ('Líneas de conteo', ConteoCiegoLinea),
    ('Conteos ciegos', ConteoCiego),
    ('Arqueos', ArqueoTurno),
    ('Abonos de deuda', AbonoDeuda),
    ('Deudas', Deuda),
    ('Deudores', Deudor),
    ('Detalles de venta', DetalleVenta),
    ('Ventas', Venta),
    ('Gastos', Gasto),
    ('Entradas', EntradaProducto),
    ('Donaciones', RetiroDonacion),
    ('Movimientos', MovimientoInventario),
    ('Inventarios diarios', InventarioDiario),
    ('Mostrador', MostradorEstado),
    ('Presentaciones', PresentacionProducto),
    ('Turnos', Turno),
    ('Empleados', Empleado),
    ('Productos', Producto),
    ('Categorías', Categoria),
    ('Sesiones', Session),
    ('Log admin', LogEntry),
]

print('Limpiando BD (se conservan usuarios y roles)...')
for nombre, modelo in ORDEN:
    n, _ = modelo.objects.all().delete()
    print(f'  [OK] {nombre}: {n} registro(s)')

print(f'\nUsuarios conservados: {User.objects.count()}')
for u in User.objects.order_by('username'):
    rol = getattr(getattr(u, 'perfil', None), 'rol', '?')
    print(f'  - {u.username} (rol={rol}, super={u.is_superuser})')
print('\nBD lista para despliegue.')
