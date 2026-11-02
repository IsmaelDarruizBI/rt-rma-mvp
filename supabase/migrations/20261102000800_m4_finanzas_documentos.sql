-- Rosario Tecno RMA — Esquema físico PostgreSQL
-- 0800. M4 Administración, finanzas y contabilidad.
--
-- RMA administra solo los aspectos económicos de sus reparaciones; no hay
-- contabilidad general. Pagos, devoluciones y documentos son inmutables y
-- tienen identificadores estables, para que un futuro módulo contable
-- independiente pueda consumirlos. Total, saldo y estado de cobro se calculan
-- (vista v_orden_saldo, migración 1000); no se guardan.

-- ---------------------------------------------------------------------------
-- pago
-- ---------------------------------------------------------------------------
create table rma.pago (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  orden_id uuid not null references rma.orden (id),
  monto numeric(14, 2) not null check (monto > 0),
  tipo_pago text not null check (tipo_pago in ('ANTICIPO', 'PARCIAL', 'FINAL', 'PAGO')),
  medio_pago_id uuid not null references rma.medio_pago (id),
  referencia text,
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now(),
  anulado_por uuid references rma.usuario (id),
  anulado_en timestamptz,
  anulacion_motivo text,
  unique (id, orden_id),
  constraint pago_anulacion_completa check (
    (anulado_en is null and anulado_por is null and anulacion_motivo is null)
    or (anulado_en is not null and anulado_por is not null and anulacion_motivo is not null)
  )
);

create index pago_orden on rma.pago (orden_id, registrado_en);

create or replace function rma.pago_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_origen text;
begin
  if tg_op = 'DELETE' then
    raise exception 'Un pago nunca se borra: se anula.' using errcode = 'restrict_violation';
  end if;
  if tg_op = 'INSERT' then
    select origen into v_origen from rma.orden where id = new.orden_id;
    if v_origen <> 'CLIENTE_EXTERNO' then
      raise exception 'Una Orden % no se cobra al cliente.', v_origen using errcode = 'check_violation';
    end if;
    return new;
  end if;
  -- UPDATE: solo se completa la anulación, una vez.
  if old.anulado_en is not null
     or new.anulado_en is null
     or row(new.orden_id, new.monto, new.tipo_pago, new.medio_pago_id, new.referencia,
            new.usuario_id, new.registrado_en, new.codigo)
        is distinct from
        row(old.orden_id, old.monto, old.tipo_pago, old.medio_pago_id, old.referencia,
            old.usuario_id, old.registrado_en, old.codigo) then
    raise exception 'Un pago solo admite registrar su anulación, una única vez.' using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

comment on function rma.pago_validar() is
  'Rechaza pagos en Órdenes no cobrables, impide borrarlos y solo permite completar la anulación una única vez.';

create trigger pago_validar before insert or update or delete on rma.pago
  for each row execute function rma.pago_validar();
create trigger pago_orden_abierta before insert on rma.pago
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.pago is
  'Dinero recibido del cliente en una Orden cobrable (cliente externo). Nunca se borra ni cambia su importe; una corrección administrativa es su anulación.';
comment on column rma.pago.id is 'Identificador interno del pago.';
comment on column rma.pago.codigo is 'Identificador público del pago, el que hoy usa la API.';
comment on column rma.pago.orden_id is 'Orden cobrada (referencia a orden).';
comment on column rma.pago.monto is 'Importe recibido en pesos, siempre positivo.';
comment on column rma.pago.tipo_pago is 'Momento del cobro, asignado por el sistema: ANTICIPO (antes del resultado), PARCIAL o FINAL (en el cierre); PAGO solo en registros anteriores.';
comment on column rma.pago.medio_pago_id is 'Medio con que se cobró (referencia a medio_pago).';
comment on column rma.pago.referencia is 'Dato de la operación: número de transferencia, cupón u observación.';
comment on column rma.pago.usuario_id is 'Usuario que registró el cobro (referencia a usuario).';
comment on column rma.pago.registrado_en is 'Fecha y hora del cobro.';
comment on column rma.pago.anulado_por is 'Usuario de Administración que anuló el pago (referencia a usuario).';
comment on column rma.pago.anulado_en is 'Fecha y hora de la anulación; un pago anulado no cuenta como pagado.';
comment on column rma.pago.anulacion_motivo is 'Motivo de la anulación.';

-- ---------------------------------------------------------------------------
-- devolucion_dinero
-- ---------------------------------------------------------------------------
create table rma.devolucion_dinero (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  orden_id uuid not null,
  pago_id uuid not null,
  monto numeric(14, 2) not null check (monto > 0),
  medio_pago_id uuid not null references rma.medio_pago (id),
  motivo text not null check (btrim(motivo) <> ''),
  referencia text,
  usuario_id uuid not null references rma.usuario (id),
  registrada_en timestamptz not null default now(),
  constraint devolucion_pago foreign key (pago_id, orden_id) references rma.pago (id, orden_id)
);

create index devolucion_dinero_orden on rma.devolucion_dinero (orden_id, registrada_en);
create index devolucion_dinero_pago on rma.devolucion_dinero (pago_id);

create or replace function rma.devolucion_dinero_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_pago rma.pago%rowtype;
  v_devuelto numeric(14, 2);
begin
  select * into v_pago from rma.pago where id = new.pago_id for update;
  if v_pago.anulado_en is not null then
    raise exception 'No se devuelve dinero desde un pago anulado.' using errcode = 'check_violation';
  end if;
  select coalesce(sum(monto), 0) into v_devuelto from rma.devolucion_dinero where pago_id = new.pago_id;
  if v_devuelto + new.monto > v_pago.monto then
    raise exception 'La devolución supera lo cobrado en el pago % menos lo ya devuelto.', v_pago.codigo
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.devolucion_dinero_validar() is
  'Impide devolver dinero desde un pago anulado o por encima de lo cobrado en ese pago. El límite del saldo a favor lo verifica FastAPI con la Orden bloqueada.';

create trigger devolucion_dinero_validar before insert on rma.devolucion_dinero
  for each row execute function rma.devolucion_dinero_validar();
create trigger devolucion_dinero_orden_abierta before insert on rma.devolucion_dinero
  for each row execute function rma.exigir_orden_abierta();
create trigger devolucion_dinero_inmutable before update or delete on rma.devolucion_dinero
  for each row execute function rma.impedir_modificacion();

comment on table rma.devolucion_dinero is
  'Dinero devuelto al cliente desde un pago, por ejemplo un saldo a favor tras cancelar trabajos (BR-REP-038). No es un pago negativo.';
comment on column rma.devolucion_dinero.id is 'Identificador interno de la devolución.';
comment on column rma.devolucion_dinero.codigo is 'Identificador público de la devolución, el que hoy usa la API.';
comment on column rma.devolucion_dinero.orden_id is 'Orden de la devolución (referencia a orden).';
comment on column rma.devolucion_dinero.pago_id is 'Pago desde el que se devuelve, de la misma Orden (referencia a pago).';
comment on column rma.devolucion_dinero.monto is 'Importe devuelto en pesos, siempre positivo.';
comment on column rma.devolucion_dinero.medio_pago_id is 'Medio con que se devolvió (referencia a medio_pago).';
comment on column rma.devolucion_dinero.motivo is 'Motivo de la devolución.';
comment on column rma.devolucion_dinero.referencia is 'Dato de la operación de devolución.';
comment on column rma.devolucion_dinero.usuario_id is 'Usuario que registró la devolución (referencia a usuario).';
comment on column rma.devolucion_dinero.registrada_en is 'Fecha y hora de la devolución.';

-- ---------------------------------------------------------------------------
-- descuento
-- ---------------------------------------------------------------------------
create table rma.descuento (
  id uuid primary key default gen_random_uuid(),
  orden_id uuid not null references rma.orden (id),
  tipo text check (tipo in ('PORCENTAJE', 'IMPORTE')),
  valor numeric(14, 2) check (valor > 0),
  motivo text not null check (btrim(motivo) <> ''),
  usuario_id uuid not null references rma.usuario (id),
  registrado_en timestamptz not null default now(),
  constraint descuento_tipo_y_valor check ((tipo is null) = (valor is null)),
  constraint descuento_porcentaje_maximo check (tipo is distinct from 'PORCENTAJE' or valor <= 100)
);

create index descuento_orden on rma.descuento (orden_id, registrado_en);

create trigger descuento_inmutable before update or delete on rma.descuento
  for each row execute function rma.impedir_modificacion();
create trigger descuento_orden_abierta before insert on rma.descuento
  for each row execute function rma.exigir_orden_abierta();

comment on table rma.descuento is
  'Cada cambio del descuento comercial de una Orden: aplicarlo, cambiarlo o quitarlo. El vigente es el último, salvo que lo quite. No cambia precios ni deja el total por debajo de lo cobrado.';
comment on column rma.descuento.id is 'Identificador interno del registro.';
comment on column rma.descuento.orden_id is 'Orden descontada (referencia a orden).';
comment on column rma.descuento.tipo is 'PORCENTAJE o IMPORTE; vacío cuando el registro quita el descuento.';
comment on column rma.descuento.valor is 'Porcentaje de 0 a 100 o importe en pesos, según el tipo; vacío cuando se quita.';
comment on column rma.descuento.motivo is 'Motivo del cambio.';
comment on column rma.descuento.usuario_id is 'Usuario que registró el cambio (referencia a usuario).';
comment on column rma.descuento.registrado_en is 'Fecha y hora del cambio.';

-- ---------------------------------------------------------------------------
-- documento_emitido
-- ---------------------------------------------------------------------------
create table rma.documento_emitido (
  id uuid primary key default gen_random_uuid(),
  codigo text not null unique,
  orden_id uuid not null references rma.orden (id),
  tipo text not null check (tipo in (
    'COMPROBANTE_INGRESO', 'COMPROBANTE_RECEPCION', 'COMPROBANTE_AUTORIZACION',
    'COMPROBANTE_ENTREGA', 'GARANTIA'
  )),
  version integer not null check (version >= 1),
  emitido_en timestamptz not null default now(),
  usuario_id uuid references rma.usuario (id),
  motivo text,
  reemplaza_a uuid,
  contenido jsonb not null check (jsonb_typeof(contenido) = 'object'),
  texto_legal_id uuid references rma.texto_legal (id),
  plantilla_version text not null check (btrim(plantilla_version) <> ''),
  archivo_clave text,
  archivo_sha256 text check (archivo_sha256 ~ '^[0-9a-f]{64}$'),
  unique (orden_id, tipo, version),
  unique (id, orden_id, tipo),
  constraint documento_reemplazo foreign key (reemplaza_a, orden_id, tipo)
    references rma.documento_emitido (id, orden_id, tipo),
  constraint documento_version_y_reemplazo check (
    (version = 1 and reemplaza_a is null)
    or (version > 1 and reemplaza_a is not null and motivo is not null)
  ),
  constraint documento_archivo_completo check ((archivo_clave is null) = (archivo_sha256 is null))
);

create index documento_emitido_orden on rma.documento_emitido (orden_id, tipo, version);

create trigger documento_emitido_inmutable before update or delete on rma.documento_emitido
  for each row execute function rma.impedir_modificacion();

comment on table rma.documento_emitido is
  'Cada versión de un comprobante entregado al cliente. Conserva el contenido, la versión del texto legal y la versión de la plantilla vigentes al emitirlo. La reproducción visual exacta requiere conservar esa plantilla o guardar el PDF original (archivo_clave).';
comment on column rma.documento_emitido.id is 'Identificador interno del documento.';
comment on column rma.documento_emitido.codigo is 'Identificador público del documento, el que hoy usa la API para descargarlo o imprimirlo.';
comment on column rma.documento_emitido.orden_id is 'Orden que emite el documento (referencia a orden).';
comment on column rma.documento_emitido.tipo is 'COMPROBANTE_INGRESO (ING), COMPROBANTE_RECEPCION, COMPROBANTE_AUTORIZACION (AUT), COMPROBANTE_ENTREGA o GARANTIA.';
comment on column rma.documento_emitido.version is 'Número de emisión de ese tipo en la Orden, desde 1; una versión nueva corrige la anterior sin borrarla.';
comment on column rma.documento_emitido.emitido_en is 'Fecha y hora de emisión.';
comment on column rma.documento_emitido.usuario_id is 'Usuario que ejecutó la acción que emitió el documento (referencia a usuario).';
comment on column rma.documento_emitido.motivo is 'Motivo de una versión nueva; obligatorio desde la versión 2.';
comment on column rma.documento_emitido.reemplaza_a is 'Versión anterior del mismo tipo y Orden que esta reemplaza (referencia a documento_emitido).';
comment on column rma.documento_emitido.contenido is 'Copia completa de los datos con que se emitió el documento: empresa, cliente, equipo, trabajos, importes y leyendas tal como estaban en ese momento.';
comment on column rma.documento_emitido.texto_legal_id is 'Versión del texto legal impresa con el documento, como los Términos y Condiciones de la entrega (referencia a texto_legal); vacía si el documento no lleva texto legal.';
comment on column rma.documento_emitido.plantilla_version is 'Versión de la plantilla de presentación usada al emitir; para reproducir el aspecto exacto hay que conservar esa plantilla.';
comment on column rma.documento_emitido.archivo_clave is 'Clave del PDF original guardado en el almacenamiento de objetos; prevista, vacía mientras no se archiven los PDF.';
comment on column rma.documento_emitido.archivo_sha256 is 'Huella SHA-256 del PDF original, en hexadecimal; vacía si no hay archivo.';
