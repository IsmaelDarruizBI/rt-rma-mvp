-- Elimina el respaldo del reinicio del UAT (esquema rma_respaldo_reinicio),
-- cuando ya no hace falta volver atrás y siempre antes de migrar la base a
-- otra región: el respaldo contiene los datos de prueba anteriores y no debe
-- viajar.
--
-- Solo con autorización explícita y con una copia externa ya verificada
-- (00_exportar.sql).
--
-- Modo seguro por defecto: con v_confirmar = false solo informa qué
-- eliminaría. Para eliminar, cambiar a true, ejecutar y volver a false.
--
--   npx -y supabase@3.1.0 db query --yes --remote=<ref> \
--     --file supabase/scripts/reinicio_uat/04_eliminar_respaldo.sql

do $$
declare
  v_confirmar constant boolean := false;
  v_tablas int;
begin
  select count(*) into v_tablas from pg_tables where schemaname = 'rma_respaldo_reinicio';
  if not exists (select 1 from pg_namespace where nspname = 'rma_respaldo_reinicio') then
    raise notice 'No hay esquema rma_respaldo_reinicio: nada que eliminar.';
  elsif not v_confirmar then
    raise exception 'SIN CONFIRMAR: se eliminaría rma_respaldo_reinicio con % tablas. Cambiar v_confirmar a true para eliminarlo.', v_tablas;
  else
    drop schema rma_respaldo_reinicio cascade;
    raise notice 'Eliminado rma_respaldo_reinicio (% tablas).', v_tablas;
  end if;
end $$;
