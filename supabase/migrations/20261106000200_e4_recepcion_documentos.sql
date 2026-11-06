-- E4 (A4): recepción, documentos, fotos y salida del agregado Orden.
--
-- Aditiva: agrega columnas nulas e índices, relaja una restricción y corrige
-- un bloqueo. No borra ni reescribe datos: las filas ya guardadas son
-- inmutables y conservan su orden (ver posicion).
-- Diseño: docs/postgresql/e4-e7-diseno-integrado.md (secciones 13.8 y 14).

-- Orden exacto de cada lista del dominio. Una fecha no alcanza: dos entradas
-- pueden compartirla, y documentos.emitidos mezcla tipos. Las filas anteriores
-- a esta migración quedan sin posicion y se leen primero (NULLS FIRST), por
-- fecha e id: las nuevas se numeran a continuación, sin tocarlas.
alter table rma.recepcion_version add column posicion integer check (posicion >= 1);
alter table rma.recepcion_nota add column posicion integer check (posicion >= 1);
alter table rma.checkin add column posicion integer check (posicion >= 1);
alter table rma.foto add column posicion integer check (posicion >= 1);
alter table rma.documento_emitido add column posicion integer check (posicion >= 1);

comment on column rma.recepcion_version.posicion is 'Orden entre las versiones de la recepción (1, 2, ...). Vacía en las filas anteriores a E4, que se leen primero.';
comment on column rma.recepcion_nota.posicion is 'Orden entre las notas de la recepción (1, 2, ...). Vacía en las filas anteriores a E4, que se leen primero.';
comment on column rma.checkin.posicion is 'Orden entre los check-in de la Orden (1, 2, ...). Vacía en las filas anteriores a E4, que se leen primero.';
comment on column rma.foto.posicion is 'Orden entre las fotos de la Orden (1, 2, ...). Vacía en las filas anteriores a E4, que se leen primero.';
comment on column rma.documento_emitido.posicion is 'Orden entre los documentos de la Orden, de cualquier tipo (1, 2, ...). Vacía en las filas anteriores a E4, que se leen primero.';

-- Dos filas de una Orden no comparten posición: el orden queda determinado.
create unique index recepcion_version_posicion on rma.recepcion_version (orden_id, posicion) where posicion is not null;
create unique index recepcion_nota_posicion on rma.recepcion_nota (orden_id, posicion) where posicion is not null;
create unique index checkin_posicion on rma.checkin (orden_id, posicion) where posicion is not null;
create unique index foto_posicion on rma.foto (orden_id, posicion) where posicion is not null;
create unique index documento_emitido_posicion on rma.documento_emitido (orden_id, posicion) where posicion is not null;

-- El dominio no registra la versión de la plantilla: no se inventa una. Las
-- filas que ya la tienen la conservan, y el CHECK sigue rechazando un texto
-- vacío.
alter table rma.documento_emitido alter column plantilla_version drop not null;

comment on column rma.documento_emitido.plantilla_version is 'Versión de la plantilla con que se emitió. Vacía cuando se desconoce: el dominio no la registra y no se inventa.';

-- QA-A2-M4. FOR UPDATE choca con el KEY SHARE que toma cualquier clave foránea
-- hacia la Orden: con un comando que ya tenía la Orden y otra transacción que
-- la referenciaba antes de pedirla, terminaba en deadlock. FOR NO KEY UPDATE
-- no choca con KEY SHARE y sigue chocando consigo mismo, que es lo que el
-- límite necesita: dos altas simultáneas se serializan.
create or replace function rma.foto_limite_por_orden()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  -- Bloquea la Orden para que dos altas simultáneas no superen el límite.
  perform 1 from rma.orden where id = new.orden_id for no key update;
  if (select count(*) from rma.foto where orden_id = new.orden_id) >= 10 then
    raise exception 'La Orden ya tiene 10 fotos, el máximo.' using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.foto_limite_por_orden() is
  'Rechaza la undécima foto de una Orden. Bloquea la Orden antes de contar, con FOR NO KEY UPDATE para no chocar con las claves foráneas, así que el límite se respeta aunque haya altas simultáneas.';
