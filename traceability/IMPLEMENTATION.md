# Trazabilidad implementada — HP-REP-001

Este documento describe **lo que ahora existe** de trazabilidad en el
repositorio. Complementa a [`README.md`](./README.md), que define la
**convencion de IDs y la jerarquia** y que fue escrito cuando todavia no
habia ninguna implementacion.

> **Nota de reconciliacion**: los README generales -raiz, backend y
> frontend- ya fueron reconciliados con el estado real. Queda
> `traceability/README.md`, que se conserva deliberadamente como el
> documento de **convencion de IDs y jerarquia**: su contenido normativo
> sigue vigente, y lleva al principio un aviso de que sus afirmaciones
> sobre "no hay implementacion todavia" quedaron desactualizadas.

## Que se agrego

| Artefacto | Ruta |
|---|---|
| Constitution del proyecto | `.specify/memory/constitution.md` |
| Especificaciones por Feature activa | `specs/001-…/` … `specs/008-…/` |
| Grafo machine-readable (items + links) | `traceability/hp-rep-001.yaml` |
| Validador de integridad | `scripts/validate-traceability.ts` |

## Alcance: slice, no Feature

La distincion mas importante de todo este material:

```text
feature_status           = draft        -> estado de la Feature V1.3
implemented_scenario     = HP-REP-001
implemented_slice_status = IMPLEMENTED  -> estado del slice, no de la Feature
```

**Ninguna `FEAT-REP-XXX` esta implementada.** Lo implementado es el
recorrido que el Scenario `HP-REP-001` ejercita dentro de cada Feature.
`FEAT-REP-009` (Cancelacion) no esta activa en el Happy Path, por lo que
no tiene spec.

El validador falla explicitamente si algun item de tipo `feature` se
declara `IMPLEMENTED`.

## Estructura del grafo

`traceability/hp-rep-001.yaml` implementa la decision de diseño que
`README.md` ya habia tomado: **items + links**, nunca anidamiento rigido,
para poder representar relaciones N:M.

```yaml
items:
  - {id: FR-REP-027, type: functional_requirement, name: …, status: …}
links:
  - {from: TR-REP-033, to: FR-REP-027, relationship: satisfies}
```

Cada item declara al menos `id`, `type`, `name` y `status`; los items de
codigo y de test declaran ademas `source` (archivo + simbolo, o archivo +
funcion). Cada link declara `from`, `to` y `relationship`.

### Niveles presentes

| Nivel | Tipo | Cantidad |
|---|---|---|
| Business Domain | `business_domain` | 1 |
| Business Process | `business_process` | 1 |
| Scenario | `scenario` | 1 |
| Feature | `feature` | 9 |
| Event | `business_event` | 2 |
| Process Node | `process_node` | 56 |
| Business Rule | `business_rule` | 18 |
| User Story | `user_story` | 16 |
| System Action | `system_action` | 26 |
| Functional Requirement | `functional_requirement` | 60 |
| Technical Requirement | `technical_requirement` | 50 |
| Data Model / Arquitectura | `data_model_artifact` | 13 |
| Task | `task` | 141 |
| Code / Artifact | `code_artifact` | 103 |
| Internal Test | `internal_test` | 175 |
| UAT | `uat` | 16 |

Los nodos del Business Process incluyen tanto los 31 que `HP-REP-001`
recorre (`in_scenario: true`) como los 25 que las Features declaran y el
Happy Path **no** recorre (`in_scenario: false`, `implemented: false`),
para que los gaps sean navegables dentro del mismo grafo.

### Vocabulario de relaciones

Declarado en `meta.relationship_vocabulary` y verificado por el
validador: `belongs_to`, `activates`, `realizes`, `covers`,
`governed_by`, `derives_from`, `satisfies`, `supports`, `implements`,
`produced_by`, `exercises`, `verifies`, `accepts`.

### El modelo de datos es transversal

Los `data_model_artifact` se enlazan con `supports` hacia Functional
Requirements **y** Technical Requirements a la vez, en N:M, tal como
`README.md` anticipaba. No ocupan un nivel fijo de la cadena.

### Capacidades transversales sin nodo de proceso

Tres System Actions no corresponden a ningun `PROC-REP-*` y lo declaran
explicitamente (`transversal: true`, `process_node: null`):

- `ACC-REP-003` — registrar el recorrido en el historial.
- `ACC-REP-020` — **Registrar Pago** (`FEAT-REP-007`, `BR-REP-017-A`).
  `HP-REP-001` la recorre como paso `kind: FUNCTIONAL_ACTION`. **No se le
  invento un `PROC-REP-*`.**
- `ACC-REP-023` — mantener derivada la situacion comercial.

Emisiones de documentos a pedido (MVP v2), tambien sin nodo propio:

- `ACC-REP-002` — **version nueva del comprobante de recepcion** a pedido
  de Recepcion (la primera la emite el proceso en `PROC-REP-060`).
- `ACC-REP-060` — **Emitir comprobante de autorizacion de reparacion**,
  documentado en `traceability/mvp-v2-comprobante-autorizacion.yaml` con
  `pending_formalization` (ver "Deuda de trazabilidad").
- `ACC-REP-026` conserva exclusivamente su significado documentado (la
  entrega del equipo): ningun documento se emite con ese id.

## Validacion

```bash
npm run validate:traceability    # solo el grafo de trazabilidad
npm run validate:all             # validate:v1.3 + validate:traceability
```

El validador esta escrito en TypeScript sobre `tsx`, igual que
`validate-process.ts`, `validate-features.ts`, `validate-references.ts` y
`validate-scenarios.ts`. **Justificacion**: el repositorio ya valida todo
artefacto de negocio con scripts `tsx` bajo `scripts/`, ya depende de
`yaml` y `tsx` en `package.json`, y los expone a todos por
`npm run validate:*`. Mantener el validador de trazabilidad en el mismo
lugar y el mismo lenguaje deja una sola superficie de validacion para
todo el repositorio, sin dependencias ni runtimes nuevos. El lado Python
del repositorio es la aplicacion backend, cuyo harness (`pytest`) verifica
comportamiento, no integridad de artefactos: otra responsabilidad.

### Que comprueba

1. IDs unicos.
2. Links sin referencias rotas y con `relationship` dentro del vocabulario.
3. Toda User Story pertenece a una Feature.
4. Toda System Action realiza al menos una User Story, salvo las que
   declaran `pending_formalization: <motivo>`: capacidades implementadas
   cuya User Story todavia no esta definida formalmente en `business/`.
   No se ocultan: el validador las informa como advertencia con su motivo.
5. Todo Functional Requirement deriva de al menos una System Action.
6. Todo Technical Requirement satisface al menos un Functional
   Requirement, salvo los marcados `cross_cutting: true`.
7. Todo Code artifact esta vinculado a una Task y/o un Technical
   Requirement.
8. Todo Internal Test se relaciona con un Code artifact, un Functional
   Requirement o un Technical Requirement, y declara su `source`.
9. Toda Task `DONE` implementa al menos un Technical Requirement. Las
   Task `NOT_IMPLEMENTED` pueden quedar sin links **a proposito**: son el
   registro explicito de los gaps.
10. Los UAT pueden —y deben— estar `PENDING`. Un UAT en cualquier otro
    estado se reporta, porque no hubo ronda de aceptacion formal.
11. Higiene de cobertura: ninguna Feature puede declararse
    `IMPLEMENTED`; debe declarar `feature_status` e
    `implemented_slice_status` por separado.

## UAT: ninguno aprobado

Los 16 `UAT-REP-XXX` estan en `PENDING`. **Los 218 tests internos en
verde no son evidencia de aceptacion de usuario** (Constitution,
Principio IX). No ha ocurrido ninguna ronda de UAT formal sobre esta
baseline.

## Estado de cobertura

| Metrica | Valor |
|---|---|
| Tasks con evidencia real de codigo + test (`DONE`) | 86 / 141 |
| Tasks `NOT_IMPLEMENTED` (gaps declarados) | 55 / 141 |
| Features con slice implementado | 8 / 9 |
| Features implementadas por completo | **0 / 9** |
| UAT aprobados | **0 / 16** |

## Iteracion de reconciliacion (prueba manual del MVP)

Cambios funcionales que surgieron de probar el MVP desde el navegador.
Todos se reflejaron primero en `business/` y despues en el codigo.

### Actores alternativos por nodo

PROC-REP V1.3 declaraba un unico `actor` por nodo y no tenia forma de
representar autorizacion alternativa. Se agrego un campo OPCIONAL y
retrocompatible al schema del Business Process:

    actor: ACT-COORD
    actores_alternativos: [ACT-RECEP]

Un nodo sin el campo admite unicamente su `actor`, asi que ningun nodo
existente cambia. No hay jerarquia entre ellos: `actor` es el actor
historico y el que recorre HP-REP-001.

Es un mecanismo generico, no una excepcion para un nodo: lo validan
`validate-references.ts` (actor inexistente y actor repetido), lo
muestra el viewer, y el backend lo resuelve con
`app.services.autorizacion.validar_alguno_de`.

Aplicado a dos nodos:

- `PROC-REP-150` (definir prioridad): ACT-COORD **o** ACT-RECEP.
- `PROC-REP-270` (entregar equipo): ACT-ADMIN **o** ACT-RECEP. La
  condicion comercial NO cambia: `REPARACION_LISTA` + saldo 0 se exigen
  igual, para cualquiera de los dos actores.

### Tipo de Pago

`Pago` gana `tipo_pago` (ANTICIPO / PAGO), dimension distinta de
`metodo` (EFECTIVO, TRANSFERENCIA, ...). No lo elige el usuario: se
deriva del estado de la Orden al registrarlo. Da soporte real a la
capacidad transversal de BR-REP-017, que ya permitia cobrar antes de la
fase de cierre. `PROC-REP-265` sigue evaluandose solo en el cierre: un
anticipo no lo dispara.

### Nombre del Tipo de Reparacion

El DTO del Detalle expone `tipo_reparacion_nombre`, resuelto al leer
contra el catalogo vigente igual que `insumos_previstos`. NO se agrega
al modelo persistido: el JSON de la Orden sigue guardando solo el ID.

### Traza de las capacidades transversales

`ACC-REP-020` (Registrar Pago) ahora deja entrada en el historial de la
Orden. Antes no dejaba ninguna, y el recorrido mostraba `PROC-REP-266`
seguido de `PROC-REP-265` sin explicar que habia pasado entre ambos.

Cada entrada declara su clase:

    tipo_referencia: PROCESS_NODE       referencia_id: PROC-REP-266
    tipo_referencia: FUNCTIONAL_ACTION  referencia_id: ACC-REP-020
    tipo_referencia: PROCESS_NODE       referencia_id: PROC-REP-265

La accion transversal **no mueve `current_process`** y **no marca
progreso** en HP-REP-001: no pertenece al recorrido. Son dos helpers
distintos en `services/workflow.py` -`registrar_paso` para nodos,
`registrar_accion_funcional` para capacidades- y pasar un `ACC-REP-*`
por el primero dejaria `current_process = ACC-REP-020`, que es falso.

La entrada enlaza al Pago que la origino (`pago_id`) y guarda una
observacion legible con tipo, medio e importe, para que el significado
se recupere sin ir a buscar el Pago ni depender del frontend.

Retrocompatibilidad: el campo acepta el nombre historico `process_id` al
construirse y al validar JSON, asi que las Ordenes ya persistidas se
cargan sin migracion y quedan como `PROCESS_NODE`.

### Pendiente registrado, no implementado

Auto-ingreso a cola (TASK-REP-147, `NOT_IMPLEMENTED`): cuando una Orden
queda HABILITADA podria pasar sola a EN_COLA con prioridad por defecto.
Alteraria el recorrido de HP-REP-001 -`PROC-REP-150` dejaria de ser una
accion humana obligatoria del Scenario-, asi que queda fuera de alcance
hasta modelarlo como variante.

## Compatibilidad de persistencia del MVP

**Decision explicita: los datos JSON locales del MVP son descartables. No
se garantiza compatibilidad hacia atras para Ordenes persistidas antes de
`mvp-reconcile`.**

- `HistorialWorkflow` **si** mantiene compatibilidad: acepta el nombre
  historico `process_id` al construirse y al validar JSON, y esas
  entradas se cargan como `PROCESS_NODE`. No hace falta migrar nada.
- `Pago.tipo_pago` **no** hace backfill automatico y es obligatorio. Una
  Orden guardada antes de esta version, con pagos que no lo traen, falla
  al cargarse.
- **No se agrega un default** como `tipo_pago = PAGO`. Desde el objeto
  `Pago` no se puede inferir si aquel cobro fue un ANTICIPO o el PAGO del
  cierre -eso depende del estado que la Orden tenia en ese momento-, y
  completarlo a ciegas seria trazabilidad falsa: exactamente lo que el
  Principio V de la constitution prohibe.
- Para el MVP se espera **recrear o resetear** los datos locales
  generados con versiones anteriores (borrar `data/ordenes/*.json`).
- Esto debera resolverse con migraciones reales cuando exista una
  persistencia estable o una base de datos. Hoy no la hay.

## Divergencias entre baseline funcional y modelado tecnico

Diferencias entre lo que `business/` define y lo que el modelado tecnico
previo dejo implementado. Siguiendo el Principio V de la constitution,
se REPORTAN: el requerimiento no se reescribe para que coincida con el
codigo, y el codigo no se toca desde esta rama.

### Catalogo de tipos de movimiento de insumo

`TipoMovimientoInsumo.DEVOLUCION` fue incorporado durante el modelado
tecnico inicial, pero no esta respaldado por PROC-REP V1.3. En sentido
inverso, `PROC-REP-210` y `BR-REP-005` contemplan `DESPERDICIO`,
actualmente ausente del enum.

La divergencia debe reconciliarse; el comportamiento de desperdicio sigue
fuera del slice implementado por HP-REP-001, que solo recorre `RESERVA`,
`CONSUMO` y `LIBERACION_RESERVA`.

Trazado como TASK-REP-089 (`NOT_IMPLEMENTED`), con TASK-REP-090
dependiendo de su resolucion. Es una decision de negocio sobre la
baseline funcional, no una tarea de implementacion.

### Otras divergencias registradas

- `PROC-REP-186` — `BR-REP-006` define que ante reserva fallida el
  Detalle queda `PENDIENTE` + `BLOQUEADO_POR_RECURSOS` y la Orden se
  recalcula. El codigo lanza un error de dominio sin ejecutar ese
  comportamiento. La invariante "sin movimientos parciales" si se
  cumple. Trazado como TASK-REP-086.
- `BR-REP-011-A` item (1) "sesion activa" — no hay gestion de sesion; se
  aproxima con rol + usuario activo. Documentado como interpretacion
  explicita en `specs/004-feat-rep-004-hp-slice/plan.md`.
- `BR-REP-017` — no define que rol puede registrar un Pago. El codigo lo
  declara pendiente funcional y solo valida usuario activo. Requiere
  decision de negocio.
- `BR-REP-015` — menciona precio configurable con historico; el catalogo
  guarda solo el precio vigente. El snapshot en el Detalle funciona.
- `BR-REP-017-A` — menciona catalogo configurable de medios de pago y
  referencia/comprobante; ninguno implementado.
- `PROC-REP-280` — describe un comprobante con desglose completo; el
  codigo registra el hecho "generado + fecha".
- `BR-REP-012` — el resolver implementa solo la regla de prioridad 2 de
  las 7, coherente con el fail-safe que la propia regla exige.

### Deuda de trazabilidad: IDs de System Action del historial

El backend registra algunas acciones funcionales con `ACC-REP-*` que en
los archivos de trazabilidad significan otra cosa. Estan **pendientes de
conciliacion con `rt-rma-app`** y no se reasignan todavia (tampoco se
asignan `ACC-REP-061` a `ACC-REP-066`):

| ID | En el codigo (historial) | En la trazabilidad |
|---|---|---|
| `ACC-REP-021` | Anular un pago | Determinar el importe a cobrar y el saldo y validar la condicion de entrega |
| `ACC-REP-022` | Devolver dinero al cliente | Registrar que la entrega queda bloqueada por saldo pendiente |
| `ACC-REP-023` | Registrar o corregir los datos del ingreso | Mantener derivados el importe a cobrar, lo pagado, el saldo y el estado de cobro |
| `ACC-REP-024` | Confirmar la recepcion fisica | Determinar que la Orden requiere entrega y notificar al cliente |
| `ACC-REP-025` | Agregar una observacion de recepcion | Generar el comprobante final y la garantia de reparacion |
| `ACC-REP-027` | Registrar equipo no recibido | Crear la Orden de origen RT_INTERNO |
| `ACC-REP-028` | Revalidar recursos desde Inventario | Determinar segun la politica del Origen si corresponde comprobante de recepcion |

`ACC-REP-026` ya se concilio: la emision de documentos usa `ACC-REP-002`
(recepcion) y `ACC-REP-060` (autorizacion). `ACC-REP-060` queda con
`pending_formalization` hasta incorporar a `business/` la autorizacion del
cliente por Detalle, hoy definida solo en la baseline V1.4 de
`rt-rma-app`.

## Iteracion 1 del UAT (mvp-v2): reglas que cambian

Mejoras del primer UAT implementadas en `mvp-v2`. Ninguna crea User
Stories, nodos de proceso ni IDs nuevos: reutilizan los existentes con el
mismo significado y dejan registradas aca las diferencias con
`business/` (PROC-REP V1.3) y con la baseline V1.4 de `rt-rma-app`, que
quedan **pendientes de formalizacion** (no se modifica `rt-rma-app`).
`ACC-REP-061` a `ACC-REP-066` siguen sin asignar.

### Ingreso inicial simplificado de CLIENTE_EXTERNO (UAT-008)

- Recepcion crea la Orden, carga los trabajos con su precio y genera el
  comprobante de ingreso y autorizacion
  (`application/ingreso_inicial.py::generar_comprobante_ingreso`). Un solo
  comando compone, en memoria y con un unico guardado: confirmacion fisica
  (`ACC-REP-024`), `PROC-REP-050`/`060` (marca del comprobante),
  factibilidad y habilitacion (`080`/`090`/`140`), la decision del cliente
  por Detalle (`046`/`047`, canal elegido, observacion "Autorizacion
  inicial en el ingreso"), la emision del documento (`ACC-REP-060`,
  `OR-xxxxxx-ING-01`) y la entrada a la cola (`150` -> `170`).
- Aplica solo a la politica que exige confirmacion fisica y autorizacion
  del cliente, en REQUERIMIENTO con la definicion abierta
  (`services/reparaciones.py::es_ingreso_inicial`). RT_INTERNO, garantia
  RMA y el camino de revision conservan su circuito.
- En ese paso la UI ya no ofrece "Confirmar la recepcion" ni "Finalizar la
  definicion" (`acciones.py`), y la API tampoco los acepta por separado:
  confirmar la recepcion, finalizar la definicion y registrar la
  autorizacion inicial responden 409 sin efectos mientras la Orden esta en
  el ingreso inicial (`services/reparaciones.py::exigir_fuera_del_ingreso_inicial`).
  Siguen vigentes para RT_INTERNO, garantia RMA, el camino de revision y
  las autorizaciones posteriores.
- El comprobante de ingreso exige al menos un trabajo y el estado fisico.
  Desde UAT-009 no pide ni lleva el check-in (ver "Check-in antes de la
  entrega"); una Orden anterior con la recepcion ya confirmada lo genera
  sin pasos adicionales.
- Presentacion derivada, sin estados nuevos: `OrdenOut.ingreso_inicial`,
  `DetalleOut.pendiente_comprobante_ingreso` y `autorizado_en_ingreso`
  (la definicion vigente es la que autorizo el comprobante). La UI muestra
  "Pendiente de comprobante de ingreso" y, generado, "Autorizado"; una
  autorizacion posterior conserva su representacion.
- **Divergencia**: PROC-REP V1.3 emite el comprobante de recepcion en
  `PROC-REP-060`; en este camino la marca del nodo queda pero el documento
  es el de ingreso (sin documentos redundantes). Las autorizaciones
  posteriores siguen el circuito explicito.

### Entrada automatica a la cola con prioridad 4

- Tras el comprobante de ingreso (o al volver a ser factible si quedo
  esperando repuestos), `PROC-REP-150` se registra con observacion
  "4 (predeterminada)" y la Orden pasa a EN_COLA
  (`application/cola.py::encolar_si_ingreso_automatico`).
- **Divergencia**: en V1.3 `PROC-REP-150` es de ACT-COORD. Solo se
  automatiza para Ordenes con comprobante de ingreso; extenderlo a
  RT_INTERNO y garantia RMA es una **decision pendiente**.
- Cambiar la prioridad despues es otra accion: `ACC-REP-007` ("Asignar la
  prioridad de ejecucion de la Orden", mismo significado) como
  FUNCTIONAL_ACTION `CAMBIAR_PRIORIDAD`, con observacion
  "anterior -> nueva (Nombre): motivo". Roles: TECNICO, COORDINADOR_RMA y
  RECEPCION; en cola o en reparacion. No vuelve a encolar.

### Liberar una Orden tomada por otro tecnico

- Ajusta la decision E2 (toma exclusiva del titular): otro tecnico o
  Coordinacion la puede liberar con motivo y confirmacion explicita
  (409 `CONFIRMACION_REQUERIDA` sin ella). Si hay una Ejecucion en curso se
  interrumpe con la logica de `PROC-REP-210` (lo usado se consume, lo
  reservado vuelve) antes de `PROC-REP-213` -> `170`.
- Trazabilidad: `TomaOrden.liberada_por` y `motivo_liberacion`, y la
  observacion de `PROC-REP-213` con titular, quien libera, estacion, motivo
  y el estado de la Orden y de cada trabajo. El titular libera como
  siempre. El aviso (y el 409 `CONFIRMACION_REQUERIDA`) dice quien la tiene
  y, con una reparacion en curso, que se interrumpe, que lo utilizado se
  consume y que lo reservado sin usar se libera. **Pendiente**: formalizar
  la enmienda de E2.

### Descuento comercial

- Porcentaje o importe fijo con motivo, por RECEPCION o ADMINISTRADOR
  (`services/descuentos.py`). Total = Subtotal - descuento; el precio
  snapshot de cada Detalle no cambia. Se rechaza si supera su base o deja
  el total por debajo de lo ya cobrado. Auditoria en la entidad
  (`OrdenReparacion.descuentos`: tipo, valor, motivo, usuario, fecha, con
  cada cambio y retiro), visible en Cobros como "Historial de descuentos".
  No entra al historial del proceso: no hay un ID de accion con ese
  significado y `ACC-REP-061` a `066` siguen reservados (**pendiente** de
  formalizar junto con `TASK-REP-118`/`125`).
- **Divergencia**: `BR-REP-016` reserva la cortesia a ACT-ADMIN; el
  descuento por Recepcion no esta en `business/`.

### Trabajo "Otros — Reparacion no tipificada"

- Tipo reservado del sistema `TR-OTROS` (no es una fila del catalogo):
  descripcion y precio manual por Detalle, puntaje 0, sin insumos
  previstos y cualquier estacion. Se nombra "Otros: <descripcion>" en
  lecturas y documentos.
- **Divergencia**: `BR-REP-015` toma el precio del catalogo. La futura
  tabla de configuracion de tipos reemplazara el tipo reservado.

### Garantia por Detalle segun el check-in

- `DatosRecepcion.checkin`: con check-in 90 dias, sin check-in 30
  (`domain/garantia.py`), sobre cualquier plazo del Tipo. Se guarda la
  sugerida (`garantia_dias_sugerida`) y la definitiva (`garantia_dias`);
  RECEPCION o COORDINADOR_RMA la ajustan con motivo antes de la entrega
  (`ajustes_garantia`). Sin dato de check-in rige el catalogo. El
  vencimiento sigue corriendo desde la entrega (`vencimiento_garantia`).
- **Divergencia**: el plazo deja de ser el del catalogo cuando hay
  check-in.

### Check-in antes de la entrega (UAT-009)

- El check-in (si se pudieron verificar las funciones basicas del equipo)
  sale del ingreso y pasa al cierre. Mismo dato (`DatosRecepcion.checkin`),
  sin un concepto nuevo: el alta, la correccion del ingreso y el
  comprobante de ingreso ya no lo reciben (la correccion conserva el que
  haya) y el comprobante de ingreso no lo lleva.
- Se registra con la reparacion lista -todos los trabajos terminados y
  aprobados en control- y antes de entregar
  (`services/garantias.py::registrar_checkin_de_entrega`,
  `POST /api/orders/{id}/checkin`, accion `REGISTRAR_CHECKIN`). Roles: los
  de la entrega (RECEPCION y ADMINISTRADOR). Se puede volver a registrar
  hasta entregar; repetir el mismo resultado no agrega nada. Quien y cuando
  quedan en `RecepcionEquipo.registros_checkin` (append-only).
- Reasigna la garantia de cada Detalle no cancelado (90/30) con
  `reaplicar_garantia_sugerida`: actualiza la sugerida y la definitiva
  solo si no hay un ajuste manual (antes o despues del check-in, el
  ajuste nunca se pisa). Hasta el check-in rige el plazo del Tipo.
- Politica del Origen `requiere_checkin_en_entrega` (solo CLIENTE_EXTERNO):
  con trabajos realizados, la entrega lo exige
  (`exigir_checkin_para_entrega`, 409 sin efectos); `ENTREGAR` se publica
  con `bloqueo` "Falta registrar el check-in". Avisada y saldada, la
  situacion operativa es `PENDIENTE_CHECKIN` ("Pendiente de verificacion de
  funciones basicas", color de advertencia) con las dos tareas: es solo
  presentacion, el workflow sigue en `REPARACION_LISTA`. Sin trabajos
  realizados (sin reparacion), RT_INTERNO y la garantia RMA no cambian.
- Notificar y cobrar no dependen del check-in; el aviso al cliente no
  menciona la garantia, y la vista previa del comprobante final y de la
  garantia muestra los plazos "A confirmar con el check-in" hasta
  registrarlo. No es un nodo del proceso ni entra al historial: no hay un
  ID de accion con ese significado y `ACC-REP-061` a `066` siguen
  reservados. Se acepta temporalmente su auditoria en la recepcion
  (`registros_checkin`), **pendiente** de formalizacion funcional.
- El comprobante final (`COMPROBANTE_ENTREGA`) lleva el resultado del
  check-in (`checkin`) y, por trabajo realizado, la garantia definitiva y
  su vencimiento desde la entrega (`garantia_dias`, `garantia_vence`). La
  garantia (`GARANTIA`) no cambia.
- Ordenes anteriores: el check-in registrado al ingresar sigue valiendo
  (cumple la exigencia de la entrega y se puede volver a registrar); los
  comprobantes de ingreso ya emitidos conservan su check-in.
- **Divergencia**: en V1.4 de `rt-rma-app` y en la iteracion 1 el check-in
  era del ingreso; queda **pendiente de formalizacion**.

### Observaciones visibles y notas internas

- `DatosRecepcion.observaciones` son visibles y salen en los comprobantes;
  `DatosRecepcion.notas_internas` y las notas con `interna: true` son solo
  para el personal y no salen en ningun documento ni PDF.

### Compatibilidad

Los campos nuevos tienen valor por defecto: las Ordenes ya guardadas se
leen sin migracion (sin check-in, sin registros de check-in, sin
descuento, sin notas internas; un comprobante final anterior, sin la
garantia por trabajo).

## UAT-010: busqueda de clientes por DNI y fotos del equipo (mvp-v2)

Sin IDs nuevos ni nodos de proceso: capacidades de la Recepcion y del
taller, **pendientes de formalizacion** en `business/`.

### Entidad Cliente: id, DNI y nombre y apellido

- `Cliente`: `id` interno (la identidad; nunca el DNI), `dni` (opcional,
  solo digitos, 7 u 8, normalizado), `nombre_apellido`, `telefono` y
  `email`. `nombre_apellido` es el nombre completo exactamente como lo
  carga Recepcion o lo devuelve una fuente autorizada: no se separa en
  nombre y apellido. Es lo que muestran la pantalla, el listado, los PDF,
  los documentos y el mensaje de WhatsApp.
- Compatibilidad de lectura: las Ordenes y los documentos anteriores
  guardaron el nombre completo en `nombre`; se leen tal cual en
  `nombre_apellido` (`Cliente._desde_estructura_anterior`), sin migrar los
  archivos. Al volver a guardar una Orden se escribe con la clave nueva:
  el texto no cambia (los documentos emitidos conservan su dato). Una
  version anterior del backend no leeria esos archivos: en el UAT los
  datos se pierden con cada despliegue, asi que no afecta; antes de tener
  datos persistentes conviene decidir si se necesita volver atras.
- Compatibilidad de escritura: la API acepta tambien la clave anterior
  `nombre` al crear (alias de entrada de `ClienteIn`; si vienen las dos,
  manda `nombre_apellido`). La salida solo tiene `nombre_apellido`.
- Sin duplicados: un DNI que ya es de un cliente no crea otro (409
  `CLIENTE_EXISTENTE`, `services/clientes.py::cliente_para_orden`); se
  reutiliza enviando su `id` (los datos pueden traer correcciones, que
  quedan en la Orden nueva; las anteriores conservan lo que se registro).
  Reutilizado con un DNI que nadie mas tiene, es una correccion del DNI.
  La comprobacion corre en la seccion critica del alta: dos altas
  simultaneas no duplican. El formulario busca el DNI en nuestra base
  (`externa=false`) antes de crear; si esa busqueda falla, crea igual. Sin
  DNI no hay como reconocerlo (no se compara por nombre). No hay
  vinculacion silenciosa por DNI.
- Hacia PostgreSQL: tabla `clientes` (`id` PK de texto, `dni` varchar(8)
  NULL, `nombre_apellido` varchar(200) NOT NULL, `telefono`, `email`,
  fechas) con indice unico parcial sobre `dni` (WHERE dni IS NOT NULL).
  **Pendiente**: antes de crear ese indice hay que resolver los DNI
  duplicados historicos (hoy la busqueda los muestra como AMBIGUO y se
  puede reutilizar cualquiera). Las Ordenes referencian `cliente_id` y los
  documentos conservan su copia del cliente. Una fuente autorizada por DNI
  (`FuentePersonas`) devuelve `nombre_apellido` tal cual.

### Busqueda por DNI

- La carga manual sigue valiendo; un DNI invalido se rechaza (409). La
  busqueda nunca bloquea el alta: sin datos, con la fuente caida o sin
  fuente habilitada, se carga a mano.
- `GET /api/clients/lookup?dni=&usuario_id=&externa=` (RECEPCION o
  ADMINISTRADOR): primero nuestras Ordenes
  (`services/clientes.py::clientes_con_dni`: un cliente ya conocido, o
  AMBIGUO si hay mas de uno); solo si no esta, `externa` no es `false` y
  hay una fuente externa AUTORIZADA configurada, esa fuente
  (`app/integraciones/personas.py::FuentePersonas`), con limite de
  consultas (`LimitadorConsultas`: intervalo minimo y maximo por minuto) y
  sin guardar nada. La busqueda nunca completa el formulario sola:
  Recepcion revisa, corrige y elige; al reutilizar un cliente conocido la
  Orden nueva queda con su mismo ID.
- **Fuente externa: ninguna habilitada.** CUIT Online
  (`/search/{dni}`): no publica una API ni condiciones para consultas
  automatizadas (busqueda del 21/10/2026: solo herramientas de terceros
  que extraen su pagina, que no son una autorizacion del sitio).
  `robots.txt` no excluye `/search/` (pide `Crawl-delay: 2`), pero el
  nombre de cada resultado llega codificado en el HTML (`div.hit
  h2.denominacion`, dentro de `paywalled-content`) detras de un muro de
  pago medido (Pigeon, con huella del navegador y creditos). Obtener el
  nombre en claro exigiria eludir ese control (decodificarlo, emular el
  navegador o leerlo de un metadato de un enlace a `/constancia/`, ruta
  excluida por `robots.txt`), asi que **no se implementa**. Para
  habilitar una fuente hace falta: una autorizacion escrita o un acceso
  por API contratado con CUIT Online, o el padron de ARCA por web service
  (`ws_sr_padron_a13`: `getIdPersonaListByDocumento` da el CUIT a partir
  del DNI y `getPersona` sus datos; requiere certificado digital, el
  servicio autorizado para la CUIT de la empresa en ARCA y su
  autenticacion WSAA). Alternativa sin terceros: leer el codigo PDF417 del
  DNI que presenta el cliente.

### Fotos del equipo (UAT-010/011)

- `OrdenReparacion.fotos`: solo los datos de cada foto (`FotoOrden`: clave
  del objeto, tipo, tamano, usuario y fecha); la imagen nunca va al JSON ni
  al disco efimero de Cloud Run. Opcionales y solo con la Orden ya creada
  (el alta no las pide); las suben RECEPCION, TECNICO, COORDINADOR_RMA o
  ADMINISTRADOR en una Orden abierta y todos las ven (tambien cerrada).
- Hasta **10 por Orden** (`MAX_FOTOS_POR_ORDEN`; la pantalla aplica el
  mismo tope y muestra "X de 10"). "Tomar foto" abre la camara del
  celular; "Elegir fotos" permite varias. Antes de subir, cada foto se ve
  en una vista previa y se acepta o se descarta: solo se suben las
  aceptadas. Las guardadas se ven en miniatura, se abren ampliadas y
  muestran quien y cuando.
- `POST /api/orders/{id}/photos?usuario_id=` (cuerpo: la imagen; JPEG, PNG
  o WebP verificados por contenido; hasta 8 MB) y
  `GET /api/orders/{id}/photos/{foto_id}` (una foto solo se sirve desde su
  Orden). El navegador reduce cada foto a 1600 px de lado mayor en JPEG
  antes de subirla.
- Almacenamiento (`app/storage/fotos.py`): `RMA_FOTOS_BUCKET` -> bucket
  PRIVADO de Cloud Storage via API JSON con el token de la cuenta de
  servicio de Cloud Run (sin dependencias nuevas). En el UAT:
  `rt-rma-uat-fotos` (southamerica-east1, acceso uniforme, prevencion de
  acceso publico, sin reglas de borrado automatico); la cuenta del
  servicio solo tiene `roles/storage.objectUser` sobre ese bucket.
  Validado contra el bucket real (22/10/2026): carga, lectura con los
  mismos bytes, tope de 10, archivo invalido, acceso anonimo rechazado y
  archivos conservados despues de reiniciar Cloud Run;
  `RMA_FOTOS_DIR` -> directorio local, solo desarrollo; sin ninguno, las
  fotos quedan deshabilitadas y la UI lo indica. La imagen se sube fuera
  de la seccion critica de Ordenes: si el registro posterior fallara queda
  un objeto huerfano en el bucket, nunca una referencia rota.
- Imagenes huerfanas: `POST /api/maintenance/photos/cleanup?usuario_id=&aplicar=`
  (ADMINISTRADOR; sin `aplicar=true` solo informa). Lista el bucket,
  despues lee las Ordenes y borra solo lo que ninguna Orden usa y tiene mas
  de una hora (una subida en curso nunca se toca). Permisos necesarios en
  el bucket: crear, leer, listar y borrar objetos.
- **Limitacion del UAT**: las Ordenes siguen en JSON efimero. Un
  redespliegue de Cloud Run borra las Ordenes pero no las fotos del
  bucket: la relacion Orden-foto **no se conserva** entre despliegues (las
  fotos anteriores quedan huerfanas y se limpian con el endpoint). No usar
  fotos de clientes reales en el UAT. Se resuelve con la persistencia de
  Ordenes (PostgreSQL), fuera de esta iteracion.

### Numero de serie en el alta de Cliente Externo (UAT-011)

- El formulario de alta de CLIENTE_EXTERNO ya no muestra "N.º de serie".
  El dato sigue en `Equipo.numero_serie` (opcional; el backend nunca lo
  exigio), RT_INTERNO lo sigue cargando y los datos anteriores no cambian.
  La correccion de los datos del ingreso lo mantiene para todos los
  Origenes.

## Catalogo de equipos de Gestion de Ventas (mvp-v2)

Sin IDs nuevos ni nodos de proceso: capacidad de la Recepcion,
**pendiente de formalizacion** en `business/`.

### Origen real: hoja `raw_TipoProducto`

Lectura de solo lectura (21/10/2026) con la cuenta de servicio con la que
Ventas compartio la planilla:

- 33 columnas y 3.792 filas con datos. `tp_id` es texto y unico en toda la
  hoja (ninguno vacio ni repetido, tampoco ignorando mayusculas).
- RMA usa `tp_id`, `tp_categoria`, `tp_subcat_1`, `tp_gp`, `tp_generator`,
  `tp_modelo`, `tp_number`, `tp_promaxness`, `tp_gb`, `tp_color` y
  `tp_eliminado` (`integraciones/catalogo/ventas.py::COLUMNAS`, ubicadas
  por nombre, no por posicion). No copia precios, descuentos, monedas,
  `tp_eliminado_por` (un email), `tp_eliminado_at` ni `tp_prod_devol`.
- Filtro `tp_subcat_1 = IPHONE USADOS`: 1.489 filas, todas de
  `tp_categoria = IPHONE` y ninguna eliminada.
  - 2 **generadores** (`tp_generator = TRUE`), sin modelo, variante,
    capacidad ni color: `iphone_usados` (raiz del grupo) y `c05e814d`
    ("iPhone 17 E 256GB", grupo `smartphone_usados_`). No son equipos: se
    copian pero no se ofrecen.
  - 1.487 variantes completas y sin combinaciones repetidas. En todas,
    `tp_id = apple_usados_iPhone_{number}_{promaxness}_{gb}_{color}` y
    `tp_modelo = "iPhone {number} {variante} {gb} {color}"`, con espacios
    (`Pro Max`, `black titanium`). RMA no arma ni interpreta el `tp_id`:
    lo copia tal cual.
  - Valores especiales: `tp_promaxness = Nada` (427 filas) es la version
    estandar; `tp_color = cualquier_color` (142) es un producto sin color
    especifico, que se ofrece como "Otro / sin especificar" (el Equipo
    queda sin color). Capacidades `64gb` a `2tb`; colores en minuscula con
    `_` o espacio (`deep_purple`, `black titanium`) y uno capitalizado
    (`Ultramarine`). RMA los muestra como "128 GB", "Deep Purple".
  - Modelos: 8, X, Xr, Xs, 11 a 18, SE 2020 y SE 2022; variantes
    Estandar, Mini, Plus, Pro, Pro Max, Max, E, Air y Duo segun el modelo.
- Observacion para Ventas: las variantes son combinaciones generadas (todos
  los colores y capacidades de cada generacion), no solo las que existen
  comercialmente (por ejemplo, iPhone 11 "black titanium" o iPhone 12 Mini
  de 512 GB). RMA ofrece lo que tiene el catalogo: no corrige a Ventas.

### Arquitectura: puerto y adaptadores

```
origen de Ventas --adaptador--> ProveedorCatalogo --> sincronizacion
(Sheets hoy;                    (el puerto)          (application)
 Cloud SQL/BigQuery                                       |
 despues)                                                 v
                    alta / selector  <--  copia local (CatalogoEquiposRepository)
```

- `app/integraciones/catalogo/`: `puerto.py` (`ProveedorCatalogo`,
  `FiltroCatalogo`, `LecturaCatalogo` y errores), `ventas.py` (formato de
  la tabla TipoProducto de Ventas, compartido por cualquier adaptador),
  `sheets.py` (Google Sheets API v4, `values.get`, solo lectura),
  `archivo.py` (CSV con las mismas columnas: desarrollo y pruebas),
  `credenciales.py` (tokens sin claves JSON) y `configuracion.py` (unico
  lugar que traduce la configuracion en un adaptador).
- Dominio: `ProductoInformado` (lo que informa el origen, ya en terminos
  de RMA), `ProductoCatalogo` (la copia) y `SincronizacionCatalogo`.
  Reglas sin E/S en `services/catalogo_equipos.py`; caso de uso en
  `application/catalogo_equipos.py`; persistencia en
  `repositories/catalogo_equipos.py` (contrato) y
  `storage/json/catalogo_equipos.py`.
- Nadie fuera del adaptador conoce Sheets: los services trabajan con el
  dominio, el alta lee la copia local y el frontend solo usa
  `GET /api/catalogs/equipment`. El alta de una Orden nunca consulta el
  origen.

### Configuracion (variables `RMA_`)

| Variable | Valor por defecto | Uso |
|---|---|---|
| `RMA_CATALOGO_ORIGEN` | `ninguno` | `google_sheets`, `archivo` o `ninguno` (sin sincronizacion) |
| `RMA_CATALOGO_SUBCATEGORIAS` | `["IPHONE USADOS"]` | filtro por `tp_subcat_1` (JSON) |
| `RMA_CATALOGO_MARCAS` | `{"IPHONE": "Apple"}` | marca por `tp_categoria` (Ventas no tiene columna de marca); sin marca, el producto no se ofrece |
| `RMA_CATALOGO_SHEETS_PLANILLA` | (obligatoria con Sheets) | ID de la planilla |
| `RMA_CATALOGO_SHEETS_HOJA` | `raw_TipoProducto` | hoja |
| `RMA_CATALOGO_SHEETS_CREDENCIAL` | `cloud_run` | `cloud_run`: identidad del servicio; `gcloud`: solo desarrollo local |
| `RMA_CATALOGO_SHEETS_CUENTA` | (vacia) | cuenta de servicio a impersonar (IAM Credentials) |
| `RMA_CATALOGO_ARCHIVO` | (obligatoria con archivo) | ruta del CSV |
| `RMA_CATALOGO_TIMEOUT_S` | `30` | espera maxima de la lectura |

Una configuracion incompleta impide arrancar el backend (en Cloud Run la
revision nueva no recibe trafico y sigue la anterior). Los tokens se piden
siempre con alcance `spreadsheets.readonly`, nunca se registran y no hay
claves JSON.

### Sincronizacion

- Manual: "Sincronizar catalogo" debajo del selector (ADMINISTRADOR o
  COORDINADOR_RMA), o `POST /api/catalogs/equipment/sync?usuario_id=`.
  No hay sincronizacion automatica.
- Lee el origen a traves del puerto, aplica el filtro y valida: columnas
  presentes y sin repetir; al menos un producto; `tp_id` sin repetir (un
  repetido es ambiguo: se rechaza todo). Una fila del filtro sin `tp_id`
  se descarta y se cuenta (no se puede referenciar).
- Fusion por `tp_id` (`fusionar_catalogo`): nuevos, actualizados, sin
  cambios, reactivados y dados de baja. **Nunca borra**: lo que Ventas deja
  de informar queda NO vigente (`NO_INFORMADO`) y lo que marca eliminado
  tambien (`ELIMINADO_EN_ORIGEN`); un eliminado que la copia nunca tuvo no
  se agrega. Repetir la sincronizacion no duplica nada.
- Cada intento queda registrado con quien, inicio, fin, origen (sin
  secretos), filtro, resultado (`EXITOSA`, `FALLIDA` si no se pudo leer,
  `RECHAZADA` si los datos no son confiables) y conteos. Se conservan los
  ultimos 100. Fallida o rechazada no cambia la copia: sigue la de la
  ultima exitosa (503 `CATALOGO_ORIGEN_NO_DISPONIBLE` o 409
  `CATALOGO_ORIGEN_INVALIDO`). Una sincronizacion por vez (409
  `SINCRONIZACION_EN_CURSO`).
- Con los datos reales: 3.792 leidas, 1.489 del filtro, 1.489 copiadas,
  1.487 para elegir; la segunda vez, 1.489 sin cambios.

### Equipo

- Identidad fisica: `id` (interno de RMA, sin cambios), `imei` y
  `numero_serie`. Caracteristicas comerciales: `marca`, `modelo`,
  `variante` (`null` = estandar), `capacidad` y `color` (`null` = no
  especificado), y `tipo_producto_id` = el `tp_id` de Ventas. El `tp_id`
  identifica un TIPO de producto, no la unidad: nunca reemplaza al `id`.
- Del catalogo, la API recibe solo `tipo_producto_id`; marca, modelo,
  variante, capacidad y color se copian de la copia local
  (`equipo_desde_catalogo`), no de lo que mande la pantalla. Un `tp_id`
  inexistente, no vigente o no seleccionable (un generador): 409
  `PRODUCTO_CATALOGO_NO_DISPONIBLE`. A mano: `marca` y `modelo`, sin
  `tipo_producto_id`. Sin ninguno de los dos: 422.
- Copia, no referencia: un cambio posterior del catalogo no reescribe la
  Orden ni sus documentos (cada documento ya guarda su copia del Equipo).
  La garantia RMA copia el Equipo de la Orden origen (mismo `tp_id`).
- Corregir los datos del ingreso: el mismo `tp_id` conserva lo que tenia
  la Orden sin consultar el catalogo (corregir el IMEI funciona aunque la
  copia se haya perdido); otro `tp_id` toma el producto de la copia; a
  mano, el Equipo deja de estar vinculado. La version anterior queda en
  `versiones_anteriores`.
- Compatibilidad: los campos nuevos son opcionales. Las Ordenes y los
  documentos anteriores cargan igual (sin `tp_id`, variante, capacidad ni
  color) y se muestran como antes ("Marca Modelo").
- Se muestra como "Apple iPhone 14 Pro Max · 256 GB · Deep Purple"
  (pantalla y listado) y con "Capacidad" y "Color" aparte en la custodia,
  el visor de documentos y el PDF.
- RT_INTERNO tambien acepta `tipo_producto_id` por API; su pantalla sigue
  con marca y modelo a mano.

### Selector del alta de Cliente Externo

- Modelo -> Variante -> Capacidad -> Color, solo con las combinaciones que
  existen en la copia (`GET /api/catalogs/equipment` devuelve el arbol, ya
  ordenado: modelos y variantes en orden natural con la estandar primero,
  capacidades de menor a mayor, "Otro / sin especificar" al final). Un
  nivel con una sola opcion se elige solo; al cambiar un nivel, lo de
  abajo se conserva si existe en la nueva combinacion. Se muestra el
  equipo elegido con su codigo de Ventas.
- "No esta en el catalogo: cargar a mano" (Marca y Modelo). Sin copia
  sincronizada o sin conexion con el backend, se carga a mano y la
  pantalla lo dice.
- IMEI sigue en el alta; el numero de serie sigue fuera del alta de
  Cliente Externo (UAT-011).
- La respuesta pesa ~150 KB en JSON y ~7 KB comprimida: el backend
  comprime las respuestas (`GZipMiddleware`; las imagenes no) y el
  frontend la pide una vez por sesion.

### Persistencia y limitaciones

- **La copia es JSON efimero en Cloud Run** (`RMA_DATA_DIR/catalogo_equipos/
  catalogo_equipos.json`): un redespliegue o un reinicio de la instancia
  la borra junto con el registro de sincronizaciones, y hay que volver a
  sincronizar. Mientras tanto, el alta funciona a mano. Las Ordenes no
  pierden nada: cada Equipo guarda su `tp_id` y su copia de los datos.
- Hacia PostgreSQL (mismo contrato `CatalogoEquiposRepository`, cada
  operacion una transaccion):

```sql
CREATE TABLE catalogo_producto (
  tipo_producto_id   text PRIMARY KEY,          -- tp_id de Ventas, tal cual
  descripcion        text NOT NULL,
  categoria          text, subcategoria text, grupo text,
  marca text, modelo text, variante text, capacidad text, color text,
  color_generico     boolean NOT NULL DEFAULT false,
  seleccionable      boolean NOT NULL,
  motivo_no_seleccionable text,
  vigente            boolean NOT NULL DEFAULT true,
  motivo_baja        text,
  valores_origen     jsonb NOT NULL DEFAULT '{}',
  primera_sincronizacion timestamptz NOT NULL,
  ultima_sincronizacion  timestamptz NOT NULL
);
CREATE TABLE catalogo_sincronizacion (
  id text PRIMARY KEY, usuario_id text NOT NULL, origen text NOT NULL,
  filtro text NOT NULL, iniciada_en timestamptz NOT NULL,
  finalizada_en timestamptz NOT NULL, resultado text NOT NULL,
  mensaje text, leidos int, filtrados int, descartados int, nuevos int,
  actualizados int, sin_cambios int, reactivados int, dados_de_baja int,
  vigentes int, elegibles int
);
-- equipos.tipo_producto_id REFERENCES catalogo_producto (sin borrado:
-- las bajas son vigente = false).
```

### Reemplazar el origen (cuando Ventas migre su base)

1. Escribir el adaptador nuevo en `app/integraciones/catalogo/` (por
   ejemplo `cloudsql.py` o `bigquery.py`) que implemente
   `ProveedorCatalogo.leer(filtro)`: consultar con el filtro aplicado en el
   origen (`WHERE tp_subcat_1 IN (...)`) y devolver
   `ventas.lectura_desde_tabla(encabezados, filas, filtro, marcas=...)` si
   la tabla conserva las columnas `tp_*`, o `ProductoInformado` armados por
   el adaptador si cambian. El `tp_id` se devuelve tal cual.
2. Agregar su caso en `configuracion.py` y sus variables en
   `core/config.py` (credencial sin claves JSON: la identidad del
   servicio con permiso de lectura).
3. Probarlo contra respuestas simuladas, igual que `sheets.py`
   (`tests/test_catalogo_equipos.py`).
4. Cambiar `RMA_CATALOGO_ORIGEN` y sincronizar. Como los `tp_id` son los
   mismos, la fusion los reconoce: nada nuevo, nada duplicado, las Ordenes
   siguen referenciando lo mismo.

No cambian el Equipo, el selector, la sincronizacion, la copia ni la API.
Si Ventas cambiara los `tp_id` en la migracion, haria falta una tabla de
equivalencias: la fusion trataria los nuevos como productos nuevos y los
viejos quedarian no vigentes (sin perder historia).

### Acceso desde Cloud Run (UAT)

- `rt-rma-uat-api` corre con una cuenta de servicio dedicada,
  `rt-rma-uat-api@<proyecto>.iam.gserviceaccount.com`: sin roles de
  proyecto, sin claves, con `roles/storage.objectUser` solo sobre el
  bucket de fotos y la planilla de Ventas compartida con ella como
  **Lector** (sin permisos de IAM: el acceso a la planilla lo da Drive).
- Configuracion: `RMA_CATALOGO_ORIGEN=google_sheets`, la planilla, la hoja
  y `RMA_CATALOGO_SHEETS_CREDENCIAL=cloud_run` (token del servidor de
  metadatos con alcance `spreadsheets.readonly`). No se usa la cuenta con
  la que Ventas comparte la planilla con otros sistemas (es Owner del
  proyecto), ni la impersonacion.
- Validado con la cuenta del UAT, antes de publicar (revision sin
  trafico): 3.792 leidas, 1.489 de IPHONE USADOS, 1.487 para elegir,
  `tp_id` identicos a la lectura de referencia, generadores fuera del
  selector, la segunda sincronizacion sin cambios, y un error real de
  Google (hoja inexistente) registrado como FALLIDA, con 503 y sin aplicar
  nada.
- Despues de cada despliegue o reinicio, la copia se pierde: hay que
  sincronizar de nuevo (Administracion o Coordinacion RMA).

## Gaps de cobertura de test conocidos

Requerimientos declarados sin un Internal Test que los verifique
directamente. Se dejan asi, sin inventar cobertura:

- `FR-REP-023` — "tomar la Orden no inicia ninguna Ejecucion". El E2E lo
  respeta de hecho, pero ningun test lo afirma explicitamente.
- `TR-REP-003` — "`domain` no importa FastAPI, repositories ni storage".
  No existe test de arquitectura que lo verifique.
- `TR-REP-023` — estandar PEP 8 / Ruff / pytest. Se verifica corriendo el
  linter, no con un test.
- `TR-REP-024` — `nuevo_id`. Solo tiene evidencia indirecta (los IDs
  aparecen en las entidades que crean los tests E2E).
