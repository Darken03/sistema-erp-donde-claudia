import os
import sys
import django

# Add the project directory to the path
sys.path.append('/c/Jose/Trabajo ALGOMIO/Proyecto de Claudia/Sistema ERP')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from core.models import Producto, InventarioDiario, EntradaProducto, DetalleVenta
from django.db.models import Sum
from datetime import date

# Target dates
target_dates = [date(2026, 4, 30), date(2026, 4, 29), date(2026, 4, 28)]  # Process in reverse order: 30, 29, 28

print("Starting inventory recalculation for dates:", target_dates)

# We'll process each product
products = Producto.objects.all()
print(f"Found {products.count()} products")

for product in products:
    print(f"\nProcessing product: {product.id} - {product.nombre}")
    
    # Variable to hold the stock_inicial of the next day (which becomes stock_final of current day)
    # For the first iteration (date=30), we don't have a next day, so we'll use current stock as stock_final
    next_day_stock_inicial = None
    
    for current_date in target_dates:
        # Determine stock_final for this date
        if current_date == date(2026, 4, 30):
            # For the most recent date, stock_final is the current stock in producto
            stock_final = product.stock
            print(f"  Date {current_date}: Using current product stock as stock_final: {stock_final}")
        else:
            # For previous dates, stock_final is the stock_inicial of the next day
            stock_final = next_day_stock_inicial
            print(f"  Date {current_date}: Using next day's stock_inicial as stock_final: {stock_final}")
        
        # Calculate total entradas for this product on this date
        entradas_qs = EntradaProducto.objects.filter(
            producto=product,
            fecha_entrada__date=current_date
        )
        entradas_total = entradas_qs.aggregate(total=Sum('cantidad'))['total'] or 0
        
        # Calculate total ventas for this product on this date
        ventas_qs = DetalleVenta.objects.filter(
            producto=product,
            venta__fecha_venta__date=current_date
        )
        ventas_total = ventas_qs.aggregate(total=Sum('cantidad'))['total'] or 0
        
        print(f"    Movements - Entradas: {entradas_total}, Ventas: {ventas_total}")
        
        # Calculate stock_inicial using the formula: stock_final = stock_inicial + entradas - ventas
        # Rearranged: stock_inicial = stock_final - entradas + ventas
        stock_inicial = stock_final - entradas_total + ventas_total
        
        print(f"    Calculated - Stock inicial: {stock_inicial}, Stock final: {stock_final}")
        
        # Update or create the InventarioDiario record
        inventario, created = InventarioDiario.objects.get_or_create(
            producto=product,
            fecha=current_date,
            defaults={
                'stock_inicial': stock_inicial,
                'entradas': entradas_total,
                'ventas': ventas_total,
                'stock_final': stock_final,
                'cerrado': False  # Assuming we don't close the record
            }
        )
        
        if not created:
            # Update existing record
            inventario.stock_inicial = stock_inicial
            inventario.entradas = entradas_total
            inventario.ventas = ventas_total
            inventario.stock_final = stock_final
            inventario.save()
            print(f"    Updated existing inventory record for {current_date}")
        else:
            print(f"    Created new inventory record for {current_date}")
        
        # Set next_day_stock_inicial for the previous day (which is the stock_inicial we just calculated)
        next_day_stock_inicial = stock_inicial

print("\nRecalculation completed.")