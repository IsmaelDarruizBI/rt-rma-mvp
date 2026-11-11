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
| P0-1 | **Respaldo automático no activado** | El plan Free no tiene copias. Hoy un error borra datos sin vuelta atrás | Activar [`RESPALDOS.md`](RESPALDOS.md), sección 4 (bucket, Job, programación), **antes de cargar datos reales** |
| P0-2 | **Rama sin integrar** | `feat/postgresql-esquema` está 30 commits por delante de `mvp-v2`, sin divergencia (admite un avance rápido), y 92 por delante de `main`. Los commits de consolidación son locales: CI no corre hasta publicarlos | Publicar la rama, revisar en un PR e integrar en `mvp-v2`, y después en `main`, antes de abrir ramas de módulos nuevos |
| P0-3 | **Corte a São Paulo sin decidir** | El UAT público sigue en Oregón, con lecturas de 1,1 s. São Paulo tiene una Orden creada después del reinicio (`OR-000001`, abierta, de la prueba manual de la vista previa) | Decidir si se conserva o se reinicia, y ejecutar el corte ([`MIGRACION_SUPABASE_SAO_PAULO.md`](MIGRACION_SUPABASE_SAO_PAULO.md), sección 16). Cada módulo nuevo se desarrolla contra una sola base |

## P1

| # | Pendiente | Afecta a | Acción sugerida |
|---|---|---|---|
| P1-1 | **Configuración solo por SQL:** tipos de reparación, precios, garantías por tipo, insumos, estaciones, medios de pago y textos legales no tienen API de escritura ni pantalla | Configuraciones operativas, garantías, compras e inventario | ABM de catálogos con rol Administración, auditoría (`accion_usuario`) y bajas lógicas (los catálogos ya tienen `activo` y triggers «sin borrado») |
| P1-2 | **Catálogo de Ventas como copia efímera:** JSON en el contenedor desde Google Sheets, sincronizado a mano después de cada despliegue. Obliga a **una sola instancia** de Cloud Run (también por el limitador por DNI en memoria) | Integración con datos de ventas, garantías de venta, escalado | Persistir el catálogo en PostgreSQL (tabla y sincronización programada o al arrancar) y mover el limitador a la base; después, permitir más de una instancia |
| P1-3 | **Sin paginación:** `GET /api/orders` y el detalle de un insumo cargan todo; las reservas incluyen Órdenes cerradas | Reporting, inventario, volumen real | Paginación por cursor y filtros en el servidor ([`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 4) |
| P1-4 | **Sin envío de mensajes:** WhatsApp existe solo como canal registrado de una decisión o un aviso; no hay proveedor, cola ni reintentos | WhatsApp | Tabla de salida (outbox) transaccional con idempotencia y un proceso de envío con reintentos. Credenciales del proveedor en Secret Manager |
| P1-5 | **Garantías de venta no modeladas:** la garantía de reparación existe (plazo por tipo, check-in, ajuste con auditoría, comprobante); la de venta no tiene datos de origen ni vínculo con el equipo vendido | Garantías RMA y de venta, ventas | Definir en `business/` (fuente funcional) el vínculo venta-equipo-garantía antes de implementar; depende de P1-2 |
| P1-6 | **Equipos internos (RT_INTERNO):** existe el origen y la Orden sin cobro; falta el buscador técnico (P-01) y un inventario de equipos propios | Equipos internos Rosario Tecno | [`pendientes-producto.md`](pendientes-producto.md), P-01 |
| P1-7 | **Reporting:** el historial (`evento_negocio`, equivalencias) da trazabilidad por Orden, pero no hay consultas agregadas ni exportación | Reporting y trazabilidad | Vistas o consultas de solo lectura sobre PostgreSQL, con un rol de lectura separado de `rma_api` |
| P1-8 | **Privilegios heredados de `PUBLIC`:** `rma_api` hereda `TEMP`, `UPDATE` sobre `pg_settings` y funciones de sesión | Seguridad de datos reales | Política de revocación ([`ESTADO_PROYECTO.md`](ESTADO_PROYECTO.md), sección E, «Privilegios») |
| P1-9 | **Rol de respaldo de solo lectura:** el Job de respaldo usaría el administrador de la base | Respaldos | Rol `rma_respaldo` con lectura de `rma`, `auth.users` y `auth.identities`, si Supabase lo permite |
| P1-10 | **Despliegue pendiente del cierre de `/docs`** (`4af9854`) y del ajuste de `04_eliminar_respaldo.sql` | Seguridad | Próximo despliegue del backend |
| P1-11 | **Largo mínimo de contraseña 10** sin confirmar en los dos proyectos de Auth | Seguridad | Confirmar en el panel |

## P2

| # | Pendiente | Nota |
|---|---|---|
| P2-1 | `ruff format --check`: 11 archivos del backend sin formatear | CI solo exige `ruff check`, la convención actual. Formatearlos en un commit aislado, sin cambios funcionales |
| P2-2 | Foto subida cuya registración falla deja un objeto huérfano | [`pendientes-producto.md`](pendientes-producto.md), nota técnica; `/photos/cleanup` lo resuelve con autorización |
| P2-3 | Doble escritura no atómica de la Orden al cerrar una reparación, solo en modo JSON | [`pendientes-producto.md`](pendientes-producto.md); no afecta a PostgreSQL |
| P2-4 | Revisiones sin tráfico con mínimo 1 instancia (`00022-vab`, `00023-zus`) | Quitar las etiquetas que no se usen después del corte y revisar el costo |
| P2-5 | Respuesta perdida de un comando (06/11): la idempotencia evita duplicados; falta revisar cómo lo informa el frontend | [`CHECKPOINT_UAT_OPTIMIZADO.md`](CHECKPOINT_UAT_OPTIMIZADO.md), sección 4 |
| P2-6 | Lecturas en lote con 2 viajes de más (hipótesis TCP) | Con São Paulo el viaje cuesta unos 3 ms: deja de importar |
| P2-7 | Pasar a Supabase Pro cuando haya datos reales | Copias físicas y PITR administradas, sin pausa por inactividad |
