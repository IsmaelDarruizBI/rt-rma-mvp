-- E3: identificador del insumo en el dominio y orden de los catálogos visibles.
--
-- Aditiva: agrega columnas y restricciones; no borra ni reescribe datos,
-- salvo completar las columnas nuevas en las filas que ya existan.
-- Diseño: docs/postgresql/e3-catalogos-diseno.md (DE3-1 y DE3-2).

-- Guarda (QAF-13, QA-E3-6, QA-E3-7). En una base con datos (insumos,
-- usuarios o medios de pago ya cargados, como DEV/UAT), esta migración deja
-- la clave y el orden provisorios: hace falta el paso de identidad aprobado
-- de E8 en la misma sesión. Sin la autorización explícita, falla antes de
-- cambiar nada. Una base vacía (local, pruebas, un entorno nuevo) no la
-- necesita: las cargas fijan la clave y el orden.
-- Procedimiento y condición de desbloqueo: docs/postgresql/integracion-pendientes.md.
do $$
begin
  if (exists (select 1 from rma.insumo)
      or exists (select 1 from rma.usuario)
      or exists (select 1 from rma.medio_pago))
     and coalesce(current_setting('rma.migracion_e3', true), '')
         <> 'estrategia_identidad_aprobada' then
    raise exception using
      message = 'La migración E3 no se aplica sobre datos existentes sin la estrategia de identidad aprobada (QA-E3-6, QA-E3-7).',
      hint = 'Procedimiento de E8 en docs/postgresql/integracion-pendientes.md: en la misma sesión y transacción, set local rma.migracion_e3 = ''estrategia_identidad_aprobada'' y el paso de datos verificado.';
  end if;
end;
$$;

-- DE3-1. El dominio identifica cada insumo con un id estable (Insumo.id,
-- por ejemplo INS-001), distinto de su código operativo (BAT-IP14) y del
-- uuid técnico. Lo referencian los insumos previstos, los movimientos y
-- las Órdenes de la aplicación. Las relaciones de la base no cambian:
-- siguen usando el uuid.
alter table rma.insumo add column clave text;

-- Una fila anterior a E3 no tiene el id del dominio: provisoriamente toma
-- su código, que es único, así que no hay colisiones ni datos perdidos.
-- La carga regenerada (supabase/seeds) fija el valor del dominio.
update rma.insumo set clave = codigo where clave is null;

alter table rma.insumo
  alter column clave set not null,
  add constraint insumo_clave_unica unique (clave),
  add constraint insumo_clave_no_vacia check (btrim(clave) <> '');

comment on column rma.insumo.clave is
  'Identificador estable del insumo en el dominio de la aplicación (Insumo.id, por ejemplo INS-001). Distinto del código operativo y del uuid técnico.';

-- Un alta que no informa la clave (por ejemplo, un insumo creado fuera de
-- la aplicación) toma su código: la misma regla que las filas anteriores.
create or replace function rma.insumo_clave_por_defecto()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if new.clave is null then
    new.clave := new.codigo;
  end if;
  return new;
end;
$$;

comment on function rma.insumo_clave_por_defecto() is
  'Completa insumo.clave con el código cuando el alta no la informa.';

-- Como las demás funciones del esquema (1100): sin EXECUTE para PUBLIC ni
-- para los roles de Supabase. El trigger la ejecuta igual: el permiso se
-- verifica al crear el trigger, no al dispararse.
revoke all on function rma.insumo_clave_por_defecto() from public;

do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on function rma.insumo_clave_por_defecto() from %I', v_rol);
    end if;
  end loop;
end;
$$;

create trigger insumo_clave_por_defecto before insert on rma.insumo
  for each row execute function rma.insumo_clave_por_defecto();

-- DE3-2. Orden en que se muestran los usuarios y los medios de pago: el de
-- su catálogo de origen, que no es alfabético. Los demás catálogos se
-- ordenan por su código.
alter table rma.usuario add column orden integer not null default 0;
alter table rma.medio_pago add column orden integer not null default 0;

comment on column rma.usuario.orden is
  'Posición del usuario en los listados (ascendente; a igual orden, por código).';
comment on column rma.medio_pago.orden is
  'Posición del medio de pago en los listados (ascendente; a igual orden, por código).';
