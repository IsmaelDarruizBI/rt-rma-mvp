/**
 * Administración de catálogos con auditoría (DC23, DC23AUD, BR-REP-040).
 * Solo Administración; las escrituras exigen la base PostgreSQL.
 */

import { get, post, put } from "./client";
import type {
  ContenidoTextoLegal,
  EmpresaEnDocumento,
  RolUsuario,
  TextoLegal,
  TipoReparacion,
  Usuario,
} from "../types/api";

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
  | "PROVEEDOR"
  | "MEDIO_PAGO"
  | "EMPRESA"
  | "TEXTO_LEGAL";

export interface CambioConfiguracion {
  entidad: EntidadConfiguracion;
  clave: string;
  campo: string;
  valor_anterior: string | null;
  valor_nuevo: string | null;
  usuario_id: string;
  fecha: string;
}

/**
 * Lo que la pantalla edita de un Tipo. CFG-06 (DF-1, DF-2): solo los plazos
 * con y sin check-in; el plazo genérico y la política RMA no se envían y
 * la API los conserva (en un alta, el genérico toma el de con check-in).
 */
export interface DatosTipo {
  nombre: string;
  precio: string;
  puntaje: number;
  activo: boolean;
  garantia_con_checkin: number;
  garantia_sin_checkin: number;
}

export function obtenerCatalogo(): Promise<CatalogoConfigurable> {
  return get<CatalogoConfigurable>("/api/admin/catalog");
}

/** CFG-01: el código lo genera la API (TR-NNN). */
export function crearTipo(
  usuarioId: string,
  datos: DatosTipo,
): Promise<TipoReparacion> {
  return post<TipoReparacion>("/api/admin/repair-types", {
    usuario_id: usuarioId,
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
  /** CFG-03: los permisos de consulta que esta acción necesita. */
  requiere?: string[];
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

// --- Comprobantes (DEC-AJ-09) ----------------------------------------------

/** Lo que edita «Datos de la empresa» (vacío: sin informar). */
export interface DatosEmpresaEditables {
  nombre: string;
  razon_social: string | null;
  cuit: string | null;
  direccion: string | null;
  telefono: string | null;
  email: string | null;
  horario: string | null;
  pie_comprobante: string | null;
}

export interface EmpresaAdmin {
  /** false en el modo JSON: la configuración es de solo lectura. */
  editable: boolean;
  empresa: EmpresaEnDocumento;
}

export function leerEmpresa(): Promise<EmpresaAdmin> {
  return get<EmpresaAdmin>("/api/admin/company");
}

export function guardarEmpresa(
  usuarioId: string,
  datos: DatosEmpresaEditables,
): Promise<EmpresaEnDocumento> {
  return put<EmpresaEnDocumento>("/api/admin/company", {
    usuario_id: usuarioId,
    ...datos,
  });
}

export interface TerminosAdmin {
  editable: boolean;
  tipo: string;
  vigente: TextoLegal | null;
  /** De la primera a la última; ninguna se modifica. */
  versiones: TextoLegal[];
}

export function leerTerminos(): Promise<TerminosAdmin> {
  return get<TerminosAdmin>("/api/admin/terms");
}

/** Publica una versión nueva y completa, vigente desde ahora. */
export function publicarTerminos(
  usuarioId: string,
  titulo: string,
  contenido: ContenidoTextoLegal,
): Promise<TextoLegal> {
  return post<TextoLegal>("/api/admin/terms", {
    usuario_id: usuarioId,
    titulo,
    contenido,
  });
}
