-- Rosario Tecno RMA — Pruebas de unicidad, idempotencia, eventos, pagos, documentos y cierre.
begin;

select rma_pruebas.preparar_orden('A');
select rma_pruebas.preparar_orden('B');

do $$
declare
  v_dni uuid := (select id from rma.tipo_documento where codigo = 'DNI');
  v_doc uuid;
  v_doc2 uuid;
  v_usuario uuid := rma_pruebas.id('usuario_A');
  v_orden uuid := rma_pruebas.id('orden_A');
  v_rechazada uuid;
  v_medio uuid;
  v_pago uuid;
  v_texto uuid;
  v_doc_emitido uuid;
  v_secuencias int[];
  i int;
begin
  -- Documentos: único entre Clientes, uno vigente por tipo, corrección auditada.
  insert into rma.documento_cliente (cliente_id, tipo_documento_id, exige_unicidad, numero_ingresado, numero_normalizado, registrado_por)
  values (rma_pruebas.id('cliente_A'), v_dni, true, '30.123.456', '30123456', v_usuario) returning id into v_doc;
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.documento_cliente (cliente_id, tipo_documento_id, exige_unicidad, numero_ingresado, numero_normalizado)
       values (%L, %L, true, '30123456', '30123456')$q$, rma_pruebas.id('cliente_B'), v_dni),
    'el mismo DNI en otro Cliente', '23505');
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.documento_cliente (cliente_id, tipo_documento_id, exige_unicidad, numero_ingresado, numero_normalizado)
       values (%L, %L, true, '31000000', '31000000')$q$, rma_pruebas.id('cliente_A'), v_dni),
    'dos DNI vigentes en el mismo Cliente', '23505');
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.documento_cliente (cliente_id, tipo_documento_id, exige_unicidad, numero_ingresado, numero_normalizado)
       values (%L, %L, false, '31000000', '31000000')$q$, rma_pruebas.id('cliente_B'), v_dni),
    'la regla de unicidad no puede contradecir a su tipo', '23503');
  -- Corrección: se cierra el anterior y se registra el nuevo.
  update rma.documento_cliente set vigente_hasta = now() where id = v_doc;
  insert into rma.documento_cliente (cliente_id, tipo_documento_id, exige_unicidad, numero_ingresado, numero_normalizado)
  values (rma_pruebas.id('cliente_A'), v_dni, true, '30123457', '30123457') returning id into v_doc2;
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.documento_cliente set numero_normalizado = '1' where id = %L$q$, v_doc2),
    'el número de un documento no se edita', '23001');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.documento_cliente set vigente_hasta = now() + interval '1 day' where id = %L$q$, v_doc),
    'la vigencia se cierra una sola vez', '23001');

  -- Exclusividad del taller.
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.toma (codigo, orden_id, usuario_id, mesa_trabajo_id) values ('TOM-A2', %L, %L, %L)$q$,
    v_orden, v_usuario, rma_pruebas.id('mesa_A')),
    'dos tomas activas en la misma Orden', '23505');
  insert into rma.ejecucion (codigo, orden_id, detalle_id, detalle_version_id, toma_id, usuario_id)
  values ('EJE-A1', v_orden, rma_pruebas.id('detalle_A'), rma_pruebas.id('version_A'), rma_pruebas.id('toma_A'), v_usuario);
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.ejecucion (codigo, orden_id, detalle_id, detalle_version_id, toma_id, usuario_id)
       values ('EJE-A2', %L, %L, %L, %L, %L)$q$,
    v_orden, rma_pruebas.id('detalle_A'), rma_pruebas.id('version_A'), rma_pruebas.id('toma_A'), v_usuario),
    'dos Ejecuciones en curso en la misma Orden', '23505');
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.ejecucion (codigo, orden_id, detalle_id, detalle_version_id, toma_id, usuario_id)
       values ('EJE-X', %L, %L, %L, %L, %L)$q$,
    rma_pruebas.id('orden_B'), rma_pruebas.id('detalle_A'), rma_pruebas.id('version_A'), rma_pruebas.id('toma_B'), v_usuario),
    'una Ejecución con un Detalle de otra Orden', '23503');

  -- Detalles y versiones.
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.detalle (orden_id, codigo, garantia_dias) values (%L, 'DET-001', 90)$q$, v_orden),
    'código de Detalle repetido en la Orden', '23505');
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.detalle_version (detalle_id, numero, tipo_reparacion_id, precio, puntaje, garantia_dias)
       values (%L, 1, %L, 1, 1, 1)$q$, rma_pruebas.id('detalle_A'), rma_pruebas.id('tipo_A')),
    'número de versión repetido', '23505');
  insert into rma.detalle_version (detalle_id, numero, tipo_reparacion_id, precio, puntaje, garantia_dias, motivo, reemplaza_a)
  values (rma_pruebas.id('detalle_A'), 2, rma_pruebas.id('tipo_A'), 90000, 10, 90, 'Cambio de diagnóstico', rma_pruebas.id('version_A'));
  perform rma_pruebas.debe_ser(
    (select numero from rma.v_detalle_version_vigente where detalle_id = rma_pruebas.id('detalle_A')), 2, 'la vigente es la de mayor número');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.detalle_version set precio = 1 where id = %L$q$, rma_pruebas.id('version_A')),
    'una versión es inmutable', '23001');

  -- Idempotencia: una clave confirmada no se repite; un rechazo previo no la bloquea.
  insert into rma.accion_usuario (usuario_id, operacion, clave_idempotencia, resultado, motivo_rechazo)
  values (v_usuario, 'REGISTRAR_PAGO', 'clave-1', 'RECHAZADA', 'Saldo inválido') returning id into v_rechazada;
  insert into rma.accion_usuario (usuario_id, operacion, clave_idempotencia, resultado)
  values (v_usuario, 'REGISTRAR_PAGO', 'clave-1', 'CONFIRMADA');
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.accion_usuario (usuario_id, operacion, clave_idempotencia, resultado)
       values (%L, 'REGISTRAR_PAGO', 'clave-1', 'CONFIRMADA')$q$, v_usuario),
    'reintento con la misma clave', '23505');

  -- Eventos: solo de acciones confirmadas, con secuencia por Orden.
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.evento_negocio (orden_id, tipo_evento_id, accion_id, responsable_tipo, usuario_id)
       values (%L, (select id from rma.tipo_evento where codigo = 'EV-REP-038'), %L, 'USUARIO', %L)$q$,
    v_orden, v_rechazada, v_usuario),
    'evento de una acción rechazada', '23503');
  for i in 1..3 loop
    insert into rma.evento_negocio (orden_id, secuencia, tipo_evento_id, accion_id, responsable_tipo, usuario_id,
                                    historial_tipo_referencia, historial_referencia_id, historial_accion)
    values (v_orden, 99, (select id from rma.tipo_evento where codigo = 'EV-REP-038'), rma_pruebas.id('accion_A'),
            'USUARIO', v_usuario, 'FUNCTIONAL_ACTION', 'ACC-REP-020', 'REGISTRAR_PAGO');
  end loop;
  select array_agg(secuencia order by secuencia) into v_secuencias from rma.evento_negocio where orden_id = v_orden;
  perform rma_pruebas.debe_ser(v_secuencias, array[1, 2, 3], 'la base asigna la secuencia, ignorando la enviada');
  perform rma_pruebas.debe_ser(
    (select count(*)::int from rma.v_historial_visible where orden_id = v_orden), 3, 'historial visible');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.evento_negocio set observacion = 'x' where orden_id = %L$q$, v_orden),
    'un evento es inmutable', '23001');

  -- Pagos.
  insert into rma.medio_pago (codigo, nombre) values ('EFECTIVO_PRUEBA', 'Efectivo') returning id into v_medio;
  insert into rma.pago (codigo, orden_id, monto, tipo_pago, medio_pago_id, usuario_id)
  values ('PAG-A1', v_orden, 50000, 'ANTICIPO', v_medio, v_usuario) returning id into v_pago;
  perform rma_pruebas.debe_ser((select saldo from rma.v_orden_saldo where orden_id = v_orden), 40000::numeric, 'saldo = 90000 - 50000');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.pago set monto = 1 where id = %L$q$, v_pago), 'el importe de un pago no cambia', '23001');
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.devolucion_dinero (codigo, orden_id, pago_id, monto, medio_pago_id, motivo, usuario_id)
       values ('DEV-A1', %L, %L, 60000, %L, 'Prueba', %L)$q$, v_orden, v_pago, v_medio, v_usuario),
    'devolución mayor que el pago', '23514');
  update rma.pago set anulado_por = v_usuario, anulado_en = now(), anulacion_motivo = 'Error de carga' where id = v_pago;
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.pago set anulacion_motivo = 'otro' where id = %L$q$, v_pago), 'la anulación es única', '23001');
  perform rma_pruebas.debe_ser((select pagado from rma.v_orden_saldo where orden_id = v_orden), 0::numeric, 'un pago anulado no cuenta');

  -- Documentos con texto legal y versión de plantilla.
  insert into rma.texto_legal (tipo, version, titulo, contenido)
  values ('TERMINOS_CONDICIONES_ENTREGA', 99, 'Prueba', '{"apartados": []}') returning id into v_texto;
  insert into rma.documento_emitido (codigo, orden_id, tipo, version, contenido, texto_legal_id, plantilla_version)
  values ('DOC-A1', v_orden, 'COMPROBANTE_ENTREGA', 1, '{"tipo": "COMPROBANTE_ENTREGA"}', v_texto, 'entrega-2026-10-28')
  returning id into v_doc_emitido;
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.documento_emitido (codigo, orden_id, tipo, version, contenido, plantilla_version)
       values ('DOC-A2', %L, 'COMPROBANTE_ENTREGA', 2, '{}', 'entrega-2026-10-28')$q$, v_orden),
    'versión nueva sin motivo ni reemplazo', '23514');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.texto_legal set titulo = 'x' where id = %L$q$, v_texto), 'un texto legal publicado no cambia', '23001');

  -- Cierre: una Orden cerrada no cambia ni admite registros, salvo los eventos del cierre.
  update rma.orden set estado_workflow = 'ENTREGADA', posicion_proceso = 'EVT-REP-999', cerrada_en = now() where id = v_orden;
  insert into rma.evento_negocio (orden_id, tipo_evento_id, accion_id, responsable_tipo)
  values (v_orden, (select id from rma.tipo_evento where codigo = 'EV-REP-037'), rma_pruebas.id('accion_A'), 'SISTEMA');
  perform rma_pruebas.debe_fallar(format(
    $q$update rma.orden set prioridad = 1 where id = %L$q$, v_orden), 'una Orden cerrada no cambia', '23001');
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.descuento (orden_id, motivo, usuario_id) values (%L, 'x', %L)$q$, v_orden, v_usuario),
    'una Orden cerrada no admite registros', '23001');

  -- Una Orden RT_INTERNO no se cobra.
  perform rma_pruebas.debe_fallar(format(
    $q$insert into rma.orden (origen, estado_workflow, posicion_proceso, cliente_id, equipo_id, equipo_marca, equipo_modelo, falla_reportada)
       values ('RT_INTERNO', 'REQUERIMIENTO', 'PROC-REP-040', %L, %L, 'Apple', 'iPhone', 'x')$q$,
    rma_pruebas.id('cliente_B'), rma_pruebas.id('equipo_B')),
    'RT_INTERNO no tiene Cliente', '23514');
end;
$$;

rollback;
