from django.test import TestCase
from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.urls import reverse
from decimal import Decimal
from .models import (
    ConfiguracionTienda, PerfilUsuario, Producto, EntradaProducto,
    Almacen, AlmacenStock, Empleado, Turno, PuntoVenta,
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
