# Pendientes de producto

Decisiones de producto tomadas durante el UAT que todavía no están implementadas. Cada entrada dice qué está decidido, cómo está hoy y qué falta. No reemplaza al registro de decisiones funcionales de `rt-rma-app` (`business/decisions/`): si un pendiente cambia la definición funcional, se resuelve allí.

Registrado el 28/10/2026, con `mvp-v2` en `a8dd74b`.

| N.º | Pendiente | Área | Estado |
|---|---|---|---|
| P-01 | Buscador técnico en el alta RT_INTERNO, con GB y color obligatorios | Ingreso de equipos | Decidido, sin implementar |
| P-02 | Números de modelo del fabricante en el catálogo técnico | Catálogo técnico | Esperando información verificada |
| P-03 | Modelos de la línea iPhone 18 | Catálogo técnico | Excluidos hasta validar |
| P-04 | Garantía de 180 días en los Términos y Condiciones | Comprobante de entrega | Decisión pendiente |
| P-05 | Cláusulas sobre el retiro por terceros | Comprobante de entrega | Revisión pendiente |
| P-06 | Override por falta de stock: cualquier usuario y sin stock negativo | Inventario | Implementado en el MVP; falta actualizar BR-REP-003 |

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

**Falta.** Validar los nombres. Después, quitarla de `MODELOS_EXCLUIDOS` y regenerar: los modelos existentes conservan sus IDs.

## P-04. Garantía de 180 días en los Términos y Condiciones

**Pendiente de decisión.** El apartado 1 de los Términos y Condiciones del comprobante de entrega dice «una garantía de seis meses (180 días de corrido)». Se transcribió tal cual la hoja de Rosario Tecno, sin validar.

**Hoy.** El sistema asigna la garantía de cada trabajo según el check-in de la entrega: 90 días si se verificaron las funciones básicas y 30 si no, con ajuste manual. El comprobante de entrega y el certificado de garantía muestran ese plazo, que puede no coincidir con los 180 días del texto.

**Falta.** Decidir cuál rige y alinear el texto (`app/frontend/src/features/ordenes-reparacion/terminosCondiciones.ts`) o las reglas de garantía.

## P-05. Cláusulas sobre el retiro por terceros

**Pendiente de revisión.** El apartado 15 anula la garantía si el equipo lo retira un comisionista, tercero, mensajero o cualquier persona distinta del titular que hizo el ingreso, aun con autorización verbal o escrita. Se imprime resaltado. El apartado 14 dice que el equipo se entrega a la misma persona que lo dejó.

**Hoy.** La entrega registra quién retira y su identificación, pero no compara a esa persona con el titular ni cambia la garantía si es otra.

**Falta.** Revisar la redacción de los dos apartados y decidir si el sistema debe reflejarlos, por ejemplo con un aviso al registrar la entrega.

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

## Nota técnica: `capacidad` como texto

`Equipo.capacidad` se guarda como texto libre (por ejemplo «256 GB», copiado del catálogo de Ventas en las Órdenes anteriores). Se mantiene así por compatibilidad con las Órdenes existentes.

Al migrar a PostgreSQL conviene normalizarla, sin eliminar el campo ni el color:

- Una columna numérica en GB (`capacidad_gb`), con 1 TB = 1024 GB.
- La conversión de los valores existentes («128 GB», «1 TB»). Lo que no se pueda convertir queda en una columna de texto original para revisarlo, sin inventar valores.
- La validación de P-01 (obligatoria en RT_INTERNO) sobre la columna normalizada.
