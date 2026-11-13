/**
 * Motivo elegido de un catálogo (DEC-MI-15) o escrito libremente.
 *
 * - Sin motivo de catálogo, el texto es obligatorio (como siempre).
 * - Con un motivo que exige descripción («Otro»), el texto es obligatorio.
 * - Con cualquier otro motivo, el texto es un detalle opcional.
 *
 * El backend aplica las mismas reglas: esto solo habilita el botón.
 */

import type { MotivoOperativo } from "../../api/operativa";

export interface MotivoElegido {
  /** Código del catálogo, o `null` para el texto libre. */
  codigo: string | null;
  texto: string;
}

export const SIN_MOTIVO: MotivoElegido = { codigo: null, texto: "" };

export function motivosVigentes(
  motivos: readonly MotivoOperativo[],
): MotivoOperativo[] {
  return motivos.filter((motivo) => motivo.activo);
}

export function motivoCompleto(
  motivos: readonly MotivoOperativo[],
  elegido: MotivoElegido,
): boolean {
  const texto = elegido.texto.trim();
  if (elegido.codigo === null) return texto !== "";
  const motivo = motivos.find((m) => m.codigo === elegido.codigo);
  if (!motivo || !motivo.activo) return false;
  return !motivo.requiere_descripcion || texto !== "";
}

/** Etiqueta del campo de texto según lo elegido. */
export function etiquetaDelTexto(
  motivos: readonly MotivoOperativo[],
  elegido: MotivoElegido,
  etiquetaLibre: string,
): string {
  if (elegido.codigo === null) return etiquetaLibre;
  const motivo = motivos.find((m) => m.codigo === elegido.codigo);
  return motivo?.requiere_descripcion
    ? "Descripción (obligatoria)"
    : "Detalle (opcional)";
}
