# Estado del proyecto Rosario Tecno RMA

Punto de entrada para retomar el desarrollo. Resume dónde está el proyecto y enlaza la documentación que es fuente de verdad de cada tema; no la reemplaza.

**Última actualización:** 05/11/2026, al cerrar la etapa E3 de la migración a PostgreSQL.

## A. Estado general

**Objetivo.** Aplicación para gestionar el área de reparaciones de Rosario Tecno: el proceso de Órdenes de Reparación (`PROC-REP`), con trazabilidad desde el proceso de negocio hasta el código, los tests y el UAT.

**Arquitectura y tecnologías:**

| Parte | Contenido |
|---|---|
| `business/` | Fuente de verdad funcional, en YAML. Es una copia generada de `rt-rma-app` (baseline V1.4, aprobada en DC01); no se edita a mano ([sincronización](sincronizacion-funcional.md)) |
| Tooling de la raíz | Node y TypeScript: validaciones, diagramas Mermaid y visor HTML (`package.json`) |
| `app/backend/` | Python 3.11 o posterior, FastAPI y Pydantic v2. Capas `api → application → services → repositories ← storage` ([README](../app/backend/README.md)) |
| `app/frontend/` | React, TypeScript y Vite ([README](../app/frontend/README.md)) |
| `supabase/` | Esquema PostgreSQL para Supabase: migraciones, seeds y pruebas SQL ([README](../supabase/README.md)). La aplicación todavía no lo usa |
| Persistencia en uso | Archivos JSON (`RMA_PERSISTENCIA=json`, el valor por defecto). Un solo worker y una sola instancia |
| UAT publicado | Backend en Cloud Run (`app/backend/Dockerfile`) y frontend en Vercel, sobre JSON |

**Rama de trabajo:** `feat/postgresql-esquema`, que sale de `mvp-v2`.

**Último commit de código:** el de E3, `feat(postgres): implementar infraestructura SQL y catalogos E3` (ver `git log`).

**Estado de desarrollo:**
- El MVP funciona sobre JSON y está en UAT.
- La migración a PostgreSQL avanza por etapas: E0 a E3 están terminadas. Lo siguiente es el discovery de E4, que no se implementa sin autorización.
- PostgreSQL sigue desactivado en la aplicación: `RMA_PERSISTENCIA=postgres` detiene el arranque.

**Funcionalidad:**

- **Implementado (con evidencia en el repositorio):**
  - los slices de los Scenarios `HP-REP-001`, `HP-REP-002` y `HP-REP-003`;
  - el multidetalle;
  - las variantes `EN_REVISION` (`VAR-REP-001/002`) y de ejecución interrumpida (`VAR-REP-003`);
  - las excepciones `EXC-REP-001` a `004`;
  - las reglas que cambiaron en la iteración 1 del UAT.

  Las specs de `mvp-v2` son las 009 a 019 de `specs/`. Los Scenarios tienen su grafo en `traceability/*.yaml`. Las reglas del UAT se describen en [`traceability/IMPLEMENTATION.md`](../traceability/IMPLEMENTATION.md).
- **Alcance real:** son slices, no Features completas. Las Features siguen en `draft` y ningún UAT está aprobado por negocio (constitución, principios IX y XI).
- **Pendiente:**
  - lo que V1.4 define y el producto no hace: [`traceability/discrepancias-baseline-v1.4.md`](../traceability/discrepancias-baseline-v1.4.md);
  - el backlog que dejó el UAT: [`pendientes-producto.md`](pendientes-producto.md).
- **Planificado:** la persistencia PostgreSQL (sección C).

**Aviso:** la introducción de alcance de `app/backend/README.md` y de `app/frontend/README.md` («solo `HP-REP-001`») es anterior a los slices de `mvp-v2`. Para el alcance implementado, mandan la trazabilidad y `specs/`.

## B. Últimos avances

### Base del esquema (02/11/2026): `28b9d15` y `44e8da3`

- Diseño lógico y físico (`docs/postgresql/`) y migraciones, seeds y pruebas SQL en `supabase/`.
- Script que genera la credencial de `rma_api` y la guarda en GCP Secret Manager, sin mostrarla. Otro script verifica TLS a través de Supavisor.
- La CA pública de Supabase, en `supabase/certs/`.

### E0. Preparación de PostgreSQL (03/11/2026): `e325e86`

- `RMA_PERSISTENCIA`: `json` es el valor por defecto; `postgres` valida la configuración y detiene el arranque porque todavía no hay repositories.
- Conexión con psycopg 3, sin sentencias preparadas del lado del servidor. Es una dependencia opcional (`[postgres]`).
- TLS `verify-full` obligatorio contra servidores remotos, con la CA empaquetada en `app/backend/app/datos/supabase-ca.crt` (copia exacta de `supabase/certs`). La URL se valida: no se aceptan varios servidores ni `host`, `hostaddr` o `service` en la query.
- Traducción de SQLSTATE a `ConflictoDeEscrituraError` o `PersistenciaError`, sin exponer secretos ni datos de filas.
- Pruebas contra un PostgreSQL local y descartable (`RMA_TEST_DATABASE_URL`). Cada corrida crea una base con las migraciones de `supabase/` y la borra al terminar.

### E1. Unidad de trabajo (04/11/2026): `6b5cdb8`

- **Contrato `UnidadDeTrabajo`** en `app/backend/app/repositories/unidad_de_trabajo.py`. Los 14 usos de `seccion_critica_*` pasan a `contexto.transaccion()`.
- **Implementación JSON** (`UnidadDeTrabajoJson`): el mismo lock de proceso y el mismo alcance que antes. Da exclusión mutua, no atomicidad.
- **Implementación PostgreSQL** (`app/backend/app/storage/postgres/transaccion.py`), probada solo contra la base local y todavía no conectada a la aplicación:
  - **Pool:** psycopg-pool configurable; si se agota, responde 503 `PERSISTENCIA_NO_DISPONIBLE`.
  - **Inicio:** `BEGIN` con `SET LOCAL lock_timeout` (5 s) y `statement_timeout` (15 s).
  - **Fin:** `COMMIT`, o `ROLLBACK` ante cualquier excepción.
  - **Anidadas:** se unen a la exterior, sin savepoints. Una falla anidada que se atrapa invalida la transacción: no se confirma nada.
  - **Errores:** sin reintentos automáticos; el 409 conserva `sqlstate` y `reintentable`.
- **Revisiones y correcciones:**
  - **H1:** una transacción es del hilo y la tarea asyncio que la abrieron; un contexto copiado no la usa.
  - **M1:** un `COMMIT` o `ROLLBACK` enviado fuera de la unidad se detecta, y el diagnóstico no afirma una reversión que no ocurrió.
  - **QA-1:** un contexto heredado de una transacción que ya terminó puede abrir la suya.
  - **Veredicto de la QA independiente:** APPROVED WITH OBSERVATIONS.
- **Pruebas** (04/11/2026, PostgreSQL 17 local):
  - suite JSON completa: 1371 passed, 49 skipped (las de PostgreSQL, sin la base local);
  - conjunto PostgreSQL más concurrencia JSON: 120 passed en tres corridas, incluido un uvicorn real con pedidos concurrentes;
  - `ruff check` sin errores.
- **Diferencias con el plan original:**
  - E1 incluyó la unidad PostgreSQL, que estaba prevista solo en JSON;
  - la atomicidad de los procesos 210 y 211 (stock y Orden) pasó a E5.

### E2. Consultas dedicadas (05/11/2026)

El detalle, con el inventario de accesos, los contratos y las pruebas, está en [`postgresql/e2-consultas-dedicadas.md`](postgresql/e2-consultas-dedicadas.md).

- **Siete contratos nuevos** en `OrdenReparacionRepository`, implementados en JSON:
  - `obtener_para_modificar` y `reservar_codigo`, que exigen la transacción de la unidad de trabajo;
  - `listar_abiertas`, `listar_por_dni_cliente`, `listar_con_reservas` (conjunto candidato), `listar_con_movimientos` y `claves_de_fotos`.
- **Reemplazos:** 13 de los 14 recorridos completos con `listar()`. Quedan dos usos justificados: el listado general (`GET /orders`) y las evidencias de faltante (F-03).
- **Principio:** el repository filtra por datos persistidos; las reglas siguen en los services.
- **QA independiente:** APPROVED WITH OBSERVATIONS.
  - Se corrigieron tres hallazgos: QA-E2-1 (las bandejas y el detalle de un insumo leen dentro de una transacción), QA-E2-2 (`listar_con_reservas` es un conjunto candidato) y QA-E2-3 (`ValueError` ante parámetros inválidos).
  - QA-E2-4 a QA-E2-10 quedaron registrados.
- **Pruebas** (05/11/2026):
  - suite JSON completa: 1430 passed, 49 skipped (las de PostgreSQL, sin la base local);
  - PostgreSQL 17 local más contrato, consistencia, equivalencia y concurrencia: 179 passed en tres corridas;
  - prueba diferencial de 56 pedidos HTTP contra el código anterior a E2: 0 diferencias;
  - `ruff check` sin errores y `npm run validate:all` pasa.
- **Diferencia con el plan:** el contrato agregado `stock_disponible(insumo_ids, bloquear)` pasó a E5 (DE-1).

### E3. Infraestructura SQL y catálogos (05/11/2026)

El detalle (diseño, implementación, QA y correcciones) está en [`postgresql/e3-catalogos-diseno.md`](postgresql/e3-catalogos-diseno.md), secciones 11 a 13. Los pendientes están en [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md).

- **Infraestructura (E3-A):**
  - un registro de consultas SQL estáticas, con clasificación `LECTURA` o `ESCRITURA`;
  - un lector y un ejecutor restringidos, que validan vigencia y dueño en cada operación (QA-2 y QA-3) y usan siempre el protocolo extendido;
  - `lectura()` con una transacción breve `READ ONLY`;
  - el pool, con un único reemplazo de una conexión cortada (M2), «sin conexión» distinguido de «pool agotado», topes de configuración, `max_idle` y `cerrar_pool`.
- **Catálogos (E3-B):**
  - `PostgresCatalogosRepository` (13 lecturas; el stock queda para E5) y `PostgresModelosEquipoRepository`;
  - pruebas de contrato iguales para JSON y PostgreSQL.
- **Migración local** `20261105000100_e3_catalogos.sql`:
  - `rma.insumo.clave` para el id del dominio, y `orden` en usuarios y medios de pago;
  - una guarda que impide aplicarla sobre datos existentes sin el procedimiento de E8.

  Las cargas iniciales se regeneraron, con validación de referencias y verificación de identidades.
- **M3:** validada contra Supavisor DEV/UAT, solo lectura y con 14 de 14 verificaciones. Su alcance real está en la sección 11.2 del diseño.
- **Auditoría:** una QA independiente, una QA final y una verificación focalizada. Resultado: **APPROVED WITH OBSERVATIONS**, con todos los hallazgos corregidos o registrados con su etapa.
- **Pruebas al cierre** (PostgreSQL 17 local):
  - suite JSON completa: 1639 passed y 121 skipped (las de PostgreSQL, sin la base);
  - conjunto PostgreSQL (E1 a E3, cargas y generador): 460 passed en dos corridas de unos 62 s;
  - pruebas SQL de Supabase: todas pasan;
  - `ruff check` y `ruff format --check` sin errores, y `npm run validate:all` pasa.
- **Sin cambios** en la aplicación, la API, el frontend, Cloud Run, Vercel ni Supabase remoto. PostgreSQL sigue desactivado.

## C. Estado de la migración

Plan aprobado el 03/11/2026. Las etapas y sus dependencias son las del plan; los criterios de aceptación se resumen debajo.

| Etapa | Estado | Próxima acción |
|---|---|---|
| E0: Preparación | Completada (`e325e86`) | Ninguna |
| E1: Unidad de trabajo | Completada (`6b5cdb8`) | Ninguna |
| E2: Consultas dedicadas | Completada (`feat(postgres): implementar consultas dedicadas E2`) | Ninguna |
| E3: Infraestructura SQL y catálogos | Completada (`feat(postgres): implementar infraestructura SQL y catalogos E3`) | Ninguna |
| E4: Orden (guardado por agregado) | Pendiente | Discovery (sección F). Condiciones de entrada: E4-MP y QAF-14 |
| E5: Inventario | Pendiente | Reserva, consumo 210 y 211 atómicos, ajustes, override P-06; integridad y concurrencia |
| E6: Acciones e idempotencia | Pendiente | Repetición por clave y commit incierto (M4) |
| E7: Equivalencia completa | Pendiente | La misma suite en modo `json` y en modo `postgres` |
| E8: DEV/UAT desde una máquina local | Pendiente | Conexión real con `verify-full` y medición de latencia. Necesita autorización |
| E9: Cloud Run | Fuera del plan | Requiere una aprobación aparte |

Alcance y criterio de aceptación de cada etapa pendiente:

- **E4.** Mapeador de carga y guardado por agregado, versiones de Detalle, `salida` y documentos, más la implementación PostgreSQL de los contratos de E2 sobre Órdenes. La fixture `HP-REP-001` y unas 10 Órdenes representativas vuelven idénticas después de guardarlas y cargarlas.
- **E5.** Incluye el contrato agregado `stock_disponible(insumo_ids, bloquear)`, diferido desde E2 (DE-1). Dos hilos compiten por la última unidad: uno gana y el otro recibe el error funcional. No hay deadlocks y `verificar_integridad()` no devuelve filas.
- **E6.** Un reintento con la misma clave devuelve el mismo resultado sin duplicar filas, y el rechazo queda registrado.
- **E7.** Respuestas idénticas en los dos modos (sin contar uuid ni horarios), sin ninguna violación de integridad de la base.
- **E8.** Se informan p50 y p95 por comando; con eso se decide la región. No se registra ningún secreto.

## D. Decisiones arquitectónicas vigentes

**Generales:**
- JSON sigue siendo el comportamiento por defecto. PostgreSQL no está conectado a la ejecución normal: `RMA_PERSISTENCIA=postgres` detiene el arranque hasta que existan los repositories.
- La migración no cambia reglas de negocio. Los únicos cambios de comportamiento aprobados son H-1 a H-4 del diseño lógico, y se aplican igual en los dos modos.
- Se preservan los tests existentes y la compatibilidad funcional: una etapa no cambia expectativas sin aprobación.
- Ninguna credencial va en el repositorio, el frontend ni los logs. A PostgreSQL se accede solo desde FastAPI, con TLS `verify-full` contra servidores remotos.

**Tecnología:**
- psycopg 3 síncrono con psycopg-pool, sin ORM.
- `guardar(orden)` por agregado; los services no cambian.
- La numeración de Órdenes admite huecos.
- El Cliente es una entidad compartida, con una copia histórica en la Orden.
- Las pruebas usan un PostgreSQL local descartable.
- La región se decide después de medir la latencia (E8).

**Transacciones:**
- Son explícitas: las abre la capa de aplicación con `contexto.transaccion()`, nunca una dependencia de FastAPI.
- Dentro de una transacción no se llama a servicios externos (fotos, fuente por DNI, catálogo de Ventas).
- Solo la unidad de trabajo envía `BEGIN`, `COMMIT` y `ROLLBACK`. Los repositories nunca controlan la transacción.
- La transacción pertenece al hilo y la tarea que la abrieron:
  - un contexto heredado de otro dueño, con la transacción todavía vigente, no puede usarla ni abrir otra;
  - un contexto heredado de una transacción que ya terminó puede abrir una nueva e independiente.
- No hay reintentos automáticos sin un diseño explícito.

**Consultas (E2):**
- El repository filtra por datos persistidos; las reglas (situación, autorización, reservas pendientes) siguen en los services.
- Toda lista se devuelve por número de Orden ascendente.
- `obtener_para_modificar` y `reservar_codigo` exigen la transacción de la unidad de trabajo, tanto en JSON como en PostgreSQL.
- `listar_con_reservas` devuelve un conjunto candidato: toda Orden con reservas pendientes y ninguna sin `RESERVA`.
- Las respuestas que combinan varias consultas leen dentro de una transacción.

**SQL y catálogos (E3):**
- Los repositories PostgreSQL no reciben la conexión. Piden a la unidad de trabajo un lector (`lectura()`) o un ejecutor (`ejecutor()`).
- Solo se ejecutan consultas registradas con `consulta(nombre, sql, modo=LECTURA | ESCRITURA)`: SQL estático, revisado y parametrizado. El registro no es un analizador de SQL ni una barrera de seguridad completa.
- El lector solo ejecuta consultas `LECTURA`. Fuera de un comando, `lectura()` abre una transacción breve `READ ONLY`.
- El id del dominio del insumo se guarda en `rma.insumo.clave`, distinto del código comercial y del uuid técnico. Usuarios y medios de pago tienen una columna `orden`.
- Los números se devuelven sin ceros de más, y todo listado tiene un `ORDER BY` explícito.
- La migración de E3 no se aplica en un entorno remoto sin la estrategia de identidad aprobada (procedimiento de E8). Su guarda es operativa, no un control de autorización.

**Ajustes obligatorios del plan:**
1. La idempotencia guarda una respuesta estable por operación y detecta una clave reusada con otros parámetros. Mientras el frontend no envíe claves estables (H-4), no protege de verdad.
2. El guardado por agregado detecta cambios y conflictos de forma robusta, no solo por el largo del historial.
3. Se preservan eventos, versiones de Detalle, autorizaciones, tiempos operativos y movimientos de inventario.
4. GCS, la fuente por DNI y la planilla quedan fuera de las transacciones, con compensaciones probadas.
5. Nunca se afirma que el lock JSON da atomicidad entre archivos.
6. No se cambian el login ni el UAT publicado.

**Infraestructura:**
- Cloud Run sigue con una sola instancia mientras el catálogo de Ventas y el limitador por DNI sean locales a cada instancia.
- Cloud Run, Vercel y Supabase remoto no se tocan sin una autorización explícita.

## E. Riesgos y pendientes

El detalle, asignado por etapa, está en [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md).

| # | Riesgo | Etapa |
|---|---|---|
| E4-MP | Los medios de pago predeterminados no tienen fila en la base: un pago no podría referenciarlos por clave foránea | Condición de entrada de E4 |
| QAF-14 | Después de un `nextval`, `currval` y `lastval` quedan en la sesión del pool | Condición de entrada de E4 |
| QA-E3-4 | El contador que distingue «sin conexión» de «pool agotado» es por unidad de trabajo: con un pool compartido clasifica mal | Antes de conectar el pool a la aplicación (E7 o E9) |
| QA-E3-8 | La equivalencia de orden y formato numérico con JSON depende de que las fuentes estén ordenadas y normalizadas | E7 o E8 |
| QA-E3-6, QA-E3-7, QAF-5, QAF-12, QAF-13 | Identidad de los insumos y `orden` en DEV/UAT: paso de datos verificado, inventario previo y guarda de la migración | E8 |
| Privilegios | El rol de la aplicación hereda de PUBLIC `TEMP`, `UPDATE` sobre `pg_settings` y funciones de sesión; la defensa hoy es el registro | Política antes de E8 |
| M2 | El reemplazo único de una conexión cortada está resuelto; falta medir los cortes reales desde Cloud Run | E8 |
| QAF-6, QAF-7, QAF-9, QAF-11 | Generador de cargas (listas vacías, validación de valores, `TR-OTROS`) y `orden` de filas nuevas | Antes de cargar catálogos reales, E6 o E8 |
| M4 | Si se pierde la conexión durante el `COMMIT`, el resultado es incierto y la API responde un 500 genérico | E6 |
| QA-E2-8 | En JSON, las bandejas y el detalle de un insumo retienen el lock global mientras leen (con 1010 Órdenes, 1,2 s y 2,0 s). Riesgo temporal aceptado, con alerta si supera 500 ms de forma sostenida | JSON (hasta PostgreSQL) |
| F-09 | Snapshot consistente para las respuestas que hacen varias consultas en PostgreSQL (evaluar `REPEATABLE READ`) | E4 |
| F-05, F-06, QA-E2-5 | Qué DNI cuenta con el Cliente compartido, `cerrada_en` en las Órdenes entregadas y el formato del número de Orden por encima de 999999 | E4 |
| F-03, QA-E2-10 | Evidencias de faltante por subcadena de texto; criterio de reserva pendiente con `DESPERDICIO` | E5 |
| L1 a L10 y el resto de E2 y E3 | Observaciones menores de E1, F-07, F-08, QA-E2-4, QA-E2-6, QA-E2-7, QA-E2-9 y QA-E3-L | Por etapa |

Otros riesgos registrados:
- **Latencia entre regiones:** Cloud Run en São Paulo y Supabase en Oregón; se mide en E8.
- **Doble escritura no atómica de la Orden al cerrar una reparación** (JSON): ver [`pendientes-producto.md`](pendientes-producto.md).
- **Foto subida cuya registración falla:** ver [`pendientes-producto.md`](pendientes-producto.md). Es una tarea separada, no de una etapa.

## F. Próximos pasos

**Próximo paso: discovery de E4 (Orden, guardado por agregado).** Conviene hacerlo integrado con E5 a E7, porque comparten el agregado de la Orden, el inventario, la idempotencia y la equivalencia de modos. Empieza con un discovery técnico y un diseño, y no se implementa sin autorización.

Condiciones de entrada de E4 ([`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md)):
1. **E4-MP:** antes de persistir pagos en PostgreSQL, todo medio de pago que use el dominio tiene que existir como fila referenciable.
2. **QAF-14:** las secuencias no deben depender de `currval` ni de `lastval` de una transacción anterior.
3. Los pendientes ya asignados a E4: F-05, F-06, F-09, QA-E2-5 y el vínculo de la unidad de trabajo por contexto (QA-E2-4).

Lo que E4 recibe de E3:
- la unidad de trabajo con `lectura()` y `ejecutor()`;
- el registro de consultas con su clasificación;
- el mapeo de identificadores (`clave` del insumo) y las reglas numéricas.

El contrato de duplicados de movimientos de stock (Q23) sigue asignado a E5.

Recordatorio: no hay modo mixto. Los repositories de catálogos existen, pero la aplicación no los usa hasta la activación integral.

## G. Cómo retomar el desarrollo

En una computadora nueva:

```bash
git clone https://github.com/IsmaelDarruizBI/rt-rma-mvp.git
cd rt-rma-mvp
git switch feat/postgresql-esquema
npm install                         # tooling de business/ y validaciones

cd app/backend
python -m venv .venv                # Python 3.11 o posterior
.venv\Scripts\activate              # Windows
source .venv/bin/activate           # Linux o macOS
pip install -e ".[dev,postgres]"
pytest                              # suite JSON; las de PostgreSQL se saltean
ruff check .
```

**Pruebas de integración con PostgreSQL:**
- Hace falta un PostgreSQL **local** 15 o posterior, con un usuario que pueda crear bases y roles. Se puede instalar nativo o en un contenedor.
- En la máquina de desarrollo original se usó un PostgreSQL 17 embebido (paquete npm `embedded-postgres`), fuera del repositorio.
- Comando, desde `app/backend/`:

  ```bash
  RMA_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres pytest tests/postgres
  ```

- La variable se rechaza si no apunta a un servidor local.
- No hace falta Supabase remoto para desarrollar ni para probar.

**Variables de entorno.** No se versiona ningún secreto.
- **Backend:** usa el prefijo `RMA_`. La lista completa y sus valores por defecto están en `app/backend/app/core/config.py` y en la sección «Configuración» de [`app/backend/README.md`](../app/backend/README.md).
- **`RMA_DATABASE_URL`:** solo con `RMA_PERSISTENCIA=postgres`. Nunca se versiona; en Cloud Run llegará desde Secret Manager.
- **Frontend:** `VITE_API_BASE_URL`, a partir de `app/frontend/.env.example`.

**Antes de una tarea**, leer [`AGENTS.md`](../AGENTS.md) y, según el tema:
- la constitución, en `.specify/memory/constitution.md`;
- `docs/postgresql/`;
- [`sincronizacion-funcional.md`](sincronizacion-funcional.md), si la tarea toca `business/`.
