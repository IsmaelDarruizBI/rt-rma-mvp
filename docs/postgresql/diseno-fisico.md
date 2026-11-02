# Rosario Tecno RMA — Diseño físico PostgreSQL

**Estado:** aplicado el 02/11/2026 en el proyecto Supabase DEV/UAT `rt-rma-db`, con las cargas operativas iniciales. El backend todavía no lo usa. Producción se crea más adelante.

**Fecha:** 02/11/2026.
- **Revisión 1:** primera versión del esquema.
- **Revisión 2:** auditoría previa a aplicar las migraciones.

**Fuentes:**
- Funcional: `rt-rma-mvp` `mvp-v2` `6516d4c`.
- Diseño lógico: `docs/postgresql/diseno-logico.md`, aprobado, con los ajustes J-1 a J-5.

**Instalación y migraciones:** `supabase/README.md`.

---

## 1. Resumen

| Concepto | Valor |
|---|---|
| Esquema | `rma`, no expuesto por la API de datos de Supabase |
| Tablas | 45, las del diseño lógico, en seis módulos |
| Columnas | 426, todas con comentario en español; 524 comentarios en total entre tablas, vistas y columnas |
| Restricciones | 45 claves primarias, 100 claves foráneas, 39 únicas, 137 CHECK |
| Índices | 143, de los cuales 8 son únicos parciales |
| Triggers | 68 |
| Funciones | 16, todas con `search_path` fijo |
| Vistas | 6 |
| Migraciones | 12 |
| Cargas iniciales | 4 de referencia operativa y 1 de desarrollo, todas reproducibles |
| Pruebas | 6 archivos SQL y una prueba de concurrencia |

Las seis vistas son `v_detalle_version_vigente`, `v_reserva_pendiente`, `v_ejecucion_insumo_consumo`, `v_orden_saldo`, `v_conciliacion_inventario` y `v_historial_visible`.

### Identificadores (G-1)

- **`id uuid`** (`gen_random_uuid()`) es la clave de todas las relaciones.
- **`codigo text unique`** guarda el identificador público actual:
  - OR-000001, por la secuencia `orden_numero_seq`;
  - DET-001, único dentro de su Orden;
  - MOD-0001;
  - los códigos de catálogo;
  - los IDs que usa hoy la API.
- **Excepciones:**
  - las tablas de relación usan la clave compuesta de sus referencias;
  - `recepcion` y `salida` usan `orden_id`;
  - `empresa` tiene una sola fila.

### Tipos

| Dato | Tipo |
|---|---|
| Importes en pesos | `numeric(14,2)` |
| Cantidades | `numeric(12,3)` |
| Fechas | `timestamptz` |
| Estados y tipos | `text` con `CHECK` |
| Copias cerradas (documentos, versiones de recepción, textos legales, datos de eventos) | `jsonb` |
| Listas | `text[]` |

### Inmutabilidad

| Clase | Tablas | Mecanismo |
|---|---|---|
| Inmutables | Eventos, libro de inventario, versiones, decisiones, controles, ajustes, check-in, salida, fotos, notas, versiones de recepción, override, declarado de Ejecución, devoluciones, descuentos, documentos, textos legales, auditoría | Trigger que rechaza UPDATE y DELETE para cualquier usuario, más permisos del backend de solo SELECT e INSERT |
| Se completan una vez | `accion_usuario` (respuesta y Orden), `pago` (anulación), `documento_cliente` (cierre de vigencia), `ejecucion` (mientras está en curso), `recepcion` (hasta decidir la custodia) | Triggers específicos y permisos por columna |
| Estado actual | `orden`, `detalle`, `toma`, `cliente`, `equipo`, catálogos | UPDATE permitido; DELETE prohibido. Una Orden cerrada no cambia, salvo su contador de eventos |
| Saldos de insumo | `stock_fisico`, `stock_reservado` | Solo los cambia el trigger del libro; el backend no tiene permiso de UPDATE sobre esas columnas |

---

## 2. Tablas y relaciones

«comp.» indica una clave foránea compuesta que valida que el registro relacionado pertenezca a la misma Orden o al mismo Detalle.

| Módulo | Tabla | Referencias principales | Restricciones destacadas |
|---|---|---|---|
| M1 | `cliente` | `usuario` | Física o jurídica; sin borrado |
| M1 | `documento_cliente` | `cliente`, `tipo_documento` (comp. con exige_unicidad), sí misma | Uno vigente por Cliente y tipo; número vigente único entre Clientes; solo se cierra la vigencia |
| M1 | `modelo_equipo` | — | MOD-nnnn; marca, modelo y variante únicos |
| M1 | `equipo` | `modelo_equipo` | Capacidad en GB más el texto original |
| M2 | `orden` | `cliente`, `equipo`, `modelo_equipo`, sí misma | Cliente según el origen; garantía con Orden de origen; cerrada no cambia |
| M2 | `orden_detalle_origen` | `orden` (comp.), `detalle` (comp.) | El Detalle reclamado es de la Orden de origen |
| M2 | `recepcion`, `recepcion_version`, `recepcion_nota` | `orden`, `usuario` | Una sola decisión de custodia; decidida no cambia |
| M2 | `checkin`, `salida`, `foto` | `orden`, `usuario` | Inmutables; una salida por Orden; hasta 10 fotos |
| M2 | `detalle` | `orden`, sí mismo, `usuario` | Código por Orden; cancelación y control completos |
| M2 | `detalle_version` | `detalle`, `tipo_reparacion`, sí misma (comp.) | Número único por Detalle; inmutable |
| M2 | `decision_cliente`, `ajuste_garantia` | `detalle_version` o `detalle`, `usuario` | Inmutables |
| M2 | `toma` | `orden`, `usuario`, `mesa_trabajo` | Una ACTIVA por Orden |
| M2 | `ejecucion` | `detalle`, `detalle_version` y `toma` (comp.) | Una EN_PROGRESO por Orden; terminada no cambia |
| M2 | `ejecucion_insumo`, `control_tecnico` | `ejecucion` (comp.), `insumo`, `detalle` | Solo lo declarado; inmutables |
| M3 | `insumo` | — | `stock_fisico >= stock_reservado >= 0`; nace en cero |
| M3 | `movimiento_inventario` | `insumo`, `orden`, `detalle` y `ejecucion` (comp.), sí mismo (comp.), `motivo_ajuste`, `usuario`, `accion_usuario` | Vínculos por tipo; DESPERDICIO y DEVOLUCION sin operación; inmutable; sin ON CONFLICT |
| M3 | `override_recursos`, `override_insumo` | `detalle_version` (comp.), `insumo` | Vale para una versión; cálculo del impacto verificado |
| M4 | `pago`, `devolucion_dinero` | `orden`, `medio_pago`, `usuario` | Solo cliente externo; importe fijo; anulación única; devolución sin superar el pago |
| M4 | `descuento` | `orden`, `usuario` | Porcentaje hasta 100; inmutable |
| M4 | `documento_emitido` | `orden`, `texto_legal`, sí mismo (comp.) | Orden, tipo y versión únicos; versión nueva con motivo |
| M5 | `accion_usuario` | `usuario`, `orden` | Clave de idempotencia única entre las confirmadas |
| M5 | `evento_negocio` | `accion_usuario` (comp. con CONFIRMADA), `orden`, `tipo_evento` y otras | Secuencia única por Orden, asignada por la base; inmutable |
| M5 | `tipo_evento`, `equivalencia_historial`, `auditoria_tecnica` | `tipo_evento`, `usuario` | 51 tipos de negocio y 1 técnico; 84 equivalencias |
| M6 | `usuario`, `rol`, `usuario_rol` | — | Email único; cuatro roles |
| M6 | `mesa_trabajo`, `mesa_tipo_reparacion`, `tipo_reparacion`, `tipo_reparacion_insumo`, `medio_pago`, `tipo_documento`, `motivo_ajuste`, `empresa`, `texto_legal` | — | Sin borrado; texto legal inmutable |

**Ciclos:** no hay ciclos de claves foráneas entre tablas distintas (prueba `10_esquema.sql`).

**Claves foráneas sin índice propio (48):** apuntan a usuarios, catálogos o registros que nunca se borran ni se consultan en sentido inverso, como `registrado_por`, `medio_pago_id` o `texto_legal_id`. No se indexan sin evidencia de uso; el asesor de rendimiento de Supabase las va a informar.

**Orden de creación:**
1. M6 configuración;
2. M3 insumos;
3. M5 base;
4. M1;
5. M2;
6. M3 libro y override;
7. M4;
8. M5 eventos;
9. vistas;
10. acceso;
11. datos de referencia.

---

## 3. Migraciones y datos iniciales

| Archivo | Contenido |
|---|---|
| `20261102000100_base.sql` | Esquema y funciones de inmutabilidad |
| `20261102000200_m6_usuarios_configuracion.sql` | Usuarios, roles y configuración |
| `20261102000300_m3_insumos.sql` | Insumos e insumos previstos |
| `20261102000400_m5_trazabilidad_base.sql` | Acciones, tipos de evento, equivalencias, auditoría |
| `20261102000500_m1_clientes_equipos.sql` | Clientes, documentos, modelos, equipos |
| `20261102000600_m2_ordenes_reparaciones.sql` | Órdenes y reparaciones |
| `20261102000700_m3_movimientos_override.sql` | Libro de inventario y override |
| `20261102000800_m4_finanzas_documentos.sql` | Pagos, devoluciones, descuentos, documentos |
| `20261102000900_m5_eventos.sql` | Eventos e historial visible |
| `20261102001000_vistas_conciliacion.sql` | Valores calculados e integridad |
| `20261102001100_acceso.sql` | Rol `rma_backend` y permisos |
| `20261102001200_datos_referencia.sql` | Roles, DNI, 52 tipos de evento, 84 equivalencias |

**Datos de referencia (en las migraciones):** iguales en todos los entornos.

**Datos operativos iniciales (`supabase/seeds/referencia_operativa/`), válidos para producción:**
- 5 medios de pago;
- empresa;
- Términos y Condiciones v1, con los 19 apartados copiados sin cambios de `terminosCondiciones.ts`;
- 36 modelos técnicos;
- 4 motivos de ajuste aprobados.

**Datos de desarrollo (`supabase/seeds/desarrollo/`):** ficticios; nunca se cargan en producción.

**Reproducibilidad:**
- Todas las cargas se pueden aplicar más de una vez: la segunda no cambia nada (probado).
- Las de catálogos usan `ON CONFLICT DO NOTHING`.
- El stock inicial de desarrollo inserta solo los ingresos que faltan, sin `ON CONFLICT`, que el libro no admite.

### Motivos de ajuste (aprobados el 02/11/2026)

| Código | Descripción | Operaciones permitidas |
|---|---|---|
| `RECUENTO` | Diferencia de recuento físico | Ajuste positivo y negativo |
| `ERROR_CARGA` | Corrección de un error de carga | Ajuste positivo y negativo |
| `DANIO` | Insumo dañado en el depósito | Solo ajuste negativo |
| `PERDIDA` | Insumo perdido o faltante | Solo ajuste negativo |

Los ingresos de stock no usan motivo de ajuste; llevan su motivo u origen en texto.

---

## 4. Restricciones implementadas en la base

**Inventario.**
- `CHECK (stock_reservado >= 0)` y `CHECK (stock_fisico >= stock_reservado)`.
- **El trigger `aplicar_movimiento_inventario`:**
  1. bloquea el insumo;
  2. rechaza un código repetido, también bajo `ON CONFLICT`;
  3. valida que consumos, liberaciones y desperdicios cierren una RESERVA del mismo insumo, Orden y Detalle sin superar lo pendiente, y que una devolución no supere lo consumido;
  4. valida el sentido del motivo;
  5. rechaza un disponible negativo;
  6. actualiza los saldos;
  7. guarda los saldos anterior y resultante.
- El insumo nace en cero.
- DESPERDICIO y DEVOLUCION están bloqueados por una restricción que se quita al habilitarlos.
- La conciliación con el libro está en `v_conciliacion_inventario` y `rma.verificar_integridad()`.

**Concurrencia.**
- Índices únicos parciales:
  - una toma ACTIVA por Orden;
  - una Ejecución EN_PROGRESO por Orden;
  - un documento vigente por Cliente y tipo;
  - un número de documento vigente único;
  - una clave de idempotencia confirmada.
- Bloqueos de fila:
  - el libro bloquea el insumo;
  - la secuencia de eventos y el límite de fotos bloquean la Orden;
  - la comprobación de Orden abierta toma un bloqueo compartido de la Orden, así que un cierre concurrente la espera.

**Eventos e idempotencia.**
- Clave foránea `(accion_id, accion_resultado)` hacia `accion_usuario (id, resultado)` con la constante `CONFIRMADA`: un evento no puede apuntar a una acción rechazada, y una transacción fallida no deja eventos.
- La secuencia por Orden la asigna la base.
- La clave de idempotencia es única por usuario entre las acciones confirmadas.
- La acción admite completar una vez su respuesta y su Orden.

**Documentos.**
- `texto_legal` es inmutable, con versión.
- `documento_emitido` guarda el contenido, el texto legal, la plantilla y, previstos, el PDF y su huella.
- **La reproducción visual exacta requiere conservar la plantilla de esa versión o guardar el PDF original.** No se desarrolló un generador nuevo de PDF.

**Cierre.**
- Una Orden cerrada no cambia y no admite registros nuevos, salvo los eventos de su propio cierre.

**Acceso.**
- El rol `rma_backend` no borra y no actualiza las tablas inmutables ni los saldos.
- `anon`, `authenticated` y `service_role` no tienen USAGE sobre el esquema.
- Las funciones que tocan columnas protegidas son `security definer` con `search_path` fijo.

---

## 5. Reglas que deben implementar los servicios FastAPI

1. **Una transacción por comando,** con acción, cambios, movimientos, documentos y eventos. Resuelve la doble escritura de los pasos 210 y 211.
2. **Bloqueo previo con `select ... for update`,** en este orden: Cliente (si cambia), Orden, insumos de menor a mayor id.
3. **Idempotencia:**
   - insertar la acción con su clave al comienzo;
   - ante una violación de unicidad, devolver la `respuesta` de la acción confirmada;
   - completar `respuesta` y `orden_id` al final.
4. **Rechazos:** revertir la transacción y registrar en una nueva la acción `RECHAZADA` y, si corresponde, `auditoria_tecnica`.
5. **Reglas de negocio:**
   - permisos por rol;
   - reserva y consumo con override según P-06;
   - devolución de dinero sin superar el saldo a favor;
   - descuento sin dejar el total por debajo de lo cobrado;
   - check-in según el origen;
   - garantía sugerida al registrar el check-in.
6. **Versiones:** crear la versión 1 junto con el Detalle y la n+1 al redefinir. La vigente sale de `v_detalle_version_vigente`.
7. **Documentos:** comprobante de entrega con el texto legal vigente y registro de `plantilla_version` (cambios H-2 y H-3).
8. **Ajuste negativo:** rechazarlo antes que la base, con un mensaje claro (cambio H-1).
9. **Cierre:** la actualización que cierra la Orden es la última de la transacción.
10. **Historial visible:** escribir `historial_*` en los eventos que hoy aparecen y leer `v_historial_visible`.
11. **Libro de inventario:** nunca usar `INSERT ... ON CONFLICT`.
12. **Conexión por el pooler en modo transacción:**
    - sin sentencias preparadas del lado del servidor (en asyncpg, `statement_cache_size=0`; en psycopg, `prepare_threshold=None`);
    - sin estado de sesión: nada de `SET` sin `LOCAL`, de bloqueos asesores de sesión ni de tablas temporales entre transacciones.

---

## 6. Auditoría y pruebas

### Resultado de la auditoría

| Área | Resultado | Probado localmente | A verificar en Supabase |
|---|---|---|---|
| Dependencias y orden de creación | Correcto; sin ciclos entre tablas | Sí: 12 migraciones sobre base vacía, varias veces | `db push --dry-run` |
| Claves foráneas e índices | 100 claves foráneas; 3 índices por Orden agregados en la auditoría (tomas, Ejecuciones, movimientos); 48 claves sin índice, justificadas | Sí | Informe del asesor de rendimiento |
| Restricciones y triggers de inventario | Correctos | Sí: `20_inventario.sql`, `40_operaciones_backend.sql` y concurrencia | — |
| Reservas y consumos | Correctos; no se puede cerrar más de lo reservado ni dejar el disponible negativo | Sí, también con transacciones simultáneas | — |
| Inmutabilidad | Correcta para eventos, documentos, movimientos, versiones y textos legales | Sí | — |
| Idempotencia | **Corregida en la auditoría:** la acción no podía completar su respuesta; ahora lo hace una sola vez | Sí, también en paralelo | — |
| `ON CONFLICT` sobre el libro | **Corregido en la auditoría:** podía aplicar saldos de un movimiento descartado; ahora se rechaza el código repetido | Sí: el reintento no cambia el stock | — |
| Orden abierta y fotos | Reforzado con bloqueo de la Orden | Sí | — |
| Permisos de `rma` y del usuario de FastAPI | Correctos; `service_role` también sin acceso | Sí, con roles simulados y un usuario de conexión `in role rma_backend` | Con los roles reales de Supabase |
| Compatibilidad con Supabase | Sintaxis válida en PostgreSQL 17.10; usa `NULLS NOT DISTINCT` (PostgreSQL 15 o posterior), `gen_random_uuid()` nativo y funciones sin `search_path` mutable | Sí, en PostgreSQL 17.10 | Versión del proyecto; permiso de `postgres` para crear el rol |
| Pooler en modo transacción | El esquema solo usa bloqueos de transacción, sin estado de sesión | No: las pruebas usaron conexiones directas | Conexión de `rma_api` por Supavisor y prueba de concurrencia a través del pooler |

### Pruebas locales

El servidor fue PostgreSQL 17.10 real, el binario oficial del paquete `embedded-postgres` 17.10.0-beta.17, en un clúster descartable.

| Prueba | Resultado |
|---|---|
| Construcción desde una base vacía: 12 migraciones, 45 tablas | Correcto |
| `10_esquema.sql`: tablas, comentarios, ciclos, datos de referencia, acceso | Correcto |
| `20_inventario.sql`: saldos, vínculos, ajuste negativo, override, conciliación, inmutabilidad | Correcto |
| `30_unicidad_eventos.sql`: documentos, exclusividades, versiones, idempotencia, eventos, pagos, documentos, cierre | Correcto |
| `40_operaciones_backend.sql`: operaciones reales como `rma_backend` (acción completada, pago, devolución, anulación, documento de Cliente, fotos, `ON CONFLICT` en el libro, eventos, borrado denegado, `service_role`) | Correcto |
| Cargas iniciales aplicadas dos veces: sin cambios y `verificar_integridad()` vacía | Correcto |
| `probar_concurrencia.cjs`, como `rma_backend`: reservas, ajuste negativo frente a ingreso, Ejecuciones, idempotencia, eventos, conciliación | Correcto |
| Las utilidades de prueba detectan una sentencia que no falla, un código de error distinto y un valor distinto | Correcto |

### Aplicación en Supabase DEV/UAT (02/11/2026)

Proyecto `rt-rma-db` (`okcscsglnujnxtgobjfw`), PostgreSQL 17.11, usado como entorno DEV/UAT.

| Verificación | Resultado |
|---|---|
| `db push --remote` de las 12 migraciones | Aplicadas sin errores; las 12 figuran en el historial de migraciones |
| Objetos | 45 tablas, 6 vistas, 16 funciones con `search_path` fijo, 68 triggers, 143 índices (8 únicos parciales); restricciones: 45 PK, 100 FK, 39 únicas, 137 CHECK. Iguales a la base local |
| Comentarios | 524; ninguna tabla, vista o columna sin comentario |
| Rol `rma_backend` | Creado, sin inicio de sesión |
| Acceso | `anon`, `authenticated` y `service_role` sin USAGE sobre `rma`; `rma_backend` no actualiza el libro ni los saldos y no borra eventos |
| Datos de referencia | 4 roles, DNI, 51 tipos de evento de negocio y 1 técnico, 84 equivalencias |
| Cargas operativas | 5 medios de pago, empresa, Términos y Condiciones v1 (idénticos al texto del frontend: 19 apartados, 2 destacados), 36 modelos técnicos, 4 motivos de ajuste aprobados. Sin Órdenes, Clientes, insumos, movimientos ni usuarios |
| Pruebas 10, 20, 30 y 40, en una transacción con ROLLBACK (`scripts/armar_pruebas_remotas.cjs`) | Todas correctas, incluida la restricción de disponible negativo y las operaciones como `rma_backend` |
| ROLLBACK verificado | Sin esquema `rma_pruebas`, sin la membresía temporal y con todas las tablas operativas vacías. Solo avanzó la secuencia de Órdenes, que no es transaccional |
| Asesores de Supabase | Ningún problema de seguridad. 100 avisos informativos de rendimiento, esperados: 59 claves foráneas sin índice que las cubra y 41 índices sin uso en una base vacía |

### Pendientes

- **Supabase local** (`supabase start`, `db reset`): requiere Docker.
- **Usuario `rma_api` y conexión por Supavisor** en modo transacción, con la prueba de concurrencia a través del pooler. Espera el mecanismo seguro de credenciales.
- **Volumen real,** en especial `v_orden_saldo` y `verificar_integridad()`.
- **Importación de copias de UAT** e ida y vuelta con el JSON. Requiere el repositorio PostgreSQL del backend.

---

## 7. Riesgos técnicos

1. **Plantillas de documentos.** Mientras la plantilla viva en el frontend, cambiarla altera la reimpresión de documentos ya emitidos, salvo que se conserve la versión anterior o se guarde el PDF.
2. **Orden del cierre.** El cierre de la Orden debe ser la última escritura de su transacción.
3. **Vistas de recálculo.** `verificar_integridad()` y `v_orden_saldo` recalculan todo: sirven para verificaciones; para pantallas, conviene filtrar por Orden.
4. **Override.** El impacto confirmado al autorizarlo puede diferir de la reserva real al iniciar, como hoy.
5. **Pruebas en remoto.** Las secuencias no son transaccionales: correr las pruebas avanza la numeración de Órdenes aunque todo se revierta. No se corren en producción.
6. **Herramienta de concurrencia.** La prueba necesita el paquete `pg`, que no es dependencia del proyecto.
