from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import (
    PerfilUsuario, Producto, Almacen, AlmacenStock, AlmacenEntrada,
)


def _usuario(username, rol='admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


def _stock(prod, alm):
    try:
        return AlmacenStock.objects.get(producto=prod, almacen=alm).cantidad
    except AlmacenStock.DoesNotExist:
        return Decimal('0')


class TestEntradas(TestCase):
    def setUp(self):
        _usuario('m_admin', 'admin')
        self.prod = Producto.objects.create(
            nombre='Arroz M', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('0'))

    def test_entradas_aisladas_por_almacen(self):
        self.client.login(username='m_admin', password='x12345')
        a1 = Almacen.objects.get(es_principal=True)
        a2 = Almacen.objects.create(nombre='Secundario M')
        self.client.post(reverse('core:almacen_entrada_crear'), {
            'producto': self.prod.pk, 'cantidad': '25',
            'costo_unitario': '12', 'almacen': str(a1.pk)})
        self.client.post(reverse('core:almacen_entrada_crear'), {
            'producto': self.prod.pk, 'cantidad': '10',
            'costo_unitario': '12', 'almacen': str(a2.pk)})
        self.assertEqual(_stock(self.prod, a1), Decimal('25'))
        self.assertEqual(_stock(self.prod, a2), Decimal('10'))
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('0'))
        # Las entradas quedaron asociadas a su almacén.
        self.assertTrue(AlmacenEntrada.objects.filter(producto=self.prod, almacen=a1).exists())
        self.assertTrue(AlmacenEntrada.objects.filter(producto=self.prod, almacen=a2).exists())

    def test_con_un_almacen_post_sin_almacen_usa_el_unico(self):
        self.client.login(username='m_admin', password='x12345')
        self.assertEqual(Almacen.objects.filter(activo=True).count(), 1)
        r = self.client.post(reverse('core:almacen_entrada_crear'), {
            'producto': self.prod.pk, 'cantidad': '7', 'costo_unitario': '5'})
        self.assertEqual(r.status_code, 302)
        a1 = Almacen.objects.get(es_principal=True)
        self.assertEqual(_stock(self.prod, a1), Decimal('7'))


class TestUnAlmacenSinSelectores(TestCase):
    def setUp(self):
        _usuario('s_admin', 'admin')

    def test_con_un_almacen_no_hay_selectores(self):
        self.client.login(username='s_admin', password='x12345')
        self.assertEqual(Almacen.objects.filter(activo=True).count(), 1)
        html = self.client.get(reverse('core:almacen_entrada_crear')).content.decode()
        self.assertTrue('name="almacen"' not in html or 'type="hidden"' in html)
        html2 = self.client.get(reverse('core:almacen_traslado_crear')).content.decode()
        self.assertTrue('name="origen"' not in html2 or 'type="hidden"' in html2)


class TestPanelFiltros(TestCase):
    def setUp(self):
        _usuario('p_admin', 'admin')

    def test_panel_y_filtros_por_almacen(self):
        self.client.login(username='p_admin', password='x12345')
        a1 = Almacen.objects.get(es_principal=True)
        Almacen.objects.create(nombre='Secundario P')
        html = self.client.get('/almacen/?almacen=%s' % a1.pk).content.decode()
        self.assertIn('Almacén Principal', html)
        self.assertIn('Secundario P', html)
        self.assertEqual(
            self.client.get('/almacen/existencias/?almacen=%s' % a1.pk).status_code, 200)


class TestTraslados(TestCase):
    def setUp(self):
        _usuario('t_admin', 'admin')
        self.prod = Producto.objects.create(
            nombre='Leche T', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('0'))

    def _entrar(self, prod, cant, alm):
        self.client.post(reverse('core:almacen_entrada_crear'), {
            'producto': prod.pk, 'cantidad': str(cant),
            'costo_unitario': '10', 'almacen': str(alm.pk)})

    def test_traslado_almacen_a_almacen_y_a_pos(self):
        self.client.login(username='t_admin', password='x12345')
        from .models import EntradaProducto
        a1 = Almacen.objects.get(es_principal=True)
        a2 = Almacen.objects.create(nombre='Secundario T')
        self._entrar(self.prod, 25, a1)
        self._entrar(self.prod, 10, a2)
        r = self.client.post(reverse('core:almacen_traslado_crear'), {
            'producto': self.prod.pk, 'cantidad': '5',
            'origen': str(a1.pk), 'destino_tipo': 'ALMACEN',
            'destino_almacen': str(a2.pk)})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(_stock(self.prod, a1), Decimal('20'))
        self.assertEqual(_stock(self.prod, a2), Decimal('15'))
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('0'))
        r2 = self.client.post(reverse('core:almacen_traslado_crear'), {
            'producto': self.prod.pk, 'cantidad': '4',
            'origen': str(a2.pk), 'destino_tipo': 'POS'})
        self.assertEqual(r2.status_code, 302)
        self.assertEqual(_stock(self.prod, a2), Decimal('11'))
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('4'))
        self.assertTrue(EntradaProducto.objects.filter(
            producto=self.prod, proveedor__startswith='Almacén').exists())
        # Sin stock bloquea y no mueve nada.
        r3 = self.client.post(reverse('core:almacen_traslado_crear'), {
            'producto': self.prod.pk, 'cantidad': '999',
            'origen': str(a1.pk), 'destino_tipo': 'POS'})
        self.assertIn(r3.status_code, (302, 200))
        self.assertEqual(_stock(self.prod, a1), Decimal('20'))
