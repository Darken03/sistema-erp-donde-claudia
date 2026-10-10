import os
import sys
import django
from django.conf import settings

# Add the project directory to the path
sys.path.append('/c/Jose/Trabajo ALGOMIO/Proyecto de Claudia/Sistema ERP')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')  # Adjust if your settings module is different
django.setup()

from core.models import Producto, InventarioDiario, EntradaProducto, DetalleVenta, MovimientoInventario
from django.db.models import Sum
from datetime import date

# Target dates
target_dates = [date(2026, 4, 28), date(2026, 4, 29), date(2026, 4, 30)]

print("Productos:")
for p in Producto.objects.filter(activo=True)[:5]:
    print(f"  {p.id}: {p.nombre} - stock actual: {p.stock}")

print("\nInventarioDiario for target dates:")
for d in target_dates:
    print(f"  {d}:")
    for inv in InventarioDiario.objects.filter(fecha=d).select_related('producto')[:5]:
        print(f"    {inv.producto.nombre}: inicial={inv.stock_inicial}, entradas={inv.entradas}, ventas={inv.ventas}, final={inv.stock_final}")

print("\nEntradas por producto y fecha:")
for d in target_dates:
    print(f"  {d}:")
    qs = EntradaProducto.objects.filter(fecha_entrada__date=d).values('producto__nombre').annotate(total=Sum('cantidad'))
    for r in qs:
        print(f"    {r['producto__nombre']}: {r['total']}")

print("\nVentas por producto y fecha:")
for d in target_dates:
    print(f"  {d}:")
    qs = DetalleVenta.objects.filter(venta__fecha_venta__date=d).values('producto__nombre').annotate(total=Sum('cantidad'))
    for r in qs:
        print(f"    {r['producto__nombre']}: {r['total']}")

print("\nMovimientos por tipo y fecha:")
for d in target_dates:
    print(f"  {d}:")
    qs = MovimientoInventario.objects.filter(fecha__date=d).values('tipo').annotate(total=Sum('cantidad'))
    for r in qs:
        print(f"    {r['tipo']}: {r['total']}")