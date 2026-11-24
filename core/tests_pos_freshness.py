"""Regresión: el POS no debe mostrar saldos/ventas atrasados tras deuda o abono.

El origen del bug era doble:
  1) el navegador/tablet servía algunos JSON del POS desde su caché;
  2) registrar una deuda no refrescaba los paneles dependientes.
Ambas cosas quedan blindadas por las pruebas de abajo.
"""

import json
import re
from decimal import Decimal
from pathlib import Path

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Deudor, Empleado, PerfilUsuario, Turno


def _usuario(username, rol='cajero'):
    u = User.objects.create_user(username=username, password='x12345')
    PerfilUsuario.objects.filter(user=u).update(rol=rol)
    return u


class PosDatosFrescosTest(TestCase):
    def setUp(self):
        self.cajero = _usuario('cajero-fresco')
        self.empleado = Empleado.objects.create(user=self.cajero, salario=0, activo=True)
        self.turno = Turno.objects.create(empleado=self.empleado)
        self.deudor = Deudor.objects.create(
            nombre='Ana', apellido='Perez', ci='900101')
        self.client.login(username='cajero-fresco', password='x12345')

    def _crear_deuda(self, monto='100'):
        r = self.client.post(
            reverse('core:pos_deuda_crear'),
            data=json.dumps({
                'deudor_id': self.deudor.pk,
                'dinero': [{'monto': monto, 'motivo': 'préstamo'}],
                'items': [],
            }),
            content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def _abonar(self, monto='40'):
        r = self.client.post(
            reverse('core:pos_deuda_abonar'),
            data=json.dumps({
                'deudor_id': self.deudor.pk, 'monto': monto,
                'metodo': 'efectivo', 'nota': '',
            }),
            content_type='application/json')
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def test_todos_los_json_del_pos_son_no_store(self):
        urls = [
            reverse('core:pos_deudores'),
            reverse('core:pos_deudor_detalle', args=[self.deudor.pk]),
            reverse('core:pos_deudor_historico', args=[self.deudor.pk]),
            reverse('core:pos_mis_ventas'),
            reverse('core:pos_mis_entradas'),
            reverse('core:pos_catalogo'),
        ]
        for url in urls:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                cabecera = r['Cache-Control'].lower()
                self.assertIn('no-store', cabecera)
                self.assertIn('no-cache', cabecera)
                self.assertIn('must-revalidate', cabecera)

        # El escáner reporta 404/400 cuando el código no existe, pero la
        # respuesta de error tampoco debe ser cacheada por la tablet.
        r = self.client.get(reverse('core:pos_buscar_codigo'), {'codigo': 'NADA'})
        self.assertIn(r.status_code, (400, 404))
        self.assertIn('no-store', r['Cache-Control'].lower())

    def test_saldos_se_ven_actualizados_tras_crear_deuda_y_abonar(self):
        resp = self._crear_deuda('100')
        self.assertEqual(Decimal(resp['saldo_deudor']), Decimal('100'))
        r = self.client.get(reverse('core:pos_deudores'))
        self.assertEqual(Decimal(r.json()['deudores'][0]['saldo']), Decimal('100'))
        r = self.client.get(reverse('core:pos_deudor_detalle', args=[self.deudor.pk]))
        self.assertEqual(Decimal(r.json()['saldo']), Decimal('100'))

        resp = self._abonar('40')
        self.assertEqual(Decimal(resp['saldo_deudor']), Decimal('60'))
        r = self.client.get(reverse('core:pos_deudores'))
        self.assertEqual(Decimal(r.json()['deudores'][0]['saldo']), Decimal('60'))
        r = self.client.get(reverse('core:pos_deudor_detalle', args=[self.deudor.pk]))
        self.assertEqual(Decimal(r.json()['saldo']), Decimal('60'))
        r = self.client.get(reverse('core:pos_deudor_historico', args=[self.deudor.pk]))
        self.assertEqual(Decimal(r.json()['total_saldo']), Decimal('60'))

    def test_plantilla_usa_helper_y_refresca_tras_cada_operacion(self):
        src = (Path(__file__).resolve().parent.parent
               / 'templates' / 'core' / 'pos.html').read_text(encoding='utf-8')
        for url in ('URL_PING', 'URL_CATALOGO', 'URL_MISVENTAS',
                    'URL_MISENTRADAS', 'URL_DEUDORES', 'URL_DEUDOR_DET',
                    'URL_DEUDOR_HIST'):
            with self.subTest(url=url):
                self.assertRegex(src, r'posFetchJSON\(' + re.escape(url))
        for handler in ('registrarDeudaPOS', 'liquidarDeudaPOS'):
            inicio = src.index('async function ' + handler)
            fin = src.index('\n}', inicio)
            self.assertIn('refrescarPos(', src[inicio:fin])
