# Business Process Discovery

Esta carpeta documenta el proceso de descubrimiento y modelado de negocio,
la primera etapa de la trazabilidad E2E descrita en el
[README principal](../../README.md).

## Alcance de esta etapa

- Definir procesos de negocio en YAML (`business/processes/`).
- Definir actores (`business/actors/`).
- Definir reglas de negocio (`business/rules/`).
- Validar la forma de los procesos contra un JSON Schema
  (`business/schemas/process.schema.json`).
- Generar automaticamente una visualizacion Mermaid de cada proceso.

## Fuera de alcance en esta etapa

- Desarrollo de la aplicacion (frontend, backend, base de datos).
- Modelo de datos tecnico.
- Requerimientos funcionales o tecnicos formales.
- Trazabilidad automatizada (ver [traceability/README.md](../../traceability/README.md)).

## Como se agrega un proceso nuevo

1. Crear el archivo YAML en `business/processes/`.
2. Seguir la estructura de `repair-management.yaml` (proceso, nodes, edges).
3. Ejecutar `npm run validate` para validarlo contra
   `business/schemas/process.schema.json`.
4. Ejecutar `npm run generate:mermaid` para producir el diagrama.

`repair-management.yaml` contiene actualmente la V1.2 (approved) del
proceso de Gestion de Ordenes de Reparacion de Rosario Tecno: Business
Process validado con negocio. Esta version constituye la baseline
funcional aprobada para iniciar la siguiente etapa del proyecto, y con
ella **queda cerrada la etapa de Business Process Discovery & Modeling
para esta baseline**. Sobre la V1.1, incorpora la validacion de Estacion
de Trabajo al momento de tomar una Orden (ver "Estaciones de Trabajo" mas
abajo). Ver "Estados conceptuales V1.2", "Estaciones de Trabajo",
"Procesos adicionales descubiertos" y "Pendientes" mas abajo.

La aprobacion es documental (estado del proceso) y no resuelve por si sola
los pendientes funcionales ya identificados (ver "Pendientes" mas abajo):
siguen abiertos exactamente igual que antes de la aprobacion. Cualquier
cambio funcional posterior -incluida la resolucion de esos pendientes-
debera generar una nueva revision del proceso (por ejemplo V1.3), no una
modificacion silenciosa de esta V1.2 aprobada.

## Estados conceptuales V1.2

Propuesta de estados de la Orden de Reparacion, tal como surge del modelado
del proceso (no son todavia un modelo de datos formal). La V1.2 no agrega
estados nuevos respecto de la V1.1: agrega una validacion (Estacion de
Trabajo) antes de poder tomar una Orden EN_COLA, sin cambiar la lista de
estados:

- REQUERIMIENTO
- EN_REVISION — la reparacion requerida todavia no esta definida.
- PENDIENTE_RECURSOS
- HABILITADA
- EN_COLA
- EN_REPARACION — con modo EXCLUSIVA / ABIERTA.
- PENDIENTE_CONTROL
- REPARACION_LISTA
- ENTREGADA
- CANCELADA — estado confirmado, reglas de transicion pendientes de
  definicion (quien puede cancelar, desde que estados, por que motivos).

No se incluye CERRADA (el flujo V1.2 no tiene un paso de cierre adicional).

TERCERIZADA sigue pendiente de definir si sera un estado: ver pendientes.

El comprobante de recepcion se genera para los origenes que lo requieren
(CLIENTE_EXTERNO, RT_GARANTIA_VENTA, RMA_GARANTIA_REPARACION)
independientemente de si la reparacion ya se conoce o la Orden esta
EN_REVISION; RT_INTERNO no lo requiere. El puntaje de una reparacion ya
puede calcularse una vez aprobado el control tecnico; su distribucion entre
multiples tecnicos sigue pendiente (ver Pendientes).

## Resultado de la Orden: SIN_REPARACION

SIN_REPARACION es un **resultado** de la Orden de Reparacion, no un
reemplazo de sus estados (en particular, no reemplaza a ENTREGADA: una
Orden SIN_REPARACION igualmente puede llegar a ENTREGADA, conservando el
resultado SIN_REPARACION). La estructura tecnica definitiva de estado vs.
resultado todavia no esta diseñada.

No equivale a CANCELADA:

- CANCELADA: la Orden fue interrumpida o cancelada.
- SIN_REPARACION: la Orden fue procesada correctamente hasta su fin, pero
  concluyo sin que se realizara una reparacion.

El primer camino implementado hacia SIN_REPARACION es: luego de una
revision tecnica (PROC-REP-065) sobre una Orden EN_REVISION, no se logra
determinar que reparacion necesita el equipo (PROC-REP-068 = No). En el
futuro, otros caminos podrian converger en este mismo resultado; por ahora
son solo posibles extensiones, sin implementar:

- El cliente decide no continuar.
- La reparacion resulta tecnicamente no realizable.
- El presupuesto no es aceptado por el cliente.
- Falta de recursos y decision de no continuar.

## Estaciones de Trabajo

Concepto incorporado en la V1.2 para poder validar, al tomar una Orden de
Reparacion, desde que Estacion de Trabajo se esta operando. Es
documentacion funcional para esta etapa: no define todavia tablas,
columnas ni endpoints.

- Las estaciones son configurables desde la futura aplicacion; el sistema
  no debe asumir una cantidad fija de estaciones. Actualmente existen 4
  estaciones fisicas (3 operativas y 1 no operativa), pero eso no es una
  restriccion del sistema.
- Una estacion puede estar OPERATIVA o NO OPERATIVA.
- Una estacion tiene identificador, nombre, estado operativa/no operativa,
  una o mas computadoras asociadas, y los tipos de reparacion que esta
  habilitada para realizar.
- Cada computadora utilizada en RMA puede estar asociada a una Estacion de
  Trabajo. La asociacion Computadora → Estacion es configurable en la
  aplicacion; no se modela dentro del flujo de Orden de Reparacion, sino
  como funcionalidad de soporte/configuracion.
- La relacion Estacion ↔ Tipo de reparacion es configurable y
  many-to-many: una estacion puede aceptar distintos tipos de reparacion.
- Sesion del tecnico (precondicion del proceso de Orden de Reparacion, no
  modelada como nodos del flujo principal): el tecnico inicia sesion, el
  sistema identifica la computadora utilizada, obtiene la estacion
  configurada para esa computadora y el tecnico confirma la estacion
  detectada; la sesion activa queda asociada a Tecnico + Estacion. Un
  tecnico no pertenece de forma permanente a una estacion: puede trabajar
  en distintas estaciones en distintos momentos.
- Cuando un tecnico toma una Orden de Reparacion (PROC-REP-180) queda
  trazada tambien la estacion utilizada, incluso cuando distintos
  tecnicos continuan la misma Orden desde distintas estaciones.

La administracion completa de estaciones (alta, baja, configuracion de
computadoras y de tipos de reparacion habilitados) sera una funcionalidad
de configuracion de la aplicacion, fuera del flujo principal de Orden de
Reparacion.

### Validaciones antes de tomar una Orden (PROC-REP-172 a PROC-REP-180)

Cuando un tecnico intenta tomar una Orden EN_COLA, las validaciones se
aplican en esta secuencia, y solo se llega a autoasignar la Orden si se
supera cada paso:

1. Validar sesion + estacion: el tecnico tiene sesion activa, esa sesion
   tiene una Estacion de Trabajo asociada/confirmada, y esa estacion esta
   configurada. Si falta cualquiera de estas tres cosas, la Orden no se
   autoasigna, no hay override posible, y la Orden permanece EN_COLA.
2. Validar operatividad: la estacion debe estar OPERATIVA. Una estacion
   NO OPERATIVA tampoco admite override: la Orden permanece EN_COLA.
3. Validar compatibilidad con el tipo de reparacion: solo se evalua una
   vez superados los dos pasos anteriores. Si la estacion (operativa) no
   esta configurada para el tipo de reparacion requerido, el sistema
   advierte la incompatibilidad y, recien alli, permite el override de un
   usuario autorizado (ver BR-REP-011); si no se autoriza, la Orden
   permanece EN_COLA.
4. Recien entonces se autoasigna la Orden (PROC-REP-180): pasa a
   EN_REPARACION y queda registrada la estacion utilizada.

## Procesos adicionales descubiertos

Durante el modelado de la V1.2 se identificaron los siguientes procesos,
relacionados con el dominio RMA:

- Gestion de Ordenes de Compra de repuestos.
- Gestion de Ordenes de Venta mayorista de repuestos.

Estos procesos **no forman parte** del Business Process de Gestion de
Ordenes de Reparacion V1.2 y no se modelan ni desarrollan en esta etapa.
Se modelaran a futuro como procesos de negocio independientes, cada uno
con su propio YAML bajo `business/processes/`.

## Pendientes

Puntos identificados durante el modelado de la V1.2 que quedan pendientes de
validacion funcional con el negocio antes de incorporarse al proceso:

- Flujo completo de tercerizacion.
- Definir si TERCERIZADA es un estado.
- Presupuesto y aprobacion de cliente externo.
- Flujo de SCRAP.
- Flujo de devolucion a proveedor.
- Modelo definitivo de reproceso (reabrir misma OR, crear nueva OR
  relacionada, registrar evento de reproceso, o un modelo combinado). La
  unica relacion confirmada por ahora es que RMA_GARANTIA_REPARACION genera
  una nueva Orden relacionada con la Orden original.
- Reglas de garantia RMA configurable.
- Override de garantia vencida.
- Distribucion de puntos entre multiples tecnicos.
- Catalogo definitivo de prioridades.
- Estado terminal definitivo de RT_INTERNO.
- Reglas de CANCELADA: quien, cuando y motivo.
- Actor/regla que define el modo EXCLUSIVA / ABIERTA de EN_REPARACION.

---

# PROC-REP V1.3 (draft)

Todo lo anterior de este documento describe **V1.2 (approved)**, que
permanece intacta como baseline historica
(`business/processes/repair-management.yaml`,
`business/rules/business-rules.yaml`). Esta seccion documenta **V1.3
(draft)**, una revision funcional independiente
(`business/processes/repair-management-v1.3.yaml`,
`business/rules/business-rules-v1.3.yaml`) que convive con V1.2 sin
reemplazarla todavia. Las 7 Features actuales siguen derivadas de V1.2 y
no fueron tocadas en esta iteracion.

## Cambio central: Orden con 1..N Detalles

La Orden de Reparacion deja de asumir una unica reparacion. Pasa a tener
1..N Detalles de Reparacion (unidad tecnica de trabajo), cada uno con su
propio Tipo de Reparacion, precio snapshot, Ejecuciones e Insumos:

```text
OrdenReparacion (unidad de gestion)
  -> DetalleReparacion (unidad tecnica de trabajo, 1..N por Orden)
      -> Ejecucion (1..N por Detalle; maximo una activa por Orden)
      -> Insumo utilizado -> MovimientoInventario
```

El tecnico toma la Orden completa (igual que V1.2) y luego selecciona un
Detalle para trabajar. Reemplaza el modo EXCLUSIVA/ABIERTA de V1.2 por
una regla mas simple: como maximo una Ejecucion activa por Orden en todo
momento, porque la Orden representa un unico equipo fisico (BR-REP-007
V1.3).

## Toma y liberacion de Orden (participacion activa)

Una Orden corresponde a un unico equipo fisico. Cuando un tecnico toma
una Orden (PROC-REP-180), toma la Orden COMPLETA, no solamente un
Detalle: existe como concepto funcional una toma/participacion activa
(Orden + tecnico + estacion + fecha/hora de inicio). Como maximo puede
existir UNA toma activa por Orden en simultaneo (BR-REP-018 V1.3) -esto
es distinto pero complementario de BR-REP-007 (maximo una Ejecucion
activa por Orden)-.

```text
Tecnico toma OR
  -> queda registrada una participacion activa (Orden + tecnico + estacion + inicio)
  -> selecciona Detalle (PROC-REP-181)
  -> inicia Ejecucion, trabaja, completa/interrumpe
  -> resolver recalcula (PROC-REP-211)
```

Si el resolver determina que sigue existiendo al menos un Detalle
trabajable y la Orden continua tomada por el tecnico actual, se pregunta
explicitamente (PROC-REP-212): **¿el tecnico desea continuar trabajando
esta Orden?**

- **Si** -> mantiene la toma activa y vuelve a seleccionar Detalle
  (PROC-REP-181).
- **No** -> PROC-REP-213 "Liberar Orden de Reparacion": cierra la
  participacion activa (fecha/hora de fin), la Orden vuelve a EN_COLA
  (PROC-REP-170), y otro tecnico -o el mismo- puede tomarla nuevamente
  pasando otra vez por PROC-REP-172/PROC-REP-180.

No se libera automaticamente una Orden trabajable solo porque termino un
Detalle: la decision de continuar o liberar es siempre una accion
explicita del tecnico. Distinto es el caso en que ya no queda ningun
Detalle trabajable porque la Orden quedo COMPLETA, PENDIENTE_RECURSOS,
REQUIERE_REVISION o TODO_CANCELADO: alli no se ofrece "continuar con otro
Detalle", y la participacion activa se cierra automaticamente (no hay
nada mas que preguntar).

El historial completo de participaciones (quien tomo la Orden, cuando,
desde que estacion, cuando la libero) se conserva siempre; nunca se
sobrescribe. Este historial es la base sobre la que, a futuro, podra
construirse reporting por tecnico (ver "Pendientes especificos de V1.3").

## Resolver de estado de Orden

El estado tecnico agregado de la Orden nunca se fija manualmente: se
calcula siempre a partir de propiedades derivadas de sus Detalles
(BR-REP-012), mediante una politica de reglas ordenada por prioridad,
pensada para poder ampliarse (nueva condicion + prioridad + resultado +
referencia a Business Rule) sin reescribir nodos del proceso.

Propiedades derivadas de cada Detalle (estado tecnico: PENDIENTE /
EN_PROCESO / COMPLETO / CANCELADO; condicion/bloqueo separada y
extensible: SIN_BLOQUEO / REQUIERE_DEFINICION / BLOQUEADO_POR_RECURSOS):

```text
es_terminal            = esta_completo OR esta_cancelado
es_trabajable           = PENDIENTE AND SIN_BLOQUEO AND tiene Tipo definido
esta_en_ejecucion       = EN_PROCESO
requiere_revision       = PENDIENTE AND REQUIERE_DEFINICION
bloqueado_por_recursos  = PENDIENTE AND BLOQUEADO_POR_RECURSOS
esta_completo           = COMPLETO
esta_cancelado          = CANCELADO
```

Matriz de prioridad (primera regla coincidente gana):

| Prioridad | Condicion | Resultado agregado |
|---|---|---|
| 0 | `cantidad_detalles = 0` (BR-REP-013) | `SIN_DETALLES` -unico resultado posible, deterministico; nunca "REQUERIMIENTO o EN_REVISION segun contexto" (ver mas abajo por que esa formulacion anterior era ambigua y como se corrigio)- |
| 1 | Todos terminales Y todos CANCELADO | `TODO_CANCELADO` -> Orden CANCELADA |
| 2 | Todos terminales Y existe >=1 COMPLETO | `COMPLETA` -> habilita Control Tecnico (incluye el caso "algunos CANCELADO + al menos uno COMPLETO", por ejemplo tras cancelar los Detalles no terminales de la Orden) |
| 3 | Existe una Ejecucion activa | `EN_EJECUCION` |
| 4 | Existe >=1 Detalle `es_trabajable` | `ABIERTA_TRABAJABLE` |
| 5 | Ninguno trabajable Y existe >=1 `requiere_revision` | `REQUIERE_REVISION` |
| 6 | Ninguno trabajable Y existe >=1 `bloqueado_por_recursos` | `PENDIENTE_RECURSOS` |
| fail-safe | Ninguna de las anteriores aplica (con `cantidad_detalles > 0`) | `CONTEXTO_INCONSISTENTE` -no es un estado de negocio: ver "Fail-safe del resolver" mas abajo- |

Esta misma politica se invoca desde tres puntos del flujo sin duplicar
logica: PROC-REP-090 (gate inicial de habilitacion), PROC-REP-211
(despues de cada Ejecucion, de un rechazo de control, de cancelar un
Detalle o de cancelar los Detalles no terminales de la Orden) y,
implicitamente, PROC-REP-172 (compatibilidad agregada de Estacion, que
reutiliza `es_trabajable`).

### Correccion: PENDIENTE_RECURSOS y REQUIERE_REVISION nunca vuelven a EN_COLA

Una version anterior de este borrador hacia que PROC-REP-211, ante
cualquier resultado "ninguno trabajable pero tampoco todos terminales",
volviera a PROC-REP-170 (EN_COLA). Esto era incorrecto: una Orden
PENDIENTE_RECURSOS o REQUIERE_REVISION no tiene ningun Detalle trabajable,
por lo que no debe quedar disponible/tomable en la cola. Se corrigio
separando ambos resultados en sus propios circuitos de espera:

- **PENDIENTE_RECURSOS** -> PROC-REP-120 ("Detalle(s) pendientes por
  recursos"). Permanece esperando hasta que ocurra un evento de
  revalidacion (por ejemplo, cambio de disponibilidad de insumos), que
  dispara nuevamente PROC-REP-080 ("Validar factibilidad por Detalle").
  No es un loop inmediato automatico: es un re-ingreso disparado por un
  evento posterior.
- **REQUIERE_REVISION** -> PROC-REP-125 ("Detalle(s) pendientes de
  revision tecnica"), nodo nuevo, analogo a PROC-REP-120 pero para la
  dimension de revision en vez de recursos. A diferencia de
  PENDIENTE_RECURSOS, aqui PROC-REP-080 no puede resolver la causa: valida
  factibilidad/recursos, pero un Detalle con condicion REQUIERE_DEFINICION
  necesita primero una accion tecnica que le quite esa condicion. Por eso
  la espera continua hacia dos nodos nuevos, tambien acotados a ESE
  Detalle en particular (no a la Orden completa):
  - **PROC-REP-126** "Realizar revision tecnica de Detalle pendiente" -
    analogo a PROC-REP-065, pero sobre un Detalle ya existente.
  - **PROC-REP-127** "Definir/actualizar reparacion del Detalle" - analogo
    a PROC-REP-070/075, redefine el MISMO Detalle (nueva definicion
    vigente, la anterior se conserva historicamente) y le quita la
    condicion REQUIERE_DEFINICION cuando corresponde.

  Quien ASIGNA REQUIERE_DEFINICION es `PROC-REP-200` con su tercer
  resultado "Requiere redefinicion" (Ejecucion cerrada como no completada,
  Detalle PENDIENTE + REQUIERE_DEFINICION, motivo obligatorio, luego
  PROC-REP-210 y PROC-REP-211); no existe un nodo aparte que la produzca.
  `PROC-REP-125` solo representa la espera/circuito posterior,
  `PROC-REP-126` realiza la revision tecnica y `PROC-REP-127` redefine y
  RETIRA la condicion. Si otro Detalle sigue trabajable, `PROC-REP-211`
  devuelve ABIERTA_TRABAJABLE y recien cuando no queda ninguno trabajable
  se llega a REQUIERE_REVISION -> 125. REQUIERE_REVISION no es un estado
  de workflow. "Interrumpido" (definicion vigente) no es lo mismo que
  "Requiere redefinicion" (definicion invalida). Un `PROC-REP-127`
  invalida cualquier override de `PROC-REP-130` anterior del mismo
  Detalle (BR-REP-003) y preserva historicamente la definicion previa
  (BR-REP-015), incluso si se confirma el mismo Tipo.

  Recien despues de PROC-REP-127 se revalida factibilidad con
  PROC-REP-080 (el Detalle ya definido). Deliberadamente NO se reutiliza
  el circuito inicial de revision de la Orden completa (PROC-REP-050,
  055, 060, 065, 068, 069): ese circuito asume que la Orden todavia no
  tiene ningun Detalle, y reutilizarlo aqui podria regenerar
  incorrectamente el comprobante de recepcion o convertir la revision de
  un unico Detalle en SIN_REPARACION de toda la Orden -efectos que no
  corresponden cuando ya existen uno o mas Detalles definidos y lo
  pendiente es solo sobre alguno en particular-. El Detalle conserva su
  identidad y su historial completo (incluida la revision de
  PROC-REP-126): no se crea un Detalle nuevo.

Ambos agregados siguen sin mezclarse entre si ni con el estado de
workflow EN_REVISION (ver mas abajo).

Hitos de **workflow** (explicitos, avanzan por eventos): REQUERIMIENTO,
EN_REVISION (fijado por PROC-REP-045/PROC-REP-055, nunca por el
resolver), HABILITADA, EN_COLA, EN_REPARACION, REPARACION_LISTA (requiere
ademas el evento externo "control tecnico aprobado" - no es deducible
solo de los Detalles), ENTREGADA, CANCELADA. PENDIENTE_CONTROL no se
persiste como estado propio: es la combinacion computada
`workflow=EN_REPARACION AND agregado=COMPLETA`.

`REQUIERE_REVISION` y `PENDIENTE_RECURSOS` son puramente agregados
derivados del resolver, nunca estados de workflow. En particular,
`REQUIERE_REVISION` es deliberadamente un nombre distinto de
`EN_REVISION`: son dos dimensiones separadas (agregado tecnico vs.
workflow) que no deben compartir nombre. La politica de workflow puede,
si asi se decide, usar `REQUIERE_REVISION` como una de las senales que
llevan o mantienen la Orden en el estado de workflow `EN_REVISION`, pero
esa es una decision de politica de workflow, no una equivalencia
automatica ni una segunda fuente de verdad.

### Correccion: `cantidad_detalles = 0` ya no es una regla ambigua

Una version anterior de este documento hacia que la regla de prioridad 0
devolviera "REQUERIMIENTO o EN_REVISION segun contexto" -dos resultados
posibles para la misma condicion, es decir no deterministica-. Se
corrigio separando con precision las dos responsabilidades:

- El **resolver tecnico** (el que agrega Detalles) devuelve, con
  `cantidad_detalles = 0`, un unico resultado posible: `SIN_DETALLES`. No
  intenta -ni le corresponde- distinguir REQUERIMIENTO de EN_REVISION,
  porque esa distincion no depende de ningun Detalle (no puede depender
  de algo que todavia no existe).
- Esa distincion es responsabilidad exclusiva del **workflow**, fijada
  por eventos explicitos ya modelados: PROC-REP-040 (Crear Orden de
  Reparacion) pone a la Orden en REQUERIMIENTO; PROC-REP-045 (decision)
  seguido de PROC-REP-055 (Marcar Orden en revision) la pasan a
  EN_REVISION cuando al momento del ingreso no se conoce ningun Detalle.
  Ninguno de los dos consulta al resolver tecnico para decidirlo.
- Como consecuencia de la topologia actual del diagrama, el resolver
  nunca llega a invocarse mientras `cantidad_detalles = 0`: los dos
  nodos que lo invocan (PROC-REP-090 y PROC-REP-211) solo son
  alcanzables despues de PROC-REP-070/075, que son los que crean el
  primer Detalle. `SIN_DETALLES` queda igual documentado, como salida
  deterministica de una regla explicita (BR-REP-013) dentro de la misma
  politica extensible, pensada como proteccion para cualquier invocacion
  futura del resolver que no respete esa precondicion (por ejemplo desde
  una UI o herramienta de diagnostico).

## Capacidades transversales (no modeladas como nodos)

Siguiendo el mismo criterio que V1.2 ya aplica a "Sesion del tecnico" y a
la configuracion de Estaciones (documentadas en prosa, no como nodos del
flujo principal), V1.3 documenta asi el **registro de Pagos** y el
**registro de Cortesia**: son acciones que pueden ocurrir en cualquier
momento desde que la Orden esta habilitada en adelante, no pasos
secuenciales de un unico punto del proceso. Se documentan funcionalmente
aqui en vez de agregarse como nodos:

- **Pago**: importe, medio de pago (catalogo configurable), fecha/hora,
  usuario, referencia/comprobante cuando corresponda. Puede ser
  anticipado, parcial, o usar varios medios en la misma Orden.
- **Cortesia** (de Detalle o de Orden completa): unicamente ACT-ADMIN
  puede autorizarla, registrando fecha/hora y motivo obligatorio
  (BR-REP-016). No modifica el precio original del Detalle, que
  permanece como dato historico dentro del Subtotal.
- **Override de recursos de un Detalle** (MVP v2, BR-REP-003): unicamente
  ACT-COORD puede autorizarlo, con motivo obligatorio, sobre cualquier
  Detalle PENDIENTE con condicion BLOQUEADO_POR_RECURSOS. Registra
  usuario, fecha, Detalle, validacion ignorada y motivo; no reserva ni
  consume stock. No exige que toda la Orden este bloqueada: tambien
  aplica con factibilidad parcial (otros Detalles trabajables, Orden
  habilitada, en cola, tomada o en reparacion), y ahi no reinicia el
  proceso (no vuelve a PROC-REP-140, no cierra la toma ni toca la
  Ejecucion en curso). Solo cuando la Orden esta detenida en PROC-REP-100
  ("ningun Detalle trabajable") la autorizacion resuelve PROC-REP-110 = Si
  y la Orden continua 130 -> 140. Es una unica capacidad: misma
  validacion y misma vigencia (la autorizacion vale mientras no exista un
  PROC-REP-127 posterior del mismo Detalle).

### Registrar Pago (transversal) vs. Completar Cobro (secuencial)

Son dos conceptos distintos que no deben confundirse (BR-REP-017):

- **Registrar Pago** es transversal: puede ocurrir en cualquier momento
  de la vida de la Orden (seña, anticipo, pagos parciales, varios medios
  de pago), no unicamente al final. No se modela como nodo, igual que el
  resto de las capacidades de esta seccion.
- **Completar Cobro** SI se modela como nodo, porque es una fase
  secuencial concreta del cierre: recien despues de REPARACION_LISTA se
  determina el Total Cobrable definitivo y se calcula el Saldo
  (PROC-REP-265). Si Saldo > 0, la Orden queda pendiente de completar
  cobro: pueden registrarse uno o mas Pagos adicionales -mediante el
  mismo mecanismo transversal de arriba, no un mecanismo aparte- y el
  Saldo se recalcula despues de cada uno (PROC-REP-266 -> PROC-REP-265,
  "Revalidar"). Solo con Saldo = 0, cortesia total, o condicion
  no-cobrable por origen se habilita la entrega (PROC-REP-270); sin
  override para deuda en V1.3.

No modelar todos los pagos como si ocurrieran unicamente al final de la
Orden, y no modelar la entrega sin este gate final de Saldo.

**Correccion funcional (MVP v2): autorizacion para Registrar Pago.** El
MVP actual dejaba registrar un Pago a cualquier usuario activo, sin
restriccion de rol; es un bug funcional. BR-REP-017 ahora define
explicitamente que puede registrar un Pago todo usuario OPERATIVO ACTIVO
EXCEPTO Tecnico (`ACT_ADMIN`, `ACT_RECEP`, `ACT_COORD` si estan activos;
`ACT_TECH` nunca). No es una decision de frontend: el backend debe hacer
cumplir `usuario activo AND rol != TECNICO`, trazable hacia
Business Rule (BR-REP-017) -> Technical Requirement -> autorizacion en el
backend -> test de API -> accion disponible en el frontend. No se
implementa el fix en Python en esta etapa: este repositorio cierra
primero el contrato funcional.

### Comprobante final despues del cobro

Corregido en este borrador: el comprobante final (PROC-REP-280) se
genera **despues** de que PROC-REP-265 aprueba la condicion de entrega,
no antes. Una version anterior lo generaba antes de completar el cobro,
lo que podia dejarlo desactualizado si despues se registraba un pago
final. Secuencia vigente, para CLIENTE_EXTERNO / entrega al cliente:

```text
REPARACION_LISTA (o SIN_REPARACION)
  -> PROC-REP-260 Notificar cliente
  -> PROC-REP-265 Completar cobro / validar saldo
       -> No cumplida -> PROC-REP-266 registrar Pago(s) -> revalida PROC-REP-265
       -> Si cumplida  -> PROC-REP-280 Generar comprobante final
                        -> PROC-REP-270 Entregar equipo
```

El comprobante final debe poder reflejar: Detalles finales, Subtotal,
Ajustes Comerciales, Total Cobrable, todos los Pagos registrados, y el
Saldo final -que para una Orden cobrable entregable debe ser el
definitivo al momento de la entrega (0, salvo cortesia total o condicion
no-cobrable)-. Registrar Pago sigue siendo una capacidad transversal:
pueden existir señas/anticipos antes de este punto igual que siempre; lo
unico que se mueve es el cierre/comprobante definitivo, que ahora ocurre
despues del gate de cobro y no antes.

Calculo comercial (extensible, sin cerrar la puerta a capas futuras):

```text
SUBTOTAL  = suma de precios snapshot de Detalles NO CANCELADOS
          + AJUSTES COMERCIALES PREVIOS (V1.3: solo CORTESIA_DETALLE / CORTESIA_ORDEN)
          = BASE COMERCIAL
          (fuera de V1.3: + impuestos/recargos/otros conceptos = TOTAL COBRABLE)

SALDO = TOTAL COBRABLE - TOTAL PAGADO
```

Un Detalle CANCELADO conserva su Tipo, precio historico y trazabilidad,
pero no participa del Subtotal (distinto de una cortesia, que si integra
el Subtotal y luego se resta como Ajuste Comercial).

## SIN_REPARACION en V1.3: sin Diagnostico cobrable

Corregido en este borrador: en V1.3 **no existe Diagnostico cobrable**.
La revision tecnica (PROC-REP-065) puede realizarse para determinar que
reparacion necesita el equipo, pero:

- no es por si misma un Detalle de Reparacion cobrable;
- no genera precio;
- no genera Subtotal;
- no existe un Tipo de Reparacion "Diagnostico" en V1.3.

Por lo tanto, SIN_REPARACION significa: la Orden fue
recibida/revisada/procesada, pero finalmente no se definio ni se realizo
una reparacion. Consecuencia directa: SIN_REPARACION implica Subtotal = 0
-no existe reparacion realizada ni importe cobrable asociado (ver
PROC-REP-069, BR-REP-010)-. Una version anterior de este borrador permitia
que SIN_REPARACION coexistiera con un importe cobrable proveniente de un
supuesto "Detalle de Diagnostico COMPLETO y cobrable"; esa referencia se
elimino de PROC-REP-069, BR-REP-010 y PROC-REP-280.

SIN_REPARACION sigue siendo distinto de CANCELADA:

- **SIN_REPARACION**: el proceso llego legitimamente a la conclusion de
  que no habra reparacion.
- **CANCELADA**: el trabajo o el proceso fue cancelado.

Si en el futuro Rosario Tecno decide cobrar el diagnostico, sera una
nueva regla/capacidad a diseñar, fuera de alcance de V1.3.

## Cancelacion

La cancelacion **si esta modelada** en V1.3 (a diferencia de V1.2, que
nunca la representa como nodos: CANCELADA es alli solo un estado
documentado en prosa, sin nodos ni edges propios). Lo que queda
pendiente no es "si existe cancelacion", sino puntos especificos
detallados en "Pendientes especificos de V1.3" mas abajo (quien puede
autorizarla, catalogo de motivos, consecuencias comerciales).

Un Detalle no terminal puede cancelarse individualmente (PROC-REP-300),
conservando su historial. Cancelar una Orden completa (PROC-REP-305) **no
implica automaticamente que termine CANCELADA**: se corrigio esa
interpretacion. La accion cancela los Detalles NO TERMINALES
(preservando los ya COMPLETO) y a continuacion se recalcula el estado
agregado mediante el resolver (PROC-REP-211, BR-REP-014):

- **(A)** Si tras la cascada TODOS los Detalles quedan CANCELADO ->
  Orden = CANCELADA, sin pasar por control tecnico ni por
  REPARACION_LISTA.
- **(B)** Si existe al menos un Detalle COMPLETO y el resto quedo
  CANCELADO -> la Orden queda tecnicamente COMPLETA y continua el flujo
  normal: Control Tecnico -> REPARACION_LISTA -> cierre comercial ->
  entrega cuando corresponda. Motivo: ese Detalle representa trabajo
  efectivamente realizado, que debe poder controlarse, cobrarse y
  cerrarse correctamente -no se descarta solo porque otros Detalles de
  la misma Orden se cancelaron-.

En ambos casos (Detalle u Orden) la cancelacion no puede ejecutarse
mientras exista una Ejecucion activa: primero debe cerrarse/
interrumpirse. Nunca se reescribe historia tecnica real.

### Reconciliacion de insumos antes de cancelar

**Invariante: un Detalle CANCELADO no puede conservar reservas activas de
inventario.** No se crea un mecanismo nuevo para garantizarlo: se
reutiliza el que ya existe (PROC-REP-210, BR-REP-005), que en cada
finalizacion de Ejecucion -Completada o Interrumpida- consume lo
efectivamente utilizado, libera toda reserva no utilizada y registra
desperdicio cuando corresponda, siempre trazado al Detalle que lo
origino.

La razon por la que esto ya esta garantizado por la topologia actual, sin
necesidad de un paso adicional en PROC-REP-300/305: un Detalle solo puede
cancelarse si es no terminal Y no tiene Ejecucion activa (PENDIENTE). El
unico camino desde EN_PROCESO hacia PENDIENTE es interrumpir la Ejecucion
(PROC-REP-200, resultado "Interrumpido"), y ese paso ya pasa
obligatoriamente por PROC-REP-210 antes de que el Detalle quede
disponible de nuevo. Es decir: para cuando un Detalle con Ejecucion
previa llega a ser candidato a cancelacion, sus insumos ya estan en
CONSUMIDO, LIBERADO o DESPERDICIO -nunca en RESERVADO-. Un Detalle sin
Ejecucion previa nunca tuvo reserva que reconciliar. Los movimientos
historicos (incluyendo los de un Detalle luego cancelado) nunca se
borran ni reescriben; conservan su trazabilidad al Detalle de origen.

## Fail-safe del resolver

Proteccion conceptual, no un estado de negocio nuevo: si
`cantidad_detalles > 0` y ninguna regla valida de la matriz de prioridad
aplica, el sistema futuro NO debe inventar un estado ni continuar
silenciosamente. Debe tratarse como **CONTEXTO_INCONSISTENTE / invariante
violada** y reportarse para diagnostico (ver la fila "fail-safe" de la
matriz y BR-REP-012).

Esto no deberia ocurrir si la politica de reglas se mantiene exhaustiva,
pero es exactamente la proteccion que hace segura la extensibilidad ya
prevista para el catalogo de condicion/bloqueo del Detalle (hoy
SIN_BLOQUEO / REQUIERE_DEFINICION / BLOQUEADO_POR_RECURSOS, "extensible a
futuro"): si en el futuro se agrega un nuevo valor de bloqueo sin
actualizar tambien las prioridades del resolver, un Detalle con ese
bloqueo nuevo no encajaria en ninguna regla existente. El fail-safe evita
que ese descuido derive en un estado de Orden erroneo silencioso.

Ejemplos de combinaciones que el futuro diseño tecnico deberia poder
detectar/impedir como invariantes violadas (no exhaustivo):

- un Detalle EN_PROCESO sin ninguna Ejecucion activa asociada;
- mas de una Ejecucion activa simultanea en la misma Orden (viola
  BR-REP-007);
- un Detalle PENDIENTE sin Tipo de Reparacion asignado y sin condicion
  REQUIERE_DEFINICION (inconsistencia entre dos hechos que deberian ir
  juntos);
- cualquier otra combinacion que las invariantes funcionales de V1.3
  declaren imposible.

Este mecanismo queda documentado para el posterior diseño tecnico; no se
implementa en este borrador (no hay base de datos ni codigo en esta
etapa).

## Features V1.3

PROC-REP V1.3 tiene ahora su propia descomposicion funcional en 9
Features draft (`business/features/repair-management-features-v1.3.yaml`),
independiente de las 7 Features de V1.2
(`business/features/repair-management-features.yaml`), que permanecen
intactas como baseline historica y no se modificaron. Ninguna User Story
ni Spec Kit fueron creados en esta iteracion.

Igual que en V1.2, la relacion Feature <-> process_nodes y Feature <->
business_rules es N:M: un mismo nodo o regla puede pertenecer a mas de
una Feature cuando es transversal. El resolver tecnico de estado de
Orden (BR-REP-012) no es una Feature independiente -es una politica
transversal que varias Features invocan-, mientras que la cancelacion si
es una Feature propia (FEAT-REP-009) por tener comportamiento y reglas
propias.

| Feature | Nombre | Nodos propios/compartidos destacados |
|---|---|---|
| FEAT-REP-001 | Ingreso y creacion de Orden de Reparacion | 010, 020, 025, 030, 035, 040, 050, 060 |
| FEAT-REP-002 | Diagnostico y gestion de Detalles de Reparacion | 045, 055, 065, 068, 069, 070*, 075*, 125, 126, 127* |
| FEAT-REP-003 | Validacion de factibilidad y habilitacion | 080, 090, 100, 110, 120, 130, 140 |
| FEAT-REP-004 | Gestion de prioridad, cola, toma y liberacion tecnica | 150, 170, 172, 180, 212, 213 |
| FEAT-REP-005 | Ejecucion de Detalles y gestion de insumos | 181, 174, 176, 178, 179, 185, 186, 190, 200, 210, 211* |
| FEAT-REP-006 | Control tecnico, retrabajo y evaluacion | 220, 230, 235, 245, 240, 211* |
| FEAT-REP-007 | Gestion comercial y pagos de la Orden | 265, 266, 070*, 075*, 127*, 280* |
| FEAT-REP-008 | Finalizacion, entrega e integracion del resultado | 250, 260, 280*, 270, 290 |
| FEAT-REP-009 | Cancelacion de Detalles y Orden | 300, 305, 211* |

`*` = nodo compartido con otra Feature (N:M). Nodos compartidos: PROC-REP-070/075/127
(entre FEAT-REP-002 y FEAT-REP-007, porque alli se registra el precio
snapshot), PROC-REP-211 (entre FEAT-REP-005, FEAT-REP-006 y FEAT-REP-009,
porque las tres reevaluan la situacion de la Orden mediante el mismo
resolver -pero no simultaneamente: ver la siguiente seccion-), y
PROC-REP-280 (entre FEAT-REP-007 y FEAT-REP-008, porque el comprobante
final materializa el resultado comercial aunque su generacion/entrega sea
responsabilidad principal de Finalizacion). Cobertura: los 56
process_nodes funcionales de PROC-REP V1.3 (excluyendo
EVT-REP-001/EVT-REP-999) quedan cubiertos por al menos una Feature.

Notas de numeracion: FEAT-REP-007 (Comercial y Pagos) precede
conceptualmente a FEAT-REP-008 (Finalizacion y Entrega), porque el gate
de Saldo ocurre antes del comprobante final y la entrega. FEAT-REP-009
(Cancelacion) queda al final de la numeracion porque es transversal -no
una etapa secuencial posterior a FEAT-REP-008-.

### Feature <-> Process Node compartido: ALWAYS vs. CONTEXTUAL

Compartir un process_node entre varias Features sigue siendo valido -la
relacion es N:M por diseño-, pero no todos los nodos compartidos
significan lo mismo. `shared_node_bindings` (campo opcional en cada
Feature, ver `business/schemas/feature.schema.json` y
`scripts/lib/feature-model.ts`) distingue dos semanticas:

- **ALWAYS**: el nodo ejecuta simultaneamente comportamiento de todas las
  Features que lo declaran ALWAYS, cada vez que se atraviesa. Ejemplo:
  `PROC-REP-070` es ALWAYS para FEAT-REP-002 (define el Detalle) y para
  FEAT-REP-007 (registra su price snapshot) - ambas cosas ocurren en el
  mismo paso.
- **CONTEXTUAL**: el nodo es un mecanismo compartido, y que Feature esta
  funcionalmente involucrada depende de por que transicion concreta se
  alcanzo. El contexto se identifica por `from + condition + to` (la
  misma identidad de edge que usan los Scenarios), declarado en
  `when.incoming_edges`. Ejemplo: `PROC-REP-211` (el resolver
  centralizado) es CONTEXTUAL para FEAT-REP-005 (via PROC-REP-186 o
  PROC-REP-210, tras una Ejecucion o una reserva fallida), para
  FEAT-REP-006 (via PROC-REP-235, tras un rechazo de control) y para
  FEAT-REP-009 (via PROC-REP-300 o PROC-REP-305, tras una cancelacion) -
  las tres reutilizan el mismo nodo, pero solo una esta funcionalmente
  activa segun por donde se llego.

`scripts/validate-references.ts` exige, como ERROR (no warning), que toda
Feature propietaria de un node genuinamente compartido (mas de un
process_nodes[] lo declara) tenga exactamente un `shared_node_binding`
para ese node: evita que un futuro node compartido quede con su semantica
sin explicar. El campo es opcional y retrocompatible: V1.2 no tiene nodes
compartidos hoy, por lo que esta regla nunca se activa alli y no requiere
migrarla.

Tres conceptos distintos, deliberadamente NO llamados "coverage" todavia:

- **touched_features**: interseccion bruta entre los nodos que un
  Scenario recorre y `Feature.process_nodes[]`. Diagnostico only - puede
  incluir falsos positivos semanticos en nodes CONTEXTUAL alcanzados por
  la transicion "equivocada".
- **active_features**: `touched_features` refinado por ALWAYS/CONTEXTUAL
  y por `FUNCTIONAL_ACTION.feature` - las Features genuinamente
  involucradas. Es lo que el viewer muestra.
- **covered_features**: NO implementado todavia. Reservado para un futuro
  Coverage Analyzer (agregando muchos Scenarios); no debe confundirse con
  "un Scenario paso una vez por esta Feature".

## Scenarios / Happy Path V1.3

PROC-REP V1.3 incorpora una tercera capa, `Scenarios`
(`business/scenarios/repair-management-scenarios-v1.3.yaml`), ademas de
Business Rules y Features:

```text
Business Process
  |- Business Rules
  |- Features
  `- Scenarios
       `- HP-REP-001
```

Un Scenario es una capa SOBRE el Business Process: no lo reemplaza ni lo
duplica. No crea un Mermaid alternativo ni nodos nuevos; cada paso
`PROCESS_EDGE` referencia una transicion real de `process.edges`
(identificada por from + condition + to, nunca solo por from/to, porque
pueden existir varias transiciones entre los mismos dos nodos), y cada
paso `FUNCTIONAL_ACTION` representa una capacidad funcional transversal
sin nodo propio (por ejemplo Registrar Pago, FEAT-REP-007/BR-REP-017),
mostrada unicamente en el panel de detalle del Scenario, nunca como una
linea nueva del diagrama.

`HP-REP-001` ("Reparacion estandar de cliente externo") es el primer
baseline E2E: una Orden CLIENTE_EXTERNO con un unico Detalle conocido
desde el ingreso, sin desvios operativos ni tecnicos. El Happy Path
representa el comportamiento NORMAL del proceso, no necesariamente el
camino con menos nodos: en particular, en lo comercial se considera
normal que el cliente tenga Saldo pendiente hasta el momento de retirar
el equipo, pague en ese momento (`PROC-REP-266` -> Registrar pago final
-> revalida `PROC-REP-265` -> Saldo = 0), y solo entonces se genere el
comprobante final y se entregue el equipo.

Por ahora solo existe `type: HAPPY_PATH` y `scope: E2E`. El modelo
(`business/schemas/scenario.schema.json`,
`scripts/lib/scenario-model.ts`) ya admite `VARIANT`/`EXCEPTION`/
`EDGE_CASE` y `scope: FEATURE`/`RULE` en el enum, para que una futura
iteracion no requiera un cambio de schema, pero su comportamiento -en
particular, una Variant como conjunto de overrides de `facts` sobre este
baseline- no esta implementado ni validado todavia. Tampoco existen
todavia Coverage Analyzer, generador automatico de Scenarios, ni User
Stories: esta iteracion es unicamente el primer Happy Path formal,
validado estructural y referencialmente (`npm run validate:scenarios:v1.3`)
y visualizado como capa de highlighting en el viewer HTML
(selector "Happy Path", independiente y mutuamente excluyente del
selector de Features).

Las Features que un Scenario "involucra" se calculan como
`active_features` (ver la seccion anterior, ALWAYS/CONTEXTUAL), nunca
como la interseccion bruta `touched_features`: para HP-REP-001 eso
significa que FEAT-REP-001 a FEAT-REP-008 quedan activas, pero
FEAT-REP-009 (Cancelacion) NO -aunque el Happy Path atraviesa
PROC-REP-211, lo hace via PROC-REP-210 (que activa a FEAT-REP-005 por
CONTEXTUAL), nunca via PROC-REP-300/305-. El panel del viewer muestra esta
lista bajo "Features involucradas", calculada por
`scripts/lib/feature-scenario-mapping.ts` (el mismo helper que usan
`validate-references.ts` y `validate-scenarios.ts`, para que la semantica
nunca diverja entre la CLI y el HTML).

### Caminos sobre el Process Graph: Happy Path, Variant, Exception, Edge Case

Vocabulario (todos son capas sobre el Process Graph, nunca copias de el):

- **Process Graph**: los nodes/edges de `repair-management-v1.3.yaml`. Es
  la unica fuente de verdad de la topologia, de las descripciones, actores,
  Business Rules y outputs de cada nodo.
- **Happy Path**: recorrido E2E CANONICO del proceso.
- **Variant**: desviacion o condicion alternativa sobre uno o mas puntos de
  un recorrido (por ejemplo una garantia).
- **Exception**: algo que falla o interrumpe el flujo esperado.
- **Edge Case**: combinacion o condicion limite poco frecuente.

> Un Happy Path representa un recorrido E2E canonico del proceso. Una
> Variant representa una desviacion o condicion alternativa sobre uno o
> mas puntos de ese recorrido. No se crean nuevos Happy Paths para cada
> combinacion de Variants.

Modelo: **Happy Path base + Variants atomicas + Exceptions + Edge Cases**.
Una ejecucion futura podra combinar varias Variants; nunca se enumeran las
combinaciones (Cliente + Garantia + Pago anticipado + Falta de stock ...),
que crecerian de forma explosiva.

```text
Process Graph  +  Happy Path (steps sobre edges reales)  =  Recorrido E2E
```

Hoy existen tres Happy Paths (`business/scenarios/repair-management-scenarios-v1.3.yaml`):

| Happy Path | Origen | Recorrido distintivo |
|---|---|---|
| **HP-REP-001** Cliente externo | CLIENTE_EXTERNO | registra cliente/equipo, comprobante de recepcion, cobro (Saldo), notificacion, comprobante final y entrega al cliente |
| **HP-REP-002** Equipo RT | RT_INTERNO | recibe contexto del equipo RT (PROC-REP-020), sin comprobante de recepcion; tras REPARACION_LISTA informa el resultado a Gestion RT (PROC-REP-290) y RECIEN DESPUES registra la entrega/devolucion del equipo a Gestion RT (PROC-REP-270), luego fin |
| **HP-REP-003** Garantia RMA | RMA_GARANTIA_REPARACION | parte de una Orden origen finalizada (EVT-REP-002), identifica la Orden y el Detalle origen (PROC-REP-035), recupera cliente/equipo, crea una NUEVA Orden vinculada; NO_COBRABLE: recorre 265 (validacion de condicion de entrega) que aprueba por origen, sin pago ni 266, con notificacion, comprobante final y entrega al cliente |

HP-REP-002 es un Happy Path propio (y no una Variant) porque el origen
cambia estructuralmente el recorrido E2E. NO tiene pago/anticipo de
cliente, validacion de saldo, cortesia comercial, notificacion de retiro
ni entrega comercial a cliente: esos nodos (030, 060, 260, 265, 266, 280)
se declaran en `skipped_nodes` con su motivo. La entrega/devolucion del
equipo a Gestion RT SI ocurre (`PROC-REP-270`, ver abajo). Se conserva la trazabilidad con
el equipo/origen RT y el resultado se informa a Gestion RT. El estado
terminal definitivo de RT_INTERNO sigue pendiente (ver Pendientes).
Orden final de HP-REP-002: `REPARACION_LISTA` (PROC-REP-240) -> `PROC-REP-250`
(no requiere entrega a cliente) -> `PROC-REP-290` informar resultado a
Gestion RT -> `PROC-REP-270` entrega/devolucion del equipo a Gestion RT ->
fin (`EVT-REP-999`). Nunca se entrega primero y se informa despues. Para
esto se reutilizo `PROC-REP-270` (no se creo un nodo) y el unico cambio de
topologia fue reemplazar el edge `PROC-REP-290 -> EVT-REP-999` por
`PROC-REP-290 -> PROC-REP-270` (`270 -> EVT-REP-999` ya existia); el camino
de cliente (`265 -> 280 -> 270`) no cambia. Para RT_INTERNO, `270` es una
devolucion a Gestion RT, no una entrega comercial: no usa Saldo ni Pagos y
NO define el estado terminal de la Orden (sigue `PENDIENTE_DE_DEFINIR`; no
se asume ENTREGADA ni un estado nuevo). No existe un nodo "Cerrar Orden"
aparte: el cierre es el fin `EVT-REP-999`.

**Feature activa no significa "todos sus comportamientos aplican".** Una
Feature esta activa en un Happy Path si PARTE de su comportamiento
funcional participa en ese recorrido; no implica que todos sus nodos,
reglas o comportamientos se ejecuten. FEAT-REP-007 esta activa tanto en
HP-REP-001 como en HP-REP-002, y es correcto, pero con comportamientos
distintos: en HP-REP-001 recorre pago, saldo y cierre comercial
(PROC-REP-265/266/280); en HP-REP-002 no hay pago, ni validacion de saldo,
ni cortesia comercial, ni notificacion de retiro. Su participacion hoy
derivada en HP-REP-002 es el registro del precio snapshot de cada Detalle
(PROC-REP-070, binding ALWAYS). Precio registrado no es pago requerido:
todo Detalle, de cualquier origen, puede tener precio snapshot, y luego la
condicion comercial (RT_INTERNO = NO_COBRABLE_AL_CLIENTE) determina si se
cobra; NO_COBRABLE tampoco significa "sin precio de referencia". La
derivacion (`deriveScenarioFeatures`) ahora devuelve `activationReasons`:
por que esta activa cada Feature (nodo propio, nodo compartido ALWAYS/
CONTEXTUAL o accion funcional), para no atribuir la activacion a una unica
causa; el viewer la muestra como "Activa por". Nota de modelo: la
entrega/devolucion (PROC-REP-270) y el informe a Gestion RT (PROC-REP-290)
pertenecen hoy a FEAT-REP-008, no a FEAT-REP-007; no se movieron Features
en esta iteracion.

**included / skipped / conditional.** *included* = nodo atravesado por
`steps[]` (se deriva, no se repite); *skipped* = nodo listado en
`skipped_nodes[]` con `reason` (documental; el validador exige que exista y
que el mismo Scenario no lo atraviese); *conditional* es un concepto de las
Variants (su `trigger`/condicion de activacion), no de un Happy Path, que
es determinista. Se eligio `steps[]` sobre edges (from + condition + to) en
vez de un mapa nodo->estado porque tambien dice QUE transicion se tomo en
nodos con varias entradas (por ejemplo PROC-REP-211) y se valida con
continuidad.

**Arquitectura preparada para Variants** (ninguna real declarada todavia).
Un Scenario de tipo VARIANT/EXCEPTION/EDGE_CASE puede indicar, todos
opcionales: `feature` (Feature donde se origina), `applies_to` (Happy Paths
a los que aplica), `trigger` (node/edge y condicion de activacion),
`affected_nodes`, `rules` (Business Rules) y `dependencies`
(`requires`/`enables`/`implies`/`excludes` hacia otros Scenarios). Solo se
valida la forma y la integridad referencial; como se combinan esas
relaciones al ejecutar NO esta implementado. Una Variant se define UNA vez
y puede impactar nodos de varias Features (`affected_nodes`), sin
duplicarse por Feature. Steps/facts/expected solo son obligatorios para un
HAPPY_PATH.

**HP-REP-003 - Garantia de reparacion RMA.** Es un Happy Path propio (no una
Variant local) porque cambia estructuralmente el recorrido E2E, igual que
HP-REP-002:

```text
HP-REP-001: necesidad nueva -> registrar cliente/equipo -> crear OR -> ... -> cobro -> saldo -> entrega
HP-REP-003: OR origen finalizada -> iniciar garantia (1..N Detalles origen)
            -> recuperar cliente/equipo/origen -> crear NUEVA OR vinculada
            -> EN_REVISION -> revision tecnica obligatoria -> definir Detalles
            -> ... -> (sin cobro, sin saldo) -> entrega
```

- **Evento inicial propio**: `EVT-REP-002` "Una Orden de Reparacion finalizada
  requiere garantia" (nuevo, unico nodo agregado). Forzar `EVT-REP-001`
  ("surge una necesidad de reparacion") habria borrado la diferencia
  funcional. Converge en `PROC-REP-035`; la entrada por `PROC-REP-010` se
  conserva como alternativa.
- **`PROC-REP-035` reutilizado y ampliado**: toma como entrada la Orden
  origen finalizada, la identifica junto con el/los Detalle(s) origen que
  fallaron, y recupera cliente y equipo de ella (no hay alta nueva, por eso
  no pasa por `PROC-REP-030`). `PROC-REP-040` crea una NUEVA Orden con origen
  RMA_GARANTIA_REPARACION, condicion NO_COBRABLE y referencia a la Orden
  origen y a los 1..N Detalles origen seleccionados (una unica Orden por
  inicio, no una por Detalle). **Revision obligatoria (MVP v2)**: la Orden
  nueva nace sin Detalles y EN_REVISION (`PROC-REP-045` = No -> 055 -> 050
  -> 060), el tecnico la revisa (065) y Recepcion define los Detalles de
  garantia (068 Si -> 075), cada uno vinculado a uno de los Detalles
  origen sin relacion 1:1; si la revision no permite definir reparacion,
  concluye SIN_REPARACION (068 No -> 069). Ya no existe el camino que
  copiaba directamente el Tipo del Detalle origen (045 Si -> 070). La
  Orden origen NO se reabre y conserva su estado: no se crearon estados
  como REABIERTA_POR_GARANTIA.
- **Trazabilidad en ambos niveles** (`BR-REP-019`): Orden nueva -> Orden
  origen y Detalle nuevo -> Detalle origen. Esto RESUELVE el pendiente
  "Orden origen vs. Detalle origen". Sigue pendiente el modelo tecnico
  (sin base de datos aqui) y las reglas de garantia RMA configurable/vencida.
- **Sin estado CERRADA**: el modelo no lo tiene (V1.2 lo excluye). La
  precondicion se define como "Orden origen finalizada (ENTREGADA)"; si
  negocio quiere otra definicion es una decision aparte.
- **Convergencia y gate general de condicion de entrega**: desde
  `PROC-REP-040` hasta `PROC-REP-260` es el mismo circuito tecnico de
  HP-REP-001, y luego HP-REP-003 recorre `PROC-REP-265` igual que
  HP-REP-001: es el mismo gate general de condicion de entrega para todo
  origen con entrega a cliente, y NO se creo ningun bypass alrededor de el
  (`260 -> 265` sin condicion, `265 -> 280 [Si]`; no hay edge
  `260 -> 280`). Lo que cambia es COMO se aprueba:

  ```text
  CLIENTE_EXTERNO          -> aprueba por Saldo = 0 o cortesia total
  RT_GARANTIA_VENTA        -> aprueba por condicion NO_COBRABLE
  RMA_GARANTIA_REPARACION  -> aprueba por condicion NO_COBRABLE
  ```

  HP-REP-003 recorre `PROC-REP-265` como validacion de condicion de
  entrega, pero nunca entra en `PROC-REP-266` ni registra pagos porque la
  condicion NO_COBRABLE aprueba directamente la entrega: no hay cobro
  pendiente, ni anticipo, ni Saldo = 0 mediante pagos, ni cortesia usada
  para evitar el cobro. Los edges de HP-REP-001 no cambian. Business
  Rules: `BR-REP-016` y `BR-REP-017` extendidas y `BR-REP-019` nueva.
- **Omitidos** (`skipped_nodes`): 010 (origen ya conocido), 030 (cliente/
  equipo se recuperan), 266 (no hay cobro pendiente ni registro de pago) y
  290 (informe a Gestion RT, propio de RT_INTERNO). `PROC-REP-265` NO esta
  omitido. El pago no tiene nodo propio (es una capacidad transversal):
  simplemente no hay ninguna accion funcional de pago.
- **Features activas**: FEAT-REP-001 a 008 (no 009). FEAT-REP-007 esta
  activa por su nodo propio `PROC-REP-265` (validacion de condicion de
  entrega) y por los nodos compartidos ALWAYS 070 (precio snapshot) y 280
  (comprobante final), pero no por `PROC-REP-266`: activa no significa
  que se ejecute el cobro. Precio registrado no implica pago requerido.

**Variants futuras ya identificadas sobre HP-REP-001** (documentadas, no
implementadas):

- *Garantia de Venta RT* (RT_GARANTIA_VENTA): hay cliente y el equipo vuelve
  a el; debe existir referencia/trazabilidad con la venta RT; la reparacion
  es NO_COBRABLE, sin pago del cliente ni bloqueo de entrega por saldo; sigue
  existiendo notificacion y entrega al cliente.
- *(La garantia de reparacion RMA ya no es una Variant futura: es el Happy
  Path HP-REP-003, ver arriba.)*

**Viewer.** El selector "Happy Path" ofrece "Proceso completo",
HP-REP-001, HP-REP-002 y HP-REP-003: resalta los nodes y los edges exactos del camino
(no elimina los demas del DOM, los atenua) y muestra los `skipped_nodes`
con su motivo. Ademas, el diagrama ahora se muestra a su tamano real y
legible (100% = tamano natural de Mermaid): antes el SVG se colapsaba a ~16%
de su tamano (`width="100%"` dentro de un contenedor `max-content`) antes de
aplicar cualquier zoom. Zoom de 15% a 800% con paso multiplicativo,
Ctrl/Cmd+rueda (o pellizco) con zoom sobre el cursor, y arrastre del fondo
para desplazarse; el diagrama completo es siempre alcanzable por scroll.

### Scenario Candidate Discovery

Herramienta de descubrimiento **estructural y deterministico** de caminos
alternativos. Compara el Process Graph con cada Happy Path y detecta donde
el grafo ofrece una transicion distinta de la que el Happy Path eligio:

```text
Process Graph + Happy Paths
        |
discover-scenario-candidates.ts
        |
Candidate Scenario Inventory   (generated/scenarios/repair-management-candidates-v1.3.yaml)
        |
LLM / analisis funcional
        |
Human confirmation
        |
VARIANT / EXCEPTION / EDGE_CASE
```

> **Un Candidate Scenario no es un Scenario aprobado.** Es solo una
> diferencia topologica entre el grafo y un Happy Path. No se clasifica
> (no dice si es Variant, Exception o Edge Case), no se nombra, no se
> prioriza y no se agrega a `repair-management-scenarios-v1.3.yaml`. El
> archivo generado esta marcado como GENERATED / NOT SOURCE OF TRUTH / NOT
> CONFIRMED BUSINESS SCENARIOS y nunca se edita a mano.

Uso: `npm run discover:scenarios:v1.3` (genera el inventario y muestra un
resumen; es generacion, por eso NO forma parte de `validate:v1.3`) y
`npm run test:scenario-discovery` (tests del algoritmo; estos si estan en
`validate:v1.3`). Codigo: `scripts/lib/scenario-discovery.ts` (funciones
puras) y `scripts/discover-scenario-candidates.ts` (CLI).

**Algoritmo.**

1. Por cada `PROCESS_EDGE` de un Happy Path (en orden), se toman todos los
   outgoing edges reales de su nodo `from`; los que no son el edge elegido
   en ese paso son alternativos. Un edge se identifica por
   `from + condition + to` (`edgeKey`, compartido), nunca por from/to.
2. Cada alternativa inicia una BFS acotada que corta cada rama en el primer
   desenlace estructural: `END` (llega a un nodo `end`; tiene precedencia
   porque el fin esta en todo Happy Path), `REJOIN_FORWARD` (vuelve a un
   nodo del Happy Path ubicado DESPUES del punto de divergencia),
   `LOOP_TO_BASELINE` (vuelve a un nodo del Happy Path ANTES o EN el punto
   de divergencia: reintentos/revalidaciones), `CYCLE` (revisita un nodo de
   su propio recorrido sin haber tocado el Happy Path), `MAX_DEPTH` (limite
   de seguridad, `DEFAULT_MAX_DEPTH = 30` centralizado) y `DEAD_END`
   (nodo sin salidas que no es `end`; red de seguridad, no ocurre en el
   grafo validado).
3. No hay explosion combinatoria: cada nodo se expande una sola vez por
   desviacion (`visited`), las ramas que reconvergen en un nodo ya explorado
   se podan y se cuentan, y los loops nunca se despliegan. Una desviacion
   que se ramifica produce un candidato por desenlace distinto.
4. Los candidatos se deduplican entre Happy Paths por una firma
   deterministica: edge baseline + edge alternativo + recorrido explorado +
   tipo y nodo de terminacion, SIN el id del Happy Path. Un candidato
   deduplicado acumula `applies_to` y `occurrences` (Happy Path y paso donde
   ocurre). Los ids `CAND-REP-NNN` se asignan tras ordenar por nodo de
   divergencia, edge alternativo, baseline y terminacion, asi que dos
   ejecuciones sin cambios producen exactamente el mismo archivo.

**Limitaciones conocidas (V1).**

- Solo encuentra alternativas que **salen de un nodo del Happy Path**. Las
  capacidades no secuenciales quedan para una futura Pass 2: cancelacion
  transversal, pago anticipado y acciones disponibles desde muchos estados.
- Cycle detection es BFS + `visited` (revisita en el recorrido propio); no
  usa Tarjan/SCC, que puede incorporarse despues si hace falta analisis de
  ciclos mas fino.
- Un candidato es un recorrido hasta el primer desenlace, no un escenario
  completo: no se explora que pasa despues de reincorporarse, ni se combinan
  desviaciones entre si.
- La poda por `visited` implica que, cuando dos ramas de una misma
  desviacion convergen, solo se reporta el recorrido mas corto.
- Los `FUNCTIONAL_ACTION` de los Happy Paths se ignoran (no son edges) y
  no se interpreta ningun nombre, descripcion ni condicion del negocio.

## MVP v2 - Scope funcional cerrado

Cierra el alcance funcional del MVP v2, antes de integrar con el
repositorio productivo `rt-rma-mvp`. Base: los tres Happy Paths
(`HP-REP-001/002/003`) mas 3 `VARIANT` y 5 `EXCEPTION` REALES y
CONFIRMADOS en `business/scenarios/repair-management-scenarios-v1.3.yaml`
(ya no solo entries de analisis). Son los primeros Scenarios que usan de
verdad los campos `feature`/`trigger`/`applies_to`/`affected_nodes`/
`rules` que el schema admitia desde HP-REP-003 pero nadie habia poblado
todavia.

**Trazabilidad Candidate -> Scenario** (no se amplio el schema con un
campo `source_candidate`: la relacion queda documentada aqui y en la
`description` de cada Scenario, que cita sus Candidate IDs de origen):

| Scenario | Tipo | Candidate(s) origen | applies_to |
|---|---|---|---|
| `VAR-REP-001` Ingreso sin diagnostico, con comprobante | VARIANT | CAND-REP-007, CAND-REP-016 | HP-REP-001 (en HP-REP-003 la revision es obligatoria y forma parte del Happy Path) |
| `VAR-REP-002` Ingreso sin diagnostico, sin comprobante (RT) | VARIANT | CAND-REP-007, CAND-REP-009 | HP-REP-002 |
| `VAR-REP-003` Ejecucion interrumpida | VARIANT | CAND-REP-027 | HP-REP-001/002/003 |
| `EXC-REP-001` Recursos insuficientes, en espera | EXCEPTION | CAND-REP-018 | HP-REP-001/002/003 |
| `EXC-REP-002` Recursos insuficientes, con override | EXCEPTION | CAND-REP-019 | HP-REP-001/002/003 |
| `EXC-REP-003` Reserva de insumos fallida al iniciar | EXCEPTION | CAND-REP-026 | HP-REP-001/002/003 |
| `EXC-REP-004` Requiere revision tecnica posterior | EXCEPTION | CAND-REP-032 | HP-REP-001/002/003 |
| `EXC-REP-005` Rechazo de control tecnico / retrabajo | EXCEPTION | CAND-REP-034 | HP-REP-001/002/003 |

**Por que VAR-REP-001/002 son dos Scenarios y no uno.** El business case
("al ingreso no se conoce el Detalle") es el mismo (CAND-REP-007), pero
`steps[]` exige una secuencia LITERAL de edges reales: los origenes con
comprobante (CLIENTE_EXTERNO/RMA_GARANTIA_REPARACION) pasan por
PROC-REP-060 y los sin comprobante (RT_INTERNO) van directo de
PROC-REP-050 a PROC-REP-065; no pueden expresarse en un unico `steps[]`.
No se fusiono el desenlace SIN_REPARACION (CAND-REP-010/017): sigue fuera
de MVP v2 (ver mas abajo).

**Por que Recursos insuficientes son 2 Scenarios (EXC-REP-001/002) y no
uno.** Mismo motivo estructural: `PROC-REP-110` bifurca en dos edges
reales distintos (`No` -> espera/PENDIENTE_RECURSOS, `Si` -> override
BR-REP-003), cada uno con su propio `steps[]` y `expected`. El schema no
admite dos recorridos alternativos dentro de un mismo Scenario, y forzar
uno solo habria ocultado que la resolucion por override es una decision
de autorizacion (BR-REP-003), no un detalle menor de redaccion. No se
crea ninguna Business Rule nueva de autorizacion: EXC-REP-002 cita
BR-REP-002 y BR-REP-003, ya existentes.

**Mecanica multi-Detalle (CAND-REP-028/029/030): NO son Scenarios.**
Siguen `MECHANISM_ONLY` (ver
`generated/scenarios/repair-management-candidate-analysis-v1.3.yaml`):
que una Orden tenga 1..N Detalles y que, al terminar uno, el tecnico
pueda continuar con la misma toma o liberar la Orden, es comportamiento
normal del proceso (BR-REP-018), no una desviacion que necesite su
propio Scenario. `scripts/test-scenarios.ts` verifica explicitamente que
ningun Scenario real declare esos edges como propios.

**Explicitamente diferido de MVP v2 (`OUT_OF_SCOPE`):**

- **`RT_GARANTIA_VENTA`**: no se formaliza ningun Scenario. Informacion
  funcional nueva indica que necesita un modelo de dominio distinto - una
  entidad generica `OrdenRevision` con `tipo_revision = GARANTIA`, cuya
  revision resuelve en `REPARACION` / `CAMBIO_DIRECTO` /
  `NO_APLICA_GARANTIA`, y solo algunas resoluciones derivan en una
  `OrdenReparacion` - todavia no suficientemente diseñado. El Process
  Graph V1.3 NO se modifica para anticipar ese modelo en esta iteracion;
  `RT_GARANTIA_VENTA` permanece como se documenta en `FG-REP-002` del
  candidate analysis (candidate a Variant de HP-REP-001, sujeto a
  revision humana), sin decidir todavia si sera una Variant o un Happy
  Path propio.
- **`SIN_REPARACION` tras un ingreso `EN_REVISION`** (CAND-REP-010/017):
  pendiente la decision de negocio sobre aviso/documentacion/cierre
  adicional (ver Pendientes especificos de V1.3).
- **Cancelacion** (CAND-REP-020/021/033, grupo `FG-REP-005`): BR-REP-014
  todavia no define quien esta autorizado a cancelar un Detalle o una
  Orden; sin esa definicion no se redacta el Scenario real.

**SOURCE_MODEL_CONFLICT durante esta formalizacion: ninguno.** Los 8
Scenarios de MVP v2 se representan integramente con el Process Graph
V1.3 existente, sin modificar nodos ni edges.

## Pendientes especificos de V1.3

Ademas de todos los pendientes de V1.2 listados arriba (que siguen
abiertos sin cambios), V1.3 identifico estos pendientes adicionales,
deliberadamente fuera de alcance de esta revision:

- Presupuestacion y aprobacion de cliente externo (se mantiene fuera de
  V1.3, como en V1.2).
- Consecuencias comerciales de la cancelacion (reembolso de pagos ya
  realizados sobre Detalles luego cancelados).
- Costo de reparacion (mano de obra + costo real de insumos vs. precio):
  metodologia de valoracion de stock (FIFO, promedio, lote especifico)
  todavia no definida.
- Impuestos, recargos, descuentos y otros conceptos comerciales futuros
  entre Base Comercial y Total Cobrable.
- Si la cortesia puede ser parcial o siempre equivale al 100% del precio
  del Detalle/Orden.
- Quien esta autorizado a cancelar un Detalle o una Orden (que actor,
  con que permiso). No se asume ningun actor: los nodos PROC-REP-300 y
  PROC-REP-305 omiten deliberadamente el campo `actor` en el YAML (el
  schema no lo exige para nodos `activity`) en vez de inventar uno sin
  aprobacion de negocio.
- (Resuelto en V1.3, BR-REP-019) Vinculacion de la garantia RMA: la Orden
  nueva referencia la Orden origen y cada Detalle nuevo referencia su
  Detalle origen. Siguen pendientes las reglas de garantia RMA configurable
  y de garantia vencida, y el modelo tecnico de esa relacion.
- Distribucion/acreditacion de puntaje entre multiples tecnicos que
  participaron de un mismo Detalle (ya pendiente en V1.2, ahora ademas
  interactua con multiples Ejecuciones por Detalle).
- Catalogo definitivo de motivos de cancelacion/interrupcion de
  Ejecucion.
- Garantia de reparacion post-entrega a nivel Detalle (hoy solo se
  relaciona a nivel Orden).
- Multi-moneda en precios y pagos.
- Que ocurre si la revision tecnica de un Detalle puntual
  (PROC-REP-126/127) tampoco logra definir una reparacion para ese
  Detalle en particular: a diferencia del circuito inicial
  (PROC-REP-068/069), aqui no existe todavia un camino equivalente a
  SIN_REPARACION acotado a un unico Detalle (por ejemplo, dejarlo
  indefinido, o cancelarlo puntualmente via PROC-REP-300). Que asigna la
  condicion REQUIERE_DEFINICION (PROC-REP-200 "Requiere redefinicion") y
  quien la retira (PROC-REP-127) ya esta definido; lo pendiente es
  exclusivamente este caso de borde.
- Efecto comercial de una redefinicion (PROC-REP-127) que cambia el
  precio snapshot: el nuevo total es la suma de los snapshots vigentes y
  saldo = total - pagado. Precio mayor -> saldo adicional pendiente;
  precio menor -> saldo negativo / pago excedente. SIN definir todavia:
  tratamiento del pago excedente (devolucion/reembolso, credito a favor),
  y aceptacion/aprobacion comercial del cliente ante un aumento de precio
  (presupuesto). No bloquea EXC-REP-004.
- **PENDING BUSINESS DECISION (MVP v2): paralelismo de Detalles /
  Ejecuciones.** Pregunta abierta al cliente: un mismo equipo, puede tener
  varias reparaciones trabajandose simultaneamente? Hasta tener respuesta
  se mantiene BR-REP-007 (maximo una Ejecucion activa por Orden) y
  BR-REP-018 sin cambios: no se inician varios Detalles en paralelo ni
  varias Ejecuciones simultaneas.
- Reporting por tecnico (a futuro, sin agregar nodos al Business
  Process): OR actualmente tomadas, OR trabajadas, OR liberadas, Detalles
  completados, trabajos pendientes. El historial de toma/liberacion
  (PROC-REP-180/212/213, BR-REP-018) ya deja la base de datos conceptual
  necesaria; el reporting en si y las Features de UI correspondientes
  quedan fuera de alcance de esta revision.
