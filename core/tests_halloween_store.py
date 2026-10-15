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


class StoreCategoriaPaginaTest(TestCase):
    def test_pagina_categoria_muestra_solo_sus_productos(self):
        cat_a = Categoria.objects.create(nombre='CatA')
        cat_b = Categoria.objects.create(nombre='CatB')
        Producto.objects.create(nombre='ProdA', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=cat_a)
        Producto.objects.create(nombre='ProdB', unidad_medida='unidades',
            precio_compra=1, precio_venta=6, stock=Decimal('4'), categoria=cat_b)
        r = self.client.get(reverse('core:store_categoria', args=[cat_a.pk]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('ProdA', html)
        self.assertNotIn('ProdB', html)
        self.assertIn('data-id=', html)

    def test_pagina_categoria_incluye_productos_de_hijas(self):
        padre = Categoria.objects.create(nombre='PadreX')
        hija = Categoria.objects.create(nombre='HijaX', padre=padre)
        Producto.objects.create(nombre='ProdHija', unidad_medida='unidades',
            precio_compra=1, precio_venta=7, stock=Decimal('2'), categoria=hija)
        r = self.client.get(reverse('core:store_categoria', args=[padre.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('ProdHija', r.content.decode())

    def test_pagina_categoria_oculta_da_404(self):
        oculta = Categoria.objects.create(nombre='OcultaX', visible_store=False)
        Producto.objects.create(nombre='FantasmaX', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('9'), categoria=oculta)
        r = self.client.get(reverse('core:store_categoria', args=[oculta.pk]))
        self.assertEqual(r.status_code, 404)

    def test_header_sin_anclas_con_selector_a_paginas(self):
        cat = Categoria.objects.create(nombre='NavCat')
        Producto.objects.create(nombre='NavProd', unidad_medida='unidades',
            precio_compra=1, precio_venta=3, stock=Decimal('1'), categoria=cat)
        html = self.client.get(reverse('core:store')).content.decode()
        self.assertNotIn('href="#catalogo"', html)
        self.assertNotIn('href="#categorias"', html)
        self.assertIn('id="navCatSel"', html)
        self.assertIn(f'/store/categoria/{cat.pk}/', html)

    def test_store_solo_param_premarca_filtro(self):
        html = self.client.get(reverse('core:store') + '?solo=1').content.decode()
        self.assertIn('id="solo" checked', html)
