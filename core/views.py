import json
from decimal import Decimal
from django.shortcuts import render, get_object_or_404, redirect
from django.http import JsonResponse, HttpResponse
from django.db.models import Sum, Count, F, Q, ProtectedError
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.views.decorators.http import require_POST
from django.utils import timezone
from datetime import datetime, timedelta
from django.template.loader import render_to_string
try:
    from xhtml2pdf import pisa
except Exception:  # entorno sin deps PDF completas: se importa lazy al generar
    pisa = None
from io import BytesIO
from .models import (
    Producto, Categoria, Venta, DetalleVenta, PerfilUsuario, Empleado, Turno, Gasto, EntradaProducto, RetiroDonacion, InventarioDiario, MovimientoInventario, Deuda, Deudor, AbonoDeuda, MostradorEstado,
    fmt_cantidad_unidad, ArqueoTurno, ConteoCiego, ConteoCiegoLinea,
    DENOMINACIONES_CUP, DENOMINACIONES_CUP_VALOR,
    ALMACEN_PROVEEDOR, almacen_proveedor_nombre, Almacen, ConfiguracionTienda,
    get_almacen_unico, AlmacenStock, AlmacenEntrada, AlmacenTraslado, AlmacenMovimiento,
    PuntoVenta,
)
from .forms import (
    ProductoForm, CategoriaForm, EmpleadoForm, PresentacionFormSet,
    AlmacenForm, ConfigTiendaForm, ConfigAparienciaForm, ConfigRegionalForm,
)


def ahora_servidor():
    return datetime.now()


# El sistema empezó a operar el 22/09/2026: no existe IPB anterior.
# Pedir una fecha más vieja solo generaba filas ficticias en la BD
# (inicial = stock vivo), por eso se bloquea a toda costa.
FECHA_INICIO_SISTEMA = datetime(2026, 9, 22).date()


def _log_cambio_precio(producto, compra_antes, compra_despues,
                       venta_antes, venta_despues,
                       accion='edicion_manual', motivo='', usuario=None,
                       costo_entrada=None, entrada=None):
    """Audita un cambio de costo/venta (Cuba: precios volátiles).

    Sin cambio real no crea fila (devuelve None). Minimal para que el IPB
    futuro pueda mostrar el precio del día en vez del actual.
    """
    from decimal import Decimal as _D
    from .models import HistorialPrecio
    try:
        ca = _D(str(compra_antes or 0))
        cd = _D(str(compra_despues or 0))
        va = _D(str(venta_antes or 0))
        vd = _D(str(venta_despues or 0))
    except Exception:
        return None
    if ca == cd and va == vd:
        return None
    try:
        margen = (vd - cd) / cd if cd > 0 else _D('0')
    except Exception:
        margen = _D('0')
    return HistorialPrecio.objects.create(
        producto=producto,
        precio_compra_antes=ca, precio_compra_despues=cd,
        precio_venta_antes=va, precio_venta_despues=vd,
        costo_entrada=(None if costo_entrada is None else _D(str(costo_entrada))),
        entrada=entrada,
        margen_resultante=margen,
        accion=accion, motivo=motivo or '', usuario=usuario,
    )


def _norm_sin_tildes(texto):
    """Normaliza para búsqueda insensible a tildes/mayúsculas.

    'Café' -> 'cafe', 'JAMÓN' -> 'jamon'. Se usa en el POS para que
    buscar 'cafe' encuentre 'Café', etc.
    """
    import unicodedata
    s = str(texto or '').strip().lower()
    s = unicodedata.normalize('NFD', s)
    return ''.join(c for c in s if unicodedata.category(c) != 'Mn')


# ============================================================
# AUTENTICACION
# ============================================================

def login_view(request):
    if request.user.is_authenticated:
        return redirect('core:redireccion_rol')
    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('core:redireccion_rol')
        else:
            return render(request, 'core/login.html', {'error': 'Usuario o contrasena incorrectos.'})
    return render(request, 'core/login.html')


def logout_view(request):
    logout(request)
    return redirect('core:login')


@login_required
def redireccion_rol(request):
    try:
        perfil = request.user.perfil
        if perfil.es_admin:
            return redirect('core:dashboard')
        elif perfil.es_almacenero:
            if modo_actual() == 'solo_pos':
                # Spec §3: en solo-POS el almacenero queda sin pantallas.
                messages.warning(
                    request,
                    'El rol almacenero no tiene pantallas en el modo solo-POS: '
                    'se sugiere reasignarlo a cajero.')
                return redirect('core:pos')
            return redirect('core:almacen_panel')
        else:
            return redirect('core:pos')
    except PerfilUsuario.DoesNotExist:
        return redirect('core:dashboard')


def requiere_admin(view_func):
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        try:
            if not request.user.perfil.es_admin:
                return redirect('core:pos')
        except PerfilUsuario.DoesNotExist:
            pass
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    wrapper.__doc__ = view_func.__doc__
    return wrapper


def requiere_almacen(view_func):
    """Permite admin o almacenero. El cajero rebota al POS."""
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('core:login')
        try:
            perfil = request.user.perfil
            if not (perfil.es_admin or perfil.es_almacenero):
                return redirect('core:pos')
        except PerfilUsuario.DoesNotExist:
            pass
        return view_func(request, *args, **kwargs)
    wrapper.__name__ = view_func.__name__
    wrapper.__doc__ = view_func.__doc__
    return wrapper


# ============================================================
# MODOS DE OPERACIÓN (spec 2026-10-10-modos-operacion, §1-2).
# Cambiar de modo NUNCA borra datos: lo no aplicable se oculta
# (sidebar + decorador) y reaparece intacto al volver.
# ============================================================

MODOS_OPERACION = ('solo_pos', 'pos_almacenes', 'multi_pos')


def modo_actual():
    """Modo vigente según ConfiguracionTienda (default: comportamiento actual)."""
    try:
        modo = ConfiguracionTienda.get_solo().modo_operacion
    except Exception:
        return 'pos_almacenes'
    return modo if modo in MODOS_OPERACION else 'pos_almacenes'


def requiere_modo(*modos):
    """Bloquea URLs fuera del modo actual (redirect + mensaje, sin 500)."""
    def deco(view_func):
        def wrapper(request, *args, **kwargs):
            if modo_actual() not in modos:
                messages.warning(
                    request, 'No disponible en el modo actual.')
                try:
                    es_admin = request.user.perfil.es_admin
                except Exception:
                    es_admin = False
                if es_admin:
                    return redirect('core:dashboard')
                return redirect('core:pos')
            return view_func(request, *args, **kwargs)
        wrapper.__name__ = view_func.__name__
        wrapper.__doc__ = view_func.__doc__
        return wrapper
    return deco


def _resolver_pos_filtro(request):
    """PuntoVenta activo de `?pos=` solo en modo multi-POS.

    Devuelve `(pos_o_None, puntos_venta_activos)`. Fuera de multi-POS el
    filtro se ignora (historia con `punto_venta=NULL`): `(None, [])`.
    Un `?pos=` ausente/inválido/inactivo también da `(None, lista)`.
    """
    if modo_actual() != 'multi_pos':
        return None, []
    puntos = list(PuntoVenta.activos().select_related('almacen'))
    try:
        pid = int(request.GET.get('pos') or 0)
    except (ValueError, TypeError):
        pid = 0
    pos = next((p for p in puntos if p.pk == pid), None)
    return pos, puntos


# ============================================================
# DASHBOARD
# ============================================================

@requiere_admin
def dashboard(request):
    from datetime import timedelta
    from django.utils import timezone
    from django.conf import settings
    ahora = timezone.make_aware(ahora_servidor().replace(hour=0, minute=0, second=0, microsecond=0))
    inicio_dia = ahora
    fin_dia = inicio_dia + timedelta(days=1)
    
    total_productos = Producto.objects.filter(activo=True).count()
    stock_bajo = Producto.objects.filter(activo=True, stock__lte=F('stock_minimo')).count()
    total_categorias = Categoria.objects.count()
    valor_inventario = Producto.objects.filter(activo=True).aggregate(
        total=Sum(F('stock') * F('precio_compra'))
    )['total'] or 0
    total_ventas_hoy = Venta.objects.filter(
        fecha_venta__gte=inicio_dia,
        fecha_venta__lt=fin_dia,
        cancelada=False
    ).aggregate(total=Sum('total'))['total'] or 0
    empleados_en_turno = Empleado.objects.filter(activo=True, turnos__abierto=True).distinct().count()

    # Top 5 productos mas vendidos hoy
    top_productos_qs = DetalleVenta.objects.filter(
        venta__fecha_venta__gte=inicio_dia,
        venta__fecha_venta__lt=fin_dia,
        venta__cancelada=False
    ).values(
        'producto__nombre', 'producto__codigo',
        'producto__precio_compra', 'producto__precio_venta',
        'producto__unidad_medida'
    ).annotate(
        total_vendido=Sum('cantidad_base'),
        total_ingreso=Sum('subtotal'),
        total_costo=Sum(F('cantidad_base') * F('producto__precio_compra'))
    ).order_by('-total_vendido')[:5]
    top_productos = []
    for p in top_productos_qs:
        ganancia = (p['total_ingreso'] or 0) - (p['total_costo'] or 0)
        # SUM en SQLite devuelve float (ej. 13.0900000000000): formatear estilo IPB.
        from .models import fmt_cantidad_unidad as _fmtu
        try:
            vendido_fmt = _fmtu(p['total_vendido'] or 0, p.get('producto__unidad_medida') or 'unidades')
        except Exception:
            vendido_fmt = str(p['total_vendido'] or 0)
        top_productos.append({
            **p,
            'ganancia': ganancia,
            'total_vendido_fmt': vendido_fmt,
        })

    context = {
        'total_productos': total_productos,
        'stock_bajo': stock_bajo,
        'total_categorias': total_categorias,
        'valor_inventario': valor_inventario,
        'total_ventas_hoy': total_ventas_hoy,
        'empleados_en_turno': empleados_en_turno,
        'top_productos': top_productos,
    }
    return render(request, 'core/dashboard.html', context)


# ============================================================
# PRODUCTOS
# ============================================================

@requiere_admin
def producto_lista(request):
    productos = Producto.objects.select_related('categoria').order_by('nombre')
    query = request.GET.get('q')
    categoria_id = request.GET.get('categoria')

    if query:
        q_norm = _norm_sin_tildes(query)
        # El código no lleva tildes: filtro directo en BD.
        ids_codigo = list(productos.filter(codigo__icontains=query).values_list('id', flat=True))
        # El nombre se compara en Python insensible a tildes:
        # 'cafe' encuentra 'Café', 'jamon' encuentra 'Jamón', etc.
        ids_nombre = []
        if q_norm:
            for pid, pnombre in productos.values_list('id', 'nombre'):
                if q_norm in _norm_sin_tildes(pnombre):
                    ids_nombre.append(pid)
        productos = productos.filter(Q(id__in=set(ids_codigo) | set(ids_nombre)))
    if categoria_id:
        productos = productos.filter(categoria_id=categoria_id)

    # Paginado: solo los primeros 20 productos por página.
    # Los filtros (q, categoria, riesgo) se conservan en los enlaces.
    paginator = Paginator(productos, 20)
    page_obj = paginator.get_page(request.GET.get('page'))
    params = request.GET.copy()
    params.pop('page', None)
    qs = params.urlencode()

    categorias = Categoria.objects.all()
    context = {
        'productos': page_obj,
        'page_obj': page_obj,
        'qs': qs,
        'categorias': categorias,
        'query': query,
        'categoria_seleccionada': categoria_id,
    }
    return render(request, 'core/producto_lista.html', context)


@requiere_admin
def producto_detalle(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    return render(request, 'core/producto_detalle.html', {'producto': producto})


@requiere_admin
def producto_crear(request):
    def _next_seguro(valor):
        if not valor:
            return ''
        valor = str(valor).strip()
        # Solo rutas internas (evita open-redirect): /algo, sin // ni esquema.
        if not valor.startswith('/') or valor.startswith('//'):
            return ''
        if ' ' in valor or '\\' in valor:
            return ''
        return valor

    next_url = _next_seguro(request.POST.get('next') or request.GET.get('next'))
    desde_almacen = next_url.startswith('/almacen/')
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES)
        if form.is_valid():
            producto = form.save()
            if desde_almacen:
                # Nace solo en almacén: sin stock en el POS e invisible
                # hasta su primer traslado. La mercancía entra vía Entrada.
                producto.stock = Decimal('0')
                producto.visible_pos = False
                producto.save(update_fields=['stock', 'visible_pos'])
                messages.info(
                    request,
                    f'{producto.nombre} nace solo en el almacén (sin stock en el POS). '
                    'Regístrele una Entrada y trasládelo para publicarlo.')
            else:
                producto.visible_pos = True
                producto.save(update_fields=['visible_pos'])
            formset = PresentacionFormSet(request.POST, instance=producto)
            if formset.is_valid():
                formset.save()
                _asegurar_presentacion_default(producto)
            else:
                _asegurar_presentacion_default(producto)
                messages.warning(request, 'Producto creado, pero revise las presentaciones.')
            if next_url:
                sep = '&' if '?' in next_url else '?'
                return redirect(f'{next_url}{sep}producto={producto.pk}')
            return redirect('core:producto_lista')
        else:
            formset = PresentacionFormSet(request.POST)
    else:
        form = ProductoForm()
        formset = PresentacionFormSet()
    return render(request, 'core/producto_form.html', {
        'form': form, 'formset': formset, 'titulo': 'Crear Producto',
        'next': next_url,
    })


def _presentacion_tiene_venta_hoy(presentacion):
    """True si la presentación se vendió hoy (ventas no canceladas)."""
    if not presentacion or not presentacion.pk:
        return False
    hoy = timezone.localdate()
    return DetalleVenta.objects.filter(
        presentacion=presentacion,
        venta__fecha_venta__date=hoy,
        venta__cancelada=False,
    ).exists()


def _asegurar_presentacion_default(producto):
    """Crea la presentación default x1 si el producto quedó sin ninguna."""
    from .models import PresentacionProducto
    if producto.presentaciones.exists():
        # Si hay pero ninguna marcada default, marca la primera.
        if not producto.presentaciones.filter(es_default=True).exists():
            primera = producto.presentaciones.order_by('factor').first()
            primera.es_default = True
            primera.save(update_fields=['es_default'])
        return
    nombres = {'kg': 'Kilogramo', 'lb': 'Libra', 'metros': 'Metro',
               'unidades': 'Unidad', 'gramos': 'Gramo'}
    PresentacionProducto.objects.create(
        producto=producto,
        nombre=nombres.get(producto.unidad_medida, 'Unidad'),
        factor=1,
        precio=producto.precio_venta,
        es_default=True,
        activo=True,
    )


@requiere_admin
def producto_editar(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    # Nombre en BD antes de que el form mutara la instancia (para borrar
    # el archivo anterior si la imagen cambia).
    try:
        imagen_anterior = Producto.objects.filter(pk=producto.pk).values_list('imagen', flat=True).first() or ''
    except Exception:
        imagen_anterior = ''
    if request.method == 'POST':
        form = ProductoForm(request.POST, request.FILES, instance=producto)
        # El stock NO se toca aquí: solo se modifica desde Ajustes (o Entradas/Ventas/POS)
        form.fields.pop('stock', None)
        formset = PresentacionFormSet(request.POST, instance=producto)
        if form.is_valid() and formset.is_valid():
            # Bloquear borrado (checkbox DELETE) si la presentación se vendió hoy
            bloqueadas = [
                f.instance.nombre for f in formset.deleted_forms
                if f.instance.pk and _presentacion_tiene_venta_hoy(f.instance)
            ]
            if bloqueadas:
                messages.error(
                    request,
                    'No se puede borrar ' + ', '.join('"%s"' % n for n in bloqueadas) +
                    ': tiene venta(s) en el día de hoy.'
                )
            else:
                compra_antes = producto.precio_compra
                venta_antes = producto.precio_venta
                form.save()
                formset.save()
                _asegurar_presentacion_default(producto)
                producto.refresh_from_db()
                # Al cambiar la imagen se borra el archivo anterior (evita huérfanos).
                imagen_nueva = producto.imagen.name if producto.imagen else ''
                if imagen_anterior and imagen_nueva and imagen_anterior != imagen_nueva:
                    try:
                        from django.core.files.storage import default_storage
                        if default_storage.exists(imagen_anterior):
                            default_storage.delete(imagen_anterior)
                    except Exception:
                        pass
                _log_cambio_precio(
                    producto, compra_antes, producto.precio_compra,
                    venta_antes, producto.precio_venta,
                    accion='edicion_manual', motivo='',
                    usuario=request.user)
                return redirect('core:producto_detalle', pk=producto.pk)
    else:
        form = ProductoForm(instance=producto)
        form.fields.pop('stock', None)
        formset = PresentacionFormSet(instance=producto)
    # Marcar qué presentaciones tienen venta hoy para bloquear su borrado en el template
    for f in formset.forms:
        try:
            f.tiene_venta_hoy = bool(f.instance.pk and _presentacion_tiene_venta_hoy(f.instance))
        except Exception:
            f.tiene_venta_hoy = False
    return render(request, 'core/producto_form.html', {
        'form': form,
        'formset': formset,
        'titulo': 'Editar Producto',
        'producto': producto,
    })


@requiere_admin
@require_POST
def presentacion_eliminar(request, pk):
    """Borrado directo de una presentación (cruz ✕ de la tarjeta).

    - 409 si tiene venta(s) en el día de hoy.
    - Si tiene historial (ventas/deudas de otros días) se desactiva en vez de
      borrar (las FK son PROTECT) para no romper el historial.
    - Si no, se elimina de forma permanente.
    """
    from .models import PresentacionProducto
    pres = get_object_or_404(PresentacionProducto, pk=pk)
    if _presentacion_tiene_venta_hoy(pres):
        return JsonResponse(
            {'ok': False, 'error': f'No se puede borrar "{pres.nombre}": tiene venta(s) en el día de hoy.'},
            status=409,
        )
    tiene_historial = (
        DetalleVenta.objects.filter(presentacion=pres).exists()
        or Deuda.objects.filter(presentacion=pres).exists()
    )
    try:
        if tiene_historial:
            pres.activo = False
            if pres.es_default:
                pres.es_default = False
            pres.save(update_fields=['activo', 'es_default'])
            _asegurar_presentacion_default(pres.producto)
            return JsonResponse({'ok': True, 'desactivada': True})
        nombre = pres.nombre
        producto = pres.producto
        pres.delete()
        _asegurar_presentacion_default(producto)
        return JsonResponse({'ok': True, 'desactivada': False})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@requiere_admin
@require_POST
def producto_imagen_eliminar(request, pk):
    producto = get_object_or_404(Producto, pk=pk)
    if producto.imagen:
        try:
            producto.imagen.delete(save=False)
        except Exception:
            pass
        producto.imagen = None
        producto.save(update_fields=['imagen'])
        messages.success(request, f'Imagen de "{producto.nombre}" eliminada.')
    # Respuesta JSON para borrado directo por AJAX/fetch (botón Eliminar)
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({'ok': True})
    return redirect('core:producto_editar', pk=pk)


@requiere_admin
def producto_imagen_recortar(request, pk):
    """Recorta la imagen del producto (cuadrado 1:1 u otras proporciones).

    GET: editor visual con selector de proporción sobre la imagen real.
    POST (x, y, w, h en píxeles naturales): recorta el rectángulo,
    convierte a WebP y reemplaza la imagen (borra el archivo anterior
    si cambia de nombre).
    """
    from PIL import Image as _Img
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    producto = get_object_or_404(Producto, pk=pk)
    nombre_actual = producto.imagen.name if producto.imagen else ''
    if not nombre_actual or not default_storage.exists(nombre_actual):
        messages.warning(request, 'Este producto no tiene imagen para recortar.')
        return redirect('core:producto_detalle', pk=pk)
    if request.method == 'POST':
        try:
            x, y, w, h = (int(request.POST.get(k, 0) or 0) for k in ('x', 'y', 'w', 'h'))
        except (TypeError, ValueError):
            x = y = w = h = 0
        if x < 0 or y < 0 or w < 50 or h < 50:
            messages.error(request, 'Selección inválida: marque un área de al menos 50 × 50 px.')
            return redirect('core:producto_imagen_recortar', pk=pk)
        try:
            with default_storage.open(nombre_actual, 'rb') as f:
                img = _Img.open(f)
                img.load()
            ancho, alto = img.size
            # Recorta el rectángulo y limita a los bordes reales.
            x = max(0, min(x, ancho - 1))
            y = max(0, min(y, alto - 1))
            w = max(50, min(w, ancho - x))
            h = max(50, min(h, alto - y))
            recorte = img.crop((x, y, x + w, y + h))
            if recorte.mode in ('RGBA', 'LA', 'PA'):
                try:
                    if recorte.getchannel('A').getextrema() == (255, 255):
                        recorte = recorte.convert('RGB')
                except Exception:
                    recorte = recorte.convert('RGB')
            elif recorte.mode != 'RGB':
                recorte = recorte.convert('RGB')
            import io as _io
            import os as _os
            import re as _re
            import time as _time
            buf = _io.BytesIO()
            recorte.save(buf, format='WEBP', quality=88, method=6)
            buf.seek(0)
            base = _os.path.splitext(nombre_actual)[0]
            # Quita sufijo previo de recorte para no acumular (_r123_r456...).
            base = _re.sub(r'_r\d+$', '', base)
            # Nombre único por recorte: la URL cambia y la Store/POS
            # muestra la nueva imagen sin quedar la anterior cacheada.
            nuevo = f"{base}_r{int(_time.time() * 1000)}.webp"
            if default_storage.exists(nuevo):
                default_storage.delete(nuevo)
            default_storage.save(nuevo, ContentFile(buf.read()))
            producto.imagen = nuevo
            producto.save(update_fields=['imagen', 'fecha_actualizacion'])
            if nuevo != nombre_actual and default_storage.exists(nombre_actual):
                default_storage.delete(nombre_actual)
        except Exception:
            messages.error(request, 'No se pudo procesar la imagen. Inténtelo de nuevo.')
            return redirect('core:producto_imagen_recortar', pk=pk)
        messages.success(request, f'Imagen de "{producto.nombre}" recortada y convertida a WebP.')
        return redirect('core:producto_detalle', pk=pk)
    try:
        with default_storage.open(nombre_actual, 'rb') as f:
            img = _Img.open(f)
            img.load()
            tamano = img.size
    except Exception:
        messages.error(request, 'No se pudo leer la imagen actual.')
        return redirect('core:producto_detalle', pk=pk)
    return render(request, 'core/producto_imagen_recortar.html', {
        'producto': producto,
        'ancho': tamano[0],
        'alto': tamano[1],
    })


def _conteo_relacionados_producto(producto):
    """Cuenta los registros ligados al producto (para avisar antes de borrar)."""
    from .models import (
        DetalleVenta, EntradaProducto, RetiroDonacion, MovimientoInventario,
        InventarioDiario, HistorialPrecio, Deuda, ConteoCiegoLinea,
        PresentacionProducto,
    )
    pres_ids = list(producto.presentaciones.values_list('id', flat=True))
    conteos = [
        ('Detalles de venta', DetalleVenta.objects.filter(producto=producto).count()),
        ('Entradas de inventario', EntradaProducto.objects.filter(producto=producto).count()),
        ('Retiros / donaciones', RetiroDonacion.objects.filter(producto=producto).count()),
        ('Movimientos de inventario', MovimientoInventario.objects.filter(producto=producto).count()),
        ('Inventarios diarios', InventarioDiario.objects.filter(producto=producto).count()),
        ('Historial de precios', HistorialPrecio.objects.filter(producto=producto).count()),
        ('Deudas con este producto', Deuda.objects.filter(producto=producto).count()),
        ('Líneas de conteo ciego', ConteoCiegoLinea.objects.filter(producto=producto).count()),
        ('Presentaciones', PresentacionProducto.objects.filter(producto=producto).count()),
    ]
    if pres_ids:
        conteos.append(('Deudas por presentación',
                         Deuda.objects.filter(presentacion_id__in=pres_ids).exclude(producto=producto).count()))
        conteos.append(('Ventas por presentación',
                         DetalleVenta.objects.filter(presentacion_id__in=pres_ids).exclude(producto=producto).count()))
    return [(n, c) for n, c in conteos if c > 0]


def _eliminar_producto_en_cascada(producto):
    """Borra el producto y TODOS sus registros ligados en una transacción.

    Orden pensado para respetar los on_delete=PROTECT:
    primero se borran Detalles/Deudas (que bloquean), luego el resto.
    Las ventas que queden vacías (sin detalles) también se eliminan
    para no dejar tickets huérfanos.
    Devuelve el nombre del producto borrado.
    """
    from .models import (
        DetalleVenta, EntradaProducto, RetiroDonacion, MovimientoInventario,
        InventarioDiario, HistorialPrecio, Deuda, ConteoCiegoLinea,
        PresentacionProducto,
    )
    with transaction.atomic():
        pres_ids = list(producto.presentaciones.values_list('id', flat=True))
        venta_ids = list(
            DetalleVenta.objects.filter(producto=producto).values_list('venta_id', flat=True).distinct()
        )
        if pres_ids:
            venta_ids += list(
                DetalleVenta.objects.filter(presentacion_id__in=pres_ids)
                .values_list('venta_id', flat=True).distinct()
            )
            # Liberar FK PROTECT hacia presentaciones antes de borrarlas.
            Deuda.objects.filter(presentacion_id__in=pres_ids).delete()
            DetalleVenta.objects.filter(presentacion_id__in=pres_ids).delete()
        DetalleVenta.objects.filter(producto=producto).delete()
        Deuda.objects.filter(producto=producto).delete()
        EntradaProducto.objects.filter(producto=producto).delete()
        RetiroDonacion.objects.filter(producto=producto).delete()
        ConteoCiegoLinea.objects.filter(producto=producto).delete()
        MovimientoInventario.objects.filter(producto=producto).delete()
        InventarioDiario.objects.filter(producto=producto).delete()
        HistorialPrecio.objects.filter(producto=producto).delete()
        PresentacionProducto.objects.filter(producto=producto).delete()
        # Ventas que se quedaron sin líneas tras el borrado.
        if venta_ids:
            Venta.objects.filter(id__in=set(venta_ids)).annotate(
                n=Count('detalles')).filter(n=0).delete()
        try:
            if producto.imagen:
                producto.imagen.delete(save=False)
        except Exception:
            pass
        nombre = producto.nombre
        producto.delete()
        return nombre


@requiere_admin
def producto_eliminar(request, pk):
    """Borrado en 2 pasos:

    Paso 1 (producto activo): solo lo DESACTIVA (ya no sale en el POS).
    Paso 2 (producto ya inactivo): exige escribir ELIMINAR y lo borra
    DEFINITIVAMENTE en cascada con todo su historial.
    """
    producto = get_object_or_404(Producto, pk=pk)
    relacionados = _conteo_relacionados_producto(producto)
    if request.method == 'POST':
        if producto.activo:
            producto.activo = False
            producto.save(update_fields=['activo'])
            messages.warning(
                request,
                f'Producto "{producto.nombre}" desactivado. Ya no aparece en el POS. '
                'Para borrarlo para siempre (con todo su historial en cascada), '
                'vuelve a pulsar Eliminar y escribe ELIMINAR para confirmar.'
            )
            return redirect('core:producto_lista')
        confirmacion = (request.POST.get('confirmacion') or '').strip().upper()
        if confirmacion != 'ELIMINAR':
            messages.error(request, 'Debes escribir ELIMINAR para confirmar el borrado definitivo.')
            return render(request, 'core/producto_confirmar_eliminar.html', {
                'producto': producto,
                'relacionados': relacionados,
                'es_definitivo': True,
            })
        nombre = _eliminar_producto_en_cascada(producto)
        messages.success(
            request,
            f'Producto "{nombre}" eliminado definitivamente junto con su historial en cascada.'
        )
        return redirect('core:producto_lista')
    return render(request, 'core/producto_confirmar_eliminar.html', {
        'producto': producto,
        'relacionados': relacionados,
        'es_definitivo': not producto.activo,
    })


@requiere_admin
@require_POST
def producto_eliminar_definitivo(request, pk):
    """Versión JSON del borrado en 2 pasos (para AJAX).

    - Si el producto está activo: lo desactiva y responde deactivated=True.
    - Si ya está inactivo: exige {"confirmacion": "ELIMINAR"} y lo borra en cascada.
    """
    producto = get_object_or_404(Producto, pk=pk)
    try:
        if producto.activo:
            producto.activo = False
            producto.save(update_fields=['activo'])
            return JsonResponse({
                'success': True,
                'message': (
                    f'Producto "{producto.nombre}" desactivado. Ya no aparece en el POS. '
                    'Vuelve a eliminarlo y escribe ELIMINAR para el borrado definitivo en cascada.'
                ),
                'deactivated': True,
                'requiere_confirmacion': True,
            })
        # Ya inactivo: confirmar texto ELIMINAR (JSON o form).
        confirmacion = ''
        if request.content_type and 'application/json' in request.content_type:
            try:
                confirmacion = (json.loads(request.body or '{}').get('confirmacion') or '')
            except Exception:
                confirmacion = ''
        else:
            confirmacion = request.POST.get('confirmacion', '')
        if str(confirmacion).strip().upper() != 'ELIMINAR':
            return JsonResponse({
                'success': False,
                'error': 'Escribe ELIMINAR para confirmar el borrado definitivo en cascada.',
                'requiere_confirmacion': True,
            }, status=400)
        nombre = _eliminar_producto_en_cascada(producto)
        return JsonResponse({
            'success': True,
            'message': f'Producto "{nombre}" eliminado definitivamente en cascada.',
            'deactivated': False,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================
# CATEGORIAS
# ============================================================

@requiere_admin
def categoria_lista(request):
    qs = Categoria.objects.select_related('padre').annotate(num_productos=Count('productos'))
    cats = list(qs)
    por_padre = {}
    for c in cats:
        por_padre.setdefault(c.padre_id, []).append(c)
    for lista in por_padre.values():
        lista.sort(key=lambda c: c.nombre.lower())
    # Subtotales: productos del subárbol (padre + hijas recursivas).
    hijos_map = {}
    for c in cats:
        hijos_map.setdefault(c.padre_id, []).append(c)
    def _subtotal(cat):
        total = getattr(cat, 'num_productos', 0) or 0
        for h in hijos_map.get(cat.id, []):
            total += _subtotal(h)
        return total
    for c in cats:
        c.subtotal = _subtotal(c)
    padres = por_padre.get(None, [])
    arbol = [{'padre': p, 'hijas': por_padre.get(p.id, [])} for p in padres]
    huerfanas = [c for c in cats if c.padre_id and not any(c.padre_id == x.id for x in cats)]
    return render(request, 'core/categoria_lista.html', {'categorias': cats, 'padres': padres, 'arbol': arbol, 'huerfanas': huerfanas})


@requiere_admin
def categoria_crear(request):
    padre_init = request.GET.get('padre')
    if request.method == 'POST':
        form = CategoriaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect('core:categoria_lista')
    else:
        initial = {}
        try:
            if padre_init and Categoria.objects.filter(pk=int(padre_init)).exists():
                initial['padre'] = int(padre_init)
        except (ValueError, TypeError):
            pass
        form = CategoriaForm(initial=initial)
    return render(request, 'core/categoria_form.html', {'form': form, 'titulo': 'Crear Categoria'})


@requiere_admin
def categoria_editar(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        form = CategoriaForm(request.POST, instance=categoria)
        if form.is_valid():
            form.save()
            return redirect('core:categoria_lista')
    else:
        form = CategoriaForm(instance=categoria)
    return render(request, 'core/categoria_form.html', {'form': form, 'titulo': 'Editar Categoria'})


@requiere_admin
def categoria_eliminar(request, pk):
    categoria = get_object_or_404(Categoria, pk=pk)
    if request.method == 'POST':
        categoria.delete()
        return redirect('core:categoria_lista')
    return render(request, 'core/categoria_confirmar_eliminar.html', {'categoria': categoria})


# ============================================================
# EMPLEADOS
# ============================================================

@requiere_admin
def empleado_lista(request):
    empleados = Empleado.objects.select_related('user').all()
    es_multi_pos = modo_actual() == 'multi_pos'
    context = {
        'empleados': empleados,
        'ahora': timezone.make_aware(ahora_servidor()),
        'es_multi_pos': es_multi_pos,
        'puntos_venta': list(
            PuntoVenta.activos().select_related('almacen')) if es_multi_pos else [],
    }
    return render(request, 'core/empleado_lista.html', context)


@requiere_admin
def empleado_crear(request):
    if request.method == 'POST':
        form = EmpleadoForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Empleado creado correctamente.')
            return redirect('core:empleado_lista')
    else:
        form = EmpleadoForm()
        if modo_actual() == 'solo_pos':
            messages.warning(
                request,
                'En el modo solo-POS el rol almacenero no tiene pantallas: '
                'se sugiere asignar cajero.')
    return render(request, 'core/empleado_form.html', {'form': form, 'titulo': 'Crear Empleado'})


@requiere_admin
def empleado_editar(request, pk):
    empleado = get_object_or_404(Empleado, pk=pk)
    if request.method == 'POST':
        form = EmpleadoForm(request.POST, instance=empleado, user_instance=empleado.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Empleado actualizado correctamente.')
            return redirect('core:empleado_lista')
    else:
        form = EmpleadoForm(instance=empleado, user_instance=empleado.user)
        if modo_actual() == 'solo_pos':
            messages.warning(
                request,
                'En el modo solo-POS el rol almacenero no tiene pantallas: '
                'se sugiere asignar cajero.')
    return render(request, 'core/empleado_form.html', {
        'form': form,
        'titulo': 'Editar Empleado',
        'empleado': empleado,
    })


@requiere_admin
@require_POST
def empleado_toggle_activo(request, pk):
    empleado = get_object_or_404(Empleado, pk=pk)
    empleado.activo = not empleado.activo
    empleado.save()
    empleado.user.is_active = empleado.activo
    empleado.user.save()
    estado = 'activado' if empleado.activo else 'desactivado'
    messages.success(request, f'Empleado {estado} correctamente.')
    return redirect('core:empleado_lista')


@requiere_admin
def empleado_eliminar(request, pk):
    empleado = get_object_or_404(Empleado, pk=pk)
    if request.method == 'POST':
        nombre = str(empleado)
        try:
            empleado.user.delete()
            messages.success(request, f'Empleado {nombre} eliminado.')
        except ProtectedError:
            # Tiene ventas/gastos u otros registros: no se puede borrar,
            # se desactiva para que no inicie sesión ni venda.
            empleado.activo = False
            empleado.save(update_fields=['activo'])
            user = empleado.user
            user.is_active = False
            user.save(update_fields=['is_active'])
            messages.warning(
                request,
                f'{nombre} tiene movimientos registrados y no se puede eliminar: '
                'se desactivó y ya no puede iniciar sesión.')
        return redirect('core:empleado_lista')
    return render(request, 'core/empleado_confirmar_eliminar.html', {'empleado': empleado})


# ============================================================
# TURNOS
# ============================================================

@requiere_admin
@require_POST
def turno_abrir(request, pk):
    empleado = get_object_or_404(Empleado, pk=pk, activo=True)
    if empleado.en_turno:
        messages.warning(request, f'{empleado} ya tiene un turno abierto.')
    elif modo_actual() == 'multi_pos':
        # Spec §5: un POS por turno. El trabajador selecciona a qué POS va
        # a trabajar (POST 'punto_venta'); su asignación se fija al abrir
        # turno y puede cambiar entre turnos. Sin POS no hay turno.
        try:
            pos_id = int(request.POST.get('punto_venta') or 0)
        except (ValueError, TypeError):
            pos_id = 0
        pos = PuntoVenta.objects.filter(pk=pos_id, activo=True).first()
        if pos is None:
            messages.error(
                request,
                'Seleccione el punto de venta del turno '
                '(obligatorio en el modo multi-POS).')
        else:
            Turno.objects.create(empleado=empleado, punto_venta=pos)
            if empleado.punto_venta_id != pos.pk:
                empleado.punto_venta = pos
                empleado.save(update_fields=['punto_venta'])
            messages.success(
                request, f'Turno abierto para {empleado} en {pos}.')
    else:
        Turno.objects.create(empleado=empleado)
        messages.success(request, f'Turno abierto para {empleado}.')
    return redirect('core:empleado_lista')


@requiere_admin
def empleado_turnos(request, pk):
    empleado = get_object_or_404(Empleado, pk=pk)
    turnos = empleado.turnos.all()[:30]
    return render(request, 'core/empleado_turnos.html', {
        'empleado': empleado,
        'turnos': turnos,
    })


# ============================================================
# VENTAS
# ============================================================

@requiere_admin
def venta_lista(request):
    from datetime import timedelta
    from django.utils import timezone
    fecha_str = request.GET.get('fecha', '')
    empleado_filtro = request.GET.get('empleado', '')
    periodo = request.GET.get('periodo', 'dia')

    hoy = ahora_servidor().date()
    
    if fecha_str:
        try:
            fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = hoy
    else:
        fecha = hoy

    ventas = Venta.objects.filter(cancelada=False).select_related('cajero', 'punto_venta')

    # Spec §5 multi-POS: filtro ?pos= por punto_venta (fuera de
    # multi-POS se ignora).
    pos_actual, puntos_venta = _resolver_pos_filtro(request)
    if pos_actual is not None:
        ventas = ventas.filter(punto_venta=pos_actual)

    if periodo == 'dia':
        titulo = f'Ventas del dia {fecha.strftime("%d/%m/%Y")}'
        fecha_dt = timezone.make_aware(timezone.datetime.combine(fecha, timezone.datetime.min.time()))
        fd = fecha_dt
        fh = fecha_dt + timedelta(days=1)
        ventas = ventas.filter(fecha_venta__gte=fd, fecha_venta__lt=fh)
    elif periodo == 'mes':
        titulo = f'Ventas de {fecha.strftime("%B %Y")}'
        ventas = ventas.filter(
            fecha_venta__year=fecha.year,
            fecha_venta__month=fecha.month
        )
    elif periodo == 'ano':
        titulo = f'Ventas del ano {fecha.year}'
        ventas = ventas.filter(fecha_venta__year=fecha.year)
    else:
        titulo = f'Ventas del dia {fecha.strftime("%d/%m/%Y")}'
        ventas = ventas.filter(fecha_venta__date=fecha)

    if empleado_filtro:
        ventas = ventas.filter(cajero__username=empleado_filtro)

    resumen = ventas.aggregate(
        total=Sum('total') or 0,
        cantidad=Count('id')
    )
    
    # Resumen de dinero por tipo de pago
    # OJO: monto_recibido es el efectivo ENTREGADO (incluye el cambio devuelto),
    # por eso el efectivo neto = recibido - cambio. Asi cuadra:
    #   efectivo_neto + transferencia = total de ventas.
    resumen_dinero = ventas.aggregate(
        efectivo=Sum('monto_recibido'),
        transferencia=Sum('monto_transferencia'),
        cambio=Sum('cambio'),
    )
    
    # Gastos del periodo
    gastos_qs = Gasto.objects.filter(fecha_gasto__date=fecha) if periodo == 'dia' else Gasto.objects.all()
    if periodo == 'dia':
        gastos_qs = gastos_qs.filter(fecha_gasto__date=fecha)
    elif periodo == 'mes':
        gastos_qs = gastos_qs.filter(fecha_gasto__year=fecha.year, fecha_gasto__month=fecha.month)
    elif periodo == 'ano':
        gastos_qs = gastos_qs.filter(fecha_gasto__year=fecha.year)
    
    if empleado_filtro:
        gastos_qs = gastos_qs.filter(cajero__username=empleado_filtro)

    # En la vista por POS, los gastos atribuidos son los de sus turnos
    # (Gasto.turno→punto_venta); los de admin sin turno quedan en el global.
    if pos_actual is not None:
        gastos_qs = gastos_qs.filter(turno__punto_venta=pos_actual)
    
    resumen_gastos = gastos_qs.aggregate(
        total=Sum(F('cantidad_efectivo') + F('cantidad_transferencia')) or 0,
        cantidad=Count('id')
    )

    empleados = Empleado.objects.filter(activo=True).select_related('user')

    context = {
        'ventas': ventas,
        'fecha': fecha.strftime('%Y-%m-%d'),
        'periodo': periodo,
        'titulo': titulo,
        'empleado_filtro': empleado_filtro,
        'empleados': empleados,
        'resumen_total': resumen['total'] or 0,
        'resumen_cantidad': resumen['cantidad'] or 0,
        'resumen_efectivo': (resumen_dinero['efectivo'] or 0) - (resumen_dinero['cambio'] or 0),
        'resumen_efectivo_recibido': resumen_dinero['efectivo'] or 0,
        'resumen_cambio': resumen_dinero['cambio'] or 0,
        'resumen_transferencia': resumen_dinero['transferencia'] or 0,
        'resumen_gastos': resumen_gastos['total'] or 0,
        'resumen_gastos_cantidad': resumen_gastos['cantidad'] or 0,
        'resumen_neto': (resumen['total'] or 0) - (resumen_gastos['total'] or 0),
        'hoy': hoy.strftime('%Y-%m-%d'),
        'es_multi_pos': modo_actual() == 'multi_pos',
        'puntos_venta': puntos_venta,
        'pos_actual': pos_actual,
    }
    return render(request, 'core/venta_lista.html', context)


@requiere_admin
def venta_crear(request):
    productos = Producto.objects.filter(activo=True).select_related('categoria').order_by('nombre')
    empleados = Empleado.objects.filter(activo=True).select_related('user')
    hoy = ahora_servidor().date()
    # Prefill ?fecha= (botón "venta de este día" desde IPB/lista), validado.
    fecha_default = hoy
    fecha_qs = request.GET.get('fecha', '')
    if fecha_qs:
        try:
            _fq = timezone.datetime.strptime(fecha_qs, '%Y-%m-%d').date()
            if FECHA_INICIO_SISTEMA <= _fq <= hoy:
                fecha_default = _fq
        except ValueError:
            pass

    if request.method == 'POST':
        if modo_actual() == 'multi_pos':
            messages.error(
                request,
                'En modo multi-POS la venta manual está desactivada: '
                'venda desde el terminal del POS.')
            return redirect('core:venta_crear')
        empleado_id = request.POST.get('cajero')
        fecha_str = request.POST.get('fecha', '')
        metodo_pago = request.POST.get('metodo_pago', 'efectivo')
        if metodo_pago not in ('efectivo', 'transferencia', 'mixto'):
            metodo_pago = 'efectivo'
        monto_efectivo = Decimal(request.POST.get('monto_efectivo') or '0')
        monto_transferencia = Decimal(request.POST.get('monto_transferencia') or '0')
        productos_data = request.POST.get('productos_data', '')

        try:
            cajero = User.objects.get(empleado__id=empleado_id) if empleado_id else request.user

            if fecha_str:
                fecha_elegida = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
            else:
                fecha_elegida = hoy
            if fecha_elegida < FECHA_INICIO_SISTEMA:
                messages.error(request, 'No se puede vender antes del 22/09/2026 (inicio del sistema).')
                return redirect('core:venta_crear')
            if fecha_elegida > hoy:
                messages.error(request, 'No se puede vender en fecha futura.')
                return redirect('core:venta_crear')
            fecha_hora = timezone.make_aware(
                timezone.datetime.combine(fecha_elegida, ahora_servidor().time()))

            import json
            items = json.loads(productos_data or '[]')
            if not items:
                messages.error(request, 'Agregue al menos un producto.')
                return redirect('core:venta_crear')

            with transaction.atomic():
                venta = Venta.objects.create(
                    numero_venta=Venta.generar_numero(),
                    cajero=cajero,
                    subtotal=Decimal('0'),
                    impuesto=Decimal('0'),
                    total=Decimal('0'),
                    metodo_pago=metodo_pago,
                    monto_recibido=monto_efectivo,
                    monto_transferencia=monto_transferencia,
                    cambio=Decimal('0'),
                    cancelada=False,
                )
                # fecha_venta es auto_now_add: hay que fijarla en un 2do save.
                venta.fecha_venta = fecha_hora
                venta.save(update_fields=['fecha_venta'])
                for item in items:
                    producto = get_object_or_404(Producto, pk=item['producto_id'], activo=True)
                    cantidad = Decimal(str(item['cantidad']))
                    if cantidad <= 0:
                        raise ValueError(f'Cantidad inválida en {producto.nombre}.')
                    if not producto.permite_decimal and cantidad != cantidad.to_integral_value():
                        raise ValueError(f'{producto.nombre} solo admite unidades enteras.')
                    _, factor, precio = _resolver_presentacion(producto, item.get('presentacion_id'))
                    cantidad_base = (cantidad * factor).quantize(Decimal('0.001'))
                    if cantidad_base > producto.stock:
                        raise ValueError(
                            f'Stock insuficiente en {producto.nombre}. Disponible: {"%g" % float(producto.stock)}.')
                    DetalleVenta.objects.create(
                        venta=venta,
                        producto=producto,
                        cantidad=cantidad,
                        cantidad_base=cantidad_base,
                        precio_unitario=precio,
                        subtotal=precio * cantidad,
                        costo_unitario_base=producto.precio_compra or 0,
                    )
                    _registrar_movimiento(producto, 'venta', cantidad_base, request.user,
                                          venta.id, f'Venta #{venta.numero_venta} manual ({fecha_elegida:%d/%m/%Y})')

                _recalcular_venta(venta)
                completado, aviso_mixto = _ajustar_pago_venta(venta)
                for det in venta.detalles.select_related('producto').all():
                    _reencadenar_producto_desde(det.producto, fecha_elegida)

            if aviso_mixto:
                messages.warning(
                    request, f'Venta {venta.numero_venta} del {fecha_elegida:%d/%m/%Y} creada, '
                    'pero es MIXTA: designe el monto en efectivo y transferencia editándola.')
            else:
                messages.success(
                    request, f'Venta {venta.numero_venta} del {fecha_elegida:%d/%m/%Y} registrada. Stock actualizado.')
            return redirect('core:venta_lista')
        except Exception as e:
            messages.error(request, f'Error al registrar venta: {str(e)}')
            return redirect('core:venta_crear')

    context = {
        'productos': productos,
        'empleados': empleados,
        'fecha_default': fecha_default.strftime('%Y-%m-%d'),
        'fecha_min': FECHA_INICIO_SISTEMA.strftime('%Y-%m-%d'),
        'fecha_max': hoy.strftime('%Y-%m-%d'),
    }
    return render(request, 'core/venta_form.html', context)


@requiere_admin
def venta_detalle(request, pk):
    venta = get_object_or_404(Venta.objects.select_related('cajero', 'turno__empleado'), pk=pk)
    detalles = venta.detalles.select_related('producto', 'presentacion').all()
    return render(request, 'core/venta_detalle.html', {
        'venta': venta,
        'detalles': detalles,
    })


@requiere_admin
def venta_editar(request, pk):
    venta = get_object_or_404(Venta, pk=pk)
    detalles = venta.detalles.select_related('producto', 'presentacion').all()
    productos = Producto.objects.filter(activo=True).prefetch_related('presentaciones')

    if request.method == 'POST':
        action = request.POST.get('action')

        if venta.punto_venta_id is not None and action in (
                'agregar_producto', 'eliminar_detalle',
                'actualizar_cantidad', 'cancelar_venta'):
            messages.error(
                request,
                'Esta venta es de un punto de venta y no puede editarse '
                'ni cancelarse aquí: use el terminal del POS.')
            return redirect('core:venta_editar', pk=venta.pk)

        if action == 'agregar_producto':
            producto_id = request.POST.get('producto_id')
            presentacion_id = request.POST.get('presentacion_id') or None
            try:
                cantidad = Decimal(str(request.POST.get('cantidad', '1')))
            except Exception:
                messages.error(request, 'Cantidad inválida.')
                return redirect('core:venta_editar', pk=venta.pk)
            producto = get_object_or_404(Producto, pk=producto_id, activo=True)
            if cantidad <= 0:
                messages.error(request, 'Cantidad inválida.')
                return redirect('core:venta_editar', pk=venta.pk)
            if not producto.permite_decimal and cantidad != cantidad.to_integral_value():
                messages.error(request, f'{producto.nombre} solo admite unidades enteras.')
                return redirect('core:venta_editar', pk=venta.pk)
            presentacion, factor, precio = _resolver_presentacion(producto, presentacion_id)
            cantidad_base = (cantidad * factor).quantize(Decimal('0.001'))
            if cantidad_base > producto.stock:
                messages.error(request, f'Stock insuficiente. Disponible: {"%g" % float(producto.stock)} {producto.unidad_medida}.')
                return redirect('core:venta_editar', pk=venta.pk)

            with transaction.atomic():
                detalle_existente = detalles.filter(producto=producto, presentacion=presentacion).first()
                if detalle_existente:
                    detalle_existente.cantidad += cantidad
                    detalle_existente.cantidad_base += cantidad_base
                    detalle_existente.subtotal = detalle_existente.cantidad * detalle_existente.precio_unitario
                    detalle_existente.save()
                else:
                    DetalleVenta.objects.create(
                        venta=venta,
                        producto=producto,
                        presentacion=presentacion,
                        cantidad=cantidad,
                        cantidad_base=cantidad_base,
                        precio_unitario=precio,
                        subtotal=precio * cantidad,
                        costo_unitario_base=producto.precio_compra or 0,
                    )

                _registrar_movimiento(producto, 'venta', cantidad_base, request.user, venta.id, f'Venta #{venta.numero_venta} - Producto agregado en edición')
                _recalcular_venta(venta)
                completado, aviso_mixto = _ajustar_pago_venta(venta)
                _reencadenar_producto_desde(producto, venta.fecha_venta.date())

            if aviso_mixto:
                messages.warning(request,
                    f'Producto {producto.nombre} agregado, pero la venta es MIXTA y falta dinero: '
                    'designe el monto en efectivo y transferencia.')
            elif completado:
                messages.success(request, f'Producto {producto.nombre} agregado. Pago y stock actualizados.')
            return redirect('core:venta_editar', pk=venta.pk)

        elif action == 'eliminar_detalle':
            detalle_id = request.POST.get('detalle_id')
            detalle = get_object_or_404(DetalleVenta, pk=detalle_id, venta=venta)
            nombre = detalle.producto.nombre
            cantidad_devuelta = detalle.cantidad_base or detalle.cantidad
            producto = detalle.producto
            with transaction.atomic():
                detalle.delete()
                _registrar_movimiento(producto, 'devolucion', cantidad_devuelta, request.user, venta.id, f'Venta #{venta.numero_venta} - Producto eliminado en edición')
                _recalcular_venta(venta)
                _ajustar_pago_venta(venta)
                _reencadenar_producto_desde(producto, venta.fecha_venta.date())
            messages.success(request, f'Producto {nombre} eliminado. Pago y stock actualizados.')
            return redirect('core:venta_editar', pk=venta.pk)

        elif action == 'actualizar_cantidad':
            detalle_id = request.POST.get('detalle_id')
            try:
                cantidad_nueva = Decimal(str(request.POST.get('cantidad', '1')))
            except Exception:
                return redirect('core:venta_editar', pk=venta.pk)
            detalle = get_object_or_404(DetalleVenta, pk=detalle_id, venta=venta)
            factor = detalle.presentacion.factor if detalle.presentacion_id and detalle.presentacion else Decimal('1')
            cantidad_anterior = detalle.cantidad
            base_anterior = detalle.cantidad_base or (cantidad_anterior * factor)
            cantidad_base_nueva = (cantidad_nueva * factor).quantize(Decimal('0.001'))
            diferencia_base = cantidad_base_nueva - base_anterior

            aviso_mixto = False
            if cantidad_nueva <= 0:
                producto = detalle.producto
                with transaction.atomic():
                    detalle.delete()
                    _registrar_movimiento(producto, 'devolucion', base_anterior, request.user, venta.id, f'Venta #{venta.numero_venta} - Producto eliminado en edición')
                    _recalcular_venta(venta)
                    _ajustar_pago_venta(venta)
                    _reencadenar_producto_desde(producto, venta.fecha_venta.date())
            else:
                if diferencia_base > 0 and diferencia_base > detalle.producto.stock:
                    messages.error(request, 'Stock insuficiente para aumentar la cantidad.')
                    return redirect('core:venta_editar', pk=venta.pk)
                with transaction.atomic():
                    detalle.cantidad = cantidad_nueva
                    detalle.cantidad_base = cantidad_base_nueva
                    detalle.subtotal = cantidad_nueva * detalle.precio_unitario
                    detalle.save()
                    if diferencia_base > 0:
                        _registrar_movimiento(detalle.producto, 'venta', diferencia_base, request.user, venta.id, f'Venta #{venta.numero_venta} - Cantidad aumentada en edición')
                    elif diferencia_base < 0:
                        _registrar_movimiento(detalle.producto, 'devolucion', abs(diferencia_base), request.user, venta.id, f'Venta #{venta.numero_venta} - Cantidad reducida en edición')
                    _recalcular_venta(venta)
                    _, aviso_mixto = _ajustar_pago_venta(venta)
                    _reencadenar_producto_desde(detalle.producto, venta.fecha_venta.date())
            if aviso_mixto:
                messages.warning(request, 'Cantidad actualizada, pero la venta es MIXTA y falta dinero: designe los montos.')
            return redirect('core:venta_editar', pk=venta.pk)

        elif action == 'cancelar_venta':
            venta.cancelada = True
            venta.save()
            with transaction.atomic():
                for detalle in venta.detalles.all():
                    _registrar_movimiento(detalle.producto, 'devolucion', detalle.cantidad_base or detalle.cantidad, request.user, venta.id, f'Venta #{venta.numero_venta} cancelada')
                    _reencadenar_producto_desde(detalle.producto, venta.fecha_venta.date())
            messages.success(request, f'Venta {venta.numero_venta} cancelada. Stock restaurado.')
            return redirect('core:venta_lista')

        elif action == 'actualizar_pago':
            metodo_pago = request.POST.get('metodo_pago', 'efectivo')
            if metodo_pago not in ('efectivo', 'transferencia', 'mixto'):
                metodo_pago = 'efectivo'
            monto_efectivo = Decimal(request.POST.get('monto_efectivo') or '0')
            monto_transferencia = Decimal(request.POST.get('monto_transferencia') or '0')

            # El campo de la pata no usada viaja oculto con su valor viejo:
            # se normaliza según el método para que las tarjetas
            # Efectivo/Transferencia siempre cuadren con la realidad.
            if metodo_pago == 'efectivo':
                monto_transferencia = Decimal('0')
            elif metodo_pago == 'transferencia':
                monto_efectivo = Decimal('0')

            venta.metodo_pago = metodo_pago
            venta.monto_recibido = monto_efectivo
            venta.monto_transferencia = monto_transferencia

            total_pagado = monto_efectivo + monto_transferencia
            if total_pagado >= venta.total:
                venta.cambio = total_pagado - venta.total
            else:
                venta.cambio = 0

            venta.save()
            messages.success(request, 'Metodo de pago actualizado.')
            return redirect('core:venta_editar', pk=venta.pk)

        elif action == 'guardar':
            messages.success(request, 'Venta actualizada correctamente.')
            return redirect('core:venta_detalle', pk=venta.pk)

    return render(request, 'core/venta_editar.html', {
        'venta': venta,
        'detalles': detalles,
        'productos': productos,
    })


def _recalcular_venta(venta):
    detalles = venta.detalles.all()
    subtotal = sum(d.subtotal for d in detalles)
    venta.subtotal = subtotal
    venta.total = subtotal
    venta.save()


# ============================================================
# PUNTO DE VENTA
# ============================================================

def _turno_pos_almacen(request):
    """(turno, pos, almacen) del turno abierto para el modo multi-POS.

    Spec §5: el POS vende y descuenta directo del `AlmacenStock` del
    almacén asignado (sin stock propio). Si el usuario no tiene turno
    abierto o el turno no tiene POS, devuelve Nones y la vista debe
    bloquear con mensaje (sin descontar nada).
    """
    try:
        turno = request.user.empleado.turno_abierto
    except Exception:
        return None, None, None
    if turno is None or turno.punto_venta_id is None:
        return turno, None, None
    pos = turno.punto_venta
    almacen = pos.almacen if pos is not None else None
    if pos is None or almacen is None:
        return turno, None, None
    return turno, pos, almacen


@login_required
def pos(request):
    # Verificar si es cajero y si tiene turno abierto
    try:
        perfil = request.user.perfil
        if perfil.es_almacenero and not perfil.es_admin:
            if modo_actual() != 'solo_pos':
                return redirect('core:almacen_panel')
            # En solo-POS el almacenero queda sin pantallas y opera en el
            # POS (el aviso de reasignarlo a cajero se da en
            # redireccion_rol): sigue al render del POS.
        if perfil.es_cajero:
            try:
                empleado = request.user.empleado
                if not empleado.en_turno:
                    return render(request, 'core/pos_sin_turno.html', {'empleado': empleado})
            except Empleado.DoesNotExist:
                return render(request, 'core/pos_sin_turno.html', {'empleado': None})
    except PerfilUsuario.DoesNotExist:
        pass

    es_admin = request.user.perfil.es_admin if hasattr(request.user, 'perfil') else False

    if modo_actual() == 'multi_pos':
        # Spec §5: catálogo = existencias del almacén del turno
        # (`visible_pos` y `Producto.stock` no son la fuente aquí).
        _, pos_obj, almacen = _turno_pos_almacen(request)
        if pos_obj is None or almacen is None:
            messages.warning(
                request,
                'Sin punto de venta asignado en el turno: abra el turno '
                'seleccionando el punto de venta para vender.')
            return render(request, 'core/pos.html', {
                'productos': [],
                'categorias': [],
                'es_admin': es_admin,
                'es_multi_pos': True,
                'pos_actual': None,
                'almacen_origen': None,
                'bloqueo_pos': True,
            })
        stock_map = _stock_map_para(almacen)
        ids_multi = [pid for pid, cant in stock_map.items() if cant > 0]
        productos_multi = list(Producto.objects.filter(
            activo=True, id__in=ids_multi).select_related(
            'categoria').prefetch_related('presentaciones').order_by('nombre'))
        for p in productos_multi:
            # Solo memoria (NO guardar): la plantilla y el catálogo JS
            # leen `producto.stock` como stock disponible.
            p.stock = stock_map.get(p.id, Decimal('0'))
        categorias_multi = Categoria.objects.filter(
            productos__id__in=ids_multi).select_related('padre').distinct()
        return render(request, 'core/pos.html', {
            'productos': productos_multi,
            'categorias': categorias_multi,
            'arbol_pos': _arbol_pos(categorias_multi),
            'es_admin': es_admin,
            'es_multi_pos': True,
            'pos_actual': pos_obj,
            'almacen_origen': almacen,
            'bloqueo_pos': False,
        })

    productos = Producto.objects.filter(activo=True, visible_pos=True, stock__gt=0).select_related('categoria').prefetch_related('presentaciones').order_by('nombre')
    categorias = Categoria.objects.filter(productos__activo=True, productos__visible_pos=True, productos__stock__gt=0).select_related('padre').distinct()
    
    context = {
        'productos': productos,
        'categorias': categorias,
        'arbol_pos': _arbol_pos(categorias),
        'es_admin': es_admin,
    }
    return render(request, 'core/pos.html', context)


def _serializar_producto_pos(p, stock_override=None):
    """Producto + presentaciones para el POS (precio manual por presentación).

    `stock_override`: en multi-POS el disponible viene del AlmacenStock
    del turno (no de `Producto.stock`); el payload no cambia, así la
    cola offline (`bizm_offline_queue_v1`) sigue compatible.
    """
    pres = [{
        'id': pr.id,
        'nombre': pr.nombre,
        'factor': str(pr.factor),
        'precio': str(pr.precio),
        'es_default': pr.es_default,
    } for pr in p.presentaciones.filter(activo=True).order_by('-es_default', 'factor')]
    if not pres:
        pres = [{'id': None, 'nombre': 'Unidad', 'factor': '1',
                 'precio': str(p.precio_venta), 'es_default': True}]
    stock = stock_override if stock_override is not None else p.stock
    return {
        'id': p.id,
        'codigo': p.codigo,
        'nombre': p.nombre,
        'precio': str(p.precio_para()),
        'stock': str(stock),
        'stock_display': ('%g' % float(stock)),
        'unidad': p.unidad_medida,
        'permite_decimal': p.permite_decimal,
        'imagen': p.imagen_url,
        'categoria': p.categoria.nombre if p.categoria else '',
        'categoria_id': p.categoria_id,
        'es_nuevo': p.es_nuevo,
        'presentaciones': pres,
    }


def _subarbol_categoria_ids(categoria_id):
    """Id de la categoría + todos sus descendientes (para filtrar familia)."""
    try:
        cid = int(categoria_id)
    except (TypeError, ValueError):
        return set()
    ids = {cid}
    pendientes = [cid]
    while pendientes:
        actual = pendientes.pop()
        hijas = list(Categoria.objects.filter(padre_id=actual).values_list('id', flat=True))
        for h in hijas:
            if h not in ids:
                ids.add(h)
                pendientes.append(h)
    return ids


def _arbol_pos(categorias):
    """Padres con hijas (recursivo) para el menú en cascada del POS.

    Incluye a los padres aunque no tengan productos directos, para
    poder llegar a las hijas. Cada nodo: id, nombre, icono, hijas y
    `familia` (ids del subárbol separados por coma, para filtrar).
    """
    por_id = {}
    for c in categorias:
        por_id[c.id] = c
    # Ancestros necesarios aunque no tengan productos directos.
    faltantes = set()
    for c in list(por_id.values()):
        a = c.padre
        while a is not None and a.id not in por_id:
            faltantes.add(a.id)
            a = a.padre
    if faltantes:
        for c in Categoria.objects.filter(pk__in=faltantes).select_related('padre'):
            por_id[c.id] = c
    # Hijas en una sola query (sin N+1).
    hijas_map = {}
    for h in Categoria.objects.filter(padre_id__in=list(por_id)).order_by('nombre'):
        if h.id in por_id:
            hijas_map.setdefault(h.padre_id, []).append(h)

    def _nodo(cat):
        nodos_hijas = [_nodo(h) for h in hijas_map.get(cat.id, [])]
        fam = [cat.id]
        for nh in nodos_hijas:
            fam.extend(nh['_ids'])
        return {
            'id': cat.id, 'nombre': cat.nombre,
            'icono': (cat.icono or '').strip(),
            'hijas': nodos_hijas,
            'familia': ','.join(str(i) for i in fam),
            '_ids': fam,
        }

    raices = sorted(
        [c for c in por_id.values() if c.padre_id not in por_id],
        key=lambda c: c.nombre.lower())
    arbol = [_nodo(c) for c in raices]
    for n in arbol:
        del n['_ids']
        _limpiar_ids(n)
    return arbol


def _limpiar_ids(nodo):
    for h in nodo['hijas']:
        del h['_ids']
        _limpiar_ids(h)


@login_required
@require_POST
def pos_buscar_productos(request):
    query = request.POST.get('q', '').strip()
    categoria_id = request.POST.get('categoria', '')

    es_multi = (modo_actual() == 'multi_pos')
    stock_map = {}
    if es_multi:
        # Spec §5: disponibilidad = AlmacenStock del almacén del turno.
        _, pos_obj, almacen = _turno_pos_almacen(request)
        if pos_obj is None or almacen is None:
            return JsonResponse({'error': 'Sin punto de venta asignado en el turno: abra el turno seleccionando el punto de venta para vender.'}, status=400)
        stock_map = _stock_map_para(almacen)
        ids_multi = [pid for pid, cant in stock_map.items() if cant > 0]
        productos = Producto.objects.filter(
            activo=True, id__in=ids_multi).select_related(
            'categoria').prefetch_related('presentaciones')
    else:
        productos = Producto.objects.filter(activo=True, visible_pos=True, stock__gt=0).select_related(
            'categoria').prefetch_related('presentaciones')
    if categoria_id:
        # La familia incluye a la categoría elegida y sus descendientes.
        productos = productos.filter(categoria_id__in=_subarbol_categoria_ids(categoria_id))
    if query:
        q_norm = _norm_sin_tildes(query)
        # El código no lleva tildes: filtro directo en BD.
        ids_codigo = list(productos.filter(codigo__icontains=query).values_list('id', flat=True))
        # El nombre se compara en Python insensible a tildes:
        # 'cafe' encuentra 'Café', 'jamon' encuentra 'Jamón', etc.
        ids_nombre = []
        if q_norm:
            for pid, pnombre in productos.values_list('id', 'nombre'):
                if q_norm in _norm_sin_tildes(pnombre):
                    ids_nombre.append(pid)
        productos = productos.filter(Q(id__in=set(ids_codigo) | set(ids_nombre)))

    if es_multi:
        data = [_serializar_producto_pos(
            p, stock_override=stock_map.get(p.id, Decimal('0'))
        ) for p in productos.order_by('nombre')[:50]]
    else:
        data = [_serializar_producto_pos(p) for p in productos.order_by('nombre')[:50]]

    return JsonResponse({'productos': data})


def _resolver_presentacion(producto, presentacion_id):
    """Devuelve (presentacion|None, factor, precio manual)."""
    from .models import PresentacionProducto
    if presentacion_id:
        try:
            pr = PresentacionProducto.objects.get(
                pk=presentacion_id, producto=producto, activo=True)
            return pr, pr.factor, pr.precio
        except PresentacionProducto.DoesNotExist:
            pass
    d = producto.presentacion_default()
    if d:
        return d, d.factor, d.precio
    return None, Decimal('1'), producto.precio_venta


@login_required
@require_POST
def pos_procesar_venta(request):
    try:
        from decimal import ROUND_HALF_UP
        data = json.loads(request.body)
        items = data.get('items', [])
        metodo_pago = data.get('metodo_pago', 'efectivo')
        # POS en pesos enteros (sin centavos): 220.2 -> 220.
        # El admin sigue aceptando decimales; aquí se redondea la venta.
        monto_efectivo = Decimal(str(data.get('monto_recibido', 0))).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        monto_transferencia = Decimal(str(data.get('monto_transferencia', 0))).quantize(Decimal('1'), rounding=ROUND_HALF_UP)

        if not items:
            return JsonResponse({'error': 'No hay productos en la venta.'}, status=400)

        es_multi = (modo_actual() == 'multi_pos')
        turno = None
        pos_obj = None
        almacen = None
        if es_multi:
            # Spec §5: el POS descuenta del almacén asignado al turno.
            # Sin POS asignado se bloquea con mensaje (nada se descuenta).
            turno, pos_obj, almacen = _turno_pos_almacen(request)
            if pos_obj is None or almacen is None:
                return JsonResponse({'error': 'Sin punto de venta asignado en el turno: abra el turno seleccionando el punto de venta para vender.'}, status=400)
            stock_map = _stock_map_para(almacen)

        subtotal = Decimal('0')
        detalles_data = []

        for item in items:
            producto = get_object_or_404(Producto, pk=item['id'])
            if es_multi:
                if not producto.activo:
                    return JsonResponse({'error': f'{producto.nombre} no está disponible en el punto de venta.'}, status=400)
            elif not producto.activo or not producto.visible_pos:
                return JsonResponse({'error': f'{producto.nombre} no está disponible en el punto de venta.'}, status=400)
            try:
                cantidad = Decimal(str(item['cantidad']))
            except Exception:
                return JsonResponse({'error': f'Cantidad invalida para {producto.nombre}.'}, status=400)
            if cantidad <= 0:
                return JsonResponse({'error': f'Cantidad invalida para {producto.nombre}.'}, status=400)
            # Solo 3 decimales
            cantidad = cantidad.quantize(Decimal('0.001'))
            # Enteros obligatorios salvo permite_decimal (cerdo, medio cartón...)
            if not producto.permite_decimal and cantidad != cantidad.to_integral_value():
                return JsonResponse({'error': f'{producto.nombre} solo admite unidades enteras.'}, status=400)
            presentacion, factor, precio = _resolver_presentacion(
                producto, item.get('presentacion_id'))
            cantidad_base = (cantidad * factor).quantize(Decimal('0.001'))
            if cantidad_base <= 0:
                return JsonResponse({'error': f'Cantidad invalida para {producto.nombre}.'}, status=400)
            if es_multi:
                disponible = stock_map.get(producto.id, Decimal('0'))
                if cantidad_base > disponible:
                    return JsonResponse({'error': f'Stock insuficiente para {producto.nombre}. Disponible: {"%g" % float(disponible)} {producto.unidad_medida} (Almacén {almacen.nombre})'}, status=400)
            elif cantidad_base > producto.stock:
                return JsonResponse({'error': f'Stock insuficiente para {producto.nombre}. Disponible: {"%g" % float(producto.stock)} {producto.unidad_medida}'}, status=400)
            # Precio y subtotal en enteros (ej. 220.2 -> 220). Cantidad sí puede ser decimal (lb, fracciones).
            precio_entero = precio.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            item_subtotal = (precio_entero * cantidad).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
            subtotal += item_subtotal
            detalles_data.append({
                'producto': producto,
                'presentacion': presentacion,
                'cantidad': cantidad,
                'cantidad_base': cantidad_base,
                'precio_unitario': precio_entero,
                'subtotal': item_subtotal,
                'costo_unitario_base': producto.precio_compra or Decimal('0'),
            })

        total = subtotal.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        total_pagado = monto_efectivo + monto_transferencia

        if total_pagado < total:
            return JsonResponse({'error': 'El monto pagado es insuficiente.'}, status=400)

        cambio = total_pagado - total

        if not es_multi:
            # Obtener turno activo del empleado
            turno = None
            try:
                empleado = request.user.empleado
                turno = empleado.turno_abierto
            except Empleado.DoesNotExist:
                pass

        with transaction.atomic():
            numero_venta = Venta.generar_numero()
            venta = Venta.objects.create(
                numero_venta=numero_venta,
                cajero=request.user,
                turno=turno,
                punto_venta=(pos_obj if es_multi else (turno.punto_venta if turno is not None and turno.punto_venta_id else None)),
                subtotal=subtotal,
                impuesto=Decimal('0'),
                total=total,
                metodo_pago=metodo_pago,
                monto_recibido=monto_efectivo,
                monto_transferencia=monto_transferencia,
                cambio=cambio,
            )

            for d in detalles_data:
                DetalleVenta.objects.create(
                    venta=venta,
                    producto=d['producto'],
                    presentacion=d['presentacion'],
                    cantidad=d['cantidad'],
                    cantidad_base=d['cantidad_base'],
                    precio_unitario=d['precio_unitario'],
                    subtotal=d['subtotal'],
                    costo_unitario_base=d.get('costo_unitario_base', 0),
                )
                if es_multi:
                    # Descuento directo del almacén del POS (Producto.stock
                    # NO se toca) + auditoría propia del almacén. El IPB del
                    # día lo refleja vía _sincronizar_inventario_dia
                    # (columna de ventas sobre los detalles).
                    stock = _stock_de(d['producto'], almacen)
                    anterior = stock.cantidad if stock is not None else Decimal('0')
                    if stock is None:
                        stock, _ = _get_or_create_stock(d['producto'], almacen)
                        anterior = stock.cantidad
                    if d['cantidad_base'] > anterior:
                        # Revalidación bajo lock (otra caja pudo vender
                        # entre la validación y el descuento).
                        raise ValueError(
                            f'Stock insuficiente para {d["producto"].nombre}. '
                            f'Disponible: {"%g" % float(anterior)} '
                            f'{d["producto"].unidad_medida} (Almacén {almacen.nombre})')
                    stock_nuevo = anterior - d['cantidad_base']
                    stock.cantidad = stock_nuevo
                    stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
                    _movimiento_almacen(
                        d['producto'], 'venta', d['cantidad_base'],
                        anterior, stock_nuevo, request.user, venta.id,
                        f'Venta #{venta.numero_venta} en {pos_obj.nombre}',
                        almacen=almacen)
                else:
                    _registrar_movimiento(d['producto'], 'venta', d['cantidad_base'], request.user, venta.id, f'Venta #{venta.numero_venta}')

        _sincronizar_inventario_dia(ahora_servidor().date())

        return JsonResponse({
            'success': True,
            'venta_id': venta.id,
            'numero_venta': venta.numero_venta,
            'total': str(venta.total),
            'cambio': str(venta.cambio),
        })
    except ValueError as e:
        return JsonResponse({'error': str(e)}, status=400)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def pos_ping(request):
    """Ping liviano para el monitor offline del POS. No requiere turno."""
    return JsonResponse({'ok': True})


@login_required
def pos_catalogo(request):
    """Catálogo completo para cache offline del POS (productos + categorías).

    En multi-POS el catálogo es por POS (existencias del almacén del
    turno); el payload no cambia, así la caché local
    (`bizm_products_cache_v1`) y la cola offline siguen compatibles.
    """
    if modo_actual() == 'multi_pos':
        _, pos_obj, almacen = _turno_pos_almacen(request)
        if pos_obj is None or almacen is None:
            return JsonResponse({'error': 'Sin punto de venta asignado en el turno: abra el turno seleccionando el punto de venta para vender.'}, status=400)
        stock_map = _stock_map_para(almacen)
        ids_multi = [pid for pid, cant in stock_map.items() if cant > 0]
        productos = Producto.objects.filter(
            activo=True, id__in=ids_multi).select_related(
            'categoria').prefetch_related('presentaciones').order_by('nombre')[:2000]
        data = [_serializar_producto_pos(
            p, stock_override=stock_map.get(p.id, Decimal('0')))
            for p in productos]
        categorias = list(Categoria.objects.filter(
            productos__id__in=ids_multi).distinct().values('id', 'nombre'))
        return JsonResponse({'productos': data, 'categorias': categorias})
    productos = Producto.objects.filter(activo=True, visible_pos=True, stock__gt=0).select_related(
        'categoria').prefetch_related('presentaciones').order_by('nombre')[:2000]
    data = [_serializar_producto_pos(p) for p in productos]
    categorias = list(Categoria.objects.filter(
        productos__activo=True, productos__visible_pos=True,
        productos__stock__gt=0).distinct().values('id', 'nombre'))
    return JsonResponse({'productos': data, 'categorias': categorias})


@login_required
def pos_ticket(request, pk):
    venta = get_object_or_404(Venta, pk=pk)
    if venta.cajero != request.user and not request.user.perfil.es_admin:
        return redirect('core:pos')
    detalles = venta.detalles.select_related('producto', 'presentacion').all()
    return render(request, 'core/pos_ticket.html', {'venta': venta, 'detalles': detalles})


@login_required
def pos_mis_ventas(request):
    hoy = ahora_servidor().date()
    ventas = Venta.objects.filter(
        cajero=request.user,
        fecha_venta__date=hoy,
        cancelada=False
    ).order_by('-fecha_venta')

    resumen = ventas.aggregate(total=Sum('total'), cantidad=Count('id'))

    data = []
    for v in ventas:
        detalles = v.detalles.select_related('producto').all()
        data.append({
            'id': v.id,
            'numero': v.numero_venta,
            'total': str(v.total),
            'metodo': v.get_metodo_pago_display(),
            'monto_recibido': str(v.monto_recibido),
            'monto_transferencia': str(v.monto_transferencia),
            'cambio': str(v.cambio),
            'hora': v.fecha_venta.strftime('%H:%M'),
            'items': [{
                'nombre': d.producto.nombre,
                'presentacion': d.presentacion.nombre if d.presentacion_id and d.presentacion else '',
                'cantidad': str(d.cantidad),
                'cantidad_base': str(d.cantidad_base or d.cantidad),
                'precio': str(d.precio_unitario),
                'subtotal': str(d.subtotal),
            } for d in detalles],
        })

    return JsonResponse({
        'ventas': data,
        'resumen': {
            'total': str(resumen['total'] or 0),
            'cantidad': resumen['cantidad'] or 0,
        }
    })


# ============================================================
# IPB - INVENTARIO PARCIAL DEL DIA
# ============================================================

def _fmt_cantidad_ipb(valor, unidad_medida):
    """Formato de cantidades para el IPB (usa el helper compartido de models)."""
    return fmt_cantidad_unidad(valor, unidad_medida)


def _obtener_datos_ipb(fecha, punto_venta=None):
    """Prepara los datos del IPB para una fecha dada. Retorna un diccionio con el contexto.

    Con `punto_venta` (modo multi-POS, filtro `?pos=`): IPB de ese POS
    calculado sobre el stock del almacén asignado (ver
    `_obtener_datos_ipb_por_pos`); sin él, el IPB global actual.
    """
    if punto_venta is not None:
        return _obtener_datos_ipb_por_pos(fecha, punto_venta)
    from datetime import timedelta
    from django.db.models import Sum
    
    hoy = ahora_servidor().date()
    
    _sincronizar_inventario_dia(fecha)
    
    inventarios = InventarioDiario.objects.filter(
        fecha=fecha,
        producto__activo=True,
        producto__visible_pos=True
    ).select_related('producto__categoria').order_by('producto__nombre')
    
    entradas_dia = EntradaProducto.objects.filter(
        fecha_entrada__date=fecha
    ).values('producto_id').annotate(
        total_costo=Sum('costo_total'),
        total_cantidad=Sum('cantidad')
    )
    entrada_costo_map = {e['producto_id']: {'costo': Decimal(str(e['total_costo'] or 0)), 'cantidad': Decimal(str(e['total_cantidad'] or 0))} for e in entradas_dia}

    # Ingreso REAL por producto: suma de los subtotales cobrados (cada
    # presentación tiene su precio: cartón ≠ unidad). Sin esto, 130 huevos
    # a $170 + 2 cartones a $4500 se calcularían como 190 x $170.
    ventas_det = DetalleVenta.objects.filter(
        venta__fecha_venta__date=fecha, venta__cancelada=False
    ).values('producto_id').annotate(ingreso_real=Sum('subtotal'))
    ingreso_map = {v['producto_id']: Decimal(str(v['ingreso_real'] or 0)) for v in ventas_det}
    # Precio histórico del día: PU dominante cobrado ese día por producto.
    # Sin esto, un cambio 520→540 reescribe el IPB viejo con el precio actual.
    pu_qs = DetalleVenta.objects.filter(
        venta__fecha_venta__date=fecha, venta__cancelada=False
    ).values('producto_id', 'precio_unitario').annotate(cant=Sum('cantidad'))
    _pu_best = {}
    for r in pu_qs:
        pid = r['producto_id']
        try:
            c = Decimal(str(r['cant'] or 0))
            pu = Decimal(str(r['precio_unitario'] or 0))
        except Exception:
            continue
        if pid not in _pu_best or c > _pu_best[pid][1]:
            _pu_best[pid] = (pu, c)
    precio_hist_map = {pid: pu for pid, (pu, _c) in _pu_best.items()}
    # Desglose por presentación para mostrar el mix (ej. "2 x Cartón 30").
    # Solo presentaciones distintas a la unidad base (factor != 1): las ventas
    # en unidades no ensucian el IPB.
    mix_qs = DetalleVenta.objects.filter(
        venta__fecha_venta__date=fecha, venta__cancelada=False
    ).values('producto_id', 'presentacion__nombre', 'presentacion__factor').annotate(
        cant=Sum('cantidad'), sub=Sum('subtotal'))
    mix_map = {}
    for m in mix_qs:
        if not m['presentacion__nombre']:
            continue
        try:
            if Decimal(str(m['presentacion__factor'] or 1)) == 1:
                continue
        except Exception:
            pass
        try:
            c = Decimal(str(m['cant'] or 0))
            cs = format(c.quantize(Decimal('0.001')).normalize(), 'f')
        except Exception:
            cs = str(m['cant'] or 0)
        nombre = m['presentacion__nombre']
        mix_map.setdefault(m['producto_id'], []).append(f"{cs} x {nombre}")

    # Salidas sin venta del día: donaciones y deudas de producto (para marcar el IPB).
    # Deudas: sumar cantidad_base (presentación convertida); fallback a cantidad
    # para registros viejos con cantidad_base en 0.
    from django.db.models import Sum as _Sum
    donaciones_dia = RetiroDonacion.objects.filter(
        fecha_retiro__date=fecha
    ).values('producto_id').annotate(total=_Sum('cantidad'))
    donado_map = {d['producto_id']: Decimal(str(d['total'] or 0)) for d in donaciones_dia}
    try:
        deudas_dia = Deuda.objects.filter(
            fecha_registro__date=fecha, tipo='producto'
        ).values('producto_id').annotate(total=_Sum('cantidad_base'))
        deuda_map = {d['producto_id']: Decimal(str(d['total'] or 0)) for d in deudas_dia}
        # Fallback: registros anteriores a la migración de presentaciones
        # (cantidad_base = 0) se miden con cantidad.
        if any(v == 0 for v in deuda_map.values()):
            deudas_old = Deuda.objects.filter(
                fecha_registro__date=fecha, tipo='producto', cantidad_base=0
            ).values('producto_id').annotate(total=_Sum('cantidad'))
            for d in deudas_old:
                if deuda_map.get(d['producto_id'], 0) == 0:
                    deuda_map[d['producto_id']] = Decimal(str(d['total'] or 0))
    except Exception:
        deudas_dia = Deuda.objects.filter(
            fecha_registro__date=fecha, tipo='producto'
        ).values('producto_id').annotate(total=_Sum('cantidad'))
        deuda_map = {d['producto_id']: Decimal(str(d['total'] or 0)) for d in deudas_dia}
    
    total_inicial = 0
    total_entradas = 0
    total_ventas = 0
    total_final = 0
    productos_movimiento = 0
    productos_sin_stock = 0
    total_donado = Decimal('0')
    total_en_deuda = Decimal('0')
    productos_donados = 0
    productos_en_deuda = 0
    
    reporte = []
    for inv in inventarios:
        total_inicial += inv.stock_inicial
        total_entradas += inv.entradas
        total_ventas += inv.ventas
        total_final += inv.stock_final
        
        if inv.ventas > 0 or inv.entradas > 0:
            productos_movimiento += 1
        if inv.stock_final == 0 and inv.ventas > 0:
            productos_sin_stock += 1
        
        precio_venta = precio_hist_map.get(
            inv.producto.id, Decimal(str(inv.producto.precio_venta)))
        
        entrada_info = entrada_costo_map.get(inv.producto.id)
        if entrada_info and entrada_info['cantidad'] > 0:
            costo_promedio_entrada = entrada_info['costo'] / entrada_info['cantidad']
        else:
            costo_promedio_entrada = inv.producto.precio_compra
        
        costo_venta = inv.ventas * costo_promedio_entrada
        # Ingreso real cobrado (respeta precios por presentación); fallback al
        # precio base solo si no hay detalle (no debería pasar con ventas > 0).
        ingreso = ingreso_map.get(inv.producto.id, inv.ventas * precio_venta)
        ganancia = ingreso - costo_venta

        donado = donado_map.get(inv.producto.id, Decimal('0'))
        en_deuda = deuda_map.get(inv.producto.id, Decimal('0'))
        if donado > 0:
            total_donado += donado
            productos_donados += 1
        if en_deuda > 0:
            total_en_deuda += en_deuda
            productos_en_deuda += 1

        reporte.append({
            'inventario': inv,
            'producto': inv.producto,
            'categoria': inv.producto.categoria,
            'stock_inicial': inv.stock_inicial,
            'entradas': inv.entradas,
            'ventas': inv.ventas,
            'stock_final': inv.stock_final,
            'stock_inicial_fmt': _fmt_cantidad_ipb(inv.stock_inicial, inv.producto.unidad_medida),
            'entradas_fmt': _fmt_cantidad_ipb(inv.entradas, inv.producto.unidad_medida),
            'ventas_fmt': _fmt_cantidad_ipb(inv.ventas, inv.producto.unidad_medida),
            'stock_final_fmt': _fmt_cantidad_ipb(inv.stock_final, inv.producto.unidad_medida),
            'precio_venta': precio_venta,
            'precio_compra': costo_promedio_entrada,
            'costo_venta': costo_venta,
            'ingreso': ingreso,
            'ganancia': ganancia,
            'mix_txt': ' + '.join(mix_map.get(inv.producto.id, [])),
            'agotado': inv.stock_final == 0 and inv.ventas > 0,
            'donado': donado,
            'donado_fmt': _fmt_cantidad_ipb(donado, inv.producto.unidad_medida),
            'tiene_donacion': donado > 0,
            'en_deuda': en_deuda,
            'en_deuda_fmt': _fmt_cantidad_ipb(en_deuda, inv.producto.unidad_medida),
            'tiene_deuda': en_deuda > 0,
        })
    
    resumen_dinero = Venta.objects.filter(
        fecha_venta__date=fecha,
        cancelada=False
    ).aggregate(
        efectivo=Sum('monto_recibido'),
        transferencia=Sum('monto_transferencia'),
        cambio=Sum('cambio'),
        total_ventas=Sum('total'),
    )
    efectivo_recibido = resumen_dinero['efectivo'] or 0
    transferencia_recibida = resumen_dinero['transferencia'] or 0
    cambio_devuelto = resumen_dinero['cambio'] or 0
    total_ventas_monto = resumen_dinero['total_ventas'] or 0
    
    gastos_dia = Gasto.objects.filter(fecha_gasto__date=fecha)
    resumen_gastos = gastos_dia.aggregate(
        total=Sum(F('cantidad_efectivo') + F('cantidad_transferencia')),
        efectivo=Sum('cantidad_efectivo'),
        transferencia=Sum('cantidad_transferencia'),
    )
    total_gastos = resumen_gastos['total'] or 0
    
    total_costo_unitario = sum(float(r['precio_compra'] * r['stock_inicial']) for r in reporte)
    total_ingreso = sum(float(r['ingreso']) for r in reporte)
    total_ganancia = sum(float(r['ganancia']) for r in reporte)
    
    return {
        'fecha': fecha,
        'hoy': hoy,
        'es_hoy': fecha == hoy,
        'reporte': reporte,
        'resumen': {
            'total_productos': len(reporte),
            'total_stock_inicial': total_inicial,
            'total_entradas': total_entradas,
            'total_ventas': total_ventas,
            'total_stock_final': total_final,
            'productos_movimiento': productos_movimiento,
            'productos_sin_stock': productos_sin_stock,
            'total_ingreso': total_ingreso,
            'total_gastos': total_gastos,
            'total_recaudado': total_ventas_monto - total_gastos,
            'total_ganancia': total_ganancia,
            'total_donado': total_donado,
            'total_en_deuda': total_en_deuda,
            'productos_donados': productos_donados,
            'productos_en_deuda': productos_en_deuda,
        },
        'ahora': timezone.now(),
        'es_por_pos': False,
        'punto_venta': None,
        'almacen': None,
    }

def _obtener_datos_ipb_por_pos(fecha, pos):
    """IPB de un POS en modo multi-POS (spec §5), sobre el almacén del POS.

    Review-focus del plan: se calcula sobre el stock del almacén asignado
    (`AlmacenStock`), NO sobre `Producto.stock`:
    - ventas/ingresos/mix: `DetalleVenta` del día con `venta.punto_venta=pos`.
    - stock_final: existencia actual en el almacén del POS; inicial =
      final + ventas (en multi-POS no hay entradas directas al POS ni
      traslados →POS: el mostrador solo sale por venta).
    - entradas del POS: 0 por lo mismo (las `AlmacenEntrada` van al almacén,
      no al mostrador).
    - donaciones/deudas: salidas del mostrador sin atribución por POS; se
      muestran globales como en el IPB general (informativo, no restan del
      inicial derivado).
    - dinero: ventas del POS; gastos: `Gasto` del día con
      `turno.punto_venta=pos` (gastos de admin sin turno no se atribuyen).
    No toca `InventarioDiario` (historia global intacta) ni borra nada.
    """
    from django.db.models import Sum as _Sum

    hoy = ahora_servidor().date()
    almacen = pos.almacen if pos is not None else None

    def _dec(v):
        return Decimal(str(v or 0))

    ventas_qs = DetalleVenta.objects.filter(
        venta__fecha_venta__date=fecha, venta__cancelada=False,
        venta__punto_venta=pos)
    ventas_map = {
        v['producto_id']: _dec(v['t'])
        for v in ventas_qs.values('producto_id').annotate(t=_Sum('cantidad_base'))
    }
    ingreso_map = {
        v['producto_id']: _dec(v['ingreso_real'])
        for v in ventas_qs.values('producto_id').annotate(
            ingreso_real=_Sum('subtotal'))
    }
    # Precio histórico del día por POS (igual que el IPB global):
    # PU dominante cobrado ese día en ese POS.
    _pu_best = {}
    for r in ventas_qs.values(
            'producto_id', 'precio_unitario').annotate(cant=_Sum('cantidad')):
        pid = r['producto_id']
        try:
            c = _dec(r['cant'])
            pu = _dec(r['precio_unitario'])
        except Exception:
            continue
        if pid not in _pu_best or c > _pu_best[pid][1]:
            _pu_best[pid] = (pu, c)
    precio_hist_map = {pid: pu for pid, (pu, _c) in _pu_best.items()}
    mix_map = {}
    for m in ventas_qs.values(
            'producto_id', 'presentacion__nombre',
            'presentacion__factor').annotate(cant=_Sum('cantidad'),
                                             sub=_Sum('subtotal')):
        if not m['presentacion__nombre']:
            continue
        try:
            if Decimal(str(m['presentacion__factor'] or 1)) == 1:
                continue
        except Exception:
            pass
        try:
            c = _dec(m['cant'])
            cs = format(c.quantize(Decimal('0.001')).normalize(), 'f')
        except Exception:
            cs = str(m['cant'] or 0)
        mix_map.setdefault(m['producto_id'], []).append(
            f"{cs} x {m['presentacion__nombre']}")

    # Donaciones/deudas globales del día (sin atribución por POS).
    donado_map = {
        d['producto_id']: _dec(d['total'])
        for d in RetiroDonacion.objects.filter(
            fecha_retiro__date=fecha
        ).values('producto_id').annotate(total=_Sum('cantidad'))
    }
    try:
        deuda_map = {
            d['producto_id']: _dec(d['total'])
            for d in Deuda.objects.filter(
                fecha_registro__date=fecha, tipo='producto'
            ).values('producto_id').annotate(total=_Sum('cantidad_base'))
        }
        if any(v == 0 for v in deuda_map.values()):
            for d in Deuda.objects.filter(
                    fecha_registro__date=fecha, tipo='producto',
                    cantidad_base=0).values('producto_id').annotate(
                        total=_Sum('cantidad')):
                if deuda_map.get(d['producto_id'], 0) == 0:
                    deuda_map[d['producto_id']] = _dec(d['total'])
    except Exception:
        deuda_map = {
            d['producto_id']: _dec(d['total'])
            for d in Deuda.objects.filter(
                fecha_registro__date=fecha, tipo='producto'
            ).values('producto_id').annotate(total=_Sum('cantidad'))
        }

    stock_map = _stock_map_para(almacen) if almacen is not None else {}
    ids = {pid for pid, cant in stock_map.items() if _dec(cant) != 0}
    ids |= set(ventas_map)
    productos = (Producto.objects.filter(
        activo=True, id__in=ids
    ).select_related('categoria').order_by('nombre') if ids else [])

    total_inicial = Decimal('0')
    total_entradas = Decimal('0')
    total_ventas = Decimal('0')
    total_final = Decimal('0')
    productos_movimiento = 0
    productos_sin_stock = 0
    total_donado = Decimal('0')
    total_en_deuda = Decimal('0')
    productos_donados = 0
    productos_en_deuda = 0

    reporte = []
    for producto in productos:
        ventas = ventas_map.get(producto.id, Decimal('0'))
        stock_final = _dec(stock_map.get(producto.id, 0))
        stock_inicial = stock_final + ventas
        entradas = Decimal('0')
        total_inicial += stock_inicial
        total_entradas += entradas
        total_ventas += ventas
        total_final += stock_final

        if ventas > 0 or entradas > 0:
            productos_movimiento += 1
        if stock_final == 0 and ventas > 0:
            productos_sin_stock += 1

        precio_venta = precio_hist_map.get(producto.id, Decimal(str(producto.precio_venta)))
        costo_unit = producto.precio_compra
        costo_venta = ventas * costo_unit
        ingreso = ingreso_map.get(producto.id, ventas * precio_venta)
        ganancia = ingreso - costo_venta

        donado = donado_map.get(producto.id, Decimal('0'))
        en_deuda = deuda_map.get(producto.id, Decimal('0'))
        if donado > 0:
            total_donado += donado
            productos_donados += 1
        if en_deuda > 0:
            total_en_deuda += en_deuda
            productos_en_deuda += 1

        reporte.append({
            'inventario': None,
            'producto': producto,
            'categoria': producto.categoria,
            'stock_inicial': stock_inicial,
            'entradas': entradas,
            'ventas': ventas,
            'stock_final': stock_final,
            'stock_inicial_fmt': _fmt_cantidad_ipb(
                stock_inicial, producto.unidad_medida),
            'entradas_fmt': _fmt_cantidad_ipb(
                entradas, producto.unidad_medida),
            'ventas_fmt': _fmt_cantidad_ipb(
                ventas, producto.unidad_medida),
            'stock_final_fmt': _fmt_cantidad_ipb(
                stock_final, producto.unidad_medida),
            'precio_venta': precio_venta,
            'precio_compra': costo_unit,
            'costo_venta': costo_venta,
            'ingreso': ingreso,
            'ganancia': ganancia,
            'mix_txt': ' + '.join(mix_map.get(producto.id, [])),
            'agotado': stock_final == 0 and ventas > 0,
            'donado': donado,
            'donado_fmt': _fmt_cantidad_ipb(
                donado, producto.unidad_medida),
            'tiene_donacion': donado > 0,
            'en_deuda': en_deuda,
            'en_deuda_fmt': _fmt_cantidad_ipb(
                en_deuda, producto.unidad_medida),
            'tiene_deuda': en_deuda > 0,
        })

    resumen_dinero = Venta.objects.filter(
        fecha_venta__date=fecha, cancelada=False,
        punto_venta=pos).aggregate(
        efectivo=_Sum('monto_recibido'),
        transferencia=_Sum('monto_transferencia'),
        cambio=_Sum('cambio'),
        total_ventas=_Sum('total'),
    )
    gastos_dia = Gasto.objects.filter(
        fecha_gasto__date=fecha, turno__punto_venta=pos)
    resumen_gastos = gastos_dia.aggregate(
        total=_Sum(F('cantidad_efectivo') + F('cantidad_transferencia')),
        efectivo=_Sum('cantidad_efectivo'),
        transferencia=_Sum('cantidad_transferencia'),
    )
    total_gastos = resumen_gastos['total'] or 0
    total_ventas_monto = resumen_dinero['total_ventas'] or 0

    total_costo_unitario = sum(
        float(r['precio_compra'] * r['stock_inicial']) for r in reporte)
    total_ingreso = sum(float(r['ingreso']) for r in reporte)
    total_ganancia = sum(float(r['ganancia']) for r in reporte)

    return {
        'fecha': fecha,
        'hoy': hoy,
        'es_hoy': fecha == hoy,
        'reporte': reporte,
        'resumen': {
            'total_productos': len(reporte),
            'total_stock_inicial': total_inicial,
            'total_entradas': total_entradas,
            'total_ventas': total_ventas,
            'total_stock_final': total_final,
            'productos_movimiento': productos_movimiento,
            'productos_sin_stock': productos_sin_stock,
            'total_ingreso': total_ingreso,
            'total_gastos': total_gastos,
            'total_recaudado': total_ventas_monto - total_gastos,
            'total_ganancia': total_ganancia,
            'total_donado': total_donado,
            'total_en_deuda': total_en_deuda,
            'productos_donados': productos_donados,
            'productos_en_deuda': productos_en_deuda,
        },
        'ahora': timezone.now(),
        'es_por_pos': True,
        'punto_venta': pos,
        'almacen': almacen,
    }

def _registrar_movimiento(producto, tipo, cantidad, usuario=None, referencia_id=None, descripcion=''):
    """Registra un movimiento de inventario."""
    stock_anterior = producto.stock
    if tipo in ['entrada', 'devolucion']:
        producto.stock += cantidad
        cantidad_signada = abs(cantidad)
    elif tipo in ['venta', 'donacion', 'deuda']:
        producto.stock -= cantidad
        cantidad_signada = -abs(cantidad)
    elif tipo == 'ajuste':
        producto.stock = cantidad
        cantidad_signada = cantidad
    producto.save()
    MovimientoInventario.objects.create(
        producto=producto,
        tipo=tipo,
        cantidad=cantidad_signada,
        stock_anterior=stock_anterior,
        stock_nuevo=producto.stock,
        referencia_id=referencia_id,
        descripcion=descripcion,
        usuario=usuario,
    )

def _sincronizar_inventario_dia(fecha):
    """Sincroniza el inventario del día con las ventas, entradas y donaciones reales.

    REGLA DE ORO: el historial no se reescribe con el stock vivo.
    - Día cerrado: no se toca.
    - Día pasado abierto: se congela stock_inicial, solo se actualizan
      entradas/ventas y se recalcula final = inicial + ent - ven - don - deuda.
    - Hoy: el inicial se congela desde el primer movimiento (o se hereda del
      último final anterior); el final se CALCULA, nunca se copia
      producto.stock. Solo si es el primer día sin anterior se bootstrapea
      desde el vivo: inicial = vivo - ent + ven + don + deuda.
    """
    from datetime import timedelta
    from django.db.models import Sum
    from decimal import Decimal

    hoy = ahora_servidor().date()

    # Bloqueo total del pasado previo al sistema: ni siquiera se calculan
    # movimientos, para no crear filas ficticias en la BD.
    if fecha < FECHA_INICIO_SISTEMA:
        return

    productos = Producto.objects.filter(activo=True, visible_pos=True)

    ventas_dia = DetalleVenta.objects.filter(
        venta__fecha_venta__date=fecha,
        venta__cancelada=False
    ).values('producto_id').annotate(cantidad_vendida=Sum('cantidad_base'))
    ventas_map = {v['producto_id']: v['cantidad_vendida'] or 0 for v in ventas_dia}
    
    entradas_dia = EntradaProducto.objects.filter(
        fecha_entrada__date=fecha
    ).values('producto_id').annotate(cantidad_entrada=Sum('cantidad'))
    entradas_map = {e['producto_id']: e['cantidad_entrada'] or 0 for e in entradas_dia}
    
    donaciones_dia = RetiroDonacion.objects.filter(
        fecha_retiro__date=fecha
    ).values('producto_id').annotate(cantidad_donada=Sum('cantidad'))
    donaciones_map = {d['producto_id']: d['cantidad_donada'] or 0 for d in donaciones_dia}

    # Productos entregados como deuda (salida sin ingreso, igual que donación).
    # Se mide en UNIDAD BASE (cantidad_base = cantidad x factor de presentación).
    try:
        deudas_dia = Deuda.objects.filter(
            fecha_registro__date=fecha,
            tipo='producto'
        ).values('producto_id').annotate(cantidad_deuda=Sum('cantidad_base'))
        deudas_map = {d['producto_id']: deudas_dia and (d['cantidad_deuda'] or 0) for d in deudas_dia}
        # Fallback para deudas viejas (cantidad_base = 0): usar cantidad.
        deudas_old = Deuda.objects.filter(
            fecha_registro__date=fecha, tipo='producto', cantidad_base=0
        ).values('producto_id').annotate(cantidad_deuda=Sum('cantidad'))
        for d in deudas_old:
            if not deudas_map.get(d['producto_id']):
                deudas_map[d['producto_id']] = d['cantidad_deuda'] or 0
    except Exception:
        deudas_dia = Deuda.objects.filter(
            fecha_registro__date=fecha,
            tipo='producto'
        ).values('producto_id').annotate(cantidad_deuda=Sum('cantidad'))
        deudas_map = {d['producto_id']: d['cantidad_deuda'] or 0 for d in deudas_dia}
    
    for producto in productos:
        inventario = InventarioDiario.objects.filter(
            fecha=fecha,
            producto=producto
        ).first()

        if inventario and inventario.cerrado:
            continue

        # Buscar el ÚLTIMO inventario anterior (no solo el día anterior)
        # para garantizar continuidad de stock_final → stock_inicial
        inv_anterior = InventarioDiario.objects.filter(
            fecha__lt=fecha,
            producto=producto
        ).order_by('-fecha').first()

        entradas = entradas_map.get(producto.id, 0)
        ventas = ventas_map.get(producto.id, 0)
        donaciones = donaciones_map.get(producto.id, 0)
        salidas_deuda = deudas_map.get(producto.id, 0)

        def _dec(v):
            return Decimal(str(v or 0))

        if inventario is None:
            if inv_anterior is not None:
                stock_inicial = inv_anterior.stock_final
            else:
                # Primer día sin historia: único caso donde se deriva del vivo.
                stock_inicial = _dec(producto.stock) - _dec(entradas) + _dec(ventas) + _dec(donaciones) + _dec(salidas_deuda)
            stock_final = _dec(stock_inicial) + _dec(entradas) - _dec(ventas) - _dec(donaciones) - _dec(salidas_deuda)
            InventarioDiario.objects.create(
                fecha=fecha,
                producto=producto,
                stock_inicial=stock_inicial,
                entradas=entradas,
                ventas=ventas,
                stock_final=stock_final,
            )
            continue

        # Día pasado: inicial congelado, solo movimientos + recalcular final.
        if fecha < hoy:
            inventario.entradas = entradas
            inventario.ventas = ventas
            inventario.calcular(donaciones=donaciones, salidas_deuda=salidas_deuda)
            inventario.save()
            continue

        # Hoy: congelar inicial en el primer valor válido.
        if inventario.stock_inicial == 0 and inv_anterior is not None:
            inventario.stock_inicial = inv_anterior.stock_final
        elif inventario.stock_inicial == 0 and inv_anterior is None:
            inventario.stock_inicial = _dec(producto.stock) - _dec(entradas) + _dec(ventas) + _dec(donaciones) + _dec(salidas_deuda)
        inventario.entradas = entradas
        inventario.ventas = ventas
        inventario.calcular(donaciones=donaciones, salidas_deuda=salidas_deuda)
        inventario.save()


def _movs_dia_producto(producto, fecha):
    """Movimientos de UN producto en un día (autoridad: tablas reales)."""
    from django.db.models import Sum
    from decimal import Decimal

    def _dec(v):
        return Decimal(str(v or 0))

    ent = EntradaProducto.objects.filter(
        fecha_entrada__date=fecha, producto=producto
    ).aggregate(t=Sum('cantidad'))['t'] or 0
    ven = DetalleVenta.objects.filter(
        venta__fecha_venta__date=fecha, venta__cancelada=False,
        producto=producto
    ).aggregate(t=Sum('cantidad_base'))['t'] or 0
    don = RetiroDonacion.objects.filter(
        fecha_retiro__date=fecha, producto=producto
    ).aggregate(t=Sum('cantidad'))['t'] or 0
    try:
        deu = Deuda.objects.filter(
            fecha_registro__date=fecha, tipo='producto', producto=producto
        ).aggregate(t=Sum('cantidad_base'))['t'] or 0
        if not deu:
            deu = Deuda.objects.filter(
                fecha_registro__date=fecha, tipo='producto',
                producto=producto, cantidad_base=0
            ).aggregate(t=Sum('cantidad'))['t'] or 0
    except Exception:
        deu = 0
    return _dec(ent), _dec(ven), _dec(don), _dec(deu)


def _reencadenar_producto_desde(producto, fecha_desde):
    """Re-encadena el IPB de UN producto desde una fecha hasta hoy.

    Para ventas tardías (ej. ayer se olvidó pasar un producto): el día D
    mantiene su inicial congelado y recalcula el final; cada día posterior
    hereda ini = fin previo y recalcula. Así no vuelve la ruptura 22-24.
    Crea el puente si falta una fila intermedia. No toca días cerrados
    en inicial, solo los corrige en cascada. Devuelve días tocados.
    """
    from datetime import timedelta
    from decimal import Decimal

    hoy = ahora_servidor().date()
    if fecha_desde < FECHA_INICIO_SISTEMA:
        return 0
    if fecha_desde > hoy:
        fecha_desde = hoy

    def _dec(v):
        return Decimal(str(v or 0))

    previo = InventarioDiario.objects.filter(
        fecha__lt=fecha_desde, producto=producto
    ).order_by('-fecha').first()
    previo_fin = previo.stock_final if previo else None

    tocados = 0
    f = fecha_desde
    while f <= hoy:
        inv = InventarioDiario.objects.filter(fecha=f, producto=producto).first()
        ent, ven, don, deu = _movs_dia_producto(producto, f)
        if inv is None:
            ini = previo_fin if previo_fin is not None else (
                _dec(producto.stock) - ent + ven + don + deu)
            inv = InventarioDiario.objects.create(
                fecha=f, producto=producto, stock_inicial=ini,
                entradas=ent, ventas=ven,
                stock_final=ini + ent - ven - don - deu,
            )
        else:
            if f == fecha_desde:
                # Día del movimiento tardío: inicial congelado (mañana).
                if inv.stock_inicial == 0 and previo_fin is not None:
                    inv.stock_inicial = previo_fin
            else:
                # Cascada: heredar siempre ini = fin previo.
                if previo_fin is not None:
                    inv.stock_inicial = previo_fin
            inv.entradas = ent
            inv.ventas = ven
            inv.calcular(donaciones=don, salidas_deuda=deu)
            inv.save()
        previo_fin = inv.stock_final
        tocados += 1
        f += timedelta(days=1)
    return tocados


def _ajustar_pago_venta(venta):
    """Cuadra el pago con el total tras agregar/quitar productos.

    - Pagado >= total: solo recompone el cambio.
    - Faltante + efectivo/transferencia: completa esa pata al total.
    - Faltante + mixto: NO reparte (devuelve aviso para designar montos).
    Retorna (completado_auto: bool, aviso_mixto: bool).
    """
    pagado = (venta.monto_recibido or 0) + (venta.monto_transferencia or 0)
    if pagado >= venta.total:
        venta.cambio = pagado - venta.total
        venta.save()
        return True, False
    if venta.metodo_pago == 'efectivo':
        venta.monto_recibido = venta.total
        venta.monto_transferencia = 0
        venta.cambio = 0
        venta.save()
        return True, False
    if venta.metodo_pago == 'transferencia':
        venta.monto_recibido = 0
        venta.monto_transferencia = venta.total
        venta.cambio = 0
        venta.save()
        return True, False
    venta.cambio = 0
    venta.save()
    return False, True


@requiere_admin
def ipb(request):
    fecha_str = request.GET.get('fecha', '')
    hoy = ahora_servidor().date()
    
    if fecha_str:
        try:
            fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = hoy
    else:
        fecha = hoy
    
    # No permitir ver IPB de fechas futuras
    if fecha > hoy:
        messages.error(request, 'No se puede ver el IPB de una fecha futura.')
        fecha = hoy

    # No existe IPB antes del inicio del sistema (22/09/2026)
    if fecha < FECHA_INICIO_SISTEMA:
        messages.warning(request, 'El IPB existe desde el 22/09/2026 (inicio del sistema).')
        fecha = FECHA_INICIO_SISTEMA

    # Spec §5 multi-POS: filtro ?pos= con cálculo sobre el almacén de
    # cada POS (fuera de multi-POS se ignora).
    pos_actual, puntos_venta = _resolver_pos_filtro(request)
    context = _obtener_datos_ipb(fecha, punto_venta=pos_actual)
    context.update({
        'es_multi_pos': modo_actual() == 'multi_pos',
        'puntos_venta': puntos_venta,
        'pos_actual': pos_actual,
    })
    return render(request, 'core/ipb.html', context)


@login_required
@require_POST
def pos_registrar_gasto(request):
    try:
        data = json.loads(request.body)
        cantidad_efectivo = Decimal(str(data.get('cantidad_efectivo', 0)))
        cantidad_transferencia = Decimal(str(data.get('cantidad_transferencia', 0)))
        descripcion = data.get('descripcion', '').strip()
        categoria = data.get('categoria', 'caja')

        total = cantidad_efectivo + cantidad_transferencia
        if total <= 0:
            return JsonResponse({'error': 'La cantidad debe ser mayor a 0.'}, status=400)

        turno = None
        try:
            empleado = request.user.empleado
            turno = empleado.turno_abierto
        except Empleado.DoesNotExist:
            pass

        numero_gasto = Gasto.generar_numero()
        gasto = Gasto.objects.create(
            numero_gasto=numero_gasto,
            cajero=request.user,
            turno=turno,
            cantidad_efectivo=cantidad_efectivo,
            cantidad_transferencia=cantidad_transferencia,
            categoria=categoria,
            descripcion=descripcion,
        )

        return JsonResponse({
            'success': True,
            'gasto_id': gasto.id,
            'numero_gasto': gasto.numero_gasto,
            'cantidad_efectivo': str(gasto.cantidad_efectivo),
            'cantidad_transferencia': str(gasto.cantidad_transferencia),
            'cantidad_total': str(gasto.cantidad_total),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def pos_mis_gastos(request):
    hoy = ahora_servidor().date()
    gastos = Gasto.objects.filter(
        cajero=request.user,
        fecha_gasto__date=hoy,
    ).order_by('-fecha_gasto')

    resumen = gastos.aggregate(
        total=Sum(F('cantidad_efectivo') + F('cantidad_transferencia')),
        efectivo=Sum('cantidad_efectivo'),
        transferencia=Sum('cantidad_transferencia'),
        cantidad=Count('id')
    )

    data = []
    for g in gastos:
        data.append({
            'id': g.id,
            'numero': g.numero_gasto,
            'cantidad_efectivo': str(g.cantidad_efectivo),
            'cantidad_transferencia': str(g.cantidad_transferencia),
            'cantidad_total': str(g.cantidad_total),
            'categoria': g.get_categoria_display(),
            'descripcion': g.descripcion or '',
            'hora': g.fecha_gasto.strftime('%H:%M'),
        })

    return JsonResponse({
        'gastos': data,
        'resumen': {
            'total': str(resumen['total'] or 0),
            'efectivo': str(resumen['efectivo'] or 0),
            'transferencia': str(resumen['transferencia'] or 0),
            'cantidad': resumen['cantidad'] or 0,
        }
    })


@login_required
def pos_mis_entradas(request):
    """Entradas de mercancía del día/turno para consulta de la dependienta.

    Las entradas las registra el admin; aquí solo se consultan (sin costos:
    la cajera ve producto, cantidad, proveedor y hora, no el costo de compra).
    Si la empleada tiene turno abierto, se filtra desde la apertura del turno;
    si no, se muestra todo lo del día.
    """
    hoy = ahora_servidor().date()
    entradas = EntradaProducto.objects.filter(
        fecha_entrada__date=hoy).select_related('producto')
    desde_turno = False
    try:
        turno = request.user.empleado.turno_abierto
    except Exception:
        turno = None
    if turno is not None:
        entradas = entradas.filter(fecha_entrada__gte=turno.fecha_apertura)
        desde_turno = True
    entradas = entradas.order_by('-fecha_entrada')

    data = []
    for e in entradas:
        data.append({
            'id': e.id,
            'numero': e.numero_entrada,
            'producto': e.producto.nombre if e.producto_id else '',
            'codigo': e.producto.codigo if e.producto_id else '',
            'cantidad': str(e.cantidad),
            'cantidad_fmt': e.cantidad_fmt,
            'unidad': e.producto.unidad_medida if e.producto_id else '',
            'proveedor': e.proveedor or '',
            'descripcion': e.descripcion or '',
            'hora': e.fecha_entrada.strftime('%H:%M'),
        })

    return JsonResponse({
        'entradas': data,
        'resumen': {'cantidad': len(data)},
        'desde_turno': desde_turno,
    })


@requiere_admin
def venta_impresion(request, fecha=None):
    """Genera PDF de ventas del dia."""
    from datetime import timedelta
    
    if fecha:
        try:
            fecha = timezone.datetime.strptime(fecha, '%Y-%m-%d').date()
        except ValueError:
            fecha = ahora_servidor().date()
    else:
        fecha_str = request.GET.get('fecha', '')
        if fecha_str:
            try:
                fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                fecha = ahora_servidor().date()
        else:
            fecha = ahora_servidor().date()
    
    periodo = request.GET.get('periodo', 'dia')
    empleado_filtro = request.GET.get('empleado', '')
    
    fecha_dt = timezone.make_aware(timezone.datetime.combine(fecha, timezone.datetime.min.time()))
    fd = fecha_dt
    fh = fecha_dt + timedelta(days=1)
    
    ventas = Venta.objects.filter(
        fecha_venta__gte=fd,
        fecha_venta__lt=fh,
        cancelada=False
    ).select_related('cajero', 'turno')
    
    if periodo == 'mes':
        ventas = Venta.objects.filter(
            fecha_venta__year=fecha.year,
            fecha_venta__month=fecha.month,
            cancelada=False
        ).select_related('cajero')
    elif periodo == 'ano':
        ventas = Venta.objects.filter(
            fecha_venta__year=fecha.year,
            cancelada=False
        ).select_related('cajero')
    
    if empleado_filtro:
        ventas = ventas.filter(cajero__username=empleado_filtro)
    
    # Consecuencial Task 5: el PDF respeta el filtro ?pos= de la lista.
    pos_imp, _puntos_imp = _resolver_pos_filtro(request)
    if pos_imp is not None:
        ventas = ventas.filter(punto_venta=pos_imp)

    try:
        ventas = ventas.prefetch_related('detalles__producto')
        ventas_list = list(ventas)
    except Exception as e:
        print(f"Error converting ventas: {e}")
        ventas_list = []
    
    monto_total = 0
    total_efectivo = 0
    total_transferencia = 0
    costo_total = 0
    total_items = 0
    ranking_map = {}

    for v in ventas_list:
        detalles = list(v.detalles.all())
        v.items_list = detalles
        v.num_items = sum(d.cantidad for d in detalles)
        costo = 0
        for d in detalles:
            precio_costo = float(d.producto.precio_compra or 0)
            costo += float(d.cantidad) * precio_costo
            total_items += d.cantidad
            r = ranking_map.get(d.producto_id)
            if r is None:
                r = ranking_map[d.producto_id] = {
                    'producto': d.producto,
                    'cantidad': 0,
                    'ingreso': 0.0,
                }
            r['cantidad'] += d.cantidad
            r['ingreso'] += float(d.subtotal)
        v.costo_venta = costo
        v.ganancia = float(v.total or 0) - costo
        costo_total += costo
        try:
            if v.total:
                monto_total += float(v.total)
            if v.monto_recibido:
                total_efectivo += float(v.monto_recibido)
            if v.monto_transferencia:
                total_transferencia += float(v.monto_transferencia)
        except Exception:
            pass

    ranking = sorted(ranking_map.values(), key=lambda x: x['ingreso'], reverse=True)
    ticket_promedio = (monto_total / len(ventas_list)) if ventas_list else 0

    context = {
        'fecha': fecha,
        'ahora': timezone.now(),
        'ventas': ventas_list,
        'monto_total': monto_total,
        'total_efectivo': total_efectivo,
        'total_transferencia': total_transferencia,
        'total_ventas': len(ventas_list),
        'ganancia_total': monto_total - costo_total,
        'ticket_promedio': ticket_promedio,
        'total_items': total_items,
        'ranking': ranking,
        'periodo': periodo,
        'empleado_filtro': empleado_filtro,
        'punto_venta': pos_imp,
    }
    
    html_string = render_to_string('core/venta_impresion.html', context)

    buffer = BytesIO()

    _pisa = pisa
    if _pisa is None:
        try:
            from xhtml2pdf import pisa as _pisa_mod
            _pisa = _pisa_mod
        except Exception:
            return HttpResponse('PDF no disponible (falta xhtml2pdf/bidi en el servidor).', status=500)

    pisa_status = _pisa.CreatePDF(
        html_string,
        dest=buffer,
        encoding='utf-8'
    )
    
    if pisa_status.err:
        return HttpResponse('Error al generar PDF', status=500)
    
    pdf = buffer.getvalue()
    buffer.close()
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Ventas_{fecha.strftime("%Y%m%d")}.pdf"'
    response.write(pdf)
    
    return response


@requiere_admin
def ipb_impresion(request, fecha=None):
    """Vista que genera un PDF del IPB para impresión."""
    if fecha:
        try:
            fecha = timezone.datetime.strptime(fecha, '%Y-%m-%d').date()
        except ValueError:
            fecha = ahora_servidor().date()
    else:
        fecha_str = request.GET.get('fecha', '')
        if fecha_str:
            try:
                fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
            except ValueError:
                fecha = ahora_servidor().date()
        else:
            fecha = ahora_servidor().date()

    # Sin IPB antes del inicio del sistema: el PDF cae al primer día válido.
    if fecha < FECHA_INICIO_SISTEMA:
        fecha = FECHA_INICIO_SISTEMA

    _sincronizar_inventario_dia(fecha)
    # Consecuencial (nota de alcance Task 5): el PDF respeta el mismo
    # filtro ?pos= del IPB en pantalla (cálculo por almacén del POS).
    pos_actual, _puntos = _resolver_pos_filtro(request)
    context = _obtener_datos_ipb(fecha, punto_venta=pos_actual)
    
    html_string = render_to_string('core/ipb_impresion.html', context)
    
    # Crear buffer para el PDF
    buffer = BytesIO()

    # Generar PDF
    _pisa2 = pisa
    if _pisa2 is None:
        try:
            from xhtml2pdf import pisa as _pisa_mod
            _pisa2 = _pisa_mod
        except Exception:
            return HttpResponse('PDF no disponible (falta xhtml2pdf/bidi en el servidor).', status=500)
    pisa_status = _pisa2.CreatePDF(
        html_string,
        dest=buffer,
        encoding='utf-8'
    )
    
    if pisa_status.err:
        return HttpResponse('Error al generar PDF', status=500)
    
    # Preparar respuesta
    pdf = buffer.getvalue()
    buffer.close()
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="IPB_{fecha.strftime("%Y%m%d")}.pdf"'
    response.write(pdf)
    
    return response


@requiere_admin
def gasto_lista(request):
    hoy = ahora_servidor().date()
    fecha_str = request.GET.get('fecha', '')
    empleado_filtro = request.GET.get('empleado', '')
    periodo = request.GET.get('periodo', 'dia')

    if fecha_str:
        try:
            fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = hoy
    else:
        fecha = hoy

    gastos = Gasto.objects.select_related('cajero').all()

    if periodo == 'dia':
        titulo = f'Gastos del dia {fecha.strftime("%d/%m/%Y")}'
        gastos = gastos.filter(fecha_gasto__date=fecha)
    elif periodo == 'mes':
        titulo = f'Gastos de {fecha.strftime("%B %Y")}'
        gastos = gastos.filter(fecha_gasto__year=fecha.year, fecha_gasto__month=fecha.month)
    elif periodo == 'ano':
        titulo = f'Gastos del ano {fecha.year}'
        gastos = gastos.filter(fecha_gasto__year=fecha.year)
    else:
        titulo = f'Gastos del dia {fecha.strftime("%d/%m/%Y")}'
        gastos = gastos.filter(fecha_gasto__date=fecha)

    if empleado_filtro:
        gastos = gastos.filter(cajero__username=empleado_filtro)

    resumen = gastos.aggregate(
        total=Sum(F('cantidad_efectivo') + F('cantidad_transferencia')) or 0,
        cantidad=Count('id'),
        efectivo=Sum('cantidad_efectivo'),
        transferencia=Sum('cantidad_transferencia'),
    )

    empleados = Empleado.objects.filter(activo=True).select_related('user')

    context = {
        'gastos': gastos,
        'fecha': fecha.strftime('%Y-%m-%d'),
        'periodo': periodo,
        'titulo': titulo,
        'empleado_filtro': empleado_filtro,
        'empleados': empleados,
        'resumen_total': resumen['total'] or 0,
        'resumen_cantidad': resumen['cantidad'] or 0,
        'resumen_efectivo': resumen['efectivo'] or 0,
        'resumen_transferencia': resumen['transferencia'] or 0,
        'hoy': hoy.strftime('%Y-%m-%d'),
    }
    return render(request, 'core/gasto_lista.html', context)


@requiere_admin
def gasto_crear(request):
    if request.method == 'POST':
        cantidad_efectivo = Decimal(str(request.POST.get('cantidad_efectivo', 0)))
        cantidad_transferencia = Decimal(str(request.POST.get('cantidad_transferencia', 0)))
        categoria = request.POST.get('categoria', 'caja')
        descripcion = request.POST.get('descripcion', '').strip()

        total = cantidad_efectivo + cantidad_transferencia
        if total <= 0:
            messages.error(request, 'La cantidad debe ser mayor a 0.')
            return redirect('core:gasto_crear')

        numero_gasto = Gasto.generar_numero()
        Gasto.objects.create(
            numero_gasto=numero_gasto,
            cajero=request.user,
            cantidad_efectivo=cantidad_efectivo,
            cantidad_transferencia=cantidad_transferencia,
            categoria=categoria,
            descripcion=descripcion,
        )
        messages.success(request, f'Gasto {numero_gasto} creado correctamente.')
        return redirect('core:gasto_lista')

    return render(request, 'core/gasto_form.html', {'titulo': 'Registrar Gasto'})


@requiere_admin
def gasto_editar(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)

    if request.method == 'POST':
        gasto.cantidad_efectivo = Decimal(str(request.POST.get('cantidad_efectivo', 0)))
        gasto.cantidad_transferencia = Decimal(str(request.POST.get('cantidad_transferencia', 0)))
        gasto.categoria = request.POST.get('categoria', 'caja')
        gasto.descripcion = request.POST.get('descripcion', '').strip()
        gasto.save()
        messages.success(request, f'Gasto {gasto.numero_gasto} actualizado.')
        return redirect('core:gasto_lista')

    return render(request, 'core/gasto_form.html', {'titulo': 'Editar Gasto', 'gasto': gasto})


@requiere_admin
def gasto_eliminar(request, pk):
    gasto = get_object_or_404(Gasto, pk=pk)
    if request.method == 'POST':
        numero = gasto.numero_gasto
        gasto.delete()
        messages.success(request, f'Gasto {numero} eliminado.')
        return redirect('core:gasto_lista')
    return render(request, 'core/gasto_confirmar_eliminar.html', {'gasto': gasto})


@requiere_admin
def entrada_lista(request):
    hoy = ahora_servidor().date()
    fecha_str = request.GET.get('fecha', '')

    if fecha_str:
        try:
            fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = hoy
    else:
        fecha = hoy

    entradas = EntradaProducto.objects.filter(fecha_entrada__date=fecha).select_related('producto').order_by('-fecha_entrada')

    resumen = entradas.aggregate(
        total=Sum('costo_total'),
        cantidad=Count('id'),
    )

    try:
        es_admin = request.user.perfil.es_admin
    except Exception:
        es_admin = False
    # Spec §3: crear/eliminar entradas directas solo admin en solo-POS.
    # En los demás modos el historial sigue visible pero de solo lectura.
    puede_gestionar = es_admin and modo_actual() == 'solo_pos'

    context = {
        'entradas': entradas,
        'fecha': fecha.strftime('%Y-%m-%d'),
        'resumen_total': float(resumen['total'] or 0),
        'resumen_cantidad': resumen['cantidad'] or 0,
        'puede_gestionar': puede_gestionar,
    }
    return render(request, 'core/entrada_lista.html', context)


@requiere_modo('solo_pos')
@requiere_admin
def entrada_crear(request):
    """Entrada directa al punto de venta (solo admin en modo solo-POS).

    Suma a `Producto.stock` y lo deja `visible_pos=True` de inmediato
    (entra directo al mostrador). El proveedor es libre: el marcador
    `ALMACEN_PROVEEDOR` NO aplica (ese es solo de traslados).
    """
    productos = Producto.objects.filter(activo=True).select_related('categoria').order_by('nombre')

    if request.method == 'POST':
        producto_id = request.POST.get('producto')
        try:
            cantidad = Decimal(str(request.POST.get('cantidad', '0')))
        except Exception:
            cantidad = Decimal('0')
        try:
            costo_unitario = Decimal(str(request.POST.get('costo_unitario', '0')))
        except Exception:
            costo_unitario = Decimal('0')
        proveedor = request.POST.get('proveedor', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()

        if not producto_id or cantidad <= 0:
            messages.error(request, 'Seleccione un producto y cantidad mayor a 0 (admite 3 decimales, ej. 2.500 lb).')
            return redirect('core:entrada_crear')

        producto = get_object_or_404(Producto, pk=producto_id)

        if costo_unitario > 0:
            compra_antes = producto.precio_compra
            venta_antes = producto.precio_venta
            producto.precio_compra = costo_unitario
            producto.save(update_fields=['precio_compra'])
            producto.refresh_from_db()

        numero_entrada = EntradaProducto.generar_numero()
        entrada = EntradaProducto.objects.create(
            numero_entrada=numero_entrada,
            producto=producto,
            cantidad=cantidad,
            costo_unitario=costo_unitario,
            proveedor=proveedor,
            descripcion=descripcion,
        )
        if costo_unitario > 0:
            _log_cambio_precio(
                producto, compra_antes, producto.precio_compra,
                venta_antes, producto.precio_venta,
                accion='entrada_ok', motivo=f'Entrada {numero_entrada}',
                usuario=request.user, costo_entrada=costo_unitario,
                entrada=entrada)

        if not producto.visible_pos:
            producto.visible_pos = True
        _registrar_movimiento(producto, 'entrada', cantidad, request.user, entrada.id, f'Entrada #{numero_entrada}')

        _sincronizar_inventario_dia(ahora_servidor().date())

        messages.success(request, f'Entrada {numero_entrada} registrada. {"%g" % float(cantidad)} {producto.unidad_medida} agregados a {producto.nombre}.')
        return redirect('core:entrada_lista')

    return render(request, 'core/entrada_form.html', {'productos': productos})


@requiere_modo('solo_pos')
@requiere_admin
@require_POST
def entrada_eliminar(request, pk):
    """Elimina una entrada directa revirtiendo su stock (solo admin en
    modo solo-POS). Las entradas generadas por traslados del almacén no
    se tocan aquí (se gestionan cancelando el traslado)."""
    entrada = get_object_or_404(EntradaProducto, pk=pk)
    if entrada.traslados_almacen.exists():
        messages.error(
            request,
            f'La entrada {entrada.numero_entrada} viene de un traslado del '
            'almacén: cancélelo desde Traslados en un modo con almacén.')
        return redirect('core:entrada_lista')
    numero = entrada.numero_entrada
    cantidad = entrada.cantidad
    fecha = entrada.fecha_entrada.date()
    with transaction.atomic():
        producto = Producto.objects.select_for_update().get(pk=entrada.producto_id)
        if producto.stock < cantidad:
            messages.error(
                request,
                f'No se puede eliminar. Stock actual ({"%g" % float(producto.stock)}) '
                f'menor que cantidad de entrada ({"%g" % float(cantidad)}).')
            return redirect('core:entrada_lista')
        producto.stock -= cantidad
        producto.save(update_fields=['stock'])
        MovimientoInventario.objects.filter(
            producto=producto,
            referencia_id=entrada.id,
            tipo='entrada'
        ).delete()
        entrada.delete()
    _sincronizar_inventario_dia(fecha)
    messages.success(
        request,
        f'Entrada {numero} eliminada. Se revirtieron {"%g" % float(cantidad)} '
        f'unidades del stock de {producto.nombre}.')
    return redirect('core:entrada_lista')


# ============================================================
# ALMACÉN (admin + almacenero; ajeno al IPB y a las ventas).
# Flujo: entrada al almacén -> traslado al POS (= entrada IPB).
# ============================================================

def _movimiento_almacen(producto, tipo, cantidad, stock_anterior, stock_nuevo,
                        usuario=None, referencia_id=None, descripcion='',
                        almacen=None):
    """Auditoría propia del almacén (no toca IPB ni MovimientoInventario)."""
    AlmacenMovimiento.objects.create(
        producto=producto,
        almacen=almacen,
        tipo=tipo,
        cantidad=cantidad,
        stock_anterior=stock_anterior,
        stock_nuevo=stock_nuevo,
        referencia_id=referencia_id,
        descripcion=descripcion,
        usuario=usuario,
    )


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_almacen
def almacen_panel(request):
    """Panel del almacén: existencias valorizadas y actividad del día."""
    hoy = ahora_servidor().date()
    almacen_f, multi = _resolver_almacen(request)
    existencias = AlmacenStock.objects.select_related(
        'producto', 'almacen').order_by('producto__nombre')
    movs = AlmacenMovimiento.objects.select_related('producto', 'almacen')
    entradas_qs = AlmacenEntrada.objects.filter(fecha_entrada__date=hoy)
    traslados_qs = AlmacenTraslado.objects.filter(fecha_traslado__date=hoy)
    if almacen_f:
        existencias = existencias.filter(Q(almacen=almacen_f) | Q(almacen__isnull=True))
        movs = movs.filter(Q(almacen=almacen_f) | Q(almacen__isnull=True))
        entradas_qs = entradas_qs.filter(Q(almacen=almacen_f) | Q(almacen__isnull=True))
        traslados_qs = traslados_qs.filter(Q(origen=almacen_f) | Q(destino_almacen=almacen_f) | Q(origen__isnull=True))
    valor = sum((s.valor for s in existencias), Decimal('0'))
    mapa_cad = _mapa_caducidad(almacen_f)
    cad_por_vencer = sum(1 for v in mapa_cad.values() if v == 'por_vencer')
    cad_vencidos = sum(1 for v in mapa_cad.values() if v == 'vencido')
    almacenes_info = []
    if multi:
        for a in Almacen.activos():
            st = AlmacenStock.objects.filter(
                Q(almacen=a) | Q(almacen__isnull=True)).select_related('producto') if a.es_principal else AlmacenStock.objects.filter(almacen=a).select_related('producto')
            v = sum((s.valor for s in st), Decimal('0'))
            almacenes_info.append({'obj': a, 'productos': st.count(), 'valor': v})
    context = {
        'total_productos': existencias.count(),
        'valor_almacen': valor,
        'entradas_hoy': entradas_qs.count(),
        'traslados_hoy': traslados_qs.count(),
        'recientes': movs.order_by('-fecha')[:10],
        'almacenes': Almacen.activos(),
        'almacen_actual': almacen_f,
        'multi': multi,
        'almacenes_info': almacenes_info,
        'cad_por_vencer': cad_por_vencer,
        'cad_vencidos': cad_vencidos,
    }
    return render(request, 'core/almacen_panel.html', context)


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_almacen
def almacen_stock(request):
    """Existencias del almacén con acceso a trasladar (y ajustar si admin)."""
    query = (request.GET.get('q') or '').strip()
    almacen_f, multi = _resolver_almacen(request)
    stocks = AlmacenStock.objects.select_related(
        'producto__categoria', 'almacen').order_by('producto__nombre')
    if almacen_f:
        stocks = stocks.filter(Q(almacen=almacen_f) | Q(almacen__isnull=True))
    if query:
        q_norm = _norm_sin_tildes(query)
        ids_codigo = [s.producto_id for s in stocks
                      if query.lower() in (s.producto.codigo or '').lower()]
        ids_nombre = [s.producto_id for s in stocks
                      if q_norm and q_norm in _norm_sin_tildes(s.producto.nombre)]
        stocks = stocks.filter(producto_id__in=set(ids_codigo) | set(ids_nombre))
    try:
        es_admin = request.user.perfil.es_admin
    except PerfilUsuario.DoesNotExist:
        es_admin = True
    mapa_cad = _mapa_caducidad(almacen_f)
    stocks = list(stocks)
    for s in stocks:
        s.caducidad = mapa_cad.get(s.producto_id, 'ok')
    return render(request, 'core/almacen_stock.html', {
        'stocks': stocks, 'q': query, 'es_admin': es_admin,
        'almacenes': Almacen.activos(), 'almacen_actual': almacen_f,
        'multi': multi,
    })


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_almacen
def almacen_entrada_lista(request):
    hoy = ahora_servidor().date()
    fecha_str = request.GET.get('fecha', '')
    if fecha_str:
        try:
            fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = hoy
    else:
        fecha = hoy
    almacen_f, multi = _resolver_almacen(request)
    entradas = AlmacenEntrada.objects.filter(
        fecha_entrada__date=fecha).select_related('producto', 'almacen').order_by('-fecha_entrada')
    if almacen_f:
        entradas = entradas.filter(almacen=almacen_f)
    resumen = entradas.aggregate(total=Sum('costo_total'), cantidad=Count('id'))
    return render(request, 'core/almacen_entrada_lista.html', {
        'entradas': entradas,
        'fecha': fecha.strftime('%Y-%m-%d'),
        'resumen_total': float(resumen['total'] or 0),
        'resumen_cantidad': resumen['cantidad'] or 0,
        'almacenes': Almacen.activos(),
        'almacen_actual': almacen_f,
        'multi': multi,
    })


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_almacen
def almacen_entrada_crear(request):
    """Entrada al almacén: suma al stock del almacén, NO al del POS."""
    productos = Producto.objects.filter(activo=True).select_related('categoria').order_by('nombre')
    if request.method == 'POST':
        producto_id = request.POST.get('producto')
        try:
            cantidad = Decimal(str(request.POST.get('cantidad', '0')))
        except Exception:
            cantidad = Decimal('0')
        try:
            costo_unitario = Decimal(str(request.POST.get('costo_unitario', '0')))
        except Exception:
            costo_unitario = Decimal('0')
        proveedor = request.POST.get('proveedor', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        fecha_caducidad = (request.POST.get('fecha_caducidad') or '').strip() or None
        if fecha_caducidad:
            try:
                timezone.datetime.strptime(fecha_caducidad, '%Y-%m-%d')
            except ValueError:
                messages.error(request, 'Fecha de caducidad inválida.')
                return redirect('core:almacen_entrada_crear')
        almacen_f, multi = _resolver_almacen(request)
        if multi and not almacen_f:
            messages.error(request, 'Seleccione el almacén destino.')
            return redirect('core:almacen_entrada_crear')
        if not producto_id or cantidad <= 0:
            messages.error(request, 'Seleccione un producto y cantidad mayor a 0 (admite 3 decimales, ej. 2.500 lb).')
            return redirect('core:almacen_entrada_crear')
        producto = get_object_or_404(Producto, pk=producto_id)
        if costo_unitario > 0:
            producto.precio_compra = costo_unitario
            producto.save(update_fields=['precio_compra'])
            producto.refresh_from_db()
        with transaction.atomic():
            entrada = AlmacenEntrada.objects.create(
                numero_entrada=AlmacenEntrada.generar_numero(),
                producto=producto,
                almacen=almacen_f,
                cantidad=cantidad,
                costo_unitario=costo_unitario,
                proveedor=proveedor,
                descripcion=descripcion,
                fecha_caducidad=fecha_caducidad,
                registrado_por=request.user,
            )
            stock, _ = _get_or_create_stock(producto, almacen_f)
            anterior = stock.cantidad
            stock.cantidad = anterior + cantidad
            stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
            _movimiento_almacen(producto, 'entrada', cantidad, anterior,
                                stock.cantidad, request.user, entrada.id,
                                f'Entrada almacén #{entrada.numero_entrada}',
                                almacen=almacen_f)
        messages.success(
            request,
            f'Entrada {entrada.numero_entrada} al almacén: {"%g" % float(cantidad)} {producto.unidad_medida} de {producto.nombre}.')
        return redirect('core:almacen_entrada_lista')
    preseleccionado = request.GET.get('producto', '') or request.POST.get('producto', '')
    from urllib.parse import quote as _quote
    _aqui = request.get_full_path()
    next_crear = f'/productos/crear/?next={_quote(_aqui, safe="")}'
    almacen_f, multi = _resolver_almacen(request)
    stock_map = _stock_map_para(almacen_f)
    return render(request, 'core/almacen_entrada_form.html', {
        'productos': productos,
        'preseleccionado': str(preseleccionado),
        'next_crear': next_crear,
        'stock_map': stock_map,
        'stock_json': json.dumps({str(k): str(v) for k, v in stock_map.items()}),
        'almacenes': Almacen.activos(),
        'almacen_actual': almacen_f,
        'multi': multi,
    })


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_admin
@require_POST
def almacen_entrada_cancelar(request, pk):
    """Cancela una entrada al almacén revirtiendo su stock (solo admin).

    El costo del producto no se revierte (pudo cambiar con entradas
    posteriores). Se bloquea si el almacén ya no tiene suficiente
    (parte de la mercancía se trasladó al POS).
    """
    from django.urls import reverse as _reverse
    entrada = get_object_or_404(AlmacenEntrada, pk=pk)
    producto = entrada.producto
    cantidad = entrada.cantidad
    numero = entrada.numero_entrada
    fecha_qs = entrada.fecha_entrada.date().isoformat()
    with transaction.atomic():
        stock = _stock_de(producto, entrada.almacen)
        disponible = stock.cantidad if stock else Decimal('0')
        if disponible < cantidad:
            messages.error(
                request,
                f'No se puede cancelar la entrada {numero}: el almacén solo tiene '
                f'{"%g" % float(disponible)} {producto.unidad_medida} de {producto.nombre} '
                '(parte ya se trasladó al punto de venta).')
            return redirect(f"{_reverse('core:almacen_entrada_lista')}?fecha={fecha_qs}")
        anterior = stock.cantidad
        stock.cantidad = anterior - cantidad
        stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
        entrada.delete()
        _movimiento_almacen(producto, 'ajuste', cantidad, anterior,
                            stock.cantidad, request.user, None,
                            f'Cancelación entrada almacén #{numero}',
                            almacen=stock.almacen)
    messages.success(
        request,
        f'Entrada {numero} cancelada: {"%g" % float(cantidad)} {producto.unidad_medida} '
        f'de {producto.nombre} devueltos (existencia actual: {"%g" % float(stock.cantidad)}).')
    return redirect(f"{_reverse('core:almacen_entrada_lista')}?fecha={fecha_qs}")


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_almacen
def almacen_traslado_lista(request):
    hoy = ahora_servidor().date()
    fecha_str = request.GET.get('fecha', '')
    if fecha_str:
        try:
            fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = hoy
    else:
        fecha = hoy
    almacen_f, multi = _resolver_almacen(request)
    traslados = AlmacenTraslado.objects.filter(
        fecha_traslado__date=fecha).select_related(
        'producto', 'origen', 'destino_almacen').order_by('-fecha_traslado')
    if almacen_f:
        traslados = traslados.filter(Q(origen=almacen_f) | Q(destino_almacen=almacen_f))
    return render(request, 'core/almacen_traslado_lista.html', {
        'traslados': traslados,
        'fecha': fecha.strftime('%Y-%m-%d'),
        'resumen_cantidad': traslados.count(),
        'almacenes': Almacen.activos(),
        'almacen_actual': almacen_f,
        'multi': multi,
    })


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_almacen
def almacen_traslado_crear(request):
    """Traslado con origen y destino (POS o almacén).

    - destino POS: genera EntradaProducto (proveedor 'Almacén: <nombre>')
      visible en IPB/POS.
    - destino ALMACEN: mueve entre stocks sin tocar el POS.
    """
    almacen_sel, multi = _resolver_almacen(request, campo='origen')
    productos = Producto.objects.filter(
        activo=True, almacen_stock__cantidad__gt=0).select_related('categoria').order_by('nombre')
    stock_map = _stock_map_para(almacen_sel)
    preseleccionado = request.GET.get('producto', '')
    if request.method == 'POST':
        producto_id = request.POST.get('producto')
        try:
            cantidad = Decimal(str(request.POST.get('cantidad', '0')))
        except Exception:
            cantidad = Decimal('0')
        origen, multi_post = _resolver_almacen(request, campo='origen')
        destino_tipo = (request.POST.get('destino_tipo') or 'POS').upper()
        if destino_tipo not in ('POS', 'ALMACEN'):
            destino_tipo = 'POS'
        # Spec §5 multi-POS: traslados hacia POS no existen (el POS vende
        # directo del almacén); solo entre almacenes. Sin borrar nada.
        if modo_actual() == 'multi_pos' and destino_tipo == 'POS':
            messages.error(
                request,
                'En el modo multi-POS los traslados al punto de venta no '
                'existen: solo entre almacenes.')
            return redirect('core:almacen_traslado_crear')
        destino_almacen = None
        if destino_tipo == 'ALMACEN':
            try:
                destino_almacen = Almacen.objects.get(
                    pk=int(request.POST.get('destino_almacen') or 0), activo=True)
            except (Almacen.DoesNotExist, ValueError, TypeError):
                destino_almacen = None
            if not destino_almacen:
                messages.error(request, 'Seleccione el almacén destino.')
                return redirect('core:almacen_traslado_crear')
        if multi_post and not origen:
            messages.error(request, 'Seleccione el almacén origen.')
            return redirect('core:almacen_traslado_crear')
        if destino_tipo == 'ALMACEN' and origen and destino_almacen and origen.pk == destino_almacen.pk:
            messages.error(request, 'El origen y el destino no pueden ser el mismo almacén.')
            return redirect('core:almacen_traslado_crear')
        if not producto_id or cantidad <= 0:
            messages.error(request, 'Seleccione un producto y cantidad mayor a 0.')
            return redirect('core:almacen_traslado_crear')
        producto = get_object_or_404(Producto, pk=producto_id)
        with transaction.atomic():
            stock = _stock_de(producto, origen)
            disponible = stock.cantidad if stock else Decimal('0')
            if disponible < cantidad:
                messages.error(
                    request,
                    f'Sin existencias suficientes en {origen.nombre if origen else "almacén"} para {producto.nombre} (disponible: {"%g" % float(disponible)}).')
                return redirect('core:almacen_traslado_crear')
            costo = producto.precio_compra or Decimal('0')
            num_traslado = AlmacenTraslado.generar_numero()
            entrada = None
            num_entrada = None
            if destino_tipo == 'POS':
                num_entrada = EntradaProducto.generar_numero()
                entrada = EntradaProducto.objects.create(
                    numero_entrada=num_entrada,
                    producto=producto,
                    cantidad=cantidad,
                    costo_unitario=costo,
                    proveedor=almacen_proveedor_nombre(origen.nombre if origen else ''),
                    descripcion=f'Traslado {num_traslado} de {origen.nombre if origen else "almacén"} al punto de venta',
                )
                _registrar_movimiento(producto, 'entrada', cantidad, request.user,
                                      entrada.id, f'Entrada #{num_entrada} (traslado {num_traslado} del almacén)')
            traslado = AlmacenTraslado.objects.create(
                numero_traslado=num_traslado,
                producto=producto,
                cantidad=cantidad,
                costo_unitario=costo,
                origen=origen,
                destino_tipo=destino_tipo,
                destino_almacen=destino_almacen,
                registrado_por=request.user,
                entrada_generada=entrada,
            )
            anterior = stock.cantidad
            stock.cantidad = anterior - cantidad
            stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
            if destino_tipo == 'POS':
                if not producto.visible_pos:
                    producto.visible_pos = True
                    producto.save(update_fields=['visible_pos'])
                _movimiento_almacen(producto, 'traslado', cantidad, anterior,
                                    stock.cantidad, request.user, traslado.id,
                                    f'Traslado #{num_traslado} al punto de venta (entrada {num_entrada})',
                                    almacen=origen)
                _sincronizar_inventario_dia(ahora_servidor().date())
                messages.success(
                    request,
                    f'Traslado {num_traslado}: {"%g" % float(cantidad)} {producto.unidad_medida} de {producto.nombre} al punto de venta (entrada {num_entrada} en el IPB, ahora visible en el POS).')
            else:
                dest_stock, _ = _get_or_create_stock(producto, destino_almacen)
                ant_dest = dest_stock.cantidad
                dest_stock.cantidad = ant_dest + cantidad
                dest_stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
                _movimiento_almacen(producto, 'traslado', cantidad, anterior,
                                    stock.cantidad, request.user, traslado.id,
                                    f'Traslado #{num_traslado} a {destino_almacen.nombre}',
                                    almacen=origen)
                _movimiento_almacen(producto, 'entrada', cantidad, ant_dest,
                                    dest_stock.cantidad, request.user, traslado.id,
                                    f'Traslado #{num_traslado} desde {origen.nombre if origen else "?"}',
                                    almacen=destino_almacen)
                messages.success(
                    request,
                    f'Traslado {num_traslado}: {"%g" % float(cantidad)} {producto.unidad_medida} de {producto.nombre} de {origen.nombre} a {destino_almacen.nombre}.')
        return redirect('core:almacen_traslado_lista')
    return render(request, 'core/almacen_traslado_form.html', {
        'productos': productos, 'stock_map': stock_map,
        'stock_json': json.dumps({str(k): str(v) for k, v in stock_map.items()}),
        'preseleccionado': str(preseleccionado),
        'almacenes': Almacen.activos(),
        'almacen_actual': almacen_sel,
        'multi': multi,
    })


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_admin
@require_POST
def almacen_traslado_cancelar(request, pk):
    """Cancela un traslado devolviendo todo a la normalidad (solo admin).

    Devuelve la cantidad al almacén, la descuenta del punto de venta,
    elimina la entrada IPB generada y el traslado, con rastro en ambas
    auditorías. Se bloquea si el POS ya no tiene suficiente (se vendió)
    o si el día del IPB está cerrado. Si el producto había sido publicado
    por este traslado y queda sin más traslados ni stock en el POS, vuelve
    a ocultarse.
    """
    from django.urls import reverse as _reverse
    traslado = get_object_or_404(AlmacenTraslado, pk=pk)
    producto = traslado.producto
    cantidad = traslado.cantidad
    numero = traslado.numero_traslado
    fecha = traslado.fecha_traslado.date()
    fecha_qs = fecha.isoformat()
    if InventarioDiario.objects.filter(
            producto=producto, fecha=fecha, cerrado=True).exists():
        messages.error(
            request,
            f'No se puede cancelar el traslado {numero}: el IPB del '
            f'{fecha.strftime("%d/%m/%Y")} ya está cerrado.')
        return redirect(f"{_reverse('core:almacen_traslado_lista')}?fecha={fecha_qs}")
    with transaction.atomic():
        producto = Producto.objects.select_for_update().get(pk=producto.pk)
        origen = traslado.origen
        if traslado.destino_tipo == 'ALMACEN' and traslado.destino_almacen_id:
            dest = _stock_de(producto, traslado.destino_almacen)
            disp_dest = dest.cantidad if dest else Decimal('0')
            if disp_dest < cantidad:
                messages.error(
                    request,
                    f'No se puede cancelar el traslado {numero}: el almacén destino solo tiene '
                    f'{"%g" % float(disp_dest)} {producto.unidad_medida} de {producto.nombre}.')
                return redirect(f"{_reverse('core:almacen_traslado_lista')}?fecha={fecha_qs}")
            stock = _stock_de(producto, origen)
            if stock is None:
                stock, _ = _get_or_create_stock(producto, origen)
            ant_alm = stock.cantidad
            stock.cantidad = ant_alm + cantidad
            stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
            ant_dest = dest.cantidad
            dest.cantidad = ant_dest - cantidad
            dest.save(update_fields=['cantidad', 'fecha_actualizacion'])
            num_entrada = None
            traslado.delete()
            _movimiento_almacen(producto, 'ajuste', cantidad, ant_dest,
                                dest.cantidad, request.user, None,
                                f'Cancelación traslado #{numero} (devolución a origen)',
                                almacen=dest.almacen)
            messages.success(request, f'Traslado {numero} cancelado: devuelto al almacén origen.')
            return redirect(f"{_reverse('core:almacen_traslado_lista')}?fecha={fecha_qs}")
        if producto.stock < cantidad:
            messages.error(
                request,
                f'No se puede cancelar el traslado {numero}: el punto de venta solo tiene '
                f'{"%g" % float(producto.stock)} {producto.unidad_medida} de {producto.nombre} '
                '(parte ya se vendió).')
            return redirect(f"{_reverse('core:almacen_traslado_lista')}?fecha={fecha_qs}")
        stock = _stock_de(producto, origen)
        if stock is None:
            stock, _ = _get_or_create_stock(producto, origen)
        ant_alm = stock.cantidad
        ant_pos = producto.stock
        producto.stock = ant_pos - cantidad
        campos = ['stock']
        otros = AlmacenTraslado.objects.filter(producto=producto).exclude(pk=traslado.pk).exists()
        if producto.stock == 0 and not otros:
            producto.visible_pos = False
            campos.append('visible_pos')
        producto.save(update_fields=campos)
        stock.cantidad = ant_alm + cantidad
        stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
        entrada = traslado.entrada_generada
        num_entrada = entrada.numero_entrada if entrada else None
        if entrada is not None:
            entrada.delete()
        traslado.delete()
        _movimiento_almacen(producto, 'ajuste', cantidad, ant_alm,
                            stock.cantidad, request.user, None,
                            f'Cancelación traslado #{numero} (devolución al almacén)',
                            almacen=origen)
        MovimientoInventario.objects.create(
            producto=producto, tipo='ajuste', cantidad=-cantidad,
            stock_anterior=ant_pos, stock_nuevo=producto.stock,
            referencia_id=None,
            descripcion=(f'Cancelación traslado #{numero}' +
                         (f' (entrada {num_entrada} eliminada)' if num_entrada else '')),
            usuario=request.user,
        )
        _sincronizar_inventario_dia(fecha)
    messages.success(
        request,
        f'Traslado {numero} cancelado: {"%g" % float(cantidad)} {producto.unidad_medida} '
        f'de {producto.nombre} devueltos al almacén.')
    return redirect(f"{_reverse('core:almacen_traslado_lista')}?fecha={fecha_qs}")


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_almacen
def almacen_movimientos(request):
    """Auditoría propia del almacén (entradas, traslados y ajustes)."""
    query = (request.GET.get('q') or '').strip()
    tipo = request.GET.get('tipo', '')
    almacen_f, multi = _resolver_almacen(request)
    movs = AlmacenMovimiento.objects.select_related('producto', 'usuario', 'almacen').order_by('-fecha')
    if almacen_f:
        movs = movs.filter(Q(almacen=almacen_f) | Q(almacen__isnull=True))
    if tipo in ('entrada', 'traslado', 'ajuste'):
        movs = movs.filter(tipo=tipo)
    if query:
        q_norm = _norm_sin_tildes(query)
        ids = [m.producto_id for m in movs.select_related('producto')
               if q_norm in _norm_sin_tildes(m.producto.nombre)]
        movs = movs.filter(producto_id__in=ids)
    return render(request, 'core/almacen_movimientos.html', {
        'movimientos': movs[:300], 'q': query, 'tipo': tipo,
        'almacenes': Almacen.activos(), 'almacen_actual': almacen_f,
        'multi': multi,
    })


@requiere_modo('pos_almacenes', 'multi_pos')
@requiere_admin
def almacen_ajuste(request):
    """Ajuste de existencias del almacén (solo admin)."""
    productos = Producto.objects.filter(activo=True).order_by('nombre')
    almacen_f, multi = _resolver_almacen(request)
    stock_map = _stock_map_para(almacen_f)
    preseleccionado = request.GET.get('producto', '') or request.POST.get('producto', '')
    if request.method == 'POST':
        producto_id = request.POST.get('producto')
        try:
            nueva = Decimal(str(request.POST.get('cantidad', '')))
        except Exception:
            nueva = None
        motivo = (request.POST.get('motivo') or '').strip()
        almacen_post, multi_post = _resolver_almacen(request)
        if multi_post and not almacen_post:
            messages.error(request, 'Seleccione el almacén del ajuste.')
            return redirect('core:almacen_ajuste')
        if not producto_id or nueva is None or nueva < 0:
            messages.error(request, 'Seleccione un producto y una cantidad válida (0 o más).')
            return redirect('core:almacen_ajuste')
        if not motivo:
            messages.error(request, 'Indique el motivo del ajuste.')
            return redirect('core:almacen_ajuste')
        producto = get_object_or_404(Producto, pk=producto_id)
        with transaction.atomic():
            stock, _ = _get_or_create_stock(producto, almacen_post)
            anterior = stock.cantidad
            stock.cantidad = nueva
            stock.save(update_fields=['cantidad', 'fecha_actualizacion'])
            _movimiento_almacen(producto, 'ajuste', nueva, anterior, nueva,
                                request.user, None, f'Ajuste: {motivo}',
                                almacen=almacen_post)
        messages.success(
            request, f'Existencia de {producto.nombre} ajustada a {"%g" % float(nueva)}.')
        return redirect('core:almacen_stock')
    return render(request, 'core/almacen_ajuste_form.html', {
        'productos': productos, 'stock_map': stock_map,
        'stock_json': json.dumps({str(k): str(v) for k, v in stock_map.items()}),
        'preseleccionado': str(preseleccionado),
        'almacenes': Almacen.activos(),
        'almacen_actual': almacen_f,
        'multi': multi,
    })


# ============================================================
# CONFIGURACIÓN (tienda + almacenes + apariencia + regional, solo admin)
# ============================================================

def _tienda_context():
    try:
        cfg = ConfiguracionTienda.get_solo()
    except Exception:
        cfg = None
    if cfg is None:
        return {'TIENDA': {'nombre': 'Donde Clau', 'logo_url': None,
                           'color_acento': '#6f53d9', 'tema': 'light'},
                'MODO': 'pos_almacenes'}
    try:
        modo = cfg.modo_operacion
    except Exception:
        modo = 'pos_almacenes'
    if modo not in MODOS_OPERACION:
        modo = 'pos_almacenes'
    return {'TIENDA': {'nombre': cfg.nombre_tienda, 'logo_url': cfg.logo_url,
                       'color_acento': cfg.color_acento or '#6f53d9',
                       'tema': cfg.tema_por_defecto or 'light',
                       'moneda': cfg.moneda, 'simbolo': cfg.simbolo_moneda,
                       'objeto': cfg, 'modo': modo},
            'MODO': modo}


def configuracion_tienda(request):
    """Context processor: nombre/logo/acento disponibles en base.html."""
    try:
        return _tienda_context()
    except Exception:
        return {}


def _resolver_almacen(request, campo='almacen'):
    """Devuelve el almacén activo según GET→sesión→único.

    Con 1 solo almacén devuelve ese sin exigir selector (compatibilidad).
    Con 2+ exige selección explícita (GET o sesión) o None.
    """
    try:
        activos = list(Almacen.activos())
    except Exception:
        return None, False
    if len(activos) == 1:
        return activos[0], False
    if not activos:
        return None, True
    # GET manda: si el parámetro viene presente pero vacío ("Todos"),
    # limpia la sesión para volver a ver todos los almacenes.
    if campo in request.GET or 'origen' in request.GET or 'almacen' in request.GET:
        raw = request.GET.get(campo, '')
        if not raw and campo != 'origen':
            raw = request.GET.get('origen', '')
        if not raw and campo != 'almacen':
            raw = request.GET.get('almacen', '')
        if not raw:
            request.session.pop('almacen_id', None)
            return None, True
        try:
            elegido = next((a for a in activos if a.pk == int(raw)), None)
        except (ValueError, TypeError):
            elegido = None
        if elegido:
            request.session['almacen_id'] = elegido.pk
        return elegido, True
    aid = request.POST.get(campo) or request.session.get('almacen_id')
    # Compat: el formulario de traslados usa campo 'origen'; acéptalo como alias.
    if not aid and campo != 'origen':
        aid = request.POST.get('origen')
    if not aid and campo != 'almacen':
        aid = request.POST.get('almacen')
    try:
        aid = int(aid) if aid else None
    except (ValueError, TypeError):
        aid = None
    return next((a for a in activos if a.pk == aid), None), True


def _stock_de(producto, almacen):
    """Stock del (producto, almacén) con compat legacy (almacen NULL→origen)."""
    if almacen is None:
        return AlmacenStock.objects.select_for_update().filter(
            producto=producto, almacen__isnull=True).first()
    stock = AlmacenStock.objects.select_for_update().filter(
        producto=producto, almacen=almacen).first()
    if stock is None:
        # Migra fila legacy sin almacén para no perder existencias previas.
        legacy = AlmacenStock.objects.select_for_update().filter(
            producto=producto, almacen__isnull=True).first()
        if legacy is not None:
            legacy.almacen = almacen
            legacy.save(update_fields=['almacen'])
            return legacy
    return stock


def _get_or_create_stock(producto, almacen):
    """Get_or_create por (producto, almacén) reutilizando fila legacy NULL."""
    if almacen is None:
        s = AlmacenStock.objects.filter(
            producto=producto, almacen__isnull=True).first()
        if s is not None:
            return s, False
        return AlmacenStock.objects.create(
            producto=producto, almacen=None, cantidad=Decimal('0')), True
    try:
        return AlmacenStock.objects.get(producto=producto, almacen=almacen), False
    except AlmacenStock.DoesNotExist:
        pass
    legacy = AlmacenStock.objects.filter(
        producto=producto, almacen__isnull=True).first()
    if legacy is not None:
        legacy.almacen = almacen
        legacy.save(update_fields=['almacen'])
        return legacy, False
    return AlmacenStock.objects.create(
        producto=producto, almacen=almacen, cantidad=Decimal('0')), True


def _mapa_caducidad(almacen_f):
    """Peor estado de caducidad por producto: vencido > por_vencer > ok."""
    from .models import DIAS_AVISO_CADUCIDAD
    hoy = ahora_servidor().date()
    limite = hoy + timedelta(days=DIAS_AVISO_CADUCIDAD)
    qs = AlmacenEntrada.objects.filter(fecha_caducidad__isnull=False)
    if almacen_f:
        qs = qs.filter(Q(almacen=almacen_f) | Q(almacen__isnull=True))
    orden = {'ok': 0, 'por_vencer': 1, 'vencido': 2}
    mapa = {}
    for e in qs.values('producto_id', 'fecha_caducidad'):
        if e['fecha_caducidad'] < hoy:
            est = 'vencido'
        elif e['fecha_caducidad'] <= limite:
            est = 'por_vencer'
        else:
            est = 'ok'
        if orden[est] > orden[mapa.get(e['producto_id'], 'ok')]:
            mapa[e['producto_id']] = est
    return mapa


def _stock_map_para(almacen_f):
    """Mapa producto_id→cantidad incluyendo filas legacy NULL si filtra."""
    qs = AlmacenStock.objects.all()
    rows = list(qs)
    m = {}
    for s in rows:
        if almacen_f and s.almacen_id not in (almacen_f.pk, None):
            continue
        # El stock del almacén manda; el legacy solo si no hay propio.
        if s.producto_id not in m or (s.almacen_id == (almacen_f.pk if almacen_f else None)):
            m[s.producto_id] = s.cantidad
    return m


def _convertir_imagenes_a_webp(calidad=85):
    """Convierte a WebP las imágenes de productos (JPG/PNG/...) .

    Por cada producto con imagen no-WebP: guarda la versión .webp
    (misma carpeta, mismo base), actualiza el producto y borra el
    archivo original. Devuelve (convertidas, omitidas, errores).
    Nunca rompe el lote: cada producto se procesa en su propio try.
    """
    import io as _io
    import os as _os
    from django.core.files.base import ContentFile
    from django.core.files.storage import default_storage
    from PIL import Image as _Img
    try:
        from pillow_heif import register_heif_opener as _reg_heif
        _reg_heif()
    except Exception:
        pass
    convertidas, omitidas, errores = 0, 0, []
    qs = Producto.objects.exclude(imagen__isnull=True).exclude(imagen='')
    for p in qs.iterator():
        try:
            nombre = p.imagen.name
        except Exception:
            omitidas += 1
            continue
        if not nombre or nombre.lower().endswith('.webp'):
            omitidas += 1
            continue
        try:
            if not default_storage.exists(nombre):
                omitidas += 1
                continue
            with default_storage.open(nombre, 'rb') as f:
                img = _Img.open(f)
                img.load()
            # WebP conserva alfa: solo se aplana si no hay transparencia.
            if img.mode in ('RGBA', 'LA', 'PA'):
                try:
                    if img.getchannel('A').getextrema() == (255, 255):
                        img = img.convert('RGB')
                except Exception:
                    img = img.convert('RGB')
            elif img.mode != 'RGB':
                img = img.convert('RGB')
            base, _ext = _os.path.splitext(nombre)
            nuevo = base + '.webp'
            buf = _io.BytesIO()
            img.save(buf, format='WEBP', quality=calidad, method=6)
            buf.seek(0)
            if default_storage.exists(nuevo):
                default_storage.delete(nuevo)
            default_storage.save(nuevo, ContentFile(buf.read()))
            p.imagen = nuevo
            p.save(update_fields=['imagen'])
            if nuevo != nombre and default_storage.exists(nombre):
                default_storage.delete(nombre)
            convertidas += 1
        except Exception as e:
            errores.append(f"{nombre}: {e}")
    return convertidas, omitidas, errores


@requiere_admin
def configuracion(request):
    cfg = ConfiguracionTienda.get_solo()
    tab = request.GET.get('tab', 'tienda')
    if request.method == 'POST':
        form_kind = request.POST.get('form_kind', 'tienda')
        if form_kind == 'modo':
            # Selector de modo de operación (solo admin: la vista ya lo exige).
            # Cambiar de modo NUNCA borra datos: solo oculta/muestra secciones.
            nuevo = (request.POST.get('modo_operacion') or '').strip()
            validos = dict(ConfiguracionTienda.MODOS_OPERACION)
            if nuevo in validos:
                if cfg.modo_operacion != nuevo:
                    cfg.modo_operacion = nuevo
                    cfg.save(update_fields=['modo_operacion'])
                    messages.success(
                        request,
                        f"Modo de operación cambiado a '{validos[nuevo]}'. "
                        'Lo no aplicable se oculta sin borrar datos.')
                else:
                    messages.info(request, 'El modo de operación no cambió.')
            else:
                messages.error(request, 'Modo de operación inválido.')
            return redirect(f"{reverse_configuracion()}?tab=tienda")
        if form_kind == 'pos_crear':
            # CRUD de puntos de venta (spec §5, solo admin: la vista lo exige).
            # Un POS ↔ un almacén (varios POS pueden compartir almacén).
            nombre = (request.POST.get('nombre') or '').strip()
            almacen = Almacen.objects.filter(pk=_pos_id(request, 'almacen')).first()
            if not nombre:
                messages.error(
                    request, 'El nombre del punto de venta es obligatorio.')
            elif almacen is None:
                messages.error(
                    request,
                    'Seleccione el almacén que surte al punto de venta.')
            elif PuntoVenta.objects.filter(nombre__iexact=nombre).exists():
                messages.error(
                    request, 'Ya existe un punto de venta con ese nombre.')
            else:
                PuntoVenta.objects.create(nombre=nombre, almacen=almacen)
                messages.success(
                    request, f"Punto de venta '{nombre}' creado.")
            return redirect(f"{reverse_configuracion()}?tab=almacenes")
        if form_kind == 'pos_editar':
            pos = PuntoVenta.objects.filter(
                pk=_pos_id(request, 'pos_id')).first()
            nombre = (request.POST.get('nombre') or '').strip()
            almacen = Almacen.objects.filter(
                pk=_pos_id(request, 'almacen')).first()
            if pos is None:
                messages.error(request, 'Punto de venta no encontrado.')
            elif not nombre:
                messages.error(
                    request, 'El nombre del punto de venta es obligatorio.')
            elif almacen is None:
                messages.error(
                    request,
                    'Seleccione el almacén que surte al punto de venta.')
            elif PuntoVenta.objects.filter(
                    nombre__iexact=nombre).exclude(pk=pos.pk).exists():
                messages.error(
                    request, 'Ya existe un punto de venta con ese nombre.')
            else:
                pos.nombre = nombre
                pos.almacen = almacen
                pos.save(update_fields=['nombre', 'almacen'])
                messages.success(
                    request, f"Punto de venta '{nombre}' actualizado.")
            return redirect(f"{reverse_configuracion()}?tab=almacenes")
        if form_kind == 'pos_toggle':
            pos = PuntoVenta.objects.filter(
                pk=_pos_id(request, 'pos_id')).first()
            if pos is None:
                messages.error(request, 'Punto de venta no encontrado.')
            elif pos.activo:
                if PuntoVenta.objects.filter(activo=True).count() <= 1:
                    messages.error(
                        request,
                        'No se puede desactivar el único punto de venta activo.')
                elif Turno.objects.filter(
                        punto_venta=pos, abierto=True).exists():
                    messages.error(
                        request,
                        f"No se puede desactivar '{pos.nombre}': "
                        'tiene turnos abiertos. Ciérrelos primero.')
                else:
                    pos.activo = False
                    pos.save(update_fields=['activo'])
                    messages.success(
                        request,
                        f"Punto de venta '{pos.nombre}' desactivado.")
            else:
                pos.activo = True
                pos.save(update_fields=['activo'])
                messages.success(
                    request, f"Punto de venta '{pos.nombre}' activado.")
            return redirect(f"{reverse_configuracion()}?tab=almacenes")
        if form_kind == 'convertir_webp':
            # Convierte a WebP todas las imágenes de productos que aún
            # estén en JPG/PNG/etc, borra el archivo original y apunta
            # cada producto a su nueva imagen .webp.
            convertidas, omitidas, errores = _convertir_imagenes_a_webp()
            if convertidas:
                messages.success(
                    request,
                    f"Imágenes convertidas a WebP: {convertidas} "
                    f"(omitidas: {omitidas}).")
            else:
                messages.info(
                    request,
                    f"No había imágenes por convertir (omitidas: {omitidas}).")
            for err in errores[:5]:
                messages.warning(request, f"No se pudo convertir: {err}")
            return redirect(f"{reverse_configuracion()}?tab=tienda")
        if form_kind == 'tienda':
            f = ConfigTiendaForm(request.POST, request.FILES, instance=cfg)
        elif form_kind == 'apariencia':
            f = ConfigAparienciaForm(request.POST, instance=cfg)
        else:
            f = ConfigRegionalForm(request.POST, instance=cfg)
        if f.is_valid():
            f.save()
            messages.success(request, 'Configuración guardada.')
        else:
            messages.error(request, 'Revise los datos del formulario.')
        return redirect(f"{reverse_configuracion()}?tab={form_kind}")
    almacenes = list(Almacen.objects.all().order_by('nombre'))
    # Enriquece con stock valorizado.
    stocks = AlmacenStock.objects.select_related('producto', 'almacen')
    por_alm = {}
    for s in stocks:
        d = por_alm.setdefault(s.almacen_id, {'productos': 0, 'valor': Decimal('0')})
        d['productos'] += 1
        try:
            d['valor'] += s.cantidad * (s.producto.precio_compra or 0)
        except Exception:
            pass
    for a in almacenes:
        d = por_alm.get(a.pk, {'productos': 0, 'valor': Decimal('0')})
        a.info_productos = d['productos']
        a.info_valor = d['valor']
    return render(request, 'core/configuracion.html', {
        'cfg': cfg, 'tab': tab,
        'modos_operacion': ConfiguracionTienda.MODOS_OPERACION,
        'form_tienda': ConfigTiendaForm(instance=cfg),
        'form_apariencia': ConfigAparienciaForm(instance=cfg),
        'form_regional': ConfigRegionalForm(instance=cfg),
        'form_almacen': AlmacenForm(),
        'almacenes': almacenes, 'por_alm': por_alm,
        'puntos_venta': list(
            PuntoVenta.objects.select_related('almacen').order_by('nombre')),
        'multi': Almacen.objects.filter(activo=True).count() > 1,
    })


def reverse_configuracion():
    from django.urls import reverse
    return reverse('core:configuracion')


def _pos_id(request, campo):
    """PK entera desde POST sin 500 ante basura (None si inválida)."""
    try:
        return int(request.POST.get(campo) or 0)
    except (ValueError, TypeError):
        return 0


@requiere_admin
def config_almacen_crear(request):
    if request.method != 'POST':
        return redirect('core:configuracion')
    form = AlmacenForm(request.POST)
    if form.is_valid():
        form.save()
        messages.success(request, f"Almacén '{form.instance.nombre}' creado.")
    else:
        messages.error(request, 'No se pudo crear: ' + '; '.join(
            f"{k}: {', '.join(v)}" for k, v in form.errors.items()))
    return redirect('/configuracion/?tab=almacenes')


@requiere_admin
def config_almacen_editar(request, pk):
    alm = get_object_or_404(Almacen, pk=pk)
    if request.method == 'POST':
        form = AlmacenForm(request.POST, instance=alm)
        if form.is_valid():
            # No permitir desactivar aquí si viola reglas (lo valida el toggle).
            if not form.cleaned_data.get('activo') and alm.activo:
                return config_almacen_toggle(request, pk)
            form.save()
            messages.success(request, f"Almacén '{alm.nombre}' actualizado.")
        else:
            messages.error(request, 'No se pudo guardar: nombre duplicado o inválido.')
        return redirect('/configuracion/?tab=almacenes')
    return render(request, 'core/configuracion.html', {
        'cfg': ConfiguracionTienda.get_solo(), 'tab': 'almacenes',
        'form_tienda': ConfigTiendaForm(instance=ConfiguracionTienda.get_solo()),
        'form_apariencia': ConfigAparienciaForm(instance=ConfiguracionTienda.get_solo()),
        'form_regional': ConfigRegionalForm(instance=ConfiguracionTienda.get_solo()),
        'form_almacen': AlmacenForm(instance=alm),
        'almacenes': Almacen.objects.all().order_by('nombre'),
        'por_alm': {}, 'multi': Almacen.objects.filter(activo=True).count() > 1,
        'editando': alm,
        'puntos_venta': list(
            PuntoVenta.objects.select_related('almacen').order_by('nombre')),
    })


@requiere_admin
@require_POST
def config_almacen_toggle(request, pk):
    alm = get_object_or_404(Almacen, pk=pk)
    if alm.activo:
        # Bloqueos: único activo o con stock.
        if Almacen.objects.filter(activo=True).count() <= 1:
            messages.error(request, 'No se puede desactivar el único almacén activo.')
            return redirect('/configuracion/?tab=almacenes')
        tiene = AlmacenStock.objects.filter(almacen=alm, cantidad__gt=0).exists()
        if tiene:
            messages.error(
                request,
                f"No se puede desactivar '{alm.nombre}': aún tiene existencias. Trasládelas primero.")
            return redirect('/configuracion/?tab=almacenes')
        alm.activo = False
        alm.save(update_fields=['activo'])
        messages.success(request, f"Almacén '{alm.nombre}' desactivado.")
    else:
        alm.activo = True
        alm.save(update_fields=['activo'])
        messages.success(request, f"Almacén '{alm.nombre}' activado.")
    return redirect('/configuracion/?tab=almacenes')


# ============================================================
# RETIROS POR DONACIÓN
# ============================================================

@requiere_admin
def retiro_donacion_lista(request):
    hoy = ahora_servidor().date()
    fecha_str = request.GET.get('fecha', '')

    if fecha_str:
        try:
            fecha = timezone.datetime.strptime(fecha_str, '%Y-%m-%d').date()
        except ValueError:
            fecha = hoy
    else:
        fecha = hoy

    retiros = RetiroDonacion.objects.filter(
        fecha_retiro__date=fecha
    ).select_related('producto', 'beneficiario', 'registrado_por').order_by('-fecha_retiro')

    q = request.GET.get('q', '').strip()
    if q:
        retiros = retiros.filter(
            Q(producto__nombre__icontains=q) | Q(producto__codigo__icontains=q)
            | Q(motivo__icontains=q)
            | Q(beneficiario__first_name__icontains=q) | Q(beneficiario__last_name__icontains=q)
            | Q(beneficiario__username__icontains=q)
        )

    resumen = retiros.aggregate(
        total=Sum('producto__precio_venta'),
        cantidad=Sum('cantidad'),
    )

    context = {
        'retiros': retiros,
        'fecha': fecha.strftime('%Y-%m-%d'),
        'q': q,
        'resumen_total': float(resumen['total'] or 0),
        'resumen_cantidad': resumen['cantidad'] or 0,
    }
    return render(request, 'core/retiro_donacion_lista.html', context)


@requiere_admin
def retiro_donacion_crear(request):
    productos = Producto.objects.filter(activo=True, visible_pos=True, stock__gt=0).select_related('categoria').order_by('categoria__nombre', 'nombre')

    if request.method == 'POST':
        beneficiario_nombre = request.POST.get('beneficiario_nombre', '').strip()
        motivo = request.POST.get('motivo', '').strip()
        
        # El POS llama por fetch: responde JSON en vez de redirect con messages.
        es_json = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        productos_data = request.POST.get('productos_data', '')
        if not productos_data:
            if es_json:
                return JsonResponse({'ok': False, 'error': 'Seleccione al menos un producto.'}, status=400)
            messages.error(request, 'Seleccione al menos un producto.')
            return redirect('core:retiro_donacion_crear')

        try:
            items = json.loads(productos_data)
        except json.JSONDecodeError:
            if es_json:
                return JsonResponse({'ok': False, 'error': 'Datos de productos inválidos.'}, status=400)
            messages.error(request, 'Datos de productos inválidos.')
            return redirect('core:retiro_donacion_crear')

        if not items:
            if es_json:
                return JsonResponse({'ok': False, 'error': 'Seleccione al menos un producto con cantidad mayor a 0.'}, status=400)
            messages.error(request, 'Seleccione al menos un producto con cantidad mayor a 0.')
            return redirect('core:retiro_donacion_crear')

        if not beneficiario_nombre:
            beneficiario_nombre = request.POST.get('beneficiario_select', '').strip()
            if beneficiario_nombre:
                try:
                    beneficiario_user = User.objects.get(pk=beneficiario_nombre)
                    beneficiario_nombre = beneficiario_user.get_full_name() or beneficiario_user.username
                except User.DoesNotExist:
                    pass
        
        if not beneficiario_nombre:
            beneficiario_nombre = 'Sin especificar'

        total_unidades = 0
        retiros_creados = []
        advertencias = []

        beneficiario_user = User.objects.filter(username='sistema').first() or User.objects.filter(is_superuser=True).first()

        for item in items:
            producto_id = item.get('producto_id')
            try:
                cantidad = Decimal(str(item.get('cantidad', '0')))
            except Exception:
                continue
            
            if cantidad <= 0 or not producto_id:
                continue
                
            try:
                producto = Producto.objects.get(pk=producto_id, activo=True)
            except Producto.DoesNotExist:
                continue
                
            if cantidad > producto.stock:
                w = f'Stock insuficiente para {producto.nombre}. Disponible: {producto.stock}'
                advertencias.append(w)
                messages.warning(request, w)
                continue

            numero_retiro = RetiroDonacion.generar_numero()
            
            retiro = RetiroDonacion.objects.create(
                numero_retiro=numero_retiro,
                producto=producto,
                cantidad=cantidad,
                beneficiario=beneficiario_user,
                registrado_por=request.user,
                motivo=f"{motivo} - Beneficiario: {beneficiario_nombre}" if motivo else beneficiario_nombre,
            )

            _registrar_movimiento(producto, 'donacion', cantidad, request.user, retiro.id, f'Donación #{numero_retiro}')
            
            total_unidades += cantidad
            retiros_creados.append(f"{producto.nombre} x{cantidad}")

        if retiros_creados:
            _sincronizar_inventario_dia(ahora_servidor().date())

            msg = f"Donación registrada para {beneficiario_nombre}: "
            msg += ", ".join(retiros_creados[:3])
            if len(retiros_creados) > 3:
                msg += f" y {len(retiros_creados) - 3} más"
            if es_json:
                return JsonResponse({'ok': True, 'message': msg,
                                     'count': len(retiros_creados),
                                     'warnings': advertencias})
            messages.success(request, msg)
        else:
            if es_json:
                return JsonResponse({'ok': False,
                                     'error': 'No se pudieron registrar las donaciones.',
                                     'warnings': advertencias}, status=400)
            messages.error(request, 'No se pudieron registrar las donaciones.')

        return redirect('core:retiro_donacion_lista')

    return render(request, 'core/retiro_donacion_form.html', {
        'productos': productos,
    })


@requiere_admin
def retiro_donacion_eliminar(request, pk):
    retiro = get_object_or_404(RetiroDonacion, pk=pk)
    if request.method == 'POST':
        numero = retiro.numero_retiro
        producto = retiro.producto
        cantidad = retiro.cantidad

        producto.stock += cantidad
        producto.save()
        
        _sincronizar_inventario_dia(ahora_servidor().date())

        messages.success(request, f'Donación {numero} eliminada. Stock restaurado.')
        return redirect('core:retiro_donacion_lista')
    return render(request, 'core/retiro_donacion_confirmar.html', {'retiro': retiro})


@requiere_admin
def submayor_lista(request):
    productos = Producto.objects.filter(activo=True).select_related('categoria').order_by('nombre')
    return render(request, 'core/submayor_lista.html', {'productos': productos})


@requiere_admin
def submayor_detalle(request, producto_id):
    producto = get_object_or_404(Producto.objects.select_related('categoria'), pk=producto_id)
    
    fecha_inicio = request.GET.get('fecha_inicio')
    fecha_fin = request.GET.get('fecha_fin')
    
    hoy = ahora_servidor().date()
    if not fecha_inicio:
        fecha_inicio = (hoy - timedelta(days=30)).strftime('%Y-%m-%d')
    if not fecha_fin:
        fecha_fin = hoy.strftime('%Y-%m-%d')
    
    movimientos = MovimientoInventario.objects.filter(
        producto=producto,
        fecha__date__gte=fecha_inicio,
        fecha__date__lte=fecha_fin
    ).order_by('-fecha')

    historial = producto.historial_precios.filter(
        fecha__date__gte=fecha_inicio,
        fecha__date__lte=fecha_fin
    ).order_by('-fecha')

    context = {
        'producto': producto,
        'movimientos': movimientos,
        'historial': historial,
        'fecha_inicio': fecha_inicio,
        'fecha_fin': fecha_fin,
    }
    return render(request, 'core/submayor_detalle.html', context)


# ============================================================
# DEUDORES Y DEUDAS
# ============================================================

def _resumen_deuda(deuda):
    """Calcula abonado/saldo de una deuda (aprovecha abonos prefetcheados)."""
    abonado = sum((a.monto for a in deuda.abonos.all()), Decimal('0'))
    deuda.calc_abonado = abonado
    deuda.calc_saldo = deuda.monto - abonado
    deuda.calc_pagada = deuda.calc_saldo <= 0
    return deuda


def saldo_deudor(deudor):
    return sum((_resumen_deuda(d).calc_saldo for d in deudor.deudas.all()), Decimal('0'))


def _aplicar_abono_deudor(deudor, monto, metodo, nota, usuario):
    """Liquida: distribuye el pago entre las deudas pendientes (más antiguas primero)."""
    monto = Decimal(str(monto))
    if monto <= 0:
        raise ValueError('El monto debe ser mayor a 0.')
    deudas = list(Deuda.objects.filter(deudor=deudor).prefetch_related('abonos').order_by('fecha_registro', 'id'))
    for d in deudas:
        _resumen_deuda(d)
    saldo_total = sum((d.calc_saldo for d in deudas if d.calc_saldo > 0), Decimal('0'))
    if monto > saldo_total:
        raise ValueError(f'El monto supera el saldo pendiente (${saldo_total}).')
    aplicados = []
    restante = monto
    for d in deudas:
        if restante <= 0:
            break
        if d.calc_saldo <= 0:
            continue
        parte = min(d.calc_saldo, restante)
        AbonoDeuda.objects.create(
            deuda=d, monto=parte, metodo=metodo,
            nota=nota or '', registrada_por=usuario,
        )
        aplicados.append({'deuda': d, 'monto': parte})
        restante -= parte
    return aplicados


def _crear_deuda(deudor, tipo, usuario, monto=None, producto=None, cantidad=1, motivo='', fecha_pago=None, presentacion=None, presentacion_id=None):
    """Crea una deuda de dinero o de producto (descuenta stock y lo valoriza a precio de la PRESENTACIÓN).

    Presentaciones: un cartón de huevo no vale lo mismo que un huevo suelto.
    - cantidad: unidades DE LA PRESENTACIÓN (ej. 1 cartón).
    - cantidad_base = cantidad x factor (unidades base que salen del stock).
    - monto = cantidad x precio manual de la presentación.
    """
    from .models import PresentacionProducto

    def _fmt_cant(v):
        try:
            c = Decimal(str(v))
            s = format(c.quantize(Decimal('0.001')).normalize(), 'f')
            return s
        except Exception:
            return str(v)

    try:
        cantidad = Decimal(str(cantidad or 1))
    except Exception:
        cantidad = Decimal('1')
    cantidad = cantidad.quantize(Decimal('0.001'))
    if tipo == 'producto':
        if producto is None:
            raise ValueError('Seleccione el producto a entregar.')
        if cantidad <= 0:
            raise ValueError('Cantidad inválida.')
        # Resolver presentación: la elegida, si no la default del producto.
        pres = presentacion
        if pres is None and presentacion_id:
            try:
                pres = PresentacionProducto.objects.get(
                    pk=presentacion_id, producto=producto, activo=True)
            except PresentacionProducto.DoesNotExist:
                pres = None
        if pres is None:
            pres = producto.presentacion_default()
        factor = pres.factor if pres else Decimal('1')
        precio = pres.precio if pres else producto.precio_venta
        if not producto.permite_decimal and cantidad != cantidad.to_integral_value():
            raise ValueError(f'{producto.nombre} solo admite unidades enteras.')
        cantidad_base = (cantidad * factor).quantize(Decimal('0.001'))
        if cantidad_base <= 0:
            raise ValueError('Cantidad inválida.')
        if cantidad_base > producto.stock:
            raise ValueError(
                f'Stock insuficiente de {producto.nombre}. Disponible: {("%g" % float(producto.stock))} {producto.unidad_medida}')
        monto = (precio * cantidad).quantize(Decimal('0.01'))
        extra = (motivo or '').strip()
        pres_txt = pres.nombre if pres else 'Unidad'
        auto = f"{_fmt_cant(cantidad)} x {pres_txt} - {producto.nombre}"
        motivo = f"{auto} - {extra}" if extra else auto
    else:
        monto = Decimal(str(monto or 0))
        if monto <= 0:
            raise ValueError('El monto debe ser mayor a 0.')
        precio = Decimal('0')
        pres = None
        cantidad_base = Decimal('0')
        cantidad = Decimal('1')
    deuda = Deuda.objects.create(
        numero_deuda=Deuda.generar_numero(),
        deudor=deudor,
        tipo=tipo,
        producto=producto if tipo == 'producto' else None,
        presentacion=pres if tipo == 'producto' else None,
        cantidad=cantidad if tipo == 'producto' else 1,
        cantidad_base=cantidad_base if tipo == 'producto' else 0,
        precio_unitario=precio,
        monto=monto,
        motivo=(motivo or '').strip(),
        fecha_pago=fecha_pago,
        registrada_por=usuario,
    )
    if tipo == 'producto':
        _registrar_movimiento(
            producto, 'deuda', cantidad_base, usuario, deuda.id,
            f'Deuda #{deuda.numero_deuda} - {deudor.nombre_completo}'
        )
        _sincronizar_inventario_dia(ahora_servidor().date())
    return deuda


def _parse_fecha_pago(valor):
    valor = (valor or '').strip()
    if not valor:
        return None
    try:
        return timezone.datetime.strptime(valor, '%Y-%m-%d').date()
    except ValueError:
        return None


@login_required
def deuda_lista(request):
    q = request.GET.get('q', '').strip()
    pendientes_only = request.GET.get('pendientes') == '1'

    deudores = Deudor.objects.prefetch_related('deudas__abonos').order_by('nombre', 'apellido')
    if q:
        deudores = deudores.filter(
            Q(nombre__icontains=q) | Q(apellido__icontains=q) | Q(ci__icontains=q)
        )
    deudores = list(deudores)
    for d in deudores:
        d.calc_saldo = saldo_deudor(d)
        d.calc_pendientes = sum(1 for deuda in d.deudas.all() if _resumen_deuda(deuda).calc_saldo > 0)

    deudas = Deuda.objects.select_related('deudor', 'producto', 'presentacion').prefetch_related('abonos').order_by('-fecha_registro')
    if pendientes_only:
        deudas = [d for d in deudas if _resumen_deuda(d).calc_saldo > 0]
    else:
        deudas = [_resumen_deuda(d) for d in deudas]

    total_por_cobrar = sum((d.calc_saldo for d in Deuda.objects.prefetch_related('abonos').all() if _resumen_deuda(d).calc_saldo > 0), Decimal('0'))
    total_cobrado = AbonoDeuda.objects.aggregate(total=Sum('monto'))['total'] or Decimal('0')

    context = {
        'deudores': deudores,
        'deudas': deudas,
        'total_por_cobrar': total_por_cobrar,
        'total_cobrado': total_cobrado,
        'total_deudores': Deudor.objects.filter(activo=True).count(),
        'q': q,
        'pendientes_only': pendientes_only,
    }
    return render(request, 'core/deuda_lista.html', context)


@login_required
def deudor_crear(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        ci = request.POST.get('ci', '').strip() or None
        telefono = request.POST.get('telefono', '').strip()

        if not nombre:
            messages.error(request, 'El nombre es requerido.')
            return redirect('core:deudor_crear')
        if not ci:
            messages.error(request, 'La CI es requerida.')
            return redirect('core:deudor_crear')
        if Deudor.objects.filter(ci=ci).exists():
            messages.error(request, 'Ya existe un deudor con esa CI.')
            return redirect('core:deudor_crear')

        deudor = Deudor.objects.create(nombre=nombre, apellido=apellido, ci=ci, telefono=telefono)
        messages.success(request, f'Deudor {deudor.nombre_completo} registrado.')
        return redirect('core:deudor_detalle', pk=deudor.pk)

    return render(request, 'core/deudor_form.html', {'titulo': 'Registrar Deudor'})


@login_required
def deudor_editar(request, pk):
    deudor = get_object_or_404(Deudor, pk=pk)

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        ci = request.POST.get('ci', '').strip() or None
        telefono = request.POST.get('telefono', '').strip()

        if not nombre:
            messages.error(request, 'El nombre es requerido.')
            return redirect('core:deudor_editar', pk=pk)
        if not ci:
            messages.error(request, 'La CI es requerida.')
            return redirect('core:deudor_editar', pk=pk)
        if Deudor.objects.filter(ci=ci).exclude(pk=pk).exists():
            messages.error(request, 'Ya existe otro deudor con esa CI.')
            return redirect('core:deudor_editar', pk=pk)

        deudor.nombre = nombre
        deudor.apellido = apellido
        deudor.ci = ci
        deudor.telefono = telefono
        deudor.save()
        messages.success(request, 'Deudor actualizado.')
        return redirect('core:deudor_detalle', pk=pk)

    return render(request, 'core/deudor_form.html', {'titulo': 'Editar Deudor', 'deudor': deudor})


@login_required
def deudor_detalle(request, pk):
    deudor = get_object_or_404(Deudor.objects.prefetch_related('deudas__abonos', 'deudas__producto', 'deudas__presentacion'), pk=pk)
    deudas = sorted(deudor.deudas.all(), key=lambda d: d.fecha_registro, reverse=True)
    for d in deudas:
        _resumen_deuda(d)
    abonos = AbonoDeuda.objects.filter(deuda__deudor=deudor).select_related('deuda').order_by('-fecha')
    saldo = sum((d.calc_saldo for d in deudas), Decimal('0'))
    context = {
        'deudor': deudor,
        'deudas': deudas,
        'abonos': abonos,
        'saldo': saldo,
    }
    return render(request, 'core/deudor_detalle.html', context)


@login_required
def deudor_toggle(request, pk):
    deudor = get_object_or_404(Deudor, pk=pk)
    deudor.activo = not deudor.activo
    deudor.save()
    estado = 'activado' if deudor.activo else 'desactivado'
    messages.success(request, f'Deudor {estado}.')
    return redirect('core:deuda_lista')


@login_required
def deudor_abonar(request, pk):
    """Liquida saldo del deudor repartiendo el pago en las deudas más antiguas."""
    deudor = get_object_or_404(Deudor, pk=pk)
    if request.method == 'POST':
        try:
            aplicados = _aplicar_abono_deudor(
                deudor,
                request.POST.get('monto', '0'),
                request.POST.get('metodo', 'efectivo'),
                request.POST.get('nota', ''),
                request.user,
            )
            total = sum((a['monto'] for a in aplicados), Decimal('0'))
            messages.success(request, f'Abono de ${total} aplicado a {len(aplicados)} deuda(s) de {deudor.nombre_completo}.')
        except (ValueError, ArithmeticError) as e:
            messages.error(request, str(e))
    return redirect('core:deudor_detalle', pk=pk)


@login_required
def deudor_eliminar(request, pk):
    deudor = get_object_or_404(Deudor, pk=pk)
    if request.method == 'POST':
        if deudor.deudas.exists():
            messages.error(request, 'No se puede eliminar: el deudor tiene deudas registradas. Desactívelo en su lugar.')
            return redirect('core:deudor_detalle', pk=pk)
        nombre = deudor.nombre_completo
        deudor.delete()
        messages.success(request, f'Deudor {nombre} eliminado.')
        return redirect('core:deuda_lista')
    return render(request, 'core/deudor_confirmar_eliminar.html', {'deudor': deudor})


@login_required
def deuda_crear(request):
    if request.method == 'POST':
        try:
            from .models import PresentacionProducto
            deudor = get_object_or_404(Deudor, pk=request.POST.get('deudor'))
            tipo = request.POST.get('tipo', 'dinero')
            motivo_base = request.POST.get('motivo', '')
            fecha_pago = _parse_fecha_pago(request.POST.get('fecha_pago', ''))
            if tipo == 'producto':
                # Multiproducto: una deuda por línea (mismo patrón que donaciones).
                # Todo o nada: si una línea falla (stock, presentación), no se crea ninguna.
                try:
                    items = json.loads(request.POST.get('productos_data') or '[]')
                except (json.JSONDecodeError, TypeError):
                    raise ValueError('Datos de productos inválidos.')
                items = [it for it in items if it]
                if not items:
                    raise ValueError('Agregue al menos un producto a la deuda.')
                creadas = []
                with transaction.atomic():
                    for it in items:
                        producto = get_object_or_404(Producto, pk=it.get('producto_id'))
                        pres_id = it.get('presentacion_id') or None
                        if pres_id and not PresentacionProducto.objects.filter(
                                pk=pres_id, producto=producto, activo=True).exists():
                            raise ValueError(f'Presentación inválida para {producto.nombre}.')
                        deuda = _crear_deuda(
                            deudor=deudor,
                            tipo='producto',
                            usuario=request.user,
                            producto=producto,
                            cantidad=it.get('cantidad', 1),
                            motivo=motivo_base,
                            fecha_pago=fecha_pago,
                            presentacion_id=pres_id,
                        )
                        creadas.append(deuda)
                total = sum((d.monto for d in creadas), Decimal('0'))
                nums = ', '.join(d.numero_deuda for d in creadas[:3])
                if len(creadas) > 3:
                    nums += f' y {len(creadas) - 3} más'
                messages.success(
                    request,
                    f'{len(creadas)} deuda(s) de productos para {deudor.nombre_completo} '
                    f'(total ${total:.2f}): {nums}.'
                )
            else:
                deuda = _crear_deuda(
                    deudor=deudor,
                    tipo=tipo,
                    usuario=request.user,
                    monto=request.POST.get('monto', '0'),
                    motivo=motivo_base,
                    fecha_pago=fecha_pago,
                )
                messages.success(request, f'Deuda {deuda.numero_deuda} registrada para {deudor.nombre_completo} (${deuda.monto}).')
            return redirect('core:deudor_detalle', pk=deudor.pk)
        except ValueError as e:
            messages.error(request, str(e))
            return redirect('core:deuda_crear')

    deudores = Deudor.objects.filter(activo=True).order_by('nombre', 'apellido')
    productos = Producto.objects.filter(activo=True, visible_pos=True, stock__gt=0).prefetch_related('presentaciones').order_by('nombre')
    preselect = request.GET.get('deudor', '')
    return render(request, 'core/deuda_form.html', {
        'titulo': 'Registrar Deuda',
        'deudores': deudores,
        'productos': productos,
        'preselect': preselect,
    })


@login_required
def deuda_editar(request, pk):
    deuda = get_object_or_404(Deuda.objects.select_related('deudor', 'producto').prefetch_related('abonos'), pk=pk)
    _resumen_deuda(deuda)

    if request.method == 'POST':
        deuda.motivo = request.POST.get('motivo', '').strip()
        deuda.fecha_pago = _parse_fecha_pago(request.POST.get('fecha_pago', ''))
        if deuda.tipo == 'dinero' and deuda.calc_abonado <= 0:
            try:
                monto = Decimal(str(request.POST.get('monto', '0')))
                if monto <= 0:
                    raise ValueError('El monto debe ser mayor a 0.')
                deuda.monto = monto
            except (ValueError, ArithmeticError) as e:
                messages.error(request, str(e))
                return redirect('core:deuda_editar', pk=pk)
        deuda.save()
        messages.success(request, 'Deuda actualizada.')
        return redirect('core:deudor_detalle', pk=deuda.deudor.pk)

    return render(request, 'core/deuda_form.html', {
        'titulo': 'Editar Deuda',
        'deuda': deuda,
    })


@login_required
def deuda_abonar(request, pk):
    deuda = get_object_or_404(Deuda.objects.select_related('deudor').prefetch_related('abonos'), pk=pk)
    _resumen_deuda(deuda)

    if request.method == 'POST':
        try:
            monto = Decimal(str(request.POST.get('monto', '0')))
            metodo = request.POST.get('metodo', 'efectivo')
            nota = request.POST.get('nota', '').strip()
            if monto <= 0:
                raise ValueError('El monto debe ser mayor a 0.')
            if monto > deuda.calc_saldo:
                raise ValueError(f'El monto supera el saldo pendiente (${deuda.calc_saldo}).')
            AbonoDeuda.objects.create(
                deuda=deuda, monto=monto, metodo=metodo,
                nota=nota, registrada_por=request.user,
            )
            messages.success(request, f'Abono de ${monto} registrado.')
            return redirect('core:deudor_detalle', pk=deuda.deudor.pk)
        except (ValueError, ArithmeticError) as e:
            messages.error(request, str(e))
            return redirect('core:deuda_abonar', pk=pk)

    return render(request, 'core/deuda_abonar.html', {'deuda': deuda})


@login_required
def deuda_eliminar(request, pk):
    deuda = get_object_or_404(Deuda.objects.select_related('deudor'), pk=pk)
    if request.method == 'POST':
        if deuda.abonos.exists():
            messages.error(request, 'No se puede eliminar: la deuda tiene abonos registrados.')
            return redirect('core:deudor_detalle', pk=deuda.deudor.pk)
        numero = deuda.numero_deuda
        deudor_pk = deuda.deudor.pk
        deuda.delete()
        messages.success(request, f'Deuda {numero} eliminada.')
        return redirect('core:deudor_detalle', pk=deudor_pk)
    return render(request, 'core/deuda_confirmar_eliminar.html', {'deuda': deuda})


# ============================================================
# POS - DEUDORES Y DEUDAS (solo online)
# ============================================================

@login_required
def pos_deudores(request):
    q = request.GET.get('q', '').strip()
    deudores = Deudor.objects.filter(activo=True).prefetch_related('deudas__abonos').order_by('nombre', 'apellido')
    if q:
        deudores = deudores.filter(
            Q(nombre__icontains=q) | Q(apellido__icontains=q) | Q(ci__icontains=q)
        )[:30]
    else:
        deudores = deudores[:30]
    data = []
    for d in deudores:
        data.append({
            'id': d.id,
            'nombre': d.nombre,
            'apellido': d.apellido,
            'nombre_completo': d.nombre_completo,
            'ci': d.ci or '',
            'telefono': d.telefono or '',
            'saldo': str(saldo_deudor(d)),
        })
    return JsonResponse({'deudores': data})


@login_required
def pos_deudor_detalle(request, pk):
    deudor = get_object_or_404(Deudor.objects.prefetch_related('deudas__abonos', 'deudas__producto', 'deudas__presentacion'), pk=pk)
    deudas = sorted(deudor.deudas.all(), key=lambda d: (d.fecha_registro, d.id))
    items = []
    for d in deudas:
        _resumen_deuda(d)
        if d.calc_saldo <= 0:
            continue
        try:
            pres_nombre = d.presentacion.nombre if d.presentacion_id and d.presentacion else ''
        except Exception:
            pres_nombre = ''
        items.append({
            'id': d.id,
            'numero': d.numero_deuda,
            'tipo': d.tipo,
            'motivo': d.motivo_display,
            'presentacion': pres_nombre,
            'monto': str(d.monto),
            'abonado': str(d.calc_abonado),
            'saldo': str(d.calc_saldo),
            'fecha': d.fecha_registro.strftime('%d/%m/%Y'),
        })
    return JsonResponse({
        'id': deudor.id,
        'nombre_completo': deudor.nombre_completo,
        'ci': deudor.ci or '',
        'saldo': str(sum((Decimal(i['saldo']) for i in items), Decimal('0'))),
        'deudas': items,
    })


@login_required
@require_POST
def pos_deudor_crear(request):
    try:
        data = json.loads(request.body)
        nombre = (data.get('nombre') or '').strip()
        apellido = (data.get('apellido') or '').strip()
        ci = (data.get('ci') or '').strip()
        telefono = (data.get('telefono') or '').strip()
        if not nombre:
            return JsonResponse({'error': 'El nombre es requerido.'}, status=400)
        if not ci:
            return JsonResponse({'error': 'La CI es requerida.'}, status=400)
        if Deudor.objects.filter(ci=ci).exists():
            return JsonResponse({'error': 'Ya existe un deudor con esa CI.'}, status=400)
        deudor = Deudor.objects.create(nombre=nombre, apellido=apellido, ci=ci, telefono=telefono)
        return JsonResponse({
            'success': True,
            'id': deudor.id,
            'nombre_completo': deudor.nombre_completo,
            'ci': deudor.ci,
            'saldo': '0',
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def pos_deuda_crear(request):
    try:
        data = json.loads(request.body)
        deudor = get_object_or_404(Deudor, pk=data.get('deudor_id'))
        tipo = data.get('tipo', 'dinero')
        if tipo not in ('dinero', 'producto'):
            return JsonResponse({'error': 'Tipo de deuda inválido.'}, status=400)
        from .models import PresentacionProducto
        motivo_base = data.get('motivo', '')
        fecha_pago = _parse_fecha_pago(data.get('fecha_pago', ''))
        if tipo == 'producto':
            # Multiproducto: lista de líneas; compat con línea única anterior.
            raw_items = data.get('items')
            if raw_items:
                items = [it for it in raw_items if it]
            else:
                items = [{'producto_id': data.get('producto_id'),
                          'presentacion_id': data.get('presentacion_id'),
                          'cantidad': data.get('cantidad', 1)}]
            if not items:
                return JsonResponse({'error': 'Agregue al menos un producto.'}, status=400)
            # Pre-validación (sin escribir nada todavía).
            for it in items:
                producto = get_object_or_404(Producto, pk=it.get('producto_id'))
                pres_id = it.get('presentacion_id') or None
                if pres_id and not PresentacionProducto.objects.filter(
                        pk=pres_id, producto=producto, activo=True).exists():
                    return JsonResponse(
                        {'error': f'Presentación inválida para {producto.nombre}.'}, status=400)
            creadas = []
            with transaction.atomic():
                try:
                    for it in items:
                        producto = get_object_or_404(Producto, pk=it.get('producto_id'))
                        creadas.append(_crear_deuda(
                            deudor=deudor,
                            tipo='producto',
                            usuario=request.user,
                            producto=producto,
                            cantidad=it.get('cantidad', 1),
                            motivo=motivo_base,
                            fecha_pago=fecha_pago,
                            presentacion_id=it.get('presentacion_id') or None,
                        ))
                except ValueError as e:
                    transaction.set_rollback(True)
                    return JsonResponse({'error': str(e)}, status=400)
            total = sum((d.monto for d in creadas), Decimal('0'))
            deuda = creadas[0]
            extra_resp = {
                'numeros': [d.numero_deuda for d in creadas],
                'count': len(creadas),
                'monto': str(total),
            }
        else:
            try:
                deuda = _crear_deuda(
                    deudor=deudor,
                    tipo=tipo,
                    usuario=request.user,
                    monto=data.get('monto', '0'),
                    motivo=motivo_base,
                    fecha_pago=fecha_pago,
                )
            except ValueError as e:
                return JsonResponse({'error': str(e)}, status=400)
            extra_resp = {}
        resp = {
            'success': True,
            'numero': deuda.numero_deuda,
            'monto': str(deuda.monto if tipo == 'dinero' else total),
            'motivo': deuda.motivo_display,
            'saldo_deudor': str(saldo_deudor(deudor)),
        }
        resp.update(extra_resp)
        return JsonResponse(resp)
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
@require_POST
def pos_deuda_abonar(request):
    """Liquida: selecciona al deudor y reduce su saldo (reparte en las más antiguas)."""
    try:
        data = json.loads(request.body)
        deudor = get_object_or_404(Deudor, pk=data.get('deudor_id'))
        metodo = data.get('metodo', 'efectivo')
        nota = (data.get('nota') or '').strip()
        try:
            aplicados = _aplicar_abono_deudor(deudor, data.get('monto', '0'), metodo, nota, request.user)
        except ValueError as e:
            return JsonResponse({'error': str(e)}, status=400)
        return JsonResponse({
            'success': True,
            'aplicados': [{'numero': a['deuda'].numero_deuda, 'monto': str(a['monto'])} for a in aplicados],
            'saldo_deudor': str(saldo_deudor(deudor)),
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


@requiere_admin
def ajuste_inventario(request):
    MOTIVOS = [
        ('inventario_fisico', 'Inventario Físico'),
        ('mercancia_danada', 'Mercancía Dañada'),
        ('mercancia_perdida', 'Mercancía Perdida'),
        ('ajuste_error', 'Ajuste por Error'),
        ('otro', 'Otro'),
    ]
    
    if request.method == 'POST':
        producto_id = request.POST.get('producto')
        motivo = request.POST.get('motivo')
        observacion = request.POST.get('observacion', '')

        producto = get_object_or_404(Producto, pk=producto_id)
        try:
            nuevo_stock = Decimal(str(request.POST.get('nuevo_stock', '')).replace(',', '.')).quantize(Decimal('0.001'))
        except Exception:
            messages.error(request, 'Nuevo stock inválido.')
            return redirect('core:ajuste_inventario')
        if nuevo_stock < 0:
            messages.error(request, 'El stock no puede ser negativo.')
            return redirect('core:ajuste_inventario')
        # Unidades enteras salvo peso (kg/lb) que admite decimales.
        if producto.unidad_medida not in ('kg', 'lb') and nuevo_stock != nuevo_stock.to_integral_value():
            messages.error(request, f'{producto.nombre} solo admite unidades enteras.')
            return redirect('core:ajuste_inventario')
        stock_anterior = producto.stock
        diferencia = nuevo_stock - stock_anterior
        
        producto.stock = nuevo_stock
        producto.save()
        
        MovimientoInventario.objects.create(
            producto=producto,
            tipo='ajuste',
            cantidad=diferencia,
            stock_anterior=stock_anterior,
            stock_nuevo=nuevo_stock,
            descripcion=f"{dict(MOTIVOS).get(motivo, motivo)} - {observacion}",
            usuario=request.user,
        )
        
        hoy = ahora_servidor().date()
        inventario_hoy = InventarioDiario.objects.filter(
            fecha=hoy,
            producto=producto
        ).first()
        
        if inventario_hoy:
            if not inventario_hoy.cerrado:
                # El ajuste mueve el vivo hoy: desplazar el inicial en la
                # misma diferencia para no romper ini+ent-ven-don-deuda=fin.
                # No tocar días pasados.
                inventario_hoy.stock_inicial = inventario_hoy.stock_inicial + diferencia
                inventario_hoy.calcular()
                inventario_hoy.save()
        else:
            InventarioDiario.objects.create(
                fecha=hoy,
                producto=producto,
                stock_inicial=nuevo_stock,
                entradas=0,
                ventas=0,
                stock_final=nuevo_stock,
            )
        
        messages.success(request, f'Stock de {producto.nombre} ajustado de {fmt_cantidad_unidad(stock_anterior, producto.unidad_medida)} a {fmt_cantidad_unidad(nuevo_stock, producto.unidad_medida)}.')
        return redirect('core:ajuste_inventario')
    
    productos = Producto.objects.filter(activo=True).order_by('categoria__nombre', 'nombre')
    ajustes = MovimientoInventario.objects.filter(tipo='ajuste').select_related('producto', 'usuario')[:50]

    return render(request, 'core/ajuste_inventario.html', {
        'productos': productos,
        'ajustes': ajustes,
    })


# ============================================================
# MOSTRADOR DEL CLIENTE (pantalla en tiempo real del POS)
# ============================================================
# Sin login ni token: /mostrador/ siempre funciona (TV del local).
# Sin websockets ni Redis: el POS empuja el carrito por POST y el
# mostrador lo lee por polling cada ~2.5 s. Funciona offline en LAN.

MOSTRADOR_PANTALLAS = [1, 2, 3, 4, 5]


def _mostrador_pantalla(request, data=None):
    try:
        pantalla = int((data or {}).get('pantalla', request.GET.get('pantalla', '1')))
    except (TypeError, ValueError):
        pantalla = 1
    return pantalla if pantalla in MOSTRADOR_PANTALLAS else 1


def mostrador_display(request):
    """Pantalla pública del cliente (TV). Siempre activa, sin login."""
    return render(request, 'core/mostrador.html', {
        'pantalla': _mostrador_pantalla(request),
    })


def catalogo(request):
    """Catálogo público de la tienda (vitrina web). Sin login ni compra.

    Agrupa productos activos por categoría. Solo muestra precio de venta
    y disponibilidad (nunca stock exacto ni costos).
    """
    from .models import Categoria

    categorias = list(
        Categoria.objects.filter(productos__activo=True, productos__visible_pos=True).distinct().order_by('nombre'))
    productos = list(
        Producto.objects.filter(activo=True, visible_pos=True).select_related('categoria')
        .prefetch_related('presentaciones').order_by('nombre'))
    sin_cat = [p for p in productos if p.categoria_id is None]

    def _item(p):
        pres = p.presentacion_default()
        if pres is not None:
            precio = pres.precio
            etiqueta = pres.nombre
        else:
            precio = p.precio_venta
            etiqueta = dict(getattr(p, 'UNIDADES_MEDIDA', [])).get(
                p.unidad_medida, '') or 'Unidad'
        return {
            'codigo': p.codigo,
            'nombre': p.nombre,
            'imagen': p.imagen_url,
            'precio': precio,
            'etiqueta': etiqueta,
            'disponible': (p.stock or 0) > 0,
        }

    grupos = []
    for cat in categorias:
        items = [_item(p) for p in productos if p.categoria_id == cat.id]
        if items:
            grupos.append({'categoria': cat.nombre, 'items': items})
    if sin_cat:
        grupos.append({'categoria': 'Otros', 'items': [_item(p) for p in sin_cat]})
    return render(request, 'core/catalogo.html', {
        'grupos': grupos,
        'total': len(productos),
    })


def _store_stock_map_suma():
    """Suma de `AlmacenStock.cantidad` por producto (vitrina /store).

    Solo almacenes activos. Si un producto tiene filas propias por
    almacén, solo esas suman; la fila legacy (`almacen=NULL`) cuenta
    únicamente cuando no hay ninguna propia (evita doble conteo tras
    migrar a multi-almacén).
    """
    filas = (AlmacenStock.objects
             .filter(Q(almacen__isnull=True) | Q(almacen__activo=True))
             .values('producto_id', 'almacen_id')
             .annotate(total=Sum('cantidad')))
    por_prod = {}
    for f in filas:
        por_prod.setdefault(f['producto_id'], []).append(f)
    m = {}
    for pid, entries in por_prod.items():
        propias = [e for e in entries if e['almacen_id'] is not None]
        base = propias if propias else entries
        m[pid] = sum((e['total'] for e in base), Decimal('0'))
    return m


def _store_items():
    """Items de la vitrina /store desde la misma fuente que el POS.

    En `multi_pos` el stock es la suma de `AlmacenStock` (se ignora
    `visible_pos`, igual que el POS); en el resto de modos es
    `Producto.stock` con `activo + visible_pos`. Se listan también los
    agotados. Límite 2000, ordenados por nombre.
    """
    if modo_actual() == 'multi_pos':
        mapa = _store_stock_map_suma()
        productos = list(Producto.objects.filter(
            activo=True).select_related('categoria')
            .prefetch_related('presentaciones').order_by('nombre')[:2000])
        for p in productos:
            # Solo memoria (NO guardar): el stock vive en AlmacenStock.
            p.stock = mapa.get(p.id, Decimal('0'))
    else:
        productos = list(Producto.objects.filter(
            activo=True, visible_pos=True).select_related('categoria')
            .prefetch_related('presentaciones').order_by('nombre')[:2000])
    items = []
    for p in productos:
        # En memoria sobre el prefetch (sin N+1): equivale a
        # presentacion_default() = activas ordenadas por -es_default, factor.
        candidatas = [pr for pr in p.presentaciones.all() if pr.activo]
        candidatas.sort(key=lambda pr: (not pr.es_default, pr.factor))
        pres = candidatas[0] if candidatas else None
        if pres is not None:
            precio = pres.precio
            etiqueta = pres.nombre
        else:
            precio = p.precio_venta
            etiqueta = dict(getattr(p, 'UNIDADES_MEDIDA', [])).get(
                p.unidad_medida, '') or 'Unidad'
        stock = p.stock if p.stock is not None else Decimal('0')
        items.append({
            'id': p.id,
            'codigo': p.codigo,
            'nombre': p.nombre,
            'categoria': p.categoria.nombre if p.categoria else '',
            'categoria_id': p.categoria_id,
            'imagen': p.imagen_url,
            'precio': precio,
            'etiqueta': etiqueta,
            'stock': stock,
            'stock_fmt': fmt_cantidad_unidad(stock, p.unidad_medida),
        'disponible': stock > 0,
        'pocas': Decimal('0') < stock <= (p.stock_minimo or Decimal('0')),
        'es_nuevo': p.es_nuevo,
        })
    # Visibilidad de tienda por rama: una categoría oculta oculta a sus hijas.
    cats = {c.id: c for c in Categoria.objects.all()}

    def _rama_visible(cid):
        """(visible, top_id) siguiendo padres; top_id None = sin categoría."""
        if cid is None:
            return True, None
        top = None
        actual = cats.get(cid)
        while actual is not None:
            if not actual.visible_store:
                return False, None
            top = actual.id
            actual = cats.get(actual.padre_id)
        if top is None:
            return False, None
        return True, top

    visibles = []
    for it in items:
        ok, top = _rama_visible(it['categoria_id'])
        if not ok:
            continue
        it['padre_top'] = top
        visibles.append(it)
    return visibles


def _store_nombres_categoria():
    """Mapa id→nombre de categorías (para el árbol padre/hijas)."""
    return dict(Categoria.objects.values_list('id', 'nombre'))


def store(request):
    """Portada pública /store: hero, tendencias y categorías destacadas.

    Sin login ni compra. Los productos por categoría viven en sus
    propias páginas (`store_categoria`) y en el buscador
    (`store_buscar`): el landing no lista el catálogo completo.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Solo GET.'}, status=405)
    if request.GET.get('solo') == '1':
        from django.urls import reverse as _reverse
        return redirect(f"{_reverse('core:store_buscar')}?solo=1")
    items = _store_items()
    # Árbol para destacadas: padres visibles con sus hijas.
    nombres = _store_nombres_categoria()
    arbol = _store_arbol(_store_grupos(items), nombres)
    # Vitrina estilo Algomio: tendencias (4 primeros disponibles) y
    # destacadas (4 padres con más productos) para el hero/secciones.
    disponibles = [it for it in items if it.get('disponible')]
    tendencias = (disponibles or items)[:4]
    for it in tendencias:
        # Página de la categoría que agrupa al producto (padre o la hoja).
        it['pagina_id'] = it.get('padre_top') or it.get('categoria_id')
    destacadas = sorted(arbol, key=lambda a: a['total'], reverse=True)[:4]
    return render(request, 'core/store.html', {
        'arbol': arbol,
        'nav': _nav_categorias(),
        'total': len(items),
        'disponibles': len(disponibles),
        'tendencias': tendencias,
        'destacadas': destacadas,
        'actualizado': timezone.now().strftime('%H:%M:%S'),
    })


def store_buscar(request):
    """Buscador público /store/buscar/: resultados por texto y/o solo disponibles."""
    if request.method != 'GET':
        return JsonResponse({'error': 'Solo GET.'}, status=405)
    q = (request.GET.get('q') or '').strip()
    solo = request.GET.get('solo') == '1'
    items = _store_items()
    if solo:
        items = [it for it in items if it.get('disponible')]
    if q:
        qn = _norm_sin_tildes(q.lower())
        items = [it for it in items
                 if qn in _norm_sin_tildes((it['nombre'] or '').lower())
                 or qn in _norm_sin_tildes((it['codigo'] or '').lower())]
    return render(request, 'core/store_buscar.html', {
        'q': q,
        'solo': solo,
        'grupos': _store_grupos(items),
        'nav': _nav_categorias(),
        'total': len(items),
        'actualizado': timezone.now().strftime('%H:%M:%S'),
    })


def _store_grupos(items):
    """Agrupa items de vitrina por categoría hoja (con id y clave del padre)."""
    grupos = []
    por_hoja = {}
    for it in items:
        key = it['categoria_id'] or 'otros'
        if key not in por_hoja:
            por_hoja[key] = {
                'categoria': it['categoria'] or 'Otros',
                'items': [],
                'padre_top': it['padre_top'],
                'hoja_id': it['categoria_id'],
            }
            grupos.append(por_hoja[key])
        por_hoja[key]['items'].append(it)
    grupos.sort(key=lambda g: (g['categoria'] == 'Otros', g['categoria'].lower()))
    for g in grupos:
        top = g['padre_top']
        g['padre_key'] = ('p%d' % top) if top is not None else 'otros'
    return grupos


def _nav_categorias():
    """Árbol recursivo de padres visibles para el menú en cascada.

    Cada nodo: id, nombre, icono e hijas (mismo formato). Incluye
    categorías aunque estén vacías (su página muestra el aviso).
    Una hija de padre oculto no se lista.
    """
    cats = list(Categoria.objects.select_related('padre').order_by('nombre'))
    visibles = set()
    for c in cats:
        actual = c
        ok = True
        while actual is not None:
            if not actual.visible_store:
                ok = False
                break
            actual = actual.padre
        if ok:
            visibles.add(c.id)
    hijos_map = {}
    for c in cats:
        if c.id in visibles and c.padre_id is not None:
            hijos_map.setdefault(c.padre_id, []).append(c)

    def _nodo(c):
        return {
            'id': c.id, 'nombre': c.nombre,
            'icono': (c.icono or '').strip(),
            'hijas': [_nodo(h) for h in hijos_map.get(c.id, [])
                      if h.id in visibles],
        }

    return [_nodo(c) for c in cats
            if c.id in visibles and c.padre_id is None]


def _store_arbol(grupos, nombres):
    """Árbol padre→hijas con ids para navegar a páginas por categoría."""
    arbol = []
    por_top = {}
    for g in grupos:
        top = g['padre_top']
        if top is None:
            clave, nombre, tid = 'otros', 'Otros', None
        else:
            clave, nombre, tid = ('p%d' % top), nombres.get(top, ''), top
        if clave not in por_top:
            por_top[clave] = {'key': clave, 'id': tid, 'nombre': nombre, 'total': 0, 'hijas': []}
            arbol.append(por_top[clave])
        por_top[clave]['total'] += len(g['items'])
        if top is not None and g['categoria'] != nombre:
            por_top[clave]['hijas'].append({
                'id': g.get('hoja_id'), 'nombre': g['categoria'], 'total': len(g['items'])})
    arbol.sort(key=lambda a: (a['key'] == 'otros', a['nombre'].lower()))
    return arbol


def store_categoria(request, pk):
    """Página pública de una categoría con selector lateral de hijas.

    - Con hijas: lista las hijas (cards) + sus productos directos; los
      productos se ven al elegir una hija en el lateral.
    - Hoja: sus productos + lateral con las hermanas.
    Sin login ni compra. Rama oculta → 404.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Solo GET.'}, status=405)
    cat = get_object_or_404(Categoria, pk=pk)
    # Rama visible + migas de pan subiendo por los padres.
    migas = []
    actual = cat
    while actual is not None:
        if not actual.visible_store:
            from django.http import Http404
            raise Http404('Categoría no disponible en la tienda.')
        migas.append(actual)
        actual = actual.padre
    migas.reverse()
    # Subárbol: la categoría + todos sus descendientes.
    ids = {cat.id}
    pendientes = list(cat.hijas.all())
    while pendientes:
        h = pendientes.pop()
        if h.id not in ids:
            ids.add(h.id)
            pendientes.extend(list(h.hijas.all()))
    todos = _store_items()
    hijas = sorted(
        [h for h in cat.hijas.all() if h.visible_store],
        key=lambda h: h.nombre.lower())
    es_padre = bool(hijas)
    if es_padre:
        # Cards de hijas + productos del subárbol agrupados por hija.
        items = [it for it in todos if it['categoria_id'] in ids]
        # Conteo del subárbol por hija (para sus cards).
        conteo = {}
        for it in todos:
            cid = it['categoria_id']
            if cid in ids:
                conteo[cid] = conteo.get(cid, 0) + 1

        def _cuenta_sub(hoja):
            total = conteo.get(hoja.id, 0)
            for n in hoja.hijas.all():
                total += _cuenta_sub(n)
            return total

        hijas_info = [{
            'id': h.id, 'nombre': h.nombre,
            'icono': (h.icono or '').strip(),
            'descripcion': h.descripcion or '',
            'total': _cuenta_sub(h),
        } for h in hijas]
        lateral = [{
            'id': h.id, 'nombre': h.nombre,
            'icono': (h.icono or '').strip(), 'actual': False,
        } for h in hijas]
    else:
        items = [it for it in todos if it['categoria_id'] in ids]
        hijas_info = []
        if cat.padre_id:
            hermanas = sorted(
                [h for h in cat.padre.hijas.all() if h.visible_store],
                key=lambda h: h.nombre.lower())
            lateral = [{
                'id': h.id, 'nombre': h.nombre,
                'icono': (h.icono or '').strip(),
                'actual': h.id == cat.id,
            } for h in hermanas]
        else:
            lateral = [{
                'id': a['id'], 'nombre': a['nombre'], 'icono': a['icono'],
                'actual': a['id'] == cat.id,
            } for a in _nav_categorias()]
    grupos = _store_grupos(items)
    # Selector del header: mismo árbol global de /store/.
    nombres = _store_nombres_categoria()
    arbol_global = _store_arbol(_store_grupos(todos), nombres)
    return render(request, 'core/store_categoria.html', {
        'categoria': cat,
        'migas': migas,
        'hijas': hijas,
        'hijas_info': hijas_info,
        'es_padre': es_padre,
        'lateral': lateral,
        'grupos': grupos,
        'arbol': arbol_global,
        'nav': _nav_categorias(),
        'total': len(items),
        'solo': request.GET.get('solo') == '1',
        'actualizado': timezone.now().strftime('%H:%M:%S'),
    })


def store_api_estado(request):
    """JSON público con precios y existencias para el polling de /store/.

    Solo GET, sin login. Nunca expone costos ni mínimos de stock.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Solo GET.'}, status=405)
    items = _store_items()
    return JsonResponse({
        'productos': [{
            'id': it['id'],
            'precio': str(it['precio']),
            'stock': str(it['stock']),
            'stock_fmt': it['stock_fmt'],
            'disponible': it['disponible'],
            'pocas': it['pocas'],
        } for it in items],
        'actualizado': timezone.now().strftime('%H:%M:%S'),
    })


def _store_detalle(pk):
    """Detalle público de un producto para el modal de /store.

    Reutiliza `_store_items` (misma visibilidad y stock que la
    vitrina). Devuelve None si no existe o está oculto de la tienda.
    Nunca expone costos ni mínimos.
    """
    try:
        pid = int(pk)
    except (TypeError, ValueError):
        return None
    base = next((it for it in _store_items() if it['id'] == pid), None)
    if base is None:
        return None
    p = Producto.objects.filter(pk=pid).select_related(
        'categoria__padre').prefetch_related('presentaciones').first()
    if p is None:
        return None
    pres = [{
        'nombre': pr.nombre,
        'precio': str(pr.precio),
    } for pr in p.presentaciones.all() if pr.activo]
    cat = p.categoria
    from django.urls import reverse as _reverse
    return {
        'id': base['id'],
        'codigo': base['codigo'],
        'nombre': base['nombre'],
        'descripcion': p.descripcion or '',
        'categoria': base['categoria'],
        'categoria_id': base['categoria_id'],
        'categoria_padre': cat.padre.nombre if cat and cat.padre else '',
        'categoria_url': _reverse('core:store_categoria', args=[base['categoria_id']]) if base['categoria_id'] else _reverse('core:store'),
        'imagen': base['imagen'],
        'precio': str(base['precio']),
        'etiqueta': base['etiqueta'],
        'presentaciones': pres,
        'stock_fmt': base['stock_fmt'],
        'disponible': base['disponible'],
        'pocas': base['pocas'],
        'es_nuevo': base['es_nuevo'],
    }


def store_producto_detalle(request, pk):
    """JSON público con el detalle de un producto para el modal.

    Solo GET, sin login. Nunca expone costos ni mínimos de stock.
    """
    if request.method != 'GET':
        return JsonResponse({'error': 'Solo GET.'}, status=405)
    det = _store_detalle(pk)
    if det is None:
        return JsonResponse({'error': 'No encontrado.'}, status=404)
    return JsonResponse(det)


def mostrador_estado(request):
    """JSON que el mostrador consulta por polling. Público."""
    pantalla = _mostrador_pantalla(request)
    est = MostradorEstado.objects.filter(pantalla=pantalla).first()
    if est is None:
        return JsonResponse({'items': [], 'total': '0.00', 'mensaje': 'vacio'})
    items = est.items()
    # Estado rancio (cajero dejó el carrito hace >15 min): mostrar vacío.
    from datetime import timedelta as _td
    if est.mensaje == 'activo' and (timezone.now() - est.actualizado) > _td(minutes=15):
        return JsonResponse({'items': [], 'total': '0.00', 'mensaje': 'vacio'})
    return JsonResponse({
        'items': items,
        'total': str(est.total),
        'mensaje': est.mensaje,
        'actualizado': est.actualizado.strftime('%H:%M:%S'),
    })


@login_required
@require_POST
def pos_mostrador_empujar(request):
    """El POS empuja el carrito actual para una pantalla (llamado en cada renderCart)."""
    try:
        data = json.loads(request.body)
    except Exception:
        return JsonResponse({'error': 'JSON inválido.'}, status=400)
    try:
        pantalla = int(data.get('pantalla', 1))
    except (TypeError, ValueError):
        pantalla = 1
    if pantalla not in MOSTRADOR_PANTALLAS:
        pantalla = 1
    items = data.get('items', [])
    if not isinstance(items, list):
        items = []
    # Saneizar: solo campos de exhibición, máx 50 líneas.
    limpios = []
    for it in items[:50]:
        if not isinstance(it, dict):
            continue
        try:
            limpios.append({
                'nombre': str(it.get('nombre', ''))[:120],
                'presentacion': str(it.get('presentacion', ''))[:80],
                'cantidad': str(it.get('cantidad', ''))[:20],
                'precio': str(it.get('precio', '0'))[:20],
                'subtotal': str(it.get('subtotal', '0'))[:20],
                'imagen': str(it.get('imagen', ''))[:500],
            })
        except Exception:
            continue
    try:
        total = Decimal(str(data.get('total', '0')))
    except Exception:
        total = Decimal('0')
    cajero = request.user.get_full_name() or request.user.username
    MostradorEstado.objects.update_or_create(
        pantalla=pantalla,
        defaults={'items_json': json.dumps(limpios), 'total': total,
                  'mensaje': 'activo' if limpios else 'vacio',
                  'cajero_nombre': cajero},
    )
    return JsonResponse({'success': True})


@login_required
@require_POST
def pos_mostrador_limpiar(request):
    """Avisa al mostrador: venta completada (muestra gracias) o carrito cancelado."""
    try:
        data = json.loads(request.body)
    except Exception:
        data = {}
    try:
        pantalla = int(data.get('pantalla', 1))
    except (TypeError, ValueError):
        pantalla = 1
    if pantalla not in MOSTRADOR_PANTALLAS:
        pantalla = 1
    mensaje = data.get('mensaje', 'vacio')
    if mensaje not in ('vacio', 'completado'):
        mensaje = 'vacio'
    MostradorEstado.objects.update_or_create(
        pantalla=pantalla,
        defaults={'items_json': '[]', 'total': Decimal('0'), 'mensaje': mensaje,
                  'cajero_nombre': request.user.get_full_name() or request.user.username},
    )
    return JsonResponse({'success': True})


# ============================================================
# PANEL DEL VENDEDOR + ARQUEO DE TURNO + CONTEO CIEGO
# ============================================================

def _empleado_de(request):
    """Empleado del usuario actual o None."""
    try:
        return request.user.empleado
    except Empleado.DoesNotExist:
        return None


def _resumen_turno(turno):
    """Esperado del turno por método (ventas − gastos del turno).

    Efectivo esperado = Σ monto_recibido − Σ cambio − gastos en efectivo.
    Transferencia esperada = Σ monto_transferencia − gastos por transferencia.
    """
    agg = turno.ventas.filter(cancelada=False).aggregate(
        ef=Sum('monto_recibido'), tr=Sum('monto_transferencia'),
        cb=Sum('cambio'), tot=Sum('total'), n=Count('id'),
    )
    ef = (agg['ef'] or Decimal('0')) - (agg['cb'] or Decimal('0'))
    tr = agg['tr'] or Decimal('0')
    gagg = turno.gastos.aggregate(
        ef=Sum('cantidad_efectivo'), tr=Sum('cantidad_transferencia'))
    gef = gagg['ef'] or Decimal('0')
    gtr = gagg['tr'] or Decimal('0')
    return {
        'num_ventas': agg['n'] or 0,
        'total_ventas': agg['tot'] or Decimal('0'),
        'ventas_efectivo': ef,
        'ventas_transferencia': tr,
        'gastos_efectivo': gef,
        'gastos_transferencia': gtr,
        'esperado_efectivo': ef - gef,
        'esperado_transferencia': tr - gtr,
    }


@login_required
def mi_panel(request):
    """Panel del vendedor: ventas del día + accesos a arqueo y conteo.

    Los admin caen a su dashboard (el panel es para el vendedor).
    """
    try:
        if request.user.perfil.es_admin:
            return redirect('core:dashboard')
    except PerfilUsuario.DoesNotExist:
        return redirect('core:dashboard')
    empleado = _empleado_de(request)
    if empleado is None:
        messages.warning(request, 'Tu usuario no tiene ficha de empleado.')
        return redirect('core:pos')
    turno = empleado.turno_abierto
    hoy = ahora_servidor().date()
    ventas_hoy = Venta.objects.filter(
        cajero=request.user, fecha_venta__date=hoy, cancelada=False
    ).order_by('-fecha_venta')[:20]
    tot_hoy = Venta.objects.filter(
        cajero=request.user, fecha_venta__date=hoy, cancelada=False
    ).aggregate(t=Sum('total'), n=Count('id'))
    resumen = _resumen_turno(turno) if turno else None
    arqueo = getattr(turno, 'arqueo', None) if turno else None
    conteos = turno.conteos.all()[:10] if turno else []
    return render(request, 'core/mi_panel.html', {
        'empleado': empleado,
        'turno': turno,
        'resumen': resumen,
        'arqueo': arqueo,
        'conteos': conteos,
        'ventas_hoy': ventas_hoy,
        'total_hoy': tot_hoy['t'] or 0,
        'num_hoy': tot_hoy['n'] or 0,
    })


@login_required
def arqueo(request):
    """Arqueo del turno abierto en 2 pasos.

    Paso 1: fondo inicial + foto del esperado por método.
    Paso 2: el cajero declara lo contado (ayudante por denominaciones);
        se muestra faltante/sobrante en grande y se exige motivo si descuadra.
    """
    empleado = _empleado_de(request)
    if empleado is None:
        messages.warning(request, 'Tu usuario no tiene ficha de empleado.')
        return redirect('core:mi_panel')
    turno = empleado.turno_abierto
    if turno is None:
        messages.warning(request, 'No tienes turno abierto.')
        return redirect('core:mi_panel')
    resumen = _resumen_turno(turno)
    arqueo, _ = ArqueoTurno.objects.get_or_create(turno=turno)
    if arqueo.estado == 'confirmado':
        messages.info(request, 'Este arqueo ya fue confirmado.')
        return redirect('core:mi_panel')

    paso = request.GET.get('paso', '1')
    if arqueo.estado == 'declarado':
        # Ya declarado: mostrar resumen en espera de confirmación.
        return render(request, 'core/arqueo.html', {
            'empleado': empleado, 'turno': turno, 'resumen': resumen,
            'arqueo': arqueo, 'paso': 'espera',
            'denominaciones': DENOMINACIONES_CUP,
        })

    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'recontar':
            # Volver a contar el dinero: se anula la declaración y se vuelve
            # al paso 2 con el fondo y el esperado intactos. Solo antes de
            # que el admin confirme (después, el turno ya está cerrado).
            if arqueo.estado != 'declarado' or not turno.abierto:
                messages.warning(request, 'Ya no se puede recontar: el arqueo fue confirmado.')
                return redirect('core:mi_panel')
            arqueo.contado_efectivo = Decimal('0')
            arqueo.contado_transferencia = Decimal('0')
            arqueo.detalle_json = '{}'
            arqueo.observacion = ''
            arqueo.estado = 'borrador'
            arqueo.declarado_por = None
            arqueo.declarado_at = None
            arqueo.save()
            messages.info(request, 'Declaración anulada. Vuelve a contar el dinero.')
            return redirect('/arqueo/?paso=2')
        if action == 'fondo':
            try:
                fondo = Decimal(str(request.POST.get('fondo_inicial', '0') or '0'))
                if fondo < 0:
                    raise ValueError('El fondo no puede ser negativo.')
            except Exception:
                messages.error(request, 'Fondo inicial inválido.')
                fondo = None
            if fondo is not None:
                arqueo.fondo_inicial = fondo
                arqueo.esperado_efectivo = resumen['esperado_efectivo'] + fondo
                arqueo.esperado_transferencia = resumen['esperado_transferencia']
                arqueo.paso1_listo = True
                arqueo.save()
                messages.success(request, 'Paso 1 guardado. Ahora cuenta el efectivo.')
                return redirect('/arqueo/?paso=2')
        elif action == 'declarar':
            import json as _json
            detalle = {}
            total_ef = Decimal('0')
            for key, _lbl in DENOMINACIONES_CUP:
                try:
                    qty = int(request.POST.get('denom_' + key, '0') or '0')
                except (TypeError, ValueError):
                    qty = 0
                if qty < 0:
                    qty = 0
                if qty:
                    detalle[key] = qty
                    total_ef += DENOMINACIONES_CUP_VALOR[key] * qty
            try:
                cont_tr = Decimal(str(request.POST.get('contado_transferencia', '0') or '0'))
                if cont_tr < 0:
                    raise ValueError('negativo')
            except Exception:
                messages.error(request, 'Transferencia contada inválida.')
                return render(request, 'core/arqueo.html', {
                    'empleado': empleado, 'turno': turno, 'resumen': resumen,
                    'arqueo': arqueo, 'paso': '2',
                    'denominaciones': DENOMINACIONES_CUP,
                })
            observacion = (request.POST.get('observacion', '') or '').strip()
            # Foto fresca del esperado al declarar.
            arqueo.esperado_efectivo = resumen['esperado_efectivo'] + arqueo.fondo_inicial
            arqueo.esperado_transferencia = resumen['esperado_transferencia']
            arqueo.contado_efectivo = total_ef
            arqueo.contado_transferencia = cont_tr
            arqueo.detalle_json = _json.dumps(detalle)
            arqueo.observacion = observacion
            if arqueo.diferencia_total != 0 and not observacion:
                arqueo.save()
                messages.error(
                    request,
                    'Hay diferencia de $%.2f: escribe el motivo para poder declarar.'
                    % arqueo.diferencia_total)
                return render(request, 'core/arqueo.html', {
                    'empleado': empleado, 'turno': turno, 'resumen': resumen,
                    'arqueo': arqueo, 'paso': '2',
                    'denominaciones': DENOMINACIONES_CUP,
                })
            arqueo.estado = 'declarado'
            arqueo.declarado_por = request.user
            arqueo.declarado_at = timezone.now()
            arqueo.save()
            messages.success(request, 'Arqueo declarado. Queda en espera de confirmación del admin.')
            return redirect('core:mi_panel')

    if paso == '2':
        if not arqueo.paso1_listo:
            messages.warning(request, 'Primero completa el paso 1 (fondo inicial).')
            paso = '1'
    return render(request, 'core/arqueo.html', {
        'empleado': empleado, 'turno': turno, 'resumen': resumen,
        'arqueo': arqueo, 'paso': paso,
        'denominaciones': DENOMINACIONES_CUP,
    })


@requiere_admin
@require_POST
def arqueo_confirmar(request, pk):
    """El admin confirma el arqueo declarado ELIGIENDO qué hacer con la
    diferencia, y cierra el turno.

    Decisiones:
    - aceptar: se acepta la diferencia y se cierra (queda en el motivo).
    - gasto: el faltante se registra como gasto de caja (visible en IPB).
    - descontar: queda anotado como pendiente a descontar al empleado.
    - sobrante_caja: el sobrante queda en caja.
    """
    turno = get_object_or_404(Turno, pk=pk)
    arqueo = getattr(turno, 'arqueo', None)
    if arqueo is None or arqueo.estado != 'declarado':
        messages.warning(request, 'Ese turno no tiene arqueo declarado.')
        return redirect('core:empleado_turnos', pk=turno.empleado_id)
    decision = request.POST.get('decision', '')
    nota = (request.POST.get('decision_nota', '') or '').strip()
    validas = [c[0] for c in ArqueoTurno.DECISIONES if c[0]]
    if decision not in validas:
        messages.error(request, 'Elige qué hacer con la diferencia antes de confirmar.')
        return redirect('core:revisar_turno', pk=turno.pk)
    # Sin decisión en el físico tampoco se cierra (se revisa antes de
    # crear el gasto o confirmar, para no dejar medias tintas).
    bloqueos_fisico = _bloqueos_cierre_turno(turno, incluir_arqueo=False)
    if bloqueos_fisico:
        messages.error(request, 'No se puede cerrar: ' + ' '.join(bloqueos_fisico))
        return redirect('core:revisar_turno', pk=turno.pk)
    dif = arqueo.diferencia_total
    if decision == 'gasto':
        if dif >= 0:
            messages.error(request, 'Esa decisión es solo para faltante (diferencia negativa).')
            return redirect('core:revisar_turno', pk=turno.pk)
        monto = -dif
        Gasto.objects.create(
            numero_gasto=Gasto.generar_numero(),
            cajero=turno.empleado.user,
            turno=turno,
            cantidad_efectivo=monto,
            cantidad_transferencia=Decimal('0'),
            categoria='caja',
            descripcion=f'Faltante de caja · Arqueo turno #{turno.pk}' + (f' · {nota}' if nota else ''),
        )
    if decision == 'descontar' and not nota:
        messages.error(request, 'Si lo descuentas al empleado, anota el acuerdo en la nota.')
        return redirect('core:revisar_turno', pk=turno.pk)
    arqueo.decision = decision
    arqueo.decision_nota = nota
    arqueo.estado = 'confirmado'
    arqueo.confirmado_por = request.user
    arqueo.confirmado_at = timezone.now()
    arqueo.save()
    if turno.abierto:
        turno.cerrar()
    messages.success(
        request,
        'Arqueo confirmado (%s) y turno cerrado. Diferencia: $%.2f.'
        % (arqueo.get_decision_display(), dif))
    return redirect('core:empleado_turnos', pk=turno.empleado_id)


@requiere_admin
@require_POST
def arqueo_recontar(request, pk):
    """El admin pide reconteo de dinero: anula la declaración del arqueo
    y el empleado vuelve al paso 2 (fondo y esperado intactos).

    Se puede pedir tantas veces como haga falta mientras el turno siga
    abierto (después de confirmado ya no: el turno está cerrado).
    """
    turno = get_object_or_404(Turno, pk=pk)
    arqueo = getattr(turno, 'arqueo', None)
    if not turno.abierto:
        messages.warning(request, 'El turno ya está cerrado: no se puede pedir reconteo.')
        return redirect('core:revisar_turno', pk=turno.pk)
    if arqueo is None or arqueo.estado != 'declarado':
        messages.warning(request, 'Solo se puede pedir reconteo de un arqueo declarado.')
        return redirect('core:revisar_turno', pk=turno.pk)
    arqueo.contado_efectivo = Decimal('0')
    arqueo.contado_transferencia = Decimal('0')
    arqueo.detalle_json = '{}'
    arqueo.observacion = ''
    arqueo.estado = 'borrador'
    arqueo.declarado_por = None
    arqueo.declarado_at = None
    arqueo.save()
    messages.warning(request, 'Reconteo de dinero pedido: la declaración quedó anulada.')
    return redirect('core:revisar_turno', pk=turno.pk)


def _bloqueos_cierre_turno(turno, incluir_arqueo=True):
    """Motivos por los que el turno NO se puede cerrar todavía.

    Regla: sin decisión del admin en el dinero (arqueo) Y en el físico
    (conteos), el turno no se cierra.
    """
    motivos = []
    if incluir_arqueo:
        arqueo = getattr(turno, 'arqueo', None)
        if arqueo is None or arqueo.estado == 'borrador':
            motivos.append('Falta declarar el arqueo de caja.')
    conteos = list(turno.conteos.all())
    if not conteos:
        motivos.append('Falta entregar el conteo físico de productos.')
    else:
        if any(c.estado != 'cerrado' for c in conteos):
            motivos.append('Hay conteos físicos aún abiertos.')
        if any(c.estado == 'cerrado' and not c.decision for c in conteos):
            motivos.append('Hay conteos cerrados sin decisión del admin.')
    return motivos


@requiere_admin
@require_POST
def turno_cerrar(request, pk):
    empleado = get_object_or_404(Empleado, pk=pk)
    turno = empleado.turno_abierto
    if turno:
        # Cierre directo solo si TODO ya está decidido; si no, a Revisar.
        bloqueos = _bloqueos_cierre_turno(turno)
        arqueo = getattr(turno, 'arqueo', None)
        if bloqueos:
            messages.error(
                request,
                'No se puede cerrar: ' + ' '.join(bloqueos))
            return redirect('core:revisar_turno', pk=turno.pk)
        if arqueo is not None and arqueo.estado == 'declarado':
            # Ya pasó por Revisar con su decisión (sin bloqueos): confirmar.
            arqueo.estado = 'confirmado'
            if not arqueo.decision:
                arqueo.decision = 'aceptar'
            arqueo.confirmado_por = request.user
            arqueo.confirmado_at = timezone.now()
            arqueo.save()
            turno.cerrar()
            messages.success(
                request,
                'Arqueo declarado confirmado al cerrar. Diferencia: $%.2f. Ventas: %s - Total: $%s'
                % (arqueo.diferencia_total, turno.num_ventas, turno.total_ventas))
        else:
            turno.cerrar()
            messages.success(request, f'Turno cerrado para {empleado}. Ventas: {turno.num_ventas} - Total: ${turno.total_ventas}.')
    else:
        messages.warning(request, f'{empleado} no tiene turno abierto.')
    return redirect('core:empleado_lista')


def _conteo_permitido(request, conteo):
    """El conteo lo ve el dueño del turno o un admin."""
    try:
        if request.user.perfil.es_admin:
            return True
    except PerfilUsuario.DoesNotExist:
        return True
    return conteo.turno.empleado.user_id == request.user.id


@login_required
def conteo_lista(request):
    """Conteos ciegos del turno abierto + crear uno nuevo."""
    empleado = _empleado_de(request)
    try:
        es_admin = request.user.perfil.es_admin
    except PerfilUsuario.DoesNotExist:
        es_admin = True
    if empleado is None and not es_admin:
        messages.warning(request, 'Tu usuario no tiene ficha de empleado.')
        return redirect('core:mi_panel')
    turno = empleado.turno_abierto if empleado else None
    if turno is None and not es_admin:
        messages.warning(request, 'No tienes turno abierto.')
        return redirect('core:mi_panel')
    if request.method == 'POST' and turno is not None:
        if turno.conteos.filter(estado='abierto').exists():
            messages.warning(request, 'Ya tienes un conteo abierto en este turno.')
        else:
            conteo = ConteoCiego.objects.create(turno=turno, creado_por=request.user)
            messages.success(request, f'Conteo #{conteo.pk} iniciado. Anota sin mirar el sistema.')
            return redirect('core:conteo_contar', pk=conteo.pk)
    conteos = turno.conteos.all() if turno else ConteoCiego.objects.none()
    return render(request, 'core/conteo_lista.html', {
        'empleado': empleado, 'turno': turno, 'conteos': conteos,
    })


@login_required
def conteo_contar(request, pk):
    """Anotar cantidades A CIEGAS (la plantilla nunca muestra el stock)."""
    conteo = get_object_or_404(ConteoCiego, pk=pk)
    if not _conteo_permitido(request, conteo):
        messages.error(request, 'No tienes permiso para ver ese conteo.')
        return redirect('core:mi_panel')
    if conteo.estado != 'abierto':
        return redirect('core:conteo_comparar', pk=conteo.pk)
    productos = Producto.objects.filter(activo=True, visible_pos=True).select_related('categoria').order_by('categoria__nombre', 'nombre')
    categorias = Categoria.objects.filter(productos__activo=True, productos__visible_pos=True).distinct().order_by('nombre')
    actuales = {l.producto_id: l.cantidad for l in conteo.lineas.all()}
    if request.method == 'POST':
        for p in productos:
            raw = request.POST.get('cant_%d' % p.pk, '')
            if raw is None or str(raw).strip() == '':
                continue
            try:
                from decimal import ROUND_HALF_UP as _RHU
                val = Decimal(str(raw).replace(',', '.'))
                if val < 0:
                    raise ValueError('negativo')
                if not p.permite_decimal:
                    val = val.to_integral_value(rounding=_RHU)
                else:
                    val = val.quantize(Decimal('0.001'))
            except Exception:
                messages.error(request, f'Cantidad inválida para {p.nombre}.')
                return render(request, 'core/conteo_contar.html', {
                    'conteo': conteo, 'productos': productos, 'actuales': actuales,
                    'categorias': categorias,
                })
            ConteoCiegoLinea.objects.update_or_create(
                conteo=conteo, producto=p, defaults={'cantidad': val})
        messages.success(request, 'Conteo guardado. Puedes seguir o cerrar para comparar.')
        return redirect('core:conteo_contar', pk=conteo.pk)
    return render(request, 'core/conteo_contar.html', {
        'conteo': conteo, 'productos': productos, 'actuales': actuales,
        'categorias': categorias,
    })


@login_required
@require_POST
def conteo_autosave(request, pk):
    """Autoguardado incremental del conteo ciego (opción C: cola offline).

    Acepta JSON: {"lineas": {"<producto_id>": "<cantidad>"}}
    o una sola línea: {"producto_id": 12, "cantidad": "1.5"}.
    - '' (vacío) = borra la línea (el input quedó vacío).
    - Valida igual que conteo_contar (no negativos, enteros si no admite decimal).
    Devuelve {"ok": true, "guardados": N, "errores": {...}, "eliminados": M}.
    Si el conteo ya está cerrado devuelve ok=False para que el JS avise.
    """
    from decimal import ROUND_HALF_UP as _RHU
    conteo = get_object_or_404(ConteoCiego, pk=pk)
    if not _conteo_permitido(request, conteo):
        return JsonResponse({'ok': False, 'error': 'Sin permiso.'}, status=403)
    if conteo.estado != 'abierto':
        return JsonResponse({'ok': False, 'error': 'El conteo ya está cerrado.'}, status=400)
    try:
        payload = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        payload = dict(request.POST)
    lineas = {}
    if isinstance(payload, dict) and 'lineas' in payload and isinstance(payload['lineas'], dict):
        lineas = dict(payload['lineas'])
    elif isinstance(payload, dict) and 'producto_id' in payload:
        lineas = {str(payload.get('producto_id')): payload.get('cantidad', '')}
    else:
        # Fallback: formato formulario cant_<id>=valor
        for k, v in (payload.items() if isinstance(payload, dict) else []):
            if str(k).startswith('cant_'):
                lineas[str(k)[5:]] = v
    if not lineas:
        return JsonResponse({'ok': False, 'error': 'Nada para guardar.'}, status=400)
    # Limita el tamaño del lote para no saturar la conexión inestable.
    if len(lineas) > 200:
        return JsonResponse({'ok': False, 'error': 'Lote muy grande.'}, status=400)
    try:
        pids = [int(pid) for pid in lineas.keys()]
    except Exception:
        return JsonResponse({'ok': False, 'error': 'IDs de producto inválidos.'}, status=400)
    productos = {p.pk: p for p in Producto.objects.filter(pk__in=pids, activo=True, visible_pos=True)}
    guardados = 0
    eliminados = 0
    errores = {}
    with transaction.atomic():
        for pid_str, raw in lineas.items():
            try:
                pid = int(pid_str)
            except Exception:
                errores[str(pid_str)] = 'ID inválido.'
                continue
            p = productos.get(pid)
            if p is None:
                errores[str(pid_str)] = 'Producto no existe o inactivo.'
                continue
            s = '' if raw is None else str(raw).strip()
            if s == '':
                ConteoCiegoLinea.objects.filter(conteo=conteo, producto_id=pid).delete()
                eliminados += 1
                continue
            try:
                val = Decimal(s.replace(',', '.'))
                if val < 0:
                    raise ValueError('negativo')
                if not p.permite_decimal:
                    val = val.to_integral_value(rounding=_RHU)
                else:
                    val = val.quantize(Decimal('0.001'))
            except Exception:
                errores[str(pid_str)] = 'Cantidad inválida.'
                continue
            ConteoCiegoLinea.objects.update_or_create(
                conteo=conteo, producto=p, defaults={'cantidad': val})
            guardados += 1
    return JsonResponse({
        'ok': True, 'guardados': guardados,
        'eliminados': eliminados, 'errores': errores,
    })


@login_required
@require_POST
def conteo_cerrar(request, pk):
    """Cierra el conteo y congela el stock del sistema por producto."""
    conteo = get_object_or_404(ConteoCiego, pk=pk)
    if not _conteo_permitido(request, conteo):
        messages.error(request, 'No tienes permiso para cerrar ese conteo.')
        return redirect('core:mi_panel')
    if conteo.estado != 'abierto':
        return redirect('core:conteo_comparar', pk=conteo.pk)
    # Productos sin línea quedan en 0 contado.
    vistos = set(conteo.lineas.values_list('producto_id', flat=True))
    for p in Producto.objects.filter(activo=True, visible_pos=True):
        linea, _ = ConteoCiegoLinea.objects.get_or_create(
            conteo=conteo, producto=p, defaults={'cantidad': Decimal('0')})
        linea.stock_sistema = p.stock
        linea.save(update_fields=['stock_sistema'])
    conteo.estado = 'cerrado'
    conteo.cerrado_por = request.user
    conteo.fecha_cierre = timezone.now()
    conteo.save()
    messages.success(
        request,
        f'Conteo #{conteo.pk} cerrado: {conteo.num_diferencias} producto(s) con diferencia.')
    return redirect('core:conteo_comparar', pk=conteo.pk)


@login_required
def conteo_comparar(request, pk):
    """Comparación producto por producto: sistema vs contado.

    Si el conteo sigue abierto, solo el admin puede espiarlo
    (el dueño debe cerrarlo primero para no romper lo "ciego").
    """
    conteo = get_object_or_404(
        ConteoCiego.objects.select_related('turno__empleado__user'), pk=pk)
    if not _conteo_permitido(request, conteo):
        messages.error(request, 'No tienes permiso para ver ese conteo.')
        return redirect('core:mi_panel')
    if conteo.estado != 'cerrado':
        try:
            es_admin = request.user.perfil.es_admin
        except PerfilUsuario.DoesNotExist:
            es_admin = True
        if not es_admin:
            messages.warning(request, 'Cierra el conteo para ver la comparación.')
            return redirect('core:conteo_contar', pk=conteo.pk)
    lineas = conteo.lineas.select_related('producto').order_by('producto__nombre')
    return render(request, 'core/conteo_comparar.html', {
        'conteo': conteo, 'lineas': lineas,
    })


# ============================================================
# REVISIÓN ADMIN: ARQUEOS + CONTEOS (qué hacer con las diferencias)
# ============================================================

@requiere_admin
def arqueos_admin(request):
    """Sección del admin: turnos abiertos con su arqueo/conteos (pendientes)
    e historial de turnos ya cerrados con su decisión."""
    # Spec §5 multi-POS: filtro ?pos= por punto_venta del turno (cada POS
    # opera su caja, turnos y cierres independientes). Fuera de multi-POS
    # se ignora. Sin cambios de template (filtro por URL).
    pos_actual, puntos_venta = _resolver_pos_filtro(request)
    abiertos = Turno.objects.filter(abierto=True).select_related(
        'empleado__user', 'punto_venta').prefetch_related(
        'conteos', 'ventas').order_by('-fecha_apertura')
    historial_qs = Turno.objects.filter(abierto=False).select_related(
        'empleado__user', 'punto_venta').order_by('-fecha_cierre')
    if pos_actual is not None:
        abiertos = abiertos.filter(punto_venta=pos_actual)
        historial_qs = historial_qs.filter(punto_venta=pos_actual)
    pendientes = []
    for t in abiertos:
        pendientes.append({
            'turno': t,
            'resumen': _resumen_turno(t),
            'arqueo': getattr(t, 'arqueo', None),
            'conteos_abiertos': t.conteos.filter(estado='abierto').count(),
            'conteos_cerrados': t.conteos.filter(estado='cerrado'),
        })
    historial = historial_qs[:20]
    return render(request, 'core/arqueos_admin.html', {
        'pendientes': pendientes,
        'historial': historial,
        'es_multi_pos': modo_actual() == 'multi_pos',
        'puntos_venta': puntos_venta,
        'pos_actual': pos_actual,
    })


@requiere_admin
def revisar_turno(request, pk):
    """Revisión conjunta del turno: dinero (arqueo) + físico (conteos).

    Aquí el admin ve lo declarado por el empleado, elige qué hacer con
    cada diferencia y confirma: eso cierra el turno.
    """
    turno = get_object_or_404(
        Turno.objects.select_related('empleado__user'), pk=pk)
    resumen = _resumen_turno(turno)
    arqueo = getattr(turno, 'arqueo', None)
    conteos = turno.conteos.prefetch_related('lineas__producto').all()
    bloqueos = _bloqueos_cierre_turno(turno) if turno.abierto else []
    bloqueos_fisico = _bloqueos_cierre_turno(turno, incluir_arqueo=False) if turno.abierto else []
    return render(request, 'core/revisar_turno.html', {
        'turno': turno,
        'empleado': turno.empleado,
        'resumen': resumen,
        'arqueo': arqueo,
        'conteos': conteos,
        'decisiones_arqueo': [c for c in ArqueoTurno.DECISIONES if c[0]],
        'bloqueos': bloqueos,
        'bloqueos_fisico': bloqueos_fisico,
    })


def _aplicar_ajuste_producto(producto, nuevo_stock, descripcion, usuario):
    """Lleva el stock del sistema a lo contado (criterio de FINAL).

    El conteo se hace al cierre sin más ventas: lo contado ES el stock
    final. Se mueve el vivo y la ficha de hoy mantiene su identidad
    (final = inicial + entradas − ventas − don − deuda) desplazando el
    inicial en la misma diferencia. Los días anteriores no se tocan.
    """
    stock_anterior = producto.stock
    diferencia = nuevo_stock - stock_anterior
    producto.stock = nuevo_stock
    producto.save()
    MovimientoInventario.objects.create(
        producto=producto,
        tipo='ajuste',
        cantidad=diferencia,
        stock_anterior=stock_anterior,
        stock_nuevo=nuevo_stock,
        descripcion=descripcion,
        usuario=usuario,
    )
    hoy = ahora_servidor().date()
    inv = InventarioDiario.objects.filter(fecha=hoy, producto=producto).first()
    if inv:
        if not inv.cerrado:
            inv.stock_inicial = inv.stock_inicial + diferencia
            inv.calcular()
            inv.save()
    else:
        InventarioDiario.objects.create(
            fecha=hoy, producto=producto, stock_inicial=nuevo_stock,
            entradas=0, ventas=0, stock_final=nuevo_stock)


@requiere_admin
@require_POST
def conteo_decidir(request, pk):
    """Decisión del admin sobre un conteo cerrado:

    - ajustar: el sistema se lleva a lo contado (movimientos de ajuste).
    - recontar: se reabre a ciegas para que el empleado cuente de nuevo.
      Se puede pedir tantas veces como haga falta: al reabrir se limpia
      la decisión para que la ronda nueva vuelva a ser decidible.
    - aceptar: se deja constancia sin mover el stock.
    Las decisiones ajustar/aceptar son terminales (no se aplican dos veces).
    """
    conteo = get_object_or_404(
        ConteoCiego.objects.select_related('turno__empleado__user'), pk=pk)
    accion = request.POST.get('accion', '')
    nota = (request.POST.get('decision_nota', '') or '').strip()
    if accion not in ('ajustar', 'recontar', 'aceptar'):
        messages.error(request, 'Acción inválida.')
        return redirect('core:revisar_turno', pk=conteo.turno_id)
    if conteo.estado != 'cerrado':
        messages.error(request, 'Solo se decide sobre un conteo cerrado.')
        return redirect('core:revisar_turno', pk=conteo.turno_id)
    if accion in ('ajustar', 'aceptar') and conteo.decision in ('ajustado', 'aceptado'):
        messages.warning(request, 'Ese conteo ya tiene decisión aplicada.')
        return redirect('core:revisar_turno', pk=conteo.turno_id)
    if accion == 'ajustar':
        n = 0
        for l in conteo.lineas.select_related('producto').all():
            if l.diferencia not in (None, 0):
                _aplicar_ajuste_producto(
                    l.producto, l.cantidad,
                    f'Ajuste por conteo ciego #{conteo.pk} (contado {l.cantidad}, sistema {l.stock_sistema})',
                    request.user)
                n += 1
        conteo.decision = 'ajustado'
        conteo.decision_nota = nota
        conteo.decidido_por = request.user
        conteo.decidido_at = timezone.now()
        conteo.save()
        messages.success(request, f'Sistema llevado a lo contado en {n} producto(s).')
    elif accion == 'recontar':
        conteo.estado = 'abierto'
        conteo.fecha_cierre = None
        conteo.lineas.all().update(stock_sistema=None)
        # Ronda nueva: se limpia la decisión para poder volver a decidir
        # (ajustar, recontar o aceptar) cuando el empleado cierre de nuevo.
        conteo.decision = ''
        conteo.decision_nota = nota
        conteo.decidido_por = request.user
        conteo.decidido_at = timezone.now()
        conteo.save()
        messages.warning(request, f'Conteo #{conteo.pk} reabierto a ciegas para reconteo.')
    else:
        conteo.decision = 'aceptado'
        conteo.decision_nota = nota
        conteo.decidido_por = request.user
        conteo.decidido_at = timezone.now()
        conteo.save()
        messages.info(request, f'Conteo #{conteo.pk} aceptado sin mover el stock.')
    return redirect('core:revisar_turno', pk=conteo.turno_id)
