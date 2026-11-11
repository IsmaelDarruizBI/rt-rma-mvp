-- Copia externa, de solo lectura, de los datos operativos antes del reinicio.
--
-- Contiene datos de clientes (nombres, teléfonos, documentos): guardarla
-- fuera del repositorio, en una carpeta privada, y borrarla cuando ya no haga
-- falta. Complementa el respaldo dentro de la base (rma_respaldo_reinicio):
-- este archivo sobrevive aunque la base se migre o se pierda.
--
--   npx -y supabase@3.1.0 db query --read-only --remote=<ref> --output-format json \
--     --file supabase/scripts/reinicio_uat/00_exportar.sql > <carpeta privada>/rma-uat-<fecha>.json

select jsonb_build_object(
  'exportado_en', now(),
  'secuencias', jsonb_build_object(
    'orden_numero_seq', (select jsonb_build_object('last_value', last_value, 'is_called', is_called) from rma.orden_numero_seq),
    'movimiento_inventario_secuencia', (select jsonb_build_object('last_value', last_value, 'is_called', is_called) from rma.movimiento_inventario_secuencia)
  ),
  'tablas', (
    select jsonb_object_agg(
      c.relname,
      (xpath('/row/d/text()', query_to_xml(
        format('select coalesce(jsonb_agg(t), ''[]'')::text as d from rma.%I t', c.relname),
        false, true, '')))[1]::text::jsonb)
      from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'rma' and c.relkind = 'r'
       and c.relname in (
         'accion_usuario', 'ajuste_garantia', 'auditoria_tecnica', 'checkin',
         'cliente', 'control_tecnico', 'decision_cliente', 'descuento', 'detalle',
         'detalle_version', 'devolucion_dinero', 'documento_cliente',
         'documento_emitido', 'ejecucion', 'ejecucion_insumo', 'equipo',
         'evento_negocio', 'foto', 'movimiento_inventario', 'orden',
         'orden_detalle_origen', 'override_insumo', 'override_recursos', 'pago',
         'recepcion', 'recepcion_nota', 'recepcion_version', 'salida', 'toma',
         'insumo')
  )
) as respaldo;
