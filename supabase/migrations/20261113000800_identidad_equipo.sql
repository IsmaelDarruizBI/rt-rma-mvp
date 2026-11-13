-- Identidad del Equipo (macroiteración integral, DEC-MI-11; cierra ABI-05).
--
-- Aditiva:
--   * `correccion_vinculo_equipo`: cada corrección de la vinculación de una
--     Orden con un Equipo (de qué identidad a cuál, motivo, quién y cuándo).
--     Inmutable. Los códigos de Equipo se guardan como texto: el destino
--     puede ser una identidad nueva que se crea en la misma operación;
--   * el comentario de `equipo` deja de decir que no hay reutilización:
--     un ingreso puede vincularse a un Equipo existente con el mismo IMEI
--     o número de serie (nunca por similitud).

create table if not exists rma.correccion_vinculo_equipo (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  equipo_anterior_codigo text not null,
  equipo_nuevo_codigo text not null,
  motivo text not null check (btrim(motivo) <> ''),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  posicion integer not null check (posicion >= 1),
  constraint correccion_vinculo_equipo_posicion unique (orden_id, posicion),
  constraint correccion_vinculo_equipo_distinto check (equipo_anterior_codigo <> equipo_nuevo_codigo)
);

drop trigger if exists correccion_vinculo_equipo_inmutable on rma.correccion_vinculo_equipo;
create trigger correccion_vinculo_equipo_inmutable before update or delete on rma.correccion_vinculo_equipo
  for each row execute function rma.impedir_modificacion();

comment on table rma.correccion_vinculo_equipo is
  'Correcciones de la vinculación de una Orden con un Equipo (DEC-MI-11): Recepción, Coordinación RMA o Administración, con motivo. Inmutables.';
comment on column rma.correccion_vinculo_equipo.id is 'Identificador interno de la corrección.';
comment on column rma.correccion_vinculo_equipo.orden_id is 'Orden corregida (referencia a orden).';
comment on column rma.correccion_vinculo_equipo.equipo_anterior_codigo is 'Código del Equipo al que estaba vinculada.';
comment on column rma.correccion_vinculo_equipo.equipo_nuevo_codigo is 'Código del Equipo al que queda vinculada (existente o nuevo).';
comment on column rma.correccion_vinculo_equipo.motivo is 'Por qué se corrige.';
comment on column rma.correccion_vinculo_equipo.usuario_id is 'Quién corrigió (referencia a usuario).';
comment on column rma.correccion_vinculo_equipo.registrado_en is 'Fecha y hora de la corrección.';
comment on column rma.correccion_vinculo_equipo.posicion is 'Orden de la corrección en la Orden.';

comment on table rma.equipo is
  'La unidad física que se repara. Un ingreso puede vincularse a un Equipo existente solo si comparte su IMEI o su número de serie (DEC-MI-11); nunca por similitud. Su historial son todas las Órdenes vinculadas.';

grant select, insert on rma.correccion_vinculo_equipo to rma_backend;
