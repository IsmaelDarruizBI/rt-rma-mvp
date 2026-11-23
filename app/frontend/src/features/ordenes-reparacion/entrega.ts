/**
 * Entrega del equipo (ajustes funcionales, bloque 2): funciones puras de la
 * pantalla, sin React, para probarlas con `npm test`.
 *
 * - DEC-AJ-03: el aviso al cliente es opcional; el retiro demorado corre
 *   desde que la Orden está lista para retirar y la fecha del aviso se
 *   muestra aparte.
 * - DEC-AJ-04: un solo «Comprobante de entrega y garantía»; el check-in
 *   que falta se pregunta en el mismo formulario de entrega.
 * - DEC-AJ-09 (P-05): «¿Retira otra persona?». Si es así, nombre, apellido
 *   y teléfono obligatorios; no se piden vínculo, DNI ni autorización, y la
 *   garantía no cambia.
 */

import type { ContenidoEntrega, Orden } from "../../types/api";

/** Desde cuándo está lista y el aviso al cliente, que es un dato aparte. */
export function textoRetiro(
  listaDesde: string,
  aviso: string | null,
  formato: (iso: string) => string,
): string {
  return `Lista para retirar desde ${formato(listaDesde)} · ${
    aviso
      ? `aviso al cliente: ${formato(aviso)}`
      : "sin aviso al cliente (es opcional)"
  }.`;
}

/**
 * Falta el check-in y la entrega lo exige: el formulario de entrega lo
 * pregunta. Es la misma condición que ofrece «Registrar el check-in» sin
 * un resultado registrado.
 */
export function checkinPendiente(
  orden: Pick<Orden, "acciones_disponibles" | "recepcion">,
): boolean {
  return (
    orden.acciones_disponibles.some(
      (accion) => accion.codigo === "REGISTRAR_CHECKIN",
    ) && (orden.recepcion?.datos.checkin ?? null) === null
  );
}

/** El título del comprobante de la salida del equipo. */
export function tituloComprobanteEntrega(
  contenido: Pick<ContenidoEntrega, "tipo_entrega" | "entrega_y_garantia">,
): string {
  if (contenido.tipo_entrega === "DEVOLUCION_SIN_REPARACION") {
    return "Comprobante de devolución sin reparación";
  }
  return contenido.entrega_y_garantia
    ? "Comprobante de entrega y garantía"
    : "Comprobante de entrega";
}

/** Lo que el formulario pregunta sobre quién retira. */
export interface RetiroFormulario {
  otraPersona: boolean;
  nombre: string;
  apellido: string;
  telefono: string;
}

/**
 * Lo que falta para poder confirmar quién retira. Si retira el titular no
 * se pide nada más; si retira otra persona, nombre, apellido y teléfono.
 */
export function faltantesDelRetiro(retiro: RetiroFormulario): string[] {
  if (!retiro.otraPersona) return [];
  return (
    [
      ["nombre", retiro.nombre],
      ["apellido", retiro.apellido],
      ["teléfono", retiro.telefono],
    ] as const
  )
    .filter(([, valor]) => valor.trim() === "")
    .map(([campo]) => campo);
}

/** Quién retira, para la confirmación y el comprobante. */
export function descripcionQuienRetira(datos: {
  recibido_por: string | null;
  identificacion_receptor?: string | null;
  retira_otra_persona?: boolean | null;
  telefono_receptor?: string | null;
}): string {
  if (!datos.recibido_por) return "—";
  if (datos.retira_otra_persona === true) {
    return `${datos.recibido_por} (otra persona${
      datos.telefono_receptor ? ` · tel. ${datos.telefono_receptor}` : ""
    })`;
  }
  if (datos.retira_otra_persona === false) {
    return `${datos.recibido_por} (titular)`;
  }
  // Registro anterior a DEC-AJ-09: como se cargó, con su identificación.
  return `${datos.recibido_por}${
    datos.identificacion_receptor ? ` · ${datos.identificacion_receptor}` : ""
  }`;
}
