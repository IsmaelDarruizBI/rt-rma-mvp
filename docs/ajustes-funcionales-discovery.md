# Ajustes funcionales del feedback de UAT (BF-01 a BF-20): análisis y plan

> **Estado (23/11/2026):** bloque 1 implementado en local. Iteración 1 (bloques 2, 3 y 4) aprobada y en implementación. `business/` está sincronizado con `rt-rma-app` `64a8583` (`spec/ajustes-funcionales`, local), con DEC-AJ-01 a 09 (sección 9.1).
>
> **Aprobado (23/11/2026):** la planificación general y la secuencia de los 8 bloques (sección 3).
>
> **Aprobado (23/11/2026):** D-01, alternativa B, y D-02, alternativa A (sección 4.1).
>
> **Bloque 1:** implementado en local; se valida a mano junto con todo el backlog (sección 8).
>
> **Replanificado (23/11/2026):** la iteración 1 incluye los bloques 2, 3 y 4, y la iteración 2 los bloques 5 a 8. Las decisiones de la iteración 1 están aprobadas (sección 9).
>
> **D-07:** aprobada la alternativa A (verificación informativa y obligatoria), el 23/11/2026.
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

## 9. Decisiones de la iteración 1 (bloques 2, 3 y 4), aprobadas (23/11/2026)

Replanificación del 23/11/2026:

- **Iteración 1:** bloques 2, 3 y 4. Se implementan juntos, después de aprobar estas decisiones.
- **Iteración 2:** bloques 5 a 8.

Las decisiones que cambian reglas vigentes se registran antes del código.

### D-03 (BF-20). Avisar al cliente deja de ser obligatorio

**Hoy:**

- La entrega exige el paso PROC-REP-260 («Notificar»). PROC-REP-260 dice: «no hay un camino alternativo que la evite».
- Hay dos avisos sin conexión entre sí:
  - el botón Notificar registra el paso 260;
  - una comunicación por WhatsApp con la plantilla `LISTO_PARA_RETIRAR` queda en el historial de comunicaciones, pero no registra el 260.
- El retiro demorado (DEC-MI-14, 30 días) cuenta desde el 260.
- Pasan por el 260: CLIENTE_EXTERNO, la garantía RMA y el resultado SIN_REPARACION.
- El camino RT usa otro paso: INFORMAR_RT (290) → DEVOLVER_RT.

**Decisiones:**

| | Pregunta | Alternativas | Recomendación |
|---|---|---|---|
| a | ¿Incluye el camino RT? | Sí / No | **No.** Informar a Gestión RT es trazabilidad hacia otro sistema, no un aviso al cliente |
| b | ¿Aplica a SIN_REPARACION y a la garantía RMA? | Solo a las reparaciones de Cliente Externo / A todo lo que se entrega al cliente | **A todo lo que se entrega al cliente**, para que la regla sea una sola |
| c | ¿Desde cuándo corre el retiro demorado si no hubo aviso? | Desde la Orden lista para entregar (reparación terminada o finalizada sin reparar) / No corre | **Desde que está lista para entregar.** Si hubo aviso, desde el aviso, como hoy |
| d | ¿Una comunicación `LISTO_PARA_RETIRAR` confirmada como enviada cuenta como aviso? | Sí: registra el 260 / No | **Sí.** Así hay un solo registro del aviso |

**Impacto:**

- **Reglas:** cambian PROC-REP-260 (pasa a ser opcional) y el flujo 250 → 265. Hay que registrar la decisión en `rt-rma-app`.
- **Código:** la entrega deja de exigir el 260 (`application/cierre.py`, `application/acciones.py`, `services/documentos.py`). Notificar queda como acción opcional; en la situación y las bandejas el aviso deja de bloquear y pasa a ser una sugerencia.
- **Pruebas:** hay que adaptar unas 28 que fijan la secuencia, sin debilitar saldo, custodia ni check-in.
- **Órdenes de prueba:** las que estén en 240 sin aviso pasan a ofrecer la entrega.
- **Migración:** no.

### D-04 (BF-18). Cierre y entrega

**Hoy:**

- Al entregar se emiten tres papeles:
  - el comprobante final, que ya lista cada trabajo con su garantía y vencimiento;
  - el certificado de garantía, un documento aparte;
  - la página de Términos y Condiciones.
- El check-in es una acción separada: la entrega aparece bloqueada hasta registrarlo.
- La custodia no confirmada no se informa como bloqueo y la pantalla la deduce por su cuenta.
- Dentro de la misma operación hay validaciones repetidas: es deuda técnica, se corrige sin decisión.

**Decisiones:**

| | Pregunta | Alternativas | Recomendación |
|---|---|---|---|
| a | Papeles de la entrega | A. Mantener comprobante final y certificado. B. **Un solo «Comprobante de entrega y garantía»**, con los Términos en el mismo PDF; deja de emitirse el certificado aparte. C. Mantener los dos, pero imprimirlos juntos | **B.** El comprobante final ya tiene la garantía por trabajo. Los certificados ya emitidos no cambian (son inmutables) |
| b | Check-in | A. Sigue aparte. B. **Dentro del formulario de entrega,** si todavía no se registró: una sola confirmación registra el check-in y la entrega | **B.** Conserva BR-REP-045 (check-in antes de entregar, auditado) y DEC-MI-05 (corrección antes de la entrega) |
| c | Cobro | A. **Sigue aparte,** con saldo exactamente 0 (BR-REP-017 y 038). B. Cobrar dentro de la entrega | **A.** No se mezclan finanzas con la entrega |

**Impacto:**

- **Reglas:** cambian BR-REP-031 y 041 en el documento de garantía (un documento en lugar de dos). El paso 269 (check-in) se registra en la misma operación que la entrega.
- **Código:** el tipo GARANTIA queda solo para los documentos ya emitidos.
- **Migración:** no.

### D-05 (BF-04). Ingreso sin trabajos estandarizados

**Hoy:**

- Hay dos caminos:
  1. **Con trabajos:** «Generar el comprobante de ingreso y autorización» (BR-REP-046) confirma la custodia, autoriza y emite en una sola operación.
  2. **Sin trabajos:** «Enviar a revisión técnica (sin diagnóstico)» (VAR-REP-001/002) emite el comprobante de recepción («reparación pendiente de diagnóstico») y deja la Orden en revisión.
     - Los trabajos los define el Técnico (PROC-REP-075).
     - El cliente autoriza después (PROC-REP-129).
     - La custodia se confirma **en otro paso**.
- El texto libre ya existe: las «Observaciones del equipo» unificadas (`falla_reportada`).

**Alternativas:**

| | Alternativa | Impacto |
|---|---|---|
| A | **Usar el camino de revisión** como ingreso sin trabajos: Recepción registra el trabajo solicitado y genera el comprobante de recepción, que **confirma la custodia en el mismo acto**. El Técnico define los trabajos, con su precio, y el cliente autoriza con el comprobante de autorización | Reutiliza un recorrido probado. Solo cambia que la custodia se confirma junto con el comprobante de recepción. Recepción no carga los trabajos de esa Orden |
| B | **Ingreso abierto en REQUERIMIENTO:** comprobante de recepción y custodia; la Orden queda para que **Recepción** agregue los trabajos después y genere la autorización | Recorrido nuevo: la operación única de BR-REP-046 se parte en dos. Hay más estados para probar |
| C | **Las dos opciones al crear:** «Lo define el técnico» (A) o «Cargo los trabajos después» (B) | Lo más flexible y lo más caro |

**Recomendación: A.**

**Hay que decidir además** si el trabajo solicitado va en un **campo propio**, «Trabajo solicitado» (migración aditiva y visible en el comprobante), o en las «Observaciones del equipo» actuales. **Recomendación:** campo propio, para que no se mezcle con el estado del equipo.

**Impacto:**

- **Reglas:** hay que registrar que el comprobante de recepción confirma la custodia (hoy son actos separados: BR-REP-033 y VAR-REP-001/002) y aclarar BR-REP-046.
- **Migración:** aditiva, si el campo es propio.

### D-06 (BF-05). IMEI provisorio

**Hoy:**

- Un equipo sin IMEI se identifica con el identificador interno del Equipo (`EQP-…`), impreso en la Orden y en el comprobante. DEC-UX-02 dice: «nunca un IMEI ficticio».
- El IMEI solo se corrige antes de confirmar la recepción (DEC-MI-07, con ABI-41 abierto: hasta cuándo se corrige).

**Alternativas:**

| | Alternativa | Impacto |
|---|---|---|
| A | **El botón no inventa un IMEI:** marca «IMEI no disponible», deja el campo vacío y muestra destacado el identificador del Equipo (`EQP-…`) como identificador provisorio, en la pantalla y en el comprobante. **Más una acción nueva, «Registrar el IMEI real»**, que se puede usar **también después de la custodia**, con motivo y auditoría, mientras la Orden no esté entregada | Cumple DEC-UX-02. No contamina la identificación, los antecedentes ni las búsquedas. Resuelve ABI-41 solo para el IMEI. El historial muestra cuándo y quién lo cargó |
| B | Identificador provisorio propio (por ejemplo `PROV-…`) en un campo aparte, que nunca se usa como IMEI | Migración aditiva. Suma un identificador más al del Equipo, que ya es único |
| C | Un IMEI generado en el campo `imei`, con una marca | Contradice DEC-UX-02. Contamina los antecedentes y la detección de equipos repetidos. **No recomendada** |

**Recomendación: A**, con la acción para registrar el IMEI real hasta la entrega.

**Impacto:**

- **Reglas:** DEC-UX-02 no cambia. Hay que registrar el cierre de ABI-41 para el IMEI.
- **Migración:** no, salvo que la auditoría pida un registro propio.

### D-07 (BF-08). Verificación inicial, check-in y garantía (aprobada: A)

**Hoy:**

- La misma pregunta, si se pudieron verificar las funciones básicas (realizado o no realizado), es el **check-in de entrega** (BR-REP-045).
- Ese check-in fija el plazo de la garantía de cada trabajo: 90 días con check-in y 30 sin él, según el Tipo (`garantia_con_checkin` y `garantia_sin_checkin`). Es obligatorio para entregar en Cliente Externo.
- La columna anterior `recepcion.checkin_ingreso` todavía se lee como check-in.

**Alternativas:**

| | Alternativa | Impacto sobre la garantía |
|---|---|---|
| A | **Informativa:** se pregunta al ingresar (Sí o No, con observaciones) y queda en la recepción y en el comprobante de ingreso. El check-in de entrega sigue igual | Ninguno. Al hacer el check-in de entrega se muestra la respuesta del ingreso como referencia |
| B | **Anticipa el check-in:** la respuesta del ingreso es el check-in; al entregar solo se confirma o se corrige con motivo (DEC-MI-05) | La garantía pasa a depender de cómo llegó el equipo y no de cómo se entrega. Cambia BR-REP-045 |
| C | **Condiciona el plazo:** si al ingresar fue «No», la garantía queda en el plazo sin check-in aunque el check-in de entrega sea «Sí» | Cambia la base de la garantía, y BR-REP-041 y 045 |

**Recomendación: A**, con respuesta obligatoria y observaciones opcionales.

**Aprobada (23/11/2026):** A, con respuesta obligatoria y observaciones opcionales (sección 9.1).

**Migración:** aditiva en las tres (dos columnas en `recepcion`). En ningún caso se reutiliza `checkin_ingreso`.

### D-08 (BF-06). Impresión directa del comprobante de ingreso

**Hoy:** se crea la Orden, se va a «Documentos», se elige el canal («El cliente autorizó», presencial por defecto), se genera y se imprime desde el visor.

**Propuesta:**

- «Nueva orden» termina con **«Crear y generar el comprobante»**, que encadena dos comandos ya idempotentes, con el canal presencial preseleccionado y editable.
- El visor se abre con «Imprimir» como acción principal. El navegador no deja imprimir sin un clic del usuario.
- Sin trabajos (D-05), se genera el comprobante de recepción.
- El canal se sigue registrando (BR-REP-028), así que no hay confirmación que quitar. Esta propuesta no contradice reglas.

### D-09 (BF-19). Comprobantes

**Hoy:**

- `rma.empresa` tiene nombre, razón social, CUIT, dirección, teléfono, email y condiciones de garantía, pero **solo el nombre está cargado** y no hay pantalla para editarla.
- Los Términos están fijos en el código. Dicen 180 días (P-04) y anulan la garantía si retira un tercero (P-05).
- `rma.salida` tiene el vínculo y el teléfono de quien retira, pero no se guardan.

**Decisiones:**

| | Pregunta | Alternativas | Recomendación |
|---|---|---|---|
| a | ¿Quién edita los datos de la empresa? | Administración, con el permiso no configurable de parámetros del sistema / un permiso configurable nuevo | **Administración**, con auditoría |
| b | ¿Qué son los «datos operativos»? | Horario de atención, sitio web o redes, pie de comprobante libre | **Horario y un pie de comprobante libre.** Migración aditiva |
| c | P-04: ¿qué plazo rige? | 180 días (Términos) / el plazo de cada trabajo (90/30 por Tipo y check-in) | **Decisión de negocio.** Sin ella, el texto pasa a remitir a «el plazo indicado para cada trabajo» |
| d | P-05: ¿qué pasa si retira un tercero? | Anula la garantía / solo queda registrado, con un aviso al entregar | **Decisión de negocio.** Recomendado: registrar quién retira, su vínculo (Titular, Tercero, Empleado o representante) y su teléfono; avisar al entregar; que el texto de los Términos lo defina el negocio |
| e | ¿El vínculo de quien retira es obligatorio? | Sí, por defecto «Titular» / No | **Sí, por defecto «Titular»** |
| f | ¿Dónde viven los Términos? | En el código, como hoy / versionados en `rma.texto_legal`, editables por Administración y guardados en cada documento | **Versionados en `rma.texto_legal`.** La tabla ya existe y nadie la lee |

### 9.1 Decisiones aprobadas (23/11/2026)

Registradas en `rt-rma-app`, rama `spec/ajustes-funcionales` (local, sin publicar), commit `64a8583`, y copiadas a `business/` ([`sincronizacion-funcional.md`](sincronizacion-funcional.md)). DEC-AJ-NN corresponde a D-NN. No agregan nodos, aristas ni estados. Las que todavía no están implementadas figuran en [`traceability/discrepancias-baseline-v1.4.md`](../traceability/discrepancias-baseline-v1.4.md).

| Decisión | ID | Definición aprobada | Implementación |
|---|---|---|---|
| D-01 (BF-07) | DEC-AJ-01 | Alternativa B: permiso de consulta configurable «Consultar la información técnica de la Orden» (`DETALLE_TECNICO_CONSULTAR`), predeterminado para Técnico, Coordinación RMA y Administración, no para Recepción. Es presentación: la API no cambia | Bloque 1 (`8980e52`) |
| D-02 (BF-12) | DEC-AJ-02 | Alternativa A: el trabajo adicional espera la autorización del cliente solo en CLIENTE_EXTERNO. BR-REP-032 no cambia | Bloque 1 (`3788aa0`) |
| D-03 (BF-20) | DEC-AJ-03 | Avisar al cliente deja de ser obligatorio para entregar, en toda entrega al cliente (CLIENTE_EXTERNO, incluido SIN_REPARACION, y la garantía RMA). El camino RT (INFORMAR_RT → DEVOLVER_RT) no cambia. El retiro demorado corre desde que la Orden está lista para retirar. La fecha del aviso se conserva aparte. Una comunicación `LISTO_PARA_RETIRAR` confirmada como enviada registra el aviso (260). Se mantienen los controles de saldo, custodia y check-in | Bloque 2 |
| D-04 (BF-18) | DEC-AJ-04 | Un solo «Comprobante de entrega y garantía» con los términos y condiciones; deja de emitirse el certificado aparte (los ya emitidos no cambian). El check-in faltante se registra en la misma confirmación de la entrega. El cobro sigue aparte, con saldo exactamente 0 | Bloque 2 |
| D-05 (BF-04) | DEC-AJ-05 | Alternativa A: camino de «Enviar a revisión técnica» con el campo propio «Trabajo solicitado»; el comprobante de recepción confirma la custodia en el mismo acto; el técnico define los trabajos y el cliente los autoriza después. BR-REP-046 sigue para el ingreso con trabajos | Bloque 3 |
| D-06 (BF-05) | DEC-AJ-06 | Alternativa A: botón «IMEI no disponible» con el identificador interno `EQP-…` (DEC-UX-02, nunca un IMEI ficticio); acción para registrar el IMEI real hasta la entrega, también con la custodia confirmada, con motivo y auditoría. Cierra ABI-41 para el IMEI | Bloque 3 |
| D-07 (BF-08) | DEC-AJ-07 | Alternativa A: pregunta **obligatoria** «¿Se pudieron verificar las funcionalidades del equipo?» Sí o No, con observaciones opcionales en los dos casos. Es **informativa**: se muestra como referencia en el check-in de entrega y no cambia la garantía ni BR-REP-045. BF-16 sigue postergado | Bloque 3 |
| D-08 (BF-06) | DEC-AJ-08 | «Crear y generar el comprobante», con el canal presencial preseleccionado (se sigue registrando, BR-REP-028); Imprimir como acción principal del visor, con un gesto del usuario. Sin trabajos, el comprobante de recepción | Bloque 3 |
| D-09 (BF-19) | DEC-AJ-09 | Administración configura los datos de la empresa (nombre comercial, dirección, teléfono, horario y pie de comprobante), con auditoría. Términos y condiciones versionados desde Configuración (`rma.texto_legal`); cada documento conserva su versión. **P-04:** los documentos informan la garantía real de cada trabajo, no los 180 días fijos. **P-05:** la entrega pregunta «¿Retira otra persona?» Sí o No; si es Sí, nombre, apellido y teléfono obligatorios; no se piden vínculo, DNI ni otra identificación, ni una autorización formal; retirar otra persona no modifica ni anula la garantía; quién retiró queda en la Orden y en el comprobante. Reemplaza las recomendaciones d y e de la tabla anterior | Bloque 4 |

## 10. Iteración 1: implementación en local

### 10.1 Bloque 2: entrega

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. `business/` no cambia: implementa DEC-AJ-03, DEC-AJ-04 y la parte P-05 de DEC-AJ-09 (sección 9.1).

| Commit | Qué |
|---|---|
| `5cf99f9` | BF-20 (DEC-AJ-03): avisar al cliente deja de ser obligatorio |
| `7be27fe` | Migración `20261123000100_checkin_en_entrega` |
| `1a3b55f` | BF-18 (DEC-AJ-04): entrega en una sola confirmación y un solo comprobante (backend) |
| `b23732f` | BF-19, P-05 (DEC-AJ-09): quién retira, sin identificación (backend) |
| `f51ce94` | Frontend de los tres: formulario de entrega, comprobante y términos |

#### Aviso opcional (DEC-AJ-03)

- **Entrega sin aviso:** ENTREGAR se ofrece con la Orden lista para retirar y la cuenta saldada, en Cliente Externo (también SIN_REPARACION) y en la garantía RMA. Sin aviso, la misma entrega registra PROC-REP-250 y evalúa PROC-REP-265 antes de 280. Con el aviso hecho, 265 ya se evaluó al avisar o al pagar y no se repite.
- **Notificar:** sigue como acción opcional hasta la entrega (`services/ordenes.py`, `aviso_registrable` y `registrar_aviso_listo`).
  - En la situación, «Avisar al cliente (opcional)» es una tarea sugerida junto a «Registrar el pago pendiente» o «Entregar el equipo». «Lista para entregar» ya no queda detrás de un aviso pendiente.
  - La bandeja «Avisar al cliente (opcional)» lo aclara.
- **WhatsApp:** confirmar como enviado un mensaje con la plantilla `LISTO_PARA_RETIRAR` registra el aviso (250 → 260 → 265, y 266 si hay deuda), una sola vez, con la Orden lista y sin entregar. La observación del paso dice `WhatsApp COM-…`. Otra plantilla, un envío no confirmado o una Orden que todavía no está lista no lo registran (`application/comunicaciones.py`).
- **Retiro demorado:** corre desde que la Orden está lista para retirar, el último paso 240 o 069 (`domain/retiro.py`, `fecha_lista_para_retirar`). Una Orden vieja sin ese paso usa el aviso, como antes.
  - Los seguimientos ya no exigen el aviso.
  - La API expone `lista_para_retirar_desde` y `fecha_aviso`; la Orden los muestra («Lista para retirar desde … · aviso al cliente: …»).
- **Camino RT_INTERNO:** sin cambios (INFORMAR_RT → DEVOLVER_RT). La entrega comercial lo rechaza.

#### Entrega y comprobante (DEC-AJ-04)

- **Una sola operación** (`services/entrega.py`, `entregar_al_cliente`):
  - Controla una vez el rol, el resultado, la cuenta (saldo exactamente 0), la custodia, el trabajo abierto, quién retira y el check-in.
  - Después registra [250] [269] [265] 280 y 270 con las versiones sin revalidar de cada service (`registrar_condicion_entrega`, `marcar_comprobante_final` y `registrar_entrega`).
  - `validar_condicion_entrega`, `generar_comprobante_final` y `entregar_equipo` conservan sus controles para quien los usa por separado.
  - Si algo falla, no se guarda nada: ni el check-in ni los pasos.
- **Validaciones repetidas eliminadas:** el rol, `lista_para_cierre`, `current_process == 265` y `condicion_entrega_cumplida` se evaluaban dos o tres veces en la misma entrega, y se volvían a verificar los documentos recién generados. Ahora cada control se hace una vez, sin debilitar ninguno.
- **Check-in dentro de la entrega:**
  - `POST /deliver` recibe `checkin` y, para corregir uno ya registrado, `checkin_motivo` (DEC-MI-05 sin cambios).
  - Si faltaba, se registra con el paso PROC-REP-269 y después se revalida 265.
  - La acción aparte «Registrar el check-in» sigue disponible antes de entregar.
  - El check-in ya no bloquea ENTREGAR ni es una situación propia: «Lista para entregar» indica que se registra al entregar. Sin la respuesta, la entrega se rechaza (BR-REP-045).
- **Custodia como bloqueo:** ENTREGAR trae en `bloqueo` la custodia sin confirmar («Falta confirmar la recepción física del equipo»). El frontend la muestra y ya no la deduce.
- **Un solo comprobante:**
  - La entrega de una reparación emite el «Comprobante de entrega y garantía». Su contenido marca `entrega_y_garantia` y `condiciones_garantia`, y lista cada trabajo con su garantía y vencimiento.
  - La vista imprimible agrega los términos y condiciones en la misma hoja.
  - Ya no se emite el certificado GARANTIA ni se ofrece su vista previa. Los emitidos se siguen leyendo con su presentación.
  - La marca `garantia_reparacion` sigue diciendo que se emitió la garantía, ahora dentro del comprobante.
  - Una devolución sin reparación sigue siendo el «Comprobante de devolución sin reparación».
- **Cobro:** sigue aparte. ENTREGAR no se ofrece con saldo distinto de 0, y el comando lo rechaza.

#### Quién retira (DEC-AJ-09, P-05)

- **Formulario:** «¿Retira otra persona?»
  - **No:** retira el titular y no se pide nada más. Queda su nombre.
  - **Sí:** nombre, apellido y teléfono obligatorios.
  - No se piden vínculo, DNI ni autorización formal. Se dejó de pedir la identificación al entregar.
- **Registro:** queda en la Orden (`entrega.retira_otra_persona` y `telefono_receptor`), en el historial del paso 270 y en el comprobante.
- **PostgreSQL:** `rma.salida` escribe y lee `retira_telefono` y `retira_vinculo` (TITULAR o TERCERO), columnas que ya existían.
- **Garantía:** que retire otra persona no la cambia.
- **Términos:** se quitaron el apartado que anulaba la garantía si retiraba un tercero y la exigencia de que retire quien dejó el equipo. El resto del texto no cambia; los 180 días (P-04) quedan para el bloque 4.

#### Migración

`20261123000100_checkin_en_entrega.sql`, aditiva, solo datos de referencia: la equivalencia del historial de PROC-REP-269 con «Check-in registrado» (EV-REP-033). Sin ella PostgreSQL rechaza guardar el paso. No agrega tablas, así que los scripts de reinicio del UAT no cambian.

#### Pruebas nuevas

| Archivo | Casos | Qué cubre |
|---|---|---|
| `tests/test_entrega_sin_aviso.py` | 11 | Entrega sin aviso en Cliente Externo, SIN_REPARACION y garantía RMA; el saldo sigue bloqueando sin dejar pasos a medias; camino RT sin cambios; aviso opcional registrado; WhatsApp `LISTO_PARA_RETIRAR` registra 260 una vez; retiro demorado desde que está lista, con la fecha del aviso aparte |
| `tests/test_entrega_y_garantia.py` | 10 | Check-in y entrega en una confirmación (con 269 y revalidación de 265); sin check-in o con saldo no se guarda nada; corrección con motivo; roles; custodia como bloqueo; un solo comprobante; devolución sin reparación; un certificado anterior se sigue leyendo |
| `tests/test_quien_retira.py` | 7 | Titular sin otro dato; nombre, apellido y teléfono obligatorios para otra persona; sin vínculo ni DNI; la garantía no cambia |
| `tests/postgres/test_entrega_postgres.py` | 2 | Paso 269 guardado como EV-REP-033, entrega sin aviso y quién retira, guardados y releídos |
| Frontend `tests/entrega.test.ts` | 7 | Retiro y aviso, título del comprobante, cuándo se pide el check-in, faltantes y descripción de quién retira |
| Frontend `tests/terminos.test.ts` | 1 | Sin la anulación de la garantía por retiro de un tercero |

#### Pruebas existentes adaptadas (aprobado: fijaban las reglas reemplazadas)

- **Aviso obligatorio (DEC-AJ-03):**
  - `test_api_sin_reparacion.py`, `test_cancelacion_orden.py`: ENTREGAR se ofrece junto a NOTIFICAR.
  - `test_api_hp_rep_003.py`: tres pruebas exigían avisar antes de entregar; ahora verifican que la entrega sin aviso pasa por 265 antes de 280.
  - `test_situacion_operativa.py`: PENDIENTE_COBRO con el aviso como tarea opcional.
  - `test_bandejas.py`: título de la bandeja del aviso.
  - `test_documentos_custodia_entrega.py`, prueba 11: el rechazo con saldo es por el saldo, no por el nodo; la Orden sigue en 266.
  - `test_motivos_retiro.py`: solo el docstring.
- **Certificado aparte y check-in como acción bloqueante (DEC-AJ-04):**
  - `test_documentos_custodia_entrega.py` (pruebas 10, 13-17, 18-19, 20, 21, 22 y circuitos A y C), `test_garantia_checkin.py` y `test_reparacion_otros.py`: la garantía de cada trabajo se lee en el comprobante de entrega. Se mantienen los mismos plazos y vencimientos.
  - `test_garantia_checkin.py` y `test_situacion_operativa.py`: el check-in faltante no bloquea ENTREGAR; la entrega sin él se sigue rechazando.
  - `test_api_sin_reparacion.py`: ENTREGAR informa la custodia sin confirmar como bloqueo.
  - `tests/postgres/corpus_ordenes.py`: la primera entrega del corpus conserva un certificado anterior, para seguir cubriendo su guardado.
- **Identificación de quien retira (DEC-AJ-09):**
  - `test_documentos_custodia_entrega.py`, pruebas 9 y 16.
  - `tests/fixtures/custodia.py`: `RECEPTOR` sin nombre ni DNI.
  - `tests/postgres/test_recepcion_documentos_postgres.py`: firma nueva de `entregar`.
- **Frontend:** `tests/terminos.test.ts`, 18 apartados y uno resaltado.

No se debilitó ninguna comprobación de saldo, custodia, check-in, idempotencia ni permisos.

#### Pruebas ejecutadas (focalizadas)

| Ámbito | Resultado |
|---|---|
| Backend: 41 archivos existentes (cierre, entrega, documentos, garantía, check-in, aviso, retiro, comunicaciones, situación, bandejas, HP-REP-001/002/003, caracterización, cancelación, SIN_REPARACION, autorización, permisos, macro V1.4 y orden cerrada) y los 3 nuevos | 680 pasan |
| PostgreSQL local: `test_ordenes`, `test_recepcion_documentos`, `test_cierre_ux`, `test_motivos_retiro`, `test_comunicaciones`, `test_iteracion1`, `test_firmas`, `test_entrega` (nuevo), `test_reclamos_garantia`, `test_macro_v14`, `test_finanzas`, `test_pruebas_sql_supabase` y `test_reinicio_clasificacion` | 174 pasan |
| Backend: `ruff check . ../../supabase/scripts` y `ruff format --check` de los archivos tocados | Limpios |
| Frontend: `typecheck`, `npm test` y `npm run build` | Pasan (209 pruebas) |
| Arranque | Backend local en modo JSON con `/health` 200 |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Limitaciones y pendientes

- **Progreso de la Orden:** sigue listando PROC-REP-260 «Notificar cliente». En una entrega sin aviso queda como no alcanzado; no se marcó como opcional en esa vista.
- **Términos:** siguen en el código y no se guardan en el documento. Una hoja ya emitida se imprime con el texto vigente, como antes. Los 180 días (P-04) y los términos versionados quedan para el bloque 4.
- **Nombre y apellido:** se guardan juntos en `recibido_por` (`rma.salida.retira_nombre`), sin columnas aparte.
- **Documentación:** `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-03 y 04 todavía «sin implementar») y `docs/ESTADO_PROYECTO.md` no se actualizaron en este bloque.
- **Datos del UAT:** las Órdenes en 240 sin aviso pasan a ofrecer la entrega (riesgo 6).
- **Validación manual:** pendiente en local, según la tabla de la sección 5.
