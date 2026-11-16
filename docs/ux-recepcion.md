# Iteración de mejoras funcionales y UX de Recepción (16/11/2026)

Rama `feat/ux-recepcion` (sobre `mvp-v2` `614d167`) y `rt-rma-app` `spec/ux-recepcion` (sobre `9854046`: DEC-UX-01 a 12 en `a6ce997` y DEC-UX-13 y 14 en `ebd0840`). Cambios aprobados UX-01 a UX-12. Este documento registra el descubrimiento, el diseño de cada cambio, lo implementado y lo que queda pendiente; el estado del proyecto está en [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md). Nada desplegado: el UAT sigue en `00031-ror`, `dpl_7Zo4…` y 35 migraciones.

## 1. Descubrimiento

| # | Área | Cómo es hoy | Clasificación |
|---|---|---|---|
| 1 | Creación de la Orden | «Nueva orden» (modal) pide origen, cliente (DNI opcional con búsqueda), equipo (catálogo técnico o carga manual), IMEI, «Falla declarada» (obligatoria), «Estado físico», «Observaciones del equipo» y «Notas internas». Los trabajos se cargan después, en la Orden, y el comprobante de ingreso y autorización confirma la recepción (BR-REP-046) | Existente; los trabajos están en otra pantalla (UX-04) |
| 2 | Identidad del equipo | `Equipo.id` (`EQP-` + 12 hexadecimales, `rma.equipo.codigo` único) es el identificador interno de RMA, independiente del IMEI y del número de serie (DEC-MI-11). Sin IMEI ni serie se crea una identidad nueva. No se muestra en la Orden ni en el comprobante | Existente, oculto (UX-02) |
| 3 | Recepción | Tres textos visibles: `equipo.falla_reportada` (obligatoria en la API), `recepcion.estado_fisico` y `recepcion.observaciones`; más `notas_internas` (nunca en documentos) | Campos separados (UX-03) |
| 4 | Detalles | `POST /api/orders/{id}/details` en REQUERIMIENTO; la evaluación técnica, la autorización (comprobante de ingreso) y la reserva (al iniciar la Ejecución) siguen igual | Existente, en otra pantalla (UX-04) |
| 5 | Comprobantes | `GET …/documents/{id}/pdf` arma el PDF desde la copia guardada del documento (misma versión, mismo PDF; no registra nada). Solo «Descargar»; la firma (DEC-MI-06) está al final de «Documentos» | Falta «Imprimir» (UX-05); firma poco visible (UX-07) |
| 6 | Comprobante de recepción | Muestra cliente, teléfono, equipo, IMEI o serie, «Falla declarada», estado físico y observaciones. La copia del documento ya guarda el cliente completo (con DNI) y el Equipo (con su identificador), pero el PDF no los muestra; no tiene espacio para firmar | Faltan DNI, identificador y firma (UX-06) |
| 7 | Medios de pago | Catálogo `medio_pago` (5, sin configuración de importes). El pago guarda monto, medio y referencia; el saldo se calcula sobre los montos | Falta el recargo (UX-08) |
| 8 | Cancelaciones | «Cancelar la Orden» y «Cancelar el trabajo» son «situaciones especiales»: van a «Más acciones». Motivo obligatorio con catálogo y «Otro» (DEC-MI-15), DC31 y restricciones por estado en el backend | «Cancelar trabajo» mal ubicado (UX-09) |
| 9 | Resultado técnico | Repartido: hito `REPARACION_LISTA` (control aprobado), `finalizada_sin_reparacion` (revisión sin reparación, PROC-REP-069), estado de cada Detalle (completado, cancelado, descarte técnico) y control técnico. No hay un lugar que lo resuma | Existente, poco visible (UX-10) |
| 10 | WhatsApp asistido | Sección plegable «Comunicaciones», cerrada, al medio del cuerpo de la Orden (DEC-MI-08) | Existente, poco accesible (UX-11) |
| 11 | Cabecera | La barra superior usa como subtítulo cliente · teléfono · custodia · estado físico; con varias acciones se corta y compite con los botones | Sobrecargada (UX-12) |
| 12 | Catálogo de modelos Apple | Catálogo técnico propio de RMA (36 modelos, `app/datos/modelos_equipo.json`), generado una sola vez (`ef8f543`, 28/10/2026) con `scripts/generar_modelos_equipo.py` desde una exportación de Ventas del 21/10/2026 | Ver UX-01 |

## 2. Diseño por cambio

- **UX-01. Modelos.** No hay error de código: el catálogo es una foto de lo que Ventas tenía el 21/10/2026. Faltan (a) la línea iPhone 18, excluida a propósito hasta verificar sus nombres y variantes (420 filas en Ventas); (b) cualquier modelo que Ventas no tenía entonces o agregó después (el catálogo no se sincroniza); (c) los modelos que Ventas nunca vendió usados (por ejemplo iPhone 7 o SE de 2016). Mecanismo: volver a correr `generar_modelos_equipo.py` sobre una exportación nueva de Ventas (solo lectura, IDs estables, nada se duplica), verificar los nombres de la línea 18 y aplicar la carga actualizada del catálogo con autorización. Mientras tanto, la carga manual sigue disponible. **Sin cambios de código en esta iteración; pendiente la exportación y la verificación** (§3).
- **UX-02. Identificador interno.** Se reutiliza `Equipo.id`: no se crea otra identidad ni un IMEI ficticio. Se muestra como «Identificador del equipo» en la Orden y en el comprobante. La base ya impide duplicados (`equipo.codigo` único); se prueba con altas concurrentes. El IMEI real se asocia después con la corrección del ingreso (DEC-MI-07), que conserva el identificador y deja la corrección en el historial.
- **UX-03. Observaciones unificadas.** En el alta, un solo campo visible «Observaciones del equipo» (lo que declara el cliente, el problema, el estado estético y otras observaciones). Se guarda en `recepcion.observaciones` con la marca `observaciones_unificadas` y en la falla declarada del Equipo (`falla_reportada`, que el resto del sistema sigue usando). **No se copia al estado físico** (revisión del 16/11, sección 6): la marca es la adaptación explícita que permite que ese texto cumpla el requisito de describir cómo se recibió el equipo. La Orden y los documentos lo muestran una sola vez. Las Órdenes anteriores no cambian: la Orden y el comprobante muestran sus campos por separado, con sus nombres. Las notas internas siguen aparte. Sin columnas nuevas ni borradas.
- **UX-04. Trabajo inicial.** El alta ofrece «Trabajo inicial (opcional)» con los Tipos de Reparación. Después de crear la Orden se agrega ese Detalle con el comando existente: mismas validaciones, evaluación técnica, autorización y reserva. Sin trabajo, la Orden se crea igual (BR-REP-023).
- **UX-05. Imprimir.** Junto a «Descargar», «Imprimir» abre el diálogo de impresión con el mismo PDF (lectura: no emite ni duplica documentos).
- **UX-06. Comprobante.** El PDF suma DNI (si lo hay; si no, «sin DNI»), identificador del equipo y un recuadro de firma y aclaración del cliente. Antes de generar el comprobante, la pantalla avisa si el cliente no tiene DNI o si el DNI no es válido; no lo inventa ni bloquea.
- **UX-07. Firma.** Sigue opcional (DEC-MI-06). Después de generar el comprobante de ingreso se ofrece «Registrar firma» en el mismo lugar; la firma o la foto del papel firmado queda ligada al documento. Nunca bloquea.
- **UX-08. Recargo por medio de pago.** `medio_pago.recargo_porcentaje` (Administración lo configura; inicial: Transferencia 2 %). Al registrar un pago se calcula y se guarda en el pago, como copia, el porcentaje y el importe del recargo. El **importe del pago** (antes del recargo) es lo que se imputa al saldo de la Orden, como hasta ahora; el recargo se cobra aparte y se muestra: importe, porcentaje, recargo y total cobrado. Los pagos anteriores quedan con recargo cero. Ver §3 para lo que no está decidido.
- **UX-09. Cancelaciones.** «Cancelar la Orden» sigue en «Más acciones». «Cancelar el trabajo» sale de «Más acciones» y aparece en las acciones de cada trabajo. Mismo comando, motivo, catálogo, «Otro», DC31 y restricciones.
- **UX-10. Resultado técnico.** Un bloque «Resultado técnico» resume lo que ya existe (reparado, sin reparación, en curso; por trabajo: completado y aprobado, cancelado o descartado) y las acciones que corresponden. Sin estados nuevos.
- **UX-11. WhatsApp.** Un acceso «WhatsApp» en la barra de la Orden abre la sección de comunicaciones (plantillas, consentimiento, intentos y confirmación manual). Sin envíos automáticos.
- **UX-12. Cabecera.** La barra superior muestra el número de Orden, las acciones y, como texto secundario, solo nombre y teléfono del cliente. Custodia y observaciones quedan en el cuerpo («Cliente y equipo»). Se prueba en pantallas angostas.

## 3. Decisiones pendientes (no se inventan)

| Tema | Pregunta | Alternativas | Mientras tanto |
|---|---|---|---|
| UX-01 | Nombres y variantes de la línea iPhone 18 y modelos nuevos de Ventas | (a) regenerar desde una exportación nueva de Ventas con la línea 18 verificada; (b) que Administración pueda agregar modelos al catálogo técnico | Carga manual; ningún modelo inventado |
| UX-08 | ¿Se devuelve el recargo cuando se devuelve dinero? | (a) nunca (el recargo cubre el costo del medio); (b) en proporción a lo devuelto del pago; (c) a criterio, con motivo | Las devoluciones siguen sobre los importes imputados (sin recargo), como hasta ahora |
| UX-08 | ¿El recargo sale en el comprobante de la Orden o solo en el registro del pago? | (a) solo en el pago y en «Cobros»; (b) también en los comprobantes | Se muestra en «Cobros» y en el historial del pago; los comprobantes no cambian |
| UX-08 | ¿El recargo se calcula sobre un pago que salda una seña o un saldo a favor? | El recargo es del cobro, no de la Orden | Se calcula sobre cada pago registrado; no hay recargo sin pago |

## 4. Implementación

| UX | Commit | Qué quedó |
|---|---|---|
| UX-01 | - | Sin cambios de código (ABI-43). |
| UX-02 | `d0f7868`, `864c599` | Identificador `EQP-…` en la cabecera, en «Cliente y equipo» y en el PDF. Pruebas PostgreSQL: cinco altas simultáneas sin IMEI con identificadores distintos, `equipo.codigo` repetido rechazado por la base, IMEI real asociado después (antes de confirmar la recepción, ABI-41) conservando el identificador. |
| UX-03 | `d0f7868`, `864c599`, `3c96320`, `0a4c5ad` | Alta y corrección con un solo campo y la marca explícita; lo registrado antes sigue mostrando falla, estado físico y observaciones por separado. |
| UX-04 | `864c599`, `3c96320`, `0a4c5ad` | «Trabajo inicial (opcional)» con los Tipos activos, sin «Otros». Alta y trabajo en una sola transacción (sección 6). |
| UX-05 | `864c599` | «Imprimir» en el visor y en la lista de documentos: el mismo PDF por un marco oculto; si el navegador no lo permite, otra pestaña. |
| UX-06 | `d0f7868`, `864c599` | PDF con DNI (o «sin DNI»), identificador y recuadro «Conformidad del cliente» (firma, aclaración, DNI). Aviso previo si falta el DNI o no es válido; no bloquea. |
| UX-07 | `864c599` | «Registrar firma (opcional)» junto al comprobante de ingreso vigente, que preselecciona el documento en «Firmas». |
| UX-08 | `b39daea`, `864c599` | Migración `20261116000100` (aditiva): `medio_pago.recargo_porcentaje` (Transferencia 2,00), `pago.recargo_porcentaje` y `pago.recargo_importe` (0 en los anteriores), inmutables como el resto del pago; entidad de auditoría `MEDIO_PAGO`. `GET/PUT /api/admin/payment-methods`. Vista previa al cobrar, recargo en los movimientos y edición en Configuración > Parámetros. Completada por DEC-UX-13 y 14 (sección 6). |
| UX-09 | `864c599` | «Cancelar el trabajo» en cada trabajo (`organizarBarra` → `porTrabajo`); «Cancelar la Orden» sigue en «Más acciones». |
| UX-10 | `864c599` | «Resultado técnico» en la cabecera (reparado, sin reparación o cancelada, y el de cada trabajo cuando hay varios) con el paso siguiente. |
| UX-11 | `864c599`, `d9803fa` | Botón «WhatsApp» en la barra que abre «Comunicaciones» y la deja bajo la barra fija. |
| UX-12 | `864c599` | Subtítulo de la barra: nombre · teléfono. Probado a 1366 y 390 px. |

## 5. Validación

- **Backend:** pruebas nuevas `tests/test_recargo_medio_pago.py` (15), `tests/test_ux_recepcion.py` (7), `tests/postgres/test_recargo_medio_pago_postgres.py` (4) y `tests/postgres/test_ux_recepcion_postgres.py` (3). Resultados completos en [`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección B.
- **Frontend:** `tests/ux-recepcion.test.ts` (lógica pura de UX-03, 04, 06, 08, 10 y 12) y un caso nuevo de UX-09 en `tests/acciones.test.ts`.
- **Navegador** (Chromium con Playwright, 16/11/2026), contra un entorno local aislado: base `rma_ux` en el PostgreSQL de Docker con las 36 migraciones y las cargas de desarrollo, backend en `127.0.0.1:8000` y frontend en modo demo. Datos ficticios. Recorrido: alta con trabajo inicial y sin IMEI → comprobante (sin aviso, DNI válido) → «Imprimir» (el marco con el PDF se crea y sigue habiendo un documento) → PDF con DNI, identificador, observaciones una vez y recuadro de firma → «Registrar firma» con el documento preseleccionado → pago por Transferencia (vista previa 10.000 + 2 % = 10.200; saldo 70.000) → Administración cambia el recargo a 3 % (auditoría `2.00 → 3.00`; el pago anterior conserva 2 % y 200) → reparación lista: «Resultado técnico: Reparado · Sigue: Avisar al cliente» → «WhatsApp» abre Comunicaciones → «Cancelar el trabajo» abre su ventana con motivo (sin confirmar) → alta sin DNI y sin trabajo, con el aviso «sin DNI» antes del comprobante. Las capturas quedaron fuera del repositorio (carpeta temporal de la sesión).
- **Observaciones del recorrido, ajenas a esta iteración:** a 390 px el bloque «Pendientes» y la tabla de autorización desbordan unos píxeles a lo ancho (componentes no modificados); el diálogo real de impresión no se ve en un navegador sin interfaz. Ambos quedan para la pasada manual (P2-17).

## 6. Cierre de la iteración (16/11/2026)

Decisiones aprobadas el 16/11/2026 y revisión de dos riesgos. Commits `3c96320` (backend y migración `20261116000200`) y `0a4c5ad` (frontend); especificación en `rt-rma-app` `ebd0840`.

### ABI-45 → DEC-UX-13: recargo incorporado a los Detalles

- Cada pago guarda, como copia, porcentaje, importe y **reparto** de su recargo entre los Detalles elegibles: no cancelados, con peso = precio menos su propio Ajuste Comercial (el de la Orden no se prorratea, DEC-MI-03). Reparto en centavos exactos por resto mayor; ante un empate, el Detalle que viene antes (`app/domain/recargos.py`).
- Lo que se presenta: el recargo cobrado y no devuelto (`recargo_neto`), repartido con el mismo criterio entre los Detalles vigentes. El comprobante de cobro (entrega) muestra cada trabajo con `precio + recargo`, el total, cada pago con lo efectivamente cobrado y su medio, y el total cobrado. No hay una línea de recargo.
- **No hay un segundo saldo:** el saldo sigue siendo `Total − Pagado + Devuelto` sobre los importes base. El comprobante suma el recargo al total y a lo cobrado, así que el saldo presentado es el mismo.
- Los comprobantes ya emitidos no cambian; los anteriores no traen recargo y se ven igual. El de ingreso y autorización no es de cobro: muestra los precios autorizados.
- Ambigüedad resuelta sin reglas nuevas: una seña cobrada antes de definir los Detalles guarda su recargo sin reparto (no hay a quién asignarlo) y se presenta repartida al emitir el comprobante.

### ABI-44 → DEC-UX-14: devoluciones

- Cada devolución sigue atada a un solo pago y guarda `recargo_importe`: la parte del recargo de ese pago proporcional a lo devuelto, al centavo; la que completa el pago devuelve todo lo que queda. La base rechaza superar el recargo cobrado (`devolucion_dinero_validar`).
- El importe sigue siendo lo que se imputa al saldo a favor: los controles (crédito, disponible del pago, duplicados, motivo, permisos) no cambian. Como cada devolución es de un único pago, no hay devoluciones que agrupen medios distintos.

### Revisión de UX-03

La versión anterior copiaba el texto único al estado físico. Así presentaba la declaración del cliente como una constatación de Recepción. Ahora la recepción lleva la marca explícita `observaciones_unificadas`:

- el texto no se copia al estado físico;
- solo con la marca, ese texto cumple el requisito de describir cómo se recibió el equipo;
- sin la marca, el requisito sigue siendo el estado físico.

Columna nueva con `false` por defecto; no se borra nada.

### Revisión de UX-04

Antes eran dos llamadas, y si el trabajo fallaba quedaba la Orden sin él. Ahora `crear_orden` y `crear_orden_rt` agregan el trabajo con el mismo servicio de dominio (`definir_reparacion_detail`) dentro de la transacción del alta:

- si falla, no queda nada;
- el formulario conserva lo cargado;
- un reintento con resultado incierto reutiliza la clave de idempotencia, así que no se duplica.

### Validación en navegador

Contra el PostgreSQL local aislado, con datos ficticios:

1. **Alta:** con el texto único y trabajo inicial. Quedó un solo Detalle, la marca puesta y el estado físico vacío.
2. **Cobro:** de 200.000 por transferencia, con vista previa de 4.000 de recargo y 204.000 en total. Reparto guardado: 1.600 / 2.400, proporcional a 80.000 / 120.000.
3. **Comprobante de cobro:**
   - cambio de batería, 81.600;
   - cambio de placa, 122.400;
   - total final, 204.000;
   - pago por transferencia, 204.000;
   - total cobrado, 204.000;
   - saldo, 0;
   - sin línea de recargo.
4. **Devolución:** en otra Orden, con 200.000 pagados por transferencia y la placa cancelada. La vista previa marcó 120.000 + 2.400 = 122.400 y el backend registró lo mismo; quedaron 1.600 incorporados al trabajo vigente.
5. **PDF de ingreso:** «Observaciones del equipo» una sola vez, sin estado físico.
