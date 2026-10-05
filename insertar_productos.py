#!/usr/bin/env python
"""
Script para insertar productos en la base de datos del sistema ERP.
Ejecutar desde la raíz del proyecto: python insertar_productos.py
"""

import os
import sys
import django

# Configurar Django
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from core.models import Producto, Categoria

PRODUCTOS = [
    # Cerdo
    ("Cerdo Entero", 12),
    ("Chicharrón Cerdo", 61),
    ("Rabo Cerdo", 8),
    ("Cocote Cerdo", 13),
    ("Picadillo Cerdo", 20),
    ("Costillas Cerdo 2 lb", 21),
    ("Chuletas Cerdo", 29),
    ("Bistec Cerdo", 15),
    ("Costilla Cerdo", 20),
    ("Hueso Cerdo", 38),
    ("Costilla Cerdo 3 lb", 13),
    ("Troceado Cerdo", 29),
    # Res
    ("Costilla Res 4 lb", 121),
    ("Carne Res Troceado", 27),
    ("Cocote Res 2 lb", 196),
    ("Costilla Cerdo 2 lb", 138),
    ("Picadillo Res 2 lb", 70),
    ("Picadillo Res", 723),
    ("Costillas Res 4 lb", 623),
    ("Bolo Res", 1),
    ("Cocote Res 3 lb", 167),
    ("Carne Separada Bolo (1 lb)", 3),
    ("Carne Separada Bolo (1 kg)", 393),
    ("Mechillo Cando", 1),
    ("Bote Res", 2),
    ("Cave Res Trozados", 6),
    # Otros
    ("Pañales desechables (17a etapa)", 1756),
    ("Café natural", 2483),
    ("Toallas húmedas", 38),
    ("Bombillo 9W", 350),
    ("Bombillo 15W", 392),
    ("Chocolate polvo", 2),
    ("Leche entera", 36),
    ("Bombillo 14W", 356),
    ("Cerveza Solera", 52704),
    ("Leche semidescremada", 3660),
    ("Arroz", 14856),
]

def main():
    print("=" * 60)
    print("INSERTANDO PRODUCTOS EN LA BASE DE DATOS")
    print("=" * 60)
    
    # Generar código inicial
    ultimo = Producto.objects.order_by('-id').first()
    if ultimo and ultimo.codigo and ultimo.codigo.startswith('PRD-'):
        try:
            num = int(ultimo.codigo.split('-')[-1])
            siguiente_num = num + 1
        except (ValueError, IndexError):
            siguiente_num = 1
    else:
        siguiente_num = 1
    
    productos_creados = 0
    productos_existentes = 0
    
    for nombre, stock in PRODUCTOS:
        # Verificar si ya existe el producto
        if Producto.objects.filter(nombre=nombre).exists():
            print(f"  [YA EXISTE] {nombre}")
            productos_existentes += 1
            continue
        
        # Crear nuevo producto
        codigo = f"PRD-{siguiente_num:04d}"
        producto = Producto(
            codigo=codigo,
            nombre=nombre,
            stock=stock,
            activo=True
        )
        producto.save()
        print(f"  [CREADO] {codigo} - {nombre} (stock: {stock})")
        
        siguiente_num += 1
        productos_creados += 1
    
    print("-" * 60)
    print(f"Total creados: {productos_creados}")
    print(f"Total existentes: {productos_existentes}")
    print(f"Total productos procesados: {productos_creados + productos_existentes}")
    print("=" * 60)
    
    # Mostrar todos los productos
    print("\nPRODUCTOS EN LA BASE DE DATOS:")
    print("-" * 60)
    for p in Producto.objects.all().order_by('codigo'):
        print(f"  {p.codigo} | {p.nombre[:40]:<40} | Stock: {p.stock}")

if __name__ == '__main__':
    main()