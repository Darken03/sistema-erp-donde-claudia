#!/usr/bin/env python
"""
Script para inicializar el módulo IPB (Inventario Parcial del Día).
Asigna el stock_inicial de cada producto en InventarioDiario
con el stock actual del producto, dado que no se han realizado
ventas ni entradas para el periodo.

Uso: python inicializar_ipb.py [fecha]
Si no se especifica fecha, se usa la fecha de hoy.
"""

import os
import sys
from datetime import datetime

os.environ['DJANGO_SETTINGS_MODULE'] = 'system_erp.settings'
import django
django.setup()

from django.utils import timezone
from core.models import Producto, InventarioDiario


def inicializar_stock_inicial(fecha=None):
    """Inicializa el stock_inicial en InventarioDiario con el stock actual de cada producto."""
    if fecha is None:
        fecha = timezone.now().date()
    
    print(f"Inicializando IPB para la fecha: {fecha}")
    print("=" * 70)
    
    productos = Producto.objects.filter(activo=True)
    total_productos = productos.count()
    actualizados = 0
    creados = 0
    
    for producto in productos:
        inventario, created = InventarioDiario.objects.get_or_create(
            fecha=fecha,
            producto=producto,
            defaults={
                'stock_inicial': producto.stock,
                'entradas': 0,
                'ventas': 0,
                'stock_final': producto.stock,
                'cerrado': False,
            }
        )
        
        if created:
            creados += 1
            print(f"  [CREAR] {producto.codigo} - {producto.nombre[:40]:40s} | stock_inicial = {producto.stock}")
        else:
            # Si ya existe pero el stock_inicial es 0 o diferente, actualizarlo
            if inventario.stock_inicial != producto.stock:
                inventario.stock_inicial = producto.stock
                inventario.calcular()
                inventario.save()
                actualizados += 1
                print(f"  [ACTUALIZAR] {producto.codigo} - {producto.nombre[:40]:40s} | stock_inicial: {inventario.stock_inicial - producto.stock:+d} -> {producto.stock}")
    
    print("=" * 70)
    print(f"Proceso completado:")
    print(f"  Total productos activos: {total_productos}")
    print(f"  Registros creados: {creados}")
    print(f"  Registros actualizados: {actualizados}")
    
    # Resumen
    inventarios = InventarioDiario.objects.filter(fecha=fecha, producto__activo=True)
    total_inicial = sum(i.stock_inicial for i in inventarios)
    total_entradas = sum(i.entradas for i in inventarios)
    total_ventas = sum(i.ventas for i in inventarios)
    total_final = sum(i.stock_final for i in inventarios)
    
    print(f"\nResumen IPB para {fecha}:")
    print(f"  Stock Inicial Total: {total_inicial}")
    print(f"  Entradas Total: {total_entradas}")
    print(f"  Ventas Total: {total_ventas}")
    print(f"  Stock Final Total: {total_final}")


if __name__ == '__main__':
    fecha = None
    if len(sys.argv) > 1:
        try:
            fecha = datetime.strptime(sys.argv[1], '%Y-%m-%d').date()
        except ValueError:
            print(f"Error: Formato de fecha inválido. Use YYYY-MM-DD")
            sys.exit(1)
    
    inicializar_stock_inicial(fecha)