"""Regresión: el listado de productos muestra la existencia total en almacén."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Almacen, AlmacenStock, Producto


class ProductoListaExistenciaAlmacenTest(TestCase):
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

    def test_listado_suma_las_existencias_de_todos_los_almacenes(self):
        r = self.client.get(reverse('core:producto_lista'))
        self.assertEqual(r.status_code, 200)
        filas = {p.pk: p for p in r.context['productos']}
        self.assertEqual(filas[self.con.pk].almacen_total, Decimal('15.500'))
        self.assertEqual(filas[self.con.pk].almacen_total_fmt, '15.5 (lb)')
        self.assertEqual(filas[self.sin.pk].almacen_total, Decimal('0'))
        self.assertEqual(filas[self.sin.pk].almacen_total_fmt, '0')
        self.assertContains(r, 'Existencia en almacén')
        self.assertContains(r, '15.5 (lb)')

    def test_el_total_se_mantiene_al_buscar_y_al_filtrar(self):
        for url in (reverse('core:producto_lista') + '?q=Cerdo',
                    reverse('core:producto_lista') + '?q=PRD-0001'):
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                filas = list(r.context['productos'])
                self.assertEqual(len(filas), 1)
                self.assertEqual(filas[0].pk, self.con.pk)
                self.assertEqual(filas[0].almacen_total, Decimal('15.500'))
