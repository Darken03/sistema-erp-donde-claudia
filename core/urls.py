from django.urls import path
from . import views

app_name = 'core'

urlpatterns = [
    # Autenticacion
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('', views.redireccion_rol, name='redireccion_rol'),
    # Dashboard (solo admin)
    path('dashboard/', views.dashboard, name='dashboard'),
    # Productos (solo admin)
    path('productos/', views.producto_lista, name='producto_lista'),
    path('productos/crear/', views.producto_crear, name='producto_crear'),
    path('productos/<int:pk>/', views.producto_detalle, name='producto_detalle'),
    path('productos/<int:pk>/editar/', views.producto_editar, name='producto_editar'),
    path('presentaciones/<int:pk>/eliminar/', views.presentacion_eliminar, name='presentacion_eliminar'),
    path('productos/<int:pk>/imagen/recortar/', views.producto_imagen_recortar, name='producto_imagen_recortar'),
    path('productos/<int:pk>/eliminar-imagen/', views.producto_imagen_eliminar, name='producto_imagen_eliminar'),
    path('productos/<int:pk>/eliminar/', views.producto_eliminar, name='producto_eliminar'),
    path('productos/<int:pk>/eliminar-definitivo/', views.producto_eliminar_definitivo, name='producto_eliminar_definitivo'),
    # Categorias (solo admin)
    path('categorias/', views.categoria_lista, name='categoria_lista'),
    path('categorias/crear/', views.categoria_crear, name='categoria_crear'),
    path('categorias/<int:pk>/editar/', views.categoria_editar, name='categoria_editar'),
    path('categorias/<int:pk>/eliminar/', views.categoria_eliminar, name='categoria_eliminar'),
    # Empleados (solo admin)
    path('empleados/', views.empleado_lista, name='empleado_lista'),
    path('empleados/crear/', views.empleado_crear, name='empleado_crear'),
    path('empleados/<int:pk>/editar/', views.empleado_editar, name='empleado_editar'),
    path('empleados/<int:pk>/eliminar/', views.empleado_eliminar, name='empleado_eliminar'),
    path('empleados/<int:pk>/toggle/', views.empleado_toggle_activo, name='empleado_toggle'),
    path('empleados/<int:pk>/turnos/', views.empleado_turnos, name='empleado_turnos'),
    # Turnos (solo admin)
    path('turnos/<int:pk>/abrir/', views.turno_abrir, name='turno_abrir'),
    path('turnos/<int:pk>/cerrar/', views.turno_cerrar, name='turno_cerrar'),
    # Ventas (solo admin)
    path('ventas/', views.venta_lista, name='venta_lista'),
    path('ventas/crear/', views.venta_crear, name='venta_crear'),
    path('ventas/<int:pk>/', views.venta_detalle, name='venta_detalle'),
    path('ventas/<int:pk>/editar/', views.venta_editar, name='venta_editar'),
    path('ventas/imprimir/', views.venta_impresion, name='venta_impresion'),
    path('ventas/imprimir/<str:fecha>/', views.venta_impresion, name='venta_impresion_fecha'),
# Punto de Venta
    path('pos/', views.pos, name='pos'),
    path('pos/buscar/', views.pos_buscar_productos, name='pos_buscar'),
    path('pos/procesar/', views.pos_procesar_venta, name='pos_procesar'),
    path('pos/mis-ventas/', views.pos_mis_ventas, name='pos_mis_ventas'),
    path('pos/entradas/', views.pos_mis_entradas, name='pos_mis_entradas'),
    path('pos/ping/', views.pos_ping, name='pos_ping'),
    path('pos/catalogo/', views.pos_catalogo, name='pos_catalogo'),
    path('pos/ticket/<int:pk>/', views.pos_ticket, name='pos_ticket'),
    path('pos/registrar-gasto/', views.pos_registrar_gasto, name='pos_registrar_gasto'),
    path('pos/gastos/', views.pos_mis_gastos, name='pos_mis_gastos'),
    # IPB (solo admin)
    path('ipb/', views.ipb, name='ipb'),
    path('ipb/imprimir/', views.ipb_impresion, name='ipb_impresion'),
    path('ipb/imprimir/<str:fecha>/', views.ipb_impresion, name='ipb_impresion_fecha'),
    # Gastos
    path('gastos/', views.gasto_lista, name='gasto_lista'),
    path('gastos/crear/', views.gasto_crear, name='gasto_crear'),
    path('gastos/<int:pk>/editar/', views.gasto_editar, name='gasto_editar'),
    path('gastos/<int:pk>/eliminar/', views.gasto_eliminar, name='gasto_eliminar'),
    # Entradas (historial de solo lectura: el flujo actual es almacén -> traslado;
    # en modo solo-POS el admin crea/elimina entradas directas al POS)
    path('entradas/', views.entrada_lista, name='entrada_lista'),
    path('entradas/crear/', views.entrada_crear, name='entrada_crear'),
    path('entradas/<int:pk>/eliminar/', views.entrada_eliminar, name='entrada_eliminar'),
    # Almacén (admin + almacenero)
    path('almacen/', views.almacen_panel, name='almacen_panel'),
    path('almacen/existencias/', views.almacen_stock, name='almacen_stock'),
    path('almacen/entradas/', views.almacen_entrada_lista, name='almacen_entrada_lista'),
    path('almacen/entradas/nueva/', views.almacen_entrada_crear, name='almacen_entrada_crear'),
    path('almacen/entradas/<int:pk>/cancelar/', views.almacen_entrada_cancelar, name='almacen_entrada_cancelar'),
    path('almacen/traslados/', views.almacen_traslado_lista, name='almacen_traslado_lista'),
    path('almacen/traslados/nuevo/', views.almacen_traslado_crear, name='almacen_traslado_crear'),
    path('almacen/traslados/<int:pk>/cancelar/', views.almacen_traslado_cancelar, name='almacen_traslado_cancelar'),
    path('almacen/movimientos/', views.almacen_movimientos, name='almacen_movimientos'),
    path('almacen/ajuste/', views.almacen_ajuste, name='almacen_ajuste'),
    # Retiros Donacion
    path('donaciones/', views.retiro_donacion_lista, name='retiro_donacion_lista'),
    path('donaciones/crear/', views.retiro_donacion_crear, name='retiro_donacion_crear'),
    path('donaciones/<int:pk>/eliminar/', views.retiro_donacion_eliminar, name='retiro_donacion_eliminar'),
    # Submayor
    path('submayor/', views.submayor_lista, name='submayor_lista'),
    path('submayor/<int:producto_id>/', views.submayor_detalle, name='submayor_detalle'),
    # Deudas
    # Deudores y Deudas
    path('deudores/crear/', views.deudor_crear, name='deudor_crear'),
    path('deudores/<int:pk>/', views.deudor_detalle, name='deudor_detalle'),
    path('deudores/<int:pk>/editar/', views.deudor_editar, name='deudor_editar'),
    path('deudores/<int:pk>/toggle/', views.deudor_toggle, name='deudor_toggle'),
    path('deudores/<int:pk>/abonar/', views.deudor_abonar, name='deudor_abonar'),
    path('deudores/<int:pk>/eliminar/', views.deudor_eliminar, name='deudor_eliminar'),
    path('deudas/', views.deuda_lista, name='deuda_lista'),
    path('deudas/crear/', views.deuda_crear, name='deuda_crear'),
    path('deudas/<int:pk>/editar/', views.deuda_editar, name='deuda_editar'),
    path('deudas/<int:pk>/abonar/', views.deuda_abonar, name='deuda_abonar'),
    path('deudas/<int:pk>/eliminar/', views.deuda_eliminar, name='deuda_eliminar'),
    # POS - Deudores y Deudas (solo online)
    path('pos/deudores/', views.pos_deudores, name='pos_deudores'),
    path('pos/deudor/crear/', views.pos_deudor_crear, name='pos_deudor_crear'),
    path('pos/deudor/<int:pk>/', views.pos_deudor_detalle, name='pos_deudor_detalle'),
    path('pos/deuda/crear/', views.pos_deuda_crear, name='pos_deuda_crear'),
    path('pos/deuda/abonar/', views.pos_deuda_abonar, name='pos_deuda_abonar'),
    # Panel del vendedor + Arqueo de turno + Conteo ciego
    path('mi-panel/', views.mi_panel, name='mi_panel'),
    path('arqueo/', views.arqueo, name='arqueo'),
    path('turnos/<int:pk>/arqueo/confirmar/', views.arqueo_confirmar, name='arqueo_confirmar'),
    path('conteos/', views.conteo_lista, name='conteo_lista'),
    path('conteos/<int:pk>/contar/', views.conteo_contar, name='conteo_contar'),
    path('conteos/<int:pk>/autosave/', views.conteo_autosave, name='conteo_autosave'),
    path('conteos/<int:pk>/cerrar/', views.conteo_cerrar, name='conteo_cerrar'),
    path('conteos/<int:pk>/comparar/', views.conteo_comparar, name='conteo_comparar'),
    # Revisión admin: arqueos + conteos del turno
    path('arqueos/', views.arqueos_admin, name='arqueos_admin'),
    path('turnos/<int:pk>/revisar/', views.revisar_turno, name='revisar_turno'),
    path('turnos/<int:pk>/arqueo/recontar/', views.arqueo_recontar, name='arqueo_recontar'),
    path('conteos/<int:pk>/decidir/', views.conteo_decidir, name='conteo_decidir'),
    # Ajustes de Inventario
    path('ajustes/', views.ajuste_inventario, name='ajuste_inventario'),
    # Mostrador del cliente (pantalla en tiempo real del POS, sin login)
    path('mostrador/', views.mostrador_display, name='mostrador_display'),
    # Catálogo público de la tienda (vitrina web, sin login ni compra)
    path('catalogo/', views.catalogo, name='catalogo'),
    # Vitrina Marketplace /store (existencias exactas en tiempo real, sin login)
    path('store/', views.store, name='store'),
    path('store/buscar/', views.store_buscar, name='store_buscar'),
    path('store/categoria/<int:pk>/', views.store_categoria, name='store_categoria'),
    path('store/api/estado/', views.store_api_estado, name='store_api'),
    path('store/api/producto/<int:pk>/', views.store_producto_detalle, name='store_producto_api'),
    path('mostrador/estado/', views.mostrador_estado, name='mostrador_estado'),
    path('pos/mostrador/empujar/', views.pos_mostrador_empujar, name='pos_mostrador_empujar'),
    path('pos/mostrador/limpiar/', views.pos_mostrador_limpiar, name='pos_mostrador_limpiar'),
    # Configuración (solo admin)
    path('configuracion/', views.configuracion, name='configuracion'),
    path('configuracion/almacenes/crear/', views.config_almacen_crear, name='config_almacen_crear'),
    path('configuracion/almacenes/<int:pk>/editar/', views.config_almacen_editar, name='config_almacen_editar'),
    path('configuracion/almacenes/<int:pk>/toggle/', views.config_almacen_toggle, name='config_almacen_toggle'),
]

