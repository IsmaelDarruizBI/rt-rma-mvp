# PostgreSQL de Rosario Tecno RMA

Documentación de la persistencia en Supabase PostgreSQL que reemplaza los archivos JSON del MVP.

| Documento | Contenido |
|---|---|
| [`diseno-logico.md`](diseno-logico.md) | Diseño lógico aprobado: 45 entidades en seis módulos, decisiones G-1 a G-10 y ajustes técnicos J-1 a J-5 |
| [`diseno-fisico.md`](diseno-fisico.md) | Esquema físico: tablas, restricciones, transacciones, auditoría, pruebas y riesgos |
| [`../../supabase/README.md`](../../supabase/README.md) | Instalación: aplicar las migraciones, cargas iniciales, pruebas y usuario de conexión |

El SQL está en `supabase/migrations/` y las pruebas en `supabase/tests/`. El backend todavía no usa esta base: sigue sobre JSON hasta su adaptación.
