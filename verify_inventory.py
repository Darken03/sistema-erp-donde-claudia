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

# Verify a few products
test_products = [198, 263]  # Products we know exist from previous output

print("Verification of inventory calculations:")
print("=" * 50)

for product_id in test_products:
    try:
        product = Producto.objects.get(id=product_id)
        print(f"\nProduct: {product.nombre} (ID: {product.id})")
        print(f"Current stock in producto: {product.stock}")
        
        # Check the three dates
        target_dates = [date(2026, 4, 30), date(2026, 4, 29), date(2026, 4, 28)]
        
        for i, current_date in enumerate(target_dates):
            inv = InventarioDiario.objects.get(producto=product, fecha=current_date)
            
            # Calculate movements for this date
            entradas = EntradaProducto.objects.filter(
                producto=product,
                fecha_entrada__date=current_date
            ).aggregate(total=Sum('cantidad'))['total'] or 0
            
            ventas = DetalleVenta.objects.filter(
                producto=product,
                venta__fecha_venta__date=current_date
            ).aggregate(total=Sum('cantidad'))['total'] or 0
            
            print(f"  Date {current_date}:")
            print(f"    Stock inicial: {inv.stock_inicial}")
            print(f"    Entradas: {entradas}")
            print(f"    Ventas: {ventas}")
            print(f"    Stock final: {inv.stock_final}")
            
            # Verify the calculation
            expected_final = inv.stock_inicial + entradas - ventas
            if inv.stock_final == expected_final:
                print(f"    OK Calculation correct: {inv.stock_inicial} + {entradas} - {ventas} = {expected_final}")
            else:
                print(f"    ERROR Calculation error: {inv.stock_inicial} + {entradas} - {ventas} = {expected_final}, but stock_final is {inv.stock_final}")
                
            # For dates except the last one, verify that stock_inicial equals next day's stock_final
            if i < len(target_dates) - 1:
                next_date = target_dates[i + 1]
                next_inv = InventarioDiario.objects.get(producto=product, fecha=next_date)
                if inv.stock_inicial == next_inv.stock_final:
                    print(f"    OK Link correct: stock_inicial today ({inv.stock_inicial}) = stock_final tomorrow ({next_inv.stock_final})")
                else:
                    print(f"    ERROR Link error: stock_inicial today ({inv.stock_inicial}) != stock_final tomorrow ({next_inv.stock_final})")
                    
    except Producto.DoesNotExist:
        print(f"Product with ID {product_id} not found")
    except InventarioDiario.DoesNotExist:
        print(f"InventarioDiario record missing for product {product_id}")

print("\n" + "=" * 50)
print("Verification completed.")