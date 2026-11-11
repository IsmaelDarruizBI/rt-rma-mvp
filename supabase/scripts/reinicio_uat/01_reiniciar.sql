-- Reinicio de los datos operativos del UAT (proyecto rt-rma-db).
--
-- Deja la base sin Órdenes ni datos transaccionales de prueba y conserva el
-- esquema, las migraciones, los usuarios de RMA con sus roles y vínculos de
-- Supabase Auth, los catálogos y la configuración. El stock vuelve a un saldo
-- inicial registrado como INGRESO, así el libro concilia.
--
-- NUNCA en producción. Requiere autorización explícita para cada ejecución.
--
-- Uso (CLI de Supabase con la sesión administrativa, nunca rma_api):
--
--   npx -y supabase@3.1.0 db query --yes --remote=<ref> \
--     --file supabase/scripts/reinicio_uat/01_reiniciar.sql
--
-- Modo 'ensayo' (por defecto): hace todo, verifica y termina con un error
-- «ENSAYO OK …» que revierte la transacción completa. No cambia nada; el
-- único efecto que no se revierte es el avance de alguna secuencia, que no
-- afecta a la numeración visible (la de Órdenes no se toca en el ensayo).
-- Modo 'aplicar': lo mismo, pero confirma.
--
-- Todo es un único bloque DO: o se aplica entero o no se aplica nada.
--
-- Guardas (cualquiera que falle aborta sin cambios):
--   - cada tabla de rma está clasificada como operativa o maestra;
--   - las Órdenes existentes son exactamente las revisadas (v_ordenes);
--   - los cuatro usuarios de RMA están activos y vinculados a una cuenta de Auth;
--   - el esquema de respaldo todavía no existe (no se pisa un respaldo).
--
-- Respaldo: antes de limpiar copia las tablas operativas, insumo y las
-- secuencias en el esquema rma_respaldo_reinicio, sin permisos para anon,
-- authenticated, service_role ni rma_backend. Se restaura con
-- 02_restaurar.sql y se elimina con 04_eliminar_respaldo.sql antes de migrar
-- la base a otra región.
--
-- TRUNCATE: los triggers de inmutabilidad y «sin borrado» son BEFORE DELETE
-- por fila y no se disparan con TRUNCATE (no hay triggers ON TRUNCATE en rma).
-- Sin CASCADE: si una tabla no listada dependiera de las operativas, falla.

do $$
declare
  -- Parámetros revisados (ajustar solo con una nueva revisión).
  v_modo constant text := 'ensayo';  -- 'ensayo' | 'aplicar'
  -- Órdenes revisadas que se eliminan. Uso vigente: São Paulo
  -- (pcdnmhzwhzymznojndrn), Órdenes de probar_recorridos.py del 11/11/2026.
  -- El reinicio de Oregón (10/11/2026) usó OR-000001 a 006 y 009 a 012.
  v_ordenes constant text[] := array['OR-000001', 'OR-000002'];
  -- Stock inicial: clave, código y cantidad de cada insumo. Los insumos no
  -- listados quedan en cero.
  v_stock constant jsonb := '[{"clave": "INS-001", "codigo": "BAT-IP14", "cantidad": 10}]';

  c_operativas constant text[] := array[
    'accion_usuario', 'ajuste_garantia', 'auditoria_tecnica', 'checkin',
    'cliente', 'control_tecnico', 'decision_cliente', 'descuento', 'detalle',
    'detalle_version', 'devolucion_dinero', 'documento_cliente',
    'documento_emitido', 'ejecucion', 'ejecucion_insumo', 'equipo',
    'evento_negocio', 'foto', 'movimiento_inventario', 'orden',
    'orden_detalle_origen', 'override_insumo', 'override_recursos', 'pago',
    'recepcion', 'recepcion_nota', 'recepcion_version', 'salida', 'toma'
  ];
  c_maestras constant text[] := array[
    'empresa', 'equivalencia_historial', 'insumo', 'medio_pago',
    'mesa_tipo_reparacion', 'mesa_trabajo', 'modelo_equipo', 'motivo_ajuste',
    'rol', 'texto_legal', 'tipo_documento', 'tipo_evento', 'tipo_reparacion',
    'tipo_reparacion_insumo', 'usuario', 'usuario_rol'
  ];
  c_respaldo constant text := 'rma_respaldo_reinicio';

  v_tabla text;
  v_n bigint;
  v_esperado bigint;
  v_texto text;
  v_antes jsonb := '{}';
  v_resumen jsonb := '{}';
  v_accion uuid;
  v_item jsonb;
  v_insumo rma.insumo%rowtype;
  v_movimientos int := 0;
  v_rol text;
begin
  if v_modo not in ('ensayo', 'aplicar') then
    raise exception 'Modo desconocido: %', v_modo;
  end if;

  -- 1. Guardas -------------------------------------------------------------
  select string_agg(c.relname, ', ' order by c.relname) into v_texto
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'rma' and c.relkind in ('r', 'p')
     and c.relname <> all (c_operativas || c_maestras);
  if v_texto is not null then
    raise exception 'Tablas de rma sin clasificar: %', v_texto;
  end if;

  if (select coalesce(array_agg(codigo order by codigo), '{}') from rma.orden)
     is distinct from (select array_agg(x order by x) from unnest(v_ordenes) x) then
    raise exception 'Las Órdenes existentes no son las revisadas: %',
      (select string_agg(codigo, ', ' order by codigo) from rma.orden);
  end if;

  select count(*) into v_n
    from rma.usuario u join auth.users a on a.id = u.auth_user_id
   where u.activo;
  if v_n <> 4 or (select count(*) from rma.usuario) <> 4 then
    raise exception 'Se esperaban 4 usuarios de RMA activos y vinculados; hay %', v_n;
  end if;

  if exists (select 1 from pg_namespace where nspname = c_respaldo) then
    raise exception 'El esquema % ya existe: no se pisa un respaldo anterior.', c_respaldo;
  end if;

  foreach v_tabla in array c_maestras loop
    execute format('select count(*) from rma.%I', v_tabla) into v_n;
    v_antes := v_antes || jsonb_build_object(v_tabla, v_n);
  end loop;

  -- 2. Respaldo dentro de la base -----------------------------------------
  execute format('create schema %I', c_respaldo);
  execute format('revoke all on schema %I from public', c_respaldo);
  foreach v_tabla in array c_operativas || array['insumo'] loop
    execute format('create table %I.%I as select * from rma.%I', c_respaldo, v_tabla, v_tabla);
  end loop;
  execute format(
    'create table %I.secuencia as
       select ''orden_numero_seq''::text as nombre, last_value, is_called from rma.orden_numero_seq
       union all
       select ''movimiento_inventario_secuencia'', last_value, is_called from rma.movimiento_inventario_secuencia',
    c_respaldo);
  execute format(
    'create table %I.metadatos as select now() as respaldado_en, %L::text as modo, current_user::text as usuario',
    c_respaldo, v_modo);
  for v_rol in
    select rolname from pg_roles
     where rolname in ('anon', 'authenticated', 'service_role', 'rma_backend')
  loop
    execute format('revoke all on schema %I from %I', c_respaldo, v_rol);
    execute format('revoke all on all tables in schema %I from %I', c_respaldo, v_rol);
  end loop;

  -- 3. Limpieza --------------------------------------------------------------
  -- RESTART IDENTITY reinicia movimiento_inventario_secuencia (propiedad de la
  -- columna) dentro de la transacción.
  execute 'truncate table '
    || (select string_agg(format('rma.%I', t), ', ') from unnest(c_operativas) t)
    || ' restart identity';
  if v_modo = 'aplicar' then
    -- La próxima Orden será OR-000001. En el ensayo no se toca.
    alter sequence rma.orden_numero_seq restart with 1;
  end if;

  -- 4. Stock inicial -----------------------------------------------------------
  update rma.insumo set stock_fisico = 0, stock_reservado = 0;
  for v_item in select * from jsonb_array_elements(v_stock) loop
    select * into v_insumo from rma.insumo
     where clave = v_item->>'clave' and codigo = v_item->>'codigo';
    if v_insumo.id is null then
      raise exception 'Insumo % / % inexistente.', v_item->>'clave', v_item->>'codigo';
    end if;
    if not v_insumo.activo then
      raise exception 'Insumo % inactivo: no admite ingresos.', v_insumo.codigo;
    end if;
    if (v_item->>'cantidad')::numeric > 0 then
      if v_accion is null then
        insert into rma.accion_usuario (proceso, operacion, resultado)
        values ('CARGA_INICIAL_UAT', 'INGRESO_STOCK_INICIAL', 'CONFIRMADA')
        returning id into v_accion;
      end if;
      insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id)
      values ('MST-INICIAL-' || v_insumo.codigo, 'INGRESO', v_insumo.id,
              (v_item->>'cantidad')::numeric, 'Stock inicial de pruebas UAT', v_accion);
      v_movimientos := v_movimientos + 1;
    end if;
    v_insumo := null;
  end loop;

  -- 5. Verificaciones -----------------------------------------------------------
  foreach v_tabla in array c_operativas loop
    execute format('select count(*) from rma.%I', v_tabla) into v_n;
    v_esperado := case v_tabla
                    when 'accion_usuario' then (v_accion is not null)::int
                    when 'movimiento_inventario' then v_movimientos
                    else 0
                  end;
    if v_n <> v_esperado then
      raise exception 'La tabla % quedó con % filas.', v_tabla, v_n;
    end if;
  end loop;

  foreach v_tabla in array c_maestras loop
    execute format('select count(*) from rma.%I', v_tabla) into v_n;
    if v_n <> (v_antes->>v_tabla)::bigint then
      raise exception 'La tabla maestra % cambió: % antes, % después.', v_tabla, v_antes->>v_tabla, v_n;
    end if;
  end loop;

  select count(*) into v_n from rma.verificar_integridad();
  if v_n <> 0 then
    raise exception 'verificar_integridad() informa % problemas.', v_n;
  end if;

  if exists (
    select 1 from rma.insumo i
     where i.stock_reservado <> 0
        or i.stock_fisico <> coalesce((
             select (e->>'cantidad')::numeric from jsonb_array_elements(v_stock) e
              where e->>'clave' = i.clave and e->>'codigo' = i.codigo), 0)
  ) then
    raise exception 'El stock no quedó en el saldo inicial configurado.';
  end if;

  select count(*) into v_n
    from rma.usuario u join auth.users a on a.id = u.auth_user_id
   where u.activo;
  if v_n <> 4 then
    raise exception 'Los vínculos de usuarios cambiaron: % vinculados.', v_n;
  end if;

  execute format('select count(*) from %I.orden', c_respaldo) into v_n;
  v_resumen := jsonb_build_object(
    'modo', v_modo,
    'ordenes_respaldadas', v_n,
    'ordenes_actuales', (select count(*) from rma.orden),
    'movimientos_stock_inicial', v_movimientos,
    'maestras', v_antes
  );

  if v_modo = 'ensayo' then
    raise exception 'ENSAYO OK (se revierte todo): %', v_resumen;
  end if;
  raise notice 'REINICIO APLICADO: %', v_resumen;
end $$;

-- Solo se llega aquí en modo 'aplicar'.
select (select count(*) from rma.orden) as ordenes,
       (select count(*) from rma.cliente) as clientes,
       (select string_agg(codigo || '=' || stock_fisico || '/' || stock_reservado, ', ') from rma.insumo) as stock,
       (select last_value || case when is_called then ' (usado)' else ' (próximo)' end from rma.orden_numero_seq) as numero_orden;
