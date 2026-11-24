-- Rosario Tecno RMA — Requisitos de insumo por tipo y pieza elegida de cada
-- trabajo (ajustes funcionales, iteración 2, bloque 8, parte B; DEC-AJ-14
-- D-14.4, BR-REP-049, BR-REP-002/005/006 sin cambios de texto, BR-REP-039).
--
-- Secuencia aprobada: tipo definido → modelo conocido → insumos necesarios →
-- piezas concretas compatibles elegidas → disponibilidad → reserva →
-- ejecución. El motor de reservas, movimientos y consumo no cambia: la pieza
-- elegida se reserva, se libera y se consume con los mismos movimientos del
-- libro (`movimiento_inventario`) y el mismo trigger de saldos.
--
-- Aditiva:
--   * `tipo_reparacion_requisito`: cada tipo puede declarar requisitos (una
--     categoría o subcategoría de insumos y una cantidad), junto a los
--     insumos previstos concretos de `tipo_reparacion_insumo`, que se
--     conservan y siguen igual. Uno por categoría; no se borran: un
--     requisito retirado queda inactivo (las elecciones lo referencian).
--     Cada cambio se audita en `cambio_configuracion` (entidad
--     TIPO_REPARACION, campos «insumos_previstos» y «requisitos»);
--   * `tipo_reparacion_insumo`: `rma_backend` puede cambiar la cantidad y
--     quitar un insumo previsto desde Configuración (el conjunto vigente; su
--     historia está en la auditoría);
--   * `detalle_pieza`: la pieza concreta elegida para cada requisito de un
--     Detalle, append-only e inmutable. Elegir, sustituir o anular agrega un
--     registro que reemplaza al último del mismo requisito (cadena lineal);
--     la vigente es la última. Guarda la copia de la categoría y la cantidad
--     del requisito, el modelo del equipo, la causa (AUTOMATICA, ELECCION,
--     SUSTITUCION, CAMBIO_MODELO o REDEFINICION), el motivo y quién y cuándo;
--   * historial: la acción transversal ACC-REP-084 (elegir, sustituir o
--     revisar la pieza de un trabajo) es EV-REP-010 «Detalle definido»; la
--     sustitución de una pieza ya reservada, EV-REP-024 «Movimientos de
--     inventario generados».
--
-- Ningún dato existente cambia: ningún tipo queda con requisitos y ningún
-- Detalle con piezas, así que todo funciona como antes.

-- ---------------------------------------------------------------------------
-- Requisitos de insumo de cada tipo (precisión 6 a)
-- ---------------------------------------------------------------------------
create table if not exists rma.tipo_reparacion_requisito (
  id uuid primary key default gen_random_uuid(),
  tipo_reparacion_id uuid not null references rma.tipo_reparacion (id),
  categoria_id uuid not null references rma.categoria_insumo (id),
  cantidad numeric(12, 3) not null check (cantidad > 0),
  posicion integer not null default 1 check (posicion >= 1),
  activo boolean not null default true,
  creado_en timestamptz not null default now(),
  modificado_en timestamptz not null default now(),
  constraint tipo_reparacion_requisito_categoria_unica unique (tipo_reparacion_id, categoria_id),
  constraint tipo_reparacion_requisito_de_tipo unique (id, tipo_reparacion_id)
);

create index if not exists tipo_reparacion_requisito_categoria
  on rma.tipo_reparacion_requisito (categoria_id);

create or replace function rma.tipo_reparacion_requisito_fijo()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
begin
  if new.tipo_reparacion_id is distinct from old.tipo_reparacion_id
     or new.categoria_id is distinct from old.categoria_id then
    raise exception 'Un requisito no cambia de tipo ni de categoría: se retira y se agrega otro.'
      using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.tipo_reparacion_requisito_fijo() is
  'El tipo y la categoría de un requisito no cambian (DEC-AJ-14): las piezas elegidas lo referencian con esa copia.';

drop trigger if exists tipo_reparacion_requisito_fijo on rma.tipo_reparacion_requisito;
create trigger tipo_reparacion_requisito_fijo before update on rma.tipo_reparacion_requisito
  for each row execute function rma.tipo_reparacion_requisito_fijo();
drop trigger if exists tipo_reparacion_requisito_modificacion on rma.tipo_reparacion_requisito;
create trigger tipo_reparacion_requisito_modificacion before update on rma.tipo_reparacion_requisito
  for each row execute function rma.marcar_modificacion();
drop trigger if exists tipo_reparacion_requisito_sin_borrado on rma.tipo_reparacion_requisito;
create trigger tipo_reparacion_requisito_sin_borrado before delete on rma.tipo_reparacion_requisito
  for each row execute function rma.impedir_borrado();

comment on table rma.tipo_reparacion_requisito is
  'Requisitos de insumo de un Tipo de Reparación (DEC-AJ-14, D-14.4): una categoría o subcategoría de insumos y la cantidad que necesita cada trabajo («1 Batería»). La pieza concreta, compatible con el modelo del equipo, se elige en cada Detalle antes de reservar (detalle_pieza). Convive con los insumos previstos concretos (tipo_reparacion_insumo). Uno por categoría; no se borra: un requisito retirado queda inactivo. Cada cambio se audita en cambio_configuracion (entidad TIPO_REPARACION, campo requisitos).';
comment on column rma.tipo_reparacion_requisito.id is 'Identificador estable del requisito: las piezas elegidas lo referencian.';
comment on column rma.tipo_reparacion_requisito.tipo_reparacion_id is 'Tipo de Reparación (referencia a tipo_reparacion). No cambia.';
comment on column rma.tipo_reparacion_requisito.categoria_id is 'Categoría o subcategoría de insumos requerida (referencia a categoria_insumo); una categoría incluye sus subcategorías. No cambia.';
comment on column rma.tipo_reparacion_requisito.cantidad is 'Cantidad que necesita cada trabajo del tipo, en la unidad del insumo.';
comment on column rma.tipo_reparacion_requisito.posicion is 'Orden en que se muestra entre los requisitos del tipo.';
comment on column rma.tipo_reparacion_requisito.activo is 'Falso: el tipo ya no lo pide. Los trabajos que ya eligieron su pieza la conservan.';
comment on column rma.tipo_reparacion_requisito.creado_en is 'Fecha y hora del alta del requisito.';
comment on column rma.tipo_reparacion_requisito.modificado_en is 'Fecha y hora del último cambio.';

grant select, insert on rma.tipo_reparacion_requisito to rma_backend;
grant update (cantidad, posicion, activo) on rma.tipo_reparacion_requisito to rma_backend;

-- Insumos previstos concretos: editables desde Configuración (conjunto
-- vigente; la historia está en cambio_configuracion).
grant update (cantidad) on rma.tipo_reparacion_insumo to rma_backend;
grant delete on rma.tipo_reparacion_insumo to rma_backend;

comment on table rma.tipo_reparacion_insumo is
  'Insumos concretos (universales) y cantidades que reserva cada tipo de reparación al iniciar un Detalle, junto a la pieza elegida de cada requisito (tipo_reparacion_requisito). La reparación «Otros» no tiene insumos previstos. Se editan desde Configuración (DEC-AJ-14) con auditoría en cambio_configuracion (campo insumos_previstos).';

-- ---------------------------------------------------------------------------
-- Pieza elegida de cada requisito de un Detalle (precisión 6 b a d)
-- ---------------------------------------------------------------------------
create table if not exists rma.detalle_pieza (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique check (btrim(codigo) <> ''),
  detalle_id uuid not null references rma.detalle (id),
  posicion integer not null check (posicion >= 1),
  requisito_id uuid not null,
  tipo_reparacion_id uuid not null references rma.tipo_reparacion (id),
  categoria_id uuid not null references rma.categoria_insumo (id),
  cantidad numeric(12, 3) not null check (cantidad > 0),
  insumo_id uuid references rma.insumo (id),
  causa text not null check (causa in (
    'AUTOMATICA', 'ELECCION', 'SUSTITUCION', 'CAMBIO_MODELO', 'REDEFINICION'
  )),
  compatibilidad_no_verificada boolean not null default false,
  modelo_equipo_id uuid references rma.modelo_equipo (id),
  motivo text check (motivo is null or btrim(motivo) <> ''),
  elegida_por uuid not null references rma.usuario (id),
  elegida_en timestamptz not null,
  reemplaza_a uuid,
  constraint detalle_pieza_posicion unique (detalle_id, posicion),
  constraint detalle_pieza_de_detalle unique (id, detalle_id),
  -- El requisito es del tipo copiado (el del Detalle al elegir).
  constraint detalle_pieza_requisito foreign key (requisito_id, tipo_reparacion_id)
    references rma.tipo_reparacion_requisito (id, tipo_reparacion_id),
  -- Reemplaza a un registro del mismo Detalle, y a lo sumo una vez.
  constraint detalle_pieza_reemplazo foreign key (reemplaza_a, detalle_id)
    references rma.detalle_pieza (id, detalle_id),
  constraint detalle_pieza_reemplazo_unico unique (reemplaza_a),
  -- Sin pieza solo una anulación por cambio de modelo o redefinición.
  constraint detalle_pieza_anulacion check (
    insumo_id is not null or causa in ('CAMBIO_MODELO', 'REDEFINICION')
  ),
  -- Sustituir exige motivo y reemplaza a la elección anterior.
  constraint detalle_pieza_sustitucion check (
    causa <> 'SUSTITUCION' or (motivo is not null and reemplaza_a is not null)
  ),
  -- Una pieza sin compatibilidad verificada exige motivo (punto 2 de la
  -- resolución de 11.1).
  constraint detalle_pieza_no_verificada check (
    not compatibilidad_no_verificada or (motivo is not null and insumo_id is not null)
  )
);

create index if not exists detalle_pieza_requisito on rma.detalle_pieza (requisito_id);
create index if not exists detalle_pieza_insumo on rma.detalle_pieza (insumo_id) where insumo_id is not null;

create or replace function rma.validar_detalle_pieza()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_ultimo uuid;
  v_categoria uuid;
begin
  -- La copia de la categoría es la del requisito.
  select categoria_id into v_categoria from rma.tipo_reparacion_requisito where id = new.requisito_id;
  if v_categoria is distinct from new.categoria_id then
    raise exception 'La categoría de la pieza elegida no es la del requisito.'
      using errcode = 'check_violation';
  end if;
  -- Cadena lineal por requisito: cada registro reemplaza al último del
  -- mismo requisito en el Detalle (el primero no reemplaza a ninguno).
  select id into v_ultimo
    from rma.detalle_pieza
   where detalle_id = new.detalle_id and requisito_id = new.requisito_id
   order by posicion desc
   limit 1;
  if new.reemplaza_a is distinct from v_ultimo then
    raise exception 'La elección de pieza % tiene que reemplazar a la última del mismo requisito.', new.codigo
      using errcode = 'check_violation';
  end if;
  -- Solo se elige una pieza vigente.
  if new.insumo_id is not null and not exists (
    select 1 from rma.insumo where id = new.insumo_id and activo
  ) then
    raise exception 'El insumo elegido está dado de baja: no se elige como pieza.'
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.validar_detalle_pieza() is
  'Una pieza elegida (DEC-AJ-14) copia la categoría de su requisito, reemplaza a la última elección del mismo requisito en el Detalle (cadena lineal) y, si tiene pieza, es un insumo vigente.';

drop trigger if exists detalle_pieza_validar on rma.detalle_pieza;
create trigger detalle_pieza_validar before insert on rma.detalle_pieza
  for each row execute function rma.validar_detalle_pieza();
drop trigger if exists detalle_pieza_inmutable on rma.detalle_pieza;
create trigger detalle_pieza_inmutable before update or delete on rma.detalle_pieza
  for each row execute function rma.impedir_modificacion();

comment on table rma.detalle_pieza is
  'Pieza concreta (un insumo, SKU real) elegida para cada requisito del tipo de un Detalle (DEC-AJ-14, D-14.4), antes de reservar. Append-only e inmutable: elegir, sustituir o anular agrega un registro que reemplaza al último del mismo requisito; la vigente es la última, y sin insumo el requisito vuelve a estar pendiente de elegir. La reserva, la liberación y el consumo de la pieza son movimientos del libro (movimiento_inventario) del mismo Detalle.';
comment on column rma.detalle_pieza.id is 'Identificador interno del registro.';
comment on column rma.detalle_pieza.codigo is 'Identificador público del registro (PZA-…), el que usa la API.';
comment on column rma.detalle_pieza.detalle_id is 'Detalle (referencia a detalle).';
comment on column rma.detalle_pieza.posicion is 'Orden del registro entre las elecciones del Detalle.';
comment on column rma.detalle_pieza.requisito_id is 'Requisito del tipo al que corresponde (referencia a tipo_reparacion_requisito).';
comment on column rma.detalle_pieza.tipo_reparacion_id is 'Tipo del Detalle al elegir (el del requisito). Una elección de otro tipo (trabajo redefinido) no se reserva.';
comment on column rma.detalle_pieza.categoria_id is 'Copia de la categoría del requisito.';
comment on column rma.detalle_pieza.cantidad is 'Copia de la cantidad del requisito al elegir: el Detalle trabaja con ella aunque el tipo cambie después.';
comment on column rma.detalle_pieza.insumo_id is 'Pieza elegida (referencia a insumo). Vacía: elección anulada por un cambio de modelo o una redefinición; el requisito vuelve a estar pendiente.';
comment on column rma.detalle_pieza.causa is 'AUTOMATICA (una sola pieza compatible y activa), ELECCION (primera elección de una persona), SUSTITUCION (cambio con motivo; con la pieza reservada, la liberación y la reserva nueva van en la misma operación), CAMBIO_MODELO (la pieza dejó de ser compatible con el modelo del equipo) o REDEFINICION (el trabajo pasó a otro tipo).';
comment on column rma.detalle_pieza.compatibilidad_no_verificada is 'Verdadero si el equipo no tenía modelo técnico y no había piezas universales: se eligió otra pieza de la categoría con motivo.';
comment on column rma.detalle_pieza.modelo_equipo_id is 'Modelo técnico del equipo al elegir (referencia a modelo_equipo); vacío si no tenía.';
comment on column rma.detalle_pieza.motivo is 'Motivo de la sustitución o de la pieza sin compatibilidad verificada; opcional en una primera elección.';
comment on column rma.detalle_pieza.elegida_por is 'Usuario que eligió, sustituyó o hizo el cambio que la revisó (referencia a usuario).';
comment on column rma.detalle_pieza.elegida_en is 'Fecha y hora del registro.';
comment on column rma.detalle_pieza.reemplaza_a is 'Registro anterior del mismo requisito que este reemplaza (referencia a detalle_pieza).';

grant select, insert on rma.detalle_pieza to rma_backend;

-- ---------------------------------------------------------------------------
-- Historial: elegir, sustituir o revisar la pieza de un trabajo
-- ---------------------------------------------------------------------------
insert into rma.equivalencia_historial (tipo_referencia, referencia_id, accion, tipo_evento_id)
select v.tipo_referencia, v.referencia_id, v.accion, t.id
from (values
  ('FUNCTIONAL_ACTION', 'ACC-REP-084', null, 'EV-REP-010'),
  ('FUNCTIONAL_ACTION', 'ACC-REP-084', 'SUSTITUIR_PIEZA_RESERVADA', 'EV-REP-024')
) as v (tipo_referencia, referencia_id, accion, codigo)
join rma.tipo_evento t on t.codigo = v.codigo
on conflict do nothing;
