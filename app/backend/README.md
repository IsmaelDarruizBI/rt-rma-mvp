# Backend MVP - Rosario Tecno RMA App

Backend FastAPI del MVP. Convive con el tooling de modelado funcional de
la raiz del repositorio (`business/`, `scripts/`, `generated/`) sin
reemplazarlo: la fuente de verdad funcional sigue siendo `business/`.

Implementa el escenario `HP-REP-001` ("Reparacion estandar de cliente
externo") de `PROC-REP` V1.3, de punta a punta. Los caminos alternativos
del proceso -revision tecnica, overrides, reserva fallida, retrabajo,
cancelacion, origenes distintos de CLIENTE_EXTERNO- **no** estan
implementados: fallan con un error de dominio explicito en vez de
inventar comportamiento.

## Stack

- Python >= 3.11
- FastAPI
- Pydantic v2 (+ pydantic-settings para la configuracion)
- Uvicorn
- Persistencia: JSON sobre el filesystem. **No hay base de datos.**

## Estructura

```text
app/
  main.py         Construye la app, monta el contexto y registra routers
  api/            Routers finos, DTOs y mapeo de errores a HTTP
  application/    Casos de uso: load -> services -> persistir
  domain/
    models/       Modelos Pydantic del dominio (sin FastAPI ni storage)
  services/       Logica de negocio pura, un caso de uso por nodo/tramo
  repositories/   Contratos (Protocol) de acceso a datos
  storage/
    json/         Implementacion JSON con escritura atomica
  core/           Configuracion tecnica transversal
data/
  ordenes/        Ordenes persistidas (una por archivo)
  catalogs/       Catalogos DEMO versionados
tests/            Tests del backend
```

Regla de dependencia: `api -> application -> services -> repositories
<- storage`, y `domain` no depende de ninguna de las otras. `services`
no conoce HTTP ni el formato de persistencia; `storage` puede
reemplazarse sin tocar `domain` ni `services`.

## Instalacion

Desde `app/backend/`:

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # Linux / macOS
pip install -e ".[dev]"
```

## Ejecucion

```bash
uvicorn app.main:app --reload --port 8000 --workers 1
```

- API: http://localhost:8000
- Health: http://localhost:8000/health
- Docs: http://localhost:8000/docs

**Un solo worker, a proposito.** Toda operacion que modifica una Orden o
el stock se protege con un unico lock de proceso (`threading.RLock`,
`app/application/concurrencia.py`) que cubre la seccion critica completa
de cada comando: leer la Orden, validar, aplicar y guardar (incluida la
reserva de `PROC-REP-185`, que lee la disponibilidad global). Por debajo,
el repositorio JSON rechaza con 409 `CONFLICTO_CONCURRENTE` cualquier
version obsoleta de una Orden (su historial persistido tiene que ser un
prefijo del que se guarda) y no sobrescribe una Orden cerrada; las
colisiones transitorias de archivos en Windows se reintentan.

Esa proteccion vale **solo dentro de un proceso**: el lock no es
distribuido, y con varios workers o instancias sobre el mismo directorio
de datos dos pedidos podrian volver a pisarse (el control de version
achica la ventana, pero no es atomico entre procesos). JSON es el
almacenamiento de las pruebas funcionales, no la solucion definitiva para
operar con varias instancias: con una base de datos, la exclusion mutua
debera resolverla el motor de persistencia (transacciones, bloqueo de
fila o control de version en la base).

## Endpoints

Lectura:

```text
GET  /health
GET  /api/orders
GET  /api/orders/{orden_id}
GET  /api/orders/{orden_id}/finances
GET  /api/orders/{orden_id}/custody
GET  /api/orders/{orden_id}/documents
GET  /api/orders/{orden_id}/documents/{documento_id}
GET  /api/orders/{orden_id}/documents/preview/{tipo}
GET  /api/catalogs/repair-types | stations | users | payment-methods
```

Comandos del Happy Path. Cada uno representa UNA intencion de una
persona y arrastra los nodos ACT-SYSTEM que la siguen hasta la proxima
frontera de actor humano:

| Endpoint | Actor | Nodos |
|---|---|---|
| `POST /api/orders` | RECEPCION | 010 → 030 → 040 |
| `POST /api/orders/{id}/details` | RECEPCION | 045 → 070 → 050 → 060 → 080 → 090 → 140 |
| `POST /api/orders/{id}/queue` | COORDINADOR_RMA o RECEPCION | 150 → 170 |
| `POST /api/orders/{id}/take` | TECNICO | 172 → 180 |
| `POST /api/orders/{id}/details/{detalle_id}/start` | TECNICO | 181 → 174 → 185 |
| `POST /api/orders/{id}/executions/{ejecucion_id}/complete` | TECNICO propietario | 190 → 200 → 210 → 211 |
| `POST /api/orders/{id}/control/approve` | RECEPCION | 220 → 230 → 245 → 240 |
| `POST /api/orders/{id}/notify` | RECEPCION | 250 → 260 → 265 [→ 266] |
| `POST /api/orders/{id}/payments` | ADMINISTRADOR, RECEPCION o COORDINADOR_RMA | `ACC-REP-020` [→ 265 \| 266] |
| `POST /api/orders/{id}/deliver` | ADMINISTRADOR o RECEPCION | 280 → 270 → EVT-REP-999 (+ comprobante final y garantia) |

Salidas del proceso (cancelacion y rechazo de control). El motivo es
obligatorio en todas; la Orden se reevalua con el resolver de siempre
(PROC-REP-211):

| Endpoint | Actor | Nodos |
|---|---|---|
| `POST /api/orders/{id}/control/reject` | RECEPCION | 220 → 230 (No) → 235 → 211 [→ 170] |
| `POST /api/orders/{id}/details/{detalle_id}/cancel` | RECEPCION o COORDINADOR_RMA | 300 → 211 |
| `POST /api/orders/{id}/cancel` | RECEPCION o COORDINADOR_RMA | 305 → 211, o 306 sin Detalles |
| `POST /api/orders/{id}/return-equipment` | ADMINISTRADOR o RECEPCION | 270 (devolucion sin reparar, + comprobante) [→ 268] → EVT-REP-999 |

`GET /api/orders/{id}` publica las cancelaciones posibles en
`acciones_cancelacion`, aparte de `acciones_disponibles`. Una Orden
CANCELADA no es ENTREGADA: si el equipo esta en custodia, queda abierta
(`devolucion_pendiente`) hasta registrar su devolucion.

Autorizacion del cliente por Detalle (BR-REP-028/029/037, V1.4 acotada):

| Endpoint | Actor | Nodos |
|---|---|---|
| `POST /api/orders/{id}/authorizations` | RECEPCION | 046 (por Detalle) → 047 [→ 300 \| 305] → 080 → 090 → 140 \| 100 \| 211 |
| `POST /api/orders/{id}/details/{detalle_id}/withdrawal` | RECEPCION | 046 (desiste) → 047 → 300 \| 305 → 211 |
| `POST /api/orders/{id}/withdrawal` | RECEPCION | 046 (rechaza pendientes / desiste de autorizados) → 047 → 305 → 211 |
| `GET /api/orders/{id}/authorizations` | lectura | decision vigente e historia por Detalle |
| `GET /api/orders/authorizations/pending` | lectura | Detalles que esperan decision |

Solo la exige `CLIENTE_EXTERNO` (`PoliticaOrigen.requiere_autorizacion_cliente`);
RT_INTERNO y RMA_GARANTIA_REPARACION siguen igual. Al finalizar la
definicion, los Detalles quedan pendientes y la Orden espera en
PROC-REP-129, sin factibilidad. Recepcion registra, en una operacion, que
Detalles autoriza el cliente y cuales rechaza (canal y observaciones); los
no respondidos no se envian y siguen pendientes sin bloquear a los demas.
Un autorizado pasa a factibilidad; un rechazado se cancela con origen
`RECHAZO_CLIENTE`. La decision queda en `ReparacionDetail.autorizaciones`
(append-only) atada a la version de la definicion: un PROC-REP-127 la deja
sin efecto y la definicion nueva vuelve a estar pendiente. Un Detalle
pendiente no se toma, selecciona, reserva ni ejecuta (409), y la Orden no
llega al control final mientras quede alguno.

Desistimiento: si el cliente ya habia autorizado un trabajo y lo deja sin
efecto antes de que se realice, se registra su desistimiento (motivo
obligatorio): la autorizacion queda en la historia y el Detalle se cancela
con origen `DESISTIMIENTO_CLIENTE`. El desistimiento de todos los trabajos
rechaza lo pendiente, desiste de lo autorizado y conserva lo COMPLETO (que
sigue al control y al cierre); con una Ejecucion activa o reservas sin
conciliar no se aplica nada (409 con los Detalles que lo impiden).
`OrdenOut.desistimiento` muestra de antemano que se cancelaria y que lo
impide.

Compatibilidad: una Orden CLIENTE_EXTERNO guardada antes, sin
`autorizaciones`, sigue cargando; sus Detalles DEFINIDO quedan pendientes
(no se presume ninguna autorizacion) y lo ya ejecutado figura
`SIN_DECISION`. Fuera de alcance: confirmacion tecnica previa
(V1.4 182–184) y reparaciones adicionales del tecnico (128).

Pagos, saldos y devoluciones de dinero (FEAT-REP-007, V1.4 265–268
acotada):

| Endpoint | Actor | Nodos |
|---|---|---|
| `POST /api/orders/{id}/payments` | ADMINISTRADOR, RECEPCION o COORDINADOR_RMA | `ACC-REP-020` [→ 265 \| 266] |
| `POST /api/orders/{id}/payments/{pago_id}/void` | ADMINISTRADOR | `ACC-REP-021` [→ 265 \| 266 \| 268] |
| `POST /api/orders/{id}/refunds` | ADMINISTRADOR o RECEPCION | `ACC-REP-022` [→ 265 \| 268 → EVT-REP-999] |
| `GET /api/orders/{id}/finances` | lectura | saldo, credito, situacion y movimientos |
| `GET /api/catalogs/payment-methods` | lectura | medios de pago activos |

Pago, anulacion y devolucion son acciones funcionales transversales: no
mueven `current_process` por si mismas y dejan traza en el historial.
Despues de cada una, la Orden se reevalua: si esperaba en 265/266 se
vuelve a validar la condicion de entrega; si esta CANCELADA y ya no
espera la devolucion fisica, se verifica el cierre financiero (268). La
logica vive en `services/pagos.py` y `application/finanzas.py`, no en
los endpoints.

- **Saldo** = total de la Orden − pagado vigente + devuelto. Positivo:
  el cliente debe. Cero: saldada. Negativo: credito a favor del cliente
  (`resumen.credito_a_favor`). Importes en `Decimal`, mayores a cero y
  con hasta dos decimales (no se redondean: se rechazan).
- **Pago**: solo en Ordenes cobrables (CLIENTE_EXTERNO), abiertas y no
  CANCELADAS; nunca con saldo ≤ 0 ni por encima del saldo. Antes de
  definir la reparacion se admite una seña sin tope. El tipo (ANTICIPO,
  PARCIAL, FINAL) lo decide el backend. Un reintento con el mismo
  `operacion_id` o una `referencia` ya usada en un pago vigente se
  rechaza (409).
- **Anulacion**: corrige un pago cargado por error; no es una devolucion
  de dinero. Solo ADMINISTRADOR, motivo obligatorio, una sola vez, nunca
  sobre un pago con devoluciones ni en una Orden cerrada. El pago queda
  en la historia con su anulacion y deja de contar como pagado.
- **Devolucion de dinero**: registra dinero efectivamente devuelto,
  vinculado a un pago vigente; motivo, medio, usuario y fecha
  obligatorios; no supera el credito a favor ni lo que queda devolvible
  de ese pago; no toca inventario. Mismas reglas de duplicados que el
  pago.
- **Cierre financiero**: una Orden cobrable se entrega solo con saldo
  cero. Una Orden CANCELADA con credito no llega a EVT-REP-999 hasta
  devolver el dinero; la devolucion fisica y la financiera pueden
  ocurrir en cualquier orden y la Orden sigue CANCELADA. RT_INTERNO y
  RMA_GARANTIA_REPARACION no se cobran ni registran movimientos.

Los medios de pago salen de `data/catalogs/medios_pago.json` (`id`,
`nombre`, `activo`, `admite_devolucion`); si el archivo no existe se
usan EFECTIVO, TRANSFERENCIA, TARJETA_DEBITO, TARJETA_CREDITO y OTRO.
Los roles de anulacion y devolucion son una propuesta del MVP: **negocio
debe validar la politica final**.

Recepcion fisica, custodia, entrega y documentos:

| Endpoint | Actor | Efecto |
|---|---|---|
| `PUT /api/orders/{id}/reception` | RECEPCION o ADMINISTRADOR | `ACC-REP-023`: registra o corrige los datos del ingreso (antes de confirmar) |
| `POST /api/orders/{id}/reception/confirm` | RECEPCION o ADMINISTRADOR | `ACC-REP-024`: el equipo quedo en el local (custodia) |
| `POST /api/orders/{id}/reception/not-received` | RECEPCION o ADMINISTRADOR | `ACC-REP-027`: el equipo nunca ingreso (Orden cancelada, motivo obligatorio) [→ 268 → EVT-REP-999] |
| `POST /api/orders/{id}/reception/notes` | RECEPCION o ADMINISTRADOR | `ACC-REP-025`: observacion complementaria |
| `POST /api/orders/{id}/documents/reception-receipt` | RECEPCION o ADMINISTRADOR | `ACC-REP-026`: version nueva del comprobante de recepcion (con motivo) |

- **Comprobante != custodia.** El comprobante de recepcion es un
  documento; la custodia es una decision explicita, con usuario y fecha:
  se confirma que el equipo esta en el local, o se registra "Equipo no
  recibido" con motivo. Se consultan por separado (`OrdenOut.custodia`):
  ninguno implica al otro y nada se deduce. El estado de custodia es
  derivado (`PENDIENTE_CONFIRMACION`, `SIN_REGISTRO`, `EN_CUSTODIA`,
  `ENTREGADO`, `DEVUELTO`, `NO_RECIBIDO`).
- **Cancelacion y custodia.** Una Orden CANCELADA solo cierra cuando el
  equipo ya no condiciona el cierre (devuelto o "no recibido") y la cuenta
  esta saldada (PROC-REP-268). Con la custodia sin definir queda abierta:
  `OrdenOut.pendientes_de_cierre` dice que falta. "Equipo no recibido" se
  registra una sola vez, solo en una Orden cancelada, y se rechaza si la
  Orden prueba que el equipo estuvo en el local (recepcion confirmada,
  salida registrada, tomas, ejecuciones, revision tecnica o control): ese
  caso se regulariza confirmando la recepcion y devolviendo el equipo.
  Nunca se emite comprobante de devolucion para un equipo no recibido.
- **Datos del ingreso.** El alta (`POST /api/orders`, `.../rt-interno`,
  `.../warranty-rma`) acepta `recepcion` (estado fisico, accesorios,
  observaciones). IMEI y numero de serie son opcionales. Antes de
  confirmar se corrigen (equipo incluido) y cada version anterior queda
  en `recepcion.versiones_anteriores`; confirmada, solo se agregan
  observaciones. Confirmar exige el estado fisico registrado.
- **Entrega.** Exige, despues de la condicion comercial de siempre, la
  custodia confirmada y quien retira (`recibido_por`; DNI u otra
  identificacion opcional). Queda en `orden.entrega` y en la misma
  operacion se emiten el comprobante final y la garantia. La devolucion
  de una Orden CANCELADA exige la custodia confirmada, emite el
  comprobante de devolucion sin reparacion y la Orden sigue CANCELADA.
  RT_INTERNO conserva su circuito: llega y vuelve a Gestion RT sin
  confirmacion de recepcion ni documentos al cliente.
- **Documentos.** Cada emision guarda un snapshot inmutable
  (`documentos.emitidos`): el comprobante de recepcion al pasar por
  PROC-REP-060, y el comprobante final y la garantia al entregar. Una
  version nueva exige motivo y conserva la anterior; volver a emitir el
  mismo contenido devuelve la vigente (un reintento no duplica). La vista
  previa (`.../preview/{tipo}`) no emite ni guarda nada. Los documentos
  de una Orden cerrada se siguen consultando.
- **Garantia.** Un trabajo realizado y aprobado por Detalle, con su
  propio `garantia_dias` (snapshot). Empieza con la entrega efectiva;
  vence el dia local de la entrega + el plazo (`RMA_UTC_OFFSET_HORAS`).
  En una garantia RMA conserva la Orden original y los Detalles
  reclamados. Sin cobros: una Orden no cobrable no muestra importes.
- **Ordenes anteriores.** Sin registro de recepcion no se presume la
  custodia: para entregarlas o devolverlas se regulariza (datos del
  ingreso + confirmacion con una observacion obligatoria, marcada como
  `REGULARIZACION`). Sus marcas de documentos se conservan, sin inventar
  una copia del contenido.

Los roles de recepcion y custodia son una propuesta del MVP: **negocio
debe validar la politica final**.

Errores: `404` no encontrado · `409` precondicion invalida o recurso no
disponible · `422` request mal formado · `500` fallo de infraestructura
(sin filtrar detalle interno).

## Configuracion

Variables de entorno con prefijo `RMA_` (ver `app/core/config.py`):

| Variable | Default |
|---|---|
| `RMA_APP_NAME` | `Rosario Tecno RMA API` |
| `RMA_APP_VERSION` | `0.1.0` |
| `RMA_DATA_DIR` | `app/backend/data` |
| `RMA_CORS_ALLOW_ORIGINS` | `["http://localhost:5173","http://127.0.0.1:5173"]` |
| `RMA_UTC_OFFSET_HORAS` | `-3` (dia local de los vencimientos de garantia) |

`RMA_DATA_DIR` decide donde viven `ordenes/` y `catalogs/`. Los tests
siempre usan `tmp_path`: nunca escriben sobre los catalogos DEMO
versionados.

## Catalogos DEMO

`data/catalogs/` trae datos ficticios para poder probar sin cargar nada:

```text
TR-001    Cambio bateria iPhone 14   precio 80000 · puntaje 10 · garantia 90
INS-001   BAT-IP14 Bateria iPhone 14 · stock_fisico 6
EST-001   Mesa tecnica 1
RECEP-001 · COORD-001 · TECH-001 · ADMIN-001
```

No contienen datos reales ni informacion personal.

Opcional: `empresa.json` (un objeto: `nombre`, `razon_social`, `cuit`,
`direccion`, `telefono`, `email`, `condiciones_garantia`) identifica a la
empresa en los documentos. Sin el archivo figura "Rosario Tecno" sin
condiciones de garantia: el sistema no las inventa.

## Compatibilidad de persistencia del MVP

**Los datos JSON locales del MVP son descartables. No se garantiza
compatibilidad hacia atras para Ordenes persistidas antes de
`mvp-reconcile`.**

Concretamente:

- `HistorialWorkflow` **si** mantiene compatibilidad: acepta el nombre
  historico `process_id` al construirse y al validar JSON, y esas
  entradas se cargan como `PROCESS_NODE`.
- `Pago.tipo_pago` **no** hace backfill automatico y es obligatorio. Una
  Orden guardada antes de esta version, con pagos sin ese campo, falla
  al cargarse.
- No se agrega un default como `tipo_pago = PAGO`: desde el objeto
  `Pago` no se puede inferir si aquel cobro fue un anticipo o el pago
  del cierre, y un default inventado seria trazabilidad falsa.
- Pagos, saldos y devoluciones **si** cargan Ordenes anteriores:
  `referencia`, `operacion_id`, `anulacion` y `resumen_pago.devoluciones`
  tienen default, y el tipo historico `PAGO` sigue aceptandose (los pagos
  nuevos son ANTICIPO, PARCIAL o FINAL).
- Recepcion, custodia y documentos **si** cargan Ordenes anteriores:
  `recepcion`, `entrega` y `documentos.emitidos` tienen default, y una
  `devolucion` sin `tipo` se lee como DEVOLUCION_SIN_REPARACION (era la
  unica posible). La custodia de esas Ordenes queda `SIN_REGISTRO`, y
  un registro sin `no_recibido` sigue pendiente: "no recibido" nunca se
  infiere.
- Para el MVP se espera **recrear o resetear** los datos locales
  generados con versiones anteriores: borrar `data/ordenes/*.json`.
- Esto debera resolverse con migraciones reales cuando exista una
  persistencia estable o una base de datos.

## Tests

```bash
pytest
ruff check .
```

Cubren los modelos de dominio, los services en memoria, las invariantes
(una sola toma activa, una sola ejecucion activa, idempotencia de
`PROC-REP-210`), la autorizacion por actor, la persistencia JSON, el
inventario global y `HP-REP-001` completo en tres niveles: services en
memoria, services contra JSON, y HTTP real con `TestClient`.
