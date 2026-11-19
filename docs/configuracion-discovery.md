# Configuración: identificadores, permisos y catálogos operativos (discovery)

> **Estado:** discovery para revisión (19/11/2026). No incluye código, migraciones ni cambios en UAT. Las decisiones abiertas están en la sección 8. La implementación espera su aprobación.
>
> **Base relevada:** rama `feat/reparacion-rt-etapa1` (`f3036ca`), que incluye los dos permisos de Reparación RT. Las referencias `archivo:línea` apuntan a esa rama. Las rutas del backend son relativas a `app/backend/app/` y las del frontend a `app/frontend/src/`.

## Resumen

1. **Identificadores (CFG-01).**
   - Toda tabla tiene un `uuid` técnico y un `codigo` visible.
   - Hoy se escriben a mano cinco códigos: tipo de reparación, motivo, plantilla y los dos del insumo (`clave` INS-… y `codigo` BAT-…).
   - Proveedor, solicitud, OC, reclamo y pregunta de checklist ya son automáticos, pero con `max(codigo)+1`. Eso no es seguro ante concurrencia y falla al pasar de 9999 o 999999 (el máximo es lexicográfico).
   - La propuesta es un único generador transaccional en la base que conserva los formatos actuales.
2. **Permisos (CFG-02).**
   - Hay 54 permisos, todos en uso.
   - Toda la administración de catálogos cuelga de `CONFIGURACION_ADMINISTRAR`, que no es configurable.
   - `COMPRAS_GESTIONAR` sí es configurable y aparece en la pantalla, pero tiene cuatro problemas:
     - agrupa seis acciones;
     - solo se asigna por rol;
     - está en un grupo poco visible;
     - sin `COMPRAS_CONSULTAR` la pantalla no se ve.
   - Se encontraron 22 brechas, entre ellas cinco roles fijos (tres en el backend y dos en el frontend) que contradicen permisos configurables.
3. **Configuración operativa (CFG-03).** Se proponen siete permisos configurables nuevos para catálogos y cinco para Compras (incluidos los proveedores). Por defecto mantienen a los roles que hoy tienen acceso, así que nadie gana acceso sin que Administración lo decida. Usuarios, roles, permisos y parámetros del sistema siguen siendo de Administración, fijos.
4. **Altas (CFG-04).** Un botón «+ Nuevo …» abre un modal sin campo de código. Al guardar se actualiza solo el listado afectado.
5. **Estructura (CFG-05).** Configuración pasa a ser un índice por funcionalidad: cada subsección se ve según su permiso y tiene su propia URL.

---

## 1. Inventario de entidades, IDs y códigos (CFG-01)

### 1.1 Convención vigente

| Tipo | Qué es | Ejemplo | Quién lo genera |
|---|---|---|---|
| **Clave técnica interna** | `id uuid` de cada tabla, usado por las FK. El backend nunca lo expone y traduce código → uuid (`storage/postgres/ordenes.py:198-213`) | `9f1c…` | La base (`gen_random_uuid()`) |
| **Código funcional visible** | `codigo` único, el «id» del dominio en la API y la pantalla | `OR-000123`, `TR-001`, `INS-001` | Varía según la entidad (tabla 1.2) |
| **Clave única de negocio** | Dato del negocio único que no es el identificador | email del usuario, documento del cliente, (marca, modelo, variante), número de lote por insumo, remito por OC | El usuario o el origen |

`services/identificadores.nuevo_id(prefijo)` genera `PREFIJO-<12 hex>`. Se guarda en `codigo`, no en la PK.

### 1.2 Entidades con código visible

**Catálogos de Configuración:**

| Entidad (tabla) | Código hoy | Generación | Concurrencia | Propuesta |
|---|---|---|---|---|
| Tipo de reparación (`tipo_reparacion`) | `codigo` sin regex; seed `TR-001`, `TR-002`; `TR-OTROS` reservado | **A mano**, sin pasar a mayúsculas (`application/configuracion.py:57`) | Si dos altas chocan, `ON CONFLICT DO NOTHING` da **500** (`storage/postgres/configuracion.py:24-37,176-179`) | **Automático `TR-NNN`** |
| Motivo de cancelación o interrupción (`motivo_operativo`) | `^[A-Z0-9][A-Z0-9_-]*$`; `CANC-OTRO`, `INT-OTRO` | **A mano**, pasado a mayúsculas | Choque → 500 | **Automático `CANC-NNN` / `INT-NNN`** según el tipo |
| Insumo, identificador (`insumo.clave`) | Seed `INS-001`, sin regex | **A mano** («Identificador») | Choque → 500 | **Automático `INS-NNN`** |
| Insumo, código operativo (`insumo.codigo`) | Seed `BAT-IP14`, tipo SKU | **A mano** («Código») | Choque → 500 | **Automático, igual a la clave, salvo que se informe uno** (D4) |
| Plantilla de mensaje (`plantilla_mensaje`) | Semántico: `INGRESO`, `LISTO_PARA_RETIRAR` | **A mano**, pasado a mayúsculas | Choque → 500 | Automático `PLT-NNN` para las nuevas; las existentes no cambian |
| Proveedor (`proveedor`) | `PRV-0001` | Automático, `max(codigo)+1` (`storage/postgres/compras.py:31-38,254-259`) | **No seguro**: choque → 500; falla después de `PRV-9999` | Mismo formato, generador nuevo |
| Pregunta de checklist (`checklist_pregunta`) | `CHK-0001` | Automático, máximo calculado en Python (`application/checklist.py:97-103`) | No seguro | Mismo formato, generador nuevo |
| Mesa de trabajo, usuario, medio de pago, modelo de equipo, tipo de equipo | `EST-001`, `RECEP-001`, `EFECTIVO`, `MOD-0001`, valor de Ventas | Seed, script o sincronización. No tienen alta en la aplicación | — | Sin cambios |

**Operaciones** (CFG-01 no las cambia salvo que se indique):

| Entidad | Código | Generación | ¿Seguro? | Propuesta |
|---|---|---|---|---|
| Orden | `OR-000001` | Secuencia SQL + `formatear_numero_orden` + bucle que saltea códigos usados (`storage/postgres/ordenes.py:183-196`) | Sí | **Modelo a imitar.** Sin cambios |
| Detalle, comunicación, recepción de compra, documento | `DET-001`, `COM-001`, `REC-01`, `{OR}-{SIGLA}-{vv}` | Correlativo por padre, con el padre bloqueado | Sí | Sin cambios |
| Solicitud y orden de compra | `SC-000001`, `OC-000001` | `max(codigo)+1` | **No**: choque → 409; falla después de 999999 | Mismo formato, generador nuevo |
| Reclamo de garantía | `RGA-000001` | `max(codigo)+1` (`storage/postgres/reclamos.py:43-46,102-106`) | **No**: choque → 500 | Mismo formato, generador nuevo |
| Cliente, equipo, toma, ejecución, movimiento, pago, devolución, foto, firma, lote | `CLI-`, `EQP-`, `TOM-`, `EJE-`, `MOV-`/`MST-`, `PAG-`, `DEV-`, `FOT-`, `FIR-`, `LOT-` + 12 hex | `nuevo_id` | Sí (aleatorio) | Sin cambios. `sincronizacion_origen.id` tiene un CHECK atado al formato de `nuevo_id` (`^SINC-[0-9a-f]{12}$`), así que ese formato no se toca |

### 1.3 Diseño del generador

Se crea una tabla de contadores en la base y una función que entrega el siguiente código **dentro de la transacción del alta**:

```text
rma.contador_codigo (prefijo PK, ultimo bigint >= 0, ancho smallint)
rma.siguiente_codigo(prefijo) -> text
  UPDATE ... SET ultimo = ultimo + 1 WHERE prefijo = $1 RETURNING ...
  formatea con ceros a la izquierda SIN truncar (lpad trunca: hay que evitarlo,
  como ya hace formatear_numero_orden)
```

**Por qué un contador en tabla y no una secuencia por catálogo:**
- El `UPDATE` bloquea la fila hasta el commit, así que dos altas simultáneas reciben números distintos.
- Si el alta falla, el número vuelve atrás: no quedan huecos.
- Para catálogos (pocas altas por día) la espera es despreciable. Para OC, SC y RGA también.
- Es un solo objeto para todos los prefijos, fácil de inicializar y de auditar.

**Inicialización (en la migración).** Para cada prefijo, `ultimo` toma el mayor sufijo numérico de los códigos que siguen el patrón `^PREFIJO-[0-9]{1,18}$`. Se ignoran los códigos que no lo siguen: `TR-OTROS`, `CANC-OTRO`, `INGRESO`, `PRV-ABC`, y los de las pruebas como `TR-OFF` o `INS-S`. Así ningún código existente cambia ni se reutiliza.

| Prefijo | Tabla y columna | Ancho mínimo | Inicializado desde |
|---|---|---|---|
| `TR` | `tipo_reparacion.codigo` | 3 | `TR-001`, `TR-002` → 2 |
| `CANC` y `INT` | `motivo_operativo.codigo` según el tipo | 3 | 0 (los `*-OTRO` no son numéricos) |
| `INS` | `insumo.clave` | 3 | `INS-001` → 1 |
| `PLT` | `plantilla_mensaje.codigo` | 3 | 0 |
| `PRV` | `proveedor.codigo` | 4 | máximo actual |
| `CHK` | `checklist_pregunta.codigo` | 4 | máximo actual |
| `SC`, `OC` y `RGA` | `solicitud_compra`, `orden_compra`, `reclamo_garantia` | 6 | máximo actual |

**Robustez:**
- Si alguien carga un código a mano por SQL o script y el generador lo alcanza, el alta reintenta con el siguiente número (hasta 5 veces), igual que `reservar_codigo` de la Orden.
- Una violación de unicidad pasa a ser **409 `CODIGO_DUPLICADO`**, no 500. Esto corrige los cinco altas que hoy responden 500.
- `TR-OTROS` sigue reservado. El generador nunca produce un sufijo no numérico.

**Inmutabilidad.**
- **En la base:** un trigger `impedir_cambio_codigo` en `tipo_reparacion`, `motivo_operativo`, `plantilla_mensaje`, `proveedor`, `checklist_pregunta` y `mesa_trabajo`. Hoy solo lo impide el servicio (el backend tiene `UPDATE` sobre toda la tabla).
- **Insumo:** ya está protegido por grants de columna.
- **OC y SC:** ya están protegidas por trigger.
- **Historia:** no se modifica ningún identificador histórico.

**Opcional (requiere revisar el UAT antes).** Unicidad sin distinguir mayúsculas (`upper(codigo)`) en `tipo_reparacion`, `insumo.clave` e `insumo.codigo`. Hoy `tr-010` y `TR-010` pueden convivir. La migración tiene que verificar que no haya choques y detenerse si los hay.

### 1.4 Contrato de la API

- **El código pasa a ser opcional en los cuatro POST:** `repair-types`, `reasons`, `supplies` (`clave` y `codigo`) y `message-templates`.
  - Si no viene, se genera.
  - Si viene, se valida (formato, mayúsculas, unicidad) y se respeta. Esto existe solo por compatibilidad con el frontend publicado durante la publicación coordinada y con los scripts de UAT: `probar_macro_v14.py:796` crea un tipo con código fijo.
  - La pantalla nueva no lo envía.
- **La respuesta del alta devuelve la entidad creada con su código,** para que la pantalla la agregue al listado y la nombre en la confirmación («Se creó TR-003 Cambio de pantalla»).
- **Las rutas de edición siguen usando el código:** `PUT /repair-types/{codigo}` y `PUT /supplies/{clave}`. No cambian.

---

## 2. Matriz de permisos (CFG-02)

### 2.1 Cómo se aplica hoy

- **Modelo:** solo **rol → permiso**. No hay concesiones por usuario. Un usuario puede tener varios roles. Los cambios se guardan en `rma.permiso` (sin fila rige el predeterminado del código) y se auditan en `cambio_configuracion`.
- **Capa de API:** `exigir_rol(permiso)` (`api/seguridad.py:123-140`). En modo demo no controla nada.
- **Capa de servicio:** `validar_alguno_de(usuario, permiso)`. Controla en los dos modos.
  - Las consultas se protegen solo en la API.
  - Los comandos de Órdenes y Compras se protegen solo en el servicio.
- **No configurables:** `CONFIGURACION_ADMINISTRAR` y `ROLES_ADMINISTRAR`, ambos solo de Administración.
- **Frontend:**
  - Lee `usuario.permisos` del catálogo de usuarios, una sola vez al montar. Usa `puede(actor, permiso, rolesPorDefecto)` con roles escritos en el código como respaldo.
  - **Un cambio de permisos no se ve en la sesión abierta hasta recargar la página.**

### 2.2 Matriz por módulo

La columna «Config.» indica si la pantalla Permisos permite cambiar quién lo tiene.

**Configuración y catálogos**

| Acción | Endpoint | Permiso actual | Roles | Config. | Se aplica en |
|---|---|---|---|---|---|
| Ver catálogo de tipos y Mesas | `GET /api/admin/catalog` | CONFIGURACION_ADMINISTRAR | ADMIN | No (fijo) | API |
| Alta y edición de tipo de reparación, incluido el precio | `POST/PUT /api/admin/repair-types` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Tipos habilitados por Mesa | `PUT /api/admin/stations/{c}/repair-types` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Motivos de cancelación e interrupción | `GET/POST/PUT /api/admin/reasons` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Insumos, incluido el precio | `GET/POST/PUT /api/admin/supplies` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Proveedores | `GET/POST/PUT /api/admin/suppliers` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Plantillas de WhatsApp | `GET/POST/PUT /api/admin/message-templates` | CONFIGURACION_ADMINISTRAR | ADMIN | No | **Solo servicio. La GET está abierta a cualquier sesión** (brecha 8) |
| Checklist (preguntas) | `POST/PUT /api/admin/checklist-questions` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Sincronizar tipos de equipo desde Ventas | `POST /api/admin/equipment-types/sync` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Parámetros (plazo de retiro) | `GET/PUT /api/admin/parameters` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Recargo por medio de pago | `GET/PUT /api/admin/payment-methods` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API + servicio |
| Auditoría de cambios | `GET /api/admin/config-changes` | CONFIGURACION_ADMINISTRAR | ADMIN | No | API |
| Roles de un usuario | `PUT /api/admin/users/{c}/roles` | API: CONFIGURACION_ADMINISTRAR; servicio: ROLES_ADMINISTRAR | ADMIN | No | Las dos capas, con permisos distintos (brecha 12) |
| Roles de un permiso | `PUT /api/admin/permissions/{c}` | Ídem | ADMIN | No | Ídem; **acepta una lista vacía** (brecha 14) |
| Sincronizar el catálogo de equipos de Ventas | `POST /api/catalogs/equipment/sync` | CATALOGO_EQUIPOS_SINCRONIZAR | ADMIN, COORD | Sí | API + servicio. **Sin botón en la interfaz** |
| Sincronizar Productos RT | `POST /api/rt-products/sync` | PRODUCTOS_RT_SINCRONIZAR | ADMIN | Sí | API + servicio |
| Limpiar fotos sin Orden | `POST /api/maintenance/photos/cleanup` | API: **rol fijo ADMIN**; servicio: FOTOS_ADMINISTRAR | ADMIN | Solo en apariencia | Brecha 3 |

**Compras**

| Acción | Endpoint | Permiso actual | Roles | Config. | Se aplica en |
|---|---|---|---|---|---|
| Ver solicitudes, OC, sugerencias, costos y proveedores | `GET /api/purchases/*` | COMPRAS_CONSULTAR | RECEP, COORD, ADMIN | Sí | API |
| Crear y descartar solicitudes | `POST /api/purchases/requests[/{id}/discard]` | COMPRAS_GESTIONAR | RECEP, COORD, ADMIN | Sí | Servicio (`services/compras.py:107,136`) |
| **Crear OC** | `POST /api/purchases/orders` | COMPRAS_GESTIONAR | ídem | Sí | Servicio (`:199`) |
| Confirmar OC | `POST /orders/{id}/confirm` | COMPRAS_GESTIONAR | ídem | Sí | Servicio (`:251`) |
| Cancelar OC | `POST /orders/{id}/cancel` | COMPRAS_GESTIONAR | ídem | Sí | Servicio (`:264`) |
| Recibir mercadería (ingresa stock, lote y costo) | `POST /orders/{id}/receipts` | COMPRAS_GESTIONAR, **sin STOCK_GESTIONAR** | ídem | Sí | Servicio (`:297`) |
| Alta y edición de proveedores | `/api/admin/suppliers` | CONFIGURACION_ADMINISTRAR | ADMIN | **No** | API + servicio |

**Por qué «no se puede configurar quién crea OC».** El permiso existe y se puede cambiar por rol, pero en la práctica no sirve para eso, por seis motivos:

1. Un solo permiso cubre seis acciones: no se puede dar «crear OC» sin confirmar, cancelar y recibir.
2. Se asigna por rol, no por usuario.
3. Está en el grupo «Inventario y catálogos» con una descripción que no dice «crear».
4. Sin `COMPRAS_CONSULTAR`, el menú oculta Compras y las GET responden 403.
5. Sin un proveedor no se puede crear una OC, y los proveedores son solo de Administración, fijo.
6. El cambio no se ve hasta recargar la página.

**Inventario e ingreso de stock**

| Acción | Endpoint | Permiso | Roles | Config. | Se aplica en |
|---|---|---|---|---|---|
| Consultar inventario, movimientos y lotes | `GET /api/inventory/*` | INVENTARIO_CONSULTAR | todos | Sí | API |
| Ingreso y ajuste manual | `POST /api/inventory/{id}/receipts`, `/adjustments` | STOCK_GESTIONAR | ADMIN, COORD | Sí | API + servicio |
| Revalidar recursos | `POST /api/inventory/revalidate-orders` | RECURSOS_REVALIDAR | ADMIN, COORD | Sí | API + servicio |
| Devolver un consumo al stock | `POST /api/orders/{id}/consumptions/{c}/return` | DEVOLUCION_STOCK | ADMIN, COORD | Sí | Servicio |

**Órdenes (66 rutas).**
- **Consultas:** `ORDENES_CONSULTAR` en la API.
- **Comandos:** cada uno tiene su permiso en el servicio (ORDEN_CREAR, DETALLE_DEFINIR_*, CUSTODIA, ENTREGA, PAGO_*, CANCELACION, etc.), todos configurables.
- **El detalle por ruta** está en el anexo A. Allí figuran las excepciones: roles fijos, rutas sin usuario y acciones que exigen varios permisos.

**Consultas y otras**

| Acción | Endpoint | Permiso | Se aplica en |
|---|---|---|---|
| Reportes | `GET /api/reports/operational` | REPORTES_CONSULTAR | API |
| Antecedentes del equipo | `GET /api/equipment/history`, `/identify` | ANTECEDENTES_CONSULTAR | API |
| Reclamos rechazados | `GET /api/warranty-claims` | RECLAMOS_CONSULTAR | API |
| Buscar cliente por DNI | `GET /api/clients/lookup` | CLIENTE_BUSCAR | API + servicio |
| Productos RT | `GET /api/rt-products` | PRODUCTOS_RT_CONSULTAR | API |
| Bandejas de trabajo | `GET /api/work/*` | **Solo la sesión**; el contenido depende del rol fijo | — |
| Usuarios con roles y permisos | `GET /api/catalogs/users` | **Solo la sesión**: cualquier usuario ve los permisos de todos | — |

### 2.3 Brechas y recomendaciones

Prioridad: **A** se corrige en esta iteración porque impide configurar o contradice la configuración. **B** conviene corregirla en esta iteración porque es de bajo costo. **C** se registra en `DEUDA_TECNICA.md`.

| # | Brecha | Dónde | Prio. | Recomendación |
|---|---|---|---|---|
| 1 | El envío a revisión usa el **rol fijo RECEPCION**, no `ENVIAR_A_REVISION` | `services/ordenes.py:665,685` | A | Usar el permiso. Su predeterminado es RECEP, así que el comportamiento no cambia |
| 2 | La garantía RMA sin excepción exige el **rol fijo RECEPCION** además de `GARANTIA_RMA_CREAR` | `application/ingreso.py:457-462` | A | Usar solo el permiso, previa verificación en `business/` de que no sea una regla deliberada |
| 3 | La limpieza de fotos tiene el **rol fijo ADMIN** en la API y `FOTOS_ADMINISTRAR` en el servicio | `api/mantenimiento.py:33` | A | `exigir_rol(FOTOS_ADMINISTRAR)` |
| 4 | Toda la administración de catálogos y proveedores depende de un permiso **no configurable** | `api/configuracion.py:63-66`, `api/compras.py:59` | A | Permisos operativos (sección 3) |
| 5 | `COMPRAS_GESTIONAR` agrupa seis acciones | `services/compras.py:107-297` | A | Separarlo (sección 3.3) |
| 6 | La recepción de compra ingresa stock sin `STOCK_GESTIONAR` | `application/compras.py:349` | C | Decisión deliberada (DEC-MI-09); documentarla |
| 7 | Gestionar sin consultar deja Compras invisible | `PanelOrdenes.tsx:800`, `api/compras.py:58` | A | Dependencias entre permisos (sección 3.4) |
| 8 | Plantillas `/api/admin/message-templates` sin `exigir_rol` | `api/comunicaciones.py:194,199,211` | A | `exigir_rol(PLANTILLA_GESTIONAR)` |
| 9 | Lecturas de Orden o cliente sin `ORDENES_CONSULTAR`: mensaje preparado, consentimientos y bandejas | `api/comunicaciones.py:112,161`, `api/trabajo.py:20,29` | B | Agregar `exigir_rol(ORDENES_CONSULTAR)` |
| 10 | Ver fotos y firmas exige el permiso de **carga** | `api/ordenes.py:1602`, `api/firmas.py:28` | B | Usar `ORDENES_CONSULTAR` |
| 11 | Rutas que cambian estado sin usuario: espera de recursos, revalidar e informar a RT | `api/ordenes.py:751,765,1667` | C | Analizarlas aparte: son «eventos de sistema» por diseño |
| 12 | Usuarios y permisos usan un permiso en la API y otro en el servicio | `api/configuracion.py:66`, `services/roles.py:65,105` | B | `exigir_rol(ROLES_ADMINISTRAR)` en esas rutas |
| 13 | La sincronización de Tipos de Equipo usa un permiso fijo; las análogas usan permisos configurables | `application/checklist.py:116` | A | `CHECKLIST_GESTIONAR` |
| 14 | `PUT /permissions` acepta una lista de roles vacía | `services/roles.py:104-116` | B | Rechazarla en el servicio, como ya hace el frontend |
| 15 | Hay acciones que exigen varios permisos: decisión con rechazos, comprobante de ingreso, continuar reclamo, evaluación técnica | anexo A | B | Documentarlas en la pantalla Permisos («también requiere …») |
| 16 | Bandejas y responsable de la situación por rol fijo | `application/bandejas.py:845-850`, `situacion.py:900` | C | Fuera de alcance: son vistas por puesto, no acciones |
| 17 | En modo demo las consultas no controlan nada y se puede suplantar al usuario | `api/seguridad.py:134` | C | Por diseño; Cloud Run ya bloquea el modo demo |
| 18 | **Frontend:** Configuración por rol fijo ADMIN; crear Orden por rol fijo RECEPCION (contradice `ORDEN_CREAR`, que es configurable) | `Configuracion.tsx:304`, `PanelOrdenes.tsx:799`, `ListadoOrdenes.tsx:943,1095` | A | Usar `puede(...)` con el permiso |
| 19 | **Frontend:** el respaldo usa el rol inexistente `"ADMINISTRACION"` | `RetiroDemorado.tsx:37` | B | Corregirlo a `ADMINISTRADOR` |
| 20 | **Frontend:** los permisos no se refrescan después de cambiarlos | `PanelOrdenes.tsx:268-302` | A | Volver a pedir el usuario actual después de guardar roles o permisos |
| 21 | `GET /api/catalogs/users` expone los permisos de todos los usuarios a cualquiera con sesión | `api/catalogos.py:51` | C | Separar «mis permisos» (`/api/me`) del selector de demo |
| 22 | Descripciones inexactas: `CUSTODIA` dice que incluye la devolución sin reparar (usa `ENTREGA`); `ENVIAR_A_REVISION` | `permisos.py:352` | B | Corregir los textos |

---

## 3. Diseño de permisos operativos (CFG-03)

### 3.1 Principios

1. **Por defecto nadie gana acceso nuevo.**
   - Cada permiso nuevo arranca con los roles que hoy pueden hacer esa acción: Administración en los catálogos; Recepción, Coordinación RMA y Administración en Compras.
   - Administración decide después, desde Permisos, a quién se lo da. Es la misma regla que DEC-MI-10.
   - La alternativa está en D2.
2. **Separar de lo sensible.**
   - Siguen fijos de Administración (`configurable=False`):
     - usuarios y roles, y la matriz de permisos (`ROLES_ADMINISTRAR`);
     - parámetros del sistema y recargos por medio de pago;
     - auditoría completa (`CONFIGURACION_ADMINISTRAR`, cuyo alcance se reduce a eso).
   - Un error ahí afecta a toda la operación o a quién puede administrarla.
3. **Un permiso por catálogo, con alta y edición juntas.** El precio es la excepción (D3).
4. **Cada permiso se aplica en las dos capas:** `exigir_rol` en la API y `validar_alguno_de` en el servicio.

### 3.2 Permisos nuevos de catálogos

**Grupo nuevo: «Configuración operativa».**

| Permiso | Cubre | Predeterminado | Reemplaza a |
|---|---|---|---|
| `INSUMO_GESTIONAR` | Alta de insumo; nombre, unidad, control por lote y vigencia | ADMIN | CONFIGURACION_ADMINISTRAR |
| `TIPO_REPARACION_GESTIONAR` | Alta de tipo; nombre, puntaje, garantía y vigencia | ADMIN | ídem |
| `PRECIOS_GESTIONAR` (D3) | Precio de los tipos de reparación y de los insumos, en el alta y en la edición | ADMIN | ídem |
| `MESA_TIPOS_GESTIONAR` | Tipos habilitados por Mesa de trabajo | ADMIN | ídem |
| `MOTIVO_GESTIONAR` | Motivos de cancelación e interrupción | ADMIN | ídem |
| `PLANTILLA_GESTIONAR` | Plantillas de WhatsApp | ADMIN | ídem (y cierra la brecha 8) |
| `CHECKLIST_GESTIONAR` | Preguntas del checklist y sincronización de Tipos de Equipo | ADMIN | ídem |

**Siguen siendo de Administración y no se configuran:**

| Permiso | Cubre |
|---|---|
| `ROLES_ADMINISTRAR` | Roles de cada usuario y la matriz de permisos |
| `CONFIGURACION_ADMINISTRAR` | Parámetros del sistema, recargos por medio de pago y auditoría completa |

**Lectura.** Los GET de cada catálogo (`/api/admin/supplies`, `/reasons`, etc.) exigen el permiso de gestión de ese catálogo. Los selectores operativos (`/api/catalogs/*`) siguen abiertos a cualquier sesión, como hoy. Cada subsección muestra **su propio** historial de cambios, filtrando `cambio_configuracion` por entidad. La auditoría completa sigue siendo de Administración.

### 3.3 Compras

**Grupo nuevo: «Compras».** `COMPRAS_GESTIONAR` se divide en:

| Permiso | Cubre | Predeterminado |
|---|---|---|
| `COMPRAS_CONSULTAR` (existe) | Ver la sección, solicitudes, OC, sugerencias y costos | RECEP, COORD, ADMIN |
| `COMPRA_SOLICITAR` | Crear y descartar solicitudes | los vigentes de COMPRAS_GESTIONAR |
| `OC_CREAR` | Crear OC en borrador | ídem |
| `OC_CONFIRMAR` | Confirmar y cancelar OC | ídem |
| `COMPRA_RECIBIR` | Registrar recepciones (ingresa stock) | ídem |
| `PROVEEDOR_GESTIONAR` | Alta y edición de proveedores (hoy fijo de ADMIN) | ADMIN |

**Migración de lo configurado:**
- Si el UAT tiene una fila de `COMPRAS_GESTIONAR` en `rma.permiso`, la migración la copia a los cuatro permisos nuevos.
- La fila original **no se borra**, para que un backend anterior siga funcionando si hay que volver atrás.
- El registro del código deja de definir `COMPRAS_GESTIONAR`. Una fila sin permiso correspondiente se ignora.

**Alcance de la división.** Si se prefiere menos granularidad, la mínima que resuelve el pedido es dos permisos: `OC_CREAR` y `COMPRAS_GESTIONAR` para todo lo demás (D5).

### 3.4 Dependencias entre permisos

Cada `Permiso` declara los permisos que **requiere**. Por ejemplo, `OC_CREAR` requiere `COMPRAS_CONSULTAR` e `INSUMO_GESTIONAR` requiere `INVENTARIO_CONSULTAR`.

- **En la pantalla Permisos:** al marcar un rol en un permiso de acción, también se marca su consulta. Si se intenta quitar una consulta de la que depende otro permiso del mismo rol, aparece un aviso.
- **En el backend:** `PUT /permissions` rechaza un cambio que deje a un rol con una acción y sin la consulta que esa acción requiere (409 con el motivo).
- **Resultado:** se evita el caso de Compras invisible (brecha 7).

### 3.5 ¿Por rol o por usuario? (D1)

El pedido menciona «qué usuarios crean OC». Hoy el modelo es solo por rol.

**Opción A (recomendada para esta iteración): seguir por rol.**
- Con los permisos separados, Administración da `OC_CREAR` a un rol y asigna ese rol a quien corresponda. Un usuario ya puede tener varios roles.
- Su limitación: no sirve para darle a una sola persona de Recepción algo que el resto de Recepción no tiene.

**Opción B: concesiones adicionales por usuario.**
- Una tabla `rma.usuario_permiso`, solo para agregar permisos, nunca para quitar.
- Resuelve el caso puntual, pero toca el corazón de la autorización:
  - `validar_alguno_de`;
  - las `AccionDisponible.roles` que recibe el frontend, que tendrían que pasar a un `permitida` calculado por usuario;
  - la pantalla Permisos;
  - la auditoría.
- Duplica aproximadamente el alcance del backend de esta iteración. Se recomienda dejarla como iteración siguiente si la opción A no alcanza.

---

## 4. Formularios y navegación (CFG-04 y CFG-05)

### 4.1 Situación actual

- Todas las altas son formularios fijos debajo del listado; ninguna usa modal.
- Después de guardar, cada pantalla vuelve a pedir su lista completa, y la pestaña Catálogos además pide la auditoría.
- **Errores existentes:**
  - el alta de insumo **vacía el formulario aunque falle** (`Insumos.tsx:210`);
  - el alta de tipo de reparación **no se limpia** al terminar.
- Tipos de reparación, motivos, plantillas e insumos piden el código a mano; el insumo pide dos.
- No hay componente de pestañas ni de tabla. Cada pantalla repite su propio `error`, `aviso`, `ocupado` y `ejecutar`.

### 4.2 Propuesta de alta y edición (CFG-04)

```text
┌ Insumos ───────────────────────────── [ + Nuevo insumo ] ┐
│ Buscar…                                                   │
│ INS-014  Batería iPhone 14   unidad   Lote ✓  $ 25.000  ✎ │
│ INS-013  Pantalla A54        unidad   Lote ✗  $ 41.000  ✎ │
└───────────────────────────────────────────────────────────┘
          ┌ Nuevo insumo ──────────────────── ✕ ┐
          │ Nombre*          [               ]  │
          │ Unidad           [ unidad        ]  │
          │ Control por lote [ ]                │
          │ Precio           [               ]  │  ← solo con PRECIOS_GESTIONAR
          │ Código operativo [ (automático)  ]  │  ← opcional (D4)
          │ El identificador se asigna al guardar.│
          │              [Cancelar] [Crear insumo]│
          └─────────────────────────────────────┘
```

**Comportamiento:**
- El botón «+ Nuevo …» va en el encabezado de cada listado y solo aparece si el usuario tiene el permiso.
- Se usa el `Modal` existente con el patrón de Inventario:
  - el modal se cierra solo si el alta salió bien;
  - el error se muestra dentro del modal y conserva lo escrito;
  - el foco va al primer campo y Escape cierra.
- **No hay campo de código.** La confirmación lo informa: «Se creó INS-014 Batería iPhone 14».
- **El listado se actualiza sin recargar la pantalla:** se inserta en la lista la entidad que devuelve el POST y se resalta la fila nueva. No se vuelve a pedir el catálogo completo ni la auditoría.
- La **edición** también usa el modal (botón ✎). Los interruptores de una sola acción (vigente, control por lote) se mantienen en la fila.
- Los campos que el usuario no puede editar se muestran en solo lectura, por ejemplo el precio sin `PRECIOS_GESTIONAR`.

**Catálogos y campos del modal:**

| Catálogo | Campos del modal |
|---|---|
| Tipo de reparación | Nombre, precio, puntaje, garantía en días y Mesas habilitadas (opcional) |
| Motivo | Tipo (Cancelación o Interrupción), nombre y «exige descripción» |
| Insumo | Nombre, unidad, control por lote, precio y código operativo (opcional) |
| Plantilla | Nombre, finalidad y texto con variables |
| Proveedor | Igual que hoy, pero en un modal |
| Pregunta de checklist | Tipo de equipo, texto y opciones |

**Piezas compartidas nuevas:**
- `FormularioModal`: el modal con los botones Cancelar y Confirmar, el estado de ocupado y el error.
- Un hook `useComando`, que unifica `error`, `aviso`, `ocupado` y `ejecutar`.
- Un componente `Pestanas`, que reemplaza las dos barras de pestañas hechas a mano.

### 4.3 Estructura de Configuración (CFG-05)

Configuración pasa a ser un índice agrupado por funcionalidad. Cada subsección se ve si el usuario tiene **su** permiso, y la sección del menú aparece si tiene al menos uno.

| Grupo | Subsección | Permiso | Ruta |
|---|---|---|---|
| Taller | Tipos de reparación | TIPO_REPARACION_GESTIONAR | `#/configuracion/tipos-reparacion` |
| Taller | Mesas de trabajo | MESA_TIPOS_GESTIONAR | `#/configuracion/mesas` |
| Taller | Motivos | MOTIVO_GESTIONAR | `#/configuracion/motivos` |
| Taller | Checklist | CHECKLIST_GESTIONAR | `#/configuracion/checklist` |
| Inventario y compras | Insumos | INSUMO_GESTIONAR | `#/configuracion/insumos` |
| Inventario y compras | Proveedores | PROVEEDOR_GESTIONAR | `#/configuracion/proveedores` |
| Comunicación | Plantillas | PLANTILLA_GESTIONAR | `#/configuracion/plantillas` |
| Sistema (Administración) | Usuarios y roles; Permisos | ROLES_ADMINISTRAR | `#/configuracion/usuarios`, `#/configuracion/permisos` |
| Sistema (Administración) | Parámetros y recargos; Auditoría | CONFIGURACION_ADMINISTRAR | `#/configuracion/parametros`, `#/configuracion/auditoria` |

- **Navegación:**
  - `#/configuracion` lleva a la primera subsección permitida;
  - una subsección sin permiso muestra «No tenés permiso para …» (el backend igual responde 403);
  - las pestañas pasan a la URL, así que se pueden recargar y compartir.
- **Pantalla Permisos:**
  - suma los grupos «Compras» y «Configuración operativa»;
  - muestra las dependencias de cada permiso;
  - incluye la nota «también requiere …» de las acciones compuestas (brecha 15);
  - corrige las descripciones (brecha 22).
- **Fuera de alcance, para evaluar después:** accesos directos desde Inventario («+ Nuevo insumo») y desde Compras («+ Nuevo proveedor»). Reutilizarían el mismo modal y el mismo permiso; la gestión queda en un solo lugar.

---

## 5. Cambios de base de datos

Una migración aditiva, `2026112xxxxxxx_configuracion_operativa.sql`:

1. **Generador de códigos.**
   - Tabla `rma.contador_codigo` y función `rma.siguiente_codigo(prefijo)` sin truncar.
   - Inicialización desde los máximos numéricos de la sección 1.3.
   - Grants: `select` y `update` sobre el contador y `execute` sobre la función para `rma_backend`; revocados para `anon`, `authenticated`, `service_role` y `public`.
2. **Inmutabilidad del código:** función `rma.impedir_cambio_codigo()` y su trigger en `tipo_reparacion`, `motivo_operativo`, `plantilla_mensaje`, `proveedor`, `checklist_pregunta` y `mesa_trabajo`.
3. **Permisos:** copiar la fila de `COMPRAS_GESTIONAR` de `rma.permiso`, si existe, a `COMPRA_SOLICITAR`, `OC_CREAR`, `OC_CONFIRMAR` y `COMPRA_RECIBIR`, con su auditoría en `cambio_configuracion`. No se borra nada.
4. **Opcional (D6):** índices únicos con `upper(codigo)` y una verificación previa que se detiene si hay choques.
5. **Sin cambios** en las tablas de operación, en los formatos de `nuevo_id` ni en los identificadores existentes.
6. **Pruebas del esquema a actualizar** (cambian el inventario de objetos, no el comportamiento):
   - `supabase/tests/10_esquema.sql`, que pasa a 73 entidades;
   - `tests/postgres/test_base_local.py`;
   - `docs/postgresql/diseno-logico.md` y `diseno-fisico.md`;
   - los scripts de reinicio del UAT (`01_reiniciar.sql`, `03_verificar.sql`), donde `contador_codigo` es una tabla maestra que **no** se reinicia.

---

## 6. Riesgos de compatibilidad

| Riesgo | Mitigación |
|---|---|
| El frontend publicado manda `codigo` en los POST de alta durante la publicación coordinada | El código es opcional y, si viene, se respeta (sección 1.4) |
| Los scripts del UAT crean entidades con código fijo (`probar_macro_v14.py:796`) | Ídem. Los scripts no cambian |
| Pruebas que esperan códigos tipeados (`TR-OFF`, `INS-S`, `CANC-PRECIO`…) | Siguen siendo válidas porque el código opcional se respeta. Se agregan pruebas del generador |
| Pruebas que fijan formatos (`PRV-0001`, `RGA-000001`, `OC-…`) | Los formatos no cambian |
| Una fila de `COMPRAS_GESTIONAR` en `rma.permiso` y la vuelta atrás a un backend anterior | Se copia y se conserva. El backend anterior la sigue leyendo |
| Hay roles en el código del frontend como respaldo (`puede(..., [roles])`) para los permisos renombrados | Actualizar los respaldos. Las pruebas `macro-integral.test.ts` y `roles.test.ts` lo cubren |
| La ruta `#/configuracion` cambia a subrutas | `#/configuracion` sigue siendo válida y redirige. Se actualiza `rutas.test.ts` |
| Un rol con un permiso nuevo y sin su consulta | Dependencias (sección 3.4) |
| El generador y un código cargado a mano por SQL que «adelanta» al contador | Reintento con el siguiente número y error 409 en lugar de 500 |
| Cambiar los roles fijos (brechas 1 a 3) cambia el comportamiento | No lo cambia mientras los permisos tengan sus predeterminados, porque coinciden con el rol fijo. Hay que confirmar en `business/` que la garantía RMA no exige Recepción por regla |
| Orden respecto de Reparación RT (rama sin integrar, con la migración `20261119000100`) | D7 |
| Ver precios sin poder editarlos: la pantalla debe mostrar el precio a quien gestiona el catálogo | El GET de cada catálogo exige su permiso de gestión, no el de precios |

---

## 7. Plan de implementación (una iteración, CFG-01 a CFG-05)

Mismo esquema de fases que Reparación RT: implementación, pruebas, QA independiente, correcciones y commits locales por fase, sin push ni UAT.

**Fase A: base y generador (CFG-01)**
1. Migración: contador, función, triggers de inmutabilidad y copia de permisos.
2. Repositorio `siguiente_codigo` con reintento y mapeo de 23505 a 409 `CODIGO_DUPLICADO`.
3. Altas de tipo de reparación, motivo, insumo y plantilla con código opcional.
4. Proveedor, SC, OC, RGA y CHK pasan al generador, con los mismos formatos.
5. **Pruebas:**
   - alta concurrente (dos conexiones, códigos distintos);
   - la reversión no deja huecos;
   - salto de un código cargado a mano;
   - `PRV-9999` → `PRV-10000`;
   - los códigos no numéricos se ignoran;
   - `TR-OTROS` sigue reservado;
   - el código es inmutable en la base;
   - el código informado se respeta.

**Fase B: permisos (CFG-02 y CFG-03, backend)**
1. Permisos nuevos y división de Compras; `CONFIGURACION_ADMINISTRAR` queda reducido; dependencias.
2. Cada router con el `exigir_rol` de su permiso y su servicio con `validar_alguno_de`.
3. Brechas A y B: 1, 2, 3, 8, 9, 10, 12, 13, 14, 19, 22.
4. **Pruebas:**
   - una matriz parametrizada (permiso × rol → 200/403) que recorre **todas** las rutas registradas y falla si aparece una ruta sin clasificar. Queda como control permanente de la auditoría;
   - JWT real;
   - un permiso reconfigurado rige desde el pedido siguiente;
   - el respaldo con la fila anterior de `COMPRAS_GESTIONAR`.

**Fase C: frontend (CFG-04 y CFG-05)**
1. `FormularioModal`, `useComando` y `Pestanas`.
2. Configuración por subsecciones con rutas, cada una con su permiso; sin `tieneRol`.
3. Modales de alta y edición para los seis catálogos; el listado se actualiza en el lugar.
4. Permisos agrupados con dependencias; los permisos del usuario se refrescan después de guardar (brecha 20).
5. Crear Orden por `ORDEN_CREAR` (brecha 18).
6. **Pruebas:** rutas, visibilidad por permiso, lógica de dependencias y reducción del listado; recorrido en el navegador con los cuatro roles, en escritorio y a 390 px.

**Fase D: cierre**
1. Suites completas: backend, `tests/postgres`, frontend y build.
2. Ensayo local de la migración sobre una base con el backend publicado.
3. QA independiente.
4. Documentación: este documento, `contratos-macro-integral.md` (permisos), `DEUDA_TECNICA.md` (brechas C), `ESTADO_PROYECTO.md` y el procedimiento de UAT.

**Futuro (no se implementa).** Jerarquía de insumos:
- categorías y subcategorías;
- productos;
- tipos de insumo;
- compatibilidad de un insumo con varios modelos de equipo.

Se registra en `docs/pendientes-producto.md` al aprobar este documento. El diseño de esta iteración no la impide: el insumo sigue con su `uuid` y su `clave`, y la compatibilidad sería una tabla `insumo_modelo_equipo` nueva.

---

## 8. Decisiones abiertas

| # | Decisión | Recomendación |
|---|---|---|
| D1 | ¿Permisos por rol o también por usuario? | Por rol en esta iteración; concesiones por usuario en la siguiente si hacen falta (sección 3.5) |
| D2 | Roles predeterminados de los permisos nuevos | Los que hoy tienen acceso (ADMIN en catálogos), y que Administración los extienda desde Permisos. Alternativa: dar desde el inicio Insumos, Motivos y Tipos a Coordinación RMA y Recepción |
| D3 | ¿Separar el precio (tipos e insumos) en `PRECIOS_GESTIONAR`? | Sí: el precio de un tipo es el precio al cliente. Un alta exige también ese permiso porque el precio es obligatorio |
| D4 | Código operativo del insumo (`codigo`, tipo SKU) | Automático igual a la clave (`INS-014`) salvo que se informe uno en el alta. Después no se puede cambiar, como hoy |
| D5 | Granularidad de Compras | Cuatro permisos (sección 3.3). La mínima es separar solo `OC_CREAR` |
| D6 | ¿Unicidad sin distinguir mayúsculas? | Sí, con verificación previa en el UAT |
| D7 | Rama base y orden respecto de Reparación RT | Partir de `feat/reparacion-rt-etapa1`, así el catálogo de permisos ya incluye Reparación RT y la migración va después de `20261119000100`. Integrar las dos en `mvp-v2` juntas o en ese orden |
| D8 | ¿Brechas B en esta iteración? | Sí, son de bajo costo. Las C van a `DEUDA_TECNICA.md` |

---

## Anexo A. Órdenes: permisos por comando

| Ruta (`/api/orders/...`) | Permiso en el servicio |
|---|---|
| `POST ""`, `/rt-interno` | ORDEN_CREAR (+ DETALLE_DEFINIR_RECEPCION si hay trabajo inicial) |
| `/details`, `/definition/finalize` | DETALLE_DEFINIR_RECEPCION o DETALLE_DEFINIR_TECNICO, según el estado |
| `/warranty-rma` | GARANTIA_RMA_CREAR o GARANTIA_EXCEPCION, **+ rol fijo RECEPCION** sin excepción (brecha 2) |
| `/send-to-review` | **rol fijo RECEPCION** (brecha 1) |
| `/review/without-repair` | ENVIAR_A_REVISION |
| `/technical-review` | REVISION_TECNICA |
| `/review/details`, `/details/{d}/technical-review`, `/redefine` | DETALLE_DEFINIR_TECNICO |
| `/details/{d}/resources/override` | RECURSOS_OVERRIDE |
| `/resources/wait`, `/resources/revalidate`, `/inform-rt` | **ninguno, sin usuario** (brecha 11) |
| `/queue` | PRIORIDAD_DEFINIR |
| `/priority` | PRIORIDAD_CAMBIAR |
| `/take`, `/details/{d}/start` | ORDEN_TOMAR |
| `/release` | ORDEN_TOMAR (propia) o LIBERACION_AJENA |
| `/details/{d}/evaluation` | EVALUACION_TECNICA + ORDEN_TOMAR (+ DETALLE_ADICIONAL) |
| `/details/additional` | DETALLE_ADICIONAL |
| `/executions/{e}/complete`, `/interrupt`, `/requires-redefinition` | EJECUCION |
| `/control/approve`, `/reject` | CONTROL_TECNICO |
| `/details/{d}/cancel`, `/cancel` | CANCELACION |
| `/authorizations` | DECISION_CLIENTE (+ CANCELACION si hay rechazos) |
| `/withdrawal`, `/details/{d}/withdrawal` | DECISION_CLIENTE + CANCELACION |
| `/return-equipment`, `/deliver`, `/return-rt` | ENTREGA |
| `PUT /reception`, `/reception/confirm`, `/not-received`, `/notes`, `/documents/reception-receipt` | CUSTODIA (INGRESO_CORREGIR si corrige datos ya registrados) |
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
