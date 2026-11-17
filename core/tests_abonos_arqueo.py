"""Pruebas del módulo Abonado (deudas) y del arqueo con deudas cobradas aparte."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import (
    AbonoDeuda, ArqueoTurno, Deuda, Deudor, Empleado, Gasto, PerfilUsuario,
    Turno, Venta,
)
from .views import _aplicar_abono_deudor, _resumen_turno


def _usuario(username, rol='cajero'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    u.refresh_from_db()
    return u


class AbonosArqueoTest(TestCase):
    def setUp(self):
        self.cajero = _usuario('cajero1')
        self.admin = _usuario('admin1', 'admin')
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.save()
        self.empleado = Empleado.objects.create(user=self.cajero, salario=0, activo=True)
        self.turno = Turno.objects.create(empleado=self.empleado)
        self.deudor = Deudor.objects.create(nombre='Ana', apellido='Perez', ci='900101')
        self.deuda = Deuda.objects.create(
            numero_deuda='DEU-000001', deudor=self.deudor, tipo='dinero',
            monto=Decimal('100'), registrada_por=self.cajero)
        # Venta del turno: 2 x $20 en efectivo, paga $50 → vuelto $10.
        Venta.objects.create(
            numero_venta='VTA-000001', cajero=self.cajero, turno=self.turno,
            subtotal=40, total=40, metodo_pago='efectivo',
            monto_recibido=50, monto_transferencia=0, cambio=10)
        Gasto.objects.create(
            numero_gasto='GST-000001', cajero=self.cajero, turno=self.turno,
            cantidad_efectivo=5, cantidad_transferencia=0, categoria='caja')

    def _abono(self, monto, metodo='efectivo'):
        return AbonoDeuda.objects.create(
            deuda=self.deuda, turno=self.turno, monto=Decimal(monto),
            metodo=metodo, registrada_por=self.cajero)

    def test_abono_deudor_guarda_turno_del_cajero(self):
        self._abono('10')
        aplicados = _aplicar_abono_deudor(
            self.deudor, Decimal('30'), 'efectivo', '', self.cajero)
        self.assertEqual(len(aplicados), 1)
        nuevo = AbonoDeuda.objects.order_by('-id').first()
        self.assertEqual(nuevo.monto, Decimal('30'))
        self.assertEqual(nuevo.turno_id, self.turno.pk)

    def test_resumen_turno_incluye_deudas_aparte(self):
        self._abono('20', 'efectivo')
        self._abono('10', 'transferencia')
        resumen = _resumen_turno(self.turno)
        # Ventas/gastos intactos: (50 − 10) − 5 = 35 en efectivo.
        self.assertEqual(resumen['esperado_efectivo'], Decimal('35'))
        self.assertEqual(resumen['esperado_transferencia'], Decimal('0'))
        self.assertEqual(resumen['deudas_cobradas'], Decimal('30'))
        self.assertEqual(resumen['deudas_efectivo'], Decimal('20'))
        self.assertEqual(resumen['deudas_transferencia'], Decimal('10'))
        self.assertEqual(resumen['num_deudas_cobradas'], 2)

    def test_arqueo_declarar_guarda_deudas_y_sigue_ciego(self):
        self._abono('30')
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        r = self.client.get('/arqueo/?paso=2')
        self.assertEqual(r.status_code, 200)
        self.assertNotContains(r, 'esperado')
        self.assertNotContains(r, 'Esperado')
        self.assertNotContains(r, 'Diferencia')
        r = self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '1', 'denom_10': '1',
            'contado_transferencia': '0', 'contado_deudas': '30',
            'observacion': '',
        })
        self.assertEqual(r.status_code, 302)
        arq = ArqueoTurno.objects.get(turno=self.turno)
        self.assertEqual(arq.estado, 'declarado')
        self.assertEqual(arq.contado_efectivo, Decimal('30'))
        self.assertEqual(arq.contado_deudas, Decimal('30'))
        self.assertEqual(arq.esperado_deudas, Decimal('30'))
        self.assertEqual(arq.diferencia_deudas, Decimal('0'))
        # La pantalla de espera tampoco revela el cálculo del sistema.
        r = self.client.get('/arqueo/?paso=2')
        self.assertNotContains(r, 'esperado')
        self.assertNotContains(r, 'Esperado')
        self.assertNotContains(r, 'Diferencia')

    def test_abono_lista_solo_admin(self):
        self._abono('15')
        self.client.login(username='cajero1', password='x12345')
        r = self.client.get(reverse('core:abono_lista'))
        self.assertEqual(r.status_code, 302)
        self.client.login(username='admin1', password='x12345')
        r = self.client.get(reverse('core:abono_lista'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Ana Perez')
        self.assertContains(r, '15.00')
