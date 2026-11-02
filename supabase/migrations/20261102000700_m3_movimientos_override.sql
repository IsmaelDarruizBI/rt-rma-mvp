-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0700. M3 Inventario: libro de movimientos y override por falta de stock.
--
-- El libro es la única fuente de los saldos: cada movimiento, al insertarse,
-- valida su vínculo de origen y actualiza stock_fisico y stock_reservado del
-- insumo en la misma transacción. La restricción insumo_fisico_cubre_reservado
-- impide que el disponible quede negativo (G-2). Los movimientos son inmutables.
--
-- Orden de bloqueo que deben respetar los servicios: Cliente, Orden e insumos
-- de menor a mayor id. El trigger vuelve a bloquear el insumo (ya bloqueado
-- por el servicio), así que no introduce un orden distinto.

create table rma.movimiento_inventario (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  tipo text not null check (tipo in (
    'RESERVA', 'LIBERACION_RESERVA', 'CONSUMO', 'INGRESO', 'AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO',
    'DESPERDICIO', 'DEVOLUCION'
  )),
  insumo_id uuid not null references rma.insumo (id),
  cantidad numeric(12, 3) not null check (cantidad > 0),
  orden_id uuid references rma.orden (id),
  detalle_id uuid,
  ejecucion_id uuid,
  movimiento_origen_id uuid,
  motivo_ajuste_id uuid references rma.motivo_ajuste (id),
  motivo_texto text,
  referencia text,
  observacion text,
  usuario_id uuid references rma.usuario (id),
  accion_id uuid not null references rma.accion_usuario (id),
  registrado_en timestamptz not null default now(),
  stock_fisico_anterior numeric(12, 3) not null default 0,
  stock_fisico_resultante numeric(12, 3) not null default 0,
  stock_reservado_resultante numeric(12, 3) not null default 0,
  unique (id, insumo_id),
  constraint movimiento_origen foreign key (movimiento_origen_id, insumo_id)
    references rma.movimiento_inventario (id, insumo_id),
  constraint movimiento_detalle foreign key (detalle_id, orden_id) references rma.detalle (id, orden_id),
  constraint movimiento_ejecucion foreign key (ejecucion_id, detalle_id) references rma.ejecucion (id, detalle_id),
  -- DESPERDICIO y DEVOLUCION están definidos sin operación habilitada (ABI-22).
  -- Habilitarlos es una migración que quita esta restricción.
  constraint movimiento_tipo_con_operacion check (tipo not in ('DESPERDICIO', 'DEVOLUCION')),
  constraint movimiento_vinculos_por_tipo check (
    (tipo = 'RESERVA'
       and orden_id is not null and detalle_id is not null
       and movimiento_origen_id is null and motivo_ajuste_id is null)
    or (tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO')
       and orden_id is not null and detalle_id is not null and ejecucion_id is not null
       and movimiento_origen_id is not null and motivo_ajuste_id is null)
    or (tipo = 'DEVOLUCION'
       and orden_id is not null and detalle_id is not null
       and movimiento_origen_id is not null and motivo_ajuste_id is null)
    or (tipo = 'INGRESO'
       and orden_id is null and detalle_id is null and ejecucion_id is null
       and movimiento_origen_id is null and motivo_ajuste_id is null
       and motivo_texto is not null)
    or (tipo in ('AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO')
       and orden_id is null and detalle_id is null and ejecucion_id is null
       and movimiento_origen_id is null and motivo_ajuste_id is not null
       and motivo_texto is not null and usuario_id is not null)
  )
);

create index movimiento_insumo_fecha on rma.movimiento_inventario (insumo_id, registrado_en);
create index movimiento_origen_idx on rma.movimiento_inventario (movimiento_origen_id) where movimiento_origen_id is not null;
create index movimiento_detalle_idx on rma.movimiento_inventario (detalle_id) where detalle_id is not null;
create index movimiento_orden_idx on rma.movimiento_inventario (orden_id) where orden_id is not null;
create index movimiento_ejecucion_idx on rma.movimiento_inventario (ejecucion_id) where ejecucion_id is not null;
create index movimiento_reservas on rma.movimiento_inventario (insumo_id) where tipo = 'RESERVA';
-- Una referencia de ingreso o ajuste no se repite por insumo y tipo (sin distinguir mayúsculas).
create unique index movimiento_referencia_unica
  on rma.movimiento_inventario (insumo_id, tipo, lower(referencia))
  where referencia is not null and tipo in ('INGRESO', 'AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO');

create or replace function rma.aplicar_movimiento_inventario()
returns trigger
language plpgsql
security definer
set search_path = rma, pg_temp
as $$
declare
  v_insumo rma.insumo%rowtype;
  v_origen rma.movimiento_inventario%rowtype;
  v_cerrado numeric(12, 3);
  v_aplica_a text;
  v_sentido text;
  v_cerrada_orden timestamptz;
  v_fisico numeric(12, 3);
  v_reservado numeric(12, 3);
begin
  select * into v_insumo from rma.insumo where id = new.insumo_id for update;

  -- Este trigger cambia saldos antes de que PostgreSQL resuelva un ON CONFLICT:
  -- un código repetido se rechaza aquí, para que un INSERT ... ON CONFLICT DO
  -- NOTHING nunca aplique un movimiento que luego se descarta. La verificación
  -- va después del bloqueo del insumo, así ve los movimientos ya confirmados.
  if exists (select 1 from rma.movimiento_inventario where codigo = new.codigo) then
    raise exception 'El movimiento % ya existe. El libro no admite ON CONFLICT: un reintento se resuelve con la clave de idempotencia de la acción.', new.codigo
      using errcode = 'unique_violation';
  end if;

  if new.orden_id is not null then
    select cerrada_en into v_cerrada_orden from rma.orden where id = new.orden_id;
    if v_cerrada_orden is not null then
      raise exception 'La Orden está cerrada: no admite movimientos de inventario.'
        using errcode = 'restrict_violation';
    end if;
  end if;

  if new.tipo in ('RESERVA', 'INGRESO', 'AJUSTE_POSITIVO') and not v_insumo.activo then
    raise exception 'El insumo % está inactivo: no admite reservas ni ingresos nuevos.', v_insumo.codigo
      using errcode = 'check_violation';
  end if;

  -- Vínculo con el movimiento de origen.
  if new.tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO') then
    select * into v_origen from rma.movimiento_inventario where id = new.movimiento_origen_id;
    if v_origen.tipo <> 'RESERVA'
       or v_origen.orden_id <> new.orden_id
       or v_origen.detalle_id <> new.detalle_id then
      raise exception 'Un % debe cerrar una RESERVA del mismo insumo, Orden y Detalle.', new.tipo
        using errcode = 'check_violation';
    end if;
    select coalesce(sum(cantidad), 0) into v_cerrado
      from rma.movimiento_inventario
     where movimiento_origen_id = v_origen.id
       and tipo in ('CONSUMO', 'LIBERACION_RESERVA', 'DESPERDICIO');
    if v_cerrado + new.cantidad > v_origen.cantidad then
      raise exception 'La reserva % tiene pendiente %, menos que % de %.',
        v_origen.codigo, v_origen.cantidad - v_cerrado, new.cantidad, new.tipo
        using errcode = 'check_violation';
    end if;
  elsif new.tipo = 'DEVOLUCION' then
    select * into v_origen from rma.movimiento_inventario where id = new.movimiento_origen_id;
    if v_origen.tipo <> 'CONSUMO'
       or v_origen.orden_id <> new.orden_id
       or v_origen.detalle_id <> new.detalle_id then
      raise exception 'Una DEVOLUCION debe referenciar un CONSUMO del mismo insumo, Orden y Detalle.'
        using errcode = 'check_violation';
    end if;
    select coalesce(sum(cantidad), 0) into v_cerrado
      from rma.movimiento_inventario
     where movimiento_origen_id = v_origen.id and tipo = 'DEVOLUCION';
    if v_cerrado + new.cantidad > v_origen.cantidad then
      raise exception 'La devolución supera lo consumido en % menos lo ya devuelto.', v_origen.codigo
        using errcode = 'check_violation';
    end if;
  elsif new.tipo in ('AJUSTE_POSITIVO', 'AJUSTE_NEGATIVO') then
    select aplica_a into v_aplica_a from rma.motivo_ajuste where id = new.motivo_ajuste_id;
    v_sentido := case new.tipo when 'AJUSTE_POSITIVO' then 'POSITIVO' else 'NEGATIVO' end;
    if v_aplica_a not in ('AMBOS', v_sentido) then
      raise exception 'El motivo elegido no aplica a un %.', new.tipo using errcode = 'check_violation';
    end if;
  end if;

  -- Efecto sobre los saldos.
  v_fisico := v_insumo.stock_fisico;
  v_reservado := v_insumo.stock_reservado;
  case new.tipo
    when 'RESERVA' then v_reservado := v_reservado + new.cantidad;
    when 'LIBERACION_RESERVA' then v_reservado := v_reservado - new.cantidad;
    when 'CONSUMO' then v_fisico := v_fisico - new.cantidad; v_reservado := v_reservado - new.cantidad;
    when 'DESPERDICIO' then v_fisico := v_fisico - new.cantidad; v_reservado := v_reservado - new.cantidad;
    when 'DEVOLUCION' then v_fisico := v_fisico + new.cantidad;
    when 'INGRESO' then v_fisico := v_fisico + new.cantidad;
    when 'AJUSTE_POSITIVO' then v_fisico := v_fisico + new.cantidad;
    when 'AJUSTE_NEGATIVO' then v_fisico := v_fisico - new.cantidad;
  end case;

  if v_fisico < v_reservado then
    raise exception 'El movimiento dejaría el stock físico de % en % con % reservado: el disponible no puede ser negativo. Regularizá antes las reservas.',
      v_insumo.codigo, v_fisico, v_reservado
      using errcode = 'check_violation';
  end if;

  new.stock_fisico_anterior := v_insumo.stock_fisico;
  new.stock_fisico_resultante := v_fisico;
  new.stock_reservado_resultante := v_reservado;

  update rma.insumo
     set stock_fisico = v_fisico, stock_reservado = v_reservado
   where id = new.insumo_id;

  return new;
end;
$$;

comment on function rma.aplicar_movimiento_inventario() is
  'Valida el vínculo de origen de cada movimiento y actualiza los saldos del insumo en la misma transacción. Rechaza el movimiento si dejaría el disponible negativo.';

create trigger movimiento_aplicar before insert on rma.movimiento_inventario
  for each row execute function rma.aplicar_movimiento_inventario();
create trigger movimiento_inmutable before update or delete on rma.movimiento_inventario
  for each row execute function rma.impedir_modificacion();

comment on table rma.movimiento_inventario is
  'Libro único e inmutable de inventario (ABI-22). Explica cada cambio de stock físico y reservado: reservas, consumos y liberaciones de las Órdenes, ingresos y ajustes manuales. Una corrección es un movimiento nuevo.';
comment on column rma.movimiento_inventario.id is 'Identificador interno del movimiento.';
comment on column rma.movimiento_inventario.codigo is 'Identificador público del movimiento, el que hoy usa la API.';
comment on column rma.movimiento_inventario.tipo is 'RESERVA (compromete stock), LIBERACION_RESERVA (devuelve lo reservado no usado), CONSUMO (baja lo usado), INGRESO, AJUSTE_POSITIVO o AJUSTE_NEGATIVO. DESPERDICIO y DEVOLUCION están definidos sin operación habilitada.';
comment on column rma.movimiento_inventario.insumo_id is 'Insumo afectado (referencia a insumo).';
comment on column rma.movimiento_inventario.cantidad is 'Cantidad movida, siempre positiva, en la unidad del insumo; el tipo define si suma o resta.';
comment on column rma.movimiento_inventario.orden_id is 'Orden que originó el movimiento (referencia a orden); vacía en ingresos y ajustes.';
comment on column rma.movimiento_inventario.detalle_id is 'Detalle que originó el movimiento (referencia a detalle); vacío en ingresos y ajustes.';
comment on column rma.movimiento_inventario.ejecucion_id is 'Ejecución que originó el movimiento (referencia a ejecucion); obligatoria en consumos y liberaciones.';
comment on column rma.movimiento_inventario.movimiento_origen_id is 'Movimiento que este cierra o revierte (referencia a movimiento_inventario): la RESERVA en consumos y liberaciones, el CONSUMO en una devolución.';
comment on column rma.movimiento_inventario.motivo_ajuste_id is 'Motivo parametrizado de un ajuste manual (referencia a motivo_ajuste); obligatorio en ajustes.';
comment on column rma.movimiento_inventario.motivo_texto is 'Motivo u origen escrito por el usuario; obligatorio en ingresos y ajustes.';
comment on column rma.movimiento_inventario.referencia is 'Referencia de la operación (remito, número de recuento); no se repite por insumo y tipo.';
comment on column rma.movimiento_inventario.observacion is 'Observación del sistema o del usuario, por ejemplo una reserva parcial por override.';
comment on column rma.movimiento_inventario.usuario_id is 'Usuario responsable (referencia a usuario); vacío en los movimientos que genera el sistema, cuyo responsable sale de la Ejecución.';
comment on column rma.movimiento_inventario.accion_id is 'Acción confirmada en la que se registró el movimiento (referencia a accion_usuario).';
comment on column rma.movimiento_inventario.registrado_en is 'Fecha y hora del movimiento.';
comment on column rma.movimiento_inventario.stock_fisico_anterior is 'Stock físico del insumo inmediatamente antes de este movimiento; lo completa la base.';
comment on column rma.movimiento_inventario.stock_fisico_resultante is 'Stock físico del insumo después de este movimiento; lo completa la base.';
comment on column rma.movimiento_inventario.stock_reservado_resultante is 'Stock reservado del insumo después de este movimiento; lo completa la base. El disponible resultante es la diferencia con el físico.';

-- ---------------------------------------------------------------------------
-- override_recursos
-- ---------------------------------------------------------------------------
create table rma.override_recursos (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null,
  detalle_id uuid not null,
  detalle_version_id uuid not null,
  motivo text not null check (btrim(motivo) <> ''),
  usuario_id uuid not null references rma.usuario (id),
  autorizado_en timestamptz not null default now(),
  constraint override_detalle foreign key (detalle_id, orden_id) references rma.detalle (id, orden_id),
  constraint override_version foreign key (detalle_version_id, detalle_id) references rma.detalle_version (id, detalle_id)
);

create index override_recursos_version on rma.override_recursos (detalle_version_id);

create trigger override_recursos_inmutable before update or delete on rma.override_recursos
  for each row execute function rma.impedir_modificacion();
create trigger override_recursos_orden_abierta before insert on rma.override_recursos
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.override_recursos is
  'Autorización para trabajar un Detalle bloqueado por falta de stock (P-06). La autoriza cualquier rol, con motivo; nunca es automática. Vale solo para la versión de definición que referencia: una redefinición la anula.';
comment on column rma.override_recursos.id is 'Identificador interno del override.';
comment on column rma.override_recursos.orden_id is 'Orden del Detalle, repetida para validar el vínculo (referencia a orden).';
comment on column rma.override_recursos.detalle_id is 'Detalle bloqueado que se autoriza (referencia a detalle).';
comment on column rma.override_recursos.detalle_version_id is 'Versión de definición para la que vale el override (referencia a detalle_version).';
comment on column rma.override_recursos.motivo is 'Motivo de la autorización.';
comment on column rma.override_recursos.usuario_id is 'Usuario que autorizó (referencia a usuario).';
comment on column rma.override_recursos.autorizado_en is 'Fecha y hora de la autorización.';

create table rma.override_insumo (
  override_id uuid not null references rma.override_recursos (id),
  insumo_id uuid not null references rma.insumo (id),
  requerido numeric(12, 3) not null check (requerido > 0),
  disponible numeric(12, 3) not null check (disponible >= 0),
  a_reservar numeric(12, 3) not null check (a_reservar >= 0),
  faltante numeric(12, 3) not null check (faltante >= 0),
  primary key (override_id, insumo_id),
  constraint override_insumo_calculo check (
    a_reservar = least(requerido, disponible) and faltante = requerido - a_reservar
  )
);

create trigger override_insumo_inmutable before update or delete on rma.override_insumo
  for each row execute function rma.impedir_modificacion();

comment on table rma.override_insumo is
  'Impacto que el usuario confirmó al autorizar un override, por insumo. Es evidencia: la reserva real se recalcula al iniciar la Ejecución.';
comment on column rma.override_insumo.override_id is 'Override al que pertenece (referencia a override_recursos).';
comment on column rma.override_insumo.insumo_id is 'Insumo afectado (referencia a insumo).';
comment on column rma.override_insumo.requerido is 'Cantidad que prevé el tipo de reparación, en la unidad del insumo.';
comment on column rma.override_insumo.disponible is 'Disponible del insumo al autorizar: físico menos reservado de todas las Órdenes.';
comment on column rma.override_insumo.a_reservar is 'Lo que se reservaría: el menor entre requerido y disponible.';
comment on column rma.override_insumo.faltante is 'Lo que no se reservaría ni se descontaría nunca: requerido menos a reservar.';
