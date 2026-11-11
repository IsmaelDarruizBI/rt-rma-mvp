-- Vuelta atrás del reinicio del UAT: restaura los datos operativos desde el
-- esquema rma_respaldo_reinicio que creó 01_reiniciar.sql.
--
-- Solo con autorización explícita. Un único bloque DO: o restaura todo o nada.
--
--   npx -y supabase@3.1.0 db query --yes --remote=<ref> \
--     --file supabase/scripts/reinicio_uat/02_restaurar.sql
--
-- Guarda: si después del reinicio se crearon Órdenes nuevas, aborta, salvo
-- que v_descartar_nuevas sea true (esas Órdenes nuevas se perderían).
--
-- Para reinsertar las filas tal como estaban desactiva temporalmente los
-- triggers de usuario de las tablas operativas (inmutabilidad, Orden abierta,
-- secuencia de eventos, aplicación de movimientos): sin eso, el INSERT
-- reaplicaría el stock y renumeraría los eventos. Las claves foráneas siguen
-- activas. Al final se reactivan los triggers y se verifica la integridad.
-- Las fotos del bucket se restauran aparte (ver el plan).

do $$
declare
  v_descartar_nuevas constant boolean := false;
  c_respaldo constant text := 'rma_respaldo_reinicio';
  -- Orden de inserción compatible con las claves foráneas.
  c_tablas constant text[] := array[
    'cliente', 'equipo', 'documento_cliente', 'orden', 'accion_usuario',
    'auditoria_tecnica', 'recepcion', 'recepcion_version', 'recepcion_nota',
    'checkin', 'detalle', 'detalle_version', 'orden_detalle_origen',
    'decision_cliente', 'override_recursos', 'override_insumo',
    'ajuste_garantia', 'toma', 'ejecucion', 'ejecucion_insumo',
    'control_tecnico', 'movimiento_inventario', 'pago', 'devolucion_dinero',
    'descuento', 'documento_emitido', 'foto', 'salida', 'evento_negocio'
  ];
  v_tabla text;
  v_columnas text;
  v_n bigint;
  v_m bigint;
begin
  if not exists (select 1 from pg_namespace where nspname = c_respaldo) then
    raise exception 'No existe el respaldo %.', c_respaldo;
  end if;
  if exists (select 1 from rma.orden) and not v_descartar_nuevas then
    raise exception 'Hay % Órdenes creadas después del reinicio. Revisar antes de descartarlas.',
      (select count(*) from rma.orden);
  end if;

  foreach v_tabla in array c_tablas loop
    execute format('alter table rma.%I disable trigger user', v_tabla);
  end loop;

  execute 'truncate table '
    || (select string_agg(format('rma.%I', t), ', ') from unnest(c_tablas) t);

  foreach v_tabla in array c_tablas loop
    select string_agg(quote_ident(attname), ', ' order by attnum) into v_columnas
      from pg_attribute
     where attrelid = format('rma.%I', v_tabla)::regclass
       and attnum > 0 and not attisdropped and attgenerated = '';
    execute format('insert into rma.%I (%s) select %s from %I.%I',
                   v_tabla, v_columnas, v_columnas, c_respaldo, v_tabla);
    execute format('select count(*) from rma.%I', v_tabla) into v_n;
    execute format('select count(*) from %I.%I', c_respaldo, v_tabla) into v_m;
    if v_n <> v_m then
      raise exception 'Restauración incompleta de %: % de %.', v_tabla, v_n, v_m;
    end if;
  end loop;

  execute format(
    'update rma.insumo i set stock_fisico = r.stock_fisico, stock_reservado = r.stock_reservado
       from %I.insumo r where r.id = i.id', c_respaldo);

  foreach v_tabla in array c_tablas loop
    execute format('alter table rma.%I enable trigger user', v_tabla);
  end loop;

  select count(*) into v_n from rma.verificar_integridad();
  if v_n <> 0 then
    raise exception 'Después de restaurar, verificar_integridad() informa % problemas.', v_n;
  end if;

  -- setval no se revierte: va al final, cuando todo lo demás ya pasó.
  execute format(
    'select setval(''rma.orden_numero_seq'', last_value, is_called) from %I.secuencia where nombre = ''orden_numero_seq''',
    c_respaldo);
  execute format(
    'select setval(''rma.movimiento_inventario_secuencia'', last_value, is_called) from %I.secuencia where nombre = ''movimiento_inventario_secuencia''',
    c_respaldo);

  raise notice 'Restaurado: % Órdenes.', (select count(*) from rma.orden);
end $$;

select string_agg(codigo, ', ' order by codigo) as ordenes_restauradas from rma.orden;
