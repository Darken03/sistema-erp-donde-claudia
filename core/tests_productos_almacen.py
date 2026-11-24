"""Regresión: la existencia total en almacén se ve solo en el detalle del producto."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Almacen, AlmacenStock, Producto


class ProductoExistenciaAlmacenTest(TestCase):
    def setUp(self):
        u = User.objects.create_user(username='admin-almacen', password='x')
        u.perfil.rol = 'admin'
        u.perfil.save(update_fields=['rol'])
        u.refresh_from_db()
        self.client.force_login(u)
        a1 = Almacen.objects.create(nombre='Almacén A')
        a2 = Almacen.objects.create(nombre='Almacén B')
        self.con = Producto.objects.create(
            nombre='Cerdo', codigo='PRD-0001', unidad_medida='lb',
            precio_venta=100)
        self.sin = Producto.objects.create(
            nombre='Sin existencia', codigo='PRD-0002',
            unidad_medida='unidades', precio_venta=10)
        AlmacenStock.objects.create(
            producto=self.con, almacen=a1, cantidad=Decimal('10'))
        AlmacenStock.objects.create(
            producto=self.con, almacen=a2, cantidad=Decimal('5.500'))

    def test_detalle_muestra_el_total_de_todos_los_almacenes(self):
        r = self.client.get(
            reverse('core:producto_detalle', args=[self.con.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(
            r.context['producto'].almacen_total_fmt, '15.5 (lb)')
        self.assertContains(r, 'Existencia en almacén (total)')
        self.assertContains(r, '15.5 (lb)')

    def test_detalle_muestra_cero_cuando_no_hay_existencias(self):
        r = self.client.get(
            reverse('core:producto_detalle', args=[self.sin.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['producto'].almacen_total_fmt, '0')
        self.assertContains(r, 'Existencia en almacén (total)')

    def test_listado_no_muestra_la_columna_de_almacen(self):
        r = self.client.get(reverse('core:producto_lista'))
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'Existencia en almacén')
        self.assertNotContains(r, '15.5 (lb)')
