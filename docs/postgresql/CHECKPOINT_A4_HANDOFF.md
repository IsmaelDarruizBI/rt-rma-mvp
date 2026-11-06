# Checkpoint A4: documento de continuidad

Para retomar la migración a PostgreSQL desde otra computadora o en una sesión nueva, sin repetir el discovery. Es autosuficiente para arrancar A3; el detalle está en los documentos de la sección 12.

## 1. Punto de partida

| Dato | Valor |
|---|---|
| Fecha | 05/11/2026 |
| Repositorio | `https://github.com/IsmaelDarruizBI/rt-rma-mvp` |
| Rama | `feat/postgresql-esquema` (sale de `mvp-v2`; no está mergeada) |
| Commit del código de A0 a A4 | `f8ade83` |
| Este documento | En el commit siguiente, que es el HEAD de la rama: `git log -1` |
| Siguiente trabajo | **A3**, autorizado para la próxima sesión. No empezó |

## 2. Objetivo

Pasar la persistencia del backend de archivos JSON a PostgreSQL (Supabase) sin cambiar reglas de negocio, API ni frontend. JSON sigue siendo el modo por defecto hasta la activación. No hay modo mixto: los dos modos conviven en el código, pero la aplicación usa uno u otro entero.

Plan por etapas E0 a E9 en [`ESTADO_PROYECTO.md`](../ESTADO_PROYECTO.md). E4 a E7 se organizan en dos bloques: **A = E4 + E5** (agregado Orden e inventario) y **B = E6 + E7** (idempotencia, equivalencia y activación local).

## 3. Arquitectura y decisiones

**Base técnica:** psycopg 3 síncrono con `psycopg_pool`, sin ORM. Unidad de trabajo con `ContextVar`. Consultas SQL estáticas en un registro, clasificadas `LECTURA` o `ESCRITURA`. Los services no cambian: reciben y devuelven la Orden.

**Decisiones que hay que respetar:**

| Tema | Decisión |
|---|---|
| Una transacción por comando | La carga, las validaciones, los services y el guardado van en una sola transacción. Una falla revierte todo, aunque el caso de uso la atrape |
| Guardado por agregado (DA-1) | `guardar` compara con la instantánea y emite solo `INSERT` de lo nuevo y `UPDATE` de lo mutable. Nunca borra ni reconstruye. `rma_backend` no tiene `DELETE` |
| Bloqueo y versión (DA-2) | `obtener_para_modificar` toma `FOR NO KEY UPDATE`. `rma.orden.version` sube 1 en cada `guardar` que cambia algo, también sin historial. Guardar sin cambios no escribe. El `UPDATE` de la raíz va al final y exige la versión leída |
| Acción técnica (DA-3) | Una por comando, en su transacción, creada cuando la necesita un evento. Un cambio sin historial no crea acción. En E6 se completa con la clave de idempotencia |
| Migraciones (DA-5) | Solo aditivas. Las filas históricas no se reescriben |
| Medios de pago (DA-10) | Son filas referenciables, cargadas por migración |
| Inventario (DI-1, DI-2, DI-3) | El libro de movimientos es la fuente de verdad; disponibilidad con bloqueo ordenado por `clave`; H-1 aprobado: un ajuste no deja el disponible negativo |

**QA-A2-H1: procedencia obligatoria.** No confundir con **H-1**, que es la regla de stock negativo. Una Orden que ya existe solo se guarda si viene de `obtener_para_modificar` en la misma transacción. Una Orden nueva se inserta sin instantánea. Cualquier otra cosa da `PersistenciaError`, no escribe nada e invalida el comando: una lectura de `obtener`, una Orden reconstruida, una de otra transacción u otra Orden, o una Orden marcada con otro código, que no se convierte en alta.

**Marca interna.** Comprobar que existe una instantánea no alcanza, porque el contenido no distingue un valor viejo de un cambio legítimo, y `updated_at` puede retroceder. `obtener_para_modificar` entrega la Orden con una marca propia de la transacción, en `__dict__`, fuera de los campos:
- no cambia el modelo, la igualdad ni lo que se serializa;
- `model_copy` y `deepcopy` la conservan, y así modifican todos los services;
- reconstruir la Orden la pierde, y entonces se rechaza.

Depende de pydantic. Verificado con 2.13.5: al actualizarlo, las pruebas `test_h1_la_marca_*` y `test_h1_una_orden_reconstruida_se_rechaza` dicen si sigue valiendo. **Regla para el código nuevo:** un service nunca reconstruye una Orden existente con `OrdenReparacion(...)` o `model_validate`.

**Orden de bloqueos (A2-3).** Para modificar: **Orden → Cliente → Documento → Equipo → insumos por `clave`**. En un alta: Cliente → Documento → Equipo, y después se inserta la Orden. Un comando que toca varias Órdenes usa una transacción por Orden. Las pruebas `test_a2_3_*` verifican el orden.

**`FOR UPDATE` no se usa de forma general.** Choca con el `KEY SHARE` de las claves foráneas: dos transacciones con `KEY SHARE` que después piden `FOR UPDATE` terminan en deadlock (reproducido). Una fila que otras referencian se bloquea con `FOR NO KEY UPDATE`. El trigger `foto_limite_por_orden` ya lo usa, y sigue sosteniendo el límite de 10 fotos.

**Mutabilidad del agregado:**

| Parte | Regla |
|---|---|
| Raíz | Mutable, salvo origen, Orden de origen, Detalles de origen y fecha de alta |
| Recepción | Mutable hasta decidir la custodia. Después, `rma.recepcion` no se actualiza |
| Estado de Detalles, tomas y ejecuciones en curso | Mutable. Una definición cambia solo con una versión nueva |
| Historial, versiones de definición, decisiones, ajustes, controles, insumos utilizados | Solo crecen |
| Versiones, notas y check-in de recepción, fotos, documentos emitidos | Solo crecen, con `posicion` |
| Salida | Una fila por Orden, inmutable |

En cada lista que solo crece, lo guardado tiene que ser el principio de lo que llega. Si no, `PersistenciaError`. Una Orden cerrada no se modifica: `ConflictoDeEscrituraError`.

**Errores (L-3):**

| Caso | Error | HTTP |
|---|---|---|
| Serialización, deadlock | Conflicto reintentable | 409 |
| Bloqueo agotado | Conflicto reintentable, con mensaje propio | 409 |
| Clave única de negocio | Conflicto «ya existe» | 409 |
| Clave primaria, CHECK, clave foránea, NOT NULL, triggers | `RestriccionDeIntegridadError` | 500 genérico |
| Valor inválido (clase 22) | `DatosInvalidosError` | 500 genérico |

El cliente nunca recibe nombres de restricciones ni detalles SQL: quedan en `sqlstate`, `restriccion` y el log. Si un rechazo de la base debe llegar al usuario, un service tiene que validarlo antes.

## 4. Qué está hecho

| Parte | Contenido |
|---|---|
| A0 | Migración aditiva, numeración sin truncar, `currval` y `lastval` prohibidos, acción técnica, almacén por transacción, medios de pago como filas, lectura breve en `REPEATABLE READ` |
| A1 | `PostgresOrdenReparacionRepository`: alta y lectura con una consulta por tabla, sin N+1 |
| A2 | `obtener_para_modificar`, guardado incremental, versión, listas que solo crecen |
| QA-A2-H1 y L-3 | Procedencia obligatoria y clasificación de errores, aprobadas |
| A4 | Recepción y sus versiones, notas, check-in, fotos, documentos con reemplazos, entrega y devolución. Aprobado |

**Mapeos de A4 que no son directos:**
- `recepcion_version.datos` (JSONB) guarda `equipo` y `datos`.
- `datos.checkin` se reconstruye: el último registro de `rma.checkin` o, si no hay, `checkin_ingreso`.
- `entrega` o `devolucion`: decide el estado, porque el `tipo` no las distingue. `entrega` solo existe con ENTREGADA.
- `documento_emitido.contenido` se escribe con `model_dump(mode="json")`: los importes son texto, nunca `float`.
- `reemplaza_a` es código en el dominio y `uuid` en la tabla.
- `plantilla_version` es opcional: el dominio no la registra y no se inventa.

**Sigue sin soporte:** `guardar` rechaza pagos, devoluciones de dinero y descuentos (A3), y movimientos de insumo (A6 y A7). Las consultas dedicadas de E2 responden «llega en A5». Por eso los comandos del taller y de cobro todavía no corren sobre PostgreSQL.

## 5. Migraciones

15 archivos en `supabase/migrations/`, aplicados en orden de nombre:

| Archivos | Contenido | DEV/UAT remoto |
|---|---|---|
| `20261102000100` a `20261102001200` (12) | Esquema base, vistas, acceso y datos de referencia | Aplicadas |
| `20261105000100_e3_catalogos.sql` | `insumo.clave`, `orden` en usuarios y medios de pago. Tiene una guarda sobre datos existentes | **No aplicada** |
| `20261106000100_e4_agregado.sql` | A0 | **No aplicada** |
| `20261106000200_e4_recepcion_documentos.sql` | A4 | **No aplicada** |

Las tres últimas solo se aplicaron y verificaron en PostgreSQL local.

## 6. Supabase e infraestructura

- DEV/UAT tiene el esquema inicial (las 12 primeras migraciones). No hay datos operativos históricos que migrar.
- PostgreSQL sigue desactivado: `RMA_PERSISTENCIA=postgres` detiene el arranque. UAT sigue en Cloud Run y Vercel, sobre JSON.
- El rol `rma_api` y el secreto de conexión están en GCP Secret Manager. Cloud Run todavía no los usa.
- El objetivo posterior es actualizar o inicializar el esquema remoto y desplegar. Son pasos aparte, sin autorización todavía (sección 9).

## 7. Pruebas

Última ejecución, sobre el código de `f8ade83`, con PostgreSQL 17 local:

| Conjunto | Resultado |
|---|---|
| Suite PostgreSQL local | 610 pasan |
| Suite JSON | 1661 pasan, 249 se saltean (las de PostgreSQL, sin la base) |
| Pruebas SQL de Supabase | Incluidas en la suite PostgreSQL (`test_pruebas_sql_supabase.py`) |
| `ruff check` | Sin errores |
| `ruff format --check` de los archivos del checkpoint | Sin errores. Sobre todo el backend marca 11 archivos anteriores, que no son de este trabajo |
| `npm run validate:all` | Sin errores |

Evidencia de las revisiones, que no se repitió en esta ejecución:
- corpus de flujos reales: 139 pasos de 16 Órdenes, iguales a su ida y vuelta por JSON;
- 31 de 31 mutaciones adversas de A4, H-1 y L-3 detectadas, y 17 de 17 en la corrección de H-1;
- toda la suite JSON medida con un plugin: 5396 guardados de 46 funciones, ninguno sin marca ni fuera de las reglas del esquema, y los 72 pasos del historial con equivalencia.

Las mutaciones y el plugin fueron scripts temporales y no están en el repositorio. Las pruebas que los respaldan, sí.

## 8. Riesgos y pendientes

Detalle en [`integracion-pendientes.md`](integracion-pendientes.md), sección «Bloque A».

| # | Etapa | Pendiente |
|---|---|---|
| QA-A2-M1 | Antes de A6 | Dos líneas del mismo insumo: JSON las acepta y PostgreSQL viola `ejecucion_insumo_pkey`. Propuesta: clave `(ejecucion_id, posicion)` |
| QA-A2-M2 | Antes de A5 | Dentro de una transacción de escritura, las lecturas son READ COMMITTED y pueden mezclar dos instantes. La garantía de `bandejas.py` no se cumple en PostgreSQL |
| QA-A2-M3 | Antes de E8 | El alta de una Orden ya cerrada viola `orden_cerrada_con_fecha`. Pierde urgencia sin datos históricos |
| QA-A2-M4 | Antes de A6 | Fotos resuelto. Falta el trigger de movimientos y DI-2, que bloquean el insumo con `FOR UPDATE` |
| QA-A2-L1 | A5 | Un cliente reutilizado sin DNI cierra su documento vigente. `listar_por_dni_cliente` debe usar la copia de la Orden |
| QA-A2-L2 | Antes de E7 | Una fecha sin zona horaria se relee distinta |
| QA-A2-L4, QA-A2-L5 | Sin urgencia y E8 | Orden de Detalles por código; CHECK de cierre sin `NOT VALID` |
| A4-1 | Antes de E7, **requiere decisión** | Texto con NUL: JSON lo guarda y PostgreSQL da 500. Rechazarlo en la API cambia un contrato HTTP |
| A4-2 | A5 | `generar_comprobante_ingreso` necesita `listar_con_reservas` |
| A4-3 | E8 | `salida` de tipo `DEVOLUCION_GESTION_RT` no se puede leer. Ningún flujo la crea |
| A4-4 | A5 | Fotos y documentos se cargan completos con cada Orden. Medir |
| A4-5 | Aceptado | Filas sin `posicion` con todas sus fechas idénticas: orden estable pero arbitrario. Esas filas no existen |
| **DI-8** | Antes de A7, **requiere decisión de producto** | El esquema exige un motivo de ajuste del catálogo y la API manda texto libre. No relajar el CHECK ni implementar los ajustes de A7 sin esa decisión |
| QA-H1 en JSON | A5 y B4 | JSON no exige la procedencia. Al parametrizar `test_contrato_ordenes.py` hay que tratar esa diferencia |
| A2-2, A2-5 | B4 y B1 | Vinculación por constructor en JSON; nombres de operación de la acción |

## 9. Restricciones vigentes

**Sin autorización explícita para esa acción:**
- no aplicar migraciones remotas ni usar `supabase db push`;
- no tocar Supabase remoto, Cloud Run, Vercel ni producción;
- no activar `RMA_PERSISTENCIA=postgres` ni introducir modo mixto;
- no hacer deploy ni merge;
- no modificar reglas de negocio, dominio, frontend ni contratos HTTP;
- no hacer push al remoto `functional` (`rt-rma-app`): nunca.

**La migración de E3 no se aplica en remoto** sin el procedimiento de identidad de E8.

**Seguridad.** El repositorio es público:
- ninguna credencial, cadena de conexión completa ni ref de proyecto nuevo en documentos o logs;
- no desactivar la verificación TLS;
- `app/backend/.env.example` queda fuera de los commits: es local, con variables `RMA_DB_*` que la aplicación no usa.

**Forma de trabajo:**
- Commit y push solo cuando el usuario lo pide.
- Usar únicamente PostgreSQL local descartable: `RMA_TEST_DATABASE_URL` rechaza una URL remota.
- Aplicar `ruff format` solo a los archivos tocados, nunca a una carpeta entera.
- Una prueba no depende de que dos fechas reales sean distintas: en Windows el reloj avanza cada ~15 ms. Pasó en A4.
- Una mutación se evalúa por **qué prueba** la detectó, no solo por el total: así apareció la inestabilidad de A4.
- Guardar el log de una corrida, no solo el total: las fallas intermitentes no se repiten a pedido.
- Pasar `tests/postgres` entero: intercalar archivos de `tests/` entre los suyos hace perder su `conftest`.

## 10. A3: alcance y primeras tareas

**Alcance** ([diseño](e4-e7-diseno-integrado.md), sección 8): pagos y medios de pago, anticipos y pagos parciales, anulación, devoluciones de dinero, descuentos, y las referencias del historial a pagos. Con escritura incremental, atomicidad, rollback, control de versión, equivalencia con JSON y comandos reales. **Aceptación del diseño:** saldos y estado de pago idénticos; saldo de `v_orden_saldo` igual al del dominio; duplicados por `operacion_id`.

No se agregan reglas funcionales: las reglas son las de `app/services/pagos.py` y `app/services/descuentos.py`.

**Lo que ya se sabe del esquema y del dominio:**

| Dominio | Tabla | A resolver |
|---|---|---|
| `resumen_pago.pagos` (`Pago`) | `pago` | Sin `operacion_id` ni `posicion`. `metodo` es el código de `medio_pago`. `anulacion` es lo único mutable: un trigger permite completarla una sola vez |
| `resumen_pago.devoluciones` (`DevolucionDinero`) | `devolucion_dinero` | Sin `operacion_id` ni `posicion`. `pago_id` es código en el dominio y `uuid` con clave compuesta en la tabla. `medio` es el código del medio |
| `descuentos` (`RegistroDescuento`) | `descuento` | Sin `posicion` y sin código. `tipo` y `valor` pueden ser nulos, juntos |
| `historial[].pago_id` | `evento_negocio.pago_id` | `_historial` hoy lo rechaza. La lectura ya hace el `JOIN` |

**Primeras tareas:**

1. Leer la fila A3 de la sección 8 del diseño, DA-10, y la fila de `operacion_id` de la sección 4.3.
2. Leer `app/domain/models/pagos.py`, `descuentos.py`, `app/services/pagos.py`, `descuentos.py`, `app/application/finanzas.py` y `registrar_pago_de_orden` en `cierre.py`, y en el esquema `20261102000800_m4_finanzas_documentos.sql` y `v_orden_saldo`.
3. Migración aditiva nueva: `operacion_id` en `pago` y `devolucion_dinero`; `posicion` con índice único parcial en las tres tablas, como en A4.
4. `ordenes_lectura.py`: tres consultas más, una por tabla, y `Instantanea` con los `uuid` de los pagos.
5. `ordenes.py`: resolver medios de pago por código; insertar pagos, devoluciones y descuentos; actualizar solo la anulación; quitar los rechazos de `_exigir_partes_soportadas` y de `_historial`, y pasar `pago_id` al evento.
6. `corpus_ordenes.py`: `proyectar` deja de quitar pagos, descuentos y pasos con `pago_id`. Sumar flujos de anticipo, pago parcial, anulación, devolución y descuento.
7. Pruebas: igualdad con JSON, saldo contra `v_orden_saldo`, comandos reales (`registrar_pago_de_orden`, `anular_pago_de_orden`, `registrar_devolucion_de_dinero`, `aplicar_descuento_de_orden`), rollback, versión, alteraciones adversas y mutaciones.
8. Evaluar `devolucion_dinero_validar`: bloquea el pago con `FOR UPDATE`, el patrón de QA-A2-M4. Bajo el bloqueo de la Orden no debería haber ciclo; hay que verificarlo.

**Después de A3:** QA integral de recepción, taller y entrega, y sigue A5.

## 11. Configurar otra computadora

Requisitos: Git, Python 3.11 o posterior, Node.js. Comandos para bash (en Windows, Git Bash).

```bash
git clone https://github.com/IsmaelDarruizBI/rt-rma-mvp.git
cd rt-rma-mvp
git switch feat/postgresql-esquema
npm install

cd app/backend
python -m venv .venv
source .venv/Scripts/activate       # Linux o macOS: source .venv/bin/activate
pip install -e ".[dev,postgres]"
pytest -q                           # JSON; las de PostgreSQL se saltean
ruff check .
```

**PostgreSQL local descartable.** Fuera del repositorio. Hace falta un servidor 15 o posterior, con un usuario que pueda crear bases y roles. Este camino es el que se verificó:

```bash
mkdir ~/pg-rma && cd ~/pg-rma
npm init -y
npm install embedded-postgres@17.10.0-beta.17
BIN=$(ls -d node_modules/@embedded-postgres/*/native/bin)
"$BIN/initdb" -D data -U postgres -A trust -E UTF8 --locale=C
"$BIN/pg_ctl" -D data -o "-p 54329 -c listen_addresses=127.0.0.1" -l pg.log -w start
```

Para detenerlo: `"$BIN/pg_ctl" -D data -m fast stop`.

**Suite PostgreSQL**, desde `app/backend`:

```bash
export RMA_TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:54329/postgres
pytest -q tests/postgres tests/test_unidad_de_trabajo.py \
  tests/test_errores_postgres.py tests/test_escrituras_concurrentes.py \
  tests/test_contrato_ordenes.py tests/test_e2_consistencia_lecturas.py \
  tests/test_e2_equivalencia.py tests/test_e3_sql_y_ajustes.py \
  tests/test_generador_cargas.py
```

Tarda unos 4 minutos. Cada corrida crea bases `rma_prueba_<hex>` y las borra. Para la suite JSON, sin la variable: `unset RMA_TEST_DATABASE_URL`.

**Validaciones funcionales,** desde la raíz: `npm run validate:all`.

No hace falta Supabase ni ninguna credencial.

## 12. Qué leer antes de modificar código

1. [`AGENTS.md`](../../AGENTS.md) y [`.specify/memory/constitution.md`](../../.specify/memory/constitution.md).
2. [`docs/ESTADO_PROYECTO.md`](../ESTADO_PROYECTO.md).
3. Este documento.
4. [`e4-e7-diseno-integrado.md`](e4-e7-diseno-integrado.md): decisiones (sección 3), agregado (4), slices (8), checkpoint de A2 (13) y A4 (14).
5. [`integracion-pendientes.md`](integracion-pendientes.md).
6. [`diseno-logico.md`](diseno-logico.md) y [`diseno-fisico.md`](diseno-fisico.md), para el esquema.
7. Código: `app/backend/app/storage/postgres/ordenes.py`, `ordenes_lectura.py`, `acciones.py`, `errores.py`, y las pruebas `tests/postgres/test_ordenes_postgres.py`, `test_recepcion_documentos_postgres.py` y `corpus_ordenes.py`.
