from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from .models import (
    Producto, Categoria, Almacen, AlmacenStock, ConfiguracionTienda,
    PresentacionProducto,
)


class StoreTest(TestCase):
    def test_store_publico_sin_login_muestra_stock_exacto(self):
        Categoria.objects.create(nombre='Viveres')
        Producto.objects.create(nombre='Arroz', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('12'))
        Producto.objects.create(nombre='OcultoNoVisible', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('9'), visible_pos=False)
        Producto.objects.create(nombre='OcultoInactivo', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('9'), activo=False)
        r = self.client.get(reverse('core:store'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Arroz')
        self.assertContains(r, '$20')
        self.assertContains(r, '12')
        self.assertNotContains(r, 'OcultoNoVisible')
        self.assertNotContains(r, 'OcultoInactivo')

    def test_store_api_no_expone_costos(self):
        Producto.objects.create(nombre='Frijol', unidad_medida='unidades',
            precio_compra=99, precio_venta=20, stock=Decimal('5'))
        r = self.client.get(reverse('core:store_api'))
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertIn('productos', body)
        payload = str(body)
        self.assertNotIn('precio_compra', payload)
        self.assertNotIn('stock_minimo', payload)
        self.assertNotIn('proveedor', payload)

    def test_store_api_multi_pos_suma(self):
        cfg = ConfiguracionTienda.get_solo()
        cfg.modo_operacion = 'multi_pos'
        cfg.save(update_fields=['modo_operacion'])
        a1 = Almacen.objects.create(nombre='A1')
        a2 = Almacen.objects.create(nombre='A2')
        p = Producto.objects.create(nombre='Azucar', unidad_medida='unidades',
            precio_compra=5, precio_venta=10, stock=Decimal('0'))
        AlmacenStock.objects.create(producto=p, almacen=a1, cantidad=Decimal('5'))
        AlmacenStock.objects.create(producto=p, almacen=a2, cantidad=Decimal('7'))
        r = self.client.get(reverse('core:store_api'))
        item = [x for x in r.json()['productos'] if x['id'] == p.id][0]
        self.assertEqual(Decimal(item['stock']), Decimal('12'))

    def test_store_template_usa_tokens_admin(self):
        Producto.objects.create(nombre='SinFoto', unidad_medida='unidades',
            precio_compra=1, precio_venta=3, stock=Decimal('4'))
        r = self.client.get(reverse('core:store'))
        self.assertContains(r, '--accent')
        self.assertContains(r, 'data-id=')
        self.assertContains(r, 'Solo disponibles')
        self.assertContains(r, 'SinFoto')
        # Fallback sin imagen (iniciales mono, sin <img> roto).
        self.assertContains(r, 'noimg')

    def test_store_api_payload_para_polling(self):
        p = Producto.objects.create(nombre='Sal', unidad_medida='lb',
            precio_compra=1, precio_venta=10, stock=Decimal('3.5'))
        item = [x for x in self.client.get(reverse('core:store_api')).json()['productos'] if x['id'] == p.id][0]
        self.assertEqual(item['stock_fmt'], '3.5 (lb)')
        for k in ('id', 'precio', 'stock', 'stock_fmt', 'disponible', 'pocas'):
            self.assertIn(k, item)

    def test_store_api_multi_ignora_almacen_inactivo(self):
        cfg = ConfiguracionTienda.get_solo()
        cfg.modo_operacion = 'multi_pos'
        cfg.save(update_fields=['modo_operacion'])
        a_on = Almacen.objects.create(nombre='On')
        a_off = Almacen.objects.create(nombre='Off', activo=False)
        p = Producto.objects.create(nombre='Cafe', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('0'))
        AlmacenStock.objects.create(producto=p, almacen=a_on, cantidad=Decimal('5'))
        AlmacenStock.objects.create(producto=p, almacen=a_off, cantidad=Decimal('100'))
        item = [x for x in self.client.get(reverse('core:store_api')).json()['productos'] if x['id'] == p.id][0]
        self.assertEqual(Decimal(item['stock']), Decimal('5'))

    def test_store_api_multi_legacy_solo_sin_propias(self):
        cfg = ConfiguracionTienda.get_solo()
        cfg.modo_operacion = 'multi_pos'
        cfg.save(update_fields=['modo_operacion'])
        a = Almacen.objects.create(nombre='A')
        pa = Producto.objects.create(nombre='ConPropia', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('0'))
        AlmacenStock.objects.create(producto=pa, almacen=None, cantidad=Decimal('4'))
        AlmacenStock.objects.create(producto=pa, almacen=a, cantidad=Decimal('6'))
        pb = Producto.objects.create(nombre='SoloLegacy', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('0'))
        AlmacenStock.objects.create(producto=pb, almacen=None, cantidad=Decimal('4'))
        data = {x['id']: x for x in self.client.get(reverse('core:store_api')).json()['productos']}
        self.assertEqual(Decimal(data[pa.id]['stock']), Decimal('6'))
        self.assertEqual(Decimal(data[pb.id]['stock']), Decimal('4'))

    def test_store_api_multi_excluye_producto_inactivo(self):
        cfg = ConfiguracionTienda.get_solo()
        cfg.modo_operacion = 'multi_pos'
        cfg.save(update_fields=['modo_operacion'])
        a = Almacen.objects.create(nombre='A')
        p = Producto.objects.create(nombre='Baja', unidad_medida='unidades',
            precio_compra=1, precio_venta=5, stock=Decimal('0'), activo=False)
        AlmacenStock.objects.create(producto=p, almacen=a, cantidad=Decimal('9'))
        ids = [x['id'] for x in self.client.get(reverse('core:store_api')).json()['productos']]
        self.assertNotIn(p.id, ids)

    def test_store_api_sin_n_mas_1_presentaciones(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        for i in range(3):
            p = Producto.objects.create(nombre=f'Prod{i}', unidad_medida='unidades',
                precio_compra=1, precio_venta=5, stock=Decimal('7'))
            PresentacionProducto.objects.create(producto=p, nombre='Unidad', factor=1, precio=5, es_default=True)
            PresentacionProducto.objects.create(producto=p, nombre='Docena', factor=12, precio=55)
        with CaptureQueriesContext(connection) as ctx:
            r = self.client.get(reverse('core:store_api'))
            self.assertEqual(r.status_code, 200)
        pres_q = [q for q in ctx.captured_queries if 'presentacion' in q['sql'].lower()]
        self.assertLessEqual(len(pres_q), 1)

    def test_store_js_usa_url_absoluta_api(self):
        r = self.client.get(reverse('core:store'))
        self.assertContains(r, '/store/api/estado/')

    def test_store_header_marketplace(self):
        r = self.client.get(reverse('core:store'))
        self.assertContains(r, 'ml-header')
        self.assertContains(r, 'href="#categorias"')
        self.assertContains(r, 'href="#catalogo"')
        self.assertContains(r, 'id="q"')

    def test_store_categorias_visuales(self):
        cat = Categoria.objects.create(nombre='Viveres')
        Producto.objects.create(nombre='Arroz', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('12'), categoria=cat)
        r = self.client.get(reverse('core:store'))
        self.assertContains(r, 'id="categorias"')
        self.assertContains(r, 'cat-visual')
        self.assertContains(r, 'Viveres')

    def test_categoria_jerarquia_padre_hijas(self):
        padre = Categoria.objects.create(nombre='Alimentos')
        h1 = Categoria.objects.create(nombre='Granos', padre=padre)
        h2 = Categoria.objects.create(nombre='Pastas', padre=padre)
        self.assertEqual(set(padre.hijas.all()), {h1, h2})
        self.assertTrue(padre.visible_store)
        self.assertTrue(h1.visible_store)

    def test_categoria_no_permite_padre_propio(self):
        from django.core.exceptions import ValidationError
        c = Categoria.objects.create(nombre='X')
        c.padre = c
        with self.assertRaises(ValidationError):
            c.full_clean()

    def test_categoria_admin_crear_con_padre(self):
        from django.contrib.auth.models import User
        admin = User.objects.create_user(username='adm1', password='x12345')
        from .models import PerfilUsuario
        PerfilUsuario.objects.filter(user=admin).update(rol='admin')
        self.client.login(username='adm1', password='x12345')
        padre = Categoria.objects.create(nombre='Padre')
        r = self.client.post(reverse('core:categoria_crear'), {
            'nombre': 'Hija', 'descripcion': '', 'padre': str(padre.pk),
            'visible_store': 'on'})
        self.assertEqual(r.status_code, 302)
        hija = Categoria.objects.get(nombre='Hija')
        self.assertEqual(hija.padre, padre)
        self.assertTrue(hija.visible_store)
        self.assertEqual(self.client.get(reverse('core:categoria_lista')).status_code, 200)
        self.assertEqual(self.client.get(reverse('core:categoria_editar', args=[padre.pk])).status_code, 200)

    def test_store_oculta_categoria_no_visible(self):
        oculta = Categoria.objects.create(nombre='Oculta', visible_store=False)
        Producto.objects.create(nombre='Fantasma', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('9'), categoria=oculta)
        r = self.client.get(reverse('core:store'))
        self.assertNotContains(r, 'Fantasma')
        nombres_api = [p['id'] for p in self.client.get(reverse('core:store_api')).json()['productos']]
        prod = Producto.objects.get(nombre='Fantasma')
        self.assertNotIn(prod.id, nombres_api)

    def test_store_oculta_hijas_de_padre_oculto(self):
        padre = Categoria.objects.create(nombre='PadreOff', visible_store=False)
        hija = Categoria.objects.create(nombre='HijaOn', padre=padre, visible_store=True)
        Producto.objects.create(nombre='Tapado', unidad_medida='unidades',
            precio_compra=1, precio_venta=2, stock=Decimal('9'), categoria=hija)
        r = self.client.get(reverse('core:store'))
        self.assertNotContains(r, 'Tapado')

    def test_store_arbol_padre_con_hijas(self):
        padre = Categoria.objects.create(nombre='Alimentos')
        hija = Categoria.objects.create(nombre='Granos', padre=padre)
        Producto.objects.create(nombre='Arroz', unidad_medida='unidades',
            precio_compra=10, precio_venta=20, stock=Decimal('12'), categoria=hija)
        r = self.client.get(reverse('core:store'))
        self.assertContains(r, 'Alimentos')
        self.assertContains(r, 'data-parent=')

    def test_store_sin_chips_duplicados(self):
        r = self.client.get(reverse('core:store'))
        self.assertNotContains(r, 'id="chips"')
