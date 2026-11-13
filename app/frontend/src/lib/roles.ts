/**
 * Roles y permisos del usuario en pantalla (DC27A, DC08).
 *
 * Un usuario puede tener varios roles: sus permisos se suman. La API manda
 * `roles` (todos) y `permisos` (los códigos que hoy habilitan sus roles,
 * con la configuración vigente); los datos anteriores solo traen `rol`.
 * La pantalla los usa para ofrecer funciones; quien autoriza es la API.
 */

import type { RolUsuario, Usuario } from "../types/api";

/** Lo mínimo de un usuario para saber sus roles y permisos. */
export type ConRoles = Pick<Usuario, "rol"> &
  Partial<Pick<Usuario, "roles" | "permisos" | "activo">>;

export function rolesDe(usuario: ConRoles | null): RolUsuario[] {
  if (usuario === null) return [];
  return usuario.roles && usuario.roles.length > 0
    ? usuario.roles
    : [usuario.rol];
}

export function tieneRol(usuario: ConRoles | null, rol: RolUsuario): boolean {
  return rolesDe(usuario).includes(rol);
}

export function tieneAlguno(
  usuario: ConRoles | null,
  roles: readonly string[],
): boolean {
  return rolesDe(usuario).some((rol) => roles.includes(rol));
}

/**
 * Si el usuario tiene el permiso. Sin la lista de permisos (una API
 * anterior), decide `porDefecto`: los roles predeterminados del permiso.
 */
export function puede(
  usuario: ConRoles | null,
  permiso: string,
  porDefecto: readonly string[] = [],
): boolean {
  if (usuario === null || usuario.activo === false) return false;
  if (usuario.permisos) return usuario.permisos.includes(permiso);
  return tieneAlguno(usuario, porDefecto);
}
