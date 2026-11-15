-- Verificación de solo lectura del UAT: antes y después de migrar, del
-- reinicio y de la limpieza del E2E.
--
--   npx -y supabase@3.1.0 db query --read-only --remote=<ref> \
--     --file supabase/scripts/reinicio_uat/03_verificar.sql
--
-- Sirve con cualquier cantidad de migraciones (23 antes de la macroiteración
-- integral, 35 después): cada tabla se cuenta solo si existe. Las que todavía
-- no existen salen con grupo «ausente» y filas vacías, en lugar de hacer
-- fallar la consulta. La primera fila informa las migraciones aplicadas.
--
-- Esperado después de un reinicio: ordenes 0; las demás operativas en 0, salvo
-- accion_usuario 1 y movimiento_inventario 1 (el stock inicial). Después de
-- la limpieza del E2E (06_limpiar_e2e.sql): los mismos conteos que antes del
-- E2E. Siempre: 4 usuarios vinculados, inventario conciliado, y los esquemas
-- de respaldo o de línea de base sin acceso para anon, authenticated,
-- service_role ni rma_backend.
--
-- La función verificar_integridad() no está habilitada para el rol de solo
-- lectura: la ejecutan 01_reiniciar.sql y 06_limpiar_e2e.sql antes de
-- confirmar.

with tablas (grupo, tabla) as (
  values
    ('operativa', 'orden'), ('operativa', 'cliente'), ('operativa', 'equipo'),
    ('operativa', 'detalle'), ('operativa', 'evaluacion_tecnica'),
    ('operativa', 'cambio_configuracion'), ('operativa', 'ejecucion'),
    ('operativa', 'pago'), ('operativa', 'documento_emitido'),
    ('operativa', 'foto'), ('operativa', 'evento_negocio'),
    ('operativa', 'accion_usuario'), ('operativa', 'movimiento_inventario'),
    -- Macroiteración integral (migraciones 20261113000100 a 20261115000100).
    ('operativa', 'lote_insumo'), ('operativa', 'orden_compra'),
    ('operativa', 'solicitud_compra'), ('operativa', 'comunicacion_cliente'),
    ('operativa', 'reclamo_garantia'), ('operativa', 'checklist_registro'),
    ('maestra', 'tipo_reparacion'), ('maestra', 'modelo_equipo'),
    ('maestra', 'insumo'), ('maestra', 'medio_pago'),
    ('maestra', 'mesa_trabajo'), ('maestra', 'texto_legal'),
    ('maestra', 'tipo_evento'), ('maestra', 'equivalencia_historial'),
    ('maestra', 'usuario_rol'),
    -- Macroiteración integral.
    ('maestra', 'proveedor'), ('maestra', 'tipo_equipo'), ('maestra', 'permiso')
)
select 'esquema' as grupo, 'migraciones' as tabla, count(*) as filas
  from supabase_migrations.schema_migrations
union all
select case when to_regclass(format('rma.%I', t.tabla)) is null then 'ausente' else t.grupo end,
       t.tabla,
       case when to_regclass(format('rma.%I', t.tabla)) is not null then
         (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from rma.%I', t.tabla), false, true, '')))[1]::text::bigint
       end
  from tablas t
union all select 'usuarios_vinculados', null,
  (select count(*) from rma.usuario u join auth.users a on a.id = u.auth_user_id where u.activo)
union all select 'stock', c.codigo || ' fisico ' || c.stock_fisico || ' reservado ' || c.stock_reservado
                          || case when c.concilia then ' concilia' else ' NO CONCILIA' end, null
  from rma.v_conciliacion_inventario c
union all select 'proxima_orden',
  'OR-' || lpad((case when is_called then last_value + 1 else last_value end)::text, 6, '0'), null
  from rma.orden_numero_seq
union all select 'respaldo', n.nspname || '.' || c.relname,
  (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from %I.%I', n.nspname, c.relname), false, true, '')))[1]::text::bigint
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname in ('rma_respaldo_reinicio', 'rma_linea_base_e2e')
   and c.relname in ('orden', 'cliente', 'evento_negocio', 'insumo', 'foto')
union all select 'respaldo_acceso_api', s.nspname || ' ' || r.rolname,
  has_schema_privilege(r.rolname, s.nspname, 'usage')::int
  from pg_roles r cross join pg_namespace s
 where r.rolname in ('anon', 'authenticated', 'service_role', 'rma_backend')
   and s.nspname in ('rma_respaldo_reinicio', 'rma_linea_base_e2e')
order by 1, 2;
