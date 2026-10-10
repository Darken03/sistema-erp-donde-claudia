from django.test import TestCase
from django.contrib.auth.models import User
from django.urls import reverse
from .models import ConfiguracionTienda, PerfilUsuario
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
