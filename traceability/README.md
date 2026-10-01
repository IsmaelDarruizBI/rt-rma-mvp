# Trazabilidad (futuro)

Este documento describe la convencion de IDs y la jerarquia conceptual que
sostiene la trazabilidad end-to-end del proyecto.

> **Estado**: este README se escribio ANTES de que existiera ninguna
> implementacion, y se conserva como el documento de **convencion**. Las
> afirmaciones del tipo "no hay todavia ninguna implementacion" o "todavia
> no existen User Stories reales" quedaron desactualizadas: la cadena fue
> reconstruida y hoy existe. Para el estado real ver
> [IMPLEMENTATION.md](./IMPLEMENTATION.md) y el grafo
> [hp-rep-001.yaml](./hp-rep-001.yaml). La convencion de IDs y niveles que
> sigue vigente es la que este documento define.

## Business Domain

El sistema RMA no va a contener solamente Gestion de Reparaciones. Ya estan
identificados, para etapas futuras, otros Business Process del mismo
dominio:

- Gestion de Ventas de Repuestos.
- Gestion de Compras de Repuestos.

Por eso, por encima de los Business Process, se define una agrupacion
funcional superior: el Business Domain.

```text
DOM-RMA  Business Domain / Area funcional RMA
├── PROC-REP  Gestion de Ordenes de Reparacion
├── PROC-VTA  Gestion de Ventas de Repuestos
└── PROC-COM  Gestion de Compras de Repuestos
```

**Importante:** de estos tres, unicamente `PROC-REP` existe actualmente
como Business Process modelado, en su V1.2 (`approved`,
`business/processes/repair-management.yaml`). `PROC-VTA` y `PROC-COM` son
procesos futuros ya identificados durante el descubrimiento; todavia no se
crean sus archivos YAML ni se modelan sus nodos, y sus prefijos (`VTA`,
`COM`) siguen siendo conceptuales hasta que esos procesos se modelen
formalmente. Sirven aqui solo para mostrar por que hace falta un nivel de
agrupacion por encima de Business Process.

## Jerarquia principal

```text
Business Domain
↓
Business Process
↓
Feature
↓
User Story
↓
System Action
↓
Functional Requirement
↓
Technical Requirement
↓
Task
↓
Code / Artifact
↓
Internal Test
↓
UAT
↓
Bug / Issue
↓
Fix / Retest / Approval
```

Esta cadena reemplaza la mencion anterior de este documento, que nombraba
Epic directamente entre Business Process y User Story sin pasar por
Feature. Epic no forma parte de esta cadena principal (ver mas abajo).

**Las relaciones entre niveles no son necesariamente 1:1.** Pueden ser 1:N o
N:M segun corresponda. Por ejemplo:

- una Feature puede tener varias User Stories;
- una User Story puede requerir varias System Actions;
- una System Action puede generar varios Functional Requirements;
- un Functional Requirement puede necesitar varios Technical Requirements;
- un Technical Requirement puede satisfacer uno o varios Functional
  Requirements;
- un Technical Requirement puede generar varias Tasks.

Por esto, la trazabilidad futura debera soportarse mediante una estructura
de **items + links** (elementos y relaciones explicitas), no mediante
anidamiento rigido uno-a-uno, precisamente para poder representar
relaciones many-to-many sin rediseñar el formato. Esto es todavia una
decision de diseño conceptual: no hay hoy en este repositorio una
implementacion de esa estructura ni herramientas que la generen o
validen.

## Data Model / Architecture (artefacto transversal)

El modelo de datos sigue siendo una etapa fundamental del proyecto, pero
no se documenta como un nivel jerarquico rigido de la cadena principal
(por ejemplo, no se ubica de forma fija entre Functional Requirement y
Technical Requirement). Se trata como un **artefacto arquitectonico
transversal**, relacionado con varios niveles a la vez mediante items +
links:

```text
Functional Requirements
        ↓
Data Model / Architecture
        ↓
Technical Requirements
```

pero permitiendo relaciones N:M, no 1:1:

- una misma entidad del modelo de datos puede satisfacer varios
  Functional Requirements;
- varios Technical Requirements pueden depender de la misma entidad;
- una modificacion del modelo de datos puede impactar varias Features a
  la vez.

Cuando la trazabilidad se implemente, estos artefactos (entidades,
decisiones de arquitectura) tambien deberan participar mediante links
explicitos, igual que el resto de los niveles. Todavia no se diseña el
modelo de datos en esta etapa.

## Epic (opcional)

Epic **no sustituye a Feature** ni a Business Domain, y **no forma parte
obligatoria** de la cadena principal de trazabilidad.

Es una agrupacion opcional de planificacion o iniciativa grande, que puede
agrupar varias Features -incluso de distintos Business Process- cuando
convenga para gestion de producto o de roadmap. Ejemplo conceptual:

```text
EPIC-RMA-001  Optimizacion de operacion de repuestos
├── FEAT-VTA-...
└── FEAT-COM-...
```

Este Epic agruparia Features de Ventas y de Compras de Repuestos sin
reemplazar a esos Business Process ni a sus Features. Por ahora no se crean
Epics reales: es solo la convencion para cuando haga falta usarlos.

## Convencion de IDs

```text
DOM-RMA        Business Domain

PROC-REP-XXX   Business Process Node - Reparaciones
EVT-REP-XXX    Event - Reparaciones
BR-REP-XXX     Business Rule - Reparaciones

FEAT-REP-XXX   Feature
US-REP-XXX     User Story
ACC-REP-XXX    System Action
FR-REP-XXX     Functional Requirement
TR-REP-XXX     Technical Requirement
TASK-REP-XXX   Development Task
CODE-REP-XXX   Code / Artifact
TEST-REP-XXX   Internal Test
UAT-REP-XXX    User Acceptance Test
BUG-REP-XXX    Bug / Issue

EPIC-RMA-XXX   Epic / iniciativa transversal (opcional)
```

`REP` identifica al Business Process de Reparaciones. Para los futuros
`PROC-VTA` y `PROC-COM` se usaran prefijos propios -conceptualmente `VTA`
(Venta de repuestos) y `COM` (Compra de repuestos)-; sus nombres
definitivos se confirman recien cuando esos procesos se modelen.

`FEAT-REP-XXX` ya tiene 7 Features reales en estado `draft` para `PROC-REP`
V1.2 (`FEAT-REP-001` a `FEAT-REP-007`, ver
`business/features/repair-management-features.yaml`). `ACC-REP-XXX` y
`TASK-REP-XXX` siguen siendo unicamente convencion conceptual: todavia no
se crearon System Actions ni Tasks reales. El enfoque items + links
descrito arriba sigue siendo una decision de diseño, no una implementacion
aprobada para uso general.

## Que representa cada nivel

- **Business Domain**: agrupacion funcional superior del negocio/producto
  (ej. `DOM-RMA`).
- **Business Process**: flujo de negocio end-to-end (ej. Gestion de Ordenes
  de Reparacion).
- **Feature**: capacidad funcional coherente y desarrollable.
- **User Story**: necesidad de un actor expresada desde su perspectiva.
- **System Action**: accion concreta que el sistema debe ejecutar para
  realizar una User Story.
- **Functional Requirement**: comportamiento funcional verificable que
  debe cumplir el sistema.
- **Technical Requirement**: decision/contrato tecnico necesario para
  implementar uno o mas requisitos funcionales.
- **Task**: unidad concreta de trabajo de desarrollo.
- **Code / Artifact**: resultado implementado.
- **Internal Test**: verificacion interna del desarrollo.
- **UAT**: validacion de aceptacion por negocio/usuario.
- **Bug / Issue**: desvio encontrado durante testing/UAT/operacion.
- **Epic**: agrupacion opcional de planificacion, no sustituto de Feature
  ni de Business Domain.

## Agrupacion de archivos de trazabilidad

Los archivos `traceability/*.yaml` representan **unidades reales de
implementacion**, no necesariamente un unico Scenario de negocio.

### Cuando agrupar Scenarios en un mismo archivo

Se pueden agrupar cuando:

- comparten esencialmente la misma capacidad funcional;
- se implementan en el mismo Slice;
- comparten la mayor parte de las US / ACC / FR / TR / TASK / CODE;
- sus diferencias se representan mediante reglas, politicas o tests;
- evolucionan como una misma unidad tecnica.

Aunque compartan archivo, **cada Scenario conserva**: su ID propio, su
definicion en `business/`, sus condiciones y expectativas, sus links, sus
tests especificos (campo `scenario` en el item de test) y sus UAT
independientes. No se inventa un Scenario ficticio que los combine (por
ejemplo `VAR-REP-001-002`).

Ejemplo: `var-rep-001-002.yaml` agrupa `VAR-REP-001` y `VAR-REP-002`, que
son la misma capacidad (ingreso sin diagnostico conocido) y solo difieren
en si el Origen requiere comprobante de recepcion (`PoliticaOrigen`).

### Cuando crear un archivo distinto

Se crea un archivo de trazabilidad distinto cuando un Scenario constituye
una **unidad de implementacion sustancialmente independiente**. Criterios:

- Slice propio e independiente;
- User Stories o System Actions materialmente diferentes;
- FR / TR principalmente propios;
- componentes o modulos propios;
- ciclo funcional diferente;
- reglas o excepciones propias relevantes;
- testing / UAT que evoluciona de forma independiente;
- el archivo compartido pierde claridad;
- separarlo mejora la navegacion E2E sin duplicar artefactos
  artificialmente.

### Regla practica

```text
Misma unidad real de implementacion
→ mismo archivo de trazabilidad.

Unidad de implementacion independiente
→ archivo de trazabilidad distinto.
```

Sea cual sea el agrupamiento, los IDs de implementacion son globalmente
unicos y la capa de negocio coincide con `business/`:
`npm run validate:traceability` lo comprueba sobre todos los archivos.

## Objetivo futuro

Poder navegar desde cualquier elemento hasta todos sus relacionados, en
ambas direcciones. Ejemplo conceptual de navegacion: hoy son reales
`DOM-RMA`, `PROC-REP-040` y las 7 Features en estado `draft` (`FEAT-REP-001`
a `FEAT-REP-007`); de `US-REP-001` en adelante, todo el resto de la cadena
sigue siendo unicamente conceptual, no implica que esos elementos ya
existan:

```text
DOM-RMA
→ PROC-REP-040
→ FEAT-REP-001
→ US-REP-001
→ ACC-REP-001
→ FR-REP-001
→ TR-REP-001
→ TASK-REP-001
→ CODE-REP-001
→ TEST-REP-001
→ UAT-REP-001
→ APPROVED
```

Si una verificacion falla, el mismo camino puede continuar hacia un Bug y
su ciclo de correccion en lugar de cerrar directamente en `APPROVED`:

```text
UAT-REP-001
→ BUG-REP-001
→ FIX
→ RETEST
→ APPROVED
```

## Estado actual

No implementado como sistema de trazabilidad completo. Esta convencion
existe para que los IDs creados desde ahora (por ejemplo, en
`business/processes/repair-management.yaml` y ahora tambien en
`business/features/repair-management-features.yaml`) sean estables y
reutilizables cuando se construya el sistema de trazabilidad.

La Etapa 2 (Feature Definition) ya comenzo formalmente: existen 7
Features reales en estado `draft` para `PROC-REP` V1.2 (`FEAT-REP-001` a
`FEAT-REP-007`), validadas estructuralmente contra
`business/schemas/feature.schema.json` mediante `npm run validate:features`.

En particular:

- las 7 Features son reales y estan en estado `draft`, no `approved`;
- todavia no existen User Stories reales;
- la trazabilidad automatizada como *sistema* (generacion de matrices de
  trazabilidad, navegacion bidireccional entre todos los niveles,
  herramientas de UI) todavia no existe: eso sigue siendo una evolucion
  posterior;
- si existe, en cambio, una primera validacion de integridad referencial
  (`scripts/validate-references.ts`, `npm run validate:references`):
  confirma que cada `process_nodes[]` y `business_rules[]` declarado en
  una Feature existe realmente en `repair-management.yaml` /
  `business-rules.yaml`, que `source_process` coincide con el Business
  Process aprobado, la integridad interna del propio Business Process
  (edges, actores, reglas) y reporta cobertura de nodos y de Business
  Rules por Feature. Es validacion estructural + referencial, no todavia
  un sistema de trazabilidad con matrices o navegacion;
- los IDs ya asignados a nodos de Business Process (por ejemplo los de
  `PROC-REP` en `repair-management.yaml`) deben mantenerse estables;
- la V1.2 aprobada de Gestion de Ordenes de Reparacion no se modifica por
  este documento, por esta convencion, ni por la definicion de Features.
