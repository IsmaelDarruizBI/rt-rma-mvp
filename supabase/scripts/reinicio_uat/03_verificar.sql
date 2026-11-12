-- Verificación de solo lectura después del reinicio del UAT.
--
--   npx -y supabase@3.1.0 db query --read-only --remote=<ref> \
--     --file supabase/scripts/reinicio_uat/03_verificar.sql
--
-- Esperado: ordenes 0; las demás operativas en 0, salvo accion_usuario 1 y
-- movimiento_inventario 1 (el stock inicial); catálogos con sus cantidades;
-- 4 usuarios vinculados; conciliación de inventario sin diferencias; el
-- respaldo presente y sin permisos para anon, authenticated ni service_role.
-- La función verificar_integridad() no está habilitada para el rol de solo
-- lectura: la ejecuta 01_reiniciar.sql antes de confirmar.

select 'operativa' as grupo, t.tabla, t.filas from (
  select 'orden' tabla, count(*) filas from rma.orden
  union all select 'cliente', count(*) from rma.cliente
  union all select 'equipo', count(*) from rma.equipo
  union all select 'detalle', count(*) from rma.detalle
  union all select 'evaluacion_tecnica', count(*) from rma.evaluacion_tecnica
  union all select 'cambio_configuracion', count(*) from rma.cambio_configuracion
  union all select 'ejecucion', count(*) from rma.ejecucion
  union all select 'pago', count(*) from rma.pago
  union all select 'documento_emitido', count(*) from rma.documento_emitido
  union all select 'foto', count(*) from rma.foto
  union all select 'evento_negocio', count(*) from rma.evento_negocio
  union all select 'accion_usuario', count(*) from rma.accion_usuario
  union all select 'movimiento_inventario', count(*) from rma.movimiento_inventario
) t
union all select 'maestra', t.tabla, t.filas from (
  select 'tipo_reparacion' tabla, count(*) filas from rma.tipo_reparacion
  union all select 'modelo_equipo', count(*) from rma.modelo_equipo
  union all select 'insumo', count(*) from rma.insumo
  union all select 'medio_pago', count(*) from rma.medio_pago
  union all select 'mesa_trabajo', count(*) from rma.mesa_trabajo
  union all select 'texto_legal', count(*) from rma.texto_legal
  union all select 'tipo_evento', count(*) from rma.tipo_evento
  union all select 'equivalencia_historial', count(*) from rma.equivalencia_historial
  union all select 'usuario_rol', count(*) from rma.usuario_rol
) t
union all select 'usuarios_vinculados', null,
  (select count(*) from rma.usuario u join auth.users a on a.id = u.auth_user_id where u.activo)
union all select 'stock', c.codigo || ' fisico ' || c.stock_fisico || ' reservado ' || c.stock_reservado
                          || case when c.concilia then ' concilia' else ' NO CONCILIA' end, null
  from rma.v_conciliacion_inventario c
union all select 'proxima_orden',
  'OR-' || lpad((case when is_called then last_value + 1 else last_value end)::text, 6, '0'), null
  from rma.orden_numero_seq
union all select 'respaldo', c.relname,
  (xpath('/row/n/text()', query_to_xml(format('select count(*) as n from rma_respaldo_reinicio.%I', c.relname), false, true, '')))[1]::text::bigint
  from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'rma_respaldo_reinicio' and c.relname in ('orden', 'cliente', 'evento_negocio', 'insumo')
union all select 'respaldo_acceso_api', r.rolname, has_schema_privilege(r.rolname, 'rma_respaldo_reinicio', 'usage')::int
  from pg_roles r
 where r.rolname in ('anon', 'authenticated', 'service_role', 'rma_backend')
   and exists (select 1 from pg_namespace where nspname = 'rma_respaldo_reinicio')
order by 1, 2;
