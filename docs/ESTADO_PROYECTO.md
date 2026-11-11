# Estado del proyecto Rosario Tecno RMA

Punto de entrada para retomar el desarrollo. Resume dónde está el proyecto y enlaza la documentación que es fuente de verdad de cada tema; no la reemplaza.

**Última actualización:** 11/11/2026.

- **Hecho:**
  - autenticación real y DC31 desplegadas en UAT (10/11, `00020-tux`);
  - datos de UAT reiniciados a cero Órdenes (10/11);
  - Supabase de São Paulo migrado, validado y en cero Órdenes, con la revisión de corte `00023-zus` sin tráfico (11/11);
  - consolidación técnica (11/11): CI, respaldo cifrado probado, checklist de seguridad, despliegue y deuda técnica ([`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md)).
- **Falta:**
  - el corte del UAT a São Paulo;
  - activar el respaldo;
  - publicar e integrar la rama.

**Para retomar el trabajo: [`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md)**: estado, pendientes con autorización y criterios para el desarrollo funcional. Corte y vuelta atrás: [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16. Entorno local: [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 5.

## A. Estado general

**Objetivo.** Aplicación para gestionar el área de reparaciones de Rosario Tecno: el proceso de Órdenes de Reparación (`PROC-REP`), con trazabilidad desde el proceso de negocio hasta el código, los tests y el UAT.

**Arquitectura y tecnologías:**

| Parte | Contenido |
|---|---|
| `business/` | Fuente de verdad funcional, en YAML. Es una copia generada de `rt-rma-app` (baseline V1.4, aprobada en DC01); no se edita a mano ([sincronización](sincronizacion-funcional.md)) |
| Tooling de la raíz | Node y TypeScript: validaciones, diagramas Mermaid y visor HTML (`package.json`) |
| `app/backend/` | Python 3.11 o posterior, FastAPI y Pydantic v2. Capas `api → application → services → repositories ← storage` ([README](../app/backend/README.md)) |
| `app/frontend/` | React, TypeScript y Vite ([README](../app/frontend/README.md)) |
| `supabase/` | Esquema PostgreSQL para Supabase: migraciones, seeds y pruebas SQL ([README](../supabase/README.md)). 20 de 20 aplicadas en `rt-rma-db` (Oregón, `us-west-2`) y en `db-rt-rma` (São Paulo, `sa-east-1`) |
| Persistencia en uso | UAT: PostgreSQL en Supabase (`RMA_PERSISTENCIA=postgres`). JSON sigue siendo el valor por defecto local |
| UAT publicado | Backend en Cloud Run (`00020-tux`, con autenticación) y frontend en Vercel, sobre Supabase Oregón. São Paulo, preparado para el corte ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md)) |

**Rama de trabajo:** `feat/postgresql-esquema`, que sale de `mvp-v2`.

**Últimos commits de código:** `61e2a14` (inicio de sesión con usuario y contraseña), `50170e4` (DC31) y `d60c124` (autenticación). Desplegado: `61e2a14`. Sin commit todavía: los scripts de `supabase/scripts/migracion_sp/` y `reinicio_uat/`, su test y esta documentación. Ver `git log`.

**Estado de desarrollo:**
- El MVP está en UAT sobre PostgreSQL, con autenticación real (Supabase Auth, usuario y contraseña) y DC31, solo con datos ficticios y en cero Órdenes ([`autenticacion.md`](autenticacion.md)).
- La base y Auth están replicadas en São Paulo para bajar la latencia. El corte está pendiente de autorización ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md)).
- La migración a PostgreSQL tiene E0 a E7 terminadas: Bloque A (E4 + E5) y Bloque B (E6 + E7, B1 a B6). La app corre localmente sobre PostgreSQL, con los datos persistentes entre reinicios.
- El frontend tiene el rediseño aprobado: sidebar, barra de acciones, modales y «Pendientes» (`fe655d7`).
- **Pendiente para la puesta en marcha:** el corte a São Paulo (resuelve la latencia), paginación y sincronización automática del catálogo de Ventas. Lista priorizada en [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 4.

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

### Consolidación técnica (11/11/2026): commits locales, sin push

- **Estado real verificado:** el público sigue en Oregón (`00020-tux`, `rt-rma-n49rz9qgv…`), coherente. El corte no se ejecutó. São Paulo tiene una Orden de la prueba manual de la vista previa.
- **Commits:** reinicio, herramientas de migración, documentación, cierre de `/docs` (`4af9854`), respaldo cifrado probado de punta a punta (`bea870a`), CI y documentos de cierre.
- **Documentos nuevos:**
  - [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md): despliegue, CI y vuelta atrás;
  - [`RESPALDOS.md`](RESPALDOS.md);
  - [`CHECKLIST_SEGURIDAD_DESPLIEGUE.md`](CHECKLIST_SEGURIDAD_DESPLIEGUE.md);
  - [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md).

Resumen: [`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md).

### Supabase en São Paulo, listo para el corte (11/11/2026): commits `0724fca` y `1c06be5`

**Proyecto nuevo:** `db-rt-rma` (`pcdnmhzwhzymznojndrn`, `sa-east-1`, plan Free).

- **Esquema:** las 20 migraciones del repositorio.
- **Datos:** maestros, usuarios y stock inicial copiados por código.
- **Cuentas de Auth:** las 4, con el mismo id y la misma contraseña (hash bcrypt, por la API de administración).
- **Conexión:** `rma_api` igual al de Oregón, secreto nuevo `rma-uat-sp-database-url:1` y TLS `verify-full` con la CA de la imagen.

**Validación:**

- `verificar` 9/9 y `comparar` 32/32 contra Oregón.
- Recorridos funcionales (HP-REP-001, DC31, idempotencia, stock y permisos): TODO OK; las Órdenes de prueba se borraron con el reinicio.

**Rendimiento:**

- viaje a la base: 179 → 3 ms;
- lecturas en el servidor: 1,08 → 0,06 s; en el cliente, −82,7 %;
- comandos: 2,4–4,7 → 0,24–0,50 s.

**Revisión de corte:** `rt-rma-uat-api-00023-zus` (etiqueta `corte`), sin tráfico. El UAT público sigue en Oregón (`00020-tux`).

Plan, resultados, corte y vuelta atrás: [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md).

### Despliegue de autenticación y DC31, y reinicio de datos de UAT (10/11/2026)

- **Despliegue:** `61e2a14` en `rt-rma-uat-api-00020-tux` (100 %) y en Vercel (`rt-rma-n49rz9qgv…`). Supabase Auth de Oregón tiene 4 cuentas vinculadas a `ADMIN-001`, `COORD-001`, `RECEP-001` y `TECH-001`. Se aplicó la migración `20261110000100_dc31_cancelacion.sql`.
- **Reinicio de datos:** con [`supabase/scripts/reinicio_uat/`](../supabase/scripts/reinicio_uat/) se eliminaron las 10 Órdenes ficticias y sus datos (402 filas) y las 42 fotos del bucket. El UAT quedó en cero Órdenes, con BAT-IP14 10/0. El respaldo externo queda fuera del repositorio.

### Circuito de cancelación DC31 (10/11/2026): desplegado el 10/11

Cancelar un trabajo nunca cancela la Orden: con todos los trabajos cancelados la Orden sigue abierta en `SIN_TRABAJOS_VIGENTES` (PROC-REP-307), sin trabajo técnico. Cancelar la Orden es una acción explícita y terminal (PROC-REP-308, o 306 sin Detalles): exige sin Ejecución, toma, reservas ni saldo, la custodia resuelta, el equipo devuelto si ingresó y ningún trabajo COMPLETO; si algo falla no cambia nada, y si no, cancela lo pendiente y cierra la Orden en el mismo acto. Rechazar o desistir de todo cancela los trabajos (305), no la Orden. La devolución física se registra antes de cancelar. Las Órdenes CANCELADA y abiertas del circuito anterior (OR-000003, 006 y 009 en UAT) lo terminan sin migrar datos: no figuran en Inicio ni Taller, se encuentran en Órdenes. Una Orden sin trabajos vigentes no admite trabajos nuevos: se crea otra Orden. Fuente: `rt-rma-app` `ab928b6` (rama `dc31/cancelacion-explicita`), sincronizada en `business/` ([`sincronizacion-funcional.md`](sincronizacion-funcional.md)). **Antes de desplegarlo** hay que aplicar en Supabase la migración nueva `supabase/migrations/20261110000100_dc31_cancelacion.sql` (aditiva, solo equivalencias del historial para los pasos 305/307/308): sin ella PostgreSQL rechaza guardar esos pasos.

### Autenticación real (09/11/2026): `feat(auth)`, desplegada el 10/11

Supabase Auth (usuario y contraseña, sin registro público) y autorización en FastAPI con los roles de PostgreSQL: token ES256 verificado localmente por JWKS, identidad por `rma.usuario.auth_user_id`, `usuario_id` del pedido igual al de la sesión, 403 por rol en las rutas administrativas y `GET /api/me`. Frontend con `@supabase/auth-js` solo para la sesión. La persona (activo y rol) se lee de PostgreSQL en cada pedido: una desactivación vale desde el pedido siguiente. Sin cambios de reglas de negocio ni de esquema. **No desplegada:** Supabase Auth, Cloud Run y Vercel siguen sin cambios. Diseño, endpoints, configuración y despliegue en [`autenticacion.md`](autenticacion.md). **Ajuste (10/11/2026, sin commit):** los empleados inician sesión con **usuario y contraseña**, sin correo: cada cuenta de Supabase Auth tiene una identidad interna `<usuario>@usuarios.rma.invalid` (dominio reservado), las cuentas las crea, restablece y bloquea Administración con `supabase/scripts/cuentas_rma.py`, y los errores no revelan qué cuentas existen ([`autenticacion.md`](autenticacion.md), sección 3).

### Optimización de rendimiento en UAT (06/11/2026): `c21f289`, `750756c`

Backend en `rt-rma-uat-api-00017-wer` (commit `3249a0a`) y frontend publicado en `rt-rma-uat.vercel.app`. Las lecturas bajaron de 4,5 a 13,6 s a unos 1,0 a 1,2 s, y los comandos de 3,9 a 15,6 s a 2,4 a 4,7 s. Mediciones y riesgos en [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md).

### Rediseño del frontend (06/11/2026): `fe655d7`

Layout común con sidebar colapsable y barra superior contextual: las acciones que el usuario puede ejecutar quedan en la barra (las excepcionales en «Más acciones») y cada una abre su formulario en una ventana que conserva lo escrito. Alta de Orden, inventario y fotos también en ventanas. «Pendientes» reemplaza el «Próximo paso» con las tareas y avisos de `orden.situacion`. Sin cambios de reglas, permisos, endpoints ni idempotencia. 95 tests del frontend y TypeScript sin errores; recorrido funcional local verificado.

### E8, preparación (06/11/2026): `2444773`

`RMA_DB_REMOTO_HABILITADO` habilita una URL remota (solo con `verify-full`); permisos de `rma_backend` verificados localmente; inspección de solo lectura de DEV/UAT con `rma_api`. Procedimiento en [`postgresql/e8-activacion-supabase.md`](postgresql/e8-activacion-supabase.md) y resultados en [`CHECKPOINT_PRE_DEPLOY.md`](CHECKPOINT_PRE_DEPLOY.md), sección 3. Ninguna migración remota aplicada.

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

### Bloque A: A0, A1, A2 y A4 (05/11/2026)

El detalle está en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), secciones 13 y 14, y el resumen para continuar en [`postgresql/CHECKPOINT_A4_HANDOFF.md`](postgresql/CHECKPOINT_A4_HANDOFF.md).

- **A0, A1 y A2:** migración aditiva, `PostgresOrdenReparacionRepository`, alta y lectura sin N+1, bloqueo con `FOR NO KEY UPDATE`, guardado incremental y versión. QA independiente: **APPROVED WITH OBSERVATIONS**.
- **QA-A2-H1 y L-3:** resueltos y aprobados. Una Orden existente solo se guarda si viene de `obtener_para_modificar` en la misma transacción. Una restricción violada ya no se presenta como un conflicto, y el cliente no recibe detalles SQL.
- **A4:** recepción y sus versiones, notas, check-in, fotos, documentos con reemplazos, entrega y devolución. Implementado, probado y aprobado para continuar.
- **Migraciones:** dos nuevas, aditivas, aplicadas y verificadas **solo en PostgreSQL local**.
- **Sin cambios** en el dominio, la API, el frontend, Cloud Run, Vercel ni Supabase remoto. PostgreSQL sigue desactivado.

### Bloque A: A3, finanzas (06/11/2026): `bd59bd3`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 15.

- Pagos (anticipo, parcial, final), anulación, devoluciones de dinero, descuentos y `pago_id` del historial, con guardado incremental, versión y medios de pago por clave foránea.
- Migración aditiva `20261106000300_e4_finanzas.sql`, aplicada **solo en PostgreSQL local**.
- Pruebas: 20 nuevas de A3 pasan. Validación integrada de `tests/postgres`: 295 pasan y 1 falla por una carrera anterior a A3 (A3-3, MINOR).
- **Sin cambios** en el dominio, la API, el frontend ni Supabase remoto. PostgreSQL sigue desactivado.

### Bloque A: A5, consultas dedicadas (06/11/2026): `bd59bd3`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 16.

- Las consultas dedicadas de E2 en PostgreSQL, con la semántica de JSON: abiertas, por DNI, con reservas, con movimientos y claves de fotos.
- QA-A2-M2 resuelto sin cambiar el aislamiento: dentro de un comando la carga se valida por versión y cada Orden no bloqueada se ve en una sola versión.
- Bandejas, pendientes de autorización, búsqueda por DNI y comprobante de ingreso dan lo mismo en JSON y en PostgreSQL.
- Pruebas: contrato E2 con las dos implementaciones (46 pasan, 16 se saltean hasta A6), 10 pruebas nuevas, e integración focalizada (148 pasan, 1 falla por A3-3).
- **Sin cambios** en el dominio, la API, el frontend ni Supabase remoto. PostgreSQL sigue desactivado.

### Bloque A: A6, reservas (06/11/2026): `bd59bd3`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 17.

- Reservas de insumos en el libro de inventario, con el bloqueo de insumos por `clave` después de la Orden (DI-2). Dos técnicos por la última unidad: uno reserva y el otro recibe la reserva fallida funcional.
- QA-A2-M1 y QA-A2-M4 resueltos. Migración `20261106000400_e5_reservas.sql`, solo local.
- Pruebas: 14 nuevas, contrato E2 con reservas (61 pasan, 1 se saltea hasta A7), 121 JSON de la reserva y 28 SQL y de migraciones.
- **Sin cambios** en el dominio, los services, la API, el frontend ni Supabase remoto. PostgreSQL sigue desactivado.

### Bloque A: A7, consumo, ingresos y ajustes (06/11/2026): `bd59bd3`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 18.

- Consumo y liberación del 210 en el libro; ingresos y ajustes con el motivo libre (DI-8 aprobada); el libro como fuente de verdad, con verificación del saldo que calcula el service (DI-1).
- A6-1 y A6-2 resueltos. Migración `20261106000500_e5_movimientos.sql`, solo local.
- Pruebas: 17 nuevas; contrato E2 completo con las dos implementaciones; corpus con movimientos (171 pasan, falla A3-3).
- **Pendiente de decisión:** A7-1, H-1 en el service antes de activar PostgreSQL.
- **Sin cambios** en el dominio, los services, la API, el frontend ni Supabase remoto. PostgreSQL sigue desactivado.

### Bloque B: B4 a B6, activación local (06/11/2026): `b84b87a`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 22. `RMA_PERSISTENCIA=postgres` arranca la app real sobre PostgreSQL **local** (sin fallback a JSON; una URL remota se rechaza hasta E8). Recorrido vivo con pagos, inventario e idempotencia, y los datos sobreviven al reinicio. 277 pruebas focalizadas pasan; las suites completas quedan para el despliegue.

### Bloque B: B2 y B3, COMMIT incierto y claves en la pantalla (06/11/2026): `b84b87a`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 21.

- COMMIT incierto: 503 `PERSISTENCIA_RESULTADO_INCIERTO` sin afirmar nada; con clave, se devuelve lo confirmado. Fotos y catálogo con clave.
- La pantalla manda la clave en las operaciones que crean registros: la misma al reintentar, otra en una operación distinta. El inventario ya no cambia su `operacion_id` en cada clic.
- Validación integrada: 20 PostgreSQL, 140 JSON, 87 del frontend, `tsc` y ruff sin errores.

### Bloque B: B1, idempotencia en el servidor (06/11/2026): `b84b87a`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 20.

- Encabezado opcional `Idempotency-Key` en los comandos que crean registros: un reintento devuelve la respuesta ya confirmada; dos solicitudes simultáneas con la misma clave ejecutan una vez; la misma clave con otros datos da 422.
- Migración `20261107000100_e6_idempotencia.sql`, solo local. Pruebas: 12 nuevas y 167 JSON de los endpoints afectados.
- **Cambio de API, aditivo:** el encabezado opcional y el 422 (B1-3). Sin clave, nada cambia. PostgreSQL sigue desactivado; JSON ignora la clave.

### Bloque A: A8, cierre e integración (06/11/2026): `bd59bd3`

Detalle en [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 19.

- DI-3 (H-1) implementada en el service, en los dos modos: un ajuste no deja el disponible negativo. Cambiaron dos pruebas JSON, por esa regla aprobada.
- A3-3 resuelto; A5-3 aceptado (409 con rollback); A6-3 verificado sin cambio; L-3 reforzada.
- Los recorridos reales del corpus corren por HTTP sobre PostgreSQL y dan lo mismo que en JSON, con saldos, stock e integridad.
- Validación integral: PostgreSQL 704 pasan, ninguna falla; JSON 1663 pasan y 341 se saltean (las de PostgreSQL, sin la base); ruff sin errores.
- **Sin cambios** en el dominio, la API, el frontend ni Supabase remoto. PostgreSQL sigue desactivado.

## C. Estado de la migración

Plan aprobado el 03/11/2026. Las etapas y sus dependencias son las del plan; los criterios de aceptación se resumen debajo.

| Etapa | Estado | Próxima acción |
|---|---|---|
| E0: Preparación | Completada (`e325e86`) | Ninguna |
| E1: Unidad de trabajo | Completada (`6b5cdb8`) | Ninguna |
| E2: Consultas dedicadas | Completada (`feat(postgres): implementar consultas dedicadas E2`) | Ninguna |
| E3: Infraestructura SQL y catálogos | Completada (`feat(postgres): implementar infraestructura SQL y catalogos E3`) | Ninguna |
| E4: Orden (guardado por agregado) | Completada (`f8ade83`, `bd59bd3`) | Ninguna local; migraciones remotas en E8 |
| E5: Inventario | Completada (`bd59bd3`) | Ninguna local; migraciones remotas en E8 |
| E6: Acciones e idempotencia | Completada (`b84b87a`) | Ninguna local; migración remota en E8 |
| E7: Equivalencia completa | Completada (`b84b87a`) | B4 a B6: cableado, equivalencia de los recorridos y activación local. Las suites completas en los dos modos quedan para preparar el despliegue |
| E8: DEV/UAT | **Completada** (06/11/2026, `17bf69a`) | 19 de 19 migraciones en `rt-rma-db`, `verificar_integridad()` vacío. Cargados los catálogos demo (`seeds/desarrollo`): el entorno es UAT, solo para datos de prueba |
| E9: Cloud Run y Vercel | **Completada** (06/11/2026) | `rt-rma-uat-api` sobre PostgreSQL; frontend en `rt-rma-uat.vercel.app`, publicado por CLI. Hoy `00020-tux`, con autenticación (10/11). `00017-wer` no tiene autenticación: no sirve como vuelta atrás |
| E10: Supabase en São Paulo | **Preparada** (11/11/2026) | `db-rt-rma` migrado y validado; revisión `00023-zus` sin tráfico. Falta el corte coordinado ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16) |

**Infraestructura:**
- Supabase DEV/UAT (Oregón) tiene las 20 migraciones aplicadas y es la persistencia de UAT; São Paulo tiene las mismas 20, aplicadas desde cero el 11/11. E3 se aplicó en una transacción con `supabase db query --remote` (`supabase/scripts/e8_aplicar_e3.sql`); el trigger `insumo_clave_por_defecto` se conserva.
- La migración de E3 y las dos del Bloque A están aplicadas y verificadas únicamente en PostgreSQL local.
- No hay datos operativos históricos que migrar. Se conservan los catálogos remotos existentes (5 medios de pago y 36 modelos técnicos).
- PostgreSQL es la persistencia del UAT publicado y de la app local (`RMA_PERSISTENCIA=postgres`).

Alcance y criterio de aceptación de cada etapa pendiente:

- **E4.** Mapeador de carga y guardado por agregado, versiones de Detalle, `salida` y documentos, más la implementación PostgreSQL de los contratos de E2 sobre Órdenes. La fixture `HP-REP-001` y unas 10 Órdenes representativas vuelven idénticas después de guardarlas y cargarlas.
- **E5.** Incluye el contrato agregado `stock_disponible(insumo_ids, bloquear)`, diferido desde E2 (DE-1). Dos hilos compiten por la última unidad: uno gana y el otro recibe el error funcional. No hay deadlocks y `verificar_integridad()` no devuelve filas.
- **E6.** Un reintento con la misma clave devuelve el mismo resultado sin duplicar filas, y el rechazo queda registrado.
- **E7.** Respuestas idénticas en los dos modos (sin contar uuid ni horarios), sin ninguna violación de integridad de la base.
- **E8.** Se informan p50 y p95 por comando; con eso se decide la región. No se registra ningún secreto.

## D. Decisiones arquitectónicas vigentes

**Generales:**
- JSON sigue siendo el comportamiento por defecto. `RMA_PERSISTENCIA=postgres` activa PostgreSQL entero, sin modo mixto ni fallback: local por defecto; un servidor remoto solo con `RMA_DB_REMOTO_HABILITADO=true` y `verify-full`.
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
| E4-MP | Resuelto en A0: los medios de pago predeterminados tienen fila en la base | Cerrado |
| QAF-14 | Resuelto en A0: el registro de consultas rechaza `currval` y `lastval` | Cerrado |
| Riesgos residuales del Bloque A | A5-3 aceptado, DI-3 en la documentación funcional, A4-1, los de datos históricos (E8) y los de E6 y B4 | [`postgresql/e4-e7-diseno-integrado.md`](postgresql/e4-e7-diseno-integrado.md), sección 19.5 |
| DI-8 | Resuelto en A7: el motivo del ajuste es el texto libre y el código del catálogo queda opcional | Cerrado |
| QA-E3-4 | El contador que distingue «sin conexión» de «pool agotado» es por unidad de trabajo: con un pool compartido clasifica mal | Antes de conectar el pool a la aplicación (E7 o E9) |
| QA-E3-8 | La equivalencia de orden y formato numérico con JSON depende de que las fuentes estén ordenadas y normalizadas | E7 o E8 |
| QA-E3-6, QA-E3-7, QAF-5, QAF-12, QAF-13 | Identidad de los insumos y `orden` en DEV/UAT: paso de datos verificado, inventario previo y guarda de la migración | E8 |
| Privilegios | El rol de la aplicación hereda de PUBLIC `TEMP`, `UPDATE` sobre `pg_settings` y funciones de sesión; la defensa hoy es el registro | Política antes de E8 |
| M2 | El reemplazo único de una conexión cortada está resuelto; falta medir los cortes reales desde Cloud Run | E8 |
| QAF-6, QAF-7, QAF-9, QAF-11 | Generador de cargas (listas vacías, validación de valores, `TR-OTROS`) y `orden` de filas nuevas | Antes de cargar catálogos reales, E6 o E8 |
| M4 | Resuelto en B2: 503 `PERSISTENCIA_RESULTADO_INCIERTO` y recuperación con la clave | Cerrado |
| QA-E2-8 | En JSON, las bandejas y el detalle de un insumo retienen el lock global mientras leen (con 1010 Órdenes, 1,2 s y 2,0 s). Riesgo temporal aceptado, con alerta si supera 500 ms de forma sostenida | JSON (hasta PostgreSQL) |
| F-09 | Resuelto: la lectura breve usa `REPEATABLE READ` y, dentro de un comando, la carga se valida por versión (QA-A2-M2, A5) | Cerrado |
| F-05 | La búsqueda por DNI usa la copia de la Orden (A5). Sigue abierto qué hacer con el documento de un cliente reutilizado sin DNI (QA-A2-L1) | B4 |
| F-03, QA-E2-10 | Evidencias de faltante por subcadena de texto; criterio de reserva pendiente con `DESPERDICIO` | E5 |
| L1 a L10 y el resto de E2 y E3 | Observaciones menores de E1, F-07, F-08, QA-E2-4, QA-E2-6, QA-E2-7, QA-E2-9 y QA-E3-L | Por etapa |

Otros riesgos registrados:
- **Latencia entre regiones:** Cloud Run en São Paulo y Supabase en Oregón, unos 179 ms por viaje: lecturas de 1,08 s en el servidor y comandos de 2,4 a 4,7 s. Se resuelve con el corte a São Paulo (3 ms por viaje; lecturas de 0,06 s). Medición en [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 8.
- **Período de vuelta atrás:** Oregón se conserva 14 días después del corte. En plan Free se pausa a los 7 días sin actividad: hace falta actividad semanal.
- **Doble escritura no atómica de la Orden al cerrar una reparación** (JSON): ver [`pendientes-producto.md`](pendientes-producto.md).
- **Foto subida cuya registración falla:** ver [`pendientes-producto.md`](pendientes-producto.md). Es una tarea separada, no de una etapa.

## F. Próximos pasos

**Próximo paso:** los P0 de [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md), cada uno con autorización.

1. **Publicar la rama** e integrarla en `mvp-v2` (avance rápido); CI en verde.
2. **Decidir sobre `OR-000001` en São Paulo** y ejecutar el corte ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16). Vuelta atrás: `00020-tux` y `rt-rma-n49rz9qgv…`.
3. **Activar el respaldo** ([`RESPALDOS.md`](RESPALDOS.md), sección 4).

Después empieza el desarrollo funcional, con los criterios de [`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md), sección 7.

Recordatorio: no hay modo mixto. Los datos creados en PostgreSQL no vuelven a JSON.

## G. Cómo retomar el desarrollo

En una computadora nueva (pasos completos, con PostgreSQL local y `rma_dev`: [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 5):

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
- En la máquina de desarrollo original se usó un PostgreSQL 17 embebido (paquete npm `embedded-postgres`), fuera del repositorio. Los comandos están en [`postgresql/CHECKPOINT_A4_HANDOFF.md`](postgresql/CHECKPOINT_A4_HANDOFF.md), sección 11.
- Comando, desde `app/backend/`:

  ```bash
  RMA_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:5432/postgres pytest tests/postgres
  ```

- La variable se rechaza si no apunta a un servidor local.
- No hace falta Supabase remoto para desarrollar ni para probar.

**Variables de entorno.** No se versiona ningún secreto.
- **Backend:** usa el prefijo `RMA_`. La lista completa y sus valores por defecto están en `app/backend/app/core/config.py` y en la sección «Configuración» de [`app/backend/README.md`](../app/backend/README.md).
- **`RMA_DATABASE_URL`:** solo con `RMA_PERSISTENCIA=postgres`. Nunca se versiona; en Cloud Run sale de Secret Manager (`rma-uat-database-url:latest`).
- **Frontend:** `VITE_API_BASE_URL`, a partir de `app/frontend/.env.example`.

**Antes de una tarea**, leer [`AGENTS.md`](../AGENTS.md) y, según el tema:
- la constitución, en `.specify/memory/constitution.md`;
- `docs/postgresql/`;
- [`sincronizacion-funcional.md`](sincronizacion-funcional.md), si la tarea toca `business/`.
