"""
Script para limpiar completamente la base de datos y crear un superusuario admin.
Uso: python reset_db.py
"""
import os
import sys
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'system_erp.settings')
django.setup()

from django.contrib.auth.models import User, Permission, Group
from django.contrib.contenttypes.models import ContentType
from django.contrib.sessions.models import Session
from django.contrib.admin.models import LogEntry
from core.models import (
    Producto, Categoria, Empleado, PerfilUsuario, Turno, 
    Venta, DetalleVenta, Gasto, EntradaProducto, 
    RetiroDonacion, MovimientoInventario, InventarioDiario, Deuda
)

print("=" * 50)
print("  BizMaster - Reset de Base de Datos")
print("=" * 50)

print("\nLimpiando tablas...")

LogEntry.objects.all().delete()
print("  [OK] LogEntry")

Session.objects.all().delete()
print("  [OK] Session")

DetalleVenta.objects.all().delete()
print("  [OK] DetalleVenta")

Venta.objects.all().delete()
print("  [OK] Venta")

Gasto.objects.all().delete()
print("  [OK] Gasto")

EntradaProducto.objects.all().delete()
print("  [OK] EntradaProducto")

MovimientoInventario.objects.all().delete()
print("  [OK] MovimientoInventario")

InventarioDiario.objects.all().delete()
print("  [OK] InventarioDiario")

RetiroDonacion.objects.all().delete()
print("  [OK] RetiroDonacion")

Turno.objects.all().delete()
print("  [OK] Turno")

Empleado.objects.all().delete()
print("  [OK] Empleado")

Producto.objects.all().delete()
print("  [OK] Producto")

Categoria.objects.all().delete()
print("  [OK] Categoria")

PerfilUsuario.objects.all().delete()
print("  [OK] PerfilUsuario")

Permission.objects.all().delete()
print("  [OK] Permission")

Group.objects.all().delete()
print("  [OK] Group")

Deuda.objects.all().delete()
    

User.objects.all().delete()
print("  [OK] Users")

ContentType.objects.all().delete()
print("  [OK] ContentType")

print("\nCreando superusuario...")
admin = User.objects.create_superuser(
    username='admin',
    email='admin@bizmaster.com',
    password='Mu@031027'
)
print(f"  [OK] Superusuario creado: admin / Mu@031027")

claudia, created = User.objects.get_or_create(
    username='claudia',
    defaults={'first_name': 'Claudia', 'email': 'claudia@bizmaster.com'}
)
if created:
    claudia.set_password('claudia123')
    claudia.save()
print(f"  [OK] Usuario creado/actualizado: claudia / claudia123")

from core.models import PerfilUsuario
perfil, _ = PerfilUsuario.objects.get_or_create(
    user=claudia,
    defaults={'rol': 'admin', 'activo': True}
)
perfil.rol = 'admin'
perfil.save()
print(f"  [OK] Rol de claudia establecido a: admin")

print("\n" + "=" * 50)
print("  Base de datos completamente limpia!")
print("=" * 50)