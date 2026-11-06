# PostgreSQL de Rosario Tecno RMA

Documentación de la persistencia en Supabase PostgreSQL que reemplaza los archivos JSON del MVP.

| Documento | Contenido |
|---|---|
| [`diseno-logico.md`](diseno-logico.md) | Diseño lógico aprobado: 45 entidades en seis módulos, decisiones G-1 a G-10 y ajustes técnicos J-1 a J-5 |
| [`diseno-fisico.md`](diseno-fisico.md) | Esquema físico: tablas, restricciones, transacciones, auditoría, pruebas y riesgos |
| [`integracion-pendientes.md`](integracion-pendientes.md) | Integración del backend: pendientes y riesgos de E1, E2 y E3, por etapa |
| [`e2-consultas-dedicadas.md`](e2-consultas-dedicadas.md) | E2: inventario de accesos, contratos de consulta, diseño del ejecutor SQL restringido para E3, implementación y QA |
| [`e3-catalogos-diseno.md`](e3-catalogos-diseno.md) | E3: ejecutor SQL restringido, pool, repositories PostgreSQL de catálogos, M3 contra Supavisor e implementación |
| [`CHECKPOINT_A4_HANDOFF.md`](CHECKPOINT_A4_HANDOFF.md) | **Para retomar el trabajo:** estado de A0 a A4, decisiones, riesgos, tareas de A3 y comandos para otra computadora |
| [`e4-e7-diseno-integrado.md`](e4-e7-diseno-integrado.md) | E4 a E7: agregado Orden, inventario transaccional, acciones e idempotencia, equivalencia, slices y plan de QA |
| [`../../supabase/README.md`](../../supabase/README.md) | Instalación: aplicar las migraciones, cargas iniciales, pruebas y usuario de conexión |

El SQL está en `supabase/migrations/` y las pruebas en `supabase/tests/`. El backend todavía no usa esta base: sigue sobre JSON hasta su adaptación.
