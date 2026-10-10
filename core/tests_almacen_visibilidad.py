import json
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import (
    PerfilUsuario, Producto, AlmacenStock, EntradaProducto,
    InventarioDiario,
)
from .views import _sincronizar_inventario_dia, ahora_servidor


def _usuario(username, rol='admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


def _form_producto(nombre, stock='5'):
    return {
        'nombre': nombre,
        'unidad_medida': 'unidades',
        'precio_compra': '10',
        'precio_venta': '20',
        'stock': stock,
        'stock_minimo': '1',
        'activo': 'on',
        'presentaciones-TOTAL_FORMS': '1',
        'presentaciones-INITIAL_FORMS': '0',
        'presentaciones-MIN_NUM_FORMS': '0',
        'presentaciones-MAX_NUM_FORMS': '1000',
        'presentaciones-0-nombre': 'Unidad',
        'presentaciones-0-factor': '1',
        'presentaciones-0-precio': '20',
        'presentaciones-0-es_default': 'on',
        'presentaciones-0-activo': 'on',
    }


class VisibilidadMigracionTest(TestCase):
    def test_productos_existentes_nacen_visibles(self):
        p = Producto.objects.create(nombre='Viejo', unidad_medida='unidades',
                                    precio_compra=1, precio_venta=2)
        p.refresh_from_db()
        self.assertTrue(p.visible_pos)


class CrearDesdeAlmacenOcultoTest(TestCase):
    def setUp(self):
        _usuario('adminVis', 'admin')
        self.client.login(username='adminVis', password='x12345')

    def test_crear_desde_almacen_nace_oculto_y_sin_stock(self):
        next_url = reverse('core:almacen_entrada_crear')
        data = _form_producto('Nuevo Oculto', stock='5')
        data['next'] = next_url
        r = self.client.post(reverse('core:producto_crear') + f'?next={next_url}', data)
        self.assertEqual(r.status_code, 302)
        prod = Producto.objects.get(nombre='Nuevo Oculto')
        self.assertEqual(prod.stock, Decimal('0'))
        self.assertFalse(prod.visible_pos)
        self.assertIn(next_url, r.url)

    def test_crear_normal_sigue_visible(self):
        r = self.client.post(reverse('core:producto_crear'), _form_producto('Normal'))
        self.assertEqual(r.status_code, 302)
        prod = Producto.objects.get(nombre='Normal')
        self.assertEqual(prod.stock, Decimal('5'))
        self.assertTrue(prod.visible_pos)

    def test_next_malicioso_se_ignora(self):
        data = _form_producto('Malicioso', stock='7')
        data['next'] = '//evil.com/x'
        r = self.client.post(reverse('core:producto_crear') + '?next=//evil.com/x', data)
        self.assertEqual(r.status_code, 302)
        self.assertIn(reverse('core:producto_lista'), r.url)
        prod = Producto.objects.get(nombre='Malicioso')
        self.assertTrue(prod.visible_pos)

    def test_oculto_no_sale_en_pos_ni_catalogo_ni_ipb(self):
        next_url = reverse('core:almacen_entrada_crear')
        data = _form_producto('Fantasma', stock='5')
        data['next'] = next_url
        self.client.post(reverse('core:producto_crear') + f'?next={next_url}', data)
        prod = Producto.objects.get(nombre='Fantasma')
        # POS buscar
        r = self.client.post(reverse('core:pos_buscar'), {'q': 'Fantasma'})
        ids = [p['id'] for p in r.json()['productos']]
        self.assertNotIn(prod.pk, ids)
        # Catálogo público (sin login)
        self.client.logout()
        r = self.client.get(reverse('core:catalogo'))
        self.assertNotContains(r, 'Fantasma')
        # IPB: el sincronizador no le crea fila
        self.client.login(username='adminVis', password='x12345')
        _sincronizar_inventario_dia(ahora_servidor().date())
        self.assertFalse(InventarioDiario.objects.filter(producto=prod).exists())

    def test_traslado_publica_y_genera_entrada_ipb(self):
        next_url = reverse('core:almacen_entrada_crear')
        data = _form_producto('Para Trasladar', stock='5')
        data['next'] = next_url
        self.client.post(reverse('core:producto_crear') + f'?next={next_url}', data)
        prod = Producto.objects.get(nombre='Para Trasladar')
        self.assertFalse(prod.visible_pos)
        AlmacenStock.objects.create(producto=prod, cantidad=Decimal('10'))
        r = self.client.post(reverse('core:almacen_traslado_crear'),
                             {'producto': prod.pk, 'cantidad': '4'})
        self.assertEqual(r.status_code, 302)
        prod.refresh_from_db()
        self.assertTrue(prod.visible_pos)
        ent = EntradaProducto.objects.filter(producto=prod, proveedor='Almacén').first()
        self.assertIsNotNone(ent)
        self.assertEqual(ent.cantidad, Decimal('4'))

    def test_traslado_de_visible_sigue_igual(self):
        prod = Producto.objects.create(nombre='Ya Visible', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('0'), permite_decimal=False)
        AlmacenStock.objects.create(producto=prod, cantidad=Decimal('10'))
        r = self.client.post(reverse('core:almacen_traslado_crear'),
                             {'producto': prod.pk, 'cantidad': '3'})
        self.assertEqual(r.status_code, 302)
        prod.refresh_from_db()
        self.assertTrue(prod.visible_pos)
        self.assertEqual(prod.stock, Decimal('3'))

    def test_entrada_expone_stock_json_y_preseleccionado(self):
        prod = Producto.objects.create(nombre='Con Stock', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('0'), permite_decimal=False)
        AlmacenStock.objects.create(producto=prod, cantidad=Decimal('8'))
        r = self.client.get(reverse('core:almacen_entrada_crear') + f'?producto={prod.pk}')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(str(r.context['preseleccionado']), str(prod.pk))
        self.assertIn(str(prod.pk), r.context['stock_json'])

    def _entrada(self, prod, cantidad='25'):
        return self.client.post(reverse('core:almacen_entrada_crear'), {
            'producto': prod.pk, 'cantidad': cantidad,
            'costo_unitario': '10', 'proveedor': 'Prov',
        })

    def _traslado(self, prod, cantidad):
        return self.client.post(reverse('core:almacen_traslado_crear'), {
            'producto': prod.pk, 'cantidad': cantidad,
        })

    def test_cancelar_entrada_revierte_stock(self):
        from .models import AlmacenEntrada, AlmacenMovimiento
        prod = Producto.objects.create(nombre='Ent Cancel', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('0'), permite_decimal=False)
        self._entrada(prod, '25')
        ent = AlmacenEntrada.objects.get(producto=prod)
        self.assertEqual(AlmacenStock.objects.get(producto=prod).cantidad, Decimal('25'))
        r = self.client.post(reverse('core:almacen_entrada_cancelar', args=[ent.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertEqual(AlmacenStock.objects.get(producto=prod).cantidad, Decimal('0'))
        self.assertFalse(AlmacenEntrada.objects.filter(pk=ent.pk).exists())
        self.assertTrue(AlmacenMovimiento.objects.filter(
            producto=prod, tipo='ajuste', descripcion__icontains='Cancelación').exists())

    def test_cancelar_entrada_bloquea_sin_stock(self):
        from .models import AlmacenEntrada
        prod = Producto.objects.create(nombre='Ent Bloq', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('0'), permite_decimal=False)
        self._entrada(prod, '25')
        self._traslado(prod, '10')
        ent = AlmacenEntrada.objects.get(producto=prod)
        r = self.client.post(reverse('core:almacen_entrada_cancelar', args=[ent.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AlmacenEntrada.objects.filter(pk=ent.pk).exists())
        self.assertEqual(AlmacenStock.objects.get(producto=prod).cantidad, Decimal('15'))

    def test_cancelar_traslado_revierte_todo(self):
        from .models import AlmacenEntrada, AlmacenTraslado
        prod = Producto.objects.create(nombre='Tras Cancel', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('100'), permite_decimal=False)
        self._entrada(prod, '25')
        self._traslado(prod, '10')
        tras = AlmacenTraslado.objects.get(producto=prod)
        ent_ipb = tras.entrada_generada_id
        self.assertIsNotNone(ent_ipb)
        r = self.client.post(reverse('core:almacen_traslado_cancelar', args=[tras.pk]))
        self.assertEqual(r.status_code, 302)
        prod.refresh_from_db()
        self.assertEqual(AlmacenStock.objects.get(producto=prod).cantidad, Decimal('25'))
        self.assertEqual(prod.stock, Decimal('100'))
        self.assertFalse(AlmacenTraslado.objects.filter(pk=tras.pk).exists())
        self.assertFalse(EntradaProducto.objects.filter(pk=ent_ipb).exists())

    def test_cancelar_traslado_bloquea_si_vendido(self):
        from .models import AlmacenTraslado
        prod = Producto.objects.create(nombre='Tras Vend', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('100'), permite_decimal=False)
        self._entrada(prod, '25')
        self._traslado(prod, '10')
        tras = AlmacenTraslado.objects.get(producto=prod)
        prod.stock = Decimal('5')
        prod.save(update_fields=['stock'])
        r = self.client.post(reverse('core:almacen_traslado_cancelar', args=[tras.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AlmacenTraslado.objects.filter(pk=tras.pk).exists())
        prod.refresh_from_db()
        self.assertEqual(prod.stock, Decimal('5'))

    def test_cancelar_traslado_bloquea_dia_cerrado(self):
        from .models import AlmacenTraslado
        prod = Producto.objects.create(nombre='Tras Cerr', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('100'), permite_decimal=False)
        self._entrada(prod, '25')
        self._traslado(prod, '10')
        tras = AlmacenTraslado.objects.get(producto=prod)
        inv = InventarioDiario.objects.get(producto=prod, fecha=ahora_servidor().date())
        inv.cerrado = True
        inv.save(update_fields=['cerrado'])
        r = self.client.post(reverse('core:almacen_traslado_cancelar', args=[tras.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AlmacenTraslado.objects.filter(pk=tras.pk).exists())

    def test_cancelar_traslado_oculta_si_fue_publicado(self):
        from .models import AlmacenTraslado
        prod = Producto.objects.create(nombre='Tras Oculta', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('0'), permite_decimal=False,
                                       visible_pos=False)
        AlmacenStock.objects.create(producto=prod, cantidad=Decimal('10'))
        self._traslado(prod, '4')
        prod.refresh_from_db()
        self.assertTrue(prod.visible_pos)
        tras = AlmacenTraslado.objects.get(producto=prod)
        self.client.post(reverse('core:almacen_traslado_cancelar', args=[tras.pk]))
        prod.refresh_from_db()
        self.assertFalse(prod.visible_pos)
        self.assertEqual(prod.stock, Decimal('0'))
        self.assertEqual(AlmacenStock.objects.get(producto=prod).cantidad, Decimal('10'))

    def test_almacenero_no_puede_cancelar(self):
        from .models import AlmacenEntrada
        _usuario('almCanc', 'almacenero')
        prod = Producto.objects.create(nombre='Sin Permiso', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('0'), permite_decimal=False)
        self._entrada(prod, '25')
        ent = AlmacenEntrada.objects.get(producto=prod)
        self.client.logout()
        self.client.login(username='almCanc', password='x12345')
        r = self.client.post(reverse('core:almacen_entrada_cancelar', args=[ent.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(AlmacenEntrada.objects.filter(pk=ent.pk).exists())
        self.assertEqual(AlmacenStock.objects.get(producto=prod).cantidad, Decimal('25'))

    def test_traslado_solo_muestra_con_stock_en_almacen(self):
        con = Producto.objects.create(nombre='Con Stock T', unidad_medida='unidades',
                                      precio_compra=10, precio_venta=20,
                                      stock=Decimal('0'), permite_decimal=False)
        AlmacenStock.objects.create(producto=con, cantidad=Decimal('5'))
        sin_fila = Producto.objects.create(nombre='Sin Fila T', unidad_medida='unidades',
                                           precio_compra=10, precio_venta=20,
                                           stock=Decimal('0'), permite_decimal=False)
        sin_stock = Producto.objects.create(nombre='Sin Stock T', unidad_medida='unidades',
                                            precio_compra=10, precio_venta=20,
                                            stock=Decimal('0'), permite_decimal=False)
        AlmacenStock.objects.create(producto=sin_stock, cantidad=Decimal('0'))
        r = self.client.get(reverse('core:almacen_traslado_crear'))
        self.assertEqual(r.status_code, 200)
        ids = [p.pk for p in r.context['productos']]
        self.assertIn(con.pk, ids)
        self.assertNotIn(sin_fila.pk, ids)
        self.assertNotIn(sin_stock.pk, ids)
        html = r.content.decode()
        self.assertIn(f'data-id="{con.pk}"', html)
        self.assertNotIn(f'data-id="{sin_fila.pk}"', html)

    def test_traslado_usa_grid_de_tarjetas(self):
        prod = Producto.objects.create(nombre='Para Grid', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('0'), permite_decimal=False)
        AlmacenStock.objects.create(producto=prod, cantidad=Decimal('6'))
        r = self.client.get(reverse('core:almacen_traslado_crear') + f'?producto={prod.pk}')
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('id="productoGrid"', html)
        self.assertIn(f'data-id="{prod.pk}"', html)
        self.assertIn('id="productoSelect" hidden', html)
        self.assertIn(str(prod.pk), r.context['stock_json'])

    def test_entrada_con_producto_inexistente_no_preselecciona(self):
        import re
        r = self.client.get(reverse('core:almacen_entrada_crear') + '?producto=999999')
        self.assertEqual(r.status_code, 200)
        marcados = re.findall(r'<option[^>]*\bselected\b', r.content.decode())
        self.assertEqual(marcados, [])

    def test_procesar_venta_rechaza_oculto(self):
        prod = Producto.objects.create(nombre='Oculto Venta', unidad_medida='unidades',
                                       precio_compra=10, precio_venta=20,
                                       stock=Decimal('10'), permite_decimal=False,
                                       visible_pos=False)
        r = self.client.post(reverse('core:pos_procesar'),
                             data=json.dumps({'items': [{'id': prod.pk, 'cantidad': '1'}],
                                              'metodo_pago': 'efectivo',
                                              'monto_recibido': 20,
                                              'monto_transferencia': 0}),
                             content_type='application/json')
        self.assertEqual(r.status_code, 400)
        prod.refresh_from_db()
        self.assertEqual(prod.stock, Decimal('10'))
