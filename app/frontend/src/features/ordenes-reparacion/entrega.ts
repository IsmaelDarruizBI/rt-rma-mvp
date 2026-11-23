/**
 * Entrega del equipo (ajustes funcionales, bloque 2): funciones puras de la
 * pantalla, sin React, para probarlas con `npm test`.
 *
 * - DEC-AJ-03: el aviso al cliente es opcional; el retiro demorado corre
 *   desde que la Orden está lista para retirar y la fecha del aviso se
 *   muestra aparte.
 */

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
