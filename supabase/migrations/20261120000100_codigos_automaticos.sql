-- Rosario Tecno RMA — Códigos automáticos de catálogos y compras
-- (Configuración v2, CFG-01; docs/configuracion-discovery.md, sección 1).
--
-- Aditiva y compatible con el código anterior:
--   * una secuencia por prefijo y rma.siguiente_codigo(prefijo): el código
--     siguiente que no esté usado. Concurrente sin bloquear filas; puede
--     dejar huecos (aprobado). Cada secuencia arranca después del mayor
--     sufijo numérico existente con el mismo formato: ningún código
--     histórico cambia ni se reutiliza, y los que no siguen el patrón
--     (TR-OTROS, CANC-OTRO, códigos de prueba como TR-OFF) se ignoran;
--   * el código de los catálogos no cambia nunca (trigger): hoy solo lo
--     impedía el servicio;
--   * unicidad sin distinguir mayúsculas en tipo_reparacion e insumo (D6).
--     Si hay códigos que solo difieren en mayúsculas, la migración se
--     detiene y los lista: no corrige datos por su cuenta.
--
-- El backend anterior sigue funcionando: escribe los códigos que recibe o
-- calcula (max+1) y la función saltea los que ya existen.

-- ---------------------------------------------------------------------------
-- Verificación previa: códigos que solo difieren en mayúsculas
-- ---------------------------------------------------------------------------
do $$
declare
  v_choques text;
begin
  select string_agg(detalle, '; ') into v_choques
  from (
    select 'tipo_reparacion.codigo ' || string_agg(codigo, ', ' order by codigo) as detalle
      from rma.tipo_reparacion group by upper(codigo) having count(*) > 1
    union all
    select 'insumo.clave ' || string_agg(clave, ', ' order by clave)
      from rma.insumo group by upper(clave) having count(*) > 1
    union all
    select 'insumo.codigo ' || string_agg(codigo, ', ' order by codigo)
      from rma.insumo group by upper(codigo) having count(*) > 1
  ) choques;
  if v_choques is not null then
    raise exception 'Códigos que solo difieren en mayúsculas: %. Corregilos antes de migrar.', v_choques
      using errcode = 'unique_violation';
  end if;
end;
$$;

create unique index if not exists tipo_reparacion_codigo_mayusculas
  on rma.tipo_reparacion (upper(codigo));
create unique index if not exists insumo_clave_mayusculas
  on rma.insumo (upper(clave));
create unique index if not exists insumo_codigo_mayusculas
  on rma.insumo (upper(codigo));

-- ---------------------------------------------------------------------------
-- Secuencias por prefijo
-- ---------------------------------------------------------------------------
create sequence if not exists rma.codigo_tr_seq;
create sequence if not exists rma.codigo_canc_seq;
create sequence if not exists rma.codigo_int_seq;
create sequence if not exists rma.codigo_ins_seq;
create sequence if not exists rma.codigo_prv_seq;
create sequence if not exists rma.codigo_chk_seq;
create sequence if not exists rma.codigo_sc_seq;
create sequence if not exists rma.codigo_oc_seq;
create sequence if not exists rma.codigo_rga_seq;

comment on sequence rma.codigo_tr_seq is 'Número de los códigos TR-NNN de tipo_reparacion (rma.siguiente_codigo).';
comment on sequence rma.codigo_canc_seq is 'Número de los códigos CANC-NNN de motivo_operativo (CANCELACION).';
comment on sequence rma.codigo_int_seq is 'Número de los códigos INT-NNN de motivo_operativo (INTERRUPCION).';
comment on sequence rma.codigo_ins_seq is 'Número de los códigos INS-NNN de insumo (clave y, por defecto, código).';
comment on sequence rma.codigo_prv_seq is 'Número de los códigos PRV-NNNN de proveedor.';
comment on sequence rma.codigo_chk_seq is 'Número de los códigos CHK-NNNN de checklist_pregunta.';
comment on sequence rma.codigo_sc_seq is 'Número de los códigos SC-NNNNNN de solicitud_compra.';
comment on sequence rma.codigo_oc_seq is 'Número de los códigos OC-NNNNNN de orden_compra.';
comment on sequence rma.codigo_rga_seq is 'Número de los códigos RGA-NNNNNN de reclamo_garantia.';

-- Arranque: el mayor sufijo numérico con el formato del prefijo. Una
-- secuencia ya avanzada (migración repetida) no retrocede.
create or replace function rma.iniciar_secuencia_codigo(p_secuencia regclass, p_maximo bigint)
returns void
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_actual bigint;
  v_usada boolean;
begin
  execute format('select last_value, is_called from %s', p_secuencia) into v_actual, v_usada;
  if p_maximo > 0 and (not v_usada or v_actual < p_maximo) then
    perform setval(p_secuencia, p_maximo, true);
  end if;
end;
$$;

revoke all on function rma.iniciar_secuencia_codigo(regclass, bigint) from public;

select rma.iniciar_secuencia_codigo('rma.codigo_tr_seq', coalesce(
  (select max(substring(codigo from '^TR-([0-9]{1,18})$')::bigint) from rma.tipo_reparacion), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_canc_seq', coalesce(
  (select max(substring(codigo from '^CANC-([0-9]{1,18})$')::bigint) from rma.motivo_operativo), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_int_seq', coalesce(
  (select max(substring(codigo from '^INT-([0-9]{1,18})$')::bigint) from rma.motivo_operativo), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_ins_seq', coalesce(
  (select max(n) from (
     select substring(upper(clave) from '^INS-([0-9]{1,18})$')::bigint as n from rma.insumo
     union all
     select substring(upper(codigo) from '^INS-([0-9]{1,18})$')::bigint from rma.insumo
   ) numeros), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_prv_seq', coalesce(
  (select max(substring(codigo from '^PRV-([0-9]{1,18})$')::bigint) from rma.proveedor), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_chk_seq', coalesce(
  (select max(substring(codigo from '^CHK-([0-9]{1,18})$')::bigint) from rma.checklist_pregunta), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_sc_seq', coalesce(
  (select max(substring(codigo from '^SC-([0-9]{1,18})$')::bigint) from rma.solicitud_compra), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_oc_seq', coalesce(
  (select max(substring(codigo from '^OC-([0-9]{1,18})$')::bigint) from rma.orden_compra), 0));
select rma.iniciar_secuencia_codigo('rma.codigo_rga_seq', coalesce(
  (select max(substring(codigo from '^RGA-([0-9]{1,18})$')::bigint) from rma.reclamo_garantia), 0));

drop function rma.iniciar_secuencia_codigo(regclass, bigint);

-- ---------------------------------------------------------------------------
-- rma.siguiente_codigo(prefijo)
-- ---------------------------------------------------------------------------
-- Cada prefijo tiene su secuencia, su ancho mínimo y la tabla donde se
-- verifica que el código no esté usado (sin distinguir mayúsculas). Todo
-- es texto fijo: no hay SQL dinámico. Un número ya usado (un código que se
-- cargó a mano o con el backend anterior) se saltea; la secuencia nunca
-- repite, así que dos llamadas concurrentes no reciben el mismo código.
create or replace function rma.siguiente_codigo(p_prefijo text)
returns text
language plpgsql
volatile
set search_path = rma, pg_temp
as $$
declare
  v_numero bigint;
  v_ancho integer;
  v_codigo text;
  v_usado boolean;
  v_intentos integer := 0;
begin
  loop
    v_intentos := v_intentos + 1;
    if v_intentos > 100000 then
      raise exception 'No hay un código % libre.', p_prefijo using errcode = 'unique_violation';
    end if;
    case p_prefijo
      when 'TR' then v_numero := nextval('rma.codigo_tr_seq'); v_ancho := 3;
      when 'CANC' then v_numero := nextval('rma.codigo_canc_seq'); v_ancho := 3;
      when 'INT' then v_numero := nextval('rma.codigo_int_seq'); v_ancho := 3;
      when 'INS' then v_numero := nextval('rma.codigo_ins_seq'); v_ancho := 3;
      when 'PRV' then v_numero := nextval('rma.codigo_prv_seq'); v_ancho := 4;
      when 'CHK' then v_numero := nextval('rma.codigo_chk_seq'); v_ancho := 4;
      when 'SC' then v_numero := nextval('rma.codigo_sc_seq'); v_ancho := 6;
      when 'OC' then v_numero := nextval('rma.codigo_oc_seq'); v_ancho := 6;
      when 'RGA' then v_numero := nextval('rma.codigo_rga_seq'); v_ancho := 6;
      else
        raise exception 'Prefijo de código desconocido: %', p_prefijo using errcode = 'invalid_parameter_value';
    end case;
    -- Sin truncar: lpad corta los números más largos que el ancho.
    v_codigo := p_prefijo || '-' || lpad(v_numero::text, greatest(v_ancho, length(v_numero::text)), '0');
    v_usado := case p_prefijo
      when 'TR' then exists (select 1 from rma.tipo_reparacion where upper(codigo) = v_codigo)
      when 'CANC' then exists (select 1 from rma.motivo_operativo where upper(codigo) = v_codigo)
      when 'INT' then exists (select 1 from rma.motivo_operativo where upper(codigo) = v_codigo)
      when 'INS' then exists (
        select 1 from rma.insumo where upper(clave) = v_codigo or upper(codigo) = v_codigo)
      when 'PRV' then exists (select 1 from rma.proveedor where upper(codigo) = v_codigo)
      when 'CHK' then exists (select 1 from rma.checklist_pregunta where upper(codigo) = v_codigo)
      when 'SC' then exists (select 1 from rma.solicitud_compra where codigo = v_codigo)
      when 'OC' then exists (select 1 from rma.orden_compra where codigo = v_codigo)
      when 'RGA' then exists (select 1 from rma.reclamo_garantia where codigo = v_codigo)
    end;
    exit when not v_usado;
  end loop;
  return v_codigo;
end;
$$;

comment on function rma.siguiente_codigo(text) is
  'Código siguiente libre de un prefijo (TR, CANC, INT, INS, PRV, CHK, SC, OC, RGA): secuencia propia, ancho mínimo sin truncar y salto de los códigos ya usados. Puede dejar huecos; nunca repite.';

-- ---------------------------------------------------------------------------
-- El código de un catálogo no cambia
-- ---------------------------------------------------------------------------
create or replace function rma.impedir_cambio_codigo()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if new.codigo is distinct from old.codigo then
    raise exception 'El código % de % no cambia.', old.codigo, tg_table_name
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.impedir_cambio_codigo() is
  'Rechaza cambiar el código público de un catálogo: lo registrado lo referencia (Configuración v2, CFG-01).';

drop trigger if exists tipo_reparacion_codigo_fijo on rma.tipo_reparacion;
create trigger tipo_reparacion_codigo_fijo before update of codigo on rma.tipo_reparacion
  for each row execute function rma.impedir_cambio_codigo();
drop trigger if exists motivo_operativo_codigo_fijo on rma.motivo_operativo;
create trigger motivo_operativo_codigo_fijo before update of codigo on rma.motivo_operativo
  for each row execute function rma.impedir_cambio_codigo();
drop trigger if exists plantilla_mensaje_codigo_fijo on rma.plantilla_mensaje;
create trigger plantilla_mensaje_codigo_fijo before update of codigo on rma.plantilla_mensaje
  for each row execute function rma.impedir_cambio_codigo();
drop trigger if exists proveedor_codigo_fijo on rma.proveedor;
create trigger proveedor_codigo_fijo before update of codigo on rma.proveedor
  for each row execute function rma.impedir_cambio_codigo();
drop trigger if exists checklist_pregunta_codigo_fijo on rma.checklist_pregunta;
create trigger checklist_pregunta_codigo_fijo before update of codigo on rma.checklist_pregunta
  for each row execute function rma.impedir_cambio_codigo();
drop trigger if exists mesa_trabajo_codigo_fijo on rma.mesa_trabajo;
create trigger mesa_trabajo_codigo_fijo before update of codigo on rma.mesa_trabajo
  for each row execute function rma.impedir_cambio_codigo();

-- ---------------------------------------------------------------------------
-- Accesos: solo el backend genera códigos
-- ---------------------------------------------------------------------------
revoke all on function rma.siguiente_codigo(text) from public;
revoke all on function rma.impedir_cambio_codigo() from public;
revoke all on sequence
  rma.codigo_tr_seq, rma.codigo_canc_seq, rma.codigo_int_seq, rma.codigo_ins_seq,
  rma.codigo_prv_seq, rma.codigo_chk_seq, rma.codigo_sc_seq, rma.codigo_oc_seq,
  rma.codigo_rga_seq
  from public;

do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on function rma.siguiente_codigo(text) from %I', v_rol);
      execute format('revoke all on function rma.impedir_cambio_codigo() from %I', v_rol);
      execute format(
        'revoke all on sequence rma.codigo_tr_seq, rma.codigo_canc_seq, rma.codigo_int_seq, '
        'rma.codigo_ins_seq, rma.codigo_prv_seq, rma.codigo_chk_seq, rma.codigo_sc_seq, '
        'rma.codigo_oc_seq, rma.codigo_rga_seq from %I', v_rol);
    end if;
  end loop;
end;
$$;

grant execute on function rma.siguiente_codigo(text) to rma_backend;
grant usage on sequence
  rma.codigo_tr_seq, rma.codigo_canc_seq, rma.codigo_int_seq, rma.codigo_ins_seq,
  rma.codigo_prv_seq, rma.codigo_chk_seq, rma.codigo_sc_seq, rma.codigo_oc_seq,
  rma.codigo_rga_seq
  to rma_backend;
