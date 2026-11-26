"""Regresión: editar/cancelar deudas ajusta el stock como corresponde."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    AbonoDeuda, Deuda, Deudor, MovimientoInventario,
    PresentacionProducto, Producto,
)
from .views import _crear_deuda


class DeudasEdicionStockTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username='admin-deudas', password='x')
        self.admin.perfil.rol = 'admin'
        self.admin.perfil.save(update_fields=['rol'])
        self.admin.refresh_from_db()
        self.client.force_login(self.admin)

        self.deudor = Deudor.objects.create(
            nombre='Ana', apellido='Perez', ci='900101')
        self.prod = Producto.objects.create(
            nombre='Cafe', codigo='PRD-0001', unidad_medida='lb',
            precio_compra=10, precio_venta=20, stock=Decimal('100'),
            permite_decimal=True)
        self.pres = PresentacionProducto.objects.create(
            producto=self.prod, nombre='Libra', factor=Decimal('1'),
            precio=Decimal('20'), es_default=True, activo=True)
        self.deuda = _crear_deuda(
            self.deudor, 'producto', self.admin,
            producto=self.prod, cantidad=Decimal('3'))
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('97.000'))

    def _editar(self, datos):
        return self.client.post(
            reverse('core:deuda_editar', args=[self.deuda.pk]), datos)

    def test_cancelar_devuelve_el_stock_y_deja_el_movimiento(self):
        r = self.client.get(
            reverse('core:deuda_eliminar', args=[self.deuda.pk]))
        self.assertContains(r, 'Se devolverán')

        r = self.client.post(
            reverse('core:deuda_eliminar', args=[self.deuda.pk]))
        self.assertEqual(r.status_code, 302)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('100.000'))
        self.assertFalse(Deuda.objects.filter(pk=self.deuda.pk).exists())
        self.assertTrue(MovimientoInventario.objects.filter(
            tipo='devolucion', referencia_id=self.deuda.pk).exists())

    def test_no_se_puede_cancelar_si_tiene_abonos_y_no_toca_stock(self):
        AbonoDeuda.objects.create(
            deuda=self.deuda, monto=Decimal('10'), metodo='efectivo',
            registrada_por=self.admin)
        r = self.client.post(
            reverse('core:deuda_eliminar', args=[self.deuda.pk]))
        self.assertEqual(r.status_code, 302)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('97.000'))
        self.assertTrue(Deuda.objects.filter(pk=self.deuda.pk).exists())

    def test_editar_cantidad_devuelve_lo_viejo_y_descuenta_lo_nuevo(self):
        r = self._editar({
            'producto': self.prod.pk, 'presentacion': self.pres.pk,
            'cantidad': '5', 'motivo': '', 'fecha_pago': '',
        })
        self.assertEqual(r.status_code, 302)
        self.deuda.refresh_from_db()
        self.prod.refresh_from_db()
        self.assertEqual(self.deuda.cantidad, Decimal('5.000'))
        self.assertEqual(self.deuda.cantidad_base, Decimal('5.000'))
        self.assertEqual(self.deuda.monto, Decimal('100.00'))
        self.assertEqual(self.prod.stock, Decimal('95.000'))
        self.assertIn('5 x Libra', self.deuda.motivo)

    def test_editar_a_otro_producto_devuelve_stock_del_anterior(self):
        otro = Producto.objects.create(
            nombre='Azucar', codigo='PRD-0002', unidad_medida='lb',
            precio_venta=10, stock=Decimal('50'), permite_decimal=True)
        pres2 = PresentacionProducto.objects.create(
            producto=otro, nombre='Libra', factor=Decimal('1'),
            precio=Decimal('10'), es_default=True, activo=True)

        r = self._editar({
            'producto': otro.pk, 'presentacion': pres2.pk,
            'cantidad': '2', 'motivo': 'nota', 'fecha_pago': '',
        })
        self.assertEqual(r.status_code, 302)
        self.deuda.refresh_from_db()
        self.prod.refresh_from_db()
        otro.refresh_from_db()
        self.assertEqual(self.deuda.producto_id, otro.pk)
        self.assertEqual(self.deuda.monto, Decimal('20.00'))
        self.assertEqual(self.prod.stock, Decimal('100.000'))
        self.assertEqual(otro.stock, Decimal('48.000'))

    def test_editar_sin_stock_suficiente_no_cambia_nada(self):
        r = self._editar({
            'producto': self.prod.pk, 'presentacion': self.pres.pk,
            'cantidad': '500', 'motivo': '', 'fecha_pago': '',
        })
        self.assertEqual(r.status_code, 302)
        self.deuda.refresh_from_db()
        self.prod.refresh_from_db()
        self.assertEqual(self.deuda.cantidad, Decimal('3.000'))
        self.assertEqual(self.prod.stock, Decimal('97.000'))

    def test_editar_deuda_de_dinero_con_abono_percambia_el_monto(self):
        deuda = _crear_deuda(
            self.deudor, 'dinero', self.admin, monto=Decimal('100'))
        AbonoDeuda.objects.create(
            deuda=deuda, monto=Decimal('30'), metodo='efectivo',
            registrada_por=self.admin)
        r = self.client.post(
            reverse('core:deuda_editar', args=[deuda.pk]), {
                'monto': '150', 'motivo': 'préstamo', 'fecha_pago': '',
            })
        self.assertEqual(r.status_code, 302)
        deuda.refresh_from_db()
        self.assertEqual(deuda.monto, Decimal('150.00'))
        self.assertEqual(deuda.motivo, 'préstamo')
