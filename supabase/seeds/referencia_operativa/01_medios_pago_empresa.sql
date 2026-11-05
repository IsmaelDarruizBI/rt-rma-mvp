-- Rosario Tecno RMA — Medios de pago y datos de la empresa
-- Generado por supabase/scripts/generar_datos_iniciales.cjs desde app/backend/app/domain/models/catalogos.py (valores predeterminados del MVP).
-- No editar a mano: regenerar.

insert into rma.medio_pago (codigo, nombre, orden) values
  ('EFECTIVO', 'Efectivo', 1),
  ('TRANSFERENCIA', 'Transferencia', 2),
  ('TARJETA_DEBITO', 'Tarjeta de debito', 3),
  ('TARJETA_CREDITO', 'Tarjeta de credito', 4),
  ('OTRO', 'Otro', 5)
on conflict (codigo) do update set orden = excluded.orden
  where rma.medio_pago.orden is distinct from excluded.orden;

insert into rma.empresa (nombre) values ('Rosario Tecno')
on conflict (id) do nothing;
