/**
 * Prioridad de la Orden en pantalla.
 *
 * La convención (1 Urgente … 4 Normal, cuanto menor más prioritaria) vive
 * en el backend (`app/domain/prioridad.py`), que la publica en el catálogo
 * `GET /api/catalogs/priorities`: acá no se interpreta ningún número.
 */

import type { Prioridad } from "../../types/api";

/** La que propone el formulario: la predeterminada del catálogo. */
export function prioridadPropuesta(prioridades: Prioridad[]): number | null {
  const propuesta = prioridades.find((prioridad) => prioridad.predeterminada);
  return propuesta?.valor ?? null;
}

/** «4 — Normal», como opción del selector. */
export function opcionDePrioridad(prioridad: Prioridad): string {
  return `${prioridad.valor} — ${prioridad.nombre}`;
}
