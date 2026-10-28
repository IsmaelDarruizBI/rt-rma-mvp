/**
 * Sesión de demostración (UAT): login dummy que elige quién opera.
 *
 * NO es autenticación ni seguridad: las credenciales viven en el frontend
 * y solo sirven para probar el acceso y la navegación por rol. Cada login
 * se resuelve, por rol, a un usuario REAL del catálogo de demostración; el
 * backend sigue validando rol y titular en cada comando.
 *
 * Se recuerda en el navegador solo el ID del usuario (ni credenciales ni
 * datos personales). La clave es nueva a propósito: la selección que
 * guardaba el selector anterior (`rt-rma.usuarioDemo`) no abre sesión.
 */

import type { RolUsuario } from "../../types/api";

const CLAVE = "rt-rma.sesionDemo";
const CLAVE_ANTERIOR = "rt-rma.usuarioDemo";

/** Usuarios dummy del UAT. La contraseña no es una medida de seguridad. */
export const CREDENCIALES_DEMO: Record<
  string,
  { contrasena: string; rol: RolUsuario }
> = {
  recepcion: { contrasena: "123456", rol: "RECEPCION" },
  tecnico: { contrasena: "123456", rol: "TECNICO" },
  coordinacion: { contrasena: "123456", rol: "COORDINADOR_RMA" },
  administracion: { contrasena: "123456", rol: "ADMINISTRADOR" },
};

export type ResultadoLogin =
  | { ok: true; usuarioId: string }
  | { ok: false; mensaje: string };

/**
 * Valida usuario y contraseña dummy y devuelve el usuario del catálogo
 * (activo) con ese rol. El nombre de usuario no distingue mayúsculas.
 */
export function validarCredenciales(
  usuario: string,
  contrasena: string,
  catalogo: { id: string; rol: string; activo?: boolean }[],
): ResultadoLogin {
  const credencial = CREDENCIALES_DEMO[usuario.trim().toLowerCase()];
  if (!credencial || credencial.contrasena !== contrasena) {
    return { ok: false, mensaje: "Usuario o contraseña incorrectos." };
  }
  const elegido = catalogo.find(
    (candidato) =>
      candidato.rol === credencial.rol && candidato.activo !== false,
  );
  if (!elegido) {
    return {
      ok: false,
      mensaje: "No hay un usuario de demostración disponible para ese rol.",
    };
  }
  return { ok: true, usuarioId: elegido.id };
}

/**
 * El usuario de la sesión guardada si sigue en el catálogo; si no, `""`
 * (sin sesión: se muestra el login).
 */
export function elegirUsuarioDemo(
  usuarios: { id: string }[],
  guardado: string | null,
): string {
  if (guardado && usuarios.some((usuario) => usuario.id === guardado)) {
    return guardado;
  }
  return "";
}

/** Lo guardado, o `null` si no hay o el navegador no lo permite. */
export function leerUsuarioDemo(): string | null {
  try {
    return window.localStorage.getItem(CLAVE);
  } catch {
    return null;
  }
}

export function guardarUsuarioDemo(usuarioId: string): void {
  try {
    if (usuarioId) window.localStorage.setItem(CLAVE, usuarioId);
    // La selección del selector anterior ya no se usa.
    window.localStorage.removeItem(CLAVE_ANTERIOR);
  } catch {
    // Sin almacenamiento (modo privado, bloqueado): solo no se recuerda.
  }
}

/** Cerrar sesión: olvida el usuario guardado. */
export function borrarUsuarioDemo(): void {
  try {
    window.localStorage.removeItem(CLAVE);
    window.localStorage.removeItem(CLAVE_ANTERIOR);
  } catch {
    // Sin almacenamiento: no había nada que olvidar.
  }
}
