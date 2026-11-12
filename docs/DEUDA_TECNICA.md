# Deuda técnica priorizada

Pendientes técnicos que pueden afectar los próximos módulos. El backlog de producto está en [`pendientes-producto.md`](pendientes-producto.md) y los riesgos de la persistencia, en [`postgresql/integracion-pendientes.md`](postgresql/integracion-pendientes.md); aquí solo se enlazan.

**Prioridades:**

- **P0:** impide operar o desarrollar con seguridad.
- **P1:** hay que resolverlo durante las próximas funcionalidades, antes o junto con el módulo que lo necesita.
- **P2:** evolutivo; puede esperar.

Revisado el 11/11/2026.

## P0

| # | Pendiente | Por qué | Acción |
|---|---|---|---|
| P0-1 | **Resuelto (11/11/2026): respaldo diario operativo** | Cloud Run Job `rt-rma-respaldo-db` a las 03:00 de Argentina, cifrado con `age`, en un bucket inmutable 30 días y con un rol de solo lectura. La primera copia se verificó, la restauración completa se ensayó en la nube y la persona responsable descifró la copia real con su clave privada ([`RESPALDOS.md`](RESPALDOS.md)) | Ensayo mensual en la nube y, cada tanto, el descifrado con la clave real |
| P0-2 | **`mvp-v2` integrada (11/11/2026); falta `main`** | `mvp-v2` avanzó por avance rápido hasta `feat/postgresql-esquema`, con los cinco workflows en verde y sin desplegar: Vercel ya no despliega desde Git ([`DESPLIEGUE_UAT.md`](DESPLIEGUE_UAT.md), al principio). `main` sigue atrás | Integrar en `main`, con autorización y revisión en un PR, antes de abrir ramas de módulos nuevos |
| P0-4 | **Resuelto (11/11/2026): CI `backend` en rojo por un defecto de DC31** | Una Orden finalizada sin reparar (PROC-REP-069) con el equipo en el local ofrecía y aceptaba `REGISTRAR_DEVOLUCION`, la devolución previa a cancelar. Si se ejecutaba, salteaba PROC-REP-290 en `RT_INTERNO` o la notificación y la entrega en `CLIENTE_EXTERNO` con la recepción confirmada, y la Orden quedaba abierta sin acciones. Una Orden así ya no se cancela (`exigir_orden_cancelable`) | `admite_devolucion_sin_reparar` y `registrar_devolucion_equipo` (`services/cancelaciones.py`) excluyen las Órdenes con resultado (`lista_para_cierre`): devuelven el equipo en su cierre. Cubierto en `test_cancelacion_orden.py`, sección «Una Orden con resultado devuelve el equipo en su cierre»; las 4 expectativas desactualizadas se corrigieron en `fbdfaec` |
| P0-3 | **Resuelto (11/11/2026): corte a São Paulo** | El UAT público corre sobre São Paulo (`00024-top`, `d226fd2`). `OR-000001` se eliminó, porque tenía datos personales reales | Hasta el 25/11/2026, conservar Oregón para volver atrás, con actividad semanal; después, decidir sobre Oregón ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16) |

## P1

| # | Pendiente | Afecta a | Acción sugerida |
|---|---|---|---|
| P1-1 | **Configuración solo por SQL, en parte resuelta (12/11/2026):** Tipos de Reparación (precio, puntaje, garantía, vigencia) y Tipos habilitados por Mesa ya tienen pantalla de Administración con auditoría (`rma.cambio_configuracion`) e historial de precios (`feat/macro-v14`). Siguen solo por SQL: insumos, medios de pago, textos legales y el resto de los parámetros | Configuraciones operativas, garantías, compras e inventario | ABM de catálogos con rol Administración, auditoría (`accion_usuario`) y bajas lógicas (los catálogos ya tienen `activo` y triggers «sin borrado») |
| P1-2 | **Catálogo de Ventas como copia efímera:** JSON en el contenedor desde Google Sheets, sincronizado a mano después de cada despliegue. Obliga a **una sola instancia** de Cloud Run (también por el limitador por DNI en memoria) | Integración con datos de ventas, garantías de venta, escalado | Persistir el catálogo en PostgreSQL (tabla y sincronización programada o al arrancar) y mover el limitador a la base; después, permitir más de una instancia |
| P1-3 | **Sin paginación:** `GET /api/orders` y el detalle de un insumo cargan todo; las reservas incluyen Órdenes cerradas | Reporting, inventario, volumen real | Paginación por cursor y filtros en el servidor ([`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 4) |
| P1-4 | **Sin envío de mensajes:** WhatsApp existe solo como canal registrado de una decisión o un aviso; no hay proveedor, cola ni reintentos | WhatsApp | Tabla de salida (outbox) transaccional con idempotencia y un proceso de envío con reintentos. Credenciales del proveedor en Secret Manager |
| P1-5 | **Garantías de venta no modeladas:** la garantía de reparación existe (plazo por tipo, check-in, ajuste con auditoría, comprobante); la de venta no tiene datos de origen ni vínculo con el equipo vendido | Garantías RMA y de venta, ventas | Definir en `business/` (fuente funcional) el vínculo venta-equipo-garantía antes de implementar; depende de P1-2 |
| P1-6 | **Equipos internos (RT_INTERNO):** existe el origen y la Orden sin cobro; falta el buscador técnico (P-01) y un inventario de equipos propios | Equipos internos Rosario Tecno | [`pendientes-producto.md`](pendientes-producto.md), P-01 |
| P1-7 | **Reporting:** el historial (`evento_negocio`, equivalencias) da trazabilidad por Orden, pero no hay consultas agregadas ni exportación | Reporting y trazabilidad | Vistas o consultas de solo lectura sobre PostgreSQL, con un rol de lectura separado de `rma_api` |
| P1-12 | **El reporte operativo v1 recorre todas las Órdenes** (`application/consultas_operativas.py`, `reporte_operativo`, en la lista blanca de recorridos completos de `test_e2_equivalencia.py`): lee el agregado completo de cada Orden y suma en Python. Medido el 12/11/2026 sobre PostgreSQL local, Órdenes ficticias de dos trabajos, 5 lecturas: 50 Órdenes, mediana 73 ms; 150, 373 ms; 300, 821 ms (máximo 1067 ms). Crece lineal, unos 2,7 ms por Orden, y más con Órdenes de historial largo | Reporting con volumen real | **Reemplazar por consultas dedicadas** (`count`/`sum` por estado, origen, técnico, estación e insumo, con `consulta(..., modo=LECTURA)` como E2) **antes de que el UAT o producción pase de 200 Órdenes, o en cuanto `medir_api.py` muestre más de 500 ms de mediana en `/api/reports/operational`**, lo primero que ocurra. Con datos reales, también ponerle un rol de consulta (DC27B) |
| P1-8 | **Privilegios heredados de `PUBLIC`:** `rma_api` hereda `TEMP`, `UPDATE` sobre `pg_settings` y funciones de sesión | Seguridad de datos reales | Política de revocación ([`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección E, «Privilegios») |
| P1-9 | **Resuelto (11/11/2026):** el respaldo usa `rma_respaldo` (`pg_read_all_data`, `BYPASSRLS`, solo lectura), no la credencial de administración | — | — |
| P1-10 | **Resuelto (11/11/2026):** el cierre de `/docs`, `/redoc` y `/openapi.json` está publicado en `00024-top` (`d226fd2`), y `04_eliminar_respaldo.sql` se usó en el segundo reinicio de São Paulo | — | — |
| P1-11 | **Largo mínimo de contraseña 10** sin confirmar en los dos proyectos de Auth | Seguridad | Confirmar en el panel |

## P2

| # | Pendiente | Nota |
|---|---|---|
| P2-1 | `ruff format --check`: 11 archivos del backend sin formatear | CI solo exige `ruff check`, la convención actual. Formatearlos en un commit aislado, sin cambios funcionales |
| P2-2 | Foto subida cuya registración falla deja un objeto huérfano | [`pendientes-producto.md`](pendientes-producto.md), nota técnica; `/photos/cleanup` lo resuelve con autorización |
| P2-3 | Doble escritura no atómica de la Orden al cerrar una reparación, solo en modo JSON | [`pendientes-producto.md`](pendientes-producto.md); no afecta a PostgreSQL |
| P2-4 | **Resuelto (11/11/2026):** se quitaron las etiquetas `saopaulo` y `corte` y se borró la vista previa `rt-rma-k1qeeu33d`. `00020-tux` (`auth`) se conserva hasta el 25/11/2026 | — |
| P2-5 | Respuesta perdida de un comando (06/11): la idempotencia evita duplicados; falta revisar cómo lo informa el frontend | [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 4 |
| P2-6 | Lecturas en lote con 2 viajes de más (hipótesis TCP) | Con São Paulo el viaje cuesta unos 3 ms: deja de importar |
| P2-7 | Pasar a Supabase Pro cuando haya datos reales | Copias físicas y PITR administradas, sin pausa por inactividad |
| P2-8 | El Job de respaldo ya fija `postgres:17-alpine` por digest, pero sigue instalando `age` con `apk` en cada ejecución | Una imagen propia con `age`, para no depender de la red ni del repositorio de Alpine |
| P2-11 | Fotos sin versionado (`gs://rt-rma-uat-fotos`, hoy vacío) | Versionado más una regla que borre las versiones no actuales a los 30 días, antes de que haya fotos reales ([`RESPALDOS.md`](RESPALDOS.md), sección 2) |
| P2-9 | Vercel conserva 14 vistas previas automáticas de `feat/postgresql-esquema`, de la época en que desplegaba desde Git. Están protegidas por la autenticación de Vercel | Borrarlas en una limpieza, con autorización |
| P2-10 | Revisiones viejas sin etiqueta ni tráfico, algunas sin autenticación (`00017-wer`, `00012-d4z` y anteriores). No son accesibles mientras no tengan tráfico ni etiqueta | Borrarlas después del 25/11/2026, con autorización. Nunca usarlas como vuelta atrás |
