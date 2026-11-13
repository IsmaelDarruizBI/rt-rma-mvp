/**
 * Administración de catálogos con auditoría (DC23, DC23AUD, BR-REP-040).
 * Solo Administración; las escrituras exigen la base PostgreSQL.
 */

import { get, post, put } from "./client";
import type { RolUsuario, TipoReparacion, Usuario } from "../types/api";

export interface MesaConfigurable {
  id: string;
  nombre: string;
  activa: boolean;
  /** Tipos de Reparación habilitados en la Mesa. */
  tipos: string[];
}

export interface CatalogoConfigurable {
  /** false en el modo JSON: los catálogos son de solo lectura. */
  editable: boolean;
  tipos: TipoReparacion[];
  mesas: MesaConfigurable[];
}

export type EntidadConfiguracion =
  | "TIPO_REPARACION"
  | "MESA_TRABAJO"
  | "USUARIO"
  | "PERMISO"
  | "INSUMO"
  | "MOTIVO"
  | "PLANTILLA"
  | "PARAMETRO"
  | "CHECKLIST"
  | "PROVEEDOR";

export interface CambioConfiguracion {
  entidad: EntidadConfiguracion;
  clave: string;
  campo: string;
  valor_anterior: string | null;
  valor_nuevo: string | null;
  usuario_id: string;
  fecha: string;
}

export interface DatosTipo {
  nombre: string;
  precio: string;
  puntaje: number;
  garantia_dias: number;
  activo: boolean;
}

export function obtenerCatalogo(): Promise<CatalogoConfigurable> {
  return get<CatalogoConfigurable>("/api/admin/catalog");
}

export function crearTipo(
  usuarioId: string,
  codigo: string,
  datos: DatosTipo,
): Promise<TipoReparacion> {
  return post<TipoReparacion>("/api/admin/repair-types", {
    usuario_id: usuarioId,
    codigo,
    ...datos,
  });
}

export function editarTipo(
  usuarioId: string,
  codigo: string,
  datos: DatosTipo,
): Promise<TipoReparacion> {
  return put<TipoReparacion>(
    `/api/admin/repair-types/${encodeURIComponent(codigo)}`,
    { usuario_id: usuarioId, ...datos },
  );
}

export function guardarTiposDeMesa(
  usuarioId: string,
  mesaId: string,
  tipos: string[],
): Promise<CambioConfiguracion> {
  return put<CambioConfiguracion>(
    `/api/admin/stations/${encodeURIComponent(mesaId)}/repair-types`,
    { usuario_id: usuarioId, tipos },
  );
}

export function obtenerCambios(
  entidad?: EntidadConfiguracion,
  clave?: string,
): Promise<CambioConfiguracion[]> {
  const parametros = new URLSearchParams();
  if (entidad) parametros.set("entidad", entidad);
  if (clave) parametros.set("clave", clave);
  const consulta = parametros.toString();
  return get<CambioConfiguracion[]>(
    `/api/admin/config-changes${consulta ? `?${consulta}` : ""}`,
  );
}

// --- Usuarios, roles y permisos (DC27A, DC08) ---------------------------

export interface PermisoConfigurable {
  codigo: string;
  descripcion: string;
  grupo: string;
  consulta: boolean;
  configurable: boolean;
  predeterminados: RolUsuario[];
  vigentes: RolUsuario[];
}

export function listarUsuarios(): Promise<Usuario[]> {
  return get<Usuario[]>("/api/admin/users");
}

export function guardarRoles(
  usuarioId: string,
  destinoId: string,
  roles: RolUsuario[],
): Promise<Usuario> {
  return put<Usuario>(`/api/admin/users/${encodeURIComponent(destinoId)}/roles`, {
    usuario_id: usuarioId,
    roles,
  });
}

export function listarPermisos(): Promise<PermisoConfigurable[]> {
  return get<PermisoConfigurable[]>("/api/admin/permissions");
}

export function guardarPermiso(
  usuarioId: string,
  codigo: string,
  roles: RolUsuario[],
): Promise<PermisoConfigurable> {
  return put<PermisoConfigurable>(
    `/api/admin/permissions/${encodeURIComponent(codigo)}`,
    { usuario_id: usuarioId, roles },
  );
}
