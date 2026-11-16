-- UX-08: recargo porcentual por medio de pago (iteración de UX de Recepción).
--
-- Aditiva: columnas con valor por defecto cero; ningún pago anterior se
-- recalcula. El importe del pago (monto) sigue siendo lo imputado al saldo de
-- la Orden; el recargo se cobra aparte y queda como copia en cada pago.

-- Medio de pago: porcentaje configurable por Administración.
alter table rma.medio_pago
  add column recargo_porcentaje numeric(5, 2) not null default 0;
alter table rma.medio_pago
  add constraint medio_pago_recargo_rango
  check (recargo_porcentaje >= 0 and recargo_porcentaje <= 100);

comment on column rma.medio_pago.recargo_porcentaje is
  'Recargo porcentual que se suma a cada cobro con este medio (0: sin recargo). Lo configura Administración; cambiarlo no altera pagos ya registrados.';

-- Configuración inicial aprobada: Transferencia 2 %.
update rma.medio_pago set recargo_porcentaje = 2 where codigo = 'TRANSFERENCIA';

-- Pago: copia histórica del recargo aplicado.
alter table rma.pago
  add column recargo_porcentaje numeric(5, 2) not null default 0,
  add column recargo_importe numeric(14, 2) not null default 0;
alter table rma.pago
  add constraint pago_recargo_rango
  check (recargo_porcentaje >= 0 and recargo_porcentaje <= 100 and recargo_importe >= 0);

comment on column rma.pago.recargo_porcentaje is
  'Copia del recargo del medio de pago al cobrar (0 en pagos anteriores a UX-08).';
comment on column rma.pago.recargo_importe is
  'Importe del recargo cobrado aparte del monto; no se imputa al saldo. Total pagado por el cliente: monto + recargo_importe.';

-- El recargo es inmutable como el resto del pago: solo se completa la anulación.
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
            new.recargo_porcentaje, new.recargo_importe)
        is distinct from
        row(old.orden_id, old.monto, old.tipo_pago, old.medio_pago_id, old.referencia,
            old.usuario_id, old.registrado_en, old.codigo,
            old.recargo_porcentaje, old.recargo_importe) then
    raise exception 'Un pago solo admite registrar su anulación, una única vez.' using errcode = 'restrict_violation';
  end if;
  return new;
end;
$$;

-- Auditoría de configuración: el cambio de recargo de un medio de pago.
alter table rma.cambio_configuracion drop constraint if exists cambio_configuracion_entidad_check;
alter table rma.cambio_configuracion add constraint cambio_configuracion_entidad_check
  check (entidad in (
    'TIPO_REPARACION', 'MESA_TRABAJO', 'USUARIO', 'PERMISO', 'INSUMO',
    'MOTIVO', 'PLANTILLA', 'PARAMETRO', 'CHECKLIST', 'PROVEEDOR', 'MEDIO_PAGO'
  ));
