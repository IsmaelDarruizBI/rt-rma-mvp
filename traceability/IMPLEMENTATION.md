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
- Sin estados sin salida: si el ingreso todavia no registra el check-in
  (por ejemplo, una Orden anterior con la recepcion ya confirmada, que ya
  no admite correcciones), el comprobante de ingreso lo recibe y lo
  completa en la misma operacion (`services/custodia.py::completar_checkin`).
  Un check-in ya registrado no se cambia desde ahi.
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

### Observaciones visibles y notas internas

- `DatosRecepcion.observaciones` son visibles y salen en los comprobantes;
  `DatosRecepcion.notas_internas` y las notas con `interna: true` son solo
  para el personal y no salen en ningun documento ni PDF.

### Compatibilidad

Los campos nuevos tienen valor por defecto: las Ordenes ya guardadas se
leen sin migracion (sin check-in, sin descuento, sin notas internas).

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
