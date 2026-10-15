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
        self.assertNotIn('Nuestros felices clientes', html)
        # Hero + exploración (nombres adaptados a nuestra tienda)
        self.assertIn('Explorar', html)

    def test_landing_sin_catalogo_por_categoria(self):
        cat = Categoria.objects.create(nombre='CatLand')
        Producto.objects.create(nombre='ProdLand', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=cat)
        html = self.client.get(reverse('core:store')).content.decode()
        # El listado completo por categoría vive en las páginas por
        # categoría y en el buscador; el landing solo muestra portada.
        self.assertNotIn('cat-sec', html)
        self.assertNotIn('id="catalogo"', html)
        self.assertNotIn('id="categorias"', html)
        self.assertIn('Tendencias del Momento', html)


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
        # La página de la hija muestra sus productos.
        r = self.client.get(reverse('core:store_categoria', args=[hija.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('ProdHija', r.content.decode())

    def test_pagina_padre_lista_hijas_y_no_vuelca_productos(self):
        padre = Categoria.objects.create(nombre='PadreL')
        hija = Categoria.objects.create(nombre='HijaL', padre=padre)
        Producto.objects.create(nombre='ProdL', unidad_medida='unidades',
            precio_compra=1, precio_venta=7, stock=Decimal('2'), categoria=hija)
        html = self.client.get(reverse('core:store_categoria', args=[padre.pk])).content.decode()
        # Cards de hijas + selector lateral, sin tarjetas de producto.
        self.assertIn('HijaL', html)
        self.assertIn(f'/store/categoria/{hija.pk}/', html)
        self.assertIn('cat-side', html)
        self.assertNotIn('ProdL', html)
        self.assertNotIn('<article', html)

    def test_pagina_padre_muestra_sus_productos_directos(self):
        padre = Categoria.objects.create(nombre='PadreD')
        hija = Categoria.objects.create(nombre='HijaD', padre=padre)
        Producto.objects.create(nombre='DirectoD', unidad_medida='unidades',
            precio_compra=1, precio_venta=7, stock=Decimal('2'), categoria=padre)
        Producto.objects.create(nombre='DeHijaD', unidad_medida='unidades',
            precio_compra=1, precio_venta=8, stock=Decimal('2'), categoria=hija)
        html = self.client.get(reverse('core:store_categoria', args=[padre.pk])).content.decode()
        self.assertIn('DirectoD', html)
        self.assertNotIn('DeHijaD', html)

    def test_pagina_hoja_con_lateral_de_hermanas(self):
        padre = Categoria.objects.create(nombre='PadreH')
        alfa = Categoria.objects.create(nombre='AlfaH', padre=padre)
        beta = Categoria.objects.create(nombre='BetaH', padre=padre)
        Producto.objects.create(nombre='ProdBeta', unidad_medida='unidades',
            precio_compra=1, precio_venta=7, stock=Decimal('2'), categoria=beta)
        html = self.client.get(reverse('core:store_categoria', args=[beta.pk])).content.decode()
        self.assertIn('ProdBeta', html)
        self.assertIn('cat-side', html)
        self.assertIn('AlfaH', html)
        self.assertIn(f'/store/categoria/{alfa.pk}/', html)

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

    def test_panel_selector_no_queda_recortado(self):
        # El contenedor del nav no debe recortar el panel desplegable.
        cat = Categoria.objects.create(nombre='Recorte')
        Producto.objects.create(nombre='ProdRec', unidad_medida='unidades',
            precio_compra=1, precio_venta=3, stock=Decimal('1'), categoria=cat)
        for url in (reverse('core:store'), reverse('core:store_buscar'),
                    reverse('core:store_categoria', args=[cat.pk])):
            html = self.client.get(url).content.decode()
            self.assertNotRegex(html, r'\.ml-nav-inner \{[^}]*overflow-x')


class StoreBuscarTest(TestCase):
    def test_buscar_filtra_por_texto(self):
        cat = Categoria.objects.create(nombre='CatB')
        Producto.objects.create(nombre='ProdBuscado', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=cat)
        Producto.objects.create(nombre='OtroCosa', unidad_medida='unidades',
            precio_compra=1, precio_venta=6, stock=Decimal('4'), categoria=cat)
        r = self.client.get(reverse('core:store_buscar') + '?q=buscado')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'ProdBuscado')
        self.assertNotContains(r, 'OtroCosa')

    def test_buscar_solo_disponibles(self):
        cat = Categoria.objects.create(nombre='CatS')
        Producto.objects.create(nombre='ConStock', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=cat)
        Producto.objects.create(nombre='AgotadoX', unidad_medida='unidades',
            precio_compra=1, precio_venta=6, stock=Decimal('0'), categoria=cat)
        html = self.client.get(reverse('core:store_buscar') + '?solo=1').content.decode()
        self.assertIn('ConStock', html)
        self.assertNotIn('AgotadoX', html)

    def test_buscar_sin_resultados_muestra_aviso(self):
        html = self.client.get(reverse('core:store_buscar') + '?q=zzzznada').content.decode()
        self.assertEqual(self.client.get(reverse('core:store_buscar') + '?q=zzzznada').status_code, 200)
        self.assertIn('Sin resultados', html)
