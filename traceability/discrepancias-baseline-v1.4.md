# Discrepancias entre la baseline V1.4 y el producto

La baseline funcional vigente es PROC-REP V1.4, aprobada en DC01 y sincronizada desde `rt-rma-app` (DC02):

- Commit de origen: `168618ad9ea6d08ec2c2ba450eb3a60393ef7ccd` (rama `spec/reparacion-rt`, publicada: DEC-RT-01 a 07 y BR-REP-050, Reparación RT, sobre `spec/ux-recepcion` `ebd0840`, con DEC-UX-01 a 14, DEC-MI-01 a 16, DC31, DEC-IT1-01 a 05 y la etiqueta `v1.4-baseline`).
- Contenido funcional aprobado en `b6cc3a5`.
- Manifiesto de procedencia: `business/FUNCTIONAL_SOURCE.json`.

Este documento lista lo que el producto todavía no hace como dice la baseline, y lo que el producto hace sin que la baseline lo defina. **No son fallas de la sincronización documental**: la copia de `business/` es idéntica a la fuente. Son trabajo de implementación o decisiones pendientes.

DC02 no modificó servicios, dominio, endpoints ni frontend. El código evaluado es el de `mvp-v2` en `f270a84`, salvo las decisiones de la sección G, revisadas en la rama `feat/iteracion-1-alineacion-v14` (iteración 1, 11/11/2026), las de la sección H, revisadas en `feat/macro-v14` (macroiteración, 12/11/2026), las de la sección I, revisadas en `feat/macro-integral` (macroiteración integral, 13/11/2026), y DEC-UX-01 a 14, revisadas en `feat/ux-recepcion` (iteración de UX de Recepción, 16/11/2026; DEC-UX-08, 13 y 14 implementadas, con ABI-44 y ABI-45 cerrados).

Fuente de los estados de implementación: `business/decisions/decision-log-v1.4.yaml` (`implementation`). Las rutas de evidencia son relativas a `app/backend/app`, salvo que digan otra cosa.

`npm run validate:discrepancies` falla si una decisión PARCIAL, NO_IMPLEMENTADO o CONTRARIO del registro, o una incorporación de UAT sin confirmar, no aparece en este documento. También falla si el documento no cita el commit de origen del manifiesto, de modo que cada resincronización obliga a revisarlo.

## A. Implementación contraria a la decisión (0)

Las tres que figuraban (DC06, DC07 y DC11) se alinearon en la iteración 1: ver la sección G.

## B. Decisiones no implementadas (10)

| Decisión | Qué dice la baseline | Situación en el producto | Pendientes |
|---|---|---|---|
| DC19 | Registrar Minorista/Mayorista sin cambios automáticos de precio | `domain/models/personas.py` (Cliente sin clasificación) | - |
| DC27C | Supabase Auth; usuarios, roles y permisos en PostgreSQL | Sin autenticación | - |
| DEC-UX-01 | Los modelos del catálogo técnico vienen de Ventas; se completan con una exportación nueva, sin inventar ni duplicar | El catálogo técnico es la copia de la exportación de Ventas del 21/10/2026 (36 modelos, sin la línea iPhone 18); el modelo que falta se carga a mano. Sin cambios de código | ABI-43 |
| DEC-RT-01 | Reparación RT: leer los Productos de Gestión RT, copia de consulta y vínculos verificables con Equipos y Órdenes | Sin implementar: solo está el mecanismo común de copias del bloque C (`application/sincronizacion_origen.py`, `rma.sincronizacion_origen`), que la copia de Productos RT reutilizará | Etapa 1 de Reparación RT ([`docs/reparacion-rt-discovery.md`](../docs/reparacion-rt-discovery.md)); ABI-52 |
| DEC-RT-02 | Un Producto no admite dos Órdenes abiertas vinculadas | Sin implementar (no hay vínculo Producto-Orden) | Etapa 2 |
| DEC-RT-03 | Las coincidencias por referencia RT o IMEI son solo sugerencias; vincular exige validación explícita y registrada, exigida por el servidor | Sin implementar | Etapas 1 (sugerencias) y 2 (validación) |
| DEC-RT-05 | La copia de Productos RT se sincroniza a pedido, controlada por Administración | Sin implementar | Etapa 1 |
| DEC-RT-06 | Observaciones del equipo opcionales en RT_INTERNO | Sin implementar: la base exige `orden.falla_reportada` | Etapa 2 |
| DEC-RT-07 | Consultan Reparación RT Recepción, Coordinación RMA y Administración | Sin implementar (no hay módulo) | Etapa 1 |
| DC02 | `rt-rma-mvp/business` es una copia generada y verificada | **Implementada por esta sincronización.** El registro de `rt-rma-app` todavía dice NO_IMPLEMENTADO porque se evaluó antes; corresponde actualizarlo en la fuente | - |

## C. Decisiones implementadas en parte (4)

| Decisión | Qué dice la baseline | Qué hay en el producto | Qué falta | Pendientes |
|---|---|---|---|---|
| DC18 | Cuatro situaciones de custodia con eventos y responsables | `domain/models/enums.py:303-327`: seis valores calculados | Unificar el modelo y registrar cada evento con responsable | - |
| DC12 | Checklist configurable por tipo de equipo, opcional, con advertencia por información faltante | Preguntas configurables con vigencia y orden, auditadas; checklist opcional con copia del tipo y de las preguntas y versiones con motivo; advertencia que nunca bloquea (`c8cd64f`, `ef79e45`) | **Dependencia pendiente (ABI-42):** sin tipos de equipo (ver DEC-MI-16) el checklist no se ofrece ni se pide | - |
| DEC-MI-16 | El Tipo de Equipo viene del catálogo de Ventas de Gestión RT; RMA configura solo las preguntas; la Orden conserva el tipo elegido | Tipos copiados del catálogo de Ventas con el origen de solo lectura existente, sin alta ni edición en RMA; identificador de Ventas y descripción en la Orden; la copia no cambia si el origen falla (`ef79e45`) | **Dependencia pendiente (ABI-42):** qué dato del catálogo de Ventas es el Tipo de Equipo. La tabla que RMA lee no tiene esa entidad y ninguna columna equivale sin ambigüedad; `RMA_TIPO_EQUIPO_CAMPO` queda sin definir | - |
| GLO-01 | Estación = Mesa de trabajo, con «Mesa de trabajo» como nombre visible | Una sola entidad; la interfaz dice «Estación de trabajo» | Texto visible | - |

## D. Diferencias de recorrido entre el grafo V1.4 y lo que registra el backend

El backend no interpreta los YAML: registra en el historial los nodos que recorre como constantes (`services/workflow.py`). Diferencias conocidas con el grafo V1.4:

| Recorrido | Grafo V1.4 | Producto | Decisión |
|---|---|---|---|
| Check-in de entrega | 265 → 269 → 265 con la acción «Registrar check-in» | Acción en la recepción (`registros_checkin`, temporal), sin nodo 269 en el historial; la entrega se bloquea igual | UAT-I01, ABI-32 |
| Ingreso en garantía no admitido | 036 → EVT-REP-998 | El rechazo (409 `GARANTIA_VENCIDA`) no crea la Orden ni cambia la origen e informa los trabajos elegibles; no se registra el intento, porque la baseline deja pendiente qué se registra | DC15B, DEC-IT1-03 (ABI-35 abierto) |
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
| Descuento por Recepción o Administración que no deja el total bajo lo cobrado (la cortesía sí puede, DC11 y DEC-IT1-02) | Permiso del DESCUENTO y su tratamiento bajo lo cobrado pendientes | ABI-09, ABI-10 |
| La idempotencia del ajuste comercial (`Idempotency-Key`) solo actúa con PostgreSQL, como la de los demás comandos (E6) | Diseño técnico vigente; con JSON no hay registro de acciones | - |
| Motivo de la interrupción en una liberación ajena («Liberada por …») | Interpretación provisional | ABI-36 |
| Mantenimiento: limpieza de fotografías huérfanas por ADMINISTRADOR (UAT-011) | Solo implementación técnica (UAT-I02) | - |
| Un Detalle registrado antes de la evaluación técnica (sin origen del diagnóstico) no la exige y no registra 182 al iniciarse | Plan de transición de la macroiteración para los datos existentes; la baseline no lo define | - |
| Reporte operativo de primera versión (estados, orígenes, técnicos, estaciones, antigüedad, reprocesos, consumo y cobros), visible para cualquier usuario autenticado | DC29 posterga el reporting; el reporte solo agrega datos registrados, sin umbrales ni indicadores nuevos | ABI-15, DC27B |
| En el modo JSON los catálogos son de solo lectura; administrarlos exige PostgreSQL | DC23 pide la administración sobre la persistencia definitiva | - |

## F. Trazabilidad y specs

- **Grafos de `traceability/`:** citan V1.4 como fuente y sus identidades validan contra V1.4 (`npm run validate:traceability:global`). Los campos de contexto (`in_scenario`, `implemented`, `coverage` y el `status` de los ítems que no son PROC-REP) describen los slices tal como se construyeron sobre V1.3. Su revisión contra los Scenarios V1.4 queda pendiente.
- **`traceability/iteracion-1-v14.yaml`:** primer grafo construido directamente sobre Scenarios V1.4 (VAR-REP-038, 039, 041 y 042, y DC06).
- **`traceability/macro-v14.yaml`:** grafo de la macroiteración (VAR-REP-019 y VAR-REP-043, evaluación técnica, reparaciones adicionales, configuración auditada y antecedentes del equipo), con la misma convención. El reporte operativo v1 no tiene Scenario ni regla propios (DC29, ABI-15).
- **`specs/001` a `019`:** son el registro histórico de slices especificados sobre V1.3. No se reescriben.
- **`traceability/IMPLEMENTATION.md`:** sus secciones anteriores al 24/10/2026 describen divergencias respecto de V1.3. Las que V1.4 formalizó figuran en las incorporaciones de UAT del registro (DC16).

## G. Alineadas en la iteración 1 (rama `feat/iteracion-1-alineacion-v14`)

Con las decisiones DEC-IT1-01 a 05 (11/11/2026) el registro de origen ya refleja este estado: DC07B, DC11 y DC15B IMPLEMENTADO; DC06, DC07 y DC09 PARCIAL. Detalle de pruebas: `docs/ESTADO_PROYECTO.md`.

| Decisión | Qué dice la baseline | Qué hace el producto ahora | Qué sigue pendiente | Pendientes |
|---|---|---|---|---|
| DC06 | El técnico define y redefine; Recepción gestiona las autorizaciones del cliente | 075 (definir luego de la revisión y cerrar esa carga) y 127 (redefinir) exigen TECNICO; las decisiones y los desistimientos del cliente siguen en Recepción; 069 (sin reparación) sigue en Recepción | VAR-REP-019 (el técnico redefine antes de ejecutar, desde PROC-REP-183) depende de la evaluación técnica obligatoria de BR-REP-035, que el producto no tiene | - |
| DC07 | Solicitud de desistimiento y cancelación efectiva registradas por separado, con usuario y fecha | Desistir de un Detalle en ejecución registra la solicitud (046, EV-REP-046: usuario, fecha, motivo, canal) sin cancelar; el técnico solo puede interrumpir; al interrumpir se cancela (300) a nombre del técnico, con la solicitud conservada (DEC-IT1-05). Lo que no se está ejecutando se sigue cancelando en el acto. DC31 sin cambios | Desistir de todo con una Ejecución activa sigue bloqueado (DC07C, VAR-REP-043, circuito guiado) | - |
| DC07B | Interrumpir para cancelar registra estado, materiales y reversibilidad | Con desistimiento pendiente, la interrupción exige reversibilidad Sí o No y la descripción del estado del trabajo (DEC-IT1-04); los insumos ya se registraban | - | - |
| DC11 | Una cortesía con Pagos previos deja saldo a favor y exige devolución antes del cierre | Ajuste de clase CORTESIA, total o parcial (DEC-IT1-02): conserva los Pagos, deja saldo a favor y la entrega se bloquea hasta devolverlo (PROC-REP-265/267/268); sin ajustes ni devoluciones duplicados | - | - |
| DC15B | Validar la vigencia de la garantía de origen (PROC-REP-036); vencida bloquea salvo excepción autorizada | Vigencia y excepción por cada trabajo reclamado (DEC-IT1-03): un vencido sin excepción rechaza el pedido sin crear nada e informa los elegibles (VAR-REP-038); la excepción de cada vencido la autorizan Recepción, Coordinación RMA o Administración (DEC-IT1-01) y queda auditada con quién, cuándo, por qué y el vencimiento original (VAR-REP-039, EV-REP-052) | Registro del intento rechazado; reparación paga vinculada; precedencias de garantía | ABI-03, ABI-34, ABI-35 |

## H. Alineadas en la macroiteración (rama `feat/macro-v14`)

Sin decisiones nuevas (12/11/2026). El registro de origen refleja este estado: DC06, DC07 y DC07C IMPLEMENTADO; DC08, DC20, DC23 y DC23AUD PARCIAL. Lo que sigue bloqueado y por qué está en la sección I del README de consolidación de `rt-rma-app`. Detalle de pruebas: `docs/ESTADO_PROYECTO.md`.

| Decisión o regla | Qué dice la baseline | Qué hace el producto ahora | Qué sigue pendiente |
|---|---|---|---|
| BR-REP-035/036, HP-REP-001/002 | Todo Detalle diagnosticado por Recepción se evalúa (182 → 183 → 184) antes de su primera Ejecución | El técnico titular evalúa cada Detalle (CONFIRMADO, DESCARTADO o REQUIERE_REDEFINICION, con motivo salvo CONFIRMADO) sobre la definición vigente; sin evaluación no se reserva ni se inicia; la evaluación queda en `rma.evaluacion_tecnica` | - |
| DC06, VAR-REP-019 | El técnico redefine antes de ejecutar | REQUIERE_REDEFINICION registra la nueva definición (127), validada por el mismo acto; la autorización anterior deja de valer | - |
| DC08 (descarte técnico) | Tres tipos de cancelación | DESCARTADO cancela el Detalle con origen DESCARTE_TECNICO a nombre del técnico; DC31 sin cambios | Permisos configurables |
| BR-REP-037, PROC-REP-128 | El técnico registra las reparaciones adicionales que detecta, con autorización diferida | Desde la evaluación (184 → 128 → 184, antes del resolver) o durante la participación (acción complementaria): Detalle nuevo de origen REVISION_TECNICA, pendiente del cliente en CLIENTE_EXTERNO y a factibilidad en los demás orígenes; la Ejecución en curso sigue | «Otros» con precio manual sigue siendo de Recepción |
| DC07, DC07C, VAR-REP-043 | Desistimiento total con una Ejecución activa como proceso guiado | Se registra la solicitud en cada trabajo afectado; al interrumpir, el técnico los cancela juntos (211 → 305); lo COMPLETO se conserva | - |
| BR-REP-022 | Antecedentes del Equipo | Consulta por IMEI o número de serie en el detalle de la Orden | ABI-05 |
| DC23, DC23AUD | Administración de catálogos auditada | Tipos de Reparación y Mesas con auditoría e historial de precios | Ver la sección C |

## I. Alineadas en la macroiteración integral (rama `feat/macro-integral`)

Implementación de DEC-MI-01 a 15 (13/11/2026), sin decisiones nuevas. El registro de origen (`99c69e8`) refleja este estado. Detalle de pruebas: `docs/ESTADO_PROYECTO.md`.

| Decisión | Qué hace el producto ahora | Commit | Qué sigue pendiente |
|---|---|---|---|
| DEC-MI-12, DC27A, DC08, DC03, DP-01, DP-02, DC10, DC18B, DEC-MI-04 | Varios roles por usuario; permisos por rol configurables desde Configuración con los predeterminados de antes; el historial guarda el rol habilitante; nunca sin un Administrador | `c47903e` | DC27B (sección C) |
| DEC-MI-03, DC09 | Ajuste comercial por Orden o por Detalle, sin prorrateo; por debajo de lo cobrado deja saldo a favor y la entrega exige devolverlo | `85f42cf` | - |
| DEC-MI-01, DC15A | Plazos por Tipo con y sin check-in; política para trabajos en garantía RMA; el ajuste manual prevalece; check-in exigible solo con garantía mayor a cero | `cc46121` | ABI-38, ABI-39 |
| DEC-MI-05, DEC-MI-07 | Check-in corregido con motivo y registros anteriores conservados; corrección del ingreso con motivo y valores anteriores y nuevos, sin tocar los comprobantes emitidos | `cc46121`, `7a79d97` | ABI-41 |
| DEC-MI-02 | Reclamo de garantía rechazado como registro propio y continuación paga vinculada, sin duplicados | `75948ac` | - |
| DEC-MI-15, DEC-MI-14 | Motivos de cancelación e interrupción por catálogo («Otro» con descripción); plazo de retiro configurable, bandeja de retiro demorado y seguimientos, sin cierre automático | `ac7a56d` | ABI-29 (medios de devolución), ABI-40 |
| DEC-MI-08, DC25, DC30 | WhatsApp asistido con plantillas editables, mensaje editable, intento y confirmación manual (nunca entregado ni leído); consentimiento por finalidad y canal | `b4dd52c` | ABI-13 (etapa 2, fuera de alcance) |
| DEC-MI-06, DC26 | Firma opcional ligada al documento emitido, en pantalla o foto del papel firmado | `6a199dc` | - |
| DEC-MI-11, DC20 | Identidad del Equipo por IMEI y después serie, sin similitud; historial por identidad; corrección auditada | `c4ca1fd` | - |
| DC23AUD | Auditoría de todos los catálogos administrados | `5c0536d` y los anteriores | - |
| DEC-MI-09, DC24 | Compras como proceso propio: solicitudes manuales o sugeridas y confirmadas, órdenes de compra sin aprobación, recepciones parciales con ingreso de stock, último costo e histórico; proveedores administrados | `3434453` | - |
| DEC-MI-10, DC24LOT | Control por lote o serie; el stock existente queda como stock sin lote identificado; desperdicio y devolución; el libro valida lotes y concurrencia | `8699dbd` | - |
| DEC-MI-13, DC23 | Todos los catálogos de BR-REP-040 y DEC-MI-13 administrados con auditoría | `5c0536d`, `8699dbd`, `3434453`, `c8cd64f` | - |
| DC27B | Consultas de Órdenes, inventario, compras, reclamos, reportes y antecedentes como permisos configurables, con todos los roles como valor inicial | `c973bb0` | - |
