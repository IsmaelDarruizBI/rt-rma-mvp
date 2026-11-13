/**
 * Reclamos de garantía rechazados (DEC-MI-02): consulta y continuación como
 * reparación paga de cliente externo.
 */

import { get, post } from "./client";

export interface VigenciaReclamada {
  detalle_id: string;
  garantia_dias: number;
  vence: string | null;
  vigente: boolean;
}

export interface ReclamoGarantia {
  id: string;
  orden_origen_id: string;
  detalles_reclamados: string[];
  equipo: { marca: string; modelo: string; imei?: string | null };
  usuario_id: string;
  fecha: string;
  vigencias: VigenciaReclamada[];
  excepciones_pedidas: Record<string, string>;
  resultado: "RECHAZADO";
  motivo: string;
  orden_continuacion_id: string | null;
  continuado_por: string | null;
  continuado_en: string | null;
}

export function listarReclamos(): Promise<ReclamoGarantia[]> {
  return get<ReclamoGarantia[]>("/api/warranty-claims");
}

export function continuarReclamo(
  reclamoId: string,
  usuarioId: string,
  fallaReportada: string | null,
): Promise<{ orden_id: string; reclamo: ReclamoGarantia }> {
  return post(`/api/warranty-claims/${encodeURIComponent(reclamoId)}/continue`, {
    usuario_id: usuarioId,
    confirmado: true,
    falla_reportada: fallaReportada,
  });
}
