-- Rosario Tecno RMA — DATOS FICTICIOS DE DESARROLLO — nunca cargar en producción
-- Generado por supabase/scripts/generar_datos_iniciales.cjs desde app/backend/data/catalogs/*.json.
-- No editar a mano: regenerar.

-- Idempotente: volver a cargarlo no duplica ni cambia nada.
-- Aplicarlo entero o nada (psql: -v ON_ERROR_STOP=1 --single-transaction).

insert into rma.usuario (codigo, nombre, activo, orden) values
  ('RECEP-001', 'Recepcion Demo', true, 1),
  ('COORD-001', 'Coordinacion Demo', true, 2),
  ('TECH-001', 'Tecnico Demo', true, 3),
  ('ADMIN-001', 'Administracion Demo', true, 4)
on conflict (codigo) do update set orden = excluded.orden
  where rma.usuario.orden is distinct from excluded.orden;

insert into rma.usuario_rol (usuario_id, rol_id)
select u.id, r.id from (values
  ('RECEP-001', 'RECEPCION'),
  ('COORD-001', 'COORDINADOR_RMA'),
  ('TECH-001', 'TECNICO'),
  ('ADMIN-001', 'ADMINISTRADOR')
) as v (usuario, rol)
join rma.usuario u on u.codigo = v.usuario
join rma.rol r on r.codigo = v.rol
on conflict do nothing;

insert into rma.mesa_trabajo (codigo, nombre, activa) values
  ('EST-001', 'Mesa tecnica 1', true)
on conflict (codigo) do nothing;

insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias, activo) values
  ('TR-001', 'Cambio bateria iPhone 14', 80000, 10, 90, true),
  ('TR-002', 'Cambio de placa iPhone 14', 120000, 20, 90, true),
  ('TR-OTROS', 'Otros — Reparación no tipificada', 0, 0, 0, true)
on conflict (codigo) do nothing;

insert into rma.mesa_tipo_reparacion (mesa_trabajo_id, tipo_reparacion_id)
select m.id, t.id from (values
  ('EST-001', 'TR-001'),
  ('EST-001', 'TR-002')
) as v (mesa, tipo)
join rma.mesa_trabajo m on m.codigo = v.mesa
join rma.tipo_reparacion t on t.codigo = v.tipo
on conflict do nothing;

insert into rma.insumo (clave, codigo, nombre, unidad, activo) values
  ('INS-001', 'BAT-IP14', 'Bateria iPhone 14', null, true)
on conflict (codigo) do update set clave = excluded.clave
  where rma.insumo.clave = rma.insumo.codigo
    and rma.insumo.clave is distinct from excluded.clave;

insert into rma.tipo_reparacion_insumo (tipo_reparacion_id, insumo_id, cantidad)
select t.id, i.id, v.cantidad from (values
  ('TR-001', 'INS-001', 'BAT-IP14', 1::numeric)
) as v (tipo, insumo, codigo, cantidad)
join rma.tipo_reparacion t on t.codigo = v.tipo
join rma.insumo i on i.clave = v.insumo and i.codigo = v.codigo
on conflict do nothing;

-- Verificación (QA-E3-5): cada fila de las fuentes quedó en la base, con su identidad.
do $$
declare
  v_faltan text;
begin
  select string_agg(concat_ws(' / ', v.usuario, v.rol), ', ') into v_faltan
  from (values
    ('RECEP-001', 'RECEPCION'),
    ('COORD-001', 'COORDINADOR_RMA'),
    ('TECH-001', 'TECNICO'),
    ('ADMIN-001', 'ADMINISTRADOR')
  ) as v (usuario, rol)
  where not exists (
    select 1 from rma.usuario u
    join rma.usuario_rol ur on ur.usuario_id = u.id
    join rma.rol r on r.id = ur.rol_id
    where u.codigo = v.usuario and r.codigo = v.rol
  );
  if v_faltan is not null then
    raise exception 'Carga de desarrollo: % sin cargar: %', 'usuarios con su rol', v_faltan;
  end if;
  select string_agg(concat_ws(' / ', v.mesa, v.tipo), ', ') into v_faltan
  from (values
    ('EST-001', 'TR-001'),
    ('EST-001', 'TR-002')
  ) as v (mesa, tipo)
  where not exists (
    select 1 from rma.mesa_tipo_reparacion x
    join rma.mesa_trabajo m on m.id = x.mesa_trabajo_id
    join rma.tipo_reparacion t on t.id = x.tipo_reparacion_id
    where m.codigo = v.mesa and t.codigo = v.tipo
  );
  if v_faltan is not null then
    raise exception 'Carga de desarrollo: % sin cargar: %', 'estaciones de los tipos', v_faltan;
  end if;
  select string_agg(concat_ws(' / ', v.clave, v.codigo), ', ') into v_faltan
  from (values
    ('INS-001', 'BAT-IP14')
  ) as v (clave, codigo)
  where not exists (
    select 1 from rma.insumo i where i.clave = v.clave and i.codigo = v.codigo
  );
  if v_faltan is not null then
    raise exception 'Carga de desarrollo: % sin cargar: %', 'insumos con su clave y su código', v_faltan;
  end if;
  select string_agg(concat_ws(' / ', v.tipo, v.insumo, v.codigo, v.cantidad), ', ') into v_faltan
  from (values
    ('TR-001', 'INS-001', 'BAT-IP14', 1::numeric)
  ) as v (tipo, insumo, codigo, cantidad)
  where not exists (
    select 1 from rma.tipo_reparacion_insumo x
    join rma.tipo_reparacion t on t.id = x.tipo_reparacion_id
    join rma.insumo i on i.id = x.insumo_id
    where t.codigo = v.tipo and i.clave = v.insumo and i.codigo = v.codigo
      and x.cantidad = v.cantidad
  );
  if v_faltan is not null then
    raise exception 'Carga de desarrollo: % sin cargar: %', 'insumos previstos', v_faltan;
  end if;
end;
$$;

-- Stock inicial: un INGRESO por insumo, registrado por el proceso de carga inicial.
-- Sin ON CONFLICT: el libro no lo admite, porque aplica los saldos antes de resolver conflictos.
-- Solo se registran los ingresos que todavía no existen, y la acción solo si hay alguno.
-- Antes de tocar el stock se confirma la identidad de cada insumo (clave y código).
do $$
declare
  v_accion uuid;
  v_faltan text;
  r record;
begin
  select string_agg(concat_ws(' / ', v.clave, v.insumo), ', ') into v_faltan
  from (values
    ('INS-001', 'BAT-IP14')
  ) as v (clave, insumo)
  where not exists (select 1 from rma.insumo i where i.clave = v.clave and i.codigo = v.insumo);
  if v_faltan is not null then
    raise exception 'Carga de desarrollo: stock inicial sin registrar, insumos sin su clave y su código: %', v_faltan;
  end if;
  for r in
    select i.id, i.codigo, v.cantidad
    from (values
      ('INS-001', 'BAT-IP14', 2::numeric)
    ) as v (clave, insumo, cantidad)
    join rma.insumo i on i.clave = v.clave and i.codigo = v.insumo
    where v.cantidad > 0
      and not exists (select 1 from rma.movimiento_inventario m where m.codigo = 'MST-INICIAL-' || i.codigo)
  loop
    if v_accion is null then
      insert into rma.accion_usuario (proceso, operacion, resultado)
      values ('CARGA_INICIAL_DESARROLLO', 'INGRESO_STOCK_INICIAL', 'CONFIRMADA')
      returning id into v_accion;
    end if;
    insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, accion_id)
    values ('MST-INICIAL-' || r.codigo, 'INGRESO', r.id, r.cantidad, 'Saldo inicial de desarrollo', v_accion);
  end loop;
end;
$$;
