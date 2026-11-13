/**
 * Firma opcional de los documentos emitidos (DEC-MI-06): en pantalla o foto
 * del documento firmado. Ningún documento la exige.
 */

import { get, getArchivo, postArchivo } from "./client";

export type FormaFirma = "PANTALLA" | "FOTO_DOCUMENTO";

export interface FirmaDocumento {
  id: string;
  orden_id: string;
  documento_id: string;
  forma: FormaFirma;
  tipo_contenido: string;
  tamano_bytes: number;
  usuario_id: string;
  fecha: string;
  firmante: string | null;
}

export function listarFirmas(ordenId: string): Promise<FirmaDocumento[]> {
  return get<FirmaDocumento[]>(`/api/orders/${ordenId}/signatures`);
}

export function registrarFirma(
  ordenId: string,
  documentoId: string,
  usuarioId: string,
  forma: FormaFirma,
  imagen: Blob,
  firmante: string | null,
): Promise<FirmaDocumento[]> {
  const parametros = new URLSearchParams({ usuario_id: usuarioId, forma });
  if (firmante) parametros.set("firmante", firmante);
  return postArchivo<FirmaDocumento[]>(
    `/api/orders/${ordenId}/documents/${encodeURIComponent(documentoId)}/signatures?${parametros}`,
    imagen,
  );
}

export function imagenDeFirma(ordenId: string, firmaId: string): Promise<Blob> {
  return getArchivo(
    `/api/orders/${ordenId}/signatures/${encodeURIComponent(firmaId)}`,
  );
}
