from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse, NoReverseMatch
from .models import (
    Empleado, PerfilUsuario, Producto,
    EntradaProducto, AlmacenStock, AlmacenEntrada,
    AlmacenTraslado, AlmacenMovimiento,
)


def _usuario(username, rol='cajero'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


class AlmacenTest(TestCase):
    def setUp(self):
        self.admin = _usuario('adminA', 'admin')
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.save()
        self.alm = _usuario('almacenero1', 'almacenero')
        self.cajero = _usuario('cajeroA')
        Empleado.objects.create(user=self.cajero, salario=0, activo=True)
        self.prod = Producto.objects.create(
            nombre='Arroz', unidad_medida='unidades', precio_compra=10,
            precio_venta=20, stock=Decimal('100'), permite_decimal=False)

    def test_entrada_almacen_suma_almacen_sin_tocar_pos(self):
        self.client.login(username='almacenero1', password='x12345')
        r = self.client.post(reverse('core:almacen_entrada_crear'), {
            'producto': self.prod.pk, 'cantidad': '25',
            'costo_unitario': '12', 'proveedor': 'Proveedor X',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AlmacenStock.objects.get(producto=self.prod).cantidad, Decimal('25'))
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('100'))
        self.assertEqual(self.prod.precio_compra, Decimal('12'))
        self.assertTrue(AlmacenMovimiento.objects.filter(
            producto=self.prod, tipo='entrada').exists())

    def test_traslado_mueve_a_pos_y_genera_entrada_ipb(self):
        AlmacenStock.objects.create(producto=self.prod, cantidad=Decimal('25'))
        self.client.login(username='almacenero1', password='x12345')
        r = self.client.post(reverse('core:almacen_traslado_crear'), {
            'producto': self.prod.pk, 'cantidad': '10',
        })
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AlmacenStock.objects.get(producto=self.prod).cantidad, Decimal('15'))
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('110'))
        ent = EntradaProducto.objects.filter(
            producto=self.prod, proveedor='Almacén').first()
        self.assertIsNotNone(ent)
        self.assertEqual(ent.cantidad, Decimal('10'))
        self.assertTrue(AlmacenMovimiento.objects.filter(
            producto=self.prod, tipo='traslado').exists())

    def test_traslado_sin_stock_rechaza(self):
        self.client.login(username='almacenero1', password='x12345')
        r = self.client.post(reverse('core:almacen_traslado_crear'), {
            'producto': self.prod.pk, 'cantidad': '999',
        })
        self.assertEqual(r.status_code, 302)
        self.assertFalse(AlmacenTraslado.objects.exists())
        self.assertFalse(EntradaProducto.objects.filter(proveedor='Almacén').exists())
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('100'))

    def test_permisos_almacen(self):
        urls = ['core:almacen_panel', 'core:almacen_stock',
                'core:almacen_entrada_lista', 'core:almacen_traslado_lista',
                'core:almacen_movimientos']
        for name in urls:
            url = reverse(name)
            # Anónimo va al login.
            self.client.logout()
            self.assertEqual(self.client.get(url).status_code, 302)
            # Cajero no entra (rebota al POS).
            self.client.login(username='cajeroA', password='x12345')
            r = self.client.get(url)
            self.assertEqual(r.status_code, 302)
            self.assertTrue(r.url.endswith('/pos/'))
            self.client.logout()
        # Almacenero y admin sí entran al panel.
        self.client.login(username='almacenero1', password='x12345')
        self.assertEqual(
            self.client.get(reverse('core:almacen_panel')).status_code, 200)
        self.client.login(username='adminA', password='x12345')
        self.assertEqual(
            self.client.get(reverse('core:almacen_panel')).status_code, 200)

    def test_almacenero_redirige_a_su_panel(self):
        self.client.login(username='almacenero1', password='x12345')
        r = self.client.get(reverse('core:redireccion_rol'))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith('/almacen/'))

    def test_almacenero_no_entra_al_pos(self):
        self.client.login(username='almacenero1', password='x12345')
        r = self.client.get(reverse('core:pos'))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith('/almacen/'))

    def test_entrada_directa_al_pos_eliminada_pero_historial_visible(self):
        with self.assertRaises(NoReverseMatch):
            reverse('core:entrada_crear')
        with self.assertRaises(NoReverseMatch):
            reverse('core:entrada_eliminar', args=[1])
        EntradaProducto.objects.create(
            numero_entrada='ENT-000001', producto=self.prod,
            cantidad=Decimal('5'), costo_unitario=Decimal('10'))
        self.client.login(username='adminA', password='x12345')
        r = self.client.get(reverse('core:entrada_lista'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ENT-000001')
        self.assertNotContains(r, 'Nueva Entrada')
