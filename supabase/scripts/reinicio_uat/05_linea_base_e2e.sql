-- Línea de base del E2E: lo que había en el UAT justo antes de una ejecución
-- de validacion_uat/probar_macro_v14.py o probar_macro_integral.py.
--
-- 06_limpiar_e2e.sql la usa después para borrar SOLO lo que creó esa
-- ejecución y comprobar que todo lo demás quedó idéntico. A diferencia de
-- 01_reiniciar.sql, no vacía nada: conserva las Órdenes, las fotos, los
-- documentos y cualquier otro registro previo.
--
-- Escribe en el UAT (crea un esquema privado). Requiere autorización
-- explícita, como el E2E. Uso (CLI de Supabase con la sesión administrativa,
-- nunca rma_api), inmediatamente antes del E2E:
--
--   npx -y supabase@3.1.0 db query --yes --remote=<ref> \
--     --file supabase/scripts/reinicio_uat/05_linea_base_e2e.sql
--
-- Qué guarda, en el esquema rma_linea_base_e2e:
--   - una copia de cada tabla de rma (incluidas las de datos personales que ya
--     hubiera: el esquema no tiene permisos para anon, authenticated,
--     service_role ni rma_backend, y 06_limpiar_e2e.sql lo elimina al aplicar);
--   - _secuencia: el valor de cada secuencia de rma;
--   - _metadatos: cuándo, quién, las migraciones y las Órdenes existentes.
--
-- Guardas: el esquema no existe (no se pisa una línea de base anterior) y no
-- hay un reinicio a medio camino (rma_respaldo_reinicio).

do $$
declare
  c_base constant text := 'rma_linea_base_e2e';
  v_tabla text;
  v_secuencia text;
  v_rol text;
  v_tablas int := 0;
begin
  if exists (select 1 from pg_namespace where nspname = c_base) then
    raise exception 'El esquema % ya existe: hay una línea de base sin limpiar. Primero 06_limpiar_e2e.sql.', c_base;
  end if;
  if exists (select 1 from pg_namespace where nspname = 'rma_respaldo_reinicio') then
    raise exception 'Existe rma_respaldo_reinicio: hay un reinicio a medio camino.';
  end if;

  execute format('create schema %I', c_base);
  execute format('revoke all on schema %I from public', c_base);

  for v_tabla in
    select c.relname from pg_class c join pg_namespace n on n.oid = c.relnamespace
     where n.nspname = 'rma' and c.relkind = 'r' order by c.relname
  loop
    execute format('create table %I.%I as select * from rma.%I', c_base, v_tabla, v_tabla);
    v_tablas := v_tablas + 1;
  end loop;

  execute format('create table %I._secuencia (nombre text primary key, last_value bigint, is_called boolean)', c_base);
  for v_secuencia in
    select sequencename from pg_sequences where schemaname = 'rma' order by sequencename
  loop
    execute format(
      'insert into %I._secuencia select %L, last_value, is_called from rma.%I',
      c_base, v_secuencia, v_secuencia);
  end loop;

  execute format(
    'create table %I._metadatos as
       select now() as creada_en, current_user::text as usuario,
              (select count(*) from supabase_migrations.schema_migrations) as migraciones,
              (select coalesce(array_agg(codigo order by codigo), ''{}'') from rma.orden) as ordenes,
              %s as tablas',
    c_base, v_tablas);

  for v_rol in
    select rolname from pg_roles
     where rolname in ('anon', 'authenticated', 'service_role', 'rma_backend')
  loop
    execute format('revoke all on schema %I from %I', c_base, v_rol);
    execute format('revoke all on all tables in schema %I from %I', c_base, v_rol);
  end loop;

  raise notice 'LINEA DE BASE E2E: % tablas', v_tablas;
end $$;

select creada_en, migraciones, ordenes, tablas
  from rma_linea_base_e2e._metadatos;
