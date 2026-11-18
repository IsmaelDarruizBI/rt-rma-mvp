-- Rosario Tecno RMA — Copias de orígenes externos (bloque C, entrega 1).
--
-- La copia del catálogo de Ventas deja de ser un archivo efímero del
-- contenedor (deuda P1-2, F-08) y pasa a la base. El registro de intentos es
-- común: lo reutilizará la copia de Productos RT (DEC-RT-01).
-- Diseño: docs/persistencia-catalogos.md.
--
-- Aditiva: dos tablas nuevas, sin tocar las existentes ni mover datos.
--
--   * rma.sincronizacion_origen: cada intento de sincronizar una copia. Una
--     sola sincronización EN_CURSO por copia, entre todas las instancias
--     (índice único parcial). Una reserva vencida (instancia apagada a
--     mitad) se da por INTERRUMPIDA y deja lugar a la siguiente. Un intento
--     finalizado no cambia más; nada se borra.
--   * rma.catalogo_producto: la copia del catálogo de Ventas
--     (ProductoCatalogo). Nunca se borra: lo que Ventas deja de informar
--     queda no vigente. Solo se escribe dentro de una sincronización
--     EN_CURSO de su copia, así que una aplicación concurrente o tardía (de
--     una reserva ya interrumpida) se rechaza.
--
-- Sin clave foránea desde orden.equipo_tipo_producto_id: las Órdenes guardan
-- su propia copia del producto y la copia nueva empieza vacía.

-- ---------------------------------------------------------------------------
-- sincronizacion_origen
-- ---------------------------------------------------------------------------
create table if not exists rma.sincronizacion_origen (
  id text primary key check (id ~ '^SINC-[0-9a-f]{12}$'),
  copia text not null check (copia in ('CATALOGO_VENTAS')),
  usuario_id uuid not null references rma.usuario (id),
  origen text not null check (btrim(origen) <> ''),
  filtro text not null default '',
  iniciada_en timestamptz not null default now(),
  vence_en timestamptz not null,
  finalizada_en timestamptz,
  resultado text not null default 'EN_CURSO'
    check (resultado in ('EN_CURSO', 'EXITOSA', 'FALLIDA', 'RECHAZADA', 'INTERRUMPIDA')),
  mensaje text,
  contadores jsonb not null default '{}' check (jsonb_typeof(contadores) = 'object'),
  constraint sincronizacion_origen_finalizada
    check ((resultado = 'EN_CURSO') = (finalizada_en is null)),
  constraint sincronizacion_origen_vence check (vence_en > iniciada_en),
  constraint sincronizacion_origen_orden_fechas
    check (finalizada_en is null or finalizada_en >= iniciada_en)
);

-- La reserva: una sola sincronización en curso por copia.
create unique index if not exists sincronizacion_origen_en_curso
  on rma.sincronizacion_origen (copia) where resultado = 'EN_CURSO';
create index if not exists sincronizacion_origen_por_copia
  on rma.sincronizacion_origen (copia, iniciada_en desc);
create index if not exists sincronizacion_origen_usuario
  on rma.sincronizacion_origen (usuario_id);

comment on table rma.sincronizacion_origen is
  'Intentos de sincronizar una copia de un origen externo (catálogo de Ventas; después Productos RT). Una sola EN_CURSO por copia; un intento finalizado no cambia; nada se borra.';
comment on column rma.sincronizacion_origen.id is 'Identificador del intento (SINC-…), el mismo que informa la API.';
comment on column rma.sincronizacion_origen.copia is 'Qué copia sincroniza: CATALOGO_VENTAS.';
comment on column rma.sincronizacion_origen.usuario_id is 'Quién la pidió (referencia a usuario).';
comment on column rma.sincronizacion_origen.origen is 'Descripción del origen, sin secretos (por ejemplo «Google Sheets (hoja raw_TipoProducto)»).';
comment on column rma.sincronizacion_origen.filtro is 'Descripción del filtro aplicado, si lo hay.';
comment on column rma.sincronizacion_origen.iniciada_en is 'Hora de la base al reservar.';
comment on column rma.sincronizacion_origen.vence_en is 'Hasta cuándo vale la reserva: pasada esta hora, otra sincronización la da por INTERRUMPIDA.';
comment on column rma.sincronizacion_origen.finalizada_en is 'Cuándo terminó; vacía mientras está EN_CURSO.';
comment on column rma.sincronizacion_origen.resultado is 'EN_CURSO, EXITOSA, FALLIDA (el origen no respondió o no se pudo aplicar), RECHAZADA (datos no confiables) o INTERRUMPIDA (venció sin terminar).';
comment on column rma.sincronizacion_origen.mensaje is 'Motivo de un intento no exitoso, sin datos del origen ni credenciales.';
comment on column rma.sincronizacion_origen.contadores is 'Contadores del intento (leidos, nuevos, dados_de_baja, …), propios de cada copia.';

-- Alta solo EN_CURSO; después, una sola finalización; nunca se borra.
create or replace function rma.sincronizacion_origen_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'En rma.sincronizacion_origen no se borran filas: son el registro de los intentos.'
      using errcode = 'restrict_violation';
  end if;
  if tg_op = 'INSERT' then
    if new.resultado <> 'EN_CURSO' or new.finalizada_en is not null then
      raise exception 'Un intento de sincronización nace EN_CURSO.'
        using errcode = 'check_violation';
    end if;
    return new;
  end if;
  -- UPDATE
  if old.resultado <> 'EN_CURSO' then
    raise exception 'El intento % ya terminó (%): no cambia más.', old.id, old.resultado
      using errcode = 'restrict_violation';
  end if;
  if (new.id, new.copia, new.usuario_id, new.origen, new.filtro, new.iniciada_en, new.vence_en)
     is distinct from
     (old.id, old.copia, old.usuario_id, old.origen, old.filtro, old.iniciada_en, old.vence_en) then
    raise exception 'De un intento solo cambian su resultado, su fin, su mensaje y sus contadores.'
      using errcode = 'restrict_violation';
  end if;
  if new.resultado = 'EN_CURSO' then
    raise exception 'Un intento EN_CURSO solo pasa a un resultado final.'
      using errcode = 'restrict_violation';
  end if;
  if new.resultado = 'INTERRUMPIDA' and old.vence_en > now() then
    raise exception 'El intento % todavía no venció: no se puede dar por interrumpido.', old.id
      using errcode = 'restrict_violation';
  end if;
  new.finalizada_en := coalesce(new.finalizada_en, now());
  return new;
end;
$$;

comment on function rma.sincronizacion_origen_validar() is
  'Un intento nace EN_CURSO, termina una sola vez (INTERRUMPIDA solo si venció) y no se borra.';

drop trigger if exists sincronizacion_origen_validar on rma.sincronizacion_origen;
create trigger sincronizacion_origen_validar
  before insert or update or delete on rma.sincronizacion_origen
  for each row execute function rma.sincronizacion_origen_validar();

-- Reserva atómica: da por interrumpida una reserva vencida de la misma copia
-- y crea la nueva con la hora de la base. Si otra está vigente, el índice
-- único rechaza la nueva (unique_violation): la sincronización está en curso.
create or replace function rma.reservar_sincronizacion(
  p_id text,
  p_copia text,
  p_usuario_id uuid,
  p_origen text,
  p_filtro text,
  p_duracion interval
)
returns rma.sincronizacion_origen
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_reserva rma.sincronizacion_origen;
begin
  if p_duracion is null or p_duracion <= interval '0' or p_duracion > interval '1 hour' then
    raise exception 'La duración de la reserva debe ser mayor que cero y de una hora como máximo.'
      using errcode = 'check_violation';
  end if;
  update rma.sincronizacion_origen
     set resultado = 'INTERRUMPIDA',
         mensaje = 'La reserva venció sin terminar (instancia apagada o caída a mitad).'
   where copia = p_copia and resultado = 'EN_CURSO' and vence_en <= now();
  insert into rma.sincronizacion_origen (id, copia, usuario_id, origen, filtro, iniciada_en, vence_en)
  values (p_id, p_copia, p_usuario_id, p_origen, coalesce(p_filtro, ''), now(), now() + p_duracion)
  returning * into v_reserva;
  return v_reserva;
end;
$$;

comment on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval) is
  'Reserva la sincronización de una copia: interrumpe una reserva vencida y crea la nueva con la hora de la base; con otra vigente, unique_violation.';

-- ---------------------------------------------------------------------------
-- catalogo_producto
-- ---------------------------------------------------------------------------
create table if not exists rma.catalogo_producto (
  tipo_producto_id text primary key
    check (btrim(tipo_producto_id) <> '' and tipo_producto_id = btrim(tipo_producto_id)),
  descripcion text not null,
  categoria text,
  subcategoria text,
  grupo text,
  marca text,
  modelo text,
  variante text,
  capacidad text,
  color text,
  color_generico boolean not null default false,
  seleccionable boolean not null,
  motivo_no_seleccionable text check (motivo_no_seleccionable in ('GENERADOR', 'INCOMPLETO')),
  vigente boolean not null default true,
  motivo_baja text check (motivo_baja in ('NO_INFORMADO', 'ELIMINADO_EN_ORIGEN')),
  valores_origen jsonb not null default '{}' check (jsonb_typeof(valores_origen) = 'object'),
  primera_sincronizacion timestamptz not null,
  ultima_sincronizacion timestamptz not null,
  sincronizacion_id text not null references rma.sincronizacion_origen (id),
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  constraint catalogo_producto_seleccionable check (seleccionable = (motivo_no_seleccionable is null)),
  constraint catalogo_producto_vigente check (vigente = (motivo_baja is null)),
  constraint catalogo_producto_fechas check (primera_sincronizacion <= ultima_sincronizacion)
);

create index if not exists catalogo_producto_sincronizacion
  on rma.catalogo_producto (sincronizacion_id);

comment on table rma.catalogo_producto is
  'Copia del catálogo de equipos de Ventas de Gestión RT (BR-REP-048). Se escribe solo dentro de una sincronización EN_CURSO de CATALOGO_VENTAS; nunca se borra: lo que Ventas deja de informar queda no vigente.';
comment on column rma.catalogo_producto.tipo_producto_id is 'tp_id de Ventas, tal cual.';
comment on column rma.catalogo_producto.descripcion is 'Descripción completa del producto en Ventas.';
comment on column rma.catalogo_producto.categoria is 'Categoría de Ventas (tp_categoria).';
comment on column rma.catalogo_producto.subcategoria is 'Subcategoría de Ventas (tp_subcat_1).';
comment on column rma.catalogo_producto.grupo is 'Grupo de productos de Ventas (tp_gp).';
comment on column rma.catalogo_producto.marca is 'Marca, ya traducida a términos de RMA.';
comment on column rma.catalogo_producto.modelo is 'Modelo.';
comment on column rma.catalogo_producto.variante is 'Variante; vacía es la versión estándar.';
comment on column rma.catalogo_producto.capacidad is 'Capacidad legible (por ejemplo «128 GB»).';
comment on column rma.catalogo_producto.color is 'Color; vacío con color_generico es «cualquier color».';
comment on column rma.catalogo_producto.color_generico is 'Producto sin un color específico.';
comment on column rma.catalogo_producto.seleccionable is 'Representa un equipo elegible en el alta.';
comment on column rma.catalogo_producto.motivo_no_seleccionable is 'GENERADOR (registro técnico de Ventas) o INCOMPLETO.';
comment on column rma.catalogo_producto.vigente is 'Lo informó la última sincronización exitosa y no está eliminado.';
comment on column rma.catalogo_producto.motivo_baja is 'NO_INFORMADO o ELIMINADO_EN_ORIGEN; vacío si está vigente.';
comment on column rma.catalogo_producto.valores_origen is 'Valores tal como vinieron de Ventas (tp_number, tp_gb, …), para auditoría.';
comment on column rma.catalogo_producto.primera_sincronizacion is 'Primera sincronización exitosa que lo trajo.';
comment on column rma.catalogo_producto.ultima_sincronizacion is 'Última sincronización exitosa que lo informó o lo dio de baja.';
comment on column rma.catalogo_producto.sincronizacion_id is 'Intento que escribió esta versión de la fila (referencia a sincronizacion_origen).';
comment on column rma.catalogo_producto.creado_en is 'Cuándo se copió por primera vez.';
comment on column rma.catalogo_producto.modificado_en is 'Última modificación de la fila.';

-- Solo se escribe dentro de una sincronización EN_CURSO de su copia. El
-- FOR SHARE coordina con la reserva: si otra sincronización interrumpe esta
-- en paralelo, una de las dos espera y la otra ve el resultado confirmado.
create or replace function rma.catalogo_producto_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_copia text;
  v_resultado text;
begin
  select copia, resultado into v_copia, v_resultado
    from rma.sincronizacion_origen where id = new.sincronizacion_id for share;
  if v_copia is distinct from 'CATALOGO_VENTAS' or v_resultado is distinct from 'EN_CURSO' then
    raise exception 'La copia del catálogo solo se escribe dentro de una sincronización EN_CURSO de CATALOGO_VENTAS (intento %: %).',
      new.sincronizacion_id, coalesce(v_resultado, 'inexistente')
      using errcode = 'restrict_violation';
  end if;
  if tg_op = 'UPDATE' and (new.tipo_producto_id, new.primera_sincronizacion, new.creado_en)
     is distinct from (old.tipo_producto_id, old.primera_sincronizacion, old.creado_en) then
    raise exception 'El identificador y la primera sincronización de un producto no cambian.'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.catalogo_producto_validar() is
  'La copia del catálogo se escribe solo dentro de una sincronización EN_CURSO de CATALOGO_VENTAS; su identificador y su primera sincronización no cambian.';

drop trigger if exists catalogo_producto_validar on rma.catalogo_producto;
create trigger catalogo_producto_validar
  before insert or update on rma.catalogo_producto
  for each row execute function rma.catalogo_producto_validar();

drop trigger if exists catalogo_producto_marcar_modificacion on rma.catalogo_producto;
create trigger catalogo_producto_marcar_modificacion
  before update on rma.catalogo_producto
  for each row execute function rma.marcar_modificacion();

drop trigger if exists catalogo_producto_sin_borrado on rma.catalogo_producto;
create trigger catalogo_producto_sin_borrado
  before delete on rma.catalogo_producto
  for each row execute function rma.impedir_borrado();

-- ---------------------------------------------------------------------------
-- Permisos (acceso, 1100): solo rma_backend; sin borrado.
-- ---------------------------------------------------------------------------
revoke all on rma.sincronizacion_origen, rma.catalogo_producto from public;
do $$
declare
  v_rol text;
begin
  foreach v_rol in array array['anon', 'authenticated', 'service_role'] loop
    if exists (select 1 from pg_roles where rolname = v_rol) then
      execute format('revoke all on rma.sincronizacion_origen, rma.catalogo_producto from %I', v_rol);
      execute format('revoke all on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval) from %I', v_rol);
    end if;
  end loop;
end;
$$;

grant select, insert on rma.sincronizacion_origen to rma_backend;
grant update (resultado, finalizada_en, mensaje, contadores) on rma.sincronizacion_origen to rma_backend;

grant select, insert on rma.catalogo_producto to rma_backend;
grant update (
  descripcion, categoria, subcategoria, grupo, marca, modelo, variante, capacidad, color,
  color_generico, seleccionable, motivo_no_seleccionable, vigente, motivo_baja,
  valores_origen, ultima_sincronizacion, sincronizacion_id
) on rma.catalogo_producto to rma_backend;

revoke all on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval) from public;
grant execute on function rma.reservar_sincronizacion(text, text, uuid, text, text, interval) to rma_backend;
