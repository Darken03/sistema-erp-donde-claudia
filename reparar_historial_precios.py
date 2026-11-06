#!/usr/bin/env python3
"""Repara la auditoría de precios faltante (Frised 530->540, Ritz 520->540, y resto).

Problema: `Producto.precio_venta` / `Presentacion.precio` se editaron a mano
sin crear `HistorialPrecio`, y el IPB viejo mostraba el precio actual.
El fix de `core/views.py` ya muestra el PU histórico del día desde
`DetalleVenta`; este script solo rellena `HistorialPrecio` donde falte.

Seguro: NO toca stock, ventas, caja ni IPB. Solo crea filas de
`HistorialPrecio`. Idempotente (no duplica antes->después iguales).

Uso en PythonAnywhere (Linux):
    python3 reparar_historial_precios.py                # dry-run, no escribe
    python3 reparar_historial_precios.py --apply        # escribe lo faltante
    python3 reparar_historial_precios.py --apply --producto "Refresco Ritz"

Uso en Windows local:
    python reparar_historial_precios.py --apply

Opciones:
    --apply          escribe en BD (por defecto solo informa)
    --producto NOMBRE  limita a un producto (icontains)
    --desde YYYY-MM-DD / --hasta YYYY-MM-DD  ventana de ventas a analizar
"""
import argparse
import os
import sys
from collections import defaultdict
from datetime import datetime
from decimal import Decimal

# Hace el script portable: se ubica solo junto a manage.py,
# tanto en Windows (C:\...) como en PythonAnywhere (/home/...).
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "system_erp.settings")

import django  # noqa: E402

django.setup()

from django.db.models import Sum  # noqa: E402
from core.models import DetalleVenta, HistorialPrecio, Producto  # noqa: E402


def parse_args():
    p = argparse.ArgumentParser(description="Backfill de HistorialPrecio desde DetalleVenta.")
    p.add_argument("--apply", action="store_true", help="Escribe en BD (sin esto: dry-run).")
    p.add_argument("--producto", default="", help="Filtra por nombre (icontains).")
    p.add_argument("--desde", default="", help="YYYY-MM-DD (incluido).")
    p.add_argument("--hasta", default="", help="YYYY-MM-DD (incluido).")
    return p.parse_args()


def pu_dominante_por_dia(desde=None, hasta=None, nombre_like=""):
    qs = DetalleVenta.objects.filter(venta__cancelada=False)
    if nombre_like:
        qs = qs.filter(producto__nombre__icontains=nombre_like)
    if desde:
        qs = qs.filter(venta__fecha_venta__date__gte=desde)
    if hasta:
        qs = qs.filter(venta__fecha_venta__date__lte=hasta)
    rows = qs.values("producto_id", "venta__fecha_venta__date", "precio_unitario").annotate(
        cant=Sum("cantidad")
    )
    best = {}
    for r in rows:
        key = (r["producto_id"], r["venta__fecha_venta__date"])
        try:
            c = Decimal(str(r["cant"] or 0))
            pu = Decimal(str(r["precio_unitario"] or 0))
        except Exception:
            continue
        if key not in best or c > best[key][1]:
            best[key] = (pu, c)
    por_prod = defaultdict(list)
    for (pid, dia), (pu, _c) in best.items():
        por_prod[pid].append((dia, pu))
    for pid in por_prod:
        por_prod[pid].sort()
    return por_prod


def cambios_detectados(por_prod):
    out = []
    for pid, pares in por_prod.items():
        prev = None
        for dia, pu in pares:
            if prev is not None and pu != prev[1]:
                out.append({"producto_id": pid, "desde_dia": prev[0],
                            "pu_antes": prev[1], "pu_despues": pu, "dia_cambio": dia})
            prev = (dia, pu)
    return out


def historial_existe(pid, antes, despues):
    return HistorialPrecio.objects.filter(
        producto_id=pid,
        precio_venta_antes=antes,
        precio_venta_despues=despues,
    ).exists()


def main():
    args = parse_args()
    desde = datetime.strptime(args.desde, "%Y-%m-%d").date() if args.desde else None
    hasta = datetime.strptime(args.hasta, "%Y-%m-%d").date() if args.hasta else None
    por_prod = pu_dominante_por_dia(desde, hasta, args.producto)
    cambios = cambios_detectados(por_prod)
    print(f"Productos con ventas: {len(por_prod)} | cambios de PU detectados: {len(cambios)}")
    creados = 0
    omitidos = 0
    for c in sorted(cambios, key=lambda x: (x['producto_id'], x['dia_cambio'])):
        prod = Producto.objects.filter(pk=c["producto_id"]).first()
        nombre = prod.nombre if prod else f"id={c['producto_id']}"
        antes, despues = c["pu_antes"], c["pu_despues"]
        ya = historial_existe(c["producto_id"], antes, despues)
        marca = "YA-EXISTE" if ya else ("CREAR" if args.apply else "FALTA")
        print(f"[{marca}] {nombre}: {antes} -> {despues} (cambio visto el {c['dia_cambio']})")
        if ya:
            omitidos += 1
            continue
        if not args.apply:
            continue
        compra = prod.precio_compra if prod else Decimal("0")
        HistorialPrecio.objects.create(
            producto_id=c["producto_id"],
            precio_compra_antes=compra, precio_compra_despues=compra,
            precio_venta_antes=antes, precio_venta_despues=despues,
            accion="edicion_manual",
            motivo=f"Reparación automática: PU {antes}->{despues} detectado en ventas del {c['dia_cambio']}",
            usuario=None,
        )
        creados += 1
    print(f"---\nOmitidos (ya existían): {omitidos} | Creados: {creados}"
          + (" (dry-run: nada escrito, usa --apply)" if not args.apply else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
