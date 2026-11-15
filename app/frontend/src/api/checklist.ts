/**
 * Checklist de recepción por tipo de equipo (DC12) y advertencia por
 * información faltante (BR-REP-025, nunca bloquea).
 */

import type { Orden } from "../types/api";
import { get, post, put } from "./client";

/** Tipo de Equipo: copia del catálogo de Ventas de Gestión RT (DC12).
 * `id` es el identificador de Ventas; RMA no los crea ni los edita. */
export interface TipoEquipo {
  id: string;
  nombre: string;
  activo: boolean;
  campo_origen?: string | null;
  sincronizado_en?: string | null;
}

export interface OrigenTiposEquipo {
  campo: string | null;
  definido: boolean;
  origen: string | null;
  sincronizable: boolean;
  ultima_sincronizacion: string | null;
  aviso: string | null;
}

export interface ResultadoSincronizacionTipos {
  campo: string;
  origen: string;
  fecha: string;
  vigentes: number;
  nuevos: number;
  reactivados: number;
  dados_de_baja: number;
  sin_cambios: number;
}

export interface PreguntaChecklist {
  id: string;
  tipo_equipo_id: string;
  texto: string;
  opciones: string[];
  activa: boolean;
  orden: number;
}

export interface RespuestaChecklist {
  pregunta_id: string;
  texto: string;
  opciones: string[];
  respuesta: string | null;
  no_realizada: boolean;
}

export interface RegistroChecklist {
  tipo_equipo_id: string;
  tipo_equipo_nombre: string;
  respuestas: RespuestaChecklist[];
  sin_registrar: string[];
  usuario_id: string;
  fecha: string;
  motivo: string | null;
}

export interface CatalogoChecklist {
  editable: boolean;
  tipos: TipoEquipo[];
  preguntas: PreguntaChecklist[];
  origen?: OrigenTiposEquipo;
}

export const catalogo = () => get<CatalogoChecklist>("/api/catalogs/checklist");
export const catalogoAdmin = () =>
  get<CatalogoChecklist>("/api/admin/checklist");

/** Actualiza la copia de los tipos desde el catálogo de Ventas. */
export function sincronizarTipos(usuarioId: string): Promise<ResultadoSincronizacionTipos> {
  return post("/api/admin/equipment-types/sync", { usuario_id: usuarioId });
}

export function guardarPregunta(
  usuarioId: string,
  pregunta: Omit<PreguntaChecklist, "id"> & { id?: string },
): Promise<PreguntaChecklist> {
  const { id, ...datos } = pregunta;
  const cuerpo = { usuario_id: usuarioId, ...datos };
  return id
    ? put(`/api/admin/checklist-questions/${encodeURIComponent(id)}`, cuerpo)
    : post("/api/admin/checklist-questions", cuerpo);
}

export function registrar(
  ordenId: string,
  datos: {
    usuario_id: string;
    tipo_equipo_id: string;
    respuestas: { pregunta_id: string; respuesta: string | null; no_realizada: boolean }[];
    motivo: string | null;
  },
): Promise<Orden> {
  return post(`/api/orders/${ordenId}/checklist`, datos);
}

export function confirmarFaltantes(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post(`/api/orders/${ordenId}/missing-info-ack`, { usuario_id: usuarioId });
}
