/**
 * DNI del cliente en el alta (UAT-010). Sin dependencias del DOM:
 * se prueban con `npm test`.
 */

/**
 * El DNI solo con dígitos (7 u 8, sin ceros de más a la izquierda), o
 * `null` si no es válido. Acepta puntos, espacios o guiones al escribirlo.
 * Es la misma regla que valida el backend.
 */
export function normalizarDni(texto: string): string | null {
  const limpio = texto.replace(/[\s.-]/g, "");
  if (!/^\d{7,8}$/.test(limpio)) return null;
  const sinCeros = limpio.replace(/^0+/, "");
  return sinCeros.length >= 7 ? sinCeros : null;
}
