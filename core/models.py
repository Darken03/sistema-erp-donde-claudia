from django.db import models
from django.db.models import Sum, Count
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from decimal import Decimal, ROUND_HALF_UP


def fmt_cantidad_unidad(valor, unidad_medida):
    """Formato de cantidades segun unidad (igual que el IPB).

    - kg / lb  -> decimales (hasta 3, sin ceros sobrantes) + sufijo ' (lb)' / ' (kg)'.
    - resto (unidades, gramos, metros...) -> entero sin decimales ni sufijo.
    """
    try:
        v = Decimal(str(valor if valor is not None else 0))
    except Exception:
        v = Decimal('0')
    if unidad_medida in ('kg', 'lb'):
        suf = 'kg' if unidad_medida == 'kg' else 'lb'
        s = format(v.quantize(Decimal('0.001')).normalize(), 'f')
        if '.' in s:
            s = s.rstrip('0').rstrip('.')
        return f"{s} ({suf})"
    return str(int(v.to_integral_value(rounding=ROUND_HALF_UP)))


# Margen mínimo de ganancia exigido al dar entrada (15%).
# Si el margen resultante es menor, la entrada exige confirmación.
# Si el costo supera al precio de venta, exige decisión explícita.
MARGEN_MINIMO_DEFECTO = Decimal('0.15')


def calcular_margen(precio_venta, costo):
    """Margen real (venta-costo)/costo. Devuelve Decimal (ej. 0.25 = 25%)."""
    try:
        v = Decimal(str(precio_venta or 0))
        c = Decimal(str(costo or 0))
    except Exception:
        return Decimal('0')
    if c <= 0:
        return Decimal('0')
    return (v - c) / c


def precio_sugerido(costo, margen=None):
    """Precio de venta sugerido para lograr el margen dado."""
    try:
        c = Decimal(str(costo or 0))
    except Exception:
        return Decimal('0')
    m = Decimal(str(margen)) if margen is not None else MARGEN_MINIMO_DEFECTO
    sugerido = (c * (Decimal('1') + m)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return sugerido if sugerido >= 0 else Decimal('0')


class PerfilUsuario(models.Model):
    ROLES = [
        ('admin', 'Administrador'),
        ('cajero', 'Cajero'),
        ('almacenero', 'Almacenero'),
    ]
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='perfil')
    rol = models.CharField(max_length=10, choices=ROLES, default='cajero')
    telefono = models.CharField(max_length=20, blank=True, null=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Perfil de Usuario'
        verbose_name_plural = 'Perfiles de Usuario'

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} ({self.get_rol_display()})"

    @property
    def es_admin(self):
        return self.rol == 'admin'

    @property
    def es_cajero(self):
        return self.rol == 'cajero'

    @property
    def es_almacenero(self):
        return self.rol == 'almacenero'


@receiver(post_save, sender=User)
def crear_perfil_usuario(sender, instance, created, **kwargs):
    if created:
        PerfilUsuario.objects.create(user=instance)


@receiver(post_save, sender=User)
def guardar_perfil_usuario(sender, instance, **kwargs):
    if hasattr(instance, 'perfil'):
        instance.perfil.save()


class Empleado(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='empleado')
    salario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    fecha_contratacion = models.DateField(auto_now_add=True)
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name = 'Empleado'
        verbose_name_plural = 'Empleados'
        ordering = ['user__first_name', 'user__last_name']

    def __str__(self):
        return self.user.get_full_name() or self.user.username

    @property
    def turno_abierto(self):
        return self.turnos.filter(abierto=True).first()

    @property
    def en_turno(self):
        return self.turnos.filter(abierto=True).exists()


class Turno(models.Model):
    empleado = models.ForeignKey(Empleado, on_delete=models.CASCADE, related_name='turnos')
    fecha_apertura = models.DateTimeField(auto_now_add=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    abierto = models.BooleanField(default=True)
    total_ventas = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    num_ventas = models.IntegerField(default=0)

    class Meta:
        verbose_name = 'Turno'
        verbose_name_plural = 'Turnos'
        ordering = ['-fecha_apertura']

    def __str__(self):
        estado = 'Abierto' if self.abierto else 'Cerrado'
        return f"Turno {self.empleado} - {self.fecha_apertura.strftime('%d/%m/%Y')} ({estado})"

    def cerrar(self):
        from django.utils import timezone
        self.fecha_cierre = timezone.now()
        self.abierto = False
        resumen = self.ventas.filter(cancelada=False).aggregate(
            total=Sum('total'),
            count=Count('id')
        )
        self.total_ventas = resumen['total'] or 0
        self.num_ventas = resumen['count'] or 0
        self.save()


class Categoria(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Categoria'
        verbose_name_plural = 'Categorias'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Producto(models.Model):
    UNIDADES_MEDIDA = [
        ('kg', 'Kilogramos (Kg)'),
        ('lb', 'Libras (lb)'),
        ('metros', 'Metros'),
        ('unidades', 'Unidades'),
        ('gramos', 'Gramos (g)'),
    ]
    codigo = models.CharField(max_length=50, unique=True, blank=True)
    nombre = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True, null=True)
    categoria = models.ForeignKey(
        Categoria,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='productos'
    )
    unidad_medida = models.CharField(max_length=15, choices=UNIDADES_MEDIDA, default='unidades')
    precio_compra = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_venta = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    # Stock en UNIDAD BASE (lb para cerdo, und para huevo). Decimal(12,3) para pesar con 3 decimales.
    stock = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    stock_minimo = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    # Si True, el POS permite cantidades fraccionarias (ej. 2.500 lb, 0.5 cartón).
    permite_decimal = models.BooleanField(default=False)
    imagen = models.ImageField(upload_to='productos/', blank=True, null=True)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Producto'
        verbose_name_plural = 'Productos'
        ordering = ['nombre']

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    @property
    def imagen_url(self):
        try:
            if self.imagen and self.imagen.storage.exists(self.imagen.name):
                return self.imagen.url
        except Exception:
            pass
        return None

    @property
    def margen_ganancia(self):
        if self.precio_compra > 0:
            return ((self.precio_venta - self.precio_compra) / self.precio_compra) * 100
        return 0

    @property
    def margen_real(self):
        """Margen en tanto por uno (0.25 = 25%)."""
        return calcular_margen(self.precio_venta, self.precio_compra)

    @property
    def en_perdida(self):
        """True si el costo actual iguala o supera al precio de venta."""
        try:
            return Decimal(str(self.precio_compra or 0)) >= Decimal(str(self.precio_venta or 0)) and Decimal(str(self.precio_compra or 0)) > 0
        except Exception:
            return False

    @property
    def margen_bajo(self):
        """True si el margen está por debajo del mínimo pero aún hay ganancia."""
        m = self.margen_real
        return Decimal('0') < m < MARGEN_MINIMO_DEFECTO

    @property
    def precio_venta_sugerido(self):
        """Precio sugerido para recuperar el margen mínimo con el costo actual."""
        return precio_sugerido(self.precio_compra, MARGEN_MINIMO_DEFECTO)

    def presentacion_mas_barata_por_base(self):
        """Menor precio por unidad base entre presentaciones activas (para alerta)."""
        pres = self.presentaciones.filter(activo=True)
        mejor = None
        for pr in pres:
            try:
                f = Decimal(str(pr.factor or 0))
                p = Decimal(str(pr.precio or 0))
            except Exception:
                continue
            if f > 0:
                unit = p / f
                if mejor is None or unit < mejor:
                    mejor = unit
        return mejor

    @property
    def stock_bajo(self):
        return self.stock <= self.stock_minimo

    @property
    def stock_fmt(self):
        """Stock con formato IPB: entero para unidades, decimales + (lb)/(kg) para peso."""
        return fmt_cantidad_unidad(self.stock, self.unidad_medida)

    @property
    def stock_minimo_fmt(self):
        return fmt_cantidad_unidad(self.stock_minimo, self.unidad_medida)

    def presentacion_default(self):
        """Devuelve la presentación default activa, o la primera, o None."""
        qs = self.presentaciones.filter(activo=True).order_by('-es_default', 'factor')
        return qs.first()

    def precio_para(self, presentacion=None):
        """Precio manual de la presentación; fallback al precio del producto."""
        if presentacion and presentacion.producto_id == self.pk:
            return presentacion.precio
        d = self.presentacion_default()
        if d:
            return d.precio
        return self.precio_venta

    @classmethod
    def generar_codigo(cls):
        ultimo = cls.objects.order_by('-id').first()
        if ultimo and ultimo.codigo and ultimo.codigo.startswith('PRD-'):
            try:
                num = int(ultimo.codigo.split('-')[-1])
                return f"PRD-{num + 1:04d}"
            except (ValueError, IndexError):
                pass
        return "PRD-0001"

    def save(self, *args, **kwargs):
        if not self.codigo:
            self.codigo = self.generar_codigo()
        super().save(*args, **kwargs)


class PresentacionProducto(models.Model):
    """Presentación de venta de un producto con precio manual propio.

    El inventario siempre se mueve en la UNIDAD BASE del producto:
        cantidad_base = cantidad * factor
    Ejemplos:
      - Cerdo (base lb): Libra x1 $180, Media libra x0.5 $95
      - Huevo (base und): Unidad x1 $10, Docena x12 $110,
        Cartón 30 x30 $250, Medio cartón x15 $130
    """
    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name='presentaciones'
    )
    nombre = models.CharField(max_length=100)
    # Cuántas unidades base equivale 1 unidad de esta presentación.
    factor = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    # Precio MANUAL de esta presentación (no se calcula automático).
    precio = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    es_default = models.BooleanField(default=False)
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Presentación de Producto'
        verbose_name_plural = 'Presentaciones de Producto'
        ordering = ['producto__nombre', 'factor']
        unique_together = ['producto', 'nombre']

    def __str__(self):
        return f"{self.producto.nombre} - {self.nombre} (x{self.factor})"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Garantiza una sola presentación default por producto.
        if self.es_default:
            PresentacionProducto.objects.filter(
                producto=self.producto, es_default=True
            ).exclude(pk=self.pk).update(es_default=False)


class Venta(models.Model):
    METODOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('mixto', 'Mixto'),
    ]
    numero_venta = models.CharField(max_length=20, unique=True)
    cajero = models.ForeignKey(User, on_delete=models.PROTECT, related_name='ventas')
    turno = models.ForeignKey(Turno, on_delete=models.SET_NULL, null=True, blank=True, related_name='ventas')
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    impuesto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    descuento = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    metodo_pago = models.CharField(max_length=15, choices=METODOS_PAGO, default='efectivo')
    monto_recibido = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    monto_transferencia = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cambio = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    fecha_venta = models.DateTimeField(auto_now_add=True)
    cancelada = models.BooleanField(default=False)

    class Meta:
        verbose_name = 'Venta'
        verbose_name_plural = 'Ventas'
        ordering = ['-fecha_venta']

    def __str__(self):
        return f"Venta #{self.numero_venta}"

    @classmethod
    def generar_numero(cls):
        ultima = cls.objects.order_by('-id').first()
        if ultima:
            ultimo_num = int(ultima.numero_venta.split('-')[-1])
            return f"VTA-{ultimo_num + 1:06d}"
        return "VTA-000001"


class DetalleVenta(models.Model):
    venta = models.ForeignKey(Venta, on_delete=models.CASCADE, related_name='detalles')
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT)
    presentacion = models.ForeignKey(
        PresentacionProducto, on_delete=models.PROTECT,
        null=True, blank=True, related_name='detalles_venta'
    )
    # Cantidad en unidades DE LA PRESENTACIÓN (ej. 2.5 lb, 0.5 cartón). 3 decimales.
    cantidad = models.DecimalField(max_digits=10, decimal_places=3, default=1)
    # Cantidad convertida a UNIDAD BASE para descontar inventario (cantidad x factor).
    cantidad_base = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    precio_unitario = models.DecimalField(max_digits=10, decimal_places=2)
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    # Costo por UNIDAD BASE congelado al momento de vender (Cuba: precios volátiles).
    # Permite calcular la ganancia histórica aunque el precio_compra cambie después.
    # 0 = registro anterior a esta mejora (usar precio_compra actual como fallback).
    costo_unitario_base = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    class Meta:
        verbose_name = 'Detalle de Venta'
        verbose_name_plural = 'Detalles de Venta'

    def __str__(self):
        return f"{self.producto.nombre} x{self.cantidad}"

    def save(self, *args, **kwargs):
        from decimal import Decimal
        self.subtotal = self.cantidad * self.precio_unitario
        # Si no se informó cantidad_base, derivarla del factor de la presentación.
        if not self.cantidad_base or self.cantidad_base == 0:
            factor = self.presentacion.factor if self.presentacion_id and self.presentacion else Decimal('1')
            self.cantidad_base = self.cantidad * factor
        super().save(*args, **kwargs)


class Gasto(models.Model):
    CATEGORIAS = [
        ('caja', 'Salida de Caja'),
        ('servicio', 'Servicio'),
        ('sueldo', 'Sueldo/Pago'),
        ('material', 'Materiales'),
        ('otro', 'Otro'),
    ]
    numero_gasto = models.CharField(max_length=20, unique=True)
    cajero = models.ForeignKey(User, on_delete=models.PROTECT, related_name='gastos')
    turno = models.ForeignKey(Turno, on_delete=models.SET_NULL, null=True, blank=True, related_name='gastos')
    cantidad_efectivo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    cantidad_transferencia = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    categoria = models.CharField(max_length=15, choices=CATEGORIAS, default='caja')
    descripcion = models.TextField(blank=True, null=True)
    fecha_gasto = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Gasto'
        verbose_name_plural = 'Gastos'
        ordering = ['-fecha_gasto']

    def __str__(self):
        return f"Gasto #{self.numero_gasto}"

    @property
    def cantidad_total(self):
        return self.cantidad_efectivo + self.cantidad_transferencia

    @classmethod
    def generar_numero(cls):
        ultimo = cls.objects.order_by('-id').first()
        if ultimo:
            ultimo_num = int(ultimo.numero_gasto.split('-')[-1])
            return f"GST-{ultimo_num + 1:06d}"
        return "GST-000001"


class EntradaProducto(models.Model):
    numero_entrada = models.CharField(max_length=20, unique=True)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='entradas')
    # Cantidad en UNIDAD BASE (lb / und). 3 decimales para pesar.
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    costo_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    proveedor = models.CharField(max_length=200, blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    fecha_entrada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Entrada de Producto'
        verbose_name_plural = 'Entradas de Productos'
        ordering = ['-fecha_entrada']

    def __str__(self):
        return f"Entrada #{self.numero_entrada} - {self.producto.nombre}"

    @property
    def cantidad_fmt(self):
        """Cantidad con formato IPB segun la unidad del producto."""
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.cantidad, unidad)

    def save(self, *args, **kwargs):
        self.costo_total = self.cantidad * self.costo_unitario
        super().save(*args, **kwargs)

    @classmethod
    def generar_numero(cls):
        ultimo = cls.objects.order_by('-id').first()
        if ultimo:
            ultimo_num = int(ultimo.numero_entrada.split('-')[-1])
            return f"ENT-{ultimo_num + 1:06d}"
        return "ENT-000001"


class HistorialPrecio(models.Model):
    """Auditoría de cada cambio de costo/venta (Cuba: precios volátiles).

    Nada se sobrescribe en silencio: cada Entrada con costo nuevo o cada
    edición manual deja quién, cuándo, antes→después y qué decisión se tomó
    ante una posible pérdida.
    """
    ACCIONES = [
        ('entrada_ok', 'Entrada con margen OK'),
        ('entrada_margen_bajo', 'Entrada con margen bajo (confirmada)'),
        ('entrada_perdida_actualiza', 'Entrada en pérdida → venta actualizada'),
        ('entrada_perdida_asumida', 'Entrada en pérdida → pérdida asumida'),
        ('edicion_manual', 'Edición manual de precio'),
    ]
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='historial_precios')
    precio_compra_antes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_compra_despues = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_venta_antes = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    precio_venta_despues = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    costo_entrada = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    entrada = models.ForeignKey(
        'EntradaProducto', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='historial_precios')
    margen_resultante = models.DecimalField(max_digits=7, decimal_places=4, default=0)
    accion = models.CharField(max_length=30, choices=ACCIONES, default='entrada_ok')
    motivo = models.CharField(max_length=255, blank=True, default='')
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    fecha = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Historial de Precio'
        verbose_name_plural = 'Historial de Precios'
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.producto.nombre}: ${self.precio_compra_antes}→${self.precio_compra_despues} / ${self.precio_venta_antes}→${self.precio_venta_despues} ({self.fecha.strftime('%d/%m/%Y')})"


class RetiroDonacion(models.Model):
    numero_retiro = models.CharField(max_length=20, unique=True)
    producto = models.ForeignKey(Producto, on_delete=models.PROTECT, related_name='retiros_donacion')
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    beneficiario = models.ForeignKey(User, on_delete=models.PROTECT, related_name='retiros_donacion')
    registrado_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='retiros_registrados')
    motivo = models.CharField(max_length=255, blank=True, null=True)
    fecha_retiro = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Retiro por Donación'
        verbose_name_plural = 'Retiros por Donación'
        ordering = ['-fecha_retiro']

    def __str__(self):
        return f"Retiro #{self.numero_retiro} - {self.producto.nombre} ({self.beneficiario.get_full_name() or self.beneficiario.username})"

    @property
    def valor(self):
        return self.cantidad * self.producto.precio_venta

    @classmethod
    def generar_numero(cls):
        ultimo = cls.objects.order_by('-id').first()
        if ultimo:
            ultimo_num = int(ultimo.numero_retiro.split('-')[-1])
            return f"DRN-{ultimo_num + 1:06d}"
        return "DRN-000001"


class MovimientoInventario(models.Model):
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('venta', 'Venta'),
        ('donacion', 'Donación'),
        ('deuda', 'Deuda (producto entregado)'),
        ('ajuste', 'Ajuste'),
        ('devolucion', 'Devolución'),
    ]
    
    fecha = models.DateTimeField(auto_now_add=True)
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='movimientos')
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    stock_anterior = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    stock_nuevo = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    referencia_id = models.IntegerField(null=True, blank=True)
    descripcion = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Movimiento de Inventario'
        verbose_name_plural = 'Movimientos de Inventario'
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.fecha.strftime('%d/%m/%Y %H:%M')} - {self.producto.nombre} - {self.tipo}: {self.cantidad}"

    @property
    def cantidad_fmt(self):
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.cantidad, unidad)

    @property
    def stock_anterior_fmt(self):
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.stock_anterior, unidad)

    @property
    def stock_nuevo_fmt(self):
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.stock_nuevo, unidad)


class InventarioDiario(models.Model):
    fecha = models.DateField()
    producto = models.ForeignKey(Producto, on_delete=models.CASCADE, related_name='inventarios_diarios')
    stock_inicial = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    entradas = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    ventas = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    stock_final = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    cerrado = models.BooleanField(default=False)
    cerrado_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Inventario Diario'
        verbose_name_plural = 'Inventarios Diarios'
        unique_together = ['fecha', 'producto']
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.fecha.strftime('%d/%m/%Y')} - {self.producto.nombre}: {self.stock_inicial} + {self.entradas} - {self.ventas} = {self.stock_final}"

    def calcular(self, donaciones=None, salidas_deuda=None):
        # El stock vivo descuenta donaciones y deudas de producto
        # (_registrar_movimiento), por eso el final también debe restarlas.
        # Si no se pasan explícitas, se consultan para esta fecha/producto.
        from decimal import Decimal
        if donaciones is None or salidas_deuda is None:
            try:
                d = RetiroDonacion.objects.filter(
                    fecha_retiro__date=self.fecha,
                    producto=self.producto,
                ).aggregate(t=models.Sum('cantidad'))['t'] or 0
                donaciones = Decimal(str(d))
            except Exception:
                donaciones = Decimal('0')
            try:
                du = Deuda.objects.filter(
                    fecha_registro__date=self.fecha,
                    tipo='producto',
                    producto=self.producto,
                ).aggregate(t=models.Sum('cantidad_base'))['t'] or 0
                if not du:
                    du = Deuda.objects.filter(
                        fecha_registro__date=self.fecha,
                        tipo='producto',
                        producto=self.producto,
                        cantidad_base=0,
                    ).aggregate(t=models.Sum('cantidad'))['t'] or 0
                salidas_deuda = Decimal(str(du))
            except Exception:
                salidas_deuda = Decimal('0')
        else:
            donaciones = Decimal(str(donaciones or 0))
            salidas_deuda = Decimal(str(salidas_deuda or 0))
        self.stock_final = self.stock_inicial + self.entradas - self.ventas - donaciones - salidas_deuda

    def cerrar_registro(self):
        self.cerrado = True
        self.calcular()
        from django.utils import timezone
        self.cerrado_at = timezone.now()
        self.save()

    @classmethod
    def obtener_o_crear(cls, producto, fecha):
        # NUNCA anclar historia al stock vivo. Solo el día de hoy sin
        # anterior puede bootstrapearse desde producto.stock; el resto
        # encadena desde el último final anterior y congela el inicial.
        from django.utils import timezone
        hoy = timezone.localdate()
        inv_anterior = cls.objects.filter(
            fecha__lt=fecha, producto=producto
        ).order_by('-fecha').first()
        inicial = inv_anterior.stock_final if inv_anterior else producto.stock
        inventario, created = cls.objects.get_or_create(
            fecha=fecha,
            producto=producto,
            defaults={
                'stock_inicial': inicial,
                'entradas': 0,
                'ventas': 0,
                'stock_final': inicial,
            }
        )
        if not created:
            if inventario.cerrado:
                return inventario
            if fecha < hoy:
                return inventario
            if inventario.stock_inicial == 0 and inv_anterior:
                inventario.stock_inicial = inv_anterior.stock_final
                inventario.calcular()
                inventario.save()
        return inventario

    @classmethod
    def inicializar_dia(cls, fecha):
        from django.utils import timezone
        hoy = timezone.localdate()

        productos = Producto.objects.filter(activo=True)
        for producto in productos:
            inv_anterior = cls.objects.filter(
                fecha__lt=fecha, producto=producto
            ).order_by('-fecha').first()
            inicial = inv_anterior.stock_final if inv_anterior else producto.stock
            inventario_hoy, created = cls.objects.get_or_create(
                fecha=fecha,
                producto=producto,
                defaults={
                    'stock_inicial': inicial,
                    'entradas': 0,
                    'ventas': 0,
                    'stock_final': inicial,
                }
            )
            if not created:
                if inventario_hoy.cerrado:
                    continue
                if fecha < hoy:
                    continue
                if inv_anterior and inventario_hoy.stock_inicial == 0:
                    inventario_hoy.stock_inicial = inv_anterior.stock_final
                    inventario_hoy.calcular()
                    inventario_hoy.save()


class Deudor(models.Model):
    nombre = models.CharField(max_length=100)
    apellido = models.CharField(max_length=100, blank=True, default='')
    ci = models.CharField(max_length=20, unique=True, null=True, blank=True)
    telefono = models.CharField(max_length=30, blank=True, default='')
    activo = models.BooleanField(default=True)
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Deudor'
        verbose_name_plural = 'Deudores'
        ordering = ['nombre', 'apellido']

    def __str__(self):
        nombre = f"{self.nombre} {self.apellido}".strip()
        return f"{nombre} ({self.ci})" if self.ci else nombre

    def save(self, *args, **kwargs):
        if not self.ci:
            self.ci = None
        super().save(*args, **kwargs)

    @property
    def nombre_completo(self):
        return f"{self.nombre} {self.apellido}".strip()

    @property
    def saldo_total(self):
        from decimal import Decimal
        return sum((d.saldo for d in self.deudas.all()), Decimal('0'))

    @property
    def deudas_pendientes(self):
        return [d for d in self.deudas.all() if d.saldo > 0]


class Deuda(models.Model):
    TIPO_CHOICES = [
        ('dinero', 'Dinero'),
        ('producto', 'Producto'),
    ]
    numero_deuda = models.CharField(max_length=20, unique=True)
    deudor = models.ForeignKey(Deudor, on_delete=models.PROTECT, related_name='deudas')
    tipo = models.CharField(max_length=10, choices=TIPO_CHOICES, default='dinero')
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT,
        null=True, blank=True, related_name='deudas'
    )
    presentacion = models.ForeignKey(
        'PresentacionProducto', on_delete=models.PROTECT,
        null=True, blank=True, related_name='deudas'
    )
    # Cantidad en unidades DE LA PRESENTACIÓN (ej. 1 cartón, 2.5 lb). 3 decimales.
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=1)
    # Cantidad convertida a UNIDAD BASE para descontar inventario (cantidad x factor).
    cantidad_base = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    precio_unitario = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    motivo = models.CharField(max_length=255, blank=True, default='')
    fecha_pago = models.DateField(null=True, blank=True)
    fecha_registro = models.DateTimeField(auto_now_add=True)
    registrada_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='deudas_registradas')

    class Meta:
        verbose_name = 'Deuda'
        verbose_name_plural = 'Deudas'
        ordering = ['-fecha_registro']

    def __str__(self):
        estado = 'PAGADA' if self.esta_pagada else 'PENDIENTE'
        return f"{self.deudor} - ${self.monto} ({estado})"

    @classmethod
    def generar_numero(cls):
        ultimo = cls.objects.order_by('-id').first()
        if ultimo:
            try:
                ultimo_num = int(ultimo.numero_deuda.split('-')[-1])
                return f"DEU-{ultimo_num + 1:06d}"
            except (ValueError, IndexError):
                pass
        return "DEU-000001"

    @property
    def total_abonado(self):
        from decimal import Decimal
        return self.abonos.aggregate(total=models.Sum('monto'))['total'] or Decimal('0')

    @property
    def saldo(self):
        return self.monto - self.total_abonado

    @property
    def esta_pagada(self):
        return self.saldo <= 0

    @property
    def motivo_display(self):
        if self.motivo:
            return self.motivo
        if self.tipo == 'producto' and self.producto:
            from decimal import Decimal as _D
            try:
                c = _D(str(self.cantidad or 0))
                cs = format(c.normalize(), 'f') if c == c.to_integral_value() else format(c.normalize(), 'f')
            except Exception:
                cs = str(self.cantidad)
            pres = f" ({self.presentacion.nombre})" if self.presentacion_id and getattr(self, 'presentacion', None) else ""
            return f"{cs} x {self.producto.nombre}{pres}"
        return '-'

    @property
    def presentacion_nombre(self):
        try:
            if self.presentacion_id and self.presentacion:
                return self.presentacion.nombre
        except Exception:
            pass
        return ''


class AbonoDeuda(models.Model):
    METODO_CHOICES = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
    ]
    deuda = models.ForeignKey(Deuda, on_delete=models.CASCADE, related_name='abonos')
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    metodo = models.CharField(max_length=15, choices=METODO_CHOICES, default='efectivo')
    nota = models.CharField(max_length=255, blank=True, default='')
    fecha = models.DateTimeField(auto_now_add=True)
    registrada_por = models.ForeignKey(User, on_delete=models.PROTECT, related_name='abonos_deuda')

    class Meta:
        verbose_name = 'Abono de Deuda'
        verbose_name_plural = 'Abonos de Deudas'
        ordering = ['-fecha']

    def __str__(self):
        return f"Abono ${self.monto} a {self.deuda.numero_deuda}"


class MostradorEstado(models.Model):
    """Último carrito empujado por el POS para una pantalla (1-5).

    El POS lo actualiza en cada cambio del carrito; el mostrador lo lee
    por polling cada ~2.5 s. Guardado en BD para que funcione con
    varios procesos (Passenger) y sin Redis/websockets.
    """
    MENSAJES = [
        ('vacio', 'Vacío'),
        ('activo', 'Carrito activo'),
        ('completado', 'Venta completada'),
    ]
    pantalla = models.PositiveSmallIntegerField(unique=True)
    items_json = models.TextField(default='[]')
    total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    mensaje = models.CharField(max_length=12, choices=MENSAJES, default='vacio')
    cajero_nombre = models.CharField(max_length=150, blank=True, default='')
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Estado de Mostrador'
        verbose_name_plural = 'Estados de Mostrador'
        ordering = ['pantalla']

    def __str__(self):
        return f"Mostrador pantalla {self.pantalla} ({self.mensaje})"

    def items(self):
        import json as _json
        try:
            data = _json.loads(self.items_json or '[]')
            return data if isinstance(data, list) else []
        except Exception:
            return []


from datetime import timedelta


# Denominaciones CUP para el ayudante de conteo del arqueo.
# Billetes y monedas de uso común en Cuba.
DENOMINACIONES_CUP = [
    ('20000', 'Billete $20000'),
    ('10000', 'Billete $10000'),
    ('5000', 'Billete $5000'),
    ('2000', 'Billete $2000'),
    ('1000', 'Billete $1000'),
    ('500', 'Billete $500'),
    ('200', 'Billete $200'),
    ('100', 'Billete $100'),
    ('50', 'Billete $50'),
    ('20', 'Billete $20'),
    ('10', 'Billete $10'),
    ('5', 'Billete $5'),
    ('5M', 'Moneda $5'),
    ('3M', 'Moneda $3'),
    ('1M', 'Moneda $1'),
]
# Valor en CUP de cada denominación (la M final = moneda).
DENOMINACIONES_CUP_VALOR = {
    '20000': Decimal('20000'), '10000': Decimal('10000'),
    '5000': Decimal('5000'), '2000': Decimal('2000'),
    '1000': Decimal('1000'), '500': Decimal('500'), '200': Decimal('200'),
    '100': Decimal('100'), '50': Decimal('50'), '20': Decimal('20'),
    '10': Decimal('10'), '5': Decimal('5'),
    '5M': Decimal('5'), '3M': Decimal('3'), '1M': Decimal('1'),
}


class ArqueoTurno(models.Model):
    """Arqueo de caja de un turno en 2 pasos.

    Paso 1 (sistema): fondo inicial + esperado por método
        (ventas del turno − gastos del turno).
    Paso 2 (cajero): declara lo contado (con ayudante por
        denominaciones) → diferencia + motivo si descuadra.
    Después un admin lo confirma y el turno se cierra.
    """
    ESTADOS = [
        ('borrador', 'Borrador (paso 1)'),
        ('declarado', 'Declarado por el cajero (paso 2)'),
        ('confirmado', 'Confirmado por admin'),
    ]
    turno = models.OneToOneField(
        Turno, on_delete=models.CASCADE, related_name='arqueo')
    fondo_inicial = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # True cuando el paso 1 (fondo + foto del esperado) ya se guardó.
    paso1_listo = models.BooleanField(default=False)
    # Foto del esperado al momento de declarar (no cambia si siguen vendiendo).
    esperado_efectivo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    esperado_transferencia = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Lo que declara el cajero.
    contado_efectivo = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    contado_transferencia = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    # Detalle del conteo por denominaciones: {"1000": 2, "100": 5, ...}.
    detalle_json = models.TextField(default='{}')
    observacion = models.CharField(max_length=255, blank=True, default='')
    estado = models.CharField(max_length=12, choices=ESTADOS, default='borrador')
    declarado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='arqueos_declarados')
    declarado_at = models.DateTimeField(null=True, blank=True)
    confirmado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='arqueos_confirmados')
    confirmado_at = models.DateTimeField(null=True, blank=True)
    # Decisión del admin ante faltante/sobrante (se elige al confirmar).
    DECISIONES = [
        ('', 'Sin decidir'),
        ('aceptar', 'Aceptar diferencia y cerrar'),
        ('gasto', 'Faltante → registrar como gasto de caja'),
        ('descontar', 'Descontar al empleado (pendiente en nómina)'),
        ('sobrante_caja', 'Sobrante → queda en caja'),
    ]
    decision = models.CharField(max_length=15, choices=DECISIONES, default='', blank=True)
    decision_nota = models.CharField(max_length=255, blank=True, default='')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Arqueo de Turno'
        verbose_name_plural = 'Arqueos de Turno'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"Arqueo turno {self.turno_id} ({self.get_estado_display()})"

    @property
    def diferencia_efectivo(self):
        return (self.contado_efectivo or 0) - (self.esperado_efectivo or 0)

    @property
    def diferencia_transferencia(self):
        return (self.contado_transferencia or 0) - (self.esperado_transferencia or 0)

    @property
    def diferencia_total(self):
        return self.diferencia_efectivo + self.diferencia_transferencia

    @property
    def descuadra(self):
        return self.diferencia_total != 0

    def detalle(self):
        import json as _json
        try:
            data = _json.loads(self.detalle_json or '{}')
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}


class ConteoCiego(models.Model):
    """Conteo físico de productos A CIEGAS para un turno.

    El empleado anota cantidades sin ver el stock del sistema.
    Al cerrar se congela el stock del sistema por producto y la
    comparación (sistema vs contado) solo se ve después de cerrado.
    """
    ESTADOS = [
        ('abierto', 'Abierto (contando)'),
        ('cerrado', 'Cerrado (comparado)'),
    ]
    turno = models.ForeignKey(
        Turno, on_delete=models.CASCADE, related_name='conteos')
    estado = models.CharField(max_length=10, choices=ESTADOS, default='abierto')
    creado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conteos_creados')
    cerrado_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conteos_cerrados')
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_cierre = models.DateTimeField(null=True, blank=True)
    # Decisión del admin ante diferencias (se elige en Revisar turno).
    DECISIONES = [
        ('', 'Sin decidir'),
        ('ajustado', 'Sistema llevado a lo contado'),
        ('recontar', 'Reconteo pedido'),
        ('aceptado', 'Aceptado sin ajustar'),
    ]
    decision = models.CharField(max_length=10, choices=DECISIONES, default='', blank=True)
    decision_nota = models.CharField(max_length=255, blank=True, default='')
    decidido_por = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='conteos_decididos')
    decidido_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = 'Conteo Ciego'
        verbose_name_plural = 'Conteos Ciegos'
        ordering = ['-fecha_creacion']

    def __str__(self):
        return f"Conteo #{self.pk} turno {self.turno_id} ({self.get_estado_display()})"

    @property
    def num_diferencias(self):
        return sum(1 for l in self.lineas.all() if l.diferencia not in (None, 0))


class ConteoCiegoLinea(models.Model):
    """Una línea del conteo: lo contado + foto del sistema al cerrar."""
    conteo = models.ForeignKey(
        ConteoCiego, on_delete=models.CASCADE, related_name='lineas')
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name='conteos_ciegos')
    # Cantidad contada físicamente (unidad base). 3 decimales para peso.
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    # Stock del sistema congelado al cerrar el conteo (None = aún abierto).
    stock_sistema = models.DecimalField(
        max_digits=12, decimal_places=3, null=True, blank=True)

    class Meta:
        verbose_name = 'Línea de Conteo Ciego'
        verbose_name_plural = 'Líneas de Conteo Ciego'
        unique_together = ['conteo', 'producto']

    def __str__(self):
        return f"{self.producto.nombre}: contado {self.cantidad}"

    @property
    def diferencia(self):
        if self.stock_sistema is None:
            return None
        return self.cantidad - self.stock_sistema


# ============================================================
# ALMACÉN (ajeno al IPB, ventas y entradas directas al POS).
# Flujo: AlmacenEntrada -> AlmacenStock -> AlmacenTraslado -> POS.
# Solo el traslado cruza al sistema actual generando una
# EntradaProducto con proveedor 'Almacén' (visible en el IPB).
# ============================================================

# Proveedor que identifica en el IPB las entradas venidas del almacén.
ALMACEN_PROVEEDOR = 'Almacén'


class AlmacenStock(models.Model):
    """Existencia de un producto en el almacén (unidad base, 3 decimales)."""
    producto = models.OneToOneField(
        Producto, on_delete=models.CASCADE, related_name='almacen_stock')
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Existencia de Almacén'
        verbose_name_plural = 'Existencias de Almacén'

    def __str__(self):
        return f"{self.producto.nombre}: {self.cantidad}"

    @property
    def cantidad_fmt(self):
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.cantidad, unidad)

    @property
    def valor(self):
        try:
            return self.cantidad * (self.producto.precio_compra or 0)
        except Exception:
            return Decimal('0')


class AlmacenEntrada(models.Model):
    """Entrada de mercancía al almacén (no toca el stock del POS)."""
    numero_entrada = models.CharField(max_length=20, unique=True)
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name='almacen_entradas')
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    costo_total = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    proveedor = models.CharField(max_length=200, blank=True, null=True)
    descripcion = models.TextField(blank=True, null=True)
    registrado_por = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='almacen_entradas_registradas')
    fecha_entrada = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Entrada de Almacén'
        verbose_name_plural = 'Entradas de Almacén'
        ordering = ['-fecha_entrada']

    def __str__(self):
        return f"Entrada almacén #{self.numero_entrada} - {self.producto.nombre}"

    @property
    def cantidad_fmt(self):
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.cantidad, unidad)

    def save(self, *args, **kwargs):
        self.costo_total = self.cantidad * self.costo_unitario
        super().save(*args, **kwargs)

    @classmethod
    def generar_numero(cls):
        ultimo = cls.objects.order_by('-id').first()
        if ultimo:
            try:
                ultimo_num = int(ultimo.numero_entrada.split('-')[-1])
                return f"AENT-{ultimo_num + 1:06d}"
            except (ValueError, IndexError):
                pass
        return "AENT-000001"


class AlmacenTraslado(models.Model):
    """Movimiento de mercancía del almacén al punto de venta.

    Al confirmarse genera una EntradaProducto (proveedor 'Almacén') con el
    costo vigente: eso es lo que el IPB muestra como entrada del día.
    Los traslados son inmutables (si hay error se corrige con ajuste).
    """
    numero_traslado = models.CharField(max_length=20, unique=True)
    producto = models.ForeignKey(
        Producto, on_delete=models.PROTECT, related_name='almacen_traslados')
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    # Foto del costo vigente al trasladar (sin costo de transporte: mismo local).
    costo_unitario = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    registrado_por = models.ForeignKey(
        User, on_delete=models.PROTECT, related_name='almacen_traslados_registrados')
    entrada_generada = models.ForeignKey(
        'EntradaProducto', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='traslados_almacen')
    fecha_traslado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = 'Traslado al Punto de Venta'
        verbose_name_plural = 'Traslados al Punto de Venta'
        ordering = ['-fecha_traslado']

    def __str__(self):
        return f"Traslado #{self.numero_traslado} - {self.producto.nombre}"

    @property
    def cantidad_fmt(self):
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.cantidad, unidad)

    @classmethod
    def generar_numero(cls):
        ultimo = cls.objects.order_by('-id').first()
        if ultimo:
            try:
                ultimo_num = int(ultimo.numero_traslado.split('-')[-1])
                return f"ATRS-{ultimo_num + 1:06d}"
            except (ValueError, IndexError):
                pass
        return "ATRS-000001"


class AlmacenMovimiento(models.Model):
    """Auditoría propia del almacén (ajena al IPB y a MovimientoInventario)."""
    TIPO_CHOICES = [
        ('entrada', 'Entrada'),
        ('traslado', 'Traslado al POS'),
        ('ajuste', 'Ajuste'),
    ]

    fecha = models.DateTimeField(auto_now_add=True)
    producto = models.ForeignKey(
        Producto, on_delete=models.CASCADE, related_name='almacen_movimientos')
    tipo = models.CharField(max_length=15, choices=TIPO_CHOICES)
    cantidad = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    stock_anterior = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    stock_nuevo = models.DecimalField(max_digits=12, decimal_places=3, default=0)
    referencia_id = models.IntegerField(null=True, blank=True)
    descripcion = models.CharField(max_length=255, blank=True)
    usuario = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        verbose_name = 'Movimiento de Almacén'
        verbose_name_plural = 'Movimientos de Almacén'
        ordering = ['-fecha']

    def __str__(self):
        return f"{self.fecha.strftime('%d/%m/%Y %H:%M')} - {self.producto.nombre} - {self.tipo}: {self.cantidad}"

    @property
    def cantidad_fmt(self):
        unidad = self.producto.unidad_medida if self.producto_id else 'unidades'
        return fmt_cantidad_unidad(self.cantidad, unidad)
