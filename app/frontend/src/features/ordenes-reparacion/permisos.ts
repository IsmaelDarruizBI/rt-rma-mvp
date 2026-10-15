/**
 * Quién puede ejecutar una acción: lo mismo que valida el backend, para no
 * ofrecer lo que va a rechazar. Usuario activo, rol autorizado (salvo un
 * paso de sistema o sin rol definido) y titular de la toma. La misma regla
 * que `puede_ejecutar` (`app/application/acciones.py`), que usan las
 * bandejas. No autoriza nada: el servidor valida igual cada comando.
 */

import type { Accion, Usuario } from "../../types/api";

export function puedeEjecutar(
  accion: Pick<Accion, "requiere_actor" | "roles" | "usuario_id">,
  actor: Pick<Usuario, "id" | "rol" | "activo"> | null,
): boolean {
  if (!accion.requiere_actor) return true;
  if (actor === null || !actor.activo) return false;
  if (accion.roles.length > 0 && !accion.roles.includes(actor.rol)) {
    return false;
  }
  return accion.usuario_id === null || accion.usuario_id === actor.id;
}
