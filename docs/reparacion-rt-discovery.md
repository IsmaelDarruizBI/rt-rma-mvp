# Reparación RT: especificación, contrato de datos y diseño

**Estado (17/11/2026): especificación aprobada e incorporada en `rt-rma-app` `spec/reparacion-rt` `168618a` (commit local, sin push); diseño aprobado conceptualmente. La etapa 1 espera el bloque C ([`persistencia-catalogos.md`](persistencia-catalogos.md)).**

- **Sin cambios:** código, base, migraciones, infraestructura, despliegues, Gestión RT, `main` y `rt-rma-app`.
- **Especificación:** su texto exacto está en el Anexo A, validado en una copia de `rt-rma-app`. Se incorpora cuando se apruebe ese texto.
- **Persistencia de copias:** el mecanismo que comparte con el catálogo de Ventas está en [`persistencia-catalogos.md`](persistencia-catalogos.md), y se implementa **antes** que este módulo.

**Objetivo.** Un módulo principal **Reparación RT**, al nivel de Órdenes, Taller y Compras, para:

- consultar los productos de Gestión RT en estado `Reparacion` (etapa 1);
- crear desde uno de ellos una Orden `RT_INTERNO` vinculada para siempre al producto (etapa 2).

**Marcas de verificación:**

- **[U]** confirmado por el usuario;
- **[C]** verificado en el código o la configuración de RMA;
- **[NV]** no verificado: tipo, formato, volumen, unicidad o semántica todavía no examinados.

## 1. Especificación funcional

Aprobación conceptual del 17/11/2026. El texto exacto está en el Anexo A.

| ID | Decisión | Resuelve |
|---|---|---|
| **DEC-RT-01** | Leer Producto (solo lectura) y su relación con TipoProducto; copia consultable en PostgreSQL, que no es una sincronización de inventario; crear Órdenes `RT_INTERNO` desde un producto. **Producto y Equipo son entidades distintas**, relacionadas solo por **vínculos verificables** (cómo, quién y cuándo). **Ninguna escritura en Gestión RT**, tampoco al informar el resultado (PROC-REP-290). Siguen excluidas las Órdenes de venta, la sincronización de inventario o stock y cualquier otra integración | Amplía DEC-MI-11, DEC-MI-16 y el fuera de alcance de la macroiteración |
| **DEC-RT-02** | Un producto no puede tener dos Órdenes vinculadas **abiertas**: ni cerradas (EVT-REP-999 o ENTREGADA) ni CANCELADA. No bloquean las cerradas por entrega, devolución a Gestión RT, cierre sin reparación o cancelación (incluido el desistimiento, DC31); ni una CANCELADA anterior a DC31 que espera devolución o dinero; ni una que solo coincide por referencia RT o IMEI. Una abierta con todos sus Detalles cancelados (PROC-REP-307) sí bloquea, porque admite trabajos nuevos | ABI-46 |
| **DEC-RT-03** | Una coincidencia **por referencia RT o por IMEI** es solo una sugerencia: nunca vincula ni fusiona. Vincular exige una validación explícita, con motivo y registro, con los roles de la corrección de la vinculación del Equipo (DEC-MI-11). Al crear desde un producto con coincidencias, se decide explícitamente y queda registrado. **El servidor lo exige**: la API rechaza crear sin la decisión y validar sin motivo o sin permiso | ABI-47 |
| **DEC-RT-04** | Se mantiene el alta `RT_INTERNO` manual; su referencia RT no vincula por sí sola | ABI-48 |
| **DEC-RT-05** | Sincronización a pedido, controlada inicialmente por Administración | ABI-49 y ABI-51 (sincronización) |
| **DEC-RT-06** | Observaciones del equipo opcionales en `RT_INTERNO`, sin completar ningún texto en su lugar | ABI-50 (UX-15) |
| **DEC-RT-07** | Consultan Recepción, Coordinación RMA y Administración | ABI-51 |
| **BR-REP-050** (nueva) | «Productos de Gestion RT en reparacion»: la copia, las entidades distintas y los vínculos verificables, las coincidencias como sugerencias, la Orden abierta única, las observaciones opcionales y ninguna escritura | — |
| **ABI-52** (abierto, POSTERIOR) | Cuándo y cómo automatizar la sincronización | — |

**Trazabilidad con lo anterior.** Ningún texto aprobado se reescribe: se agrega la referencia a la ampliación.

- DEC-MI-11: «salvo los vínculos verificables con el Producto … DEC-RT-01; una coincidencia de IMEI … nunca vincula por sí sola (DEC-RT-03)».
- DEC-MI-16: la lectura autorizada se amplía; el alcance del checklist no cambia.
- BR-REP-022: los vínculos verificables con el Producto; entidades distintas; la referencia RT y el IMEI nunca vinculan solos.
- BR-REP-048: cita BR-REP-050.
- FEAT-REP-001:
  - alcance: «Consultar los Productos de Gestión RT en Reparación y crear una Orden RT_INTERNO desde uno de ellos (DEC-RT-01)»;
  - exclusiones: «… salvo los vínculos verificables Producto-Equipo» y «Escribir en Gestión RT o cambiar el estado de sus Productos»;
  - declara BR-REP-050.
- ABI-46 a ABI-51 se registran **cerrados** por DEC-RT-02 a 07, con la fecha y la resolución, como ABI-44 y 45 con DEC-UX-13 y 14.

**Control de contradicciones (17/11/2026).** Se revisó todo artefacto V1.4 que menciona Gestión RT o `RT_INTERNO`:

- decisiones ABI-21, ABI-27, ABI-39, ABI-42, DEC-IT1-05, DEC-MI-11, DEC-MI-16 y DEC-UX-01;
- reglas BR-REP-012, 016, 017, 022, 024, 028, 031, 033, 034, 038, 040, 045, 046 y 048;
- los nodos PROC-REP-020, 040 y 290, y el fuera de alcance de la macroiteración.

| Posible conflicto | Resolución en el texto |
|---|---|
| DEC-MI-11, BR-REP-022, FEAT-REP-001 y el fuera de alcance de la macroiteración excluyen vincular con Gestión RT | DEC-RT-01 los amplía expresamente; cada texto cita la excepción, sin borrar lo aprobado |
| DEC-MI-16 excluye «sincronizar inventario» | La copia se declara **de consulta, no** una sincronización de inventario; esa exclusión sigue |
| PROC-REP-290 prevé informar el resultado «a futuro» al sistema de stock y ventas | DEC-RT-01: se sigue registrando en RMA sin escribir en Gestión RT; automatizarlo requiere otra decisión |
| El estado terminal de `RT_INTERNO` está pendiente (ABI-27, BR-REP-012) | DEC-RT-02 usa «abierta» = sin llegar al fin operativo EVT-REP-999, no un estado terminal |
| BR-REP-046 (observaciones del ingreso) | Aplica solo a `CLIENTE_EXTERNO`; PROC-REP-040 ya no exige observaciones; DEC-RT-06 no la cambia |
| DEC-MI-11 permite reutilizar un Equipo por IMEI si Recepción lo elige | Compatible: DEC-RT-03 exige esa elección explícita y la registra |
| ROLES del catálogo de Ventas (Administración y Coordinación) | No cambian; la copia de Productos RT tiene su propio permiso (DEC-RT-05) |

El diff solo quita 6 líneas, y cada una se reemplaza por su versión ampliada: ningún texto aprobado se elimina.

**Validación.** En una copia de `rt-rma-app` `spec/ux-recepcion` `ebd0840`, con la matriz regenerada, pasan:

- `validate-decisions` (86 decisiones, 52 pendientes; versión 3 del texto) y `validate-process`, `-features`, `-references` y `-scenarios`;
- `test-scenarios`, `test-feature-scenario-mapping`, `test-commercial-closure`, `test-customer-decision`, `test-consolidation` y `test-origin-view`.

Se hizo un ajuste en la prueba que cuenta las reglas nuevas desde BR-REP-039 (de 11 a 12), como cuando se agregaron las anteriores. `test-functional-copy` exige un repositorio Git y no se corrió en la copia.

**Para incorporarlo,** con autorización:

1. Rama `spec/reparacion-rt` desde `spec/ux-recepcion` en `rt-rma-app`.
2. Aplicar el Anexo A y regenerar la matriz (`validate-decisions --write`).
3. `npm run validate:v1.4`, commit y push.
4. En `rt-rma-mvp`: sincronizar `business/` ([`sincronizacion-funcional.md`](sincronizacion-funcional.md)) y `npm run validate:all`.

## 2. Contrato de datos Gestión RT → RMA

### 2.1 Origen [U]

| Tabla | Dónde | Ubicación |
|---|---|---|
| Producto | Planilla `1uzGqHgmtynZW8RakCJEB_DuGNy2QQMl8ByNkIpxzPE0`, GID `1030788425` | El adaptador resuelve el nombre de la hoja desde el GID en cada sincronización: un cambio de nombre no la rompe |
| TipoProducto | La misma planilla, hoja `raw_TipoProducto` [C] | Por nombre, como hoy |

### 2.2 Las 31 columnas de Producto

Nombres [U]; tipos, formatos y semántica [NV] salvo los indicados.

**Regla de lectura:**

- Se lee la fila 1 (encabezado) y se piden **solo** las columnas marcadas «Copiar» (`values:batchGet` por columna).
- Las demás nunca salen de Google: `producto_passcode` no se solicita jamás (sección 2.8).
- Las columnas obligatorias tienen que existir y aparecer una sola vez, o la sincronización se rechaza.

| # | Columna | Decisión | Obligatoria | Destino (`rma.producto_rt`) | Motivo / regla |
|---|---|---|---|---|---|
| 1 | `producto_id` | **Copiar** | Sí | `producto_id` `text` PK | Identificador [U]. Texto sin espacios al borde; un número `n.0` se lleva a entero (criterio de `ventas._texto`). Tipo y formato [NV] |
| 2 | `producto_oc` | No leer | — | — | Orden de compra (dato comercial) [NV] |
| 3 | `producto_tp` | **Copiar** | Sí | `tipo_producto_id` `text` | `= TipoProducto.tp_id` [U] (sección 2.3) |
| 4 | `producto_movimiento` | No leer | — | — | Semántica [NV]; candidata si se aclara |
| 5 | `producto_imei` | **Copiar** | Sí | `imei`, `imei_normalizado`, `imei_valido` | Sección 2.5. Contenido y formato [NV] |
| 6 | `producto_bateria` | **Copiar** | No | `bateria` `text` | Dato técnico para la ficha. Formato [NV] (¿porcentaje?); se muestra tal cual |
| 7 | `producto_precio_compra` | No leer | — | — | Dato comercial |
| 8 | `producto_cantidad` | No leer | — | — | Inventario; semántica [NV] |
| 9 | `producto_venta_reparacion` | No leer | — | — | Semántica [NV]; candidata si se aclara |
| 10 | `producto_detalle_estetico` | **Copiar** | No | `detalle_estetico` `text` | Dato técnico para la ficha |
| 11 | `producto_sede` | **Copiar** | Sí | `sede` `text` | Valores [U]: Alippi, Centro, eCommerce, Fisherton y RMA. Otro valor se guarda y se informa |
| 12 | `producto_comentario` | No leer | — | — | Texto libre: puede contener datos personales. Candidata con decisión |
| 13 | `producto_creado_en` | **Copiar** | No | `creado_en_origen` `timestamptz` | Antigüedad. Formato [NV]: se lee como número de serie de fecha de Sheets (`dateTimeRenderOption=SERIAL_NUMBER`) |
| 14 | `producto_creado_por` | No leer | — | — | Dato de una persona |
| 15 | `producto_eliminado` | **Copiar** | Sí | `eliminado_en_origen` `boolean` | Un eliminado no se lista. Valores [NV]: se interpretan como `tp_eliminado` (`yes`, `true`, `si`, `1`, `x`) |
| 16 | `producto_eliminado_por` | No leer | — | — | Dato de una persona |
| 17 | `producto_eliminado_at` | No leer | — | — | No se usa |
| 18 | `producto_status` | **Copiar** | Sí | `estado_gestion_rt` | En reparación ⇔ `Reparacion` [U], comparado sin espacios al borde y **exacto**. Otras variantes se informan como aviso |
| 19 | `producto_ov` | No leer | — | — | Orden de venta: excluida por DEC-RT-01 |
| 20 | `producto_precio_vendido` | No leer | — | — | Comercial |
| 21 | `producto_fecha_venta` | No leer | — | — | Comercial |
| 22 | `producto_enviar_precio` | No leer | — | — | Comercial |
| 23 | `producto_defecto` | **Copiar** | No | `defecto` `text` | Falla informada por Gestión RT, para la ficha. ¿Precargarla como observaciones en la etapa 2? Decisión pendiente (sección 9) |
| 24 | `producto_toma_rt` | **Copiar** | No | `toma_rt` `text` | Tipo de ingreso (PROC-REP-020). Valores [NV]; se muestra tal cual |
| 25 | `producto_stock` | No leer | — | — | Inventario: excluido por DEC-RT-01 |
| 26 | `producto_passcode` | **Nunca** | — | — | Sensible [U] |
| 27 | `app_id` | No leer | — | — | Semántica [NV] (¿identificador interno de AppSheet?) |
| 28 | `producto_documento` | No leer | — | — | Posible documento de una persona |
| 29 | `producto_check_movimiento` | No leer | — | — | Semántica [NV] |
| 30 | `producto_tipo_reparacion` | **Copiar** | No | `tipo_reparacion_origen` `text` | Para la ficha. **No** se mapea a los Tipos de reparación de RMA |
| 31 | `producto_repuesto` | **Copiar** | No | `repuesto` `text` | Para la ficha |

**Resumen:**

- 13 columnas se copian: 6 obligatorias (`producto_id`, `producto_tp`, `producto_imei`, `producto_sede`, `producto_status`, `producto_eliminado`) y 7 opcionales.
- 17 no se leen.
- `producto_passcode` nunca se lee.

Una columna opcional que falta deja su campo vacío y genera un aviso. Sumar una columna requiere una decisión.

**Producto no tiene color, capacidad ni número de serie.** Esos datos salen del TipoProducto (sección 2.3) y la identidad física es solo el IMEI.

### 2.3 Relación con TipoProducto

- En cada sincronización de Productos se lee `raw_TipoProducto` completa, sin el filtro `IPHONE USADOS` del catálogo de Ventas, y se resuelve `producto_tp → tp_id`.
- Se guarda en el producto una copia de: `tp_modelo`, `tp_categoria`, `tp_subcat_1`, `tp_number`, `tp_promaxness`, `tp_gb` (con la capacidad interpretada por `ventas.etiqueta_capacidad`) y `tp_color`.
- Ese es todo el dato del equipo: Producto no tiene color ni capacidad propios.
- **TipoProducto inexistente:** `tipo_producto_encontrado = false`, con un aviso en la ficha y el `tp_id` visible.
- **TipoProducto eliminado:** se copia igual y se marca `tipo_producto_eliminado = true`.
- **Por qué no se reutiliza `rma.catalogo_producto`:** está filtrada por subcategoría y sus bajas significan «no se ofrece en el alta».

### 2.4 Validación de ID y duplicados

| Caso | Tratamiento |
|---|---|
| Falta una columna obligatoria o está repetida; la hoja (GID) no existe o está vacía | **RECHAZADA**: la copia no cambia |
| `producto_id` vacío | La fila se descarta y se cuenta |
| `producto_id` repetido en la lectura (unicidad real [NV]) | No se aplican esas filas; si el ID ya estaba en la copia, conserva sus datos y se marca `conflicto_origen`. Aviso con la lista. El resto se aplica |
| Desaparece más del 50 % de los productos presentes | **RECHAZADA** (protección contra una lectura truncada); umbral configurable |
| El mismo `producto_id` cambia de IMEI o de TipoProducto | Se actualiza la copia, se marca `cambio_identidad` y se conserva la huella anterior. Órdenes y Equipos no cambian; en la etapa 2 se avisa en la ficha |

### 2.5 IMEI

- **Normalización:** sin espacios ni separadores (`domain/identidad.normalizar`).
- **Válido:** 15 dígitos. El dígito verificador (Luhn) se informa, pero no invalida.
- **Ausente:** `imei = null`. El producto se lista y se busca por ID y modelo.
- **Inválido:** incluye el caso de un valor numérico en notación científica, porque `producto_imei` podría estar guardado como número [NV]. Se guarda tal cual con `imei_valido = false` y no se usa para sugerir coincidencias.
- **Repetido entre productos:** `imei_repetido = true` en ambos. Se informa, y nunca vincula (DEC-RT-03).

### 2.6 Última sincronización

- Cada intento se registra en `rma.sincronizacion_origen` con `copia = 'PRODUCTOS_RT'`. Es el registro común del catálogo de Ventas ([`persistencia-catalogos.md`](persistencia-catalogos.md)).
- La API devuelve el bloque `copia` (última exitosa, último intento, resultado y mensaje) y la pantalla siempre muestra la fecha de los datos.
- Sin automatización (DEC-RT-05): un aviso indica la antigüedad de la copia. El umbral del aviso es configurable, por ejemplo 24 horas.

### 2.7 Productos que salen de Reparación

- **Filas que se aplican:** las de `producto_status = Reparacion` **y** las de cualquier estado cuyo `producto_id` ya está en la copia. Así se conoce el estado actual de los que salieron, sin copiar el inventario.
- **Al salir:**
  - `en_reparacion = false`, `salio_de_reparacion_en` y `estado_gestion_rt` con el estado nuevo;
  - deja de listarse por defecto;
  - la casilla «Mostrar los que salieron» y la ficha lo siguen mostrando.
- **Eliminado en Gestión RT o ausente del origen:** se marca `eliminado_en_origen` o `presente_en_origen = false`. **Nunca se borra.**
- **Si vuelve a Reparación:** un nuevo período (`en_reparacion_desde`).
- **Órdenes y Equipos no cambian nunca por una sincronización.** La desalineación con una Orden activa se avisa en la etapa 2.

### 2.8 Datos sensibles

- **`producto_passcode` nunca se solicita:** la lectura pide solo los rangos de las columnas «Copiar». Una prueba falla si algún rango pedido corresponde a una columna fuera de esa lista, o si `producto_passcode` entrara en ella.
- **Columnas comerciales y de personas:** no se leen (2, 7, 14, 16, 19 a 22, 28) y tampoco el texto libre (12).
- **Registros:** solo contadores, el identificador del intento y los `producto_id` en conflicto. Nunca IMEI, valores ni tokens.
- **UAT:** nunca la planilla real (sección 3.3).

### 2.9 Errores de sincronización

| Caso | Resultado | Copia |
|---|---|---|
| 401 / 403 (sin permiso), 404 (planilla), GID inexistente, 400, 429 (cuota), tiempo agotado | **FALLIDA**, con el mensaje (los textos de `catalogo/sheets._mensaje_http`) | Intacta |
| Estructura (sección 2.4) | **RECHAZADA** | Intacta |
| Error al aplicar | Rollback; **FALLIDA** | Intacta |
| Instancia apagada a mitad | El intento vence y el siguiente lo marca **INTERRUMPIDA** | Intacta |
| Otra sincronización en curso | HTTP 409 | — |
| Conflictos de ID, sedes desconocidas, estado con otra variante | **EXITOSA** con avisos | Aplicada salvo los IDs en conflicto |

## 3. Arquitectura de sincronización

### 3.1 Reutiliza el mecanismo del catálogo de Ventas

Es el de [`persistencia-catalogos.md`](persistencia-catalogos.md), sección 4:

- **Común:**
  - `rma.sincronizacion_origen`, con la reserva por índice único (vale entre instancias y con escalado a cero);
  - el motor `ejecutar_sincronizacion`: reservar, leer fuera de la transacción, validar, aplicar en una transacción y finalizar;
  - `LectorSheets`, extraído del adaptador actual, con `batchGet` y la resolución del GID;
  - las credenciales existentes: cuenta de servicio, `spreadsheets.readonly`, sin claves JSON.
- **Propio de Productos RT:**
  - el puerto `ProveedorProductosRt`, con adaptadores `sheets` y `archivo`;
  - `integraciones/gestion_rt/contrato.py`, con las columnas de la sección 2.2, la normalización y la validación;
  - la tabla `rma.producto_rt`;
  - la definición de la copia `PRODUCTOS_RT`.

Cambiar el origen (BigQuery u otro) es escribir otro adaptador del mismo puerto.

### 3.2 Configuración

Sin secretos:

- `RMA_PRODUCTOS_RT_ORIGEN`: `ninguno` (por defecto), `google_sheets` o `archivo`;
- `RMA_PRODUCTOS_RT_PLANILLA`, `RMA_PRODUCTOS_RT_GID` y `RMA_PRODUCTOS_RT_ARCHIVO`;
- `RMA_PRODUCTOS_RT_ESTADO` (`Reparacion`).

La hoja de TipoProducto y la credencial son las del catálogo de Ventas.

### 3.3 Ambientes y datos ficticios

| Ambiente | Origen |
|---|---|
| Local y CI | `archivo` con productos ficticios (sección 8) |
| UAT | **Planilla de prueba** con las 31 columnas reales y filas ficticias, compartida como Lector con `rt-rma-uat-api@…`. La crea el usuario. Alternativa: `archivo` dentro de la imagen. **Nunca la planilla real** |
| Producción (futuro) | Planilla real, con autorización |

## 4. Pantalla Reparación RT (etapa 1)

```
┌ Reparación RT ──────────────────────────────────────────────────────────────┐
│ Datos de Gestión RT del 17/11 10:42 · 214 en reparación   [Actualizar]*     │
│ ⚠ La última actualización falló a las 11:05: … (se muestran los datos de 10:42)│
├─────────────────────────────────────────────────────────────────────────────┤
│ [Buscar por ID, IMEI o modelo…                    ]                         │
│ Sede: (Todas 214) (Alippi 40) (Centro 61) (eCommerce 12) (Fisherton 33) (RMA 68)│
│ Orden RMA: [Todas ▾] Sin coincidencias · Con coincidencias sugeridas         │
│ □ Mostrar los que salieron de Reparación                                    │
├──────────┬───────────────┬──────────────────────────────┬────────┬──────────┤
│ ID RT    │ IMEI          │ Equipo                       │ Sede   │ Orden RMA│
│ 10432    │ …4 5678       │ iPhone 13 Pro 256 GB Graphite│ Centro │ ¿OR-000041? En cola (sugerida por referencia RT)│
│ 10433    │ —             │ iPhone 12 128 GB Black       │ RMA    │ Sin coincidencias│
│ 10440    │ …1 2345       │ iPhone 11 64 GB White        │ Alippi │ ¿OR-000017? (sugerida por IMEI)│
└──────────┴───────────────┴──────────────────────────────┴────────┴──────────┘
  * solo con el permiso de sincronizar (Administración)          ‹ 1 2 3 › (50)
```

- **Búsqueda:** una sola caja. Por ID exacto o prefijo, IMEI completo o sus últimos dígitos, y modelo (palabras parciales, sin mayúsculas ni tildes). Se ejecuta en el backend.
- **Filtros:** sede, con su cantidad (incluye «Otra» si aparece un valor no confirmado); Orden RMA; «Mostrar los que salieron».
- **Ficha** (panel lateral):
  - **Datos técnicos:** ID, IMEI (con avisos), modelo, capacidad, color y categoría del TipoProducto, batería, detalle estético, defecto, tipo de reparación y repuesto de Gestión RT, toma RT, sede, estado, alta en Gestión RT, en reparación desde y fecha de la copia.
  - **Órdenes:** en la etapa 1 no hay vínculos todavía: solo **coincidencias sugeridas**, por referencia RT o por IMEI, cada una con su criterio y su enlace (`ruta.pantalla = "orden"`). Desde la etapa 2, «Vinculadas» y «Sugeridas» en **secciones separadas**.
  - **Historial:** desde la etapa 2, las Órdenes vinculadas; una sugerida nunca se presenta como historial del producto.
- **Estados:**
  - cargando;
  - sin origen configurado;
  - nunca sincronizada (con [Actualizar] solo para Administración);
  - sin resultados;
  - actualizando;
  - error con copia anterior (aviso amarillo);
  - error sin copia (rojo);
  - error del backend;
  - sin permiso (sin menú, 403);
  - modo JSON («funciona sobre PostgreSQL», como Compras).
- **Diseño:** componentes existentes; a 390 px, tarjetas sin desborde.

## 5. Modelo de vinculación con RMA

Producto RT y Equipo RMA son **entidades distintas**: nunca se fusionan y se relacionan solo mediante **vínculos verificables** (DEC-RT-01). Una coincidencia por referencia RT o por IMEI es solo una **sugerencia** (DEC-RT-03).

**Etapa 1** (sin vínculos; sin migraciones sobre `orden` ni `equipo`):

| Coincidencia sugerida | Regla | Presentación |
|---|---|---|
| Por referencia RT | Orden `RT_INTERNO` cuya `referencia_rt`, sin espacios al borde, es igual a `producto_id` (alta manual, DEC-RT-04) | «¿OR-…? (sugerida por referencia RT)», con su estado |
| Por IMEI | Orden de cualquier origen cuyo `equipo_imei` normalizado es igual al IMEI válido y no repetido del producto | «¿OR-…? (sugerida por IMEI)», con su estado |

Ninguna cuenta como Orden activa del producto ni como historial. El filtro las agrupa en «Con coincidencias sugeridas».

**Etapa 2: vínculos verificables:**

```
producto_rt (copia)          vinculo_producto_rt (registro, inmutable)          equipo / orden (RMA)
───────────────────          ─────────────────────────────────────────          ────────────────────
producto_id (PK) ◄────────── producto_id                                         equipo.id (EQP-…)
                             equipo_id, orden_id ─────────────────────────────►  orden.id
                             como: CREADA_DESDE_PRODUCTO | VALIDACION_EXPLICITA
                             criterio de la coincidencia validada (REFERENCIA_RT | IMEI), motivo
                             usuario, rol habilitante, fecha
                             anulado_por / anulado_en / motivo (corrección auditada, nunca borrado)

orden.producto_rt_id  (copia del vínculo vigente; solo para la restricción)
índice único parcial: orden (producto_rt_id) WHERE cerrada_en IS NULL AND estado_workflow <> 'CANCELADA'   ← DEC-RT-02
```

- **El Equipo no cambia de forma ni de identidad.** La relación con el producto vive en `vinculo_producto_rt`, que dice cómo, quién y cuándo, y se puede verificar y corregir con auditoría.
- **Crear desde un producto sin coincidencias:** una Orden `RT_INTERNO` con una identidad de Equipo nueva y un vínculo `CREADA_DESDE_PRODUCTO`.
- **Crear desde un producto con coincidencias sugeridas:** la ventana las muestra y exige una decisión explícita, que queda registrada:
  - (a) **validar** una Orden sugerida abierta como la de este producto, lo que crea un vínculo `VALIDACION_EXPLICITA` y no crea otra Orden, por DEC-RT-02;
  - (b) **usar el Equipo** de una coincidencia por IMEI, con los controles de DEC-MI-11;
  - (c) **seguir sin vincular**, con motivo.
- **Validar después:** desde la ficha, una coincidencia sugerida se puede validar con motivo. Usa los roles de la corrección de la vinculación del Equipo: Recepción, Coordinación RMA y Administración.
- **Alta manual (DEC-RT-04):** sigue como hoy. Su `referencia_rt` **no** crea un vínculo, aunque sea igual a un `producto_id`.
- **Observaciones (DEC-RT-06):** `orden.falla_reportada` pasa a admitir vacío solo en `RT_INTERNO` (migración aditiva: `check (falla_reportada is not null or origen = 'RT_INTERNO')`). Los documentos muestran «—»; nunca un texto inventado.

## 6. Diseño técnico de la etapa 1

### 6.1 Endpoints

Bajo `/api/rt-products`, solo PostgreSQL.

| Método y ruta | Permiso | Entrada | Salida |
|---|---|---|---|
| `GET /api/rt-products` | `PRODUCTOS_RT_CONSULTAR` | `q`, `sede` (repetible), `orden_rma` (`SIN_COINCIDENCIAS`, `CON_SUGERENCIAS`; `VINCULADA` desde la etapa 2), `incluir_fuera`, `pagina`, `tamano` (≤ 100) | `{copia, sedes: [{sede, cantidad}], total, productos: [ProductoRtResumenOut]}` |
| `GET /api/rt-products/{producto_id}` | `PRODUCTOS_RT_CONSULTAR` | — | `ProductoRtOut`: datos técnicos, avisos y `coincidencias_sugeridas[]` (criterio, Orden, estado). `vinculos[]` desde la etapa 2 |
| `POST /api/rt-products/sync` | `PRODUCTOS_RT_SINCRONIZAR` | `usuario_id`; idempotencia existente | El intento (resultado, contadores, avisos); 409 si hay otro en curso |
| `GET /api/rt-products/syncs?limite=10` | `PRODUCTOS_RT_SINCRONIZAR` | — | Los últimos intentos |

### 6.2 PostgreSQL

Propuesta de la migración aditiva de la etapa 1, **no creada**. Va después de la de [`persistencia-catalogos.md`](persistencia-catalogos.md).

```sql
alter table rma.sincronizacion_origen drop constraint <check de copia>;
alter table rma.sincronizacion_origen add constraint sincronizacion_origen_copia
  check (copia in ('CATALOGO_VENTAS', 'PRODUCTOS_RT'));

create table rma.producto_rt (
  producto_id text primary key check (btrim(producto_id) <> ''),
  estado_gestion_rt text not null,
  en_reparacion boolean not null,
  en_reparacion_desde timestamptz,
  salio_de_reparacion_en timestamptz,
  eliminado_en_origen boolean not null default false,
  presente_en_origen boolean not null default true,
  sede text,
  imei text, imei_normalizado text,
  imei_valido boolean not null default false,
  imei_repetido boolean not null default false,
  tipo_producto_id text,
  tipo_producto_encontrado boolean not null default false,
  tipo_producto_eliminado boolean not null default false,
  modelo text, categoria text, subcategoria text, capacidad_texto text, color text,
  bateria text, detalle_estetico text, defecto text, toma_rt text,
  tipo_reparacion_origen text, repuesto text,
  creado_en_origen timestamptz,
  conflicto_origen boolean not null default false,
  cambio_identidad boolean not null default false,
  texto_busqueda text not null,       -- id, imei y modelo normalizados
  huella text not null,               -- detecta cambios
  primera_vez_visto_en timestamptz not null,
  sincronizado_en timestamptz not null,
  sincronizacion_id text not null references rma.sincronizacion_origen (id)
);
create index producto_rt_listado on rma.producto_rt (sede, en_reparacion_desde)
  where en_reparacion and not eliminado_en_origen;
create index producto_rt_imei on rma.producto_rt (imei_normalizado)
  where imei_valido and not imei_repetido;
-- Sin borrado (trigger); rma_backend: select, insert, update.
```

**Listado.** Coincidencias sugeridas por consulta, sin columnas en `orden`:

```sql
with sugeridas as (
  select p.producto_id, o.codigo, o.estado_workflow, o.cerrada_en, 'REFERENCIA_RT' as criterio
    from rma.producto_rt p
    join rma.orden o on o.origen = 'RT_INTERNO' and btrim(o.referencia_rt) = p.producto_id
  union
  select p.producto_id, o.codigo, o.estado_workflow, o.cerrada_en, 'IMEI'
    from rma.producto_rt p
    join rma.orden o on p.imei_valido and not p.imei_repetido
                    and upper(regexp_replace(coalesce(o.equipo_imei, ''), '\s', '', 'g')) = p.imei_normalizado
)
select … from rma.producto_rt p
 where (p.en_reparacion and not p.eliminado_en_origen) or :incluir_fuera
   and (:q is null or p.texto_busqueda like '%' || :q || '%')
   and (:sedes is null or p.sede = any(:sedes))
 … sugeridas agregadas por producto (una Orden con los dos criterios aparece una vez, con ambos),
   filtro orden_rma, orden por en_reparacion_desde, limit/offset;
```

**Rendimiento.** El volumen es [NV]. Si hacen falta, se agregan un índice de expresión sobre `orden.equipo_imei` y `pg_trgm`, medidos con la planilla de prueba.

### 6.3 Permisos

| Código | Predeterminado | Grupo |
|---|---|---|
| `PRODUCTOS_RT_CONSULTAR` (consulta) | Recepción, Coordinación RMA y Administración (DEC-RT-07) | Consultas |
| `PRODUCTOS_RT_SINCRONIZAR` | Administración (DEC-RT-05) | Inventario y catálogos |

Los dos son configurables, como los demás. Los enlaces a Órdenes respetan `ORDENES_CONSULTAR`. En la etapa 2, crear la Orden usa `ORDEN_CREAR`.

### 6.4 Frontend

| Pieza | Cambio |
|---|---|
| `components/layout.tsx` y `iconos.tsx` | Sección `"reparacion-rt"`, «Reparación RT» entre Taller e Inventario, visible con `puedeConsultarProductosRt` |
| `api/productosRt.ts` y `types/api.ts` | Cliente y tipos |
| `features/reparacion-rt/ReparacionRtPanel.tsx` | Estado de la copia, [Actualizar] (solo con permiso), búsqueda, filtros, tabla o tarjetas, paginación y estados |
| `features/reparacion-rt/FichaProductoRt.tsx` | Datos técnicos; coincidencias sugeridas con su criterio (etapa 1); vinculadas aparte (etapa 2) |
| `features/reparacion-rt/filtros.ts` | Filtros en la URL |
| `PanelOrdenes.tsx` | Renderiza la sección y le pasa la navegación a una Orden |
| `tests/reparacion-rt.test.ts` | Filtros, estados, armado del equipo, rotulado de sugerencias por criterio |

## 7. Plan de implementación

**Bloque C, persistencia de copias, primero.** Las tareas C1 a C8 de [`persistencia-catalogos.md`](persistencia-catalogos.md), sección 5. Reparación RT empieza con C4 terminada.

**Etapa 0, sin código:**

| # | Tarea | Verificable |
|---|---|---|
| 0.1 | Aprobar el texto del Anexo A e incorporarlo (sección 1) | `validate:v1.4` y `validate:all` en verde; commits con autorización |
| 0.2 | Planilla de prueba con las 31 columnas y filas ficticias, compartida con la cuenta del UAT (usuario) | GID y lectura comprobados |
| 0.3 | Una fila de ejemplo **ficticia pero con el formato real** de cada columna «Copiar» (`producto_id`, `producto_imei`, `producto_creado_en`, `producto_eliminado`, `producto_bateria`, `producto_toma_rt`) | Tabla 2.2 sin [NV] de formato en las obligatorias |

**Etapa 1: consulta, búsqueda, filtros y visualización.**

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 1.1 | `gestion_rt/contrato.py`: columnas, normalización y validaciones de las secciones 2.4 y 2.5 | Una prueba unitaria por caso |
| 1.2 | Adaptadores `archivo` y `sheets` (`LectorSheets` de C5) y configuración | Ningún rango fuera de la lista (prueba con `producto_passcode`); errores de la sección 2.9 |
| 1.3 | Migración aditiva: `producto_rt` y `'PRODUCTOS_RT'` en el registro | `tests/postgres` desde cero; sin DELETE |
| 1.4 | Definición `PRODUCTOS_RT` sobre el motor común | En PostgreSQL: idempotente, nunca borra, copia intacta ante FALLIDA o RECHAZADA, salida y regreso a Reparación, conflictos, 409 entre instancias, reinicio |
| 1.5 | Listado y ficha (sección 6.2), con coincidencias sugeridas por referencia RT y por IMEI | Por sede, `q` y `orden_rma`; IMEI repetido o inválido no sugiere; una sugerencia nunca se presenta como vínculo, Orden activa ni historial |
| 1.6 | API y permisos (sección 6.3) | 401, 403 (Recepción no sincroniza), 409 |
| 1.7 | Frontend (sección 6.4) | `typecheck`, pruebas y `build`; recorrido en el navegador con el archivo ficticio, también a 390 px |
| 1.8 | Generador de datos ficticios y E2E `probar_reparacion_rt.py` contra la planilla de prueba | Contadores esperados; sin IMEI en los registros |
| 1.9 | Documentación: [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), evidencia de DEC-RT-01, 03, 05 y 07 en `business/` | Revisión |

**Aceptación de la etapa 1:**

- (a) Solo se listan los productos `Reparacion` no eliminados.
- (b) Los filtros por sede dan las cantidades del archivo ficticio.
- (c) La búsqueda funciona por ID, IMEI completo, últimos 4 dígitos y modelo.
- (d) Toda relación con una Orden es una coincidencia sugerida rotulada con su criterio; ninguna se presenta como vínculo.
- (e) La fecha de los datos siempre está visible, y un error muestra la copia anterior.
- (f) `producto_passcode` y las columnas «No leer» no aparecen en pedidos, tablas, respuestas ni registros.
- (g) Nada escribe en Gestión RT.
- (h) Sincroniza solo Administración.
- (i) La copia sobrevive a un reinicio y al escalado a cero.
- (j) El UAT tiene solo datos ficticios.

**Etapa 2: Orden vinculada y prevención de duplicados.**

| # | Tarea | Criterio de aceptación |
|---|---|---|
| 2.1 | Migración aditiva: `vinculo_producto_rt` (inmutable, con anulación auditada), `orden.producto_rt_id` e índice único parcial de Orden abierta, `falla_reportada` opcional solo en `RT_INTERNO` | La base rechaza una segunda Orden activa aun con dos pedidos simultáneos |
| 2.2 | `POST /api/rt-products/{producto_id}/orders` (alta RT con el equipo de la copia y la decisión explícita sobre las coincidencias) y `POST /api/rt-products/{producto_id}/links` (validar una coincidencia, con motivo) | Una transacción; las pruebas de HP-REP-002 siguen en verde |
| 2.3 | Observaciones opcionales en RT (DEC-RT-06), sin texto inventado, en la API, los documentos y el frontend | Una Orden RT sin observaciones se crea y sus documentos muestran «—» |
| 2.4 | P-01: capacidad y color obligatorios en el alta RT manual. Desde un producto vienen del TipoProducto | El alta manual sin ellos se rechaza |
| 2.5 | Ventana de alta precargada y bloqueada; ficha con historial del Equipo y avisos de desalineación | Recorrido en el navegador |
| 2.6 | E2E: crear, segundo intento bloqueado, coincidencias por referencia RT y por IMEI decididas explícitamente, validación posterior, limpieza selectiva (06 extendido a las tablas nuevas) | Verde |

**Aceptación de la etapa 2:**

- (a) La Orden `RT_INTERNO` se crea con el equipo precargado, el `producto_id` en la Orden y en el Equipo, y el mismo recorrido posterior.
- (b) No hay dos Órdenes activas por producto, tampoco en concurrencia.
- (c) Ninguna coincidencia por referencia RT o por IMEI vincula sin una validación explícita registrada; Producto y Equipo nunca se fusionan.
- (d) Una sincronización no cambia Órdenes, Equipos ni documentos.
- (e) Ninguna escritura en Gestión RT.

## 8. Pruebas con productos ficticios

**Generador** (`supabase/scripts/validacion_uat/generar_productos_rt_ficticios.py`). Produce un CSV para el adaptador `archivo` y para cargar la planilla de prueba:

- **Estructura:** las 31 columnas reales, en su orden.
- **Valores:**
  - IMEI de 15 dígitos con dígito verificador válido y prefijo de prueba;
  - `producto_tp` del catálogo de Ventas (no es sensible);
  - `producto_passcode`, `producto_documento`, precios y emails con el valor fijo `NO-LEER-FICTICIO`, para comprobar que nunca aparecen.

**Casos que tiene que cubrir:**

- productos `Reparacion` de las 5 sedes y otros estados;
- variantes `reparacion`, ` Reparacion ` y `Reparación`: solo la segunda cuenta, y las otras dos generan aviso;
- sin IMEI, IMEI inválido, en notación científica y repetido;
- `producto_id` vacío y repetido;
- `producto_tp` inexistente y eliminado;
- sede desconocida;
- eliminado en Gestión RT;
- salida y regreso a Reparación;
- una columna obligatoria faltante o repetida;
- una lectura que pierde más del 50 %;
- una Orden RT manual con `referencia_rt = producto_id` y una Orden de cliente con el mismo IMEI: las dos sugeridas, cada una con su criterio, ninguna vinculada.

**Dónde corre:** local y CI (`backend`, `postgres`, `frontend`). El E2E del UAT corre solo contra la planilla de prueba.

## 9. Riesgos y bloqueantes

**Bloqueantes reales:**

| # | Bloqueante | Para | Quién |
|---|---|---|---|
| B1 | Aprobar el texto exacto del Anexo A y autorizar su incorporación | Etapa 1 | Usuario |
| B2 | Bloque C (persistencia de copias) implementado (C1 a C4) | Etapa 1 | Desarrollo, con autorización |
| B3 | Planilla de prueba ficticia (0.2) | E2E y despliegue de la etapa 1 en UAT | Usuario |
| B4 | Formato real de las columnas «Copiar» (0.3) | Etapa 1 (validaciones de ID, IMEI, fechas y eliminado) | Usuario o Gestión RT |

**Decisiones pendientes que no bloquean la etapa 1:**

- **ABI-52:** automatizar la sincronización.
- **¿Precargar `producto_defecto` como observaciones?** Etapa 2. Hasta decidirlo, no se precarga, por DEC-RT-06.
- **Semántica de `producto_movimiento`, `producto_venta_reparacion`, `producto_check_movimiento` y `app_id`:** solo si se quieren usar.

**Riesgos:**

| Riesgo | Mitigación |
|---|---|
| Formatos reales distintos de los supuestos (ID numérico, IMEI como número, fechas como texto) | 0.3 antes de programar; la validación rechaza o avisa, nunca adivina |
| Copia desactualizada (sin automatización) | Fecha visible y aviso de antigüedad |
| `producto_id` reutilizado en Gestión RT | `cambio_identidad` y huella; confirmar con Gestión RT |
| Estructura de la hoja cambiada | RECHAZADA; copia intacta |
| Cuota o caída de Sheets | FALLIDA; copia intacta |
| Datos sensibles | Lectura solo de las columnas «Copiar» |
| Datos reales en el UAT | Planilla de prueba; nunca la real |
| Duplicados de Orden (etapa 2) | Índice único parcial e idempotencia |
| Desalineación con Gestión RT | Avisos; RMA no escribe en Gestión RT |
| **Corrección:** el impacto de la copia efímera del catálogo informado el 16/11 (R1) era menor | El alta usa el catálogo técnico versionado ([`persistencia-catalogos.md`](persistencia-catalogos.md), sección 1); la corrección se hace igual, por arquitectura |

## Anexo A. Texto incorporado en `rt-rma-app`

Aprobado el 17/11/2026 e incorporado en `rt-rma-app` `spec/reparacion-rt`, commit `168618a` (local, sin push) sobre `ebd0840`. `npm run validate:v1.4` está completo en verde, incluida la copia funcional (DC02). El texto es el de la versión 3 presentada, con los dos ajustes pedidos en la revisión:

- **DEC-RT-02:** qué Orden bloquea. Solo una vinculada abierta, que no está cerrada ni CANCELADA. Las cerradas, canceladas y desistidas no bloquean; las CANCELADA anteriores a DC31 tampoco; una abierta con todos sus Detalles cancelados sí. Lo verifica `domain/models/orden_reparacion.esta_cerrada` y DC31 (`services/cancelaciones.py`).
- **DEC-RT-03 y BR-REP-050:** la validación explícita de una coincidencia la exige el servidor (API), no solo la pantalla.

Se ve con `git -C ../rt-rma-app show 168618a`. Falta sincronizar `business/` en `rt-rma-mvp` cuando se autorice integrar esa rama.
