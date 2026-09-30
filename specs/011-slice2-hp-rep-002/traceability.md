# Traceability: HP-REP-002 (Equipo RT Interno)

Vista narrativa. La fuente machine-readable es
`traceability/hp-rep-002.yaml` (items + links, validado por
`npx tsx scripts/validate-traceability.ts traceability/hp-rep-002.yaml`).
Este documento NO la duplica: resume la cadena y explica las decisiones
que no caben en una fila de tabla del YAML.

## Por que no hay Features nuevas

HP-REP-002 reutiliza las mismas 8 Features que HP-REP-001 activa
(`FEAT-REP-001`..`008`). `traceability/hp-rep-002.yaml` las redeclara con
`implemented_scenario` como lista (`[HP-REP-001, HP-REP-002]`) porque
cada archivo de trazabilidad es autocontenido y el validador solo ve un
archivo por corrida; `traceability/hp-rep-001.yaml` no se modifica (ver
la nota de cabecera del YAML para el detalle de esta decision).

## User Story -> Feature

| US | Feature | Resumen |
|---|---|---|
| `US-REP-017` | `FEAT-REP-001` | Ingresar equipo RT sin Cliente |
| `US-REP-018` | `FEAT-REP-007` | RT no ofrece ni acepta cobro |
| `US-REP-019` | `FEAT-REP-008` | Informar resultado a Gestion RT |
| `US-REP-020` | `FEAT-REP-008` | Devolver equipo a Gestion RT |

## System Action -> Functional Requirement -> Technical Requirement

| ACC | FR | TR | Que hace |
|---|---|---|---|
| `ACC-REP-027` | `FR-REP-067`, `FR-REP-073` | `TR-REP-065`, `TR-REP-071` | Crear Orden RT sin Cliente; ruta de progreso propia |
| `ACC-REP-028` | `FR-REP-068` | `TR-REP-066` | Comprobante de recepcion por `PoliticaOrigen`, no hardcodeado |
| `ACC-REP-029` | `FR-REP-069` | `TR-REP-067`, `TR-REP-072` | No ofrecer Pago/Notificar/Entregar; `requiere_actor` en la UI |
| `ACC-REP-030` | `FR-REP-070` | `TR-REP-068` | Informar a Gestion RT (PROC-REP-290, `ACT-SYSTEM`) |
| `ACC-REP-031` | `FR-REP-071`, `FR-REP-072` | `TR-REP-069`, `TR-REP-070` | Devolver equipo sin asentar `ENTREGADA` |
| `ACC-REP-032` | `FR-REP-074` | `TR-REP-073` | Rechazar Registrar Pago en el service para Origen no `COBRABLE` |

`ACC-REP-032`/`FR-REP-074`/`TR-REP-073` se agregaron en la revision del
slice (ver `tasks.md`, Fase 7): la version inicial solo omitia
`REGISTRAR_PAGO` en `acciones_disponibles`, lo cual no bastaba -BR-REP-017
exige que el backend lo garantice, no solo la UI-.

## Decisiones que el grafo no puede expresar por si solo

- **PROC-REP-290 es `actor: ACT-SYSTEM`, no "rol humano sin definir"**:
  `informar_resultado_rt` no recibe `Usuario`; el historial de ese paso
  queda con `usuario_id: null`. Esto exigio una dimension nueva en
  `AccionDisponible`/`AccionOut` (`requiere_actor: bool`, default
  `true`) para no seguir usando `roles: ()` con dos significados
  distintos: "el negocio no definio el rol" (Registrar Pago antes de
  BR-REP-017, sigue siendo una accion humana) vs. "no hay ningun actor
  humano que autorizar" (un nodo `ACT-SYSTEM`). `TR-REP-067` y
  `TR-REP-068` documentan esta distincion; `TR-REP-072` la propaga al
  frontend.
- **Estado terminal `PENDIENTE_DE_DEFINIR`**: `devolver_equipo_rt` fija
  `current_process = "EVT-REP-999"` pero NO `estado_workflow =
  ENTREGADA`, porque V1.3 deja ese estado explicitamente sin definir
  (`business/scenarios/repair-management-scenarios-v1.3.yaml`,
  `HP-REP-002.expected.terminal_state`). `acciones_disponibles` detecta
  el fin de proceso por `current_process == "EVT-REP-999"` ademas de
  `estado_workflow == ENTREGADA` (`TR-REP-070`), para no dejar acciones
  abiertas sobre una Orden terminada.
- **Registrar Pago rechazado en el service, no solo omitido en la UI**:
  `PoliticaOrigen.condicion_comercial != COBRABLE` hace que
  `registrar_pago` lance `PrecondicionInvalidaError` (409) sin importar
  quien lo invoque -service directo, comando de aplicacion o HTTP-. La
  UI seguia sin ofrecer el boton desde la implementacion inicial, pero
  eso por si solo no era una garantia de backend (`TR-REP-073`).
- **PROC-REP-270 SI exige un actor humano real**: a diferencia de
  PROC-REP-290, el Business Process declara `actor: ACT-ADMIN` con
  `actores_alternativos: [ACT-RECEP]`. `devolver_equipo_rt` ya lo
  respetaba desde su implementacion inicial (`Usuario` obligatorio,
  `validar_alguno_de(usuario, ROLES_ENTREGA)`, `usuario_id` real en el
  historial); la verificacion posterior a la Fase 7 (ver `tasks.md`,
  Fase 8) confirmo que la correccion de PROC-REP-290 no se le habia
  aplicado por error, y agrego la cobertura de test que faltaba
  (`TEST-REP-251`..`TEST-REP-255`) sin cambiar codigo de produccion.

## Internal Tests (33 nuevos: 19 de la implementacion inicial + 9 de la revision + 5 de la verificacion de actores)

Ver `traceability/hp-rep-002.yaml` (`TEST-REP-223`..`TEST-REP-255`) para
el mapeo completo `test -> FR/TR/Code`. Resumen por archivo:

| Archivo | Tests | Verifica |
|---|---|---|
| `tests/test_hp_rep_002.py` | 23 | Flujo service-level completo, negativos (Pago, actor de PROC-REP-290/270, orden de cierre) y representacion comercial |
| `tests/test_api_hp_rep_002.py` | 9 | E2E por HTTP, regresion cruzada con `CLIENTE_EXTERNO`, rechazo de Pago por HTTP, actor de PROC-REP-270 por HTTP |
| `tests/test_repositories_json.py` | 1 | Compatibilidad JSON (`referencia_rt` ausente en Ordenes anteriores) |

Total: 349 tests (316 baseline de MVP v2 Foundation + 33 de este
slice), todos en verde.

## UAT

| UAT | Acepta | Estado |
|---|---|---|
| `UAT-REP-017` | `US-REP-017` | `PENDING` |
| `UAT-REP-018` | `US-REP-018` | `PENDING` |
| `UAT-REP-019` | `US-REP-019` | `PENDING` |
| `UAT-REP-020` | `US-REP-020` | `PENDING` |

Ningun UAT se marca aprobado: no hubo ronda formal de aceptacion de
negocio. Los internal tests demuestran comportamiento, no aceptacion de
usuario.
