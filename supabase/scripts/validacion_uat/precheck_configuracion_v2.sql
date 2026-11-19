-- Rosario Tecno RMA — Consultas previas de Configuración v2 (SOLO LECTURA).
--
-- Correr en el SQL Editor del UAT ANTES de aplicar las migraciones
-- 20261120000100 y 20261120000200 (docs/DESPLIEGUE_UAT.md, sección 12).
-- No modifican nada: la transacción es de solo lectura y termina en
-- rollback. Cada bloque devuelve filas solo si hay algo que decidir.

begin transaction read only;

-- 1. D6: códigos que solo difieren en mayúsculas. Si devuelve filas, la
--    migración 20261120000100 se detendría: hay que decidir qué código
--    queda antes de migrar (no se corrige solo).
select 'tipo_reparacion.codigo' as columna, upper(codigo) as clave, string_agg(codigo, ', ') as codigos
  from rma.tipo_reparacion group by upper(codigo) having count(*) > 1
union all
select 'insumo.clave', upper(clave), string_agg(clave, ', ')
  from rma.insumo group by upper(clave) having count(*) > 1
union all
select 'insumo.codigo', upper(codigo), string_agg(codigo, ', ')
  from rma.insumo group by upper(codigo) having count(*) > 1;

-- 2. DF-1 y DF-2: tipos cuyo plazo genérico (sin check-in registrado)
--    difiere del plazo con check-in, o con política RMA definida. Se
--    conservan tal cual (la pantalla ya no los muestra); revisar que sea
--    lo esperado.
select codigo, nombre, garantia_dias, garantia_con_checkin, garantia_sin_checkin, politica_garantia_rma
  from rma.tipo_reparacion
 where garantia_dias <> garantia_con_checkin or politica_garantia_rma is not null
 order by codigo;

-- 3. DF-4: permisos configurados. Si COMPRAS_GESTIONAR tiene fila, la
--    migración 20261120000200 copia sus roles a los cinco permisos nuevos.
select codigo, roles, modificado_en from rma.permiso order by codigo;

-- 4. Dependencias (CFG-03): roles con COMPRAS_GESTIONAR configurado y sin
--    COMPRAS_CONSULTAR. Tras la copia quedarían con acciones de Compras sin
--    poder ver la sección: corregirlo desde Permisos después del despliegue.
--    Sin fila rige el predeterminado (Recepción, Coordinación RMA y
--    Administración en los dos).
with vigentes as (
  select
    coalesce((select roles from rma.permiso where codigo = 'COMPRAS_GESTIONAR'),
             array['RECEPCION','COORDINADOR_RMA','ADMINISTRADOR']) as gestionar,
    coalesce((select roles from rma.permiso where codigo = 'COMPRAS_CONSULTAR'),
             array['RECEPCION','COORDINADOR_RMA','ADMINISTRADOR']) as consultar
)
select gestionar as compras_gestionar, consultar as compras_consultar
  from vigentes
 where not gestionar <@ consultar;

-- 5. Plantillas existentes (ninguna se borra; solo dos quedan visibles).
select codigo, nombre, activa from rma.plantilla_mensaje order by orden, codigo;

rollback;
