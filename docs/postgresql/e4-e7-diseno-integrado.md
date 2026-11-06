# E4 a E7. Discovery técnico y diseño integrado

**Estado:** diseño aprobado para el Bloque A. Están implementados y aprobados A0, A1, A2 y A4, con QA-A2-H1 y L-3 (secciones 13 y 14). El Bloque A está cerrado: A3 y A5 a A8 implementados, sin commit (secciones 15 a 19). Del Bloque B, B1 a B6 están implementados, sin commit (secciones 20 a 22). Para retomar: [`CHECKPOINT_A4_HANDOFF.md`](CHECKPOINT_A4_HANDOFF.md).

**Base:** rama `feat/postgresql-esquema`, commit `99734f2` (E3).

**Evidencia:**
- lectura del código (dominio, services, capa de aplicación, repositories JSON y PostgreSQL, API y frontend);
- lectura de las migraciones de `supabase/migrations` y de los diseños [lógico](diseno-logico.md) y [físico](diseno-fisico.md);
- los documentos de [E2](e2-consultas-dedicadas.md) y [E3](e3-catalogos-diseno.md) y los [pendientes](integracion-pendientes.md).

No se ejecutó nada contra una base. Las referencias de código son de esta revisión.

**Organización aprobada:** dos bloques. **A = E4 + E5**: el agregado Orden y el inventario transaccional. **B = E6 + E7**: acciones, idempotencia, equivalencia y activación local. Cada bloque se implementa en slices verificables, con una QA independiente al final del bloque.

## 1. Resumen ejecutivo

**Lo que el discovery cambia respecto del plan:**

1. **E4 necesita parte de E6.** `rma.evento_negocio.accion_id` y `rma.movimiento_inventario.accion_id` son `NOT NULL`, con FK a una `accion_usuario` CONFIRMADA. No se puede guardar ni un paso del historial ni un movimiento sin registrar antes la acción del comando. El Bloque A registra la acción (sin clave de idempotencia); el Bloque B le agrega la clave, la respuesta guardada y la deduplicación.
2. **Guardar por agregado no puede borrar y reinsertar.** `rma_backend` no tiene `DELETE` en ninguna tabla del agregado, y las historias son inmutables por trigger. `guardar()` tiene que comparar la Orden que llega con la que se cargó y emitir solo `UPDATE` de lo mutable e `INSERT` de lo nuevo. Varias historias del dominio no tienen id: lo nuevo se reconoce por posición.
3. **La detección de conflictos de JSON no alcanza en PostgreSQL.** JSON compara el prefijo del historial, pero hay comandos que cambian la Orden sin agregar historial: descuentos, check-in, ajuste de garantía y fotos. En JSON los protege el lock del proceso; en PostgreSQL hace falta un bloqueo de fila y una versión.
4. **El inventario no se puede atomizar sin tocar cómo los services leen la disponibilidad.** En PostgreSQL el stock lo mueve un trigger al insertar cada movimiento, y dos reservas concurrentes pasarían la verificación de Python. La segunda recibiría un 409 técnico en lugar de «Reserva fallida» (PROC-REP-186). Hace falta el contrato `stock_disponible(insumo_ids, bloquear)`, diferido desde E2 (DE-1), con bloqueo ordenado de insumos.
5. **Hay diferencias funcionales que ya están decididas pero no implementadas.** H-1 (un ajuste negativo no puede dejar el disponible negativo) es un cambio aprobado que se aplica en los dos modos. Además, el esquema exige un motivo de ajuste del catálogo (`motivo_ajuste_id`) y la API envía texto libre: eso requiere una decisión de producto (DI-8).
6. **E7 no tiene todavía su infraestructura.** Unas 30 pruebas de la API leen o editan los archivos JSON directamente, no hay aislamiento por prueba en la base local y la prueba diferencial de E2 no quedó versionada. Hay que construir esa base antes de comparar los modos.

**Recomendación:** **GO condicionado** para el Bloque A, una vez aprobadas las decisiones bloqueantes de la sección 3.

## 2. Arquitectura propuesta

```
api ─► application ─► services (sin cambios de reglas)
            │
            ├─ contexto.transaccion()   ← UnidadDeTrabajo (JSON: RLock; PG: BEGIN … COMMIT)
            │      └─ acción del comando (Bloque A: técnica; Bloque B: con clave)
            ▼
       repositories (Protocol)
            ├─ OrdenReparacionRepository     JSON ✓ | PG: mapeador del agregado (A1–A5)
            ├─ CatalogosRepository            JSON ✓ | PG: lecturas ✓, stock (A6–A7)
            ├─ stock_disponible (DE-1)        JSON: derivado | PG: insumo FOR UPDATE (A6)
            └─ ModelosEquipo / CatalogoEquipos (Ventas, sigue en JSON)
```

**Principios:**
- **Una transacción por comando.** Cargar, validar, aplicar los services, guardar y registrar la acción ocurren dentro de `contexto.transaccion()`. En PostgreSQL es todo o nada.
- **Las reglas no se mueven.** La base respalda las invariantes técnicas con CHECKs, triggers y bloqueos. Las reglas de negocio siguen en los services. Los services no cambian, salvo para usar `stock_disponible` (DE-1, ya previsto en el plan).
- **Los repositories PostgreSQL** usan el ejecutor restringido de E3 (`lectura()` y `ejecutor()`) y consultas registradas `LECTURA` o `ESCRITURA`.
- **Orden de bloqueo único (A2-3):** para modificar una Orden, Orden (`FOR NO KEY UPDATE`), Cliente, Documento, Equipo e insumos por `clave` ascendente. Ningún comando toma bloqueos en otro orden. Las altas y los modos de bloqueo están en la [sección 13.7](#137-regla-de-bloqueos-a2-3-aprobada).
- **Nada externo dentro de la transacción.** Las fotos se suben antes y se registran adentro; la fuente por DNI y el catálogo de Ventas quedan afuera. Ya es así hoy.
- **JSON sigue siendo el modo por defecto,** con su comportamiento actual. Cada contrato nuevo tiene implementación JSON y prueba compartida.

## 3. Decisiones que requieren aprobación

Las marcadas **(B)** bloquean el inicio del Bloque A o del slice indicado.

### 3.1 Agregado y persistencia (E4)

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| **DA-1 (B)** | Estrategia de `guardar()` | (a) Comparar con la instantánea cargada en la transacción: `UPDATE` de filas mutables e `INSERT` de las entradas nuevas de historias, exigiendo que lo guardado sea prefijo. (b) Guardar el agregado como `jsonb` y derivar las tablas. (c) Borrar y reinsertar: imposible, porque no hay `DELETE` | **(a)**. Respeta el esquema aprobado, la inmutabilidad y los permisos. Si una entrada inmutable ya guardada cambia, es un error de programación (`PersistenciaError`), no un conflicto |
| **DA-2 (B)** | Concurrencia sobre la Orden | (a) Pesimista: `obtener_para_modificar` toma `FOR NO KEY UPDATE`. (b) Optimista: `orden.version` en `UPDATE … WHERE version = %s`. (c) Las dos | **(c)**. El bloqueo serializa los comandos sobre la misma Orden. La versión, mantenida por el repository, detecta un `guardar` de una Orden leída sin bloqueo y da `ConflictoDeEscrituraError` (409). La versión no entra al dominio: se guarda en la instantánea de la transacción |
| **DA-3 (B)** | Acción del comando (`accion_usuario`, exigida por eventos y movimientos) | (a) La capa de aplicación declara la operación y el usuario al abrir la transacción. (b) El repository la crea cuando hace falta: el usuario sale de la primera entrada nueva del historial o del movimiento, y si no hay usuario, `proceso` del sistema | **(b) en el Bloque A** (sin tocar unos 40 puntos de entrada), **(a) en el Bloque B**, junto con la clave de idempotencia. La acción técnica es CONFIRMADA y sin clave. Riesgo: un comando que escribe filas de usuario sin historial (descuento, check-in) no tiene de dónde sacar el usuario; se toma de la entidad escrita (`registrado_por`) |
| **DA-4** | Lectura del agregado fuera de un comando (F-09) | (a) `lectura()` en `READ COMMITTED`. (b) `lectura()` de solo lectura en `REPEATABLE READ` para cargar el agregado y para las respuestas de varias consultas | **(b)**. Las 15 a 20 consultas de un agregado ven el mismo instante. Dentro de un comando basta `READ COMMITTED` más el bloqueo de la Orden. Se agrega el aislamiento como opción de `lectura()` |
| **DA-5 (B para A1)** | Huecos de mapeo entre dominio y esquema (sección 4.3) | (a) Migraciones locales aditivas que hagan el viaje de ida y vuelta exacto. (b) Aceptar pérdidas documentadas | **(a)**. Criterio de aceptación de E4: `obtener(guardar(o)) == o` para toda Orden del corpus. Las migraciones son aditivas (columnas nulas o con default), como en E3 |
| **DA-6** | `cerrada_en` (F-06) | (a) El repository lo fija cuando `esta_cerrada` pasa a verdadero, en el último `UPDATE` de la transacción. (b) Lo fija un trigger según el estado | **(a)**. Además, un CHECK nuevo en la migración local: estado ENTREGADA o posición EVT-REP-999 implica `cerrada_en` no nulo. Las Órdenes cerradas sin fecha se corrigen al migrar los datos (E8) |
| **DA-7** | Numeración (QA-E2-5, QAF-14) | — | Migración local que reemplaza el default por un formato que no trunca (`lpad` hasta 6 dígitos, sin cortar los números más largos). `reservar_codigo` usa el valor devuelto por la misma sentencia; el registro rechaza `currval` y `lastval`. Los huecos ya están admitidos por el contrato. `setval` sobre el máximo migrado, en E8 |
| **DA-8** | Identidad del cliente y DNI (F-05) | (a) `listar_por_dni_cliente` busca por la copia del documento en la Orden (`orden.cliente_documento_numero` normalizado). (b) Busca por el documento vigente del cliente compartido | **(a)**: es la semántica de JSON. El cliente compartido (`rma.cliente`, por `codigo` CLI-…) se mantiene para la identidad; la búsqueda por el documento vigente es una evolución aparte |
| **DA-9** | Vinculación y cableado (QA-E2-4, QA-E3-4) | — | Los repositories reciben la unidad de trabajo en el constructor, en los dos modos; se elimina la mutación de `__post_init__`. Hay un pool y una sola `UnidadDeTrabajoPostgres` por aplicación, compartida por todos los repositories, y una prueba que lo garantiza (cierra QA-E3-4 por invariante). Pool en un `lifespan`, en el Bloque B |
| **DA-10 (B para A3)** | Medios de pago (E4-MP) | (a) Migración de datos idempotente con los medios predeterminados del dominio, más una verificación al arrancar en modo PostgreSQL. (b) Exigir la carga de referencia operativa como precondición. (c) Insertar un medio faltante en el comando | **(a)**. Toda base con el esquema tiene los medios que el dominio puede usar. Un código desconocido es un error explícito. La rama de predeterminados de DE3-7 deja de alcanzarse en PostgreSQL |

### 3.2 Inventario (E5)

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| **DI-1 (B para A6)** | Fuente de verdad del stock en PostgreSQL | (a) El libro: el trigger aplica cada movimiento y `actualizar_stock_insumo` no escribe; registra el saldo esperado y `guardar` lo verifica después de insertar los movimientos. (b) Refactorizar los services a un puerto de inventario | **(a)**. Respeta «los services no cambian», y una diferencia entre el cálculo de Python y el trigger se vuelve un error explícito en lugar de pasar en silencio. La opción (b) queda para una limpieza posterior |
| **DI-2 (B para A6)** | Disponibilidad y bloqueo (DE-1) | — | Contrato `stock_disponible(insumo_ids, bloquear)`. JSON: la derivación actual. PostgreSQL: `insumo` `FOR UPDATE` ordenado por `clave`, con disponible = físico − reservado. Lo usan la reserva (185), el consumo con override (210), los ajustes y el override P-06, antes de decidir. Es el único cambio en los services, sin cambio de reglas |
| **DI-3 (cerrada, A8)** | Stock negativo (H-1 y G-2) | — | **Implementada en A8**, en los dos modos: el service rechaza el ajuste negativo que dejaría el físico por debajo de lo reservado, aun confirmado, diciendo cuánto está reservado y en qué Órdenes. El trigger del libro queda como red. Pendiente funcional: actualizar BR-REP-049 en `rt-rma-app` después de la V1.4 |
| **DI-4** | Movimientos duplicados (Q23) | (a) Columna aditiva `operacion_id` en `movimiento_inventario`, con índice único global, como JSON. (b) Esperar a la clave de acción de E6 (por usuario) | **(a) en el Bloque A** para conservar el comportamiento. En el Bloque B se vincula con `accion_usuario.clave_idempotencia`. La deduplicación por `referencia` ya existe (`movimiento_referencia_unica`) |
| **DI-5** | `DESPERDICIO` y `DEVOLUCION` (QA-E2-10) | — | Siguen deshabilitados (CHECK `movimiento_tipo_con_operacion`). Habilitarlos exige agregar `DESPERDICIO` a `cantidad_pendiente` del dominio: queda fuera de E5 |
| **DI-6** | F-03 y F-07 | — | **F-03:** la evidencia de faltante compara el id del insumo como palabra completa en los dos modos, sin cambiar la regla; en PostgreSQL se consulta por tipo de evento 210. **F-07:** respaldo en la base: el `UPDATE` que cierra la Orden falla si quedan reservas pendientes (`v_reserva_pendiente`). La regla sigue en los services |
| **DI-7** | Doble escritura de 210 y 211 | — | En PostgreSQL las dos llamadas a `guardar` ocurren en la misma transacción. La instantánea se actualiza después de cada `guardar`, así que el segundo compara contra el primero. En JSON la brecha se mantiene documentada, porque arreglarla cambiaría el código de los casos de uso |
| **DI-8 (aprobada, A7)** | Motivo de un ajuste | (a) Agregar el código del motivo a la API y la pantalla. (b) Aceptar `motivo_texto` sin `motivo_ajuste_id`. (c) Mapear todo a un código técnico | **Aprobada:** el contrato de la API no cambia; el motivo es el texto libre, íntegro, y el código del catálogo queda opcional para una clasificación futura (migración `20261106000500`, sección 18) |

### 3.3 Acciones e idempotencia (E6)

| # | Decisión | Recomendación |
|---|---|---|
| **DE6-1** | Transporte de la clave | Encabezado opcional `Idempotency-Key`. Es compatible hacia atrás: sin clave, el comportamiento actual. Se exige solo cuando la pantalla la envíe (H-4). Implementarlo es un cambio de API: requiere aprobación al empezar el Bloque B |
| **DE6-2** | Alcance de la clave | Por usuario y operación, como el índice actual (`usuario_id, clave_idempotencia`). Los procesos del sistema usan su propio espacio de nombres |
| **DE6-3** | Clave reusada con otros parámetros | Columna aditiva `huella` (sha256 de la operación y de los parámetros normalizados) en `accion_usuario`. Si la clave coincide y la huella no, 422 `CLAVE_REUTILIZADA` |
| **DE6-4** | Respuesta guardada | `accion_usuario.respuesta` guarda el cuerpo HTTP que se devolvió. Un reintento devuelve exactamente lo mismo, incluido el código. Si llega mientras la primera sigue en curso, el índice único espera; después se lee la respuesta confirmada |
| **DE6-5** | COMMIT incierto (M4) | Código nuevo `PERSISTENCIA_RESULTADO_INCIERTO` (503). Con clave, reintentar es seguro. Sin clave, solo para las operaciones idempotentes por naturaleza |
| **DE6-6** | Rechazos | Se registran como `RECHAZADA` en su propia transacción, después del ROLLBACK, y solo para las operaciones con clave. Las demás siguen como hoy |

## 4. Diseño del agregado y su persistencia (E4)

### 4.1 Composición

`OrdenReparacion` (`domain/models/orden_reparacion.py`) se compone de:
- **Raíz:** `orden`, con copia del cliente y del equipo, posición en el proceso, prioridad, versión y `cerrada_en`.
- **Mutables:**
  - `recepcion.datos`;
  - cada Detalle: definición vigente, estado, condición, control y cancelación;
  - tomas y ejecuciones, mientras están en curso;
  - la anulación de un pago, que se completa una sola vez;
  - las marcas de documentos generados.
- **Append-only, con id del dominio:** fotos (FOT), pagos (PAG), devoluciones (DEV), movimientos de insumo (MOV), documentos emitidos (`{orden}-{SIGLA}-{vv}`).
- **Append-only, sin id:**
  - historial;
  - en cada Detalle: definiciones anteriores, autorizaciones (por `version_definicion`), controles y ajustes de garantía;
  - descuentos;
  - en la recepción: versiones anteriores, notas y registros de check-in;
  - insumos utilizados.
- **Una sola vez:** la confirmación de recepción o el «no recibido», y la salida (entrega o devolución).

**Derivados, que no se guardan:** totales, saldo, estado de pago y `esta_cerrada`. La vista `v_orden_saldo` los reproduce solo para conciliar.

### 4.2 Mapeo y guardado

| Parte | Tabla | Escritura de `guardar` |
|---|---|---|
| Raíz | `orden` | `INSERT` al crear. Después, `UPDATE … WHERE id = %s AND version = %s` con `version = version + 1`. Si no actualiza ninguna fila: conflicto |
| Cliente | `cliente`, `documento_cliente` + copia en `orden` | Alta o actualización del cliente por `codigo`. Un cambio de documento cierra el vigente y crea uno nuevo (trigger existente) |
| Equipo | `equipo` + copia en `orden` | Alta o actualización por `codigo` |
| Recepción | `recepcion`, `recepcion_version`, `recepcion_nota`, `checkin` | `UPDATE` de `datos`; `INSERT` de lo nuevo por posición |
| Detalles | `detalle`, `detalle_version`, `decision_cliente`, `ajuste_garantia`, `control_tecnico`, `orden_detalle_origen` | `UPDATE` del Detalle; `INSERT` de versiones, decisiones, ajustes y controles nuevos |
| Tomas y ejecuciones | `toma`, `ejecucion`, `ejecucion_insumo` | `INSERT` y `UPDATE` de estado. `ejecucion.detalle_version_id` es la versión vigente al insertar |
| Movimientos | `movimiento_inventario` | `INSERT` de los nuevos, con su acción. El trigger aplica el stock |
| Finanzas | `pago`, `devolucion_dinero`, `descuento` | `INSERT`. La anulación es un `UPDATE` de columnas permitidas |
| Documentos | `documento_emitido` + marcas en `orden` | `INSERT`. `plantilla_version` toma un valor fijo por tipo hasta H-3 |
| Fotos | `foto` | `INSERT`. El trigger limita a 10 y bloquea la Orden |
| Historial | `evento_negocio` (vista `v_historial_visible`) | `INSERT` de cada paso nuevo con su `tipo_evento` (tabla `equivalencia_historial`), la acción y `responsable_tipo`. La secuencia la asigna un trigger |
| Salida | `salida` | `INSERT` una vez |

**Orden de las sentencias en `guardar`:**
1. Cliente y equipo.
2. La raíz, si la Orden es nueva.
3. Las entidades hijas, de padres a hijos.
4. Los movimientos.
5. Los eventos.
6. Al final, el `UPDATE` de la raíz: versión, posición y, si corresponde, `cerrada_en`, que va siempre último ([diseño físico, regla 9](diseno-fisico.md)).

**Instantánea:** `obtener_para_modificar` guarda en el estado de la transacción la Orden cargada, su versión y la cantidad de filas de cada lista. `guardar` compara contra esa instantánea y la reemplaza al terminar, así un segundo `guardar` del mismo comando funciona (DI-7). Si `guardar` recibe una Orden sin instantánea:
- **nueva:** se inserta;
- **existente:** se rechaza con `PersistenciaError`, sin escribir nada (QA-A2-H1, sección 13.6). También se rechaza una Orden que no viene de esa instantánea.

**Prefijo:** en cada lista append-only, lo ya guardado tiene que coincidir campo a campo con el principio de la lista que llega. Si no coincide, `PersistenciaError` («una entrada inmutable cambió»). Es una invariante del dominio que la base respalda con triggers de inmutabilidad.

### 4.3 Huecos de mapeo (DA-5)

| Hueco | Propuesta |
|---|---|
| `Pago.operacion_id` y `DevolucionDinero.operacion_id` sin columna (los usan las verificaciones de duplicados) | Columna aditiva `operacion_id`, nula. En el Bloque B se vincula con la acción |
| `DefinicionAnteriorDetalle` (sin `descripcion`, con `reemplazada_en` y `usuario_id`) frente a `detalle_version` (`definida_en`, `definida_por`, `descripcion`) | Columnas aditivas `reemplazada_en` y `reemplazada_por` en `detalle_version`, y `descripcion` nula para las versiones históricas. Verificarlo con una prueba de ida y vuelta antes de A2 |
| `Documento.generado` sin `fecha_generacion` | Verificar si el dominio lo permite. Si sí: columnas booleanas aditivas; si no: documentar la invariante |
| `datos.checkin` vigente | El último registro de `checkin` |
| Override P-06, solo en el historial | Se guarda solo como evento, igual que en JSON. Las tablas `override_recursos` y `override_insumo` quedan sin uso hasta que el dominio tenga la entidad |
| `ejecucion.detalle_version_id` | La versión vigente al insertar la Ejecución |
| `documento_emitido.plantilla_version` | Constante por tipo de documento (`v1`) hasta H-3 |
| `orden.version` sin trigger | La mantiene el repository (DA-2) |
| `modificado_en`, forzado por trigger | El `updated_at` del dominio se guarda en su propia columna si existe; si no, se agrega. Verificarlo en A1 |
| `equipo.capacidad` (texto en el dominio) | Verificar el tipo de columna en A1 |

### 4.4 Lectura

**`obtener` y las consultas de E2:**
- Una consulta por tabla, filtrando por la Orden o, en los listados, por `orden_id = ANY(%s)`, para no hacer una consulta por Orden.
- El orden de las listas lo da un `ORDER BY` explícito: secuencia del evento, número de versión, fecha y luego `id`.
- Los números pasan por `decimal_sin_ceros` (E3).
- Los listados devuelven por número de Orden.

**Consultas de E2:**
- **`listar_abiertas`:** `cerrada_en IS NULL`. Es equivalente gracias a DA-6.
- **`listar_por_dni_cliente`:** por la copia del documento en la Orden (DA-8).
- **`listar_con_reservas`:** las Órdenes con reservas pendientes en `v_reserva_pendiente`. Es un subconjunto válido del contrato.
- **`listar_con_movimientos`:** por `movimiento_inventario`.
- **`claves_de_fotos`:** por `foto`.

## 5. Inventario transaccional (E5)

### 5.1 Circuitos y garantías

| Circuito | Hoy (JSON) | Con PostgreSQL |
|---|---|---|
| Reserva, 185 (`taller.iniciar_detalle`) | Calcula faltantes, agrega movimientos RESERVA a la Orden y la guarda, sin tocar el stock | Bloquea la Orden y luego los insumos (DI-2), decide con el disponible bloqueado e inserta las RESERVA en la misma transacción. Si dos comandos compiten por la última unidad, uno reserva y el otro recibe «Reserva fallida», nunca un 409 técnico |
| Consumo y liberación, 210 + 211 | Escribe el stock por insumo, después la Orden, y compensa si falla; luego un segundo `guardar` | Inserta CONSUMO y LIBERACION con su RESERVA de origen; el trigger aplica el stock. `actualizar_stock_insumo` solo se verifica (DI-1). El 211 va en la misma transacción. Todo o nada |
| Ingreso y ajuste | Dos archivos con compensación; disponible negativo con confirmación | Un `INSERT` en el libro, con los saldos anterior y posterior que calcula el trigger (se devuelven con `RETURNING`). H-1 rechaza el negativo (DI-3). Deduplicación por `referencia` y `operacion_id` (DI-4) |
| Override P-06 | Paso del historial con el impacto en texto | Igual, como evento. El impacto se calcula con el disponible bloqueado |
| Revalidación (080 y masiva) | Lee el stock y escribe solo la Orden | Igual, sin bloquear insumos: no reserva. Si la lectura queda vieja, es inofensivo, como hoy |
| Disponibilidad (pantallas) | Se deriva leyendo todas las Órdenes con reservas | `insumo.stock_fisico − stock_reservado`, sin recorrer Órdenes |

**Invariantes que garantiza la base:**
- reservado ≥ 0 y físico ≥ reservado;
- un movimiento es inmutable;
- un CONSUMO o una LIBERACION necesitan una RESERVA de origen con saldo pendiente;
- no hay movimientos en una Orden cerrada.

`verificar_integridad()` concilia el libro con los saldos. Una corrida de cada suite de concurrencia tiene que dejarlo vacío.

### 5.2 Bloqueos

**Orden:** Orden (`FOR NO KEY UPDATE`), Cliente, Documento y Equipo si cambian, después todos los insumos del comando ordenados por `clave`, antes del primer movimiento. El trigger vuelve a bloquear cada insumo, pero ya lo tiene. El modo del bloqueo de insumos se define antes de A6: `FOR UPDATE` después de un `KEY SHARE` produce un deadlock (QA-A2-M4, sección 13.7). Un comando que toca varias Órdenes (la revalidación masiva) usa una transacción por Orden, como hoy. Con `lock_timeout = 5 s`, una espera agotada da 409 `reintentable`, sin reintento automático.

**Escenarios de prueba concurrentes** (con hilos y barreras, contra la base local):
1. **La última unidad:** dos reservas de Órdenes distintas. Exactamente una reserva; la otra recibe 186.
2. **Reserva contra ajuste negativo** del mismo insumo: ningún resultado deja físico < reservado.
3. **Consumo contra ingreso:** los saldos finales son la suma exacta.
4. **Dos comandos sobre la misma Orden:** se serializan. Ninguno pisa al otro (versión) y el historial queda completo.
5. **Insumos en orden inverso:** dos comandos que tocan A y B en orden contrario no se bloquean mutuamente (sin deadlock), gracias al orden por `clave`.
6. **Interrupción a mitad de comando:** se corta la conexión o se lanza una excepción después del primer movimiento. No queda nada escrito.
7. **El mismo ajuste dos veces** con la misma `referencia` u `operacion_id`: uno se registra y el otro recibe 409.

## 6. Acciones e idempotencia (E6)

### 6.1 Clasificación de las operaciones

| Grupo | Operaciones | Tratamiento |
|---|---|---|
| **Crean registros en cada llamada (necesitan clave)** | Alta de Orden (cliente externo, RT interno, RMA de garantía); definir un Detalle (dos rutas); nota de recepción; notificar; pago; devolución de dinero; foto; ingreso y ajuste de stock; sincronización del catálogo | Clave obligatoria cuando la pantalla la envíe (H-4). Un reintento devuelve la respuesta guardada |
| **Transición de estado (un reintento recibe 409)** | Tomar, iniciar, completar o interrumpir, autorizar, prioridad, garantía, anular un pago, entregar, cancelar, retiros, controles, override, cola, revisión, devolución a RT | Idempotentes por naturaleza. Con clave, un reintento después de un COMMIT incierto devuelve el resultado en lugar del 409 |
| **Sin cambio si se repite** | Recepción (`PUT`), comprobantes (`NO-OP` si el contenido es el mismo), check-in con el mismo valor, limpieza de fotos | No necesitan clave |

**Deduplicación que existe hoy:** el `operacion_id` del cuerpo, en pagos, devoluciones y stock, que responde 409 en lugar del resultado original. La clave de inventario cambia en cada envío (`Inventario.tsx`), así que no protege un reintento manual.

### 6.2 Contrato propuesto (sin cambiar la API todavía)

1. **Registro de la acción.** La capa de aplicación abre la transacción con un descriptor `Accion(operacion, usuario, clave, huella)`, al menos en las operaciones del primer grupo. El primer `INSERT` es la acción CONFIRMADA.
2. **Clave repetida:**
   - si la clave ya existe CONFIRMADA y la huella coincide, se devuelve `respuesta` sin ejecutar nada;
   - si la huella no coincide, 422;
   - si hay otra en curso, se espera el índice único y luego se lee la respuesta.
3. **Fin del comando.** Al terminar, se completa `respuesta` y `orden_id`, el único `UPDATE` permitido.
4. **Rechazo.** Después del ROLLBACK, si la operación tenía clave, se registra la acción RECHAZADA en otra transacción, para auditoría.
5. **COMMIT incierto (M4).** Error `PERSISTENCIA_RESULTADO_INCIERTO`. La pantalla reintenta con la misma clave.
6. **Fotos.** La clave define el nombre del objeto en GCS, así que un reintento no duplica el objeto.

## 7. Equivalencia (E7)

### 7.1 Estrategia

1. **Contratos de repositorio** parametrizados con JSON y PostgreSQL:
   - `test_contrato_ordenes.py` (hoy solo JSON, 33 pruebas), más los contratos nuevos de stock;
   - la misma prueba, sin excepciones por modo, salvo las diferencias técnicas de 7.2.
2. **Ida y vuelta del agregado:** para el corpus (HP-REP-001, 002 y 003, VAR-REP, EXC-REP, multidetalle, finanzas con pagos, anulaciones, devoluciones y descuentos, garantía, fotos y documentos), la Orden se guarda en cada paso del recorrido y `obtener` devuelve exactamente la misma. Es el criterio de E4: «HP-REP-001 y unas 10 Órdenes vuelven idénticas».
3. **Diferencial por HTTP**, versionado esta vez:
   - un arnés corre los mismos guiones de pedidos contra la aplicación en modo JSON y en modo PostgreSQL local;
   - normaliza los ids aleatorios, las fechas y los huecos de numeración;
   - compara cada respuesta y el estado final, incluido el stock por insumo.
4. **Suites de la API en los dos modos:**
   - un sembrador independiente del modo, que carga catálogos y stock por repositories o por SQL;
   - los ayudantes de stock (`_stock`, `_fijar_stock`) pasan por el repositorio;
   - aislamiento por prueba con bases clonadas de una plantilla (`CREATE DATABASE … TEMPLATE`);
   - las pruebas que leen archivos JSON por diseño quedan solo para JSON, marcadas.
5. **Concurrencia e interrupciones:** se comparan invariantes, no respuestas: `verificar_integridad()` vacío, sin stock negativo, un solo ganador.
6. **Errores de persistencia:**
   - corte de conexión;
   - `lock_timeout`;
   - COMMIT incierto simulado;
   - pool agotado, que da 503.

### 7.2 Diferencias técnicas aceptables

- **Ids aleatorios y huecos de numeración:** un alta revertida no reutiliza su número en PostgreSQL.
- **Formato de fechas:** se normaliza a UTC con el mismo formato.
- **Escala de los números:** una fuente con ceros de más (QA-E3-8).
- **Concurrencia:**
  - PostgreSQL permite paralelismo entre Órdenes distintas;
  - un conflicto real da 409 `reintentable`;
  - el pool agotado da 503;
  - JSON serializa todo.
- **Restricciones más estrictas en PostgreSQL:** las de la base y las de H-1, que también rige en JSON.

Cualquier otra diferencia de negocio (estado, saldo, historial visible, stock, documentos) es un defecto.

### 7.3 Condiciones para arrancar en modo PostgreSQL (solo local)

1. Están implementados todos los repositories que usa la aplicación: Órdenes, Catálogos con stock y Modelos. El catálogo de Ventas sigue en JSON.
2. El pool se abre y se cierra en el `lifespan`, con una sola unidad de trabajo (DA-9 y QA-E3-4).
3. Las migraciones locales están aplicadas, incluidas las de este diseño, y los medios de pago existen (DA-10).
4. El diferencial y las suites de la API están en verde en los dos modos, y `verificar_integridad()` queda vacío después de la suite.
5. Las dos pruebas que hoy exigen el bloqueo del arranque se reemplazan por una que admite PostgreSQL **solo con una URL local**. DEV/UAT sigue requiriendo E8 y una autorización aparte.

## 8. Plan de slices

### Bloque A (E4 + E5)

| Slice | Objetivo | Repositories y contratos | Migraciones locales | Pruebas | Aceptación |
|---|---|---|---|---|---|
| **A0. Base** | Preparar sin cambiar comportamiento | Vinculación por constructor (QA-E2-4); `lectura(aislamiento)`; registro sin `currval`/`lastval`; descriptor de acción técnica (DA-3); sembrador independiente del modo y bases por plantilla | Aditivas de DA-5, DA-6, DA-7 (numeración), DA-10 (medios de pago), DI-4 y DI-8 si se aprueba (b) | Suite JSON sin cambios; pruebas de migración sobre una base anterior (como en E3) | Todo en verde; ninguna expectativa cambiada |
| **A1. Alta y lectura del agregado** | Crear una Orden y leerla | `PostgresOrdenReparacionRepository`: `reservar_codigo`, `guardar` (alta), `obtener`, `listar` | — | Ida y vuelta de las altas del corpus; numeración concurrente (N hilos, números únicos); QA-E2-5 por encima de 999999 | `obtener(guardar(o)) == o` en las altas |
| **A2. Guardado incremental** | Mutaciones y conflictos | `obtener_para_modificar` (bloqueo), instantánea, versión, prefijos, `cerrada_en` | — | HP-REP-001, guardado y vuelta en cada paso; dos comandos sobre la misma Orden; guardar sin instantánea; entrada inmutable alterada | Ida y vuelta en todos los pasos; conflicto con 409 y sin escritura |
| **A3. Finanzas** | Pagos, anulación, devoluciones, descuentos | Mapeo de finanzas; medios por FK | — | Corpus de finanzas; saldo de `v_orden_saldo` igual al del dominio; duplicados por `operacion_id` | Saldos y estado de pago idénticos |
| **A4. Recepción, documentos, fotos, salida** | El resto del agregado | Mapeo de recepción, check-in, documentos, fotos y salida | — | Corpus de custodia, garantía y entrega; límite de 10 fotos | Ida y vuelta completa del corpus |
| **A5. Consultas de E2** | C3 a C7 en PostgreSQL | `listar_abiertas`, `por_dni`, `con_reservas`, `con_movimientos`, `claves_de_fotos`; lectura `REPEATABLE READ` (F-09) | — | `test_contrato_ordenes.py` con el parámetro `postgres` | Mismo contrato que JSON |
| **A6. Reservas** | 185 atómico y concurrente | `stock_disponible` (DE-1) en JSON y PostgreSQL; bloqueo ordenado; H-1 | — | Escenarios 1, 2 y 5 de §5.2; reserva fallida funcional | Un solo ganador; integridad vacía |
| **A7. Consumo, ingresos y ajustes** | 210 y 211 atómicos; libro | Movimientos con origen; `actualizar_stock_insumo` que verifica; `registrar_movimiento_stock` y `listar_movimientos_stock` en PostgreSQL; F-03 y F-07 | — | Escenarios 3, 6 y 7; consumo con override; reintento del 210 | Saldos exactos; todo o nada |
| **A8. Endurecimiento** | Concurrencia e interrupciones de punta a punta | — | — | Carga con N hilos, cortes de conexión, `lock_timeout`; mutaciones de las invariantes críticas | Integridad vacía en todas las corridas; sin deadlocks |

### Bloque B (E6 + E7)

| Slice | Objetivo | Dependencia |
|---|---|---|
| **B1. Acciones explícitas e idempotencia en el servidor** | Descriptor `Accion` en las operaciones del primer grupo; clave opcional por encabezado; huella; respuesta guardada; RECHAZADA (DE6-1 a DE6-6) | Bloque A; aprobación del cambio de API |
| **B2. COMMIT incierto** | `PERSISTENCIA_RESULTADO_INCIERTO`; reintento con clave | B1 |
| **B3. Pantalla (H-4)** | Claves estables en todas las operaciones del primer grupo, incluido el inventario | B1; aprobación del cambio en la pantalla |
| **B4. Cableado local** | `lifespan` con el pool; contexto PostgreSQL; prueba de una unidad por pool; arranque solo con una URL local | Bloque A |
| **B5. Equivalencia** | Arnés diferencial versionado; suites de la API parametrizadas; informe de diferencias | B4 |
| **B6. Activación local** | Suite completa en modo PostgreSQL; integridad vacía; documentación | B5 |

### 8.1 Dependencias

```
A0 ──► A1 ──► A2 ──┬─► A3 ──┐
                   ├─► A4 ──┼─► A5 ──► A6 ──► A7 ──► A8 ──► (QA Bloque A)
                   └────────┘
(QA A) ──► B1 ──► B2 ──► B3
     └──► B4 ──► B5 ──► B6 ──► (QA Bloque B)
```

- A3 y A4 pueden avanzar en paralelo después de A2.
- A6 necesita A2 (bloqueo y guardado de movimientos) y A0 (acción técnica).
- B4 puede empezar en paralelo con B1.

## 9. Metodología y plan de QA

1. **Este discovery** y una aprobación arquitectónica de las decisiones de la sección 3. Se aprueban todas juntas; las no bloqueantes pueden quedar con su recomendación por defecto.
2. **Bloque A por slices.** Cada slice cierra con:
   - sus pruebas automáticas, más la suite JSON y la de PostgreSQL locales;
   - `ruff` y `npm run validate:all` si toca `business/`;
   - mutaciones de las invariantes críticas que agrega (bloqueo, versión, prefijo, orden de bloqueo, todo o nada);
   - una nota breve en el documento de diseño.

   Un slice no pide una aprobación nueva, salvo que aparezca una decisión no prevista o un conflicto de integridad.
3. **Checkpoints internos** al cerrar A2, A5 y A8. Con un revisor independiente y focalizado en el slice, no una auditoría general.
4. **QA independiente integral del Bloque A,** con dos revisores en paralelo:
   - persistencia y concurrencia del agregado;
   - inventario y equivalencia.

   Se audita el bloque entero una sola vez.
5. **Correcciones focalizadas** y una **verificación puntual** solo de lo corregido. No se repite la auditoría general por correcciones menores.
6. **Commits autorizados del Bloque A** (sección 10).
7. **Bloque B**, con el mismo esquema: slices, una QA integral y una verificación puntual.
8. **Cierre documental:** `ESTADO_PROYECTO.md`, pendientes y diseño.

**Criterios de aceptación del Bloque A:**
- ida y vuelta exacta del corpus;
- contrato de Órdenes y de stock igual en los dos modos;
- los 7 escenarios concurrentes de §5.2 en verde, repetidos 3 veces;
- `verificar_integridad()` vacío;
- suite JSON sin cambios de expectativas, salvo H-1, que está aprobado;
- mutaciones de las invariantes detectadas;
- PostgreSQL sigue desactivado en la aplicación.

**Criterios de aceptación del Bloque B:**
- un reintento con clave devuelve la misma respuesta sin duplicar filas;
- una clave reusada con otros parámetros da 422;
- el COMMIT incierto se distingue;
- el diferencial y las suites de la API en verde en los dos modos;
- arranque local en modo PostgreSQL;
- sin cambios en DEV/UAT ni en producción.

## 10. Commits y checkpoints propuestos

| Commit | Contenido | Cuándo |
|---|---|---|
| A-1 | A0: base, migraciones locales aditivas, sembrador y bases por prueba | Después de la QA del Bloque A, o antes si se autorizan commits intermedios |
| A-2 | A1 y A2: núcleo del agregado | ídem |
| A-3 | A3 a A5: resto del agregado y consultas | ídem |
| A-4 | A6 a A8: inventario transaccional y concurrencia | ídem |
| B-1 a B-3 | Idempotencia; cableado y equivalencia; activación local | Después de la QA del Bloque B |

**Decisión de proceso:** se recomienda autorizar **commits locales por grupo de slices** (sin push), después de su checkpoint. Así la QA del bloque revisa commits acotados y no un único cambio enorme. La alternativa es un solo commit por bloque después de su QA.

## 11. Riesgos

| Riesgo | Mitigación |
|---|---|
| Huecos de mapeo no detectados que rompen la ida y vuelta | Corpus amplio y prueba de ida y vuelta en cada slice; migraciones aditivas (DA-5) |
| Rendimiento de cargar el agregado (15 a 20 consultas) y de `listar()` | Consultas por lote (`ANY`); medir en A5 y en E8. `listar()` queda solo para el listado general |
| Deadlocks por un orden de bloqueo violado | Un único punto que bloquea los insumos (DI-2), prueba con orden inverso y `lock_timeout` |
| Diferencias entre el cálculo de stock de Python y el trigger | Verificación del saldo esperado (DI-1): error explícito, no silencio |
| Cambios de API y pantalla para la idempotencia (H-4) | Aislados en el Bloque B, compatibles hacia atrás y con aprobación propia |
| Un motivo de ajuste sin catálogo en la API (DI-8) | Decisión de producto antes de A7 |
| Datos de UAT incompatibles (stock negativo, `cerrada_en`, inventario inicial sin INGRESO) | Paso de datos de E8 con inventario previo; fuera de E4 a E7 |
| Pruebas de la API acopladas a los archivos JSON | Sembrador y ayudantes independientes del modo (A0 y B5), migrados de a poco |
| Volumen del cambio | Slices con criterios propios, checkpoints y commits por grupo |
| Pendientes de E3 que llegan al cableado (QA-E3-4, QAF-14, E4-MP) | Resueltos en A0 y B4 (DA-7, DA-9, DA-10) |

## 12. Pendientes previos que este diseño resuelve o asigna

| # | Dónde |
|---|---|
| E4-MP | DA-10, A0 |
| QAF-14 | DA-7, A0 |
| F-05 | DA-8, A5 |
| F-06 | DA-6, A2 |
| F-09 | DA-4, A5 |
| QA-E2-4 | DA-9, A0 |
| QA-E2-5 | DA-7, A1 |
| DE-1 | DI-2, A6 |
| F-03 y F-07 | DI-6, A7 |
| QA-E2-10 | DI-5, fuera de alcance |
| Q23 | DI-4, A0 y A7 |
| M4 | DE6-5, B2 |
| QA-E3-4 | DA-9, B4 |
| H-1 | DI-3, A6 |
| H-4 | B3 |

## 13. Bloque A: implementación de A0, A1 y A2 (checkpoint)

Implementado el 05/11/2026 sobre `99734f2`, sin commit. Se aplican las decisiones aprobadas DA-1, DA-2, DA-3, DA-5, DA-10, DI-1, DI-2 y DI-3, y las no bloqueantes DA-4, DA-6 y DA-7. DI-8 sigue pendiente.

La aplicación sigue en JSON: `RMA_PERSISTENCIA=postgres` detiene el arranque y no hay modo mixto. No se tocó nada remoto.

### 13.1 Qué se implementó

**A0. Infraestructura**

- **Migración local `20261106000100_e4_agregado.sql`.** Es aditiva:
  - `rma.formatear_numero_orden`: número de Orden sin truncar (QA-E2-5, DA-7). Pasa a ser el default de `orden.codigo`.
  - `orden.actualizado_en`: el `updated_at` del dominio. `modificado_en` lo pisa un trigger.
  - `detalle_version.garantia_dias_reemplazada`.
  - Columna `posicion` en las listas sin fecha única: Detalles de origen, decisiones, ajustes, controles, tomas, ejecuciones e insumos utilizados.
  - CHECK `orden_cerrada_con_fecha` (DA-6, F-06).
  - Los cinco medios de pago predeterminados como filas (DA-10, E4-MP).
- **Unidad de trabajo:**
  - `datos_de_transaccion()`: un almacén que vive lo que dura la transacción. Guarda las instantáneas y la acción.
  - La lectura breve pasa a `REPEATABLE READ READ ONLY` (DA-4, F-09).
- **Registro de consultas:** rechaza `currval` y `lastval` (QAF-14).
- **Acción del comando (`acciones.py`, DA-3).** Se crea dentro de la transacción la primera vez que hace falta: una por comando, CONFIRMADA y sin clave.
  - Responsable: el usuario del primer paso nuevo del historial o, si no hay, `SISTEMA`.
  - Si el comando se revierte, la acción también.
- **Pruebas:**
  - `clonar_base` (bases por plantilla, una por prueba);
  - `sembrado.py` carga en PostgreSQL los mismos catálogos JSON que la prueba;
  - `corpus_ordenes.py` graba cada Orden que guardan flujos reales de la API.

**A1. Alta y lectura (`ordenes.py`, `ordenes_lectura.py`)**

- **`obtener` y `listar`.** Una consulta por tabla, filtrada por la lista de Órdenes (`= ANY`), con `ORDER BY` explícito y las fechas en UTC.
- **`reservar_codigo`:**
  - toma `nextval` y lo formatea en la misma sentencia;
  - salta un número ya guardado con un código explícito;
  - exige una transacción.
- **`guardar` de una Orden nueva.** Inserta, en la misma transacción:
  - el cliente compartido y su documento vigente;
  - el equipo y la raíz;
  - los Detalles de origen y la recepción;
  - los Detalles con sus versiones, decisiones y ajustes;
  - las tomas, las ejecuciones con sus insumos utilizados y los controles;
  - los eventos del historial, cada uno con su tipo de evento (`equivalencia_historial`) y la acción.
- **Lo que A1 y A2 todavía no guardan se rechaza con `PersistenciaError`** antes de escribir:
  - pagos, devoluciones y descuentos (A3);
  - documentos emitidos, fotos, versiones, notas y check-in de la recepción, y la salida (A4);
  - movimientos de insumo (A6, A7).

  Las consultas dedicadas de E2 responden «llega en A5».

**A2. Guardado incremental y concurrencia**

- **`obtener_para_modificar`:**
  - exige una transacción;
  - toma `FOR NO KEY UPDATE` sobre la Orden;
  - carga el agregado y deja la instantánea en la transacción.
- **`guardar`** compara la Orden que llega con la instantánea y hace `UPDATE` o `INSERT`, nunca borra.

**Mutables y append-only.** Se verificó en el código que estas son las únicas partes que cambian; todo lo demás solo crece:

| Parte | Qué cambia |
|---|---|
| Raíz | estado, posición, prioridad, referencia RT, copias de cliente y equipo, marcas de documentos, `updated_at` y cierre |
| Recepción | solo hasta decidir la custodia |
| Detalle | estado, condición, control vigente, garantía, cancelación y observaciones |
| Toma | estado, fin y liberación |
| Ejecución | estado, fin, observaciones y motivos, mientras está EN_PROGRESO |

Solo crecen el historial, las versiones de definición, las decisiones, los ajustes, los controles, los insumos utilizados y los Detalles de origen. En cada uno, lo guardado tiene que ser el principio de lo que llega.

**Versionado de la definición.** La versión *k* es la definición *k*. Quién y cuándo la reemplazó, y con qué garantía quedó, se guardan en la fila *k+1*, porque las filas son inmutables. La definición vigente solo cambia con una versión nueva: si no, es un error.

### 13.2 Semántica de versión y conflictos

| Caso | Resultado |
|---|---|
| `guardar` sin cambios | No escribe nada; la versión no cambia |
| `guardar` con cambios | `version + 1`, también si el cambio no deja historial (prioridad, check-in, descuento) |
| Dos `guardar` en el mismo comando (DI-7) | Cada uno sube 1. El segundo compara contra el primero. Una sola acción |
| Dos comandos sobre la misma Orden | Se serializan por el bloqueo. El segundo lee lo que confirmó el primero: no se pierde ningún cambio, sea el mismo campo o distintos |
| `UPDATE` final con una versión que no coincide | `ConflictoDeEscrituraError` (409); la transacción se revierte |
| `guardar` de una Orden existente que no viene de `obtener_para_modificar` en esta transacción | `PersistenciaError`, sin escribir nada (sección 13.6) |
| `guardar` de una Orden cerrada | `ConflictoDeEscrituraError` |
| Dentro del comando, una entrada inmutable alterada | `PersistenciaError` («inmutable»): es un error de programación |
| `lock_timeout` agotado esperando la Orden | 409 `reintentable`, sin reintento automático |
| Error a mitad de `guardar` | Se revierte todo: la Orden, sus hijas y la acción |

Todos los comandos de la aplicación que modifican una Orden usan `obtener_para_modificar` (`application/modificacion.py`). Las únicas que guardan sin instantánea son las tres altas.

### 13.3 Pruebas

| Conjunto | Resultado |
|---|---|
| Conjunto PostgreSQL (E1 a E4, cargas y generador) | 537, 2 corridas pasan (antes de A0 eran 460) |
| Suite JSON | 1659 pasan, 178 se saltean (las de PostgreSQL, sin la base). Ninguna expectativa de JSON cambió |
| Pruebas SQL de Supabase | todas OK, con la migración de E4 |
| `ruff check` del backend y `npm run validate:all` | sin errores |
| `ruff format --check` de los archivos de A0 a A2 y de la corrección | sin errores. Sobre todo el backend marca 11 archivos que ya estaban así y no son de este trabajo |
| Mutaciones de QA-A2-H1 y L-3 | 17 de 17 detectadas |

`tests/postgres/test_ordenes_postgres.py` (58 pruebas; las de QA-A2-H1, A2-3 y L-3 están en la sección 13.6):
- **Guardar y releer:** cada uno de los 52 pasos de 8 Órdenes reales vuelve idéntico, como objeto y en su JSON. La versión se verifica en cada paso.
- **Corpus:**
  - alta externa y RT interna;
  - dos Detalles, ingreso, toma;
  - ejecución completa con insumos, control aprobado y rechazado;
  - ejecución que pide redefinición, con revisión y versión nueva;
  - ejecución interrumpida, Detalle cancelado, Orden en revisión y cancelada;
  - un cliente con DNI en dos Órdenes.
- **Alta:**
  - fuera de una transacción;
  - con error, sin dejar nada;
  - con partes fuera de alcance;
  - con un código inexistente o decimales de más.
- **Numeración:** 8 hilos a la vez sin números repetidos, por encima de 999999 y sin repetir un número guardado.
- **Guardado:**
  - sin cambios;
  - un cambio sin historial sube la versión;
  - dos comandos sobre campos distintos y sobre el mismo campo;
  - una lectura vieja;
  - una versión obsoleta.
- **Inmutables:** 7 alteraciones distintas.
- **Atomicidad y bloqueo:**
  - error a mitad, que revierte todo;
  - bloqueo retenido y liberado al revertir;
  - Orden cerrada y el CHECK de cierre;
  - dos `guardar` en el mismo comando;
  - una acción por comando y ninguna si se revierte.
- **Migración de E4** sobre datos existentes.

Además:
- el registro rechaza `currval` y `lastval`;
- la lectura breve es `REPEATABLE READ`;
- las pruebas estáticas cubren los módulos nuevos.

Las pruebas de E3 que simulan una base anterior a E3 pasan a usar las migraciones anteriores por nombre, porque la de E4 supone las columnas de E3. No cambia lo que verifican.

**Mutaciones:** se reintrodujo cada defecto de a uno, y las 11 fueron detectadas. Los archivos se restauraron y se verificó su hash.
- Concurrencia:
  - sin `FOR NO KEY UPDATE`;
  - sin control de versión;
  - la versión no sube;
  - sin instantánea en `obtener_para_modificar`.
- Integridad del agregado:
  - sin exigir prefijo;
  - partes fuera de alcance aceptadas;
  - la definición vigente cambia sin versión.
- Resto:
  - una acción por cada `guardar`;
  - lectura en `READ COMMITTED`;
  - `reservar_codigo` que repite un número;
  - el registro admite `currval`.

### 13.4 Hallazgos y decisiones para el checkpoint

| # | Hallazgo | Propuesta |
|---|---|---|
| A2-1 | **Orden de los slices.** Los flujos reales llegan a partes de A4 justo después de definir los trabajos: las versiones y el check-in de la recepción, y el comprobante de ingreso. Sin A4, ninguna Orden real llega al taller por la API. Las pruebas de A1 y A2 usan las Órdenes reales proyectadas: se quitan solo esas partes, que van a tablas propias | Hacer A4 antes que A3, o en paralelo. La prueba de guardar y releer del flujo completo queda como criterio de A4 |
| A2-2 | QA-E2-4 (vincular la unidad de trabajo por constructor) no se hizo en JSON en A0. El repository PostgreSQL ya la recibe por constructor; cambiar el contexto JSON toca muchas pruebas que usan `replace()` y no hace falta mientras no se cablee PostgreSQL | Pasarlo a B4 (cableado), junto con QA-E3-4 |
| A2-3 | El orden de bloqueo efectivo es Orden → Cliente: la fila del cliente se bloquea solo si cambian sus datos. El diseño decía Cliente → Orden. No se encontró ningún ciclo: un alta bloquea el cliente e inserta una Orden nueva, que nadie más tiene | **Aprobado**, ampliado con Documento y Equipo (sección 13.7) |
| A2-4 | `test_contrato_ordenes.py` sigue solo en JSON: casi todo son consultas de E2 (A5). El contrato de A1 y A2 está en `test_ordenes_postgres.py` | Parametrizarlo en A5 |
| A2-5 | La acción técnica toma como operación la referencia del primer paso nuevo (por ejemplo `PROC-REP-170`) | Definir los nombres de operación en B1 |
| A2-6 | `cerrada_en` toma el `updated_at` del `guardar` que cierra. La versión 1 de una definición registra como fecha el alta de la Orden, porque el dominio no la tiene. Las filas históricas creadas de una vez (una importación) guardan la garantía final | Aceptar; documentado |
| A2-7 | El corpus no cubre las Órdenes de garantía (RMA): Detalles de origen y Detalle de origen | Cubrirlas en A4, cuyo flujo las crea |

### 13.5 Preparación para E5 y E6

- **E5:**
  - una sola transacción puede incluir la Orden y el inventario: los movimientos se insertarán desde `guardar`, con la misma acción;
  - el bloqueo de la Orden se toma primero, y el de los insumos (DI-2) irá después, por `clave`;
  - las tablas de movimientos todavía no se tocan.
- **E6:** la acción del comando es la fila que E6 completará con la clave de idempotencia y la respuesta. Ya está en la transacción y es única por comando.
- **Reintentos internos:** un `guardar` repetido no duplica eventos ni filas, porque compara contra la instantánea.

### 13.6 QA del checkpoint y corrección QA-A2-H1

La QA independiente de A0 a A2 concluyó **APPROVED WITH OBSERVATIONS**, con un defecto HIGH. Los hallazgos diferidos están en [`integracion-pendientes.md`](integracion-pendientes.md#hallazgos-de-la-qa-del-checkpoint-a2).

**QA-A2-H1** es la pérdida de actualizaciones al guardar una Orden existente sin instantánea. No tiene relación con **H-1** del diseño lógico, que es la regla aprobada sobre el stock negativo (DI-3).

El defecto: sin instantánea, `guardar` leía la versión bajo su propio bloqueo y la comparaba consigo misma. Una lectura vieja pisaba en silencio cualquier campo sin historial, aun sin cambios propios. Ningún comando lo hacía, pero el contrato lo permitía.

**Contrato de `guardar`:**

| Lo que llega | Resultado |
|---|---|
| Orden nueva, sin marca | Se inserta |
| Orden con marca, sin instantánea de ese código | `PersistenciaError`: salió de otra Orden, no pasa a ser un alta |
| Orden existente sin instantánea en esta transacción | `PersistenciaError` |
| Hay instantánea, pero lo que llega no viene de ella (lectura previa, `obtener` dentro del comando, instantánea de otra Orden u otra transacción) | `PersistenciaError` |
| Viene de `obtener_para_modificar` en esta transacción, también como copia de un service | Se guarda |
| Segundo `guardar` de una Orden creada en esta transacción | Se guarda: esa fila no la pudo escribir nadie más |
| Dos altas simultáneas del mismo código | La segunda da 409 por `orden_codigo_key`: nunca se vuelve una actualización |

El rechazo no escribe nada e invalida el comando: lo que ya hubiera hecho se revierte, aunque el caso de uso atrape el error.

**La marca.** Comprobar que existe una instantánea no alcanza: en `obtener` → `obtener_para_modificar` → `guardar(lectura vieja)` existe, y el contenido no distingue un valor viejo de un cambio legítimo. `updated_at` tampoco sirve, porque muchos comandos toman la fecha antes de esperar el bloqueo y puede retroceder. Por eso `obtener_para_modificar` entrega la Orden con una marca propia de la transacción:
- está fuera de los campos: no cambia el modelo, la igualdad ni lo que se serializa;
- `model_copy` y `deepcopy` la conservan, y así modifican todos los services;
- reconstruir la Orden la pierde, y entonces se rechaza: el error es ruidoso, nunca silencioso.

Es una convención interna del repository, aprobada en el cierre del checkpoint. Depende de pydantic: que `model_copy` y `deepcopy` conserven `__dict__`, y que `__eq__` y la serialización ignoren lo que no es un campo, como con un `cached_property`. Verificado con pydantic 2.13.5. Al actualizarlo, las pruebas `test_h1_la_marca_*` y `test_h1_una_orden_reconstruida_se_rechaza` fallan si deja de valer. Con toda la suite JSON marcada, 5170 guardados de 46 funciones de aplicación llegaron con marca o fueron altas, y ninguno sin marca.

JSON no incorpora la restricción en esta etapa: sigue con su sección crítica y su control de historial. La alineación queda para B4.

**L-3. Traducción de errores:**

| SQLSTATE | Error | HTTP |
|---|---|---|
| `40001`, `40P01` | `ConflictoDeEscrituraError`, reintentable: «los datos cambiaron» | 409 |
| `55P03` | `ConflictoDeEscrituraError`, reintentable: «otra operación está usando estos datos» | 409 |
| `23505` de una clave única de negocio, o de un trigger | `ConflictoDeEscrituraError`: «ya existe un registro con esos datos» | 409 |
| `23505` de una clave primaria y el resto de la clase 23 (CHECK, clave foránea, NOT NULL, triggers) | `RestriccionDeIntegridadError` | 500 |
| Clase 22 (valor inválido) | `DatosInvalidosError` | 500 |
| Lo demás | `PersistenciaError`, sin cambios | 500 |

Los dos errores nuevos son `PersistenciaError`, así que usan el 500 genérico que ya existe: `api/errores.py` no cambió y no hay códigos nuevos. Lo que cambia, solo en PostgreSQL y mientras esté inactivo, es que esos casos dejan de ser 409. Ningún error le muestra al cliente nombres de restricciones ni detalles SQL: el 409 lleva un mensaje propio, y el SQLSTATE y la restricción quedan en los atributos del error y en el log. Si un service necesita informar un rechazo de la base, tiene que validarlo antes: es lo que DI-2 prevé para el stock en A6.

Se ajustaron las expectativas de cuatro pruebas de E3 que afirmaban que toda la clase 23 era un conflicto, y de cinco de A2 que guardaban una Orden ajena después de `obtener_para_modificar`.

### 13.7 Regla de bloqueos (A2-3, aprobada)

**Modificación de una Orden existente:** Orden → Cliente → Documento → Equipo → insumos por `clave` ascendente.

| Paso | Cuándo | Modo |
|---|---|---|
| Orden | Siempre, en `obtener_para_modificar` | `FOR NO KEY UPDATE` |
| Cliente | Solo si su copia cambió | `FOR UPDATE` |
| Documento del cliente | Solo si la copia del cliente cambió | `FOR UPDATE` |
| Equipo | Solo si su copia cambió | `FOR UPDATE` |
| Insumos (A6) | Antes del primer movimiento | Se define antes de A6 (QA-A2-M4) |

**Altas:** Cliente → Documento → Equipo, y después se inserta la Orden, que todavía no ve nadie. Una garantía RMA toma además `KEY SHARE` sobre su Orden origen por la clave foránea, que no choca con `FOR NO KEY UPDATE`.

**Otros caminos, verificados:**
- el movimiento de stock solo toma el insumo, sin tocar Órdenes;
- la revalidación masiva abre una transacción por Orden;
- `aplicar_movimientos_inventario` corre dentro del comando que ya tiene la Orden.

`test_a2_3_al_modificar_orden_cliente_documento_equipo` y `test_a2_3_un_alta_bloquea_cliente_documento_y_equipo` verifican el orden de las consultas.

**`FOR UPDATE` no se aplica de forma general.** Choca con el `KEY SHARE` que toman las claves foráneas: dos transacciones con `KEY SHARE` sobre una fila que después piden `FOR UPDATE` terminan en deadlock (`40P01`, reproducido); con `FOR NO KEY UPDATE`, no. Una fila que otras referencian se bloquea con `FOR NO KEY UPDATE`, salvo que cambie su clave. Hoy Cliente, Documento y Equipo usan `FOR UPDATE` sin riesgo, porque todo lo que los referencia se inserta después de bloquearlos. Conviene pasarlos a `FOR NO KEY UPDATE` junto con QA-A2-M4.

**Orden de los hijos:** ninguna fila hija de una Orden existente se inserta antes de bloquearla. El trigger `exigir_orden_abierta` toma `FOR SHARE`, y sin el bloqueo previo dos transacciones podrían quedar esperándose al pedir uno más fuerte. La precondición de `guardar` lo garantiza.

### 13.8 Condiciones de entrada de A4

Todas resueltas en A4 (sección 14). La 3 se decidió así: `plantilla_version` se vuelve opcional.

1. **Trigger de fotos.** `rma.foto_limite_por_orden` debe usar `FOR NO KEY UPDATE`, con una migración aditiva (`create or replace function`).
   - Hoy toma `FOR UPDATE` sobre la Orden. Con un comando que ya tiene la Orden y otra transacción con `KEY SHARE` sobre ella que después la pide, se reprodujo un deadlock y la foto fue la víctima. Con `FOR NO KEY UPDATE` no hubo ciclo ni espera.
   - El límite no cambia: `FOR NO KEY UPDATE` choca consigo mismo. Con 9 fotos y 4 altas simultáneas quedaron 10 en las dos versiones.
   - Ningún camino actual toma `KEY SHARE` sobre una Orden antes de bloquearla, así que no es un defecto de hoy. E6 podría crearlo si inserta la acción con `orden_id` antes del bloqueo.
   - Pruebas de entrada: las dos anteriores, contra la migración real.
2. **Check-in después de la custodia.** `registrar_checkin` cambia `recepcion.datos.checkin` y agrega un registro, pero `recepcion_decidida_no_cambia` impide actualizar `rma.recepcion` después de decidir la custodia. `datos.checkin` tiene que derivarse del último `rma.checkin`, y si no hay ninguno, de `checkin_ingreso`. Hoy `_recepcion` rechaza ese caso.
3. **`documento_emitido.plantilla_version`** es obligatoria y el dominio no tiene ese campo. **Decisión:** un valor constante por tipo de documento, o volverla opcional con una migración.
4. **`posicion` en las tablas de A4.** `recepcion_version`, `recepcion_nota`, `checkin`, `foto` y `documento_emitido` no la tienen, y la verificación de prefijo necesita el orden exacto del dominio. Una fecha no alcanza: dos entradas pueden compartirla, y `documentos.emitidos` mezcla tipos. Migración aditiva, como la de A0.
5. **Mapeos que no son directos:**
   - `recepcion_version.datos` guarda también `equipo`, porque `VersionRecepcion` lo tiene;
   - `documento_emitido.contenido` se escribe con `model_dump(mode="json")`, para que los importes no pasen por `float`;
   - `reemplaza_a` es un código en el dominio y un `uuid` en la tabla;
   - `salida` es una fila por Orden y el dominio tiene `devolucion` y `entrega`: se reconstruye por `tipo`, y hay que verificar que nunca coexistan;
   - `recibido_por` e `identificacion_receptor` van a `retira_nombre` y `retira_identificacion`; `retira_vinculo` y `retira_telefono` quedan vacíos.
6. **Cierre.** La salida y los documentos se insertan antes del `UPDATE` de la raíz, que sigue siendo el último (regla 9).
7. **Contratos que se amplían:**
   - `_exigir_partes_soportadas` deja de rechazar `documentos.emitidos`, `fotos`, `devolucion`, `entrega`, `recepcion.versiones_anteriores`, `recepcion.notas` y `recepcion.registros_checkin`; sigue rechazando A3 y A6;
   - `Instantanea` y `cargar_ordenes` suman esas listas, con una consulta por tabla;
   - `_Guardado` las trata como listas que solo crecen;
   - `proyectar` deja de quitarlas del corpus;
   - el corpus suma las Órdenes de garantía (A2-7).
8. **Límite de A4:** la entrega de una Orden con saldo necesita A3, porque el historial referencia el pago. La prueba de punta a punta de entrega y garantía queda para después de A3 y A4.

## 14. Bloque A: implementación de A4 (checkpoint)

**Estado:** implementado y aprobado. A3 sigue después; la QA integral de recepción, taller y entrega se hace cuando estén A3 y A4. E4 no está completa.

### 14.1 Qué se implementó

| Parte del dominio | Tabla | Cómo se guarda |
|---|---|---|
| `recepcion.versiones_anteriores` | `recepcion_version` | Solo crece. `datos` (JSONB) guarda `equipo` y `datos` de esa versión |
| `recepcion.notas` | `recepcion_nota` | Solo crece, también después de decidir la custodia |
| `recepcion.registros_checkin` | `checkin` | Solo crece, también después de decidir la custodia |
| `recepcion.datos.checkin` | `checkin` o `recepcion.checkin_ingreso` | Se reconstruye: el último registro y, si no hay, el del ingreso |
| `fotos` | `foto` | Solo crece |
| `documentos.emitidos` | `documento_emitido` | Solo crece. `reemplaza_a` pasa de código a `uuid` y vuelve |
| `entrega`, `devolucion` | `salida` | Una fila por Orden, inmutable |

Cada comando sigue siendo una transacción, con una sola acción técnica, sin borrar ni reconstruir nada. Una nota, una foto o un check-in suben la versión aunque no dejen historial. `guardar` aplica primero la precondición de QA-A2-H1, y solo después las validaciones de contenido.

`guardar` sigue rechazando pagos, devoluciones y descuentos (A3) y movimientos de insumo (A6 y A7).

### 14.2 Mapeos resueltos

- **Check-in posterior a la custodia.** `rma.recepcion` no se toca, porque un trigger lo impide: el registro va a `rma.checkin` y `datos.checkin` se reconstruye al leer. Si el dominio trajera un check-in vigente distinto del último registro, se rechaza, porque se perdería al releer. En toda la suite JSON no ocurre nunca.
- **Entrega y devolución.** El `tipo` no las distingue: una Orden sin reparación se entrega como `DEVOLUCION_SIN_REPARACION`. Decide el estado, porque `entrega` solo existe en una Orden ENTREGADA. Una salida que no corresponde a su estado se rechaza. `retira_vinculo` y `retira_telefono` quedan vacíos, porque el dominio no los tiene. Un RT interno no tiene salida en el dominio y no genera fila.
- **Importes.** `contenido` se escribe con `model_dump(mode="json")`, igual que en JSON: los importes son texto dentro del JSONB, nunca números. Conservan todos sus decimales, también los ceros finales.
- **`plantilla_version`.** Se vuelve opcional y `guardar` no la escribe, porque el dominio no la registra. Las filas que la tengan la conservan, y el CHECK sigue rechazando un texto vacío.
- **`posicion`.** Se agrega en las cinco tablas, con un índice único parcial por Orden. Las filas anteriores no se tocan: quedan sin posición, se leen primero por fecha y las nuevas se numeran a continuación. Los empates de fecha entre esas filas se resuelven con `registrado_en` en las versiones, con el código en fotos y documentos, y con el id en las notas y el check-in.

### 14.3 Migración

`20261106000200_e4_recepcion_documentos.sql`, aditiva y solo local:
- `posicion` e índices únicos parciales en `recepcion_version`, `recepcion_nota`, `checkin`, `foto` y `documento_emitido`;
- `plantilla_version` sin `NOT NULL`;
- `foto_limite_por_orden` con `FOR NO KEY UPDATE`.

Una prueba vuelve el esquema atrás sobre una base con datos y aplica la migración real: ninguna fila cambia.

### 14.4 Pruebas

| Conjunto | Resultado |
|---|---|
| Suite PostgreSQL local | 609 pasan, 2 corridas |
| Suite JSON | 1661 pasan, 248 se saltean (las de PostgreSQL, sin la base). Ninguna expectativa de JSON cambió |
| Pruebas SQL de Supabase | todas OK, con las dos migraciones de E4 |
| `ruff check` del backend, `ruff format --check` de lo modificado y `npm run validate:all` | sin errores |
| Mutaciones adversas (A4, QA-A2-H1 y L-3) | 31 de 31 detectadas |

`tests/postgres/test_recepcion_documentos_postgres.py` (62 pruebas). El corpus pasó a 139 pasos de 16 Órdenes, y ahora incluye corrección de recepción, notas, fotos, reemplazos de documentos, check-in, entrega, devolución, equipo no recibido, RT cerrado y garantía RMA de punta a punta.

**Equivalencia:** cada paso del corpus, leído de PostgreSQL, es igual a su ida y vuelta por JSON, como objeto y como JSON.

**Medición sobre toda la suite JSON,** con un plugin de una sola corrida: 5396 guardados de 46 funciones de aplicación. Ninguno sin marca, ninguno viola una regla del esquema de A4, y los 72 pasos distintos del historial tienen equivalencia en `rma.equivalencia_historial`.

**Comandos reales sobre PostgreSQL:** `crear_orden`, `registrar_recepcion`, `agregar_observacion_recepcion`, `agregar_foto`, `definir_reparacion`, `enviar_a_revision`, `confirmar_recepcion`, `registrar_no_recepcion`, `emitir_comprobante_recepcion`, `cancelar_orden`, `registrar_devolucion`, `registrar_checkin` y `entregar`.

**Concurrencia de fotos:**

| Escenario | Resultado |
|---|---|
| 4 subidas reales con 9 fotos | Una se guarda y tres reciben el 409 funcional. Quedan 10 |
| 4 comandos del repository con 9 fotos | Una se guarda y tres reciben la restricción. Quedan 10 |
| 4 altas directas por SQL, sin bloqueo del comando | Una se guarda: el trigger sostiene el límite solo |
| Comando con la Orden, y dos transacciones con `KEY SHARE` que después la piden | Sin deadlock y sin espera. Con `FOR UPDATE` era un `40P01` |

### 14.5 Hallazgos

| # | Hallazgo | Propuesta |
|---|---|---|
| A4-1 | Un texto con el carácter NUL: JSON lo guarda y PostgreSQL lo rechaza con un 500, sin escribir nada. Vale para cualquier texto, no solo los de A4 | Decidir antes de E7: rechazarlo en la API con un 422 cambiaría un contrato HTTP |
| A4-2 | `generar_comprobante_ingreso`, y por eso el ingreso real de un cliente externo, necesita `listar_con_reservas` (A5). Los flujos reales lo cubren por el corpus y no como comando sobre PostgreSQL | Cubrirlo en A5 |
| A4-3 | Una fila de `salida` de tipo `DEVOLUCION_GESTION_RT` no se puede leer: el dominio no tiene ese valor. Ningún flujo la crea | Revisar en E8 |
| A4-4 | `documentos.emitidos` y `fotos` se cargan completos con cada Orden, también `contenido`. `listar` trae todo | Medir en A5, junto con las consultas dedicadas |
| A4-5 | Filas sin `posicion` con fechas idénticas: si coinciden todas las fechas de la cadena, ningún dato conserva el orden original y queda el del id, estable pero arbitrario. Se detectó porque dos pruebas fallaban de forma intermitente: el reloj de Windows avanza cada ~15 ms y el corpus producía esos empates. No tiene impacto funcional: esas filas no existen (DEV y UAT no tienen Órdenes) y todo lo que escribe A4 lleva posición | Aceptado. El corpus separa sus comandos y la prueba de empates fija sus fechas. Las expectativas de las dos pruebas no cambiaron |

## 15. Bloque A: implementación de A3 (finanzas)

**Estado:** implementado el 06/11/2026, sin commit. Con A3 y A4, `guardar` solo rechaza los movimientos de insumo (A6 y A7).

### 15.1 Qué se implementó

| Parte del dominio | Tabla | Cómo se guarda |
|---|---|---|
| `resumen_pago.pagos` | `pago` | Solo crece, con `posicion`. Lo único mutable es la anulación: `UPDATE` de `anulado_*`, una sola vez (lo exige `pago_validar`). Cambiar otro dato, quitar o intercalar un pago da `PersistenciaError` |
| `resumen_pago.devoluciones` | `devolucion_dinero` | Solo crece, con `posicion`. `pago_id` pasa de código a `uuid` del pago de la misma Orden |
| `descuentos` | `descuento` | Solo crece, con `posicion`. `tipo` y `valor` nulos: quita el descuento |
| `historial[].pago_id` | `evento_negocio.pago_id` | `uuid` del pago de la Orden; un código ajeno da `PersistenciaError` |

- `metodo` y `medio` se resuelven por código en `rma.medio_pago` (DA-10): un código desconocido es un error explícito y no se escribe nada.
- Importes con `_escala` a dos decimales (la API y los services ya los limitan). Se leen sin ceros de más (DE3-3): `100.50` vuelve como `100.5`, con el mismo valor.
- Pagos, devoluciones y descuentos se insertan antes del historial y la raíz va al final, como en A4: un pago y el cierre en el mismo comando respetan `exigir_orden_abierta`.

### 15.2 Migración

`20261106000300_e4_finanzas.sql`, aditiva y solo local:
- `operacion_id` nulo en `pago` y `devolucion_dinero`, con índice único parcial por Orden. Es la red bajo la verificación del service: un duplicado que llegue a la base da el 409 de L-3 (`pago_operacion`).
- `posicion` e índices únicos parciales en `pago`, `devolucion_dinero` y `descuento`.
- `v_orden_saldo`: el descuento vigente se elige por `posicion` (antes, por fecha e id: con dos registros en el mismo instante podía elegir el que no era el último). Mismas columnas.
- `devolucion_dinero_validar` bloquea el pago con `FOR NO KEY UPDATE` en lugar de `FOR UPDATE` (punto 8 del handoff, patrón QA-A2-M4). Sigue serializando dos devoluciones del mismo pago y la anulación; ya no choca con el `KEY SHARE` de las claves foráneas.

### 15.3 Pruebas

`tests/postgres/test_finanzas_postgres.py` (20 pruebas) y el corpus ampliado (`corpus_ordenes.py`): `proyectar` ya no quita pagos, descuentos ni pasos con `pago_id`, y se suman dos recorridos reales por la API (anticipos con `operacion_id` y referencia, anulación, cuatro cambios de descuento incluido quitarlo, Detalle cancelado, pago parcial y final al entregar; pago completo, Orden cancelada y crédito devuelto en dos partes).

- En cada paso financiero del corpus, la Orden vuelve igual (objeto y JSON) y subtotal, descuento, total, pagado, devuelto, saldo y estado de pago del dominio son los de `v_orden_saldo`.
- Comandos reales sobre PostgreSQL: `registrar_pago_de_orden`, `anular_pago_de_orden`, `aplicar_descuento_de_orden`, `cancelar_detalle` y `registrar_devolucion_de_dinero`; cada uno sube la versión en 1.
- Sin duplicados: el mismo `operacion_id` en dos comandos simultáneos registra un solo pago; tres pagos simultáneos distintos se conservan todos; un reintento no escribe nada.
- Alteraciones adversas (monto, medio, quitar, intercalar, segunda anulación, descuento cambiado o quitado, medio inexistente, devolución de un pago ajeno) se rechazan sin escribir ni cambiar la versión.
- Un error después de insertar el pago revierte el comando entero.
- Una transacción con `KEY SHARE` sobre el pago no frena la devolución.

`test_lo_que_todavia_no_se_guarda_se_rechaza_sin_escribir` usaba un pago como ejemplo de parte no soportada; ahora usa un movimiento de insumo, que sigue sin soporte. La expectativa (rechazo sin escribir) no cambió.

### 15.4 Hallazgos

| # | Hallazgo | Propuesta |
|---|---|---|
| A3-1 | DE3-3 alcanza a los importes de pagos, devoluciones y descuentos: `100.50` se relee `100.5`. El valor y los cálculos son iguales; cambia el texto en la respuesta de la API | MINOR, aceptado como en E3 |
| A3-2 | La unicidad de `operacion_id` es por Orden, como en JSON. DI-4 y E6 la vinculan con la clave de idempotencia por usuario | Revisar en E6 |
| A3-3 | En la validación integrada (`tests/postgres`: 295 pasan, 1 falla) falló `test_numeracion_concurrente_unica_y_sin_truncar` (A2, sin cambios): 8 altas simultáneas con el mismo Cliente nuevo; dos lo insertan y una recibe el 409 de `cliente_codigo_key`, con rollback. Carrera anterior a A3: pasó en el checkpoint A4 y falló en las corridas de A3 y A5. Sin flujo real afectado | MINOR. Resolver en A8 (`ON CONFLICT DO NOTHING` y releer con bloqueo) |

## 16. Bloque A: implementación de A5 (consultas dedicadas y lecturas consistentes)

**Estado:** implementado el 06/11/2026, sin commit.

### 16.1 Consultas

Cada consulta de E2 es un filtro SQL estático que devuelve las candidatas con su versión. Las Órdenes se cargan por lote (una consulta por tabla, sin N+1) y el resultado lo decide el mismo predicado que usa JSON sobre la Orden cargada, así que la semántica y el orden por número son los de JSON por construcción.

| Consulta | Filtro SQL | Predicado |
|---|---|---|
| `obtener`, `listar` | Por código; todas | — |
| `listar_abiertas` | Ni `ENTREGADA` ni `EVT-REP-999` | `not esta_cerrada` |
| `listar_por_dni_cliente` | La copia del cliente en la Orden (QA-A2-L1) | `cliente.dni == dni` |
| `listar_con_reservas` | Alguna `RESERVA` en `rma.movimiento_inventario` (de esas claves) | Igual que JSON: toda Orden con alguna RESERVA |
| `listar_con_movimientos` | Algún movimiento de la Orden (de esa clave) | Igual que JSON |
| `claves_de_fotos` | `objeto_clave` de `rma.foto`, en una sola consulta | — |

Las validaciones de parámetros (`None`, un `str` como colección, colección vacía) son las de JSON.

### 16.2 QA-A2-M2: lecturas consistentes sin cambiar el aislamiento

Fuera de un comando, la lectura breve sigue siendo REPEATABLE READ. Dentro de un comando (READ COMMITTED), `UnidadDeTrabajoPostgres.lectura_de_un_instante()` es falso y el repository:

1. **Valida la carga por versión.** Lee las candidatas con su versión, carga el agregado y relee las versiones. Si alguna cambió, otro comando confirmó en el medio y se carga otra vez, hasta 3 veces; después, `ConflictoDeEscrituraError` reintentable. Alcanza porque todo cambio del agregado sube `rma.orden.version` (DA-2) y la confirmación de otro comando es atómica. No toma bloqueos ni cambia el aislamiento de los comandos.
2. **Fija una versión por Orden en el comando (QA-E2-1).** La primera versión leída de una Orden que el comando no bloqueó queda en el almacén de la transacción; las consultas siguientes se evalúan sobre ella, también si el filtro SQL ya no la trae. Las Órdenes bloqueadas (`obtener_para_modificar`) o escritas por el comando se leen como están.

### 16.3 Pruebas

- `tests/test_contrato_ordenes.py` con JSON y PostgreSQL (A2-4): 46 pasan y 16 se saltean (las de PostgreSQL que guardan movimientos, hasta A6).
- `tests/postgres/test_consultas_postgres.py` (10 pruebas):
  - Una escritura que confirma entre la raíz y las hijas mezcla la Orden sin la validación y no con ella, en `obtener`, `listar` y `listar_abiertas`.
  - Si la Orden no deja de cambiar, el conflicto es reintentable.
  - Una sola versión por comando, y lo bloqueado se lee fresco.
  - Bandejas de inicio y de taller de los cuatro roles, pendientes de autorización, búsqueda por DNI y `generar_comprobante_ingreso` (A4-2) dan lo mismo en JSON y en PostgreSQL, desde el mismo estado y con el reloj fijo.
- Integración focalizada de lo que usa `obtener` y `listar` (`test_ordenes_postgres.py`, `test_recepcion_documentos_postgres.py`, `test_finanzas_postgres.py`): 148 pasan y 1 falla, A3-3.

### 16.4 Hallazgos

| # | Hallazgo | Propuesta |
|---|---|---|
| A5-1 | El esquema rechaza datos que JSON guarda y la app no produce: una Orden que nace cerrada (QA-A2-M3), un número fuera de `OR-NNNNNN`, dos clientes con el mismo DNI, un cliente externo sin cliente y códigos de hijas repetidos entre Órdenes | Aceptado. El contrato E2 en PostgreSQL arma sus datos respetándolos; lo que verifica no cambia |
| A5-2 | Los filtros de reservas y movimientos solo se probaron vacíos: no hay movimientos guardados hasta A6 | Habilitar en A6 las pruebas del contrato que se saltean |
| A5-3 | Dos altas simultáneas con el mismo DNI nuevo: una recibe el 409 de `documento_cliente_numero_unico`. No duplica el cliente | Revisar con A3-3 en A8 o B4 |

## 17. Bloque A: implementación de A6 (reservas)

**Estado:** implementado el 06/11/2026, sin commit.

### 17.1 Qué se implementó

- **Reservas en el agregado.** Los movimientos de la Orden se guardan en `rma.movimiento_inventario` con `posicion`, solo crecen y llevan la acción del comando. El trigger del libro aplica `stock_reservado` y rechaza un disponible negativo. Se leen por `posicion` con el insumo por `clave`. `guardar` acepta solo RESERVA: consumos, liberaciones y devoluciones se rechazan hasta A7.
- **DI-2: bloqueo de insumos.** `CatalogosRepository.bloquear_insumos(insumo_ids)` toma `FOR NO KEY UPDATE` por `clave` ascendente en PostgreSQL. En JSON no hace nada, porque el lock de la unidad de trabajo ya serializa. La reserva (185, `taller.iniciar_detalle`) lo llama después de bloquear la Orden y antes de leer stock y reservas. `guardar` lo vuelve a pedir antes del primer movimiento. Orden de bloqueos: Orden → Cliente → Documento → Equipo → insumos por `clave` (A2-3).
- **El valor de `stock_disponible` sigue saliendo de los services.** Bajo el bloqueo, el cálculo actual (físico menos reservas propias y ajenas) ya no cambia hasta confirmar. No se agregó una función que devuelva el disponible desde la base, para no repetir la regla de reserva pendiente en un tercer lugar (DE-1). Los services no cambiaron.
- **Red por debajo.** Si un camino no bloquea, el trigger igual impide la sobreasignación: la segunda reserva recibe un error técnico (500) y no queda nada escrito. La prueba de control lo verifica.

### 17.2 Migración

`20261106000400_e5_reservas.sql`, solo local:
- `posicion` en `movimiento_inventario`, con un índice único parcial por Orden;
- QA-A2-M1: la clave de `ejecucion_insumo` pasa a `(ejecucion_id, posicion)`, con `posicion NOT NULL` (DEV y UAT no tienen Órdenes). Un `INSERT` sin posición recibe la siguiente de su Ejecución, por trigger. `v_ejecucion_insumo_consumo` suma las líneas de un mismo insumo y conserva sus columnas;
- QA-A2-M4: `aplicar_movimiento_inventario` bloquea el insumo con `FOR NO KEY UPDATE`, con el mismo cuerpo.

### 17.3 Pruebas

- `tests/postgres/test_reservas_postgres.py` (14 pruebas), con la reserva 185 real sobre PostgreSQL (catálogos y stock en la base):
  - escenario 1 de §5.2: dos técnicos por la última unidad; uno reserva y el otro recibe 186, sin errores. La prueba fuerza la superposición: espera después de leer las reservas;
  - control sin el bloqueo: el trigger rechaza la segunda;
  - sin stock: reserva fallida y ningún movimiento;
  - con stock suficiente, las dos reservas conviven;
  - insumos bloqueados después de la Orden y antes del primer movimiento, aunque el dominio los traiga en otro orden;
  - un `KEY SHARE` sobre el insumo no frena la reserva;
  - rollback completo;
  - un movimiento repetido da 409 y una reserva alterada se rechaza;
  - dos líneas del mismo insumo (M-1);
  - las consultas de E2 con reservas reales, dentro y fuera de un comando (A5-2).
- `test_contrato_ordenes.py` en PostgreSQL usa las Órdenes con reservas: 61 pasan y 1 se saltea (`listar_con_movimientos` necesita consumos, A7).
- JSON, el contrato de la reserva: EXC-REP-003, override con reservas ajenas, inventario operativo, escrituras concurrentes, consistencia de E2 y HP-REP-001. Pasan 121.
- Pruebas SQL de Supabase, base local y cargas iniciales: pasan 28.

### 17.4 Hallazgos

| # | Hallazgo | Propuesta |
|---|---|---|
| A6-1 | El corpus sigue sin movimientos: sus flujos consumen, y el consumo es A7 | Sumarlos al corpus en A7 |
| A6-2 | Los caminos que A7 implementa (consumo con override 210, ajustes, H-1) tienen que llamar a `bloquear_insumos` antes de decidir. Sin eso, el trigger los protege igual, pero con un 500 en lugar del mensaje funcional | Criterio de A7; escenario 2 de §5.2 en A7 |
| A6-3 | Cliente, Documento y Equipo siguen con `FOR UPDATE` (sección 13.7). Hoy no hay riesgo: todo lo que los referencia se inserta después de bloquearlos | Pasarlos a `FOR NO KEY UPDATE` en A8 |

## 18. Bloque A: implementación de A7 (consumo, ingresos y ajustes)

**Estado:** implementado el 06/11/2026, sin commit.

### 18.1 Qué se implementó

- **Consumo y liberación (210 y 211).** `guardar` inserta CONSUMO y LIBERACION_RESERVA con su RESERVA de origen. El trigger exige que la reserva tenga pendiente suficiente, así que no puede haber doble consumo ni doble liberación. DEVOLUCION y DESPERDICIO no tienen operación en el dominio ni en la API, y el CHECK del libro no los admite (DI-5): se rechazan con un mensaje explícito.
- **DI-1: el libro es la fuente de verdad.** `actualizar_stock_insumo` no escribe en PostgreSQL. Registra el stock que espera el service, y `guardar` lo compara con el del libro después de insertar los movimientos. Una diferencia es `PersistenciaError` y revierte el comando. La compensación de JSON (`_restaurar_stock`) queda sin efecto en PostgreSQL, porque la transacción revierte todo.
- **Ingresos y ajustes.** `registrar_movimiento_stock` inserta en el libro con la acción del comando, el usuario, la referencia y `operacion_id`, y verifica que los saldos del trigger sean los que calculó el service (DI-1). `listar_movimientos_stock` devuelve los registrados por un usuario, en orden de llegada (`secuencia`). El saldo inicial que carga el sistema no es un movimiento del dominio, como en JSON, donde vive en el catálogo.
- **DI-8:** el motivo del ajuste se guarda íntegro en `motivo_texto` y `motivo_ajuste_id` queda vacío.
- **A6-2: bloqueo antes de decidir.** El 210, tanto al cerrar una Ejecución como al liberar una Orden ajena, bloquea los insumos del Detalle y los utilizados antes de calcular el tope del override y el stock. Ingresos y ajustes bloquean el insumo antes de leer su situación y los movimientos existentes. Siempre después de la Orden y por `clave`.
- **A6-1:** el corpus ya no quita los movimientos. La base arranca con el stock inicial del catálogo y el libro reproduce los flujos JSON: 8 reservas, 6 consumos y 2 liberaciones.

### 18.2 Migración

`20261106000500_e5_movimientos.sql`, solo local:
- DI-8: `movimiento_vinculos_por_tipo` deja de exigir `motivo_ajuste_id` en un ajuste. Las demás condiciones no cambian, y `motivo_texto` no puede quedar vacío;
- DI-4: `operacion_id`, con un índice único global, igual que en JSON;
- `secuencia`: el orden de llegada de cada movimiento nuevo, con su secuencia y el permiso para `rma_backend`.

### 18.3 Pruebas

- `tests/postgres/test_movimientos_postgres.py` (17 pruebas, comandos reales):
  - consumo y liberación: completar, interrumpir y uso parcial;
  - diferencia con el libro (DI-1);
  - doble consumo y doble liberación;
  - completar otra vez;
  - ingreso, operación y referencia repetidas, y dos envíos simultáneos de la misma operación;
  - ajuste con motivo libre y confirmación;
  - H-1;
  - historial de movimientos;
  - escenarios 2 y 3 de §5.2, y consumo contra reserva del mismo insumo.
- Contrato E2 en JSON y PostgreSQL, completo con consumos y liberaciones: 97 pasan con el de catálogos, sin saltos.
- Corpus con movimientos en los módulos de A1 a A6: 171 pasan y fallan 2. Una es A3-3; la otra era `test_l3_una_clave_primaria_no_se_presenta_como_conflicto`, que provocaba la clave primaria con M-1. Ahora la provoca con un Detalle de origen repetido y su expectativa no cambió.
- JSON de inventario, 210 y liberación: 64 pasan. SQL de Supabase, base local y cargas iniciales: 28 pasan.

### 18.4 Hallazgos

| # | Hallazgo | Propuesta |
|---|---|---|
| A7-1 | **H-1 no está en el service.** En JSON, un ajuste negativo confirmado todavía puede dejar el disponible negativo. En PostgreSQL lo rechaza el trigger, con el 500 genérico y sin escribir nada | Decidir antes de B4 (activación): validar H-1 en `registrar_movimiento_operativo`, en los dos modos, con el mensaje de DI-3. Es la regla ya aprobada, pero cambia expectativas de pruebas JSON y requiere autorización |
| A7-2 | Devolución y desperdicio de insumos: el dominio no tiene operación (DI-5) | Sin cambio. Habilitarlos es una regla funcional nueva |
| A7-3 | Una expectativa de stock (DI-1) que no sigue un `guardar` en la misma transacción no se verifica. Hoy toda llamada a `actualizar_stock_insumo` es del 210, que guarda enseguida | Aceptado |

## 19. Bloque A: A8, cierre e integración

**Estado:** implementado el 06/11/2026, sin commit. Cierra el Bloque A (E4 + E5).

### 19.1 Cambios

| Tema | Cambio |
|---|---|
| **DI-3 / A7-1 (H-1)** | `registrar_movimiento_operativo` rechaza el ajuste negativo que dejaría el disponible negativo, aun confirmado, con `PrecondicionInvalidaError` (409): el mensaje dice lo reservado y las Órdenes. El insumo ya está bloqueado (A7). El resto de los ajustes negativos sigue pidiendo confirmación. En PostgreSQL el trigger sigue como red: si alguien saltea el service, el rechazo es técnico y no escribe nada |
| **A3-3** | El alta de un cliente o un equipo nuevo usa `INSERT ... ON CONFLICT (codigo) DO NOTHING`: si otra alta simultánea lo creó, espera a que confirme y lo relee bloqueado. Sin duplicados ni reintentos |
| **A5-3** | **Decisión aceptada:** dos altas simultáneas con el mismo DNI nuevo y clientes distintos. Una se guarda y la otra recibe 409 (`documento_cliente_numero_unico`), con rollback completo. Nunca hay dos clientes con el mismo DNI; al reintentar, la búsqueda por DNI encuentra al primero |
| **A6-3** | Sin cambio. En cada comando, `FOR UPDATE` sobre Cliente, Documento y Equipo precede a todo `KEY SHARE` sobre esas filas, porque las filas que los referencian se insertan después. Un `UPDATE` de la Orden que no cambia `cliente_id` ni `equipo_id` no toma `KEY SHARE`. La prueba con dos cambios del mismo cliente y un alta que lo reutiliza corre sin deadlock ni errores |
| **L-3** | La prueba de la clave primaria verifica que el error es `RestriccionDeIntegridadError`, no un conflicto, que no es reintentable, que la restricción es `orden_detalle_origen_pkey` y que no se escribe nada |
| Guardas de E3 | El registro de SQL admite las consultas de stock que escriben (A6 y A7). Las lecturas de A5 respetan la convención de constantes registradas |

### 19.2 Pruebas que cambiaron por DI-3

- `test_inventario_operativo.py::test_7_8_9_17_ajuste_que_toca_reservas_se_rechaza_h1`, antes `..._exige_confirmacion`. El ajuste que deja el disponible en −1 ahora se rechaza aun confirmado; el que lo deja en 0 pide confirmación.
- `test_bandejas.py::test_coordinacion_ve_faltantes_y_disponible_negativo`. El disponible negativo ya no se produce con un ajuste: se arma como dato anterior a H-1, como los de UAT que E8 regulariza (J-5).
- En PostgreSQL, `test_a7_h1_*` espera el error funcional y una prueba nueva verifica la red del trigger.

### 19.3 Integración

`tests/postgres/test_bloque_a_postgres.py`: los recorridos reales del corpus corren por HTTP con la API apuntando a PostgreSQL. La aplicación no se activa: la prueba reemplaza su contexto. Cubren alta, recepción, documentos, fotos, definición, reserva, ejecución y consumo, control, pagos, descuentos, devoluciones de dinero, ingreso y ajuste de stock, entrega, devolución del equipo y garantía RMA.

Las mismas corridas en JSON dan, Orden por Orden, los mismos estados, Detalles, movimientos, pagos, saldos, historial, documentos y salida. El saldo de `v_orden_saldo` y el stock físico del libro coinciden con el dominio y con JSON. `verificar_integridad()` queda vacía y todo evento tiene su acción. H-1 por la API responde 409.

### 19.4 Validación integral del Bloque A

| Conjunto | Resultado |
|---|---|
| Suite PostgreSQL (`tests/postgres` y los archivos de contrato, errores, concurrencia, E2 y E3 que corren contra la base) | 704 pasan, ninguna falla |
| Suite JSON completa | 1663 pasan y 341 se saltean (las de PostgreSQL, sin la base) |
| `ruff check .` y `ruff format --check` de los archivos modificados | sin errores |
| Pruebas SQL de Supabase y de migraciones | Incluidas en la suite PostgreSQL |
| `npm run validate:all` | No se corrió: no cambió `business/`, `specs/` ni `traceability/` |

### 19.5 Riesgos residuales

| # | Riesgo | Etapa |
|---|---|---|
| A5-3 | Dos altas simultáneas con el mismo DNI nuevo: 409 para una (decisión aceptada) | Aceptado |
| DI-3 | Actualizar BR-REP-049 en `rt-rma-app`; la pantalla de inventario muestra el rechazo como error, sin la confirmación anterior | Funcional, después de la V1.4 |
| A4-1 | Texto con NUL: 500 en PostgreSQL | Decisión antes de E7 |
| QA-A2-M3, QA-A2-L5, A4-3 | Datos históricos (Órdenes cerradas, CHECK sin `NOT VALID`, salida RT) | E8 |
| A4-4 | Fotos y documentos completos en cada carga | Medir en E8 |
| A3-2, M4 | `operacion_id` por Orden; resultado incierto del `COMMIT` | E6 |
| QA-A2-L1, QA-H1 en JSON | Documento de un cliente reutilizado sin DNI; procedencia en JSON | B4 |

## 20. Bloque B: implementación de B1 (idempotencia en el servidor)

**Estado:** implementado el 06/11/2026, sin commit. Aplica DE6-1 a DE6-4 y DE6-6; DE6-5 (COMMIT incierto) es B2.

### 20.1 Qué se implementó

- **Clave por encabezado (DE6-1).** `Idempotency-Key` opcional en los endpoints del primer grupo (sección 6.1): alta de Orden (cliente externo, RT interno y garantía RMA), definir un Detalle (las dos rutas), nota de recepción, notificar, pago, devolución de dinero, ingreso y ajuste de stock. Se aplica con el decorador `@idempotente` (`api/idempotencia.py`); el cuerpo de los endpoints no cambió. **Sin clave, todo es igual que antes.** Es el único cambio de la API y es aditivo: un encabezado opcional y el 422 `CLAVE_REUTILIZADA`.
- **Alcance y huella (DE6-2, DE6-3).** La clave es de cada usuario: la unicidad la da el índice que ya existía (`accion_usuario_idempotencia`, usuario y clave entre las acciones CONFIRMADAS). La huella es el SHA-256 de la operación y de sus parámetros (ruta y cuerpo); la misma clave con otra huella responde 422 y no escribe nada.
- **Una transacción (DE6-4).** `con_clave` registra la acción con su clave, ejecuta el caso de uso (que se une a la transacción), arma la respuesta y la guarda en la acción. La respuesta se confirma con el comando o no se confirma, así que no puede quedar un resultado confirmado falso. Esa acción es la del comando: eventos y movimientos la referencian, y se completa su `orden_id`.
- **Reintento.** Con la clave confirmada y la misma huella, se devuelve la respuesta guardada, con su código y su cuerpo, sin ejecutar nada.
- **Concurrencia.** Una segunda solicitud con la clave de otra en curso espera en el índice único (`INSERT ... ON CONFLICT DO NOTHING`). Si la primera confirma, recibe su respuesta; si se revierte, ejecuta.
- **Rechazos (DE6-6).** Un rechazo funcional revierte el comando y queda RECHAZADO, con su motivo y su respuesta, en otra transacción, solo para auditoría. No bloquea la clave: un reintento ejecuta otra vez. Así se puede reenviar un ajuste con `confirmado` sin cambiar la clave. Los errores técnicos no se registran.
- **`operacion_id` no cambió:** sigue siendo la deduplicación del dominio, y forma parte de la huella.
- **JSON** no registra acciones: el contexto tiene `acciones = None` y la clave se ignora.

### 20.2 Migración

`20261107000100_e6_idempotencia.sql`, aditiva y solo local: `accion_usuario.huella`, con un CHECK de SHA-256 hexadecimal.

### 20.3 Pruebas

`tests/postgres/test_idempotencia_postgres.py` (12 pruebas, por HTTP con la API apuntando a PostgreSQL):
- sin clave no cambia nada;
- el reintento devuelve el mismo código y cuerpo, que también es el de la API sin clave, sin otro pago ni otro cambio de versión;
- la misma clave con otros datos o con otra operación da 422 y no escribe;
- la clave es de cada usuario;
- dos solicitudes simultáneas con la misma clave dejan un solo pago y la misma respuesta;
- un fallo después de guardar el pago revierte todo, también la acción, y el reintento ejecuta;
- un rechazo queda RECHAZADO y no bloquea;
- los eventos del comando referencian la acción con clave;
- un ingreso reintentado entra una vez;
- reservas y consumos, que son transiciones, no se duplican;
- JSON ignora la clave.

Pruebas JSON de los endpoints con el decorador (pagos y devoluciones, inventario, ingreso inicial, HP-REP-001 a 003, custodia y multidetalle): pasan 167.

### 20.4 Hallazgos

| # | Hallazgo | Propuesta |
|---|---|---|
| B1-1 | Resuelto en B2+B3: la foto y la sincronización del catálogo aceptan la clave; el id de la foto y su objeto salen de ella | — |
| B1-2 | JSON ignora la clave: un reintento con clave duplica en JSON lo que en PostgreSQL no | Aceptado mientras JSON siga activo; B5 trata la diferencia |
| B1-3 | El encabezado opcional y el 422 son un cambio aditivo de la API (DE6-1), informado al implementar B1 | Confirmar al aprobar B1 |
| B1-4 | La respuesta repetida es la del momento de la operación: si la Orden cambió después, el reintento no lo muestra (DE6-4) | Aceptado: es el contrato |

## 21. Bloque B: B2 (COMMIT incierto) y B3 (claves en la pantalla)

**Estado:** implementados juntos el 06/11/2026, sin commit. Cierra E6.

### 21.1 B2: COMMIT incierto (M4, DE6-5)

- Si se pierde la conexión durante el COMMIT, la unidad de trabajo lanza `PersistenciaResultadoInciertoError` y descarta la conexión. La API responde **503 `PERSISTENCIA_RESULTADO_INCIERTO`** y no afirma ningún resultado: dice que se reintente tal cual o que se revise la Orden. Antes era un 500 genérico.
- **Con clave**, `con_clave` busca la acción con otra conexión. Si quedó confirmada, devuelve su respuesta: el usuario recibe el resultado real. Si no aparece, sigue siendo 503: no se afirma que no se guardó, porque el COMMIT pudo estar terminando. El reintento con la misma clave devuelve lo confirmado o ejecuta una vez.
- **Sin clave**, 503 aunque se haya guardado: no hay forma de saberlo.

### 21.2 B1-1: fotos y catálogo

- **Foto:** con clave, `foto_id` (y por eso el nombre del objeto) es `FOT-` más los primeros 12 caracteres del SHA-256 de usuario y clave. La huella incluye el SHA-256 del contenido. Un reintento sobrescribe el mismo objeto y devuelve la misma respuesta; otro contenido con la clave da 422.
- **Sincronización del catálogo** de equipos: decorada como las demás, con el usuario de la consulta.

### 21.3 B3: claves en la pantalla (H-4)

- **`src/api/idempotencia.ts`:** el cliente HTTP agrega `Idempotency-Key` a los POST del primer grupo, según una lista de rutas. Ninguna función de la API cambió.
- **La clave identifica la operación,** que es la ruta y el cuerpo, o el archivo en las fotos:
  - se conserva mientras el resultado es incierto (sin conexión, 5xx, 503);
  - se descarta con una respuesta definitiva (éxito o rechazo), así que repetir a propósito la misma operación es otra;
  - otra ruta u otro cuerpo, otra clave.
- **Inventario:** `operacion_id` ya no cambia en cada clic. Es el mismo para los mismos datos hasta registrarse; en el ajuste no depende de `confirmado`. Así el reintento manda el mismo cuerpo y su clave.

### 21.4 Validación integrada

| Conjunto | Resultado |
|---|---|
| PostgreSQL: idempotencia (17), recorridos E2E sin clave por los endpoints decorados (3) | 20 pasan |
| JSON: fotos, catálogo de equipos, pagos y devoluciones, inventario | 140 pasan |
| Frontend: `tsc --noEmit` y `npm test` (87, 6 de B3) | Sin errores; 87 pasan |
| `ruff check .` y `ruff format --check` de los archivos tocados | Sin errores |

Antes, la unidad de trabajo y los errores de PostgreSQL (81) y la idempotencia en desarrollo (16) también pasaron.

### 21.5 Riesgos

| # | Riesgo | Etapa |
|---|---|---|
| B1-2 | JSON ignora la clave | Mientras JSON siga activo; B5 |
| B2-1 | Sin clave, un COMMIT incierto es 503 aunque se haya guardado. La pantalla ya manda clave en todas las operaciones del primer grupo; las transiciones de estado se repiten con un 409 | Aceptado |
| B3-1 | La clave vive en la memoria de la pestaña: recargar la página durante un resultado incierto genera otra clave al reintentar | Aceptado; el mensaje del 503 pide revisar la Orden |
| B3-2 | El formulario de pago conserva su `operacion_id` mientras está abierto (comportamiento anterior): un segundo pago igual en el mismo formulario lo rechaza el dominio | Sin cambio |

## 22. Bloque B: B4 a B6 (cableado, equivalencia y activación local)

**Estado:** implementado el 06/11/2026, sin commit.

- **B4:** `RMA_PERSISTENCIA=postgres` arma el contexto real (`application/contexto.py`): pool, unidad de trabajo, repositories de Órdenes, catálogos y modelos técnicos, y registro de acciones. Sin modo mixto ni fallback: si la base no responde, la app no arranca. Solo contra un servidor local; una URL remota (Supabase) se rechaza hasta E8. El pool se cierra en el `lifespan` (`main.py`). La copia local del catálogo de Ventas y las fotos conservan su almacenamiento.
- **B5:** equivalencia de los recorridos principales por HTTP, ya probada en el cierre del Bloque A (`test_bloque_a_postgres.py`), y vuelta a correr con el cableado. No apareció ninguna diferencia bloqueante.
- **B6:** la app real (uvicorn con PostgreSQL local y el frontend de Vite) sirve los catálogos y corre un recorrido vivo: alta de Orden, Detalle, pago con clave reintentado (un solo pago), clave reutilizada (422), ingreso de stock reintentado (una sola vez). Tras reiniciar el backend, la Orden, el pago y el stock siguen iguales.
- **Pruebas:** 277 focalizadas pasan (recorridos, idempotencia, arranque, contexto FastAPI, configuración, unidad de trabajo y guardas SQL); `ruff` sin errores. Las suites completas quedan para preparar el despliegue.
- **Riesgos:** la app local conecta como superusuario; para E8 hay que usar `rma_backend` y revisar privilegios. QA-E3-4 (contador de conexiones por unidad) sigue pendiente antes de conectar a Supabase. JSON sigue disponible como modo alternativo, no como respaldo.
