/**
 * Nombre de usuario de un empleado -> identidad de su cuenta en Supabase Auth.
 *
 * Supabase Auth verifica contraseñas de cuentas con email (no tiene login por
 * nombre de usuario). Los empleados no usan su correo: cada cuenta tiene como
 * "email" un identificador interno `<usuario>@<dominio>`, con un dominio
 * reservado que no existe ni recibe correo (`.invalid`, RFC 2606/6761). La
 * regla es fija y pública: no hay ningún directorio que consultar, así que no
 * hay nada que enumerar. La misma regla la aplica el script de Administración
 * que crea las cuentas (`supabase/scripts/cuentas_rma.py`).
 */

/** Dominio por defecto de las identidades internas (no existe ni recibe correo). */
export const DOMINIO_USUARIOS_POR_DEFECTO = "usuarios.rma.invalid";

/** 3 a 32 caracteres: minúsculas, dígitos, punto, guion y guion bajo; empieza
 * con letra o dígito. */
const FORMATO = /^[a-z0-9][a-z0-9._-]{2,31}$/;

/** El nombre normalizado, o `null` si no tiene el formato de un usuario. */
export function normalizarUsuario(texto: string): string | null {
  const usuario = texto.trim().toLowerCase();
  return FORMATO.test(usuario) ? usuario : null;
}

/** La identidad interna de Supabase Auth para ese usuario, o `null`. */
export function identidadDeUsuario(
  texto: string,
  dominio: string = DOMINIO_USUARIOS_POR_DEFECTO,
): string | null {
  const usuario = normalizarUsuario(texto);
  return usuario === null ? null : `${usuario}@${dominio}`;
}

/** Un dominio aceptable para las identidades internas. */
export function dominioValido(dominio: string): boolean {
  return /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(dominio);
}
