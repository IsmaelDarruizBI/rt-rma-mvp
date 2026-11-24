# Ajustes funcionales del feedback de UAT (BF-01 a BF-20): análisis y plan

> **Estado (24/11/2026):** iteraciones 1 (bloques 1 a 4) y 2 (bloques 5 a 8) implementadas en local (secciones 8, 10 y 11.2 a 11.7), sin push ni despliegue. `business/` está sincronizado con `rt-rma-app` `2e93e9b` (`spec/ajustes-funcionales`, local), con DEC-AJ-01 a 14 implementadas (secciones 9.1 y 11.1). Sigue la validación manual de los ocho bloques (sección 12).
>
> **Aprobado (23/11/2026):** la planificación general y la secuencia de los 8 bloques (sección 3).
>
> **Aprobado (23/11/2026):** D-01, alternativa B, y D-02, alternativa A (sección 4.1).
>
> **Aprobado (23/11/2026):** las decisiones de la iteración 2, D-10 a D-14. D-12.2, D-13.1, D-14.3 y D-14.4 fueron modificadas por el usuario. Rige la sección 11.1, con las precisiones de implementación de la coordinación.
>
> **Bloques 1 a 8:** implementados en local; se validan a mano juntos, con el recorrido de la sección 12.
>
> **Replanificado (23/11/2026):** la iteración 1 incluye los bloques 2, 3 y 4, y la iteración 2 los bloques 5 a 8. Las decisiones de la iteración 1 están aprobadas (sección 9).
>
> **D-07:** aprobada la alternativa A (verificación informativa y obligatoria), el 23/11/2026.
>
> **Rama:** `feat/ajustes-funcionales-uat`, desde `mvp-v2` `82ebbb6`, con 42 migraciones; la iteración 1 suma tres aditivas (`20261123000100` a `20261123000300`) y la iteración 2, seis (`20261124000100` a `20261124000600`), todas solo locales: 51 migraciones y 80 tablas. La iteración 2 agrega la dependencia `openpyxl`.
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

Las decisiones de los bloques 5 a 8 están desarrolladas en la **sección 11**; las preguntas de abajo son las originales.

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

### 10.2 Bloque 3: ingreso

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. `business/` no cambia: implementa DEC-AJ-05, DEC-AJ-06, DEC-AJ-07 y DEC-AJ-08 (sección 9.1).

| Commit | Qué |
|---|---|
| `0376f34` | Migración `20261123000200_ingreso_trabajo_verificacion_imei` y persistencia de los datos nuevos del ingreso |
| `462ff87` | BF-04 (DEC-AJ-05), BF-08 (DEC-AJ-07) y la parte de backend de BF-06 (DEC-AJ-08): ingreso sin trabajos, custodia con el comprobante de recepción y verificación del ingreso |
| `869a003` | BF-05 (DEC-AJ-06): «IMEI no disponible» y «Registrar el IMEI real» |
| `e1ffcd0` | Frontend de los cuatro: alta, «Crear y generar el comprobante», visor, Orden y check-in |
| `a55b1b8` | Frontend: «IMEI no disponible» vuelve a «Ninguno» la identidad elegida por IMEI |

#### Ingreso sin trabajos estandarizados (DEC-AJ-05)

- **Trabajo solicitado:** texto libre propio de la recepción (`DatosRecepcion.trabajo_solicitado`, `rma.recepcion.trabajo_solicitado`), distinto de las «Observaciones del equipo». No crea Detalles.
  - Se registra al crear la Orden.
  - Se corrige como el resto del ingreso: con versión y, si cambia un dato ya registrado, con motivo.
  - Sale en la Orden, en el comprobante de recepción y en el de ingreso (también en el PDF).
- **Sin trabajos:** el alta no exige un Tipo. El ingreso sigue por «Enviar a revisión técnica» (PROC-REP-045 = No, VAR-REP-001).
- **Custodia con el comprobante de recepción:** en Cliente Externo, enviar a revisión confirma la recepción física en el mismo acto (`application/ingreso.py`, `enviar_a_revision`, con `services/reparaciones.py`, `recepcion_con_el_comprobante`).
  - El historial queda 045 → 055 → ACC-REP-024 (confirmación) → 050 → 060. El comprobante se emite con la custodia `EN_CUSTODIA` y quién la confirmó.
  - Exige lo mismo que recibir el equipo (`faltantes_para_recepcion`): el estado físico (u observaciones unificadas) y la verificación del ingreso. Si falta algo, se rechaza sin registrar nada, y la acción ENVIAR_A_REVISION lo informa en `bloqueo`.
  - Además de `ENVIAR_A_REVISION`, exige `CUSTODIA`, el permiso de confirmar la recepción.
  - No cambian RT_INTERNO (VAR-REP-002) ni la garantía RMA, que no pasa por este comando.
- **Después:**
  - el técnico revisa y define los trabajos (065 → 068 → 075);
  - la definición se cierra y la Orden espera la decisión del cliente (129);
  - con la autorización sigue como siempre (080 → 090 → 140).

  Con el equipo en custodia también se ofrece la devolución sin reparar (DC31), como cuando la custodia se confirmaba aparte.
- **Con trabajos:** sin cambios. El comprobante de ingreso y autorización confirma, autoriza y emite en una sola operación (BR-REP-046). Ahora exige también la verificación.

#### Verificación inicial (DEC-AJ-07)

- **Datos:** `funcionalidades_verificadas` (Sí, No o sin responder) y `observaciones_verificacion`, en la recepción y en sus versiones. Son columnas nuevas: no se reutilizan `recepcion.checkin_ingreso` ni `DatosRecepcion.checkin`.
- **Obligatoria:**
  - En la pantalla, para crear la Orden, en los dos orígenes.
  - En la API, para recibir el equipo con el comprobante: el de ingreso y autorización y, sin trabajos, el de recepción (faltantes y `bloqueo`).
  - Crear la Orden por la API sin la respuesta sigue siendo posible (BR-REP-023): se completa después con la corrección del ingreso.
  - Registrar la primera respuesta no pide motivo; cambiarla es una corrección.
- **Dónde se ve:**
  - en «Cliente y equipo» de la Orden;
  - en los comprobantes de recepción y de ingreso, en pantalla y en el PDF («Funcionalidades verificadas al ingresar»);
  - como referencia, junto al check-in de entrega: en el formulario de entrega y en «Registrar el check-in».
- **Sin efecto sobre la garantía:** el check-in de entrega sigue igual. La entrega lo sigue exigiendo. Los plazos siguen siendo de 90 o 30 días según ese check-in, sin importar la respuesta del ingreso.

#### Crear y generar el comprobante (DEC-AJ-08)

- «Nueva orden» de Cliente Externo termina con **«Crear y generar el comprobante»** (`PanelOrdenes.tsx`, `crearYGenerar`). Encadena dos comandos:
  - **Con trabajo inicial:** crea la Orden y genera el comprobante de ingreso y autorización. El canal llega presencial y se puede cambiar en el mismo formulario; se registra igual (BR-REP-028).
  - **Sin trabajo:** crea la Orden y la envía a revisión, con el comprobante de recepción que confirma la custodia.
- **Visor:** se abre con el comprobante generado y **«Imprimir»** como acción principal (el PDF en el de ingreso; la hoja imprimible en el de recepción). La impresión la inicia el clic del usuario: no se imprime sola después de las llamadas.
- **Si el comprobante falla:** la Orden ya quedó creada. El error se muestra en esa Orden y el comprobante se genera desde ahí.
- **Idempotencia:** crear la Orden y el comprobante de ingreso ya lo eran. Ahora enviar a revisión también: un reintento sobre la Orden ya enviada y todavía sin revisar la devuelve sin cambios.
- **Confirmaciones:** no se agregó ninguna.

#### IMEI no disponible e IMEI real (DEC-AJ-06)

- **«IMEI no disponible»:** un botón junto al IMEI.
  - El campo queda vacío y la recepción guarda la marca `imei_no_disponible`.
  - El equipo se identifica con su `EQP-…` (DEC-UX-02). Se aclara que es provisorio y que no es un IMEI en el alta, en la cabecera, en «Cliente y equipo», en los comprobantes y en el PDF.
  - El backend rechaza la marca junto con un IMEI: nunca un IMEI ficticio.
- **«Registrar el IMEI real»:** `POST /api/orders/{id}/real-imei`. El IMEI viaja en el cuerpo, nunca en la URL (P1-18).
  - **Cuándo:** se ofrece (`acciones_custodia`) mientras el equipo no tenga IMEI y la Orden no se haya entregado ni devuelto, también con la custodia confirmada. Después de la entrega se rechaza.
  - **Motivo y permiso:** el motivo es obligatorio. Usa el permiso configurable de la corrección del ingreso, `INGRESO_CORREGIR` (DEC-MI-07): Recepción, Coordinación RMA y Administración. No hay permiso nuevo.
  - **Auditoría:** como en las correcciones del ingreso. Queda una versión de la recepción con el equipo anterior, el motivo y el cambio `equipo.imei`, y el paso ACC-REP-023 `REGISTRAR_IMEI_REAL` («Datos del ingreso corregidos», EV-REP-002). El IMEI no va en la observación del historial.
  - **Qué cambia:** `rma.equipo.imei` y la copia de la Orden. No cambian la fila decidida de `rma.recepcion` (el trigger `recepcion_decidida_no_cambia` sigue igual), los comprobantes emitidos ni el identificador interno.
- **Otro equipo con ese IMEI (DEC-MI-11):**
  - Responde 409 `CONFIRMACION_REQUERIDA` con los `EQP-…` que coinciden, y no registra nada.
  - Si se confirma a propósito, el IMEI queda en este equipo, sin vincularlos.
  - Si es el mismo equipo, se usa «Corregir la vinculación».

#### Migración

`20261123000200_ingreso_trabajo_verificacion_imei.sql`, aditiva e idempotente:

- cuatro columnas en `rma.recepcion`: `trabajo_solicitado`, `funcionalidades_verificadas`, `observaciones_verificacion` e `imei_no_disponible` (`false` por defecto);
- los comentarios de esas columnas y el de `rma.recepcion_version`, que ahora también guarda el registro del IMEI real.

No agrega tablas, así que los scripts de reinicio del UAT no cambian.

#### Pruebas nuevas

| Archivo | Casos | Qué cubre |
|---|---|---|
| `tests/test_ingreso_sin_trabajos.py` | 12 | Alta sin trabajos con el trabajo solicitado y su corrección versionada; el comprobante de recepción confirma la custodia (historial, contenido, idempotencia); sin estado físico ni verificación no se recibe ni queda nada; RT_INTERNO sin cambios; definición del técnico y autorización del cliente después; con trabajos, el comprobante de ingreso con el canal; crear y generar con y sin trabajos; la Orden queda creada si falla el comprobante; verificación obligatoria, registrada, corregida con motivo, en los comprobantes y el PDF; la garantía no cambia (90/30 solo según el check-in de entrega) |
| `tests/test_imei_no_disponible.py` | 6 | IMEI vacío con `EQP-…` y la aclaración en el PDF; la marca con un IMEI se rechaza; IMEI real con la custodia confirmada (motivo, versión, historial sin el IMEI, comprobante sin cambios, una sola vez); permiso; rechazado después de la entrega; aviso de otro equipo sin vincular |
| `tests/postgres/test_ingreso_bloque3_postgres.py` | 2 | Columnas nuevas y sus versiones guardadas y releídas; custodia con el comprobante de recepción e IMEI real después (equipo y copia de la Orden, recepción sin tocar, EV-REP-002) |
| Frontend `tests/ingreso-ajustes.test.ts` | 8 | Datos del alta, faltantes, verificación y su referencia en el check-in, comprobante del alta, comprobante que abre el visor, identificación provisoria e IMEI real |

#### Pruebas existentes adaptadas (aprobado: fijaban las reglas reemplazadas)

- **Fixtures centrales:**
  - `tests/fixtures/custodia.py`: `preparar_ingreso` registra la verificación si falta. Suma dos funciones:
    - `enviar_a_revision`, que deja los datos que exige el comprobante de recepción;
    - `revision_anterior_sin_custodia`, una Orden enviada a revisión antes de DEC-AJ-05, con la custodia pendiente, como las del UAT.
  - `tests/fixtures/ingreso_inicial.py`: el alta con la verificación.
  - `tests/fixtures/api_definicion.py` y `tests/fixtures/api_salidas.py`: el camino de revisión usa `enviar_a_revision`.
- **Custodia aparte del comprobante de recepción (DEC-AJ-05):**
  - `test_documentos_custodia_entrega.py`:
    - pruebas 2 a 8: el comprobante sale `EN_CUSTODIA` y la versión a pedido sale de una observación nueva;
    - prueba 5: pasa a verificar la confirmación con el comprobante (una sola vez, permisos y estado físico, sin dejar nada a medias);
    - prueba 7: la inmutabilidad se prueba con una observación;
    - prueba 1: compara también los datos nuevos de la recepción.
  - `test_ingreso_inicial.py` (2 pruebas), `test_api_var_rep_001_002.py` (historial con ACC-REP-024 y devolución ofrecida), `test_api_sin_reparacion.py`, `test_api_definicion.py`, `test_cancelacion_orden.py` y `test_comprobante_autorizacion.py`.
  - `test_entrega_y_garantia.py`: la entrega bloqueada por la custodia se prueba con una garantía RMA, que la sigue confirmando aparte.
  - `test_entrega_sin_aviso.py`, `test_orden_cerrada.py` y `test_permisos_operativos.py`: enviar a revisión exige también `CUSTODIA`.
  - `test_equipo_no_recibido.py`, `test_inventario_operativo.py` y `test_situacion_operativa.py`: la custodia pendiente después de enviar a revisión se arma como una Orden anterior a DEC-AJ-05 (`revision_anterior_sin_custodia`).
  - `tests/postgres/test_recepcion_documentos_postgres.py` y `tests/postgres/corpus_ordenes.py`: la verificación se registra antes del comprobante.
- **Idempotencia:** `test_api_var_rep_001_002.py` ya no espera 409 al enviar dos veces: el segundo envío no duplica nada (historial y documentos iguales).
- **Alta sin la verificación:** `test_ux_recepcion.py`.
- **Ruta nueva:** `test_matriz_permisos.py` clasifica `real-imei` y suma `CUSTODIA` a `send-to-review`.
- **Scripts E2E (sin ejecutar):** `probar_macro_v14.py` (`crear_ficticia`), `probar_ux_recepcion.py` (`alta`) y `probar_recorridos.py` registran la verificación.

No se debilitó ninguna comprobación de custodia, autorización, inmutabilidad de documentos, idempotencia ni permisos.

#### Pruebas ejecutadas (focalizadas)

| Ámbito | Resultado |
|---|---|
| Backend: 79 archivos (ingreso, ingreso inicial, corrección del ingreso, custodia y documentos, identidad, VAR-REP-001/002, caracterización, recepción, check-in y garantía, entregas, matriz de permisos, cancelaciones, situación, bandejas, HP/EXC, macro V1.4, permisos y PDF, entre otros), con los 2 nuevos | 989 pasan (29 omitidas); falla `test_pagos_devoluciones.py::test_21_no_se_entrega_con_saldo_pendiente`, que ya fallaba antes de este bloque (ver limitaciones) |
| PostgreSQL local: `test_ingreso_bloque3` (nuevo), `test_recepcion_documentos`, `test_ux_recepcion`, `test_ordenes`, `test_cierre_ux`, `test_entrega`, `test_iteracion1`, `test_macro_v14`, `test_consultas`, `test_identidad_equipo`, `test_idempotencia`, `test_pruebas_sql_supabase`, `test_reinicio_clasificacion`, `test_permisos_operativos`, `test_firmas`, `test_comunicaciones`, `test_motivos_retiro`, `test_finanzas`, `test_reservas`, `test_garantias_tipo` y `test_bloque_a` | 239 pasan |
| Backend: `ruff check . ../../supabase/scripts` y `ruff format --check` de los archivos tocados | Limpios |
| Frontend: `typecheck`, `npm test` y `npm run build` | Pasan (217 pruebas) |
| Arranque | Backend local en modo JSON con `/health` 200; `npm run dev` levanta |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Decisiones tomadas en la implementación

- **Dónde vive el trabajo solicitado:** en los datos de la recepción, no en la raíz de la Orden. Así se versiona y se corrige como el resto del ingreso, y queda fijo con la custodia.
- **Dónde se exige la verificación:** en la API, al recibir el equipo con el comprobante, no al crear la Orden. BR-REP-023 dice que ningún campo es obligatorio para crear; así no se rompen los clientes de la API ni las Órdenes ya creadas. La pantalla la exige al crear.
- **Orden del historial:** la confirmación de la custodia va antes de 050/060, como en el comprobante de ingreso, para que el comprobante de recepción salga con la custodia confirmada.
- **Permiso para enviar a revisión:** como el mismo acto confirma la custodia, exige también `CUSTODIA`. Con la configuración inicial, Recepción tiene los dos.
- **Auditoría del IMEI real:** se reutilizan la versión de la recepción (`rma.recepcion_version`, que solo crece) en lugar de una tabla nueva, y el permiso de corrección del ingreso en lugar de uno nuevo.
- **La marca «IMEI no disponible»:** es un hecho del ingreso. Se conserva después de registrar el IMEI real; cuando el IMEI existe, la pantalla muestra el IMEI.
- **Comprobante de recepción:** se sigue imprimiendo desde la hoja del navegador, sin un PDF propio. `test_comprobante_autorizacion.py` fija que solo el de ingreso y el de autorización se descargan como PDF.
- **Verificación en RT_INTERNO:** la pantalla la pide en los dos orígenes; la API solo la exige cuando el comprobante confirma la custodia (Cliente Externo).

#### Limitaciones y pendientes

- **Garantía RMA:** su ingreso sigue confirmando la custodia aparte y no pide la verificación (DEC-AJ-05 habla del ingreso de Cliente Externo). El formulario de la garantía no cambió.
- **Órdenes del UAT:**
  - las que ya se enviaron a revisión conservan su custodia pendiente y se confirman como antes;
  - las que están en REQUERIMIENTO sin la verificación tienen que responderla (corrección del ingreso) antes de generar el comprobante.
- **IMEI en la URL:** la identificación por IMEI del alta sigue mandándolo en la URL (`/equipment/identify`, P1-18). El registro del IMEI real lo manda en el cuerpo, y la búsqueda de coincidencias se hace en el servidor.
- **Prueba que ya fallaba:** `test_pagos_devoluciones.py::test_21_no_se_entrega_con_saldo_pendiente` falla también sin este bloque. Espera PROC-REP-266 en el mensaje de rechazo, que el bloque 2 cambió.
- **Documentación:** no se actualizaron en este bloque `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-05 a 08 siguen «sin implementar») ni `docs/ESTADO_PROYECTO.md`.
- **Validación manual:** pendiente, en local y en un navegador. Recorrido:
  1. alta con trabajo y alta sin trabajo;
  2. impresión desde el visor;
  3. IMEI no disponible y registro del IMEI real después de la custodia;
  4. check-in con la referencia del ingreso.

### 10.3 Bloque 4: comprobantes

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. `business/` no cambia: implementa el resto de DEC-AJ-09 (la parte P-05 ya estaba en el bloque 2) y el pendiente del bloque 2 sobre el progreso de la Orden (DEC-AJ-03).

| Commit | Qué |
|---|---|
| `d657ca5` | Migración `20261123000300_comprobantes_empresa_terminos` y persistencia de los datos de la empresa y de los términos versionados |
| `0552bbd` | BF-19 (DEC-AJ-09): API y servicio de los datos de la empresa y de los términos; los comprobantes copian la empresa y la versión de los términos |
| `1a14ea5` | DEC-AJ-03: en el progreso, avisar al cliente figura opcional y salteado, no pendiente |
| `89a3e6a` | Frontend: «Datos de la empresa», «Términos y condiciones», hoja de los comprobantes y página de términos |

#### Datos de la empresa (DEC-AJ-09 a y b)

- **Quién:** Administración, con el permiso no configurable de parámetros del sistema, `CONFIGURACION_ADMINISTRAR` (alternativa aprobada en D-09 a). Su descripción ahora nombra los datos de la empresa y los términos.
- **Qué:** nombre comercial (obligatorio: encabeza cada comprobante), razón social, CUIT, dirección, teléfono, email, horario de atención y un pie de comprobante libre. Un campo vacío queda sin informar.
- **API:** `GET /api/admin/company` (`editable` y `empresa`) y `PUT /api/admin/company`. Sin cambios, sin nombre o con un email sin `@`: 409. La escritura es solo sobre PostgreSQL, como el resto de la configuración (DC23); en JSON la pantalla queda de solo lectura.
- **Auditoría:** un registro por campo cambiado en `cambio_configuracion`, entidad `EMPRESA`, clave `EMPRESA` (`services/comprobantes.py`, `datos_de_empresa_editados`).
- **Pantalla:** Configuración → grupo «Comprobantes» → «Datos de la empresa», con su historial de cambios.
- **Comprobantes:** todos (recepción, ingreso ING, autorización y entrega y garantía) copian la empresa en su snapshot, ahora con `horario` y `pie_comprobante`. La hoja muestra nombre, razón social, CUIT, dirección, teléfono, email y horario; el pie va al final (en la entrega, antes de la página de términos). El PDF del ingreso y de la autorización imprime el horario en el encabezado y el pie al final.
- **Snapshots anteriores:** los campos nuevos son opcionales; un documento emitido antes se sigue leyendo y se imprime sin horario ni pie. Cambiar la empresa no altera lo emitido.

#### Términos y condiciones versionados (DEC-AJ-09 f)

- **Dónde:** en `rma.texto_legal`, que ya era inmutable (trigger `texto_legal_inmutable`): una versión publicada no se edita ni se borra.
- **Vigente:** la de mayor número. Publicar crea la versión siguiente, completa y vigente desde ese momento (`vigente_desde` es la fecha de publicación y `publicado_por`, el usuario).
- **API:** `GET /api/admin/terms` (`vigente` y `versiones`) y `POST /api/admin/terms` (`titulo` y `contenido`: encabezado, apartados y pie). Los apartados se numeran en el orden recibido. Un texto igual al vigente: 409. Dos publicaciones simultáneas no pisan una versión: la segunda falla con 409.
- **Auditoría:** entidad `TEXTO_LEGAL`, clave `TERMINOS_CONDICIONES_ENTREGA`, campo `version` (de la anterior a la nueva).
- **Pantalla:** «Términos y condiciones» lista las versiones (con la vigente marcada y cada una para ver) y arma una versión nueva a partir de la vigente: título, marca, subtítulo, apartados (una línea por renglón, resaltado, quitar y agregar) y los espacios del pie. No publica sin cambios ni con apartados vacíos.
- **En cada comprobante:** el «Comprobante de entrega y garantía» guarda la copia de la versión vigente al emitirse (`contenido.terminos`) y, en PostgreSQL, `documento_emitido.texto_legal_id`. La página de términos imprime esa versión, con su número, aunque después se publique otra. La vista previa muestra la vigente. Una devolución sin reparación no lleva términos.
- **Anteriores:** un comprobante emitido antes, sin `terminos`, imprime el texto anterior del frontend (`terminosCondiciones.ts`, el del bloque 2), como hasta ahora.
- **Modo JSON:** rige la versión inicial (`app/datos/terminos_condiciones_v2.json`); un `textos_legales.json` en los catálogos permite probar otra.

#### Versión inicial con P-04 y P-05

- La migración carga la **versión 2**: el texto vigente del bloque 2 (sin el apartado que anulaba la garantía si retiraba otra persona ni la exigencia de que retire quien dejó el equipo, P-05) con P-04 aplicado.
- **P-04:** el apartado 1 ya no dice «seis meses (180 días de corrido)». Dice: «La reparación cuenta con la garantía indicada para cada trabajo en este comprobante, con su plazo en días y su fecha de vencimiento, válida exclusivamente sobre el trabajo realizado y/o el repuesto colocado, contada a partir de la fecha de entrega del equipo». El comprobante ya lista cada trabajo con su plazo y su vencimiento (90 o 30 días según el Tipo y el check-in, o el ajustado). Las reglas de garantía no cambian.
- **P-05:** el comprobante sigue diciendo quién retiró (el titular, u otra persona con nombre, apellido y teléfono) y los términos no anulan la garantía por eso.
- **Versión 1:** queda como estaba (la transcripción original). `generar_datos_iniciales.cjs` ya no la regenera desde el frontend: está congelada.

#### Progreso de la Orden (pendiente del bloque 2, DEC-AJ-03)

- `progreso` suma `opcional` y `omitido` a cada paso (`application/progreso.py`, `PasoProgresoOut`). PROC-REP-260 «Notificar cliente» es opcional; si la Orden ya siguió adelante sin el aviso (entrega sin aviso, también SIN_REPARACION), queda `omitido`. `alcanzado` no cambia de significado y el grafo del proceso tampoco.
- En el «Recorrido técnico del proceso», un paso opcional tiene borde punteado; el omitido, además, tachado, con el título «(opcional, salteado)».

#### Migración

`20261123000300_comprobantes_empresa_terminos.sql`, aditiva e idempotente:

- `rma.empresa`: columnas `horario` y `pie_comprobante`, con sus comentarios;
- `cambio_configuracion.entidad` admite `EMPRESA` y `TEXTO_LEGAL` (el CHECK se reemplaza agregando valores, como en las migraciones anteriores);
- `rma.texto_legal`: la versión 2 de `TERMINOS_CONDICIONES_ENTREGA`, con `on conflict do nothing`. Es la misma copia que `app/datos/terminos_condiciones_v2.json` (lo verifica `tests/test_comprobantes.py`).

No agrega tablas ni permisos de base (`rma_backend` ya podía insertar en `texto_legal` y actualizar `empresa`), así que los scripts de reinicio del UAT no cambian: `empresa` y `texto_legal` ya son maestras.

#### Pruebas nuevas

| Archivo | Casos | Qué cubre |
|---|---|---|
| `tests/test_comprobantes.py` | 12 | Edición de la empresa auditada por campo, que conserva lo que no edita; solo Administración, nombre obligatorio, sin cambios rechazado; en JSON, empresa y términos de solo lectura; los comprobantes nuevos copian empresa, horario y pie (también en el PDF) y lo emitido no cambia; un snapshot anterior se sigue leyendo; P-04 sin 180 días ni anulación por terceros; la migración carga la misma versión 2; una versión nueva numera apartados y se audita; igual a la vigente o de otro rol, no se publica; el comprobante guarda e imprime su versión y la conserva cuando rige otra; quién retiró, en el comprobante, sin cambiar la garantía; la devolución sin reparación no lleva términos |
| `tests/test_progreso_aviso_opcional.py` | 3 | 260 opcional antes de entregar, omitido al entregar sin aviso (también SIN_REPARACION) y alcanzado con aviso |
| `tests/postgres/test_comprobantes_postgres.py` | 3 | Columnas y versiones 1 y 2 de la migración; edición de la empresa con auditoría `EMPRESA`, 409 para Recepción y comprobantes antes y después; versión 3 publicada con auditoría `TEXTO_LEGAL`, `texto_legal_id` de cada comprobante (2 y 3), 409 para Recepción y sin cambios, y una versión usada que no se modifica ni se borra |
| Frontend `tests/comprobantes.test.ts` | 5 | Datos de la empresa en la hoja (con y sin horario y pie), formulario de la empresa, borrador de los términos, numeración y faltantes |
| Frontend `tests/progreso.test.ts` | 1 | Título del paso opcional y salteado |
| Frontend `tests/terminos.test.ts` | +2 | Imprime la versión guardada; sin versión, el texto anterior |

Además, `tests/postgres/test_contrato_catalogos.py` compara la versión vigente de PostgreSQL con la del modo JSON. Con sesión real, el 403 de cada ruta nueva lo prueba `tests/postgres/test_permisos_operativos_postgres.py`, que recorre la matriz.

#### Pruebas existentes adaptadas

- `tests/test_matriz_permisos.py`: clasifica las cuatro rutas nuevas con `CONFIGURACION_ADMINISTRAR` (control permanente de la matriz).
- Frontend `tests/configuracion-v2.test.ts`: Administración ve 13 subsecciones (eran 11) y el grupo nuevo «Comprobantes».
- Frontend `tests/terminos.test.ts`: la prueba de los 18 apartados pasa a describir el texto anterior; sus aserciones no cambian.

No se debilitó ninguna comprobación de inmutabilidad o versionado de documentos, permisos, auditoría ni idempotencia.

#### Pruebas ejecutadas (focalizadas)

| Ámbito | Resultado |
|---|---|
| Backend: 58 archivos (documentos y custodia, comprobantes, entregas, quién retira, ingreso, IMEI, configuración, matriz y permisos, garantías, check-in, HP/EXC/VAR, caracterización, SIN_REPARACION, historial, PDF, firmas, comunicaciones, recargos, motivos, pagos, situación, bandejas, repositorios JSON y generador de cargas, entre otros) | 871 pasan (29 omitidas). Después, con las pruebas del progreso en su archivo: `test_comprobantes.py` y `test_progreso_aviso_opcional.py`, 15 pasan |
| PostgreSQL local: `test_comprobantes` (nuevo), `test_contrato_catalogos`, `test_recepcion_documentos`, `test_entrega`, `test_pruebas_sql_supabase`, `test_reinicio_clasificacion`, `test_permisos_operativos`, `test_ordenes`, `test_configuracion`, `test_recargo_medio_pago`, `test_ejecutor_sql`, `test_cargas_iniciales`, `test_macro_v14`, `test_ingreso_bloque3`, `test_cierre_ux` y `test_firmas` | 262 pasan |
| PostgreSQL local, segunda tanda: `test_reclamos_garantia`, `test_iteracion1`, `test_arranque`, `test_ux_recepcion`, `test_comprobantes`, `test_motivos_retiro` y `test_comunicaciones` | 19 pasan |
| Backend: `ruff check . ../../supabase/scripts` y `ruff format --check` de los archivos tocados | Limpios |
| Frontend: `typecheck`, `npm test` y `npm run build` | Pasan (225 pruebas) |
| Arranque | Backend local en modo JSON con `/health` 200 y las rutas nuevas respondiendo; `npm run dev` levanta |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Decisiones tomadas en la implementación

- **Permiso:** `CONFIGURACION_ADMINISTRAR`, el no configurable de Administración (D-09 a), para la empresa y para los términos; no se creó un permiso nuevo.
- **Campos editables:** los ocho de la tarea. Las «condiciones de garantía» de `rma.empresa` no se editan en la pantalla (las cubren los términos versionados) y se conservan al guardar.
- **Versión vigente:** la de mayor número; se publica vigente desde ese momento, sin versiones a futuro. Así la vigencia no depende de la diferencia entre el reloj del servidor y el de la base.
- **Copia y referencia:** el comprobante guarda la versión completa en su snapshot (como el resto de lo que imprime) y, en PostgreSQL, además `texto_legal_id`. La impresión sale de la copia, así que también funciona en JSON.
- **Texto anterior:** los comprobantes emitidos antes del bloque 4 siguen imprimiendo el texto del frontend del bloque 2 (con los 180 días), que es el que se les imprimía. P-04 rige para los nuevos.
- **Versión inicial por migración:** la versión 2 la carga una migración, no una carga inicial, para que llegue al UAT al migrar. La versión 1 queda congelada.
- **Pie del comprobante:** va al final de cada hoja; en la de entrega, antes de la página de términos, para que quede en la hoja que se entrega.
- **Progreso:** se agregan `opcional` y `omitido` en lugar de cambiar `alcanzado`, para no alterar su significado ni las pruebas y pantallas que lo usan.

#### Limitaciones y pendientes

- **Texto de negocio:** los apartados 6 («los equipos que ingresen apagados… no cuentan con garantía») y 18 (plazos desde la notificación) no se tocaron. El 6 puede no coincidir con la regla vigente (sin check-in, el trabajo igual tiene 30 días) y el 18 cuenta desde la notificación, que ahora es opcional (DEC-AJ-03). Los define el negocio con una versión nueva desde Configuración.
- **Leyendas:** las de los comprobantes de recepción, ingreso y autorización siguen fijas en el código (`services/documentos.py`); D-09 no las incluyó.
- **Comprobante de entrega en PDF:** se sigue imprimiendo desde el navegador; el PDF descargable es solo el de ingreso y el de autorización.
- **Modo JSON:** la empresa y los términos se ven, pero no se editan (la configuración se administra sobre PostgreSQL).
- **Documentación:** no se actualizaron en este bloque `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-09 sigue «sin implementar»), `docs/pendientes-producto.md` (P-04 y P-05) ni `docs/ESTADO_PROYECTO.md`. Las rutas nuevas sí están en `docs/contratos-macro-integral.md`.
- **Validación manual:** pendiente, en local y en un navegador:
  1. editar los datos de la empresa y ver un comprobante nuevo y uno anterior;
  2. publicar una versión de los términos y entregar una Orden antes y otra después;
  3. reimprimir el comprobante anterior;
  4. ver el progreso de una Orden entregada sin aviso.

## 11. Decisiones de la iteración 2 (bloques 5 a 8): análisis y propuestas (23/11/2026)

> **Aprobadas el 23/11/2026, con cambios: rige la sección 11.1.** Lo que sigue es el análisis y las propuestas que se presentaron a revisión. Donde difiere de 11.1 (por ejemplo D-12.2, D-13.1, D-14.3 y D-14.4), vale 11.1.

Revisado contra el código, el esquema (45 migraciones) y `business/` (`713a9b9`). Reemplaza las preguntas de la sección 4 para los bloques 5 a 8. Cada decisión aprobada se registra como DEC-AJ en `rt-rma-app` antes del código, igual que en la iteración 1.

**Datos que cambian el planteo:**

- **BF-09:** BR-REP-016 **ya unifica** descuento y cortesía en un único «Ajuste Comercial», con motivo, usuario, fecha e historial. Lo que falta es la reversión de un error, la copia de los importes, el historial de la Orden (EV-REP-041 nunca se emite) y que los comprobantes muestren el ajuste por trabajo.
- **BF-15:** el «faltante» actual **no puede ocurrir en PostgreSQL**: el trigger impide que el stock físico quede por debajo de lo reservado. Por eso el filtro «Solo faltantes» y la bandeja «Insumos negativos» siempre están vacíos. El mínimo necesita su propia comparación.
- **BF-01:** el catálogo de modelos (`modelo_equipo`) es un archivo fijo con 36 modelos Apple, sin pantalla de alta. Falta la línea iPhone 18 (ABI-43). El nombre del trabajo no se copia en el Detalle: se lee del catálogo en cada pantalla.
- **BF-14:** los insumos previstos por tipo (`tipo_reparacion_insumo`) **no tienen pantalla ni API**: solo se cargan por seed. La reserva, el consumo y el libro trabajan siempre sobre el mismo `insumo_id`.
- **BF-02:** no hay subida de archivos multipart ni lector de Excel. Las fotos y firmas suben el cuerpo crudo.

### Bloque 5. D-10 (BF-09): ajustes comerciales

#### D-10.1 Unificación y permisos

- **Hoy:**
  - hay una sola entidad, pero tres formularios: descuento a la Orden, cortesía a la Orden y ajuste por trabajo;
  - el comprobante imprime «Descuento» aunque sea una cortesía;
  - se mantienen dos permisos, DESCUENTO y CORTESIA, ambos por defecto para Recepción, Coordinación y Administración (BR-REP-039).
- **Alternativas:**
  - (A) una sola acción «Ajuste comercial», que elige la clase (descuento o cortesía) y el destino (la Orden o un trabajo), conservando los dos permisos;
  - (B) además, fusionar los permisos y eliminar la clase.
- **Propuesta:** **A**. La clase sirve para distinguir en reportes y comprobantes, y los permisos ya tienen los mismos roles: para el usuario es una sola acción. Se corrige además un hueco: hoy, con solo DESCUENTO, la API deja reemplazar una cortesía vigente. Cambiar o quitar un ajuste va a exigir el permiso de la clase que se reemplaza y el de la nueva.
- **Consecuencias:** un formulario único, con una vista previa del precio original, el ajuste y el final. La validación de la cortesía usa la misma base que el backend.
- **Datos y migraciones:** ninguna.

#### D-10.2 Corregir o revertir un ajuste equivocado

- **Hoy:**
  - «rige el último» por destino (la Orden o el trabajo);
  - cambiar o quitar es un registro nuevo con motivo, indistinguible de una corrección;
  - los registros no tienen identificador en el dominio y no quedan en el historial de la Orden.
- **Alternativas:**
  - (A) dejarlo así y solo mostrar mejor el historial;
  - (B) **reversión**, como la anulación de pagos: el registro equivocado queda marcado como revertido (quién, cuándo y motivo), deja de contar y **vuelve a regir el ajuste anterior válido**. «Corregir» es revertir y aplicar el correcto en una sola confirmación, y el nuevo queda enlazado al que corrige;
  - (C) un registro de tipo «corrección», sin marcar el original.
- **Propuesta:** **B**.
  - «Cambiar» y «Quitar» siguen siendo decisiones comerciales; «Revertir» y «Corregir» son la enmienda de un error.
  - Permiso nuevo «Revertir un ajuste comercial», por defecto para Coordinación y Administración y configurable. La anulación de pagos es solo de Administración; ¿se prefiere lo mismo?
  - Cada alta, cambio, retiro y reversión queda en el historial de la Orden (EV-REP-041).
- **Consecuencias:**
  - Revertir con pagos ya hechos puede dejar saldo a cobrar o saldo a favor. Se resuelve con el circuito actual: cobro, o devolución enlazada al pago. La entrega sigue exigiendo saldo 0.
  - Habilita, como hoy, una nueva versión del comprobante de autorización.
- **Datos y migraciones:** aditiva.
  - En `descuento`: `revertido_por`, `revertido_en`, `reversion_motivo` y `corrige_a`.
  - Cambio del trigger de inmutabilidad para admitir una única reversión, como en `pago`.
  - Nueva definición de `v_orden_saldo`, que excluye los revertidos, cambiada junto con el dominio.
  - Equivalencia de historial para EV-REP-041.
  - Los registros viejos quedan sin revertir.

#### D-10.3 Ajustes después de la entrega

- **Hoy:** solo con la Orden abierta (servicio y trigger).
- **Alternativas:**
  - (A) mantenerlo: después de la entrega no se ajusta ni se revierte;
  - (B) permitir la reversión después de la entrega, solo a Administración. Genera saldo, cobro o devolución posterior y una nueva versión del comprobante de entrega.
- **Propuesta:** **A**. La entrega cierra la cuenta con saldo 0 y un comprobante inmutable; reabrirla toca la caja y los documentos ya firmados. Si el negocio lo necesita, es un circuito propio de posventa.
- **Consecuencias:** un error detectado después de la entrega se resuelve fuera de la Orden.
- **Datos y migraciones:** ninguna.

#### D-10.4 Copia del precio original, el importe y el final

- **Hoy:** se derivan. Si después se redefine o se cancela el trabajo:
  - un porcentaje se recalcula sobre el precio nuevo;
  - un importe fijo se recorta en silencio al precio nuevo;
  - el ajuste de un trabajo cancelado deja de contar sin dejar rastro.
- **Alternativas:**
  - (A) solo derivar y mostrar;
  - (B) guardar en cada registro, como evidencia, el precio original, el importe aplicado y el final al momento de registrarlo. El saldo sigue calculándose sobre lo vigente, y un recálculo por redefinición o cancelación queda en el historial y se avisa antes de confirmar la redefinición;
  - (C) congelar el importe para que la redefinición no lo cambie. Contradice BR-REP-016, que lo topea al precio.
- **Propuesta:** **B**.
- **Consecuencias:** el historial muestra qué precio vio quien aplicó el ajuste y cuánto rige hoy.
- **Datos y migraciones:** aditiva. Tres columnas opcionales en `descuento`; los registros viejos quedan sin copia.

#### D-10.5 Qué muestran los comprobantes

- **Hoy:** una sola línea con el total de los ajustes y la palabra «Descuento». No hay importe por trabajo.
- **Alternativas:**
  - (A) por trabajo: precio, ajuste (clase y motivo) y precio final, más una línea aparte para el ajuste de la Orden. Usuario y fecha solo en el historial interno;
  - (B) igual, y además usuario y fecha en el comprobante del cliente.
- **Propuesta:** **A**. Usuario y fecha son controles internos; BF-09 pide registrarlos, no imprimirlos.
- **Consecuencias:** cambian los comprobantes de ingreso, de autorización y de entrega emitidos desde ahora. Los ya emitidos no cambian.
- **Datos y migraciones:** ninguna. Son campos opcionales del snapshot.

**Correcciones técnicas incluidas, sin decisión:**

- **Recargo:** el reparto que se muestra usa la copia que guarda cada pago, no los ajustes actuales (DEC-UX-13).
- **Vista previa del comprobante:** incluye los ajustes por trabajo.
- **Textos:** se corrigen los comentarios viejos («no por debajo de lo cobrado», «la cortesía queda fuera de alcance»).

### Bloque 6. D-11 (BF-15): stock mínimo

#### D-11.1 Contra qué cantidad se compara

- **Hoy:** no hay mínimo. Disponible = físico − reservado.
  - «En camino» suma las órdenes de compra en borrador, confirmadas y parciales, y las solicitudes pendientes.
- **Alternativas:**
  - (A) el stock físico: ignora lo comprometido con reparaciones;
  - (B) el disponible;
  - (C) disponible + en camino: la alerta desaparece apenas se pide.
- **Propuesta:** **B**, con dos estados:
  - «Bajo mínimo»;
  - «Bajo mínimo · repuesto pedido», cuando lo confirmado en órdenes de compra cubre la diferencia.

  Para ese segundo estado no cuentan los borradores ni las solicitudes.
- **Consecuencias:** la alerta sigue visible hasta que el repuesto entra, pero se distingue lo que ya está gestionado.
- **Datos y migraciones:** ver D-11.2.

#### D-11.2 Dónde y quién lo configura

- **Alternativas:**
  - (A) en Configuración → Insumos, con el permiso «Gestionar insumos» (Administración);
  - (B) en Inventario, con «Gestionar stock» (Administración y Coordinación).
- **Propuesta:** **A**. Todos los datos del insumo quedan en un solo formulario, auditado; el permiso es configurable si Coordinación también tiene que editarlo.
  - El mínimo es por insumo y opcional: vacío significa sin alerta.
  - Es solo un mínimo: no hay punto de pedido ni máximo.
- **Datos y migraciones:** aditiva. `insumo.stock_minimo`, opcional y ≥ 0, con su permiso de escritura y su auditoría.

#### D-11.3 Cómo se muestran las alertas

- **Propuesta:** en tres lugares, sin mecanismos nuevos:
  - **Inventario:** el estado «Bajo mínimo» y el filtro «Bajo mínimo», junto a «Solo faltantes».
  - **Inicio:** la bandeja «Insumos a reponer», para Coordinación y Administración. Reemplaza a «Insumos negativos», que en PostgreSQL siempre está vacía, y conserva los faltantes si los hubiera.
  - **Compras:** la sugerencia pasa a cubrir la demanda y además reponer hasta el mínimo (`demanda + mínimo − disponible − en camino`). La solicitud generada queda con el origen «Stock mínimo». Nunca se compra sola (BR-REP-049).
- **Alternativas:**
  - aviso en el menú: hoy no existen insignias en el menú;
  - notificación por correo o WhatsApp: no recomendada para un MVP.
- **Datos y migraciones:** aditiva. El nuevo origen `STOCK_MINIMO` en el CHECK de `solicitud_compra`.

### Bloques 7 y 8: diseño conjunto

**Modelo propuesto:**

```text
Tipo de Reparación (trabajo genérico: «Cambio de batería»)
  ├─ garantía, puntaje, Mesas, política RMA            (por tipo, como hoy)
  ├─ precio único                 si «precio por modelo» = No (diagnóstico, limpieza)
  ├─ precio por modelo ──► Modelo de equipo (MOD-…)     si «precio por modelo» = Sí
  └─ requisitos de insumo: subcategoría + cantidad  (o un insumo concreto, si es universal)
                               │
Insumo = SKU real con stock (INS-…) ◄─ Subcategoría ◄─ Categoría
  ├─ fabricante, variante, código del fabricante
  ├─ compatible con ──► Modelo de equipo (N:M; sin modelos = universal)
  └─ stock, lotes, costo, reservas, consumo y desperdicio   (sin cambios)
```

El stock, los lotes, el libro, Compras y las reservas siguen en la fila actual de `insumo`. **No hace falta mover ni repartir stock existente.**

#### D-12 (BF-01). Tipos de Reparación y precio por modelo

##### D-12.1 Estructura del precio

- **Hoy:** un precio único por tipo, copiado al Detalle (BR-REP-015). Los tipos son «por modelo» en el nombre.
- **Alternativas:**
  - (A) cada tipo indica si su precio varía por modelo. Si varía, el precio sale de la tabla (tipo, modelo); si no, del precio único actual;
  - (B) igual, pero con el precio único como respaldo cuando falta el del modelo;
  - (C) todos los tipos con precio por modelo.
- **Propuesta:** **A, sin respaldo**. Un precio base aplicado en silencio presupuesta mal un modelo caro. Los trabajos que no dependen del modelo (diagnóstico, software, limpieza) no necesitan cargar 36 precios.
- **Consecuencias:**
  - los selectores de trabajo (ingreso, agregar, adicional, evaluación y redefinición) muestran el precio para el modelo de la Orden;
  - el técnico sigue sin fijar precios;
  - la garantía RMA y RT Interno siguen siendo no cobrables.
- **Datos y migraciones:** aditiva.
  - `tipo_reparacion.precio_por_modelo` (por defecto No: los tipos actuales no cambian).
  - Tabla `precio_tipo_modelo` (tipo, modelo, precio), única por par.

##### D-12.2 Equipo sin modelo técnico o modelo sin precio

- **Alternativas:**
  - (A) ese tipo no se ofrece para ese equipo: se muestra «sin precio para este modelo». Las salidas son «Otros», con descripción y precio manual (ya existe para Recepción), o que Administración cargue el precio;
  - (B) precio manual del tipo con un permiso nuevo y motivo;
  - (C) usar el precio base.
- **Propuesta:** **A**. No crea una vía nueva para fijar precios fuera de Administración (DEC-CFG-03). «Otros» ya cubre el caso excepcional y se distingue en los reportes (BR-REP-047).
- **Consecuencias:** un equipo cargado a mano o fuera del catálogo solo puede recibir tipos de precio único u «Otros». Por eso importa D-12.5.
- **Datos y migraciones:** ninguna.

##### D-12.3 Qué depende del modelo

- **Propuesta:** solo el precio y, a través de BF-14, la pieza.
  - La garantía, el puntaje, las Mesas y la política RMA siguen siendo del tipo (BR-REP-011 y BR-REP-041).
  - Si un modelo necesita otra garantía u otro puntaje, es otro tipo.
- **Alternativa:** puntaje o garantía por modelo. Agrega dimensiones a la planilla de BF-02 y no fue pedido.
- **Datos y migraciones:** ninguna.

##### D-12.4 Datos históricos y tipos actuales

- **Hoy:** el Detalle guarda el tipo y la copia del precio, la garantía y el puntaje, pero no el nombre: renombrar un tipo cambia cómo se ven las Órdenes viejas.
- **Alternativas:**
  - (A) **sin conversión automática:** los tipos actuales siguen como de precio único. Administración crea los tipos genéricos (o los importa con BF-02) y desactiva los viejos cuando quiera, porque no se pueden borrar;
  - (B) una migración que renombra los tipos actuales a genéricos y mueve su precio al modelo del nombre. Depende de interpretar nombres libres y cambia la etiqueta de las Órdenes existentes.
- **Propuesta:** **A**. Además, cada Detalle nuevo guarda una copia del nombre del trabajo y del modelo con el que se tomó el precio. Las Órdenes viejas siguen leyendo el nombre del catálogo.
- **Consecuencias:**
  - durante la transición conviven tipos viejos y genéricos;
  - los reportes actuales no agrupan por tipo, así que no se mezclan.
- **Datos y migraciones:** aditiva. `detalle_version.nombre_trabajo` y `detalle_version.modelo_equipo_id`, opcionales.

##### D-12.5 Alta de modelos nuevos

- **Hoy:** los modelos salen de un archivo versionado con el código. Agregar el iPhone 18 exige un desarrollo (ABI-43).
- **Alternativas:**
  - (A) seguir regenerando el archivo;
  - (B) Administración da de alta y desactiva modelos (marca, modelo, variante) desde Configuración, auditado y con código MOD automático.
- **Propuesta:** **B**. La lista de precios y la compatibilidad de insumos dependen del catálogo, y salen modelos todos los años.
  - Cierra ABI-43 en la parte de los modelos.
  - No toca el catálogo de Ventas, que sigue siendo una copia de solo lectura (BR-REP-048).
- **Datos y migraciones:** aditiva.
  - Permiso de escritura sobre `modelo_equipo`.
  - Secuencia del código MOD (hoy no existe).
  - Entidad `MODELO_EQUIPO` en la auditoría.
  - Permiso nuevo o reutilizar «Gestionar tipos de reparación».

##### D-12.6 Cambio de modelo con trabajos ya cargados

- **Alternativas:**
  - (A) antes de la autorización del cliente, los precios por modelo se recalculan solos y se informa el cambio. Después, se conservan con un aviso «precio de otro modelo», y se corrige redefiniendo el trabajo;
  - (B) no recalcular nunca;
  - (C) bloquear el cambio de modelo.
- **Propuesta:** **A**. Antes de autorizar no hay nada pactado con el cliente; después rige la copia (BR-REP-015).
- **Datos y migraciones:** ninguna.

#### D-13 (BF-02). Importación de precios

##### D-13.1 Formato y claves

- **Alternativas:**
  - **forma de la planilla:** (A) una matriz, con modelos en las filas y tipos en las columnas, o (B) formato largo, una fila por tipo y modelo;
  - **cómo llega:** (C) subir el XLSX, que agrega dos dependencias (lector de Excel y subida multipart), o (D) el enlace de Google Sheets, que exige compartir la planilla con la cuenta de servicio.
- **Propuesta:** **una matriz (A)**, porque es como se maneja una lista de precios, cargada como CSV exportado de Excel o Sheets o pegando las celdas copiadas.
  - La pantalla ofrece **descargar la planilla actual** con los códigos y los precios vigentes. Se edita y se vuelve a subir.
  - Las claves son los códigos (MOD-… en las filas, TR-… en los encabezados). Los nombres van como referencia y se ignoran.
  - Se aceptan importes con formato argentino («80.000» o «80000,50»).

##### D-13.2 Alcance

- **Propuesta:**
  - crea o actualiza precios de tipos con precio por modelo y de modelos existentes;
  - **no crea tipos ni modelos**: se dan de alta individualmente (D-12.5);
  - una celda vacía no cambia nada;
  - quitar un precio se hace solo desde la edición individual;
  - la edición individual se mantiene;
  - permiso «Gestionar precios».
- **Alternativa:** que la importación cree tipos y modelos. Mezcla el alta del catálogo con la lista de precios.

##### D-13.3 Validación y errores

- **Alternativas:**
  - (A) vista previa con todos los errores y cambios (nuevo, cambia, sin cambios); se aplica **todo o nada**, en una transacción;
  - (B) aplicar las filas válidas y descartar las otras.
- **Propuesta:** **A**. Una lista de precios aplicada a medias es peor que ninguna.
  - Errores: código desconocido, tipo sin precio por modelo, importe inválido o con más de 2 decimales, celdas duplicadas.
  - Aviso, sin bloquear: una variación de más del 50 %.
- **Datos y migraciones:**
  - auditoría de cada precio que cambia, con un identificador común de la importación. Los que no cambian no se auditan;
  - entidad `PRECIO_MODELO` en la auditoría;
  - `historial_precio` extendido;
  - columna opcional del lote de importación en `cambio_configuracion`.

#### D-14 (BF-14). Jerarquía de insumos

##### D-14.1 Estructura

- **Alternativas** (sección 1):
  - (A) el insumo es la pieza física concreta (SKU), con su clasificación y su compatibilidad;
  - (B) un producto genérico con variantes que llevan stock;
  - (C) atributos libres.
- **Propuesta:** **A**.
  - Cada insumo actual ya es un SKU, con su stock, sus lotes, su costo y su desperdicio.
  - B rompe la regla de que lo previsto, lo reservado y lo consumido son el mismo insumo, y obliga a repartir stock con movimientos.
  - C no permite reportes ni reglas.
- **Consecuencias:** stock, costo, consumo y desperdicio por pieza real, como pide BF-14, sin tocar el libro.

##### D-14.2 Niveles y atributos

- **Propuesta:**
  - **Categoría → Subcategoría:** dos niveles fijos, administrables, con la subcategoría opcional (por ejemplo «Módulo → OLED»);
  - **Fabricante:** un catálogo administrable, distinto de la marca del equipo;
  - **Variante:** texto descriptivo (color, con marco);
  - **Código del fabricante o del proveedor:** opcional, para buscar. El SKU interno sigue siendo el código INS-…, que no cambia;
  - **Compatibilidad:** con los modelos del catálogo técnico, de muchos a muchos. Sin modelos significa universal (adhesivo, tornillería). Responde la pregunta abierta de ABI-53: los modelos salen de `modelo_equipo`, el mismo catálogo de los precios.
- **Alternativa:** un árbol de profundidad libre. Es más flexible, pero complica pantallas y reportes sin un caso concreto.
- **Datos y migraciones:** aditiva.
  - Tablas `categoria_insumo` (con padre), `fabricante_repuesto` e `insumo_compatibilidad`.
  - Columnas opcionales en `insumo`.
  - Entidades nuevas en la auditoría.

##### D-14.3 Calidad del repuesto y precio

Es la decisión de negocio central del cruce entre BF-01 y BF-14.

- **Alternativas:**
  - (A) si la calidad cambia el precio o la garantía para el cliente (original, OLED, alternativo), es **otro Tipo de Reparación** («Cambio de módulo original» y «Cambio de módulo alternativo»), cada uno con su subcategoría. Marca y variante dentro de una subcategoría son intercambiables para el cliente: mismo precio y misma garantía;
  - (B) el precio depende de tipo, modelo y calidad: la planilla de BF-02 pasa a tener tres dimensiones.
- **Propuesta:** **A**. Mantiene la matriz de precios simple y deja la elección de calidad explícita en la autorización del cliente.

##### D-14.4 Insumos previstos, reserva y consumo

- **Hoy:** el tipo prevé insumos concretos (sin pantalla), se reserva todo o nada al iniciar la ejecución, y no se consume lo que no se reservó.
- **Alternativas:**
  - (A) el tipo declara requisitos («1 Batería»). La factibilidad suma el disponible de los SKU compatibles con el modelo. **Al iniciar la ejecución, el técnico elige la pieza** entre las compatibles con stock (preseleccionada si hay una sola o una marcada como preferida). Antes de consumir puede cambiarla: se libera una reserva y se hace otra;
  - (B) el sistema elige solo la pieza (la preferida o la de más stock);
  - (C) Recepción elige la pieza al autorizar.
- **Propuesta:** **A**.
  - El requisito también puede ser un insumo concreto universal, que es como siguen funcionando los previstos actuales.
  - Se agrega la pantalla de requisitos por tipo, que hoy no existe.
- **Consecuencias:**
  - el consumo, el lote y el desperdicio quedan en el SKU real;
  - las sugerencias de compra por faltante muestran el requisito («Batería · iPhone 14: faltan 2») y proponen el SKU preferido, editable.
- **Datos y migraciones:** aditiva.
  - Tabla `tipo_reparacion_requisito` (tipo, subcategoría, cantidad), junto a la actual `tipo_reparacion_insumo`, que se conserva.
  - Marca de preferido en la compatibilidad.

##### D-14.5 Datos existentes y compatibilidad

- **Insumos actuales:** conservan su stock, sus lotes, sus reservas y su historial. Quedan sin clasificar hasta que Administración los clasifique: es opcional y gradual, y no requiere movimientos.
- **Órdenes, ejecuciones y movimientos ya registrados:** no cambian. Los nuevos se crean con el mismo `insumo_id`.
- **Compras:** sigue por SKU, con una línea por insumo por orden de compra. Los selectores agregan búsqueda por categoría, modelo y fabricante.
- **Stock mínimo (bloque 6):** es por SKU. Un mínimo por subcategoría y modelo («tener 3 baterías de iPhone 14, de cualquier marca») queda para después, si se necesita.

### Resumen de las propuestas

| Decisión | Propuesta | Migración |
|---|---|---|
| D-10.1 Unificación | Un formulario; se conservan los dos permisos y se corrige el hueco | No |
| D-10.2 Corrección | Revertir y Corregir, con un permiso propio; vuelve a regir el ajuste anterior | Aditiva |
| D-10.3 Después de la entrega | No se ajusta | No |
| D-10.4 Copia de valores | Precio original, importe y final como evidencia; los recálculos van al historial | Aditiva |
| D-10.5 Comprobantes | Ajuste y final por trabajo; usuario y fecha solo internos | No |
| D-11.1 Comparación | Contra el disponible, con «repuesto pedido» | No |
| D-11.2 Configuración | Configuración → Insumos, por insumo y opcional | Aditiva |
| D-11.3 Alertas | Inventario, bandeja de Inicio y sugerencias de Compras | Aditiva (origen) |
| D-12.1 Precio | Tipo con precio único o por modelo, sin respaldo | Aditiva |
| D-12.2 Sin precio | No se ofrece; «Otros» o carga del precio | No |
| D-12.3 Por modelo | Solo el precio y la pieza | No |
| D-12.4 Históricos | Sin conversión; copia del nombre y del modelo en el Detalle | Aditiva |
| D-12.5 Modelos | Alta desde Configuración | Aditiva |
| D-12.6 Cambio de modelo | Recalcula antes de autorizar; después avisa | No |
| D-13.1 Formato | Matriz por códigos, en CSV o pegada; descarga de la planilla actual | No |
| D-13.2 Alcance | Solo precios de tipos y modelos existentes | No |
| D-13.3 Errores | Vista previa; todo o nada | Aditiva (auditoría) |
| D-14.1 Estructura | Insumo = SKU real (A) | No |
| D-14.2 Atributos | Categoría y subcategoría, fabricante, variante, compatibilidad N:M | Aditiva |
| D-14.3 Calidad | Otro Tipo de Reparación si cambia el precio | No |
| D-14.4 Reserva | Requisitos por subcategoría; el técnico elige el SKU compatible | Aditiva |
| D-14.5 Existentes | Se conservan sin mover stock; clasificación gradual | No |

**Reglas de `rt-rma-app` que cambian:** BR-REP-016 (reversión), BR-REP-039 (permiso de reversión), BR-REP-015 (precio del tipo para el modelo), BR-REP-002, BR-REP-005 y BR-REP-006 (requisitos y elección de la pieza), BR-REP-049 (jerarquía y mínimo), DEC-CFG-05 y ABI-53 (jerarquía), y ABI-43 (alta de modelos). Se registran como DEC-AJ-10 en adelante antes del código.

**Orden de implementación propuesto:**

1. bloque 5;
2. bloque 6;
3. bloque 7: modelos, precio por modelo e importación;
4. bloque 8: catálogos, compatibilidad, requisitos y elección de la pieza.

Hasta que termine el bloque 8, los tipos genéricos solo pueden prever insumos universales, igual que hoy, porque los previstos no tienen pantalla.

### 11.1 Decisiones aprobadas (23/11/2026)

**Rige esta sección.** El análisis y las propuestas de la sección 11 quedan como contexto; donde difieren, vale lo de aquí.

Registradas en `rt-rma-app`, rama `spec/ajustes-funcionales` (local, sin publicar), commit `a2c64f3`, y copiadas a `business/` ([`sincronizacion-funcional.md`](sincronizacion-funcional.md)). DEC-AJ-NN corresponde a D-NN y agrupa sus puntos. No agregan nodos, aristas ni estados. Se implementaron en la iteración 2 (secciones 11.2 a 11.7) y `rt-rma-app` `2e93e9b` las registra como implementadas: figuran en la sección J de [`traceability/discrepancias-baseline-v1.4.md`](../traceability/discrepancias-baseline-v1.4.md).

- **Modificadas por el usuario** respecto de la propuesta: D-12.2, D-13.1, D-14.3 y D-14.4.
- **Precisiones de implementación:** las definió la coordinación del desarrollo para cerrar huecos del texto aprobado. No son texto aprobado. En `rt-rma-app` van separadas en las notas de cada DEC-AJ, y en las reglas llevan la marca «precisión de implementación».

| Decisión | ID | Definición aprobada | Implementación |
|---|---|---|---|
| D-10 (BF-09) | DEC-AJ-10 | **D-10.1:** una sola entidad de ajuste comercial para descuento y cortesía, con una experiencia unificada; se conservan los permisos por clase y se corrige que el permiso de descuento modifique una cortesía. **D-10.2:** acciones explícitas de corrección y reversión, sin borrar registros; el ajuste revertido deja de contar y vuelve a regir el anterior, si existe; permiso configurable nuevo, por defecto **solo Administración**; se registran usuario, fecha, motivo y operación; ninguna reversión deja pagos, devoluciones o saldos inconsistentes. **D-10.3:** después de la entrega no se agregan, corrigen ni revierten ajustes. **D-10.4:** se conservan precio original, importe del ajuste, precio final, motivo, usuario, fecha y hora, y la evidencia de los recálculos; la redefinición o cancelación de un trabajo mantiene la trazabilidad. **D-10.5:** los comprobantes muestran por trabajo el precio original, el ajuste y el precio final; usuario, fecha y justificación quedan solo en el registro interno; los cálculos de saldo del backend deben dar lo mismo | Bloque 5 |
| D-11 (BF-15) | DEC-AJ-11 | **D-11.1:** el mínimo se compara con el disponible, no solo con el físico; se distinguen stock suficiente, bajo mínimo y bajo mínimo con reposición solicitada; no se confunde con stock negativo ni faltantes. **D-11.2:** mínimo opcional por insumo, editable desde Configuración → Insumos, con permisos y auditoría; los insumos sin mínimo siguen funcionando. **D-11.3:** indicador y filtro en Inventario, aviso en Inicio y sugerencia de la cantidad a reponer hasta el mínimo, que considera la disponibilidad y no duplica solicitudes existentes; nunca se crean Órdenes de Compra automáticamente | Bloque 6 |
| D-12 (BF-01) | DEC-AJ-12 | **D-12.1:** Tipo de Reparación, Modelo de equipo y Precio separados; cada tipo con precio único o por modelo; con precio por modelo, nunca un precio genérico de respaldo en silencio; los tipos actuales siguen funcionando. **D-12.2 (modificada):** sin precio para la combinación se puede continuar con un **precio manual justificado y autorizado**, sin obligar a usar «Otros»: se muestra que falta el precio de catálogo, se piden precio y motivo, se exige un permiso configurable, se registran precio, motivo, usuario y fecha, el trabajo conserva el origen manual y el catálogo no cambia; no permite eludir los controles de los ajustes comerciales. **D-12.3:** el precio depende de tipo y modelo; la marca, el fabricante o la calidad del insumo no lo cambian; garantía, puntaje y Mesas siguen en el tipo; los insumos deben ser compatibles con el modelo; un trabajo puede usar cero, uno o varios. **D-12.4:** los tipos históricos no se convierten; cada trabajo nuevo copia nombre del tipo, modelo y precio autorizado. **D-12.5:** Administración da de alta modelos desde Configuración; el catálogo no depende solo de una lista fija; se revisa la integración con los modelos de Gestión RT. **D-12.6:** antes de autorizar, un cambio de modelo vuelve a determinar el precio; después se conserva el autorizado y se advierte el cambio; modificar un precio autorizado usa el circuito vigente | Bloque 7 |
| D-13 (BF-02) | DEC-AJ-13 | **D-13.1 (modificada):** importación desde **Excel `.xlsx`**, CSV y celdas pegadas de Google Sheets; matriz con modelos en filas y tipos en columnas; combinaciones identificadas por códigos estables; descarga de una plantilla con los precios actuales. **D-13.2:** solo precios de tipos y modelos existentes; celdas vacías sin efecto; no crea modelos ni tipos; primero iPhone, multimarca fuera de la importación masiva. **D-13.3:** vista previa con cambios, errores, duplicados, permisos y precios nuevos frente a actualizaciones; aplicación transaccional, todo o nada; no toca precios ya registrados en Órdenes; auditoría de la importación | Bloque 7 |
| D-14 (BF-14) | DEC-AJ-14 | **D-14.1:** cada insumo es un repuesto o SKU real, con su stock, lotes, costos, movimientos, reservas y consumos; no se agrupan marcas distintas. **D-14.2:** categoría, subcategoría, marca o fabricante, variante y modelos compatibles; sin restricción de modelo, compatible con todos cuando corresponde; clasificación gradual. **D-14.3 (modificada):** la marca, el fabricante o la calidad **no definen por sí solos otro Tipo**: «Cambio de batería» + iPhone 14 tiene un precio, con cualquier batería compatible; los costos sí se individualizan; otro tipo solo si el servicio es realmente distinto. **D-14.4 (modificada):** la pieza concreta se elige **durante la definición o preparación del trabajo, antes de reservar** (tipo → modelo → insumos necesarios → piezas compatibles → disponibilidad → reserva → ejecución); nunca dos reservas sobre la misma disponibilidad; sustituciones controladas con trazabilidad; cero, uno o varios insumos; sin rediseñar el motor de reservas, movimientos y consumo. **D-14.5:** no se mueven ni recalculan existencias; no se alteran lotes, movimientos, compras ni consumos | Bloque 8 |

**Consistencia entre los bloques 7 y 8 (aprobada):** el tipo define el trabajo; el modelo, el dispositivo; tipo + modelo, el precio de catálogo. Los insumos reales se eligen por compatibilidad y disponibilidad. El costo es del insumo y el precio de venta no depende de su marca. Las Órdenes conservan copias y trazabilidad. Se amplían las entidades existentes (`detalle_version`, `tipo_reparacion_insumo`, `insumo`, `modelo_equipo`, compras, reservas, movimientos, lotes, garantías e historial) en lugar de duplicarlas.

#### Precisiones de implementación (coordinación del desarrollo, 23/11/2026)

- **D-10.2:**
  - **Qué se revierte:** solo el ajuste vigente de un destino (la Orden o un trabajo). Vuelve a regir el registro anterior no revertido de ese destino; si ese registro es un «quitar», no queda ningún ajuste.
  - **Corregir:** revierte y registra el ajuste correcto en la misma transacción, enlazado con `corrige_a`. Exige `AJUSTE_REVERTIR` y el permiso de la clase del ajuste nuevo.
  - **Permiso:** `AJUSTE_REVERTIR`, solo Administración por defecto y configurable.
  - **Se rechaza:** con la Orden entregada, cerrada o cancelada, o si el resultado supera los topes de BR-REP-016 (el ajuste no supera el importe al que se aplica y el total nunca es negativo). Nunca se modifican pagos, devoluciones ni las copias de recargo de los pagos.
  - **Estado consistente:** la vista SQL y el dominio dan el mismo saldo, y las devoluciones nunca superan lo pagado. Un saldo a favor es el estado que ya admite DEC-MI-03 (devolución enlazada al pago, antes de entregar). La entrega sigue exigiendo saldo 0.
- **D-10.4:** cada registro nuevo guarda el precio original (la base), el importe aplicado y el precio final. Si una redefinición o cancelación cambia el importe efectivo de un ajuste vigente, se persiste un registro inmutable de recálculo (ajuste, causa, precio e importe anterior y nuevo, usuario y fecha), que también va al historial de la Orden. No se escribe un ajuste nuevo. Cada alta, cambio, retiro, corrección y reversión emite `EV-REP-041`.
- **D-12.2:**
  - **Permiso:** `PRECIO_MANUAL` («Autorizar un precio manual cuando falta el precio de catálogo»), por defecto Coordinación RMA y Administración, configurable. El técnico no fija precios ni lo tiene por defecto.
  - **Se acepta:** si el tipo tiene precio por modelo y no hay precio para el modelo de la Orden, o si el equipo no tiene modelo técnico.
  - **Se rechaza:** si existe precio de catálogo para la combinación (para bajar un precio está el ajuste comercial) y en los tipos de precio único. «Otros» sigue como hoy.
  - **Copia en el Detalle:** origen del precio (`CATALOGO`, `CATALOGO_MODELO`, `MANUAL` u `OTROS`), motivo del precio manual y quién lo definió.
- **D-12.6:** antes de la autorización del cliente, un cambio de modelo vuelve a resolver el precio de los trabajos con precio por modelo; sin precio para el modelo nuevo, el trabajo queda «precio pendiente de definir» y no se autoriza hasta definirlo (catálogo o precio manual autorizado). Después de la autorización se conserva la copia, con el aviso «el precio corresponde a otro modelo».
- **D-13:** lectura del `.xlsx` en el backend con `openpyxl` (dependencia nueva, solo lectura); subida del cuerpo crudo, como fotos y firmas, sin multipart; plantilla en `.xlsx` y CSV; pegado de Google Sheets como texto separado por tabulaciones; solo modelos Apple y tipos con precio por modelo (otra marca es un error de la fila); importes con formato argentino; un identificador común por importación en la auditoría.
- **D-14.4:**
  - **Requisitos:** el tipo declara requisitos (categoría o subcategoría + cantidad), junto a los insumos previstos concretos actuales (universales), que se conservan.
  - **Pieza elegida:** por requisito, el Detalle guarda un SKU compatible con el modelo de la Orden. La elige el sistema si hay una sola compatible activa; si no, quien prepara el trabajo (permiso nuevo o existente, por defecto Técnico, Coordinación y Administración).
  - **Factibilidad y reserva:** sobre las piezas elegidas; una sola reserva por disponibilidad, garantizada por el motor actual. La reserva sigue al iniciar la ejecución (BR-REP-006) y no se inicia con requisitos sin pieza elegida.
  - **Sustitución:** antes de reservar cambia la elección, con motivo y registro; después de reservar y antes de consumir, liberación y reserva nueva en una sola transacción, con motivo.
  - **Sin requisitos:** como hoy. **Compras:** las sugerencias por faltante usan la pieza elegida.

#### Registro en `rt-rma-app`

- **Cambian de texto:**
  - reglas BR-REP-015, 016, 031, 039, 040 y 047 a 049;
  - nodos PROC-REP-030, 070, 075, 080, 127, 185, 270 y 280;
  - Features FEAT-REP-001, 002, 003, 005, 007, 008, 010 y 011;
  - Scenario VAR-REP-041;
  - notas de DEC-MI-03 y 09, DEC-IT1-02, DEC-UX-01 y 13, DEC-CFG-03 y 05.
- **ABI-53** cerrado por DEC-AJ-14. **ABI-43** cerrado en parte por DEC-AJ-12: sigue abierto para cargar la línea iPhone 18.
- **Sin cambios de texto:** BR-REP-002, 005 y 006, PROC-REP-210 y EXC-REP-001 y 003. `test-scenarios` exige que sigan iguales a V1.3. Lo que DEC-AJ-14 agrega a la factibilidad, la reserva y los movimientos está en BR-REP-049 y en PROC-REP-080 y 185. Cambiar esos textos obliga a declararlos en la prueba, y eso requiere aprobación.

#### Puntos para resolver en la implementación o con el negocio

1. **Factibilidad sin pieza elegida (D-14.4).** La factibilidad (PROC-REP-080) corre al definir o autorizar el trabajo. Si hay varias piezas compatibles y nadie eligió todavía, no está definido qué evalúa: puede tratar el requisito como «pendiente de elegir» o sumar el disponible de las compatibles.
2. **Equipo sin modelo técnico con requisitos por categoría.** Solo serían compatibles las piezas sin restricción de modelo. Si no hay ninguna, el trabajo no puede iniciarse, y eso no está definido.
3. **Técnico y precio faltante (D-12.2).** El técnico define trabajos (075, 127 y 128) sin `PRECIO_MANUAL`. La precisión de D-12.6 («precio pendiente de definir», que bloquea la autorización) debería aplicarse también a esos casos. En los orígenes sin autorización del cliente no hay un paso que lo bloquee.
4. **«Otros» y precio manual.** Recepción no tiene `PRECIO_MANUAL` por defecto, pero sigue pudiendo usar «Otros» con precio manual (BR-REP-047). Precio manual y «Otros» conviven con controles distintos.
5. **Precios y DEC-CFG-03.** Fijar precios es de Administración (DEC-CFG-03). `PRECIO_MANUAL` agrega una vía por trabajo para Coordinación, sin tocar el catálogo. Es coherente con el texto aprobado, pero es una excepción a «solo Administración fija precios».
6. **Reparto del recargo (DEC-UX-13).** DEC-UX-13 dice que el comprobante reparte el recargo cobrado entre los trabajos vigentes al emitirlo. La corrección técnica de la sección 11 dice que el reparto mostrado use la copia de cada pago. Hay que confirmar que no contradice DEC-UX-13 antes de cambiar la presentación.
7. **«Reposición solicitada» (D-11.1).** La propuesta contaba solo las Órdenes de Compra confirmadas. El texto aprobado habla de «reposición solicitada» y de no duplicar solicitudes, lo que sugiere contar también las solicitudes pendientes. Falta fijar qué estados cuentan.
8. **Catálogo técnico administrado por RMA (D-12.5).** BR-REP-040 dice que el catálogo de equipos lo mantiene Ventas, y DEC-UX-01 dice que no se inventan modelos. Desde DEC-AJ-12, el catálogo técnico (`modelo_equipo`) también se da de alta desde Configuración. La copia de productos de Ventas sigue siendo de solo lectura. Hay que evitar duplicados con una exportación futura de Ventas.
9. **Calidad del repuesto (D-14.3).** Original y alternativo tienen el mismo precio si el servicio es el mismo. El cliente no elige la calidad al autorizar, y el comprobante no la muestra. Si el negocio necesita precios distintos por calidad, solo quedan un tipo realmente distinto o un ajuste comercial.
10. **Permisos sin nombre en el texto aprobado.** La importación (D-13.3) y el mínimo (D-11.2) exigen «permisos» sin nombrarlos. Lo natural es el permiso de precios (DEC-CFG-03) y el de insumos.
11. **Cambio de modelo sin autorización del cliente (D-12.6).** En RT_INTERNO y en las garantías no hay autorización del cliente, así que no está definido cuándo se congela el precio. El efecto es menor, porque no se cobra.

#### Resolución de los puntos (coordinación técnica, 23/11/2026)

Son precisiones de implementación dentro del texto aprobado. Si alguna no coincide con lo que espera el negocio, se ajusta en la validación manual.

1. **Factibilidad sin pieza elegida:** mientras un requisito no tiene pieza elegida, cuenta como factible si alguna pieza compatible tiene disponible suficiente. Con la pieza elegida, se evalúa esa pieza.
2. **Equipo sin modelo técnico:** se ofrecen primero las piezas universales. Si no hay ninguna, quien prepara el trabajo puede elegir cualquier pieza de la categoría con un motivo obligatorio, y queda marcada como «compatibilidad no verificada».
3. **Precio faltante sin `PRECIO_MANUAL`:** la regla es la misma en el ingreso, en 070, 075, 127 y 128.
   - **Con el permiso:** precio manual con motivo.
   - **Sin el permiso:** el trabajo se crea con el precio pendiente de definir (origen `PENDIENTE`, sin importe). Lo resuelve quien tenga `PRECIO_MANUAL`, o se toma el precio de catálogo cuando Administración lo carga.
   - **Qué bloquea:** con el precio pendiente no se emite el comprobante de ingreso ni se registra la autorización del cliente (Cliente Externo).
   - **Orígenes no cobrables** (RT_INTERNO y garantías): no bloquea.
4. **«Otros»:** queda como está (BR-REP-047) y se distingue en los reportes. El precio manual con `PRECIO_MANUAL` es para tipos del catálogo sin precio para el modelo.
5. **DEC-CFG-03:** se mantiene para el catálogo. El precio manual vale para un solo trabajo, nunca cambia el catálogo y queda auditado.
6. **Recargo:** no se cambia la presentación. Rige DEC-UX-13 y se descarta la «corrección técnica» de la sección 11.
7. **Reposición solicitada:** cuenta lo que ya calcula «en camino»: solicitudes pendientes y Órdenes de Compra en borrador, confirmadas o parciales. La sugerencia descuenta todo eso, así que no se duplican solicitudes.
8. **Catálogo técnico:** `modelo_equipo` es el catálogo técnico de RMA (DEC-UX-01), distinto de la copia de Ventas, que sigue siendo de solo lectura.
   - La unicidad (marca, modelo, variante) impide duplicados.
   - El archivo versionado queda como carga inicial.
   - Una futura regeneración desde Ventas tiene que emparejar por esa clave, sin duplicar.
9. **Calidad del repuesto:** no cambia el precio de venta. Para cobrar distinto queda el ajuste comercial o un tipo realmente distinto.
10. **Permisos:**
    - la importación usa `PRECIOS_GESTIONAR`;
    - el mínimo, `INSUMO_GESTIONAR`;
    - el alta de modelos, un permiso nuevo «Gestionar modelos de equipo», de Administración;
    - las categorías y los fabricantes de insumos, `INSUMO_GESTIONAR`.
11. **Orígenes sin autorización del cliente:** el precio queda fijo cuando se define el trabajo. Un cambio de modelo posterior solo genera un aviso.

#### Estado de validación de las once precisiones (24/11/2026)

Las once resoluciones de arriba las decidió la coordinación técnica para poder implementar. **No están aprobadas funcionalmente**, salvo las que solo repiten una regla ya aprobada. En la validación manual se confirman o se corrigen.

| # | Precisión | Clase | Qué hay que confirmar |
|---|---|---|---|
| 1 | Factibilidad con un requisito sin pieza elegida: factible si alguna pieza compatible tiene disponible | **Funcional: validar** | Que una Orden no quede bloqueada por recursos solo porque nadie eligió todavía la pieza |
| 2 | Equipo sin modelo técnico: primero las piezas universales; si no hay, cualquiera de la categoría con motivo y marca «compatibilidad no verificada» | **Funcional: validar** | Que esa vía exista, quién la usa (hoy, quien tiene «Elegir la pieza»: Técnico, Coordinación y Administración) y que el motivo alcance como control |
| 3 | Precio faltante sin permiso de precio manual: el trabajo queda «precio pendiente»; bloquea el comprobante de ingreso y la autorización solo en Cliente Externo | **Funcional: validar** | El flujo de Recepción cuando falta el precio, y que en RT Interno y garantías no bloquee |
| 4 | «Otros» sigue como está (BR-REP-047) | Regla vigente: sin cambio | Nada; solo saber que convive con el precio manual |
| 5 | El precio manual vale para un trabajo y nunca cambia el catálogo; lo autorizan Coordinación y Administración | **Funcional: validar** | Los roles que pueden autorizar un precio manual |
| 6 | Recargo: se mantiene DEC-UX-13 y se descarta la corrección propuesta | Técnica: sin cambio de comportamiento | Nada |
| 7 | «Reposición solicitada» cuenta solicitudes pendientes y Órdenes de Compra en borrador, confirmadas o parciales | **Funcional: validar** | Si un borrador o una solicitud ya cuentan como reposición en curso |
| 8 | El catálogo técnico de modelos es de RMA, distinto de la copia de Ventas, y se empareja por marca, modelo y variante | Técnica: arquitectura de datos | Nada en esta etapa; importa si Ventas vuelve a exportar modelos |
| 9 | La calidad del repuesto no cambia el precio de venta | Ya aprobada (D-14.3) | Nada |
| 10 | Permisos: importación con «Gestionar precios», mínimo y clasificación con «Gestionar insumos», modelos con un permiso nuevo; todos de Administración por defecto | **Funcional: validar** | Si Coordinación también tiene que poder editar mínimos, clasificación o modelos |
| 11 | Orígenes sin autorización del cliente (RT Interno, garantías): el precio queda fijo al definir el trabajo; un cambio de modelo posterior solo avisa | **Funcional: validar** (impacto bajo: no se cobra) | Que alcance con el aviso |

**Elecciones de implementación que también conviene validar:**
- la elección automática de la pieza corre también al iniciar;
- una pieza ya consumida queda fija para ese trabajo;
- los comprobantes nuevos no imprimen el motivo del ajuste;
- un retiro de ajuste no se revierte, se vuelve a aplicar;
- con la configuración por defecto, Recepción y Técnico no cargan precios manuales.

**Corrección del 24/11/2026:** aplicar un ajuste ahora valida los topes de todos los ajustes vigentes (`6ca558e`). Antes, un ajuste nuevo sobre un trabajo podía dejar el importe fijo de la Orden por encima de su base, y el exceso se recortaba en silencio. No es una regla nueva: es cumplir BR-REP-016, que ya decía que un ajuste no supera el importe al que se aplica.

### 11.2 Bloque 5: implementación

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. Implementa DEC-AJ-10 (D-10.1 a D-10.5) con las precisiones de 11.1. `business/` no cambia.

| Commit | Qué |
|---|---|
| `a2a896c` | Backend: permisos por clase al cambiar o quitar, reversión y corrección, evidencia de importes, recálculos por redefinición y cancelación, historial EV-REP-041, migración y persistencia PostgreSQL |
| `6aba17c` | Comprobantes de ingreso, autorización y entrega con el ajuste por trabajo y el de la Orden aparte; PDF |
| `a76da9a` | Frontend: formulario único, historial con Revertir y Corregir, aviso de recálculo, comprobantes y WhatsApp |
| `f9cf53e` | Comentarios viejos y diseño físico |
| este | Esta sección y `docs/contratos-macro-integral.md` |

#### Qué quedó

- **D-10.1, permisos:** `aplicar_descuento` exige el permiso de la clase nueva y, si hay un ajuste vigente en ese destino, también el de su clase. Quitar exige el de la clase del vigente. Con solo `DESCUENTO` ya no se reemplaza ni se quita una cortesía. Las acciones `APLICAR_DESCUENTO` y `OTORGAR_CORTESIA` no cambian. En el frontend las dos abren el mismo formulario «Ajuste comercial», con la clase preseleccionada.
- **D-10.2, reversión y corrección:**
  - **Rutas:** `POST /api/orders/{id}/adjustments/{ajuste}/revert` y `/correct` (`services/descuentos.py`: `revertir_ajuste` y `corregir_ajuste`).
  - **Permiso:** `AJUSTE_REVERTIR`, «Revertir o corregir un ajuste comercial», grupo Comercial, configurable y solo de Administración por defecto. Corregir exige además el permiso de la clase nueva.
  - **Qué se revierte:** solo el vigente de su destino, es decir, el último registro no revertido que no quita el ajuste. Vuelve a regir el anterior no revertido; si ese quitó el ajuste, no queda ninguno.
  - **Corregir:** marca la reversión y agrega el registro correcto en el mismo destino, con `corrige_a`, en un solo guardado. Va al historial como un solo paso.
  - **Cuándo se rechaza:** con la Orden entregada, cerrada o cancelada (`descuento_editable`; en PostgreSQL, también el trigger), y si un ajuste vigente de importe fijo superaría su base después de la operación.
  - **Pagos:** no toca pagos, devoluciones ni el reparto del recargo. Si queda saldo a favor, la entrega lo sigue bloqueando hasta la devolución.
- **D-10.3:** después de la entrega no se aplica, corrige ni revierte. Lo cortan `orden_para_modificar` (`ORDEN_CERRADA`), el servicio y, en PostgreSQL, `descuento_validar()` y `exigir_orden_abierta()`.
- **D-10.4, evidencia:**
  - **Al registrar:** cada registro nuevo guarda `precio_original` (la base: el precio del trabajo o lo que quedaba de la Orden), `importe_aplicado` y `precio_final`. Un retiro guarda la base con importe 0.
  - **Recálculos:** `registrar_recalculos` compara el importe efectivo de cada ajuste vigente antes y después de `aplicar_redefinicion` (127 y 183), `cancelar_detalle` (incluye el desistimiento), `cancelar_trabajos_pendientes` y `cancelar_orden`. Si cambió, agrega un `RecalculoAjuste` (ajuste, causa, precio e importe anterior y nuevo, usuario y fecha) y un paso del historial. No escribe un ajuste nuevo.
- **Historial:** cada alta, cambio, retiro, corrección, reversión y recálculo queda como `ACC-REP-072`, la system action «Aplicar un ajuste comercial por Orden o por Detalle» de `traceability/macro-integral.yaml`. Las acciones son `APLICAR_`, `CAMBIAR_`, `QUITAR_`, `CORREGIR_`, `REVERTIR_` y `RECALCULAR_AJUSTE_COMERCIAL`. En PostgreSQL se traduce a EV-REP-041, que ahora es visible y se renombra «Ajuste comercial aplicado, cambiado, quitado, corregido, revertido o recalculado».
- **Identificador:** `RegistroDescuento.id`.
  - **Registros nuevos:** `AJ-xxxxxxxxxxxx`.
  - **JSON anterior:** al cargarlo, cada registro toma `AJ-001`, `AJ-002`… por su posición.
  - **PostgreSQL:** `codigo` o, en las filas anteriores, el `id` uuid.
- **Saldo:** `_ajuste_vigente` del dominio y `v_orden_saldo` excluyen los revertidos. La equivalencia se prueba paso a paso con reversión y corrección.
- **D-10.5, comprobantes:** los emitidos desde ahora llevan, por trabajo, `ajuste` (clase, descripción e importe) y `precio_final`, y además `ajuste_orden` y `ajustes_por_trabajo`.
  - **Presentación:** la hoja, el PDF y el mensaje de WhatsApp muestran precio, ajuste («Cortesía» o «Descuento») y precio final por trabajo, y el ajuste de la Orden en una línea aparte, sin motivo, usuario ni fecha. En la entrega, el recargo se sigue incorporando como siempre (DEC-UX-13, punto 6 de 11.1).
  - **Agregado anterior:** `descuento` se conserva para la compatibilidad.
  - **Documentos anteriores:** se presentan igual.
  - **Comprobante de autorización:** un cambio de clase también ofrece una versión nueva. Se ofrece, no se emite sola.
- **Frontend:**
  - **Formulario único:** reemplaza a los tres formularios (`PagosOrden.tsx`). Tiene clase, destino, tipo, valor y motivo, con la vista previa del precio original, el ajuste y el final, sobre la misma base que el backend.
  - **Historial de ajustes:** muestra la operación, la evidencia, el motivo, el usuario y la fecha, los revertidos tachados y los recálculos. Los botones «Revertir» y «Corregir» aparecen sobre el vigente de cada destino con `puede(actor, "AJUSTE_REVERTIR")`.
  - **Aviso de recálculo:** al redefinir o cancelar un trabajo.
  - **Comprobantes:** vista previa y hoja con el ajuste por trabajo.
  - **Lógica pura:** en `ajusteComercial.ts`.

#### Migración

`20261124000100_ajuste_comercial_reversion.sql`, aditiva:

- **`descuento`:** columnas que admiten vacío: `codigo`, `precio_original`, `importe_aplicado`, `precio_final`, `corrige_a` (FK a `descuento`), `revertido_por`, `revertido_en` y `reversion_motivo`.
- **Restricciones:** CHECK de reversión completa, de evidencia coherente y de que un registro no se corrige a sí mismo; `unique (id, orden_id)`; índices únicos de `codigo` por Orden y de `corrige_a`.
- **Triggers:**
  - `descuento_validar()` reemplaza a `descuento_inmutable`. No admite borrar y solo deja completar la reversión, una vez y con la Orden abierta.
  - `descuento_correccion_valida()` exige que `corrige_a` apunte a un revertido de la misma Orden y del mismo destino.
- **Permisos de la base:** `rma_backend` solo actualiza las tres columnas de la reversión.
- **Tabla nueva `descuento_recalculo`:** inmutable y solo con la Orden abierta. La FK compuesta al ajuste de la misma Orden garantiza que pertenece a esa Orden. Son 73 tablas y 8 vistas.
- **`v_orden_saldo`:** `create or replace`, con las mismas columnas y sin los revertidos.
- **Historial:** la equivalencia `ACC-REP-072 → EV-REP-041`, y EV-REP-041 pasa a visible.
- **Comentario de la tabla:** ya no dice «no por debajo de lo cobrado».
- **Datos:** ningún registro existente cambia.

#### Pruebas focalizadas

| Qué | Resultado |
|---|---|
| Backend JSON: `test_ajuste_comercial_dec_aj_10.py` y `test_ajuste_comercial_comprobantes.py` (nuevos, 15), `test_descuentos`, `test_ajuste_por_detalle`, `test_iteracion1_v14`, `test_recargo_detalles_devoluciones`, `test_recargo_medio_pago`, `test_roles_permisos`, `test_matriz_permisos`, `test_e3_sql_y_ajustes`, `test_pagos_devoluciones`, `test_comprobante_autorizacion`, `test_comprobantes`, `test_documentos_custodia_entrega`, `test_firmas_documentos`, `test_pdf`, `test_cancelacion_detalle`, `test_cancelacion_heredada`, `test_cancelacion_orden`, `test_desistimiento_cliente`, `test_historial_transversal`, `test_api_exc_rep_004`, `test_exc_rep_004` y `test_macro_v14` | 534 pasan |
| PostgreSQL local: `test_ajuste_comercial_postgres` (nuevo, 6: vista y dominio en cada paso con reversión y corrección, relectura igual, recálculo guardado, el trigger admite la reversión una sola vez, rechazo con la Orden cerrada y migración aditiva), `test_ajuste_por_detalle`, `test_finanzas`, `test_iteracion1`, `test_base_local`, `test_permisos_macro_v14`, `test_permisos_operativos`, `test_permisos_rma_backend`, `test_roles_permisos`, `test_ordenes`, `test_bloque_a`, `test_comprobantes`, `test_macro_v14` y `test_entrega` | 173 pasan |
| Backend: `ruff check .` y `ruff format --check app` | Limpios |
| Frontend: `npm run typecheck`, `npm test` (incluye `ajuste-comercial.test.ts`, 9 pruebas nuevas) y `npm run build` | Pasan (234 pruebas) |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Tests adaptados

- **`test_documentos_custodia_entrega.py::test_16_comprobante_final`:** compara el renglón completo del trabajo realizado y ahora incluye `"ajuste": None` y `"precio_final": "80000"`. Son los campos nuevos del snapshot de D-10.5.
- **`tests/postgres/test_base_local.py`:** el conteo pasa de 72 a 73 tablas por `descuento_recalculo`.
- **`test_matriz_permisos.py`:** se clasifican las dos rutas nuevas, como `SERVICIO("AJUSTE_REVERTIR")` y `SERVICIO("AJUSTE_REVERTIR", "DESCUENTO", "CORTESIA")`.
- **Ninguna otra expectativa cambió.** El mensaje de `PersistenciaError` al alterar un ajuste guardado conserva «los descuentos», que fija `test_finanzas_postgres`.

#### Decisiones tomadas en la implementación

- **Qué se revierte:** solo un registro que aplica un ajuste. Un retiro (sin `tipo`) no se revierte. Para volver a un ajuste quitado por error se aplica de nuevo.
- **Topes:** después de revertir o corregir, ningún ajuste vigente de importe fijo puede superar su base. Por ejemplo, si al revertir vuelve a regir un importe fijo mayor que el precio redefinido del trabajo, se rechaza. Al aplicar no se agregó este control, para no cambiar la regla vigente.
- **Recálculo:** solo cuando cambia el importe efectivo, sobre todos los ajustes vigentes: el del trabajo y el de la Orden, cuya base cambia. Un importe fijo que sigue entrando en la base nueva no deja recálculo. El ajuste de un trabajo cancelado queda con precio nuevo 0 e importe 0.
- **Historial:** se usa la system action existente ACC-REP-072, en lugar de un identificador nuevo.
- **Formulario único:** se mantienen las dos acciones del backend. El formulario solo ofrece las clases que el usuario tiene permiso de aplicar y, si no tiene el permiso de la clase del vigente, no deja cambiarlo ni quitarlo.
- **Comprobantes:** no se imprime el motivo del ajuste en los comprobantes nuevos. El PDF lo imprimía; ahora queda en el registro interno, según D-10.5. El agregado `descuento` se sigue llenando para la compatibilidad y para las pruebas existentes.

#### Limitaciones y pendientes

- **Recargo:** el reparto del recargo de un pago sigue usando los ajustes actuales al emitir (DEC-UX-13). Un ajuste o una reversión posterior al cobro cambia cómo se presenta el reparto, no el saldo.
- **Comprobante de entrega:** se sigue imprimiendo desde el navegador; solo el ingreso y la autorización tienen PDF descargable.
- **Documentación:** no se actualizaron `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-10 sigue «sin implementar»), `docs/ESTADO_PROYECTO.md` ni `docs/pendientes-producto.md`.
- **Validación manual:** pendiente, en un navegador:
  1. aplicar un descuento y una cortesía por trabajo y a la Orden;
  2. revertir y corregir con Administración;
  3. intentarlo con Recepción;
  4. cancelar o redefinir un trabajo con ajuste y ver el recálculo;
  5. emitir los comprobantes y ver uno anterior.
- **Para el bloque 6:**
  - La última migración es `20261124000100`; la siguiente va después.
  - `test_base_local` fija 73 tablas y 8 vistas.
  - `test_matriz_permisos` exige que todo permiso nuevo tenga uso en el backend y que toda ruta nueva esté clasificada.
  - `test_e3_sql_y_ajustes` solo cuenta las consultas de catálogos y modelos.

### 11.3 Bloque 6: implementación

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. Implementa DEC-AJ-11 (D-11.1 a D-11.3) con las precisiones de 11.1 (puntos 7 y 10). `business/` no cambia.

| Commit | Qué |
|---|---|
| `4c523c4` | Migración, `Insumo.stock_minimo`, edición validada y auditada en Configuración → Insumos, persistencia PostgreSQL |
| `ffec63b` | Estado de reposición, Inventario (filtro y campos), bandeja de Inicio, sugerencias de Compras hasta el mínimo y pruebas |
| `00ab211` | Frontend: Insumos, Inventario, Inicio y Compras |
| este | Esta sección, `docs/contratos-macro-integral.md` y `docs/postgresql/diseno-fisico.md` |

#### Qué quedó

- **D-11.1, estado de reposición** (`services/stock_minimo.py`, funciones puras; la única fuente de la regla):
  - `SIN_MINIMO`: el insumo no tiene mínimo.
  - `SUFICIENTE`: disponible ≥ mínimo.
  - `BAJO_MINIMO`: disponible < mínimo y disponible + en camino < mínimo.
  - `BAJO_MINIMO_REPOSICION_SOLICITADA`: disponible < mínimo, pero disponible + en camino ≥ mínimo.
  - **Contra qué se compara:** el disponible (físico − reservado pendiente), no el físico.
  - **Reposición solicitada:** lo que ya calcula «en camino» (punto 7 de 11.1): solicitudes `PENDIENTE` y lo que falta recibir de las órdenes de compra en borrador, confirmadas o parciales. Se corrigió el docstring de `en_camino`, que hablaba solo de confirmadas y parciales. En JSON no hay Compras: en camino es 0.
  - **Faltante:** sigue aparte y sin cambios (`SituacionInsumo.faltante`, «Solo faltantes», `INSUMOS_NEGATIVOS`).
  - **Alerta:** `SituacionInsumo.bajo_minimo` es un insumo vigente en cualquiera de los dos estados «bajo mínimo». Un insumo inactivo informa su estado, pero no alerta, no entra en el filtro ni en la bandeja y no se sugiere reponerlo.
- **D-11.2, configuración:**
  - `rma.insumo.stock_minimo` y `Insumo.stock_minimo`, opcionales. Vacío significa sin mínimo, y los insumos existentes siguen igual. En JSON se lee con ese valor por defecto; el catálogo de demostración no trae mínimos.
  - `GET/POST/PUT /api/admin/supplies` lo reciben y devuelven. Permiso: `INSUMO_GESTIONAR` (punto 10 de 11.1); su descripción ahora nombra el stock mínimo.
  - **Validación:** ≥ 0 y hasta tres decimales, los que guarda la base, como el stock. La API rechaza un negativo con 422; el servicio rechaza más decimales con 409.
  - **Auditoría:** `stock_minimo` es un campo más de `CAMPOS_INSUMO` (entidad `INSUMO`). Se audita con sus decimales («2.125», sin ceros de más): `texto()` redondea a dos y habría perdido cambios.
  - **Edición:** en el `PUT`, si el pedido no trae el campo se conserva el mínimo, para que un cliente anterior no lo borre; `null` lo quita.
- **D-11.3, alertas:**
  - **Inventario:** `GET /api/inventory?bajo_minimo=true` filtra; se combina con Y con `buscar` y `solo_faltantes`. Cada situación (lista, detalle y bandejas) suma `stock_minimo`, `en_camino`, `estado_reposicion` y `bajo_minimo`. En PostgreSQL, la consulta lee lo en camino en la misma lectura.
  - **Inicio:** bandeja nueva `STOCK_BAJO_MINIMO`, «Insumos a reponer», de seguimiento, con destino Inventario, para Coordinación RMA y Administración. Lista los insumos bajo su mínimo: primero los que no tienen reposición solicitada y después en el orden del catálogo. Lo en camino se lee solo si algún insumo está debajo de su mínimo, así la lectura de Inicio no crece en el caso habitual.
  - **`INSUMOS_NEGATIVOS`:** se mantiene sin cambios y en su lugar, a diferencia de la propuesta de la sección 11, que la reemplazaba. Su lógica sigue igual, ahora sobre la misma situación calculada.
  - **Compras:** `sugerencias()` recibe los mínimos de los insumos vigentes.
    - **Sin mínimo:** la fórmula de siempre, demanda − disponible − en camino, si es positiva.
    - **Con mínimo:** `max(0, demanda + mínimo − disponible − en camino)`.
    - **Candidatos:** la demanda de los Detalles bloqueados, el disponible negativo y los insumos vigentes con disponible < mínimo.
    - **Cada sugerencia** suma `stock_minimo`, `por_faltante` (lo que pide la demanda sola), `por_minimo` (el resto) y `motivo`.
    - **Origen (regla):** `motivo` es `STOCK_MINIMO` si `por_minimo > 0`, es decir, si el mínimo aporta algo a la cantidad, solo o junto con un faltante. En ese caso la solicitud se crea con origen `STOCK_MINIMO` y conserva las Órdenes del faltante, si las hay. Si el mínimo no aporta nada, el motivo es `FALTANTE`, como siempre.
    - **Sin duplicados:** las solicitudes pendientes y las órdenes de compra abiertas se descuentan (en camino), así que lo ya pedido no se vuelve a sugerir.
    - **Sin compras automáticas:** nunca se crea una solicitud ni una orden de compra sola.
- **Frontend:**
  - **Insumos:** campo «Stock mínimo (opcional)», con coma decimal y la validación de arriba, y columna en la tabla. La edición en la fila conserva el mínimo.
  - **Inventario:** filtro «Bajo mínimo» junto a «Solo faltantes», y columnas «Mínimo» y «Reposición». El indicador distingue «Bajo mínimo» (ámbar) de «Bajo mínimo · reposición solicitada» (azul) y muestra lo en camino; el detalle del insumo también.
  - **Inicio:** las bandejas de insumos muestran el estado, el mínimo y lo en camino. Una bandeja de insumos vacía dice «No hay insumos en esta bandeja».
  - **Compras:** «Sugerencias de reposición», con la causa (faltante, mínimo o ambos) y la solicitud con su origen. El origen de cada solicitud se nombra: manual, por faltante o por stock mínimo.
  - **Lógica pura:** `features/inventario/stockMinimo.ts`.

#### Migración

`20261124000200_stock_minimo.sql`, aditiva:

- **`insumo.stock_minimo`:** `numeric(12,3)`, admite vacío, con `insumo_stock_minimo_no_negativo` (≥ 0) y comentario. `grant update (stock_minimo)` a `rma_backend`.
- **`solicitud_compra_origen_check`:** se reemplaza por `origen in ('MANUAL', 'FALTANTE', 'STOCK_MINIMO')`, y se actualiza el comentario de la columna.
- **Sin tablas ni vistas nuevas:** siguen 73 tablas y 8 vistas. Ningún dato cambia.

#### Pruebas focalizadas

| Qué | Resultado |
|---|---|
| Backend JSON: `test_stock_minimo.py` (nuevo, 17: los cuatro estados y sin mínimo, con y sin en camino; comparación contra el disponible y no contra el físico; insumo inactivo; cantidad a reponer por causa; sugerencias con motivo y sin duplicar lo en camino; auditoría con tres decimales, validación y permiso; Inventario con el filtro y los campos; bandeja para Coordinación y Administración y no para Recepción ni Técnico), `test_inventario_operativo`, `test_inventario_global`, `test_compras_reglas`, `test_insumos_admin`, `test_bandejas`, `test_matriz_permisos`, `test_e3_sql_y_ajustes`, `test_configuracion`, `test_configuracion_persistencia`, `test_roles_permisos`, `test_autenticacion`, `test_cancelacion_heredada`, `test_e2_equivalencia`, `test_entrega_sin_aviso`, `test_hito_habilitacion_unico`, `test_ingreso_inicial`, `test_liberacion_cruzada`, `test_motivos_retiro`, `test_prioridad_cola` y `test_reparacion_otros` | 506 pasan |
| PostgreSQL local: `test_stock_minimo_postgres` (nuevo, 3: migración —tipo, vacío, sin datos, grant, CHECK y origen—; alta y edición por la API con permiso, decimales, conservar, quitar y auditoría; circuito sugerencia → solicitudes `STOCK_MINIMO` → orden de compra → recepción, con el estado y la bandeja en cada paso y sin sugerencias duplicadas), `test_compras_postgres`, `test_insumos_admin_postgres`, `test_reservas_postgres`, `test_base_local`, `test_configuracion_postgres`, `test_permisos_macro_v14`, `test_permisos_operativos_postgres`, `test_permisos_rma_backend`, `test_roles_permisos_postgres`, `test_lotes_postgres`, `test_consultas_postgres` y `test_bloque_a_postgres` | 112 pasan |
| PostgreSQL local: `test_autenticacion_postgres`, `test_codigos_automaticos_postgres` y `test_idempotencia_postgres` | 36 pasan |
| Backend: `ruff check .` y `ruff format --check` | Limpios |
| Frontend: `npm run typecheck`, `npm test` (incluye `stock-minimo.test.ts`, 7 pruebas nuevas) y `npm run build` | Pasan (241 pruebas) |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Tests adaptados

- **`test_bandejas.py::test_cada_rol_ve_sus_bandejas`:** fija la lista de bandejas por rol. Coordinación y Administración suman `STOCK_BAJO_MINIMO` antes de `INSUMOS_NEGATIVOS`: es el aviso en Inicio que pide D-11.3.
- **Ninguna otra expectativa cambió.** `test_base_local` sigue en 73 tablas y 8 vistas. No hay rutas ni permisos nuevos: `test_matriz_permisos` no cambia. Las consultas SQL registradas no cambian de cantidad: `test_e3_sql_y_ajustes` no cambia.

#### Limitaciones y pendientes

- **Lectura de lo en camino:** en PostgreSQL, Inventario lee todas las órdenes de compra y solicitudes para calcularlo, con la misma función que Compras y sin SQL nuevo. Alcanza para el volumen del MVP. Si crece, conviene una consulta agregada.
- **Reservas de Compras:** las sugerencias de Compras calculan el disponible con las reservas de las Órdenes abiertas, como antes, mientras que Inventario usa todas las Órdenes con reservas. Solo difieren si una Orden cerrada conserva una reserva, lo que no debería pasar.
- **Sugerencia en el modo JSON:** no hay Compras, así que no hay sugerencia ni reposición solicitada. El estado sale con en camino 0.
- **Documentación:** no se actualizaron `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-11 sigue «sin implementar»), `docs/ESTADO_PROYECTO.md` ni `docs/pendientes-producto.md`.
- **Validación manual:** pendiente, en un navegador y sobre PostgreSQL:
  1. cargar un mínimo con Administración y comprobar que Coordinación no puede;
  2. ver el estado y el filtro en Inventario;
  3. ver la bandeja en Inicio;
  4. crear la solicitud sugerida y ver «reposición solicitada»;
  5. recibir la orden de compra y ver que la alerta desaparece.
- **Para el bloque 7:**
  - La última migración es `20261124000200`; la siguiente va después.
  - `test_base_local` sigue fijando 73 tablas y 8 vistas.
  - `Insumo` ya tiene `stock_minimo`. El SELECT de insumos de `storage/postgres/catalogos.py`, `CAMPOS_INSUMO` y el `InsumoIn` de la API son los lugares que se tocan para sumar campos al insumo; el bloque 8 los va a necesitar para la clasificación.
  - `solicitud_compra.origen` admite `MANUAL`, `FALTANTE` y `STOCK_MINIMO`.
  - `en_camino_de_compras(contexto)`, en `application/inventario.py`, es la forma de leer lo en camino dentro de una lectura. En JSON devuelve vacío.
  - `sugerencias()` recibe `minimos`. La sugerencia por faltante con la pieza elegida del bloque 8 tiene que conservar `por_faltante` y `por_minimo`.

### 11.4 Bloque 7: precio por modelo (implementación)

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. Implementa la parte A del bloque 7: DEC-AJ-12 (D-12.1 a D-12.6, BF-01) con las precisiones de 11.1 (puntos 3, 4, 5, 8, 10 y 11). La importación masiva (DEC-AJ-13, BF-02) es la parte B y no está hecha. `business/` no cambia.

| Commit | Qué |
|---|---|
| `f3a216b` | Migración, regla única del precio, precio manual y pendiente, «Definir precio», copia del trabajo, cambio de modelo, avisos, modelos y precios por modelo en Configuración, persistencia PostgreSQL y pruebas |
| `4b21e7c` | Frontend: selectores con el precio del modelo, precio manual o aviso de pendiente, «Precio pendiente de definir», «Definir precio», Modelos de equipo y grilla de precios por modelo |
| este | Esta sección, `docs/contratos-macro-integral.md` y `docs/postgresql/diseno-fisico.md` |

#### Qué quedó

- **Regla única** (`services/precio_trabajo.py`, `resolver_precio`): la usan todos los caminos que crean o redefinen un trabajo: el trabajo inicial del alta (`crear_orden` y `crear_orden_rt`), 070, 075, 127 (`aplicar_redefinicion`, también desde la evaluación 183), 128 y los adicionales de 184, en todos los Orígenes. Devuelve el precio y su origen:
  - `OTROS`: «Otros», como hoy (BR-REP-047).
  - `CATALOGO`: el precio único del Tipo.
  - `CATALOGO_MODELO`: el precio del Tipo para el modelo técnico del equipo de la Orden (`equipo.modelo_tecnico_id`).
  - `MANUAL`: el Tipo tiene precio por modelo, no hay precio para el modelo (o el equipo no tiene modelo técnico) y el actor tiene `PRECIO_MANUAL` e informa precio y motivo.
  - `PENDIENTE`: lo mismo, sin precio manual. Nunca se usa el precio único como respaldo (D-12.1).
  - **Rechazos:** un precio manual con precio de catálogo para la combinación («para bajarlo está el ajuste comercial»), en un Tipo de precio único, en «Otros», sin el permiso o sin motivo, o con más de dos decimales. Son 409 con el código de siempre (`PRECONDICION_INVALIDA`).
- **Permisos nuevos:**
  - `PRECIO_MANUAL`, «Autorizar un precio manual cuando falta el precio de catálogo», grupo Comercial, Coordinación RMA y Administración, configurable. El Técnico y Recepción no lo tienen.
  - `MODELO_EQUIPO_GESTIONAR`, «Gestionar modelos de equipo», Configuración operativa, Administración.
- **Precio pendiente** (punto 3 de 11.1):
  - **Qué se guarda:** precio 0 con origen `PENDIENTE`. La base lo exige (`detalle_version_precio_pendiente`). La API lo marca con `precio_pendiente` y la pantalla muestra «Precio pendiente de definir», nunca $0.
  - **Qué bloquea, solo en los Orígenes con autorización del cliente (Cliente Externo):** el comprobante de ingreso (`faltantes_para_ingreso` suma «definir el precio pendiente de …») y registrar la autorización (`registrar_decision_cliente` rechaza `AUTORIZADO` con el código `PRECIO_PENDIENTE`; el rechazo sí se admite). En RT_INTERNO y en las garantías no bloquea nada.
  - **Aviso** `PRECIO_PENDIENTE` en la situación de la Orden, con la acción `DEFINIR_PRECIO` por trabajo (también en `acciones_complementarias`).
- **«Definir precio»** (`POST /api/orders/{id}/details/{detalle}/price`, `definir_precio`):
  - **Sin precio:** toma el precio de catálogo, que tiene que existir ahora para el modelo de la Orden. Lo puede quien edita los trabajos: la unión de `DETALLE_DEFINIR_RECEPCION`, `DETALLE_DEFINIR_TECNICO`, `DECISION_CLIENTE` y `PRECIO_MANUAL`.
  - **Con precio y motivo:** precio manual, con `PRECIO_MANUAL`. Se rechaza si ya hay precio de catálogo.
  - **Mecanismo:** una versión nueva del Detalle (`detalle_version`, inmutable) marcada `solo_precio`. La anterior (pendiente) queda en `definiciones_anteriores`. El historial registra `ACC-REP-083` / `DEFINIR_PRECIO_TRABAJO`; en PostgreSQL, EV-REP-026 «Detalle redefinido».
  - **Evaluación técnica:** una versión `solo_precio` no cambia el trabajo, así que la evaluación de la definición técnica sigue valiendo (`evaluacion_vigente` mira desde la primera versión técnica igual). Una redefinición técnica la deja sin efecto, como siempre.
  - **Autorización del cliente:** se pide sobre la versión nueva. Como el pendiente impide autorizar, nunca se pierde una autorización.
  - **Ajustes:** si había un ajuste comercial vigente, su recálculo queda como siempre (D-10.4, causa `REDEFINICION`).
- **Copia del trabajo** (D-12.4): cada definición nueva guarda `nombre_trabajo`, `modelo_equipo_id`, `origen_precio`, `precio_motivo`, `precio_definido_por` y `precio_definido_en`. `nombre_del_trabajo` (pantallas, bandejas, situación y comprobantes) prefiere la copia y lee el catálogo solo en los Detalles anteriores, sin copia. Un cambio del catálogo (nombre o precios) no toca las Órdenes.
- **Cambio de modelo** (D-12.6, precisión d y punto 11):
  - **Antes de la autorización del cliente:** al corregir el modelo con `PUT /api/orders/{id}/reception` (`registrar_recepcion`), en Cliente Externo y en los trabajos que todavía la esperan, se vuelve a resolver el precio de los que dependen del modelo (`CATALOGO_MODELO`, `MANUAL` y `PENDIENTE`). Queda una versión `solo_precio` con `REDETERMINAR_PRECIO_POR_CAMBIO_DE_MODELO`.
  - **Un precio manual no se traslada a otro modelo:** toma el de catálogo del modelo nuevo si existe; si no, vuelve a quedar pendiente.
  - **Después de la autorización, y en los Orígenes sin autorización del cliente:** el precio queda como se definió. El Detalle trae `precio_de_otro_modelo` y la situación el aviso `PRECIO_OTRO_MODELO` («se conserva el precio definido; para cambiarlo hay que redefinir el trabajo»).
  - La corrección del vínculo de identidad no cambia el modelo, así que no interviene.
- **Configuración** (solo PostgreSQL, como el resto; en JSON, de solo lectura):
  - **Modelos de equipo** (`GET/POST/PUT /api/admin/device-models`): alta con código `MOD-NNNN` generado por la base (`siguiente_codigo('MOD')`, sigue al mayor existente: `MOD-0037` sobre la carga inicial), edición y baja por desactivación. No admite otra marca + modelo + variante igual sin distinguir mayúsculas ni espacios. Cada campo se audita (entidad `MODELO_EQUIPO`). Los modelos nuevos aparecen en la selección del ingreso (`GET /api/catalogs/device-models`).
  - **Precio por modelo:** `precio_por_modelo` en el alta y la edición del Tipo, con `PRECIOS_GESTIONAR` y auditado. El precio único se conserva pero no se usa.
  - **Precios por modelo** (`PUT /api/admin/repair-types/{codigo}/model-prices`): en bloque, todo o nada, con `PRECIOS_GESTIONAR`. Un precio `null` lo retira: la fila queda inactiva, no se borra. Las combinaciones sin cambios no se escriben; si no cambia ninguna, se rechaza. Cada cambio se audita como `PRECIO_MODELO`, clave «TR-001/MOD-0012», campo `precio`. `historial_precio` los incluye, con la columna `modelo_equipo`.
  - **Lectura:** los Tipos traen `precio_por_modelo` y `precios_modelo` (código del modelo → precio vigente), en la misma consulta del catálogo.
- **Integración con Ventas** (D-12.5, punto 8): `modelo_equipo` es el catálogo técnico de RMA. La copia de productos de Ventas (`catalogo_producto`) sigue aparte y de solo lectura; el alta de Órdenes nuevas elige del catálogo técnico, y el `tp_id` de Ventas queda solo en Órdenes anteriores. El archivo versionado (`app/datos/modelos_equipo.json` y `supabase/seeds/referencia_operativa/03_modelos_equipo.sql`) queda como carga inicial. **Una futura regeneración desde Ventas tiene que emparejar por (marca, modelo, variante)**, la clave única de la tabla, actualizar lo que ya existe sin cambiar su código y crear solo lo que falta con `siguiente_codigo('MOD')`, sin duplicar.
- **Frontend:**
  - **Selectores** (agregar trabajo, agregar según la revisión, evaluación, adicional, redefinición y el trabajo inicial del alta, que usa el modelo elegido en el mismo formulario): muestran el precio del modelo o «Sin precio para este modelo». Con `PRECIO_MANUAL` piden precio y motivo; sin él, avisan que quedará pendiente y qué bloquea.
  - **Trabajos:** marcas «Precio manual» (con motivo y quién) y «Precio pendiente», «Precio de otro modelo» y el formulario «Definir precio» (tomar el de catálogo o, con el permiso, uno manual).
  - **Configuración:** la sección «Modelos de equipo», la casilla «Precio por modelo» del Tipo y su grilla de precios.
  - **Lógica pura:** `features/ordenes-reparacion/precioModelo.ts`.

#### Migración

`20261124000300_precio_por_modelo.sql`, aditiva:

- **`modelo_equipo`:**
  - secuencia `codigo_mod_seq`, iniciada en el mayor `MOD-` existente;
  - `siguiente_codigo` (`create or replace`) suma el prefijo `MOD` y no cambia los demás;
  - trigger `modelo_equipo_codigo_fijo`;
  - `grant insert/update` por columna a `rma_backend`, que ya tenía permiso sobre la tabla.
- **`tipo_reparacion.precio_por_modelo`:** `boolean not null default false`. Los existentes quedan en precio único.
- **Tabla `precio_tipo_modelo`:**
  - columnas `tipo_reparacion_id`, `modelo_equipo_id`, `precio numeric(14,2) >= 0`, `activo` y fechas;
  - única por par, sin borrado;
  - `rma_backend` inserta y actualiza `precio` y `activo`.
- **`detalle_version`:**
  - columnas nuevas, todas admiten vacío salvo `solo_precio`: `nombre_trabajo`, `modelo_equipo_id` (FK), `origen_precio`, `precio_motivo`, `precio_definido_por` (FK), `precio_definido_en` y `solo_precio` (`not null default false`);
  - CHECK de los orígenes;
  - CHECK de manual: motivo si y solo si `MANUAL`, y entonces quién y cuándo;
  - CHECK de pendiente: precio 0;
  - CHECK de `solo_precio`: no en la versión 1 y con origen.
- **`cambio_configuracion`:** el CHECK de entidad suma `MODELO_EQUIPO` y `PRECIO_MODELO`.
- **`historial_precio`:** `create or replace` con las mismas columnas y `modelo_equipo` al final.
- **Historial:** equivalencia `ACC-REP-083` → EV-REP-026.
- **Conteo:** 74 tablas y 8 vistas. Ningún dato existente cambia.

#### Pruebas focalizadas

| Qué | Resultado |
|---|---|
| Backend JSON: `test_precio_por_modelo.py` (nuevo, 24: cada origen y sin respaldo; precio manual rechazado con catálogo, en precio único, en «Otros», sin permiso, sin motivo y con tres decimales; 070 con la copia; pendiente que bloquea el comprobante, con aviso y acción; Recepción no fija precios; trabajo inicial con el modelo del alta; equipo sin modelo técnico; «Definir precio» manual y tomado del catálogo; autorización bloqueada y luego permitida; RT_INTERNO sin bloqueo y con aviso de otro modelo; cambio de modelo antes de autorizar, incluido el manual que pasa al catálogo; después de autorizar se conserva; redefinición 127 y adicional 128 con la misma regla; evaluación vigente con `solo_precio`; nombre por copia y por catálogo; administración solo en PostgreSQL) y los relacionados: `test_configuracion`, `test_configuracion_persistencia`, `test_politica_garantia`, `test_multidetalle`, `test_api_hp_rep_001/002/003`, `test_ingreso_inicial`, `test_ingreso_sin_trabajos`, `test_autorizacion_cliente`, `test_autorizacion_cliente_servicios`, `test_services_autorizacion`, `test_macro_v14`, `test_matriz_permisos`, `test_e3_sql_y_ajustes`, `test_roles_permisos`, `test_situacion_operativa`, `test_reparacion_otros`, `test_correccion_ingreso`, `test_exc_rep_004`, `test_api_exc_rep_004`, `test_adicional_pendiente_sector`, `test_comprobante_autorizacion`, `test_comprobantes`, `test_documentos_custodia_entrega`, `test_bandejas`, `test_ajuste_comercial_*`, `test_descuentos`, `test_e2_equivalencia`, `test_imei_no_disponible`, `test_cancelacion_heredada`, `test_iteracion1_v14`, `test_identidad_equipo`, `test_hito_habilitacion_unico` y `test_integracion_multidetalle_rt` | 801 pasan |
| PostgreSQL local: `test_precio_por_modelo_postgres` (nuevo, 4: migración aditiva —columnas, CHECK, privilegios, `MOD-0037`, única por par, sin borrado, código fijo—; alta y edición de modelos con auditoría, duplicados y permiso; precios por modelo en bloque con retiro, historial con el modelo, rechazos y permiso; copia del trabajo guardada y releída, catálogo que cambia sin tocar la Orden, comprobante después de definir el precio y CHECK del pendiente), `test_base_local`, `test_configuracion_postgres`, `test_contrato_catalogos`, `test_codigos_automaticos_postgres`, `test_macro_v14_postgres`, `test_ordenes_postgres`, `test_garantias_tipo_postgres`, `test_ingreso_bloque3_postgres`, `test_permisos_macro_v14`, `test_permisos_operativos_postgres`, `test_permisos_rma_backend`, `test_ajuste_comercial_postgres`, `test_ux_recepcion_postgres`, `test_iteracion1_postgres` y `test_roles_permisos_postgres` | 213 pasan |
| Backend: `ruff check .` y `ruff format --check` | Limpios |
| Frontend: `npm run typecheck`, `npm test` (incluye `precio-modelo.test.ts`, 6 pruebas nuevas) y `npm run build` | Pasan (247 pruebas) |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Tests adaptados

- **`tests/postgres/test_base_local.py`:** el conteo pasa de 73 a 74 tablas por `precio_tipo_modelo`.
- **`test_matriz_permisos.py`:** se clasifican las cinco rutas nuevas (`details/{detalle}/price` como `SERVICIO` de los cuatro permisos que pueden definir el precio; las de Configuración como `API`).
- **Ninguna otra expectativa cambió.**
  - `test_e3_sql_y_ajustes` no cambia: las consultas de Tipos se amplían, no se suman.
  - El precio informado en un Tipo de catálogo sigue rechazándose con 409 `PRECONDICION_INVALIDA` y un mensaje que nombra el catálogo, como fija `test_reparacion_otros`.

#### Decisiones tomadas en la implementación

- **Precio pendiente = 0 con origen `PENDIENTE`:** `detalle_version.precio` no admite vacío y el saldo, la vista `v_orden_saldo` y los ajustes siguen igual. Por eso el bloqueo está en el comprobante y en la autorización, y la pantalla nunca lo muestra como importe.
- **«Definir precio» como versión nueva:** es la única forma de cambiar el precio sin reescribir una fila inmutable, y deja la historia del trabajo (pendiente → manual) a la vista.
- **`solo_precio` no conserva la autorización del cliente:** no hace falta, porque un pendiente no se autoriza y después de autorizar el precio no se vuelve a determinar.
- **Por defecto nadie fija un precio manual al cargar el trabajo:**
  - 070 y el alta son de Recepción, que no tiene `PRECIO_MANUAL`;
  - 075, 127 y 128 son del Técnico.
  
  El trabajo queda pendiente y lo define Coordinación o Administración con «Definir precio». Si Administración le da `PRECIO_MANUAL` a otro rol, los formularios ya piden precio y motivo.
- **Tomar el precio de catálogo:** no fija ningún importe, así que lo puede quien edita los trabajos. El precio manual sigue exigiendo el permiso.
- **Precios cargados en un Tipo de precio único:** se admiten, pero no se usan hasta marcar «Precio por modelo». Así se puede preparar la grilla y activarla de una vez. La importación (parte B) los limita a los Tipos con precio por modelo.
- **Historial:** `ACC-REP-083` es un identificador nuevo de acción transversal («definir o volver a determinar el precio de un trabajo»). Falta registrarlo en `traceability/` y en `rt-rma-app`; no se tocó `traceability/` para no reabrir la validación.
- **Recálculo de ajustes:** al definir o volver a determinar un precio usa la causa `REDEFINICION`. No se agregó una causa nueva al CHECK de `descuento_recalculo`.

#### Limitaciones y pendientes

- **Cambio de modelo en Cliente Externo:** la corrección del ingreso solo se admite antes de confirmar la recepción (ABI-41), y el comprobante de ingreso confirma y autoriza a la vez. Por eso el cambio de modelo después de autorizar no se puede producir por ese camino. El aviso `PRECIO_OTRO_MODELO` aparece sobre todo en RT_INTERNO.
- **Reportes:** agrupan por `tipo_reparacion_id`, como antes. No usan todavía el origen del precio ni el modelo de la copia.
- **Comprobantes:** el precio pendiente no llega a ninguno, porque los bloquea. Los comprobantes no muestran el origen del precio.
- **JSON:** los Tipos del archivo admiten `precio_por_modelo` y `precios_modelo`, pero no hay administración (DC23).
- **Documentación:** no se actualizaron `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-12 sigue «sin implementar»), `docs/ESTADO_PROYECTO.md` ni `docs/pendientes-producto.md`.
- **Validación manual:** pendiente, en un navegador y sobre PostgreSQL:
  1. dar de alta un modelo;
  2. marcar un Tipo con precio por modelo y cargar su grilla;
  3. ingresar un equipo con y sin precio para su modelo;
  4. ver el pendiente y el bloqueo del comprobante;
  5. definir el precio con Coordinación;
  6. corregir el modelo antes de autorizar.

#### Para la parte B (importación, DEC-AJ-13)

- **Tabla:** `rma.precio_tipo_modelo`.
  - **Columnas:** `tipo_reparacion_id` y `modelo_equipo_id` (uuid, FK), `precio numeric(14,2) >= 0`, `activo`, `creado_en` y `modificado_en`.
  - **Clave:** única por par.
  - **Retiro:** `activo = false`; la fila no se borra.
  - **`rma_backend`:** inserta y actualiza `precio` y `activo`.
- **Escritura atómica con auditoría:** `application.configuracion.guardar_precios_modelo(contexto, usuario_id=..., precios=[PrecioTipoModelo(tipo_reparacion_id="TR-…", modelo_equipo_id="MOD-…", precio=Decimal | None)])`.
  - **Qué valida:** `services.configuracion.cambios_de_precios_modelo` exige `PRECIOS_GESTIONAR`, que existan el Tipo y el modelo, que no sea «Otros», un importe `>= 0` con dos decimales y que no haya pares repetidos.
  - **Qué escribe:** saltea los pares sin cambios y escribe todo en una transacción: `ConfiguracionRepository.guardar_precios_modelo(efectivos, cambios)`, que en PostgreSQL es un `INSERT … ON CONFLICT` con `unnest`, un `UPDATE` para los retiros y una fila de auditoría por cambio.
  - **Celdas vacías:** `precio=None` **retira** el precio. La importación no debe enviar las celdas vacías (D-13.2: no modifican).
  - **Sin cambios:** si ningún par cambia, se rechaza con «no hay cambios». La vista previa puede usar la misma función de validación antes de confirmar.
- **Auditoría:**
  - **Registro:** entidad `PRECIO_MODELO`, clave `"{TR}/{MOD}"` (por ejemplo `TR-001/MOD-0012`), campo `precio`, valores con dos decimales (`"60000.00"`; `None` si se retira).
  - **Historial:** `rma.historial_precio` los muestra con la columna `modelo_equipo`.
  - **Identificador común por importación:** no existe. Hace falta una columna aditiva en `cambio_configuracion` (o una tabla de lotes) y pasarla a `_auditar`.
- **Permiso:** `PRECIOS_GESTIONAR` (punto 10 de 11.1).
- **Modelos Apple:** `application.configuracion.listar_modelos_administrables(contexto)` (todos, también los inactivos) o `GET /api/admin/device-models`, filtrando `marca` Apple sin distinguir mayúsculas. Los códigos son estables (`MOD-…`).
- **Tipos con precio por modelo:** `contexto.catalogos.listar_tipos_reparacion()` con `precio_por_modelo`. Cada uno trae `precios_modelo` (código del modelo → precio vigente): son los valores actuales para la plantilla.
- **Lo que la importación tiene que agregar:** la restricción a marca Apple y a Tipos con `precio_por_modelo`, porque `cambios_de_precios_modelo` no la aplica; la lectura de `.xlsx` (`openpyxl`), CSV y texto con tabulaciones; los importes con formato argentino; la plantilla; y la vista previa.
- **Guardas:**
  - la última migración es `20261124000300`;
  - `test_base_local` fija 74 tablas y 8 vistas;
  - las rutas nuevas van en `test_matriz_permisos`;
  - `test_e3_sql_y_ajustes` solo cuenta las consultas de `catalogos` y `modelos_equipo`. Las escrituras de configuración van en `storage/postgres/configuracion.py`, que no cuenta.

### 11.5 Bloque 7: importación de precios (implementación)

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. Implementa la parte B del bloque 7: DEC-AJ-13 (D-13.1 a D-13.3, BF-02) con la precisión D-13 de 11.1 y el punto 10 de la resolución (permiso `PRECIOS_GESTIONAR`). `business/` no cambia.

| Commit | Qué |
|---|---|
| `1e8a642` | Dependencia `openpyxl`, lógica pura, lectura de planillas, plantilla, API, migración y pruebas del backend |
| `0ff410b` | Frontend: Configuración → «Importar precios» |
| este | Esta sección, `docs/contratos-macro-integral.md` y `docs/postgresql/diseno-fisico.md` |

#### Qué quedó

- **Dependencia:** `openpyxl>=3.1.5` en las dependencias principales de `pyproject.toml` (la imagen la instala con `pip install ".[postgres]"`). Se usa en modo de solo lectura y solo valores (`load_workbook(read_only=True, data_only=True)`) para leer, y para escribir la plantilla. No se agregó soporte multipart.
- **Forma de la planilla** (`services/importacion_precios.py`, lógica pura):
  - **Encabezado:** la primera fila con contenido.
  - **Columna clave:** la primera cuyo encabezado es «Modelo» (también «Código del modelo», sin distinguir mayúsculas ni acentos); si no hay ninguna, la primera columna. Se toma el código `MOD-…` del principio de la celda.
  - **Columnas de precios:** las que empiezan con un código de Tipo (`TR-001` o «TR-001 · Cambio de batería»).
  - **Columnas ignoradas:** cualquier otra (por ejemplo «Nombre del modelo»). La vista previa las lista, para que un encabezado mal escrito («TR001») no pase inadvertido.
- **Importes:** `80000`, `80000.50`, `80000,50`, `80.000`, `80.000,50` y `$ 80.000`. La coma separa decimales y el punto los miles; un único punto seguido de uno o dos dígitos es decimal. Se rechazan con su motivo: «80,000» (ambiguo), las comas de miles («1,234,567», «80,000.50»), los negativos, más de dos decimales y lo que no es un importe. Una celda numérica del `.xlsx` llega como número; un binario que está a menos de una millonésima de los centavos (80000.09999999999) se toma como 80000.10.
- **Validación** (todos los errores juntos, con la celda en notación de planilla):
  - **Columnas:** Tipo desconocido, «Otros», Tipo de precio único, Tipo dado de baja y Tipo repetido.
  - **Filas:** código que no es `MOD-…`, modelo desconocido, modelo de otra marca (solo Apple, sin distinguir mayúsculas), modelo dado de baja (**error**: probablemente una plantilla vieja; se quita la fila o se reactiva el modelo), modelo repetido y fila con precios sin código.
  - **Celdas:** importe inválido. Una celda vacía no cambia nada.
  - Los errores de fila y columna se informan aunque sus celdas estén vacías. Las celdas de una fila o columna con error no se evalúan.
  - **Estructura:** planilla vacía, sin columnas de Tipos, más de 500 filas de modelos, más de 100 columnas o más de 20.000 celdas con datos. El archivo, hasta 2 MB; el `.xlsx`, hasta 30 MB descomprimido.
- **Clasificación:** cada celda válida queda NUEVO (sin precio vigente), CAMBIA o SIN_CAMBIO. Avisos que no bloquean: una variación de más del 50 % y un precio 0. `aplicable`: sin errores y con algún cambio.
- **Lectura** (`integraciones/planillas.py`):
  - **`.xlsx`:** se reconoce por su contenido (ZIP), declare lo que declare el navegador. Solo la primera hoja. Un `.xls` antiguo se rechaza con un mensaje que pide guardarlo como `.xlsx` o CSV.
  - **CSV:** UTF-8 con o sin BOM; si no es UTF-8, Windows-1252 (el CSV de Excel en Windows). El separador se detecta en la primera fila con contenido entre tabulación, punto y coma y coma: gana el que da más columnas.
  - **Celdas pegadas:** texto con tabulaciones (`text/tab-separated-values` o `text/plain`), con la misma detección.
- **Plantilla:** modelos Apple vigentes en las filas (código y nombre), Tipos vigentes con precio por modelo en las columnas («TR-001 · nombre», ordenados por código) y el precio vigente, o la celda vacía.
  - **`.xlsx`:** hoja «Precios» con el encabezado fijo y formato de miles, y una hoja «Instrucciones».
  - **CSV:** UTF-8 con BOM, punto y coma e importes `80000,00`, para que Excel en castellano lo abra bien.
  - Descargarla y volver a importarla da cero cambios y cero errores, en los dos formatos.
- **API** (`api/importacion_precios.py`, todas con `PRECIOS_GESTIONAR`):
  - **`GET /api/admin/model-prices/template?formato=xlsx` (o `csv`):** la plantilla.
  - **`POST /api/admin/model-prices/import/preview?usuario_id=&nombre=`:** la vista previa, sin escribir. Funciona también en el modo JSON, con `editable: false`.
  - **`POST /api/admin/model-prices/import?usuario_id=&nombre=`:** aplicar. Solo PostgreSQL, como el resto de la administración.
  - **Cuerpo:** la planilla cruda, como las fotos y las firmas, con el límite por `Content-Length` y por tamaño leído.
- **Aplicar** (`application/importacion_precios.py`):
  - **Revalidación:** vuelve a leer la misma planilla y a validarla en el servidor, dentro de la transacción y contra los precios de ese momento. Nunca confía en la vista previa del cliente.
  - **Concurrencia:** si un precio cambió entre la vista previa y aplicar, cuenta el actual. Lo que ya tiene ese valor pasa a SIN_CAMBIO, y si no queda ningún cambio se rechaza con «no hay cambios».
  - **Rechazos:** con algún error responde 409, con la cantidad y los tres primeros, y no escribe nada. Sin cambios, también 409.
  - **Escritura:** todo o nada, con `guardar_precios_modelo` (el mismo comando y la misma validación de la edición individual). Solo con los precios NUEVO y CAMBIA: nunca manda un precio vacío, así que nunca retira uno.
  - **Idempotencia:** acepta `Idempotency-Key` (operación `IMPORTAR_PRECIOS_MODELO`, huella con el SHA-256 del contenido), como las fotos. Sin clave, repetirla da «no hay cambios».
- **Auditoría agrupada:**
  - `guardar_precios_modelo` recibe una `ImportacionPrecios` opcional. La registra en la misma transacción, antes de los cambios, con los nuevos y actualizados contados sobre lo que se escribe. Cada `CambioConfiguracion` lleva `importacion_id`.
  - `GET /api/admin/config-changes` y `historial_precio` muestran el identificador.
  - La auditoría de muchos cambios se inserta en lote (`ejecutar_lote`), después de comprobar el usuario. Una importación de 400 precios no hace 400 viajes a la base.
- **Frontend:** Configuración → Taller → «Importar precios» (`ImportarPrecios.tsx`, permiso `PRECIOS_GESTIONAR`):
  - descarga de la plantilla (`.xlsx` o CSV);
  - archivo `.xlsx` o `.csv`: el tipo sale de la extensión y el contenido se copia al elegirlo, así que la vista previa y «Aplicar» envían lo mismo. Se puede volver a elegir el mismo archivo después de editarlo;
  - o pegar las celdas;
  - «Vista previa» muestra el resumen, los errores con su celda, los avisos, las columnas ignoradas y los cambios (modelo, tipo, antes → nuevo, Nuevo o Cambia);
  - «Aplicar» solo se habilita sin errores, con cambios y sobre PostgreSQL. Si no se puede, la pantalla dice por qué. Después muestra el resultado con el identificador;
  - el historial de `PRECIO_MODELO` muestra la importación de cada cambio. La edición individual no cambia;
  - lógica pura en `features/configuracion/importacionPrecios.ts`.

#### Migración

`20261124000400_importacion_precios.sql`, aditiva:

- **Tabla `importacion_precio`:**
  - columnas `id` (uuid), `usuario_id`, `registrado_en`, `formato` (XLSX, CSV o TEXTO), `nombre_archivo`, `precios_nuevos`, `precios_actualizados` y `precios_sin_cambio`;
  - al menos un nuevo o actualizado;
  - inmutable;
  - `rma_backend` solo inserta y lee.
- **`cambio_configuracion.importacion_id`:** FK, vacío en lo existente. El CHECK `cambio_configuracion_importacion_precio` lo admite solo en `PRECIO_MODELO`. Índice parcial. El `grant insert` de la tabla ya lo cubre.
- **`historial_precio`:** `create or replace` con las mismas columnas y `importacion_id` al final.
- **Conteo:** 75 tablas y 8 vistas. Ningún dato existente cambia.

#### Pruebas focalizadas

| Qué | Resultado |
|---|---|
| Backend JSON: `test_importacion_precios.py` (nuevo, 46: importes válidos e inválidos con su motivo; coordenadas; clasificación, avisos, columnas ignoradas y precios a aplicar; errores de columnas y de filas con su celda; estructura y límites; columna clave por nombre y encabezado después de filas vacías; plantilla solo Apple y Tipos por modelo; CSV con BOM y `;`, con `,` y comillas, en Windows-1252; celdas pegadas; formatos no admitidos, `.xls`, ZIP roto, vacío y más de 2 MB; `.xlsx` con números, textos y filas vacías; `.xlsx` sobre el límite de filas; plantilla de ida y vuelta sin cambios en `.xlsx` y CSV; API en JSON: plantilla, vista previa, aplicar rechazado por ser de PostgreSQL, permiso y formato) y los relacionados: `test_precio_por_modelo`, `test_configuracion`, `test_configuracion_persistencia`, `test_matriz_permisos`, `test_e3_sql_y_ajustes`, `test_roles_permisos`, `test_permisos_operativos`, `test_autenticacion` y `test_unidad_de_trabajo` | 397 pasan |
| PostgreSQL local: `test_importacion_precios_postgres` (nuevo, 7: migración aditiva —columna, vista, privilegios, CHECK—; aplicar con la auditoría agrupada, la importación registrada, `historial_precio` y `config-changes`, y repetirla sin cambios; un error no escribe nada; otra marca es error de la fila y no sale en la plantilla; revalidación con los precios del momento; permiso y clave de idempotencia; plantilla `.xlsx` y CSV de ida y vuelta), `test_precio_por_modelo_postgres`, `test_configuracion_postgres`, `test_base_local`, `test_permisos_macro_v14`, `test_permisos_operativos_postgres` (incluye las tres rutas nuevas con sesión real: 401, 403 y no 5xx), `test_permisos_rma_backend`, `test_idempotencia_postgres` y `test_roles_permisos_postgres` | 94 pasan |
| Backend: `ruff check .` y `ruff format --check` | Limpios |
| Frontend: `npm run typecheck`, `npm test` (incluye `importacion-precios.test.ts`, 9 pruebas nuevas) y `npm run build` | Pasan (256 pruebas) |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Tests adaptados

- **`tests/postgres/test_base_local.py`:** el conteo pasa de 74 a 75 tablas por `importacion_precio`.
- **`test_matriz_permisos.py`:** se clasifican las tres rutas nuevas como `API("PRECIOS_GESTIONAR")`.
- **Ninguna otra expectativa cambió.** `test_e3_sql_y_ajustes` no cambia: las consultas nuevas están en `storage/postgres/configuracion.py`.

#### Decisiones tomadas en la implementación

- **Una tabla de importaciones además de la columna:** D-13.3 pide conservar la auditoría «de la importación y sus cambios». La columna agrupa los cambios. La tabla guarda lo que no está en ellos: el archivo, el formato y los sin cambios. Una importación rechazada no deja registro: no se aplicó nada.
- **Modelo dado de baja, otra marca o Tipo inválido:** son errores aunque sus celdas estén vacías. La regla es simple y predecible, y una plantilla vieja se corrige quitando la fila o la columna.
- **«80.000» son ochenta mil:** sigue el formato argentino del texto aprobado. Un único punto con uno o dos dígitos es decimal, para aceptar el formato llano («80000.50»).
- **La vista previa funciona en el modo JSON:** no escribe nada. Aplicar sigue el patrón de la administración y es solo PostgreSQL.
- **Celdas vacías y retiros:** la importación nunca retira un precio (D-13.2). Quitar uno sigue siendo de la edición individual.

#### Limitaciones y pendientes

- **Multimarca:** queda fuera (D-13.2). Otra marca es un error de la fila.
- **Listado de importaciones:** no hay pantalla. Se ven en el historial de precios y en `rma.importacion_precio`.
- **Concurrencia:** dos importaciones simultáneas no se bloquean entre sí, igual que la edición individual. La última escritura gana y la auditoría registra cada una.
- **Documentación:** no se actualizaron `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-13 sigue «sin implementar»), `docs/ESTADO_PROYECTO.md` ni `docs/pendientes-producto.md`, como en los bloques anteriores.
- **Validación manual:** pendiente, en un navegador y sobre PostgreSQL:
  1. descargar la plantilla en `.xlsx` y en CSV;
  2. abrirla en Excel y en Google Sheets, cambiar precios y volver a subirla;
  3. pegar celdas copiadas de Google Sheets;
  4. ver los errores con una planilla con fallas;
  5. aplicar y revisar el historial.

#### Para el bloque 8 (DEC-AJ-14)

- **Guardas:**
  - la última migración es `20261124000400`;
  - `test_base_local` fija 75 tablas y 8 vistas.
- **Auditoría:**
  - `CambioConfiguracion` tiene `importacion_id`, opcional;
  - `cambio_configuracion.importacion_id` solo se admite en `PRECIO_MODELO`, por CHECK;
  - `_auditar` inserta en lote cuando hay más de un cambio.
- **Lectura de planillas:** `integraciones/planillas.py` (`formato_de`, `leer_planilla`, `escribir_xlsx`, `escribir_csv`) es reutilizable si el bloque 8 necesita importar la clasificación de insumos. `openpyxl` ya es dependencia.
- **Patrón de importación:** lógica pura que devuelve una vista previa con errores por celda, más aplicar revalidando en el servidor dentro de la transacción. Sirve como modelo.

### 11.6 Bloque 8: clasificación y compatibilidad (implementación)

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. Implementa la parte A del bloque 8: DEC-AJ-14 D-14.1, D-14.2 y D-14.5 (BF-14), con el punto 10 de la resolución de 11.1 (categorías y fabricantes con `INSUMO_GESTIONAR`). Los requisitos por tipo, la elección de la pieza antes de reservar, la sustitución, la factibilidad y las sugerencias por pieza elegida (D-14.4, precisión 6 y puntos 1 y 2 de la resolución) son la parte B y no están hechos. `business/` no cambia.

| Commit | Qué |
|---|---|
| `108840e` | Migración, dominio, funciones de compatibilidad, administración de categorías y fabricantes, clasificación del insumo, persistencia y pruebas del backend |
| `1bfe356` | Frontend: Categorías de insumos, Fabricantes de repuestos, Insumos, Inventario, Compras y `SelectorInsumo` |
| este | Esta sección, `docs/contratos-macro-integral.md` y `docs/postgresql/diseno-fisico.md` |

#### Qué quedó

- **Insumo = SKU real (D-14.1):** el stock, los lotes, los costos, el libro, las reservas, los consumos, Compras y los insumos previstos siguen en la fila de `insumo` y referencian el mismo `insumo.id`. Ninguna de esas tablas cambió.
- **Clasificación (D-14.2), opcional y gradual:**
  - **Categoría → Subcategoría:** catálogo `categoria_insumo` con dos niveles fijos. Una categoría no tiene padre; una subcategoría tiene por padre una categoría. El nivel y el padre se fijan en el alta y **no cambian** (mover una subcategoría reclasificaría en silencio sus insumos), así que nunca hay un tercer nivel.
  - **El insumo guarda el nivel más específico** (`Insumo.categoria_id`: la subcategoría o, si no tiene, la categoría). La categoría padre se deriva.
  - **Fabricante:** catálogo `fabricante_repuesto`, distinto de la marca del equipo.
  - **Variante** y **código del fabricante o del proveedor:** texto opcional. El código no es único y no reemplaza al INS.
  - **Modelos compatibles:** `insumo_compatibilidad`, de muchos a muchos con `modelo_equipo` (el catálogo de los precios). **Sin filas, el insumo es universal.**
- **Compatibilidad** (`services/clasificacion_insumos.py`, funciones puras):
  - universal: sirve para todo modelo;
  - con modelos: solo esos;
  - equipo sin modelo técnico (`None`): solo los universales. La elección de otra pieza con «compatibilidad no verificada» (punto 2 de la resolución) es de la parte B.
- **Administración** (solo PostgreSQL, con `INSUMO_GESTIONAR`, auditada):
  - **Categorías:** alta con código `CAT-NNN` generado por la base, edición del nombre y baja por desactivación. El nombre no se repite entre las categorías ni entre las subcategorías de una misma categoría, sin distinguir mayúsculas. Una subcategoría nueva necesita una categoría vigente.
  - **Fabricantes:** alta con `FAB-NNN`, edición y baja. Nombre único sin distinguir mayúsculas.
  - **Auditoría:** entidades `CATEGORIA_INSUMO` (campos `nombre`, `padre_id`, `activo`) y `FABRICANTE_REPUESTO` (`nombre`, `activo`). Su historial lo ve quien tiene `INSUMO_GESTIONAR`.
- **Clasificación del insumo** (`POST/PUT /api/admin/supplies`):
  - campos `categoria_id`, `fabricante_id`, `variante`, `codigo_fabricante` y `modelos_compatibles`. En el `PUT`, el que no viene se conserva y `null` (o `[]`) lo quita, como el stock mínimo;
  - **la compatibilidad reemplaza el conjunto** (se quitan los modelos que ya no están y se agregan los nuevos) en la misma transacción que el insumo y su auditoría. Si no queda como se pidió, se revierte todo;
  - **auditoría** en la entidad `INSUMO`: campos `categoria`, `fabricante`, `variante`, `codigo_fabricante` y `compatibilidad` (los códigos MOD ordenados y separados por coma; vacío es universal).
- **Validación (decidida en la implementación):**
  - la categoría, el fabricante y los modelos tienen que existir;
  - **lo que se asigna o se agrega tiene que estar vigente**. Una subcategoría de una categoría dada de baja cuenta como dada de baja;
  - **lo que el insumo ya tenía se conserva aunque se haya dado de baja**: la clasificación es gradual y dar de baja un modelo o una categoría no obliga a corregir los insumos.
- **Lectura en los dos modos:**
  - los insumos (`GET /api/admin/supplies` y cada situación de `GET /api/inventory`) traen la clasificación y `modelos_compatibles`;
  - `GET /api/catalogs/supply-classification` (cualquier sesión) da categorías, fabricantes y modelos, activos o no, para nombrar y filtrar;
  - en JSON los insumos se leen sin clasificar y universales, sin categorías ni fabricantes, y la administración responde que es de PostgreSQL.
- **Inventario:** `buscar` también encuentra por el código del fabricante y la variante.
- **Frontend:**
  - **Configuración → Inventario y compras:** secciones «Categorías de insumos» (en árbol, con alta de subcategorías desde su categoría) y «Fabricantes de repuestos», con `INSUMO_GESTIONAR` y su historial.
  - **Insumos:** columnas Categoría (Cat › Subcat), Fabricante, Variante y Compatibilidad («Universal», los modelos o «N modelos»); filtros por texto, categoría, «Sin clasificar», fabricante y modelo compatible. La ventana edita la clasificación y los modelos con «Universal» o «Solo para algunos modelos», búsqueda, «Agregar los N visibles» (por ejemplo, todas las variantes de «iPhone 14») y quitar. Un modelo dado de baja no se agrega pero se conserva.
  - **Inventario:** columna Clasificación con la compatibilidad, filtros por categoría, fabricante y modelo compatible (sobre la lista leída) y la clasificación en el detalle del insumo.
  - **Compras:** la nueva solicitud, «Agregar insumo» de la orden de compra y el filtro de costos usan `SelectorInsumo`, con búsqueda y filtros, y las etiquetas «INS-012 · Batería iPhone 14 · Acme · alta capacidad». Sigue una línea por insumo por orden de compra.
  - **Lógica pura:** `features/inventario/clasificacion.ts`.

#### Migración

`20261124000500_clasificacion_insumos.sql`, aditiva:

- **`categoria_insumo`:**
  - `codigo` CAT-nnn, `nombre`, `padre_id` (FK a sí misma), `activo` y fechas;
  - índice único `(padre_id, lower(btrim(nombre))) nulls not distinct`;
  - trigger `categoria_insumo_dos_niveles`: el padre es una categoría sin padre y no cambia;
  - código fijo y sin borrado;
  - `rma_backend` inserta y actualiza `nombre` y `activo`.
- **`fabricante_repuesto`:** `codigo` FAB-nnn, `nombre` único sin distinguir mayúsculas, `activo` y fechas; código fijo, sin borrado y los mismos privilegios.
- **`insumo`:** `categoria_id` y `fabricante_id` (FK), `variante` y `codigo_fabricante`, opcionales, sin texto en blanco, con índices parciales y `grant update`.
- **`insumo_compatibilidad`:** clave `(insumo_id, modelo_equipo_id)`, índice por modelo. `rma_backend` lee, inserta y borra: es el conjunto vigente y su historia está en la auditoría.
- **Códigos:** secuencias `codigo_cat_seq` y `codigo_fab_seq`; `siguiente_codigo` (`create or replace`) suma `CAT` y `FAB` sin cambiar los demás.
- **`cambio_configuracion`:** el CHECK de entidad suma `CATEGORIA_INSUMO` y `FABRICANTE_REPUESTO`.
- **Datos (D-14.5):** ningún insumo queda clasificado ni con modelos (todos universales), y no hay movimientos de stock.
- **Conteo:** 78 tablas y 8 vistas.

#### Pruebas focalizadas

| Qué | Resultado |
|---|---|
| Backend JSON: `test_clasificacion_insumos.py` (nuevo, 27: universal, con modelos y sin modelo técnico; categoría que incluye sus subcategorías; `insumos_compatibles` por modelo, categoría y vigencia; alta y edición de categorías con auditoría, dos niveles, padre inexistente o de baja, nombres repetidos entre pares, nivel fijo y sin cambios; fabricantes únicos; sin permiso; clasificación auditada con la compatibilidad ordenada y la vuelta a universal; alta sin clasificar sin auditar vacíos; lo nuevo tiene que existir y estar vigente y lo que ya tenía se conserva; JSON sin clasificar, universal y de solo lectura; `listar_insumos_compatibles` en JSON) y los relacionados: `test_insumos_admin`, `test_inventario_operativo`, `test_inventario_global`, `test_compras_reglas`, `test_stock_minimo`, `test_configuracion`, `test_configuracion_persistencia`, `test_matriz_permisos`, `test_e3_sql_y_ajustes`, `test_exc_rep_001` a `004`, `test_api_exc_rep_001` a `004`, `test_override_reservas_ajenas`, `test_permisos_operativos`, `test_roles_permisos`, `test_precio_por_modelo`, `test_importacion_precios`, `test_bandejas` y `test_comprobantes` | 660 pasan |
| PostgreSQL local: `test_clasificacion_insumos_postgres` (nuevo, 6: migración aditiva —columnas, sin datos, códigos CAT-001 y FAB-001, privilegios, CHECK de entidad—; la base exige dos niveles, padre fijo, nombres únicos, formato y código fijo, sin borrado y sin textos en blanco; categorías y fabricantes por la API con auditoría, permiso y lectura en los dos GET; clasificación y compatibilidad del insumo por la API con reemplazo del conjunto, modelos de baja y desconocidos rechazados sin cambiar nada, conservación de lo de baja, vuelta a universal, auditoría y sin movimientos; categoría de baja que se conserva pero no se asigna; atomicidad con la validación desactivada), `test_insumos_admin_postgres`, `test_compras_postgres`, `test_reservas_postgres`, `test_lotes_postgres`, `test_stock_minimo_postgres`, `test_base_local`, `test_configuracion_postgres`, `test_permisos_macro_v14`, `test_permisos_operativos_postgres`, `test_permisos_rma_backend`, `test_roles_permisos_postgres`, `test_contrato_catalogos`, `test_codigos_automaticos_postgres`, `test_precio_por_modelo_postgres`, `test_importacion_precios_postgres`, `test_movimientos_postgres`, `test_consultas_postgres` y `test_migracion_stock_lotes` | 196 pasan |
| PostgreSQL local: `test_pruebas_sql_supabase` (las pruebas SQL de `supabase/tests`) | Pasa |
| Backend: `ruff check .` y `ruff format --check` | Limpios |
| Frontend: `npm run typecheck`, `npm test` (incluye `clasificacion-insumos.test.ts`, 11 pruebas nuevas) y `npm run build` | Pasan (266 pruebas) |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Tests adaptados

- **`tests/postgres/test_base_local.py`:** el conteo pasa de 75 a 78 tablas por `categoria_insumo`, `fabricante_repuesto` e `insumo_compatibilidad`.
- **`test_matriz_permisos.py`:** se clasifican las seis rutas nuevas: `GET /api/catalogs/supply-classification` como `SESION` y las de Configuración como `API("INSUMO_GESTIONAR")`.
- **`supabase/tests/10_esquema.sql`:** la lista de entidades estaba desactualizada desde los bloques 5 y 7 (72 entidades; faltaban `descuento_recalculo`, `precio_tipo_modelo` e `importacion_precio`), así que `test_pruebas_sql_supabase` fallaba. Suma esas tres y las tres de este bloque: 78.
- **`frontend/tests/configuracion-v2.test.ts`:** Administración ve 15 secciones (antes 13) y Recepción con `INSUMO_GESTIONAR` ve «Insumos», «Categorías de insumos» y «Fabricantes de repuestos». Las dos secciones nuevas son de DEC-AJ-14 y usan el permiso de insumos (punto 10 de la resolución).
- **Ninguna otra expectativa cambió.** `test_e3_sql_y_ajustes` no cambia: las consultas de insumos de `catalogos` se amplían, no se suman, y las nuevas están en `storage/postgres/operativa.py`.

#### Decisiones tomadas en la implementación

- **Nivel y padre fijos:** una categoría no pasa a subcategoría ni cambia de categoría. Garantiza los dos niveles sin revisar descendientes y evita reclasificar insumos en silencio. Para reorganizar, se da de alta otra y se reclasifican los insumos.
- **Lo de baja se conserva, no se asigna:** vale para categorías, subcategorías de categorías de baja, fabricantes y modelos compatibles.
- **Compatibilidad como conjunto con borrado:** es la única tabla de este bloque donde `rma_backend` borra, igual que `mesa_tipo_reparacion`. La historia completa queda en `cambio_configuracion` (antes y después de cada cambio).
- **Auditoría de la compatibilidad en la entidad `INSUMO`:** el historial del insumo muestra su clasificación y su compatibilidad juntas, sin otra entidad.
- **Una lectura pública de la clasificación:** Inventario y Compras la necesitan para nombrar y filtrar, y la consultan roles sin `INSUMO_GESTIONAR`. No expone nada sensible.
- **Sin importación masiva de la clasificación:** se clasifica de a uno, con los filtros «Sin clasificar» y por categoría para encontrar lo pendiente. `integraciones/planillas.py` queda disponible si hace falta.
- **Reporte de consumo por categoría:** no se agregó. El reporte operativo lee solo Órdenes y sumarlo agrega la lectura de insumos y categorías; queda como mejora.

#### Limitaciones y pendientes

- **Parte B sin hacer:** requisitos por tipo, pieza elegida en el Detalle, elección automática con una sola compatible, «compatibilidad no verificada», sustitución antes y después de reservar, factibilidad sobre la pieza elegida y sugerencias de Compras con la pieza elegida.
- **Insumos previstos actuales** (`tipo_reparacion_insumo`): siguen igual. No se valida su compatibilidad con el modelo; la precisión 6 los trata como universales.
- **Stock mínimo:** sigue por SKU (D-14.5 lo deja así).
- **Documentación:** no se actualizaron `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-14 sigue «sin implementar»), `docs/ESTADO_PROYECTO.md` ni `docs/pendientes-producto.md`, como en los bloques anteriores.
- **Validación manual:** pendiente, en un navegador y sobre PostgreSQL:
  1. dar de alta categorías, subcategorías y fabricantes;
  2. clasificar un insumo y marcar sus modelos con la búsqueda;
  3. filtrar «Sin clasificar» en Insumos;
  4. filtrar por modelo en Inventario;
  5. elegir insumos con los filtros en Compras;
  6. dar de baja una categoría y ver que el insumo la conserva.

#### Para la parte B (D-14.4)

- **Guardas:**
  - la última migración es `20261124000500`;
  - `test_base_local` fija 78 tablas y 8 vistas, y `supabase/tests/10_esquema.sql` lista 78 entidades: una tabla nueva va en los dos;
  - las rutas nuevas van en `test_matriz_permisos`;
  - `test_e3_sql_y_ajustes` cuenta solo las consultas de `catalogos` y `modelos_equipo`.
- **Tablas:**
  - `rma.categoria_insumo` (`id` uuid, `codigo` CAT-nnn, `nombre`, `padre_id`, `activo`);
  - `rma.fabricante_repuesto` (`id`, `codigo` FAB-nnn, `nombre`, `activo`);
  - `rma.insumo` suma `categoria_id`, `fabricante_id`, `variante` y `codigo_fabricante`;
  - `rma.insumo_compatibilidad` (`insumo_id`, `modelo_equipo_id`), sin filas: universal.
  - Un requisito por categoría o subcategoría (`tipo_reparacion_requisito`, precisión 6) puede referenciar `categoria_insumo.id`; la pieza elegida en `detalle_version`, `insumo.id`.
- **Dominio** (`app.domain.models`):
  - `Insumo.categoria_id`, `fabricante_id`, `variante`, `codigo_fabricante` (códigos o texto, `None` si no hay) y `modelos_compatibles: tuple[str, ...]` (códigos MOD ordenados; vacío: universal);
  - `CategoriaInsumo(id, nombre, padre_id, activo)` con `es_subcategoria`;
  - `FabricanteRepuesto(id, nombre, activo)`.
- **Funciones puras** (`app.services.clasificacion_insumos`):
  - `compatible(insumo: Insumo, modelo_equipo_id: str | None) -> bool`;
  - `es_universal(insumo) -> bool`;
  - `en_categoria(insumo, categoria_id, categorias: Mapping[str, CategoriaInsumo]) -> bool` (una categoría incluye sus subcategorías);
  - `categoria_padre(categoria_id, categorias) -> str | None` y `categorias_por_id(categorias)`;
  - `insumos_compatibles(insumos, modelo_equipo_id, categoria_id=None, *, categorias=(), solo_activos=True) -> list[Insumo]`, en el orden recibido;
  - `categoria_vigente(categoria, categorias)`.
- **Cómo listar las piezas para (categoría, modelo):** `app.application.clasificacion_insumos.listar_insumos_compatibles(contexto, modelo_equipo_id=…, categoria_id=…, solo_activos=True)`. Lee los insumos y, si hace falta, las categorías, y aplica `insumos_compatibles`. El modelo de la Orden es `equipo.modelo_tecnico_id`; sin él, solo los universales. «Una sola compatible activa» es `len(...) == 1`.
- **Catálogos:** `contexto.operativa.listar_categorias_insumo()` y `listar_fabricantes_repuesto()` (en JSON, vacías); los modelos, `application.configuracion.listar_modelos_administrables(contexto)`.
- **Factibilidad sin pieza elegida (punto 1):** sumar el disponible de `insumos_compatibles(...)` por requisito, o evaluar la pieza elegida.
- **Frontend:**
  - `components/SelectorInsumo.tsx`: `SelectorInsumo` acepta `modelo` (fijo: solo compatibles; `null`: equipo sin modelo, solo universales), `categoria` (fija: la del requisito), `soloVigentes`, `valor`, `onCambiar`, `etiqueta` y `opcionVacia`. Sirve para elegir o sustituir la pieza. `useClasificacionInsumos()` y `FiltrosClasificacion` también se exportan.
  - `features/inventario/clasificacion.ts`: `compatibleCon`, `filtrarInsumos`, `etiquetaInsumo`, `nombreCategoria`, `textoCompatibilidad` y `opcionesCategoria`.
  - `SituacionInsumo` (tipos) trae la clasificación y `modelos_compatibles`.

### 11.7 Bloque 8: requisitos y elección de la pieza (implementación)

Commits en `feat/ajustes-funcionales-uat`, sin push ni despliegue. Implementa la parte B del bloque 8: DEC-AJ-14 D-14.4 (modificada), la precisión 6 y los puntos 1 y 2 de la resolución de 11.1. `business/` no cambia (BR-REP-002, 005 y 006 y PROC-REP-210 conservan su texto: lo nuevo está en BR-REP-049 y PROC-REP-080/185, ya registrados).

| Commit | Qué |
|---|---|
| `508cbaa` | Migración, dominio, `services/piezas.py`, integración con la factibilidad, la reserva y el consumo, administración de los insumos necesarios, API, persistencia y pruebas del backend |
| `7fc4114` | Frontend: piezas del trabajo, «Elegir pieza» / «Sustituir», aviso al iniciar, «Insumos necesarios» del tipo y trabajos sin pieza en Compras |
| este | Esta sección, `docs/contratos-macro-integral.md` y `docs/postgresql/diseno-fisico.md` |

#### Qué quedó

- **Secuencia aprobada:** tipo definido → modelo conocido → insumos necesarios → pieza compatible elegida → disponibilidad → reserva al iniciar (BR-REP-006) → ejecución. El motor de reservas, movimientos y consumo no se rediseñó: la pieza elegida entra en lo previsto del Detalle (`services.inventario.insumos_previstos_del_detalle`: previstos concretos del tipo + pieza vigente de cada requisito, una línea por insumo con las cantidades sumadas). Desde ahí la usan la factibilidad, la reserva todo o nada, el impacto del override y el formulario de consumo.
- **Requisitos por tipo** (`TipoReparacionRequisito`): categoría o subcategoría (`CAT-…`; una categoría incluye sus subcategorías) y cantidad, uno por categoría, con posición. Conviven con `tipo_reparacion_insumo` (previstos concretos), que se conserva igual.
  - **Configuración → Tipos de reparación → «Insumos necesarios»** (`TIPO_REPARACION_GESTIONAR`, solo PostgreSQL). Edita los dos conjuntos en bloque.
  - **Previstos concretos:** lo que se agrega tiene que ser un insumo vigente y **universal**. Una pieza que depende del modelo va como requisito. Lo que ya estaba se conserva.
  - **Requisitos:** lo que se agrega tiene que tener la categoría vigente (y su padre). El que sigue conserva su id, el que se quita queda inactivo (nunca se borra) y el que vuelve se reactiva.
  - **Auditoría:** entidad `TIPO_REPARACION`, campos `insumos_previstos` y `requisitos` («INS-001 x 1; …»). Sin cambios se rechaza.
  - **Modo JSON:** archivo opcional `tipo_reparacion_requisitos.json` (sin él, ningún requisito).
- **Pieza elegida** (`ReparacionDetail.piezas: list[EleccionPieza]`, append-only).
  - **Cada registro:** requisito, copia del tipo, la categoría y la cantidad, pieza (`insumo_id`; vacía en una anulación), causa (`AUTOMATICA`, `ELECCION`, `SUSTITUCION`, `CAMBIO_MODELO` o `REDEFINICION`), «compatibilidad no verificada», modelo del equipo, motivo, quién, cuándo y `reemplaza_a`.
  - **Vigente:** la última del requisito, si tiene pieza y es del tipo vigente del Detalle.
  - Una vez elegida, el Detalle trabaja con su elección aunque el tipo cambie la cantidad o retire el requisito. Los requisitos sin elección se leen en vivo del tipo.
- **Piezas elegibles** (`piezas_elegibles`):
  - con modelo, las activas de la categoría compatibles con él (universales incluidas);
  - sin modelo técnico, las universales;
  - si no hay universales, cualquiera activa de la categoría, con motivo obligatorio y la marca «compatibilidad no verificada» (punto 2).
- **Elección automática** (`conciliar_piezas`, causa `AUTOMATICA`, a nombre de quien hace la acción): un requisito sin pieza con una sola elegible verificada la recibe. Sin modelo y sin universales, nunca (hace falta motivo).
  - **Cuándo corre:** al definir un trabajo (alta con trabajo inicial, 070, 075), al agregar uno (128, 183/184), al redefinir (127), al cambiar el modelo del equipo y al iniciar la Ejecución (preparación).
  - Solo toca Detalles DEFINIDO.
- **Elección manual** (`POST …/details/{detalle}/pieces`, permiso nuevo **`PIEZA_ELEGIR`** «Elegir o sustituir la pieza concreta de un trabajo», por defecto Técnico, Coordinación RMA y Administración, BR-REP-039):
  - solo piezas elegibles y vigentes, con el Detalle DEFINIDO o EN_PROGRESO y la Orden abierta;
  - `GET …/pieces/options` da las elegibles con su disponible.
- **Sustitución antes de reservar:** un registro `SUSTITUCION` con motivo obligatorio que reemplaza al anterior. No toca el inventario.
- **Sustitución después de reservar** (Detalle EN_PROGRESO): en una sola transacción, con la Orden y los dos insumos bloqueados por clave (DI-2).
  - **Liberación:** LIBERACION_RESERVA de lo pendiente de la pieza anterior en el Detalle, hasta la cantidad de la elección (lo demás sigue reservado si la pieza coincidía con un previsto concreto). Referencia su RESERVA y va trazada a la Ejecución en curso, con el usuario y la observación «Sustitución de pieza: …».
  - **Reserva nueva:** RESERVA de la pieza nueva, trazada igual.
  - **Registro:** la elección y el paso del historial.
  - **Sin disponible** (descontadas las reservas de las demás Órdenes): se rechaza con 409 `RECURSO_NO_DISPONIBLE` y no cambia nada. Con override vigente del Detalle reserva solo lo disponible, como al iniciar (P-06).
  - **PROC-REP-210:** la liberación por sustitución no cuenta como inventario aplicado (`inventario.es_liberacion_por_sustitucion`). Al completar o interrumpir, el 210 consume y libera lo pendiente como siempre.
- **No se sustituye:**
  - una pieza con CONSUMO o DESPERDICIO en el Detalle;
  - un Detalle COMPLETO o CANCELADO;
  - con la Ejecución en curso, un requisito que todavía no tenía pieza («se elige antes de iniciar»).
- **Factibilidad (PROC-REP-080)** (`piezas.faltantes_con_requisitos`):
  - previstos concretos y piezas elegidas como siempre;
  - un requisito sin pieza es factible si alguna pieza elegible tiene disponible suficiente (punto 1);
  - si no, falta «Sin pieza elegida: <categoría>», que no es un ID de insumo, así que Compras no lo cuenta como demanda de un SKU.
- **Reserva (PROC-REP-185):** no se inicia con un requisito vigente sin pieza, ni con una pieza dada de baja o que ya no sirve para el modelo.
  - Es una precondición: 409 `PIEZA_SIN_ELEGIR`, sin reserva ni paso. No es la reserva fallida.
  - Con todas elegidas, la reserva es la de siempre: todo o nada, con 186 y BLOQUEADO_POR_RECURSOS si falta stock; el override sigue igual.
  - Una sola reserva por disponibilidad: el bloqueo por clave y el trigger del libro, como siempre (prueba de concurrencia de la sustitución en PostgreSQL).
- **Consumo (PROC-REP-210):** sin cambios de reglas; el formulario lista los previstos con la pieza elegida (por SKU y lote).
- **Cambio de modelo y redefinición** (`conciliar_piezas`, regla documentada):
  - una pieza elegida para otro tipo (redefinición) se anula (`REDEFINICION`);
  - una que ya no sirve para el modelo se reemplaza por la única compatible o se anula (`CAMBIO_MODELO`), y el requisito vuelve a «Pendiente de elegir»;
  - **nunca** se toca una pieza con reserva pendiente o ya consumida en el Detalle: se conserva y la lectura la marca `compatible_con_modelo: false`, para sustituirla a mano;
  - en la práctica no hay reservas en esos momentos: el modelo solo cambia antes de confirmar la recepción (sin custodia no se reserva) y la redefinición (127) parte de un Detalle sin Ejecución, con sus reservas cerradas por el 210. Ninguna reserva queda huérfana.
- **Compras:** la demanda por faltante de un trabajo bloqueado es la de su pieza elegida (por SKU), sumada a `por_faltante` como en el bloque 6.
  - Un requisito sin pieza y sin ninguna elegible en stock se informa aparte: `GET /api/purchases/suggestions/pending-pieces`, «Trabajos sin pieza elegida» en Compras. No suma demanda de ningún SKU, así que `por_faltante` y `por_minimo` siguen consistentes.
- **Historial:** acción transversal nueva **`ACC-REP-084`** (no está en `traceability/`): `ELEGIR_PIEZA`, `ELEGIR_PIEZA_AUTOMATICA`, `SUSTITUIR_PIEZA`, `SUSTITUIR_PIEZA_RESERVADA` y `REVISAR_PIEZA`. En PostgreSQL es EV-REP-010 «Detalle definido», y la sustitución reservada EV-REP-024.
- **Lectura** (`GET /api/orders/{id}`): cada Detalle suma `requisitos_insumo` (estado, pieza, causa, marcas, reservada, consumida, motivo, quién y cuándo) y `piezas`. `insumos_previstos` incluye las piezas (`pieza: true`).
- **Frontend:**
  - bloque «Piezas por categoría» del trabajo, con la visibilidad de la información técnica (`DETALLE_TECNICO_CONSULTAR`, BF-07);
  - marcas «Pendiente de elegir», «Elegida automáticamente», «Compatibilidad no verificada», «No compatible con el modelo actual», «Reservada» y «Consumida»;
  - ventana «Elegir pieza» / «Sustituir» con `SelectorInsumo` sobre las elegibles, su disponible y el motivo;
  - aviso al iniciar y mensaje de `PIEZA_SIN_ELEGIR`;
  - «· pieza elegida» en el formulario de consumo;
  - «Insumos necesarios» en Configuración → Tipos de reparación;
  - «Trabajos sin pieza elegida» en Compras;
  - lógica pura en `features/ordenes-reparacion/piezas.ts` y `features/configuracion/insumosNecesarios.ts`.

#### Migración

`20261124000600_requisitos_pieza.sql`, aditiva:

- **`tipo_reparacion_requisito`:**
  - columnas `id` uuid, `tipo_reparacion_id`, `categoria_id`, `cantidad numeric(12,3) > 0`, `posicion`, `activo` y fechas;
  - únicas `(tipo, categoría)` e `(id, tipo)`;
  - tipo y categoría fijos (trigger), sin borrado;
  - `rma_backend` inserta y actualiza `cantidad`, `posicion` y `activo`.
- **`tipo_reparacion_insumo`:** `grant update (cantidad)` y `delete`, para editarlo desde Configuración.
- **`detalle_pieza`:**
  - código `PZA-…` y posición única por Detalle;
  - FK compuesta al requisito con el tipo copiado y FK compuesta `reemplaza_a` del mismo Detalle, única;
  - CHECK de anulación (sin pieza solo `CAMBIO_MODELO` o `REDEFINICION`), de sustitución (motivo y reemplazo) y de compatibilidad no verificada (motivo y pieza);
  - trigger `validar_detalle_pieza`: categoría del requisito, cadena lineal (reemplaza a la última del requisito) y pieza vigente;
  - inmutable; `rma_backend` solo inserta y lee.
- **Historial:** equivalencias ACC-REP-084 → EV-REP-010 y `SUSTITUIR_PIEZA_RESERVADA` → EV-REP-024.
- **Datos:** ningún tipo queda con requisitos ni ningún Detalle con piezas; no hay movimientos.
- **Conteo:** 80 tablas y 8 vistas.

#### Pruebas focalizadas

| Qué | Resultado |
|---|---|
| Backend JSON: `test_requisitos_pieza.py` (nuevo, 44). Cubre: tipo sin requisitos como antes; elección automática con una sola compatible y sus pasos; pendiente con varias; opciones; factibilidad de un pendiente con y sin disponible; inicio rechazado sin pieza (`PIEZA_SIN_ELEGIR`, nada cambia); reserva de previstos y pieza; reserva fallida con la pieza elegida; override sin cambios; permiso (Recepción no, Técnico, Coordinación y Administración sí); compatibilidad y categoría; sustitución antes de reservar con motivo; sin modelo (universales automáticas, no verificada con motivo); sustitución reservada (una LIBERACION_RESERVA y una RESERVA, saldos, consumo de la nueva al completar); sin disponible o con la última unidad reservada por otra Orden; primera elección en curso rechazada; pieza consumida y trabajo terminado; cambio de modelo (reemplazo, anulación y pieza reservada intacta); redefinición a otro tipo (anulación y automáticas); administración solo PostgreSQL; reglas puras de «Insumos necesarios» | 44 pasan |
| Backend JSON, relacionados: `test_inventario_operativo`, `test_inventario_global`, `test_override_reservas_ajenas`, `test_compras_reglas`, `test_exc_rep_001` a `004`, `test_api_exc_rep_001` a `004`, `test_completar_ejecucion_consistencia`, `test_integracion_multidetalle_rt`, `test_multidetalle`, `test_macro_v14`, `test_stock_minimo`, `test_precio_por_modelo` y `test_clasificacion_insumos` | 335 pasan |
| Backend JSON, más relacionados: `test_e3_sql_y_ajustes`, `test_bandejas`, `test_configuracion`, `test_configuracion_persistencia`, `test_correccion_ingreso`, `test_matriz_permisos`, `test_insumos_admin`, `test_permisos_operativos`, `test_roles_permisos`, `test_importacion_precios`, `test_comprobantes`, `test_ajuste_comercial_dec_aj_10`, `test_autorizacion_cliente`, `test_autorizacion_cliente_servicios`, `test_comprobante_autorizacion`, `test_hito_habilitacion_unico`, `test_ingreso_inicial`, `test_iteracion1_v14`, `test_motivo_interrupcion`, `test_orden_cerrada`, `test_salidas_servicios`, `test_situacion_operativa`, `test_titularidad_toma`, `test_ingreso_sin_trabajos` (incluye las 44 nuevas) | 600 pasan |
| PostgreSQL local: `test_requisitos_pieza_postgres.py` (nuevo, 7). Cubre: migración aditiva con sus privilegios por tabla y columna y las equivalencias; insumos necesarios por la API con auditoría, id conservado, desactivar y reactivar, universal y permiso; la base protege requisitos y piezas (inmutable, sin borrado, tipo y categoría fijos, cadena lineal, CHECK); elegir, reservar, sustituir y consumir con el libro, los saldos, `v_conciliacion_inventario` y `verificar_integridad()` conciliados, los eventos y la relectura idéntica; inicio rechazado sin pieza; dos sustituciones a la vez sobre la última unidad (una reserva y la otra se rechaza sin cambios); Compras pide la pieza elegida y lista aparte el requisito sin pieza | 7 pasan |
| PostgreSQL local, relacionados: `test_reservas_postgres`, `test_movimientos_postgres`, `test_lotes_postgres`, `test_compras_postgres`, `test_migracion_stock_lotes`, `test_macro_v14_postgres`, `test_clasificacion_insumos_postgres`, `test_permisos_rma_backend`, `test_permisos_macro_v14`, `test_permisos_operativos_postgres`, `test_ordenes_postgres`, `test_configuracion_postgres`, `test_precio_por_modelo_postgres` | 172 pasan |
| PostgreSQL local: `test_base_local` y `test_pruebas_sql_supabase` | 19 pasan |
| Backend: `ruff check .` y `ruff format --check .` | Limpios |
| Frontend: `npm run typecheck`, `npm test` (incluye `requisitos-pieza.test.ts`, 33 pruebas nuevas) y `npm run build` | Pasan (299 pruebas; el build con el aviso de siempre por el tamaño del bundle) |

La suite completa, el resto de `tests/postgres` y los E2E quedan para el QA integral.

#### Tests adaptados

- **`tests/postgres/test_base_local.py`:** de 78 a 80 tablas (`tipo_reparacion_requisito` y `detalle_pieza`).
- **`supabase/tests/10_esquema.sql`:** suma las dos tablas y pasa a 80 entidades.
- **`test_e3_sql_y_ajustes.py`:** la lectura `catalogos.tipo_reparacion_requisitos` suma una consulta de catálogos (de 17 a 18 más las del stock).
- **`test_matriz_permisos.py`:** cinco rutas nuevas clasificadas:
  - `POST …/pieces`: `SERVICIO("PIEZA_ELEGIR")`;
  - `GET …/pieces/options`: `API("ORDENES_CONSULTAR")`;
  - `GET/PUT /api/admin/repair-types/…/supplies`: `API("TIPO_REPARACION_GESTIONAR")`;
  - `GET /api/purchases/suggestions/pending-pieces`: `API("COMPRAS_CONSULTAR")`.
- **Ninguna otra expectativa cambió.** En el frontend no se cambió ningún test.

#### Decisiones tomadas en la implementación

- **Elección automática también al iniciar:** es parte de la preparación. Si el tipo ganó un requisito después de definir el trabajo y hay una sola pieza, no se bloquea en vano. Queda en el historial.
- **Cantidad de una sustitución:** la de la elección anterior, no la del requisito vigente. El Detalle trabaja con su elección.
- **«Consumida» = cualquier CONSUMO o DESPERDICIO de la pieza en el Detalle:** por ejemplo, una Ejecución interrumpida que la usó. Desde ahí su elección queda fija en ese Detalle. Un retrabajo la vuelve a reservar como hoy con los previstos concretos.
- **Coincidencias:** si la pieza elegida coincide con un previsto concreto, se pide y se reserva la suma, y la sustitución libera solo la cantidad de la elección. En la pantalla, esa línea aparece en el bloque de piezas y no entre los previstos concretos.
- **Previstos concretos universales:** se exige al agregarlos (precisión 6). Los existentes no se validan contra el modelo.
- **Una LIBERACION_RESERVA por sustitución con usuario:** el libro exige la Ejecución en la liberación. El usuario y la observación la distinguen del 210.

#### Limitaciones y pendientes

- **Trazabilidad:**
  - `ACC-REP-084` es un identificador nuevo; falta registrarlo en `traceability/` y en `rt-rma-app`, igual que ACC-REP-083;
  - no se actualizaron `traceability/discrepancias-baseline-v1.4.md` (DEC-AJ-14 sigue «sin implementar»), `docs/ESTADO_PROYECTO.md` ni `docs/pendientes-producto.md`, como en los bloques anteriores.
- **Etiqueta de la pieza en la Orden:** la lectura trae código y nombre, no el fabricante ni la variante (la ventana de elección sí).
- **Sin preferida:** no hay marca de pieza preferida ni sugerencia de SKU para un requisito sin pieza en Compras (la propuesta de la sección 11 la mencionaba; la decisión aprobada no la pide).
- **Stock mínimo:** sigue por SKU. Un mínimo por categoría y modelo queda para después.
- **Cambio de modelo con la pieza reservada:** solo se probó en el service, porque la API no permite cambiar el modelo después de confirmar la recepción.
- **Validación manual:** pendiente, en un navegador y sobre PostgreSQL:
  1. cargar categorías y piezas con su compatibilidad;
  2. definir los insumos necesarios de un tipo;
  3. ingresar un equipo con modelo y ver la elección automática o «Pendiente de elegir»;
  4. elegir la pieza e iniciar;
  5. sustituirla con la Ejecución en curso y ver el inventario;
  6. completar y ver el consumo;
  7. equipo sin modelo con una pieza no verificada;
  8. trabajos sin pieza en Compras.

#### Para el QA integral

Es el último bloque de la iteración 2. Conviene correr la suite completa del backend, `tests/postgres` completo y los E2E antes de proponer la integración. Además, revisar a mano el circuito de piezas con un técnico, Coordinación y Recepción, esta última sin `PIEZA_ELEGIR` ni la información técnica.

## 12. Validación manual de los ocho bloques

Recorrido único para validar a mano las iteraciones 1 y 2 antes del QA integral (paso 3 de la metodología). Junta los pasos manuales de las secciones 8, 10 y 11.2 a 11.7 en el orden de un caso real: primero la configuración y después una Orden desde el ingreso hasta la entrega.

Casi toda la administración nueva es **solo de PostgreSQL**: modelos, precios por modelo, importación, categorías, fabricantes, insumos necesarios, stock mínimo, empresa y términos. En JSON se ve, pero no se edita. Por eso se valida sobre PostgreSQL local, en una base aparte.

Cada diferencia se anota con el número del paso (por ejemplo, «C5») y el usuario. Esas notas son la entrada de los ajustes (paso 4 de la metodología).

### 12.1 Entorno local sobre PostgreSQL

La puesta en marcha está en [`VALIDACION_LOCAL.md`](VALIDACION_LOCAL.md), con comandos para PowerShell: PostgreSQL local (puerto 54329), la base aparte **`rma_validacion`** (nunca `rma_dev` ni `rma_ensayo_integral`), el backend sobre PostgreSQL con el acceso de prueba, el frontend, los usuarios y una carga de **datos ficticios por la API** (`supabase/scripts/validacion_local/`).

**Datos de partida:** los de la sección 4 de esa guía.

- **Configuración ya cargada:** empresa, los modelos MOD-0037 («iPhone 18 · Prueba local») y MOD-0038 (otra marca), categorías CAT-001 a 009, fabricantes FAB-001 a 003, insumos INS-002 a 012 con su clasificación, stock y mínimos, los Tipos TR-003 a TR-008 con precio por modelo (con huecos a propósito: la batería del iPhone 13) e insumos necesarios, y una solicitud y una orden de compra.
- **Órdenes:** OR-000001 a OR-000004, en el ingreso.
- **Planillas de ejemplo** para la importación, sin aplicar.
- **Cómo se ajustan los pasos:** la sección 4.7 de la guía explica cómo se ajustan los pasos de abajo a esos datos. Por ejemplo, el próximo modelo es MOD-0039 y las Órdenes nuevas empiezan en OR-000005.

### 12.2 Recorrido

Los bloques (B1 a B8) y los BF de cada paso permiten volver al detalle de las secciones 8 a 11. Los nombres entre comillas son los de la pantalla.

#### A. Configuración (bloques 4, 6, 7 y 8)

| Paso | Usuario | Qué hacer | Esperado |
|---|---|---|---|
| A1 | administracion | Configuración → «Datos de la empresa»: cambiar el horario y el pie del comprobante | Se guarda y queda en el historial de cambios. Los comprobantes nuevos lo copian (B4, BF-19) |
| A2 | administracion | Configuración → «Términos y condiciones»: ver la versión 2 y publicar una 3 con un cambio menor | La versión 2 no tiene los 180 días ni la anulación por retiro de un tercero. La 3 rige para los comprobantes nuevos y las anteriores se conservan (B4, P-04 y P-05) |
| A3 | administracion | Configuración → «Modelos de equipo»: dar de alta un modelo Apple de prueba. Repetirlo con otras mayúsculas o espacios | Se crea con el código `MOD-0037` y aparece en el alta de Órdenes. El duplicado se rechaza. `coordinacion` no ve la sección (B7, BF-01) |
| A4 | administracion | Configuración → Tipos de reparación: crear «Cambio de batería» con la Mesa EST-001 y «Precio por modelo». En su grilla, poner precio a las variantes de iPhone 14 y a A3, y dejar sin precio el iPhone 13. Después, quitar un precio | La grilla se guarda todo o nada. El precio quitado queda inactivo, sin borrarse. Cada cambio queda en el historial de precios con su modelo (B7, BF-01) |
| A5 | administracion | Configuración → «Importar precios»: descargar la plantilla `.xlsx` y la CSV y subirlas sin cambios | «No hay cambios» y ningún error, en los dos formatos (B7, BF-02) |
| A6 | administracion | Editar la plantilla en Excel o Google Sheets: cambiar dos precios y agregar errores («80,000», un encabezado «TR001» y un modelo de otra marca). Ver la vista previa | Cada error con su celda, la columna «TR001» entre las ignoradas y «Aplicar» deshabilitado |
| A7 | administracion | Corregir los errores, ver la vista previa y aplicar. Después, pegar celdas copiadas de Google Sheets | Nuevo y Cambia con el precio anterior y el nuevo; se aplica todo junto. El historial de precios muestra el identificador de la importación. El pegado funciona igual |
| A8 | administracion | Configuración → «Categorías de insumos»: crear «Baterías» y una subcategoría. En «Fabricantes de repuestos», dos fabricantes. Repetir un nombre | Códigos `CAT-…` y `FAB-…`. El nombre repetido se rechaza (B8, BF-14) |
| A9 | administracion | Configuración → Insumos: crear dos baterías de iPhone 14 de fabricantes distintos, en «Baterías», con «Solo para algunos modelos» y «Agregar los N visibles» de iPhone 14. Crear un insumo universal (por ejemplo, un adhesivo). Poner stock mínimo 2 a la primera batería | Las columnas muestran la categoría, el fabricante, la compatibilidad y el mínimo. El filtro «Sin clasificar» muestra INS-001 y el adhesivo (B8 y B6, BF-14 y BF-15) |
| A10 | coordinacion | Intentar editar el stock mínimo | No puede: no tiene `INSUMO_GESTIONAR` (BF-15) |
| A11 | administracion | Tipos de reparación → «Insumos necesarios» de «Cambio de batería»: requisito «Baterías» × 1 y el adhesivo como previsto concreto. Intentar agregar una batería como previsto concreto | Se guarda con auditoría. La batería se rechaza como previsto: no es universal y va como requisito (B8, BF-14) |
| A12 | administracion | Inventario → «Registrar ingreso»: 1 unidad de la primera batería, 3 de la segunda y 5 del adhesivo | La primera batería queda «Bajo mínimo» (ámbar). El filtro «Bajo mínimo» la muestra. En Inicio aparece «Insumos a reponer» para `coordinacion` y `administracion`, y no para `recepcion` ni `tecnico` (B6, BF-15) |
| A13 | administracion | Compras → «Sugerencias de reposición»: crear la solicitud sugerida | La cantidad completa el mínimo y la causa es el stock mínimo. En Inventario pasa a «Bajo mínimo · reposición solicitada» (azul) y no se vuelve a sugerir. Nada se crea solo |
| A14 | administracion | Compras → nueva solicitud: buscar con el selector y filtrar por categoría, fabricante y modelo. En Inventario, filtrar por modelo compatible iPhone 14. Dar de baja la subcategoría de A8 | Etiquetas «INS-… · nombre · fabricante · variante». Por modelo se ven las baterías compatibles y los universales. El insumo conserva la subcategoría dada de baja, pero no se le puede asignar a otro (B8, BF-14) |

#### B. Ingreso (bloques 1, 3 y 7)

| Paso | Usuario | Qué hacer | Esperado |
|---|---|---|---|
| B1 | recepcion | Orden 1, Cliente Externo: iPhone 14 del catálogo, «Cambio de batería» y la verificación de funcionalidades. Usar «Crear y generar el comprobante» | El selector muestra el precio del modelo. La verificación es obligatoria. El canal presencial viene preseleccionado. El visor ofrece «Imprimir» como acción principal y no imprime solo. El comprobante trae la verificación y los datos de A1 (B3 y B7, BF-06, BF-08 y BF-01) |
| B2 | recepcion | Orden 2: el mismo trabajo con iPhone 13, sin precio para el tipo | «Sin precio para este modelo» y el aviso de que queda pendiente. La Orden se crea, pero el comprobante no. El trabajo muestra «Precio pendiente de definir», nunca $0 (B7, BF-01) |
| B3 | recepcion | Orden 2: corregir el modelo a iPhone 14 en los datos del ingreso. Después, volver a iPhone 13 | Con iPhone 14 toma el precio de catálogo; con iPhone 13 vuelve a quedar pendiente. El historial registra que se volvió a determinar el precio |
| B4 | coordinacion | Orden 2: «Definir precio» con precio manual y motivo. Intentar lo mismo en la Orden 1 | Marca «Precio manual» con el motivo y quién. En la Orden 1 se rechaza, porque hay precio de catálogo: para bajarlo está el ajuste comercial. Después, `recepcion` genera el comprobante de la Orden 2. Como ninguna batería es compatible con iPhone 13, el trabajo queda bloqueado por recursos (C9) |
| B5 | recepcion | Orden 3, sin trabajos: «Trabajo solicitado» en texto libre, el modelo cargado a mano (sin modelo técnico) e «IMEI no disponible». Enviar a revisión | El equipo se identifica con su `EQP-…`, nunca con un IMEI ficticio. El comprobante de recepción confirma la custodia en el mismo acto (B3, BF-04 y BF-05) |
| B6 | recepcion | Orden 3: «Registrar el IMEI real», con motivo | Queda en la Orden y en la auditoría. Se admite hasta la entrega (BF-05) |
| B7 | recepcion | Abrir la Orden 1 | No ve la información técnica: antecedentes, ejecuciones, insumos previstos, «Datos técnicos» ni piezas. Sí ve el estado, el precio, el historial y los cobros (B1, BF-07) |

#### C. Diagnóstico, piezas y ejecución (bloques 1 y 8)

| Paso | Usuario | Qué hacer | Esperado |
|---|---|---|---|
| C1 | tecnico | Orden 1: ver «Piezas por categoría» | «Baterías» está «Pendiente de elegir», porque hay dos piezas compatibles. Con una sola, sería «Elegida automáticamente» (B8, BF-14) |
| C2 | tecnico | Tomar la Orden 1 e iniciar la Ejecución sin elegir la pieza | Rechazo `PIEZA_SIN_ELEGIR`, con el aviso. No hay reserva ni paso nuevo |
| C3 | recepcion | Buscar «Elegir pieza» en la Orden 1 | No aparece: no tiene `PIEZA_ELEGIR` |
| C4 | tecnico | «Elegir pieza»: la primera batería, que muestra su disponible. Iniciar | Se reservan la pieza y el adhesivo. Inventario los muestra reservados |
| C5 | tecnico | Con la Ejecución en curso, «Sustituir» por la segunda batería. Probar sin motivo y después con motivo | Sin motivo se rechaza. Con motivo, en una sola operación: la liberación de la primera, la reserva de la segunda (observación «Sustitución de pieza») y el paso del historial. Si la segunda no tuviera disponible, 409 sin cambios |
| C6 | tecnico | Completar la Ejecución y consumir | El formulario de consumo marca «· pieza elegida». Se consume la segunda batería, que queda «Consumida» y ya no se puede sustituir |
| C7 | tecnico y coordinacion | Orden 3: `tecnico` agrega «Cambio de batería» según la revisión; `coordinacion` define el precio manual. `tecnico` elige la pieza | Sin modelo técnico el precio queda pendiente, hasta el precio manual (B7). No hay baterías universales, así que se puede elegir cualquiera de la categoría, con motivo obligatorio y la marca «Compatibilidad no verificada» (B8) |
| C8 | tecnico | Con una Ejecución en curso de Cliente Externo, agregar un trabajo adicional | Espera la autorización del cliente. La Orden aparece en «Pendientes de mi sector» de `recepcion` aunque haya una ejecución en curso. Iniciar el adicional sin autorizar da 409 (B1, BF-12) |
| C9 | administracion | Compras → «Trabajos sin pieza elegida» | La Orden 2 aparece aparte, con «Sin pieza elegida» y la categoría, y no suma demanda a ningún SKU en las sugerencias (B8) |

#### D. Cobro y ajustes (bloque 5)

| Paso | Usuario | Qué hacer | Esperado |
|---|---|---|---|
| D1 | recepcion | Orden 2: «Ajuste comercial»: descuento al trabajo y cortesía a la Orden | Un solo formulario con clase, destino, tipo, valor y motivo, y la vista previa del precio original, el ajuste y el final, igual al saldo (B5, BF-09) |
| D2 | administracion y recepcion | En Configuración → Permisos, quitar la cortesía a Recepción. Con `recepcion`, intentar cambiar o quitar la cortesía. Restaurar el permiso | Con solo el permiso del descuento no se puede cambiar ni quitar una cortesía |
| D3 | recepcion | Buscar «Revertir» y «Corregir» en el historial de ajustes | No aparecen: no tiene `AJUSTE_REVERTIR` |
| D4 | administracion | Revertir el descuento del trabajo. Corregir la cortesía de la Orden a otro importe | El revertido se ve tachado y vuelve a regir el anterior, o ninguno. La corrección queda enlazada. El saldo se recalcula y los pagos no cambian. Cada operación queda en el historial |
| D5 | tecnico o recepcion | Redefinir o cancelar un trabajo que tiene ajuste, antes de ejecutarlo | Aviso de recálculo, y el recálculo en el historial de ajustes, sin un ajuste nuevo |
| D6 | recepcion | Emitir la versión nueva del comprobante de autorización y ver el de ingreso anterior | Por trabajo: precio, «Descuento» o «Cortesía» y precio final. El ajuste de la Orden va en una línea aparte, sin motivo, usuario ni fecha. El comprobante anterior se ve como se emitió |
| D7 | recepcion | Registrar el pago de la Orden 1 hasta saldo 0 | Saldo 0. Si un ajuste dejara saldo a favor, la entrega exigiría devolverlo antes |

#### E. Entrega y cierre (bloques 1, 2, 4 y 6)

| Paso | Usuario | Qué hacer | Esperado |
|---|---|---|---|
| E1 | recepcion | Orden 1, lista para retirar: entregar sin avisar al cliente | Se ofrece la entrega sin el aviso (paso 260). El progreso muestra el aviso como opcional y salteado (B2, BF-20) |
| E2 | recepcion | En la misma confirmación: el check-in faltante, con la verificación del ingreso como referencia, y «¿Retira otra persona?» Sí, con nombre, apellido y teléfono | Una sola confirmación, con saldo 0 y custodia. Un solo «Comprobante de entrega y garantía», con los términos de A2, la garantía de cada trabajo desde la entrega (la misma fecha en todos los documentos) y quién retiró. La garantía no cambia (B2 y B4, BF-18, BF-19 y BF-17) |
| E3 | administracion | Orden 1 entregada: intentar aplicar, corregir o revertir un ajuste | Se rechaza: después de la entrega no hay ajustes (B5) |
| E4 | administracion y recepcion | Cambiar otra vez el pie en «Datos de la empresa» y reimprimir el comprobante de E2 | Conserva la empresa y los términos con que se emitió (B4) |
| E5 | recepcion | Orden 3, después de autorizarla, ejecutarla y cobrarla: enviar el WhatsApp «equipo listo para retirar» y confirmar el envío | Registra el aviso una sola vez. El retiro demorado cuenta desde que la Orden quedó lista, no desde el aviso (B2, BF-20) |
| E6 | administracion | Convertir la solicitud de A13 en una orden de compra y recibirla | La primera batería pasa a «Suficiente» y sale de «Insumos a reponer» (B6, BF-15) |

### 12.3 Qué no cubre

- **QA integral:** la suite completa del backend, `tests/postgres` completo y los E2E siguen pendientes. Este recorrido no los reemplaza.
- **Casos que cubren las pruebas automáticas y no se hacen a mano:** concurrencia (dos sustituciones sobre la última unidad, dos importaciones a la vez), el cambio de modelo con una pieza reservada (solo en el service: la API no lo permite después de confirmar la recepción) y los límites de tamaño de las planillas.
- **Modo JSON:** la administración nueva no se valida en JSON, porque es de solo lectura.
- **Entornos remotos:** nada se despliega. El UAT sigue sin las nueve migraciones ni la imagen con `openpyxl`, y la autenticación es la de prueba, no Supabase Auth.
- **Fuera de alcance:** la garantía RMA (su ingreso sigue confirmando la custodia aparte, sin la verificación); BF-03, BF-10, BF-11, BF-13 y BF-16; el PDF descargable del comprobante de entrega, que se imprime desde el navegador.
- **Pendientes de producto:** P-08 a P-16 de [`pendientes-producto.md`](pendientes-producto.md) son decisiones abiertas, no fallas. Una diferencia que ya figure allí se anota igual, como confirmación.
- **Pantallas en celular (390 px) y otros navegadores:** quedan para la pasada manual del QA integral (P2-17 de [`DEUDA_TECNICA.md`](DEUDA_TECNICA.md)).
