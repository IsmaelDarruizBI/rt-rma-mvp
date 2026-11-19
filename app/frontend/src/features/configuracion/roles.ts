/**
 * Reglas de pantalla de Usuarios y roles y de Permisos (DC27A, DC27B,
 * DEC-MI-12), sin React. La API valida todo de nuevo; esto evita ofrecer
 * un guardado que el servidor rechazaría.
 */

import { rolesDe } from "../../lib/roles.ts";
import type { RolUsuario, Usuario } from "../../types/api";

export const ROLES: RolUsuario[] = [
  "ADMINISTRADOR",
  "COORDINADOR_RMA",
  "RECEPCION",
  "TECNICO",
];

export function mismosRoles(a: RolUsuario[], b: RolUsuario[]): boolean {
  return a.length === b.length && a.every((r) => b.includes(r));
}

/** Marca o desmarca un rol sin repetirlo. */
export function alternarRol(roles: RolUsuario[], rol: RolUsuario, marcado: boolean): RolUsuario[] {
  if (marcado) return roles.includes(rol) ? roles : [...roles, rol];
  return roles.filter((r) => r !== rol);
}

/** Por qué no se pueden guardar estos roles para el usuario, o null.
 * Nunca queda el sistema sin un Administrador activo. */
export function motivoParaNoGuardarRoles(
  usuarios: Usuario[],
  usuarioId: string,
  propuestos: RolUsuario[],
): string | null {
  if (propuestos.length === 0) return "Un usuario tiene al menos un rol.";
  const quedan = usuarios.filter(
    (u) =>
      u.activo &&
      (u.id === usuarioId ? propuestos : rolesDe(u)).includes("ADMINISTRADOR"),
  );
  if (quedan.length === 0) return "No puede quedar el sistema sin un Administrador activo.";
  return null;
}

/** Un permiso se guarda si es configurable, cambió y tiene algún rol. */
export function puedeGuardarPermiso(
  permiso: { configurable: boolean; vigentes: RolUsuario[] },
  propuestos: RolUsuario[],
): boolean {
  return permiso.configurable && propuestos.length > 0 && !mismosRoles(propuestos, permiso.vigentes);
}

/** Lo mínimo de un permiso para sus dependencias (CFG-03). */
export interface PermisoConDependencias {
  codigo: string;
  descripcion: string;
  vigentes: RolUsuario[];
  requiere?: string[];
}

/**
 * Las consultas que una acción requiere y que hay que habilitar primero
 * para los roles propuestos (por ejemplo, ver Compras antes de crear OC).
 * La API rechaza el orden inverso: así no queda una acción sin su consulta.
 */
export function consultasAHabilitar(
  permiso: PermisoConDependencias,
  propuestos: RolUsuario[],
  todos: PermisoConDependencias[],
): { codigo: string; descripcion: string; roles: RolUsuario[] }[] {
  const resultado: { codigo: string; descripcion: string; roles: RolUsuario[] }[] = [];
  for (const codigo of permiso.requiere ?? []) {
    const consulta = todos.find((p) => p.codigo === codigo);
    if (!consulta) continue;
    const faltan = propuestos.filter((rol) => !consulta.vigentes.includes(rol));
    if (faltan.length > 0) {
      resultado.push({
        codigo,
        descripcion: consulta.descripcion,
        roles: ROLES.filter((r) => consulta.vigentes.includes(r) || faltan.includes(r)),
      });
    }
  }
  return resultado;
}

/**
 * Las acciones que requieren este permiso y que todavía tiene un rol que
 * se le quita: primero hay que quitarle esas acciones.
 */
export function accionesQueLoRequieren(
  permiso: PermisoConDependencias,
  propuestos: RolUsuario[],
  todos: PermisoConDependencias[],
): string[] {
  const quitados = permiso.vigentes.filter((rol) => !propuestos.includes(rol));
  return todos
    .filter(
      (p) =>
        (p.requiere ?? []).includes(permiso.codigo) &&
        p.vigentes.some((rol) => quitados.includes(rol)),
    )
    .map((p) => p.descripcion);
}
