-- Rosario Tecno RMA — Utilidades de las pruebas de esquema.
-- Se cargan en el esquema rma_pruebas, que las pruebas usan y descartan.
-- Cada archivo de prueba corre en una transacción que termina en ROLLBACK.

create schema if not exists rma_pruebas;

-- Ejecuta una sentencia que debe fallar con un código de error concreto.
create or replace function rma_pruebas.debe_fallar(sentencia text, caso text, estado_esperado text)
returns void
language plpgsql
as $$
begin
  begin
    execute sentencia;
  exception when others then
    if sqlstate <> estado_esperado then
      raise exception 'Caso «%»: falló con % (%), se esperaba %.', caso, sqlstate, sqlerrm, estado_esperado;
    end if;
    return;
  end;
  raise exception 'Caso «%»: la sentencia debía fallar y se ejecutó.', caso;
end;
$$;

create or replace function rma_pruebas.debe_ser(valor anyelement, esperado anyelement, caso text)
returns void
language plpgsql
as $$
begin
  if valor is distinct from esperado then
    raise exception 'Caso «%»: se obtuvo %, se esperaba %.', caso, valor, esperado;
  end if;
end;
$$;

-- Datos mínimos de prueba: usuario, Cliente, Equipo, Orden, Detalle con su versión,
-- toma y una acción confirmada. Devuelve los identificadores en una tabla temporal.
create or replace function rma_pruebas.preparar_orden(sufijo text)
returns void
language plpgsql
as $$
declare
  v_usuario uuid; v_cliente uuid; v_equipo uuid; v_orden uuid; v_detalle uuid;
  v_version uuid; v_tipo uuid; v_mesa uuid; v_toma uuid; v_accion uuid;
begin
  insert into rma.usuario (codigo, nombre) values ('USR-' || sufijo, 'Usuario ' || sufijo) returning id into v_usuario;
  insert into rma.cliente (codigo, nombre, telefono) values ('CLI-' || sufijo, 'Cliente ' || sufijo, '341000000') returning id into v_cliente;
  insert into rma.equipo (codigo) values ('EQ-' || sufijo) returning id into v_equipo;
  insert into rma.orden (origen, estado_workflow, posicion_proceso, cliente_id, equipo_id,
                         cliente_nombre, equipo_marca, equipo_modelo, falla_reportada)
  values ('CLIENTE_EXTERNO', 'EN_COLA', 'PROC-REP-170', v_cliente, v_equipo,
          'Cliente ' || sufijo, 'Apple', 'iPhone 14', 'No carga') returning id into v_orden;
  insert into rma.tipo_reparacion (codigo, nombre, precio, puntaje, garantia_dias)
  values ('TR-' || sufijo, 'Cambio de batería ' || sufijo, 80000, 10, 90) returning id into v_tipo;
  insert into rma.detalle (orden_id, codigo, garantia_dias) values (v_orden, 'DET-001', 90) returning id into v_detalle;
  insert into rma.detalle_version (detalle_id, numero, tipo_reparacion_id, precio, puntaje, garantia_dias, definida_por)
  values (v_detalle, 1, v_tipo, 80000, 10, 90, v_usuario) returning id into v_version;
  insert into rma.mesa_trabajo (codigo, nombre) values ('MESA-' || sufijo, 'Mesa ' || sufijo) returning id into v_mesa;
  insert into rma.toma (codigo, orden_id, usuario_id, mesa_trabajo_id) values ('TOM-' || sufijo, v_orden, v_usuario, v_mesa) returning id into v_toma;
  insert into rma.accion_usuario (usuario_id, rol_codigo, operacion, resultado)
  values (v_usuario, 'TECNICO', 'PRUEBA', 'CONFIRMADA') returning id into v_accion;

  create temp table if not exists ctx (clave text primary key, valor uuid) on commit drop;
  insert into ctx values
    ('usuario_' || sufijo, v_usuario), ('cliente_' || sufijo, v_cliente), ('equipo_' || sufijo, v_equipo),
    ('orden_' || sufijo, v_orden), ('detalle_' || sufijo, v_detalle), ('version_' || sufijo, v_version),
    ('tipo_' || sufijo, v_tipo), ('mesa_' || sufijo, v_mesa), ('toma_' || sufijo, v_toma), ('accion_' || sufijo, v_accion);
end;
$$;

-- Las pruebas de permisos ejecutan estas utilidades como rma_backend.
grant usage on schema rma_pruebas to rma_backend;

create or replace function rma_pruebas.id(p_clave text)
returns uuid
language plpgsql
as $$
declare
  v uuid;
begin
  execute 'select valor from ctx where clave = $1' into v using p_clave;
  if v is null then raise exception 'Dato de prueba % no preparado.', p_clave; end if;
  return v;
end;
$$;
