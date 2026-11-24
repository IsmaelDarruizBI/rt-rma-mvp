# Pendientes de producto

Decisiones de producto tomadas durante el UAT que todavía no están implementadas. Cada entrada dice qué está decidido, cómo está hoy y qué falta. No reemplaza al registro de decisiones funcionales de `rt-rma-app` (`business/decisions/`): si un pendiente cambia la definición funcional, se resuelve allí.

Registrado el 28/10/2026, con `mvp-v2` en `a8dd74b`.

| N.º | Pendiente | Área | Estado |
|---|---|---|---|
| P-01 | Buscador técnico en el alta RT_INTERNO, con GB y color obligatorios | Ingreso de equipos | Decidido, sin implementar |
| P-02 | Números de modelo del fabricante en el catálogo técnico | Catálogo técnico | Esperando información verificada |
| P-03 | Modelos de la línea iPhone 18 | Catálogo técnico | Excluidos hasta validar; desde DEC-AJ-12 y 13 se pueden cargar desde Configuración (local) |
| P-04 | Garantía de 180 días en los Términos y Condiciones | Comprobante de entrega | Resuelto por DEC-AJ-09; implementado en local |
| P-05 | Cláusulas sobre el retiro por terceros | Comprobante de entrega | Resuelto por DEC-AJ-09; implementado en local |
| P-06 | Override por falta de stock: cualquier usuario y sin stock negativo | Inventario | Implementado en el MVP; falta actualizar BR-REP-003 |
| P-07 | Jerarquía y compatibilidad de insumos | Inventario | Resuelto por DEC-AJ-14; implementado en local |
| P-08 | Apartados 6 y 18 de los Términos y Condiciones | Comprobante de entrega | Revisión pendiente |
| P-09 | Motivo del ajuste comercial fuera de los comprobantes | Comprobantes | Implementado en local; confirmar |
| P-10 | Revertir el retiro de un ajuste comercial | Ajuste comercial | Decisión pendiente |
| P-11 | Tope del ajuste de importe fijo solo al revertir o corregir | Ajuste comercial | Decisión pendiente |
| P-12 | Pieza preferida por requisito | Insumos y Compras | Sin decidir |
| P-13 | Importación masiva de la clasificación de insumos | Insumos | Sin decidir |
| P-14 | Reportes de consumo por categoría y por origen del precio | Reportes | Sin decidir |
| P-15 | Stock mínimo por categoría y modelo | Inventario | Sin decidir |
| P-16 | Precios multimarca en la importación | Precios | Fuera por D-13.2 |

## P-01. Buscador técnico para RT_INTERNO

**Decidido.** El alta de equipos internos usará el mismo buscador del catálogo técnico que el alta de Cliente Externo. Las validaciones dependen del origen de la Orden:

| Origen | Capacidad (GB) | Color |
|---|---|---|
| CLIENTE_EXTERNO | Opcional | Opcional |
| RT_INTERNO | **Obligatoria** | **Obligatorio** |
| RMA_GARANTIA_REPARACION | Se conserva la de la Orden original | Se conserva el de la Orden original |

Marca, modelo y variante salen del modelo técnico, que es compartido. Capacidad y color son del equipo físico.

**Hoy.**

- El formulario RT_INTERNO pide marca y modelo a mano y no pide GB ni color.
- El backend tampoco los exige: un alta RT sin GB ni color se acepta, y nunca se exigió.
- La API no recibe la capacidad: no hay forma de cargarla, ni en Cliente Externo.
- Al corregir el equipo eligiendo un modelo del catálogo o cargándolo a mano, la capacidad que tenía la Orden se pierde. Esto afecta también a una Orden RMA que la había copiado de su Orden original.

**Falta.**

1. Aceptar `capacidad` en el alta y la corrección, y conservarla al elegir un modelo, igual que el color.
2. Validar en el backend GB y color obligatorios para RT_INTERNO.
3. Usar el buscador y los campos de GB y color en el formulario RT_INTERNO.

Los pasos 2 y 3 tienen que entrar juntos: si la validación llega antes, el alta RT deja de funcionar.

## P-02. Números de modelo del fabricante

**Decidido.** `numeros_modelo` (por ejemplo «A2849») se carga de a poco, solo con información verificada. El buscador ya los usa cuando existen.

**Hoy.** Está vacío en los 36 modelos de `app/backend/app/datos/modelos_equipo.json`. El `tp_number` de Ventas no es un número de modelo del fabricante y no se usa para esto.

**Falta.** Una fuente verificada. Se cargan en el JSON y regenerar el catálogo los conserva (`app/backend/scripts/generar_modelos_equipo.py`).

## P-03. Modelos de la línea iPhone 18

**Decidido.** La línea queda fuera del catálogo técnico hasta verificar sus denominaciones y variantes comerciales. No se borra del catálogo de Ventas.

**Hoy.** El generador la excluye (`MODELOS_EXCLUIDOS`). En la exportación de Ventas del 21/10/2026 son 420 filas con las variantes Estándar, Pro, Pro Max, Air, E y Duo, más dos filas sin número de modelo («iPhone 18 Pro 256GB» y «iPhone 18 Pro Max 256GB»). Mientras tanto, un iPhone 18 se puede cargar a mano.

**Desde DEC-AJ-12 y 13** (implementado en local, `f3a216b` y `1e8a642`), Administración puede dar de alta un modelo en Configuración → Modelos de equipo y cargar sus precios en la grilla del tipo o con la importación de precios, sin esperar la exportación de Ventas.

**Falta.** Decidir si la línea se da de alta así o con la exportación, y validar los nombres. Por la exportación: quitarla de `MODELOS_EXCLUIDOS` y regenerar: los modelos existentes conservan sus IDs. La iteración de UX de Recepción (DEC-UX-01, 16/11/2026) confirmó que el mismo mecanismo completa también los modelos que Ventas agregó después del 21/10 o nunca vendió: hace falta una exportación nueva de Ventas (pendiente ABI-43 en `business/`; detalle en [`ux-recepcion.md`](ux-recepcion.md), UX-01).

## P-04. Garantía de 180 días en los Términos y Condiciones

**Resuelto por DEC-AJ-09 (23/11/2026).** El apartado 1 de los Términos y Condiciones decía «una garantía de seis meses (180 días de corrido)», transcripto de la hoja de Rosario Tecno sin validar. Ya no hay un plazo fijo: los términos remiten a la garantía de cada trabajo que figura en el comprobante, con su plazo y su vencimiento, contada desde la entrega. Las reglas de garantía no cambian (90 o 30 días según el check-in de entrega, con ajuste manual).

**Implementado en local** (`feat/ajustes-funcionales-uat`, bloque 4: `d657ca5`, `0552bbd` y `89a3e6a`). Los términos son versionados y los administra Administración desde Configuración; la migración `20261123000300` carga la versión 2 con este cambio, y cada comprobante conserva la versión que usó. Los comprobantes emitidos antes se siguen imprimiendo con el texto anterior. Detalle: [`ajustes-funcionales-discovery.md`](ajustes-funcionales-discovery.md), sección 10.3.

## P-05. Cláusulas sobre el retiro por terceros

**Resuelto por DEC-AJ-09 (23/11/2026).** El apartado 15 anulaba la garantía si retiraba el equipo una persona distinta del titular, y el 14 exigía entregarlo a quien lo dejó. Ahora la entrega pregunta «¿Retira otra persona?»: si es Sí, se piden nombre, apellido y teléfono, sin vínculo, DNI ni otra identificación. Que retire otra persona no modifica ni anula la garantía. Quién retiró queda en la Orden y en el comprobante.

**Implementado en local** (`feat/ajustes-funcionales-uat`, bloque 2: `b23732f` y `f51ce94`). Los dos apartados se quitaron de los términos, también de la versión 2. Detalle: [`ajustes-funcionales-discovery.md`](ajustes-funcionales-discovery.md), sección 10.1.

## P-06. Override por falta de stock

Registrado el 29/10/2026. En el UAT el stock inicial de baterías es chico y las reparaciones quedaban bloqueadas.

**Decidido.** Cualquier usuario puede forzar un Detalle bloqueado por falta de stock, sin que el inventario quede en negativo:

1. Lo autorizan Recepción, Técnico, Coordinación RMA y Administración, siempre con motivo y confirmando el impacto en el stock. Nunca es automático.
2. Con override se reserva solo lo realmente disponible, sin usar reservas de otras Órdenes.
3. El Detalle se puede ejecutar y terminar aunque no haya stock suficiente.
4. Se descuenta a lo sumo lo reservado y existente. Lo que se usó de más no genera movimiento ni queda pendiente: no se descuenta cuando ingresa mercadería.
5. Una redefinición del Detalle sigue anulando el override.

**Cómo queda registrado**, todo en el historial de la Orden y asociado al Detalle:

| Momento | Paso | Qué dice |
|---|---|---|
| Autorización | ACC-REP-049 | Usuario, fecha, motivo y, por insumo: requerido, disponible, se reserva y faltante |
| Inicio de la reparación | PROC-REP-185 | Si falta stock: «Reserva parcial por override, sin stock para el resto: INS-x reservado 1 de 3» |
| Fin de la reparación | PROC-REP-210 | Si se usó más de lo reservado: «Utilizado sin respaldo de stock (override): INS-x utilizado 3, descontado 1, sin respaldo 2» |

La Ejecución conserva lo que el técnico informó como utilizado; los movimientos de inventario, solo lo que se descontó.

**Diferencia con la especificación.** BR-REP-003 de la V1.4 limita el override al Coordinador RMA y acepta que la reserva exceda el disponible y que el consumo deje el stock físico en negativo. El MVP ya no hace ninguna de las dos cosas.

**Falta.**

1. Actualizar BR-REP-003 (y lo que la referencie en `rt-rma-app`) con esta regla.
2. Si en la realidad se usó una pieza que no estaba cargada en el sistema, el conteo físico va a diferir del sistema. Se corrige con un ajuste de inventario; definir si hace falta un procedimiento.
3. Sigue existiendo, fuera del override, un caso de stock negativo: el consumo de una reserva propia después de un ajuste manual que dejó el físico por debajo de lo reservado. No se cambió.

## P-07. Jerarquía y compatibilidad de insumos

Registrado el 19/11/2026 (Configuración v2): organizar los insumos por categorías y registrar su compatibilidad con varios modelos de equipo.

**Resuelto por DEC-AJ-14 (23/11/2026) e implementado en local** (`108840e`, `1bfe356`, `508cbaa` y `7fc4114`). Cada insumo es un SKU real con categoría y subcategoría, fabricante, variante y modelos compatibles (sin modelos, universal); el tipo declara sus insumos necesarios por categoría y la pieza concreta se elige antes de reservar. Detalle: [`ajustes-funcionales-discovery.md`](ajustes-funcionales-discovery.md), secciones 11.6 y 11.7. Lo que quedó afuera está en P-12 a P-15.

## P-08. Apartados 6 y 18 de los Términos y Condiciones

Registrado el 23/11/2026 (bloque 4 de los ajustes funcionales). **Pendiente de revisión del negocio, sin decidir.**

- **Apartado 6:** dice que los equipos que ingresan apagados no cuentan con garantía. Puede no coincidir con la regla vigente: sin check-in, el trabajo igual tiene garantía de 30 días.
- **Apartado 18:** cuenta sus plazos desde la notificación al cliente, que desde DEC-AJ-03 es opcional.

**Hoy.** Los dos apartados siguen igual en la versión 2 de los términos.

**Falta.** Que el negocio revise la redacción. Si cambia, se publica una versión nueva desde Configuración, sin cambiar código; si cambia una regla, se decide antes en `rt-rma-app`.

## P-09 a P-16. Seguimiento de la iteración 2 de los ajustes funcionales

Registrado el 24/11/2026. Lo implementado está en local (`feat/ajustes-funcionales-uat`); el detalle técnico, en [`ajustes-funcionales-discovery.md`](ajustes-funcionales-discovery.md), secciones 11.2 a 11.7. Ninguno bloquea la validación manual.

- **P-09. Motivo del ajuste comercial:** desde DEC-AJ-10 (D-10.5) ya no se imprime en los comprobantes nuevos (el PDF lo imprimía); queda en el registro interno. Confirmar con el negocio.
- **P-10. Revertir un retiro:** quitar un ajuste no se revierte; para volver a un ajuste quitado por error se aplica de nuevo. Decidir si alcanza.
- **P-11. Tope del importe fijo:** un ajuste de importe fijo mayor que su base (por ejemplo, después de bajar el precio en una redefinición) solo se rechaza al revertir o corregir; al aplicar rige la regla anterior. Decidir si se controla también al aplicar o al redefinir.
- **P-12. Pieza preferida:** no hay marca de pieza preferida por requisito ni sugerencia de un SKU en Compras para los trabajos sin pieza elegida; DEC-AJ-14 no lo pide.
- **P-13. Importación de la clasificación:** la categoría, el fabricante y la compatibilidad se cargan de a un insumo, con el filtro «Sin clasificar». Decidir si hace falta importarla antes de clasificar el stock real.
- **P-14. Reportes:** no hay consumo por categoría de insumo, y los reportes no distinguen el origen del precio (catálogo, manual, pendiente u «Otros») ni el modelo de la copia.
- **P-15. Stock mínimo por categoría y modelo:** el mínimo es por SKU (D-14.5); uno por categoría y modelo queda para después.
- **P-16. Precios multimarca:** la importación acepta solo modelos Apple (D-13.2). Definir sus particularidades antes de extenderla.

## Nota técnica: `capacidad` como texto

`Equipo.capacidad` se guarda como texto libre (por ejemplo «256 GB», copiado del catálogo de Ventas en las Órdenes anteriores). Se mantiene así por compatibilidad con las Órdenes existentes.

Al migrar a PostgreSQL conviene normalizarla, sin eliminar el campo ni el color:

- Una columna numérica en GB (`capacidad_gb`), con 1 TB = 1024 GB.
- La conversión de los valores existentes («128 GB», «1 TB»). Lo que no se pueda convertir queda en una columna de texto original para revisarlo, sin inventar valores.
- La validación de P-01 (obligatoria en RT_INTERNO) sobre la columna normalizada.

## Nota técnica: doble escritura de la Orden al cerrar una reparación

Riesgo anterior a P-06, detectado en la revisión del override (29/10/2026). Al cerrar una Ejecución, la Orden se guarda dos veces dentro de la misma operación:

1. Al aplicar el inventario (PROC-REP-210): primero el stock y después la Orden; si falla la Orden, el stock se restaura.
2. Después de recalcular la situación (PROC-REP-211).

Si falla solo la segunda escritura, la Orden queda con el inventario aplicado y sin el paso 211. Reintentar el cierre responde 409 porque la Ejecución ya está terminada. No se reprodujo sin forzar un fallo de disco.

**Falta.** Resolverlo con una transacción única (stock y Orden) al migrar a PostgreSQL.

## Nota técnica: foto subida cuya registración falla

Registrado en E1 de la integración con PostgreSQL (03/11/2026). Agregar una foto la sube primero al almacenamiento (GCS) y después la registra en la Orden, a propósito fuera de la transacción: una subida lenta no retiene bloqueos. Si la registración falla (Orden cerrada en el medio, conflicto, error de la base), la imagen queda en el bucket sin Orden.

Hoy la cubre la limpieza de huérfanas (Administración, `POST /api/maintenance/photos/cleanup`), que solo borra imágenes de más de una hora que ninguna Orden usa.

**Falta.** Tarea separada, no incluida en E1: borrar la imagen enseguida cuando la registración falla (compensación de mejor esfuerzo, fuera de la transacción), sin tapar el error original y conservando la limpieza como red.
