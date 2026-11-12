# Estado del proyecto Rosario Tecno RMA

Punto de entrada para retomar el desarrollo. Resume dónde está el proyecto y enlaza la documentación que es fuente de verdad de cada tema; no la reemplaza.

**Última actualización:** 12/11/2026.

- **Hecho:**
  - autenticación real y DC31 desplegadas en UAT (10/11, `00020-tux`);
  - datos de UAT reiniciados a cero Órdenes (10/11);
  - Supabase de São Paulo migrado, validado y en cero Órdenes, con la revisión de corte `00023-zus` sin tráfico (11/11);
  - consolidación técnica (11/11): CI, respaldo cifrado probado, checklist de seguridad, despliegue y deuda técnica ([`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md));
  - corte del UAT a São Paulo y respaldo diario activo (11/11);
  - **iteración funcional 1 cerrada** (11/11): DC06, DC07, DC11 y DC15B alineadas con V1.4 y las cinco decisiones DEC-IT1-01 a 05 incorporadas en `rt-rma-app` (`708d81b`) e implementadas (sección B);
  - **iteración 1 en UAT** (12/11): migración `20261111000100` en São Paulo, Cloud Run `00027-sas` (`14108ef`) y Vercel `dpl_CdRi5ttvBwRnxfADjtM4yRVjUkS2` (sección B);
  - **macroiteración funcional** (12/11): evaluación técnica, reparaciones adicionales, desistimiento total guiado, antecedentes del equipo, reporte operativo y configuración auditada; integrada en `mvp-v2` (`5c6137e`) con el CI en verde (sección B);
  - **macroiteración en UAT** (12/11): migraciones `20261112000100` y `20261112000200` en São Paulo, Cloud Run `00029-kay` (`5c6137e`) y Vercel `dpl_CRXZubTCVE1ALhZmLe2wHhoZhbWR` (sección B).
- **Falta:**
  - las decisiones abiertas que bloquean el resto de la macroiteración (`rt-rma-app`, `docs/consolidation/README.md`, sección I);
  - la validación autenticada en UAT con una cuenta real (lecturas y recorridos de la iteración 1 y de la macroiteración; sección F);
  - integrar en `main` (P0-2).

**Para retomar el trabajo: [`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md)**: estado, pendientes con autorización y criterios para el desarrollo funcional. Corte y vuelta atrás: [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16. Entorno local: [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 5. En otra computadora: [`CONTINUIDAD.md`](CONTINUIDAD.md).

## A. Estado general

**Objetivo.** Aplicación para gestionar el área de reparaciones de Rosario Tecno: el proceso de Órdenes de Reparación (`PROC-REP`), con trazabilidad desde el proceso de negocio hasta el código, los tests y el UAT.

**Arquitectura y tecnologías:**

| Parte | Contenido |
|---|---|
| `business/` | Fuente de verdad funcional, en YAML. Es una copia generada de `rt-rma-app` (baseline V1.4, aprobada en DC01); no se edita a mano ([sincronización](sincronizacion-funcional.md)) |
| Tooling de la raíz | Node y TypeScript: validaciones, diagramas Mermaid y visor HTML (`package.json`) |
| `app/backend/` | Python 3.11 o posterior, FastAPI y Pydantic v2. Capas `api → application → services → repositories ← storage` ([README](../app/backend/README.md)) |
| `app/frontend/` | React, TypeScript y Vite ([README](../app/frontend/README.md)) |
| `supabase/` | Esquema PostgreSQL para Supabase: migraciones, seeds y pruebas SQL ([README](../supabase/README.md)). 23 de 23 aplicadas en `db-rt-rma` (São Paulo, `sa-east-1`): la 21 (`20261111000100_it1_alineacion_v14.sql`), la 22 (`20261112000100_evaluacion_tecnica.sql`) y la 23 (`20261112000200_configuracion_auditada.sql`), aditivas, el 12/11/2026. Oregón (`rt-rma-db`, vuelta atrás) queda en 20 |
| Persistencia en uso | UAT: PostgreSQL en Supabase (`RMA_PERSISTENCIA=postgres`). JSON sigue siendo el valor por defecto local |
| UAT publicado | Desde el 12/11/2026 a las 15:14 UTC, macroiteración V1.4 sobre Supabase São Paulo: backend en Cloud Run (`00029-kay`, código `5c6137e`) y frontend en Vercel (`dpl_CRXZubTCVE1ALhZmLe2wHhoZhbWR`). Vuelta atrás inmediata: `00027-sas` y `dpl_CdRi5ttv…` ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), sección 6). Oregón sigue como vuelta atrás de la migración hasta el 25/11/2026 |

**Rama de trabajo:** `mvp-v2`, con la macroiteración integrada por avance rápido el 12/11/2026 (`feat/macro-v14`, publicada). CI en verde en la rama y en `mvp-v2`. `business/` viene de `rt-rma-app` `420feb9` (rama `spec/macro-v14`, publicada). `main` sin cambios. Integrar no publica: el UAT se despliega aparte ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md)).

**Últimos commits de código:** `673dc7d` (macroiteración), `5c6137e` (cierre de QA) y `14108ef` (iteración 1). Desplegado: `5c6137e` (macroiteración), desde el 12/11/2026. Ver `git log`.

**Estado de desarrollo:**
- El MVP está en UAT sobre PostgreSQL, con autenticación real (Supabase Auth, usuario y contraseña) y DC31, solo con datos ficticios y en cero Órdenes ([`autenticacion.md`](autenticacion.md)).
- El UAT corre sobre São Paulo desde el 11/11/2026 ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16).
- La migración a PostgreSQL tiene E0 a E7 terminadas: Bloque A (E4 + E5) y Bloque B (E6 + E7, B1 a B6). La app corre localmente sobre PostgreSQL, con los datos persistentes entre reinicios.
- El frontend tiene el rediseño aprobado: sidebar, barra de acciones, modales y «Pendientes» (`fe655d7`).
- **Pendiente para la puesta en marcha:** el respaldo automático, paginación y sincronización automática del catálogo de Ventas. Lista priorizada en [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 4.

**Funcionalidad:**

- **Implementado (con evidencia en el repositorio):**
  - los slices de los Scenarios `HP-REP-001`, `HP-REP-002` y `HP-REP-003`;
  - el multidetalle;
  - las variantes `EN_REVISION` (`VAR-REP-001/002`) y de ejecución interrumpida (`VAR-REP-003`);
  - las excepciones `EXC-REP-001` a `004`;
  - las reglas que cambiaron en la iteración 1 del UAT;
  - en la rama de la iteración funcional 1: `VAR-REP-038`, `039`, `041` y `042`, y DC06 ([`traceability/iteracion-1-v14.yaml`](../traceability/iteracion-1-v14.yaml));
  - en la macroiteración: `VAR-REP-019` y `VAR-REP-043`, evaluación técnica, reparaciones adicionales, configuración auditada y antecedentes del equipo ([`traceability/macro-v14.yaml`](../traceability/macro-v14.yaml)).

  Las specs de `mvp-v2` son las 009 a 019 de `specs/`. Los Scenarios tienen su grafo en `traceability/*.yaml`. Las reglas del UAT se describen en [`traceability/IMPLEMENTATION.md`](../traceability/IMPLEMENTATION.md).
- **Alcance real:** son slices, no Features completas. Las Features siguen en `draft` y ningún UAT está aprobado por negocio (constitución, principios IX y XI).
- **Pendiente:**
  - lo que V1.4 define y el producto no hace: [`traceability/discrepancias-baseline-v1.4.md`](../traceability/discrepancias-baseline-v1.4.md);
  - el backlog que dejó el UAT: [`pendientes-producto.md`](pendientes-producto.md).
- **Planificado:** la persistencia PostgreSQL (sección C).

**Aviso:** la introducción de alcance de `app/backend/README.md` y de `app/frontend/README.md` («solo `HP-REP-001`») es anterior a los slices de `mvp-v2`. Para el alcance implementado, mandan la trazabilidad y `specs/`.

## B. Últimos avances

### Despliegue de la macroiteración V1.4 en UAT (12/11/2026)

- **Antes:** `mvp-v2` limpio y sincronizado en `5c6137e`; `business/` igual a `420feb9`; tráfico 100 % en `00027-sas`; Vercel `dpl_CdRi5ttv…`, desconectado de GitHub; São Paulo con 21 migraciones, 0 Órdenes y los mismos conteos que el respaldo de las 06:00 UTC, sin actividad; respaldo previo `uat/20261112T145502Z` (ejecución `rt-rma-respaldo-db-5ncpg`).
- **Compatibilidad:** las dos migraciones son aditivas (columna que admite vacío, CHECK ampliado que conserva los valores anteriores, dos tablas inmutables, una vista, permisos y equivalencias con `on conflict do nothing`). Las pruebas de `14108ef` (el código de `00027-sas`) pasan sobre el esquema migrado, salvo las 2 que cuentan tablas. Nueva prueba [`test_permisos_macro_v14.py`](../app/backend/tests/postgres/test_permisos_macro_v14.py): las pruebas PostgreSQL de la evaluación, los adicionales y la configuración corren con un rol de login miembro de `rma_backend`, como `rma_api` en UAT (antes solo corrían como superusuario): 9 de 9; suite `tests/postgres` completa 410 de 410.
- **Migraciones:** `supabase db push --dry-run` mostró solo `20261112000100` y `20261112000200`; aplicadas a las 14:59 UTC. Registradas (23); `detalle.origen_diagnostico` que admite vacío y su CHECK; `cancelacion_origen` con DESCARTE_TECNICO; `evaluacion_tecnica` y `cambio_configuracion` con sus restricciones y triggers de inmutabilidad; vista `historial_precio`; 47 tablas; equivalencias 182, 183, 184 y 128 (94 en total). `rma_backend`: SELECT e INSERT en las tablas nuevas (sin UPDATE ni DELETE), SELECT en la vista y DELETE en `mesa_tipo_reparacion`. `rma_respaldo` lee las tablas nuevas y no escribe. `anon` y `authenticated` sin acceso. Integridad: el ensayo de restauración en la nube (`rt-rma-respaldo-db-8k7zh`) restauró con 23 migraciones, 47 tablas con sus conteos, `verificar_integridad()` sin problemas, secuencias iguales y 4 cuentas.
- **Backend:** revisión `rt-rma-uat-api-00029-kay` (etiqueta `v14-5c6137e`, imagen `sha256:e2568619d764…`), construida desde una exportación limpia de `5c6137e`, con la plantilla de `00027-sas`: las mismas 14 variables (São Paulo, secreto `rma-uat-sp-database-url:1`, CORS solo del frontend, fotos en GCS), la misma cuenta, recursos y escalado. Por la etiqueta: arranque con la base, `/health` 200, 401 sin token y con token inválido, también en los endpoints nuevos (reportes, antecedentes, administración, evaluación y adicionales), `/docs`, `/redoc` y `/openapi.json` 404 y CORS sin origen ajeno.
- **Frontend:** `vercel deploy --prod --skip-domain` desde una exportación limpia de `5c6137e` (`dpl_CRXZubTCVE1ALhZmLe2wHhoZhbWR`, `rt-rma-62sdml5sb…`). El bundle apunta a São Paulo y a la API pública, sin Oregón ni URL de etiqueta, solo con la clave publicable, sin JWT ni claves secretas, y con el contrato nuevo. Las mismas 5 variables `VITE_*`.
- **Corte coordinado:** de 15:13:46 a 15:14:43 UTC (tráfico del backend y `vercel promote`).
- **Después:** tráfico 100 % en `00029-kay`; el dominio sirve `dpl_CRXZ…`; la API pública (las dos URL) repite los controles; la pantalla de ingreso carga sin errores, salvo el `favicon.ico` 404 que ya existía; sin errores, 5xx ni credenciales en los registros. Respaldo posterior `uat/20261112T151635Z` (`rt-rma-respaldo-db-t2lzw`): 23 migraciones; el único cambio de conteos son las 4 equivalencias nuevas.
- **Sin validar en UAT:** el inicio de sesión, las lecturas autenticadas y los recorridos de la macroiteración (evaluación, adicionales, desistimiento total, Configuración, antecedentes y reportes). Piden la contraseña de una cuenta real y los recorridos escriben datos; no se crearon Órdenes ni se cambió la configuración. La cobertura está en las pruebas JSON y PostgreSQL, en la prueba con `rma_backend` y en la verificación por interfaz sobre PostgreSQL local.

### Macroiteración de desarrollo funcional (12/11/2026), rama `feat/macro-v14`

Commits sobre `mvp-v2` (`6e6bf0b`), publicados e integrados por avance rápido en `mvp-v2` (`5c6137e`) con el CI en verde. Especificación: `rt-rma-app` `spec/macro-v14` (`420feb9`), sincronizada en `business/`. Diferencias con la baseline: [`discrepancias-baseline-v1.4.md`](../traceability/discrepancias-baseline-v1.4.md), sección H. Sin decisiones nuevas: lo bloqueado por decisiones abiertas figura en la sección I del README de consolidación de `rt-rma-app`.

- **Evaluación técnica (BR-REP-035/036, HP-REP-001/002, VAR-REP-019):** todo Detalle diagnosticado por Recepción se evalúa antes de su primera Ejecución (182 → 183 → 184): CONFIRMADO, DESCARTADO (cancelación por descarte técnico) o REQUIERE_REDEFINICION (127 en el mismo acto). La hace el técnico titular de la toma; no reserva ni consume. Los Detalles anteriores (sin origen del diagnóstico) no la exigen: plan de transición sin migrar datos.
- **Reparaciones adicionales (PROC-REP-128, BR-REP-037):** desde la evaluación (antes del resolver, para que un descarte no deje la Orden sin trabajos) o como acción complementaria durante la participación. Nacen pendientes del cliente en CLIENTE_EXTERNO; la Ejecución en curso sigue.
- **Desistimiento total guiado (DC07C, VAR-REP-043):** con una Ejecución activa se registra la solicitud en cada trabajo; al interrumpir, el técnico los cancela juntos (211 → 305). Lo COMPLETO se conserva; DC31 sin cambios.
- **Antecedentes del equipo (BR-REP-022):** otras Órdenes con el mismo IMEI o número de serie, en el detalle de la Orden.
- **Reporte operativo v1 (DC29, sin umbrales):** pantalla «Reportes».
- **Configuración (DC23, DC23AUD):** pantalla «Configuración», solo Administración y sobre PostgreSQL: Tipos de Reparación y Tipos habilitados por Mesa, con auditoría inmutable e historial de precios. En el modo JSON es de solo lectura.
- **Interfaz:** botones por trabajo con el nombre del trabajo cuando hay varios. Recorridos verificados en el navegador sobre datos locales: evaluación con adicional, inicio, adicional durante la ejecución, antecedentes, reportes y configuración.
- **Migraciones aditivas:** `20261112000100_evaluacion_tecnica.sql` y `20261112000200_configuracion_auditada.sql`, aplicadas en São Paulo el 12/11/2026 (ver el despliegue).
- **Pruebas:** JSON 1777 pasan, 0 fallan (397 omitidas, las de PostgreSQL); `tests/postgres`: suite completa 400 pasan y 1 falla (la prueba que cuenta tablas y vistas: 47 y 7 por la adición prevista; ajustada, su archivo pasa 18 de 18); compatibilidad hacia atrás: las de `14108ef` sobre el esquema migrado, 387 pasan y 2 fallan, ambas pruebas de inventario del esquema; `ruff` sin errores; frontend: typecheck, 124 tests y build; `npm run validate:all` y `validate:v1.4` en verde; búsqueda de secretos limpia.
- **Cierre de QA (12/11/2026):** la transición no deja omitir la evaluación (toda alta nueva fija el origen, el cliente no puede elegirlo y RT_INTERNO también la exige); Configuración probada en el navegador contra PostgreSQL local (alta, edición, Mesas, auditoría y persistencia tras recargar); reportes, antecedentes y administración exigen sesión, la administración da 403 a los demás roles y las consultas no devuelven datos personales del cliente; rendimiento del reporte medido y con umbral de reemplazo ([`DEUDA_TECNICA.md`](DEUDA_TECNICA.md), P1-12); trazabilidad en [`traceability/macro-v14.yaml`](../traceability/macro-v14.yaml); README del backend al día con PostgreSQL.
- **Regresión final del cierre:** JSON 1783 pasan, 0 fallan (397 omitidas, las de PostgreSQL); `tests/postgres` 401 pasan, 0 fallan; `ruff`, typecheck, 124 tests y build del frontend; `validate:all`, copia de `business/` contra `420feb9`, búsqueda de secretos y `git diff --check` en verde.

### Despliegue de la iteración 1 en UAT (12/11/2026)

- **Antes:** Git limpio en `14108ef`; tráfico 100 % en `00024-top`; Vercel `dpl_6vsL…`, desconectado de GitHub; São Paulo con 0 Órdenes, 20 migraciones y sin columnas nuevas; respaldo previo `uat/20261112T031447Z` (ejecución `rt-rma-respaldo-db-jsk68`); `business/` igual a `708d81b`.
- **Compatibilidad hacia atrás demostrada:** las pruebas `tests/postgres` de `d226fd2` (el código de `00024-top`) sobre sus 20 migraciones más la nueva: 383 de 384 pasan. La única falla es la prueba SQL que cuenta exactamente 51 tipos de evento (ahora 52 por EV-REP-052): es la adición prevista, no un fallo de funcionamiento.
- **Migración:** `supabase db push --dry-run` mostró solo `20261111000100`; aplicada. Registrada, 13 columnas y 3 restricciones nuevas, 52 eventos de negocio, 90 equivalencias, permisos de `rma_backend` y `rma_respaldo` sobre las columnas nuevas y `verificar_integridad()` sin problemas.
- **Backend:** revisión `rt-rma-uat-api-00027-sas` (etiqueta `it1-14108ef`, imagen `sha256:a3d960a7aa5d…`), con la plantilla de `00024-top` (São Paulo, secreto `rma-uat-sp-database-url:1`, CORS solo del frontend, fotos en GCS). Por la etiqueta: arranque con la base (sin base no arranca), `/health` 200, 401 sin token y con token inválido, `/docs`, `/redoc` y `/openapi.json` 404, CORS sin origen ajeno.
- **Frontend:** `vercel deploy --prod --skip-domain` desde una exportación limpia de `14108ef`; luego `vercel promote`. Corte coordinado de 03:27:12 a 03:27:24 UTC (tráfico del backend y promoción).
- **Después:** tráfico 100 % en `00027-sas`; Vercel sirve `dpl_CdRi5ttvBwRnxfADjtM4yRVjUkS2`; el bundle apunta a São Paulo y a la API pública, solo con la clave publicable, sin JWT ni claves secretas, con el contrato nuevo; la API pública repite los controles; Auth con registro deshabilitado, solo `email` y JWKS `ES256`; sin errores, 5xx ni credenciales en los registros.
- **Respaldos:** la migración 21 se agregó a `_herramientas/migraciones/` y el ensayo en la nube (`rt-rma-respaldo-db-kk6k6`) restauró con 21 migraciones, 45 tablas, integridad y secuencias correctas y 4 cuentas.
- **Sin validar en UAT:** las lecturas y los recorridos autenticados. Piden la contraseña de una cuenta real (no se usa ni se crea ninguna sin la persona responsable) y los recorridos escriben datos. La cobertura funcional está en las pruebas JSON y PostgreSQL y en la verificación por interfaz sobre datos locales.

### Iteración funcional 1: alineación con V1.4 (11/11/2026), rama `feat/iteracion-1-alineacion-v14`

Commit local sobre `mvp-v2`, sin push ni merge. Diferencias con la baseline: [`discrepancias-baseline-v1.4.md`](../traceability/discrepancias-baseline-v1.4.md), sección G. Trazabilidad: [`iteracion-1-v14.yaml`](../traceability/iteracion-1-v14.yaml).

- **DC15B (`VAR-REP-038`/`039`):** la garantía RMA valida la vigencia de cada Detalle origen (PROC-REP-036: entrega + días de garantía). Vigente: 035 → 036 → 040. Vencida sin excepción: 409 `GARANTIA_VENCIDA`, no se crea la Orden. Con motivo y un usuario autorizado se admite y queda auditado quién, cuándo, por qué, el Detalle y el vencimiento (EV-REP-052). La Orden entregada muestra la vigencia de cada trabajo.
- **DC06:** definir luego de la revisión (075), cerrar esa carga y redefinir (127) son del Técnico; la decisión y el desistimiento del cliente siguen en Recepción.
- **DC07/DC07B (`VAR-REP-042`):** desistir de un trabajo en ejecución registra la solicitud (EV-REP-046) sin cancelar; el técnico solo puede interrumpirlo, indicando cómo queda el trabajo y si se puede revertir; al interrumpir se cancela, con la solicitud conservada. DC31 sin cambios.
- **DC11 (`VAR-REP-041`):** cortesía total como Ajuste Comercial de clase CORTESIA: conserva los pagos, deja saldo a favor y bloquea la entrega hasta la devolución.
- **Interfaz:** los cuatro recorridos y DC06 se completaron en el navegador sobre datos locales (formulario de garantía con vigencia y excepción, cortesía, solicitud de desistimiento, interrupción con estado y reversibilidad).
- **Migración aditiva** `20261111000100_it1_alineacion_v14.sql`: columnas que admiten vacío, `descuento.clase` con valor por defecto, EV-REP-052 y tres equivalencias del historial. No se aplicó en ninguna base remota.
- **Pruebas:** JSON 1717 pasan y 29 se saltean; `tests/postgres` 387 pasan; `ruff` sin errores; frontend: typecheck, 123 tests y build; `npm run validate:all` en verde.
- **Pruebas** de la primera entrega: JSON 1717, `tests/postgres` 387 y frontend 123.

**Cierre funcional (11/11/2026): decisiones DEC-IT1-01 a 05.** Especificadas en `rt-rma-app` (`708d81b`, rama `spec/iteracion-1-decisiones`: reglas, PROC-REP-036, VAR-REP-038/039/041/042, Features, registro con ABI-04, 18, 26 y 33 cerrados, matriz, diseño lógico y vistas) y sincronizadas en `business/`.

- **DEC-IT1-01:** la excepción de garantía la autorizan Recepción, Coordinación RMA o Administración; el Técnico no. Lo valida el backend.
- **DEC-IT1-03:** vigencia y excepción **por trabajo**. Un pedido con un vencido sin excepción no crea nada e informa los elegibles; la pantalla pide un motivo por cada vencido o permite desmarcarlos. La excepción vive en cada fila de `orden_detalle_origen` (la migración `20261111000100` se ajustó en el lugar: no estaba publicada ni aplicada).
- **DEC-IT1-02:** cortesía total o parcial (porcentaje o importe) con el mismo Ajuste Comercial; la otorgan, modifican o quitan los tres roles. Con saldo a favor la entrega se bloquea hasta devolver. El ajuste es idempotente (`Idempotency-Key`, efectivo con PostgreSQL).
- **DEC-IT1-04 y 05:** reversibilidad Sí o No y descripción obligatoria al interrumpir para cancelar; la cancelación efectiva queda a nombre del técnico que interrumpió, separada de la solicitud de Recepción.
- **Interfaz:** recorridos verificados en el navegador con los roles de cada decisión (excepción de un trabajo entre tres, desmarcar vencidos, cortesía parcial con devolución y entrega, modificar o quitar, desistimiento e interrupción no reversible).
- **Pruebas finales:** sección F.

### Preparación para el cambio de computadora (11/11/2026)

- [`CONTINUIDAD.md`](CONTINUIDAD.md) reescrito con la arquitectura de São Paulo; es la guía para retomar.
- Auditoría de portabilidad: [`AUDITORIA_PORTABILIDAD.md`](AUDITORIA_PORTABILIDAD.md).
- La guía de pruebas manual del UAT quedó versionada en [`qa/guia-pruebas-uat.html`](qa/guia-pruebas-uat.html).
- El commit local de `rt-rma-app` se archivó en `archivo/test-v1.2-3cf273e`.
- Se traslada a mano la clave privada `age` ([`CONTINUIDAD.md`](CONTINUIDAD.md), sección 7).

### Consolidación técnica cerrada (11/11/2026)

- **Respaldo operativo:** la persona responsable descifró la copia real (`uat/20261111T193144Z`) con su clave privada: `rma.dump.age` y `auth.dump.age` dan `PGDMP`.
- **Infraestructura de São Paulo** (verificación de solo lectura):
  - `00024-top` con el 100 % del tráfico;
  - Vercel `dpl_6vsL…` publicado contra São Paulo;
  - Job y Scheduler de respaldo habilitados, con 4 copias en el bucket;
  - sin errores recientes.
- **Git:** todo publicado; `feat/postgresql-esquema` y `mvp-v2` en el mismo commit.
- **Siguiente etapa:** desarrollo funcional.

### Respaldo diario activo y limpieza posterior al corte (11/11/2026)

- **Inicio de sesión manual verificado** en los registros: lecturas autenticadas con 200 después del corte.
- **Limpieza:** se quitaron las etiquetas `saopaulo` y `corte` y se borró la vista previa `rt-rma-k1qeeu33d`. Sin cambios de tráfico; `00020-tux` (`auth`) y `dpl_F1M6…` se conservan.
- **Respaldo:** activo, con el Job `rt-rma-respaldo-db`, el Scheduler `rt-rma-respaldo-diario` (03:00 de Argentina) y el bucket `rt-rma-uat-respaldos`, inmutable 30 días.
  - Usa el rol de solo lectura `rma_respaldo`, no el administrador.
  - Primera copia `uat/20261111T193144Z` verificada; ensayo de restauración completo en la nube.
  - Descifrado con la clave real: OK (ver «Consolidación técnica cerrada»).

### Cierre técnico posterior al corte (11/11/2026)

- **Git:** `5ebf474` publicado; `feat/postgresql-esquema` y `mvp-v2` en el mismo commit, por avance rápido. `seguridad` en verde y ningún despliegue de Vercel.
- **Respaldos:** compatibles con São Paulo; costo estimado menor a US$ 0,15 por mes. Falta la autorización para crear los recursos ([`RESPALDOS.md`](RESPALDOS.md)).
- **Limpieza:** no se hizo, porque todavía no hay un inicio de sesión real después del corte.
- **Deuda técnica** consolidada en [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md).

### Corte del UAT a São Paulo (11/11/2026)

- **Publicado:** `d226fd2` en Cloud Run (`00024-top`, 100 %) y en Vercel (`dpl_6vsL…`), sobre Supabase São Paulo. Incluye DC31 corregido y `/docs`, `/redoc` y `/openapi.json` cerrados.
- **Antes:** São Paulo volvió a cero Órdenes, porque `OR-000001` tenía datos personales reales. Ensayo con huella idéntica; copia externa protegida, que se borra el 25/11/2026.
- **Verificado:** 401 sin token en todas las rutas, documentación cerrada, CORS solo para producción, bundle sin Oregón ni claves secretas, `verificar` 9/9 y registros sin errores.
- **Pendiente:** el inicio de sesión manual de las 4 personas usuarias.
- **Detalle:** [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16.

### Integración separada del despliegue (11/11/2026)

- **Vercel:** `rt-rma-uat` está desconectado del repositorio. Antes, cada push creaba un despliegue y un push a `mvp-v2` publicaba en producción. Sin cambios en variables, dominios ni el despliegue activo (`rt-rma-n49rz9qgv…`). Desactivar `createDeployments` no alcanzó ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), al principio).
- **`mvp-v2`:** integrada por avance rápido, sin force push; P0-2 queda pendiente solo para `main`.
- **DC31:** `ac619ed` corrige la devolución previa a cancelar en Órdenes con resultado (P0-4).

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
| IT1-1 | Resuelto (DEC-IT1-01): la excepción de garantía la autorizan Recepción, Coordinación RMA o Administración | Cerrado |
| IT1-2 | Resuelto (DEC-IT1-02): cortesía total o parcial, por los tres roles. Sigue abierto el permiso del DESCUENTO y su tratamiento bajo lo cobrado (ABI-09, ABI-10) | Cerrado |
| IT1-3 | Resuelto (DEC-IT1-03): vigencia y excepción por trabajo | Cerrado |
| IT1-4 | El intento de garantía rechazado no se registra (ABI-35, pendiente en la baseline) | Posterior |
| IT1-5 | VAR-REP-019 (el técnico redefine antes de ejecutar) no se implementó: depende de la evaluación técnica de BR-REP-035, que el producto no tiene | Posterior |
| IT1-6 | Resuelto (12/11/2026): `20261111000100` aplicada en São Paulo, y también `20261112000100` y `20261112000200` de la macroiteración | Cerrado |
| IT1-7 | Resuelto (12/11/2026): `spec/iteracion-1-decisiones` publicada; la copia funcional se verifica contra `708d81b` | Cerrado |
| IT1-8 | DC07C: desistir de todo con una reparación en curso sigue bloqueado (circuito guiado pendiente) | Posterior |

Otros riesgos registrados:
- **Latencia entre regiones:** resuelta con el corte a São Paulo (11/11/2026). La medición previa está en [`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 8.
- **Período de vuelta atrás, hasta el 25/11/2026:** Oregón (`00020-tux`, `rt-rma-n49rz9qgv…`, proyecto y secreto) se conserva. En plan Free se pausa a los 7 días sin actividad: hace falta una consulta semanal de solo lectura. Una vuelta atrás pierde lo creado en São Paulo.
- **Respaldo diario de São Paulo activo** desde el 11/11/2026 ([`RESPALDOS.md`](RESPALDOS.md)). Las herramientas del bucket no se pueden reemplazar durante 30 días: se cambian subiéndolas a otra carpeta.
- **Doble escritura no atómica de la Orden al cerrar una reparación** (JSON): ver [`pendientes-producto.md`](pendientes-producto.md).
- **Foto subida cuya registración falla:** ver [`pendientes-producto.md`](pendientes-producto.md). Es una tarea separada, no de una etapa.

## F. Próximos pasos

**Próximo paso (12/11/2026):** la macroiteración está desplegada en UAT. Falta la validación autenticada con una cuenta real, a cargo de la persona responsable: `probar_entornos.py` y `medir_api.py` (solo lectura, contraseña pedida sin eco) y, con autorización para datos ficticios, una pasada por la evaluación técnica, los adicionales, el desistimiento total con una Ejecución activa, Configuración (un cambio de prueba queda auditado y no se puede borrar), antecedentes y reportes. Para seguir con lo bloqueado hacen falta las decisiones de la sección I del README de consolidación (garantías ABI-03/34/35/37, comercial ABI-09/10, comunicaciones ABI-13/31, compras ABI-12, equipos ABI-05). DC27A (varios roles) no tiene pendientes y puede ser la próxima iteración.

**Paso anterior:** la iteración 1 está desplegada en UAT (12/11/2026). Falta la validación autenticada con una cuenta real: `probar_entornos.py` y `medir_api.py` (solo lectura, contraseña pedida sin eco) y una pasada manual por los recorridos de la iteración 1 con Órdenes ficticias. Después, la iteración 2. Pruebas del cierre (11/11/2026): JSON 1720 pasan y 29 se saltean; `tests/postgres` 389 pasan; frontend: typecheck, 124 tests y build; `npm run validate:all` en verde; los cinco workflows de CI en verde en la rama y en `mvp-v2`. Quedan además los pendientes operativos con fecha y `main`:

1. **Hecho (11/11/2026):** inicio de sesión manual en `rt-rma-uat.vercel.app`, verificado en los registros.
2. **Hecho (11/11/2026):** limpieza (P2-4) y respaldo diario (P0-1).
3. **Hecho (11/11/2026):** descifrado de una copia real con la clave privada.
   - **El 12/11/2026:** confirmar la primera ejecución programada del respaldo (06:00 UTC).
   - **Cada mes:** el ensayo en la nube.
4. **Hasta el 25/11/2026:** una consulta semanal de solo lectura en Oregón, para que el plan Free no lo pause.
5. **El 25/11/2026:**
   - decidir sobre Oregón: pausarlo o eliminarlo, junto con `00020-tux`, `rma-uat-database-url` y `dpl_F1M6…`;
   - borrar las copias externas con datos personales y la copia descargada `nube-uat-20261111T193144Z` ([`RESPALDOS.md`](RESPALDOS.md), sección 5).
6. **Integrar en `main`** (P0-2), con un PR.

**Criterios para empezar el desarrollo funcional** ([`CIERRE_CONSOLIDACION_TECNICA.md`](CIERRE_CONSOLIDACION_TECNICA.md), sección 7), al 11/11/2026:

| Criterio | Estado |
|---|---|
| 1. Rama integrada en `mvp-v2`, CI en verde | Cumplido. Falta `main` (P0-2) |
| 2. Una sola base de UAT | Cumplido: São Paulo. Oregón es solo la vuelta atrás |
| 3. Respaldo diario y restauración ensayada | Cumplido (11/11/2026): respaldo diario activo, restauración ensayada en la nube y descifrado con la clave real |
| 4. Cambios funcionales primero en `business/` | Regla vigente |
| 5. Solo migraciones aditivas, `postgres` en verde | Regla vigente |
| 6. Checklist de seguridad y par de vuelta atrás en cada despliegue | Regla vigente. Integrar ya no despliega |
| 7. Los P1 de cada módulo, dentro del módulo | Regla vigente ([`DEUDA_TECNICA.md`](DEUDA_TECNICA.md)) |

Se puede empezar el desarrollo funcional, en ramas propias que salgan de `mvp-v2`. Antes de cargar datos reales: revisar la retención de los respaldos, el plan de Supabase (P2-7) y el versionado de fotos (P2-11).

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
