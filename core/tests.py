from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils import timezone
from .models import (
    Empleado, PerfilUsuario, Producto, Turno, Venta, Gasto,
    ArqueoTurno, ConteoCiego, ConteoCiegoLinea,
)


def _usuario(username, rol='cajero'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    # Sin esto, la caché de u.perfil (rol viejo) revierte el update al guardar u.
    u.refresh_from_db()
    return u


class ArqueoConteoTest(TestCase):
    def setUp(self):
        self.cajero = _usuario('cajero1')
        self.admin = _usuario('admin1', 'admin')
        self.admin.is_staff = True
        self.admin.is_superuser = True
        self.admin.save()
        self.empleado = Empleado.objects.create(user=self.cajero, salario=0, activo=True)
        self.turno = Turno.objects.create(empleado=self.empleado)
        self.prod = Producto.objects.create(
            nombre='Cafe', unidad_medida='unidades', precio_compra=10,
            precio_venta=20, stock=Decimal('100'), permite_decimal=False)
        # Venta del turno: 2 x $20 en efectivo, paga $50 → vuelto $10.
        self.venta = Venta.objects.create(
            numero_venta='VTA-000001', cajero=self.cajero, turno=self.turno,
            subtotal=40, total=40, metodo_pago='efectivo',
            monto_recibido=50, monto_transferencia=0, cambio=10)
        Gasto.objects.create(
            numero_gasto='GST-000001', cajero=self.cajero, turno=self.turno,
            cantidad_efectivo=5, cantidad_transferencia=0, categoria='caja')

    def test_mi_panel_cajero_ok_y_admin_rebota(self):
        self.client.login(username='cajero1', password='x12345')
        r = self.client.get(reverse('core:mi_panel'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Arqueo de turno')
        self.client.login(username='admin1', password='x12345')
        r = self.client.get(reverse('core:mi_panel'))
        self.assertEqual(r.status_code, 302)
        self.assertTrue(r.url.endswith('/dashboard/'))

    def test_arqueo_paso1_y_paso2_cuadrado(self):
        self.client.login(username='cajero1', password='x12345')
        # Paso 1: fondo 100. Esperado ef = (50-10) - 5 + 100 = 135.
        r = self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '100'})
        self.assertEqual(r.status_code, 302)
        arq = ArqueoTurno.objects.get(turno=self.turno)
        self.assertTrue(arq.paso1_listo)
        self.assertEqual(arq.esperado_efectivo, Decimal('135'))
        # Paso 2: declara 1x$100 + 1x$20 + 3x$5 = 135, tr 0 → cuadra sin motivo.
        r = self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_100': '1', 'denom_20': '1',
            'denom_5M': '3', 'contado_transferencia': '0', 'observacion': '',
        })
        self.assertEqual(r.status_code, 302)
        arq.refresh_from_db()
        self.assertEqual(arq.estado, 'declarado')
        self.assertEqual(arq.contado_efectivo, Decimal('135'))
        self.assertEqual(arq.diferencia_total, Decimal('0'))

    def test_arqueo_exige_motivo_si_descuadra(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        # Declara 30 vs esperado 35 → falta 5 sin motivo: se rechaza.
        r = self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '1', 'denom_10': '1',
            'contado_transferencia': '0', 'observacion': '',
        })
        self.assertEqual(r.status_code, 200)
        arq = ArqueoTurno.objects.get(turno=self.turno)
        self.assertEqual(arq.estado, 'borrador')
        # Con motivo sí declara.
        r = self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '1', 'denom_10': '1',
            'contado_transferencia': '0', 'observacion': 'Faltan $5',
        })
        self.assertEqual(r.status_code, 302)
        arq.refresh_from_db()
        self.assertEqual(arq.estado, 'declarado')
        self.assertEqual(arq.diferencia_total, Decimal('-5'))

    def test_confirmar_cierra_turno(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '1', 'denom_10': '1',
            'denom_5M': '1', 'contado_transferencia': '0', 'observacion': '',
        })
        self._conteo_cerrado_decidido()
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]),
                             {'decision': 'aceptar', 'decision_nota': ''})
        self.assertEqual(r.status_code, 302)
        self.turno.refresh_from_db()
        self.assertFalse(self.turno.abierto)
        self.assertEqual(self.turno.arqueo.estado, 'confirmado')
        self.assertEqual(self.turno.arqueo.decision, 'aceptar')

    def _conteo_cerrado_decidido(self, cantidad='98', decision='ajustado'):
        conteo = ConteoCiego.objects.create(
            turno=self.turno, creado_por=self.cajero, estado='cerrado',
            fecha_cierre=timezone.now(), decision=decision,
            decidido_por=self.admin)
        ConteoCiegoLinea.objects.create(
            conteo=conteo, producto=self.prod, cantidad=Decimal(cantidad),
            stock_sistema=self.prod.stock)
        return conteo

    def test_confirmar_exige_decision(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '1', 'denom_10': '1',
            'denom_5M': '1', 'contado_transferencia': '0', 'observacion': '',
        })
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]), {})
        self.assertEqual(r.status_code, 302)
        self.turno.refresh_from_db()
        self.assertTrue(self.turno.abierto)

    def test_faltante_como_gasto(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        # Esperado 35, declara 30 → faltan 5.
        self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '1', 'denom_10': '1',
            'contado_transferencia': '0', 'observacion': 'Faltan $5',
        })
        self._conteo_cerrado_decidido()
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]),
                             {'decision': 'gasto', 'decision_nota': 'Se registra'})
        self.assertEqual(r.status_code, 302)
        from .models import Gasto as _G
        g = _G.objects.filter(turno=self.turno, categoria='caja').first()
        self.assertIsNotNone(g)
        self.assertEqual(g.cantidad_efectivo, Decimal('5'))
        self.turno.refresh_from_db()
        self.assertFalse(self.turno.abierto)

    def test_gasto_rechazado_si_hay_sobrante(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        # Esperado 35, declara 40 → sobran 5.
        self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '2',
            'contado_transferencia': '0', 'observacion': 'Sobra',
        })
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]),
                             {'decision': 'gasto', 'decision_nota': ''})
        self.assertEqual(r.status_code, 302)
        self.turno.refresh_from_db()
        self.assertTrue(self.turno.abierto)

    def test_admin_revisa_turno_y_conteo(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        self.client.post(reverse('core:conteo_lista'))
        conteo = ConteoCiego.objects.get(turno=self.turno)
        self.client.post(reverse('core:conteo_contar', args=[conteo.pk]),
                         {'cant_%d' % self.prod.pk: '98'})
        self.client.post(reverse('core:conteo_cerrar', args=[conteo.pk]))
        self.client.login(username='admin1', password='x12345')
        r = self.client.get(reverse('core:arqueos_admin'))
        self.assertEqual(r.status_code, 200)
        r = self.client.get(reverse('core:revisar_turno', args=[self.turno.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Conteo #')
        # Ajustar: el sistema pasa de 100 a 98 + movimiento de ajuste.
        r = self.client.post(reverse('core:conteo_decidir', args=[conteo.pk]),
                             {'accion': 'ajustar', 'decision_nota': 'ok'})
        self.assertEqual(r.status_code, 302)
        self.prod.refresh_from_db()
        self.assertEqual(self.prod.stock, Decimal('98'))
        from .models import MovimientoInventario as _M
        self.assertTrue(_M.objects.filter(
            producto=self.prod, tipo='ajuste',
            descripcion__contains='conteo ciego').exists())
        conteo.refresh_from_db()
        self.assertEqual(conteo.decision, 'ajustado')
        # La ficha de hoy queda anclada al final contado (98), no al revés.
        from .models import InventarioDiario as _ID
        from datetime import date as _date
        inv = _ID.objects.filter(fecha=_date.today(), producto=self.prod).first()
        if inv is not None:
            self.assertEqual(inv.stock_final, Decimal('98'))

    def test_reconteo_reabre_a_ciegas(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post(reverse('core:conteo_lista'))
        conteo = ConteoCiego.objects.get(turno=self.turno)
        self.client.post(reverse('core:conteo_contar', args=[conteo.pk]),
                         {'cant_%d' % self.prod.pk: '50'})
        self.client.post(reverse('core:conteo_cerrar', args=[conteo.pk]))
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:conteo_decidir', args=[conteo.pk]),
                             {'accion': 'recontar', 'decision_nota': 'dudoso'})
        self.assertEqual(r.status_code, 302)
        conteo.refresh_from_db()
        self.assertEqual(conteo.estado, 'abierto')
        self.assertIsNone(conteo.lineas.first().stock_sistema)

    def test_cajero_no_entra_a_revision_admin(self):
        self.client.login(username='cajero1', password='x12345')
        r = self.client.get(reverse('core:arqueos_admin'))
        self.assertEqual(r.status_code, 302)

    def test_eliminar_empleado_con_ventas_lo_desactiva(self):
        # cajero1 tiene una venta: borrarlo debe desactivarlo, sin error 500.
        emp_id = self.empleado.pk
        user_id = self.cajero.pk
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:empleado_eliminar', args=[emp_id]))
        self.assertEqual(r.status_code, 302)
        self.empleado.refresh_from_db()
        self.cajero.refresh_from_db()
        self.assertFalse(self.empleado.activo)
        self.assertFalse(self.cajero.is_active)
        # Y ya no puede loguearse.
        self.client.logout()
        self.assertFalse(self.client.login(username='cajero1', password='x12345'))

    def test_eliminar_empleado_sin_movimientos_lo_borra(self):
        otro = User.objects.create_user(username='temporal', password='x12345')
        PerfilUsuario.objects.filter(user=otro).update(rol='cajero')
        emp = Empleado.objects.create(user=otro, salario=0, activo=True)
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:empleado_eliminar', args=[emp.pk]))
        self.assertEqual(r.status_code, 302)
        self.assertFalse(User.objects.filter(pk=otro.pk).exists())
        self.assertFalse(Empleado.objects.filter(pk=emp.pk).exists())

    def _declarar_cuadrado(self):
        self.client.login(username='cajero1', password='x12345')
        self.client.post('/arqueo/', {'action': 'fondo', 'fondo_inicial': '0'})
        self.client.post('/arqueo/', {
            'action': 'declarar', 'denom_20': '1', 'denom_10': '1',
            'denom_5M': '1', 'contado_transferencia': '0', 'observacion': '',
        })
        self.client.login(username='admin1', password='x12345')

    def test_no_cierra_sin_conteo_fisico(self):
        self._declarar_cuadrado()
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]),
                             {'decision': 'aceptar', 'decision_nota': ''})
        self.assertEqual(r.status_code, 302)
        self.turno.refresh_from_db()
        self.assertTrue(self.turno.abierto)
        # Vía rápida tampoco.
        r = self.client.post(reverse('core:turno_cerrar', args=[self.empleado.pk]))
        self.turno.refresh_from_db()
        self.assertTrue(self.turno.abierto)

    def test_no_cierra_con_conteo_abierto_ni_sin_decidir(self):
        self._declarar_cuadrado()
        conteo = ConteoCiego.objects.create(turno=self.turno, creado_por=self.cajero)
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]),
                             {'decision': 'aceptar', 'decision_nota': ''})
        self.turno.refresh_from_db()
        self.assertTrue(self.turno.abierto)
        # Cerrado pero sin decisión del admin: sigue bloqueado.
        conteo.estado = 'cerrado'
        conteo.fecha_cierre = timezone.now()
        conteo.save()
        ConteoCiegoLinea.objects.create(
            conteo=conteo, producto=self.prod, cantidad=Decimal('100'),
            stock_sistema=self.prod.stock)
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]),
                             {'decision': 'aceptar', 'decision_nota': ''})
        self.turno.refresh_from_db()
        self.assertTrue(self.turno.abierto)
        # Decidido (aceptado): ahora sí cierra.
        conteo.decision = 'aceptado'
        conteo.decidido_por = self.admin
        conteo.save()
        r = self.client.post(reverse('core:arqueo_confirmar', args=[self.turno.pk]),
                             {'decision': 'aceptar', 'decision_nota': ''})
        self.turno.refresh_from_db()
        self.assertFalse(self.turno.abierto)

    def test_no_cierra_sin_arqueo(self):
        self.client.login(username='admin1', password='x12345')
        r = self.client.post(reverse('core:turno_cerrar', args=[self.empleado.pk]))
        self.assertEqual(r.status_code, 302)
        self.turno.refresh_from_db()
        self.assertTrue(self.turno.abierto)

    def test_conteo_ciego_flujo(self):
        self.client.login(username='cajero1', password='x12345')
        # La pantalla de contar NO muestra el stock.
        r = self.client.post(reverse('core:conteo_lista'))
        conteo = ConteoCiego.objects.get(turno=self.turno)
        r = self.client.get(reverse('core:conteo_contar', args=[conteo.pk]))
        self.assertEqual(r.status_code, 200)
        # A ciegas: sin stock ni cantidades del sistema (solo código/nombre/unidad).
        self.assertNotContains(r, 'Stock')
        self.assertNotContains(r, 'value="100"')
        # Anota 98 (sistema tiene 100).
        r = self.client.post(
            reverse('core:conteo_contar', args=[conteo.pk]),
            {'cant_%d' % self.prod.pk: '98'})
        self.assertEqual(r.status_code, 302)
        # Comparar antes de cerrar lo devuelve a contar.
        r = self.client.get(reverse('core:conteo_comparar', args=[conteo.pk]))
        self.assertEqual(r.status_code, 302)
        # Cierra: congela sistema=100 y compara dif=-2.
        r = self.client.post(reverse('core:conteo_cerrar', args=[conteo.pk]))
        self.assertEqual(r.status_code, 302)
        r = self.client.get(reverse('core:conteo_comparar', args=[conteo.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '-2')
