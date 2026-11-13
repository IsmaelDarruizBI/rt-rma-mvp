/**
 * Presentación de las comunicaciones (DEC-MI-08), sin React: se prueba con
 * node. Nunca dice «entregado» ni «leído».
 */

import type { ComunicacionCliente } from "../../types/api";

export function estadoDeComunicacion(comunicacion: ComunicacionCliente): string {
  if (comunicacion.confirmacion === null) {
    return "WhatsApp abierto · falta confirmar si se envió";
  }
  return comunicacion.confirmacion.enviado
    ? "Enviado (confirmado por el usuario)"
    : "No se envió (confirmado por el usuario)";
}

/** Texto de un consentimiento vigente. */
export function textoConsentimiento(vigente: boolean | null): string {
  if (vigente === null) return "Sin registro";
  return vigente ? "Otorgado" : "Rechazado o revocado";
}
