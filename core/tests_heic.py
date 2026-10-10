import io
from django.test import TestCase
from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image

from .forms import ProductoForm


def _make_heic_bytes(size=(200, 200), color='red'):
    """Genera bytes HEIC reales usando pillow-heif."""
    from pillow_heif import register_heif_opener
    register_heif_opener()
    img = Image.new('RGB', size, color=color)
    buf = io.BytesIO()
    img.save(buf, format='HEIF')
    return buf.getvalue()


class ProductoHeicTest(TestCase):
    def test_form_acepta_heic_y_lo_convierte_a_jpeg(self):
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
            imagen_limpia.name.lower().endswith(('.jpg', '.jpeg')),
            f"La imagen convertida deberia ser .jpg, fue: {imagen_limpia.name}",
        )
        # Debe ser un JPEG valido abrible por Pillow
        imagen_limpia.seek(0)
        img = Image.open(imagen_limpia)
        img.verify()
