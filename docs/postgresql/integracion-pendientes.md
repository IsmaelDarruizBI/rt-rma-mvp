# Integración del backend con PostgreSQL: pendientes

Hallazgos de la revisión independiente de E1 (unidad de trabajo, 03/11/2026) y de su QA final que no bloquean el commit de E1. Cada uno queda asignado a la etapa en que corresponde resolverlo. Ninguno está implementado.

H1 (contextos copiados), M1 (control transaccional externo) y QA-1 (un contexto heredado de una transacción terminada no podía abrir la suya) se corrigieron en E1.

## Antes de usar repositories contra Supabase (E3)

### M3. Validar BEGIN y SET LOCAL contra Supavisor

La unidad de trabajo envía `BEGIN; SET LOCAL lock_timeout = …; SET LOCAL statement_timeout = …` en una sola consulta simple, sobre conexiones `autocommit`. Solo se probó contra PostgreSQL local.

**Falta.** Una prueba autorizada y de solo lectura contra DEV/UAT, a través del pooler en modo transacción: `BEGIN; SET LOCAL …; SHOW lock_timeout; SHOW statement_timeout; ROLLBACK`. Hay que comprobar que los valores se apliquen y que la conexión quede `IDLE` al final.

### M2. Conexiones ociosas cortadas

Si el servidor, el pooler o la red cortan una conexión mientras espera en el pool, el primer comando que la recibe falla en el `BEGIN` con un 500 (por ejemplo, SQLSTATE 57P01), aunque no se haya ejecutado nada. El pool la descarta y el comando siguiente funciona.

**Falta.** Medir contra Supavisor desde Cloud Run, sin cambiar parámetros por suposición, y elegir una de estas opciones:

- `check=ConnectionPool.check_connection`, con una ida y vuelta más por comando (unos 226 ms medidos desde Argentina);
- si el error de conexión ocurre en el `BEGIN`, descartar la conexión y tomar otra una sola vez. No es un reintento de la transacción, porque no se ejecutó nada;
- un `max_idle` menor que el tiempo de corte de la red.

### Interfaz restringida para los repositories (propuesta)

Hoy un repository recibe la `psycopg.Connection` completa (`conexion_actual()`) y podría llamar `commit()` o `rollback()`, o ejecutar `COMMIT`, `ROLLBACK`, `BEGIN` o `SAVEPOINT`. La unidad de trabajo lo detecta al final, salvo un `COMMIT` seguido de un `BEGIN`, pero lo ejecutado pudo quedar confirmado.

Propuesta para E3: los repositories no reciben la conexión, sino un ejecutor de la transacción en curso.

- `ejecutor_actual()` devuelve un objeto con `execute(sql, params)`, `executemany`, `fetchone` y `fetchall`. No expone `commit`, `rollback`, `transaction`, `autocommit` ni la conexión.
- `execute` rechaza el SQL de control transaccional (`BEGIN`, `START TRANSACTION`, `COMMIT`, `END`, `ROLLBACK`, `SAVEPOINT`, `RELEASE`, `PREPARE TRANSACTION`, `SET TRANSACTION`, `SET SESSION`) antes de enviarlo.
- Si un repository necesita un `SET LOCAL`, lo pide a la unidad de trabajo.
- Una prueba estática verifica que ningún módulo de `app/storage/postgres` fuera de `transaccion.py` llame a `commit`, `rollback` o `conexion_actual`.

### Criterios de aceptación obligatorios de E3 (QA final de E1)

Los repositories de E3 no se aceptan sin estos dos requisitos, cada uno con su prueba contra PostgreSQL local.

**QA-2. Estado de sesión.** El ejecutor restringido impide, antes de enviarlos, el control transaccional y los cambios no autorizados del estado de la sesión:

- `COMMIT`, `END` y `ROLLBACK`;
- `BEGIN` y `START TRANSACTION`;
- `SET` sin `LOCAL`, `SET SESSION` y `SET TRANSACTION`;
- `RESET` y `DISCARD`.

Hoy, si un repository los ejecutara, el estado volvería al pool con la conexión. En la QA, un `SET search_path` sin `LOCAL` lo vio la transacción siguiente, y un `commit()` seguido de `autocommit = False` devolvió la conexión con `autocommit` apagado. Falta evaluar, además, descartar la conexión (cerrarla en vez de devolverla) cuando se detecte una violación o un control externo, porque su estado de sesión ya no es confiable.

**QA-3. Conexión retenida.** Los repositories no obtienen ni conservan una `psycopg.Connection`: usan el ejecutor de la transacción en curso. El ejecutor comprueba en **cada** operación SQL que la transacción siga vigente y que la use su dueño (el hilo y la tarea que la abrieron), no solo al entregarlo. Una referencia al ejecutor conservada después del cierre no ejecuta consultas. Hoy, una conexión obtenida con `conexion_actual()` y guardada sigue escribiendo, en autocommit, después de que la transacción terminó.

## Idempotencia (E6)

### M4. Resultado incierto del COMMIT

Si se pierde la conexión durante el `COMMIT`, la unidad de trabajo lanza `PersistenciaError` («no se sabe si se guardó») y la API responde un 500 genérico, igual que cualquier otro fallo interno. El cliente no puede distinguirlo y, sin idempotencia, un reintento puede duplicar la operación.

**Falta.** Un código específico (por ejemplo, `PERSISTENCIA_RESULTADO_INCIERTO`) y su tratamiento con las claves de idempotencia.

## Consultas dedicadas (E2)

Hallazgos del discovery, la implementación y la QA de E2. El detalle está en [`e2-consultas-dedicadas.md`](e2-consultas-dedicadas.md), secciones F, H e I. Ninguno se corrige en E2, salvo F-09 para JSON (QA-E2-1).

| # | Etapa | Hallazgo |
|---|---|---|
| F-03 | E5 o producto | Las evidencias de faltante buscan el id del insumo como subcadena de un texto libre del historial: con ids de cuatro dígitos, `INS-1000` daría evidencias de `INS-100`. Por eso siguen leyendo todas las Órdenes |
| F-04 | E3 | Con parámetros vacíos, psycopg usa el protocolo simple y acepta varias sentencias; `set_config(…, false)` cambia la sesión. El ejecutor restringido fuerza el protocolo extendido (`binary=True`) y revisa su SQL estáticamente |
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

## Observaciones de severidad baja

| # | Etapa | Observación |
|---|---|---|
| L1 | E3 | `ajustes.py` no tiene tope superior: un `RMA_DB_LOCK_TIMEOUT_MS` o `RMA_DB_STATEMENT_TIMEOUT_MS` mayor que 2147483647 pasa la validación, y después todas las transacciones fallan con SQLSTATE 22023. Tampoco rechaza un `RMA_DB_POOL_ESPERA_S` no finito. |
| L2 | E3 | Un rol inexistente o una contraseña incorrecta aparecen como 503 «ocupado» al vencer la espera del pool. La causa solo figura en los avisos del logger `psycopg.pool`. |
| L3 | E3 | Si la transacción se cierra desde otro contexto (por ejemplo, abierta en una dependencia `yield`, lo que está prohibido), el `ValueError` de la `ContextVar` reemplaza al error original. La conexión vuelve al pool igual. |
| L4 | E1 (resuelto) | El diagnóstico de una transacción abortada o sin conexión ya no afirma que «se revirtió todo» (corregido junto con M1). |
| L5 | E3 | Una transacción de otra unidad de trabajo anidada se rechaza antes de entrar y no invalida la exterior. Si la exterior atrapa ese error, confirma lo suyo. Aceptable; falta documentarlo junto con los repositories. |
| L6 | E3 | El 409 `CONFLICTO_CONCURRENTE` le muestra al cliente el SQLSTATE y el nombre de la restricción (por ejemplo `insumo_stock_valido`), nunca datos de filas. Decidir si el nombre de la restricción queda solo en el log. |
| L7 | E3 | Bajo saturación, con `max_waiting` sin límite y 40 hilos de anyio para 4 conexiones, los pedidos que esperan ocupan el threadpool hasta `RMA_DB_POOL_ESPERA_S` cada uno y demoran también a los endpoints que no usan la base. Medir antes de fijar `max_waiting` o el tamaño del pool. |
| L8 | E3 | Abrir el pool al arrancar y cerrarlo (`pool.close()`) al apagar la aplicación. |
| L9 | E3 | Pruebas: la de uvicorn demuestra aislamiento y limpieza, pero no distingue `ContextVar` de `threading.local`; el camino del ROLLBACK que falla no tiene prueba en el repo (se verificó a mano en la revisión); `tests/test_unidad_de_trabajo.py` importa funciones auxiliares de `tests/test_fotos_orden.py`. |
| L10 | Sin etapa | Dos instancias de `UnidadDeTrabajoJson` con el mismo lock llevan contadores separados, así que `en_curso()` no coincide entre ellas. Solo ocurre en pruebas: la aplicación usa una sola instancia. |

## Límites del diseño (documentados, no son defectos)

- Un caso de uso síncrono corre en el threadpool de FastAPI. Llamado directamente desde un endpoint `async`, bloquearía el event loop durante cada consulta.
- La transacción no se abre en una dependencia `yield` ni abarca una `StreamingResponse`.
- Un hilo o una tarea creados dentro de una transacción no pueden usarla. Mientras la del padre sigue abierta tampoco pueden abrir otra (`PersistenciaError`): el trabajo con la base que deban hacer va después de que la del padre termine, y entonces abren la suya, con otra conexión del pool.
- `BackgroundTasks` corre después de que la transacción terminó y no la ve.
