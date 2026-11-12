/**
 * Consultas de solo lectura (macroiteración V1.4): antecedentes del equipo
 * por IMEI o número de serie (BR-REP-022) y reporte operativo.
 */

import { get } from "./client";

export interface TrabajoAntecedente {
  detalle_id: string;
  tipo_reparacion_id: string;
  estado: string;
  garantia_dias: number;
}

export interface Antecedente {
  orden_id: string;
  origen: string;
  estado_workflow: string;
  creada_en: string;
  entregada_en: string | null;
  falla_reportada: string;
  orden_origen_id: string | null;
  trabajos: TrabajoAntecedente[];
  coincide_por: string[];
}

export interface AntecedentesEquipo {
  imei: string | null;
  numero_serie: string | null;
  /** Sin IMEI ni número de serie no hay con qué buscar (ABI-05). */
  sin_identificacion: boolean;
  ordenes: Antecedente[];
}

export function obtenerAntecedentesEquipo(
  imei: string | null,
  numeroSerie: string | null,
  excluirOrdenId: string | null,
): Promise<AntecedentesEquipo> {
  const parametros = new URLSearchParams();
  if (imei) parametros.set("imei", imei);
  if (numeroSerie) parametros.set("numero_serie", numeroSerie);
  if (excluirOrdenId) parametros.set("excluir_orden_id", excluirOrdenId);
  return get<AntecedentesEquipo>(`/api/equipment/history?${parametros}`);
}

export interface ReporteOperativo {
  generado_en: string;
  ordenes_por_estado: Record<string, number>;
  ordenes_por_origen: Record<string, number>;
  trabajos_por_tecnico: {
    usuario_id: string;
    completadas: number;
    interrumpidas: number;
    puntaje: number;
  }[];
  tiempos_por_estacion: {
    estacion_id: string;
    ejecuciones: number;
    horas_totales: string;
    horas_promedio: string;
  }[];
  pendientes: {
    orden_id: string;
    estado_workflow: string;
    origen: string;
    dias_abierta: number;
    dias_sin_movimiento: number;
  }[];
  reprocesos: Record<string, number>;
  consumo_insumos: { insumo_id: string; cantidad: string }[];
  cobros: {
    cobrado: string;
    devuelto: string;
    saldo_pendiente_ordenes_abiertas: string;
    credito_a_favor_pendiente: string;
  };
}

export function obtenerReporteOperativo(): Promise<ReporteOperativo> {
  return get<ReporteOperativo>("/api/reports/operational");
}
