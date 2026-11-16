/**
 * UX-05: imprimir un comprobante ya generado.
 *
 * Usa el MISMO PDF que se descarga (lectura del documento emitido): no
 * emite, no registra ni duplica documentos. Abre el diálogo de impresión
 * del navegador desde un marco oculto; si el navegador no lo permite (por
 * ejemplo, algunos Safari), abre el PDF en otra pestaña para imprimirlo
 * desde ahí.
 */

export type FormaImpresion = "dialogo" | "pestana";

/** Cuánto vive el marco oculto: el diálogo de impresión lo sigue usando. */
const VIDA_DEL_MARCO_MS = 120_000;

export function imprimirPdf(pdf: Blob): Promise<FormaImpresion> {
  const url = URL.createObjectURL(pdf);
  const limpiar = (marco?: HTMLIFrameElement) =>
    setTimeout(() => {
      marco?.remove();
      URL.revokeObjectURL(url);
    }, VIDA_DEL_MARCO_MS);

  const enPestana = (marco?: HTMLIFrameElement): FormaImpresion => {
    window.open(url, "_blank", "noopener");
    limpiar(marco);
    return "pestana";
  };

  return new Promise((resolver) => {
    const marco = document.createElement("iframe");
    marco.setAttribute("aria-hidden", "true");
    marco.title = "Impresión del comprobante";
    Object.assign(marco.style, {
      position: "fixed",
      right: "0",
      bottom: "0",
      width: "0",
      height: "0",
      border: "0",
      visibility: "hidden",
    });
    marco.onload = () => {
      try {
        const ventana = marco.contentWindow;
        if (!ventana) throw new Error("sin ventana");
        ventana.focus();
        ventana.print();
        limpiar(marco);
        resolver("dialogo");
      } catch {
        resolver(enPestana(marco));
      }
    };
    marco.src = url;
    document.body.appendChild(marco);
  });
}
