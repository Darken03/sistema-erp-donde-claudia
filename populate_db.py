"""
Script para poblar la base de datos con datos de ejemplo.
Uso: python populate_db.py
"""
import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from datetime import timedelta
from core.models import (
    Categoria, Producto, PerfilUsuario, Empleado, Turno,
    Venta, DetalleVenta, Gasto, EntradaProducto
)

print("=" * 60)
print("  BizMaster - Poblar Base de Datos")
print("=" * 60)

IMAGENES = {
    'bebida': 'https://images.unsplash.com/photo-1622483767028-3f66f32aef97?w=300&h=300&fit=crop',
    'snack': 'https://images.unsplash.com/photo-1621939514649-280e2ee25f60?w=300&h=300&fit=crop',
    'galleta': 'https://images.unsplash.com/photo-1499636136210-6f4ee915583e?w=300&h=300&fit=crop',
    'jugo': 'https://images.unsplash.com/photo-1600273002811-94c9d33f6d0e?w=300&h=300&fit=crop',
    'chocolate': 'https://images.unsplash.com/photo-1606312619070-d48b4c643a92?w=300&h=300&fit=crop',
    'agua': 'https://images.unsplash.com/photo-1548839140-29a749e1cf4d?w=300&h=300&fit=crop',
    'cafe': 'https://images.unsplash.com/photo-1559525839-b184a4d698c7?w=300&h=300&fit=crop',
    'helado': 'https://images.unsplash.com/photo-1497034825429-c343d7c6a68f?w=300&h=300&fit=crop',
    'pan': 'https://images.unsplash.com/photo-1509440159596-0249088772ff?w=300&h=300&fit=crop',
    'leche': 'https://images.unsplash.com/photo-1563636619-e9143da7973b?w=300&h=300&fit=crop',
    'varios': 'https://images.unsplash.com/photo-1550989460-0adf9ea622e2?w=300&h=300&fit=crop',
}

print("\n[1/6] Creando categorias...")
categorias_data = [
    {'nombre': 'Bebidas', 'descripcion': 'Bebidas frías y calientes'},
    {'nombre': 'Snacks', 'descripcion': 'Botanas y frituras'},
    {'nombre': 'Confitería', 'descripcion': 'Dulces y chocolates'},
    {'nombre': 'Panadería', 'descripcion': 'Pan y bollos'},
    {'nombre': 'Lácteos', 'descripcion': 'Leche, yogur y quesos'},
    {'nombre': 'Varios', 'descripcion': 'Otros productos'},
]

categorias = {}
for cat_data in categorias_data:
    cat, _ = Categoria.objects.get_or_create(nombre=cat_data['nombre'])
    cat.descripcion = cat_data['descripcion']
    cat.save()
    categorias[cat_data['nombre']] = cat
    print(f"  [OK] {cat.nombre}")

print("\n[2/6] Creando productos...")
productos_data = [
    {'nombre': 'Coca Cola 600ml', 'categoria': 'Bebidas', 'precio_compra': 8.00, 'precio_venta': 15.00, 'stock': 50, 'imagen': 'bebida'},
    {'nombre': 'Pepsi 600ml', 'categoria': 'Bebidas', 'precio_compra': 7.50, 'precio_venta': 15.00, 'stock': 45, 'imagen': 'bebida'},
    {'nombre': 'Agua Bonafont 500ml', 'categoria': 'Bebidas', 'precio_compra': 5.00, 'precio_venta': 10.00, 'stock': 80, 'imagen': 'agua'},
    {'nombre': 'Jugo Mango 500ml', 'categoria': 'Bebidas', 'precio_compra': 9.00, 'precio_venta': 18.00, 'stock': 30, 'imagen': 'jugo'},
    {'nombre': 'Café Capuchino', 'categoria': 'Bebidas', 'precio_compra': 12.00, 'precio_venta': 25.00, 'stock': 20, 'imagen': 'cafe'},
    {'nombre': 'Leche Entera 1L', 'categoria': 'Lácteos', 'precio_compra': 14.00, 'precio_venta': 22.00, 'stock': 25, 'imagen': 'leche'},
    {'nombre': 'Yogur Fresa 200g', 'categoria': 'Lácteos', 'precio_compra': 8.00, 'precio_venta': 15.00, 'stock': 40, 'imagen': 'leche'},
    {'nombre': 'Doritos Nacho 150g', 'categoria': 'Snacks', 'precio_compra': 10.00, 'precio_venta': 20.00, 'stock': 35, 'imagen': 'snack'},
    {'nombre': 'Paketaxo 150g', 'categoria': 'Snacks', 'precio_compra': 9.00, 'precio_venta': 18.00, 'stock': 30, 'imagen': 'snack'},
    {'nombre': 'Cheetos 150g', 'categoria': 'Snacks', 'precio_compra': 9.50, 'precio_venta': 18.00, 'stock': 28, 'imagen': 'snack'},
    {'nombre': 'Barcel Hot Crunch', 'categoria': 'Snacks', 'precio_compra': 11.00, 'precio_venta': 22.00, 'stock': 25, 'imagen': 'snack'},
    {'nombre': 'Churrumais 200g', 'categoria': 'Snacks', 'precio_compra': 12.00, 'precio_venta': 24.00, 'stock': 20, 'imagen': 'snack'},
    {'nombre': 'Chocolate Milky Way', 'categoria': 'Confitería', 'precio_compra': 8.00, 'precio_venta': 15.00, 'stock': 50, 'imagen': 'chocolate'},
    {'nombre': 'Chocolate Skittles', 'categoria': 'Confitería', 'precio_compra': 10.00, 'precio_venta': 20.00, 'stock': 40, 'imagen': 'chocolate'},
    {'nombre': 'Paleta Popsicle', 'categoria': 'Confitería', 'precio_compra': 5.00, 'precio_venta': 12.00, 'stock': 60, 'imagen': 'helado'},
    {'nombre': 'Galleta María', 'categoria': 'Confitería', 'precio_compra': 7.00, 'precio_venta': 14.00, 'stock': 45, 'imagen': 'galleta'},
    {'nombre': 'Bolillo', 'categoria': 'Panadería', 'precio_compra': 1.50, 'precio_venta': 4.00, 'stock': 100, 'imagen': 'pan'},
    {'nombre': 'Concha', 'categoria': 'Panadería', 'precio_compra': 3.00, 'precio_venta': 8.00, 'stock': 30, 'imagen': 'pan'},
    {'nombre': 'Donque', 'categoria': 'Panadería', 'precio_compra': 4.00, 'precio_venta': 10.00, 'stock': 25, 'imagen': 'pan'},
    {'nombre': 'Chocoramo', 'categoria': 'Panadería', 'precio_compra': 6.00, 'precio_venta': 12.00, 'stock': 35, 'imagen': 'chocolate'},
]

productos = []
for prod_data in productos_data:
    cat = categorias[prod_data['categoria']]
    prod, created = Producto.objects.get_or_create(
        nombre=prod_data['nombre'],
        categoria=cat,
        defaults={
            'precio_compra': prod_data['precio_compra'],
            'precio_venta': prod_data['precio_venta'],
            'stock': prod_data['stock'],
            'stock_minimo': 10,
            'descripcion': f"{prod_data['nombre']} - Stock mínimo: 10",
        }
    )
    if created:
        prod.imagen = IMAGENES.get(prod_data['imagen'], IMAGENES['varios'])
        prod.save()
    productos.append(prod)
    print(f"  [OK] {prod.nombre} (Stock: {prod.stock})")

print("\n[3/6] Creando usuarios y empleados...")
usuarios_data = [
    {'username': 'admin', 'first_name': 'Juan', 'last_name': 'Pérez', 'email': 'admin@bizmaster.com', 'rol': 'admin', 'password': 'admin123'},
    {'username': 'claudia', 'first_name': 'Claudia', 'last_name': '', 'email': 'claudia@bizmaster.com', 'rol': 'admin', 'password': 'claudia123'},
    {'username': 'caja1', 'first_name': 'María', 'last_name': 'García', 'email': 'caja1@bizmaster.com', 'rol': 'cajero', 'password': 'caja123'},
    {'username': 'caja2', 'first_name': 'Pedro', 'last_name': 'López', 'email': 'caja2@bizmaster.com', 'rol': 'cajero', 'password': 'caja123'},
]

empleados = []
for user_data in usuarios_data:
    user, created = User.objects.get_or_create(
        username=user_data['username'],
        defaults={
            'first_name': user_data['first_name'],
            'last_name': user_data['last_name'],
            'email': user_data['email'],
        }
    )
    if created:
        user.set_password(user_data['password'])
        user.save()
    
    perfil, _ = PerfilUsuario.objects.get_or_create(
        user=user,
        defaults={'rol': user_data['rol'], 'activo': True}
    )
    perfil.rol = user_data['rol']
    perfil.save()
    
    empleado, _ = Empleado.objects.get_or_create(
        user=user,
        defaults={'salario': 450.00 if user_data['rol'] == 'admin' else 350.00, 'activo': True}
    )
    empleados.append(empleado)
    print(f"  [OK] {user.username} ({user_data['rol']}) - {user.get_full_name()}")

print("\n[4/6] Creando turnos...")
fecha_ahora = timezone.now()
turno1 = Turno.objects.create(
    empleado=empleados[1],
    abierto=False,
    total_ventas=450.00,
    num_ventas=15,
)
turno1.fecha_apertura = fecha_ahora - timedelta(hours=8)
turno1.save()

turno2 = Turno.objects.create(
    empleado=empleados[1],
    abierto=True,
    fecha_apertura=fecha_ahora - timedelta(hours=2),
)
print(f"  [OK] Turno mañana (cerrado)")
print(f"  [OK] Turno actual (abierto)")

print("\n[5/6] Creando ventas de ejemplo...")
productos_venta = productos[:8]
for i in range(3):
    numero = Venta.generar_numero()
    while Venta.objects.filter(numero_venta=numero).exists():
        numero = Venta.generar_numero()
    
    venta = Venta.objects.create(
        numero_venta=numero,
        cajero=empleados[1].user,
        turno=turno1 if i < 2 else turno2,
        subtotal=0,
        impuesto=0,
        descuento=0,
        total=0,
        metodo_pago='efectivo',
        monto_recibido=0,
        cancelada=False,
    )
    venta.fecha_venta = fecha_ahora - timedelta(hours=7+i)
    venta.save()
    
    total_venta = Decimal('0')
    for j, prod in enumerate(productos_venta[:5]):
        cantidad = (i + 1) * (j + 1)
        DetalleVenta.objects.create(
            venta=venta,
            producto=prod,
            cantidad=cantidad,
            precio_unitario=prod.precio_venta,
            subtotal=cantidad * prod.precio_venta,
        )
        total_venta += Decimal(str(cantidad)) * prod.precio_venta
    
    venta.subtotal = total_venta
    venta.total = total_venta
    venta.monto_recibido = total_venta
    venta.cambio = 0
    venta.save()
    print(f"  [OK] Venta #{venta.numero_venta} - Total: ${venta.total}")

print("\n[6/6] Creando gastos de ejemplo...")
gastos_data = [
    {'cantidad_efectivo': 150.00, 'categoria': 'servicio', 'descripcion': 'Pago de luz'},
    {'cantidad_efectivo': 200.00, 'categoria': 'servicio', 'descripcion': 'Pago de agua'},
    {'cantidad_efectivo': 80.00, 'categoria': 'material', 'descripcion': 'Boletos de venta'},
]

for i, gasto_data in enumerate(gastos_data):
    numero = Gasto.generar_numero()
    while Gasto.objects.filter(numero_gasto=numero).exists():
        numero = Gasto.generar_numero()
    
    Gasto.objects.create(
        numero_gasto=numero,
        cajero=empleados[1].user,
        turno=turno1,
        cantidad_efectivo=gasto_data['cantidad_efectivo'],
        cantidad_transferencia=0,
        categoria=gasto_data['categoria'],
        descripcion=gasto_data['descripcion'],
    )
    print(f"  [OK] Gasto #{i+1} - ${gasto_data['cantidad_efectivo']}")

print("\n" + "=" * 60)
print("  Base de datos poblada exitosamente!")
print("=" * 60)
print(f"\nResumen:")
print(f"  - Categorías: {Categoria.objects.count()}")
print(f"  - Productos: {Producto.objects.count()}")
print(f"  - Usuarios: {User.objects.count()}")
print(f"  - Empleados: {Empleado.objects.count()}")
print(f"  - Turnos: {Turno.objects.count()}")
print(f"  - Ventas: {Venta.objects.count()}")
print(f"  - Gastos: {Gasto.objects.count()}")
print("\nCredenciales de acceso:")
print("  Admin: admin / admin123")
print("  Admin: claudia / claudia123")
print("  Cajero: caja1 / caja123")
print("=" * 60)