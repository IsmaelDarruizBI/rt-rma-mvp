# Discrepancias entre la baseline V1.4 y el producto

La baseline funcional vigente es PROC-REP V1.4, aprobada en DC01 y sincronizada desde `rt-rma-app` (DC02):

- Commit de origen: `ab928b6e33203257c26427cbb9af7875bd38693b` (rama `dc31/cancelacion-explicita`: V1.4 con la revisión DC31, sobre la etiqueta `v1.4-baseline`).
- Contenido funcional aprobado en `b6cc3a5`.
- Manifiesto de procedencia: `business/FUNCTIONAL_SOURCE.json`.

Este documento lista lo que el producto todavía no hace como dice la baseline, y lo que el producto hace sin que la baseline lo defina. **No son fallas de la sincronización documental**: la copia de `business/` es idéntica a la fuente. Son trabajo de implementación o decisiones pendientes.

DC02 no modificó servicios, dominio, endpoints ni frontend. El código evaluado es el de `mvp-v2` en `f270a84`, salvo las decisiones de la sección G, revisadas en la rama `feat/iteracion-1-alineacion-v14` (iteración 1, 11/11/2026).

Fuente de los estados de implementación: `business/decisions/decision-log-v1.4.yaml` (`implementation`). Las rutas de evidencia son relativas a `app/backend/app`, salvo que digan otra cosa.

`npm run validate:discrepancies` falla si una decisión PARCIAL, NO_IMPLEMENTADO o CONTRARIO del registro, o una incorporación de UAT sin confirmar, no aparece en este documento. También falla si el documento no cita el commit de origen del manifiesto, de modo que cada resincronización obliga a revisarlo.

## A. Implementación contraria a la decisión (0)

Las tres que figuraban (DC06, DC07 y DC11) se alinearon en la iteración 1: ver la sección G.

## B. Decisiones no implementadas (12)

| Decisión | Qué dice la baseline | Situación en el producto | Pendientes |
|---|---|---|---|
| DC18B | Permisos configurables por evento de custodia | `services/custodia.py:68` (ROLES_RECEPCION_EQUIPO fijo) | ABI-06 |
| DC19 | Registrar Minorista/Mayorista sin cambios automáticos de precio | `domain/models/personas.py` (Cliente sin clasificación) | - |
| DC12 | Checklist configurable por tipo de equipo, opcional, con advertencia por información faltante | No existe checklist | - |
| DC23 | Administración gestiona catálogos y valores predeterminados; permisos delegables | Catálogos en archivos JSON sin administración | - |
| DC26 | Firma en pantalla o archivo firmado, ligados al documento y su versión | Los documentos no tienen firma | ABI-08 |
| DC24 | Compras en un proceso propio, después de PostgreSQL | No existe módulo de Compras | ABI-12 |
| DC24LOT | Movimientos por lote con trazabilidad hasta el Detalle | Movimientos sin lote | ABI-12 |
| DC30 | Consentimiento y preferencias por finalidad | No existe registro de consentimiento | ABI-31 |
| DC27A | Varios roles por usuario; permisos como unión | `domain/models/personas.py:45-51` (Usuario.rol único) | - |
| DC27B | Permisos de consulta configurables | Las consultas GET no están protegidas | - |
| DC27C | Supabase Auth; usuarios, roles y permisos en PostgreSQL | Sin autenticación | - |
| DC02 | `rt-rma-mvp/business` es una copia generada y verificada | **Implementada por esta sincronización.** El registro de `rt-rma-app` todavía dice NO_IMPLEMENTADO porque se evaluó antes; corresponde actualizarlo en la fuente | - |

## C. Decisiones implementadas en parte (13)

| Decisión | Qué dice la baseline | Qué hay en el producto | Qué falta | Pendientes |
|---|---|---|---|---|
| DC03 | Priorizan Coordinación o Recepción; entregan Administración o Recepción; permisos modificables | `services/ordenes.py:74` y `:79`: roles constantes | Configurarlos desde Administración | - |
| DP-01 | Cambio de prioridad por Técnico, Recepción y Coordinación, configurable y trazado | `services/ordenes.py:694` y la observación «anterior -> nueva» en el historial | Rol configurable | - |
| DP-02 | Liberación de una Orden ajena por Técnico y Coordinación, con advertencia, motivo y auditoría | `services/tomas.py:373` y `services/ejecuciones.py:523`: la interrupción ocurre solo dentro de la liberación | Rol configurable | ABI-36 |
| DC08 | Permisos por acción y contexto; tres tipos de cancelación | Roles fijos (`services/cancelaciones.py:66`); `OrigenCancelacion` sin descarte técnico | Permisos configurables y tipo descarte técnico | ABI-06, ABI-23 |
| DC18 | Cuatro situaciones de custodia con eventos y responsables | `domain/models/enums.py:303-327`: seis valores calculados | Unificar el modelo y registrar cada evento con responsable | - |
| DC20 | Identidad física propia del Equipo; reutilización por IMEI confirmada; `tp_id` como referencia comercial | `domain/models/equipos.py:10-63`: el Equipo se copia en cada Orden | Equipo con historia propia, búsqueda y confirmación de reutilización | ABI-05 |
| DC15A | Política de garantía configurable por tipo de reparación y check-in | `domain/garantia.py:15-18`: 90/30 fijo, garantía sugerida y definitiva por Detalle | Política configurable y precedencias; criterio de garantía aplicable | ABI-03, ABI-37 |
| DC23AUD | Auditoría de cambios de configuración; historial de precios | Snapshots en Detalles y documentos; el catálogo guarda solo el precio vigente | Auditoría e historial de precios | - |
| GLO-01 | Estación = Mesa de trabajo, con «Mesa de trabajo» como nombre visible | Una sola entidad; la interfaz dice «Estación de trabajo» | Texto visible | - |
| DC09 | Ajuste Comercial (CORTESIA o DESCUENTO) por Orden o por Detalle | `services/descuentos.py`: un ajuste por Orden con clase DESCUENTO (RECEP o ADMIN) o CORTESIA total (ADMIN, provisional, iteración 1) | Ajuste por Detalle; cortesía parcial; permisos por tipo de ajuste | ABI-09, ABI-10, ABI-26 |
| DC10 | Anulación de Pagos por Administración, delegable, con motivo, sin borrar el Pago | `services/pagos.py:386-416` | Delegación configurable (depende de DC08) | - |
| DC25 | WhatsApp asistido con plantillas e historial (etapa 1) | `app/frontend/src/features/ordenes-reparacion/whatsapp.ts`: comparte sin plantillas ni historial | Plantillas e historial de envíos | ABI-13 |
| DC07C | Desistimiento total como proceso guiado | `services/decision_cliente.py:337-376`: análisis previo sin circuito guiado | Circuito guiado | - |

## D. Diferencias de recorrido entre el grafo V1.4 y lo que registra el backend

El backend no interpreta los YAML: registra en el historial los nodos que recorre como constantes (`services/workflow.py`). Diferencias conocidas con el grafo V1.4:

| Recorrido | Grafo V1.4 | Producto | Decisión |
|---|---|---|---|
| Check-in de entrega | 265 → 269 → 265 con la acción «Registrar check-in» | Acción en la recepción (`registros_checkin`, temporal), sin nodo 269 en el historial; la entrega se bloquea igual | UAT-I01, ABI-32 |
| Ingreso en garantía no admitido | 036 → EVT-REP-998 | El rechazo (409 `GARANTIA_VENCIDA`) no crea la Orden ni cambia la origen; no se registra el intento, porque la baseline deja pendiente qué se registra | DC15B (abierto en la baseline) |
| Desistimiento solicitado, Ejecución con desperdicio | 211 → 300 o 305 | Solo 300 (cancelar el Detalle); el 305 de cancelar trabajos pendientes no se usa desde este camino | DC07 |

## E. Lo que el producto hace sin que la baseline lo defina como regla

| Comportamiento | Situación en la baseline | Pendiente |
|---|---|---|
| UAT-I18: corrección de los datos del ingreso con versiones anteriores | Implementado sin aprobación documentada; no es regla | ABI-25 |
| UAT-I19: bandejas por rol, cola de taller, búsqueda y navegación | Presentación; no se formaliza en `business/` | - |
| Volver a registrar el check-in hasta la entrega | Comportamiento técnico sin aprobación funcional | ABI-32 |
| Exigir el check-in con al menos un trabajo realizado | Interpretación provisional de «garantía aplicable» | ABI-37 |
| Plazo del tipo de reparación hasta registrar el check-in | Dentro de las precedencias pendientes | ABI-03 |
| Estado físico obligatorio para el comprobante de ingreso | Decisión de la implementación por confirmar | ABI-19 |
| «Otros»: puntaje 0 y cualquier Mesa de trabajo | Por confirmar | ABI-20 |
| Entrada automática a la cola solo para el ingreso inicial de CLIENTE_EXTERNO | Extensión a otros orígenes pendiente | ABI-21 |
| Tipo de movimiento DEVOLUCION de insumos | Frente a DESPERDICIO de BR-REP-005 | ABI-22 |
| Roles predeterminados de inventario, catálogo, ajuste de garantía y fotografías | Provisionales | ABI-23 |
| Descuento por Recepción o Administración que no deja el total bajo lo cobrado (la cortesía total sí puede, DC11) | Permisos por tipo y tratamiento pendientes | ABI-09, ABI-10 |
| Excepción de garantía autorizada por Coordinación RMA o Administración (iteración 1) | BR-REP-039 deja el permiso predeterminado pendiente | ABI-04 |
| Cortesía total otorgada y quitada solo por Administración (iteración 1) | BR-REP-016 deja el permiso pendiente | ABI-09 |
| Reclamo de garantía con algún Detalle vencido y otros vigentes: exige la excepción para todo el reclamo | La baseline no trata el reclamo mixto | ABI-33 |
| Reversibilidad de lo hecho al interrumpir por desistimiento: sí o no | La baseline no fija los valores | ABI-18 |
| Motivo de la interrupción en una liberación ajena («Liberada por …») | Interpretación provisional | ABI-36 |
| Mantenimiento: limpieza de fotografías huérfanas por ADMINISTRADOR (UAT-011) | Solo implementación técnica (UAT-I02) | - |

## F. Trazabilidad y specs

- **Grafos de `traceability/`:** citan V1.4 como fuente y sus identidades validan contra V1.4 (`npm run validate:traceability:global`). Los campos de contexto (`in_scenario`, `implemented`, `coverage` y el `status` de los ítems que no son PROC-REP) describen los slices tal como se construyeron sobre V1.3. Su revisión contra los Scenarios V1.4 queda pendiente.
- **`traceability/iteracion-1-v14.yaml`:** primer grafo construido directamente sobre Scenarios V1.4 (VAR-REP-038, 039, 041 y 042, y DC06).
- **`specs/001` a `019`:** son el registro histórico de slices especificados sobre V1.3. No se reescriben.
- **`traceability/IMPLEMENTATION.md`:** sus secciones anteriores al 24/10/2026 describen divergencias respecto de V1.3. Las que V1.4 formalizó figuran en las incorporaciones de UAT del registro (DC16).

## G. Alineadas en la iteración 1 (rama `feat/iteracion-1-alineacion-v14`)

El registro de origen (`business/decisions/decision-log-v1.4.yaml`) todavía las marca como pendientes porque se evaluó antes; corresponde actualizarlo en `rt-rma-app` y resincronizar (DC02). Detalle de pruebas y decisiones provisionales: `docs/ESTADO_PROYECTO.md`.

| Decisión | Qué dice la baseline | Qué hace el producto ahora | Qué sigue pendiente | Pendientes |
|---|---|---|---|---|
| DC06 | El técnico define y redefine; Recepción gestiona las autorizaciones del cliente | 075 (definir luego de la revisión y cerrar esa carga) y 127 (redefinir) exigen TECNICO; las decisiones y los desistimientos del cliente siguen en Recepción; 069 (sin reparación) sigue en Recepción | VAR-REP-019 (el técnico redefine antes de ejecutar, desde PROC-REP-183) depende de la evaluación técnica obligatoria de BR-REP-035, que el producto no tiene | - |
| DC07 | Solicitud de desistimiento y cancelación efectiva registradas por separado, con usuario y fecha | Desistir de un Detalle en ejecución registra la solicitud (046, EV-REP-046) sin cancelar; el técnico solo puede interrumpir; al interrumpir se cancela (300) con la solicitud conservada. Lo que no se está ejecutando se sigue cancelando en el acto. DC31 sin cambios: cancelar trabajos no cancela la Orden | Desistir de todo con una Ejecución activa sigue bloqueado (DC07C, circuito guiado) | - |
| DC07B | Interrumpir para cancelar registra estado, materiales y reversibilidad | Con desistimiento pendiente, la interrupción exige el estado del trabajo y si es reversible; los insumos ya se registraban | Catálogo de estados y valores de reversibilidad | ABI-18 |
| DC11 | Una cortesía total con Pagos previos deja saldo a favor y exige devolución antes del cierre | Ajuste de clase CORTESIA total: conserva los Pagos, deja saldo a favor y la entrega se bloquea hasta devolverlo (PROC-REP-265/267/268); sin pagos ni devoluciones duplicados | Cortesía parcial; permisos por tipo de ajuste | ABI-10 |
| DC15B | Validar la vigencia de la garantía de origen (PROC-REP-036); vencida bloquea salvo excepción autorizada | 035 → 036 → 040 con la vigencia por Detalle (entrega + días); vencida sin excepción: 409, no se crea la Orden (VAR-REP-038); con motivo y un usuario autorizado: se crea y se audita quién, cuándo, por qué, vencimiento y Detalle (VAR-REP-039, EV-REP-052) | Registro del intento rechazado (ABI-35); reparación paga vinculada (ABI-34); quién autoriza por defecto (ABI-04); reclamo parcialmente vigente (ABI-33) | ABI-03, ABI-04, ABI-33, ABI-34, ABI-35 |
