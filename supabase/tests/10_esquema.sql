-- Rosario Tecno RMA — Pruebas de estructura del esquema.
begin;

-- Las 45 entidades del diseño lógico existen como tablas.
do $$
declare
  v_esperadas text[] := array[
    'cliente', 'documento_cliente', 'modelo_equipo', 'equipo',
    'orden', 'orden_detalle_origen', 'recepcion', 'recepcion_version', 'recepcion_nota', 'checkin', 'salida', 'foto',
    'detalle', 'detalle_version', 'decision_cliente', 'ajuste_garantia', 'toma', 'ejecucion', 'ejecucion_insumo', 'control_tecnico', 'evaluacion_tecnica',
    'insumo', 'movimiento_inventario', 'override_recursos', 'override_insumo',
    'pago', 'devolucion_dinero', 'descuento', 'documento_emitido',
    'accion_usuario', 'evento_negocio', 'tipo_evento', 'equivalencia_historial', 'auditoria_tecnica', 'cambio_configuracion',
    'usuario', 'rol', 'usuario_rol', 'mesa_trabajo', 'mesa_tipo_reparacion', 'tipo_reparacion',
    'tipo_reparacion_insumo', 'medio_pago', 'tipo_documento', 'motivo_ajuste', 'empresa', 'texto_legal'
  ];
  v_faltan text[];
  v_sobran text[];
begin
  perform rma_pruebas.debe_ser(cardinality(v_esperadas), 47, 'el diseño lógico tiene 47 entidades');
  select array_agg(t) into v_faltan from unnest(v_esperadas) t
   where not exists (select 1 from information_schema.tables
                      where table_schema = 'rma' and table_name = t and table_type = 'BASE TABLE');
  select array_agg(table_name::text) into v_sobran from information_schema.tables
   where table_schema = 'rma' and table_type = 'BASE TABLE' and table_name <> all (v_esperadas);
  if v_faltan is not null or v_sobran is not null then
    raise exception 'Tablas: faltan %, sobran %.', v_faltan, v_sobran;
  end if;
end;
$$;

-- Toda tabla, vista y columna tiene su descripción.
do $$
declare
  v_sin text[];
begin
  select array_agg(c.relname::text) into v_sin
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'rma' and c.relkind in ('r', 'v')
     and obj_description(c.oid, 'pg_class') is null;
  if v_sin is not null then raise exception 'Tablas o vistas sin comentario: %', v_sin; end if;

  select array_agg(c.relname || '.' || a.attname) into v_sin
    from pg_attribute a
    join pg_class c on c.oid = a.attrelid
    join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'rma' and c.relkind in ('r', 'v') and a.attnum > 0 and not a.attisdropped
     and col_description(c.oid, a.attnum) is null;
  if v_sin is not null then raise exception 'Columnas sin comentario: %', v_sin; end if;
end;
$$;

-- Las claves foráneas no forman ciclos entre tablas distintas
-- (las autorreferencias, como el reemplazo de versiones, son esperadas).
do $$
declare
  v_ciclo text;
begin
  with recursive fk as (
    select distinct c.conrelid::regclass::text as desde, c.confrelid::regclass::text as hacia
      from pg_constraint c join pg_namespace n on n.oid = c.connamespace
     where c.contype = 'f' and n.nspname = 'rma' and c.conrelid <> c.confrelid
  ), camino as (
    select desde, hacia, array[desde, hacia] as recorrido, false as ciclo from fk
    union all
    select c.desde, f.hacia, c.recorrido || f.hacia, f.hacia = any (c.recorrido)
      from camino c join fk f on f.desde = c.hacia
     where not c.ciclo
  )
  select array_to_string(recorrido, ' -> ') into v_ciclo from camino where ciclo limit 1;
  if v_ciclo is not null then raise exception 'Ciclo de claves foráneas: %', v_ciclo; end if;
end;
$$;

-- Datos de referencia completos.
do $$
begin
  perform rma_pruebas.debe_ser((select count(*)::int from rma.rol), 4, 'cuatro roles');
  perform rma_pruebas.debe_ser((select count(*)::int from rma.tipo_evento where es_negocio), 52, '52 tipos de evento de negocio (51 de la base y EV-REP-052, iteracion 1)');
  perform rma_pruebas.debe_ser((select count(*)::int from rma.tipo_evento where not es_negocio), 1, 'un tipo técnico');
  perform rma_pruebas.debe_ser(
    (select count(*)::int from rma.tipo_evento where codigo like 'ACC-REP-%'), 0, 'ningún tipo reutiliza ACC-REP');
  -- Las entradas que hoy registra el MVP tienen equivalencia (choques de ACC-REP-021 a 028 incluidos).
  perform rma_pruebas.debe_ser(
    (select t.codigo from rma.equivalencia_historial e join rma.tipo_evento t on t.id = e.tipo_evento_id
      where e.referencia_id = 'ACC-REP-021' and e.accion = 'ANULAR_PAGO'), 'EV-REP-039', 'ACC-REP-021 es la anulación de un pago');
  perform rma_pruebas.debe_ser(
    (select t.codigo from rma.equivalencia_historial e join rma.tipo_evento t on t.id = e.tipo_evento_id
      where e.referencia_id = 'PROC-REP-270' and e.accion = 'DEVOLVER_EQUIPO_RT'), 'EV-REP-036', 'devolución a Gestión RT');
end;
$$;

-- Acceso (G-5): el frontend no ve el esquema y el backend no borra.
do $$
begin
  if exists (select 1 from pg_roles where rolname = 'anon') then
    perform rma_pruebas.debe_ser(has_schema_privilege('anon', 'rma', 'USAGE'), false, 'anon sin acceso a rma');
    perform rma_pruebas.debe_ser(has_schema_privilege('authenticated', 'rma', 'USAGE'), false, 'authenticated sin acceso a rma');
  end if;
  if exists (select 1 from pg_roles where rolname = 'service_role') then
    perform rma_pruebas.debe_ser(has_schema_privilege('service_role', 'rma', 'USAGE'), false, 'service_role sin acceso a rma');
  end if;
  -- Ninguna función del esquema tiene search_path mutable.
  perform rma_pruebas.debe_ser(
    (select count(*)::int from pg_proc p join pg_namespace n on n.oid = p.pronamespace
      where n.nspname = 'rma' and not exists (
        select 1 from unnest(coalesce(p.proconfig, '{}')) c where c like 'search_path=%')),
    0, 'funciones con search_path fijo');
  perform rma_pruebas.debe_ser(has_table_privilege('rma_backend', 'rma.movimiento_inventario', 'UPDATE'), false, 'el libro no se actualiza');
  perform rma_pruebas.debe_ser(has_table_privilege('rma_backend', 'rma.evento_negocio', 'DELETE'), false, 'los eventos no se borran');
  perform rma_pruebas.debe_ser(has_column_privilege('rma_backend', 'rma.insumo', 'stock_fisico', 'UPDATE'), false, 'el stock solo cambia por movimientos');
  perform rma_pruebas.debe_ser(has_table_privilege('rma_backend', 'rma.tipo_evento', 'INSERT'), false, 'los tipos de evento se cargan por migración');
  perform rma_pruebas.debe_ser(has_table_privilege('rma_backend', 'rma.pago', 'SELECT'), true, 'el backend lee pagos');
end;
$$;

rollback;
