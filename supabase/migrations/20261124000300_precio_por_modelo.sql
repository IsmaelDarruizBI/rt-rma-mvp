-- Rosario Tecno RMA — Precio por modelo, modelos administrables y copia del
-- trabajo (ajustes funcionales, iteración 2, bloque 7; DEC-AJ-12, BR-REP-015,
-- BR-REP-039, BR-REP-040, BR-REP-047, BR-REP-048).
--
-- Aditiva y compatible con los registros existentes:
--   * `modelo_equipo`: Administración da de alta y edita modelos desde
--     Configuración (D-12.5). Código MOD-NNNN automático con su secuencia,
--     que sigue al mayor código existente; el código no cambia. El archivo
--     versionado queda como carga inicial. La unicidad (marca, modelo,
--     variante) ya existente impide duplicados, también con una futura
--     regeneración desde Ventas;
--   * `tipo_reparacion.precio_por_modelo` (por defecto falso): los tipos
--     actuales siguen con su precio único. Con verdadero, el precio sale de
--     `precio_tipo_modelo` y nunca del precio único (D-12.1);
--   * tabla nueva `precio_tipo_modelo`: el precio de cada combinación tipo +
--     modelo. No se borra: un precio retirado queda inactivo. Cada alta,
--     cambio y retiro se audita en `cambio_configuracion` (entidad
--     PRECIO_MODELO, clave «TR-001/MOD-0012», campo precio);
--   * `historial_precio`: `create or replace`, mismas columnas y una nueva al
--     final (`modelo_equipo`), que incluye los precios por modelo;
--   * `detalle_version`: copia del nombre del trabajo, el modelo con el que se
--     tomó el precio, el origen del precio (CATALOGO, CATALOGO_MODELO, MANUAL,
--     OTROS o PENDIENTE), el motivo y quién y cuándo lo definió (D-12.2,
--     D-12.4), y si la versión solo cambió el precio de la anterior. Las
--     versiones existentes quedan vacías: se siguen leyendo con el nombre del
--     catálogo.
--
-- Ningún dato existente cambia.

-- ---------------------------------------------------------------------------
-- Modelos de equipo administrables (D-12.5)
-- ---------------------------------------------------------------------------
create sequence if not exists rma.codigo_mod_seq;
comment on sequence rma.codigo_mod_seq is 'Número de los códigos MOD-NNNN de modelo_equipo (rma.siguiente_codigo).';

-- Arranque: el mayor sufijo numérico existente. Una secuencia ya avanzada
-- (migración repetida) no retrocede. Si los modelos se cargan después (datos
-- de referencia), siguiente_codigo saltea los códigos ya usados.
do $$
declare
  v_maximo bigint;
  v_actual bigint;
  v_usada boolean;
begin
  select coalesce(max(substring(codigo from '^MOD-([0-9]{1,18})$')::bigint), 0)
    into v_maximo from rma.modelo_equipo;
  select last_value, is_called into v_actual, v_usada from rma.codigo_mod_seq;
  if v_maximo > 0 and (not v_usada or v_actual < v_maximo) then
    perform setval('rma.codigo_mod_seq', v_maximo, true);
  end if;
end;
$$;

create or replace function rma.siguiente_codigo(p_prefijo text)
returns text
language plpgsql
volatile
set search_path = rma, pg_temp
as $$
declare
  v_numero bigint;
  v_ancho integer;
  v_codigo text;
  v_usado boolean;
  v_intentos integer := 0;
begin
  loop
    v_intentos := v_intentos + 1;
    if v_intentos > 100000 then
      raise exception 'No hay un código % libre.', p_prefijo using errcode = 'unique_violation';
    end if;
    case p_prefijo
      when 'TR' then v_numero := nextval('rma.codigo_tr_seq'); v_ancho := 3;
      when 'CANC' then v_numero := nextval('rma.codigo_canc_seq'); v_ancho := 3;
      when 'INT' then v_numero := nextval('rma.codigo_int_seq'); v_ancho := 3;
      when 'INS' then v_numero := nextval('rma.codigo_ins_seq'); v_ancho := 3;
      when 'PRV' then v_numero := nextval('rma.codigo_prv_seq'); v_ancho := 4;
      when 'CHK' then v_numero := nextval('rma.codigo_chk_seq'); v_ancho := 4;
      when 'SC' then v_numero := nextval('rma.codigo_sc_seq'); v_ancho := 6;
      when 'OC' then v_numero := nextval('rma.codigo_oc_seq'); v_ancho := 6;
      when 'RGA' then v_numero := nextval('rma.codigo_rga_seq'); v_ancho := 6;
      when 'MOD' then v_numero := nextval('rma.codigo_mod_seq'); v_ancho := 4;
      else
        raise exception 'Prefijo de código desconocido: %', p_prefijo using errcode = 'invalid_parameter_value';
    end case;
    -- Sin truncar: lpad corta los números más largos que el ancho.
    v_codigo := p_prefijo || '-' || lpad(v_numero::text, greatest(v_ancho, length(v_numero::text)), '0');
    v_usado := case p_prefijo
      when 'TR' then exists (select 1 from rma.tipo_reparacion where upper(codigo) = v_codigo)
      when 'CANC' then exists (select 1 from rma.motivo_operativo where upper(codigo) = v_codigo)
      when 'INT' then exists (select 1 from rma.motivo_operativo where upper(codigo) = v_codigo)
      when 'INS' then exists (
        select 1 from rma.insumo where upper(clave) = v_codigo or upper(codigo) = v_codigo)
      when 'PRV' then exists (select 1 from rma.proveedor where upper(codigo) = v_codigo)
      when 'CHK' then exists (select 1 from rma.checklist_pregunta where upper(codigo) = v_codigo)
      when 'SC' then exists (select 1 from rma.solicitud_compra where codigo = v_codigo)
      when 'OC' then exists (select 1 from rma.orden_compra where codigo = v_codigo)
      when 'RGA' then exists (select 1 from rma.reclamo_garantia where codigo = v_codigo)
      when 'MOD' then exists (select 1 from rma.modelo_equipo where upper(codigo) = v_codigo)
    end;
    exit when not v_usado;
  end loop;
  return v_codigo;
end;
$$;

comment on function rma.siguiente_codigo(text) is
  'Código siguiente libre de un prefijo (TR, CANC, INT, INS, PRV, CHK, SC, OC, RGA, MOD): secuencia propia, ancho mínimo sin truncar y salto de los códigos ya usados. Puede dejar huecos; nunca repite.';

drop trigger if exists modelo_equipo_codigo_fijo on rma.modelo_equipo;
create trigger modelo_equipo_codigo_fijo before update of codigo on rma.modelo_equipo
  for each row execute function rma.impedir_cambio_codigo();

comment on table rma.modelo_equipo is
  'Catálogo técnico propio de RMA: qué equipo es (marca, modelo comercial y variante). No depende del catálogo comercial de Ventas. La carga inicial sale del archivo versionado; Administración da de alta y edita modelos desde Configuración, con auditoría (DEC-AJ-12). Una futura regeneración desde Ventas empareja por (marca, modelo, variante), sin duplicar. Un modelo no se borra, se desactiva.';
comment on column rma.modelo_equipo.codigo is
  'Identificador público estable del modelo, con formato MOD-0001. Lo genera la base (rma.siguiente_codigo) y no cambia.';

revoke all on sequence rma.codigo_mod_seq from public;
do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on sequence rma.codigo_mod_seq from %I', v_rol);
    end if;
  end loop;
end;
$$;
grant usage on sequence rma.codigo_mod_seq to rma_backend;
grant insert (codigo, marca, modelo, variante, numeros_modelo, activo) on rma.modelo_equipo to rma_backend;
grant update (marca, modelo, variante, numeros_modelo, activo) on rma.modelo_equipo to rma_backend;

-- ---------------------------------------------------------------------------
-- Precio por modelo (D-12.1, D-12.3)
-- ---------------------------------------------------------------------------
alter table rma.tipo_reparacion
  add column if not exists precio_por_modelo boolean not null default false;

comment on column rma.tipo_reparacion.precio_por_modelo is
  'Si el precio depende del modelo del equipo (DEC-AJ-12). Falso: rige el precio único. Verdadero: rige precio_tipo_modelo para el modelo de la Orden, sin usar el precio único como respaldo; sin precio para el modelo, el trabajo lleva un precio manual autorizado o queda con el precio pendiente de definir.';
comment on column rma.tipo_reparacion.precio is
  'Precio único vigente en pesos, con historial en historial_precio. No se usa si el tipo tiene precio por modelo.';

create table if not exists rma.precio_tipo_modelo (
  id uuid primary key default gen_random_uuid(),
  tipo_reparacion_id uuid not null references rma.tipo_reparacion (id),
  modelo_equipo_id uuid not null references rma.modelo_equipo (id),
  precio numeric(14, 2) not null check (precio >= 0),
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  constraint precio_tipo_modelo_unico unique (tipo_reparacion_id, modelo_equipo_id)
);

create index if not exists precio_tipo_modelo_modelo on rma.precio_tipo_modelo (modelo_equipo_id);

drop trigger if exists precio_tipo_modelo_modificacion on rma.precio_tipo_modelo;
create trigger precio_tipo_modelo_modificacion before update on rma.precio_tipo_modelo
  for each row execute function rma.marcar_modificacion();
drop trigger if exists precio_tipo_modelo_sin_borrado on rma.precio_tipo_modelo;
create trigger precio_tipo_modelo_sin_borrado before delete on rma.precio_tipo_modelo
  for each row execute function rma.impedir_borrado();

comment on table rma.precio_tipo_modelo is
  'Precio de catálogo de un Tipo de Reparación para un Modelo de equipo (DEC-AJ-12). Rige solo si el tipo tiene precio por modelo. Única por par; no se borra: un precio retirado queda inactivo. Cada alta, cambio y retiro se audita en cambio_configuracion (entidad PRECIO_MODELO). Los Detalles guardan su copia: cambiarlo no altera las Órdenes.';
comment on column rma.precio_tipo_modelo.id is 'Identificador interno.';
comment on column rma.precio_tipo_modelo.tipo_reparacion_id is 'Tipo de Reparación (referencia a tipo_reparacion).';
comment on column rma.precio_tipo_modelo.modelo_equipo_id is 'Modelo de equipo (referencia a modelo_equipo).';
comment on column rma.precio_tipo_modelo.precio is 'Precio en pesos de la combinación, con dos decimales.';
comment on column rma.precio_tipo_modelo.activo is 'Falso: el precio se retiró y la combinación queda sin precio de catálogo.';
comment on column rma.precio_tipo_modelo.creado_en is 'Fecha y hora del alta del precio.';
comment on column rma.precio_tipo_modelo.modificado_en is 'Fecha y hora del último cambio.';

grant select, insert on rma.precio_tipo_modelo to rma_backend;
grant update (precio, activo) on rma.precio_tipo_modelo to rma_backend;

-- ---------------------------------------------------------------------------
-- Auditoría
-- ---------------------------------------------------------------------------
alter table rma.cambio_configuracion drop constraint if exists cambio_configuracion_entidad_check;
alter table rma.cambio_configuracion add constraint cambio_configuracion_entidad_check
  check (entidad in (
    'TIPO_REPARACION', 'MESA_TRABAJO', 'USUARIO', 'PERMISO', 'INSUMO',
    'MOTIVO', 'PLANTILLA', 'PARAMETRO', 'CHECKLIST', 'PROVEEDOR', 'MEDIO_PAGO',
    'EMPRESA', 'TEXTO_LEGAL', 'MODELO_EQUIPO', 'PRECIO_MODELO'
  ));

comment on column rma.cambio_configuracion.entidad is
  'Qué se cambió: un catálogo (TIPO_REPARACION, MESA_TRABAJO, INSUMO, MOTIVO, PLANTILLA, CHECKLIST, PROVEEDOR, MODELO_EQUIPO), el precio de un tipo para un modelo (PRECIO_MODELO, clave «TR-001/MOD-0012»), la asignación de roles (USUARIO), un permiso (PERMISO), un parámetro (PARAMETRO), el recargo de un medio de pago (MEDIO_PAGO), los datos de la empresa (EMPRESA) o una versión nueva de un texto legal (TEXTO_LEGAL).';

create or replace view rma.historial_precio as
select c.secuencia,
       case when c.entidad = 'PRECIO_MODELO' then split_part(c.clave, '/', 1) else c.clave end as tipo_reparacion,
       c.valor_anterior as precio_anterior,
       c.valor_nuevo as precio_nuevo, c.usuario_id, c.registrado_en,
       case when c.entidad = 'PRECIO_MODELO' then split_part(c.clave, '/', 2) end as modelo_equipo
from rma.cambio_configuracion c
where c.campo = 'precio' and c.entidad in ('TIPO_REPARACION', 'PRECIO_MODELO');

comment on view rma.historial_precio is
  'Historial de precios de cada Tipo de Reparación (DC23AUD): los cambios de su precio único y, con DEC-AJ-12, de sus precios por modelo.';
comment on column rma.historial_precio.tipo_reparacion is 'Código del Tipo de Reparación.';
comment on column rma.historial_precio.precio_anterior is 'Precio anterior; vacío en el alta.';
comment on column rma.historial_precio.precio_nuevo is 'Precio desde el cambio; vacío si se retiró el precio de un modelo.';
comment on column rma.historial_precio.modelo_equipo is 'Código del modelo (MOD-…) en un precio por modelo; vacío en el precio único.';

grant select on rma.historial_precio to rma_backend;

-- ---------------------------------------------------------------------------
-- Copia del trabajo en cada definición (D-12.2, D-12.4)
-- ---------------------------------------------------------------------------
alter table rma.detalle_version
  add column if not exists nombre_trabajo text,
  add column if not exists modelo_equipo_id uuid references rma.modelo_equipo (id),
  add column if not exists origen_precio text,
  add column if not exists precio_motivo text,
  add column if not exists precio_definido_por uuid references rma.usuario (id),
  add column if not exists precio_definido_en timestamptz,
  add column if not exists solo_precio boolean not null default false;

alter table rma.detalle_version drop constraint if exists detalle_version_origen_precio;
alter table rma.detalle_version add constraint detalle_version_origen_precio
  check (origen_precio in ('CATALOGO', 'CATALOGO_MODELO', 'MANUAL', 'OTROS', 'PENDIENTE'));
alter table rma.detalle_version drop constraint if exists detalle_version_precio_manual;
alter table rma.detalle_version add constraint detalle_version_precio_manual check (
  (origen_precio = 'MANUAL') = (precio_motivo is not null)
  and (origen_precio is distinct from 'MANUAL' or (
    btrim(precio_motivo) <> '' and precio_definido_por is not null and precio_definido_en is not null))
);
alter table rma.detalle_version drop constraint if exists detalle_version_precio_pendiente;
alter table rma.detalle_version add constraint detalle_version_precio_pendiente
  check (origen_precio is distinct from 'PENDIENTE' or precio = 0);
alter table rma.detalle_version drop constraint if exists detalle_version_solo_precio;
alter table rma.detalle_version add constraint detalle_version_solo_precio
  check (not solo_precio or (numero > 1 and origen_precio is not null));

comment on column rma.detalle_version.precio is
  'Precio en pesos copiado del catálogo (precio único o del modelo), cargado a mano en «Otros» o en un precio manual autorizado, al momento de definir; no se relee del catálogo. Con el origen PENDIENTE vale 0 y no es un precio: falta definirlo.';
comment on column rma.detalle_version.nombre_trabajo is
  'Nombre del Tipo de Reparación al definir (DEC-AJ-12); vacío en las versiones anteriores, que se muestran con el nombre del catálogo.';
comment on column rma.detalle_version.modelo_equipo_id is
  'Modelo del equipo de la Orden con el que se determinó el precio (referencia a modelo_equipo); vacío si el equipo no tenía modelo técnico o en versiones anteriores.';
comment on column rma.detalle_version.origen_precio is
  'De dónde salió el precio: CATALOGO (precio único del tipo), CATALOGO_MODELO (precio del tipo para el modelo), MANUAL (autorizado con el permiso PRECIO_MANUAL porque faltaba el de catálogo), OTROS (reparación no tipificada) o PENDIENTE (falta definirlo: bloquea el comprobante de ingreso y la autorización del cliente). Vacío en versiones anteriores.';
comment on column rma.detalle_version.precio_motivo is 'Motivo obligatorio del precio manual; vacío en los demás orígenes.';
comment on column rma.detalle_version.precio_definido_por is 'Usuario que definió el precio de esta versión (referencia a usuario).';
comment on column rma.detalle_version.precio_definido_en is 'Fecha y hora en que se definió el precio de esta versión.';
comment on column rma.detalle_version.solo_precio is
  'Verdadero si la versión solo define el precio de la anterior (precio pendiente definido, tomado del catálogo o vuelto a determinar por un cambio de modelo): la evaluación técnica de la anterior sigue valiendo.';

-- ---------------------------------------------------------------------------
-- Historial: definir o volver a determinar el precio de un trabajo
-- ---------------------------------------------------------------------------
-- La accion transversal ACC-REP-083 (DEFINIR_PRECIO_TRABAJO y
-- REDETERMINAR_PRECIO_POR_CAMBIO_DE_MODELO) crea una version nueva del
-- Detalle: es EV-REP-026 «Detalle redefinido».
insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select 'FUNCTIONAL_ACTION', 'ACC-REP-083', null, t.id
from rma.tipo_evento t
where t.codigo = 'EV-REP-026'
on conflict do nothing;
