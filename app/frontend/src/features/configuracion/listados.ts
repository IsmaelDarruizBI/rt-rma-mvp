/**
 * Reglas de pantalla de los catálogos de Configuración (CFG-04, CFG-06,
 * CFG-08), sin React.
 */

/**
 * El listado después de un alta o una edición, sin volver a pedirlo: el
 * elemento que devolvió la API reemplaza al anterior (mismo id) o se agrega
 * al final.
 */
export function conElemento<T>(lista: readonly T[], elemento: T, id: (x: T) => string): T[] {
  const clave = id(elemento);
  return lista.some((x) => id(x) === clave)
    ? lista.map((x) => (id(x) === clave ? elemento : x))
    : [...lista, elemento];
}

/** Un precio con hasta dos decimales, no negativo (la API lo valida igual). */
export function precioValido(texto: string): boolean {
  return /^\d+(\.\d{1,2})?$/.test(texto.trim());
}

/** CFG-06: la pantalla muestra solo los plazos con y sin check-in. */
export function textoGarantias(tipo: {
  garantia_con_checkin?: number | null;
  garantia_sin_checkin?: number | null;
}): string {
  return `${tipo.garantia_con_checkin ?? 90} con check-in · ${tipo.garantia_sin_checkin ?? 30} sin check-in`;
}

/**
 * CFG-08 (DF-3): la interfaz ofrece solo Ingreso y Equipo listo para
 * retirar, en Configuración y en la Orden. La API las marca con `visible`;
 * con una API anterior (sin el campo) decide esta lista. Las demás no se
 * borran: siguen en la base y en la API.
 */
export const PLANTILLAS_VISIBLES = ["INGRESO", "LISTO_PARA_RETIRAR"] as const;

export function esPlantillaVisible(plantilla: { codigo: string; visible?: boolean }): boolean {
  return plantilla.visible ?? (PLANTILLAS_VISIBLES as readonly string[]).includes(plantilla.codigo);
}
