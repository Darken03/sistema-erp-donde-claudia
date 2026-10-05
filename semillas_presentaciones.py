"""Semillas: Cerdo por libra + Huevo por unidad/docena/cartón (precios manuales de ejemplo).

Uso:
    venv/Scripts/python.exe semillas_presentaciones.py
Idempotente: si existen, solo completa presentaciones faltantes.
"""
import os
import django
from decimal import Decimal

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from core.models import Producto, PresentacionProducto


def upsert_producto(nombre, unidad, permite_decimal, stock, precio_ref, presentaciones):
    p, created = Producto.objects.get_or_create(
        nombre=nombre,
        defaults={
            'unidad_medida': unidad, 'permite_decimal': permite_decimal,
            'stock': Decimal(str(stock)), 'stock_minimo': Decimal('0'),
            'precio_compra': Decimal('0'), 'precio_venta': Decimal(str(precio_ref)),
            'activo': True,
        },
    )
    if not created:
        p.unidad_medida = unidad
        p.permite_decimal = permite_decimal
        p.save(update_fields=['unidad_medida', 'permite_decimal'])
    for nombre_pr, factor, precio, es_default in presentaciones:
        pr, c2 = PresentacionProducto.objects.get_or_create(
            producto=p, nombre=nombre_pr,
            defaults={'factor': Decimal(str(factor)), 'precio': Decimal(str(precio)),
                      'es_default': es_default, 'activo': True},
        )
        if not c2:
            pr.factor = Decimal(str(factor))
            pr.precio = Decimal(str(precio))
            pr.activo = True
            if es_default:
                pr.es_default = True
            pr.save()
    # Garantiza un default
    if not p.presentaciones.filter(es_default=True).exists():
        primera = p.presentaciones.order_by('factor').first()
        if primera:
            primera.es_default = True
            primera.save(update_fields=['es_default'])
    print(('CREADO ' if created else 'OK ') + f'{p.codigo} - {p.nombre} '
          f'(stock {p.stock} {p.unidad_medida})')
    for pr in p.presentaciones.order_by('factor'):
        print(f'    - {pr.nombre} x{pr.factor} = ${pr.precio}'
              + (' [default]' if pr.es_default else ''))


upsert_producto('Cerdo', 'lb', True, 100, 180, [
    ('Libra', 1, 180, True),
    ('Media libra', 0.5, 95, False),
])

upsert_producto('Huevo', 'unidades', True, 500, 10, [
    ('Unidad', 1, 10, True),
    ('Docena', 12, 110, False),
    ('Medio cartón', 15, 130, False),
    ('Cartón 30', 30, 250, False),
])

print('Listo. Ajuste precios/stock desde el admin o producto_editar.')
