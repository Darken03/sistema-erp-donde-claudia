# SDD ledger — plan: docs/superpowers/plans/2026-10-13-store.md

Pre-flight: Task 1 produce `_store_items` (grupos/total/actualizado + data-id + claves id/precio/stock/stock_fmt/disponible/pocas), Task 2 consume ese contexto, Task 3 consume el API `{productos, actualizado}`. Nombres de URLs `core:store` / `core:store_api` consistentes en los 3 tasks. Sin conflictos.
Ruling: se implementa en el workspace actual (rama master) sin worktree aislado — el usuario pidió implementar en el sistema y el harness es Windows/PowerShell sin scripts sdd ejecutables; costo si erro: mezclar cambios con master (mitigado con commits por task).

Task 1: complete (tests: python manage.py test core.tests_store -v 1 ? 3/3 pass; suite core ? 95/95 pass)
Task 1: Ruling: template minimo provisional para el contrato GREEN de Task 1 — Task 2 lo reemplaza con el diseno completo; costo si erro: ninguno (sobrescrito en Task 2).
Task 2: complete (tests: core.tests_store 4/4 pass; template store.html con tokens DESIGN.MD, filtros cliente, fallback noimg).
Task 3: Ruling: el test de payload paso en verde a la primera porque el contrato ya quedo implementado en Task 1 — se conserva como pin de regresion (caso lb 3.5) y lo nuevo (JS polling) se verifico vivo: /store/ 200 ~147KB con datos reales, /store/api/estado/ 200 con stock exacto sin costos, node --check del JS limpio.
Task 3: complete (tests: core.tests_store 5/5 pass).
Final: fixed suma incluye almacen inactivo — test_store_api_multi_ignora_almacen_inactivo RED→GREEN, suite 102/102.
Final: fixed N+1 presentacion_default por producto — test_store_api_sin_n_mas_1_presentaciones RED→GREEN (4 queries→1), suite 102/102.
Final: fixed agregacion en Python sin filtro — absorbido en _store_stock_map_suma con values+Sum y filtro activo, suite 102/102.
Final: fixed fetch con URL relativa hardcodeada — test_store_js_usa_url_absoluta_api RED→GREEN, suite 102/102.
Final: fixed huecos de test (proveedor, legacy, inactivo en multi) — nuevos tests RED→GREEN donde aplicaba, suite 102/102.
Final: minor (deferred): store() responde JsonResponse en non-GET en vez de HttpResponseNotAllowed.
Final: minor (deferred): clave pocas difiere del spec (pocas_unidades); plan/tests/JS usan pocas de forma consistente.
Final: minor (deferred): aviso offline no conserva el ultimo HH:MM:SS.
Final: minor (deferred): categoria real llamada Otros se fusiona con sin-categoria.
Final: minor (deferred): SIMBOLO sin escapejs (campo de admin, 5 chars).
Final: minor (deferred): logo hero sin segundo onerror si webp y png fallan.
