/**
 * Identidad del Equipo (DEC-MI-11): por IMEI y, si no hay, por número de
 * serie; nunca por similitud.
 */

import type { Orden } from "../types/api";
import { get, post } from "./client";

export interface CandidatoEquipo {
  equipo_id: string;
  imei: string | null;
  numero_serie: string | null;
  marca: string;
  modelo: string;
  variante: string | null;
  ordenes: string[];
  ultimo_ingreso: string;
}

export interface Identificacion {
  criterio: "IMEI" | "NUMERO_SERIE" | null;
  candidatos: CandidatoEquipo[];
}

export interface OrdenDelEquipo {
  orden_id: string;
  origen: string;
  estado_workflow: string;
  creada_en: string;
  entregada_en: string | null;
  falla_reportada: string;
  orden_origen_id: string | null;
  trabajos: {
    detalle_id: string;
    tipo_reparacion_id: string;
    estado: string;
    garantia_dias: number;
  }[];
  custodia: "ENTREGADO" | "EN_LOCAL" | "SIN_CONFIRMAR";
}

export function identificarEquipo(
  imei: string | null,
  numeroSerie: string | null,
): Promise<Identificacion> {
  const parametros = new URLSearchParams();
  if (imei) parametros.set("imei", imei);
  if (numeroSerie) parametros.set("numero_serie", numeroSerie);
  return get<Identificacion>(`/api/equipment/identify?${parametros}`);
}

export function historialDelEquipo(
  equipoId: string,
): Promise<{ equipo_id: string; ordenes: OrdenDelEquipo[] }> {
  return get(`/api/equipment/${encodeURIComponent(equipoId)}/orders`);
}

/** `equipoId` en `null`: «Ninguno», una identidad nueva. */
export function corregirVinculoEquipo(
  ordenId: string,
  usuarioId: string,
  equipoId: string | null,
  motivo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/equipment-link`, {
    usuario_id: usuarioId,
    equipo_id: equipoId,
    motivo,
  });
}
