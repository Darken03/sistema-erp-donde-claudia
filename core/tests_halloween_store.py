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

    def test_pagina_padre_lista_hijas_y_sus_productos(self):
        padre = Categoria.objects.create(nombre='PadreL')
        hija = Categoria.objects.create(nombre='HijaL', padre=padre)
        Producto.objects.create(nombre='ProdL', unidad_medida='unidades',
            precio_compra=1, precio_venta=7, stock=Decimal('2'), categoria=hija)
        html = self.client.get(reverse('core:store_categoria', args=[padre.pk])).content.decode()
        # Cards de hijas + selector lateral + productos de las hijas.
        self.assertIn('HijaL', html)
        self.assertIn(f'/store/categoria/{hija.pk}/', html)
        self.assertIn('cat-side', html)
        self.assertIn('ProdL', html)
        self.assertIn('<article', html)

    def test_pagina_padre_muestra_directos_y_de_hijas(self):
        padre = Categoria.objects.create(nombre='PadreD')
        hija = Categoria.objects.create(nombre='HijaD', padre=padre)
        Producto.objects.create(nombre='DirectoD', unidad_medida='unidades',
            precio_compra=1, precio_venta=7, stock=Decimal('2'), categoria=padre)
        Producto.objects.create(nombre='DeHijaD', unidad_medida='unidades',
            precio_compra=1, precio_venta=8, stock=Decimal('2'), categoria=hija)
        html = self.client.get(reverse('core:store_categoria', args=[padre.pk])).content.decode()
        self.assertIn('DirectoD', html)
        self.assertIn('DeHijaD', html)

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

    def test_lateral_sin_titulo_mas_de(self):
        padre = Categoria.objects.create(nombre='PadreT')
        beta = Categoria.objects.create(nombre='BetaT', padre=padre)
        html = self.client.get(reverse('core:store_categoria', args=[beta.pk])).content.decode()
        self.assertNotIn('Más de', html)
        self.assertNotIn('lateral_titulo', html)
        self.assertIn('cat-side', html)
        self.assertIn(f'/store/categoria/{padre.pk}/', html)

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

    def test_dropdown_agrupa_hijas_en_flyout_como_pos(self):
        padre = Categoria.objects.create(nombre='PadreF', icono='🎃')
        hija = Categoria.objects.create(nombre='HijaF', padre=padre)
        Producto.objects.create(nombre='ProdF', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=hija)
        html = self.client.get(reverse('core:store')).content.decode()
        # Flyout lateral estilo POS con la hija dentro, no mezclada en plano.
        self.assertIn('nav-dd-sub', html)
        self.assertIn(f'/store/categoria/{hija.pk}/', html)
        self.assertIn('🎃', html)
        # Bootstrap Icons cargado para los chevrones.
        self.assertIn('bootstrap-icons', html)

    def test_dropdown_anida_tres_niveles(self):
        abuelo = Categoria.objects.create(nombre='AbueloN')
        padre = Categoria.objects.create(nombre='PadreN', padre=abuelo)
        hija = Categoria.objects.create(nombre='HijaN', padre=padre)
        Producto.objects.create(nombre='ProdN', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=hija)
        html = self.client.get(reverse('core:store')).content.decode()
        for cat in (abuelo, padre, hija):
            self.assertIn(f'/store/categoria/{cat.pk}/', html)
        # Dos flyouts anidados: hijas del abuelo y de la padre.
        self.assertGreaterEqual(html.count('nav-dd-sub'), 2)

    def test_drawer_movil_con_toggle_distinto(self):
        padre = Categoria.objects.create(nombre='PadreM', icono='🎃')
        hija = Categoria.objects.create(nombre='HijaM', padre=padre)
        Producto.objects.create(nombre='ProdM', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=hija)
        for url in (reverse('core:store'),
                    reverse('core:store_categoria', args=[padre.pk])):
            html = self.client.get(url).content.decode()
            # Menú lateral móvil con todas las categorías y toggle
            # plegable de color distinto para las hijas.
            self.assertIn('id="navCatDrawer"', html)
            self.assertIn('nav-m-toggle', html)
            self.assertIn('🎃', html)
            self.assertIn(f'/store/categoria/{padre.pk}/', html)
            self.assertIn(f'/store/categoria/{hija.pk}/', html)

    def test_vistas_store_responsive_movil(self):
        cat = Categoria.objects.create(nombre='Resp')
        Producto.objects.create(nombre='ProdResp', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=cat)
        for url in (reverse('core:store'),
                    reverse('core:store_buscar'),
                    reverse('core:store_categoria', args=[cat.pk])):
            html = self.client.get(url).content.decode()
            # Breakpoints móvil/tablet + drawer + viewport en las 3 vistas.
            self.assertIn('name="viewport"', html)
            self.assertIn('max-width:1024px', html)
            self.assertIn('max-width:480px', html)
            self.assertIn('nav-m-drawer', html)
            # En móvil chico se libera espacio: sin guirnalda ni contador.
            self.assertIn('.hwn-garland{display:none', html)
            self.assertIn('.ml-nav .count{display:none', html)

    def test_pagina_categoria_responsive_tablet_movil(self):
        padre = Categoria.objects.create(nombre='PadreR')
        hija = Categoria.objects.create(nombre='HijaR', padre=padre)
        Producto.objects.create(nombre='ProdR', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'), categoria=hija)
        html = self.client.get(
            reverse('core:store_categoria', args=[padre.pk])).content.decode()
        # En tablet el lateral se apila arriba (chips horizontales).
        self.assertIn('.cat-layout{grid-template-columns:1fr', html)
        # En móvil las cards se compactan.
        self.assertIn('.product-card .img-zone{height:84px', html)
        self.assertIn('.product-card .stockrow{flex-wrap:wrap', html)

    def test_grid_sin_desborde_horizontal(self):
        # Los items del grid y la columna principal necesitan min-width:0;
        # si no, nombres/SKU largos estiran la columna y la página
        # desborda en móvil.
        cat = Categoria.objects.create(nombre='Ancho')
        Producto.objects.create(
            nombre='Producto con nombre larguisimo para probar desborde',
            unidad_medida='unidades', precio_compra=1, precio_venta=5,
            stock=Decimal('3'), categoria=cat)
        for url in (reverse('core:store_categoria', args=[cat.pk]),
                    reverse('core:store_buscar')):
            html = self.client.get(url).content.decode()
            self.assertIn('.product-card{min-width:0', html)
        html = self.client.get(
            reverse('core:store_categoria', args=[cat.pk])).content.decode()
        self.assertIn('.cat-main{min-width:0', html)

    def test_grid_movil_maximo_dos_columnas(self):
        # En móvil los grids son explícitamente de 2 columnas compactas
        # (productos e hijas): nada a 1 columna gigante.
        cat = Categoria.objects.create(nombre='DosCol')
        hija = Categoria.objects.create(nombre='HijaCol', padre=cat)
        for url in (reverse('core:store_categoria', args=[cat.pk]),
                    reverse('core:store_categoria', args=[hija.pk]),
                    reverse('core:store_buscar')):
            html = self.client.get(url).content.decode()
            self.assertIn('.grid{grid-template-columns:repeat(2,minmax(0,1fr))', html)
        html = self.client.get(
            reverse('core:store_categoria', args=[cat.pk])).content.decode()
        self.assertIn('.kid-grid{grid-template-columns:repeat(2,minmax(0,1fr))', html)

    def test_cards_muestran_badge_nuevo_solo_recientes(self):
        from django.utils import timezone
        from datetime import timedelta
        cat = Categoria.objects.create(nombre='CatNuevo')
        Producto.objects.create(
            nombre='ProdNuevo', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'),
            categoria=cat)
        viejo = Producto.objects.create(
            nombre='ProdViejo', unidad_medida='unidades',
            precio_compra=1, precio_venta=6, stock=Decimal('4'),
            categoria=cat)
        Producto.objects.filter(pk=viejo.pk).update(
            fecha_creacion=timezone.now() - timedelta(days=60))
        html = self.client.get(
            reverse('core:store_categoria', args=[cat.pk])).content.decode()
        # Nombre a 2 líneas y solo el reciente lleva NUEVO.
        self.assertIn('clamp-2', html)
        self.assertEqual(html.count('<span class="nuevo-badge">NUEVO</span>'), 1)

    def test_pos_buscar_incluye_es_nuevo(self):
        from django.utils import timezone
        from datetime import timedelta
        u = _admin('esnuevo_admin')
        self.client.force_login(u)
        cat = Categoria.objects.create(nombre='CatEN')
        fresco = Producto.objects.create(
            nombre='FrescoEN', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('3'),
            categoria=cat)
        viejo = Producto.objects.create(
            nombre='ViejoEN', unidad_medida='unidades',
            precio_compra=1, precio_venta=6, stock=Decimal('4'),
            categoria=cat)
        Producto.objects.filter(pk=viejo.pk).update(
            fecha_creacion=timezone.now() - timedelta(days=60))
        r = self.client.post(
            reverse('core:pos_buscar'), {'q': '', 'categoria': str(cat.pk)})
        self.assertEqual(r.status_code, 200)
        data = {p['id']: p for p in r.json()['productos']}
        self.assertTrue(data[fresco.pk]['es_nuevo'])
        self.assertFalse(data[viejo.pk]['es_nuevo'])

    def test_imagenes_relleno_uniforme_como_pos(self):
        # Las fotos se ven completas (contain) en zona cuadrada 1:1,
        # uniformes como en el POS tras el encuadre del editor.
        cat = Categoria.objects.create(nombre='Foto')
        for url in (reverse('core:store'),
                    reverse('core:store_categoria', args=[cat.pk]),
                    reverse('core:store_buscar')):
            html = self.client.get(url).content.decode()
            self.assertIn('object-fit:contain', html)

    def test_header_flexible_sin_aplaste(self):
        # El buscador y la marca deben ceder (min-width:0 + ellipsis),
        # como el header del panel admin: nada se aplasta en móvil.
        cat = Categoria.objects.create(nombre='Head')
        for url in (reverse('core:store'),
                    reverse('core:store_buscar'),
                    reverse('core:store_categoria', args=[cat.pk])):
            html = self.client.get(url).content.decode()
            self.assertIn('.ml-search input{min-width:0', html)
            self.assertIn('.ml-brand .t1,.ml-brand .t2{overflow:hidden', html)

    def test_nav_movil_en_una_sola_linea(self):
        # En móvil Solo disponibles va a continuación del selector,
        # sin saltar de línea: nav compacto con scroll lateral.
        cat = Categoria.objects.create(nombre='Nav1')
        for url in (reverse('core:store'),
                    reverse('core:store_buscar'),
                    reverse('core:store_categoria', args=[cat.pk])):
            html = self.client.get(url).content.decode()
            self.assertIn('.ml-nav-inner{flex-wrap:nowrap', html)
            self.assertIn('.ml-nav a,.nav-m-btn{padding:9px 8px', html)

    def test_logo_webp_existe(self):
        # El header referencia logo-donde-clau.webp: debe existir para
        # no devolver 404 en consola.
        from django.contrib.staticfiles import finders
        self.assertIsNotNone(finders.find('img/logo-donde-clau.webp'))


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


class StoreProductoModalTest(TestCase):
    def setUp(self):
        from .models import PresentacionProducto
        self.cat = Categoria.objects.create(nombre='CatModal')
        self.prod = Producto.objects.create(
            nombre='ProdModal', descripcion='Descripción rica del producto',
            unidad_medida='unidades', precio_compra=10, precio_venta=25,
            stock=Decimal('7'), categoria=self.cat)
        PresentacionProducto.objects.create(
            producto=self.prod, nombre='Unidad', factor=1,
            precio=25, es_default=True)

    def test_api_detalle_producto(self):
        r = self.client.get(reverse('core:store_producto_api', args=[self.prod.pk]))
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertEqual(d['nombre'], 'ProdModal')
        self.assertEqual(d['descripcion'], 'Descripción rica del producto')
        self.assertEqual(d['precio'], '25.00')
        self.assertIn('Unidad', str(d['presentaciones']))
        # Nunca expone costos ni mínimos.
        payload = str(d)
        self.assertNotIn('precio_compra', payload)
        self.assertNotIn('stock_minimo', payload)
        self.assertNotIn('proveedor', payload)

    def test_api_404_oculto_e_inexistente(self):
        oculta = Categoria.objects.create(nombre='OcultaM', visible_store=False)
        fantasma = Producto.objects.create(
            nombre='FantasmaM', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('9'),
            categoria=oculta)
        self.assertEqual(
            self.client.get(reverse('core:store_producto_api', args=[fantasma.pk])).status_code, 404)
        self.assertEqual(
            self.client.get(reverse('core:store_producto_api', args=[999999])).status_code, 404)

    def test_api_solo_get(self):
        r = self.client.post(reverse('core:store_producto_api', args=[self.prod.pk]))
        self.assertEqual(r.status_code, 405)

    def test_paginas_traen_modal_y_cards_clicables(self):
        for url in (reverse('core:store'),
                    reverse('core:store_buscar'),
                    reverse('core:store_categoria', args=[self.cat.pk])):
            html = self.client.get(url).content.decode()
            self.assertIn('id="prodModal"', html)
            self.assertIn('data-prod=', html)

    def test_modal_sin_enlace_ver_categoria(self):
        for url in (reverse('core:store'),
                    reverse('core:store_buscar'),
                    reverse('core:store_categoria', args=[self.cat.pk])):
            html = self.client.get(url).content.decode()
            self.assertNotIn('id="prodModalCatLink"', html)

    def test_modal_reinicia_imagen_al_abrir(self):
        # Regresión: al reabrir, el reset no depende del span de
        # iniciales (desaparece cuando el producto anterior tenía
        # foto); el wrap siempre vuelve a su esqueleto.
        html = self.client.get(reverse('core:store')).content.decode()
        self.assertIn('prodModalImgWrap', html)
        self.assertNotIn("$('prodModalInitials').textContent", html)
