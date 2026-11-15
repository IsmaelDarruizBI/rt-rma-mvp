-- Tipos de equipo del checklist desde el catálogo de Ventas de Gestión RT
-- (DC12, decisión aprobada el 15/11/2026).
--
-- `rma.tipo_equipo` pasa de ser un catálogo que define Administración a
-- ser la COPIA de solo lectura de los tipos de Ventas: el código es el
-- identificador de Ventas tal cual (ya no `TEQ-...`) y cada fila recuerda
-- de qué columna salió y cuándo se vio por última vez. Las preguntas
-- siguen referenciando la fila (consistencia referencial) y los checklists
-- registrados guardan su copia del tipo, así que un cambio posterior del
-- catálogo no los altera.
--
-- Aditiva y compatible: dos columnas que admiten vacío y una restricción
-- del código que se amplía (todo código `TEQ-...` sigue siendo válido).
-- No mueve datos ni borra nada.

alter table rma.tipo_equipo
  drop constraint if exists tipo_equipo_codigo_check;

alter table rma.tipo_equipo
  drop constraint if exists tipo_equipo_codigo_valido;

alter table rma.tipo_equipo
  add constraint tipo_equipo_codigo_valido
  check (btrim(codigo) <> '' and codigo = btrim(codigo) and length(codigo) <= 200);

alter table rma.tipo_equipo
  add column if not exists campo_origen text
    check (campo_origen in ('tp_categoria', 'tp_subcat_1', 'tp_gp'));

alter table rma.tipo_equipo
  add column if not exists sincronizado_en timestamptz;

comment on table rma.tipo_equipo is 'Copia de los tipos de equipo del catálogo de Ventas de Gestión RT (DC12). Se actualiza sincronizando (solo lectura); RMA no los crea ni los edita. No se borran: los que dejan de venir quedan no vigentes.';
comment on column rma.tipo_equipo.codigo is 'Identificador del tipo en Ventas, tal cual.';
comment on column rma.tipo_equipo.nombre is 'Descripción del tipo según Ventas.';
comment on column rma.tipo_equipo.activo is 'Si estaba en el catálogo de Ventas en la última sincronización (vigente).';
comment on column rma.tipo_equipo.campo_origen is 'Columna del catálogo de Ventas de la que salió (RMA_TIPO_EQUIPO_CAMPO).';
comment on column rma.tipo_equipo.sincronizado_en is 'Última sincronización en la que estaba en el catálogo.';
