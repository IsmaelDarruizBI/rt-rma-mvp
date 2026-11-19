-- Rosario Tecno RMA — Productos de Gestión RT en reparación (Reparación RT,
-- etapa 1; DEC-RT-01, 05 y 07; BR-REP-050).
--
-- Copia de CONSULTA de los productos de Gestión RT en estado Reparacion: no
-- es una sincronización de inventario ni un Equipo de RMA. Producto RT y
-- Equipo RMA son entidades distintas; en la etapa 1 no hay vínculos: las
-- coincidencias con Órdenes (por referencia RT o IMEI) se calculan al
-- consultar y son solo sugerencias (DEC-RT-03). Diseño:
-- docs/reparacion-rt-discovery.md, secciones 2 y 6.2.
--
-- Aditiva:
--   * rma.sincronizacion_origen admite la copia PRODUCTOS_RT (el registro,
--     la reserva entre instancias y el propietario del bloque C, sin
--     cambios);
--   * tabla nueva rma.producto_rt: solo las columnas de la lista permitida
--     (nunca producto_passcode, precios ni datos de personas); se escribe
--     solo dentro de una sincronización EN_CURSO de PRODUCTOS_RT y con el
--     secreto de su propietario; nunca se borra.
--
-- Sin cambios en orden, equipo ni en las demás tablas. La revisión
-- publicada (bloque C) sigue funcionando: solo usa CATALOGO_VENTAS.

-- ---------------------------------------------------------------------------
-- sincronizacion_origen: la copia PRODUCTOS_RT
-- ---------------------------------------------------------------------------
alter table rma.sincronizacion_origen drop constraint if exists sincronizacion_origen_copia_check;
alter table rma.sincronizacion_origen drop constraint if exists sincronizacion_origen_copia;
alter table rma.sincronizacion_origen add constraint sincronizacion_origen_copia
  check (copia in ('CATALOGO_VENTAS', 'PRODUCTOS_RT'));

comment on column rma.sincronizacion_origen.copia is
  'Qué copia sincroniza: CATALOGO_VENTAS o PRODUCTOS_RT.';

-- ---------------------------------------------------------------------------
-- producto_rt
-- ---------------------------------------------------------------------------
create table if not exists rma.producto_rt (
  producto_id text primary key
    check (btrim(producto_id) <> '' and producto_id = btrim(producto_id)),
  estado_gestion_rt text not null,
  en_reparacion boolean not null,
  en_reparacion_desde timestamptz,
  salio_de_reparacion_en timestamptz,
  eliminado_en_origen boolean not null default false,
  presente_en_origen boolean not null default true,
  sede text,
  imei text,
  imei_normalizado text,
  imei_valido boolean not null default false,
  imei_luhn_valido boolean,
  imei_repetido boolean not null default false,
  tipo_producto_id text,
  tipo_producto_encontrado boolean not null default false,
  tipo_producto_eliminado boolean not null default false,
  descripcion_tipo text,
  modelo text,
  categoria text,
  subcategoria text,
  capacidad text,
  color text,
  bateria text,
  detalle_estetico text,
  defecto text,
  toma_rt text,
  tipo_reparacion_origen text,
  repuesto text,
  creado_en_origen timestamptz,
  conflicto_origen boolean not null default false,
  cambio_identidad boolean not null default false,
  identidad_anterior jsonb
    check (identidad_anterior is null or jsonb_typeof(identidad_anterior) = 'object'),
  texto_busqueda text not null,
  huella text not null check (huella ~ '^[0-9a-f]{64}$'),
  primera_vez_visto_en timestamptz not null,
  sincronizado_en timestamptz not null,
  sincronizacion_id text not null references rma.sincronizacion_origen (id),
  -- Transitoria: el secreto del propietario viaja en cada escritura; el
  -- trigger lo verifica y lo vacía (como en catalogo_producto).
  propietario text,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  constraint producto_rt_propietario_transitorio check (propietario is null),
  constraint producto_rt_periodo check (
    (not en_reparacion or (en_reparacion_desde is not null and salio_de_reparacion_en is null))
  ),
  constraint producto_rt_imei_valido check (
    not imei_valido or imei_normalizado ~ '^[0-9]{15}$'
  ),
  constraint producto_rt_imei_luhn check (imei_valido or imei_luhn_valido is null),
  constraint producto_rt_imei_repetido check (not imei_repetido or imei_valido),
  constraint producto_rt_tipo check (
    tipo_producto_encontrado or not tipo_producto_eliminado
  ),
  constraint producto_rt_fechas check (primera_vez_visto_en <= sincronizado_en)
);

-- El listado por defecto: en Reparación, presentes y no eliminados.
create index if not exists producto_rt_listado
  on rma.producto_rt (sede, en_reparacion_desde)
  where en_reparacion and presente_en_origen and not eliminado_en_origen;
-- Coincidencias por IMEI (solo IMEI válidos y no repetidos sugieren).
create index if not exists producto_rt_imei
  on rma.producto_rt (imei_normalizado)
  where imei_valido and not imei_repetido;
create index if not exists producto_rt_sincronizacion
  on rma.producto_rt (sincronizacion_id);

comment on table rma.producto_rt is
  'Copia de consulta de los Productos de Gestión RT en reparación (DEC-RT-01; BR-REP-050). No es inventario ni un Equipo de RMA. Solo las columnas permitidas (nunca producto_passcode). Se escribe solo dentro de una sincronización EN_CURSO de PRODUCTOS_RT; nunca se borra.';
comment on column rma.producto_rt.producto_id is 'producto_id de Gestión RT, tal cual (sin espacios al borde).';
comment on column rma.producto_rt.estado_gestion_rt is 'producto_status de Gestión RT en la última lectura.';
comment on column rma.producto_rt.en_reparacion is 'producto_status es exactamente el estado configurado (Reparacion).';
comment on column rma.producto_rt.en_reparacion_desde is 'Inicio del período de reparación vigente o del último: la primera sincronización que lo vio en Reparación.';
comment on column rma.producto_rt.salio_de_reparacion_en is 'Sincronización que lo vio salir de Reparación; vacía mientras sigue.';
comment on column rma.producto_rt.eliminado_en_origen is 'Gestión RT lo marca eliminado (producto_eliminado): no se lista.';
comment on column rma.producto_rt.presente_en_origen is 'Lo trajo la última lectura exitosa; falso si dejó de aparecer (nunca se borra).';
comment on column rma.producto_rt.sede is 'producto_sede: Alippi, Centro, eCommerce, Fisherton o RMA; otro valor se guarda y se informa.';
comment on column rma.producto_rt.imei is 'producto_imei tal como vino.';
comment on column rma.producto_rt.imei_normalizado is 'IMEI sin espacios y en mayúsculas (como el del Equipo).';
comment on column rma.producto_rt.imei_valido is '15 dígitos. Solo un IMEI válido y no repetido sugiere coincidencias.';
comment on column rma.producto_rt.imei_luhn_valido is 'Dígito verificador correcto (se informa, no invalida); vacío si el IMEI no es válido.';
comment on column rma.producto_rt.imei_repetido is 'Otro producto presente tiene el mismo IMEI válido: nunca sugiere ni vincula (DEC-RT-03).';
comment on column rma.producto_rt.tipo_producto_id is 'producto_tp = TipoProducto.tp_id.';
comment on column rma.producto_rt.tipo_producto_encontrado is 'El tp_id existe en TipoProducto.';
comment on column rma.producto_rt.tipo_producto_eliminado is 'El TipoProducto está eliminado en Ventas (se copia igual).';
comment on column rma.producto_rt.descripcion_tipo is 'tp_modelo del TipoProducto (descripción completa).';
comment on column rma.producto_rt.modelo is 'Modelo y variante del TipoProducto (por ejemplo «iPhone 12 Pro Max»).';
comment on column rma.producto_rt.categoria is 'tp_categoria del TipoProducto.';
comment on column rma.producto_rt.subcategoria is 'tp_subcat_1 del TipoProducto.';
comment on column rma.producto_rt.capacidad is 'Capacidad legible del TipoProducto (tp_gb).';
comment on column rma.producto_rt.color is 'Color del TipoProducto (tp_color).';
comment on column rma.producto_rt.bateria is 'producto_bateria, tal cual.';
comment on column rma.producto_rt.detalle_estetico is 'producto_detalle_estetico, tal cual.';
comment on column rma.producto_rt.defecto is 'producto_defecto: la falla informada por Gestión RT.';
comment on column rma.producto_rt.toma_rt is 'producto_toma_rt: tipo de ingreso, tal cual.';
comment on column rma.producto_rt.tipo_reparacion_origen is 'producto_tipo_reparacion de Gestión RT; no se mapea a los Tipos de reparación de RMA.';
comment on column rma.producto_rt.repuesto is 'producto_repuesto, tal cual.';
comment on column rma.producto_rt.creado_en_origen is 'producto_creado_en (alta en Gestión RT).';
comment on column rma.producto_rt.conflicto_origen is 'El producto_id vino repetido en la última lectura: se conservan los datos anteriores.';
comment on column rma.producto_rt.cambio_identidad is 'Cambió el IMEI o el TipoProducto que ya tenía el mismo producto_id.';
comment on column rma.producto_rt.identidad_anterior is 'IMEI y TipoProducto anteriores al último cambio de identidad.';
comment on column rma.producto_rt.texto_busqueda is 'ID, IMEI y equipo normalizados (sin mayúsculas ni tildes) para la búsqueda.';
comment on column rma.producto_rt.huella is 'SHA-256 de los datos del origen: detecta los cambios.';
comment on column rma.producto_rt.primera_vez_visto_en is 'Primera sincronización exitosa que lo trajo.';
comment on column rma.producto_rt.sincronizado_en is 'Última sincronización exitosa que escribió la fila.';
comment on column rma.producto_rt.sincronizacion_id is 'Intento que escribió esta versión de la fila (referencia a sincronizacion_origen).';
comment on column rma.producto_rt.propietario is
  'Transitoria: el secreto de la sincronización en curso viaja en cada escritura; el trigger lo verifica y lo vacía. Nunca se guarda. En un INSERT ... ON CONFLICT DO UPDATE, el DO UPDATE repite el secreto como parámetro.';
comment on column rma.producto_rt.creado_en is 'Cuándo se copió por primera vez.';
comment on column rma.producto_rt.modificado_en is 'Última modificación de la fila.';

-- Solo dentro de una sincronización EN_CURSO de PRODUCTOS_RT y con el
-- secreto de quien la reservó (como catalogo_producto_validar).
create or replace function rma.producto_rt_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_copia text;
  v_resultado text;
  v_hash text;
begin
  select copia, resultado, propietario_hash into v_copia, v_resultado, v_hash
    from rma.sincronizacion_origen where id = new.sincronizacion_id for share;
  if v_copia is distinct from 'PRODUCTOS_RT' or v_resultado is distinct from 'EN_CURSO' then
    raise exception 'La copia de Productos RT solo se escribe dentro de una sincronización EN_CURSO de PRODUCTOS_RT (intento %: %).',
      new.sincronizacion_id, coalesce(v_resultado, 'inexistente')
      using errcode = 'restrict_violation';
  end if;
  if v_hash is null or new.propietario is null or rma.hash_propietario(new.propietario) <> v_hash then
    raise exception 'Solo la sincronización que reservó el intento % escribe la copia.', new.sincronizacion_id
      using errcode = 'insufficient_privilege';
  end if;
  new.propietario := null;
  if tg_op = 'UPDATE' and (new.producto_id, new.primera_vez_visto_en, new.creado_en)
     is distinct from (old.producto_id, old.primera_vez_visto_en, old.creado_en) then
    raise exception 'El identificador y la primera sincronización de un producto no cambian.'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.producto_rt_validar() is
  'La copia de Productos RT se escribe solo dentro de una sincronización EN_CURSO de PRODUCTOS_RT y con el secreto de su propietario; su identificador y su primera sincronización no cambian.';

drop trigger if exists producto_rt_validar on rma.producto_rt;
create trigger producto_rt_validar
  before insert or update on rma.producto_rt
  for each row execute function rma.producto_rt_validar();

drop trigger if exists producto_rt_marcar_modificacion on rma.producto_rt;
create trigger producto_rt_marcar_modificacion
  before update on rma.producto_rt
  for each row execute function rma.marcar_modificacion();

drop trigger if exists producto_rt_sin_borrado on rma.producto_rt;
create trigger producto_rt_sin_borrado
  before delete on rma.producto_rt
  for each row execute function rma.impedir_borrado();

-- ---------------------------------------------------------------------------
-- Permisos (acceso, 1100): solo rma_backend; sin borrado.
-- ---------------------------------------------------------------------------
revoke all on rma.producto_rt from public;
do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on rma.producto_rt from %I', v_rol);
    end if;
  end loop;
end;
$$;

grant select, insert on rma.producto_rt to rma_backend;
grant update (
  estado_gestion_rt, en_reparacion, en_reparacion_desde, salio_de_reparacion_en,
  eliminado_en_origen, presente_en_origen, sede, imei, imei_normalizado, imei_valido,
  imei_luhn_valido, imei_repetido, tipo_producto_id, tipo_producto_encontrado,
  tipo_producto_eliminado, descripcion_tipo, modelo, categoria, subcategoria, capacidad,
  color, bateria, detalle_estetico, defecto, toma_rt, tipo_reparacion_origen, repuesto,
  creado_en_origen, conflicto_origen, cambio_identidad, identidad_anterior,
  texto_busqueda, huella, sincronizado_en, sincronizacion_id, propietario
) on rma.producto_rt to rma_backend;

revoke all on function rma.producto_rt_validar() from public;
