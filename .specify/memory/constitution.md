# Rosario Tecno RMA App Constitution

Alcance de esta constitution: el trabajo de especificacion y trazabilidad
del MVP ya implementado de Gestion de Ordenes de Reparacion (PROC-REP; la
baseline vigente es V1.4, aprobada en DC01; el trabajo inicial se hizo
sobre V1.3 y el Scenario `HP-REP-001`). Recoge unicamente principios que ya estan
vigentes en el repositorio o que fueron acordados explicitamente durante
el descubrimiento. No introduce principios aspiracionales nuevos.

## Core Principles

### I. Business YAML es la fuente funcional de verdad

El comportamiento funcional del sistema se define en `business/`:
`business/processes/repair-management-v1.4.yaml`,
`business/rules/business-rules-v1.4.yaml`,
`business/features/repair-management-features-v1.4.yaml` y
`business/scenarios/repair-management-scenarios-v1.4.yaml`, la baseline
vigente (DC01). Los archivos V1.3 y V1.2 se conservan como historico.

`business/` es una copia generada desde `rt-rma-app`, la fuente unica
(DC02): `business/FUNCTIONAL_SOURCE.json` identifica el commit de origen
y el SHA-256 de cada archivo. No se edita a mano; un cambio funcional se
hace en `rt-rma-app` y se vuelve a generar la copia
(`docs/sincronizacion-funcional.md`).

Ningun artefacto posterior (spec, plan, task, codigo o test) puede
redefinir, ampliar ni contradecir ese contenido. Cuando una spec necesita
un comportamiento que `business/` no declara, eso es un hallazgo a
reportar al negocio, no una licencia para inventarlo.

Orden de precedencia cuando dos fuentes discrepan:

1. Business Process (`repair-management-v1.4.yaml`)
2. Business Rules (`business-rules-v1.4.yaml`)
3. Business Features (`repair-management-features-v1.4.yaml`)
4. Scenarios (`repair-management-scenarios-v1.4.yaml`)
5. `traceability/README.md` (convencion de IDs y jerarquia)
6. Codigo implementado
7. Tests existentes

### II. Los IDs funcionales existentes son estables

`DOM-RMA`, `PROC-REP-XXX`, `EVT-REP-XXX`, `BR-REP-XXX`, `FEAT-REP-XXX` y
`HP-REP-001` ya estan asignados y NO se renumeran, reasignan ni reciclan.
Los IDs nuevos (`US-REP-XXX`, `ACC-REP-XXX`, `FR-REP-XXX`, `TR-REP-XXX`,
`TASK-REP-XXX`, `CODE-REP-XXX`, `TEST-REP-XXX`, `UAT-REP-XXX`) siguen la
convencion de `traceability/README.md` y, una vez publicados, tambien son
estables.

### III. La trazabilidad end-to-end es obligatoria

Ningun elemento de la cadena existe huerfano. Todo artefacto debe poder
navegarse en ambas direcciones a lo largo de:

```text
Business Domain -> Business Process -> Feature -> User Story ->
System Action -> Functional Requirement -> Technical Requirement ->
Task -> Code/Artifact -> Internal Test -> UAT
```

Las relaciones no son 1:1: son 1:N y N:M. Por eso la trazabilidad se
representa con **items + links** explicitos (decision ya tomada en
`traceability/README.md`), nunca con anidamiento rigido. La validacion
automatica de esa integridad es un gate del repositorio.

### IV. El modelo de datos es un artefacto transversal N:M

El modelo de datos / arquitectura no es un nivel fijo de la cadena entre
Functional Requirement y Technical Requirement. Es un artefacto
transversal que se relaciona con varios niveles a la vez mediante links:
una misma entidad puede satisfacer varios Functional Requirements, y
varios Technical Requirements pueden depender de la misma entidad.

### V. No se infiere comportamiento funcional desde la implementacion

Reconciliacion brownfield: `business/` + el Scenario definen **que
comportamiento debia existir**; el codigo describe **como fue
implementado**; los tests son **evidencia ejecutable**. Cuando el codigo
y el Business Process difieren, NO se reescribe el requerimiento para que
coincida con el codigo: se reporta la inconsistencia.

Un Functional Requirement se escribe en lenguaje de negocio y es
independiente de FastAPI, Pydantic, JSON o React. "Usar Pydantic",
"guardar en JSON" o "crear un endpoint POST" son Technical Requirements,
nunca Functional Requirements.

### VI. Separacion de capas del backend

Regla de dependencia vigente (`app/backend/README.md`):
`api -> services -> repositories <- storage`, y `domain` no depende de
ninguna de las otras.

- `domain/` no importa FastAPI, repositories ni storage.
- `services/` no conocen HTTP ni el formato de persistencia; reciben y
  devuelven modelos de dominio y contratos de repository.
- `repositories/` declaran el contrato (QUE) mediante `typing.Protocol`;
  `storage/` provee la implementacion (COMO) y debe poder reemplazarse
  sin tocar `domain` ni `services`.

### VII. Codigo modular y parametrizable, sin sobreingenieria

Se prefiere codigo modular, parametrizable y reutilizable cuando eso
aporta valor real (por ejemplo, una politica de estado centralizada en
vez de repetida en cada nodo). No se anticipan abstracciones, capas ni
configurabilidad que ningun requerimiento vigente necesite. El alcance de
los enums y de los servicios del MVP se limita deliberadamente a lo que
`HP-REP-001` recorre.

### VIII. Los tests internos se vinculan al requerimiento que verifican

Todo Internal Test debe estar enlazado al menos a un Functional
Requirement o Technical Requirement (y, cuando corresponda, al Code /
Artifact que ejercita). Un test sin requerimiento asociado es un hallazgo
de trazabilidad, no un test valido.

### IX. UAT es distinto del testing interno

Los tests internos son verificacion del equipo de desarrollo. El UAT es
aceptacion de negocio. Ninguna cantidad de tests internos aprobados
constituye evidencia de aceptacion de usuario. Un UAT solo pasa a
aprobado cuando negocio lo ejecuta y lo aprueba formalmente; hasta
entonces su estado es `PENDING`.

### X. Estandares de codigo Python

Python >= 3.11. Se respetan PEP 8 y la configuracion de Ruff ya vigente
en `app/backend/pyproject.toml` (`line-length = 79`, reglas `E`, `W`,
`F`, `I`). Los tests se ejecutan con `pytest` desde `app/backend/`.

### XI. HP-REP-001 es el unico Scenario implementado en esta baseline

`HP-REP-001` ("Reparacion estandar de cliente externo") es el unico
Scenario que la baseline actual implementa. Las Features
`FEAT-REP-001` a `FEAT-REP-008` estan activas en ese Happy Path;
`FEAT-REP-009` (Cancelacion) NO lo esta.

Consecuencia obligatoria para todo artefacto: hay que distinguir siempre
"Feature completa" de "slice de Feature implementado por
HP-REP-001". Ninguna Feature puede declararse IMPLEMENTADA porque exista
su Happy Path. La forma de declararlo es:

```text
feature_status           = draft        (estado de la Feature en la baseline vigente)
implemented_scenario     = HP-REP-001
implemented_slice_status = IMPLEMENTED  (estado del slice, no de la Feature)
```

## Alcance y restricciones vigentes

- Business Process activo: `PROC-REP` V1.4, estado `approved` (DC01,
  24/10/2026), sincronizado desde `rt-rma-app` (etiqueta `v1.4-baseline`).
  `PROC-REP` V1.3 (`draft`) y V1.2 (`approved`) permanecen como historico y
  no se modifican.
- Las 11 Features V1.4 estan en estado `draft`. Este trabajo no las
  aprueba ni las modifica.
- Las 49 Business Rules V1.4 estan en estado `approved`.
- Lo que el producto todavia no hace como dice V1.4 se registra en
  `traceability/discrepancias-baseline-v1.4.md` (Principio V): son
  divergencias a resolver, no fallas de la copia funcional.
- `PROC-VTA` (Ventas de Repuestos) y `PROC-COM` (Compras de Repuestos)
  estan identificados pero no modelados: fuera de alcance.
- Persistencia del MVP: archivos JSON locales bajo `app/backend/data/`,
  sin datos reales ni credenciales.
- Los pendientes funcionales declarados en `docs/discovery/README.md` y en
  `open_items` de `business/decisions/decision-log-v1.4.yaml`
  (presupuestacion, costos, impuestos, cortesias parciales, actor
  autorizado a cancelar, reproceso RMA, reporting por tecnico, entre
  otros) siguen fuera de alcance y no deben especificarse como si
  estuvieran resueltos.

## Flujo de trabajo y gates de calidad

1. Toda spec nueva de este ciclo se deriva de una Business Feature
   existente (`FEAT-REP-XXX`) y declara explicitamente su
   `implemented_scenario`.
2. `spec.md` contiene User Stories, acceptance scenarios y Functional
   Requirements. Una User Story expresa la necesidad de un ACTOR HUMANO;
   "Como sistema quiero..." esta prohibido: eso es una System Action.
3. `plan.md` describe la arquitectura realmente existente, el modelo de
   datos y los Technical Requirements, con paths reales del repositorio.
4. `tasks.md` reconstruye el trabajo realizado. Una tarea solo se marca
   `[x]` cuando existe evidencia real de codigo **y** de test. Nunca se
   marca por inferencia.
5. Gates ejecutables del repositorio:
   - `npm run verify:functional-copy` (la copia funcional coincide con su
     manifiesto) debe pasar.
   - `npm run validate:v1.4` (proceso, features, referencias, scenarios,
     mapping Feature<->Scenario y fines de cada recorrido) debe pasar, y
     `npm run validate:v1.3` sigue como regresion del historico.
   - `npm run validate:traceability` (integridad de items + links) y
     `npm run validate:discrepancies` deben pasar.
   - `npm run validate:all` corre todos los anteriores.
   - `pytest` desde `app/backend/` debe seguir en verde.
6. Ningun artefacto de especificacion o trazabilidad justifica modificar
   codigo productivo para que el artefacto "pase". Si un artefacto no
   cierra contra el codigo, se reporta el gap.

## Governance

Esta constitution prevalece sobre cualquier practica ad hoc de este
repositorio en materia de especificacion y trazabilidad. No prevalece
sobre `business/`: ante conflicto, manda el Principio I.

Enmiendas: cualquier cambio requiere (a) quedar documentado en este
archivo, (b) indicar que artefactos existentes se ven afectados y (c) un
incremento de version segun semver (MAJOR = se elimina o se redefine
incompatiblemente un principio, MINOR = se agrega un principio o una
seccion, PATCH = aclaracion sin cambio de alcance).

Cumplimiento: toda revision de specs, plans, tasks o artefactos de
trazabilidad verifica el cumplimiento de estos principios. Toda
desviacion se documenta explicitamente en `Complexity Tracking` del
`plan.md` correspondiente o se reporta como gap; no se deja implicita.

Enmienda 1.1.0 (24/10/2026, DC02, MINOR): la fuente funcional pasa a ser la
baseline V1.4 aprobada en DC01, como copia generada y verificada desde
`rt-rma-app`; V1.3 queda como historico. Se agregan los gates de la copia
funcional, de V1.4 y de la lista de discrepancias. Los principios no
cambian de alcance. Artefactos afectados: `business/` (copia generada),
`traceability/*.yaml` (fuente V1.4), `scripts/` y `package.json` (validacion
V1.4), `traceability/discrepancias-baseline-v1.4.md`,
`docs/sincronizacion-funcional.md`, `README.md` y
`traceability/IMPLEMENTATION.md`. Los `specs/001` a `019` se conservan como
registro historico de slices sobre V1.3.

**Version**: 1.1.0 | **Ratified**: 2026-09-24 | **Last Amended**: 2026-10-24
