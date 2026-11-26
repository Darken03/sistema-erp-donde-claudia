"""Regresión: filtro de ventas por tipo de operación (efectivo/transferencia/mixto)."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Venta


class VentasFiltroMetodoTest(TestCase):
    def setUp(self):
        admin = User.objects.create_user(username='admin-ventas', password='x')
        admin.perfil.rol = 'admin'
        admin.perfil.save(update_fields=['rol'])
        admin.refresh_from_db()
        self.client.force_login(admin)
        cajero = User.objects.create_user(username='caja-filtro', password='x')

        self.efectivo = Venta.objects.create(
            numero_venta='VTA-FIL-001', cajero=cajero,
            subtotal=100, total=100, metodo_pago='efectivo',
            monto_recibido=100, monto_transferencia=0, cambio=0)
        self.transferencia = Venta.objects.create(
            numero_venta='VTA-FIL-002', cajero=cajero,
            subtotal=200, total=200, metodo_pago='transferencia',
            monto_recibido=0, monto_transferencia=200, cambio=0)
        self.mixto = Venta.objects.create(
            numero_venta='VTA-FIL-003', cajero=cajero,
            subtotal=300, total=300, metodo_pago='mixto',
            monto_recibido=100, monto_transferencia=200, cambio=0)
        self.hoy = timezone.localdate().strftime('%Y-%m-%d')
        self.url = reverse('core:venta_lista')

    def _listar(self, metodo=''):
        return self.client.get(self.url, {
            'fecha': self.hoy, 'metodo': metodo,
        })

    def test_sin_filtro_aparecen_las_tres_operaciones(self):
        r = self._listar()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['resumen_cantidad'], 3)
        self.assertEqual(len(list(r.context['ventas'])), 3)
        self.assertContains(r, 'Tipo de operación')
        for label in ('Efectivo', 'Transferencia', 'Mixto'):
            with self.subTest(label=label):
                self.assertContains(r, label)

    def test_filtro_por_cada_tipo_de_operacion(self):
        casos = (
            ('efectivo', self.efectivo, Decimal('100'), Decimal('100'), Decimal('0')),
            ('transferencia', self.transferencia, Decimal('200'), Decimal('0'), Decimal('200')),
            ('mixto', self.mixto, Decimal('300'), Decimal('100'), Decimal('200')),
        )
        for metodo, esperada, total, efectivo, transferencia in casos:
            with self.subTest(metodo=metodo):
                r = self._listar(metodo)
                self.assertEqual(r.status_code, 200)
                filas = list(r.context['ventas'])
                self.assertEqual([v.pk for v in filas], [esperada.pk])
                self.assertEqual(r.context['resumen_cantidad'], 1)
                self.assertEqual(r.context['resumen_total'], total)
                self.assertEqual(r.context['resumen_efectivo'], efectivo)
                self.assertEqual(r.context['resumen_transferencia'], transferencia)
                self.assertContains(r, esperada.numero_venta)

    def test_valor_desconocido_no_filtra(self):
        r = self._listar('chocolate')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context['resumen_cantidad'], 3)
        self.assertEqual(r.context['metodo_filtro'], '')

    def test_el_pdf_respeta_el_filtro(self):
        r = self.client.get(
            reverse('core:venta_impresion'),
            {'fecha': self.hoy, 'metodo': 'transferencia'})
        self.assertEqual(r.status_code, 200)
