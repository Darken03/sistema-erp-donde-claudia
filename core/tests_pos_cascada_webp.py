import io
import os
import shutil
import tempfile
from decimal import Decimal

from django.test import TestCase, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from .models import Producto, Categoria, PerfilUsuario, Empleado, Turno


def _usuario(username, rol='admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


def _jpeg_bytes(color='red'):
    buf = io.BytesIO()
    Image.new('RGB', (60, 40), color).save(buf, format='JPEG')
    buf.seek(0)
    return buf.read()


class IconoCategoriaTest(TestCase):
    def setUp(self):
        _usuario('ico_admin', 'admin')
        self.client.login(username='ico_admin', password='x12345')

    def test_form_guarda_icono_emoji(self):
        r = self.client.post(reverse('core:categoria_crear'), {
            'nombre': 'Frutas', 'descripcion': '', 'padre': '',
            'visible_store': 'on', 'icono': '🍎'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(Categoria.objects.get(nombre='Frutas').icono, '🍎')

    def test_pos_muestra_icono_y_submenu_en_cascada(self):
        cajero = _usuario('ico_cajero', 'cajero')
        empleado = Empleado.objects.create(user=cajero, salario=0, activo=True)
        Turno.objects.create(empleado=empleado, abierto=True)
        padre = Categoria.objects.create(nombre='PadreIco', icono='🎃')
        hija = Categoria.objects.create(nombre='HijaIco', padre=padre, icono='🍬')
        Producto.objects.create(
            nombre='ProdIco', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('4'),
            categoria=hija)
        self.client.login(username='ico_cajero', password='x12345')
        r = self.client.get(reverse('core:pos'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('🎃', html)
        self.assertIn('cat-sub', html)
        self.assertIn('HijaIco', html)


class WebpConfigTest(TestCase):
    def setUp(self):
        _usuario('webp_admin', 'admin')
        self.client.login(username='webp_admin', password='x12345')
        self.tmp = tempfile.mkdtemp(prefix='bizm_webp_')
        self._ov = override_settings(MEDIA_ROOT=self.tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _producto_con_jpeg(self, nombre='ProdWebp'):
        return Producto.objects.create(
            nombre=nombre, unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('2'),
            imagen=SimpleUploadedFile(
                'foto.jpg', _jpeg_bytes(), content_type='image/jpeg'))

    def test_boton_convierte_jpg_a_webp_y_borra_original(self):
        p = self._producto_con_jpeg()
        vieja = p.imagen.path
        self.assertTrue(os.path.exists(vieja))
        r = self.client.post('/configuracion/?tab=tienda', {'form_kind': 'convertir_webp'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.imagen.name.endswith('.webp'), p.imagen.name)
        self.assertTrue(os.path.exists(p.imagen.path))
        self.assertFalse(os.path.exists(vieja))

    def test_no_reconvierte_lo_ya_webp(self):
        p = self._producto_con_jpeg()
        self.client.post('/configuracion/?tab=tienda', {'form_kind': 'convertir_webp'})
        p.refresh_from_db()
        nombre_webp = p.imagen.name
        r = self.client.post('/configuracion/?tab=tienda', {'form_kind': 'convertir_webp'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.imagen.name, nombre_webp)
