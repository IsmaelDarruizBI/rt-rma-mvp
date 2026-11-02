-- Rosario Tecno RMA — Medios de pago y datos de la empresa
-- Generado por supabase/scripts/generar_datos_iniciales.cjs desde app/backend/app/domain/models/catalogos.py (valores predeterminados del MVP).
-- No editar a mano: regenerar.

insert into rma.medio_pago (codigo, nombre) values
  ('EFECTIVO', 'Efectivo'),
  ('TRANSFERENCIA', 'Transferencia'),
  ('TARJETA_DEBITO', 'Tarjeta de debito'),
  ('TARJETA_CREDITO', 'Tarjeta de credito'),
  ('OTRO', 'Otro')
on conflict (codigo) do nothing;

insert into rma.empresa (nombre) values ('Rosario Tecno')
on conflict (id) do nothing;
