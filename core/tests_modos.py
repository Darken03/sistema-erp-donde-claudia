from django.test import TestCase
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.urls import reverse
from decimal import Decimal
import json
from .models import (
    ConfiguracionTienda, PerfilUsuario, Producto, EntradaProducto,
    Almacen, AlmacenStock, AlmacenTraslado, Empleado, Turno, PuntoVenta, Venta,
)
from .views import modo_actual


def set_modo(modo):
    """Fija el modo de operación (helper compartido por los tests de modos)."""
    cfg = ConfiguracionTienda.get_solo()
    cfg.modo_operacion = modo
    cfg.save(update_fields=['modo_operacion'])


def _usuario(username, rol='admin'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


class TestModoBase(TestCase):
    def setUp(self):
        _usuario('modo_admin', 'admin')
        _usuario('modo_cajero', 'cajero')

    def test_modo_default_y_oculta_almacen_en_solo_pos(self):
        self.assertEqual(
            ConfiguracionTienda.get_solo().modo_operacion, 'pos_almacenes')
        self.assertEqual(modo_actual(), 'pos_almacenes')
        set_modo('solo_pos')
        self.assertEqual(modo_actual(), 'solo_pos')
        self.client.login(username='modo_admin', password='x12345')
        self.assertEqual(self.client.get('/almacen/').status_code, 302)
        html = self.client.get('/dashboard/').content.decode()
        self.assertNotIn('Almacén', html)

    def test_admin_cambia_modo_en_configuracion(self):
        self.client.login(username='modo_admin', password='x12345')
        r = self.client.post(reverse('core:configuracion'), {
            'form_kind': 'modo', 'modo_operacion': 'solo_pos'})
        self.assertEqual(r.status_code, 302)
        self.assertEqual(
            ConfiguracionTienda.get_solo().modo_operacion, 'solo_pos')
        # Valor inválido: se rechaza sin cambiar.
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'modo', 'modo_operacion': 'invalido'})
        self.assertEqual(
            ConfiguracionTienda.get_solo().modo_operacion, 'solo_pos')

    def test_no_admin_no_cambia_modo(self):
        self.client.login(username='modo_cajero', password='x12345')
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'modo', 'modo_operacion': 'solo_pos'})
        self.assertEqual(
            ConfiguracionTienda.get_solo().modo_operacion, 'pos_almacenes')

    def test_grupo_pos_solo_visible_en_multi_pos(self):
        self.client.login(username='modo_admin', password='x12345')
        html = self.client.get('/dashboard/').content.decode()
        self.assertNotIn('Puntos de venta', html)
        set_modo('multi_pos')
        html = self.client.get('/dashboard/').content.decode()
        self.assertIn('Puntos de venta', html)


class TestSoloPos(TestCase):
    """Modo solo-POS (spec §3): entradas directas solo admin + ocultamiento
    de datos de almacén sin borrarlos + almacenero redirige al POS."""

    def setUp(self):
        self.admin = _usuario('solo_admin', 'admin')
        self.cajero = _usuario('solo_cajero', 'cajero')
        self.alm = _usuario('solo_alm', 'almacenero')
        self.prod = Producto.objects.create(
            nombre='Café', unidad_medida='unidades', precio_compra=10,
            precio_venta=20, stock=Decimal('0'), permite_decimal=False,
            visible_pos=False)
        self.almacen = Almacen.objects.create(nombre='Almacén Test')
        self.stock_alm = AlmacenStock.objects.create(
            producto=self.prod, almacen=self.almacen, cantidad=Decimal('30'))

    def _post_entrada_directa(self, cantidad='5'):
        return self.client.post(reverse('core:entrada_crear'), {
            'producto': self.prod.pk, 'cantidad': cantidad,
            'costo_unitario': '12', 'proveedor': 'Proveedor Y',
            'descripcion': 'compra directa',
        })

    def test_entradas_directas_y_datos_ocultos_no_borrados(self):
        set_modo('solo_pos')
        # Admin crea entrada directa: suma a Producto.stock y publica en POS.
        self.client.login(username='solo_admin', password='x12345')
        r = self._post_entrada_directa()
        self.assertEqual(r.status_code, 302)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('5'))
        self.assertTrue(self.prod.visible_pos)
        ent = EntradaProducto.objects.get(producto=self.prod)
        self.assertEqual(ent.cantidad, Decimal('5'))
        # Proveedor libre: NO se usa el marcador de traslados ('Almacén').
        self.assertEqual(ent.proveedor, 'Proveedor Y')
        # Cajero no puede crear entradas directas.
        self.client.login(username='solo_cajero', password='x12345')
        n = EntradaProducto.objects.count()
        r = self._post_entrada_directa()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(EntradaProducto.objects.count(), n)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('5'))
        # Al volver a un modo con almacén, todo reaparece intacto.
        set_modo('pos_almacenes')
        st = AlmacenStock.objects.get(
            producto=self.prod, almacen=self.almacen)
        self.assertEqual(st.cantidad, Decimal('30'))

    def test_entrada_eliminar_revierte_stock_solo_admin_solo_pos(self):
        set_modo('solo_pos')
        self.client.login(username='solo_admin', password='x12345')
        self._post_entrada_directa()
        ent = EntradaProducto.objects.get(producto=self.prod)
        r = self.client.post(
            reverse('core:entrada_eliminar', args=[ent.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(
            EntradaProducto.objects.filter(pk=ent.pk).exists())
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('0'))
        # Cajero no puede eliminar: la entrada y el stock quedan intactos.
        self._post_entrada_directa()
        ent2 = EntradaProducto.objects.get(producto=self.prod)
        self.client.login(username='solo_cajero', password='x12345')
        r = self.client.post(
            reverse('core:entrada_eliminar', args=[ent2.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(
            EntradaProducto.objects.filter(pk=ent2.pk).exists())
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('5'))

    def test_vistas_almacen_redirigen_en_solo_pos(self):
        set_modo('solo_pos')
        self.client.login(username='solo_admin', password='x12345')
        for name in ('core:almacen_panel', 'core:almacen_stock',
                     'core:almacen_entrada_lista',
                     'core:almacen_traslado_lista',
                     'core:almacen_movimientos'):
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
        # Entradas directas bloqueadas fuera de solo-POS (sin borrar nada).
        set_modo('pos_almacenes')
        n = EntradaProducto.objects.count()
        r = self._post_entrada_directa()
        self.assertEqual(r.status_code, 302)
        self.assertEqual(EntradaProducto.objects.count(), n)

    def test_entrada_lista_gestion_solo_en_solo_pos(self):
        self.client.login(username='solo_admin', password='x12345')
        set_modo('solo_pos')
        html = self.client.get(
            reverse('core:entrada_lista')).content.decode()
        self.assertIn('Nueva Entrada', html)
        r = self.client.get(reverse('core:entrada_crear'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Registrar Entrada')
        set_modo('pos_almacenes')
        html = self.client.get(
            reverse('core:entrada_lista')).content.decode()
        self.assertNotIn('Nueva Entrada', html)

    def test_almacenero_redirige_al_pos_con_aviso_en_solo_pos(self):
        set_modo('solo_pos')
        self.client.login(username='solo_alm', password='x12345')
        r = self.client.get(
            reverse('core:redireccion_rol'), follow=True)
        self.assertEqual(r.redirect_chain[-1][0], '/pos/')
        msgs = [str(m).lower() for m in r.context['messages']]
        self.assertTrue(
            any('cajero' in m for m in msgs),
            f'se esperaba aviso de reasignar a cajero, hubo: {msgs}')
        # El rol queda sin pantallas de almacén.
        html = r.content.decode()
        self.assertNotIn('Almacén', html)
        # Toda URL de almacén lo lleva al POS (sin 500).
        r2 = self.client.get(reverse('core:almacen_stock'))
        self.assertEqual(r2.status_code, 302)
        self.assertTrue(r2.url.endswith('/pos/'))

    def test_empleado_form_sugiere_cajero_en_solo_pos(self):
        self.client.login(username='solo_admin', password='x12345')
        set_modo('solo_pos')
        r = self.client.get(reverse('core:empleado_crear'))
        self.assertEqual(r.status_code, 200)
        msgs = [str(m).lower() for m in r.context['messages']]
        self.assertTrue(
            any('cajero' in m for m in msgs),
            f'se esperaba sugerencia de cajero, hubo: {msgs}')


class TestPuntoVenta(TestCase):
    """Modo multi-POS (spec §5): entidad PuntoVenta + turno exige POS.

    Un POS ↔ un almacén (varios POS pueden compartir almacén);
    `Empleado.punto_venta` se fija al abrir turno; varios trabajadores
    pueden compartir POS en turnos propios. Historia previa: FKs NULL.
    """

    def setUp(self):
        self.admin = _usuario('pos_admin', 'admin')
        cajero = _usuario('pos_cajero', 'cajero')
        self.empleado = Empleado.objects.create(
            user=cajero, salario=0, activo=True)
        self.almacen = Almacen.objects.create(nombre='Almacén POS 1')

    def _abrir_turno(self, pos_pk=None):
        url = reverse('core:turno_abrir', args=[self.empleado.pk])
        data = {} if pos_pk is None else {'punto_venta': pos_pk}
        return self.client.post(url, data)

    def test_pos_requiere_almacen_y_turno_exige_pos(self):
        # Un POS sin almacén falla (FK obligatoria).
        with transaction.atomic(), self.assertRaises(IntegrityError):
            PuntoVenta.objects.create(nombre='POS huérfano')
        # Nombre único, estilo Almacen.
        PuntoVenta.objects.create(nombre='Caja 1', almacen=self.almacen)
        with transaction.atomic(), self.assertRaises(IntegrityError):
            PuntoVenta.objects.create(nombre='Caja 1', almacen=self.almacen)
        # En multi-POS, abrir turno sin POS falla (no se crea el turno).
        set_modo('multi_pos')
        self.client.login(username='pos_admin', password='x12345')
        r = self._abrir_turno()
        self.assertEqual(r.status_code, 302)
        self.assertFalse(
            Turno.objects.filter(empleado=self.empleado).exists())
        # Con POS válido: turno con POS + empleado asignado a ese POS.
        pos = PuntoVenta.objects.get(nombre='Caja 1')
        r = self._abrir_turno(pos.pk)
        self.assertEqual(r.status_code, 302)
        turno = Turno.objects.get(empleado=self.empleado, abierto=True)
        self.assertEqual(turno.punto_venta_id, pos.pk)
        self.empleado.refresh_from_db()
        self.assertEqual(self.empleado.punto_venta_id, pos.pk)
        # Varios trabajadores comparten POS en turnos propios.
        otro_user = _usuario('pos_cajero2', 'cajero')
        otro = Empleado.objects.create(user=otro_user, salario=0, activo=True)
        r = self.client.post(
            reverse('core:turno_abrir', args=[otro.pk]),
            {'punto_venta': pos.pk})
        self.assertEqual(r.status_code, 302)
        turno2 = Turno.objects.get(empleado=otro, abierto=True)
        self.assertEqual(turno2.punto_venta_id, pos.pk)

    def test_turno_sin_pos_fuera_de_multi_pos_y_crud_configuracion(self):
        # Fuera de multi-POS el turno abre sin POS (historia con NULL).
        self.client.login(username='pos_admin', password='x12345')
        r = self._abrir_turno()
        self.assertEqual(r.status_code, 302)
        turno = Turno.objects.get(empleado=self.empleado, abierto=True)
        self.assertIsNone(turno.punto_venta)
        # CRUD de POS en Configuración (solo admin).
        r = self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_crear', 'nombre': 'Caja N',
            'almacen': self.almacen.pk})
        self.assertEqual(r.status_code, 302)
        pos = PuntoVenta.objects.get(nombre='Caja N')
        self.assertEqual(pos.almacen_id, self.almacen.pk)
        self.assertTrue(pos.activo)
        # Duplicado no crea; sin almacén no crea.
        n = PuntoVenta.objects.count()
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_crear', 'nombre': 'Caja N',
            'almacen': self.almacen.pk})
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_crear', 'nombre': 'Sin Almacén'})
        self.assertEqual(PuntoVenta.objects.count(), n)
        # Editar cambia nombre y almacén.
        alm2 = Almacen.objects.create(nombre='Almacén POS 2')
        r = self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_editar', 'pos_id': pos.pk,
            'nombre': 'Caja Norte', 'almacen': alm2.pk})
        self.assertEqual(r.status_code, 302)
        pos.refresh_from_db()
        self.assertEqual((pos.nombre, pos.almacen_id), ('Caja Norte', alm2.pk))
        # Toggle desactiva: en multi-POS ese POS ya no abre turnos.
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_toggle', 'pos_id': pos.pk})
        pos.refresh_from_db()
        self.assertFalse(pos.activo)
        turno.cerrar()
        set_modo('multi_pos')
        r = self._abrir_turno(pos.pk)
        self.assertEqual(r.status_code, 302)
        self.assertFalse(
            Turno.objects.filter(empleado=self.empleado, abierto=True).exists())
        # No-admin no gestiona POS.
        self.client.login(username='pos_cajero', password='x12345')
        n = PuntoVenta.objects.count()
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_crear', 'nombre': 'Intruso',
            'almacen': self.almacen.pk})
        self.assertEqual(PuntoVenta.objects.count(), n)


class TestPuntoVentaUI(TestCase):
    """Findings C1/C2/I1: UI de POS en apertura de turno y configuración."""

    def setUp(self):
        _usuario('posui_admin', 'admin')
        cajero = _usuario('posui_cajero', 'cajero')
        self.empleado = Empleado.objects.create(
            user=cajero, salario=0, activo=True)
        self.almacen = Almacen.objects.create(nombre='Almacén UI')
        self.pos = PuntoVenta.objects.create(
            nombre='Caja UI', almacen=self.almacen)
        self.client.login(username='posui_admin', password='x12345')

    def test_C1_select_pos_en_apertura_solo_en_multi_pos(self):
        set_modo('multi_pos')
        html = self.client.get(
            reverse('core:empleado_lista')).content.decode()
        self.assertIn('<select name="punto_venta"', html)
        self.assertIn(f'value="{self.pos.pk}"', html)
        self.assertIn('Caja UI', html)
        # Un POS inactivo no se ofrece en el selector.
        inactivo = PuntoVenta.objects.create(
            nombre='Caja Cerrada', almacen=self.almacen, activo=False)
        html = self.client.get(
            reverse('core:empleado_lista')).content.decode()
        self.assertNotIn(f'value="{inactivo.pk}"', html)
        # Apertura iniciada desde la UI (con punto_venta del select) funciona.
        r = self.client.post(
            reverse('core:turno_abrir', args=[self.empleado.pk]),
            {'punto_venta': self.pos.pk})
        self.assertEqual(r.status_code, 302)
        turno = Turno.objects.get(empleado=self.empleado, abierto=True)
        self.assertEqual(turno.punto_venta_id, self.pos.pk)
        # Fuera de multi_pos el selector se oculta/omite.
        turno.cerrar()
        set_modo('pos_almacenes')
        html = self.client.get(
            reverse('core:empleado_lista')).content.decode()
        self.assertNotIn('<select name="punto_venta"', html)

    def test_C2_seccion_pos_en_configuracion_y_crud_end_to_end(self):
        html = self.client.get(
            reverse('core:configuracion') + '?tab=almacenes').content.decode()
        # Sección con nombre/almacén/activo y formularios al CRUD existente.
        self.assertIn('Puntos de venta', html)
        self.assertIn('Caja UI', html)
        self.assertIn('Almacén UI', html)
        self.assertIn('value="pos_crear"', html)
        self.assertIn('value="pos_editar"', html)
        self.assertIn('value="pos_toggle"', html)
        # Crear a través de la UI y verlo listado.
        r = self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_crear', 'nombre': 'Caja Sur',
            'almacen': self.almacen.pk})
        self.assertEqual(r.status_code, 302)
        nuevo = PuntoVenta.objects.get(nombre='Caja Sur')
        html = self.client.get(
            reverse('core:configuracion') + '?tab=almacenes').content.decode()
        self.assertIn('Caja Sur', html)
        # Editar a través de la UI y verlo actualizado.
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_editar', 'pos_id': nuevo.pk,
            'nombre': 'Caja Sur 2', 'almacen': self.almacen.pk})
        html = self.client.get(
            reverse('core:configuracion') + '?tab=almacenes').content.decode()
        self.assertIn('Caja Sur 2', html)
        # Toggle a través de la UI y ver el estado cambiado.
        self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_toggle', 'pos_id': nuevo.pk})
        nuevo.refresh_from_db()
        self.assertFalse(nuevo.activo)
        html = self.client.get(
            reverse('core:configuracion') + '?tab=almacenes').content.decode()
        self.assertIn('Inactivo', html)

    def test_I1_redirects_pos_caen_en_tab_de_pos(self):
        r = self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_crear', 'nombre': 'Caja Tab',
            'almacen': self.almacen.pk})
        self.assertEqual(r.status_code, 302)
        self.assertIn('tab=almacenes', r.url)
        pos = PuntoVenta.objects.get(nombre='Caja Tab')
        r = self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_editar', 'pos_id': pos.pk,
            'nombre': 'Caja Tab 2', 'almacen': self.almacen.pk})
        self.assertIn('tab=almacenes', r.url)
        r = self.client.post(reverse('core:configuracion'), {
            'form_kind': 'pos_toggle', 'pos_id': pos.pk})
        self.assertIn('tab=almacenes', r.url)


class TestVentasMultiPos(TestCase):
    """Modo multi-POS (spec §5): el POS vende del AlmacenStock asignado.

    Sin stock propio del POS: catálogo = existencias del almacén del
    turno; la venta descuenta ese almacén (+ `AlmacenMovimiento`) y
    guarda `Venta.punto_venta`; `Producto.stock` no se toca.
    """

    def setUp(self):
        self.admin = _usuario('vmp_admin', 'admin')
        cajero = _usuario('vmp_cajero', 'cajero')
        self.empleado = Empleado.objects.create(
            user=cajero, salario=0, activo=True)
        self.almacen1 = Almacen.objects.create(nombre='Almacén VMP 1')
        self.almacen2 = Almacen.objects.create(nombre='Almacén VMP 2')
        self.pos1 = PuntoVenta.objects.create(
            nombre='Caja VMP 1', almacen=self.almacen1)
        self.prod = Producto.objects.create(
            nombre='Pan VMP', unidad_medida='unidades', precio_compra=10,
            precio_venta=20, stock=Decimal('0'), permite_decimal=False,
            visible_pos=False)
        AlmacenStock.objects.create(
            producto=self.prod, almacen=self.almacen1,
            cantidad=Decimal('10'))
        AlmacenStock.objects.create(
            producto=self.prod, almacen=self.almacen2,
            cantidad=Decimal('5'))

    def _abrir_turno_pos1(self):
        self.client.login(username='vmp_admin', password='x12345')
        self.client.post(
            reverse('core:turno_abrir', args=[self.empleado.pk]),
            {'punto_venta': self.pos1.pk})
        self.client.logout()

    def _vender(self, cantidad='2', monto_recibido=50):
        self.client.login(username='vmp_cajero', password='x12345')
        return self.client.post(
            reverse('core:pos_procesar'),
            data=json.dumps({
                'items': [{'id': self.prod.pk, 'cantidad': cantidad}],
                'metodo_pago': 'efectivo',
                'monto_recibido': monto_recibido,
                'monto_transferencia': 0,
            }),
            content_type='application/json')

    def _stock_almacen(self, almacen):
        return AlmacenStock.objects.get(
            producto=self.prod, almacen=almacen).cantidad

    def test_venta_descuenta_almacen_asignado(self):
        set_modo('multi_pos')
        self._abrir_turno_pos1()
        r = self._vender(cantidad='2')
        self.assertEqual(r.status_code, 200, r.content.decode()[:500])
        venta = Venta.objects.get(cajero__username='vmp_cajero')
        self.assertEqual(self._stock_almacen(self.almacen1), Decimal('8'))
        # El otro almacén no se toca.
        self.assertEqual(self._stock_almacen(self.almacen2), Decimal('5'))
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('0'))
        self.assertEqual(venta.punto_venta_id, self.pos1.pk)

    def test_catalogo_pos_usa_stock_almacen(self):
        set_modo('multi_pos')
        self._abrir_turno_pos1()
        self.client.login(username='vmp_cajero', password='x12345')
        r = self.client.get(reverse('core:pos_catalogo'))
        self.assertEqual(r.status_code, 200)
        items = {p['id']: p for p in r.json()['productos']}
        # visible_pos=False y stock=0: en modo normal sería invisible;
        # en multi-POS aparece con las 10 existencias de su almacén.
        self.assertIn(self.prod.pk, items)
        self.assertEqual(Decimal(items[self.prod.pk]['stock']), Decimal('10'))
        r = self.client.post(reverse('core:pos_buscar'), {'q': 'pan vmp'})
        self.assertEqual(r.status_code, 200)
        items = {p['id']: p for p in r.json()['productos']}
        self.assertIn(self.prod.pk, items)
        self.assertEqual(Decimal(items[self.prod.pk]['stock']), Decimal('10'))
        # La página muestra el origen del stock (POS + almacén).
        r = self.client.get(reverse('core:pos'))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Caja VMP 1', html)
        self.assertIn('Almacén VMP 1', html)

    def test_sin_pos_bloquea_venta(self):
        # Turno abierto sin POS (modo anterior) + cambio a multi-POS:
        # la venta se bloquea con mensaje y nada se descuenta.
        # (El cambio de modo NUNCA borra datos: el turno sigue intacto.)
        self.prod.visible_pos = True
        self.prod.stock = Decimal('5')
        self.prod.save(update_fields=['visible_pos', 'stock'])
        self.client.login(username='vmp_admin', password='x12345')
        self.client.post(
            reverse('core:turno_abrir', args=[self.empleado.pk]))
        self.client.logout()
        set_modo('multi_pos')
        r = self._vender(cantidad='1')
        self.assertEqual(r.status_code, 400, r.content.decode()[:500])
        self.assertIn('punto de venta', r.json()['error'].lower())
        self.assertFalse(
            Venta.objects.filter(cajero__username='vmp_cajero').exists())
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('5'))
        self.assertEqual(self._stock_almacen(self.almacen1), Decimal('10'))
        # La página del POS también se bloquea con mensaje (sin 500).
        self.client.login(username='vmp_cajero', password='x12345')
        r = self.client.get(reverse('core:pos'))
        self.assertEqual(r.status_code, 200)
        self.assertIn('Sin punto de venta asignado', r.content.decode())


class TestReportesPorPos(TestCase):
    """Modo multi-POS (spec §5): IPB/ventas/arqueos por POS + sin traslados a POS.

    IPB con filtro `?pos=` calculado sobre el stock del almacén de cada POS
    (no sobre `Producto.stock`); ventas y arqueos filtran por `punto_venta`;
    `destino_tipo=POS` rechazado en multi-POS (solo entre almacenes).
    """

    def setUp(self):
        self.admin = _usuario('rep_admin', 'admin')
        cajero1 = _usuario('rep_cajero1', 'cajero')
        cajero2 = _usuario('rep_cajero2', 'cajero')
        self.emp1 = Empleado.objects.create(
            user=cajero1, salario=0, activo=True)
        self.emp2 = Empleado.objects.create(
            user=cajero2, salario=0, activo=True)
        self.alm1 = Almacen.objects.create(nombre='Almacén REP 1')
        self.alm2 = Almacen.objects.create(nombre='Almacén REP 2')
        self.pos1 = PuntoVenta.objects.create(
            nombre='Caja REP 1', almacen=self.alm1)
        self.pos2 = PuntoVenta.objects.create(
            nombre='Caja REP 2', almacen=self.alm2)
        self.prod = Producto.objects.create(
            nombre='Pan REP', unidad_medida='unidades', precio_compra=10,
            precio_venta=20, stock=Decimal('0'), permite_decimal=False,
            visible_pos=False)
        AlmacenStock.objects.create(
            producto=self.prod, almacen=self.alm1,
            cantidad=Decimal('10'))
        AlmacenStock.objects.create(
            producto=self.prod, almacen=self.alm2,
            cantidad=Decimal('5'))

    def _abrir_turnos(self):
        self.client.login(username='rep_admin', password='x12345')
        self.client.post(
            reverse('core:turno_abrir', args=[self.emp1.pk]),
            {'punto_venta': self.pos1.pk})
        self.client.post(
            reverse('core:turno_abrir', args=[self.emp2.pk]),
            {'punto_venta': self.pos2.pk})
        self.client.logout()

    def _vender(self, username, cantidad, recibido):
        self.client.login(username=username, password='x12345')
        r = self.client.post(
            reverse('core:pos_procesar'),
            data=json.dumps({
                'items': [{'id': self.prod.pk, 'cantidad': cantidad}],
                'metodo_pago': 'efectivo',
                'monto_recibido': recibido,
                'monto_transferencia': 0,
            }),
            content_type='application/json')
        self.client.logout()
        return r

    def test_ipb_y_ventas_por_pos_y_sin_traslado_a_pos(self):
        from .views import _obtener_datos_ipb, ahora_servidor
        set_modo('multi_pos')
        self._abrir_turnos()
        r = self._vender('rep_cajero1', '2', 50)
        self.assertEqual(r.status_code, 200, r.content.decode()[:500])
        r = self._vender('rep_cajero2', '1', 50)
        self.assertEqual(r.status_code, 200, r.content.decode()[:500])
        hoy = ahora_servidor().date()

        # IPB por POS: mismo producto, distinto almacén y distintas ventas.
        d1 = _obtener_datos_ipb(hoy, punto_venta=self.pos1)
        d2 = _obtener_datos_ipb(hoy, punto_venta=self.pos2)
        self.assertEqual(d1['resumen']['total_ventas'], Decimal('2'))
        self.assertEqual(d2['resumen']['total_ventas'], Decimal('1'))
        self.assertNotEqual(
            d1['resumen']['total_stock_final'],
            d2['resumen']['total_stock_final'])

        # El filtro ?pos= llega end-to-end (cabecera + opción seleccionada).
        self.client.login(username='rep_admin', password='x12345')
        h1 = self.client.get(
            reverse('core:ipb') + f'?pos={self.pos1.pk}')
        h2 = self.client.get(
            reverse('core:ipb') + f'?pos={self.pos2.pk}')
        self.assertEqual(h1.status_code, 200)
        self.assertEqual(h2.status_code, 200)
        self.assertIn('Caja REP 1', h1.content.decode())
        self.assertIn('Caja REP 2', h2.content.decode())
        self.assertIn(
            f'value="{self.pos1.pk}" selected', h1.content.decode())

        # Ventas filtradas por POS (números de ticket exactos).
        n1 = Venta.objects.get(punto_venta=self.pos1).numero_venta
        n2 = Venta.objects.get(punto_venta=self.pos2).numero_venta
        v1 = self.client.get(
            reverse('core:venta_lista') + f'?pos={self.pos1.pk}').content.decode()
        v2 = self.client.get(
            reverse('core:venta_lista') + f'?pos={self.pos2.pk}').content.decode()
        self.assertIn(n1, v1)
        self.assertNotIn(n2, v1)
        self.assertIn(n2, v2)
        self.assertNotIn(n1, v2)

        # Traslado →POS bloqueado en multi (sin crear nada); entre
        # almacenes sí pasa.
        n = AlmacenTraslado.objects.count()
        rb = self.client.post(
            reverse('core:almacen_traslado_crear'), {
                'producto': self.prod.pk, 'cantidad': '1',
                'origen': self.alm1.pk, 'destino_tipo': 'POS'},
            follow=True)
        self.assertEqual(AlmacenTraslado.objects.count(), n)
        msgs = [str(m).lower() for m in rb.context['messages']]
        self.assertTrue(
            any('entre almacenes' in m for m in msgs),
            f'se esperaba bloqueo solo-entre-almacenes, hubo: {msgs}')
        rok = self.client.post(
            reverse('core:almacen_traslado_crear'), {
                'producto': self.prod.pk, 'cantidad': '1',
                'origen': self.alm1.pk, 'destino_tipo': 'ALMACEN',
                'destino_almacen': self.alm2.pk})
        self.assertEqual(rok.status_code, 302)
        self.assertEqual(AlmacenTraslado.objects.count(), n + 1)

        # Arqueos filtrados por POS (un turno por POS).
        a1 = self.client.get(
            reverse('core:arqueos_admin') + f'?pos={self.pos1.pk}').content.decode()
        self.assertIn('rep_cajero1', a1)
        self.assertNotIn('rep_cajero2', a1)
