-- Motivos operativos, parámetros y seguimiento del retiro demorado
-- (macroiteración integral, DEC-MI-13, DEC-MI-14 y DEC-MI-15; cierra ABI-07
-- y la parte de cancelación e interrupción de ABI-29).
--
-- Aditiva:
--   * `motivo_operativo`: catálogos separados de motivos de cancelación y
--     de interrupción. Empiezan solo con «Otro», que exige descripción; el
--     resto lo carga Administración. El texto del motivo se copia en cada
--     registro que lo usa, así que cambiar el catálogo no cambia el
--     significado de lo registrado;
--   * `parametro`: parámetros operativos; el plazo de retiro demorado
--     empieza en 30 días desde el aviso de equipo listo;
--   * `seguimiento_retiro`: seguimientos de un retiro demorado, inmutables.
--     La Orden sigue abierta: nunca se cierra ni se dispone del equipo por
--     el vencimiento.

create table if not exists rma.motivo_operativo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^[A-Z0-9][A-Z0-9_-]*$'),
  tipo text not null check (tipo in ('CANCELACION', 'INTERRUPCION')),
  nombre text not null check (btrim(nombre) <> ''),
  activo boolean not null default true,
  requiere_descripcion boolean not null default false,
  orden integer not null default 0,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

comment on table rma.motivo_operativo is
  'Motivos de cancelación y de interrupción (DEC-MI-15). No se borran: se desactivan. Lo registrado guarda una copia del texto.';
comment on column rma.motivo_operativo.id is 'Identificador interno del motivo.';
comment on column rma.motivo_operativo.codigo is 'Código público del motivo.';
comment on column rma.motivo_operativo.tipo is 'CANCELACION o INTERRUPCION: catálogos separados.';
comment on column rma.motivo_operativo.nombre is 'Texto del motivo.';
comment on column rma.motivo_operativo.activo is 'Si se ofrece para registros nuevos.';
comment on column rma.motivo_operativo.requiere_descripcion is 'Si exige una descripción (por ejemplo «Otro»).';
comment on column rma.motivo_operativo.orden is 'Orden de presentación.';
comment on column rma.motivo_operativo.creado_en is 'Fecha y hora de alta.';
comment on column rma.motivo_operativo.modificado_en is 'Fecha y hora del último cambio.';

insert into rma.motivo_operativo (codigo, tipo, nombre, requiere_descripcion, orden)
values ('CANC-OTRO', 'CANCELACION', 'Otro', true, 1),
       ('INT-OTRO', 'INTERRUPCION', 'Otro', true, 2)
on conflict (codigo) do nothing;

create table if not exists rma.parametro (
  clave text primary key check (clave ~ '^[A-Z][A-Z_]*$'),
  valor text not null,
  modificado_en timestamptz not null default now()
);

comment on table rma.parametro is
  'Parámetros operativos administrados por Administración (DEC-MI-13). Cada cambio queda en cambio_configuracion (entidad PARAMETRO).';
comment on column rma.parametro.clave is 'Nombre del parámetro (por ejemplo PLAZO_RETIRO_DIAS).';
comment on column rma.parametro.valor is 'Valor vigente, como texto.';
comment on column rma.parametro.modificado_en is 'Fecha y hora del último cambio.';

insert into rma.parametro (clave, valor) values ('PLAZO_RETIRO_DIAS', '30')
on conflict (clave) do nothing;

create table if not exists rma.seguimiento_retiro (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  nota text not null check (btrim(nota) <> ''),
  canal text,
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null,
  posicion integer not null check (posicion >= 1),
  constraint seguimiento_retiro_posicion unique (orden_id, posicion)
);

drop trigger if exists seguimiento_retiro_inmutable on rma.seguimiento_retiro;
create trigger seguimiento_retiro_inmutable before update or delete on rma.seguimiento_retiro
  for each row execute function rma.impedir_modificacion();

comment on table rma.seguimiento_retiro is
  'Seguimientos de un retiro demorado (DEC-MI-14): quién, cuándo, qué y por qué canal. Inmutables.';
comment on column rma.seguimiento_retiro.id is 'Identificador interno del seguimiento.';
comment on column rma.seguimiento_retiro.orden_id is 'Orden en retiro demorado (referencia a orden).';
comment on column rma.seguimiento_retiro.nota is 'Qué se hizo o se acordó.';
comment on column rma.seguimiento_retiro.canal is 'Canal usado, si hubo contacto.';
comment on column rma.seguimiento_retiro.usuario_id is 'Quién lo registró (referencia a usuario).';
comment on column rma.seguimiento_retiro.registrado_en is 'Fecha y hora del seguimiento.';
comment on column rma.seguimiento_retiro.posicion is 'Orden del seguimiento en la Orden.';

grant select, insert, update on rma.motivo_operativo to rma_backend;
grant select, update on rma.parametro to rma_backend;
grant select, insert on rma.seguimiento_retiro to rma_backend;
