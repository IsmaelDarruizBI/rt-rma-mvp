/**
 * Checklist de recepción por tipo de equipo (DC12) y advertencia por
 * información faltante (BR-REP-025, nunca bloquea).
 */

import type { Orden } from "../types/api";
import { get, post, put } from "./client";

export interface TipoEquipo {
  id: string;
  nombre: string;
  activo: boolean;
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
}

export const catalogo = () => get<CatalogoChecklist>("/api/catalogs/checklist");
export const catalogoAdmin = () =>
  get<CatalogoChecklist>("/api/admin/checklist");

export function guardarTipo(
  usuarioId: string,
  tipo: { id?: string; nombre: string; activo: boolean },
): Promise<TipoEquipo> {
  const cuerpo = { usuario_id: usuarioId, nombre: tipo.nombre, activo: tipo.activo };
  return tipo.id
    ? put(`/api/admin/equipment-types/${encodeURIComponent(tipo.id)}`, cuerpo)
    : post("/api/admin/equipment-types", cuerpo);
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
