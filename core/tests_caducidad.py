from datetime import date, timedelta
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import (
    PerfilUsuario, Producto, Almacen, AlmacenStock, AlmacenEntrada,
    DIAS_AVISO_CADUCIDAD,
)


def _usuario(username, rol='admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


class TestCaducidad(TestCase):
    def setUp(self):
        _usuario('cad_admin', 'admin')
        self.prod = Producto.objects.create(
            nombre='Leche C', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('0'))

    def _entrar(self, dias, cantidad='10', prod=None):
        self.client.login(username='cad_admin', password='x12345')
        a1 = Almacen.objects.get(es_principal=True)
        fecha = (date.today() + timedelta(days=dias)).isoformat() if dias is not None else ''
        return self.client.post(reverse('core:almacen_entrada_crear'), {
            'producto': (prod or self.prod).pk, 'cantidad': cantidad,
            'costo_unitario': '10', 'almacen': str(a1.pk),
            'fecha_caducidad': fecha})

    def test_entrada_guarda_fecha_caducidad(self):
        self._entrar(60)
        ent = AlmacenEntrada.objects.get(producto=self.prod)
        self.assertEqual(ent.fecha_caducidad, date.today() + timedelta(days=60))
        self.assertEqual(ent.estado_caducidad, 'ok')

    def test_por_vencer_un_mes(self):
        self._entrar(20)
        ent = AlmacenEntrada.objects.get(producto=self.prod)
        self.assertEqual(ent.estado_caducidad, 'por_vencer')
        self.assertEqual(DIAS_AVISO_CADUCIDAD, 30)

    def test_vencido(self):
        self._entrar(-5)
        ent = AlmacenEntrada.objects.get(producto=self.prod)
        self.assertEqual(ent.estado_caducidad, 'vencido')

    def test_sin_fecha_no_marca(self):
        self._entrar(None)
        ent = AlmacenEntrada.objects.get(producto=self.prod)
        self.assertIsNone(ent.fecha_caducidad)
        self.assertEqual(ent.estado_caducidad, 'ok')

    def test_existencias_resalta_por_vencer(self):
        self._entrar(10)
        a1 = Almacen.objects.get(es_principal=True)
        html = self.client.get(
            '/almacen/existencias/?almacen=%s' % a1.pk).content.decode()
        self.assertIn('caducidad-por-vencer', html)

    def test_panel_alerta_caducidad(self):
        self._entrar(10)
        otro = Producto.objects.create(
            nombre='Yogur C', unidad_medida='unidades',
            precio_compra=5, precio_venta=10, stock=Decimal('0'))
        self._entrar(-3, prod=otro)
        html = self.client.get('/almacen/').content.decode()
        self.assertIn('por vencer', html)
        self.assertIn('vencidos', html)
