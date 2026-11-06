from datetime import timedelta
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from django.urls import reverse
from .models import (
    Producto, Venta, DetalleVenta, PresentacionProducto, HistorialPrecio,
    Almacen, PuntoVenta, AlmacenStock, PerfilUsuario,
)
from .views import (
    _obtener_datos_ipb, _sincronizar_inventario_dia, ahora_servidor,
    _log_cambio_precio,
)


class IpbPrecioHistoricoTest(TestCase):
    def test_ipb_muestra_precio_del_dia_no_el_actual(self):
        u = User.objects.create_user(username='caja_hist', password='x')
        prod = Producto.objects.create(
            nombre='Refresco Test Hist', unidad_medida='unidades',
            precio_compra=470, precio_venta=Decimal('540'),
            stock=Decimal('100'), permite_decimal=False)
        pres = PresentacionProducto.objects.create(
            producto=prod, nombre='Unidad', factor=1, precio=Decimal('540'),
            es_default=True, activo=True)
        ayer = (ahora_servidor() - timedelta(days=1)).date()
        v = Venta.objects.create(
            numero_venta='VTA-HIST001', cajero=u,
            subtotal=520, total=520, metodo_pago='efectivo',
            monto_recibido=520, monto_transferencia=0, cambio=0)
        DetalleVenta.objects.create(
            venta=v, producto=prod, presentacion=pres,
            cantidad=1, cantidad_base=1,
            precio_unitario=Decimal('520'), subtotal=Decimal('520'))
        # Mover la venta a ayer (auto_now_add no deja setearlo al crear).
        aware_ayer = timezone.make_aware(
            timezone.datetime.combine(ayer, timezone.datetime.min.time()))
        Venta.objects.filter(pk=v.pk).update(fecha_venta=aware_ayer)
        _sincronizar_inventario_dia(ayer)
        datos = _obtener_datos_ipb(ayer)
        fila = [r for r in datos['reporte'] if r['producto'].pk == prod.pk][0]
        # El ingreso congelado siempre fue 520.
        self.assertEqual(fila['ingreso'], Decimal('520'))
        # El precio mostrado debe ser el del día (520), no el actual (540).
        self.assertEqual(fila['precio_venta'], Decimal('520'))


class HistorialPrecioLogTest(TestCase):
    def test_log_cambio_precio_guarda_antes_despues(self):
        u = User.objects.create_user(username='admin_hist2', password='x')
        prod = Producto.objects.create(
            nombre='Hist Log', unidad_medida='unidades',
            precio_compra=10, precio_venta=Decimal('20'),
            stock=Decimal('10'))
        h = _log_cambio_precio(
            prod, Decimal('10'), Decimal('10'),
            Decimal('20'), Decimal('25'),
            accion='edicion_manual', motivo='sube a 25', usuario=u)
        self.assertIsNotNone(h)
        self.assertEqual(h.precio_venta_antes, Decimal('20'))
        self.assertEqual(h.precio_venta_despues, Decimal('25'))
        self.assertEqual(
            HistorialPrecio.objects.filter(producto=prod).count(), 1)

    def test_log_sin_cambio_no_crea_fila(self):
        u = User.objects.create_user(username='admin_hist3', password='x')
        prod = Producto.objects.create(
            nombre='Hist Log 2', unidad_medida='unidades',
            precio_compra=10, precio_venta=Decimal('20'),
            stock=Decimal('10'))
        h = _log_cambio_precio(
            prod, Decimal('10'), Decimal('10'),
            Decimal('20'), Decimal('20'),
            accion='edicion_manual', motivo='', usuario=u)
        self.assertIsNone(h)
        self.assertEqual(
            HistorialPrecio.objects.filter(producto=prod).count(), 0)


class IpbPorPosPrecioHistoricoTest(TestCase):
    def test_ipb_por_pos_muestra_precio_del_dia(self):
        u = User.objects.create_user(username='caja_pos_hist', password='x')
        alm = Almacen.objects.create(nombre='Almacén POS Hist')
        pos = PuntoVenta.objects.create(nombre='Caja POS Hist', almacen=alm)
        prod = Producto.objects.create(
            nombre='Refresco POS Hist', unidad_medida='unidades',
            precio_compra=470, precio_venta=Decimal('540'),
            stock=Decimal('0'), permite_decimal=False)
        AlmacenStock.objects.create(
            producto=prod, almacen=alm, cantidad=Decimal('10'))
        pres = PresentacionProducto.objects.create(
            producto=prod, nombre='Unidad', factor=1, precio=Decimal('540'),
            es_default=True, activo=True)
        ayer = (ahora_servidor() - timedelta(days=1)).date()
        v = Venta.objects.create(
            numero_venta='VTA-POSHIST1', cajero=u, punto_venta=pos,
            subtotal=520, total=520, metodo_pago='efectivo',
            monto_recibido=520, monto_transferencia=0, cambio=0)
        DetalleVenta.objects.create(
            venta=v, producto=prod, presentacion=pres,
            cantidad=1, cantidad_base=1,
            precio_unitario=Decimal('520'), subtotal=Decimal('520'))
        aware_ayer = timezone.make_aware(
            timezone.datetime.combine(ayer, timezone.datetime.min.time()))
        Venta.objects.filter(pk=v.pk).update(fecha_venta=aware_ayer)
        datos = _obtener_datos_ipb(ayer, punto_venta=pos)
        fila = [r for r in datos['reporte'] if r['producto'].pk == prod.pk][0]
        self.assertEqual(fila['ingreso'], Decimal('520'))
        self.assertEqual(fila['precio_venta'], Decimal('520'))


class SubmayorHistorialPrecioTest(TestCase):
    def test_submayor_muestra_historial_de_precios(self):
        from django.contrib.auth.models import User as _U
        admin = _U.objects.create_user(username='admin_submayor', password='x12345')
        PerfilUsuario.objects.filter(user=admin).update(rol='admin')
        admin.refresh_from_db()
        prod = Producto.objects.create(
            nombre='Submayor Hist', unidad_medida='unidades',
            precio_compra=10, precio_venta=Decimal('25'),
            stock=Decimal('10'))
        HistorialPrecio.objects.create(
            producto=prod,
            precio_compra_antes=Decimal('10'), precio_compra_despues=Decimal('10'),
            precio_venta_antes=Decimal('20'), precio_venta_despues=Decimal('25'),
            accion='edicion_manual', motivo='sube a 25', usuario=admin)
        self.client.login(username='admin_submayor', password='x12345')
        r = self.client.get(reverse('core:submayor_detalle', args=[prod.pk]))
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn('Historial de precios', html)
        self.assertIn('20', html)
        self.assertIn('25', html)

    def test_submayor_historial_sin_usuario_muestra_sistema(self):
        from django.contrib.auth.models import User as _U
        admin = _U.objects.create_user(username='admin_submayor2', password='x12345')
        PerfilUsuario.objects.filter(user=admin).update(rol='admin')
        admin.refresh_from_db()
        prod = Producto.objects.create(
            nombre='Submayor Hist Sin User', unidad_medida='unidades',
            precio_compra=10, precio_venta=Decimal('25'),
            stock=Decimal('10'))
        HistorialPrecio.objects.create(
            producto=prod,
            precio_compra_antes=Decimal('10'), precio_compra_despues=Decimal('10'),
            precio_venta_antes=Decimal('20'), precio_venta_despues=Decimal('25'),
            accion='edicion_manual', motivo='reparación', usuario=None)
        self.client.login(username='admin_submayor2', password='x12345')
        r = self.client.get(reverse('core:submayor_detalle', args=[prod.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertIn('Sistema', r.content.decode())
