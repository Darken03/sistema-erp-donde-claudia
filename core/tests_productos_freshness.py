"""Regresión: listado de productos fresco, códigos PRD- únicos y aviso al borrar.

Causas que se cubren aquí:
  1) El navegador servía el listado de administración desde su caché/bfcache
     y hacía falta pulsar F5 para ver los cambios.
  2) generar_codigo() miraba el producto con mayor id, no el mayor número de
     código usado: podía devolver un PRD- ya existente (Duplicate entry).
  3) Los mensajes de desactivar/borrar se perdían al volver a una página
     cacheada en vez de al listado recién renderizado.
"""

from pathlib import Path
from unittest.mock import patch

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .models import Producto


def _admin(username):
    u = User.objects.create_user(username=username, password='x12345')
    # La señal guardar_perfil_usuario vuelve a grabar el perfil cacheado en el
    # usuario al iniciar sesión: hay que cambiar esa misma instancia, no solo
    # la fila, o el login lo devuelve a 'cajero' y no pasa requiere_admin.
    u.perfil.rol = 'admin'
    u.perfil.save(update_fields=['rol'])
    u.refresh_from_db()
    return u


class ProductoCodigoTest(TestCase):
    def test_generar_codigo_usa_el_maximo_numero_no_el_ultimo_id(self):
        # Codigo alto creado primero (id menor) y codigo bajo creado después
        # (id mayor): el calculo antiguo devolvia PRD-0350, duplicado.
        Producto.objects.create(codigo='PRD-0350', nombre='Viejo', precio_venta=1)
        Producto.objects.create(codigo='PRD-0349', nombre='Reciente', precio_venta=1)
        self.assertEqual(Producto.generar_codigo(), 'PRD-0351')
        self.assertEqual(
            Producto.objects.create(nombre='Auto', precio_venta=1).codigo,
            'PRD-0351')

    def test_ignora_codigos_que_no_sean_prd_numerico(self):
        Producto.objects.create(codigo='PRD-0007', nombre='Normal', precio_venta=1)
        Producto.objects.create(codigo='PRD-XX', nombre='Raro', precio_venta=1)
        Producto.objects.create(codigo='OTRO-9999', nombre='Otro', precio_venta=1)
        self.assertEqual(Producto.generar_codigo(), 'PRD-0008')

    def test_reintenta_si_otra_operacion_tomo_el_mismo_codigo(self):
        Producto.objects.create(codigo='PRD-0001', nombre='Ocupado', precio_venta=1)
        # Primera lectura devuelve un código ya usado (condición de carrera).
        with patch.object(
                Producto, 'generar_codigo',
                side_effect=['PRD-0001', 'PRD-0002']):
            creado = Producto.objects.create(nombre='Reintentado', precio_venta=1)
        self.assertEqual(creado.codigo, 'PRD-0002')
        self.assertTrue(Producto.objects.filter(codigo='PRD-0002').exists())

    def test_alta_por_formulario_ya_no_da_duplicate_entry(self):
        self.client.force_login(_admin('admin-codigos'))
        Producto.objects.create(codigo='PRD-0350', nombre='Viejo', precio_venta=1)
        Producto.objects.create(codigo='PRD-0349', nombre='Reciente', precio_venta=1)
        r = self.client.post(reverse('core:producto_crear'), {
            'codigo': '', 'nombre': 'Nuevo', 'unidad_medida': 'unidades',
            'precio_compra': '1', 'precio_venta': '2', 'stock': '0',
            'stock_minimo': '0', 'activo': 'on',
        })
        self.assertEqual(r.status_code, 302)
        self.assertTrue(Producto.objects.filter(codigo='PRD-0351').exists())


class ProductoListaFrescoTest(TestCase):
    def setUp(self):
        self.client.force_login(_admin('admin-fresco'))
        self.producto = Producto.objects.create(
            nombre='Café', codigo='PRD-0001', precio_venta=10)

    def test_vistas_de_productos_envian_no_store(self):
        urls = [
            reverse('core:producto_lista'),
            reverse('core:producto_detalle', args=[self.producto.pk]),
            reverse('core:producto_crear'),
            reverse('core:producto_editar', args=[self.producto.pk]),
            reverse('core:producto_eliminar', args=[self.producto.pk]),
            reverse('core:productos_codigos_barras'),
        ]
        for url in urls:
            with self.subTest(url=url):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200)
                cabecera = r['Cache-Control'].lower()
                self.assertIn('no-store', cabecera)
                self.assertIn('no-cache', cabecera)

    def test_plantilla_recarga_al_volver_de_bfcache(self):
        src = (Path(__file__).resolve().parent.parent
               / 'templates' / 'core' / 'producto_lista.html').read_text(
                   encoding='utf-8')
        self.assertIn('pageshow', src)
        self.assertIn('e.persisted', src)
        self.assertIn('location.reload()', src)

    def test_listado_muestra_lo_cambiado_tras_crear_editar_y_borrar(self):
        # Crear: el producto nuevo aparece en el listado al seguir el redirect.
        r = self.client.post(reverse('core:producto_crear'), {
            'codigo': '', 'nombre': 'Té', 'unidad_medida': 'unidades',
            'precio_compra': '1', 'precio_venta': '3', 'stock': '0',
            'stock_minimo': '0', 'activo': 'on',
        }, follow=True)
        self.assertContains(r, 'PRD-0002')
        self.assertContains(r, 'Té')

        # Editar: el nombre nuevo se ve sin F5.
        r = self.client.post(
            reverse('core:producto_editar', args=[self.producto.pk]), {
                'codigo': 'PRD-0001', 'nombre': 'Café molido',
                'unidad_medida': 'unidades', 'precio_compra': '1',
                'precio_venta': '11', 'stock': '0', 'stock_minimo': '0',
                'activo': 'on',
            }, follow=True)
        self.assertContains(r, 'Café molido')

        # Borrar en 2 pasos: aviso de desactivado y luego de eliminado.
        r = self.client.post(
            reverse('core:producto_eliminar', args=[self.producto.pk]),
            follow=True)
        self.assertContains(r, 'desactivado')
        r = self.client.post(
            reverse('core:producto_eliminar', args=[self.producto.pk]),
            {'confirmacion': 'ELIMINAR'}, follow=True)
        self.assertContains(r, 'eliminado definitivamente')
        self.assertFalse(Producto.objects.filter(pk=self.producto.pk).exists())
