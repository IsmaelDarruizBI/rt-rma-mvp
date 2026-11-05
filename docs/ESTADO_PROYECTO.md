# Estado del proyecto Rosario Tecno RMA

Punto de entrada para retomar el desarrollo. Resume dónde está el proyecto y enlaza la documentación que es fuente de verdad de cada tema; no la reemplaza.

**Última actualización:** 04/11/2026, al cerrar la etapa E1 de la migración a PostgreSQL.

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

**Último commit de código:** `6b5cdb8` (E1).

**Estado de desarrollo:**
- El MVP funciona sobre JSON y está en UAT.
- La migración a PostgreSQL avanza por etapas: E0 y E1 están terminadas y la siguiente es E2.

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

## C. Estado de la migración

Plan aprobado el 03/11/2026. Las etapas y sus dependencias son las del plan; los criterios de aceptación se resumen debajo.

| Etapa | Estado | Próxima acción |
|---|---|---|
| E0: Preparación | Completada (`e325e86`) | Ninguna |
| E1: Unidad de trabajo | Completada (`6b5cdb8`) | Ninguna |
| E2: Consultas dedicadas | Pendiente | Diseñar el alcance (sección F) y pedir autorización |
| E3: Catálogos (primeros repositories PostgreSQL) | Pendiente | Después de E2. Cumplir QA-2, QA-3, M2 y M3 |
| E4: Orden (guardado por agregado) | Pendiente | Diseñar la persistencia por agregado y el control de versión |
| E5: Inventario | Pendiente | Reserva, consumo 210 y 211 atómicos, ajustes, override P-06; integridad y concurrencia |
| E6: Acciones e idempotencia | Pendiente | Repetición por clave y commit incierto (M4) |
| E7: Equivalencia completa | Pendiente | La misma suite en modo `json` y en modo `postgres` |
| E8: DEV/UAT desde una máquina local | Pendiente | Conexión real con `verify-full` y medición de latencia. Necesita autorización |
| E9: Cloud Run | Fuera del plan | Requiere una aprobación aparte |

Alcance y criterio de aceptación de cada etapa pendiente:

- **E2.** Reemplaza los recorridos completos con `listar()` por consultas dedicadas y agrega los contratos de repository `reservar_codigo()` y `stock_disponible(insumo_ids, bloquear)`, implementados en JSON. La función de service `stock_disponible` ya existe y es otra cosa. Los tests pasan sin cambios y los resultados son idénticos.
- **E3.** `PostgresCatalogosRepository` y `modelos_equipo`. Los tests de contrato son los mismos para JSON y para PostgreSQL contra la base local.
- **E4.** Mapeador de carga y guardado por agregado, versiones de Detalle, `salida` y documentos. La fixture `HP-REP-001` y unas 10 Órdenes representativas vuelven idénticas después de guardarlas y cargarlas.
- **E5.** Dos hilos compiten por la última unidad: uno gana y el otro recibe el error funcional. No hay deadlocks y `verificar_integridad()` no devuelve filas.
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
| M2 | Una conexión ociosa cortada por la red o el pooler hace fallar con 500 el primer comando | E3 |
| M3 | `BEGIN` y `SET LOCAL` en un solo envío solo se probaron contra PostgreSQL local, no contra Supavisor | E3 |
| QA-2 | El ejecutor restringido debe impedir el control transaccional y los cambios de estado de la sesión | E3 (criterio de aceptación) |
| QA-3 | Los repositories no retienen la conexión; el ejecutor valida vigencia y dueño en cada operación | E3 (criterio de aceptación) |
| Límite conocido | Un `COMMIT` seguido de un `BEGIN` dentro del bloque no se detecta. Lo impide la interfaz restringida de E3 | E3 |
| M4 | Si se pierde la conexión durante el `COMMIT`, el resultado es incierto y la API responde un 500 genérico | E6 |
| L1 a L10 | Observaciones menores: validación de rangos, mensajes, cierre del pool, pruebas | Por etapa |

Otros riesgos registrados:
- **Latencia entre regiones:** Cloud Run en São Paulo y Supabase en Oregón; se mide en E8.
- **Doble escritura no atómica de la Orden al cerrar una reparación** (JSON): ver [`pendientes-producto.md`](pendientes-producto.md).
- **Foto subida cuya registración falla:** ver [`pendientes-producto.md`](pendientes-producto.md). Es una tarea separada, no de una etapa.

## F. Próximos pasos

**Próxima etapa: E2, diseño e implementación de las consultas dedicadas.** No empieza sin autorización.

Punto de partida, medido el 04/11/2026:
- hay 14 llamadas a `contexto.ordenes.listar()` en 9 módulos de `app/backend/app/application` y `app/backend/app/services`: `autorizacion_cliente`, `bandejas`, `clientes`, `consultas`, `fotos`, `identificadores`, `ingreso`, `inventario` e `inventario_global`;
- `reservar_codigo()` y `obtener_para_modificar()` (`SELECT … FOR UPDATE`), previstos en el plan, todavía no existen.

Antes de desarrollar:
1. Identificar todos los usos relevantes de `listar()`.
2. Analizar los recorridos completos de entidades y su costo.
3. Clasificar las necesidades de consulta por caso de uso.
4. Diseñar contratos de consulta específicos.
5. Evaluar consistencia, filtros, paginación y concurrencia.
6. Mantener la compatibilidad con JSON.
7. Definir las pruebas de aceptación de E2.
8. Considerar desde el diseño la interfaz restringida de E3 (QA-2 y QA-3).

Decisiones que requieren aprobación antes de implementar E2:
- el alcance de E2;
- si `obtener_para_modificar()` entra en E2 o en E4;
- si el diseño del ejecutor restringido se define en E2 o en E3.

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
