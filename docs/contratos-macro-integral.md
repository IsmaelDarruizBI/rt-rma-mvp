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

La copia de los Tipos de Equipo desde el catálogo de Ventas (`POST /api/admin/equipment-types/sync`) es de Administración (`CONFIGURACION_ADMINISTRAR`).
| `ORDENES_CONSULTAR`, `INVENTARIO_CONSULTAR` (consulta) | Todos | Consultas de Órdenes e inventario (DC27B) |

`CONFIGURACION_ADMINISTRAR` y `ROLES_ADMINISTRAR` (Administración) no se configuran.

## Rutas por módulo

| Módulo | Rutas |
|---|---|
| Roles y permisos | `GET/PUT /api/admin/users[/{codigo}/roles]`, `GET/PUT /api/admin/permissions[/{codigo}]` |
| Reclamos | `GET /api/warranty-claims[/{id}]`, `POST /api/warranty-claims/{id}/continue` |
| Motivos y retiro | `GET /api/catalogs/reasons?tipo=`, `GET/POST/PUT /api/admin/reasons`, `GET/PUT /api/admin/parameters`, `POST /api/orders/{id}/pickup-followups` |
| Recargo por medio de pago (DEC-UX-08, rama `feat/ux-recepcion`) | `GET /api/admin/payment-methods` (`editable` y los medios con `recargo_porcentaje`), `PUT /api/admin/payment-methods/{codigo}` (`usuario_id`, `recargo_porcentaje` 0 a 100 con hasta dos decimales; Administración, auditado como `MEDIO_PAGO`; solo PostgreSQL). `MedioPagoOut` suma `recargo_porcentaje`; `PagoOut` suma `recargo_porcentaje`, `recargo_importe` y `total_cobrado` (`monto` + recargo; `monto` es lo imputado al saldo) |
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
- **Auditoría:** todo cambio de catálogo queda en `rma.cambio_configuracion` (entidades PERMISO, USUARIO, TIPO_REPARACION, MESA_TRABAJO, INSUMO, MOTIVO, PARAMETRO, PLANTILLA, PROVEEDOR, CHECKLIST).
