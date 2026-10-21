/**
 * Fotos del equipo (UAT-010): validación y reducción en el navegador antes
 * de subirlas. Una foto del celular pesa varios MB; reducida a 1600 px de
 * lado mayor en JPEG queda en unos cientos de KB y se ve bien.
 *
 * `dimensionesReducidas` y `motivoArchivoInvalido` no usan el DOM: se
 * prueban con `npm test`. `reducirFoto` sí (canvas).
 */

/** Fotos por Orden (UAT-011): el mismo tope que aplica el backend. */
export const MAX_FOTOS = 10;
export const LADO_MAXIMO = 1600;
export const CALIDAD_JPEG = 0.82;
/** El mismo tope que aplica el backend a cada foto. */
export const MAX_BYTES_FOTO = 8 * 1024 * 1024;
/** Lo que se acepta elegir; se sube siempre como JPEG, PNG o WebP. */
export const TIPOS_ELEGIBLES = /^image\//;

/** Las dimensiones para que el lado mayor no pase de `maximo`. */
export function dimensionesReducidas(
  ancho: number,
  alto: number,
  maximo: number = LADO_MAXIMO,
): { ancho: number; alto: number } {
  const mayor = Math.max(ancho, alto);
  if (mayor <= maximo) return { ancho, alto };
  const escala = maximo / mayor;
  return {
    ancho: Math.max(1, Math.round(ancho * escala)),
    alto: Math.max(1, Math.round(alto * escala)),
  };
}

/**
 * Cuántas de las elegidas entran: el tope cuenta las guardadas y las que
 * esperan revisión (las de más quedan afuera, con aviso).
 */
export function fotosQueCaben(
  guardadas: number,
  pendientes: number,
  elegidas: number,
): number {
  return Math.max(0, Math.min(elegidas, MAX_FOTOS - guardadas - pendientes));
}

/** Por qué no se puede subir ese archivo, o `null` si se puede. */
export function motivoArchivoInvalido(tipo: string, tamano: number): string | null {
  if (!TIPOS_ELEGIBLES.test(tipo)) return "no es una imagen";
  if (tamano <= 0) return "está vacío";
  if (tamano > MAX_BYTES_FOTO) return "pesa más de 8 MB";
  return null;
}

/**
 * La foto reducida en JPEG. Si el navegador no puede decodificarla (por
 * ejemplo, un formato que no soporta), se devuelve el archivo original y
 * el backend decide: acepta JPEG, PNG y WebP.
 */
export async function reducirFoto(archivo: File): Promise<Blob> {
  try {
    const imagen = await createImageBitmap(archivo);
    const { ancho, alto } = dimensionesReducidas(imagen.width, imagen.height);
    const lienzo = document.createElement("canvas");
    lienzo.width = ancho;
    lienzo.height = alto;
    const contexto = lienzo.getContext("2d");
    if (!contexto) return archivo;
    contexto.drawImage(imagen, 0, 0, ancho, alto);
    imagen.close();
    const reducida = await new Promise<Blob | null>((resolver) =>
      lienzo.toBlob(resolver, "image/jpeg", CALIDAD_JPEG),
    );
    // El original solo si ya es un tipo aceptado y pesa menos (un HEIC del
    // iPhone puede pesar menos que su JPEG, pero el backend no lo acepta).
    const aceptado = /^image\/(jpeg|png|webp)$/.test(archivo.type);
    if (!reducida) return archivo;
    return aceptado && archivo.size <= reducida.size ? archivo : reducida;
  } catch {
    return archivo;
  }
}
