# Validación funcional del UAT

Recorrido autenticado y E2E de la macroiteración V1.4 sobre el UAT de São Paulo, con datos ficticios, y su limpieza. Se usó el 12/11/2026, con el resultado en [`docs/ESTADO_PROYECTO.md`](../../../docs/ESTADO_PROYECTO.md), sección B.

**Escribe en el UAT:** cada ejecución necesita autorización explícita, y la limpieza es un paso aparte, también autorizado.

## Piezas

| Archivo | Qué hace |
|---|---|
| [`validar_uat.ps1`](validar_uat.ps1) | Corre los tres pasos en orden y guarda las salidas. Pide las contraseñas sin eco |
| [`../migracion_sp/probar_entornos.py`](../migracion_sp/probar_entornos.py) | Paso 1, solo lectura: inicio de sesión, aislamiento de tokens entre Oregón y São Paulo, catálogos, Inicio, Taller, cero Órdenes y stock |
| [`../migracion_sp/medir_api.py`](../migracion_sp/medir_api.py) | Paso 2, solo lectura: lecturas autenticadas con sus tiempos |
| [`probar_macro_v14.py`](probar_macro_v14.py) | Paso 3, **escribe**: 6 escenarios, 67 comprobaciones con las cuatro cuentas |
| [`probar_macro_integral.py`](probar_macro_integral.py) | **Escribe**, macroiteración integral: DC12 inactiva (ABI-42), permisos configurables, desperdicio y devolución, compra con recepciones parciales e idempotencia, stock sin lote, catálogos operativos, identidad por IMEI, garantías (check-in corregido con motivo, garantía RMA vigente, reclamo rechazado con un trabajo en 0 días y su continuación paga) y comunicaciones (intento y confirmación manual). 9 escenarios; en el UAT el 16/11/2026, 68 de 68. Reutiliza la conexión, las sesiones y las guardas de `probar_macro_v14.py`. Deja inactivo el «Proveedor Ficticio E2E» (no admite borrado) |
| [`probar_ux_recepcion.py`](probar_ux_recepcion.py) | **Escribe**, iteración de UX de Recepción: alta con trabajo inicial y texto único sin IMEI (un alta fallida no crea nada), comprobante de ingreso, configuración de medios de pago, recargos repartidos entre los trabajos con copia histórica del porcentaje y comprobante de cobro sin línea de recargo, devoluciones parciales, sucesivas y totales con su proporción de recargo, cancelaciones y WhatsApp. 7 escenarios; en local, 43 de 43. Cambia el recargo de Transferencia a 3 % y lo restaura a 2 % al terminar (también si falla) |
| [`ensayar_despliegue_ux.py`](ensayar_despliegue_ux.py) | **Solo local.** El despliegue de la iteración de UX: de 35 a 37 migraciones con el backend anterior en marcha, los tres E2E con su limpieza y la vuelta atrás leyendo lo que crea la versión nueva |
| [`verificar_escalado_uat.py`](verificar_escalado_uat.py) | Solo lectura, **después de cada publicación**: el backend del UAT escala a cero (sin mínimo de servicio ni de plantilla, 100 % en la revisión esperada, sin etiquetas y sin mínimo en las revisiones referenciadas). Usa la sesión de `gcloud`. Uso en [`docs/DESPLIEGUE_UAT.md`](../../../docs/DESPLIEGUE_UAT.md), sección 9 |
| [`probar_persistencia_catalogo.py`](probar_persistencia_catalogo.py) | Bloque C, C8: la copia del catálogo de Ventas sobrevive al escalado a cero del UAT. `--fase sincronizar` (Administración, contraseña sin eco) guarda el estado; `--fase comprobar`, después de llegar a 0 instancias, lo compara. Solo actualiza la copia del catálogo (un intento y sus filas), sin Órdenes ni otros datos. Ensayado contra una API local (`--sin-autenticacion`) el 17/11/2026. Uso en [`docs/DESPLIEGUE_UAT.md`](../../../docs/DESPLIEGUE_UAT.md), sección 10 |
| [`ensayar_persistencia_catalogo.py`](ensayar_persistencia_catalogo.py) | **Solo local.** Bloque C: la copia del catálogo de Ventas en PostgreSQL con procesos reales de uvicorn. Una instancia sincroniza y se la mata; otra con la carpeta de datos vacía ve la misma copia. Datos rechazados y origen inaccesible no la tocan. Un proceso muerto a mitad de una sincronización deja la reserva hasta que vence y la siguiente la marca INTERRUMPIDA. El backend publicado (`--anterior`) funciona sobre la base nueva. El 17/11/2026, 26 de 26. Diseño en [`docs/persistencia-catalogos.md`](../../../docs/persistencia-catalogos.md) |
| [`generar_productos_rt_ficticios.py`](generar_productos_rt_ficticios.py) | Reparación RT, etapa 1: escribe `producto.csv` (las 31 columnas reales de Producto, con los casos de la sección 8 del diseño) y `tipo_producto.csv`, ficticios. Para el adaptador `archivo` y para cargar la **planilla de prueba** del UAT; nunca la planilla real. `producto_passcode`, documento, precios y personas llevan `NO-LEER-FICTICIO` |
| [`probar_reparacion_rt.py`](probar_reparacion_rt.py) | Reparación RT, etapa 1, **E2E contra la planilla de prueba**. `--fase sincronizar` (Administración, contraseña sin eco): contadores, sedes, búsquedas, filtros, ficha, avisos y nada sensible, comparados con los datos ficticios; `--fase comprobar`, después del escalado a cero. Escribe solo la copia de Productos RT. Contra una API local (`--sin-autenticacion`) el 19/11/2026: 23 de 23 y 1 de 1. Uso en [`docs/DESPLIEGUE_UAT.md`](../../../docs/DESPLIEGUE_UAT.md), sección 11 |
| [`ensayar_reparacion_rt.py`](ensayar_reparacion_rt.py) | **Solo local.** Reparación RT, etapa 1, con procesos reales de uvicorn: reinicio y arranque en frío sin origen ni carpeta, un proceso muerto a mitad de una sincronización (409 y luego INTERRUMPIDA), el backend publicado (`--anterior`) sobre la migración nueva y nada sensible en registros ni en la base. El 19/11/2026 con `fd434ef`, 21 de 21 |
| [`ensayar_limpieza_e2e.py`](ensayar_limpieza_e2e.py) | **Solo local.** La limpieza selectiva de punta a punta. Con una Orden previa y su foto, corre los dos E2E, cada uno con su línea de base y su limpieza en ensayo y aplicada, y comprueba que todo queda como antes; también prueba las guardas y `03_verificar.sql` con 23 y con 35 migraciones |
| [`ensayar_migracion_integral.py`](ensayar_migracion_integral.py) | **Solo local.** Ensayo completo del despliegue de la macroiteración integral: base con las 23 migraciones de São Paulo, datos del código publicado, las 12 migraciones nuevas con conciliación, código nuevo, vuelta atrás (y sus incompatibilidades conocidas), restauración del respaldo y reinicio. Uso en [`docs/DESPLIEGUE_UAT.md`](../../../docs/DESPLIEGUE_UAT.md), sección 7 |

**Escenarios de `probar_macro_v14.py`:**

1. Evaluación técnica obligatoria, confirmación y adicionales.
2. Redefinición en la evaluación y descarte técnico.
3. Desistimiento total con una reparación activa (DC07C).
4. Antecedentes del equipo.
5. Reporte operativo.
6. Administración de Tipos de Reparación y de Mesas.

Reutiliza los helpers de `app/backend/tests/fixtures`, así que recorre los mismos caminos que las pruebas automáticas.

**Guardas de `probar_macro_v14.py`:**

- **Destino:** solo la API pública con el proyecto de São Paulo, o una API local con `--sin-autenticacion`.
- **Escritura:** sin `--escribir` solo verifica las precondiciones. No escribe nada si las Órdenes existentes no son exactamente las de `--ordenes-previas` (por defecto, ninguna). Las comprobaciones miran solo las Órdenes que crea, y el reporte operativo se compara contra el tomado antes de escribir.
- **Datos:** todos ficticios (cliente «Cliente Ficticio E2E V14», teléfono 000-0000, IMEI de ejemplo).
- **Catálogo:** el precio y la Mesa que cambia vuelven a su valor al final, aunque falle una comprobación.
- **Tipos de Reparación:** no crea ninguno, porque `tipo_reparacion` no admite borrado y quedaría para siempre.

## Recorrido

1. **Antes:**
   - identificar las Órdenes existentes, que se conservan, con `03_verificar.sql` (hoy `OR-000001`);
   - registrar el estado inicial (catálogos, stock, secuencias, cuentas);
   - comprobar un respaldo cifrado reciente ([`docs/RESPALDOS.md`](../../../docs/RESPALDOS.md)).
2. **Ensayo local, sin contraseñas.** Base con migraciones y semillas, como en [`docs/CHECKPOINT_PRE_DEPLOY.md`](../../../docs/CHECKPOINT_PRE_DEPLOY.md), sección 7, y backend local en modo demo:

   ```bash
   app/backend/.venv/Scripts/python supabase/scripts/validacion_uat/probar_macro_v14.py --api http://127.0.0.1:8000 --sin-autenticacion --escribir
   ```

3. **En el UAT, la persona responsable:**
   1. con autorización, [`../reinicio_uat/05_linea_base_e2e.sql`](../reinicio_uat/05_linea_base_e2e.sql), inmediatamente antes;
   2. cargar las claves publicables en `SUPABASE_PUBLISHABLE_KEY_ORIGEN` y `SUPABASE_PUBLISHABLE_KEY_DESTINO`;
   3. ejecutar `validar_uat.ps1 -Salida <carpeta> -OrdenesPrevias OR-000001`. Usar `-SinOregon` si Oregón ya no está.
4. **Identificar los datos creados.** Comparar con el informe JSON:
   - las Órdenes y su horario;
   - que todos los clientes sean ficticios;
   - que no haya eventos fuera de esas Órdenes;
   - los movimientos y los cambios de configuración.
5. **Limpieza selectiva con [`../reinicio_uat/06_limpiar_e2e.sql`](../reinicio_uat/06_limpiar_e2e.sql):**
   1. correrla en modo `ensayo`: no deja ningún efecto;
   2. tomar un respaldo cifrado;
   3. correrla en modo `aplicar`, sobre una copia con `v_modo` cambiado, sin tocar el archivo versionado;
   4. correr `03_verificar.sql`: los mismos conteos que antes del E2E.

   Borra solo lo que no estaba en la línea de base; las Órdenes previas, sus fotos y documentos no se tocan. Aborta sin cambios si:
   - una Orden o un cliente nuevo no es del E2E;
   - cambió una fila previa;
   - cambió un catálogo, salvo el stock y el proveedor ficticio.

   Al aplicar elimina la línea de base, que contiene copias de los datos previos. Si el resumen lista fotos nuevas, se borran del bucket por nombre, nunca por prefijo.

   `01_reiniciar.sql` vacía **todas** las Órdenes: no se usa después de un E2E, solo para un reinicio total autorizado.
6. **Después:**
   - ensayo de restauración en la nube;
   - estado igual al inicial (el `updated_at` de Auth cambia por los inicios de sesión).

**Macroiteración integral:** el mismo recorrido con `probar_macro_integral.py` después de `probar_macro_v14.py`: cada uno con su línea de base y su limpieza, y los dos con `--ordenes-previas`. El reinicio y la limpieza ya clasifican las 22 tablas nuevas: las de compras, lotes, comunicaciones, firmas, reclamos, seguimientos y checklists son operativas; permisos, motivos, parámetros, plantillas, proveedores y Tipos de Equipo son maestras. Ensayado completo, con su vuelta atrás (`02_restaurar.sql`), por `ensayar_migracion_integral.py`.
