-- E8: script unico de la migracion de E3 para Supabase DEV/UAT.
--
-- Procedimiento: docs/postgresql/integracion-pendientes.md, «Procedimiento
-- seguro de la migracion de E3». Solo con autorizacion escrita y solo asi:
--
--   psql -v ON_ERROR_STOP=1 --single-transaction \
--     -f supabase/scripts/e8_aplicar_e3.sql "<url de administracion>"
--
-- Sin esas dos opciones la guarda de la migracion no protege. Despues:
--   npx supabase migration repair --status applied 20261105000100 --remote
--
-- Pensado para el estado inspeccionado el 06/11/2026: sin insumos ni
-- usuarios, 5 medios de pago y 36 modelos. Con otro estado falla sin cambiar
-- nada. Sin insumos, el paso «clave desde las fuentes» no tiene filas.

set local rma.migracion_e3 = 'estrategia_identidad_aprobada';
set local lock_timeout = '5s';

-- 1. Precondiciones.
do $$
declare
  v_medios text;
  v_modelos text;
begin
  if exists (select 1 from information_schema.columns
             where table_schema = 'rma' and table_name = 'insumo'
               and column_name = 'clave') then
    raise exception 'E3 ya aplicada: rma.insumo.clave existe.';
  end if;
  if exists (select 1 from rma.insumo) or exists (select 1 from rma.usuario) then
    raise exception 'Hay insumos o usuarios: este script no asigna su identidad.';
  end if;
  select string_agg(codigo || '|' || nombre || '|' || activo, ',' order by codigo)
    into v_medios from rma.medio_pago;
  if v_medios is distinct from
     'EFECTIVO|Efectivo|true,OTRO|Otro|true,'
     'TARJETA_CREDITO|Tarjeta de credito|true,'
     'TARJETA_DEBITO|Tarjeta de debito|true,TRANSFERENCIA|Transferencia|true' then
    raise exception 'Los medios de pago no son los inspeccionados: %', v_medios;
  end if;
  select md5(string_agg(concat_ws('|', codigo, marca, modelo, variante, activo),
                        E'\n' order by codigo))
    into v_modelos from rma.modelo_equipo;
  if v_modelos is distinct from '5141b0f8b277456b64d0832c03911523' then
    raise exception 'Los modelos de equipo no son los inspeccionados: %', v_modelos;
  end if;
end;
$$;

-- 2. La migracion, sin copiarla.
\ir ../migrations/20261105000100_e3_catalogos.sql

-- 3. Orden de los medios de pago (QA-E3-7): el de la lista predeterminada.
update rma.medio_pago m set orden = v.orden
from (values ('EFECTIVO', 1), ('TRANSFERENCIA', 2), ('TARJETA_DEBITO', 3),
             ('TARJETA_CREDITO', 4), ('OTRO', 5)) as v (codigo, orden)
where m.codigo = v.codigo;

-- 4. Verificacion final: si algo no coincide, se revierte todo.
do $$
declare
  v_medios text;
  v_modelos text;
begin
  select string_agg(codigo || '|' || nombre || '|' || activo || '|' || orden,
                    ',' order by orden)
    into v_medios from rma.medio_pago;
  if v_medios is distinct from
     'EFECTIVO|Efectivo|true|1,TRANSFERENCIA|Transferencia|true|2,'
     'TARJETA_DEBITO|Tarjeta de debito|true|3,'
     'TARJETA_CREDITO|Tarjeta de credito|true|4,OTRO|Otro|true|5' then
    raise exception 'Medios de pago distintos de lo esperado: %', v_medios;
  end if;
  select md5(string_agg(concat_ws('|', codigo, marca, modelo, variante, activo),
                        E'\n' order by codigo))
    into v_modelos from rma.modelo_equipo;
  if v_modelos is distinct from '5141b0f8b277456b64d0832c03911523' then
    raise exception 'Cambiaron los modelos de equipo: %', v_modelos;
  end if;
  if exists (select 1 from rma.insumo) or exists (select 1 from rma.usuario)
     or exists (select 1 from rma.tipo_reparacion_insumo) then
    raise exception 'Aparecieron insumos, usuarios o insumos previstos.';
  end if;
  if not exists (select 1 from pg_trigger
                 where tgname = 'insumo_clave_por_defecto' and not tgisinternal) then
    raise exception 'Falta el trigger de clave.';
  end if;
end;
$$;
