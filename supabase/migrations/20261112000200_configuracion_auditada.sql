-- Administración de configuración con auditoría (macroiteración V1.4,
-- módulo E: DC23, DC23AUD, BR-REP-040, FEAT-REP-010).
--
-- Aditiva:
--   * tabla nueva `cambio_configuracion`, inmutable: cada cambio de un
--     catálogo con entidad, clave, campo, valor anterior y nuevo, usuario
--     y fecha/hora. El historial de precios de un Tipo de Reparación son
--     sus cambios del campo `precio` (vista `historial_precio`);
--   * `rma_backend` puede retirar un tipo habilitado de una Mesa de trabajo
--     (DELETE en `mesa_tipo_reparacion`); el cambio queda auditado.
-- No cambia filas existentes: lo ya registrado en Detalles, Ejecuciones y
-- documentos conserva su copia (BR-REP-015).

create table if not exists rma.cambio_configuracion (
  id uuid primary key default gen_random_uuid(),
  secuencia bigint generated always as identity,
  entidad text not null check (entidad in ('TIPO_REPARACION', 'MESA_TRABAJO')),
  clave text not null check (btrim(clave) <> ''),
  campo text not null check (btrim(campo) <> ''),
  valor_anterior text,
  valor_nuevo text,
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  constraint cambio_con_valor check (valor_anterior is not null or valor_nuevo is not null)
);

create index if not exists cambio_configuracion_clave
  on rma.cambio_configuracion (entidad, clave, secuencia);

drop trigger if exists cambio_configuracion_inmutable on rma.cambio_configuracion;
create trigger cambio_configuracion_inmutable before update or delete on rma.cambio_configuracion
  for each row execute function rma.impedir_modificacion();

comment on table rma.cambio_configuracion is
  'Auditoría de cada cambio de configuración (DC23AUD, BR-REP-040): un registro por campo cambiado. Inmutable.';
comment on column rma.cambio_configuracion.id is 'Identificador interno del registro.';
comment on column rma.cambio_configuracion.secuencia is 'Orden de registro de los cambios (desempata los de un mismo instante).';
comment on column rma.cambio_configuracion.entidad is 'Catálogo cambiado: TIPO_REPARACION o MESA_TRABAJO.';
comment on column rma.cambio_configuracion.clave is 'Código público del registro cambiado (por ejemplo TR-001 o EST-001).';
comment on column rma.cambio_configuracion.campo is 'Campo cambiado (por ejemplo precio o tipos_habilitados).';
comment on column rma.cambio_configuracion.valor_anterior is 'Valor anterior como texto; vacío en un alta.';
comment on column rma.cambio_configuracion.valor_nuevo is 'Valor nuevo como texto.';
comment on column rma.cambio_configuracion.usuario_id is 'Usuario que hizo el cambio (referencia a usuario).';
comment on column rma.cambio_configuracion.registrado_en is 'Fecha y hora del cambio.';

create or replace view rma.historial_precio as
select c.secuencia, c.clave as tipo_reparacion, c.valor_anterior as precio_anterior,
       c.valor_nuevo as precio_nuevo, c.usuario_id, c.registrado_en
from rma.cambio_configuracion c
where c.entidad = 'TIPO_REPARACION' and c.campo = 'precio';

comment on view rma.historial_precio is
  'Historial de precios de cada Tipo de Reparación (DC23AUD): sus cambios del campo precio.';

comment on column rma.historial_precio.secuencia is 'Orden de registro del cambio.';
comment on column rma.historial_precio.tipo_reparacion is 'Código del Tipo de Reparación.';
comment on column rma.historial_precio.precio_anterior is 'Precio anterior; vacío en el alta.';
comment on column rma.historial_precio.precio_nuevo is 'Precio desde el cambio.';
comment on column rma.historial_precio.usuario_id is 'Usuario que cambió el precio (referencia a usuario).';
comment on column rma.historial_precio.registrado_en is 'Fecha y hora del cambio.';

grant select, insert on rma.cambio_configuracion to rma_backend;
grant select on rma.historial_precio to rma_backend;
grant delete on rma.mesa_tipo_reparacion to rma_backend;
