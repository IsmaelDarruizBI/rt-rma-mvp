/**
 * Cancelación de la Orden (DC31): qué se muestra antes de confirmarla.
 *
 * Cancelar un trabajo nunca cancela la Orden. Cancelar la Orden es
 * explícito y definitivo: cancela los trabajos pendientes y la cierra; si
 * algo lo impide (ejecución, toma, reservas, saldo, custodia o equipo en el
 * local), el backend publica la acción con `bloqueo` y el motivo. Acá solo
 * se arma el texto: la regla la aplica el backend.
 */

import type { Accion, Orden } from "../../types/api";

/** Los trabajos pendientes que la cancelación de la Orden va a cancelar. */
export function trabajosACancelar(
  orden: Pick<Orden, "reparaciones_detail">,
): string[] {
  return orden.reparaciones_detail
    .filter((detalle) => detalle.estado === "DEFINIDO")
    .map((detalle) => detalle.tipo_reparacion_nombre ?? detalle.id);
}

/** Lo que pasa al confirmar: siempre definitivo. */
export function avisoCancelacionOrden(
  orden: Pick<Orden, "reparaciones_detail">,
): string {
  const cantidad = trabajosACancelar(orden).length;
  const definitiva =
    "La Orden queda CANCELADA y cerrada: después no admite ninguna acción, " +
    "solo consultar su información, documentos e historial.";
  if (cantidad === 0) return definitiva;
  return (
    `Se cancela${cantidad === 1 ? "" : "n"} ${cantidad} trabajo` +
    `${cantidad === 1 ? "" : "s"} pendiente${cantidad === 1 ? "" : "s"}. ` +
    definitiva
  );
}

/**
 * Los motivos del bloqueo, uno por línea. El backend los manda juntos:
 * «No se puede cancelar todavia: motivo; motivo.»
 */
export function motivosDeBloqueo(bloqueo: Accion["bloqueo"]): string[] {
  if (!bloqueo) return [];
  const sinPrefijo = bloqueo.replace(/^No se puede cancelar todav[ií]a:\s*/i, "");
  return sinPrefijo
    .replace(/\.\s*$/, "")
    .split(";")
    .map((motivo) => motivo.trim())
    .filter((motivo) => motivo !== "")
    .map((motivo) => motivo.charAt(0).toUpperCase() + motivo.slice(1));
}
