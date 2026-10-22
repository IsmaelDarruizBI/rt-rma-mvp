/**
 * Compartir el comprobante de autorización por WhatsApp, sin integrar la
 * API de WhatsApp Business.
 *
 * - Si el navegador puede compartir archivos (Web Share API), se abre su
 *   menú de compartir con el PDF y el mensaje: el empleado elige WhatsApp.
 * - Si no, se descarga el PDF y se abre WhatsApp (wa.me) con el mensaje ya
 *   escrito y el teléfono del cliente, para adjuntarlo a mano.
 *
 * Nada de esto prueba que el cliente lo recibió: no se registra como
 * enviado ni como entregado.
 */

import type { ContenidoAutorizacion, ContenidoIngreso } from "../../types/api";

/**
 * El teléfono como lo pide wa.me (solo dígitos, con código de país), o
 * `null` si no se puede armar uno válido.
 *
 * Números argentinos: se quitan el 0 de la característica y el 15 del
 * celular, y se antepone 549 (+54 9). Un número con otro código de país
 * (escrito con + o 00) se usa tal cual.
 */
export function telefonoParaWhatsapp(
  telefono: string | null | undefined,
): string | null {
  if (!telefono) return null;
  const escrito = telefono.trim();
  let digitos = escrito.replace(/\D/g, "");
  // Un número de relleno (todo ceros) no es de nadie.
  if (/^0*$/.test(digitos)) return null;
  let conPais = escrito.startsWith("+");
  if (digitos.startsWith("00")) {
    digitos = digitos.slice(2);
    conPais = true;
  }
  if (conPais && !digitos.startsWith("54")) {
    return digitos.length >= 8 && digitos.length <= 15 ? digitos : null;
  }
  if (digitos.startsWith("54") && digitos.length >= 12) {
    digitos = digitos.slice(2);
    if (digitos.startsWith("9")) digitos = digitos.slice(1);
  }
  if (digitos.startsWith("0")) digitos = digitos.slice(1);
  // El 15 del celular va después de la característica (2 a 4 dígitos).
  if (digitos.length === 12) {
    const largo = [2, 3, 4].find(
      (candidato) => digitos.slice(candidato, candidato + 2) === "15",
    );
    if (largo !== undefined) {
      digitos = digitos.slice(0, largo) + digitos.slice(largo + 2);
    }
  }
  if (digitos.length !== 10 || /^0+$/.test(digitos)) return null;
  return `549${digitos}`;
}

function pesos(valor: string): string {
  const numero = Number(valor);
  if (Number.isNaN(numero)) return valor;
  return numero.toLocaleString("es-AR", {
    style: "currency",
    currency: "ARS",
    maximumFractionDigits: 2,
  });
}

/**
 * El texto que acompaña al PDF (comprobante de autorización o de ingreso).
 * No dice que sea un comprobante de pago ni que el cliente lo recibió.
 */
export function mensajeComprobante(
  contenido: ContenidoAutorizacion | ContenidoIngreso,
): string {
  const saludo = contenido.cliente
    ? `Hola ${contenido.cliente.nombre_apellido}!`
    : "Hola!";
  // Marca, modelo y variante (sin importar módulos: se prueba con node).
  const { marca, modelo, variante } = contenido.equipo;
  const equipo = [marca, modelo, variante].filter(Boolean).join(" ");
  const ingreso = contenido.tipo === "COMPROBANTE_INGRESO";
  const trabajos = contenido.trabajos
    .map((trabajo) => `• ${trabajo.nombre}: ${pesos(trabajo.precio)}`)
    .join("\n");
  const total = ingreso ? contenido.total : contenido.total_autorizado;
  const subtotal = ingreso ? contenido.subtotal : contenido.subtotal_autorizado;
  const descuento = contenido.descuento
    ? [
        `Subtotal: ${pesos(subtotal ?? total)}`,
        `Descuento (${contenido.descuento.descripcion}): -${pesos(contenido.descuento.importe)}`,
      ]
    : [];
  return [
    ingreso
      ? `${saludo} Te enviamos el comprobante de ingreso y autorización de ` +
        `la orden ${contenido.orden_id} (${equipo}).`
      : `${saludo} Te enviamos el comprobante de autorización de la orden ` +
        `${contenido.orden_id} (${equipo}).`,
    "",
    "Trabajos autorizados:",
    trabajos,
    ...descuento,
    `Total autorizado: ${pesos(total)}`,
    "",
    "No es un comprobante de pago.",
    contenido.empresa.nombre,
  ].join("\n");
}

/** wa.me con el mensaje; sin teléfono válido, WhatsApp pide el contacto. */
export function enlaceWhatsapp(
  telefono: string | null,
  mensaje: string,
): string {
  const texto = encodeURIComponent(mensaje);
  return telefono
    ? `https://wa.me/${telefono}?text=${texto}`
    : `https://wa.me/?text=${texto}`;
}

/** Cómo terminó el intento de compartir (nunca "enviado"). */
export type ResultadoCompartir =
  | { forma: "menu" }
  | { forma: "cancelado" }
  | { forma: "descarga"; enlace: string; abierto: boolean };

/** Descarga un archivo generado en el navegador. */
export function descargarArchivo(archivo: Blob, nombre: string): void {
  const url = URL.createObjectURL(archivo);
  const enlace = document.createElement("a");
  enlace.href = url;
  enlace.download = nombre;
  enlace.rel = "noopener";
  document.body.appendChild(enlace);
  enlace.click();
  enlace.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

/**
 * Comparte el PDF: menú del sistema si se puede adjuntar el archivo; si
 * no (o si falla), descarga el PDF y abre WhatsApp con el mensaje.
 */
export async function compartirPorWhatsapp({
  pdf,
  nombre,
  mensaje,
  telefono,
}: {
  pdf: Blob;
  nombre: string;
  mensaje: string;
  telefono: string | null;
}): Promise<ResultadoCompartir> {
  const archivo = new File([pdf], nombre, { type: "application/pdf" });
  const datos: ShareData = { files: [archivo], text: mensaje };
  if (
    typeof navigator.share === "function" &&
    typeof navigator.canShare === "function" &&
    navigator.canShare(datos)
  ) {
    try {
      await navigator.share(datos);
      return { forma: "menu" };
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") {
        return { forma: "cancelado" };
      }
      // Cualquier otro error: se sigue con la descarga.
    }
  }
  descargarArchivo(pdf, nombre);
  const enlace = enlaceWhatsapp(telefono, mensaje);
  const ventana = window.open(enlace, "_blank", "noopener");
  return { forma: "descarga", enlace, abierto: ventana !== null };
}
