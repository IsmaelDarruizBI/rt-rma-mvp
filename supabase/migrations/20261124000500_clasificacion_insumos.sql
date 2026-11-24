-- Rosario Tecno RMA — Clasificación de insumos y compatibilidad con modelos
-- (ajustes funcionales, iteración 2, bloque 8, parte A; DEC-AJ-14 D-14.1,
-- D-14.2 y D-14.5, BR-REP-049, DEC-CFG-05, ABI-53).
--
-- Cada insumo sigue siendo un repuesto real (SKU) con su stock, lotes,
-- costos, movimientos, reservas y consumos: nada de eso cambia. Se agrega:
--   * `categoria_insumo`: catálogo administrable de dos niveles fijos,
--     categoría (sin padre) y subcategoría (su padre es una categoría). El
--     padre no cambia después del alta, así que nunca hay un tercer nivel.
--     Código CAT-NNN automático. No se borra: se desactiva;
--   * `fabricante_repuesto`: catálogo administrable de fabricantes o marcas
--     de repuestos, distinto de la marca del equipo. Código FAB-NNN
--     automático. No se borra: se desactiva;
--   * en `insumo`, opcionales: la categoría (el nivel más específico: una
--     subcategoría o, si no tiene, la categoría; la categoría padre se
--     deriva), el fabricante, la variante y el código del fabricante o del
--     proveedor (para buscar; no es único y no reemplaza al código INS);
--   * `insumo_compatibilidad`: los modelos de equipo (el mismo catálogo de
--     los precios, DEC-AJ-12) con los que es compatible cada insumo. Sin
--     filas, el insumo es universal (compatible con todos). Cada cambio se
--     audita en `cambio_configuracion` (entidad INSUMO, campo
--     «compatibilidad», con la lista ordenada de códigos MOD);
--   * entidades CATEGORIA_INSUMO y FABRICANTE_REPUESTO en la auditoría.
--
-- D-14.5: ningún dato existente cambia. Los insumos quedan sin clasificar y
-- universales, sin movimientos de stock; lotes, movimientos, compras,
-- reservas y consumos no se tocan.

-- ---------------------------------------------------------------------------
-- Códigos CAT-NNN y FAB-NNN
-- ---------------------------------------------------------------------------
create sequence if not exists rma.codigo_cat_seq;
comment on sequence rma.codigo_cat_seq is 'Número de los códigos CAT-NNN de categoria_insumo (rma.siguiente_codigo).';
create sequence if not exists rma.codigo_fab_seq;
comment on sequence rma.codigo_fab_seq is 'Número de los códigos FAB-NNN de fabricante_repuesto (rma.siguiente_codigo).';

-- ---------------------------------------------------------------------------
-- Categorías y subcategorías (D-14.2)
-- ---------------------------------------------------------------------------
create table if not exists rma.categoria_insumo (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^CAT-[0-9]{3,}$'),
  nombre text not null check (btrim(nombre) <> ''),
  padre_id uuid references rma.categoria_insumo (id),
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  constraint categoria_insumo_no_es_su_padre check (padre_id is distinct from id)
);

-- El mismo nombre no se repite entre las categorías ni entre las
-- subcategorías de una misma categoría, sin distinguir mayúsculas.
create unique index if not exists categoria_insumo_nombre_unico
  on rma.categoria_insumo (padre_id, lower(btrim(nombre))) nulls not distinct;
create index if not exists categoria_insumo_padre on rma.categoria_insumo (padre_id);

create or replace function rma.categoria_insumo_dos_niveles()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'UPDATE' and new.padre_id is distinct from old.padre_id then
    raise exception 'La categoría % no cambia de nivel ni de categoría padre.', old.codigo
      using errcode = 'restrict_violation';
  end if;
  if new.padre_id is not null and exists (
    select 1 from rma.categoria_insumo p where p.id = new.padre_id and p.padre_id is not null
  ) then
    raise exception 'Solo hay dos niveles: la categoría padre de % no puede ser una subcategoría.', new.codigo
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.categoria_insumo_dos_niveles() is
  'Categorías de insumos con dos niveles fijos (DEC-AJ-14): el padre de una subcategoría es una categoría sin padre, y el padre no cambia después del alta.';

drop trigger if exists categoria_insumo_dos_niveles on rma.categoria_insumo;
create trigger categoria_insumo_dos_niveles before insert or update on rma.categoria_insumo
  for each row execute function rma.categoria_insumo_dos_niveles();
drop trigger if exists categoria_insumo_codigo_fijo on rma.categoria_insumo;
create trigger categoria_insumo_codigo_fijo before update of codigo on rma.categoria_insumo
  for each row execute function rma.impedir_cambio_codigo();
drop trigger if exists categoria_insumo_modificacion on rma.categoria_insumo;
create trigger categoria_insumo_modificacion before update on rma.categoria_insumo
  for each row execute function rma.marcar_modificacion();
drop trigger if exists categoria_insumo_sin_borrado on rma.categoria_insumo;
create trigger categoria_insumo_sin_borrado before delete on rma.categoria_insumo
  for each row execute function rma.impedir_borrado();

comment on table rma.categoria_insumo is
  'Categorías y subcategorías de insumos (DEC-AJ-14): dos niveles fijos, administrables con el permiso de insumos y auditados (entidad CATEGORIA_INSUMO). Una categoría no tiene padre; una subcategoría tiene por padre una categoría. No se borran: se desactivan, y una inactiva no se asigna a un insumo nuevo ni a un cambio.';
comment on column rma.categoria_insumo.id is 'Identificador interno.';
comment on column rma.categoria_insumo.codigo is 'Identificador público estable, con formato CAT-001. Lo genera la base (rma.siguiente_codigo) y no cambia.';
comment on column rma.categoria_insumo.nombre is 'Nombre visible (por ejemplo «Baterías» o «OLED»); único entre sus pares sin distinguir mayúsculas.';
comment on column rma.categoria_insumo.padre_id is 'Categoría a la que pertenece una subcategoría (referencia a categoria_insumo); vacío en una categoría. No cambia después del alta.';
comment on column rma.categoria_insumo.activo is 'Falso: dada de baja; los insumos que ya la tienen la conservan.';
comment on column rma.categoria_insumo.creado_en is 'Fecha y hora del alta.';
comment on column rma.categoria_insumo.modificado_en is 'Fecha y hora del último cambio.';

-- ---------------------------------------------------------------------------
-- Fabricantes de repuestos (D-14.2)
-- ---------------------------------------------------------------------------
create table if not exists rma.fabricante_repuesto (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (codigo ~ '^FAB-[0-9]{3,}$'),
  nombre text not null check (btrim(nombre) <> ''),
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now()
);

create unique index if not exists fabricante_repuesto_nombre_unico
  on rma.fabricante_repuesto (lower(btrim(nombre)));

drop trigger if exists fabricante_repuesto_codigo_fijo on rma.fabricante_repuesto;
create trigger fabricante_repuesto_codigo_fijo before update of codigo on rma.fabricante_repuesto
  for each row execute function rma.impedir_cambio_codigo();
drop trigger if exists fabricante_repuesto_modificacion on rma.fabricante_repuesto;
create trigger fabricante_repuesto_modificacion before update on rma.fabricante_repuesto
  for each row execute function rma.marcar_modificacion();
drop trigger if exists fabricante_repuesto_sin_borrado on rma.fabricante_repuesto;
create trigger fabricante_repuesto_sin_borrado before delete on rma.fabricante_repuesto
  for each row execute function rma.impedir_borrado();

comment on table rma.fabricante_repuesto is
  'Fabricantes o marcas de repuestos (DEC-AJ-14), distintos de la marca del equipo. Administrables con el permiso de insumos y auditados (entidad FABRICANTE_REPUESTO). No se borran: se desactivan. La marca del repuesto no cambia el Tipo de Reparación ni el precio de venta (D-14.3).';
comment on column rma.fabricante_repuesto.id is 'Identificador interno.';
comment on column rma.fabricante_repuesto.codigo is 'Identificador público estable, con formato FAB-001. Lo genera la base (rma.siguiente_codigo) y no cambia.';
comment on column rma.fabricante_repuesto.nombre is 'Nombre del fabricante o marca; único sin distinguir mayúsculas.';
comment on column rma.fabricante_repuesto.activo is 'Falso: dado de baja; los insumos que ya lo tienen lo conservan.';
comment on column rma.fabricante_repuesto.creado_en is 'Fecha y hora del alta.';
comment on column rma.fabricante_repuesto.modificado_en is 'Fecha y hora del último cambio.';

-- ---------------------------------------------------------------------------
-- Clasificación del insumo (D-14.1, D-14.2): opcional y gradual
-- ---------------------------------------------------------------------------
alter table rma.insumo
  add column if not exists categoria_id uuid references rma.categoria_insumo (id),
  add column if not exists fabricante_id uuid references rma.fabricante_repuesto (id),
  add column if not exists variante text,
  add column if not exists codigo_fabricante text;

alter table rma.insumo drop constraint if exists insumo_variante_no_vacia;
alter table rma.insumo add constraint insumo_variante_no_vacia
  check (variante is null or btrim(variante) <> '');
alter table rma.insumo drop constraint if exists insumo_codigo_fabricante_no_vacio;
alter table rma.insumo add constraint insumo_codigo_fabricante_no_vacio
  check (codigo_fabricante is null or btrim(codigo_fabricante) <> '');

create index if not exists insumo_categoria on rma.insumo (categoria_id) where categoria_id is not null;
create index if not exists insumo_fabricante on rma.insumo (fabricante_id) where fabricante_id is not null;

comment on table rma.insumo is
  'Repuestos y materiales con stock. Cada insumo es un repuesto real (SKU): su stock, lotes, costos, movimientos, reservas y consumos son suyos (DEC-AJ-14). El disponible (físico menos reservado) nunca es negativo: la base exige que el físico cubra siempre lo reservado (G-2).';
comment on column rma.insumo.categoria_id is
  'Clasificación del insumo (referencia a categoria_insumo): el nivel más específico, una subcategoría o, si no tiene, una categoría; la categoría padre se deriva. Vacío: sin clasificar (los insumos anteriores a DEC-AJ-14).';
comment on column rma.insumo.fabricante_id is 'Fabricante o marca del repuesto (referencia a fabricante_repuesto); vacío si no se informó.';
comment on column rma.insumo.variante is 'Variante descriptiva del repuesto (por ejemplo «con marco» o «negro»); vacía si no se informó.';
comment on column rma.insumo.codigo_fabricante is 'Código del fabricante o del proveedor (número de parte), para buscar; opcional y no único. El identificador interno sigue siendo el código INS.';

grant update (categoria_id, fabricante_id, variante, codigo_fabricante) on rma.insumo to rma_backend;

-- ---------------------------------------------------------------------------
-- Compatibilidad con modelos de equipo (D-14.2, ABI-53)
-- ---------------------------------------------------------------------------
create table if not exists rma.insumo_compatibilidad (
  insumo_id uuid not null references rma.insumo (id),
  modelo_equipo_id uuid not null references rma.modelo_equipo (id),
  creado_en timestamptz not null default now(),
  primary key (insumo_id, modelo_equipo_id)
);

create index if not exists insumo_compatibilidad_modelo on rma.insumo_compatibilidad (modelo_equipo_id);

comment on table rma.insumo_compatibilidad is
  'Modelos de equipo con los que es compatible cada insumo (DEC-AJ-14): de muchos a muchos con el catálogo técnico de los precios (modelo_equipo). Un insumo sin filas es universal: compatible con todos los modelos. Es el conjunto vigente: al editarlo se agregan y se quitan filas, y cada cambio queda en cambio_configuracion (entidad INSUMO, campo «compatibilidad», con los códigos MOD ordenados antes y después).';
comment on column rma.insumo_compatibilidad.insumo_id is 'Insumo (referencia a insumo).';
comment on column rma.insumo_compatibilidad.modelo_equipo_id is 'Modelo de equipo compatible (referencia a modelo_equipo).';
comment on column rma.insumo_compatibilidad.creado_en is 'Fecha y hora en que se agregó el modelo.';

grant select, insert, delete on rma.insumo_compatibilidad to rma_backend;

-- ---------------------------------------------------------------------------
-- Códigos automáticos: CAT y FAB (los demás prefijos no cambian)
-- ---------------------------------------------------------------------------
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
      when 'CAT' then v_numero := nextval('rma.codigo_cat_seq'); v_ancho := 3;
      when 'FAB' then v_numero := nextval('rma.codigo_fab_seq'); v_ancho := 3;
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
      when 'CAT' then exists (select 1 from rma.categoria_insumo where codigo = v_codigo)
      when 'FAB' then exists (select 1 from rma.fabricante_repuesto where codigo = v_codigo)
    end;
    exit when not v_usado;
  end loop;
  return v_codigo;
end;
$$;

comment on function rma.siguiente_codigo(text) is
  'Código siguiente libre de un prefijo (TR, CANC, INT, INS, PRV, CHK, SC, OC, RGA, MOD, CAT, FAB): secuencia propia, ancho mínimo sin truncar y salto de los códigos ya usados. Puede dejar huecos; nunca repite.';

revoke all on sequence rma.codigo_cat_seq from public;
revoke all on sequence rma.codigo_fab_seq from public;
do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on sequence rma.codigo_cat_seq from %I', v_rol);
      execute format('revoke all on sequence rma.codigo_fab_seq from %I', v_rol);
    end if;
  end loop;
end;
$$;
grant usage on sequence rma.codigo_cat_seq to rma_backend;
grant usage on sequence rma.codigo_fab_seq to rma_backend;

grant select on rma.categoria_insumo to rma_backend;
grant insert (codigo, nombre, padre_id, activo) on rma.categoria_insumo to rma_backend;
grant update (nombre, activo) on rma.categoria_insumo to rma_backend;
grant select on rma.fabricante_repuesto to rma_backend;
grant insert (codigo, nombre, activo) on rma.fabricante_repuesto to rma_backend;
grant update (nombre, activo) on rma.fabricante_repuesto to rma_backend;

-- ---------------------------------------------------------------------------
-- Auditoría
-- ---------------------------------------------------------------------------
alter table rma.cambio_configuracion drop constraint if exists cambio_configuracion_entidad_check;
alter table rma.cambio_configuracion add constraint cambio_configuracion_entidad_check
  check (entidad in (
    'TIPO_REPARACION', 'MESA_TRABAJO', 'USUARIO', 'PERMISO', 'INSUMO',
    'MOTIVO', 'PLANTILLA', 'PARAMETRO', 'CHECKLIST', 'PROVEEDOR', 'MEDIO_PAGO',
    'EMPRESA', 'TEXTO_LEGAL', 'MODELO_EQUIPO', 'PRECIO_MODELO',
    'CATEGORIA_INSUMO', 'FABRICANTE_REPUESTO'
  ));

comment on column rma.cambio_configuracion.entidad is
  'Qué se cambió: un catálogo (TIPO_REPARACION, MESA_TRABAJO, INSUMO, MOTIVO, PLANTILLA, CHECKLIST, PROVEEDOR, MODELO_EQUIPO, CATEGORIA_INSUMO, FABRICANTE_REPUESTO), el precio de un tipo para un modelo (PRECIO_MODELO, clave «TR-001/MOD-0012»), la asignación de roles (USUARIO), un permiso (PERMISO), un parámetro (PARAMETRO), el recargo de un medio de pago (MEDIO_PAGO), los datos de la empresa (EMPRESA) o una versión nueva de un texto legal (TEXTO_LEGAL). La clasificación y la compatibilidad de un insumo van en INSUMO (campos categoria, fabricante, variante, codigo_fabricante y compatibilidad).';
