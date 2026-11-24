# Contratos de la macroiteración integral

API, entidades y permisos que agregó la rama `feat/macro-integral` (DEC-MI-01 a 16 y DC12). El comportamiento funcional es el de `business/`; el estado de cada decisión, el de [`traceability/discrepancias-baseline-v1.4.md`](../traceability/discrepancias-baseline-v1.4.md), sección I; las tablas, las de [`postgresql/diseno-fisico.md`](postgresql/diseno-fisico.md). Este documento solo describe los contratos.

Convenciones: todas las rutas exigen sesión; las escrituras llevan `usuario_id` en el cuerpo y el caso de uso valida el permiso (409 `PRECONDICION_INVALIDA` si falta); las consultas marcadas «consulta» responden 403 con sesión real si el rol no tiene el permiso. «Solo PostgreSQL»: en la demo JSON responde que no está disponible (409) o devuelve el catálogo vacío.

## Permisos nuevos

Todos configurables desde Configuración > Permisos. El valor inicial es el que figura acá; ninguno concede acceso que antes no había.

| Permiso | Roles iniciales | Para qué |
|---|---|---|
| `INGRESO_CORREGIR` | Recepción, Coordinación RMA, Administración | Corregir los datos del ingreso con motivo (DEC-MI-07) |
| `RECLAMO_CONTINUAR`, `RECLAMOS_CONSULTAR` (consulta) | Recepción; Recepción, Coordinación, Administración | Reclamos rechazados (DEC-MI-02) |
| `RETIRO_SEGUIMIENTO` | Recepción, Administración | Seguimientos del retiro demorado (DEC-MI-14) |
| `COMUNICACION_ENVIAR`, `CONSENTIMIENTO_REGISTRAR` | Recepción, Coordinación, Administración | WhatsApp asistido y consentimiento (DEC-MI-08) |
| `FIRMA_REGISTRAR` | Recepción, Coordinación, Administración | Firmas de documentos (DEC-MI-06) |
| `EQUIPO_VINCULO_CORREGIR` | Recepción, Coordinación, Administración | Corregir la identidad del Equipo (DEC-MI-11) |
| `DEVOLUCION_STOCK` | Administración, Coordinación | Devolver al stock lo consumido (DEC-MI-10) |
| `COMPRAS_GESTIONAR`, `COMPRAS_CONSULTAR` (consulta) | Recepción, Coordinación, Administración | Compras (DEC-MI-09) |
| `CHECKLIST_REGISTRAR` | Recepción, Coordinación, Administración | Checklist y advertencia de faltantes (DC12) |
| `AJUSTE_REVERTIR` | Administración | Revertir o corregir un ajuste comercial (DEC-AJ-10, bloque 5 de ajustes funcionales) |

La copia de los Tipos de Equipo desde el catálogo de Ventas (`POST /api/admin/equipment-types/sync`) es de Administración (`CONFIGURACION_ADMINISTRAR`).
| `ORDENES_CONSULTAR`, `INVENTARIO_CONSULTAR` (consulta) | Todos | Consultas de Órdenes e inventario (DC27B) |

`CONFIGURACION_ADMINISTRAR` y `ROLES_ADMINISTRAR` (Administración) no se configuran.

## Configuración v2 (19/11/2026, rama `feat/configuracion-v2`)

Diseño y decisiones en [`configuracion-discovery.md`](configuracion-discovery.md). Matriz de todas las rutas en `app/backend/tests/test_matriz_permisos.py` (una ruta sin clasificar hace fallar la prueba).

**Permisos.** `COMPRAS_GESTIONAR` se reemplaza por los de abajo; `CONFIGURACION_ADMINISTRAR` queda para parámetros, recargos y la auditoría completa. Todos configurables salvo los dos de Administración.

| Permiso | Roles iniciales | Requiere | Para qué |
|---|---|---|---|
| `COMPRA_SOLICITAR`, `OC_CREAR`, `OC_CONFIRMAR`, `OC_CANCELAR`, `COMPRA_RECIBIR` | Los de `COMPRAS_GESTIONAR` (Recepción, Coordinación, Administración; la migración `20261120000200` copia lo configurado) | `COMPRAS_CONSULTAR` | Cada acción de Compras; `OC_CREAR` también descarta el borrador propio (DF-5) |
| `PROVEEDOR_GESTIONAR` | Administración | `COMPRAS_CONSULTAR` | Alta y edición de proveedores |
| `TIPO_REPARACION_GESTIONAR`, `PRECIOS_GESTIONAR`, `MESA_TIPOS_GESTIONAR`, `MOTIVO_GESTIONAR`, `PLANTILLA_GESTIONAR`, `CHECKLIST_GESTIONAR` | Administración | — | Cada catálogo; el precio aparte (un alta de tipo exige los dos) |
| `INSUMO_GESTIONAR` | Administración | `INVENTARIO_CONSULTAR` | Insumos (el precio, con `PRECIOS_GESTIONAR`) |

`GET /api/admin/permissions` informa `requiere`; `PUT /api/admin/permissions/{codigo}` rechaza (409) una lista vacía y un cambio que deje una acción sin su consulta. `permisos_de` (y `GET /api/me`, `GET /api/catalogs/users`) informa además el alias `COMPRAS_GESTIONAR` a quien tiene `OC_CREAR`, para el frontend anterior. `GET /api/admin/config-changes?entidad=X` lo ve quien administra esa entidad; sin `entidad`, Administración.

**Contratos que cambian (compatibles):**

- **Códigos automáticos (CFG-01):** `codigo` es opcional en `POST /api/admin/repair-types` (`TR-NNN`) y `POST /api/admin/reasons` (`CANC-NNN` o `INT-NNN`); `clave` y `codigo` en `POST /api/admin/supplies` (`INS-NNN`, el código igual a la clave) y `codigo` en `PUT /api/admin/supplies/{clave}`. Si vienen, se respetan. Duplicados sin distinguir mayúsculas: 409 `PRECONDICION_INVALIDA`, nunca 500. Proveedor, solicitud, OC, reclamo y pregunta usan el mismo generador con sus formatos.
- **Garantías del Tipo (CFG-06):** `garantia_dias`, `garantia_con_checkin`, `garantia_sin_checkin` y `politica_garantia_rma` son opcionales: lo que no viene se conserva al editar; en el alta el genérico toma el de con check-in.
- **Plantillas (CFG-08):** cada plantilla informa `visible` (solo `INGRESO` y `LISTO_PARA_RETIRAR`).
- **Rutas que ahora controlan el permiso en la API:** las de Compras por acción; `/api/admin/*` por catálogo; plantillas de Administración; mensaje preparado, consentimientos, bandejas, fotos y firmas con `ORDENES_CONSULTAR`; limpieza de fotos con `FOTOS_ADMINISTRAR`.

## Rutas por módulo

| Módulo | Rutas |
|---|---|
| Roles y permisos | `GET/PUT /api/admin/users[/{codigo}/roles]`, `GET/PUT /api/admin/permissions[/{codigo}]` |
| Reclamos | `GET /api/warranty-claims[/{id}]`, `POST /api/warranty-claims/{id}/continue` |
| Motivos y retiro | `GET /api/catalogs/reasons?tipo=`, `GET/POST/PUT /api/admin/reasons`, `GET/PUT /api/admin/parameters`, `POST /api/orders/{id}/pickup-followups` |
| Recargo por medio de pago (DEC-UX-08, rama `feat/ux-recepcion`) | `GET /api/admin/payment-methods` (`editable` y los medios con `recargo_porcentaje`), `PUT /api/admin/payment-methods/{codigo}` (`usuario_id`, `recargo_porcentaje` 0 a 100 con hasta dos decimales; Administración, auditado como `MEDIO_PAGO`; solo PostgreSQL). `MedioPagoOut` suma `recargo_porcentaje`; `PagoOut` suma `recargo_porcentaje`, `recargo_importe`, `total_cobrado` (`monto` + recargo; `monto` es lo imputado al saldo), `recargo_distribucion` (`[{detalle_id, importe}]`, DEC-UX-13) y `recargo_devuelto`; `DevolucionDineroOut` suma `recargo_importe` y `total_reintegrado` (DEC-UX-14); el resumen de la Orden, `recargo_cobrado`, `recargo_devuelto` y `recargo_por_detalle`; el comprobante de entrega, `recargo` por trabajo, pago y devolución y `recargo_incorporado`, `recargo_cobrado` y `recargo_devuelto` |
| Comprobantes (DEC-AJ-09, bloque 4 de ajustes funcionales) | `GET /api/admin/company` (`editable` y `empresa`), `PUT /api/admin/company` (`usuario_id`, `nombre` obligatorio, `razon_social`, `cuit`, `direccion`, `telefono`, `email`, `horario`, `pie_comprobante`; auditado como `EMPRESA`), `GET /api/admin/terms` (`editable`, `vigente` y `versiones`), `POST /api/admin/terms` (`usuario_id`, `titulo`, `contenido`: publica la versión siguiente, vigente desde ese momento; auditada como `TEXTO_LEGAL`). Todas con `CONFIGURACION_ADMINISTRAR`; las escrituras, solo PostgreSQL. El contenido de los documentos suma `empresa.horario` y `empresa.pie_comprobante`; el del comprobante de entrega, `terminos` (la versión que imprime). `PasoProgresoOut` suma `opcional` y `omitido` (DEC-AJ-03) |
| Ajuste comercial (DEC-AJ-10, bloque 5 de ajustes funcionales) | `POST /api/orders/{id}/discount` (sin cambios de forma: cambiar o quitar un ajuste vigente exige además el permiso de su clase), `POST /api/orders/{id}/adjustments/{ajuste}/revert` (`usuario_id`, `motivo`; `AJUSTE_REVERTIR`; solo el vigente de su destino, antes de la entrega), `POST /api/orders/{id}/adjustments/{ajuste}/correct` (`usuario_id`, `tipo`, `valor`, `clase`, `motivo`; `AJUSTE_REVERTIR` y el permiso de la clase nueva). Cada registro de `descuentos` suma `id`, `precio_original`, `importe_aplicado`, `precio_final`, `corrige_a` y `reversion`; la Orden suma `recalculos_ajuste`. Los comprobantes nuevos suman, por trabajo, `ajuste` y `precio_final`, y `ajuste_orden` y `ajustes_por_trabajo` |
| Iteración de UX de Recepción | `POST /api/orders` y `POST /api/orders/rt-interno` aceptan `trabajo_inicial` (Tipo de Reparación; se agrega en la misma transacción, DEC-UX-04); `recepcion.observaciones_unificadas` en el alta, en `PUT .../reception` y en la salida (DEC-UX-03) |
| Comunicaciones | `GET /api/communications/templates`, `GET /api/orders/{id}/messages/prepare?plantilla=`, `POST /api/orders/{id}/messages`, `POST /api/orders/{id}/messages/{com}/confirm`, `GET/POST /api/clients/{id}/consents`, `GET/POST/PUT /api/admin/message-templates` |
| Firmas | `GET /api/orders/{id}/signatures[/{firma}]`, `POST /api/orders/{id}/documents/{doc}/signatures?usuario_id=&forma=` (cuerpo: la imagen) |
| Identidad del equipo | `GET /api/equipment/identify?imei=&numero_serie=`, `GET /api/equipment/{equipo}/orders`, `POST /api/orders/{id}/equipment-link` |
| Insumos y lotes | `GET/POST/PUT /api/admin/supplies` (con `control` y `precio`), `GET /api/inventory/{insumo}/lots`, `lote` en `POST /api/inventory/{insumo}/receipts`, `lote_id` en `POST .../adjustments`, `desperdicio` y `lote_id` en cada insumo utilizado al cerrar una Ejecución, `POST /api/orders/{id}/consumptions/{consumo}/return` |
| Compras (solo PostgreSQL) | `GET /api/purchases/status`, `GET /api/purchases/{suppliers,requests,suggestions,orders,costs}`, `POST /api/purchases/requests[/{id}/discard]`, `POST /api/purchases/orders[/{id}/confirm, /{id}/cancel, /{id}/receipts]`, `GET/POST/PUT /api/admin/suppliers` |
| Checklist | `GET /api/catalogs/checklist` y `GET /api/admin/checklist` (con `origen`: columna de Ventas, origen, última sincronización y aviso si falta definir la columna), `POST /api/admin/equipment-types/sync` (copia los tipos desde el catálogo de Ventas; 409 sin columna definida o con datos ambiguos, 503 si el origen no responde; no hay alta ni edición de tipos, DEC-MI-16), `POST/PUT /api/admin/checklist-questions[/{codigo}]` (con `orden`), `POST /api/orders/{id}/checklist`, `POST /api/orders/{id}/missing-info-ack` |

**Catálogo de Ventas (DEC-MI-16).** Los tipos se leen con el mismo origen de solo lectura de la copia de productos (`RMA_CATALOGO_ORIGEN`, `RMA_CATALOGO_SUBCATEGORIAS`), de la columna `RMA_TIPO_EQUIPO_CAMPO` (`tp_categoria`, `tp_subcat_1` o `tp_gp`). Vacía por defecto: qué columna es el tipo está pendiente (ABI-42), y sin ella no hay tipos ni se pide el checklist. El código del tipo es el valor de Ventas tal cual; los que dejan de venir quedan no vigentes, nunca se borran.

`OrdenOut` suma `seguimientos_retiro`, `retiro_demorado_dias`, `comunicaciones`, `correcciones_equipo`, `consumos_insumo` (con lo devuelto), `checklists_recepcion`, `informacion_faltante` y `tipo_equipo` (identificador de Ventas y descripción del último checklist).

## Garantías de integridad

- **Lotes:** el saldo de un lote y el stock sin lote identificado salen del libro; nunca quedan negativos, ni con operaciones concurrentes (trigger del libro, insumo bloqueado). La disponibilidad sigue siendo una por insumo.
- **Compras:** una recepción nunca supera lo pendiente (trigger con la orden bloqueada); cada línea genera un INGRESO con referencia `OC/REC/línea` única; una orden confirmada o cancelada no vuelve atrás.
- **Registros históricos inmutables:** comunicaciones y su confirmación, consentimientos, firmas, correcciones del Equipo, checklists, confirmaciones de faltantes, seguimientos del retiro, reclamos, lotes y recepciones.
- **Auditoría:** todo cambio de catálogo queda en `rma.cambio_configuracion` (entidades PERMISO, USUARIO, TIPO_REPARACION, MESA_TRABAJO, INSUMO, MOTIVO, PARAMETRO, PLANTILLA, PROVEEDOR, CHECKLIST, MEDIO_PAGO, EMPRESA, TEXTO_LEGAL).
