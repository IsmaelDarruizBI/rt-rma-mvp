/**
 * Importación masiva de precios por modelo (DEC-AJ-13), sin React.
 *
 * La planilla viaja tal cual como cuerpo del pedido (sin multipart): un
 * `.xlsx`, un `.csv` o las celdas pegadas desde Google Sheets o Excel, que
 * llegan como texto separado por tabulaciones. El tipo se decide por la
 * extensión del archivo, no por lo que declare el navegador (Windows
 * declara los `.csv` como Excel). La API vuelve a validar todo al aplicar.
 */

import type {
  EstadoPrecioImportado,
  ResumenImportacion,
  VistaPreviaImportacion,
} from "../../api/configuracion";

export const TIPO_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
export const TIPO_CSV = "text/csv";
export const TIPO_PEGADO = "text/tab-separated-values";
/** El mismo límite que la API. */
export const MAX_BYTES_PLANILLA = 2 * 1024 * 1024;

export interface Planilla {
  cuerpo: Blob;
  /** Nombre del archivo, para la auditoría; vacío en las celdas pegadas. */
  nombre: string | null;
}

/** El tipo de contenido según la extensión, o `null` si no se admite. */
export function tipoDeArchivo(nombre: string): string | null {
  const extension = nombre.toLowerCase().split(".").pop() ?? "";
  if (extension === "xlsx") return TIPO_XLSX;
  if (extension === "csv") return TIPO_CSV;
  if (extension === "tsv" || extension === "txt") return TIPO_PEGADO;
  return null;
}

/** La planilla de un archivo elegido, o el motivo por el que no sirve. */
export function planillaDeArchivo(
  archivo: Blob,
  nombre: string,
): Planilla | { error: string } {
  const tipo = tipoDeArchivo(nombre);
  if (tipo === null) {
    return {
      error: nombre.toLowerCase().endsWith(".xls")
        ? "Es un Excel antiguo (.xls): guardalo como .xlsx o como CSV."
        : "Elegí un archivo .xlsx o .csv.",
    };
  }
  if (archivo.size === 0) return { error: "El archivo está vacío." };
  if (archivo.size > MAX_BYTES_PLANILLA) return { error: "El archivo supera los 2 MB." };
  return { cuerpo: new Blob([archivo], { type: tipo }), nombre };
}

/** Las celdas pegadas; `null` si no hay nada. */
export function planillaPegada(texto: string): Planilla | null {
  if (texto.trim() === "") return null;
  return { cuerpo: new Blob([texto], { type: TIPO_PEGADO }), nombre: null };
}

/** La consulta de la vista previa y de aplicar. */
export function consultaImportacion(usuarioId: string, nombre: string | null): string {
  const parametros = new URLSearchParams({ usuario_id: usuarioId });
  if (nombre) parametros.set("nombre", nombre);
  return parametros.toString();
}

function plural(cantidad: number, singular: string, varios: string): string {
  return `${cantidad} ${cantidad === 1 ? singular : varios}`;
}

/** «2 precios nuevos, 1 actualizado, 30 sin cambios y 4 celdas vacías». */
export function textoResumen(resumen: ResumenImportacion): string {
  const partes = [
    plural(resumen.nuevos, "precio nuevo", "precios nuevos"),
    plural(resumen.actualizados, "actualizado", "actualizados"),
    `${resumen.sin_cambio} sin cambios`,
    plural(resumen.vacias, "celda vacía", "celdas vacías"),
  ];
  const ultima = partes.pop()!;
  return `${partes.join(", ")} y ${ultima}`;
}

/** Aplicar solo sin errores, con algún cambio y sobre PostgreSQL. */
export function puedeAplicar(vista: VistaPreviaImportacion | null): boolean {
  return vista !== null && vista.aplicable && vista.editable !== false;
}

/** Por qué no se puede aplicar todavía (o `null` si se puede). */
export function motivoParaNoAplicar(vista: VistaPreviaImportacion | null): string | null {
  if (vista === null) return "Primero revisá la vista previa.";
  if (vista.errores.length > 0) {
    return `Corregí ${plural(vista.errores.length, "error", "errores")} en la planilla y volvé a revisarla: no se aplica nada mientras haya errores.`;
  }
  if (vista.cambios.length === 0) return "La planilla no cambia ningún precio.";
  if (vista.editable === false) {
    return "En este entorno (modo JSON) los catálogos son de solo lectura.";
  }
  return null;
}

export function etiquetaEstado(estado: EstadoPrecioImportado): string {
  return estado === "NUEVO" ? "Nuevo" : "Cambia";
}

/** «C5: mensaje», o solo el mensaje si no es de una celda. */
export function textoObservacion(observacion: { celda: string | null; mensaje: string }): string {
  return observacion.celda ? `${observacion.celda}: ${observacion.mensaje}` : observacion.mensaje;
}

export function nombrePlantilla(formato: "xlsx" | "csv", hoy: Date = new Date()): string {
  const fecha = [
    hoy.getFullYear(),
    String(hoy.getMonth() + 1).padStart(2, "0"),
    String(hoy.getDate()).padStart(2, "0"),
  ].join("");
  return `precios-por-modelo-${fecha}.${formato}`;
}
