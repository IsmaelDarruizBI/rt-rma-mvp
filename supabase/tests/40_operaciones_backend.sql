-- Rosario Tecno RMA — Operaciones reales con los permisos del backend (rol rma_backend).
-- Los datos se preparan con el usuario de las migraciones; las operaciones se
-- ejecutan como rma_backend, igual que FastAPI.
begin;

select rma_pruebas.preparar_orden('BK');

do $$
declare
  v_usuario uuid := rma_pruebas.id('usuario_BK');
  v_orden uuid := rma_pruebas.id('orden_BK');
  v_cliente uuid := rma_pruebas.id('cliente_BK');
  v_dni uuid := (select id from rma.tipo_documento where codigo = 'DNI');
  v_accion uuid;
  v_medio uuid;
  v_pago uuid;
  v_doc uuid;
  v_insumo uuid;
  v_stock numeric;
  i int;
begin
  insert into rma.medio_pago (codigo, nombre) values ('MEDIO-BK', 'Efectivo') returning id into v_medio;
  insert into rma.insumo (codigo, nombre) values ('INS-BK', 'Insumo backend') returning id into v_insumo;
  insert into rma.documento_cliente (cliente_id, tipo_documento_id, exige_unicidad, numero_ingresado, numero_normalizado)
  values (v_cliente, v_dni, true, '40111222', '40111222') returning id into v_doc;

  set local role rma_backend;

  -- Acción: se inserta al principio y se completa una vez al final.
  insert into rma.accion_usuario (usuario_id, rol_codigo, operacion, clave_idempotencia, resultado)
  values (v_usuario, 'RECEPCION', 'REGISTRAR_PAGO', 'clave-bk', 'CONFIRMADA') returning id into v_accion;
  update rma.accion_usuario set respuesta = '{"pago": "PAG-BK1"}', orden_id = v_orden where id = v_accion;
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.accion_usuario set respuesta = '{"otra": 1}' where id = %L$q$, v_accion),
    'la respuesta se completa una sola vez', '23001');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.accion_usuario set operacion = 'OTRA' where id = %L$q$, v_accion),
    'el resto de la acción no cambia', '42501');

  -- Pago, devolución (bloquea el pago) y anulación.
  insert into rma.pago (codigo, orden_id, monto, tipo_pago, medio_pago_id, usuario_id)
  values ('PAG-BK1', v_orden, 1000, 'ANTICIPO', v_medio, v_usuario) returning id into v_pago;
  insert into rma.devolucion_dinero (codigo, orden_id, pago_id, monto, medio_pago_id, motivo, usuario_id)
  values ('DEV-BK1', v_orden, v_pago, 400, v_medio, 'Saldo a favor', v_usuario);
  update rma.pago set anulado_por = v_usuario, anulado_en = now(), anulacion_motivo = 'Error' where id = v_pago;
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.pago set monto = 1 where id = %L$q$, v_pago), 'el backend no cambia importes', '42501');

  -- Corrección de un documento de Cliente.
  update rma.documento_cliente set vigente_hasta = now() where id = v_doc;

  -- Fotos: bloquean la Orden y respetan el máximo.
  for i in 1..10 loop
    insert into rma.foto (codigo, orden_id, objeto_clave, tipo_contenido, tamano_bytes, usuario_id)
    values ('FOT-BK' || i, v_orden, 'ordenes/bk/' || i, 'image/jpeg', 100, v_usuario);
  end loop;
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.foto (codigo, orden_id, objeto_clave, tipo_contenido, tamano_bytes, usuario_id)
       values ('FOT-BK11', %L, 'ordenes/bk/11', 'image/jpeg', 100, %L)$q$, v_orden, v_usuario),
    'undécima foto', '23514');

  -- El libro rechaza un código repetido incluso con ON CONFLICT, sin tocar el stock.
  insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id, accion_id)
  values ('MOV-BK1', 'INGRESO', v_insumo, 5, 'Compra', v_usuario, v_accion);
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id, accion_id)
       values ('MOV-BK1', 'INGRESO', %L, 5, 'Compra', %L, %L) on conflict (codigo) do nothing$q$, v_insumo, v_usuario, v_accion),
    'ON CONFLICT sobre el libro', '23505');
  select stock_fisico into v_stock from rma.insumo where id = v_insumo;
  perform rma_pruebas.debe_ser(v_stock, 5::numeric, 'el reintento no infló el stock');

  -- Eventos con secuencia asignada por la base.
  insert into rma.evento_negocio (orden_id, tipo_evento_id, accion_id, responsable_tipo, usuario_id)
  values (v_orden, (select id from rma.tipo_evento where codigo = 'EV-REP-038'), v_accion, 'USUARIO', v_usuario);

  -- El backend no borra.
  perform rma_pruebas.debe_fallar(format($q$delete from rma.foto where orden_id = %L$q$, v_orden), 'borrar fotos', '42501');
  perform rma_pruebas.debe_fallar(format($q$delete from rma.orden where id = %L$q$, v_orden), 'borrar la Orden', '42501');

  reset role;

  if exists (select 1 from pg_roles where rolname = 'service_role') then
    perform rma_pruebas.debe_ser(has_schema_privilege('service_role', 'rma', 'USAGE'), false, 'service_role sin acceso a rma');
  end if;
  perform rma_pruebas.debe_ser(
    (select count(*)::int from rma.verificar_integridad() where verificacion = 'CONCILIACION_INVENTARIO'), 0,
    'el inventario concilia');
end;
$$;

rollback;
