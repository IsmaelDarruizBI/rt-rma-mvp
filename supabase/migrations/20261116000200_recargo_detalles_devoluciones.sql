-- Cierre de la iteración de UX de Recepción (16/11/2026): DEC-UX-13
-- (ABI-45, recargo incorporado a los Detalles), DEC-UX-14 (ABI-44, el
-- recargo se devuelve en proporción) y la marca explícita del texto único
-- de observaciones (DEC-UX-03).
--
-- Aditiva: columnas con valor por defecto; ningún pago, devolución ni
-- recepción existente cambia de significado.

-- ---------------------------------------------------------------------------
-- Pago: cómo se repartió su recargo entre los Detalles (copia histórica)
-- ---------------------------------------------------------------------------
alter table rma.pago
  add column recargo_distribucion jsonb not null default '[]'::jsonb;
alter table rma.pago
  add constraint pago_recargo_distribucion_lista
  check (jsonb_typeof(recargo_distribucion) = 'array');

comment on column rma.pago.recargo_distribucion is
  'Reparto del recargo de este pago entre los Detalles elegibles al cobrarlo, en proporción a sus importes: [{"detalle_id", "importe"}] (DEC-UX-13). Vacío sin recargo, en los pagos anteriores o si todavía no había Detalles.';

-- El reparto es inmutable como el resto del pago: solo se completa la anulación.
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
            new.usuario_id, new.registrado_en, new.codigo,
            new.recargo_porcentaje, new.recargo_importe, new.recargo_distribucion)
        is distinct from
        row(old.orden_id, old.monto, old.tipo_pago, old.medio_pago_id, old.referencia,
            old.usuario_id, old.registrado_en, old.codigo,
            old.recargo_porcentaje, old.recargo_importe, old.recargo_distribucion) then
    raise exception 'Un pago solo admite registrar su anulación, una única vez.' using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

-- ---------------------------------------------------------------------------
-- Devolución: el recargo que se reintegra con el importe
-- ---------------------------------------------------------------------------
alter table rma.devolucion_dinero
  add column recargo_importe numeric(14, 2) not null default 0;
alter table rma.devolucion_dinero
  add constraint devolucion_recargo_no_negativo check (recargo_importe >= 0);

comment on column rma.devolucion_dinero.recargo_importe is
  'Parte del recargo del pago que se reintegra con el importe, en proporción a lo devuelto (DEC-UX-14). El importe (monto) es lo que se imputa al saldo; el cliente recibe monto + recargo_importe.';

-- Ni el importe ni el recargo devueltos superan lo cobrado en el pago.
create or replace function rma.devolucion_dinero_validar()
returns trigger
language plpgsql
set search_path = rma, pg_temp
as $$
declare
  v_pago rma.pago%rowtype;
  v_devuelto numeric(14, 2);
  v_recargo_devuelto numeric(14, 2);
begin
  select * into v_pago from rma.pago where id = new.pago_id for no key update;
  if v_pago.anulado_en is not null then
    raise exception 'No se devuelve dinero desde un pago anulado.' using errcode = 'check_violation';
  end if;
  select coalesce(sum(monto), 0), coalesce(sum(recargo_importe), 0)
    into v_devuelto, v_recargo_devuelto
    from rma.devolucion_dinero where pago_id = new.pago_id;
  if v_devuelto + new.monto > v_pago.monto then
    raise exception 'La devolución supera lo cobrado en el pago % menos lo ya devuelto.', v_pago.codigo
      using errcode = 'check_violation';
  end if;
  if v_recargo_devuelto + new.recargo_importe > v_pago.recargo_importe then
    raise exception 'El recargo devuelto supera el recargo cobrado en el pago % menos lo ya devuelto.', v_pago.codigo
      using errcode = 'check_violation';
  end if;
  return new;
end;
$$;

comment on function rma.devolucion_dinero_validar() is
  'Impide devolver dinero desde un pago anulado o por encima de lo cobrado en ese pago, en importe y en recargo. Bloquea el pago con FOR NO KEY UPDATE, para no chocar con las claves foráneas. El límite del saldo a favor lo verifica FastAPI con la Orden bloqueada.';

-- ---------------------------------------------------------------------------
-- Recepción: el texto único de observaciones (DEC-UX-03)
-- ---------------------------------------------------------------------------
alter table rma.recepcion
  add column observaciones_unificadas boolean not null default false;

comment on column rma.recepcion.observaciones_unificadas is
  'observaciones es el texto único «Observaciones del equipo» (lo que declara el cliente, el problema, el estado estético y otras observaciones); no se copia al estado físico (DEC-UX-03). false en lo registrado antes.';
