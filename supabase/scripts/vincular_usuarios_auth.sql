-- Vincula un usuario de RMA con su cuenta de Supabase Auth.
--
-- Uso (con autorizacion, despues de crear la cuenta en Supabase Auth), una
-- vez por persona:
--
--   psql "$URL_ADMIN" -v ON_ERROR_STOP=1 --single-transaction \
--     -v codigo=RECEP-001 -v email=recepcion@ejemplo.com \
--     -f supabase/scripts/vincular_usuarios_auth.sql
--
-- Solo completa un vinculo vacio: nunca pisa otro. Falla (y no cambia
-- nada) si el usuario o la cuenta no existen, o si ya estaba vinculado.
-- No crea cuentas ni contrasenas: eso se hace en Supabase Auth.

select set_config('rma.vinculo_codigo', :'codigo', true),
       set_config('rma.vinculo_email', lower(:'email'), true);

do $$
declare
  v_codigo text := current_setting('rma.vinculo_codigo');
  v_email text := current_setting('rma.vinculo_email');
  v_cuenta uuid;
  v_filas int;
begin
  select id into v_cuenta from auth.users where lower(email) = v_email;
  if v_cuenta is null then
    raise exception 'No hay una cuenta de Supabase Auth con el email %', v_email;
  end if;

  update rma.usuario
     set auth_user_id = v_cuenta,
         email = v_email
   where codigo = v_codigo
     and auth_user_id is null
     and activo;
  get diagnostics v_filas = row_count;
  if v_filas <> 1 then
    raise exception
      'El usuario % no existe, esta inactivo o ya tiene un vinculo', v_codigo;
  end if;
end $$;

-- Verificacion: el usuario, su rol unico y el vinculo.
select u.codigo, u.email, u.auth_user_id is not null as vinculado,
       array_agg(r.codigo) as roles
  from rma.usuario u
  join rma.usuario_rol ur on ur.usuario_id = u.id
  join rma.rol r on r.id = ur.rol_id
 where u.codigo = :'codigo'
 group by u.codigo, u.email, u.auth_user_id;
