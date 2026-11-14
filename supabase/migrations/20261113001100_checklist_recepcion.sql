-- Checklist de recepción por tipo de equipo y advertencia por información
-- faltante (macroiteración integral, DC12; BR-REP-024, 025 y 040).
--
-- Aditiva:
--   * `tipo_equipo` y `checklist_pregunta`: catálogo que configura
--     Administración, con auditoría (entidad CHECKLIST). Empieza vacío: la
--     base no trae una clasificación de equipos;
--   * `checklist_registro`: cada checklist completado en una Orden, con la
--     copia de las preguntas y opciones aplicadas. Una corrección agrega un
--     registro con motivo; ninguno se modifica;
--   * `informacion_faltante_confirmacion`: Recepción continuó igualmente
--     con información faltante (la advertencia nunca bloquea).

create table if not exists rma.tipo_equipo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^TEQ-[0-9A-Z-]+$'),
  nombre text not null check (btrim(nombre) <> ''),
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

drop trigger if exists tipo_equipo_sin_borrado on rma.tipo_equipo;
create trigger tipo_equipo_sin_borrado before delete on rma.tipo_equipo
  for each row execute function rma.impedir_borrado();

comment on table rma.tipo_equipo is 'Tipos de equipo del checklist de recepción (DC12). Los define Administración; no se borran, se desactivan.';
comment on column rma.tipo_equipo.id is 'Identificador interno.';
comment on column rma.tipo_equipo.codigo is 'Código público (TEQ-...).';
comment on column rma.tipo_equipo.nombre is 'Nombre del tipo de equipo.';
comment on column rma.tipo_equipo.activo is 'Si se ofrece al completar un checklist.';
comment on column rma.tipo_equipo.creado_en is 'Fecha y hora de alta.';
comment on column rma.tipo_equipo.modificado_en is 'Fecha y hora del último cambio.';

create table if not exists rma.checklist_pregunta (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^CHK-[0-9A-Z-]+$'),
  tipo_equipo_id uuid not null references rma.tipo_equipo (id),
  texto text not null check (btrim(texto) <> ''),
  opciones text[] not null check (cardinality(opciones) >= 2),
  activa boolean not null default true,
  orden integer not null default 0,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

drop trigger if exists checklist_pregunta_sin_borrado on rma.checklist_pregunta;
create trigger checklist_pregunta_sin_borrado before delete on rma.checklist_pregunta
  for each row execute function rma.impedir_borrado();

comment on table rma.checklist_pregunta is 'Preguntas del checklist de un tipo de equipo, con sus opciones (DC12). Todas opcionales. No se borran: se desactivan.';
comment on column rma.checklist_pregunta.id is 'Identificador interno.';
comment on column rma.checklist_pregunta.codigo is 'Código público (CHK-...).';
comment on column rma.checklist_pregunta.tipo_equipo_id is 'Tipo de equipo (referencia a tipo_equipo).';
comment on column rma.checklist_pregunta.texto is 'Verificación que se pregunta.';
comment on column rma.checklist_pregunta.opciones is 'Opciones de respuesta (al menos dos).';
comment on column rma.checklist_pregunta.activa is 'Si se ofrece en checklists nuevos.';
comment on column rma.checklist_pregunta.orden is 'Orden de presentación.';
comment on column rma.checklist_pregunta.creado_en is 'Fecha y hora de alta.';
comment on column rma.checklist_pregunta.modificado_en is 'Fecha y hora del último cambio.';

create table if not exists rma.checklist_registro (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  posicion integer not null check (posicion >= 1),
  tipo_equipo_codigo text not null,
  tipo_equipo_nombre text not null,
  respuestas jsonb not null default '[]',
  sin_registrar text[] not null default '{}',
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  motivo text,
  constraint checklist_registro_posicion unique (orden_id, posicion),
  constraint checklist_registro_correccion check (posicion = 1 or btrim(coalesce(motivo, '')) <> '')
);

drop trigger if exists checklist_registro_inmutable on rma.checklist_registro;
create trigger checklist_registro_inmutable before update or delete on rma.checklist_registro
  for each row execute function rma.impedir_modificacion();

comment on table rma.checklist_registro is 'Checklists de recepción de una Orden (DC12): copia de las preguntas y opciones aplicadas y sus respuestas. Una corrección es un registro nuevo con motivo. Inmutable.';
comment on column rma.checklist_registro.id is 'Identificador interno.';
comment on column rma.checklist_registro.orden_id is 'Orden (referencia a orden).';
comment on column rma.checklist_registro.posicion is 'Versión del checklist en la Orden; rige la mayor.';
comment on column rma.checklist_registro.tipo_equipo_codigo is 'Tipo de equipo elegido (código, copia).';
comment on column rma.checklist_registro.tipo_equipo_nombre is 'Nombre del tipo de equipo al registrarlo (copia).';
comment on column rma.checklist_registro.respuestas is 'Preguntas aplicadas con sus opciones y la respuesta o «no realizada».';
comment on column rma.checklist_registro.sin_registrar is 'Preguntas vigentes que quedaron sin registrar.';
comment on column rma.checklist_registro.usuario_id is 'Quién lo registró (referencia a usuario).';
comment on column rma.checklist_registro.registrado_en is 'Fecha y hora del registro.';
comment on column rma.checklist_registro.motivo is 'Motivo de la corrección (obligatorio desde la segunda versión).';

create table if not exists rma.informacion_faltante_confirmacion (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  posicion integer not null check (posicion >= 1),
  faltantes text[] not null check (cardinality(faltantes) >= 1),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  constraint informacion_faltante_posicion unique (orden_id, posicion)
);

drop trigger if exists informacion_faltante_inmutable on rma.informacion_faltante_confirmacion;
create trigger informacion_faltante_inmutable before update or delete on rma.informacion_faltante_confirmacion
  for each row execute function rma.impedir_modificacion();

comment on table rma.informacion_faltante_confirmacion is 'Recepción continuó igualmente con información faltante (BR-REP-025): qué faltaba, quién y cuándo. La advertencia nunca bloquea. Inmutable.';
comment on column rma.informacion_faltante_confirmacion.id is 'Identificador interno.';
comment on column rma.informacion_faltante_confirmacion.orden_id is 'Orden (referencia a orden).';
comment on column rma.informacion_faltante_confirmacion.posicion is 'Orden de la confirmación en la Orden.';
comment on column rma.informacion_faltante_confirmacion.faltantes is 'Lo que faltaba al confirmar.';
comment on column rma.informacion_faltante_confirmacion.usuario_id is 'Quién confirmó (referencia a usuario).';
comment on column rma.informacion_faltante_confirmacion.registrado_en is 'Fecha y hora de la confirmación.';

grant select, insert, update on rma.tipo_equipo to rma_backend;
grant select, insert, update on rma.checklist_pregunta to rma_backend;
grant select, insert on rma.checklist_registro to rma_backend;
grant select, insert on rma.informacion_faltante_confirmacion to rma_backend;
