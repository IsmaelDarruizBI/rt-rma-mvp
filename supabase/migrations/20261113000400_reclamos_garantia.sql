-- Reclamos de garantía rechazados (macroiteración integral, DEC-MI-02;
-- cierra ABI-35 y ABI-34; DC15B, BR-REP-019, PROC-REP-036, EVT-REP-998).
--
-- Aditiva: tabla nueva. Cuando un reclamo de garantía no se admite (algún
-- Detalle vencido sin excepción) no se crea la Orden de garantía y la Orden
-- original no se modifica: el intento queda aquí. Es inmutable salvo su
-- continuación como reparación paga, que se completa una sola vez.

create table if not exists rma.reclamo_garantia (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^RGA-[0-9]{6,}$'),
  orden_origen_id uuid not null references rma.orden (id),
  detalles jsonb not null check (jsonb_typeof(detalles) = 'array'),
  equipo jsonb not null check (jsonb_typeof(equipo) = 'object'),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  vigencias jsonb not null default '[]' check (jsonb_typeof(vigencias) = 'array'),
  excepciones jsonb not null default '{}' check (jsonb_typeof(excepciones) = 'object'),
  resultado text not null check (resultado in ('RECHAZADO')),
  motivo text not null check (btrim(motivo) <> ''),
  orden_continuacion_id uuid unique references rma.orden (id),
  continuado_por uuid references rma.usuario (id),
  continuado_en timestamptz,
  constraint reclamo_continuacion_completa check (
    (orden_continuacion_id is null) = (continuado_por is null)
    and (orden_continuacion_id is null) = (continuado_en is null)
  )
);

create index if not exists reclamo_garantia_origen on rma.reclamo_garantia (orden_origen_id);

create or replace function rma.reclamo_garantia_solo_continuar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'Un reclamo de garantía no se borra.';
  end if;
  if old.orden_continuacion_id is not null
     or (to_jsonb(new) - array['orden_continuacion_id', 'continuado_por', 'continuado_en'])
        is distinct from
        (to_jsonb(old) - array['orden_continuacion_id', 'continuado_por', 'continuado_en']) then
    raise exception 'Un reclamo de garantía solo se completa con su continuación, una vez.';
  end if;
  return new;
end;
$$;

drop trigger if exists reclamo_garantia_inmutable on rma.reclamo_garantia;
create trigger reclamo_garantia_inmutable before update or delete on rma.reclamo_garantia
  for each row execute function rma.reclamo_garantia_solo_continuar();

comment on table rma.reclamo_garantia is
  'Reclamos de garantía rechazados (DEC-MI-02): Orden y trabajos reclamados, equipo, vigencia evaluada, motivo, excepciones pedidas, usuario y fecha. Inmutable salvo la continuación como reparación paga.';
comment on column rma.reclamo_garantia.id is 'Identificador interno del reclamo.';
comment on column rma.reclamo_garantia.codigo is 'Código público del reclamo (RGA-000001).';
comment on column rma.reclamo_garantia.orden_origen_id is 'Orden original entregada (referencia a orden); no se modifica.';
comment on column rma.reclamo_garantia.detalles is 'Códigos de los Detalles origen reclamados.';
comment on column rma.reclamo_garantia.equipo is 'Copia del Equipo de la Orden original.';
comment on column rma.reclamo_garantia.usuario_id is 'Quién registró el pedido (referencia a usuario).';
comment on column rma.reclamo_garantia.registrado_en is 'Fecha y hora del pedido.';
comment on column rma.reclamo_garantia.vigencias is 'Vigencia evaluada de cada Detalle: plazo, vencimiento, vigente y excepción autorizada.';
comment on column rma.reclamo_garantia.excepciones is 'Motivos de excepción que traía el pedido, por Detalle.';
comment on column rma.reclamo_garantia.resultado is 'RECHAZADO.';
comment on column rma.reclamo_garantia.motivo is 'Motivo del rechazo.';
comment on column rma.reclamo_garantia.orden_continuacion_id is 'Orden paga de CLIENTE_EXTERNO que continuó el reclamo (referencia a orden); una sola.';
comment on column rma.reclamo_garantia.continuado_por is 'Quién lo continuó (referencia a usuario).';
comment on column rma.reclamo_garantia.continuado_en is 'Cuándo se continuó.';

grant select, insert on rma.reclamo_garantia to rma_backend;
grant update (orden_continuacion_id, continuado_por, continuado_en) on rma.reclamo_garantia to rma_backend;

-- El alta de la Orden que continúa un reclamo deja un paso en su historial.
insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select 'FUNCTIONAL_ACTION', 'ACC-REP-MI02', null, t.id
from rma.tipo_evento t where t.codigo = 'EV-REP-001'
on conflict on constraint equivalencia_unica do nothing;
