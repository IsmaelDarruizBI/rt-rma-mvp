-- Rosario Tecno RMA — Stock mínimo por insumo
-- (ajustes funcionales, iteración 2, bloque 6; DEC-AJ-11, BR-REP-049).
--
-- Aditiva y compatible con los registros existentes:
--   * `insumo.stock_minimo`: opcional y mayor o igual a cero. Vacío significa
--     «sin mínimo»: los insumos existentes siguen igual, sin alertas. Lo edita
--     el backend desde Configuración → Insumos (permiso «Gestionar insumos»),
--     auditado en `cambio_configuracion` con la entidad INSUMO, que ya está en
--     su CHECK. No interviene en el libro de inventario: los saldos siguen
--     cambiando solo por movimientos;
--   * `solicitud_compra.origen` admite STOCK_MINIMO: una solicitud que un
--     usuario confirma desde la sugerencia de reposición hasta el mínimo. Nunca
--     se crea sola (DEC-MI-09). MANUAL y FALTANTE se conservan.
--
-- Ningún dato existente cambia.

alter table rma.insumo add column if not exists stock_minimo numeric(12, 3);

alter table rma.insumo drop constraint if exists insumo_stock_minimo_no_negativo;
alter table rma.insumo add constraint insumo_stock_minimo_no_negativo
  check (stock_minimo is null or stock_minimo >= 0);

comment on column rma.insumo.stock_minimo is
  'Stock mínimo del insumo (DEC-AJ-11), en su unidad; vacío si no tiene. Se compara con el disponible (físico menos reservado): por debajo, el insumo está «bajo mínimo» y se sugiere reponer hasta alcanzarlo. Lo configura quien gestiona insumos; no genera compras automáticas.';

grant update (stock_minimo) on rma.insumo to rma_backend;

alter table rma.solicitud_compra drop constraint if exists solicitud_compra_origen_check;
alter table rma.solicitud_compra add constraint solicitud_compra_origen_check
  check (origen in ('MANUAL', 'FALTANTE', 'STOCK_MINIMO'));

comment on column rma.solicitud_compra.origen is
  'MANUAL, FALTANTE (sugerida por las Órdenes que esperan recursos) o STOCK_MINIMO (sugerida para reponer hasta el stock mínimo, DEC-AJ-11; puede cubrir también un faltante).';
