/**
 * Ajustes funcionales, bloque 3: ingreso (DEC-AJ-05 a DEC-AJ-08).
 *
 * Lógica de presentación sin dependencias del DOM (se prueba con
 * `npm test`). No decide reglas: arma lo que se muestra o se envía con lo
 * que ya entrega el backend, que vuelve a validar todo.
 *
 * - DEC-AJ-05: «Trabajo solicitado» en texto libre; sin trabajos
 *   estandarizados el ingreso sigue por la revisión técnica y el
 *   comprobante de recepción confirma la custodia.
 * - DEC-AJ-07: «¿Se pudieron verificar las funcionalidades del equipo?»,
 *   obligatoria e informativa (no es el check-in de entrega).
 * - DEC-AJ-08: «Crear y generar el comprobante».
 * - DEC-AJ-06: «IMEI no disponible» y el IMEI real registrado después.
 */

import type {
  CanalComunicacion,
  DatosRecepcion,
  DocumentoEmitido,
  Equipo,
  TipoDocumento,
} from "../../types/api";

// --- DEC-AJ-07: verificación de funcionalidades --------------------------

/** Respuesta del formulario: sin elegir, Sí o No. */
export type RespuestaVerificacion = "" | "SI" | "NO";

export const PREGUNTA_VERIFICACION =
  "¿Se pudieron verificar las funcionalidades del equipo?";

export function verificacionDe(respuesta: RespuestaVerificacion): boolean | null {
  if (respuesta === "SI") return true;
  if (respuesta === "NO") return false;
  return null;
}

export function respuestaDe(valor: boolean | null | undefined): RespuestaVerificacion {
  if (valor === true) return "SI";
  if (valor === false) return "NO";
  return "";
}

/**
 * Cómo se muestra la respuesta del ingreso, o `null` si no se respondió.
 * Es informativa: no es el check-in de entrega.
 */
export function textoVerificacion(
  datos:
    | Pick<DatosRecepcion, "funcionalidades_verificadas" | "observaciones_verificacion">
    | null
    | undefined,
): string | null {
  const valor = datos?.funcionalidades_verificadas;
  if (valor === null || valor === undefined) return null;
  const respuesta = valor ? "Sí" : "No";
  const observaciones = (datos?.observaciones_verificacion ?? "").trim();
  return observaciones ? `${respuesta}. ${observaciones}` : respuesta;
}

/**
 * La referencia que se muestra junto al check-in de entrega (DEC-AJ-07):
 * la respuesta del ingreso, aclarando que no lo reemplaza.
 */
export function referenciaParaCheckin(
  datos:
    | Pick<DatosRecepcion, "funcionalidades_verificadas" | "observaciones_verificacion">
    | null
    | undefined,
): string {
  const texto = textoVerificacion(datos);
  return texto === null
    ? "Al ingresar no se registró si se pudieron verificar las funcionalidades."
    : `Al ingresar, ¿se pudieron verificar las funcionalidades? ${texto} ` +
        "(solo como referencia: no reemplaza este check-in).";
}

// --- Datos del alta -------------------------------------------------------

/** Lo que el alta agrega a la recepción (además de las observaciones). */
export function datosAgregadosDelIngreso(entrada: {
  trabajoSolicitado: string;
  verificacion: RespuestaVerificacion;
  observacionesVerificacion: string;
  imeiNoDisponible: boolean;
}): Pick<
  DatosRecepcion,
  | "trabajo_solicitado"
  | "funcionalidades_verificadas"
  | "observaciones_verificacion"
  | "imei_no_disponible"
> {
  return {
    trabajo_solicitado: entrada.trabajoSolicitado.trim() || null,
    funcionalidades_verificadas: verificacionDe(entrada.verificacion),
    observaciones_verificacion: entrada.observacionesVerificacion.trim() || null,
    imei_no_disponible: entrada.imeiNoDisponible,
  };
}

/**
 * Lo que falta para crear la Orden desde el formulario (además del cliente
 * y el equipo, que ya se controlan aparte).
 */
export function faltantesDelIngreso(entrada: {
  observaciones: string;
  verificacion: RespuestaVerificacion;
}): string[] {
  const faltan: string[] = [];
  if (!entrada.observaciones.trim()) {
    faltan.push("describir el equipo (observaciones)");
  }
  if (entrada.verificacion === "") {
    faltan.push("responder si se pudieron verificar las funcionalidades");
  }
  return faltan;
}

// --- DEC-AJ-08: crear y generar el comprobante ---------------------------

/** Qué comprobante genera «Crear y generar el comprobante». */
export type ComprobanteDelAlta = "INGRESO" | "RECEPCION";

export function comprobanteDelAlta(trabajoInicial: string | null): ComprobanteDelAlta {
  return trabajoInicial ? "INGRESO" : "RECEPCION";
}

export const TIPO_DEL_COMPROBANTE: Record<ComprobanteDelAlta, TipoDocumento> = {
  INGRESO: "COMPROBANTE_INGRESO",
  RECEPCION: "COMPROBANTE_RECEPCION",
};

/** Qué explica el formulario antes de «Crear y generar el comprobante». */
export function explicacionDelAlta(comprobante: ComprobanteDelAlta): string {
  return comprobante === "INGRESO"
    ? "Crea la Orden con el trabajo elegido y genera el comprobante de " +
        "ingreso y autorización: confirma que el equipo quedó en el local y " +
        "registra que el cliente autorizó el trabajo por el canal elegido."
    : "Sin trabajo estandarizado: crea la Orden, la envía a revisión técnica " +
        "y genera el comprobante de recepción, que confirma que el equipo " +
        "quedó en el local. El técnico define después los trabajos y el " +
        "cliente los autoriza.";
}

/** El canal con el que llega el formulario (BR-REP-028: se registra). */
export const CANAL_PREDETERMINADO: CanalComunicacion = "PRESENCIAL";

/**
 * El comprobante que el visor abre después de generarlo: el último emitido
 * de ese tipo, si es otro que el que ya estaba (`anterior`).
 */
export function comprobanteGenerado(
  emitidos: DocumentoEmitido[],
  tipo: TipoDocumento,
  anterior: string | null = null,
): DocumentoEmitido | null {
  const delTipo = emitidos.filter((documento) => documento.tipo === tipo);
  const ultimo = delTipo[delTipo.length - 1];
  return ultimo && ultimo.id !== anterior ? ultimo : null;
}

// --- DEC-AJ-06: IMEI no disponible e IMEI real ----------------------------

/**
 * Cómo se identifica el equipo: con su IMEI o, sin IMEI, con el
 * identificador interno, que no es un IMEI (provisorio si se marcó «IMEI no
 * disponible»).
 */
export function identificacionDelEquipo(
  equipo: Pick<Equipo, "id" | "imei">,
  imeiNoDisponible: boolean | null | undefined,
): { imei: string; provisorio: boolean } {
  if (equipo.imei) return { imei: equipo.imei, provisorio: false };
  if (imeiNoDisponible) {
    return {
      imei: `No disponible · se identifica con ${equipo.id} (provisorio, no es un IMEI)`,
      provisorio: true,
    };
  }
  return { imei: `Sin IMEI · se identifica con ${equipo.id}`, provisorio: false };
}

/**
 * El IMEI real no puede quedar vacío. No se valida el formato: el backend
 * tampoco lo hace (DEC-MI-11), y no se inventa una regla.
 */
export function imeiRealCompleto(imei: string): boolean {
  return imei.trim() !== "";
}

/** Un IMEI que ya tiene otro Equipo: el backend pide confirmarlo. */
export function esCoincidenciaDeImei(codigo: string | null | undefined): boolean {
  return codigo === "CONFIRMACION_REQUERIDA";
}
