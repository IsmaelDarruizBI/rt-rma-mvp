# Ajustes funcionales del feedback de UAT (BF-01 a BF-20): análisis y plan

> **Estado:** análisis del 23/11/2026, **sin implementar**. No hay código, migraciones ni cambios en `business/`.
>
> **Aprobado (23/11/2026):** la planificación general y la secuencia de los 8 bloques (sección 3).
>
> **Aprobado (23/11/2026):** D-01, alternativa B, y D-02, alternativa A (sección 4.1).
>
> **Bloque 1:** implementado en local, en espera de la validación manual (sección 8).
>
> **Pendiente:** D-07; no está aprobado que la verificación inicial sea solo informativa.
>
> **Rama:** `feat/ajustes-funcionales-uat`, desde `mvp-v2` `82ebbb6`, con 42 migraciones.
>
> **Referencias:** las de backend son relativas a `app/backend/app/` y las de frontend, a `app/frontend/src/`.
>
> **Fuera de alcance:** BF-03 (cerrado en Configuración v2), BF-10, BF-11, BF-13 y BF-16 (postergados).
>
> **Metodología:** la de la iteración:
> 1. análisis;
> 2. bloques con pruebas focalizadas;
> 3. validación manual en local;
> 4. ajustes;
> 5. QA integral y E2E;
> 6. UAT.

## Resumen

| | BF |
|---|---|
| **Ya cumple: solo verificar** | BF-12 (con dos brechas menores) y BF-17 |
| **Ajuste de algo que existe, sin migración** | BF-06, BF-07, BF-18 y BF-20 |
| **Ajuste con migración aditiva chica** | BF-08, BF-09 (si se guardan copias) y BF-15 |
| **Desarrollo nuevo con diseño previo** | BF-01, BF-02 y BF-14 |
| **Contradicen una regla aprobada:** primero la decisión en `rt-rma-app` y la copia de `business/` | BF-04 (BR-REP-046), BF-05 (DEC-UX-02 y BR-REP-022), BF-08 (BR-REP-045) y BF-20 (PROC-REP-260) |

**Datos que reordenan el plan:**

- **BF-04:** el texto libre ya existe (`falla_reportada`) y el Tipo ya es opcional al crear la Orden. Lo que bloquea es que el comprobante de ingreso exige al menos un trabajo.
- **BF-08:** la pregunta «¿se pudieron verificar las funcionalidades?» ya existe, pero **al entregar** (check-in de entrega, BR-REP-045), y de ella depende el plazo de la garantía.
- **BF-15:** no existe ningún stock mínimo.

## 1. Matriz de impacto

### BF-01. Tipos de Reparación separados del modelo, con precio por modelo

- **Hoy:**
  - `tipo_reparacion` es genérico, con un **precio único**, garantía, puntaje y Mesas (`m6_usuarios_configuracion.sql:107-117`). No tiene ninguna relación con `modelo_equipo`.
  - El modelo aparece solo en el **nombre** («Cambio batería iPhone 14»).
  - El precio del Detalle se copia del tipo (`services/reparaciones.py:314-354`; redefinición en `services/redefinicion.py:258-276`) a `detalle_version.precio` (BR-REP-015).
  - Los insumos previstos y las Mesas son por tipo.
- **Pedido:** un tipo de trabajo único con un precio por modelo.
- **Frontend:**
  - `features/configuracion/TiposReparacion.tsx`;
  - selectores de tipo en `AccionesOrden.tsx` (Detalle, adicional, redefinición);
  - trabajo inicial en `ListadoOrdenes.tsx`;
  - `PanelOrdenes.tsx`.
- **Backend:**
  - `api/configuracion.py:175-190` y `services/configuracion.py:86-130`, con el permiso `PRECIOS_GESTIONAR`;
  - `application/ingreso.py:215-226` y `application/evaluacion.py`;
  - `services/reparaciones.py` y `services/redefinicion.py`;
  - `services/inventario.py:43-52`, para los insumos previstos;
  - los adaptadores JSON y PostgreSQL de catálogos.
- **Tablas:**
  - nueva tabla de precio por (tipo, modelo);
  - CHECK de `cambio_configuracion.entidad`;
  - la vista `historial_precio`, que hoy lee solo `TIPO_REPARACION.precio`;
  - opcionalmente, el origen del precio en `detalle_version`.
- **Reglas:** BR-REP-015, BR-REP-040 (DC23 y DC23AUD), BR-REP-039 (DEC-CFG-03), BR-REP-011, BR-REP-041 (DEC-MI-01), BR-REP-047 («Otros») y DEC-UX-04.
- **Migración:** sí, aditiva. Los Detalles existentes conservan su copia del precio.
- **Riesgos:**
  - **Tipos actuales:** son «por modelo» y no se pueden borrar (`sin_borrado`); hay que desactivarlos y mapearlos a mano.
  - **Reportes:** agrupan por `tipo_reparacion_id` y mezclarían tipos viejos y nuevos.
  - **Equipos cargados a mano:** no tienen modelo técnico, así que no habría precio que resolver.
  - **Insumos previstos:** un tipo genérico reservaría una pieza equivocada (depende de BF-14).

### BF-02. Importación masiva de precios de iPhone

- **Hoy:** no hay importación de precios. Hay piezas reutilizables:
  - el lector de Sheets `integraciones/sheets.py`;
  - el adaptador CSV `integraciones/catalogo/archivo.py`;
  - el motor de sincronización `application/sincronizacion_origen.py`, que está pensado para copias que nunca borran, no para configuración auditada.

  No hay ninguna librería que lea Excel.
- **Pedido:** importar entre 300 y 400 precios, manteniendo la edición individual.
- **Frontend:** pantalla nueva en Configuración, con vista previa y confirmación.
- **Backend:** endpoint de administración con `PRECIOS_GESTIONAR`, que valida que el modelo y el tipo existan y que el precio tenga como máximo 2 decimales, aplica en una sola transacción y audita cada fila (`storage/postgres/configuracion.py:291`).
- **Tablas:** la de precio por (tipo, modelo), que define BF-01. Opcionalmente, un identificador de importación en la auditoría.
- **Migración:** no propia, depende de la de BF-01. La agrupación de la auditoría es opcional.
- **Riesgos:**
  - el emparejamiento por nombre no es confiable: `tipo_reparacion.nombre` no es único;
  - el catálogo tiene 36 modelos Apple y la línea iPhone 18 falta (P-03, ABI-43);
  - cada importación genera unas 400 filas de auditoría.
- **Recomendación:** **CSV exportado** de Excel o Sheets, con claves por código (`MOD-…` y `TR-…`). Evita agregar una dependencia para leer Excel y no depende de credenciales de Sheets.

### BF-04. Trabajo solicitado en texto libre al ingresar

- **Hoy:**
  - el alta exige `falla_reportada`, que se muestra como «Observaciones del equipo» unificadas (DEC-UX-03);
  - el Tipo es opcional («Trabajo inicial (opcional)»);
  - **sin trabajos no se puede generar el comprobante de ingreso y autorización ni confirmar la custodia por separado** (`services/reparaciones.py:162-176`, `application/acciones.py:464-487`). La única salida es «Enviar a revisión técnica» (PROC-REP-045 → 055 → 060), donde define el Técnico.
- **Pedido:** registrar en texto libre lo que pide el cliente, sin exigir un Tipo, y cargar los Detalles estandarizados después.
- **Frontend:** `ListadoOrdenes.tsx:559-724` (`CamposIngreso`), `recepcionUx.ts` y `DocumentosOrden.tsx:471-548`.
- **Backend:** `application/ingreso.py`, `application/ingreso_inicial.py`, `services/reparaciones.py:88-176`, `application/acciones.py:447-495` y `application/situacion.py`.
- **Tablas:** `orden.falla_reportada`, `recepcion.observaciones` y, si se decide, un campo nuevo «trabajo solicitado».
- **Reglas:** **BR-REP-046** (el comprobante de ingreso exige trabajos con precio), BR-REP-001, BR-REP-023, BR-REP-028, DEC-UX-03 y DEC-UX-04, y PROC-REP-032, 045, 046, 055, 075 y 129.
- **Migración:** no, si se reutiliza el texto; aditiva, si se quiere un campo aparte.
- **Riesgos:**
  - cambia la operación única de BR-REP-046, que confirma la recepción, autoriza y emite el comprobante;
  - un comprobante sin trabajos no tiene total autorizado.

### BF-05. Generador de IMEI provisorio

- **Hoy:**
  - el IMEI y la serie están en `equipo`, con copias en `orden`. No hay unicidad, formato ni verificación Luhn (`domain/identidad.py`);
  - un equipo sin IMEI usa el identificador interno `EQP-…`, impreso en la Orden y en el comprobante. **DEC-UX-02 y BR-REP-022: «nunca un IMEI ficticio»**;
  - corregir el IMEI solo se puede **antes de confirmar la recepción**, que en Cliente Externo ocurre al generar el comprobante (`services/custodia.py:280-326`, trigger `recepcion_decidida_no_cambia`, ABI-41).
- **Pedido:** un botón que genere un identificador provisorio único, distinguible del real y reemplazable después, sin perder la trazabilidad.
- **Opciones:**
  - **(a)** El botón usa o muestra el `EQP-…` que ya existe. Sin migración, cumple DEC-UX-02.
  - **(b)** Un campo nuevo para el identificador provisorio, que nunca participe en la identificación ni en los antecedentes. Migración aditiva.
  - **(c)** Guardarlo en `imei` sin marca: **no recomendable**, porque contamina la identificación, los antecedentes y las búsquedas.
- **Frontend:** `ListadoOrdenes.tsx:639-666`, `IdentidadEquipo.tsx`, `CustodiaOrden.tsx` y `AntecedentesEquipo.tsx`.
- **Backend:** `application/identidad.py`, `domain/identidad.py`, `services/custodia.py` y `services/identidad.py` (`correccion_vinculo_equipo`, que corrige el vínculo, no el IMEI).
- **Migración:** depende de la opción.
- **Riesgos:**
  - reemplazar el IMEI después de la custodia exige revisar ABI-41 y el trigger;
  - el IMEI va en las URL de identificación y antecedentes, igual que en P1-18.

### BF-06. Simplificar la autorización y la impresión del comprobante de ingreso

- **Hoy:** son cuatro pasos:
  1. alta en una ventana;
  2. en «Documentos», elegir el canal («El cliente autorizó», presencial por defecto) y generar. Ese comando confirma la custodia, autoriza y emite (`application/ingreso_inicial.py:70-136`);
  3. el visor se abre solo, con Descargar, Imprimir y WhatsApp (`DocumentosOrden.tsx:197-204, 554-629`);
  4. la firma, que es opcional.

  Solo hay un «¿Confirmás…?» en las autorizaciones posteriores y en los desistimientos.
- **Pedido:** menos pasos y ofrecer la impresión apenas se genera, conservando las reglas y la evidencia.
- **Frontend:** `PanelOrdenes.tsx`, `DocumentosOrden.tsx`, `lib/impresion.ts`, `FirmasDocumentos.tsx` y `AccionesOrden.tsx`.
- **Backend:** no cambia. Una acción «Crear y generar comprobante» encadena dos comandos que ya son idempotentes (`POST /api/orders` y `POST /documents/intake-receipt`).
- **Migración:** no.
- **Riesgos:**
  - el navegador puede bloquear `window.print()` después de una llamada asíncrona. Conviene imprimir con un gesto del usuario en el visor;
  - si falla la emisión, la Orden ya quedó creada;
  - el canal de la autorización es un dato de BR-REP-028: no se puede quitar, solo dejar uno por defecto.

### BF-07. Detalle de la Orden simplificado para Recepción

- **Hoy:** todas las secciones se ven para todos los roles:
  - trabajos con ejecuciones e insumos previstos (`DetalleOrden.tsx:483-511`);
  - antecedentes;
  - ejecuciones, insumos y devoluciones;
  - historial y datos técnicos;
  - el bloque «Resultado técnico».

  El frontend ya recibe los roles y los permisos (`lib/roles.ts:38-46`) y existe `ABIERTA_POR_ROL` (`PanelOrdenes.tsx:142`).
- **Pedido:** ocultar a Recepción la información técnica, mantenerla en Taller según los permisos, y no tocar datos ni endpoints.
- **Frontend:** `PanelOrdenes.tsx` y `DetalleOrden.tsx`.
- **Backend:** nada. Si se elige un permiso configurable, va en `services/permisos.py` y no necesita filas.
- **Migración:** no.
- **Riesgos:**
  - **no** quitar `ANTECEDENTES_CONSULTAR` a Recepción: protege `/equipment/identify`, que usa el alta;
  - «Corregir la identidad» está dentro de Antecedentes y hay que moverla a un lugar visible para Recepción;
  - los usuarios con varios roles tienen que ver la unión de lo que ve cada rol.

### BF-08. Verificación inicial de funcionalidades (Sí o No)

- **Hoy:**
  - el check-in es **de entrega** (BR-REP-045: «registra si se pudieron verificar las funciones básicas: realizado o no realizado», antes de entregar);
  - **su valor fija el plazo de la garantía** del Detalle (`garantia_con_checkin` o `garantia_sin_checkin`, `services/reparaciones.py:307,333-336`) y es un requisito para entregar (`services/garantias.py:94-101`);
  - existe una columna anterior `recepcion.checkin_ingreso` que la lectura todavía considera (`ordenes_lectura.py:1041`);
  - el checklist DC12 está inactivo (ABI-42).
- **Pedido:** al ingresar, preguntar «¿Se pudieron verificar las funcionalidades?» Sí o No, con observaciones opcionales, sin cambiar el alcance de la garantía.
- **Frontend:** `CamposIngreso`, `CustodiaOrden.tsx` y el PDF de ingreso (`DocumentosOrden.tsx:1043-1066`).
- **Backend:** `DatosRecepcionIn` (`api/schemas.py:330`), `services/custodia.py` y `storage/postgres/ordenes.py:621-641`.
- **Tablas:** `recepcion`, con dos columnas nuevas (verificación y observaciones). `recepcion_version` las guarda en su copia.
- **Migración:** sí, aditiva. **No reutilizar `checkin_ingreso` ni `DatosRecepcion.checkin`**: cambiaría la garantía y daría por hecho el check-in de entrega.
- **Riesgos:** confundirla con el check-in de entrega en pantallas, PDF y avisos de faltantes. Después de la custodia, la recepción no se edita.

### BF-09. Descuentos justificados

- **Hoy:** descuento y cortesía **ya son una sola entidad**, el ajuste comercial:
  - `rma.descuento` con `clase` DESCUENTO o CORTESIA, `tipo` PORCENTAJE o IMPORTE, motivo obligatorio, usuario, fecha y `detalle_id` opcional (`m4_finanzas_documentos.sql:158-185`; `it1_alineacion_v14.sql:94-99`; `ajuste_por_detalle.sql`);
  - es inmutable y solo admite agregar registros: cambiar o quitar un ajuste es un registro nuevo, y rige el último;
  - se calcula en `v_orden_saldo` y, duplicado, en `domain/models/orden_reparacion.py:188-319`;
  - los permisos `DESCUENTO` y `CORTESIA` están separados (BR-REP-039, DEC-IT1-02, DEC-MI-03);
  - solo se puede ajustar antes de la entrega (`services/descuentos.py:53-62`).
- **Pedido:** registrar el precio original, el ajuste, el motivo, el usuario, la fecha y el precio final, y poder corregir o revertir con trazabilidad.
- **Brechas:**
  - no se guardan como copia el precio original, el importe aplicado ni el final: se derivan;
  - una corrección no se distingue de un cambio comercial ni queda enlazada al registro que corrige;
  - no se puede corregir después de la entrega;
  - `EV-REP-041` está definido y nunca se emite;
  - hay dos o tres formularios separados (`PagosOrden.tsx:247, 385-500, 1136-1210`);
  - los documentos no muestran usuario, fecha ni precio final por Detalle.
- **Backend:** `api/ordenes.py:1400-1424`, `application/finanzas.py:144-177`, `services/descuentos.py`, `storage/postgres/ordenes.py:2234-2263` y `services/documentos.py:395-432`.
- **Migración:** no, si alcanza con derivar los valores y cambiar la interfaz y los documentos. Aditiva (columnas opcionales en `descuento` para la copia y el vínculo de corrección), si se guardan.
- **Riesgos:**
  - **cálculo duplicado:** la vista SQL y el dominio calculan lo mismo, y tienen que cambiar juntos;
  - **recargo:** el recargo de un pago se reparte con los ajustes actuales, así que un ajuste posterior cambia el reparto que se muestra (DEC-UX-13);
  - **comprobante:** cada cambio genera una versión nueva del comprobante de autorización.

### BF-12. Autorización de trabajos adicionales: verificación

- **Cumple de punta a punta en Cliente Externo:**
  - el técnico propone el adicional, que nace pendiente (`services/reparaciones.py:477-555`);
  - la tarea aparece en la bandeja de autorizaciones de Recepción, también con una ejecución en curso (`application/bandejas.py:625-631`);
  - Recepción registra la decisión (`services/decision_cliente.py:184-223`);
  - sin autorización no se selecciona, no se reserva ni se inicia (`services/tomas.py:349`, `services/ejecuciones.py:227`, `application/autorizacion_cliente.py:156-189`);
  - lo cubren `test_macro_v14.py:347-491`, `test_autorizacion_cliente.py:335-357, 604-635`, `test_bandejas.py` y `postgres/test_macro_v14_postgres.py`.
- **Brechas menores:**
  - el filtro «Pendientes de mi sector» del listado usa solo el rol de la tarea principal (`application/situacion.py:270-325`). Con una ejecución activa, el aviso de autorización probablemente no suma a Recepción. Hay que verificarlo y corregirlo;
  - no hay un test que recorra de una sola vez el adicional del técnico, la bandeja, el 409 y la autorización.
- **Alcance:** BR-REP-032 limita la espera de autorización a Cliente Externo. En RT_INTERNO y en garantía, el adicional no espera.
- **Migración:** no.

### BF-14. Jerarquía de insumos

- **Hoy:**
  - `insumo` tiene código, nombre, unidad, saldos que solo mueve el libro, control SIN_LOTE, LOTE o SERIE, y precio (`m3_insumos.sql`, `lotes_inventario.sql:28-36`);
  - hay lotes inmutables y el libro `movimiento_inventario` (reserva, consumo y desperdicio);
  - `ejecucion_insumo` registra el desperdicio y el lote, y Compras registra el costo por línea;
  - no hay categoría ni compatibilidad con modelos (P-07, BR-REP-049).
- **Alternativas, sin decidir.** En las tres, **el stock sigue en la fila actual de `insumo`**:
  - **A. Insumo = pieza física concreta.** Categoría, subcategoría, marca y variante como atributos o catálogos, más una tabla de compatibilidad insumo–modelo.
    - A favor: es aditiva y no toca el libro, los lotes ni Compras.
    - En contra: muchos insumos, y los insumos previstos tienen que elegir entre las piezas compatibles.
  - **B. Producto genérico con variantes que llevan stock.** Los insumos previstos apuntan al genérico y se elige la variante al reservar.
    - A favor: distingue bien costo y desperdicio por pieza real.
    - En contra: hay que resolver qué variante se reserva, y es más compleja.
  - **C. Atributos flexibles** sobre el insumo actual.
    - A favor: es la más barata.
    - En contra: la integridad es débil y los reportes son difíciles.
- **Frontend:** `features/configuracion/Insumos.tsx`, `features/inventario/Inventario.tsx` y `features/compras/Compras.tsx`.
- **Backend:** `api/configuracion.py:370-411`, `services/operativa.py:202-240` y `storage/postgres/catalogos.py`.
- **Migración:** sí, en cualquiera de las tres.
- **Riesgos:** el stock, las reservas y los lotes actuales quedan sin clasificar. Repartir saldos (en B) exige movimientos nuevos, porque el libro es inmutable.

### BF-15. Alertas de stock mínimo

- **Hoy:** **no existe**. Solo están el filtro «Solo faltantes» (`api/inventario.py:51-61`, `Inventario.tsx:341-354`) y las sugerencias de compra por demanda (`services/compras.py:154-182`). P2-16 lo registra.
- **Pedido:** un mínimo configurable por insumo, con alertas visibles y sin duplicar mecanismos.
- **Tablas:** `insumo.stock_minimo`, auditado con la entidad INSUMO, que ya está en el CHECK.
- **Migración:** sí, una columna opcional.
- **Nota:** como en las tres alternativas de BF-14 el stock sigue por insumo, **el mínimo por insumo no queda descartado por BF-14**. Se puede hacer antes.
- **Riesgos:** pocos. No genera compras automáticas (DEC-MI-09).

### BF-17. La garantía empieza en la entrega efectiva: verificación

- **Ya cumple:**
  - el vencimiento suma el plazo al día local de la entrega (`domain/garantia.py:46-60`);
  - el comprobante final, el certificado, el reclamo RMA y `{garantia_hasta}` usan la fecha de la salida (`services/documentos.py:515-519, 602-614`, `services/ordenes.py:383-430`);
  - BR-REP-041: «nunca desde la creación ni la finalización técnica».
- **Inconsistencia menor:**
  - `services/documentos.py` no usa la misma caída al historial que `fecha_de_entrega()`. Afecta solo a Órdenes viejas;
  - el texto de Términos dice 180 días (P-04), un plazo distinto del de 90/30 días del sistema.
- **Migración:** no.

### BF-18. Simplificar el cierre y la entrega

- **Hoy:** control → **aviso obligatorio** → pago (saldo 0) → check-in, como acción aparte → custodia confirmada → quién retira → confirmación → comprobante final, certificado de garantía y Términos.
- **Qué sobra:**
  - **El aviso obligatorio:** es BF-20.
  - **Validaciones repetidas en la misma operación:**
    - el rol, dos veces;
    - `lista_para_cierre`, tres veces;
    - `current_process == 265`, dos veces;
    - `condicion_entrega_cumplida`, tres veces;
    - la verificación de los documentos justo después de generarlos (`application/cierre.py`, `services/documentos.py:233-245`, `services/ordenes.py:1240-1262`).
  - **El check-in fuera del formulario de entrega.**
  - **La custodia no se informa como bloqueo:** el frontend la deduce por su cuenta.
  - **Documentos que se superponen:** el comprobante final ya lista la garantía y el vencimiento de cada trabajo, y además se emiten el certificado y los Términos.
  - **Nodos no registrados:** 268 y 269 no quedan en el historial.
- **Hay que conservar:** BR-REP-017 y 038 (saldo exactamente 0), BR-REP-045 (check-in), BR-REP-033 (custodia), BR-REP-031 (versiones) y PROC-REP-265, 280 y 270.
- **Frontend:** `AccionesOrden.tsx:997-1133` (`FormularioEntrega`, `FormularioCheckin`), `PagosOrden.tsx`, `DocumentosOrden.tsx`, `ProximoPaso.tsx` y `RetiroDemorado.tsx`.
- **Backend:** `application/cierre.py`, `services/pagos.py`, `services/garantias.py`, `services/custodia.py` y `application/documentos.py`.
- **Migración:** no, salvo que se unifiquen tipos de documento.
- **Riesgos:** los documentos emitidos son inmutables, y los tests de servicios llaman a la entrega y al comprobante por separado.

### BF-19. Personalizar los comprobantes

- **Hoy:**
  - `rma.empresa` ya tiene nombre, razón social, CUIT, dirección, teléfono, email y condiciones, pero **solo se cargó el nombre** y **no hay API ni pantalla** para editarla. Se copia al snapshot del documento (`services/documentos.py:309-328`);
  - las leyendas están fijas en el código (`services/documentos.py:112-131`) y los Términos, en el frontend (`terminosCondiciones.ts`). `rma.texto_legal` existe, pero nadie la lee;
  - **quién retira:** `rma.salida` ya tiene `retira_telefono` y `retira_vinculo` (TITULAR, EMPLEADO_REPRESENTANTE, TERCERO, GESTION_RT), pero **no se escriben** (`storage/postgres/ordenes.py:272-281`), y la interfaz solo ofrece «Retira el titular».
- **Pedido:** nombre comercial, dirección, teléfono, datos operativos, condiciones de garantía e identificación de quien retira, incluidos terceros.
- **Frontend:** `DocumentosOrden.tsx` (`HojaDocumento` y los cuerpos de ingreso, entrega y garantía), `terminosCondiciones.ts`, `Configuracion.tsx` y el formulario de entrega.
- **Backend:** API y servicio nuevos para la empresa, con auditoría; `application/documentos.py`, `application/documentos_pdf.py`, `domain/models/documentos.py:164-300` y la escritura de `salida`.
- **Migración:** no, para quien retira y los datos que ya existen en `empresa`. Aditiva, si se agregan campos como el horario o versiones de otros textos legales (CHECK de `texto_legal.tipo`).
- **Riesgos:** los snapshots ya emitidos no cambian. Los campos nuevos tienen que ser opcionales, para seguir leyendo los JSON viejos.

### BF-20. Avisar al cliente deja de ser obligatorio para entregar

- **Hoy:** el aviso habilita la entrega en tres puntos:
  - ENTREGAR solo se ofrece si la Orden fue «notificada» (`application/acciones.py:693-741`);
  - la entrega y el comprobante final exigen `current_process == PROC-REP-265` (`application/cierre.py:290-295`, `services/documentos.py:239-244`);
  - a 265 solo se llega por `notificar` (`application/cierre.py:138-165`).

  Además:
  - el botón Notificar registra el paso 260 sin mensaje, y Comunicaciones (WhatsApp asistido) nunca registra 260;
  - el retiro demorado cuenta desde 260 (`domain/retiro.py:13-40`, DEC-MI-14).
- **Pedido:** el aviso pasa a ser una acción opcional y registrable, y la entrega deja de depender de él, conservando la trazabilidad de las comunicaciones.
- **Frontend:** `AccionesOrden.tsx:648-663`, `PanelOrdenes.tsx`, `ComunicacionesOrden.tsx`, `RetiroDemorado.tsx`, `etiquetas.ts`, la situación (`application/situacion.py:578-671`, PENDIENTE_NOTIFICACION) y las bandejas (`application/bandejas.py:641-673`).
- **Backend:** `application/cierre.py`, `application/acciones.py`, `services/ordenes.py:1173-1295`, `services/pagos.py:613-684`, `application/finanzas.py:45-72` y `application/progreso.py`.
- **Reglas:** **PROC-REP-260** («no hay un camino alternativo que la evite»), PROC-REP-250 y 265, BR-REP-017, BR-REP-033, BR-REP-043 y 044, DEC-MI-08, DEC-MI-14 y HP-REP-001.
- **Migración:** no.
- **Riesgos:**
  - **28 archivos de tests** nombran 260 o `notificar` (entre otros `test_caracterizacion_hp1.py`, `test_hp_rep_001_*`, `test_api_hp_rep_003.py` y `test_api_sin_reparacion.py`);
  - las Órdenes que hoy están en 240 sin aviso pasarían a ofrecer la entrega;
  - SIN_REPARACION y la garantía RMA también pasan por 260;
  - el camino RT (INFORMAR_RT → DEVOLVER_RT) es otro nodo (290).

## 2. Dependencias

| Dependencia | Por qué |
|---|---|
| BF-02 → BF-01 | Se importa la tabla de precio por (tipo, modelo) |
| BF-01 ↔ BF-14 | Un tipo genérico necesita la compatibilidad insumo–modelo para prever y reservar la pieza correcta (BR-REP-002 y 005) |
| BF-15 ⟂ BF-14 | Independiente: el mínimo va en el insumo con stock, igual en las tres alternativas |
| BF-04 → BF-06 | Sin trabajos no hay comprobante de ingreso y autorización: qué se imprime depende de BF-04 |
| BF-05 ↔ BF-06 | Generar el comprobante confirma la custodia y hoy congela el IMEI (ABI-41) |
| BF-08 ↔ BF-04, BF-06 | La respuesta se registra antes de la custodia y puede ir al comprobante |
| BF-07 ↔ BF-05 | La corrección de identidad está en Antecedentes, y el alta necesita `ANTECEDENTES_CONSULTAR` |
| BF-20 ⊂ BF-18 | Tocan las mismas compuertas (`application/cierre.py`, `acciones.py` y `situacion.py`): van juntos |
| BF-18 → BF-17 | Al reorganizar la entrega, la garantía sigue empezando en la salida registrada |
| BF-19 → BF-18, BF-04 | Quien retira se carga en la entrega, y el comprobante de ingreso depende de BF-04 |
| BF-09 ⟂ resto | Independiente. Se cruza con el recargo (DEC-UX-13) y con BF-01 (redefinición con otro precio) |

## 3. Bloques y orden recomendado

| # | Bloque | BF | Migración | ¿Necesita una decisión en `business/`? | Por qué en ese lugar |
|---|---|---|---|---|---|
| **1** | Recepción sin ruido y verificaciones | BF-07, BF-12 (filtro «Pendientes de mi sector» y un test de punta a punta) y BF-17 (consistencia de la fecha) | No | No | Valor inmediato y riesgo bajo; no espera decisiones |
| **2** | Entrega sin aviso obligatorio y cierre simplificado | BF-20 y BF-18 | No | **Sí** (PROC-REP-260) | El mayor ahorro de pasos. Tiene que pasar antes de BF-19 |
| **3** | Ingreso de la Orden | BF-04, BF-08, BF-06 y BF-05 | Aditiva (BF-08; quizás BF-04 y BF-05) | **Sí** (BR-REP-046, BR-REP-045 y DEC-UX-02) | Comparten el formulario y el comprobante de ingreso |
| **4** | Comprobantes | BF-19 | Opcional | Solo P-04 y P-05 | Usa el formulario de entrega del bloque 2 y el comprobante de ingreso del bloque 3 |
| **5** | Ajustes comerciales | BF-09 | Opcional | Quizás (permisos y corrección después de la entrega) | Independiente; cuida pagos y saldo |
| **6** | Stock mínimo | BF-15 | Sí, una columna | No | Chico e independiente de BF-14 |
| **7** | Tipos y precios por modelo | BF-01 y BF-02 | Sí | Sí (modelo de precios) | Cambia el catálogo central; requiere el diseño cerrado |
| **8** | Jerarquía de insumos | BF-14 | Sí | Sí (alternativa) | Transversal: inventario, Compras, reservas y BF-01 |

Los bloques 7 y 8 conviene **diseñarlos juntos**, aunque se implementen en este orden. Los bloques 1, 5 y 6 pueden avanzar mientras se resuelven las decisiones de los bloques 2 y 3.

## 4. Decisiones que bloquean

Solo las que hay que resolver antes de implementar cada bloque. Las de los bloques 2 y 3 cambian reglas aprobadas: se registran en `rt-rma-app` y se sincroniza `business/` antes del código.

**Bloque 1**

- **D-01 (BF-07):** cómo se oculta la información técnica a Recepción. En revisión: sección 4.1.
- **D-02 (BF-12):** en qué orígenes un trabajo adicional espera la autorización del cliente. En revisión: sección 4.1.

**Bloque 2**

- **D-03 (BF-20):** decisión que reemplaza «no hay un camino alternativo» en PROC-REP-260. Hay que definir:
  - (a) si el camino RT (INFORMAR_RT → DEVOLVER_RT) queda fuera. **Propuesta:** sí, porque es trazabilidad hacia Gestión RT;
  - (b) si aplica también a SIN_REPARACION y a la garantía RMA;
  - (c) desde cuándo corre el retiro demorado cuando no hubo aviso: desde la reparación lista o no corre;
  - (d) si una comunicación «equipo listo» confirmada como enviada registra el aviso (260).
- **D-04 (BF-18):** dos puntos:
  - ¿un solo comprobante de entrega con la garantía incluida, o se mantienen el comprobante final y el certificado?
  - ¿el check-in se registra dentro del formulario de entrega?

**Bloque 3**

- **D-05 (BF-04):** sin trabajos al ingresar:
  - ¿qué documento se entrega (comprobante de ingreso sin autorización o el de recepción) y cuándo se confirma la custodia?
  - ¿los trabajos los carga después Recepción o el Técnico?
  - ¿el pedido va en un campo nuevo «Trabajo solicitado» o en las observaciones actuales?
- **D-06 (BF-05):** revisar DEC-UX-02, que dice «nunca un IMEI ficticio». Hay que definir:
  - la opción (a), (b) o (c);
  - el formato del provisorio;
  - quién y hasta cuándo reemplaza el provisorio por el IMEI real después de la custodia (ABI-41).
- **D-07 (BF-08):** la misma pregunta ya es el check-in de entrega (BR-REP-045), que fija la garantía. Hay que definir:
  - si la de ingreso es **solo informativa** (sin efecto en la garantía ni en el check-in de entrega), o si reemplaza, anticipa o condiciona al de entrega y al plazo de la garantía. **Pendiente (23/11/2026):** no se aprobó que sea solo informativa. Se decide antes del bloque 3, junto con BR-REP-045 y la configuración de garantía con y sin check-in, cuyo alcance no cambia;
  - si es obligatoria;
  - si va en el comprobante.
- **D-08 (BF-06):** ¿qué confirmación es la redundante? El canal (BR-REP-028) no se puede quitar, solo dejar uno por defecto. Depende de D-05.

**Bloque 4**

- **D-09 (BF-19):**
  - qué son los «datos operativos», por ejemplo el horario;
  - dónde van las condiciones de garantía: texto de la empresa, por Tipo o en los Términos;
  - P-04: ¿rigen los 180 días del texto o los 90/30 del sistema?;
  - P-05: el retiro por un tercero, ¿anula la garantía o solo genera un aviso?;
  - ¿el vínculo de quien retira es obligatorio?

**Bloque 5**

- **D-10 (BF-09):**
  - ¿«unificar» incluye fusionar los permisos DESCUENTO y CORTESIA (BR-REP-039)?
  - ¿se puede corregir después de la entrega o el cierre?
  - ¿la corrección por error es un acto distinto, con su propio permiso, como la anulación de pagos?
  - ¿el precio final se guarda como copia?
  - ¿el comprobante muestra usuario y fecha del ajuste?

**Bloque 6**

- **D-11 (BF-15):** ¿el mínimo se compara con lo disponible o con el stock físico? ¿Dónde se avisa: Inventario, el menú o Inicio de Administración?

**Bloques 7 y 8**

- **D-12 (BF-01):**
  - qué hacer sin modelo o sin precio para el modelo: precio base del tipo, precio manual o bloqueo;
  - si garantía, puntaje y Mesas son del tipo o también del modelo;
  - si los insumos previstos son por (tipo, modelo);
  - cómo se convierten los tipos actuales «por modelo»;
  - qué efecto tiene un cambio de modelo del equipo sobre el precio.
- **D-13 (BF-02):**
  - formato y claves de la planilla. **Propuesta:** CSV con códigos;
  - si la importación crea tipos o modelos, o solo actualiza precios;
  - si una fila inválida rechaza toda la importación o solo esa fila.
- **D-14 (BF-14):**
  - alternativa A, B o C;
  - si el «tipo específico» tiene stock propio;
  - si marca y variante cambian el costo o la garantía;
  - si la reserva es por pieza concreta o por genérico compatible.

### 4.1 D-01 y D-02 en detalle (aprobadas el 23/11/2026)

#### D-01 (BF-07). Información técnica en el detalle de la Orden

**Hoy:**

- Todas las secciones de la Orden se ven igual para todos los roles (`features/ordenes-reparacion/PanelOrdenes.tsx`):
  - Trabajos;
  - Antecedentes del equipo;
  - Comunicaciones;
  - Cliente y equipo;
  - Fotos;
  - Autorización del cliente;
  - Ejecuciones e insumos, con sus devoluciones;
  - Cobros;
  - Documentos;
  - «Historial y datos técnicos», con los bloques Datos técnicos, Recorrido técnico del proceso, Ejecuciones (técnico) e Historial.
- Dentro de Trabajos, cada Detalle muestra el «Resultado técnico» y los «Insumos previstos» (`DetalleOrden.tsx:238, 485`).
- Lo único que depende del rol es qué sección se abre sola: Administración abre Cobros (`ABIERTA_POR_ROL`, `PanelOrdenes.tsx:142`).
- Los permisos ya llegan al frontend y se consultan con `puede()` (`lib/roles.ts`).
- Las consultas configurables (DC27B, grupo «Consultas» de `services/permisos.py:526-577`) se declaran solo en el código: sin una fila en `rma.permiso` rige el valor predeterminado, así que no hace falta migración (igual que en `20261120000200_permisos_operativos.sql`).

**Alternativas:**

| | Alternativa | Consecuencias |
|---|---|---|
| A | **Por rol fijo:** quien solo tiene el rol Recepción no ve lo técnico | Es lo más simple. No se puede ajustar desde Configuración. Si una persona de Recepción necesita verlo, hay que darle el rol Técnico, que también le habilita acciones técnicas. Con varios roles se aplica la unión |
| B | **Permiso de consulta configurable nuevo,** `DETALLE_TECNICO_CONSULTAR` («Consultar la información técnica de la Orden»), en «Consultas», con Técnico, Coordinación RMA y Administración como roles predeterminados | Administración puede habilitarlo para Recepción desde Configuración, con auditoría. Es coherente con DC27B y con CFG-02 y CFG-03, y no requiere migración. Suma un permiso a la pantalla de permisos |
| C | **Secciones plegadas para Recepción,** con un «Ver información técnica» que las despliega | No oculta: reduce el ruido, pero la información sigue a un clic, así que no cumple del todo BF-07. No requiere permisos ni migración |

**En cualquiera de las tres:**

- es un cambio **de presentación**: los datos siguen viniendo en la respuesta de la API y los endpoints no cambian, como pide BF-07. **No es un control de seguridad**;
- `ANTECEDENTES_CONSULTAR` **no se toca**: el alta lo usa para identificar el equipo (`/api/equipment/identify`).

**Propuesta: B.**

Qué se oculta **sin el permiso**:

- la sección «Antecedentes del equipo». «Corregir la identidad», que hoy vive ahí, pasa a «Cliente y equipo», porque Recepción la usa;
- la sección «Ejecuciones e insumos», con sus devoluciones de insumo;
- los «Insumos previstos» de cada Detalle;
- de «Historial y datos técnicos», los bloques Datos técnicos, Recorrido técnico del proceso y Ejecuciones (técnico).

Qué sigue visible para Recepción:

- Trabajos: tipo, precio, estado, autorización y **Resultado técnico**, que Recepción necesita para avisar y entregar, por ejemplo si quedó sin reparar;
- Cliente y equipo, Fotos, Autorización, Comunicaciones, Cobros y Documentos;
- el bloque **Historial**, que pasa a una sección propia «Historial»: quién hizo qué y cuándo, sin datos técnicos.

**Puntos a confirmar dentro de D-01:**

- (i) que el Resultado técnico siga visible;
- (ii) que el Historial de eventos siga visible;
- (iii) que las devoluciones de insumo se oculten;
- (iv) que Recepción deje de ver los antecedentes en el detalle de la Orden. La identificación del equipo al ingresar no cambia.

#### D-02 (BF-12). En qué orígenes espera la autorización un trabajo adicional

**Hoy:**

- BR-REP-032 dice que en CLIENTE_EXTERNO el adicional queda PENDIENTE_AUTORIZACION: el técnico no puede empezarlo, Recepción consulta al cliente y registra la decisión.
- El código lo aplica con `PoliticaOrigen.requiere_autorizacion_cliente` (`domain/politicas.py:76-108`):

  | Origen | Cobro | Requiere autorización |
  |---|---|---|
  | `CLIENTE_EXTERNO` | Cobrable | **Sí** |
  | `RT_INTERNO` | No se cobra al cliente | No |
  | `RMA_GARANTIA_REPARACION` | No se cobra | No |

- En RT_INTERNO y RMA_GARANTIA_REPARACION el adicional pasa directo a factibilidad y se puede empezar (`test_macro_v14.py:462-491`).

**Alternativas:**

| | Alternativa | Consecuencias |
|---|---|---|
| A | **Mantener:** espera autorización solo en Cliente Externo | Sin cambios de reglas, código ni tests. En equipos de Rosario Tecno y en reparaciones de garantía, el técnico sigue sin esperar. El bloque 1 solo corrige el filtro «Pendientes de mi sector» y agrega el test de punta a punta |
| B | **Extender a la garantía RMA** (`RMA_GARANTIA_REPARACION`) | El cliente consiente cada intervención adicional sobre un equipo en garantía, aunque no se le cobre. Cambian BR-REP-028 y 032 (decisión en `rt-rma-app`), `PoliticaOrigen` y sus tests, y Recepción recibe tareas también en Órdenes de garantía. No resuelve qué pasa si el adicional no está cubierto por la garantía (cobrarlo o no): eso sería otra decisión |
| C | **Extender a todos los orígenes,** incluido RT_INTERNO | Hay que definir quién autoriza en RT_INTERNO, donde no hay cliente externo, y si es Gestión RT, cómo se registra. Se cruza con la Reparación RT recién publicada (DEC-RT-01 a 07). Suma esperas a reparaciones internas que hoy no se cobran a nadie |

**Propuesta: A.**

- La regla confirmada («el técnico propone → tarea de Recepción → autorización o rechazo → recién entonces se empieza») ya se cumple de punta a punta en el origen que se cobra.
- Extenderla cambia reglas aprobadas sin un pedido concreto.
- Si más adelante se quiere B, se registra como decisión propia, con la pregunta del cobro de un adicional fuera de garantía.

## 5. Plan por bloque

Pruebas de desarrollo: solo las de los componentes tocados. `ruff`; `pytest` de los archivos de tests del área; `tests/postgres` del área si se toca la persistencia; `typecheck` y los tests del frontend del área. La suite completa y los E2E van en el QA integral (paso 6).

| Bloque | Alcance | Pruebas mínimas | Listo para validación manual cuando… |
|---|---|---|---|
| 1 | Secciones técnicas ocultas según D-01 y la corrección de identidad movida; filtro «Pendientes de mi sector» con el aviso de autorización; test de punta a punta del adicional; fecha de entrega unificada en documentos | Tests del frontend de `PanelOrdenes` y `DetalleOrden`; `test_bandejas.py`, `test_situacion_operativa.py`, `test_macro_v14.py` y `test_documentos_custodia_entrega.py` | Recepción ve una Orden sin bloques técnicos y Taller la ve completa; un adicional pendiente aparece en «Pendientes de mi sector» con una ejecución en curso |
| 2 | La entrega evalúa 250 → 265 sin aviso; Notificar es opcional y registrable; situación y bandejas sin la etiqueta PENDIENTE_NOTIFICACION como bloqueo; validaciones repetidas eliminadas; check-in y custodia en el formulario de entrega; documentos según D-04 | Los tests de cierre y entrega que fijan la secuencia, adaptados a la regla nueva (con aprobación) y no debilitados; `test_cancelacion_orden.py` (DC31); camino RT sin cambios | Una Orden reparada se entrega sin avisar y con el aviso opcional; el saldo 0, la custodia y el check-in se siguen exigiendo; la garantía empieza en la entrega |
| 3 | Alta con el pedido en texto libre; comprobante según D-05; verificación Sí o No informativa; «Crear y generar comprobante» con impresión desde el visor; identificador provisorio según D-06 | Tests de ingreso (`test_ingreso_inicial.py`, `test_correccion_ingreso.py`, `test_documentos_custodia_entrega.py`); PostgreSQL de `recepcion` si hay migración | Recepción crea, registra la verificación y emite e imprime en un solo recorrido; los Detalles se agregan después |
| 4 | API y pantalla de los datos de la empresa con auditoría; quién retira (vínculo, teléfono, tercero) en la entrega y los documentos; textos según D-09 | Documentos (vistas previas, PDF y snapshots viejos legibles); permisos de Configuración | Los tres comprobantes muestran los datos de la empresa y quién retira |
| 5 | Formulario único de ajuste; corrección enlazada según D-10; documentos con precio original, ajuste y final; `EV-REP-041` | `test_descuentos.py`, `test_ajuste_por_detalle.py`, finanzas y saldo (la vista y el dominio juntos), recargo, documentos; PostgreSQL de finanzas | Un ajuste y su corrección se ven con su trazabilidad, y saldo y comprobantes coinciden |
| 6 | `insumo.stock_minimo` con auditoría; aviso según D-11 | Configuración de insumos, inventario y PostgreSQL de catálogos | Un insumo bajo el mínimo se ve marcado donde se decida |
| 7 | Precio por (tipo, modelo) con su resolución en el Detalle; conversión de los tipos actuales; importación CSV con vista previa | Configuración, reparaciones, redefinición y evaluación; importación (validaciones y atomicidad); PostgreSQL de catálogos | Un mismo tipo da precios distintos según el modelo, y una planilla de prueba actualiza los precios con su auditoría |
| 8 | Según D-14 | Inventario, compras, lotes, reservas y PostgreSQL | Los insumos se clasifican y filtran por categoría y modelo, y el stock y los costos siguen conciliados |

**Mientras se desarrolla:** commits chicos por funcionalidad, sin push salvo autorización y sin desplegar. Cada bloque cierra con la validación manual en local. El QA integral, los E2E y el despliegue se hacen al final (pasos 6 y 7).

## 8. Bloque 1: implementación en local (23/11/2026)

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. No hay migraciones ni cambios en `business/`.

### BF-12. Autorización de trabajos adicionales (`3788aa0`)

- **Defecto corregido:** con otro trabajo en ejecución, la autorización pendiente de un adicional es un aviso de la situación (`AUTORIZACION_PENDIENTE`), no la situación principal. El campo `situacion.roles`, del que sale el filtro «Pendientes de mi sector», se calculaba solo con la situación principal. Por eso Recepción no veía la Orden en el filtro, aunque sí en su bandeja de autorizaciones.
- **Corrección:** se suman al sector los roles de ese aviso (`application/situacion.py`, `_AVISOS_DEL_SECTOR`). Los demás avisos no cambian.
- **Autorización por origen:** sin cambios (D-02, alternativa A).
- **Prueba:** `tests/test_adicional_pendiente_sector.py`, 3 casos. Recorre el adicional durante una ejecución, el filtro, el rechazo del inicio con 409, la autorización y el inicio, y también el rechazo del adicional. Sin la corrección, falla.

### BF-17. Inicio de la garantía (`2f1a342` y `5a7fbd8`)

- **Estado:** la garantía ya empezaba en la entrega efectiva.
- **Inconsistencia corregida:** el certificado de garantía y el comprobante final tomaban `orden.entrega.fecha` sin el respaldo del historial (PROC-REP-270) que sí usan `fecha_de_entrega()`, el reclamo RMA y `{garantia_hasta}`. Ahora los tres usan la misma función (`services/documentos.py`).
- **Plazos y alcance:** sin cambios.
- **Prueba:** `tests/test_garantia_desde_entrega.py`, con una Orden sin registro de entrega pero con el paso 270. Sin la corrección, falla.

### BF-07. Información técnica según permiso (`8980e52`)

- **Permiso:** `DETALLE_TECNICO_CONSULTAR`, «Consultar la información técnica de la Orden», en el grupo «Consultas». Predeterminado para Técnico, Coordinación RMA y Administración, y configurable desde Configuración. No necesita fila en `rma.permiso` ni migración.
- **Se oculta sin el permiso:**
  - antecedentes del equipo;
  - ejecuciones e insumos, con sus devoluciones;
  - los insumos previstos y las ejecuciones de cada trabajo;
  - los bloques técnicos, en la nueva sección «Datos técnicos».
- **Sigue visible:**
  - el resultado técnico, el estado y el precio de cada trabajo;
  - el historial de eventos, en su propia sección «Historial»;
  - cliente y equipo, fotos, autorización, comunicaciones, cobros y documentos.
- **«Corregir la identidad»:** pasa a «Cliente y equipo». La identificación del equipo al ingresar no cambia.
- **Pantallas:** `features/ordenes-reparacion/PanelOrdenes.tsx`, `DetalleOrden.tsx` y `detalleTecnico.ts`, una función pura con su prueba `tests/detalle-tecnico.test.ts`.
- **Prueba existente cambiada:** la guarda `test_ningun_permiso_queda_sin_uso` (`tests/test_matriz_permisos.py`) ahora admite permisos de solo presentación (`permisos.SOLO_PRESENTACION`), siempre que el frontend los use y ningún endpoint los exija.
- **Limitación:** es **presentación, no seguridad**. `GET /api/orders/{id}` y los endpoints de antecedentes, ejecuciones e inventario siguen devolviendo esos datos a quien consulta la Orden (`ORDENES_CONSULTAR`, `ANTECEDENTES_CONSULTAR` e `INVENTARIO_CONSULTAR`). Ocultarlos en la API sería otra decisión, fuera del alcance aprobado.

### Pruebas ejecutadas (focalizadas)

| Ámbito | Resultado |
|---|---|
| Backend: `test_adicional_pendiente_sector`, `test_situacion_operativa`, `test_bandejas`, `test_macro_v14`, `test_autorizacion_cliente` y `test_autorizacion_cliente_servicios` | 120 pasan |
| Backend: `test_garantia_desde_entrega`, `test_documentos_custodia_entrega`, `test_garantia_checkin`, `test_politica_garantia`, `test_reclamos_garantia` y `test_comunicaciones` | 52 pasan |
| Backend: `test_matriz_permisos` y `test_roles_permisos` | 25 pasan |
| Backend: `ruff check` y formato | Limpios |
| Frontend: `typecheck`, `npm test` y `npm run build` | Pasan (201 pruebas, incluidas las 4 nuevas) |
| Arranque | Backend local con `/health` 200; el permiso aparece en el catálogo de Configuración; en la lista de usuarios, Recepción no lo tiene y Técnico, Coordinación y Administración sí |

La suite completa, las pruebas de PostgreSQL y los E2E quedan para el QA integral.

## 6. Riesgos principales

1. **Reglas aprobadas que cambian (BF-04, 05, 08 y 20).** Implementarlas sin registrar antes la decisión en `rt-rma-app` deja `business/` contradiciendo al código. Mitigación: decisión primero y después sincronizar.
2. **Tests que fijan la secuencia de entrega.** Son 28 archivos. Adaptarlos solo con aprobación (AGENTS.md) y sin debilitar las comprobaciones de saldo, custodia ni check-in.
3. **Integridad financiera (BF-09).** El saldo se calcula en dos lugares y el recargo se reparte con los ajustes actuales. Cualquier cambio va en la vista y en el dominio juntos, con pruebas de PostgreSQL.
4. **Migración del catálogo (BF-01 y BF-14).** Los tipos actuales no se pueden borrar, hay Órdenes con Detalles que los referencian, y existen stock, reservas y lotes sin clasificar. Hace falta una conversión explícita y un ensayo local antes del UAT.
5. **Compatibilidad con la versión publicada.** Todas las migraciones tienen que ser aditivas, para que `00042-suw` siga funcionando como vuelta atrás (como en P1-15).
6. **Datos de prueba del UAT.** `OR-000001` a `OR-000006` pueden quedar a mitad del workflow cuando cambien las compuertas de la entrega (bloque 2).

## 7. Primer bloque recomendado

**Bloque 1: BF-07, BF-12 y BF-17.**

- No necesita migraciones ni decisiones en `business/`, y no toca pagos, stock ni la secuencia de la entrega.
- Solo espera D-01 y D-02 (sección 4.1).
- Da una mejora visible para Recepción y cierra dos verificaciones.

**En paralelo:** resolver D-03 y D-04 (bloque 2) y D-05 a D-08 (bloque 3), y registrar en `rt-rma-app` las que cambian reglas, para que esos bloques puedan empezar enseguida.
