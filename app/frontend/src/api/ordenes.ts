/**
 * Llamadas a la API de Ordenes y catalogos.
 *
 * Una funcion por intencion de usuario, con los mismos nombres que los
 * comandos del backend. Cada POST devuelve la Orden ya actualizada, asi
 * que la UI nunca tiene que recomponer el estado por su cuenta.
 */

import type {
  Estacion,
  InsumoUtilizado,
  Orden,
  OrdenResumen,
  TipoReparacion,
  Usuario,
} from "../types/api";
import { get, post } from "./client";

// --- Catalogos ---------------------------------------------------------

export function listarTiposReparacion(): Promise<TipoReparacion[]> {
  return get<TipoReparacion[]>("/api/catalogs/repair-types");
}

export function listarEstaciones(): Promise<Estacion[]> {
  return get<Estacion[]>("/api/catalogs/stations");
}

export function listarUsuarios(): Promise<Usuario[]> {
  return get<Usuario[]>("/api/catalogs/users");
}

// --- Lectura de Ordenes ------------------------------------------------

export function listarOrdenes(): Promise<OrdenResumen[]> {
  return get<OrdenResumen[]>("/api/orders");
}

export function obtenerOrden(ordenId: string): Promise<Orden> {
  return get<Orden>(`/api/orders/${ordenId}`);
}

// --- Comandos del Happy Path -------------------------------------------

export interface DatosNuevaOrden {
  usuario_id: string;
  cliente: { nombre: string; telefono: string; email?: string | null };
  equipo: { marca: string; modelo: string; falla_reportada: string };
}

/** PROC-REP-010 -> 030 -> 040 (Recepción). */
export function crearOrden(datos: DatosNuevaOrden): Promise<Orden> {
  return post<Orden>("/api/orders", datos);
}

export interface DatosNuevaOrdenRt {
  usuario_id: string;
  equipo: { marca: string; modelo: string; falla_reportada: string };
  referencia_rt: string;
}

/** PROC-REP-010 -> 020 -> 040 (Recepción, HP-REP-002). Sin Cliente. */
export function crearOrdenRt(datos: DatosNuevaOrdenRt): Promise<Orden> {
  return post<Orden>("/api/orders/rt-interno", datos);
}

/** PROC-REP-045 -> 070 -> 050 -> 060 -> 080 -> 090 -> 140 (Recepción). */
export function definirReparacion(
  ordenId: string,
  usuarioId: string,
  tipoReparacionId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/details`, {
    usuario_id: usuarioId,
    tipo_reparacion_id: tipoReparacionId,
  });
}

/** PROC-REP-150 -> 170 (Coordinador). */
export function encolar(
  ordenId: string,
  usuarioId: string,
  prioridad: number,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/queue`, {
    usuario_id: usuarioId,
    prioridad,
  });
}

/** PROC-REP-172 -> 180 (Técnico). */
export function tomarOrden(
  ordenId: string,
  usuarioId: string,
  estacionId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/take`, {
    usuario_id: usuarioId,
    estacion_id: estacionId,
  });
}

/** PROC-REP-181 -> 174 -> 185: reserva real (Técnico). */
export function iniciarDetalle(
  ordenId: string,
  detalleId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/details/${detalleId}/start`, {
    usuario_id: usuarioId,
  });
}

/** PROC-REP-190 -> 200 -> 210 -> 211 (Técnico propietario). */
export function completarEjecucion(
  ordenId: string,
  ejecucionId: string,
  usuarioId: string,
  insumosUtilizados: InsumoUtilizado[],
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenId}/executions/${ejecucionId}/complete`,
    {
      usuario_id: usuarioId,
      insumos_utilizados: insumosUtilizados,
      observaciones,
    },
  );
}

/** PROC-REP-220 -> 230 -> 245 -> 240 (Recepción). */
export function aprobarControl(
  ordenId: string,
  usuarioId: string,
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/control/approve`, {
    usuario_id: usuarioId,
    observaciones,
  });
}

/** PROC-REP-250 -> 260 -> 265 [-> 266] (Recepción). */
export function notificar(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/notify`, {
    usuario_id: usuarioId,
  });
}

/** Capacidad transversal FEAT-REP-007 / BR-REP-017, sin rol exigido. */
export function registrarPago(
  ordenId: string,
  usuarioId: string,
  monto: string,
  metodo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/payments`, {
    usuario_id: usuarioId,
    monto,
    metodo,
  });
}

/** PROC-REP-280 -> 270 -> EVT-REP-999 (Administrador). */
export function entregar(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/deliver`, {
    usuario_id: usuarioId,
  });
}

/**
 * PROC-REP-250 -> 290 (HP-REP-002, RT_INTERNO).
 *
 * PROC-REP-290 es `actor: ACT-SYSTEM`: no hay actor humano que
 * autorizar, así que este comando no envía `usuario_id`.
 */
export function informarRt(ordenId: string): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/inform-rt`, {});
}

/** PROC-REP-270 reutilizado (HP-REP-002, RT_INTERNO -> EVT-REP-999). */
export function devolverRt(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/return-rt`, {
    usuario_id: usuarioId,
  });
}
