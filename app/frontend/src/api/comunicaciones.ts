/**
 * Comunicaciones asistidas por WhatsApp y consentimiento (DEC-MI-08).
 * Abrir WhatsApp no es enviar: el envío lo confirma el usuario a mano y
 * nunca hay «entregado» ni «leído».
 */

import type { Orden } from "../types/api";
import { get, post, put } from "./client";

export type Finalidad = "OPERATIVA" | "COMERCIAL";

export interface PlantillaMensaje {
  codigo: string;
  nombre: string;
  finalidad: Finalidad;
  texto: string;
  activa: boolean;
}

export interface Plantillas {
  editable: boolean;
  plantillas: PlantillaMensaje[];
  variables: Record<string, string>;
}

export interface MensajePreparado {
  plantilla: PlantillaMensaje;
  mensaje: string;
  faltantes: string[];
  destinatario: string | null;
  impedimento: string | null;
}

export interface Consentimiento {
  cliente_id: string;
  finalidad: Finalidad;
  canal: "WHATSAPP";
  otorgado: boolean;
  origen: string;
  usuario_id: string;
  fecha: string;
}

export interface Consentimientos {
  historial: Consentimiento[];
  vigentes: Record<Finalidad, boolean | null>;
}

export function listarPlantillas(): Promise<Plantillas> {
  return get<Plantillas>("/api/communications/templates");
}

export function prepararMensaje(
  ordenId: string,
  plantilla: string,
): Promise<MensajePreparado> {
  return get<MensajePreparado>(
    `/api/orders/${ordenId}/messages/prepare?plantilla=${encodeURIComponent(plantilla)}`,
  );
}

/** Registra el intento (se abre WhatsApp). No es un envío. */
export function registrarIntento(
  ordenId: string,
  usuarioId: string,
  plantilla: string | null,
  mensaje: string,
  destinatario: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/messages`, {
    usuario_id: usuarioId,
    plantilla_codigo: plantilla,
    mensaje,
    destinatario,
  });
}

export function confirmarEnvio(
  ordenId: string,
  comunicacionId: string,
  usuarioId: string,
  enviado: boolean,
  nota: string | null,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenId}/messages/${encodeURIComponent(comunicacionId)}/confirm`,
    { usuario_id: usuarioId, enviado, nota },
  );
}

export function leerConsentimientos(
  clienteId: string,
): Promise<Consentimientos> {
  return get<Consentimientos>(
    `/api/clients/${encodeURIComponent(clienteId)}/consents`,
  );
}

export function registrarConsentimiento(
  clienteId: string,
  usuarioId: string,
  finalidad: Finalidad,
  otorgado: boolean,
  origen: string,
): Promise<Consentimientos> {
  return post<Consentimientos>(
    `/api/clients/${encodeURIComponent(clienteId)}/consents`,
    { usuario_id: usuarioId, finalidad, otorgado, origen },
  );
}

export function listarPlantillasAdmin(): Promise<Plantillas> {
  return get<Plantillas>("/api/admin/message-templates");
}

export function crearPlantilla(
  usuarioId: string,
  plantilla: PlantillaMensaje,
): Promise<PlantillaMensaje> {
  return post<PlantillaMensaje>("/api/admin/message-templates", {
    usuario_id: usuarioId,
    ...plantilla,
  });
}

export function editarPlantilla(
  usuarioId: string,
  plantilla: PlantillaMensaje,
): Promise<PlantillaMensaje> {
  return put<PlantillaMensaje>(
    `/api/admin/message-templates/${encodeURIComponent(plantilla.codigo)}`,
    {
      usuario_id: usuarioId,
      nombre: plantilla.nombre,
      finalidad: plantilla.finalidad,
      texto: plantilla.texto,
      activa: plantilla.activa,
    },
  );
}
