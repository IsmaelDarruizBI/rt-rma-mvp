-- Rosario Tecno RMA — Pruebas de inventario: stock_fisico >= stock_reservado >= 0,
-- libro inmutable, vínculos de origen, override y conciliación.
begin;

select rma_pruebas.preparar_orden('INV');

do $$
declare
  v_insumo uuid;
  v_accion uuid := rma_pruebas.id('accion_INV');
  v_usuario uuid := rma_pruebas.id('usuario_INV');
  v_orden uuid := rma_pruebas.id('orden_INV');
  v_detalle uuid := rma_pruebas.id('detalle_INV');
  v_reserva uuid;
  v_ejecucion uuid;
  v_motivo_neg uuid;
  v_override uuid;
begin
  -- Un insumo nace sin stock aunque se intente cargarlo directamente.
  insert into rma.insumo (codigo, nombre, stock_fisico, stock_reservado)
  values ('BAT-PRUEBA', 'Batería de prueba', 50, 7) returning id into v_insumo;
  perform rma_pruebas.debe_ser((select stock_fisico from rma.insumo where id = v_insumo), 0::numeric, 'saldo inicial cero');

  insert into rma.motivo_ajuste (codigo, descripcion, aplica_a) values ('PRUEBA_NEG', 'Ajuste de prueba', 'NEGATIVO')
  returning id into v_motivo_neg;

  -- Ingreso de 2 unidades.
  insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id, accion_id, referencia)
  values ('MOV-I1', 'INGRESO', v_insumo, 2, 'Compra', v_usuario, v_accion, 'REMITO-1');
  perform rma_pruebas.debe_ser((select stock_fisico from rma.insumo where id = v_insumo), 2::numeric, 'ingreso suma físico');
  perform rma_pruebas.debe_ser(
    (select stock_fisico_resultante from rma.movimiento_inventario where codigo = 'MOV-I1'), 2::numeric, 'snapshot del resultante');

  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_texto, usuario_id, accion_id, referencia)
       values ('MOV-I2', 'INGRESO', %L, 1, 'Compra', %L, %L, 'remito-1')$q$, v_insumo, v_usuario, v_accion),
    'referencia de ingreso repetida sin distinguir mayúsculas', '23505');

  -- Reserva de 2: disponible 0.
  insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, accion_id)
  values ('MOV-R1', 'RESERVA', v_insumo, 2, v_orden, v_detalle, v_accion) returning id into v_reserva;
  perform rma_pruebas.debe_ser((select stock_reservado from rma.insumo where id = v_insumo), 2::numeric, 'reserva suma reservado');

  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, accion_id)
       values ('MOV-R2', 'RESERVA', %L, 1, %L, %L, %L)$q$, v_insumo, v_orden, v_detalle, v_accion),
    'reserva sin disponible', '23514');

  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_ajuste_id, motivo_texto, usuario_id, accion_id)
       values ('MOV-A1', 'AJUSTE_NEGATIVO', %L, 1, %L, 'Recuento', %L, %L)$q$, v_insumo, v_motivo_neg, v_usuario, v_accion),
    'ajuste negativo que dejaría el físico por debajo del reservado (G-2)', '23514');

  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, motivo_ajuste_id, motivo_texto, usuario_id, accion_id)
       values ('MOV-A2', 'AJUSTE_POSITIVO', %L, 1, %L, 'Recuento', %L, %L)$q$, v_insumo, v_motivo_neg, v_usuario, v_accion),
    'motivo de ajuste negativo usado en un ajuste positivo', '23514');

  -- Ejecución que consume 1 y libera 1.
  insert into rma.ejecucion (codigo, orden_id, detalle_id, detalle_version_id, toma_id, usuario_id)
  values ('EJE-INV', v_orden, v_detalle, rma_pruebas.id('version_INV'), rma_pruebas.id('toma_INV'), v_usuario)
  returning id into v_ejecucion;

  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, accion_id, movimiento_origen_id)
       values ('MOV-C0', 'CONSUMO', %L, 1, %L, %L, %L, %L)$q$, v_insumo, v_orden, v_detalle, v_accion, v_reserva),
    'consumo sin Ejecución', '23514');

  insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, ejecucion_id, movimiento_origen_id, accion_id)
  values ('MOV-C1', 'CONSUMO', v_insumo, 1, v_orden, v_detalle, v_ejecucion, v_reserva, v_accion),
         ('MOV-L1', 'LIBERACION_RESERVA', v_insumo, 1, v_orden, v_detalle, v_ejecucion, v_reserva, v_accion);
  perform rma_pruebas.debe_ser((select stock_fisico from rma.insumo where id = v_insumo), 1::numeric, 'consumo baja físico');
  perform rma_pruebas.debe_ser((select stock_reservado from rma.insumo where id = v_insumo), 0::numeric, 'cierre de la reserva');

  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, ejecucion_id, movimiento_origen_id, accion_id)
       values ('MOV-C2', 'CONSUMO', %L, 1, %L, %L, %L, %L, %L)$q$, v_insumo, v_orden, v_detalle, v_ejecucion, v_reserva, v_accion),
    'consumo de más sobre una reserva ya cerrada', '23514');

  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.movimiento_inventario (codigo, tipo, insumo_id, cantidad, orden_id, detalle_id, ejecucion_id, movimiento_origen_id, accion_id)
       values ('MOV-D1', 'DESPERDICIO', %L, 1, %L, %L, %L, %L, %L)$q$, v_insumo, v_orden, v_detalle, v_ejecucion, v_reserva, v_accion),
    'DESPERDICIO sin operación habilitada', '23514');

  -- Lo declarado se guarda aparte; lo sin respaldo es la diferencia.
  update rma.ejecucion set estado = 'COMPLETADO', fin = now() where id = v_ejecucion;
  insert into rma.ejecucion_insumo (ejecucion_id, insumo_id, cantidad_utilizada) values (v_ejecucion, v_insumo, 3);
  perform rma_pruebas.debe_ser(
    (select sin_respaldo from rma.v_ejecucion_insumo_consumo where ejecucion_id = v_ejecucion), 2::numeric,
    'utilizado 3, consumido 1: sin respaldo 2');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.ejecucion set observaciones = 'x' where id = %L$q$, v_ejecucion),
    'una Ejecución terminada no se reabre', '23001');

  -- El libro es inmutable.
  perform rma_pruebas.debe_fallar($q$update rma.movimiento_inventario set cantidad = 9 where codigo = 'MOV-I1'$q$,
    'movimiento modificado', '23001');
  perform rma_pruebas.debe_fallar($q$delete from rma.movimiento_inventario where codigo = 'MOV-I1'$q$,
    'movimiento borrado', '23001');

  -- Restricción directa sobre el insumo, aunque alguien saltee el libro.
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.insumo set stock_reservado = stock_fisico + 1 where id = %L$q$, v_insumo),
    'físico menor que reservado', '23514');

  -- Override vinculado a una versión, con su cálculo de impacto.
  insert into rma.override_recursos (orden_id, detalle_id, detalle_version_id, motivo, usuario_id)
  values (v_orden, v_detalle, rma_pruebas.id('version_INV'), 'Sin stock de baterías', v_usuario) returning id into v_override;
  insert into rma.override_insumo (override_id, insumo_id, requerido, disponible, a_reservar, faltante)
  values (v_override, v_insumo, 3, 1, 1, 2);
  insert into rma.override_recursos (orden_id, detalle_id, detalle_version_id, motivo, usuario_id)
  values (v_orden, v_detalle, rma_pruebas.id('version_INV'), 'Segundo override', v_usuario) returning id into v_override;
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.override_insumo (override_id, insumo_id, requerido, disponible, a_reservar, faltante)
       values (%L, %L, 3, 1, 3, 0)$q$, v_override, v_insumo),
    'override que reservaría más que lo disponible', '23514');

  -- Todo concilia.
  perform rma_pruebas.debe_ser(
    (select count(*)::int from rma.verificar_integridad() where verificacion = 'CONCILIACION_INVENTARIO'), 0,
    'el inventario concilia con el libro');
end;
$$;

rollback;
