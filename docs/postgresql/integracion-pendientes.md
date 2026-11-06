# Integración del backend con PostgreSQL: pendientes

Hallazgos de las revisiones de E1, E2 y E3 que no bloquearon sus commits, asignados a la etapa en que corresponde resolverlos. Lo resuelto se indica en cada caso.

H1 (contextos copiados), M1 (control transaccional externo) y QA-1 (un contexto heredado de una transacción terminada no podía abrir la suya) se corrigieron en E1.

## Repositories y conexión (E3)

Estado después de la implementación de E3 y de dos rondas de correcciones, posteriores a su QA independiente y a su QA final (05/11/2026). Sin commit, pendiente de una verificación final focalizada. El detalle está en [`e3-catalogos-diseno.md`](e3-catalogos-diseno.md), secciones 11 a 13.

### M3. BEGIN y SET LOCAL a través de Supavisor: validado

Prueba de solo lectura contra DEV/UAT (`rt-rma-db`), autorizada (DA-E3-3), el 05/11/2026: 14 de 14 verificaciones.
- El destino se confirmó antes de conectar (`rma_api` del proyecto, pooler en el puerto 6543), con TLS `verify-full` en uso.
- `BEGIN READ ONLY` con los `SET LOCAL` en un solo envío: aplicados, y no pasan a la transacción siguiente.
- Ninguna sentencia preparada en el servidor.
- El protocolo extendido en binario funciona, y el servidor rechaza dos sentencias en un envío también a través del pooler.

No se escribió nada. El script quedó fuera del repositorio.

**Alcance.** Valida el protocolo y la sesión a través de Supavisor, no el código de la aplicación:
- usó una conexión directa, sin el pool, `lectura()`, el ejecutor ni M2;
- no registró el SQLSTATE del rechazo de dos sentencias;
- no verificó que `statement_timeout` no pase a la transacción siguiente;
- la ausencia de sentencias preparadas la demuestra `prepare_threshold = None` del lado del cliente, no la vista del servidor;
- no revisó datos remotos.

Esos puntos se repiten en E8 desde Cloud Run (sección 11.2 del diseño de E3).

### M2. Conexiones ociosas cortadas: resuelto en parte

Si el `BEGIN` falla por un error de conexión, la conexión se descarta y se toma otra **una sola vez**: no es un reintento de la transacción, porque no se ejecutó nada. Si la segunda también está cortada, la respuesta es 503 `PERSISTENCIA_SIN_CONEXION` y no un 500 (QA-E3-2, corregido), y el pool repone las conexiones descartadas. `RMA_DB_POOL_MAX_IDLE_S` = 300 s, provisorio. `max_idle` solo renueva las conexiones que superan `pool_min`.

**Falta (E8).** Medir desde Cloud Run los cortes reales y decidir `max_idle` y si conviene `check_connection`.

### Interfaz restringida para los repositories: implementada (QA-2, QA-3, F-04)

- **Acceso:** los repositories usan `lectura()` o `ejecutor()` y nunca reciben la conexión; `conexion_actual()` pasó a ser privado.
- **SQL:** solo se ejecutan consultas registradas con `consulta(..., modo=LECTURA | ESCRITURA)`. Cada una cumple estas reglas:
  - es estática y de una sola sentencia;
  - empieza con `SELECT`, `WITH`, `INSERT`, `UPDATE` o `DELETE`;
  - no tiene `;`, comentarios, `$` ni `U&`;
  - usa `INTO` solo en un `INSERT INTO` en posición de sentencia (QAF-2), y nunca `pg_temp`;
  - no usa `pg_settings`, ni funciones conocidas de sesión, espera, bloqueo advisory, objetos grandes o archivos, ni funciones que ejecuten SQL recibido como texto (QA-E3-1, QAF-4, corregidos);
  - las comillas dobles de un identificador cuentan como separación: no esconden un nombre ni pegan dos palabras (QAF-1, corregido).

  El registro solo valida SQL estático escrito y revisado en el repositorio. No es un analizador de SQL general y no sirve para aceptar SQL de fuentes no confiables.
- **Lector:** solo ejecuta consultas `LECTURA`, que no escriben ni bloquean filas. Una `ESCRITURA` se rechaza sin enviarla e invalida la transacción (QA-E3-3, corregido).
- **Protocolo:** siempre extendido; el servidor rechaza varias sentencias en un envío.
- **Controles en cada operación:** vigencia, dueño y que el lector o ejecutor sea de la transacción actual.
- **Después de un error SQL** no se ejecuta nada más.
- **Estado dudoso:** se descarta la conexión en estos casos:
  - un control externo detectado;
  - una interrupción durante el `BEGIN`;
  - una conexión que no quedó en `IDLE`.
- **El límite del `COMMIT` seguido de un `BEGIN`** (también `COMMIT AND CHAIN`) ya no es alcanzable a través del ejecutor: solo lo impide el registro.

**Límites.** Es una red contra errores de programación, no un analizador de SQL ni una barrera contra código malicioso:
- los atributos privados y la traza de una excepción traducida siguen permitiendo llegar a la conexión;
- ninguna lista es completa;
- la clasificación de `LECTURA` es por texto: una función definida por el usuario podría escribir.

El estado de sesión no se detecta al devolver la conexión. Con Supavisor en modo transacción, además, quedaría en una conexión del servidor que comparten otros clientes. Por eso se previene. Los privilegios de `rma_backend` no lo impiden, porque lo permite PUBLIC (medido en la sección 12.3 del diseño). Las barreras reales son el SQL estático, la revisión y la transacción `READ ONLY` de las lecturas fuera de un comando. Antes de E8 se decide la política mínima de privilegios (misma sección).

## Bloque A (E4 y E5): checkpoints de A2 y A4

A0, A1, A2 y A4 están implementados y aprobados, con QA-A2-H1 y QA-A2-L3. El detalle está en [`e4-e7-diseno-integrado.md`](e4-e7-diseno-integrado.md), secciones 13 y 14.

| # | Etapa | Pendiente |
|---|---|---|
| A2-1 | A4 | Los flujos reales necesitan A4 (recepción y documentos emitidos) antes de llegar al taller. Las pruebas de A1 y A2 usan las Órdenes reales proyectadas. Propuesta: A4 antes que A3 o en paralelo; guardar y releer el flujo completo queda como criterio de A4 |
| A2-2 | B4 | QA-E2-4 en JSON (vincular la unidad de trabajo por constructor) pasa al cableado, junto con QA-E3-4. El repository PostgreSQL ya la recibe por constructor |
| A2-3 | Aprobado | Orden → Cliente → Documento → Equipo → insumos por `clave`. Regla completa en [`e4-e7-diseno-integrado.md`](e4-e7-diseno-integrado.md), sección 13.7 |
| A2-4 | A5 | `test_contrato_ordenes.py` se parametriza con PostgreSQL junto con las consultas dedicadas de E2 |
| A2-5 | B1 | Nombres de operación de la acción del comando. Hoy toma la referencia del primer paso nuevo del historial |
| A2-6 | Aceptado | `cerrada_en` es el `updated_at` del cierre; la versión 1 de una definición registra el alta de la Orden; las versiones históricas creadas de una vez guardan la garantía final |
| A2-7 | Resuelto en A4 | El corpus cubre una garantía RMA de punta a punta, con Detalles de origen |

### Hallazgos de la QA del checkpoint A2

Los identificadores llevan el prefijo `QA-A2-` para no confundirse con M1 a M4 y L1 a L10 de este documento, ni con **H-1** del diseño lógico, que es la regla aprobada sobre el stock negativo.

| # | Etapa | Hallazgo |
|---|---|---|
| QA-A2-H1 | Corregido | `guardar` de una Orden existente sin instantánea perdía actualizaciones. Ahora se rechaza. Contrato en [`e4-e7-diseno-integrado.md`](e4-e7-diseno-integrado.md), sección 13.6 |
| QA-A2-H1 (JSON) | A5 y B4 | JSON no exige esa precondición: guarda una Orden existente sin `obtener_para_modificar`. Al parametrizar `test_contrato_ordenes.py` (A2-4) hay que tratar esa diferencia, y alinearla en B4 |
| QA-A2-L3 | Corregido | Una restricción violada se presentaba como un 409 por datos modificados. Ahora solo es 409 lo concurrente y la unicidad de negocio. Tabla en la sección 13.6 |
| QA-A2-M1 | Antes de A6 | Dos líneas del mismo insumo en `insumos_utilizados`: la API JSON las acepta (0,5 + 0,5 → 200) y PostgreSQL viola `ejecucion_insumo_pkey`. Propuesta: clave primaria `(ejecucion_id, posicion)` |
| QA-A2-M2 | Antes de A5 | Dentro de una transacción de escritura, `obtener` y `listar` corren en READ COMMITTED y pueden mezclar dos instantes de una Orden no bloqueada (reproducido). La garantía QA-E2-1 de `application/bandejas.py` no se cumple en PostgreSQL. Propuesta: una transacción de lectura consistente para las consultas |
| QA-A2-M3 | Antes de E8 | El alta de una Orden ya cerrada viola `orden_cerrada_con_fecha`, porque el `INSERT` no lleva `cerrada_en`. Ningún comando lo hace, pero una importación sí. Propuesta: incluir `cerrada_en` en el `INSERT` |
| QA-A2-M4 | Fotos: resuelto en A4. Insumos: antes de A6 | `FOR UPDATE` después de `KEY SHARE` produce un deadlock (`40P01`, reproducido). El trigger de fotos ya usa `FOR NO KEY UPDATE`. Falta el trigger de movimientos y DI-2, que bloquean el insumo con `FOR UPDATE` mientras `guardar` inserta `ejecucion_insumo`: `FOR NO KEY UPDATE`, o bloquear antes de insertar cualquier fila que los referencie |
| QA-A2-L1 | A5 | Un cliente reutilizado sin DNI cierra su documento vigente compartido, aunque la Orden conserva su copia. Confirmar si es lo buscado. `listar_por_dni_cliente` debe usar la copia de la Orden para coincidir con JSON |
| QA-A2-L2 | Antes de E7 | Una fecha sin zona horaria se relee con zona y deja de ser igual. No se encontró quién las produzca. Validarlo en el dominio o en `guardar` |
| QA-A2-L4 | Sin urgencia | Los Detalles se ordenan por código: `DET-1000` quedaría antes de `DET-999` y fallaría la verificación de prefijo. Solo con más de 999 Detalles en una Orden |
| QA-A2-L5 | E8 | El CHECK `orden_cerrada_con_fecha` se agrega sin `NOT VALID`: en una base con Órdenes cerradas sin fecha, la migración fallaría. DEV y UAT no tienen Órdenes |
| QA-A2-L6 | Corregido | Afirmaciones incorrectas: «formato sin errores» en E3 y A2 (solo valía para los archivos de cada etapa) y el orden de bloqueo en `supabase/README.md` y `diseno-fisico.md` |

### Hallazgos de A4

| # | Etapa | Hallazgo |
|---|---|---|
| A4-1 | Antes de E7 | Un texto con el carácter NUL: JSON lo guarda y PostgreSQL lo rechaza con un 500, sin escribir nada. Vale para cualquier texto. Rechazarlo en la API cambiaría un contrato HTTP: requiere decisión |
| A4-2 | A5 | `generar_comprobante_ingreso` necesita `listar_con_reservas`: el ingreso real de un cliente externo no corre todavía como comando sobre PostgreSQL. Sus datos sí se guardan y releen, por el corpus |
| A4-3 | E8 | Una fila de `salida` de tipo `DEVOLUCION_GESTION_RT` no se puede leer: el dominio no tiene ese valor. Ningún flujo la crea |
| A4-4 | A5 | `documentos.emitidos` y `fotos` se cargan completos con cada Orden, también `contenido`, y `listar` trae todo. Medir junto con las consultas dedicadas |
| A4-5 | Aceptado | Filas sin `posicion` con todas sus fechas idénticas: queda el orden del id, estable pero arbitrario. Sin impacto: esas filas no existen y todo lo que escribe A4 lleva posición |

## Idempotencia (E6)

### M4. Resultado incierto del COMMIT

Si se pierde la conexión durante el `COMMIT`, la unidad de trabajo lanza `PersistenciaError` («no se sabe si se guardó») y la API responde un 500 genérico, igual que cualquier otro fallo interno. El cliente no puede distinguirlo y, sin idempotencia, un reintento puede duplicar la operación.

**Falta.** Un código específico (por ejemplo, `PERSISTENCIA_RESULTADO_INCIERTO`) y su tratamiento con las claves de idempotencia.

## Consultas dedicadas (E2)

Hallazgos del discovery, la implementación y la QA de E2. El detalle está en [`e2-consultas-dedicadas.md`](e2-consultas-dedicadas.md), secciones F, H e I. Ninguno se corrige en E2, salvo F-09 para JSON (QA-E2-1).

| # | Etapa | Hallazgo |
|---|---|---|
| F-03 | E5 o producto | Las evidencias de faltante buscan el id del insumo como subcadena de un texto libre del historial: con ids de cuatro dígitos, `INS-1000` daría evidencias de `INS-100`. Por eso siguen leyendo todas las Órdenes |
| F-04 | E3 (resuelto) | El ejecutor fuerza el protocolo extendido (`binary=True`, validado también a través de Supavisor en M3) y el registro rechaza el SQL de control, de sesión y las funciones con efectos conocidas |
| F-05 | E4 | Con el Cliente compartido, falta decidir qué DNI cuenta en `listar_por_dni_cliente`: el vigente o el de la copia de cada Orden |
| F-06 | E4 | El CHECK de `rma.orden` permite ENTREGADA con `cerrada_en` nulo; `listar_abiertas` depende de que el mapeador lo fije al cerrar |
| F-07 | E5 | «Cerrada implica sin reservas pendientes» no es una invariante explícita. Por eso las reservas se leen de `listar_con_reservas`, no de las abiertas |
| F-08 | Sin etapa | El docstring de `repositories/catalogo_equipos.py` dice que su implementación definitiva es PostgreSQL; el plan aprobado la deja en JSON |
| F-09 | E4 | Las bandejas y el detalle de un insumo leen el repository más de una vez. **Corregido en JSON** (QA-E2-1): las lecturas van dentro de `contexto.transaccion()`. En PostgreSQL, `READ COMMITTED` da un momento distinto a cada sentencia: evaluar transacciones de solo lectura `REPEATABLE READ` para las respuestas que hacen varias consultas |
| F-10 / QA-E2-4 | E3 o E4 | Si una misma instancia del repository JSON se usa con dos unidades de trabajo, vale la última vinculada y el otro contexto falla cerrado (`PersistenciaError`). La aplicación usa una sola. Al introducir la unidad PostgreSQL, vincular por contexto en lugar de mutar un repository compartido |
| QA-E2-5 | E4 | El `default` de `orden.codigo` usa `lpad(…, 6, '0')`, que trunca: 1000000 y 1000001 dan los dos `OR-100000`, mientras JSON genera `OR-1000000`. La restricción única haría fallar el alta. Usar un formato que no trunque |
| QA-E2-6 | Opcional | El control estático de `listar()` reconoce el receptor por nombre (`ordenes`): un alias (`repo = contexto.ordenes`) lo esquiva |
| QA-E2-7 | Pruebas | Con la máquina cargada, una prueba de `tests/postgres` (E1) falló una vez por timeout de conexión del helper de verificación. Pasó 5 de 5 al repetirla. Si se repite, subir el `connect_timeout` de las pruebas |
| QA-E2-8 | Riesgo temporal aceptado (JSON) | Las lecturas coherentes de las bandejas y del detalle de un insumo (QA-E2-1) retienen el lock global de la unidad de trabajo, y la implementación JSON relee todos los archivos en cada consulta. Mientras tanto se bloquean los comandos y las demás lecturas. Referencia medida: con 210 Órdenes, 0,2 s por bandeja y 0,3 s por detalle; con 1010, 1,2 s y 2,0 s. **Alerta provisional:** revisar si el bloqueo supera 500 ms de forma sostenida o los usuarios notan esperas. La mitigación (leer cada archivo una vez por transacción) no se implementa todavía. PostgreSQL lo reemplaza |
| QA-E2-9 | Pruebas | Las pruebas de `tests/test_e2_consistencia_lecturas.py` le dan 0,5 s a la escritura concurrente. Después de la corrección no dan falsos errores, pero bajo carga podrían no detectar una regresión. Mejora: sincronizar con eventos o con un lock instrumentado que avise cuando un hilo queda esperando, para una reproducción determinista |
| QA-E2-10 | E5 (diseño) | El trigger de `rma.movimiento_inventario` cierra reservas con `CONSUMO`, `LIBERACION_RESERVA` y `DESPERDICIO`; el dominio Python (`cantidad_pendiente`) no tiene el tipo `DESPERDICIO`. Antes de implementar en PostgreSQL las consultas de reservas (C5 y el agregado de DE-1), verificar que el criterio del libro coincida con el del dominio. No se cambian reglas ni esquema ahora |
| E3-1 | E8 | La migración de E3 completa `insumo.clave` con el código en las filas anteriores a E3; la carga regenerada fija el id del dominio. En DEV/UAT el catálogo de tipos estaba vacío según M3, pero los insumos no se revisaron. Ver QA-E3-6: la migración no se aplica en un entorno remoto sin una estrategia de identidad verificada |
| E3-2 | Resuelto (diagnóstico) | La lectura breve termina con `ROLLBACK`. Un `COMMIT` sí se distingue: un ajuste de sesión (`set_config(…, false)`) sobrevive al `COMMIT` y se revierte con el `ROLLBACK`, aun en `READ ONLY`. Una prueba lo verifica. El `ROLLBACK` no libera bloqueos advisory de sesión: los impide el registro |
| E3-3 / QA-E3-4 | Antes de conectar el pool a la aplicación (E7 o E9) | El contador que distingue «sin conexión» de «pool agotado» es por unidad de trabajo. Con dos unidades sobre el mismo pool, la QA reprodujo una clasificación incorrecta («sin conexión» con la base disponible). Hoy no es un defecto: la aplicación no crea pools. **Debe resolverse antes de conectar los repositories a un pool compartido**, clasificando con el estado del pool o imponiendo una sola unidad por pool |
| QA-E3-1 | E3 (resuelto) | SQL que pasaba el registro (`UPDATE pg_settings`, `SELECT … INTO TEMP`, `query_to_xml` con el nombre partido, `pg_try_advisory_lock`) dejaba estado en la conexión del pool. El registro los rechaza, y hay pruebas con los ataques y con mutaciones |
| QA-E3-2 | E3 (resuelto) | Dos conexiones ociosas cortadas daban 500. Ahora el segundo corte da 503 `PERSISTENCIA_SIN_CONEXION` y el pool se recupera |
| QA-E3-3 | E3 (resuelto) | El lector podía escribir. La clasificación `LECTURA`/`ESCRITURA` es obligatoria al registrar, y el lector rechaza las escrituras |
| QA-E3-5 | E3 (resuelto) | El generador de cargas descartaba en silencio un insumo previsto con un id inexistente, y la carga podía asociarlo a un insumo ajeno o pisar una identidad. Ahora el generador valida las referencias, la carga asocia por clave y código, solo completa claves provisorias y verifica cada fila de las fuentes |
| QA-E3-6 | E8 (prohibición vigente, con guarda técnica) | El trigger `insumo_clave_por_defecto` acepta altas sin `clave`: una carga que la omita deja el código como identidad del dominio y el error aparece recién al usar el insumo. **Prohibido aplicar la migración de E3 en un entorno remoto sin una estrategia de identidad verificada.** La migración tiene una guarda (QAF-13) y el procedimiento está abajo, en «Procedimiento seguro de la migración de E3» |
| QA-E3-7 | E8 | `db push` no ejecuta las cargas: en DEV/UAT las filas quedarían con `orden = 0` y los usuarios y medios de pago saldrían en orden alfabético. El paso de datos de E8 completa `orden` desde las fuentes y lo verifica |
| QA-E3-8 | E7 o E8 | La equivalencia del orden y del formato numérico con JSON depende de que las fuentes estén ordenadas por el id del dominio y sin ceros de más. En tipos, estaciones y modelos ese id es el código; en insumos e insumos previstos, la `clave` (`INS-001`), no el código comercial (corregido en QAF-10). Hoy se cumple. Antes de E7 o E8: exigirlo al cargar, o agregar `orden` a esos catálogos |
| QAF-1 a QAF-4 | E3 (resueltos) | QA final: (1) las comillas dobles pegadas a una palabra (`ALL"set_config"`) esquivaban el registro; (2) `insert` como alias habilitaba `INTO`, también tras `)` y con `INTO LOCAL` o `GLOBAL TEMP` (variante de la verificación focalizada, corregida antes del commit); (3) una interrupción en la limpieza de un `BEGIN` fallido perdía la conexión; (4) `pg_sleep_for` y `pg_sleep_until` pasaban. Hay pruebas y mutaciones de cada uno |
| QAF-5 | E8 | Las cargas de `supabase/seeds` son inicializadores, no sincronizaciones. Si cambian las fuentes y se vuelven a aplicar, no aplican cambios de atributos ni quitan relaciones o roles, y la verificación puede pasar con la base distinta de las fuentes (por ejemplo, un usuario con dos roles). Antes del paso de datos de E8: una verificación exacta, o una sola carga sobre una base sin esos datos. No se implementa una sincronización en E3 |
| QAF-6 | Antes de cargar catálogos reales | Con una lista de fuentes vacía, el generador produce SQL inválido. Falla al aplicar (42601), no en silencio. Omitir las sentencias de listas vacías |
| QAF-7 | Antes de cargar catálogos reales | El generador no valida los valores de las fuentes: un `activo` ausente se carga como `false` (el dominio toma `true`), un precio con más de dos decimales se redondea sin aviso y un valor ausente da un error poco claro. Validar tipos, `activo` y la precisión monetaria |
| QAF-8 | E3 (resuelto) | El bloque de stock de la carga de desarrollo buscaba el insumo solo por código. Ahora confirma la clave y el código de cada insumo antes de registrar nada, también aplicado sentencia por sentencia |
| QAF-9 | Antes de cargar catálogos reales | Si las fuentes incluyeran `TR-OTROS`, el generador lo aceptaría, JSON lo listaría y PostgreSQL no. Rechazarlo en `validarDesarrollo` |
| QAF-10 | E3 (resuelto) | Documentación: el encabezado huérfano de la sección 11.4 y la condición de orden de QA-E3-8 |
| QAF-11 | E6 o E8 | `orden` vale 0 por defecto: una fila creada después sin `orden` sale antes que las cargadas, mientras JSON la agrega al final. Asignar `orden` al crear, o cambiar el criterio |
| QAF-12 | E8 | Un insumo anterior a E3 con código vacío hace fallar la migración (23514, de forma atómica). Incluirlo en el inventario previo |
| QAF-13 | E8 (guarda vigente) | Riesgo de aplicar la migración de E3 en un entorno remoto antes de tiempo. La migración falla si hay filas en `rma.insumo`, `rma.usuario` o `rma.medio_pago` y la sesión no tiene `rma.migracion_e3 = 'estrategia_identidad_aprobada'`. **Es una guarda operativa, no un control de autorización.** Ver sus límites en el procedimiento de abajo |
| QAF-14 | **Condición de entrada de E4** | Después de un `nextval` legítimo de un comando, `currval` y `lastval` quedan en la sesión del pool y los ve el flujo siguiente. No expone datos. Las secuencias de E4 no deben depender de `currval` ni de `lastval` de una transacción anterior; usar `RETURNING` o el valor devuelto en la misma sentencia |
| E4-MP | **Condición de entrada de E4** | Medios de pago predeterminados sin fila en la base. Con `rma.medio_pago` vacía, `listar_medios_pago` devuelve los predeterminados del dominio (DE3-7), pero no tienen fila, así que un pago no podría referenciarlos por clave foránea. Antes de implementar las operaciones PostgreSQL que guardan pagos, garantizar que todo medio de pago que use el dominio exista como fila referenciable: por ejemplo, exigir la carga de referencia operativa como precondición verificada, o validarla al iniciar. No se resuelve en E3 ni cambia reglas funcionales (antes, QA-E3-L(5)) |
| QA-E3-L | Varias | Observaciones bajas de la QA de E3, no corregidas: (1) la migración cambia `modificado_en` de los insumos anteriores a E3; (2) un dato inválido en la base lanza `ValidationError` y no `PersistenciaError`; (3) un usuario con 0 o 2 roles hace fallar todo `listar_usuarios` (DE3-6, revisar en E6); (4) un stock negativo de las fuentes se carga como 0 (E5); (5) los medios de pago predeterminados sin fila en la base, que pasó a condición de entrada de E4 (E4-MP); (6) el registro rechaza algunos identificadores legítimos, como `lo_que_sea` (falsos positivos aceptados) |

### Procedimiento seguro de la migración de E3 (E8)

`supabase/migrations/20261105000100_e3_catalogos.sql` no se aplica con `db push` sobre una base con datos. Su guarda lo impide (QAF-13): sin la autorización en la sesión, falla antes de cambiar nada. Sobre una base vacía no hace falta autorización.

**Límites de la guarda:**
- Es una protección operativa contra un error, no un control de autorización. La variable de sesión no prueba ninguna aprobación, y cualquiera que la configure la satisface: un `SET`, `PGOPTIONS` u `options=-c` en la conexión, o un `ALTER DATABASE` o `ALTER ROLE … SET`. Estas dos últimas la dejan satisfecha en silencio.
- No reemplaza la aprobación humana del procedimiento.
- Depende de ejecutar el archivo en una única transacción: `db push`, una única consulta, o `psql -v ON_ERROR_STOP=1 --single-transaction`.
- No protege al SQL ejecutado a mano fuera del procedimiento. Con un `psql -f` sin esas opciones, la migración se aplica igual, y una falla posterior deja cambios parciales.

La prohibición sigue vigente: no se aplica en ningún entorno remoto antes de aprobar y verificar la estrategia de identidad. La autorización se pone solo con `set local` dentro del script de abajo, nunca a nivel de base o de rol.

**Condición de desbloqueo (E8):**
- la estrategia de identidad aprobada por escrito;
- un inventario de solo lectura de `rma.insumo`, `rma.usuario` y `rma.medio_pago`, revisado: códigos vacíos (QAF-12), códigos iguales al id del dominio de otro insumo y filas que no están en las fuentes;
- el script de abajo, probado sobre una copia o una base local con los mismos datos.

**Script único, en una transacción** (`psql -v ON_ERROR_STOP=1 --single-transaction`):
1. `set local rma.migracion_e3 = 'estrategia_identidad_aprobada'`.
2. El contenido de la migración.
3. `clave` desde las fuentes, emparejando por código y solo donde `clave = codigo`.
4. `orden` de usuarios y medios de pago (QA-E3-7).
5. La decisión sobre el trigger de `clave`: quitarlo o hacerlo fallar (QA-E3-6).
6. Verificaciones que fallan si algo no coincide: conjuntos y cantidades de `(clave, codigo)`, insumos previstos y `orden`.

Después, registrar la migración con `supabase migration repair --status applied 20261105000100`. El detalle está en la sección 13.3 del diseño de E3.

## Observaciones de severidad baja

| # | Etapa | Observación |
|---|---|---|
| L1 | E3 (resuelto) | `validar_ajustes` rechaza tiempos mayores que 2147483647 ms, esperas y `max_idle` no finitos o no positivos, y un pool de más de 20 conexiones |
| L2 | E3 (resuelto) | Si la base no responde y había lugar en el pool: `PersistenciaSinConexionError` (503 `PERSISTENCIA_SIN_CONEXION`), distinta del pool agotado (503 `PERSISTENCIA_NO_DISPONIBLE`). El texto de la respuesta sigue siendo el genérico de «ocupado»: revisarlo al activar PostgreSQL (E7 o E9) |
| L3 | E3 | Si la transacción se cierra desde otro contexto (por ejemplo, abierta en una dependencia `yield`, lo que está prohibido), el `ValueError` de la `ContextVar` reemplaza al error original. La conexión vuelve al pool igual. |
| L4 | E1 (resuelto) | El diagnóstico de una transacción abortada o sin conexión ya no afirma que «se revirtió todo» (corregido junto con M1). |
| L5 | E3 | Una transacción de otra unidad de trabajo anidada se rechaza antes de entrar y no invalida la exterior. Si la exterior atrapa ese error, confirma lo suyo. Aceptable; falta documentarlo junto con los repositories. |
| L6 | Resuelto (QA-A2-L3) | El 409 `CONFLICTO_CONCURRENTE` ya no le muestra al cliente el SQLSTATE ni el nombre de la restricción, que quedan en el log. Antes los mostraba, nunca datos de filas. Decidir si el nombre de la restricción queda solo en el log. |
| L7 | E3 | Bajo saturación, con `max_waiting` sin límite y 40 hilos de anyio para 4 conexiones, los pedidos que esperan ocupan el threadpool hasta `RMA_DB_POOL_ESPERA_S` cada uno y demoran también a los endpoints que no usan la base. Medir antes de fijar `max_waiting` o el tamaño del pool. |
| L8 | E7 o E9 (en parte) | `cerrar_pool()` existe y está probado; falta conectarlo, junto con la apertura, al `lifespan` de la aplicación cuando se active PostgreSQL |
| L9 | E3 | Pruebas: la de uvicorn demuestra aislamiento y limpieza, pero no distingue `ContextVar` de `threading.local`; el camino del ROLLBACK que falla no tiene prueba en el repo (se verificó a mano en la revisión); `tests/test_unidad_de_trabajo.py` importa funciones auxiliares de `tests/test_fotos_orden.py`. |
| L10 | Sin etapa | Dos instancias de `UnidadDeTrabajoJson` con el mismo lock llevan contadores separados, así que `en_curso()` no coincide entre ellas. Solo ocurre en pruebas: la aplicación usa una sola instancia. |

## Límites del diseño (documentados, no son defectos)

- Un caso de uso síncrono corre en el threadpool de FastAPI. Llamado directamente desde un endpoint `async`, bloquearía el event loop durante cada consulta.
- La transacción no se abre en una dependencia `yield` ni abarca una `StreamingResponse`.
- Un hilo o una tarea creados dentro de una transacción no pueden usarla. Mientras la del padre sigue abierta tampoco pueden abrir otra (`PersistenciaError`): el trabajo con la base que deban hacer va después de que la del padre termine, y entonces abren la suya, con otra conexión del pool.
- `BackgroundTasks` corre después de que la transacción terminó y no la ve.
