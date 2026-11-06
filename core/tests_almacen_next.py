from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import PerfilUsuario, Producto


def _usuario(username, rol='admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


class AlmacenEntradaProductoCrearRetornoTest(TestCase):
    def setUp(self):
        self.admin = _usuario('adminNext', 'admin')
        self.client.login(username='adminNext', password='x12345')

    def test_producto_crear_con_next_vuelve_a_entrada_y_preselecciona(self):
        next_url = reverse('core:almacen_entrada_crear')
        url = reverse('core:producto_crear') + f'?next={next_url}'
        r = self.client.post(url, {
            'nombre': 'Queso Nuevo',
            'unidad_medida': 'unidades',
            'precio_compra': '10',
            'precio_venta': '20',
            'stock': '5',
            'stock_minimo': '1',
            'activo': 'on',
            # formset mínimo (extra=1)
            'presentaciones-TOTAL_FORMS': '1',
            'presentaciones-INITIAL_FORMS': '0',
            'presentaciones-MIN_NUM_FORMS': '0',
            'presentaciones-MAX_NUM_FORMS': '1000',
            'presentaciones-0-nombre': 'Unidad',
            'presentaciones-0-factor': '1',
            'presentaciones-0-precio': '20',
            'presentaciones-0-es_default': 'on',
            'presentaciones-0-activo': 'on',
            'next': next_url,
        })
        self.assertEqual(r.status_code, 302)
        prod = Producto.objects.get(nombre='Queso Nuevo')
        self.assertIn(next_url, r.url)
        self.assertIn(f'producto={prod.pk}', r.url)

    def test_entrada_preselecciona_producto_por_query(self):
        prod = Producto.objects.create(
            nombre='Arroz Pre', unidad_medida='unidades',
            precio_compra=10, precio_venta=20,
            stock=Decimal('100'), permite_decimal=False)
        url = reverse('core:almacen_entrada_crear') + f'?producto={prod.pk}'
        r = self.client.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(str(r.context['preseleccionado']), str(prod.pk))
