# Configuración v2: identificadores, permisos y catálogos operativos

> **Estado:** implementado en local (19/11/2026), fases A a E, con QA independiente por fase y QA integral; sin push ni despliegue. Implementación y resultados en la sección 12.
>
> **Rama:** `feat/configuracion-v2`, creada desde `feat/reparacion-rt-etapa1` (`f3036ca`). Las referencias `archivo:línea` apuntan a esa base. Las del backend son relativas a `app/backend/app/` y las del frontend a `app/frontend/src/`.
>
> **Decisiones:** D1 a D8 y DF-1 a DF-5 aprobadas el 19/11/2026 (sección 10).

## Decisiones aprobadas

| # | Decisión aprobada | Cómo queda en el diseño |
|---|---|---|
| D1 | Permisos por rol, sin permisos individuales | Sección 3. Las concesiones por usuario quedan para otra iteración |
| D2 | Los permisos nuevos empiezan solo con Administración | Sección 3.2. La división de Compras es un caso particular: DF-4 |
| D3 | Separar la modificación de precios | `PRECIOS_GESTIONAR` (sección 3.2) |
| D4 | El identificador y el código del insumo son automáticos; los personalizados no se piden por defecto | Sección 1.4. La pantalla no tiene campos de código |
| D5 | Separar los permisos de Compras y evaluar si confirmar y cancelar van por separado | Sección 3.3. Se recomienda separarlos (DF-5) |
| D6 | Códigos únicos sin distinguir mayúsculas | Secciones 1.3 y 7 |
| D7 | Rama `feat/configuracion-v2` desde `feat/reparacion-rt-etapa1` | Creada. El discovery está en `109666b` |
| D8 | Resolver las brechas críticas y las de bajo costo; registrar el resto | Sección 2.3 |

**Ajustes pedidos en la revisión:**

| # | Ajuste | Dónde se aplica |
|---|---|---|
| 1 | La numeración puede tener huecos; lo importante es unicidad, seguridad ante concurrencia e inmutabilidad | Generador con secuencias de PostgreSQL (1.3) |
| 2 | **CFG-06** Garantías: mostrar solo días con y sin check-in | Sección 5 |
| 3 | **CFG-07** Retirar de la interfaz el plazo de retiro; el backend lo conserva | Sección 6 |
| 4 | **CFG-08** Mostrar solo las plantillas de ingreso y retiro | Sección 6 |
| 5 | Verificar que cada permiso se aplique en el backend y en el frontend | Sección 8 |
| 6 | Compatibilidad con versiones anteriores y datos históricos | Sección 9 |
| 7 | Los códigos automáticos no se vuelven obligatorios | 1.4: opcionales en la API y sin restricciones nuevas en la base |
| 8 | Nada se oculta cambiando parámetros ni borrando plantillas | Secciones 5 y 6: se oculta solo en la interfaz |

## Resumen

1. **Identificadores (CFG-01).**
   - Se crea un generador en la base con una secuencia por prefijo. No bloquea filas y puede dejar huecos.
   - Lo usan tipos de reparación, motivos, insumos, proveedores, solicitudes y órdenes de compra, reclamos y preguntas de checklist.
   - Los formatos actuales se conservan y ningún código existente cambia.
   - El código queda protegido contra cambios en la base.
   - La unicidad no distingue mayúsculas.
2. **Permisos (CFG-02 y CFG-03).**
   - Siete permisos configurables nuevos para catálogos, que empiezan con Administración.
   - Seis permisos de Compras en lugar de `COMPRAS_GESTIONAR`.
   - Dependencias entre permisos de acción y de consulta.
   - Se corrigen las brechas A y B.
   - Una prueba de la matriz recorre **todas** las rutas del backend y otra recorre los controles del frontend.
3. **Altas (CFG-04).** Un botón «+ Nuevo …» abre un modal sin campos de código. Al guardar se actualiza solo el listado afectado.
4. **Estructura (CFG-05).** Configuración se organiza por funcionalidad. Cada subsección tiene su ruta y su permiso.
5. **CFG-06, CFG-07 y CFG-08.** Solo cambia la interfaz; la base de datos y el comportamiento del backend se conservan.
   - Los tipos muestran únicamente los plazos con y sin check-in.
   - El plazo de retiro desaparece de la pantalla y sigue rigiendo con su valor actual.
   - Solo se ven las plantillas de ingreso y de retiro.

---

## 1. Identificadores y códigos (CFG-01)

### 1.1 Convención vigente

| Tipo | Qué es | Ejemplo | Quién lo genera |
|---|---|---|---|
| **Clave técnica interna** | `id uuid` de cada tabla, usado en las FK. El backend nunca lo expone y traduce código → uuid (`storage/postgres/ordenes.py:198-213`) | `9f1c…` | La base (`gen_random_uuid()`) |
| **Código funcional visible** | `codigo` único: es el «id» del dominio en la API y en pantalla | `OR-000123`, `TR-001`, `INS-001` | Depende de la entidad (1.2) |
| **Clave única de negocio** | Dato de negocio único que no es el identificador | email del usuario, documento del cliente, (marca, modelo, variante), número de lote por insumo, remito por OC | El usuario o el origen |

`services/identificadores.nuevo_id(prefijo)` genera `PREFIJO-<12 hex>` y se guarda en `codigo`, no en la PK.

### 1.2 Inventario y propuesta

**Catálogos de Configuración**

| Entidad (tabla) | Código hoy | Generación hoy | Problema | Propuesta |
|---|---|---|---|---|
| Tipo de reparación (`tipo_reparacion.codigo`) | Sin regex. Seed `TR-001`, `TR-002`. `TR-OTROS` reservado | **A mano**, distingue mayúsculas (`application/configuracion.py:57`) | Si dos altas chocan da **500** (`storage/postgres/configuracion.py:24-37,176-179`) | **Automático `TR-NNN`** |
| Motivo (`motivo_operativo.codigo`) | `^[A-Z0-9][A-Z0-9_-]*$`. `CANC-OTRO`, `INT-OTRO` | **A mano**, pasado a mayúsculas | Choque: 500 | **Automático `CANC-NNN` o `INT-NNN`**, según el tipo |
| Insumo, identificador (`insumo.clave`) | Seed `INS-001` | **A mano** («Identificador») | Choque: 500 | **Automático `INS-NNN`** |
| Insumo, código operativo (`insumo.codigo`) | Seed `BAT-IP14` | **A mano** («Código») | Choque: 500 | **Automático: igual a la clave** (D4) |
| Plantilla (`plantilla_mensaje.codigo`) | Semántico (`INGRESO`, …) | A mano | — | **Sin cambios**: con CFG-08 la interfaz ya no da altas (sección 6) |
| Proveedor (`proveedor.codigo`) | `PRV-0001` | Automático con `max(codigo)+1` (`storage/postgres/compras.py:31-38,254-259`) | **No es seguro**: choque da 500; el máximo es lexicográfico, así que se repite después de `PRV-9999` | Mismo formato, generador nuevo |
| Pregunta de checklist (`checklist_pregunta.codigo`) | `CHK-0001` | Automático con el máximo en Python (`application/checklist.py:97-103`) | No es seguro | Mismo formato, generador nuevo |
| Mesa, usuario, medio de pago, modelo de equipo, tipo de equipo | `EST-001`, `RECEP-001`, `EFECTIVO`, `MOD-0001`, valor de Ventas | Seed, script o sincronización. No tienen alta en la aplicación | — | Sin cambios |

**Operaciones**

| Entidad | Código | Generación | Problema | Propuesta |
|---|---|---|---|---|
| Orden | `OR-000001` | Secuencia, formato y salto de códigos usados (`storage/postgres/ordenes.py:183-196`) | Ninguno | **Es el modelo a imitar.** Sin cambios |
| Detalle, comunicación, recepción de compra, documento | `DET-001`, `COM-001`, `REC-01`, `{OR}-{SIGLA}-{vv}` | Correlativo por padre, con el padre bloqueado | Ninguno | Sin cambios |
| Solicitud y orden de compra | `SC-000001`, `OC-000001` | `max(codigo)+1` | **No es seguro**: choque da 409; se repite después de 999999 | Mismo formato, generador nuevo |
| Reclamo de garantía | `RGA-000001` | `max(codigo)+1` (`storage/postgres/reclamos.py:43-46,102-106`) | **No es seguro**: choque da 500 | Mismo formato, generador nuevo |
| Cliente, equipo, toma, ejecución, movimiento, pago, devolución, foto, firma, lote | `CLI-`, `EQP-`, `TOM-`, `EJE-`, `MOV-`/`MST-`, `PAG-`, `DEV-`, `FOT-`, `FIR-`, `LOT-` + 12 hex | `nuevo_id` (aleatorio) | Ninguno | Sin cambios. `sincronizacion_origen.id` tiene un CHECK atado a ese formato (`^SINC-[0-9a-f]{12}$`) |

### 1.3 Generador (con huecos permitidos)

Se crea una **secuencia de PostgreSQL por prefijo** y una función de formato, como ya se hace con la Orden:

```text
rma.codigo_tr_seq, codigo_canc_seq, codigo_int_seq, codigo_ins_seq,
codigo_prv_seq, codigo_chk_seq, codigo_sc_seq, codigo_oc_seq, codigo_rga_seq

rma.siguiente_codigo(prefijo text) -> text
  CASE fijo prefijo -> secuencia y ancho (sin SQL dinámico);
  nextval(...) y ceros a la izquierda SIN truncar (lpad trunca: se usa el
  mismo criterio que formatear_numero_orden).
```

**Propiedades:**
- **Concurrencia:** `nextval` nunca entrega dos veces el mismo número y no bloquea filas. Dos altas simultáneas reciben números distintos, sin esperas.
- **Huecos:** si un alta falla, ese número se pierde. Está aceptado (ajuste 1).
- **Unicidad aunque haya códigos cargados por otros medios** (SQL o un script):
  - el backend pide el siguiente número mientras el código ya exista, igual que `reservar_codigo` de la Orden;
  - el `INSERT` usa `ON CONFLICT DO NOTHING` y, si no inserta, reintenta;
  - si se agotan los reintentos, responde **409**, nunca 500, con el mismo código de error que estas altas ya devolvían ante un duplicado (`PRECONDICION_INVALIDA`), para no cambiar el contrato de los clientes publicados (decisión de implementación, QA de la fase A).
- **Inicialización en la migración:** cada secuencia arranca después del mayor sufijo numérico que sigue el patrón `^PREFIJO-[0-9]{1,18}$`. Se ignoran los códigos que no lo siguen: `TR-OTROS`, `CANC-OTRO`, `PRV-ABC` y los de pruebas como `TR-OFF` o `INS-S`. Así nada cambia ni se reutiliza.

| Prefijo | Tabla y columna | Ancho mínimo | Ejemplo siguiente |
|---|---|---|---|
| `TR` | `tipo_reparacion.codigo` | 3 | `TR-003` |
| `CANC` y `INT` | `motivo_operativo.codigo`, según el tipo | 3 | `CANC-001` |
| `INS` | `insumo.clave` (y `insumo.codigo`, D4) | 3 | `INS-002` |
| `PRV` | `proveedor.codigo` | 4 | `PRV-0002` |
| `CHK` | `checklist_pregunta.codigo` | 4 | `CHK-0004` |
| `SC`, `OC` y `RGA` | `solicitud_compra`, `orden_compra`, `reclamo_garantia` | 6 | `OC-000013` |

**Otras reglas:**
- `TR-OTROS` sigue reservado: el generador nunca produce sufijos que no sean números.
- **Inmutabilidad en la base:**
  - Un trigger nuevo, `rma.impedir_cambio_codigo()`, en `tipo_reparacion`, `motivo_operativo`, `plantilla_mensaje`, `proveedor`, `checklist_pregunta` y `mesa_trabajo`. Hoy solo lo impide el servicio.
  - El insumo ya está protegido por permisos de columna, y la OC y la SC por triggers.
  - No se modifica ningún identificador histórico.
- **Sin distinguir mayúsculas (D6):** índices únicos `upper(codigo)` en `tipo_reparacion`, y `upper(clave)` y `upper(codigo)` en `insumo`.
  - Motivos, proveedores, preguntas y plantillas ya exigen mayúsculas por CHECK, así que no necesitan índice.
  - Si hay choques, la migración **se detiene con la lista** y no corrige nada sola. Antes del UAT se corre una consulta de solo lectura (sección 11).
- **Sin restricciones nuevas de formato:** no se agregan CHECK que rompan los códigos existentes, ni columnas obligatorias (ajuste 7).

### 1.4 Contrato de la API

| Endpoint | Hoy | Propuesta |
|---|---|---|
| `POST /api/admin/repair-types` | `codigo` obligatorio | `codigo` **opcional**: si no viene se genera; si viene se respeta (validado y único sin distinguir mayúsculas) |
| `POST /api/admin/reasons` | `codigo` obligatorio | ídem, con prefijo según el tipo |
| `POST /api/admin/supplies` | `clave` y `codigo` obligatorios | los dos **opcionales**. Sin clave se genera `INS-NNN`; sin código se usa la clave |
| `PUT /api/admin/supplies/{clave}` | `codigo` obligatorio en el cuerpo, aunque no se puede cambiar | opcional y se ignora, como hoy en la práctica |
| `POST /api/admin/message-templates` | `codigo` obligatorio | **Sin cambios.** La interfaz deja de ofrecer el alta (CFG-08) |
| Altas de proveedor, solicitud, OC, reclamo y pregunta | ya automáticas | mismo contrato, generador nuevo |

- **El alta devuelve la entidad creada con su código.** La pantalla la agrega al listado y lo informa: «Se creó TR-003 Cambio de pantalla».
- **El código opcional se respeta por compatibilidad:**
  - el frontend publicado lo manda durante la publicación coordinada;
  - los scripts del UAT crean entidades con código fijo (`probar_macro_v14.py:796`);
  - hay pruebas existentes que lo usan.
- La pantalla nueva **no** lo envía (D4).

---

## 2. Matriz de permisos (CFG-02)

### 2.1 Cómo se aplica hoy

- **Modelo:** solo **rol → permiso**, con varios roles por usuario. Lo configurado se guarda en `rma.permiso`; sin fila rige el predeterminado del código. Cada cambio se audita en `cambio_configuracion`.
- **API:** `exigir_rol(permiso)` (`api/seguridad.py:123-140`). En modo demo no controla nada.
- **Servicio:** `validar_alguno_de(usuario, permiso)`, en los dos modos.
  - Las consultas se protegen solo en la API.
  - Los comandos de Órdenes y Compras, solo en el servicio.
- **No configurables:** `CONFIGURACION_ADMINISTRAR` y `ROLES_ADMINISTRAR`, los dos solo de Administración.
- **Frontend:**
  - lee `usuario.permisos` una vez al montar;
  - usa `puede(actor, permiso, rolesDeRespaldo)`;
  - **un cambio de permisos no se ve hasta recargar la página.**

### 2.2 Matriz

En la columna «Config.», «Sí» significa que se cambia desde la pantalla Permisos.

**Configuración y catálogos**

| Acción | Endpoint | Permiso actual | Roles | Config. | Se aplica en |
|---|---|---|---|---|---|
| Ver tipos y Mesas | `GET /api/admin/catalog` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API |
| Alta y edición de tipo, con precio | `POST/PUT /api/admin/repair-types` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Tipos habilitados por Mesa | `PUT /api/admin/stations/{c}/repair-types` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Motivos | `GET/POST/PUT /api/admin/reasons` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Insumos, con precio | `GET/POST/PUT /api/admin/supplies` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Proveedores | `GET/POST/PUT /api/admin/suppliers` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Plantillas | `GET/POST/PUT /api/admin/message-templates` | CONFIGURACION_ADMINISTRAR | ADMIN | No | **Solo servicio; la GET queda abierta** (brecha 8) |
| Preguntas de checklist | `POST/PUT /api/admin/checklist-questions` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Sincronizar tipos de equipo | `POST /api/admin/equipment-types/sync` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Parámetros (plazo de retiro) | `GET/PUT /api/admin/parameters` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Recargo por medio de pago | `GET/PUT /api/admin/payment-methods` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Auditoría | `GET /api/admin/config-changes` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API |
| Roles de un usuario | `PUT /api/admin/users/{c}/roles` | API: CONFIGURACION_ADMINISTRAR. Servicio: ROLES_ADMINISTRAR | ADMIN | No | Las dos capas, con permisos distintos (brecha 12) |
| Roles de un permiso | `PUT /api/admin/permissions/{c}` | ídem | ADMIN | No | Ídem. **Acepta una lista vacía** (brecha 14) |
| Sincronizar el catálogo de Ventas | `POST /api/catalogs/equipment/sync` | CATALOGO_EQUIPOS_SINCRONIZAR | ADMIN, COORD | Sí | API + servicio. Sin botón en la interfaz |
| Sincronizar Productos RT | `POST /api/rt-products/sync` | PRODUCTOS_RT_SINCRONIZAR | ADMIN | Sí | API + servicio |
| Limpiar fotos sin Orden | `POST /api/maintenance/photos/cleanup` | API: **rol fijo ADMIN**. Servicio: FOTOS_ADMINISTRAR | ADMIN | Solo en apariencia | Brecha 3 |

**Compras**

| Acción | Endpoint | Permiso actual | Roles | Config. | Se aplica en |
|---|---|---|---|---|---|
| Ver solicitudes, OC, sugerencias, costos y proveedores | `GET /api/purchases/*` | COMPRAS_CONSULTAR | RECEP, COORD, ADMIN | Sí | API |
| Crear y descartar solicitudes | `POST /api/purchases/requests[/{id}/discard]` | COMPRAS_GESTIONAR | RECEP, COORD, ADMIN | Sí | Servicio (`services/compras.py:107,136`) |
| **Crear OC** | `POST /api/purchases/orders` | COMPRAS_GESTIONAR | ídem | Sí | Servicio (`:199`) |
| Confirmar OC | `POST /orders/{id}/confirm` | COMPRAS_GESTIONAR | ídem | Sí | Servicio (`:251`) |
| Cancelar OC (en borrador o confirmada sin recepciones) | `POST /orders/{id}/cancel` | COMPRAS_GESTIONAR | ídem | Sí | Servicio (`:264`) |
| Recibir (ingresa stock, lote y costo) | `POST /orders/{id}/receipts` | COMPRAS_GESTIONAR, **sin STOCK_GESTIONAR** | ídem | Sí | Servicio (`:297`) |
| Proveedores | `/api/admin/suppliers` | CONFIGURACION_ADMINISTRAR | ADMIN | **No** | API + servicio |

**Por qué hoy no se puede configurar quién crea OC.** El permiso existe y se puede cambiar por rol, pero en la práctica no alcanza:

1. Cubre seis acciones juntas.
2. Se asigna por rol, no por persona.
3. Está en el grupo «Inventario y catálogos» y su descripción no dice «crear».
4. Sin `COMPRAS_CONSULTAR` la sección no aparece.
5. Sin proveedor no hay OC, y los proveedores son solo de Administración.
6. El cambio no se ve hasta recargar la página.

**Inventario**

| Acción | Endpoint | Permiso | Roles | Config. | Se aplica en |
|---|---|---|---|---|---|
| Consultar inventario, movimientos y lotes | `GET /api/inventory/*` | INVENTARIO_CONSULTAR | todos | Sí | API |
| Ingreso y ajuste manual | `POST /api/inventory/{id}/receipts`, `/adjustments` | STOCK_GESTIONAR | ADMIN, COORD | Sí | API + servicio |
| Revalidar recursos | `POST /api/inventory/revalidate-orders` | RECURSOS_REVALIDAR | ADMIN, COORD | Sí | API + servicio |
| Devolver un consumo | `POST /api/orders/{id}/consumptions/{c}/return` | DEVOLUCION_STOCK | ADMIN, COORD | Sí | Servicio |

**Órdenes (66 rutas).**
- Las consultas exigen `ORDENES_CONSULTAR` en la API.
- Cada comando tiene su permiso configurable en el servicio.
- El anexo A lo detalla ruta por ruta, con las excepciones: roles fijos, rutas sin usuario y acciones que exigen varios permisos.

**Consultas y otras**

| Acción | Endpoint | Permiso | Se aplica en |
|---|---|---|---|
| Reportes | `GET /api/reports/operational` | REPORTES_CONSULTAR | API |
| Antecedentes | `GET /api/equipment/history`, `/identify` | ANTECEDENTES_CONSULTAR | API |
| Reclamos rechazados | `GET /api/warranty-claims` | RECLAMOS_CONSULTAR | API |
| Buscar cliente | `GET /api/clients/lookup` | CLIENTE_BUSCAR | API + servicio |
| Productos RT | `GET /api/rt-products` | PRODUCTOS_RT_CONSULTAR | API |
| Bandejas | `GET /api/work/*` | **solo la sesión**; el contenido depende del rol fijo | — |
| Usuarios con roles y permisos | `GET /api/catalogs/users` | **solo la sesión** | — |

### 2.3 Brechas

**Prioridad:**
- **A:** crítica, se corrige en esta iteración.
- **B:** bajo costo, también se corrige ahora (D8).
- **C:** se registra en `DEUDA_TECNICA.md`.

| # | Brecha | Dónde | Prio. | Corrección |
|---|---|---|---|---|
| 1 | Enviar a revisión usa el **rol fijo RECEPCION**, no `ENVIAR_A_REVISION` | `services/ordenes.py:665,685` | A | Usar el permiso. Su predeterminado es RECEP, así que nada cambia |
| 2 | La garantía RMA sin excepción exige el **rol fijo RECEPCION** además de `GARANTIA_RMA_CREAR` | `application/ingreso.py:457-462` | A | Solo el permiso, después de verificar en `business/` que no es una regla deliberada |
| 3 | La limpieza de fotos tiene el **rol fijo ADMIN** en la API y `FOTOS_ADMINISTRAR` en el servicio | `api/mantenimiento.py:33` | A | `exigir_rol(FOTOS_ADMINISTRAR)` |
| 4 | Toda la administración de catálogos depende de un permiso **no configurable** | `api/configuracion.py:63-66`, `api/compras.py:59` | A | Sección 3.2 |
| 5 | `COMPRAS_GESTIONAR` agrupa seis acciones | `services/compras.py:107-297` | A | Sección 3.3 |
| 6 | La recepción de compra ingresa stock sin `STOCK_GESTIONAR` | `application/compras.py:349` | C | Es deliberado (DEC-MI-09); se documenta |
| 7 | Gestionar sin consultar deja Compras invisible | `PanelOrdenes.tsx:800`, `api/compras.py:58` | A | Dependencias (3.4) |
| 8 | Plantillas sin `exigir_rol` | `api/comunicaciones.py:194,199,211` | A | `exigir_rol(PLANTILLA_GESTIONAR)` |
| 9 | Mensaje preparado, consentimientos y bandejas sin `ORDENES_CONSULTAR` | `api/comunicaciones.py:112,161`, `api/trabajo.py:20,29` | B | Agregar el `exigir_rol` |
| 10 | Ver fotos y firmas exige el permiso de **carga** | `api/ordenes.py:1602`, `api/firmas.py:28` | B | `ORDENES_CONSULTAR` |
| 11 | Rutas que cambian estado sin usuario (esperar y revalidar recursos, informar a RT) | `api/ordenes.py:751,765,1667` | C | Análisis aparte: son eventos de sistema |
| 12 | Usuarios y permisos usan un permiso en la API y otro en el servicio | `api/configuracion.py:66`, `services/roles.py:65,105` | B | `exigir_rol(ROLES_ADMINISTRAR)` |
| 13 | La sincronización de Tipos de Equipo usa un permiso fijo; las análogas, uno configurable | `application/checklist.py:116` | A | `CHECKLIST_GESTIONAR` |
| 14 | `PUT /permissions` acepta cero roles | `services/roles.py:104-116` | B | Rechazarlo en el servicio |
| 15 | Acciones que exigen varios permisos | anexo A | B | Nota «también requiere …» en la pantalla Permisos |
| 16 | Bandejas y responsable de la situación por rol fijo | `application/bandejas.py:845-850`, `situacion.py:900` | C | Son vistas por puesto, no acciones |
| 17 | Modo demo sin control en las consultas | `api/seguridad.py:134` | C | Es por diseño; Cloud Run lo bloquea |
| 18 | **Frontend:** Configuración por rol fijo ADMIN; crear Orden por rol fijo RECEPCION, aunque `ORDEN_CREAR` es configurable | `Configuracion.tsx:304`, `PanelOrdenes.tsx:799`, `ListadoOrdenes.tsx:943,1095` | A | `puede(...)` con el permiso |
| 19 | **Frontend:** el rol de respaldo `"ADMINISTRACION"` no existe | `RetiroDemorado.tsx:37` | B | Se elimina junto con los respaldos (sección 8) |
| 20 | **Frontend:** los permisos no se refrescan | `PanelOrdenes.tsx:268-302` | A | Volver a pedir el usuario después de cambiar roles o permisos |
| 21 | `GET /api/catalogs/users` expone los permisos de todos | `api/catalogos.py:51` | C | Separar «mis permisos» del selector de demo |
| 22 | Descripciones inexactas (`CUSTODIA`, `ENVIAR_A_REVISION`) | `permisos.py:352` | B | Corregir los textos |
| 23 | **Frontend:** Inventario y Reportes no se controlan en el menú (el backend sí responde 403) | `layout.tsx:46-75` | B | Controlar por `INVENTARIO_CONSULTAR` y `REPORTES_CONSULTAR` |

---

## 3. Permisos operativos (CFG-03)

### 3.1 Principios

1. **Nadie gana acceso sin una decisión de Administración (D2).** Los permisos nuevos de catálogos empiezan solo con Administración, que después los extiende desde Permisos. La división de un permiso existente hereda sus roles vigentes (DF-4), así nadie pierde un acceso.
2. **Lo sensible queda fijo para Administración.**
   - `ROLES_ADMINISTRAR`: usuarios, roles y la matriz de permisos.
   - `CONFIGURACION_ADMINISTRAR`: parámetros del sistema, recargos por medio de pago y la auditoría completa.
3. **Un permiso por catálogo, con alta y edición juntas.** La excepción es el precio (D3).
4. **Cada permiso se aplica en las dos capas:** la API (`exigir_rol`) y el servicio (`validar_alguno_de`).

### 3.2 Catálogos: grupo nuevo «Configuración operativa»

| Permiso | Cubre | Predeterminado |
|---|---|---|
| `TIPO_REPARACION_GESTIONAR` | Alta de tipo; nombre, puntaje, plazos de garantía y vigencia | ADMIN |
| `PRECIOS_GESTIONAR` | Precio de tipos e insumos, en el alta y en la edición | ADMIN |
| `MESA_TIPOS_GESTIONAR` | Tipos habilitados por Mesa | ADMIN |
| `MOTIVO_GESTIONAR` | Motivos de cancelación e interrupción | ADMIN |
| `INSUMO_GESTIONAR` | Alta de insumo; nombre, unidad, control por lote y vigencia | ADMIN |
| `PLANTILLA_GESTIONAR` | Texto y vigencia de las plantillas visibles | ADMIN |
| `CHECKLIST_GESTIONAR` | Preguntas del checklist y sincronización de Tipos de Equipo | ADMIN |

**Precio (D3):**
- **Alta de tipo de reparación:** exige `TIPO_REPARACION_GESTIONAR` **y** `PRECIOS_GESTIONAR`, porque el precio es obligatorio.
- **Alta de insumo:** el precio es opcional. Con solo `INSUMO_GESTIONAR` se crea sin precio, y quien tenga `PRECIOS_GESTIONAR` lo completa después.
- **Quien gestiona un catálogo ve los precios en solo lectura.**

**Lectura y auditoría:**
- El GET de cada catálogo de administración exige su permiso de gestión.
- Los selectores operativos (`/api/catalogs/*`) no cambian.
- Cada subsección muestra su propio historial: `cambio_configuracion` filtrado por entidad.
- La auditoría completa sigue siendo de Administración.

### 3.3 Compras: grupo nuevo «Compras» (D5)

| Permiso | Cubre | Predeterminado |
|---|---|---|
| `COMPRAS_CONSULTAR` (existe) | Ver la sección | RECEP, COORD, ADMIN (sin cambios) |
| `COMPRA_SOLICITAR` | Crear y descartar solicitudes | roles vigentes de `COMPRAS_GESTIONAR` (DF-4) |
| `OC_CREAR` | Crear OC en borrador y cancelar un **borrador** | ídem |
| `OC_CONFIRMAR` | Confirmar una OC | ídem |
| `OC_CANCELAR` | Cancelar una OC **confirmada** (y cualquier borrador) | ídem |
| `COMPRA_RECIBIR` | Registrar recepciones (ingresan stock) | ídem |
| `PROVEEDOR_GESTIONAR` | Alta y edición de proveedores | ADMIN (como hoy) |

**Evaluación de confirmar y cancelar (D5): se recomienda separarlos.**
- **Confirmar** compromete la compra con el proveedor y deja la OC lista para recibir.
- **Cancelar una OC confirmada** deshace ese compromiso. Es una decisión de otra naturaleza, y conviene poder reservarla a quien gestiona la relación con el proveedor.
- **Cancelar un borrador** no tiene efecto externo. Quien lo creó tiene que poder descartarlo aunque no pueda cancelar OC confirmadas; por eso `OC_CREAR` también alcanza para un borrador.
- La regla queda en el servicio, según el estado de la OC (DF-5).

**Migración de lo configurado:**
- Si `rma.permiso` tiene una fila de `COMPRAS_GESTIONAR`, se copia a los cinco permisos nuevos, con su auditoría.
- La fila original se **conserva**, para que un backend anterior siga funcionando si hay vuelta atrás.

**Compatibilidad del frontend anterior:**
- `permisos_de(usuario)` sigue informando el código `COMPRAS_GESTIONAR` como alias de lectura cuando el usuario tiene `OC_CREAR`. Así el frontend publicado no oculta los botones de Compras durante la publicación coordinada.
- El alias no se muestra en la pantalla Permisos y no se configura.

### 3.4 Dependencias entre permisos

Cada `Permiso` declara los permisos que **requiere**:

| Permiso | Requiere |
|---|---|
| Los de Compras | `COMPRAS_CONSULTAR` |
| `INSUMO_GESTIONAR` | `INVENTARIO_CONSULTAR` |
| `PRECIOS_GESTIONAR` | ninguno (se usa junto con el de su catálogo) |

**Cómo se aplican:**
- **Pantalla Permisos:** al marcar un rol en una acción, también se marca su consulta. Si se quiere quitar una consulta de la que depende otra acción del mismo rol, aparece un aviso.
- **Backend:** `PUT /permissions` rechaza con 409 un cambio que deje a un rol con una acción sin su consulta, con el motivo. También rechaza una lista de roles vacía (brecha 14).

---

## 4. Formularios y navegación (CFG-04 y CFG-05)

### 4.1 Alta y edición

```text
┌ Insumos ───────────────────────────── [ + Nuevo insumo ] ┐
│ Buscar…                                                   │
│ INS-014  Batería iPhone 14   unidad   Lote ✓  $ 25.000  ✎ │
└───────────────────────────────────────────────────────────┘
          ┌ Nuevo insumo ─────────────────── ✕ ┐
          │ Nombre*          [               ]  │
          │ Unidad           [ unidad        ]  │
          │ Control por lote [ ]                │
          │ Precio           [               ]  │ ← editable solo con PRECIOS_GESTIONAR
          │ El código se asigna al guardar.     │
          │             [Cancelar] [Crear insumo]│
          └─────────────────────────────────────┘
```

**Comportamiento:**
- **El botón «+ Nuevo …»** va en el encabezado del listado y solo aparece con el permiso.
- **El modal** reutiliza `Modal` con el patrón de Inventario:
  - se cierra solo si el alta salió bien;
  - si falla, muestra el error adentro y conserva lo escrito;
  - pone el foco en el primer campo y se cierra con Escape.
- **No hay campos de código (D4).** La confirmación informa el código asignado.
- **Se actualiza solo el listado afectado:** la entidad que devuelve el POST se agrega a la lista y su fila queda resaltada. No se pide de nuevo el catálogo completo ni la auditoría.
- **La edición también usa el modal** (✎). Los interruptores de una sola acción (vigente, control por lote) siguen en la fila.
- **Se corrigen dos errores actuales:**
  - el alta de insumo vacía el formulario aunque falle (`Insumos.tsx:210`);
  - el alta de tipo no se limpia al terminar.

**Campos del modal:**

| Catálogo | Campos del modal |
|---|---|
| Tipo de reparación | Nombre, precio, puntaje, **garantía con check-in y sin check-in** (CFG-06) y Mesas habilitadas (opcional) |
| Motivo | Tipo (Cancelación o Interrupción), nombre y «exige descripción» |
| Insumo | Nombre, unidad, control por lote y precio |
| Proveedor | Los campos actuales |
| Pregunta de checklist | Tipo de equipo, texto y opciones |
| Plantilla | Solo edición: nombre, texto y vigencia (CFG-08) |

**Piezas compartidas nuevas:** `FormularioModal`, el hook `useComando` (unifica `error`, `aviso`, `ocupado` y `ejecutar`) y `Pestanas`.

### 4.2 Estructura de Configuración

| Grupo | Subsección | Permiso | Ruta |
|---|---|---|---|
| Taller | Tipos de reparación | TIPO_REPARACION_GESTIONAR | `#/configuracion/tipos-reparacion` |
| Taller | Mesas de trabajo | MESA_TIPOS_GESTIONAR | `#/configuracion/mesas` |
| Taller | Motivos | MOTIVO_GESTIONAR | `#/configuracion/motivos` |
| Taller | Checklist | CHECKLIST_GESTIONAR | `#/configuracion/checklist` |
| Inventario y compras | Insumos | INSUMO_GESTIONAR | `#/configuracion/insumos` |
| Inventario y compras | Proveedores | PROVEEDOR_GESTIONAR | `#/configuracion/proveedores` |
| Comunicación | Plantillas de WhatsApp | PLANTILLA_GESTIONAR | `#/configuracion/plantillas` |
| Sistema | Usuarios y roles; Permisos | ROLES_ADMINISTRAR | `#/configuracion/usuarios`, `/permisos` |
| Sistema | Recargos por medio de pago; Auditoría | CONFIGURACION_ADMINISTRAR | `#/configuracion/recargos`, `/auditoria` |

- **Menú:** Configuración aparece si el usuario tiene al menos uno de esos permisos.
- **`#/configuracion`** lleva a la primera subsección permitida.
- **Subsección sin permiso:** muestra «No tenés permiso para …». El backend igual responde 403.
- **Pantalla Permisos:**
  - grupos «Compras» y «Configuración operativa»;
  - dependencias marcadas;
  - nota «también requiere …» en las acciones compuestas;
  - descripciones corregidas.
- **Después de guardar roles o permisos** se refrescan los permisos del usuario actual (brecha 20).

---

## 5. Garantías del tipo de reparación (CFG-06)

### 5.1 Situación actual

El tipo tiene tres plazos y una política, y la pantalla muestra los cuatro (`Configuracion.tsx:172-220`):

| Campo | Etiqueta actual | Cuándo rige (`domain/garantia.py:23-43`) |
|---|---|---|
| `garantia_con_checkin` | «Garantía con check-in realizado» | Check-in de entrega realizado |
| `garantia_sin_checkin` | «Garantía con check-in no realizado» | Check-in registrado como no realizado |
| `garantia_dias` | «Garantía sin check-in exigible» | **Sin check-in registrado:** RT interno, garantía RMA y la asignación provisoria hasta el check-in. También es el plazo de la política RMA `NUEVO_PLAZO` o sin definir (`services/documentos.py:181-215`). La regla funcional está abierta (ABI-39) |
| `politica_garantia_rma` | «Trabajos hechos dentro de una garantía RMA» | Garantía de un trabajo hecho dentro de una garantía RMA. La inicial está abierta (ABI-38) |

### 5.2 Propuesta

- **La pantalla** (listado y modal) muestra solo **«Garantía con check-in (días)»** y **«Garantía sin check-in (días)»**.
- **`garantia_dias` y `politica_garantia_rma` siguen en la base y en el backend.** No se borran ni se cambian los valores existentes (ajuste 8). Los Detalles guardan su propia copia, así que lo histórico no se toca.
- **`garantia_dias` en la API:** pasa a ser opcional. Si no viene:
  - **en el alta** toma el plazo **con check-in**: el seed tiene `garantia_dias = 90 = con check-in`, así que repite el comportamiento actual;
  - **en la edición** se conserva el valor del Tipo (DF-1 aprobado: «conservar los valores existentes»).

  Si viene, porque lo manda el frontend anterior o un script, se respeta.
- **`politica_garantia_rma` en la API:** pasa a ser opcional. Si no viene, se conserva el valor guardado; en un alta queda vacía, que es el comportamiento vigente (DF-2).
- **Antes del UAT** se corre una consulta de solo lectura que lista los tipos cuyo `garantia_dias` difiere de `garantia_con_checkin`, o que tienen política RMA definida. Así la decisión DF-1 se toma con los datos reales.

---

## 6. Plazo de retiro y plantillas (CFG-07 y CFG-08)

### 6.1 Plazo de retiro (CFG-07)

- `PLAZO_RETIRO_DIAS` define cuándo un retiro pasa a «demorado» en las bandejas y en la Orden (`application/operativa.py:96`, `bandejas.py:195`). Vale 30 por defecto.
- **Se quita de la interfaz.** La subsección «Parámetros» pasa a ser «Recargos por medio de pago».
- **Se conserva** el parámetro en la base con su valor actual, su lectura y su efecto en el backend. También el endpoint `GET/PUT /api/admin/parameters`, que queda sin pantalla y solo para Administración.
- No se cambia ningún valor (ajuste 8).

### 6.2 Plantillas de WhatsApp (CFG-08)

**Hoy hay cinco plantillas:** `INGRESO`, `AUTORIZACION_PENDIENTE`, `LISTO_PARA_RETIRAR`, `RECORDATORIO_RETIRO` y `GARANTIA`. La Orden ofrece todas las activas (`ComunicacionesOrden.tsx:60-61`).

**Propuesta:**
- **Lista de plantillas visibles en el backend** (`PLANTILLAS_VISIBLES`, en el dominio): **`INGRESO` y `LISTO_PARA_RETIRAR`** (DF-3).
- **La API agrega `visible: bool`** a cada plantilla. El frontend nuevo muestra solo las visibles. El anterior ignora el campo y sigue mostrando todas (compatibilidad).
- **Dónde se aplica:**
  - en Configuración, con edición de texto y vigencia, sin alta de plantillas nuevas;
  - en el selector de la Orden (DF-3 aprobada).
- **No se desactiva ni se borra ninguna plantilla** (ajuste 8).
- **Historia:** las comunicaciones ya registradas guardan su texto (`comunicacion_cliente.mensaje`, inmutable), así que su historial se sigue viendo completo.
- **Endpoints:** el POST de alta queda solo en la API, para compatibilidad. Preparar un mensaje con una plantilla oculta sigue funcionando en el backend; solo deja de ofrecerse en pantalla.

---

## 7. Cambios de base de datos

Dos migraciones aditivas, posteriores a la de Reparación RT: `20261120000100_codigos_automaticos.sql` (puntos 1 a 3) y `20261120000200_permisos_operativos.sql` (punto 4). Las secuencias permiten huecos (ajuste 1), en lugar del contador sin huecos descrito arriba:

1. **Secuencias** `rma.codigo_*_seq`, inicializadas desde los máximos numéricos (1.3), y la función `rma.siguiente_codigo(prefijo)`.
   - `rma_backend` recibe `usage` sobre las secuencias y `execute` sobre la función.
   - Se revocan para `public`, `anon`, `authenticated` y `service_role`.
2. **Trigger** `rma.impedir_cambio_codigo()` en seis tablas.
3. **Índices únicos sin distinguir mayúsculas** en `tipo_reparacion` e `insumo`, con una verificación previa que aborta y lista los choques.
4. **Copia** de la fila de `COMPRAS_GESTIONAR` de `rma.permiso` a los cinco permisos nuevos, con una fila de auditoría. Nada se borra.
5. **Sin cambios** en:
   - columnas y tablas de operación;
   - parámetros y plantillas;
   - `garantia_dias` y la política RMA;
   - los formatos de `nuevo_id`.
6. **Inventario de objetos:**
   - no cambia la cantidad de tablas (72), porque no hay tablas nuevas;
   - `supabase/tests/10_esquema.sql` incorpora las secuencias, la función y los triggers;
   - el reinicio del UAT (`01_reiniciar.sql`) reinicia solo `codigo_sc_seq`, `codigo_oc_seq` y `codigo_rga_seq`, porque vacía esas tablas; las de los catálogos (maestras) se conservan. La línea de base y la limpieza de los E2E restauran todas.

---

## 8. Verificación de cada permiso en el backend y el frontend

**Backend: prueba de matriz de rutas** (`tests/test_matriz_permisos.py`)
- Recorre `app.routes` y exige que **cada** ruta esté clasificada en una tabla de la prueba: su permiso o una excepción justificada (pública, solo sesión, evento de sistema).
- Una ruta nueva sin clasificar hace fallar la prueba, así que es un control permanente.
- Para cada ruta con permiso, contra PostgreSQL y con JWT real:
  - un rol sin el permiso recibe 403 **en la API**;
  - el servicio también lo rechaza cuando se lo invoca directo;
  - un rol con el permiso pasa.
- Se repite con una política reconfigurada: el permiso dado a otro rol rige desde el pedido siguiente.

**Frontend: prueba estática de controles**
- Ningún `tieneRol(...)` se usa para habilitar acciones. Las excepciones quedan listadas, por ejemplo el selector de demo.
- Todo código usado en `puede(actor, "X")` existe en el registro del backend. Se compara con una lista exportada por el backend en la prueba.
- Cada sección del menú y cada subsección de Configuración declara su permiso.
- Los respaldos por rol de `puede()` se conservan solo para una API sin lista de permisos (el backend nuevo siempre la manda). El rol inexistente `"ADMINISTRACION"` se corrigió (brecha 19).

**Recorrido en el navegador:** los cuatro roles y un rol con permisos reconfigurados, que debe ver exactamente lo que el backend le permite.

---

## 9. Compatibilidad

| Caso | Cómo se garantiza | Cómo se prueba |
|---|---|---|
| El frontend publicado manda códigos y `garantia_dias` en las altas | Son opcionales y, si vienen, se respetan | Pruebas de contrato con el cuerpo anterior |
| El frontend publicado usa `COMPRAS_GESTIONAR` | Alias de lectura en `permisos_de` | Prueba de contrato |
| El backend publicado (vuelta atrás) sobre la base migrada | La migración solo agrega; la fila de `COMPRAS_GESTIONAR` se conserva; las secuencias no molestan al `max()+1` anterior | Ensayo local con el backend publicado, igual que en Reparación RT |
| Vuelta al backend nuevo después de altas hechas por el anterior | El generador saltea los códigos que ya existen | Prueba: códigos creados «por fuera» y luego altas nuevas |
| Scripts del UAT con códigos fijos (`probar_macro_v14.py`) | Código opcional respetado | Se corren sin cambios |
| Pruebas que esperan formatos (`PRV-0001`, `RGA-000001`) y códigos tipeados (`TR-OFF`, `INS-S`) | Formatos iguales; código informado respetado | Las suites existentes sin cambios de expectativas |
| Datos históricos: Detalles, comunicaciones, auditoría | No se reescribe nada; los Detalles y las comunicaciones guardan sus copias | Pruebas de lectura sobre datos anteriores |
| Ruta `#/configuracion` | Sigue siendo válida y redirige | `rutas.test.ts` actualizado |

---

## 10. Decisiones funcionales necesarias antes de programar

| # | Decisión | Opciones | Recomendación |
|---|---|---|---|
| DF-1 | Valor del plazo oculto `garantia_dias`: rige sin check-in registrado, es decir en RT interno, garantía RMA y la asignación provisoria | a) igual a «con check-in»; b) igual a «sin check-in»; c) conservar el valor y no tocarlo en la edición | **Aprobado (19/11/2026):** conservar los existentes; en el alta, el valor de con check-in |
| DF-2 | Política de garantía RMA del tipo | a) ocultarla y conservar los valores; b) seguir mostrándola | **Aprobado:** a), conservando la información y las reglas actuales |
| DF-3 | Qué plantillas son «ingreso y retiro», y dónde se ocultan las demás | Plantillas: `INGRESO` + `LISTO_PARA_RETIRAR`, o sumar `RECORDATORIO_RETIRO`. Lugar: solo Configuración, o también el selector de la Orden | **Aprobado:** `INGRESO` y `LISTO_PARA_RETIRAR`, en Configuración y en la Orden; sin `RECORDATORIO_RETIRO`; nada se borra ni se desactiva |
| DF-4 | Roles iniciales de los permisos que resultan de dividir `COMPRAS_GESTIONAR` | a) heredan sus roles vigentes (RECEP, COORD, ADMIN); b) solo ADMIN, como D2 | **Aprobado:** a), sin quitar accesos existentes |
| DF-5 | Cancelación de OC | a) `OC_CANCELAR` para confirmadas y `OC_CREAR` también alcanza para un borrador; b) `OC_CANCELAR` para todo; c) junto con confirmar | **Aprobado:** a), con los controles desde el backend |

---

## 11. Plan de implementación (CFG-01 a CFG-08)

**Cómo se trabaja:**
- Rama `feat/configuracion-v2`.
- Cada fase pasa por implementación, pruebas, QA independiente, correcciones y commits locales.
- Sin push, merge ni UAT.
- Pruebas focalizadas durante el desarrollo; la suite `tests/postgres` completa, al cierre.

### Fase A: generador e identificadores (CFG-01 y D6)

1. La migración: secuencias, función, triggers, índices sin distinguir mayúsculas y su verificación previa.
2. `siguiente_codigo` en el repositorio, con salto de los códigos existentes, reintento de las altas con código generado y 409 `PRECONDICION_INVALIDA` ante un duplicado.
3. Altas de tipo, motivo e insumo con código opcional. Proveedor, SC, OC, RGA y CHK pasan al generador.
4. **Pruebas:**
   - altas concurrentes en dos conexiones;
   - la reversión no repite códigos;
   - se saltean los códigos cargados por fuera;
   - `PRV-9999` → `PRV-10000`;
   - se ignoran los códigos no numéricos;
   - `TR-OTROS` sigue reservado;
   - la base rechaza cambiar un código;
   - `tr-010` frente a `TR-010`;
   - la migración aborta si hay choques.

### Fase B: permisos en el backend (CFG-02 y CFG-03)

1. Permisos de catálogos, precio y Compras; dependencias; alias `COMPRAS_GESTIONAR`; copia de lo configurado.
2. Cada router con su `exigir_rol` y cada servicio con su `validar_alguno_de`, incluida la regla de cancelación por estado (DF-5).
3. Brechas A y B del backend: 1, 2, 3, 8, 9, 10, 12, 13, 14, 22.
4. **Pruebas:** la matriz de rutas (sección 8), reconfiguración y vuelta atrás con la fila anterior.

### Fase C: garantías, plazo de retiro y plantillas en el backend (CFG-06, CFG-07 y CFG-08)

1. `garantia_dias` y `politica_garantia_rma` opcionales, con las reglas de DF-1 y DF-2.
2. El campo `visible` de las plantillas según DF-3.
3. **Pruebas:**
   - cuerpo anterior y cuerpo nuevo;
   - los Detalles históricos no cambian;
   - el plazo de retiro sigue rigiendo en las bandejas;
   - una plantilla oculta sigue funcionando por API.

### Fase D: frontend (CFG-04, CFG-05 y la parte visible de CFG-06 a CFG-08)

1. `FormularioModal`, `useComando` y `Pestanas`.
2. Configuración por subsecciones con rutas y permisos; menú controlado por permisos; se quitan los respaldos por rol.
3. Modales de alta y edición de los seis catálogos, sin campos de código, con el listado actualizado en el lugar.
4. Garantías con dos plazos, sin el plazo de retiro, y plantillas filtradas en Configuración y en la Orden.
5. Pantalla Permisos con grupos, dependencias y refresco de los permisos propios.
6. Crear Orden controlado por `ORDEN_CREAR`.
7. **Pruebas:**
   - prueba estática de controles (sección 8);
   - rutas y lógica de dependencias;
   - recorrido en el navegador con los cuatro roles y un rol reconfigurado, en escritorio y a 390 px.

### Fase E: compatibilidad y cierre

1. Suites completas: backend, `tests/postgres`, frontend y build.
2. **Ensayo de compatibilidad local:**
   - backend publicado sobre la base migrada;
   - frontend publicado contra el backend nuevo, con pruebas de contrato;
   - vuelta al backend nuevo después de altas hechas por el anterior;
   - scripts de UAT existentes.
3. QA independiente de toda la iteración.
4. **Documentación:**
   - este documento;
   - `contratos-macro-integral.md` (permisos);
   - `DEUDA_TECNICA.md` (brechas C);
   - `pendientes-producto.md` (jerarquía de insumos);
   - `ESTADO_PROYECTO.md`;
   - un procedimiento de UAT con las consultas previas de solo lectura: choques de mayúsculas (D6), plazos de garantía (DF-1) y filas de `rma.permiso`.

**Mejora futura de insumos (no se implementa).**
- Alcance: categorías, subcategorías, productos, tipos de insumo y compatibilidad de un insumo con varios modelos de equipo.
- Este diseño no la impide: el insumo conserva su `uuid` y su `clave`, y la compatibilidad sería una tabla `insumo_modelo_equipo` nueva.

---

## 12. Implementación (19/11/2026)

Rama `feat/configuracion-v2`, desde `feat/reparacion-rt-etapa1` (`f3036ca`). Commits locales, sin push, sin integrar y sin cambios en el UAT, Gestión RT ni `main`.

| Fase | Commit | Contenido |
|---|---|---|
| Discovery y diseño | `109666b`, `1b79802` | Este documento |
| A. Códigos automáticos (CFG-01, D6) | `1d59a83` | Migración `20261120000100`; generador en la base; códigos opcionales en la API; 409 en vez de 500 |
| B. Permisos (CFG-02, CFG-03) | `8c3bdcd` | Permisos de catálogos y de Compras; dependencias; migración `20261120000200`; matriz de rutas |
| C. Garantías, plazo de retiro y plantillas (CFG-06 a CFG-08) | `6683bcf` | Plazos opcionales que se conservan; `visible` en plantillas |
| D. Frontend (CFG-03 a CFG-08) | `928012c` | Configuración por funcionalidad, altas en ventana, Compras por acción, Permisos con dependencias |
| E. Compatibilidad y cierre | este commit | Ensayo de compatibilidad, consultas previas, documentación |

**Decisiones de implementación** (dentro de lo aprobado):

- **Errores de duplicado:** 409 con el código `PRECONDICION_INVALIDA` que estas altas ya devolvían, no un código nuevo, para no cambiar el contrato de los clientes publicados.
- **Dos migraciones**, una por fase, en lugar de una.
- **Secuencias con huecos** (ajuste 1). Un alta con código generado que choca con uno cargado en paralelo se reintenta; uno informado por el cliente responde 409.
- **Permiso antes del código:** un rechazo por permiso no consume números.
- **Escritura de insumos y tipos:** exige el permiso del catálogo. `PRECIOS_GESTIONAR` se suma para fijar o cambiar el precio; quien gestiona el catálogo ve el precio en solo lectura. Los precios con más de dos decimales se rechazan, porque la base los redondearía sin pasar por el permiso.
- **Garantías:** un plazo enviado en null también se conserva; la política enviada en null es «sin definir», como antes.
- **Respaldos por rol de `puede()`:** se conservan solo para una API sin lista de permisos.
- **Reinicio del UAT:** reinicia también las secuencias de SC, OC y RGA.

**Pruebas:**

| Suite | Resultado |
|---|---|
| Backend sin PostgreSQL (árbol final) | 2022 pasadas, 29 salteadas, 0 fallas; `ruff check` limpio |
| `tests/postgres` completa | 569 pasadas, 0 fallas |
| Frontend | `tsc` sin errores, 197 pruebas, build correcto |
| Ensayo de compatibilidad `ensayar_configuracion_v2.py --anterior fd434ef` | 24 de 24 |
| Ensayo de Reparación RT sobre las 42 migraciones | 21 de 21 |
| Recorrido en el navegador (Administración, Recepción con insumos delegados, Técnico; escritorio y 390 px) | Sin desbordes; altas sin código; dependencias; secciones por permiso |

**QA independiente:** una por fase y una integral. Ninguna encontró hallazgos bloqueantes ni mayores. Se corrigieron todos los menores:

- A: 3;
- B: 2;
- C: 1, más una prueba;
- D: 3;
- integral: 5, de documentación.

**Riesgos y pendientes:**

- **Vuelta atrás conjunta:** backend y frontend se vuelven atrás juntos. Lo cambiado en Compras con los permisos nuevos no llega a la fila de `COMPRAS_GESTIONAR` ([`DEUDA_TECNICA.md`](DEUDA_TECNICA.md), P1-17).
- **Brechas C registradas** en P1-16.
- **Mejoras de pantalla fuera de alcance** en P2-19.
- **Jerarquía de insumos:** queda para más adelante ([`pendientes-producto.md`](pendientes-producto.md), P-07).
- **Trazabilidad:** las decisiones D1 a D8 y DF-1 a DF-5 están en este documento. Si negocio las quiere en `business/` (fuente `rt-rma-app`), hay que registrarlas allí como DEC-CFG.
- **Antes de migrar el UAT:** las consultas de [`precheck_configuracion_v2.sql`](../supabase/scripts/validacion_uat/precheck_configuracion_v2.sql), según [`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), sección 12.

## Anexo A. Órdenes: permiso de cada comando

| Ruta (`/api/orders/...`) | Permiso en el servicio |
|---|---|
| `POST ""`, `/rt-interno` | ORDEN_CREAR (+ DETALLE_DEFINIR_RECEPCION si hay trabajo inicial) |
| `/details`, `/definition/finalize` | DETALLE_DEFINIR_RECEPCION o DETALLE_DEFINIR_TECNICO según el estado |
| `/warranty-rma` | GARANTIA_RMA_CREAR o GARANTIA_EXCEPCION, **más el rol fijo RECEPCION** sin excepción (brecha 2) |
| `/send-to-review` | **rol fijo RECEPCION** (brecha 1) |
| `/review/without-repair` | ENVIAR_A_REVISION |
| `/technical-review` | REVISION_TECNICA |
| `/review/details`, `/details/{d}/technical-review`, `/redefine` | DETALLE_DEFINIR_TECNICO |
| `/details/{d}/resources/override` | RECURSOS_OVERRIDE |
| `/resources/wait`, `/resources/revalidate`, `/inform-rt` | **ninguno: sin usuario** (brecha 11) |
| `/queue` | PRIORIDAD_DEFINIR |
| `/priority` | PRIORIDAD_CAMBIAR |
| `/take`, `/details/{d}/start` | ORDEN_TOMAR |
| `/release` | ORDEN_TOMAR (la propia) o LIBERACION_AJENA |
| `/details/{d}/evaluation` | EVALUACION_TECNICA + ORDEN_TOMAR (+ DETALLE_ADICIONAL) |
| `/details/additional` | DETALLE_ADICIONAL |
| `/executions/{e}/complete`, `/interrupt`, `/requires-redefinition` | EJECUCION |
| `/control/approve`, `/reject` | CONTROL_TECNICO |
| `/details/{d}/cancel`, `/cancel` | CANCELACION |
| `/authorizations` | DECISION_CLIENTE (+ CANCELACION si hay rechazos) |
| `/withdrawal`, `/details/{d}/withdrawal` | DECISION_CLIENTE + CANCELACION |
| `/return-equipment`, `/deliver`, `/return-rt` | ENTREGA |
| `PUT /reception`, `/reception/confirm`, `/not-received`, `/notes`, `/documents/reception-receipt` | CUSTODIA (INGRESO_CORREGIR si corrige datos registrados) |
| `/documents/intake-receipt` | DETALLE_DEFINIR_RECEPCION + CUSTODIA + DECISION_CLIENTE + COMPROBANTE_AUTORIZACION |
| `/documents/authorization-receipt` | COMPROBANTE_AUTORIZACION |
| `/discount` | DESCUENTO o CORTESIA |
| `/details/{d}/warranty` | GARANTIA_AJUSTAR |
| `/notify` | CLIENTE_NOTIFICAR |
| `/payments`, `/payments/{p}/void`, `/refunds` | PAGO_REGISTRAR, PAGO_ANULAR, DEVOLUCION_DINERO |
| `/photos` (alta y vista) | FOTOS_CARGAR (brecha 10) |
| `/checkin` | CHECKIN |
| `/pickup-followups` | RETIRO_SEGUIMIENTO |
| `/consumptions/{c}/return` | DEVOLUCION_STOCK |
| `/checklist`, `/missing-info-ack` | CHECKLIST_REGISTRAR |
| `POST /api/orders/{id}/equipment-link` | EQUIPO_VINCULO_CORREGIR |
| `POST /api/orders/{id}/messages[/…/confirm]` | COMUNICACION_ENVIAR |
| `POST /api/clients/{id}/consents` | CONSENTIMIENTO_REGISTRAR |
| `POST /api/orders/{id}/documents/{d}/signatures` | FIRMA_REGISTRAR |
| `POST /api/warranty-claims/{c}/continue` | RECLAMO_CONTINUAR + ORDEN_CREAR (+ DETALLE_DEFINIR_RECEPCION) |
