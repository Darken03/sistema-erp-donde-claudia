from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from .models import Producto, Categoria, PerfilUsuario


def _admin(username='hwn_admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol='admin')
    return u


class StoreHalloweenAlgomioTest(TestCase):
    def test_store_trae_colores_halloween_pos(self):
        r = self.client.get(reverse('core:store'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('#e8641b', html)
        self.assertIn('#7c3aed', html)

    def test_store_trae_secciones_estilo_algomio(self):
        Categoria.objects.create(nombre='Viveres')
        Producto.objects.create(nombre='Arroz', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('12'))
        r = self.client.get(reverse('core:store'))
        html = r.content.decode()
        self.assertIn('Tendencias del Momento', html)
        self.assertIn('Categorías Destacadas', html)
        self.assertIn('Nuestros felices clientes', html)
        # Hero + exploración (nombres adaptados a nuestra tienda)
        self.assertIn('Explorar', html)


class CategoriaArbolTest(TestCase):
    def setUp(self):
        _admin()
        self.client.login(username='hwn_admin', password='x12345')

    def test_lista_muestra_arbol_con_hijas(self):
        padre = Categoria.objects.create(nombre='Alimentos')
        Categoria.objects.create(nombre='Granos', padre=padre)
        r = self.client.get(reverse('core:categoria_lista'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Alimentos', html)
        self.assertIn('Granos', html)
        # Enlace para crear subcategoría desde el padre
        self.assertIn(f'?padre={padre.pk}', html)

    def test_crear_precarga_padre_desde_query(self):
        padre = Categoria.objects.create(nombre='PadreQ')
        r = self.client.get(reverse('core:categoria_crear') + f'?padre={padre.pk}')
        self.assertEqual(r.status_code, 200)
        # El select de padre debe traer preseleccionado al padre
        self.assertIn(f'value="{padre.pk}" selected', r.content.decode())
