import io
import os
import shutil
import tempfile
from datetime import timedelta
from django.test import TestCase, override_settings
from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .forms import ProductoForm
from .models import Producto, Categoria, PerfilUsuario


from decimal import Decimal


def _make_heic_bytes(size=(200, 200), color='red'):
    """Genera bytes HEIC reales usando pillow-heif."""
    from pillow_heif import register_heif_opener
    register_heif_opener()
    img = Image.new('RGB', size, color=color)
    buf = io.BytesIO()
    img.save(buf, format='HEIF')
    return buf.getvalue()


def _make_image_bytes(fmt='JPEG', size=(400, 300), color='blue'):
    buf = io.BytesIO()
    Image.new('RGB', size, color=color).save(buf, format=fmt)
    buf.seek(0)
    return buf.read()


class ProductoHeicTest(TestCase):
    def test_form_acepta_heic_y_lo_convierte_a_webp(self):
        heic_bytes = _make_heic_bytes()
        heic_file = SimpleUploadedFile(
            'foto.heic', heic_bytes, content_type='image/heic'
        )
        form = ProductoForm(
            data={
                'nombre': 'Producto HEIC',
                'precio_compra': '10',
                'precio_venta': '20',
                'stock': '5',
                'stock_minimo': '1',
                'unidad_medida': 'unidades',
            },
            files={'imagen': heic_file},
        )
        self.assertTrue(
            form.is_valid(), f"El form deberia aceptar .heic, errores: {form.errors}"
        )
        imagen_limpia = form.cleaned_data['imagen']
        self.assertTrue(
            imagen_limpia.name.lower().endswith('.webp'),
            f"La imagen convertida deberia ser .webp, fue: {imagen_limpia.name}",
        )
        # Debe ser un WebP valido abrible por Pillow
        imagen_limpia.seek(0)
        img = Image.open(imagen_limpia)
        self.assertEqual(img.format, 'WEBP')
        img.verify()


class ProductoWebpUploadTest(TestCase):
    """Al subir una imagen en cualquier formato se guarda como WebP."""

    def _form_con(self, nombre_archivo, contenido, content_type):
        return ProductoForm(
            data={
                'nombre': 'Prod WebP', 'precio_compra': '10',
                'precio_venta': '20', 'stock': '5', 'stock_minimo': '1',
                'unidad_medida': 'unidades',
            },
            files={'imagen': SimpleUploadedFile(
                nombre_archivo, contenido, content_type=content_type)},
        )

    def test_form_convierte_jpg_a_webp(self):
        form = self._form_con(
            'foto.jpg', _make_image_bytes('JPEG'), 'image/jpeg')
        self.assertTrue(form.is_valid(), form.errors)
        limpia = form.cleaned_data['imagen']
        self.assertTrue(limpia.name.lower().endswith('.webp'), limpia.name)
        limpia.seek(0)
        self.assertEqual(Image.open(limpia).format, 'WEBP')

    def test_form_convierte_png_a_webp(self):
        form = self._form_con(
            'foto.png', _make_image_bytes('PNG'), 'image/png')
        self.assertTrue(form.is_valid(), form.errors)
        limpia = form.cleaned_data['imagen']
        self.assertTrue(limpia.name.lower().endswith('.webp'), limpia.name)
        limpia.seek(0)
        self.assertEqual(Image.open(limpia).format, 'WEBP')

    def test_form_deja_webp_intacto(self):
        buf = io.BytesIO()
        Image.new('RGB', (120, 120), color='green').save(buf, format='WEBP')
        buf.seek(0)
        form = self._form_con('foto.webp', buf.read(), 'image/webp')
        self.assertTrue(form.is_valid(), form.errors)
        limpia = form.cleaned_data['imagen']
        self.assertTrue(limpia.name.lower().endswith('.webp'), limpia.name)

    def test_heic_termina_en_webp(self):
        form = self._form_con(
            'foto.heic', _make_heic_bytes(), 'image/heic')
        self.assertTrue(form.is_valid(), form.errors)
        limpia = form.cleaned_data['imagen']
        self.assertTrue(limpia.name.lower().endswith('.webp'), limpia.name)
        limpia.seek(0)
        self.assertEqual(Image.open(limpia).format, 'WEBP')


class ProductoRecorteTest(TestCase):
    """Recorte cuadrado de la imagen del producto (termina en WebP)."""

    def setUp(self):
        from django.contrib.auth.models import User
        u = User.objects.create_user(username='recorte_admin', password='x12345')
        PerfilUsuario.objects.filter(user=u).update(rol='admin')
        u.refresh_from_db()
        self.client.login(username='recorte_admin', password='x12345')
        self.tmp = tempfile.mkdtemp(prefix='bizm_crop_')
        self._ov = override_settings(MEDIA_ROOT=self.tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _producto_con_imagen(self, w=400, h=300, nombre='foto.png'):
        return Producto.objects.create(
            nombre='Prod Recorte', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('1'),
            imagen=SimpleUploadedFile(
                nombre, _make_image_bytes('PNG', (w, h)),
                content_type='image/png'))

    def test_get_muestra_recortador(self):
        p = self._producto_con_imagen()
        r = self.client.get(
            reverse('core:producto_imagen_recortar', args=[p.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'cropViewport')
        self.assertContains(r, 'ratioBar')
        self.assertContains(r, 'Libre')
        self.assertContains(r, 'cropHandleE')
        self.assertContains(r, 'cropHandleS')

    def test_post_recorta_y_convierte_a_webp(self):
        p = self._producto_con_imagen(400, 300)
        vieja = p.imagen.path
        self.assertTrue(os.path.exists(vieja))
        r = self.client.post(
            reverse('core:producto_imagen_recortar', args=[p.pk]),
            {'x': '50', 'y': '40', 'w': '100', 'h': '100'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.imagen.name.lower().endswith('.webp'), p.imagen.name)
        img = Image.open(p.imagen.path)
        self.assertEqual(img.size, (100, 100))
        self.assertFalse(os.path.exists(vieja))

    def test_post_recorte_webp_cambia_url_para_store(self):
        # Regresión: recortar un .webp no debe sobrescribir la misma URL
        # (el navegador cacheaba la anterior y la Store seguía vieja).
        p = self._producto_con_imagen(400, 300, nombre='foto.webp')
        nombre_antes = p.imagen.name
        r = self.client.post(
            reverse('core:producto_imagen_recortar', args=[p.pk]),
            {'x': '50', 'y': '40', 'w': '100', 'h': '100'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.imagen.name.lower().endswith('.webp'), p.imagen.name)
        self.assertNotEqual(p.imagen.name, nombre_antes)
        self.assertIn('_r', p.imagen.name)
        # La Store debe exponer la nueva URL, no la anterior.
        from .views import _store_items
        imagenes = [it['imagen'] for it in _store_items() if it['id'] == p.pk]
        self.assertTrue(imagenes)
        self.assertIn(p.imagen.url, imagenes[0])

    def test_post_recorta_rectangular_ancho_alto_independientes(self):
        # Proporciones libres: w y h independientes (ej. 4:3 -> 120x90).
        p = self._producto_con_imagen(400, 300)
        r = self.client.post(
            reverse('core:producto_imagen_recortar', args=[p.pk]),
            {'x': '10', 'y': '10', 'w': '120', 'h': '90'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.imagen.name.lower().endswith('.webp'), p.imagen.name)
        img = Image.open(p.imagen.path)
        self.assertEqual(img.size, (120, 90))

    def test_post_coordenadas_invalidas_no_rompe(self):
        p = self._producto_con_imagen()
        nombre_antes = p.imagen.name
        r = self.client.post(
            reverse('core:producto_imagen_recortar', args=[p.pk]),
            {'x': '0', 'y': '0', 'w': '0', 'h': '0'})
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertEqual(p.imagen.name, nombre_antes)

    def test_get_sin_imagen_redirige_al_detalle(self):
        p = Producto.objects.create(
            nombre='Sin Foto', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('1'))
        r = self.client.get(
            reverse('core:producto_imagen_recortar', args=[p.pk]))
        self.assertEqual(r.status_code, 302)


class ProductoImagenArchivoTest(TestCase):
    """Al cambiar la imagen se borra la anterior; al eliminarla se borra el archivo."""

    def setUp(self):
        u = User.objects.create_user(username='img_admin', password='x12345')
        PerfilUsuario.objects.filter(user=u).update(rol='admin')
        u.refresh_from_db()
        self.client.login(username='img_admin', password='x12345')
        self.tmp = tempfile.mkdtemp(prefix='bizm_img_')
        self._ov = override_settings(MEDIA_ROOT=self.tmp)
        self._ov.enable()
        self.addCleanup(self._ov.disable)
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _producto_con_imagen(self, nombre='vieja.png'):
        return Producto.objects.create(
            nombre='Prod Img', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('1'),
            imagen=SimpleUploadedFile(
                nombre, _make_image_bytes('PNG', (200, 200)),
                content_type='image/png'))

    def _post_editar_con_imagen(self, p, archivo, content_type):
        return self.client.post(
            reverse('core:producto_editar', args=[p.pk]),
            {
                'nombre': p.nombre, 'descripcion': '', 'categoria': '',
                'unidad_medida': 'unidades', 'precio_compra': '1',
                'precio_venta': '2', 'stock_minimo': '0', 'activo': 'on',
                'presentaciones-TOTAL_FORMS': '0',
                'presentaciones-INITIAL_FORMS': '0',
                'presentaciones-MIN_NUM_FORMS': '0',
                'presentaciones-MAX_NUM_FORMS': '1000',
                'imagen': SimpleUploadedFile(
                    archivo, _make_image_bytes('JPEG', (300, 300)),
                    content_type=content_type),
            })

    def test_editar_cambia_imagen_borra_anterior(self):
        p = self._producto_con_imagen()
        vieja_path = p.imagen.path
        self.assertTrue(os.path.exists(vieja_path))
        r = self._post_editar_con_imagen(p, 'nueva.jpg', 'image/jpeg')
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.imagen)
        self.assertTrue(os.path.exists(p.imagen.path))
        self.assertFalse(os.path.exists(vieja_path))

    def test_eliminar_imagen_borra_archivo(self):
        p = self._producto_con_imagen()
        ruta = p.imagen.path
        self.assertTrue(os.path.exists(ruta))
        r = self.client.post(
            reverse('core:producto_imagen_eliminar', args=[p.pk]))
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertFalse(bool(p.imagen))
        self.assertFalse(os.path.exists(ruta))
