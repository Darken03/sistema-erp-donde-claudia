from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.db import IntegrityError
from django.urls import reverse
from .models import PerfilUsuario, Producto, Almacen, ConfiguracionTienda, AlmacenStock


def _usuario(username, rol='admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


class TestModelosMigracion(TestCase):
    def test_migracion_crea_principal_y_stock_por_almacen(self):
        # La migración de datos debe dejar un Principal activo + config default.
        principales = Almacen.objects.filter(es_principal=True, activo=True)
        self.assertEqual(principales.count(), 1)
        self.assertEqual(ConfiguracionTienda.get_solo().nombre_tienda, 'Donde Clau')
        # Stock único por (producto, almacen).
        prod = Producto.objects.create(
            nombre='Frijol', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('0'))
        a1 = principales.first()
        AlmacenStock.objects.create(producto=prod, almacen=a1, cantidad=Decimal('1'))
        with self.assertRaises(IntegrityError):
            AlmacenStock.objects.create(producto=prod, almacen=a1, cantidad=Decimal('2'))


class TestPermisosConfig(TestCase):
    def setUp(self):
        _usuario('cfg_admin', 'admin')
        _usuario('cfg_cajero', 'cajero')

    def test_solo_admin_accede(self):
        self.client.login(username='cfg_cajero', password='x12345')
        r = self.client.get(reverse('core:configuracion'))
        self.assertIn(r.status_code, (302, 403))
        self.client.login(username='cfg_admin', password='x12345')
        self.assertEqual(self.client.get(reverse('core:configuracion')).status_code, 200)


class TestCRUDAlmacen(TestCase):
    def setUp(self):
        _usuario('crud_admin', 'admin')

    def test_crea_almacen_con_nombre_y_bloquea_duplicado(self):
        self.client.login(username='crud_admin', password='x12345')
        r = self.client.post(reverse('core:config_almacen_crear'), {
            'nombre': 'Secundario', 'descripcion': 'Segundo'})
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Almacen.objects.filter(nombre='Secundario').exists())
        n = Almacen.objects.count()
        self.client.post(reverse('core:config_almacen_crear'), {
            'nombre': 'Secundario', 'descripcion': 'Dup'})
        self.assertEqual(Almacen.objects.count(), n)

class TestApariencia(TestCase):
    def setUp(self):
        _usuario('ap_admin', 'admin')

    def test_logo_y_acento_aplican(self):
        self.client.login(username='ap_admin', password='x12345')
        r = self.client.post('/configuracion/?tab=apariencia', {
            'form_kind': 'apariencia', 'color_acento': '#0ea5e9',
            'tema_por_defecto': 'dark'})
        self.assertEqual(r.status_code, 302)
        cfg = ConfiguracionTienda.get_solo()
        self.assertEqual(cfg.color_acento, '#0ea5e9')
        html = self.client.get('/configuracion/?tab=apariencia').content.decode()
        self.assertIn('#0ea5e9', html)
        # Upload logo JPG válido persiste.
        import io
        from PIL import Image
        from django.core.files.uploadedfile import SimpleUploadedFile
        buf = io.BytesIO()
        Image.new('RGB', (10, 10), 'red').save(buf, format='JPEG')
        buf.seek(0)
        logo = SimpleUploadedFile('logo.jpg', buf.read(), content_type='image/jpeg')
        r2 = self.client.post('/configuracion/?tab=tienda', {
            'form_kind': 'tienda', 'nombre_tienda': 'Mi Tienda',
            'telefono': '', 'direccion': '', 'logo': logo})
        self.assertEqual(r2.status_code, 302)
        self.assertTrue(bool(ConfiguracionTienda.get_solo().logo))

    def test_no_desactiva_unico_ni_con_stock(self):
        self.client.login(username='crud_admin', password='x12345')
        principal = Almacen.objects.get(es_principal=True)
        r = self.client.post(reverse('core:config_almacen_toggle', args=[principal.pk]))
        self.assertEqual(r.status_code, 302)
        principal.refresh_from_db()
        self.assertTrue(principal.activo)
        # Con 2 almacenes, con stock no desactiva.
        a2 = Almacen.objects.create(nombre='Secundario 2')
        prod = Producto.objects.create(
            nombre='Azucar', unidad_medida='unidades',
            precio_compra=5, precio_venta=10, stock=Decimal('0'))
        AlmacenStock.objects.create(producto=prod, almacen=a2, cantidad=Decimal('3'))
        self.client.post(reverse('core:config_almacen_toggle', args=[a2.pk]))
        a2.refresh_from_db()
        self.assertTrue(a2.activo)
