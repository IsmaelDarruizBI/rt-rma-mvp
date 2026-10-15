/**
 * Usuario de demostración: a falta de login, se elige quién opera.
 *
 * Se recuerda en el navegador solo como comodidad (el ID del usuario, nada
 * más: ni credenciales ni datos personales). No es autenticación: el
 * backend valida rol y titular en cada comando, sea quien sea el elegido.
 */

const CLAVE = "rt-rma.usuarioDemo";

/**
 * El usuario guardado si sigue en el catálogo; si no, el primero.
 * `""` cuando el catálogo está vacío.
 */
export function elegirUsuarioDemo(
  usuarios: { id: string }[],
  guardado: string | null,
): string {
  if (guardado && usuarios.some((usuario) => usuario.id === guardado)) {
    return guardado;
  }
  return usuarios[0]?.id ?? "";
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
  } catch {
    // Sin almacenamiento (modo privado, bloqueado): solo no se recuerda.
  }
}
