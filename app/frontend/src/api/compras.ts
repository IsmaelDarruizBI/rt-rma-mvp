/**
 * Compras (DEC-MI-09): solicitudes, órdenes de compra, recepciones y
 * costos. Solo sobre PostgreSQL; en la demo JSON `estado().disponible` es
 * falso.
 */

import { get, post, put } from "./client";

export type EstadoSolicitud = "PENDIENTE" | "EN_ORDEN" | "DESCARTADA";
export type EstadoOrdenCompra =
  | "BORRADOR"
  | "CONFIRMADA"
  | "PARCIAL"
  | "RECIBIDA"
  | "CANCELADA";

export interface Proveedor {
  id: string;
  nombre: string;
  cuit: string | null;
  telefono: string | null;
  email: string | null;
  contacto: string | null;
  activo: boolean;
}

export interface SolicitudCompra {
  id: string;
  insumo_id: string;
  cantidad: string;
  origen: "MANUAL" | "FALTANTE" | "STOCK_MINIMO";
  motivo: string;
  ordenes: string[];
  usuario_id: string;
  fecha: string;
  estado: EstadoSolicitud;
  orden_compra_id: string | null;
  descartada_por: string | null;
  motivo_descarte: string | null;
}

export interface SugerenciaCompra {
  insumo_id: string;
  disponible: string;
  demanda_bloqueada: string;
  en_camino: string;
  sugerido: string;
  ordenes: string[];
  /** DEC-AJ-11: sugerido = por_faltante + por_minimo. */
  stock_minimo?: string | null;
  por_faltante?: string;
  por_minimo?: string;
  /** Origen con que se confirma la solicitud. */
  motivo?: "FALTANTE" | "STOCK_MINIMO";
}

export interface ItemOrdenCompra {
  insumo_id: string;
  cantidad: string;
  costo_unitario: string;
}

export interface LineaRecepcion {
  insumo_id: string;
  cantidad: string;
  costo_unitario: string;
  lote: string | null;
  series: string[];
  movimientos?: string[];
  diferencia: string | null;
}

export interface RecepcionCompra {
  id: string;
  usuario_id: string;
  fecha: string;
  remito: string | null;
  lineas: LineaRecepcion[];
  observaciones: string | null;
}

export interface OrdenCompra {
  id: string;
  proveedor_id: string;
  items: ItemOrdenCompra[];
  solicitudes: string[];
  creada_por: string;
  creada_en: string;
  confirmada_por: string | null;
  confirmada_en: string | null;
  cancelada_por: string | null;
  motivo_cancelacion: string | null;
  recepciones: RecepcionCompra[];
  observaciones: string | null;
  estado: EstadoOrdenCompra;
  renglones: {
    insumo_id: string;
    pedido: string;
    recibido: string;
    pendiente: string;
  }[];
}

export interface CostoCompra {
  insumo_id: string;
  orden_compra_id: string;
  recepcion_id: string;
  proveedor_id: string;
  cantidad: string;
  costo_unitario: string;
  fecha: string;
}

export const estado = () =>
  get<{ disponible: boolean }>("/api/purchases/status");
export const proveedores = () => get<Proveedor[]>("/api/purchases/suppliers");
export const solicitudes = () =>
  get<SolicitudCompra[]>("/api/purchases/requests");
export const sugerencias = () =>
  get<SugerenciaCompra[]>("/api/purchases/suggestions");
/**
 * DEC-AJ-14: trabajos que esperan recursos con un requisito sin pieza
 * elegida y sin ninguna pieza elegible con disponible. No son demanda de un
 * SKU: se elige la pieza o se compra una compatible.
 */
export interface TrabajoSinPieza {
  orden_id: string;
  detalle_id: string;
  tipo_reparacion_id: string;
  requisito_id: string;
  categoria_id: string;
  categoria_nombre: string;
  cantidad: string;
  modelo_equipo_id: string | null;
}

export const trabajosSinPieza = () =>
  get<TrabajoSinPieza[]>("/api/purchases/suggestions/pending-pieces");
export const ordenes = () => get<OrdenCompra[]>("/api/purchases/orders");
export const costos = (insumoId?: string) =>
  get<CostoCompra[]>(
    `/api/purchases/costs${insumoId ? `?insumo_id=${encodeURIComponent(insumoId)}` : ""}`,
  );

export function crearSolicitud(datos: {
  usuario_id: string;
  insumo_id: string;
  cantidad: string;
  motivo: string;
  origen?: "MANUAL" | "FALTANTE" | "STOCK_MINIMO";
  ordenes?: string[];
}): Promise<SolicitudCompra> {
  return post("/api/purchases/requests", datos);
}

export function descartarSolicitud(
  id: string,
  usuarioId: string,
  motivo: string,
): Promise<SolicitudCompra> {
  return post(`/api/purchases/requests/${encodeURIComponent(id)}/discard`, {
    usuario_id: usuarioId,
    motivo,
  });
}

export function crearOrden(datos: {
  usuario_id: string;
  proveedor_id: string;
  items: ItemOrdenCompra[];
  solicitudes: string[];
  observaciones: string | null;
}): Promise<OrdenCompra> {
  return post("/api/purchases/orders", datos);
}

export function confirmarOrden(
  id: string,
  usuarioId: string,
): Promise<OrdenCompra> {
  return post(`/api/purchases/orders/${encodeURIComponent(id)}/confirm`, {
    usuario_id: usuarioId,
  });
}

export function cancelarOrden(
  id: string,
  usuarioId: string,
  motivo: string,
): Promise<OrdenCompra> {
  return post(`/api/purchases/orders/${encodeURIComponent(id)}/cancel`, {
    usuario_id: usuarioId,
    motivo,
  });
}

export function recibir(
  id: string,
  datos: {
    usuario_id: string;
    lineas: LineaRecepcion[];
    remito: string | null;
    observaciones: string | null;
  },
): Promise<OrdenCompra> {
  return post(`/api/purchases/orders/${encodeURIComponent(id)}/receipts`, datos);
}

export const proveedoresAdmin = () =>
  get<{ editable: boolean; proveedores: Proveedor[] }>("/api/admin/suppliers");

export function guardarProveedor(
  usuarioId: string,
  proveedor: Omit<Proveedor, "id"> & { id?: string },
): Promise<Proveedor> {
  const { id, ...datos } = proveedor;
  const cuerpo = { usuario_id: usuarioId, ...datos };
  return id
    ? put(`/api/admin/suppliers/${encodeURIComponent(id)}`, cuerpo)
    : post("/api/admin/suppliers", cuerpo);
}
