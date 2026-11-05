# E2. Consultas dedicadas: discovery técnico y diseño

**Estado:**
- Diseño aprobado el 05/11/2026, con las decisiones DE-1 a DE-4 autorizadas.
- Implementado sobre JSON (sección H). La QA independiente dio APPROVED WITH OBSERVATIONS.
- QA-E2-1, QA-E2-2 y QA-E2-3 corregidos (sección I). La revisión final dio APPROVED WITH OBSERVATIONS; QA-E2-8 a QA-E2-10 están en `integracion-pendientes.md`.
- **Cerrada el 05/11/2026** con el commit `feat(postgres): implementar consultas dedicadas E2`. `docs/ESTADO_PROYECTO.md` se actualizó en ese cierre.
- Las diferencias con el plan aprobado están en la sección F.

**Base:** rama `feat/postgresql-esquema`, commit `0143373`.

**Evidencia:**
- inventario AST de todas las llamadas a los cuatro contratos de repository en `app/backend/app`;
- lectura de cada sitio;
- dos mediciones sobre la suite JSON completa (1371 passed);
- pruebas puntuales contra PostgreSQL 17 local.

Los scripts de medición quedaron fuera del repositorio.

Las rutas de código son relativas a `app/backend/app/`.

## A. Resumen ejecutivo

**Diagnóstico:**
- **Acceso a Órdenes:** `guardar` se llama 48 veces y `obtener` 13. `listar()` se llama **14 veces en 9 módulos**, como dice el plan.
- **Alcance real de esos 14 `listar()`:** alimentan 21 casos de uso. `cargar_reservas_externas` lo usan 5 comandos y `siguiente_orden_id` lo usan 3 altas.
- **Catálogos:** tienen 49 `obtener_usuario` y 31 listados completos de datos de referencia.
- **Claves de negocio:** las únicas búsquedas son el número de Orden y el DNI. No hay búsquedas por IMEI, número de serie ni equipo: la identidad propia del Equipo (DC20) no está implementada.
- **Filtros:** casi todos dependen de reglas derivadas del dominio (situación operativa, acciones, autorización, reservas pendientes) y no de columnas.

**Principio de diseño:** el repository filtra por datos persistidos y estables; las reglas siguen en los services. Así ningún contrato duplica una regla en SQL ni en `storage/json`, que por la regla de capas no importa `services`.

**Problemas principales:**
1. **Reservas:** cinco comandos, las bandejas y el inventario recorren todas las Órdenes para calcular las reservas pendientes. La revalidación de recursos lo hace una vez por candidata, con costo cuadrático.
2. **Numeración:** el número de Orden se calcula como el máximo más uno sobre todas las Órdenes.
3. **Orden implícito:** el contrato `listar()` no declara un orden, pero la implementación JSON ordena por id y el historial de movimientos depende de ese orden para desempatar fechas iguales.
4. **Defecto latente:** las evidencias de faltante buscan el id del insumo como subcadena de un texto libre del historial.
5. **Riesgos del ejecutor futuro:**
   - con parámetros vacíos, psycopg usa el protocolo simple y acepta `SELECT 1; COMMIT`;
   - `SELECT set_config(..., false)` cambia la sesión y sobrevive al `COMMIT`.

   Los dos se verificaron contra PostgreSQL local.

**Alcance recomendado para E2:**
- siete contratos nuevos en `OrdenReparacionRepository`, implementados en JSON;
- 13 de los 14 `listar()` reemplazados;
- ningún cambio de reglas ni de modelos de dominio;
- contratos documentados para su implementación PostgreSQL en E4 y E5;
- diseño del ejecutor restringido, que se implementa en E3.

Los agregados del libro de inventario y el bloqueo de insumos quedan para E5.

## B. Inventario de accesos

**Categorías:** A puntual · B clave de negocio · C colección filtrada · D existencia o validación · E agregado · F lectura para modificar · G numeración.

**Etapas:** «E2» es el contrato con su implementación JSON. La implementación PostgreSQL va en la etapa indicada entre paréntesis.

### Órdenes: `listar()` (14 sitios)

| ID | Ubicación | Caso de uso | Entidad | Implementación actual | Filtros | Cardinalidad | Modifica | Consistencia | Problema | Contrato propuesto | Etapa |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Q01 | `application/identificadores.py:33` `siguiente_orden_id`. La llaman `ingreso.py:107`, `:141` y `:367` | Alta CLIENTE_EXTERNO, RT_INTERNO y garantía RMA | Números `OR-NNNNNN` | `listar()`, regex y máximo más uno | Ids con patrón `OR-\d+` | Todas | Sí (el alta) | Dentro de la transacción del alta; el lock JSON evita duplicados | Carga todos los agregados para leer ids | `reservar_codigo()` (G) | E2 (E4: `nextval`) |
| Q02 | `application/clientes.py:70` `buscar_cliente_por_dni` | Buscar cliente por DNI (UAT-010) | Cliente embebido en cada Orden | `listar()` y `clientes_con_dni` | `cliente.dni == dni` normalizado | Varias | No | Lectura | Recorre todas las Órdenes | `listar_por_dni_cliente(dni)` (B) | E2 (E4) |
| Q03 | `application/ingreso.py:102` `crear_orden` → `cliente_para_orden` | Alta: no duplicar un cliente por DNI | Ídem | Ídem, dentro de la transacción | Ídem | Varias | Sí | Dentro de la transacción; unicidad hoy por el lock JSON | Ídem; en PostgreSQL necesita restricción única y bloqueo | `listar_por_dni_cliente(dni)` (D) | E2 (E4) |
| Q04 | `application/consultas.py:64` `listar_ordenes` (GET `/orders`) | Listado general con situación y posición por prioridad | Órdenes completas | `listar()`, ordenado por fecha descendente | Ninguno | Todas | No | Lectura | Sin paginación ni proyección | Sigue con `listar()`. **Recorrido legítimo** | Paginar cambia la API: decisión aparte |
| Q05 | `application/autorizacion_cliente.py:272` `pendientes_de_autorizacion` | Bandeja de autorizaciones | Detalles pendientes | `listar()` y `decision_registrable` | La regla exige Orden no cerrada | Varias | No | Lectura | Recorre también las cerradas | `listar_abiertas()` (C) | E2 (E4) |
| Q06 | `application/bandejas.py:194` `_Lectura` | Bandejas de inicio y de taller | Órdenes, situación y faltantes | `listar()`; la situación se deriva por Orden | Reglas de situación y acciones | Varias | No | Lectura | Recorre también las cerradas; las reservas salen de la misma lista | Filas: `listar_abiertas()`. Reservas: `listar_con_reservas()` | E2 (E4/E5) |
| Q07 | `application/fotos.py:121` `limpiar_fotos_huerfanas` | Mantenimiento: fotos sin Orden | Claves de fotos | `listar()` y `fotos_referenciadas` | Ninguno | Todas (incluidas las cerradas) | No (borra en GCS, fuera de la transacción) | Lee las Órdenes después de listar el bucket | Carga los agregados completos para extraer claves | `claves_de_fotos()` (E). **Recorrido legítimo** | E2 (E4) |
| Q08 | `application/inventario.py:91` `consultar_inventario` | Situación de cada insumo | Reservas vigentes | `listar()` y `situacion_inventario` | RESERVA con pendiente | Todas las que tienen reservas | No | Lectura | Recorre todas las Órdenes | `listar_con_reservas()` (E) | E2 (E5: libro de inventario) |
| Q09 | `application/inventario.py:104` `detalle_de_insumo` | Detalle de un insumo: situación, historial y faltantes | Reservas, movimientos y evidencias | `listar()` para las tres consultas | `insumo_id` exacto, salvo las evidencias, que buscan subcadena | Varias | No | Lectura | Las evidencias buscan subcadena en texto libre (F-03) | Situación: `listar_con_reservas([id])`. Historial: `listar_con_movimientos(id)`. Evidencias: siguen con `listar()` | E2 (E5) |
| Q10 | `application/inventario.py:126` `movimientos_de_inventario` | Historial de movimientos | Movimientos de las Órdenes y del catálogo | `listar()` y `historial_movimientos` | `insumo_id` y `tipo` opcionales | Varias | No | Lectura | El desempate de fechas iguales depende del orden por id | `listar_con_movimientos(insumo_id)` (C) | E2 (E5) |
| Q11 | `application/inventario.py:153` `_registrar_movimiento` | Ingreso o ajuste de stock | Reservas de un insumo | `listar()` dentro de la transacción | Ese insumo | Varias | Sí | Disponible coherente con el stock escrito | Recorre todas las Órdenes; en PostgreSQL necesita bloquear el insumo | `listar_con_reservas([insumo_id])` (E) | E2 (E5: `FOR UPDATE` del insumo) |
| Q12 | `application/inventario.py:421` `revalidar_ordenes_pendientes` | Revalidación masiva de recursos | Candidatas | `listar()` fuera de la transacción, y luego relectura por Orden | `_candidata`, que exige no cerrada | Varias | Sí (por Orden) | Se recomprueba cada candidata dentro de su transacción | Cuadrática por Q13 | `listar_abiertas()` (C) | E2 (E4) |
| Q13 | `services/inventario_global.py:115` `cargar_reservas_externas`. La llaman `autorizacion_cliente.py:379`, `ingreso.py:303`, `inventario.py:490`, `recursos.py:101` y `taller.py:179` | Factibilidad, decisión del cliente, reserva 185 e impacto del override | Reservas de las otras Órdenes | `listar()` y `reservas_externas_a` | Excluye la Orden propia | Varias | Sí (salvo `impacto_override`) | Dentro de la transacción del comando | Recorre todas las Órdenes en el camino caliente | `listar_con_reservas()` (E) | E2 (E5: libro y bloqueo de insumos) |
| Q14 | `services/inventario_global.py:244` `_tope_por_override` | Consumo 210 con override P-06 | Ídem | Ídem | Ídem | Varias | Sí | Dentro del 210 | Ídem | `listar_con_reservas()` (E) | E2 (E5) |

### Órdenes: `obtener` (13) y `guardar` (48)

| ID | Ubicación | Caso de uso | Implementación actual | Cardinalidad | Modifica | Consistencia | Observación | Contrato propuesto | Etapa |
|---|---|---|---|---|---|---|---|---|---|
| Q15 | `application/modificacion.py:51` `orden_para_modificar`. La usan **43 comandos** | Toda modificación de una Orden existente | `obtener` dentro de `contexto.transaccion()`, y después `exigir_orden_abierta` | Una | Sí | Lectura para modificar: serializada | Punto único: un reemplazo cubre los 43 | `obtener_para_modificar(id)` (F) | E2 (E4: `FOR UPDATE`) |
| Q16 | `consultas.py:75`, `documentos.py:257`, `:271`, `:285`, `:296`, `fotos.py:152`, `autorizacion_cliente.py:231`, `recursos.py:153` | Lecturas por id | `obtener` | Una | No | Lectura | Correctas | Sin cambio: `obtener` (A) | E4 |
| Q17 | `consultas.py:195`, `documentos.py:81`, `ingreso.py:363` (fuera de la transacción) | Orden origen de una garantía RMA | `obtener` de una Orden ENTREGADA | Una | No | La origen está cerrada y nunca cambia | Leerla fuera de la transacción es seguro; no hay control de reclamos duplicados (BR-REP-019 lo deja pendiente) | Sin cambio (A) | E4 |
| Q18 | `fotos.py:64` `agregar_foto` | Validación previa a subir la imagen | `obtener` fuera de la transacción; se recomprueba dentro | Una | No (la previa) | Comprobación previa y recomprobación | Patrón correcto | Sin cambio (A) | E4 |
| Q19 | 48 `guardar` | Escritura del agregado | Reemplaza el archivo y controla la versión | Una | Sí | Transacción del comando | Fuera de E2 | Guardado por agregado | E4 |

### Catálogos, movimientos de stock, catálogo de Ventas y modelos

| ID | Ubicación | Uso | Cardinalidad | Clasificación | Etapa |
|---|---|---|---|---|---|
| Q20 | `obtener_usuario` (49 sitios) | Actor de cada comando | Una | A, correcto | E3 |
| Q21 | `listar_tipos_reparacion` (4), `listar_insumos` (8), `listar_tipo_reparacion_insumos` (7), `listar_estaciones` (3), `listar_tipo_reparacion_estaciones` (3), `listar_usuarios` (2), `listar_medios_pago` (4) | Datos de referencia para factibilidad, bandejas, documentos y formularios | Todos | Datos de referencia chicos: **recorrido legítimo**. E3 decide si hace falta `insumos_por_ids` | E3 |
| Q22 | `obtener_insumo` (4), `obtener_tipo_reparacion` (2), `obtener_datos_empresa` (1) | Lecturas por id | Una | A | E3 |
| Q23 | `listar_movimientos_stock`: `inventario.py:105` y `:127` (historial), `:162` (duplicados) | Historial y control de reintentos por `operacion_id` o referencia | Todos | Historial: C. Duplicados: **D**. Contrato candidato: `movimientos_stock_coincidentes(operacion_id, insumo_id, tipo)`, con la regla y el mensaje en el service | E3 (E5: bloqueo) |
| Q24 | `actualizar_stock_insumo` (2) y `registrar_movimiento_stock` (1) | Escrituras de stock | — | Escritura | E5 |
| Q25 | `catalogo_equipos`: `listar_productos` (3), `listar_sincronizaciones`, `obtener_producto`, `registrar_sincronizacion` (2), `aplicar_sincronizacion` | Copia del catálogo de Ventas | Todos o uno | Sigue en JSON en los dos modos (plan aprobado) | Fuera del plan (F-08) |
| Q26 | `modelos_equipo`: `listar_modelos` y `obtener_modelo` | Catálogo técnico | Todos o uno | Referencia | E3 (`rma.modelo_equipo`) |

### Mediciones que respaldan los prefiltros

Cada medición compara, en cada llamada real de la suite completa, el resultado sobre todas las Órdenes con el resultado sobre el subconjunto propuesto:

| Comparación | Llamadas | Diferencias |
|---|---|---|
| `bandejas_de_inicio` con solo las abiertas | 50 | 0 |
| `bandejas_de_taller` con solo las abiertas | 20 | 0 |
| `reservas_activas_globales` con solo las abiertas | 1019 | 0 |
| `reservas_vigentes_por_insumo` con solo las abiertas | 143 | 0 |
| `reservas_activas_globales` con solo las Órdenes con algún RESERVA | 1003 | 0 |
| `reservas_vigentes_por_insumo`, ídem | 129 | 0 |
| `evidencias_de_faltante` con solo las Órdenes con movimientos del insumo | 10 | 0 |
| `fotos_referenciadas` con solo las Órdenes con fotos | 2 | 0 |

**Lo que se toma de cada medición:**
- **Reservas («solo las Órdenes con algún RESERVA»):** equivalen **por construcción**, porque una Orden sin RESERVA no aporta nada al cálculo. La medición lo confirma.
- **Bandejas («solo las abiertas»):** equivalen por el código. Una Orden cerrada solo ofrece `INICIAR_GARANTIA_RMA` (`acciones.py:307`), que no está en ninguna bandeja, y su situación `CERRADA` no figura en ningún criterio.
- **Reservas («solo las abiertas»):** **no** equivalen por construcción. No hay una regla explícita «cerrada implica sin reservas», solo una invariante derivada del flujo. Por eso las reservas salen de `listar_con_reservas()` y no de las abiertas.
- **Evidencias («solo las Órdenes con movimientos del insumo»):** **no** se adopta. La coincidencia por subcadena (F-03) puede encontrar evidencias en Órdenes sin movimientos de ese insumo, así que el prefiltro cambiaría el resultado.

## C. Contratos propuestos

Los siete métodos se agregan a `OrdenReparacionRepository` (`repositories/ordenes.py`). Devuelven los mismos tipos de dominio que hoy consumen los services, que no cambian. Las proyecciones más livianas se deciden cuando exista una implementación PostgreSQL que medir.

**Reglas comunes:**
- **Orden:** el de cada contrato. Las listas van por número de Orden ascendente, el mismo orden de `listar()` JSON (`storage/json/ordenes.py:117`). En PostgreSQL: `ORDER BY codigo COLLATE "C"`, para que coincida con el orden de Python.
- **Errores:** los de persistencia (`PersistenciaError`), igual que hoy. Ningún contrato traduce reglas de dominio.
- **Paginación:** ninguna. Ninguna consulta actual pagina, y paginar cambiaría respuestas de la API.

### C1. `obtener_para_modificar(orden_id: str) -> OrdenReparacion` (F)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Cargar la Orden que el comando va a modificar, con la garantía de que nadie más la modifica hasta el final de la transacción |
| Precondición | Una transacción vigente de la unidad de trabajo. Sin ella: `PersistenciaError` («fuera de una transacción»), nunca una lectura sin protección |
| Sin resultados | `EntidadPersistidaNoEncontradaError`, igual que `obtener` |
| No hace | No verifica que la Orden esté abierta: `exigir_orden_abierta` sigue en `orden_para_modificar`, con el mismo orden de rechazos (409 `ORDEN_CERRADA`) |
| JSON (E2) | Igual que `obtener`. La exclusión ya la da el lock de proceso que retiene la transacción. Verifica la precondición con un `en_transaccion: Callable[[], bool]` que inyecta el contexto (decisión DE-2) |
| PostgreSQL (E4) | `SELECT … FROM rma.orden WHERE codigo = %s FOR UPDATE` y la carga del agregado. Si conviene `FOR NO KEY UPDATE`, se decide en E4 |
| Reemplaza | `modificacion.py:51`, que cubre a los 43 comandos |

### C2. `reservar_codigo() -> str` (G)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Devolver el número de una Orden nueva (`OR-NNNNNN`, seis dígitos). Es el número de negocio, distinto de los ids técnicos (`uuid` en PostgreSQL; `nuevo_id(...)` para tomas, pagos o fotos) |
| Precondición | Una transacción vigente. El que llama guarda la Orden con ese número dentro de la misma transacción |
| Garantía | Nunca devuelve un número ya guardado. **No** garantiza correlatividad: en PostgreSQL un alta revertida deja un hueco (D-5, aceptado). En JSON no hay huecos porque no se reserva nada: es el máximo más uno en el momento de la llamada |
| Concurrencia | JSON: el lock de proceso serializa las altas. PostgreSQL (E4): `nextval('rma.orden_numero_seq')`, sin bloqueo |
| Regla vigente que conserva | Se ignoran los ids que no siguen el patrón (`identificadores.py:29`) |
| JSON (E2) | El mismo algoritmo de hoy, sobre los ids persistidos |
| Reemplaza | `siguiente_orden_id`, que queda como envoltura del contrato para no tocar sus tres llamadores ni su export |
| Riesgos para E4 | La secuencia tiene que quedar por encima del máximo existente al migrar datos (`setval`). Hay que decidir si el `default` de `orden.codigo` convive con el código explícito |

### C3. `listar_abiertas() -> list[OrdenReparacion]` (C)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Las Órdenes que todavía admiten trabajo: `not orden.esta_cerrada`. Es decir, ni ENTREGADA ni en `EVT-REP-999`. **Las CANCELADAS están incluidas** porque no están cerradas |
| Orden | Número de Orden ascendente |
| Sin resultados | Lista vacía |
| Consistencia | Lectura del momento. Quien modifica después recomprueba dentro de la transacción, como hace la revalidación |
| PostgreSQL (E4) | `WHERE cerrada_en IS NULL`, con el índice parcial `orden_estado`. Solo equivale si el mapeador de E4 fija `cerrada_en` exactamente cuando `esta_cerrada` pasa a verdadero; el CHECK actual permite ENTREGADA con `cerrada_en` nulo (F-06) |
| Reemplaza | Q05, Q06 (filas) y Q12 |

### C4. `listar_por_dni_cliente(dni: str) -> list[OrdenReparacion]` (B, D)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Las Órdenes cuyo cliente tiene exactamente ese DNI ya normalizado. El que llama normaliza (`normalizar_dni`), como hoy |
| Orden y sin resultados | Número de Orden ascendente; lista vacía |
| No hace | No agrupa por cliente ni elige el más reciente: lo sigue haciendo `clientes_con_dni`, sin cambios |
| Consistencia | En el alta (Q03), dentro de la transacción. JSON: unicidad por el lock. PostgreSQL (E4): restricción única `documento_cliente_numero_unico` y bloqueo del Cliente |
| PostgreSQL (E4) | Búsqueda por `documento_cliente.numero_normalizado`. **Queda abierta la semántica** (F-05): JSON compara la copia del cliente de cada Orden; con el Cliente compartido (D-12) hay que decidir si cuenta el DNI vigente del Cliente o el de la copia histórica |
| Reemplaza | Q02 y Q03. En Q03, solo si `cliente.dni` no es nulo, igual que hoy |

### C5. `listar_con_reservas(insumo_ids: Collection[str] | None = None) -> list[OrdenReparacion]` (E)

| Aspecto | Definición |
|---|---|
| Responsabilidad | **Conjunto candidato** (corregido por QA-E2-2). Garantiza que incluye toda Orden con alguna `RESERVA` pendiente (de esos insumos, si se indican) y que no incluye ninguna Orden sin `RESERVA`. Puede incluir Órdenes cuyas reservas ya se consumieron o liberaron. La regla de reserva pendiente sigue en `services/inventario.cantidad_pendiente`, nunca en el repository |
| Orden y sin resultados | Número de Orden ascendente; lista vacía |
| Parámetros inválidos | `insumo_ids` como `str` lanza `ValueError` (QA-E2-3) |
| Equivalencia | Por construcción: las Órdenes que la implementación puede omitir no tienen reservas pendientes, así que no aportan nada a `reservas_activas_globales`, `reservas_vigentes_por_insumo` ni `reservas_externas_a` |
| Implementaciones | JSON devuelve el conjunto más amplio (toda Orden con alguna `RESERVA`). PostgreSQL puede limitarse a las que tienen reservas pendientes según el libro de inventario, sin traer el historial completo |
| Consistencia | Dentro de la transacción del comando. El bloqueo de insumos para que la disponibilidad no cambie hasta el commit es de E5 (`FOR UPDATE` ordenado por id) |
| PostgreSQL (E5) | Desde el libro `movimiento_inventario`. E5 podrá reemplazarlo por el agregado `stock_reservado` (decisión DE-1) |
| Reemplaza | Q06 (reservas de las bandejas), Q08, Q09 (situación), Q11, Q13 y Q14. En `services/inventario_global.py` cambian dos llamadas, no la regla |

### C6. `listar_con_movimientos(insumo_id: str | None = None) -> list[OrdenReparacion]` (C)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Las Órdenes con al menos un movimiento de insumo (de ese insumo, si se indica) |
| Orden | Número de Orden ascendente. **Es parte del contrato:** `historial_movimientos` desempata fechas iguales por el orden de llegada |
| Equivalencia | Por construcción: `historial_movimientos` solo recorre `movimientos_insumo` y filtra por igualdad exacta |
| PostgreSQL (E5) | Desde `movimiento_inventario` |
| Reemplaza | Q09 (historial) y Q10. **No** reemplaza las evidencias de faltante (F-03) |

### C7. `claves_de_fotos() -> frozenset[str]` (E)

| Aspecto | Definición |
|---|---|
| Responsabilidad | Las claves de objeto de todas las fotos registradas en cualquier Orden, incluidas las cerradas. Extrae datos; no aplica ninguna regla |
| Sin resultados | Conjunto vacío |
| Consistencia | La de hoy: se lee después de listar el bucket. Una foto registrada en el medio cuenta como usada |
| PostgreSQL (E4) | `SELECT objeto FROM rma.foto` |
| Reemplaza | Q07. `fotos_referenciadas` deja de usarse en ese camino |

### `listar()` se conserva

Lo usan el listado general (Q04), las evidencias de faltante (Q09) y siete llamadas de las pruebas (`tests/`). Su docstring tiene que declarar el orden por número de Orden, del que ya dependen los consumidores.

### Por categoría: qué se resuelve ahora y qué se difiere

| Categoría | Ahora (E2) | Se difiere |
|---|---|---|
| A. Puntual | Nada: `obtener` es correcto | La carga eficiente del agregado (E4) |
| B. Clave de negocio | DNI (C4) | IMEI y serie: no existen en el producto (DC20) |
| C. Colecciones filtradas | C3 y C6 | Paginación y proyecciones del listado general (decisión DE-3) |
| D. Existencia y validación | Unicidad del DNI en el alta (C4) | Duplicados de movimientos de stock (Q23, E3); restricciones únicas en PostgreSQL (E4) |
| E. Agregadas | Prefiltros C5 y C7 | Agregados del libro de inventario y `stock_reservado` (E5) |
| F. Lectura para modificar | Contrato C1 y su precondición | `FOR UPDATE` (E4); bloqueo de insumos (E5) |
| G. Numeración | Contrato C2 | `nextval` y `setval` de la migración (E4) |

## D. Ejecutor SQL restringido (diseño para E3)

**Objetivo:** que un repository PostgreSQL no pueda controlar la transacción, alterar la sesión ni usar una transacción ajena o terminada. Cubre QA-2 y QA-3 y cierra el límite conocido del `COMMIT` seguido de un `BEGIN`.

### API

```python
class EjecutorSql(Protocol):
    def filas(self, sql: Consulta, parametros: Parametros) -> list[Fila]: ...
    def fila(self, sql: Consulta, parametros: Parametros) -> Fila | None: ...
    def ejecutar(self, sql: Consulta, parametros: Parametros) -> int: ...  # filas afectadas
    def ejecutar_lote(self, sql: Consulta, lotes: Iterable[Parametros]) -> None: ...
```

- **Tipos:** `Consulta` es SQL estático (`LiteralString` o `psycopg.sql.SQL`), `Parametros` es una tupla o un diccionario, y `Fila` es una fila materializada.
- **Obtención:** `unidad.ejecutor()`. Queda atado al `_EnCurso` vigente en ese momento.
- **Lo que no tiene:** `commit`, `rollback`, `transaction`, `autocommit`, `cursor` ni ningún atributo que devuelva la conexión.
- **`conexion_actual()`:** deja de ser pública en E3.
- **Resultados materializados:** `Fila` es una tupla con nombre o un diccionario. Nunca se devuelve un cursor, porque `cursor.connection` expondría la conexión.

### Controles en cada operación (QA-3)

1. Que exista transacción: si no, `PersistenciaError`.
2. Que el `_EnCurso` actual de la `ContextVar` sea **el mismo objeto** al que se ató el ejecutor. Si no, se rechaza: es un ejecutor guardado de otra transacción, aunque sea del mismo flujo.
3. `estado.activa` y `estado.problema() is None`: vigencia y dueño (hilo y tarea), como en E1.
4. Si la conexión está `INERROR` o `estado.invalidada` es verdadero: `TransaccionInvalidadaError` («la transacción ya falló; no se ejecuta nada más»), sin ir al servidor.
5. Si la operación falla: se marca `estado.invalidada = True` y se lanza el error traducido. Así, aunque el error se atrape, la unidad de trabajo revierte, que es lo que ya hace con un error SQL atrapado.

### Restricción del SQL (QA-2), por capas

| Capa | Qué impide | Límite |
|---|---|---|
| Protocolo extendido forzado: toda ejecución lleva `binary=True` | El servidor rechaza más de una sentencia por envío («cannot insert multiple commands into a prepared statement»). Verificado: con `()` y sin `binary`, `SELECT 1; COMMIT` **se acepta**; con `binary=True`, se rechaza. No crea sentencias preparadas (`pg_prepared_statements = 0`) | Hay que validarlo a través de Supavisor (con M3) y revisar los tipos en binario |
| Lista permitida del primer token, después de quitar comentarios y espacios: `SELECT`, `WITH`, `INSERT`, `UPDATE`, `DELETE` | Rechaza `BEGIN`, `START`, `COMMIT`, `END`, `ROLLBACK`, `ABORT`, `SAVEPOINT`, `RELEASE`, `PREPARE`, `SET` (con o sin `SESSION`, `TRANSACTION` o `LOCAL`), `RESET`, `DISCARD`, `LOCK`, `CALL`, `DO`, `COPY`, `LISTEN` y el resto | Es una lista permitida, no prohibida. No ve dentro de un `SELECT` |
| SQL estático: constantes de módulo (`LiteralString` o `psycopg.sql.SQL`), nunca texto armado con datos | Inyección y SQL dinámico | Python no lo hace cumplir en tiempo de ejecución: lo verifica un análisis estático |
| Prueba estática sobre las constantes SQL de `storage/postgres` | Funciones con efecto de sesión dentro de un `SELECT`: `set_config(…, false)`, `pg_advisory_lock` (de sesión), `dblink`, `lo_*`. Verificado: `SELECT set_config('search_path', 'pg_catalog', false)` sobrevive al `COMMIT` | Ninguna lista de palabras dentro del texto es completa: es una red, no una barrera |
| Privilegios del rol `rma_api` | La barrera real contra lo que el código no debería hacer (DDL, extensiones) | No impide los `SET` de sesión, que cualquier rol puede hacer |
| Descarte de la conexión ante una violación detectada | Una conexión con estado dudoso no vuelve al pool (QA-2) | Con Supavisor en modo transacción, un `SET` de sesión puede afectar a otro cliente del pooler. Por eso importan las capas anteriores |

**Conclusión:** el ejecutor es una barrera contra errores de programación, no contra código malicioso. Las barreras efectivas son el protocolo extendido, el SQL estático, la revisión y el rol de la base.

### Pruebas de aceptación (E3)

1. Cada sentencia de control o de sesión se rechaza antes de llegar al servidor, también en minúsculas, con comentarios delante (`/* x */ COMMIT`, `-- x\nCOMMIT`) o entre paréntesis.
2. `SELECT 1; COMMIT`, con y sin parámetros, falla y no termina la transacción.
3. Se permiten `SELECT`, `WITH`, `INSERT`, `UPDATE`, `DELETE` y `SELECT … FOR UPDATE`.
4. Ejecutor sin transacción, después del cierre, en un contexto copiado (hilo o tarea) y guardado de una transacción anterior del mismo flujo: los cuatro se rechazan.
5. Después de un error SQL atrapado, la siguiente operación lanza `TransaccionInvalidadaError` sin ir al servidor, y la unidad de trabajo revierte todo.
6. Ningún resultado expone la conexión: no hay cursores y las filas son materializadas.
7. Prueba estática: fuera de `transaccion.py`, ningún módulo de `storage/postgres` usa `conexion_actual`, `commit`, `rollback`, `_conexion` ni las funciones de sesión de la lista.
8. Regresión: las reproducciones R1, R2, R2b y QA-1 pasan, y R1 es imposible a través del ejecutor.
9. Los tipos con `binary=True` (`int`, `Decimal`, `datetime`, `text`, `uuid`, `jsonb`) coinciden con los del protocolo de texto.

## E. Plan de implementación de E2

**Orden recomendado (cada paso deja la suite en verde):**
1. **Contratos.** Agregar los siete métodos a `repositories/ordenes.py`, con su docstring (orden, sin resultados, precondiciones), y declarar el orden de `listar()`.
2. **Implementación JSON** en `storage/json/ordenes.py`. Los filtros son de datos persistidos: `esta_cerrada`, `cliente.dni`, tipo e insumo de los movimientos, claves de fotos. Se agrega la inyección de `en_transaccion` (DE-2) en `application/contexto.py`.
3. **Pruebas de contrato** (`tests/test_ordenes_repository_contrato.py`), parametrizadas por implementación, para que E4 y E5 agreguen PostgreSQL sin reescribirlas.
4. **Reemplazo sitio por sitio**, cada uno con su prueba de equivalencia:
   - C2 (`identificadores.py`);
   - C1 (`modificacion.py`);
   - C4 (`clientes.py` e `ingreso.py`);
   - C3 (`autorizacion_cliente.py`, `inventario.py` y `bandejas.py`);
   - C5 (`services/inventario_global.py`, `bandejas.py` e `inventario.py`);
   - C6 (`inventario.py`);
   - C7 (`fotos.py`).
5. **Prueba estática:** fuera de `consultas.listar_ordenes` y de las evidencias de faltante, nadie en `application/` ni en `services/` llama `ordenes.listar()`.
6. **Documentación:** `docs/ESTADO_PROYECTO.md`, `docs/postgresql/integracion-pendientes.md` (F-03 a F-06) y el índice de `docs/postgresql/README.md`.

**Archivos que se modifican:**
- `repositories/ordenes.py`, `storage/json/ordenes.py` y `application/contexto.py`;
- en `application/`: `identificadores.py`, `modificacion.py`, `clientes.py`, `ingreso.py`, `autorizacion_cliente.py`, `bandejas.py`, `inventario.py` y `fotos.py`;
- `services/inventario_global.py`, solo dos llamadas;
- las pruebas nuevas;
- la documentación.

**No se tocan:** modelos de dominio, reglas de services, JSON persistido, API, frontend, `storage/postgres` ni el esquema.

**Dependencias:**
- E1, ya hecha, para la precondición de transacción.
- No depende de E3 ni de E4. Las implementaciones PostgreSQL de C1 a C7 se escriben en E4 y E5 contra las mismas pruebas de contrato.

**Verificaciones de cada paso:**
- `pytest`, con la suite completa sin cambiar expectativas;
- `ruff check`;
- las pruebas de equivalencia;
- `tests/postgres`, porque la unidad de trabajo no debe cambiar;
- `npm run validate:all`, si se tocan los documentos de trazabilidad (no debería hacer falta).

## F. Riesgos y decisiones

### Decisiones existentes que este diseño respeta

- **Plan aprobado:**
  - E2 reemplaza los `listar()` y define `reservar_codigo()` y `obtener_para_modificar()`, implementados en JSON;
  - `listar()` se conserva para pruebas y exportación;
  - la numeración admite huecos (D-5);
  - el Cliente es compartido, con una copia histórica (D-12).
- **E1:** la transacción se abre en la capa de aplicación; los repositories no la controlan (QA-2) ni retienen la conexión (QA-3).
- **Constitución:** capas `application → services → repositories ← storage`, y ninguna regla funcional nueva.

### Diferencias con el plan versionado (requieren aprobación)

- **DE-1. `stock_disponible(insumo_ids, bloquear)` no se define en E2.**
  - El plan lo ponía en E2, implementado en JSON con «el cálculo global actual». Ese cálculo vive en `services`, que `storage/json` no puede importar, y repetirlo en `storage` duplicaría la regla de reserva pendiente en un tercer lugar (también está en los triggers de PostgreSQL).
  - `bloquear` no tiene sentido sin la base.
  - Propuesta: `listar_con_reservas` en E2, y el agregado con bloqueo en E5, donde existen el libro y los bloqueos de insumos.
- **DE-2. La precondición de transacción se verifica también en JSON,** con un `en_transaccion` inyectado por el contexto, para que los dos modos fallen igual. La alternativa es verificarla solo en la capa de aplicación, que ya abre la transacción.
- **DE-3. El listado general (GET `/orders`) sigue sin paginar.** Paginarlo cambia la respuesta de la API y requiere una decisión de producto.
- **DE-4. E2 no mejora el rendimiento de JSON:** la implementación sigue leyendo todos los archivos. El objetivo es fijar los contratos; la eficiencia llega con PostgreSQL.
- **El texto completo del plan no está en el repositorio.** `ESTADO_PROYECTO.md` resume las etapas, pero no los cambios de contrato de su §2.2. Este documento los recoge para E2.

### Propuestas nuevas

- **Principio:** el repository filtra por datos persistidos y las reglas quedan en los services.
- **Los siete contratos C1 a C7.**
- **Orden explícito por número de Orden,** con `COLLATE "C"` en PostgreSQL.
- **Diseño del ejecutor restringido:** protocolo extendido forzado, lista permitida, SQL estático, ejecutor atado a su `_EnCurso` e invalidación tras un error.

### Hallazgos registrados (no se corrigen en E2)

| # | Hallazgo | Severidad | Etapa |
|---|---|---|---|
| F-01 | El contrato `listar()` no declara su orden, pero los consumidores dependen del orden por id | Baja | E2: documentarlo |
| F-02 | Revalidación masiva cuadrática: `cargar_reservas_externas` relee todas las Órdenes por candidata | Baja | E2 la mitiga con C5; E5 la resuelve |
| F-03 | `evidencias_de_faltante` busca el id del insumo como **subcadena** de un texto libre: con ids de cuatro dígitos, `INS-1000` encontraría evidencias de `INS-100`. Hoy los ids tienen tres dígitos (`INS-001`) | Media, latente | Producto o E5: faltante como evento estructurado. E2 no cambia el comportamiento |
| F-04 | Con parámetros vacíos, psycopg usa el protocolo simple y acepta varias sentencias por envío; `set_config(…, false)` dentro de un `SELECT` cambia la sesión. El ejecutor de E3 tiene que forzar el protocolo extendido (`binary=True`) y revisar estáticamente su SQL (sección D) | Alta para E3 | E3 |
| F-05 | Con el Cliente compartido, no está decidido qué DNI cuenta: el vigente o el de la copia de cada Orden | Media | E4 |
| F-06 | El CHECK de `rma.orden` permite ENTREGADA con `cerrada_en` nulo; `listar_abiertas` en PostgreSQL depende de que el mapeador lo fije | Media | E4 |
| F-07 | La invariante «cerrada implica sin reservas pendientes» no es explícita (se deriva del flujo) | Baja | Prueba de invariante, opcional, en E5 |
| F-08 | El docstring de `repositories/catalogo_equipos.py` dice que su implementación definitiva es PostgreSQL; el plan aprobado lo deja en JSON | Baja | Aclarar fuera de E2 |

### Riesgos diferidos

- E4: `FOR UPDATE`, `nextval` y `setval`, F-05 y F-06.
- E5: agregados del libro, bloqueo de insumos ordenado por id, F-03 y F-07.
- E3: ejecutor (F-04), M2, M3 y Q23.
- E6: M4.
- Latencia: la carga del agregado por cada Orden de una lista (C3 a C6) puede ser cara con Supabase en otra región. Se mide en E8; si hace falta, se agregan proyecciones con su propia aprobación.

## G. Criterios de aceptación de E2

1. Los siete contratos están en `OrdenReparacionRepository`, con docstrings que declaran orden, resultado vacío, precondiciones y errores. `listar()` declara su orden.
2. La implementación JSON pasa las pruebas de contrato, que cubren:
   - resultados, orden por número y vacíos;
   - Órdenes cerradas y canceladas;
   - Órdenes sin cliente (RT_INTERNO) y con DNI nulo;
   - ids fuera de patrón para `reservar_codigo`, y la primera Orden (`OR-000001`).
3. `obtener_para_modificar` y `reservar_codigo` fuera de una transacción lanzan `PersistenciaError` y no leen nada.
4. Dos altas simultáneas reciben números distintos y no duplican un cliente por DNI. Son pruebas de concurrencia JSON con hilos.
5. Cada sitio reemplazado tiene una prueba de equivalencia: el resultado nuevo es idéntico al de `listar()` más el filtro anterior, sobre fixtures con Órdenes abiertas, cerradas, canceladas, con reservas consumidas, liberadas y pendientes, y con fotos.
6. Solo `consultas.listar_ordenes` y las evidencias de faltante usan `ordenes.listar()` en `application/` y `services/`. Lo verifica una prueba estática.
7. La suite JSON completa pasa **sin cambios de expectativas**, `tests/postgres` sigue en verde y `ruff check` no reporta errores.
8. No cambian los modelos de dominio, las reglas de los services, el JSON persistido, la API ni el frontend. El diff no toca `storage/postgres` ni `supabase/`.
9. `docs/ESTADO_PROYECTO.md` y `integracion-pendientes.md` están actualizados, con F-03 a F-08 asignados.
10. La revisión independiente de E2 da APPROVED o APPROVED WITH OBSERVATIONS.

## H. Implementación (05/11/2026)

Implementada sobre JSON, sin commit, para la QA independiente. PostgreSQL sigue deshabilitado: `RMA_PERSISTENCIA=postgres` detiene el arranque igual que antes.

### Contratos implementados

| Contrato | Implementación JSON (`storage/json/ordenes.py`) |
|---|---|
| C1 `obtener_para_modificar` | Exige la transacción vinculada y después hace lo mismo que `obtener` |
| C2 `reservar_codigo` | Exige la transacción; máximo de los ids `OR-\d+` más uno, a seis dígitos. Es el algoritmo de siempre, trasladado de `application/identificadores.py` |
| C3 `listar_abiertas` | `not orden.esta_cerrada` |
| C4 `listar_por_dni_cliente` | `orden.cliente.dni == dni`; omite las Órdenes sin cliente. `dni=None` lanza `ValueError` |
| C5 `listar_con_reservas` | Algún movimiento `RESERVA`, de los insumos indicados si los hay: el conjunto candidato más amplio. Un `str` como `insumo_ids` lanza `ValueError` |
| C6 `listar_con_movimientos` | Algún movimiento de insumo, comparado por igualdad exacta |
| C7 `claves_de_fotos` | `frozenset` de `foto.objeto` de todas las Órdenes |

**Formato del número de Orden.** El prefijo (`PREFIJO_CODIGO_ORDEN`) y la cantidad de dígitos (`DIGITOS_CODIGO_ORDEN`) quedan definidos en `repositories/ordenes.py`, para que `storage` no importe `application`. `siguiente_orden_id` delega en `reservar_codigo`, así que sus tres llamadores no cambian.

**Precondición de transacción (DE-2).**
- El repository JSON recibe `en_transaccion` en su constructor o con `exigir_transaccion_con`.
- `ApplicationContext.__post_init__` le vincula `unidad_de_trabajo.en_curso`. Así cubre todo contexto: el de `construir_contexto` y los que arman las pruebas.
- Sin vínculo, el repository falla cerrado: lanza `PersistenciaError` y no lee nada.
- La transacción de otra unidad u otro hilo no cuenta.
- Ese vínculo no forma parte del Protocol: es cableado propio de JSON. PostgreSQL usará su propia unidad de trabajo.

### Accesos reemplazados (13 de 14)

| ID | Sitio | Ahora usa |
|---|---|---|
| Q01 | `identificadores.siguiente_orden_id` | `reservar_codigo()` |
| Q02 | `clientes.buscar_cliente_por_dni` | `listar_por_dni_cliente(dni)` |
| Q03 | `ingreso.crear_orden` | `listar_por_dni_cliente(cliente.dni)`, o nada si el DNI es nulo (antes `cliente_para_orden` tampoco comparaba) |
| Q05 | `autorizacion_cliente.pendientes_de_autorizacion` | `listar_abiertas()` |
| Q06 | `bandejas._Lectura` | Filas: `listar_abiertas()`. Faltantes e insumos negativos: `listar_con_reservas()` |
| Q07 | `fotos.limpiar_fotos_huerfanas` | `claves_de_fotos()`, dentro de la misma transacción de antes |
| Q08 | `inventario.consultar_inventario` | `listar_con_reservas()` |
| Q09 | `inventario.detalle_de_insumo` | Situación: `listar_con_reservas([id])`. Historial: `listar_con_movimientos(id)`. Evidencias: **siguen con `listar()`** (F-03) |
| Q10 | `inventario.movimientos_de_inventario` | `listar_con_movimientos(insumo_id)` |
| Q11 | `inventario._registrar_movimiento` | `listar_con_reservas([insumo_id])` |
| Q12 | `inventario.revalidar_ordenes_pendientes` | `listar_abiertas()` |
| Q13 | `services/inventario_global.cargar_reservas_externas` | `listar_con_reservas()` |
| Q14 | `services/inventario_global._tope_por_override` | `listar_con_reservas()` |
| Q15 | `modificacion.orden_para_modificar` | `obtener_para_modificar()` (cubre los 43 comandos) |

`consultas.listar_ordenes` (Q04, `GET /orders`) sigue con `listar()`, sin cambios (DE-3).

### Pruebas añadidas

- **`tests/test_contrato_ordenes.py`** (17 pruebas). Se parametrizan por implementación con `IMPLEMENTACIONES`: hoy JSON; E4 y E5 agregan PostgreSQL. Cubren:
  - conjuntos vacíos, un único resultado, varios resultados y el orden por número;
  - Órdenes abiertas, canceladas, entregadas y RT cerradas por `EVT-REP-999`;
  - DNI exacto, DNI nulo, Órdenes sin cliente y dos clientes con el mismo DNI;
  - `RESERVA` pendiente y consumida, consumo sin reserva, una cerrada con reserva y el filtro por insumos (vacío e inexistente);
  - movimientos con igualdad exacta (`INS-1` frente a `INS-10`);
  - fotos de Órdenes abiertas y cerradas;
  - numeración con ids fuera de patrón;
  - precondiciones dentro y fuera de la transacción, y la transacción de otro hilo;
  - altas concurrentes y lecturas para modificar concurrentes.

  Se agregan tres pruebas propias de JSON: la numeración exacta (máximo más uno), el repository sin vínculo y el vínculo que hace el contexto.
- **`tests/test_e2_equivalencia.py`** (24 pruebas).
  - **Corpus:** se arma por la API y tiene seis Órdenes: una con la reserva pendiente, una consumida y entregada, una cancelada, dos del mismo cliente con DNI y una sin DNI, más dos fotos.
  - **Comparación:** cada caso de uso de Q01 a Q15 se ejecuta con el repository real y con uno de referencia que responde cada consulta dedicada con `listar()`, como antes de E2. Los que escriben (Q03, Q11, Q12 y el alta) se comparan sobre dos copias del directorio.
  - **Control estático:** en `application/`, `services/` y `api/`, solo `consultas.listar_ordenes` e `inventario.detalle_de_insumo` (por las evidencias, F-03) llaman `ordenes.listar()`.
- **Sensibilidad de las pruebas:**
  - Las 8 mutaciones del repository JSON se detectan: abiertas sin canceladas, `RESERVA` cambiado por `CONSUMO`, DNI que nunca coincide, fotos solo de abiertas, número máximo más dos, sin exigir la transacción, movimientos por subcadena y listas sin ordenar.
  - Las dos pruebas de concurrencia fallan en 5 de 5 corridas contra una unidad sin exclusión mutua.

### Surgido en la implementación

- **F-09.** Las bandejas y el detalle de un insumo leen el repository más de una vez. La QA lo confirmó como regresión (QA-E2-1) y **está corregido para JSON**: ver «Correcciones posteriores a la QA». En PostgreSQL queda pendiente para E4.
- **F-10 (baja).** Si una misma instancia del repository JSON se usa en dos contextos con unidades de trabajo distintas, vale la última vinculada. La aplicación usa una sola unidad (`UNIDAD_DE_TRABAJO_JSON`).
- **Criterio 9 de la sección G.** Pediste no tocar `docs/ESTADO_PROYECTO.md` hasta el cierre posterior a la QA, así que no se actualizó. Los hallazgos F-03 a F-10 se registraron en `integracion-pendientes.md`.

### Pendientes por etapa

- **E3:**
  - el ejecutor restringido (sección D, QA-2, QA-3 y F-04);
  - M2 y M3;
  - los duplicados de movimientos de stock (Q23);
  - `conexion_actual()` deja de ser público.
- **E4:**
  - C1 con `FOR UPDATE`;
  - C2 con `nextval` y `setval` de la migración;
  - C3 con `cerrada_en` (F-06);
  - C4 con la semántica del DNI (F-05);
  - C7 desde `rma.foto`;
  - un snapshot consistente para las respuestas que hacen varias consultas (F-09): evaluar transacciones de solo lectura `REPEATABLE READ`, porque en `READ COMMITTED` cada sentencia ve su propio momento;
  - el formato del número de Orden por encima de 999999 (QA-E2-5).
- **E5:**
  - C5 y C6 desde el libro `movimiento_inventario`. C5 puede limitarse a las Órdenes con reservas pendientes (QA-E2-2);
  - `stock_disponible` agregado con bloqueo de insumos (DE-1);
  - F-03 (faltante como dato estructurado) y F-07.
- **E6:** M4.

### Resultados de la validación (05/11/2026)

| Verificación | Resultado |
|---|---|
| Suite JSON completa | 1412 passed, 49 skipped: las 1371 anteriores sin cambios de expectativas, más las 41 nuevas. Las 49 omitidas son las de PostgreSQL sin la base local |
| PostgreSQL 17 local: `tests/postgres`, unidad de trabajo, errores, concurrencia JSON, contrato y equivalencia | 161 passed en tres corridas, sin bases sobrantes |
| `ruff check` y formato de los 14 archivos tocados | Sin errores |
| `npm run validate:all` | Pasa |

## I. Correcciones posteriores a la QA (05/11/2026)

La QA independiente dio APPROVED WITH OBSERVATIONS, condicionado a QA-E2-1 y QA-E2-2. También se autorizó QA-E2-3.

### QA-E2-1: lecturas coherentes dentro de una respuesta

- **Qué cambió.** `bandejas._Lectura` y `inventario.detalle_de_insumo` hacen todas sus lecturas (Órdenes y catálogos) dentro de `with contexto.transaccion():`. Con JSON, el lock de la unidad de trabajo impide que una escritura se meta entre ellas, así que cada Orden se ve en una sola versión.
- **Qué queda igual.**
  - Solo hay lecturas dentro: el cálculo de situaciones, faltantes e historial sigue afuera, y no hay llamadas externas.
  - El orden de los locks es el de siempre: primero el de la unidad de trabajo y después el de archivos.
  - Las respuestas y los errores no cambian; por ejemplo, un insumo inexistente sigue dando 404.
- **Los demás casos de uso de E2.**
  - Ninguno vuelve a leer la misma Orden fuera de una transacción. Los que escriben (alta, ingresos y ajustes, comandos con reservas externas, limpieza de fotos) ya leen dentro de su transacción, y la revalidación vuelve a comprobar cada candidata.
  - `consultar_inventario` y `movimientos_de_inventario` combinan una lectura del catálogo con una de Órdenes, igual que antes de E2. Una escritura en el medio puede desfasar el stock físico de las reservas, pero ninguna Orden aparece dos veces. No es una regresión de E2 y no se cambió.
- **PostgreSQL (E4).** En `READ COMMITTED`, cada sentencia ve su propio momento: hay que evaluar transacciones de solo lectura `REPEATABLE READ` para estas respuestas.

### QA-E2-2: `listar_con_reservas` como conjunto candidato

- **El contrato pasa a garantizar dos cosas:**
  - incluye toda Orden con alguna reserva pendiente;
  - no incluye ninguna Orden sin `RESERVA`.

  Las Órdenes con reservas cerradas quedan a elección de la implementación.
- **JSON no cambia:** sigue devolviendo toda Orden con alguna `RESERVA`.
- **PostgreSQL** puede limitarse a las pendientes del libro de inventario, sin traer el historial completo al camino de los cinco comandos, las bandejas y el inventario.
- **La regla** de reserva pendiente sigue solo en los services.

### QA-E2-3: parámetros inválidos

| Llamada | Antes | Ahora |
|---|---|---|
| `listar_con_reservas("INS-001")` | `[]` en silencio (se tomaba letra por letra) | `ValueError` |
| `listar_por_dni_cliente(None)` | Los clientes sin DNI (en SQL no habría dado ninguno) | `ValueError` |

`ValueError` es la convención del almacenamiento para argumentos inválidos (`storage/fotos.py`, `storage/postgres/conexion.py`). Ningún caller actual hace estas llamadas, y la API no cambia.

### Pruebas de las correcciones

| Prueba | Antes de corregir | Después |
|---|---|---|
| `tests/test_e2_consistencia_lecturas.py` (2 pruebas: detalle de insumo y bandeja, con una escritura desde otro hilo justo después de la primera lectura) | **Las 2 fallan**: la reserva aparece vigente junto al consumo que la cierra, y la Orden en dos versiones | Las 2 pasan: la escritura espera al lock y termina bien después de la respuesta |
| `test_con_reservas_es_un_conjunto_candidato` y `test_con_reservas_alcanza_para_los_calculos_de_reservas` (7 filtros de insumos cada una) | La prueba anterior exigía el conjunto exacto | Pasan: verifican las garantías mínimas y que las reservas calculadas sobre las candidatas sean las mismas que sobre todas las Órdenes |
| `test_json_devuelve_toda_orden_con_alguna_reserva` | — | Fija la elección de JSON (el resultado de antes) sin restringir a PostgreSQL |
| `test_un_insumo_suelto_como_str_se_rechaza` y `test_buscar_por_dni_none_se_rechaza` | Fallan sin la validación | Pasan |

**Mutaciones de la implementación JSON:**
- **Solo las Órdenes con reservas pendientes** (lo que podría hacer PostgreSQL): pasan todas las pruebas portables, y solo falla la prueba propia de JSON.
- **Excluir una Orden cerrada con una reserva pendiente:** falla.
- **Incluir Órdenes sin `RESERVA`:** falla.
- **Sin cada una de las dos validaciones:** falla su prueba.

### Pendientes registrados, sin corregir

QA-E2-4 a QA-E2-7 quedan en `integracion-pendientes.md`, junto con F-03 a F-10.

### Resultados después de las correcciones (05/11/2026)

| Verificación | Resultado |
|---|---|
| Suite JSON completa | 1430 passed, 49 skipped (las de PostgreSQL sin la base local), 0 failed. Las 1371 anteriores siguen sin cambios de expectativas |
| PostgreSQL 17 local: `tests/postgres`, unidad de trabajo, errores, concurrencia, contrato, consistencia y equivalencia | 179 passed en tres corridas, sin bases sobrantes |
| Prueba diferencial contra el código anterior a E2 (56 pedidos HTTP sobre el mismo corpus) | 54 idénticos byte a byte; 0 diferencias después de normalizar ids aleatorios y fechas |
| `ruff check` y `npm run validate:all` | Sin errores; pasa |
