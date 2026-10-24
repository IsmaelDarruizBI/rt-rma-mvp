# Rosario Tecno RMA App

Repositorio base para la aplicacion de gestion del area de reparaciones de
Rosario Tecno.

## Objetivo

Este repositorio busca mantener trazabilidad end-to-end. La jerarquia
principal, definida en detalle en
[traceability/README.md](traceability/README.md), es:

```text
Business Domain
→ Business Process
→ Feature
→ User Story
→ System Action
→ Functional Requirement
→ Technical Requirement
→ Task
→ Code / Artifact
→ Internal Test
→ UAT
→ Bug / Issue
→ Fix / Retest / Approval
```

Epic es opcional: no sustituye a Feature, y puede usarse como agrupacion
transversal de planificacion (por ejemplo, agrupando Features de distintos
Business Process) sin formar parte de la cadena obligatoria.

El Data Model / Architecture sigue siendo una etapa fundamental del
proyecto, pero se trata como un artefacto arquitectonico transversal, no
como un nivel jerarquico rigido entre Functional Requirement y Technical
Requirement: una misma entidad puede satisfacer varios Functional
Requirements y varios Technical Requirements pueden depender de ella
(relacion N:M, no 1:1).

Ver [traceability/README.md](traceability/README.md) para la convencion
completa de IDs y las relaciones 1:N / N:M entre niveles, y
[docs/discovery/README.md](docs/discovery/README.md) para el detalle de la
etapa de Business Process Discovery & Modeling.

Sobre esa baseline funcional existe hoy un **MVP ejecutable** en `app/`
(backend FastAPI + frontend React), que implementa el escenario
`HP-REP-001`. Ver "Estado actual" mas abajo. No hay base de datos: la
persistencia del MVP es JSON local.

## Principio arquitectonico

```text
YAML            = Source of Truth
JSON Schema     = Validation Contract
Mermaid         = Visualizacion general
HTML Viewer     = Visualizacion interactiva para negocio
React Flow      = Futuro renderer avanzado
```

El proceso de negocio se define en YAML bajo `business/`. Ese YAML es la
unica fuente de verdad. Desde DC02 (24/10/2026), `business/` es una **copia
generada** desde `rt-rma-app`, con el commit de origen y los hashes en
`business/FUNCTIONAL_SOURCE.json`: no se edita a mano, se regenera (ver
[docs/sincronizacion-funcional.md](docs/sincronizacion-funcional.md)). A
partir de ese YAML se generan automaticamente un diagrama
Mermaid y un viewer HTML interactivo para visualizacion humana; ninguno de
los dos se edita a mano ni introduce informacion nueva. El modelo de datos
(`nodes[]` / `edges[]`) esta pensado desde el inicio para poder alimentar
React Flow en el futuro sin rediseñar el esquema.

```text
YAML → JSON Schema → Renderer → Mermaid / HTML Viewer (hoy) → React Flow (futuro)
```

## Estructura

```text
business/        FUENTE DE VERDAD FUNCIONAL (copia generada desde rt-rma-app, DC02)
  processes/     Procesos de negocio en YAML
  actors/        Actores que participan en los procesos
  rules/         Reglas de negocio
  features/      Definiciones funcionales de Features
  scenarios/     Scenarios sobre el proceso
  decisions/     Registro de decisiones de la consolidacion V1.4
  schemas/       JSON Schema de validacion
  FUNCTIONAL_SOURCE.json  Procedencia: commit de origen y SHA-256 de cada archivo

app/             MVP EJECUTABLE
  backend/       FastAPI · Pydantic v2 · persistencia JSON
  frontend/      React + TypeScript + Vite

specs/           Especificacion Spec Kit, una por Feature activa
.specify/        Constitution del proyecto y plantillas de Spec Kit

traceability/    Cadena E2E: convencion, grafo items+links y su estado

generated/
  mermaid/       Diagramas Mermaid generados automaticamente (no editar)
  viewer/        Viewer HTML interactivo generado automaticamente (no editar)

scripts/         Generadores y validadores de este repositorio

docs/
  discovery/     Documentacion del proceso de descubrimiento de negocio
```

## Instalacion

```bash
npm install
```

## Visualizacion

Ambas visualizaciones se generan desde el mismo YAML y nunca deben editarse
manualmente.

### Mermaid general

`generated/mermaid/repair-management.mmd`

```bash
npm run generate:mermaid
```

Diagrama Mermaid plano, pensado como vista general del proceso (por ejemplo
para pegar en un documento o visor de Mermaid).

### Viewer interactivo

`generated/viewer/repair-management.html`

```bash
npm run generate:viewer
```

HTML autocontenido (incluye Mermaid embebido, funciona sin conexion) pensado
para validacion funcional con el negocio. Al hacer click sobre un nodo del
diagrama, un panel lateral muestra su detalle: actor, descripcion, inputs,
outputs y reglas de negocio, resolviendo las referencias contra
`business/actors/actors.yaml` y `business/rules/business-rules.yaml`. Si una
referencia no existe, el panel lo muestra como una advertencia visible en
lugar de fallar silenciosamente.

El viewer tambien permite navegar las **Features** (`business/features/`)
como una capa sobre el mismo diagrama del Business Process: un selector en
la toolbar ("Vista: Todas las Features") permite elegir una Feature y
resalta unicamente sus `process_nodes` (atenuando el resto), sin alterar
el diagrama ni convertir Features en nodos nuevos. El detalle de cada nodo
incluye ademas sus "Features relacionadas", y el detalle de cada Feature
incluye sus Process Nodes -en ambos casos clickeables-, permitiendo
navegar en cualquier direccion entre un Process Node y las Features que lo
agrupan.

### Comandos

```bash
npm run validate
npm run generate:mermaid
npm run generate:viewer
```

o, para correr los tres pasos en orden:

```bash
npm run generate
```

## Estado actual

### Modelado funcional

```text
PROC-REP  Gestion de Ordenes de Reparacion  V1.2 — approved  (baseline historica)
PROC-REP  Gestion de Ordenes de Reparacion  V1.3 — draft     (historica)
PROC-REP  Gestion de Ordenes de Reparacion  V1.4 — approved  (baseline vigente, DC01)
```

La baseline vigente es la V1.4 consolidada, aprobada en DC01 el 24/10/2026 y
sincronizada desde `rt-rma-app` (etiqueta `v1.4-baseline`, commit
`e99b283`). Tiene 49 Business Rules aprobadas, 11 Features en `draft` (2
TRANSVERSALES) y 51 Scenarios, entre ellos los tres Happy Paths:

```text
HP-REP-001  Reparacion estandar de cliente externo  (HAPPY_PATH / E2E)
HP-REP-002  Reparacion estandar de equipo RT        (HAPPY_PATH / E2E)
HP-REP-003  Garantia de reparacion RMA              (HAPPY_PATH / E2E)
```

V1.3 queda como historico: es el V1.3 original de `rt-rma-app`, sin los
cambios que el MVP le habia hecho, porque esos cambios estan en V1.4. Lo
que el producto todavia no hace como dice V1.4 esta en
[traceability/discrepancias-baseline-v1.4.md](traceability/discrepancias-baseline-v1.4.md).

`PROC-VTA` (Ventas de Repuestos) y `PROC-COM` (Compras de Repuestos)
siguen siendo procesos futuros identificados dentro de `DOM-RMA`: todavia
no tienen YAML ni modelado propio.

### MVP ejecutable

```text
app/backend/    FastAPI · Pydantic v2 · persistencia JSON local
app/frontend/   React + TypeScript + Vite
```

Implementa `HP-REP-001` de punta a punta: se puede crear una Orden desde
el navegador y recorrer todo el circuito hasta `ENTREGADA`. Ver
[app/backend/README.md](app/backend/README.md) y
[app/frontend/README.md](app/frontend/README.md).

**No hay base de datos productiva.** El almacenamiento es JSON sobre el
filesystem, pensado como MVP y detras de contratos de repository para
poder reemplazarse despues.

### Especificacion y trazabilidad

[Spec Kit](https://github.com/github/spec-kit) esta incorporado
(`.specify/`, `specs/`), con una constitution del proyecto y una
especificacion por Business Feature activa. La cadena de trazabilidad
E2E fue **reconstruida desde el baseline implementado**:

```text
Business Process → Feature → User Story → System Action
→ Functional Requirement → Technical Requirement → Task
→ Code → Internal Test → UAT
```

y existe en formato machine-readable en
[traceability/hp-rep-001.yaml](traceability/hp-rep-001.yaml) como items +
links, validable con `npm run validate:traceability`. Ver
[traceability/IMPLEMENTATION.md](traceability/IMPLEMENTATION.md).

### Alcance: slice, no Feature completa

Esta es la distincion mas importante del estado actual:

- las Features siguen en estado **`draft`**;
- lo implementado es el **slice que recorre `HP-REP-001`**, no la
  cobertura completa de ninguna Feature;
- **ninguna Feature esta implementada por completo**;
- los **UAT siguen `PENDING`**: los tests internos son evidencia de
  desarrollo, no aceptacion de negocio.

Los caminos alternativos de V1.3 -revision tecnica, overrides, reserva
fallida, retrabajo, cancelacion (FEAT-REP-009), origenes distintos de
CLIENTE_EXTERNO- no estan implementados y figuran como tareas
`NOT_IMPLEMENTED` en la trazabilidad.

### La fuente de verdad no cambio

```text
YAML (business/)  = Source of Truth funcional
JSON Schema       = Contrato de validacion
Mermaid / Viewer  = Visualizacion
```

El codigo **no** es fuente de verdad funcional: si difiere de
`business/`, se reporta la divergencia en vez de reescribir el
requerimiento. React Flow sigue siendo una futura capa de visualizacion
avanzada.

### Comandos principales

```bash
npm run verify:functional-copy         # business/ coincide con su manifiesto (DC02)
npm run verify:functional-copy:source  # ademas, con el commit de origen en ../rt-rma-app
npm run validate:v1.4                  # valida la baseline vigente V1.4
npm run validate:v1.3                  # regresion del historico V1.3
npm run validate:traceability          # valida los grafos de trazabilidad
npm run validate:discrepancies         # la lista baseline/producto esta completa
npm run validate:all                   # todo lo anterior salvo :source
npm run generate:v1.4                  # regenera Mermaid + viewers de V1.4
```

Backend y frontend tienen sus propios comandos: ver sus README.

### Nota sobre datos sensibles

Este repositorio puede ser publico. Antes de incorporar datos reales,
credenciales, configuraciones sensibles, documentacion interna sensible o
evidencias reales de UAT, debe revisarse su politica de visibilidad/acceso.
