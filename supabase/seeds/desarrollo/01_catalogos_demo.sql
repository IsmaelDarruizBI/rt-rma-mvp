-- Rosario Tecno RMA — DATOS FICTICIOS DE DESARROLLO — nunca cargar en producción
-- Generado por supabase/scripts/generar_datos_iniciales.cjs desde app/backend/data/catalogs/*.json.
-- No editar a mano: regenerar.

-- Idempotente: volver a cargarlo no duplica ni cambia nada.

insert into rma.usuario (codigo, nombre, activo) values
  ('RECEP-001', 'Recepcion Demo', true),
  ('COORD-001', 'Coordinacion Demo', true),
  ('TECH-001', 'Tecnico Demo', true),
  ('ADMIN-001', 'Administracion Demo', true)
on conflict (codigo) do nothing;

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

insert into rma.insumo (codigo, nombre, unidad, activo) values
  ('BAT-IP14', 'Bateria iPhone 14', null, true)
on conflict (codigo) do nothing;

insert into rma.tipo_reparacion_insumo (tipo_reparacion_id, insumo_id, cantidad)
select t.id, i.id, v.cantidad from (values
  ('TR-001', 'BAT-IP14', 1::numeric)
) as v (tipo, insumo, cantidad)
join rma.tipo_reparacion t on t.codigo = v.tipo
join rma.insumo i on i.codigo = v.insumo
on conflict do nothing;

-- Stock inicial: un INGRESO por insumo, registrado por el proceso de carga inicial.
-- Sin ON CONFLICT: el libro no lo admite, porque aplica los saldos antes de resolver conflictos.
-- Solo se registran los ingresos que todavía no existen, y la acción solo si hay alguno.
do $$
declare
  v_accion uuid;
  r record;
begin
  for r in
    select i.id, i.codigo, v.cantidad
    from (values
      ('BAT-IP14', 2::numeric)
    ) as v (insumo, cantidad)
    join rma.insumo i on i.codigo = v.insumo
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
