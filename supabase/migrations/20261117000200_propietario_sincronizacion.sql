-- Rosario Tecno RMA — Propietario de una sincronización (bloque C, QA C1 M3).
--
-- Solo quien reservó una sincronización puede escribir la copia y finalizar
-- el intento. Al reservar se entrega un secreto aleatorio (propietario); la
-- base guarda solo su hash (SHA-256). Para escribir una fila de la copia o
-- finalizar el intento, la sentencia trae el secreto en la columna
-- transitoria «propietario»: el trigger compara su hash y la vacía, y un
-- CHECK garantiza que nunca queda guardada. Sin estado de sesión ni
-- funciones SECURITY DEFINER.
--
-- Dar por INTERRUMPIDA una reserva vencida no exige el secreto: es la toma
-- de una reserva abandonada, y solo vale si venció.
--
-- Aditiva sobre 20261117000100 (nunca aplicada fuera de bases locales):
-- dos columnas por tabla, las funciones reemplazadas y la reserva con un
-- parámetro más.

alter table rma.sincronizacion_origen
  add column if not exists propietario_hash text
    check (propietario_hash ~ '^[0-9a-f]{64}$');
alter table rma.sincronizacion_origen
  add column if not exists propietario text;
alter table rma.sincronizacion_origen
  drop constraint if exists sincronizacion_origen_propietario_transitorio;
alter table rma.sincronizacion_origen
  add constraint sincronizacion_origen_propietario_transitorio check (propietario is null);

alter table rma.catalogo_producto
  add column if not exists propietario text;
alter table rma.catalogo_producto
  drop constraint if exists catalogo_producto_propietario_transitorio;
alter table rma.catalogo_producto
  add constraint catalogo_producto_propietario_transitorio check (propietario is null);

comment on column rma.sincronizacion_origen.propietario_hash is
  'SHA-256 (hexadecimal) del secreto de quien reservó: solo esa sincronización escribe la copia y finaliza el intento.';
comment on column rma.sincronizacion_origen.propietario is
  'Transitoria: el secreto del propietario viaja en la sentencia que finaliza; el trigger lo verifica y lo vacía. Nunca se guarda.';
comment on column rma.catalogo_producto.propietario is
  'Transitoria: el secreto de la sincronización en curso viaja en cada escritura; el trigger lo verifica y lo vacía. Nunca se guarda. En un INSERT ... ON CONFLICT DO UPDATE, excluded.propietario ya llega vacío (lo vació el trigger del INSERT): el DO UPDATE repite el secreto como parámetro.';

-- Hash del secreto, igual en todos los triggers.
create or replace function rma.hash_propietario(p_propietario text)
returns text
language sql
immutable
set search_path = rma, pg_temp
as $$
  select encode(sha256(convert_to(p_propietario, 'UTF8')), 'hex')
$$;

comment on function rma.hash_propietario(text) is
  'SHA-256 hexadecimal del secreto del propietario de una sincronización.';

create or replace function rma.sincronizacion_origen_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'En rma.sincronizacion_origen no se borran filas: son el registro de los intentos.'
      using errcode = 'restrict_violation';
  end if;
  if tg_op = 'INSERT' then
    if new.resultado <> 'EN_CURSO' or new.finalizada_en is not null then
      raise exception 'Un intento de sincronización nace EN_CURSO.'
        using errcode = 'check_violation';
    end if;
    -- La reserva usa la hora de la base y dura una hora como máximo.
    new.iniciada_en := now();
    if new.vence_en is null or new.vence_en <= new.iniciada_en
       or new.vence_en > new.iniciada_en + interval '1 hour' then
      raise exception 'La reserva debe vencer después de ahora y dentro de una hora.'
        using errcode = 'check_violation';
    end if;
    -- Nace con su propietario: el secreto se guarda como hash.
    if new.propietario is null or length(new.propietario) < 32 then
      raise exception 'Una reserva necesita el secreto de su propietario.'
        using errcode = 'check_violation';
    end if;
    new.propietario_hash := rma.hash_propietario(new.propietario);
    new.propietario := null;
    return new;
  end if;
  -- UPDATE
  if old.resultado <> 'EN_CURSO' then
    raise exception 'El intento % ya terminó (%): no cambia más.', old.id, old.resultado
      using errcode = 'restrict_violation';
  end if;
  if (new.id, new.copia, new.usuario_id, new.origen, new.filtro, new.iniciada_en, new.vence_en, new.propietario_hash)
     is distinct from
     (old.id, old.copia, old.usuario_id, old.origen, old.filtro, old.iniciada_en, old.vence_en, old.propietario_hash) then
    raise exception 'De un intento solo cambian su resultado, su fin, su mensaje y sus contadores.'
      using errcode = 'restrict_violation';
  end if;
  if new.resultado = 'EN_CURSO' then
    raise exception 'Un intento EN_CURSO solo pasa a un resultado final.'
      using errcode = 'restrict_violation';
  end if;
  if new.resultado = 'INTERRUMPIDA' then
    if old.vence_en > now() then
      raise exception 'El intento % todavía no venció: no se puede dar por interrumpido.', old.id
        using errcode = 'restrict_violation';
    end if;
  elsif old.propietario_hash is null
        or new.propietario is null
        or rma.hash_propietario(new.propietario) <> old.propietario_hash then
    raise exception 'Solo quien reservó el intento % puede finalizarlo.', old.id
      using errcode = 'insufficient_privilege';
  end if;
  new.propietario := null;
  -- El fin es siempre la hora de la base al finalizar.
  new.finalizada_en := now();
  return new;
end;
$$;

comment on function rma.sincronizacion_origen_validar() is
  'Un intento nace EN_CURSO con la hora de la base, una reserva de una hora como máximo y el hash del secreto de su propietario; solo su propietario lo finaliza (EXITOSA, FALLIDA, RECHAZADA), con la hora de la base; INTERRUMPIDA solo si venció; no se borra.';

create or replace function rma.catalogo_producto_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_copia text;
  v_resultado text;
  v_hash text;
begin
  select copia, resultado, propietario_hash into v_copia, v_resultado, v_hash
    from rma.sincronizacion_origen where id = new.sincronizacion_id for share;
  if v_copia is distinct from 'CATALOGO_VENTAS' or v_resultado is distinct from 'EN_CURSO' then
    raise exception 'La copia del catálogo solo se escribe dentro de una sincronización EN_CURSO de CATALOGO_VENTAS (intento %: %).',
      new.sincronizacion_id, coalesce(v_resultado, 'inexistente')
      using errcode = 'restrict_violation';
  end if;
  if v_hash is null or new.propietario is null or rma.hash_propietario(new.propietario) <> v_hash then
    raise exception 'Solo la sincronización que reservó el intento % escribe la copia.', new.sincronizacion_id
      using errcode = 'insufficient_privilege';
  end if;
  new.propietario := null;
  if tg_op = 'UPDATE' and (new.tipo_producto_id, new.primera_sincronizacion, new.creado_en)
     is distinct from (old.tipo_producto_id, old.primera_sincronizacion, old.creado_en) then
    raise exception 'El identificador y la primera sincronización de un producto no cambian.'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.catalogo_producto_validar() is
  'La copia del catálogo se escribe solo dentro de una sincronización EN_CURSO de CATALOGO_VENTAS y con el secreto de su propietario; su identificador y su primera sincronización no cambian.';

-- La reserva recibe el secreto de su propietario.
drop function if exists rma.reservar_sincronizacion(text, text, uuid, text, text, interval);

create or replace function rma.reservar_sincronizacion(
  p_id text,
  p_copia text,
  p_usuario_id uuid,
  p_origen text,
  p_filtro text,
  p_duracion interval,
  p_propietario text
)
returns table (id text, iniciada_en timestamptz, vence_en timestamptz)
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if p_duracion is null or p_duracion <= interval '0' or p_duracion > interval '1 hour' then
    raise exception 'La duración de la reserva debe ser mayor que cero y de una hora como máximo.'
      using errcode = 'check_violation';
  end if;
  update rma.sincronizacion_origen s
     set resultado = 'INTERRUMPIDA',
         mensaje = 'La reserva venció sin terminar (instancia apagada o caída a mitad).'
   where s.copia = p_copia and s.resultado = 'EN_CURSO' and s.vence_en <= now();
  return query
  insert into rma.sincronizacion_origen as s
    (id, copia, usuario_id, origen, filtro, iniciada_en, vence_en, propietario)
  values (p_id, p_copia, p_usuario_id, p_origen, coalesce(p_filtro, ''), now(), now() + p_duracion, p_propietario)
  returning s.id, s.iniciada_en, s.vence_en;
end;
$$;

comment on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval, text) is
  'Reserva la sincronización de una copia con el secreto de su propietario: interrumpe una reserva vencida y crea la nueva con la hora de la base; con otra vigente, unique_violation.';

-- Permisos: el secreto viaja en la columna transitoria al finalizar y al
-- escribir la copia; la nueva reserva solo para rma_backend.
grant update (propietario) on rma.sincronizacion_origen to rma_backend;
grant update (propietario) on rma.catalogo_producto to rma_backend;

revoke all on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval, text) from public;
grant execute on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval, text) to rma_backend;
revoke all on function rma.hash_propietario(text) from public;
grant execute on function rma.hash_propietario(text) to rma_backend;
do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval, text) from %I', v_rol);
      execute format('revoke all on function rma.hash_propietario(text) from %I', v_rol);
    end if;
  end loop;
end;
$$;
