from django.contrib import admin
from .models import Producto, Categoria, PerfilUsuario, Venta, DetalleVenta, Empleado, Turno, Deudor, Deuda, AbonoDeuda, PresentacionProducto, MostradorEstado, ArqueoTurno, ConteoCiego, ConteoCiegoLinea, Almacen, ConfiguracionTienda, AlmacenStock, AlmacenEntrada, AlmacenTraslado, AlmacenMovimiento


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'descripcion', 'fecha_creacion']
    search_fields = ['nombre']
    ordering = ['nombre']


@admin.register(Producto)
class ProductoAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'categoria', 'precio_compra', 'precio_venta', 'stock', 'permite_decimal', 'activo']
    list_filter = ['activo', 'categoria', 'permite_decimal']
    search_fields = ['codigo', 'nombre']
    list_editable = ['precio_venta', 'activo']
    ordering = ['nombre']


class PresentacionProductoInline(admin.TabularInline):
    model = PresentacionProducto
    extra = 1
    fields = ['nombre', 'factor', 'precio', 'es_default', 'activo']


ProductoAdmin.inlines = [PresentacionProductoInline]


@admin.register(PresentacionProducto)
class PresentacionProductoAdmin(admin.ModelAdmin):
    list_display = ['producto', 'nombre', 'factor', 'precio', 'es_default', 'activo']
    list_filter = ['activo', 'es_default']
    search_fields = ['producto__nombre', 'nombre']


@admin.register(PerfilUsuario)
class PerfilUsuarioAdmin(admin.ModelAdmin):
    list_display = ['user', 'rol', 'telefono', 'activo']
    list_filter = ['rol', 'activo']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']


@admin.register(Empleado)
class EmpleadoAdmin(admin.ModelAdmin):
    list_display = ['user', 'salario', 'activo', 'en_turno', 'fecha_contratacion']
    list_filter = ['activo']
    search_fields = ['user__username', 'user__first_name', 'user__last_name']


@admin.register(Turno)
class TurnoAdmin(admin.ModelAdmin):
    list_display = ['empleado', 'fecha_apertura', 'fecha_cierre', 'abierto', 'total_ventas', 'num_ventas']
    list_filter = ['abierto', 'fecha_apertura']
    search_fields = ['empleado__user__first_name']


@admin.register(Deudor)
class DeudorAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'apellido', 'ci', 'telefono', 'activo']
    list_filter = ['activo']
    search_fields = ['nombre', 'apellido', 'ci']
    ordering = ['nombre', 'apellido']


class AbonoDeudaInline(admin.TabularInline):
    model = AbonoDeuda
    extra = 0
    readonly_fields = ['deuda', 'monto', 'metodo', 'nota', 'fecha', 'registrada_por']


@admin.register(Deuda)
class DeudaAdmin(admin.ModelAdmin):
    list_display = ['numero_deuda', 'deudor', 'tipo', 'monto', 'fecha_pago', 'fecha_registro']
    list_filter = ['tipo', 'fecha_registro']
    search_fields = ['numero_deuda', 'deudor__nombre', 'deudor__apellido', 'deudor__ci']
    inlines = [AbonoDeudaInline]
    readonly_fields = ['numero_deuda', 'monto', 'fecha_registro']


class DetalleVentaInline(admin.TabularInline):
    model = DetalleVenta
    extra = 0
    readonly_fields = ['producto', 'cantidad', 'precio_unitario', 'subtotal']


@admin.register(Venta)
class VentaAdmin(admin.ModelAdmin):
    list_display = ['numero_venta', 'cajero', 'turno', 'total', 'metodo_pago', 'monto_recibido', 'monto_transferencia', 'fecha_venta', 'cancelada']
    list_filter = ['metodo_pago', 'cancelada', 'fecha_venta']
    search_fields = ['numero_venta']
    inlines = [DetalleVentaInline]
    readonly_fields = ['numero_venta', 'subtotal', 'impuesto', 'total', 'monto_recibido', 'monto_transferencia', 'cambio']


@admin.register(MostradorEstado)
class MostradorEstadoAdmin(admin.ModelAdmin):
    list_display = ['pantalla', 'mensaje', 'total', 'cajero_nombre', 'actualizado']
    list_filter = ['mensaje']
    readonly_fields = ['pantalla', 'items_json', 'total', 'mensaje', 'cajero_nombre', 'actualizado']


@admin.register(ArqueoTurno)
class ArqueoTurnoAdmin(admin.ModelAdmin):
    list_display = ['turno', 'estado', 'fondo_inicial', 'esperado_efectivo', 'contado_efectivo', 'esperado_transferencia', 'contado_transferencia']
    list_filter = ['estado']
    readonly_fields = ['turno', 'fondo_inicial', 'esperado_efectivo', 'esperado_transferencia',
                       'contado_efectivo', 'contado_transferencia', 'detalle_json', 'observacion',
                       'estado', 'declarado_por', 'declarado_at', 'confirmado_por', 'confirmado_at']


class ConteoCiegoLineaInline(admin.TabularInline):
    model = ConteoCiegoLinea
    extra = 0
    readonly_fields = ['producto', 'cantidad', 'stock_sistema']


@admin.register(ConteoCiego)
class ConteoCiegoAdmin(admin.ModelAdmin):
    list_display = ['id', 'turno', 'estado', 'creado_por', 'fecha_creacion', 'fecha_cierre']
    list_filter = ['estado']
    inlines = [ConteoCiegoLineaInline]


@admin.register(Almacen)
class AlmacenAdmin(admin.ModelAdmin):
    list_display = ['nombre', 'activo', 'es_principal', 'fecha_creacion']
    list_filter = ['activo', 'es_principal']
    search_fields = ['nombre']


@admin.register(ConfiguracionTienda)
class ConfiguracionTiendaAdmin(admin.ModelAdmin):
    list_display = ['nombre_tienda', 'moneda', 'color_acento', 'tema_por_defecto']


@admin.register(AlmacenStock)
class AlmacenStockAdmin(admin.ModelAdmin):
    list_display = ['producto', 'almacen', 'cantidad', 'fecha_actualizacion']
    list_filter = ['almacen']


@admin.register(AlmacenEntrada)
class AlmacenEntradaAdmin(admin.ModelAdmin):
    list_display = ['numero_entrada', 'producto', 'almacen', 'cantidad', 'fecha_entrada']
    list_filter = ['almacen']


@admin.register(AlmacenTraslado)
class AlmacenTrasladoAdmin(admin.ModelAdmin):
    list_display = ['numero_traslado', 'producto', 'origen', 'destino_tipo', 'destino_almacen', 'cantidad', 'fecha_traslado']
    list_filter = ['destino_tipo', 'origen']


@admin.register(AlmacenMovimiento)
class AlmacenMovimientoAdmin(admin.ModelAdmin):
    list_display = ['fecha', 'producto', 'almacen', 'tipo', 'cantidad']
    list_filter = ['tipo', 'almacen']
