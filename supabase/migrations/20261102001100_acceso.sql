-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 1100. Acceso (G-5): solo el backend FastAPI.
--
-- rma_backend es un rol sin inicio de sesión que concentra los permisos. El
-- usuario con que se conecta FastAPI se crea en cada entorno, fuera de Git, y
-- recibe este rol (ver supabase/README.md). Los roles anon, authenticated y
-- service_role de Supabase no tienen ningún acceso al esquema rma, y el esquema
-- no se expone por la API de datos. Sin USAGE sobre el esquema, ninguna
-- concesión posterior sobre una tabla les da acceso.
--
-- Inmutabilidad por permisos, además de los triggers: el backend no puede
-- borrar nada, y solo actualiza las tablas de estado actual y, en ellas, las
-- columnas que corresponden.

do $$
begin
  if not exists (select 1 from pg_roles where rolname = 'rma_backend') then
    create role rma_backend nologin;
  end if;
end;
$$;

comment on role rma_backend is
  'Permisos del backend FastAPI de Rosario Tecno RMA sobre el esquema rma. Sin inicio de sesión: se otorga al usuario de conexión de cada entorno.';

revoke all on schema rma from public;
revoke all on all tables in schema rma from public;
revoke all on all sequences in schema rma from public;
revoke all on all functions in schema rma from public;

do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on schema rma from %I', v_rol);
      execute format('revoke all on all tables in schema rma from %I', v_rol);
      execute format('revoke all on all sequences in schema rma from %I', v_rol);
      execute format('revoke all on all functions in schema rma from %I', v_rol);
    end if;
  end loop;
end;
$$;

grant usage on schema rma to rma_backend;

-- Lectura de todas las tablas y vistas.
grant select on all tables in schema rma to rma_backend;

-- Alta en todas las tablas operativas. Los catálogos de referencia
-- (rol, tipo_evento, equivalencia_historial) se cargan solo por migración.
grant insert on
  rma.usuario, rma.usuario_rol, rma.mesa_trabajo, rma.tipo_reparacion, rma.mesa_tipo_reparacion,
  rma.medio_pago, rma.tipo_documento, rma.motivo_ajuste, rma.empresa, rma.texto_legal,
  rma.insumo, rma.tipo_reparacion_insumo,
  rma.accion_usuario, rma.auditoria_tecnica,
  rma.cliente, rma.documento_cliente, rma.modelo_equipo, rma.equipo,
  rma.orden, rma.recepcion, rma.recepcion_version, rma.recepcion_nota, rma.checkin, rma.salida, rma.foto,
  rma.detalle, rma.orden_detalle_origen, rma.detalle_version, rma.decision_cliente, rma.ajuste_garantia,
  rma.toma, rma.ejecucion, rma.ejecucion_insumo, rma.control_tecnico,
  rma.movimiento_inventario, rma.override_recursos, rma.override_insumo,
  rma.pago, rma.devolucion_dinero, rma.descuento, rma.documento_emitido,
  rma.evento_negocio
to rma_backend;

-- Actualización solo del estado actual y de los catálogos.
grant update on
  rma.usuario, rma.mesa_trabajo, rma.tipo_reparacion, rma.medio_pago, rma.tipo_documento,
  rma.motivo_ajuste, rma.empresa, rma.cliente, rma.modelo_equipo, rma.equipo,
  rma.orden, rma.recepcion, rma.detalle, rma.toma, rma.ejecucion
to rma_backend;

-- Columnas actualizables en tablas con una sola modificación permitida.
grant update (nombre, unidad, activo) on rma.insumo to rma_backend;
grant update (vigente_hasta, reemplazado_por_id) on rma.documento_cliente to rma_backend;
grant update (anulado_por, anulado_en, anulacion_motivo) on rma.pago to rma_backend;
grant update (respuesta, orden_id) on rma.accion_usuario to rma_backend;

-- Borrado solo de asignaciones de rol (retirar un rol).
grant delete on rma.usuario_rol to rma_backend;

grant usage, select on all sequences in schema rma to rma_backend;
grant execute on function rma.verificar_integridad() to rma_backend;
