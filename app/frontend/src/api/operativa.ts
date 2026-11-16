/**
 * Configuración operativa (DEC-MI-14 y 15): motivos de cancelación e
 * interrupción, parámetros y seguimientos del retiro demorado.
 */

import type { MedioPago, Orden } from "../types/api";
import { get, post, put } from "./client";

export type TipoMotivo = "CANCELACION" | "INTERRUPCION";

export interface MotivoOperativo {
  codigo: string;
  tipo: TipoMotivo;
  nombre: string;
  activo: boolean;
  requiere_descripcion: boolean;
}

/** Motivos de un tipo (los inactivos también: la UI ofrece los activos). */
export function listarMotivos(tipo: TipoMotivo): Promise<MotivoOperativo[]> {
  return get<MotivoOperativo[]>(`/api/catalogs/reasons?tipo=${tipo}`);
}

export interface MotivosAdmin {
  editable: boolean;
  motivos: MotivoOperativo[];
}

export function listarMotivosAdmin(): Promise<MotivosAdmin> {
  return get<MotivosAdmin>("/api/admin/reasons");
}

export function crearMotivo(
  usuarioId: string,
  motivo: MotivoOperativo,
): Promise<MotivoOperativo> {
  return post<MotivoOperativo>("/api/admin/reasons", {
    usuario_id: usuarioId,
    ...motivo,
  });
}

export function editarMotivo(
  usuarioId: string,
  motivo: MotivoOperativo,
): Promise<MotivoOperativo> {
  return put<MotivoOperativo>(
    `/api/admin/reasons/${encodeURIComponent(motivo.codigo)}`,
    {
      usuario_id: usuarioId,
      tipo: motivo.tipo,
      nombre: motivo.nombre,
      activo: motivo.activo,
      requiere_descripcion: motivo.requiere_descripcion,
    },
  );
}

export interface ParametrosAdmin {
  editable: boolean;
  parametros: Record<string, string>;
}

export function leerParametros(): Promise<ParametrosAdmin> {
  return get<ParametrosAdmin>("/api/admin/parameters");
}

export function guardarParametro(
  usuarioId: string,
  clave: string,
  valor: string,
): Promise<Record<string, string>> {
  return put<Record<string, string>>(
    `/api/admin/parameters/${encodeURIComponent(clave)}`,
    { usuario_id: usuarioId, valor },
  );
}

/** UX-08: medios de pago con su recargo, para Administración. */
export interface MediosPagoAdmin {
  editable: boolean;
  medios: MedioPago[];
}

export function leerMediosPago(): Promise<MediosPagoAdmin> {
  return get<MediosPagoAdmin>("/api/admin/payment-methods");
}

/** Cambia el recargo de un medio, con auditoría; no toca pagos ya hechos. */
export function guardarRecargo(
  usuarioId: string,
  medioId: string,
  porcentaje: string,
): Promise<MedioPago> {
  return put<MedioPago>(
    `/api/admin/payment-methods/${encodeURIComponent(medioId)}`,
    { usuario_id: usuarioId, recargo_porcentaje: porcentaje },
  );
}

/** Seguimiento de un retiro demorado (DEC-MI-14). No cierra la Orden. */
export function registrarSeguimientoRetiro(
  ordenId: string,
  usuarioId: string,
  nota: string,
  canal: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/pickup-followups`, {
    usuario_id: usuarioId,
    nota,
    canal,
  });
}
