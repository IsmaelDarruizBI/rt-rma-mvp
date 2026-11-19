-- Limpieza de UNA ejecución del E2E (validacion_uat/probar_macro_v14.py o
-- probar_macro_integral.py) contra la línea de base de 05_linea_base_e2e.sql.
--
-- Borra solo las filas que no estaban en la línea de base y deja todo lo
-- demás idéntico: las Órdenes previas, sus fotos, documentos, eventos y
-- movimientos no se tocan. Las fotos del bucket tampoco: el resumen lista las
-- claves de las fotos nuevas (el E2E no sube ninguna) para borrarlas aparte,
-- por nombre, y nunca por prefijo.
--
-- Requiere autorización explícita para cada ejecución. Uso (CLI de Supabase
-- con la sesión administrativa, nunca rma_api), después del E2E:
--
--   npx -y supabase@3.1.0 db query --yes --remote=<ref> \
--     --file supabase/scripts/reinicio_uat/06_limpiar_e2e.sql
--
-- Modo 'ensayo' (por defecto): hace todo, verifica y termina con un error
-- «ENSAYO OK …» que revierte la transacción completa. Modo 'aplicar': lo
-- mismo, confirma y elimina la línea de base (que contiene copias de los
-- datos previos). Se aplica sobre una copia con v_modo cambiado, sin tocar el
-- archivo versionado. Todo es un único bloque DO: o se aplica entero o nada.
--
-- Guardas (cualquiera que falle aborta sin cambios):
--   - la línea de base existe, con las mismas migraciones y todas las tablas;
--   - cada tabla de rma está clasificada como operativa o maestra (las mismas
--     listas que 01_reiniciar.sql; un test lo comprueba);
--   - las Órdenes y los clientes nuevos son todos ficticios del E2E;
--   - ninguna fila previa de una tabla operativa cambió ni desapareció;
--   - las tablas maestras no cambiaron, salvo el stock de insumo (que vuelve
--     al de la línea de base) y el «Proveedor Ficticio E2E», que el E2E
--     reutiliza y deja inactivo (no admite borrado);
--   - después de borrar: cada tabla es idéntica a la línea de base (sin contar
--     sellos de tiempo y versión), verificar_integridad() vacío, el
--     inventario concilia y los usuarios siguen vinculados.
--
-- Secuencias: al aplicar vuelven al valor de la línea de base, como último
-- paso (setval no es transaccional). El ensayo no las toca: no deja ningún
-- efecto.
--
-- Los triggers «sin borrado» e inmutabilidad son BEFORE DELETE por fila: se
-- desactivan uno por uno dentro de la transacción y se reactivan los mismos
-- antes de verificar. Las claves foráneas siguen activas: si una fila previa
-- referenciara una nueva, el borrado falla y no se aplica nada.

do $$
declare
  v_modo constant text := 'ensayo';  -- 'ensayo' | 'aplicar'
  c_base constant text := 'rma_linea_base_e2e';
  -- Marcas de los datos ficticios del E2E.
  c_cliente_ficticio constant text := 'Cliente Ficticio E2E%';
  c_proveedor_ficticio constant text := 'Proveedor Ficticio E2E';
  -- Columnas que cambian sin cambiar el dato.
  c_volatiles constant text[] := array['modificado_en', 'actualizado_en', 'version'];
  c_stock constant text[] := array['stock_fisico', 'stock_reservado'];

  -- Las mismas listas que 01_reiniciar.sql.
  c_operativas constant text[] := array[
    'accion_usuario', 'ajuste_garantia', 'auditoria_tecnica',
    'cambio_configuracion', 'checkin', 'cliente', 'control_tecnico', 'decision_cliente', 'descuento', 'detalle',
    'detalle_version', 'devolucion_dinero', 'documento_cliente',
    'documento_emitido', 'ejecucion', 'ejecucion_insumo', 'equipo',
    'evaluacion_tecnica', 'evento_negocio', 'foto', 'movimiento_inventario', 'orden',
    'orden_detalle_origen', 'override_insumo', 'override_recursos', 'pago',
    'recepcion', 'recepcion_nota', 'recepcion_version', 'salida', 'toma',
    -- Macroiteración integral.
    'checklist_registro', 'comunicacion_cliente', 'comunicacion_confirmacion',
    'consentimiento_comunicacion', 'correccion_vinculo_equipo', 'firma_documento',
    'informacion_faltante_confirmacion', 'lote_insumo', 'orden_compra',
    'orden_compra_item', 'recepcion_compra', 'recepcion_compra_linea',
    'reclamo_garantia', 'seguimiento_retiro', 'solicitud_compra'
  ];
  c_maestras constant text[] := array[
    'empresa', 'equivalencia_historial', 'insumo', 'medio_pago',
    'mesa_tipo_reparacion', 'mesa_trabajo', 'modelo_equipo', 'motivo_ajuste',
    'rol', 'texto_legal', 'tipo_documento', 'tipo_evento', 'tipo_reparacion',
    'tipo_reparacion_insumo', 'usuario', 'usuario_rol',
    -- Macroiteración integral.
    'checklist_pregunta', 'motivo_operativo', 'parametro', 'permiso',
    'plantilla_mensaje', 'proveedor', 'tipo_equipo',
    -- Copias de orígenes externos (bloque C y Reparación RT): se conservan
    -- como las maestras.
    'catalogo_producto', 'sincronizacion_origen', 'producto_rt'
  ];

  v_tabla text;
  v_cond text;
  v_excluir text[];
  v_filtro text;
  v_n bigint;
  v_m bigint;
  v_texto text;
  v_nuevas jsonb := '{}';
  v_borradas jsonb := '{}';
  v_cambios text[] := '{}';
  v_fotos jsonb;
  v_triggers text[][] := '{}';
  v_trigger record;
  v_secuencia record;
  v_pendientes int;
  v_progreso boolean;
  v_vinculados bigint;
  v_resumen jsonb;
begin
  if v_modo not in ('ensayo', 'aplicar') then
    raise exception 'Modo desconocido: %', v_modo;
  end if;

  -- 1. Guardas sobre la línea de base ----------------------------------------
  if not exists (select 1 from pg_namespace where nspname = c_base) then
    raise exception 'No existe %: sin línea de base no se puede limpiar selectivamente.', c_base;
  end if;
  execute format('select migraciones from %I._metadatos', c_base) into v_n;
  if v_n <> (select count(*) from supabase_migrations.schema_migrations) then
    raise exception 'La línea de base tiene % migraciones y la base %: se tomó con otro esquema.',
      v_n, (select count(*) from supabase_migrations.schema_migrations);
  end if;

  select string_agg(c.relname, ', ' order by c.relname) into v_texto
    from pg_class c join pg_namespace n on n.oid = c.relnamespace
   where n.nspname = 'rma' and c.relkind in ('r', 'p')
     and c.relname <> all (c_operativas || c_maestras);
  if v_texto is not null then
    raise exception 'Tablas de rma sin clasificar: %', v_texto;
  end if;
  select string_agg(t, ', ' order by t) into v_texto
    from unnest(c_operativas || c_maestras) t
   where to_regclass(format('%I.%I', c_base, t)) is null
      or to_regclass(format('rma.%I', t)) is null;
  if v_texto is not null then
    raise exception 'Tablas que faltan en rma o en la línea de base: %', v_texto;
  end if;

  -- Condición de igualdad por clave primaria entre r (rma) y b (línea de base).
  create temp table _pk on commit drop as
    select t.relname::text as tabla,
           string_agg(format('b.%1$I = r.%1$I', a.attname), ' and ' order by k.ord) as cond
      from pg_constraint c
      join pg_class t on t.oid = c.conrelid
      join pg_namespace n on n.oid = t.relnamespace
      cross join lateral unnest(c.conkey) with ordinality k(attnum, ord)
      join pg_attribute a on a.attrelid = t.oid and a.attnum = k.attnum
     where n.nspname = 'rma' and c.contype = 'p'
     group by t.relname;
  select string_agg(t, ', ') into v_texto
    from unnest(c_operativas || c_maestras) t where t not in (select tabla from _pk);
  if v_texto is not null then
    raise exception 'Tablas sin clave primaria: %', v_texto;
  end if;

  -- 2. Qué creó el E2E y qué cambió ---------------------------------------------
  foreach v_tabla in array c_operativas || c_maestras loop
    select cond into v_cond from _pk where tabla = v_tabla;
    v_excluir := c_volatiles || case when v_tabla = 'insumo' then c_stock else '{}' end;
    v_filtro := case when v_tabla = 'proveedor'
                     then format('and %s.nombre <> %L', '%s', c_proveedor_ficticio) else '' end;

    -- Filas nuevas (no estaban en la línea de base).
    execute format('select count(*) from rma.%I r where not exists (select 1 from %I.%I b where %s) %s',
                   v_tabla, c_base, v_tabla, v_cond, format(v_filtro, 'r')) into v_n;
    if v_n > 0 then
      v_nuevas := v_nuevas || jsonb_build_object(v_tabla, v_n);
    end if;

    -- Filas previas que cambiaron o desaparecieron.
    execute format(
      'select count(*) from %I.%I b where not exists (
         select 1 from rma.%I r where %s and (to_jsonb(r) - %L::text[]) = (to_jsonb(b) - %L::text[])) %s',
      c_base, v_tabla, v_tabla, v_cond, v_excluir, v_excluir, format(v_filtro, 'b')) into v_m;
    if v_m > 0 then
      v_cambios := v_cambios || format('%s: %s filas previas cambiaron o faltan', v_tabla, v_m);
    end if;
    if v_tabla = any (c_maestras) and v_n > 0 then
      v_cambios := v_cambios || format('%s (maestra): %s filas nuevas', v_tabla, v_n);
    end if;
  end loop;

  if cardinality(v_cambios) > 0 then
    raise exception 'Cambios fuera de lo que crea el E2E (no se borra nada): %', array_to_string(v_cambios, '; ');
  end if;

  execute format('select count(*) from rma.orden r where not exists (select 1 from %I.orden b where b.id = r.id)
                    and coalesce(r.cliente_nombre, '''') not like %L', c_base, c_cliente_ficticio) into v_n;
  if v_n > 0 then
    raise exception '% Órdenes nuevas no son del E2E (cliente sin la marca %): no se borra nada.', v_n, c_cliente_ficticio;
  end if;
  execute format('select count(*) from rma.cliente r where not exists (select 1 from %I.cliente b where b.id = r.id)
                    and r.nombre not like %L', c_base, c_cliente_ficticio) into v_n;
  if v_n > 0 then
    raise exception '% clientes nuevos no son del E2E: no se borra nada.', v_n;
  end if;

  execute format('select coalesce(jsonb_agg(r.objeto_clave order by r.objeto_clave), ''[]'') from rma.foto r
                   where not exists (select 1 from %I.foto b where b.id = r.id)', c_base) into v_fotos;

  -- 3. Borrado de lo nuevo, con los triggers de usuario desactivados -------------
  for v_trigger in
    select c.relname::text as tabla, t.tgname::text as nombre
      from pg_trigger t join pg_class c on c.oid = t.tgrelid join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'rma' and not t.tgisinternal and t.tgenabled = 'O'
       and c.relname = any (c_operativas || array['insumo'])
  loop
    execute format('alter table rma.%I disable trigger %I', v_trigger.tabla, v_trigger.nombre);
    v_triggers := v_triggers || array[[v_trigger.tabla, v_trigger.nombre]];
  end loop;

  loop
    v_pendientes := 0;
    v_progreso := false;
    foreach v_tabla in array c_operativas loop
      select cond into v_cond from _pk where tabla = v_tabla;
      begin
        execute format('delete from rma.%I r where not exists (select 1 from %I.%I b where %s)',
                       v_tabla, c_base, v_tabla, v_cond);
        get diagnostics v_n = row_count;
        if v_n > 0 then
          v_borradas := v_borradas || jsonb_build_object(v_tabla, coalesce((v_borradas->>v_tabla)::bigint, 0) + v_n);
          v_progreso := true;
        end if;
      exception when foreign_key_violation then
        -- Quedan filas nuevas que la referencian: se reintenta en otra vuelta.
        v_pendientes := v_pendientes + 1;
      end;
    end loop;
    exit when v_pendientes = 0;
    if not v_progreso then
      raise exception 'No se puede borrar lo nuevo sin romper referencias de filas previas: no se aplica nada.';
    end if;
  end loop;

  execute format('update rma.insumo i set stock_fisico = b.stock_fisico, stock_reservado = b.stock_reservado
                    from %I.insumo b where b.id = i.id
                     and (i.stock_fisico, i.stock_reservado) is distinct from (b.stock_fisico, b.stock_reservado)', c_base);

  for v_n in 1 .. coalesce(array_length(v_triggers, 1), 0) loop
    execute format('alter table rma.%I enable trigger %I', v_triggers[v_n][1], v_triggers[v_n][2]);
  end loop;

  -- 4. Verificaciones -------------------------------------------------------------
  foreach v_tabla in array c_operativas || c_maestras loop
    v_filtro := case when v_tabla = 'proveedor' then format('where x.nombre <> %L', c_proveedor_ficticio) else '' end;
    execute format(
      'select (select md5(coalesce(string_agg((to_jsonb(x) - %1$L::text[])::text, E''\n'' order by (to_jsonb(x) - %1$L::text[])::text), '''')) from rma.%2$I x %4$s)
            = (select md5(coalesce(string_agg((to_jsonb(x) - %1$L::text[])::text, E''\n'' order by (to_jsonb(x) - %1$L::text[])::text), '''')) from %3$I.%2$I x %4$s)',
      c_volatiles, v_tabla, c_base, v_filtro) into v_progreso;
    if not v_progreso then
      raise exception 'La tabla % no quedó igual a la línea de base.', v_tabla;
    end if;
  end loop;

  select count(*) into v_n from rma.verificar_integridad();
  if v_n <> 0 then
    raise exception 'verificar_integridad() informa % problemas.', v_n;
  end if;
  if exists (select 1 from rma.v_conciliacion_inventario where not concilia) then
    raise exception 'El inventario no concilia.';
  end if;
  execute format('select count(*) from %I.usuario u join auth.users a on a.id = u.auth_user_id where u.activo', c_base)
    into v_vinculados;
  if (select count(*) from rma.usuario u join auth.users a on a.id = u.auth_user_id where u.activo) <> v_vinculados then
    raise exception 'Los vínculos de usuarios cambiaron.';
  end if;

  v_resumen := jsonb_build_object(
    'modo', v_modo,
    'ordenes_borradas', coalesce((v_borradas->>'orden')::bigint, 0),
    'ordenes_conservadas', (select coalesce(jsonb_agg(codigo order by codigo), '[]') from rma.orden),
    'filas_borradas', v_borradas,
    'fotos_nuevas_a_borrar_del_bucket', v_fotos,
    'proveedor_ficticio_conservado', exists (select 1 from rma.proveedor where nombre = c_proveedor_ficticio)
  );

  if v_modo = 'ensayo' then
    -- Sin setval: no es transaccional y el ensayo no debe dejar ningún efecto.
    raise exception 'ENSAYO OK (se revierte todo; las secuencias vuelven a su valor solo al aplicar): %', v_resumen;
  end if;

  -- 5. Aplicar ------------------------------------------------------------------
  -- Las secuencias vuelven a su valor como ÚLTIMO paso: setval no se revierte,
  -- y si algo fallara después de él con las filas del E2E todavía en la base,
  -- la próxima alta repetiría un código. Después de setval no queda nada que
  -- pueda fallar.
  create temp table resumen_limpieza_e2e as select v_resumen as resumen;
  create temp table _secuencias_e2e on commit drop as
    select * from rma_linea_base_e2e._secuencia;
  execute format('drop schema %I cascade', c_base);
  for v_secuencia in select nombre, last_value, is_called from _secuencias_e2e loop
    perform setval(format('rma.%I', v_secuencia.nombre), v_secuencia.last_value, v_secuencia.is_called);
  end loop;
  raise notice 'LIMPIEZA APLICADA: %', v_resumen;
end $$;

-- Solo se llega aquí en modo 'aplicar'.
select resumen from resumen_limpieza_e2e;
