# Persistencia de las copias de orígenes externos (catálogo de Ventas y Productos RT)

**Estado: diseño aprobado conceptualmente el 17/11/2026; plan de ejecución para aprobación.** Sin código, sin migraciones y sin despliegues. Resuelve la deuda P1-2 ([`DEUDA_TECNICA.md`](DEUDA_TECNICA.md)) y F-08 ([`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md)). Es la base de la copia de Productos RT ([`reparacion-rt-discovery.md`](reparacion-rt-discovery.md)).

## 1. Problema

**Cómo funciona hoy [verificado en el código]:**

- La copia del catálogo de Ventas (`raw_TipoProducto`) se guarda en `JsonCatalogoEquiposRepository`, un archivo `data/catalogo_equipos/catalogo_equipos.json` dentro del contenedor. Esto pasa **también en modo PostgreSQL** (`application/contexto.py`, función `_contexto_postgres`).
- No hay volumen montado, y el arranque (`main._ciclo_de_vida`) no vuelve a sincronizar.
- Desde el 16/11/2026 el UAT escala a cero ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), sección 9). La copia y su registro de sincronizaciones se pierden unos 15 minutos después de cada período sin uso, y también en cada despliegue.
- La sincronización se protege con un candado en memoria (`threading.Lock`): sirve para un solo proceso, no entre instancias.

**Impacto real hoy (corrige lo informado el 16/11/2026, R1).**

- **Sin impacto en el alta:** desde `a8dd74b` (28/10) el alta y la corrección del equipo usan el **catálogo técnico de modelos**, que viene versionado con el código y no se pierde.
- **Endpoints sin pantalla:** `GET /api/catalogs/equipment` y `POST /api/catalogs/equipment/sync` no los llama ninguna pantalla del frontend actual.
- **Ruta sin uso en la interfaz:** `equipo_desde_catalogo` consulta la copia solo cuando llega un `tipo_producto_id` **distinto** del que ya tiene la Orden, y la interfaz actual no lo envía (`SelectorEquipo` solo conserva el producto de Ventas existente).
- **Checklist a salvo:** los Tipos de Equipo del checklist ya están en PostgreSQL (`rma.tipo_equipo`).

**Por qué igual se corrige ahora:**

- es un defecto de arquitectura: el contrato del repositorio (`repositories/catalogo_equipos.py`) se diseñó para PostgreSQL y el UAT no lo cumple;
- impide más de una instancia;
- cualquier uso nuevo de la copia heredaría la pérdida, y Reparación RT necesita el mismo mecanismo.

## 2. Objetivos

| # | Objetivo | Cómo |
|---|---|---|
| 1 | El catálogo de Ventas en PostgreSQL | `rma.catalogo_producto` con el contrato `CatalogoEquiposRepository` actual (sección 3) |
| 2 | La última copia válida sobrevive a los reinicios | Las filas viven en la base; nada en el disco ni en memoria |
| 3 | Fecha de actualización y errores | `rma.sincronizacion_origen`: cada intento con su resultado, mensaje y contadores |
| 4 | Una sincronización fallida no destruye la copia | Lectura fuera de la transacción; aplicación en **una** transacción; nunca `DELETE` (trigger y permisos) |
| 5 | Reutilizable por Productos RT | Registro de intentos, reserva, motor de sincronización y lector de Sheets genéricos (sección 4) |
| 6 | Mínimo 0 en el UAT | Sin estado en memoria: reserva en la base, sin sincronización al arrancar |
| 7 | Pruebas de reinicio, escalado a cero y fallos | Sección 6 |

## 3. Diseño

### 3.1 Esquema

**Implementado** en `supabase/migrations/20261117000100_copias_origen_externo.sql` (entrega 1, 17/11/2026, commits locales), que es la fuente de verdad del detalle. Resumen:

| Tabla | Contenido |
|---|---|
| `rma.sincronizacion_origen` | Cada intento: `id` (`SINC-` + 12 hexadecimales, `nuevo_id("SINC")`), `copia` (`CATALOGO_VENTAS`; Productos RT agregará `PRODUCTOS_RT`), `usuario_id`, `origen` y `filtro` sin secretos, `iniciada_en`, `vence_en`, `finalizada_en`, `resultado` (`EN_CURSO`, `EXITOSA`, `FALLIDA`, `RECHAZADA`, `INTERRUMPIDA`), `mensaje` y `contadores` (objeto JSON). Índice único parcial `sincronizacion_origen_en_curso (copia) where resultado = 'EN_CURSO'`: **una sola en curso por copia entre todas las instancias** |
| `rma.catalogo_producto` | La copia de `ProductoCatalogo` (`tipo_producto_id` tal cual, descripción, clasificación, características, `seleccionable` y su motivo, `vigente` y su motivo de baja, `valores_origen`, primera y última sincronización), más `sincronizacion_id` (el intento que escribió la fila), `creado_en` y `modificado_en` |

**Reglas que impone la base** (triggers y `check`):

- **Un intento nace `EN_CURSO`** con la hora de la base (`iniciada_en := now()`, aunque el `insert` traiga otra) y con una reserva de **una hora como máximo**.
- **Termina una sola vez**, con la hora de la base (`finalizada_en := now()`). `INTERRUMPIDA` se acepta solo si la reserva venció.
- **Un intento finalizado no cambia más.** No se borra ningún intento ni ninguna fila de la copia.
- **La copia solo se escribe dentro de un intento `EN_CURSO` de `CATALOGO_VENTAS`.** El trigger toma `FOR SHARE` sobre el intento: una toma de la reserva en paralelo espera, y una aplicación tardía de una reserva ya interrumpida se rechaza.
- **No cambian:** el identificador, la primera sincronización y `creado_en` de un producto.
- **`seleccionable` y `vigente`** son coherentes con sus motivos.

**`rma.reservar_sincronizacion(id, copia, usuario, origen, filtro, duración)`:**

- en una sola llamada, da por `INTERRUMPIDA` una reserva vencida de la copia y crea la nueva con `vence_en = now() + duración` (máximo una hora);
- si hay otra vigente, el índice único la rechaza (`unique_violation`, que el motor traduce a 409).

**Permisos de `rma_backend`:**

| Objeto | Puede | No puede |
|---|---|---|
| Las dos tablas | `select` e `insert` | `delete` ni `truncate` |
| El intento | Actualizar `resultado`, `mensaje` y `contadores` | El resto, incluido `finalizada_en`, que fija la base |
| La copia | Actualizar todo lo demás | Identidad, primera sincronización y `creado_en` |
| `reservar_sincronizacion` | Ejecutarla | — |

- `anon`, `authenticated`, `service_role` y `PUBLIC` no tienen acceso, como el resto de `rma`; las funciones trigger no son ejecutables por `PUBLIC`.
- La restauración de respaldos (`restaurar.sh`, en modo `replica`) carga intentos finalizados y la copia sin disparar los triggers.

**Sin clave foránea desde `orden.equipo_tipo_producto_id`, a propósito.**

- Las Órdenes guardan su copia del producto y tienen `tp_id` que la copia nueva todavía no tiene: empieza vacía (sección 3.5).
- Una FK impediría crear o leer esas Órdenes.
- La referencia sigue siendo de texto, como hoy.

### 3.2 Flujo de una sincronización

Es el motor común (sección 4).

```
1. RESERVAR (transaccion corta, se confirma): rma.reservar_sincronizacion(…, duracion = 10 min)
   ├─ una reserva vencida de la copia (instancia apagada o caida a mitad) se marca INTERRUMPIDA en la misma llamada
   └─ otra reserva vigente → unique_violation → SincronizacionEnCursoError (HTTP 409)
2. LEER el origen FUERA de toda transaccion (Sheets, segundos)
   ├─ no responde → FINALIZAR FALLIDA (mensaje)            → la copia no cambia
   └─ datos no confiables (columnas, tp_id repetidos, vacio) → FINALIZAR RECHAZADA → la copia no cambia
3. APLICAR (UNA transaccion)
   leer la copia actual (dentro de la transaccion) → fusionar_catalogo (sin cambios) →
   upsert de cada producto (insert ... on conflict do update; nunca delete) →
   update del intento a EXITOSA con contadores → commit
   └─ cualquier error → rollback (la copia queda como estaba) →
      FINALIZAR FALLIDA en otra transaccion ("No se pudo aplicar: …")
4. Si la instancia muere en 2 o 3: el intento queda EN_CURSO hasta vence_en; el siguiente lo marca INTERRUMPIDA.
   La copia nunca queda a medias (el paso 3 es atomico).
```

- **Reserva.** El índice único parcial reemplaza al `threading.Lock`: vale entre instancias y sobrevive a un apagado.
- **Vencimiento.** 10 minutos por defecto, configurable hasta una hora (límite de la base). Supera holgadamente el tiempo de lectura de Sheets (`catalogo_timeout_s` = 30 s) y el de aplicación. Lo calcula la base, nunca el reloj de la instancia.
- **Solo quien reservó finaliza (QA C1, M3).** La base acepta que una sesión cierre como FALLIDA, EXITOSA o RECHAZADA un intento vigente ajeno; no se corrompe la copia (el `FOR SHARE` ordena las operaciones y una aplicación posterior se rechaza), pero sería un error del motor. El motor (C3) finaliza solo el `id` que reservó, y sus pruebas lo cubren.
- **Lógica que no cambia:** `fusionar_catalogo`, `validar_informados`, los modelos (`ProductoCatalogo`, `SincronizacionCatalogo`) y los adaptadores de origen.

### 3.3 Repositorio

`storage/postgres/catalogo_equipos.py`, clase `PostgresCatalogoEquiposRepository`, cumple `CatalogoEquiposRepository`:

| Método actual | Implementación en PostgreSQL |
|---|---|
| `listar_productos()` | `select … from rma.catalogo_producto` (unos 1.500 registros) |
| `obtener_producto(tp_id)` | Por clave primaria |
| `listar_sincronizaciones()` | Las de `copia = 'CATALOGO_VENTAS'`, por `iniciada_en`; las últimas N para el estado |
| `registrar_sincronizacion(s)` | Finaliza el intento reservado como FALLIDA o RECHAZADA |
| `aplicar_sincronizacion(s, productos)` | El paso 3, en una transacción |

**Métodos nuevos del contrato,** que también implementa el repositorio JSON para el modo local:

- `reservar_sincronizacion(id, usuario, duracion) -> None`: en PostgreSQL llama a `rma.reservar_sincronizacion` (la hora la pone la base) y traduce `unique_violation` a `SincronizacionEnCursoError`; en JSON, con el candado en memoria actual.
- `ultima_exitosa()` y `ultima()`, para el estado sin leer todo el registro.

**Contexto.** `_contexto_postgres` usa `PostgresCatalogoEquiposRepository`. El modo JSON (desarrollo local) conserva `JsonCatalogoEquiposRepository`.

### 3.4 Arranque, escalado a cero y varias instancias

- **Al arrancar no se sincroniza.** Sería una lectura de Sheets en cada arranque en frío (unos segundos de latencia y cuota) y no hace falta: la copia está en la base.
- **Sin estado en memoria.** Solo un caché opcional de `listar_productos` invalidado por el `id` de la última exitosa. No se implementa hasta medir que hace falta.
- **Varias instancias:** la reserva en la base las coordina. Lo único que sigue impidiendo más de una instancia es el limitador de consultas por DNI en memoria (P1-2), fuera de este alcance.

### 3.5 Puesta en marcha

- **Sin migración de datos.** La copia JSON del UAT es efímera, probablemente vacía, y producción no existe.
- **Después de desplegar,** Administración o Coordinación RMA ejecuta **una** sincronización (`POST /api/catalogs/equipment/sync`). Se agrega como paso del procedimiento ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md)).
- **Mientras la copia está vacía,** el comportamiento es el de hoy sin copia: el alta usa el catálogo técnico y no se ve afectada.
- **Vuelta atrás:** la revisión anterior ignora las tablas nuevas (migración aditiva) y vuelve a la copia JSON efímera, sin daño.

### 3.6 Lo que no cambia

- La API y su contrato (`GET /api/catalogs/equipment`, `POST …/sync`, roles `ROLES_SINCRONIZACION_CATALOGO`).
- El frontend.
- Los adaptadores (`integraciones/catalogo/*`).
- BR-REP-048, que ya exige esta política: copia que nunca borra, conserva la última válida y audita. Es un cambio técnico, sin cambio funcional.

## 4. Arquitectura reutilizable (Productos RT)

```
application/sincronizacion_origen.py   ejecutar_sincronizacion(contexto, definicion, usuario_id)
                                        reservar → leer fuera de la transaccion → validar →
                                        aplicar en una transaccion → finalizar; maneja FALLIDA,
                                        RECHAZADA, INTERRUMPIDA y 409
domain/models/sincronizacion.py         ResultadoSincronizacion (+ EN_CURSO, INTERRUMPIDA),
                                        IntentoSincronizacion (copia, contadores genericos)
repositories/sincronizacion_origen.py   protocolo: reservar, finalizar, aplicar(filas, intento),
                                        ultima, ultima_exitosa
integraciones/sheets.py                 LectorSheets: values.get, values:batchGet por columnas,
                                        resolver GID → nombre de hoja, errores HTTP; credenciales de
                                        integraciones/catalogo/credenciales.py
```

| Copia | `copia` | Definición (lee, valida, fusiona) | Tabla |
|---|---|---|---|
| Catálogo de Ventas | `CATALOGO_VENTAS` | `ProveedorCatalogo`, `validar_informados` y `fusionar_catalogo` (existentes) | `rma.catalogo_producto` |
| Productos RT (etapa 1 de Reparación RT) | `PRODUCTOS_RT` | `ProveedorProductosRt` y el contrato de columnas de [`reparacion-rt-discovery.md`](reparacion-rt-discovery.md), sección 2 | `rma.producto_rt` |

- **Lo que agrega Productos RT:** su tabla, su definición y `'PRODUCTOS_RT'` en el `check` de `copia`.
- **Lo que reutiliza:** registro, reserva, motor, lector de Sheets, estado («última actualización») y las pruebas de la sección 6, con el mismo esqueleto.

## 5. Plan de ejecución del bloque C

**Rama:** `feat/persistencia-catalogos` desde `mvp-v2`. Una entrega es uno o más commits que se cierran juntos; el push y la integración en `mvp-v2` se hacen con autorización.

**Pruebas durante el desarrollo:** focalizadas (las nuevas, las afectadas, `ruff` sobre lo tocado). La suite completa (`pytest` y `tests/postgres`) se corre al cierre del bloque (entrega 5) o ante un cambio transversal.

**Fallas:** se clasifican BLOQUEANTE, MAYOR o MENOR. Una MENOR se registra y no detiene la entrega.

**Cada entrega tiene seis partes:**

1. **Implementación.**
2. **Pruebas automatizadas.**
3. **QA independiente:** una revisión sin el contexto de quien implementó, hecha por un agente revisor nuevo o por una persona. Usa `/code-review` sobre el diff de la entrega, vuelve a correr sus pruebas y recorre la lista de la entrega. Sus hallazgos BLOQUEANTE y MAYOR se resuelven antes de cerrarla.
4. **Compatibilidad.**
5. **Seguridad.**
6. **Aceptación.**

### Entrega 1: esquema (C1)

| | |
|---|---|
| Implementación | `supabase/migrations/<fecha>_copias_origen_externo.sql`: `rma.sincronizacion_origen` (con el índice único parcial de la reserva) y `rma.catalogo_producto`, comentarios, triggers sin borrado e inmutabilidad del intento finalizado, y permisos. `docs/postgresql/diseno-logico.md` y `diseno-fisico.md` |
| Pruebas automatizadas | Las migraciones desde cero en PostgreSQL 17 local (las mismas que el workflow `postgres`). `tests/postgres/test_copias_origen_esquema.py`: tablas, `check` y el índice único parcial (dos EN_CURSO de la misma copia: rechazado); `delete` rechazado como dueño (trigger) y como `rma_backend` (permiso); un intento finalizado no cambia; la transición EN_CURSO → final permitida una vez |
| QA independiente | Revisión del SQL: nombres, comentarios, permisos mínimos, no toca tablas existentes, idempotencia (`if not exists`) como las demás migraciones |
| Compatibilidad | Aditiva, sin tocar tablas existentes. El backend publicado (`677dbb1`, exportado con `git archive`) arranca sobre la base con la migración nueva y pasa un humo (`/health`, listado y detalle de Órdenes, como el ensayo de `ensayar_despliegue_ux.py`). `supabase/tests` (pruebas SQL) en verde |
| Seguridad | `anon` y `authenticated` sin acceso; `rma_backend` sin `delete`; sin datos en la migración; ningún secreto; búsqueda de secretos (`scripts/ci/buscar_secretos.sh`) limpia |
| Aceptación | Todo lo anterior en verde; 38 migraciones locales |

### Entrega 2: contrato, lector de Sheets y motor común, sin cambio de comportamiento (C2, C5 y C3)

| | |
|---|---|
| Implementación | **C2:** `EN_CURSO` e `INTERRUMPIDA` en `ResultadoSincronizacion`; `reservar_sincronizacion`, `ultima` y `ultima_exitosa` en `CatalogoEquiposRepository` y en `JsonCatalogoEquiposRepository` (con el candado en memoria actual). **C5:** `integraciones/sheets.py` (`LectorSheets`: `values.get`, `values:batchGet` por columnas, resolver GID → nombre, mensajes HTTP), con `integraciones/catalogo/sheets.py` usándolo. **C3:** `application/sincronizacion_origen.py` (`ejecutar_sincronizacion`) y `sincronizar_catalogo_equipos` sobre él |
| Pruebas automatizadas | Sin cambio de expectativas: `tests/test_catalogo_equipos.py`, `tests/test_api_catalogo_equipos.py` y las del adaptador de Sheets. Nuevas: el motor con repositorio y origen simulados (sección 6.1); `LectorSheets` con HTTP simulado (`batchGet` pide solo las columnas indicadas; GID inexistente; 401, 403, 404, 400, 429 y tiempo agotado) |
| QA independiente | Comprobar que es un refactor: mismas respuestas de la API (comparar `GET /api/catalogs/equipment` y `POST …/sync` antes y después con el origen `archivo`), mismos mensajes y mismos registros |
| Compatibilidad | Modo JSON idéntico; contrato de la API sin cambios (`openapi.json` local igual para `/api/catalogs/equipment*`); el frontend no se toca |
| Seguridad | Los tokens siguen sin registrarse ni aparecer en mensajes de error (prueba existente más una nueva para `batchGet`); alcance `spreadsheets.readonly` sin cambios; ninguna credencial nueva |
| Aceptación | Pruebas focalizadas y `ruff` en verde; QA sin hallazgos BLOQUEANTE ni MAYOR |

### Entrega 3: persistencia en PostgreSQL (C4)

| | |
|---|---|
| Implementación | `storage/postgres/catalogo_equipos.py` (`PostgresCatalogoEquiposRepository`): reserva, aplicación en una transacción con upsert por lotes, finalización y estado. `application/contexto.py`: `_contexto_postgres` la usa; JSON sin cambios |
| Pruebas automatizadas | `tests/postgres/test_catalogo_persistente_postgres.py`, con todos los casos de la sección 6.2: reinicio (otro pool y **otro proceso**), sin disco, fallo de lectura, rechazo, fallo a mitad de la aplicación (huella idéntica), instancia caída (INTERRUMPIDA), dos instancias a la vez (una 409), idempotencia, bajas, sin borrado, inmutabilidad y API después de reiniciar. Más las pruebas de la entrega 2 corriendo sobre PostgreSQL |
| QA independiente | Revisión de la transaccionalidad: lectura fuera de la transacción, una sola transacción para aplicar, rollback y finalización FALLIDA en otra transacción, sin `delete`; reproducir a mano el fallo a mitad y la caída |
| Compatibilidad | Con la base vacía de catálogo, el alta y la corrección del equipo funcionan igual (catálogo técnico); `test_api_catalogo_equipos.py` también en modo PostgreSQL; rol mínimo `rma_backend` (como `test_permisos_rma_backend.py`) |
| Seguridad | Consultas parametrizadas (sin SQL armado con texto del origen); `mensaje` sin datos del origen ni credenciales; los permisos `ROLES_SINCRONIZACION_CATALOGO` siguen exigidos en la API (401 y 403 probados) |
| Aceptación | Todos los casos de la sección 6.2 en verde; QA sin hallazgos BLOQUEANTE ni MAYOR |

### Entrega 4: ensayo local de reinicio y fallos (C6)

| | |
|---|---|
| Implementación | `supabase/scripts/validacion_uat/ensayar_persistencia_catalogo.py`: los 6 pasos de la sección 6.3, más la vuelta atrás (backend `677dbb1` sobre la base con la migración: arranca y usa su copia JSON sin errores) |
| Pruebas automatizadas | El propio ensayo, con su informe (`--informe`), como `ensayar_despliegue_ux.py` |
| QA independiente | Correr el ensayo desde cero en otra sesión; revisar que mata el proceso de verdad y que el directorio de datos queda vacío entre arranques |
| Compatibilidad | La vuelta atrás ensayada |
| Seguridad | Solo PostgreSQL local descartable, nunca Supabase; datos ficticios |
| Aceptación | Ensayo «RESULTADO: OK» |

### Entrega 5: cierre del bloque, documentación e integración (C7)

| | |
|---|---|
| Implementación | Documentación: [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md) P1-2 (la copia, resuelta; el limitador por DNI sigue); [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md) F-08; `traceability/IMPLEMENTATION.md`; `app/backend/README.md`; [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md) (la sincronización después de desplegar, la prueba de escalado a cero y la migración nueva); [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md). En `business/` no hay cambio funcional: BR-REP-048 ya exige esta política |
| Pruebas automatizadas | **Suite completa:** `pytest` (JSON), `tests/postgres`, `ruff check .`, frontend sin cambios (`typecheck`, pruebas y `build` igual); `npm run validate:all` |
| QA independiente | Revisión del bloque completo (`/code-review` sobre `mvp-v2...feat/persistencia-catalogos`) y la lista de seguridad de [`CHECKLIST_SEGURIDAD_DESPLIEGUE.md`](CHECKLIST_SEGURIDAD_DESPLIEGUE.md) |
| Compatibilidad | Integración por avance rápido en `mvp-v2` (con autorización) y CI en verde: `seguridad`, `backend` y `postgres` |
| Seguridad | Búsqueda de secretos limpia; diff sin credenciales; lista de seguridad completa |
| Aceptación | Criterios de la sección 8 (puerta A) |

### Entrega 6: UAT, solo con autorización (C8)

| | |
|---|---|
| Implementación | Procedimiento de [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md): respaldo previo; `db push --dry-run`, que tiene que listar solo la migración nueva, y después aplicarla; revisión nueva **sin tráfico y con etiqueta temporal**; pruebas por la etiqueta; tráfico; quitar la etiqueta; `verificar_escalado_uat.py`; una sincronización con la cuenta de Administración (contraseña ingresada por el usuario); respaldo posterior |
| Pruebas automatizadas | La prueba de escalado a cero de la sección 6.4 (sincronizar, esperar a 0 instancias medido en Cloud Monitoring, leer y comparar) y los E2E de la iteración vigente con limpieza selectiva |
| QA independiente | Revisión de las evidencias: intento EXITOSA, la misma `ultima_exitosa` después del arranque en frío, métricas en 0 |
| Compatibilidad | Vuelta atrás disponible: la revisión anterior por nombre (`00036-jis`); la migración es aditiva |
| Seguridad | Sin credenciales en los registros; mínimo 0 y sin etiquetas al terminar; `CHECKLIST_SEGURIDAD_DESPLIEGUE.md` |
| Aceptación | Criterios de la sección 8 (puerta B) |

**Orden y dependencias:**

- Entrega 1 → 2 → 3 → 4 → 5, más la 6 con autorización.
- La 2 no depende de la 1 y puede adelantarse.
- La 3 necesita la 1 y la 2.

## 6. Pruebas

### 6.1 Unitarias (sin base)

Con un repositorio y un origen simulados:

- **Resultados del motor:** EXITOSA con contadores; FALLIDA con origen caído; RECHAZADA con columnas faltantes, `tp_id` repetidos o lectura vacía.
- **En FALLIDA y RECHAZADA:** no se llama a `aplicar`.
- **Concurrencia:** la reserva tomada responde 409.
- **Reserva vencida:** se marca INTERRUMPIDA y la sincronización sigue.

### 6.2 PostgreSQL (`tests/postgres/test_catalogo_persistente_postgres.py`)

| Prueba | Cómo | Esperado |
|---|---|---|
| Reinicio | Contexto A: sincronizar con un origen `archivo`. Cerrar su pool. Contexto B nuevo (otro pool, como otra instancia) | B lee los mismos productos, la misma última exitosa y el mismo registro |
| Reinicio en otro proceso | Igual, con B en un **subproceso** de Python, como un arranque en frío real | Igual |
| Sin disco | Contexto con `RMA_DATA_DIR` en un directorio temporal que se borra entre A y B | B igual: nada depende del disco |
| Fallo de lectura | Copia válida y después el origen lanza `CatalogoOrigenNoDisponibleError` | Huella (md5) de `catalogo_producto` idéntica; intento FALLIDA con mensaje |
| Datos rechazados | Origen con columna faltante, `tp_id` repetidos o vacío | Huella idéntica; RECHAZADA |
| Fallo a mitad de la aplicación | Error inyectado después de N upserts (repositorio envuelto o trigger de prueba) | Rollback: huella idéntica; el intento termina FALLIDA |
| Instancia caída a mitad | Intento EN_CURSO con `vence_en` en el pasado | El siguiente lo marca INTERRUMPIDA y sincroniza |
| Dos instancias a la vez | Dos contextos sincronizan en paralelo (hilos) | Uno EXITOSA; el otro 409 (`SincronizacionEnCursoError`); la copia consistente |
| Idempotencia | Repetir la misma sincronización | `sin_cambios` igual al total; sin filas nuevas |
| Bajas | El origen deja de informar un producto o lo marca eliminado | `vigente = false` con su motivo; la fila sigue |
| Sin borrado | `delete` como `rma_backend` y como dueño | Permiso denegado / trigger |
| Inmutabilidad del registro | `update` de un intento finalizado | Rechazado |
| API después de reiniciar | `TestClient` sobre una app nueva con la misma base | `GET /api/catalogs/equipment` igual |

### 6.3 Ensayo local de reinicio

`ensayar_persistencia_catalogo.py`, como `ensayar_despliegue_ux.py`:

1. PostgreSQL local descartable con las migraciones.
2. Backend en uvicorn con el origen `archivo`; sincronizar por la API.
3. **Matar el proceso** y volver a arrancarlo con otro directorio de datos vacío. El GET devuelve la misma copia y la misma fecha.
4. Apuntar el origen a un archivo roto y sincronizar: respuesta de error, copia igual, intento RECHAZADA visible.
5. Origen inaccesible: FALLIDA, copia igual.
6. Matar el proceso **durante** una sincronización lenta (origen simulado con demora): al volver, la copia está igual y el intento siguiente marca INTERRUMPIDA.

### 6.4 UAT, después de un despliegue autorizado

Con mínimo 0:

1. `POST /api/catalogs/equipment/sync` con la cuenta de Administración: EXITOSA, N vigentes.
2. Esperar a que `run.googleapis.com/container/instance_count` llegue a 0 (unos 15 minutos sin solicitudes; [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), sección 9).
3. `GET /api/catalogs/equipment`, que provoca el arranque en frío: la misma `ultima_exitosa` y los mismos N vigentes.
4. Revisión nueva sin cambios de código (o la del despliegue siguiente): la copia sigue.
5. `verificar_escalado_uat.py` OK.

Las cuentas y contraseñas las ingresa el usuario. El script recibe el token por el mismo mecanismo que `probar_macro_v14.py`.

### 6.5 CI

- `postgres`: las migraciones desde cero y las pruebas de 6.2.
- `backend`: las de 6.1 y las actuales.

## 7. Riesgos del diseño

| Riesgo | Mitigación |
|---|---|
| Un intento queda EN_CURSO para siempre si la instancia muere | `vence_en` más INTERRUMPIDA |
| Una transacción larga al aplicar unas 1.500 filas | Upsert por lotes (`executemany`) dentro de la misma transacción; se mide en el ensayo |
| El UAT queda sin copia hasta la primera sincronización después de desplegar | El alta no depende de ella (sección 1); paso explícito del procedimiento |
| Cambio del contrato del repositorio | Métodos agregados, no cambiados; el repositorio JSON los implementa |
| Vuelta atrás a una revisión anterior | Migración aditiva; la anterior usa su JSON |

## 8. Criterios de bloque C terminado

**Puerta A: habilita a programar la etapa 1 de Reparación RT.**

1. Las entregas 1 a 5 están integradas en `mvp-v2`, con el CI en verde (`seguridad`, `backend` y `postgres`).
2. La suite completa está en verde: `pytest` (JSON), `tests/postgres` y `ruff`. El frontend no cambió.
3. Pasan todas las pruebas de la sección 6.2, en especial:
   - reinicio en otro proceso;
   - fallo a mitad con la huella idéntica;
   - dos instancias a la vez;
   - instancia caída.
4. El ensayo local de la sección 6.3, con la vuelta atrás, da «RESULTADO: OK».
5. Compatibilidad verificada en cuatro frentes:
   - la API sin cambios;
   - el modo JSON idéntico;
   - el backend publicado funcionando sobre la migración nueva;
   - el alta funcionando con la copia vacía.
6. QA independiente y revisión de seguridad sin hallazgos BLOQUEANTE ni MAYOR abiertos; los MENOR, registrados.
7. Documentación actualizada (entrega 5).
8. Además de este bloque, la etapa 1 necesita, aparte:
   - la especificación DEC-RT incorporada en `rt-rma-app` y sincronizada en `business/`;
   - la planilla de prueba ficticia;
   - los formatos de las columnas «Copiar» verificados con información ficticia representativa ([`reparacion-rt-discovery.md`](reparacion-rt-discovery.md), sección 9).

**Puerta B: habilita a publicar la etapa 1 en el UAT.**

- La puerta A.
- La entrega 6 hecha con autorización:
  - la migración aplicada;
  - la copia del catálogo sobrevive al escalado a cero (medido);
  - `verificar_escalado_uat.py` OK;
  - respaldos previo y posterior correctos.

## 9. Dependencias y riesgos del bloque C

**Dependencias:**

| Dependencia | Para | Estado |
|---|---|---|
| PostgreSQL 17 local descartable (`127.0.0.1:55432`) y `app/backend/.venv` | Entregas 1 a 5 | Disponibles (usados en los ensayos anteriores) |
| Autorización de push e integración en `mvp-v2` | Entrega 5 | Pendiente |
| Autorización de migración remota y despliegue; sesión de `gcloud` y de Supabase; contraseña de Administración ingresada por el usuario | Entrega 6 | Pendiente |
| Nada de Gestión RT | — | El bloque C usa el origen `archivo` en las pruebas y la hoja `raw_TipoProducto` que ya lee el UAT |

**Riesgos:**

| Riesgo | Prob. | Impacto | Mitigación |
|---|---|---|---|
| El refactor (entrega 2) cambia el comportamiento sin querer | Media | Medio | Entrega separada; pruebas existentes sin cambio de expectativas; comparación antes y después de la API |
| Pruebas de concurrencia inestables | Media | Bajo | Reserva por índice único (determinista); hilos con barrera; sin esperas por tiempo |
| Reserva que no vence si el reloj difiere entre instancias | Baja | Medio | `vence_en` con `now()` de la base, nunca la hora de la instancia |
| Transacción larga con unas 1.500 filas | Baja | Bajo | Upsert por lotes; se mide en el ensayo |
| La fecha del nombre de la migración choca con otra rama | Baja | Bajo | Se fija al crear la entrega 1, después de la última de `mvp-v2` |
| El UAT queda sin copia hasta la primera sincronización | Alta | Bajo | El alta no depende de la copia; paso explícito del procedimiento |
| Vuelta atrás a `00036-jis` después de migrar | Baja | Bajo | Migración aditiva; ensayada en la entrega 4 |
| Cambio del contrato del repositorio | Baja | Bajo | Solo se agregan métodos; el JSON los implementa |
| Una sincronización entre la línea de base de un E2E y su limpieza hace abortar `06_limpiar_e2e.sql` (las tablas son maestras; QA C1) | Baja | Bajo | Aborta sin cambiar nada; no sincronizar durante los E2E. Se agrega a [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md) en la entrega 5 |
| Una sesión cierra un intento vigente ajeno (QA C1, M3) | Baja | Bajo | La copia no se corrompe; el motor finaliza solo su propio intento (C3) |
