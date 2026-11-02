-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0100. Base común: esquema propio, funciones de apoyo e inmutabilidad.
--
-- Diseño lógico de referencia: diseno-logico-postgresql-rma.md (revisión 2,
-- decisiones G-1 a G-10). Las tablas viven en el esquema «rma», que no se
-- expone por la API de Supabase: solo FastAPI accede a los datos (G-5).

create schema if not exists rma;

comment on schema rma is
  'Datos de Rosario Tecno RMA. Solo accede el backend FastAPI; no se expone por la API de Supabase ni al frontend.';

-- Fecha y hora de modificación automática para las filas actualizables.
create or replace function rma.marcar_modificacion()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  new.modificado_en := now();
  return new;
end;
$$;

comment on function rma.marcar_modificacion() is
  'Completa modificado_en con la fecha y hora de la transacción en cada actualización de una fila.';

-- Registros inmutables: ni actualización ni borrado, para nadie.
create or replace function rma.impedir_modificacion()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  raise exception 'La tabla %.% es inmutable: % no está permitido. Una corrección se registra como un registro nuevo.',
    tg_table_schema, tg_table_name, tg_op
    using errcode = 'restrict_violation';
end;
$$;

comment on function rma.impedir_modificacion() is
  'Rechaza UPDATE y DELETE sobre tablas de registros históricos inmutables: eventos, libro de inventario, versiones y documentos.';

-- Borrado prohibido en tablas actualizables: nada se borra; se desactiva o se corrige.
create or replace function rma.impedir_borrado()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  raise exception 'En %.% no se borran filas: se desactivan o se corrigen con un registro nuevo.',
    tg_table_schema, tg_table_name
    using errcode = 'restrict_violation';
end;
$$;

comment on function rma.impedir_borrado() is
  'Rechaza DELETE sobre tablas actualizables: los catálogos se desactivan y los registros se corrigen con registros nuevos.';
