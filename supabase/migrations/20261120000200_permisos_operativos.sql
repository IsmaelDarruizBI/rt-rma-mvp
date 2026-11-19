-- Rosario Tecno RMA — Permisos de Compras por acción (Configuración v2,
-- CFG-03, D5, DF-4 y DF-5; docs/configuracion-discovery.md, sección 3.3).
--
-- El backend reemplaza COMPRAS_GESTIONAR por COMPRA_SOLICITAR, OC_CREAR,
-- OC_CONFIRMAR, OC_CANCELAR y COMPRA_RECIBIR. Sin fila en rma.permiso rige
-- el predeterminado del código, que es el mismo de COMPRAS_GESTIONAR
-- (Recepción, Coordinación RMA y Administración). Si Administración lo
-- había cambiado, esos roles se copian a los cinco permisos nuevos: nadie
-- gana ni pierde un acceso (DF-4). La copia queda en la auditoría con el
-- usuario que hizo el último cambio de COMPRAS_GESTIONAR.
--
-- La fila de COMPRAS_GESTIONAR NO se borra: un backend anterior (vuelta
-- atrás) la sigue leyendo. El backend nuevo la ignora.
--
-- Los permisos nuevos de los catálogos (TIPO_REPARACION_GESTIONAR,
-- PRECIOS_GESTIONAR, ...) no necesitan filas: su predeterminado es solo
-- Administración (D2), igual que el CONFIGURACION_ADMINISTRAR anterior.
--
-- Idempotente: una fila ya existente de un permiso nuevo no se pisa.

do $$
declare
  v_roles text[];
  v_usuario uuid;
  v_codigo text;
begin
  select roles into v_roles from rma.permiso where codigo = 'COMPRAS_GESTIONAR';
  if v_roles is null then
    return;
  end if;
  select usuario_id into v_usuario
    from rma.cambio_configuracion
   where entidad = 'PERMISO' and clave = 'COMPRAS_GESTIONAR'
   order by secuencia desc
   limit 1;
  foreach v_codigo in array array['COMPRA_SOLICITAR', 'OC_CREAR', 'OC_CONFIRMAR', 'OC_CANCELAR', 'COMPRA_RECIBIR'] loop
    insert into rma.permiso (codigo, roles, modificado_en)
    values (v_codigo, v_roles, now())
    on conflict (codigo) do nothing;
    if found and v_usuario is not null then
      insert into rma.cambio_configuracion
        (entidad, clave, campo, valor_anterior, valor_nuevo, usuario_id, registrado_en)
      values
        ('PERMISO', v_codigo, 'roles', '(predeterminados)',
         array_to_string(v_roles, ', ') || ' (copiado de COMPRAS_GESTIONAR)', v_usuario, now());
    end if;
  end loop;
end;
$$;
