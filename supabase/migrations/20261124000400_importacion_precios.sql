-- Rosario Tecno RMA — Importación masiva de precios por modelo
-- (ajustes funcionales, iteración 2, bloque 7; DEC-AJ-13, BR-REP-040).
--
-- Aditiva y compatible con los registros existentes:
--   * tabla nueva `importacion_precio`, inmutable: cada importación aplicada
--     (quién, cuándo, el formato y el nombre del archivo, y cuántos precios
--     fueron nuevos, actualizados o quedaron sin cambios). Una importación
--     con errores o sin cambios no se aplica y no deja registro;
--   * `cambio_configuracion.importacion_id`: los cambios de precio de una
--     importación (entidad PRECIO_MODELO) comparten su identificador. Vacío
--     en los cambios anteriores y en la edición individual;
--   * `historial_precio`: `create or replace`, mismas columnas y una nueva al
--     final (`importacion_id`).
--
-- Ningún dato existente cambia.

create table if not exists rma.importacion_precio (
  id uuid primary key,
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  formato text not null check (formato in ('XLSX', 'CSV', 'TEXTO')),
  nombre_archivo text check (nombre_archivo is null or btrim(nombre_archivo) <> ''),
  precios_nuevos integer not null check (precios_nuevos >= 0),
  precios_actualizados integer not null check (precios_actualizados >= 0),
  precios_sin_cambio integer not null check (precios_sin_cambio >= 0),
  constraint importacion_precio_con_cambios check (precios_nuevos + precios_actualizados > 0)
);

drop trigger if exists importacion_precio_inmutable on rma.importacion_precio;
create trigger importacion_precio_inmutable before update or delete on rma.importacion_precio
  for each row execute function rma.impedir_modificacion();

comment on table rma.importacion_precio is
  'Importación masiva de precios por modelo aplicada (DEC-AJ-13): matriz de modelos Apple por Tipos de Reparación con precio por modelo, desde Excel .xlsx, CSV o celdas pegadas, aplicada todo o nada. Sus cambios de precio están en cambio_configuracion con este identificador (importacion_id). Inmutable.';
comment on column rma.importacion_precio.id is 'Identificador de la importación; lo comparten sus cambios en cambio_configuracion.';
comment on column rma.importacion_precio.usuario_id is 'Usuario que aplicó la importación (referencia a usuario).';
comment on column rma.importacion_precio.registrado_en is 'Fecha y hora en que se aplicó.';
comment on column rma.importacion_precio.formato is 'Cómo llegó la planilla: XLSX, CSV o TEXTO (celdas pegadas, separadas por tabulaciones).';
comment on column rma.importacion_precio.nombre_archivo is 'Nombre del archivo importado, como referencia; vacío en las celdas pegadas.';
comment on column rma.importacion_precio.precios_nuevos is 'Combinaciones que no tenían precio vigente.';
comment on column rma.importacion_precio.precios_actualizados is 'Combinaciones cuyo precio cambió.';
comment on column rma.importacion_precio.precios_sin_cambio is 'Celdas con el mismo precio vigente: no se escribieron ni se auditaron.';

grant select, insert on rma.importacion_precio to rma_backend;

-- ---------------------------------------------------------------------------
-- Auditoría agrupada por importación
-- ---------------------------------------------------------------------------
alter table rma.cambio_configuracion
  add column if not exists importacion_id uuid references rma.importacion_precio (id);

alter table rma.cambio_configuracion drop constraint if exists cambio_configuracion_importacion_precio;
alter table rma.cambio_configuracion add constraint cambio_configuracion_importacion_precio
  check (importacion_id is null or entidad = 'PRECIO_MODELO');

create index if not exists cambio_configuracion_importacion
  on rma.cambio_configuracion (importacion_id) where importacion_id is not null;

comment on column rma.cambio_configuracion.importacion_id is
  'Importación masiva de precios a la que pertenece el cambio (referencia a importacion_precio, DEC-AJ-13); vacío en los demás cambios.';

create or replace view rma.historial_precio as
select c.secuencia,
       case when c.entidad = 'PRECIO_MODELO' then split_part(c.clave, '/', 1) else c.clave end as tipo_reparacion,
       c.valor_anterior as precio_anterior,
       c.valor_nuevo as precio_nuevo, c.usuario_id, c.registrado_en,
       case when c.entidad = 'PRECIO_MODELO' then split_part(c.clave, '/', 2) end as modelo_equipo,
       c.importacion_id
from rma.cambio_configuracion c
where c.campo = 'precio' and c.entidad in ('TIPO_REPARACION', 'PRECIO_MODELO');

comment on column rma.historial_precio.importacion_id is
  'Importación masiva que cambió el precio (referencia a importacion_precio); vacío en la edición individual.';

grant select on rma.historial_precio to rma_backend;
