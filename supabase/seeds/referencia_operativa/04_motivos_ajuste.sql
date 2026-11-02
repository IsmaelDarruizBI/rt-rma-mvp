-- Rosario Tecno RMA — Motivos de ajuste de stock
-- Generado por supabase/scripts/generar_datos_iniciales.cjs desde la lista aprobada por el responsable de producto el 02/11/2026.
-- No editar a mano: regenerar.

-- Aprobados el 02/11/2026: RECUENTO y ERROR_CARGA para ajustes positivos y negativos; DANIO y PERDIDA solo negativos.
insert into rma.motivo_ajuste (codigo, descripcion, aplica_a) values
  ('RECUENTO', 'Diferencia de recuento físico', 'AMBOS'),
  ('ERROR_CARGA', 'Corrección de un error de carga', 'AMBOS'),
  ('DANIO', 'Insumo dañado en el depósito', 'NEGATIVO'),
  ('PERDIDA', 'Insumo perdido o faltante', 'NEGATIVO')
on conflict (codigo) do nothing;
