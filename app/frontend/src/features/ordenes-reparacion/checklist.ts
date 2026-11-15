/**
 * Reglas de pantalla del checklist de recepción (DC12), sin React: qué
 * preguntas se muestran, qué se envía y qué se informa cuando no hay
 * tipos de equipo. Los Tipos de Equipo vienen del catálogo de Ventas de
 * Gestión RT (copia de solo lectura); RMA no los crea.
 */

import type {
  CatalogoChecklist,
  OrigenTiposEquipo,
  PreguntaChecklist,
  TipoEquipo,
} from "../../api/checklist";

/** Valor del selector de una pregunta: "" (sin registrar), `R:<opción>` o
 * `NO_REALIZADA`. */
export type ValorRespuesta = string;

export const NO_REALIZADA = "NO_REALIZADA";

/** Las preguntas vigentes de un tipo, en su orden de presentación. */
export function preguntasDelTipo(
  catalogo: Pick<CatalogoChecklist, "preguntas"> | null,
  tipo: string,
): PreguntaChecklist[] {
  return (catalogo?.preguntas ?? [])
    .filter((p) => p.tipo_equipo_id === tipo && p.activa)
    .sort((a, b) => a.orden - b.orden || a.id.localeCompare(b.id));
}

/** Lo que se envía: solo lo registrado; «sin registrar» no viaja. */
export function respuestasParaEnviar(respuestas: Record<string, ValorRespuesta>) {
  return Object.entries(respuestas)
    .filter(([, valor]) => valor)
    .map(([pregunta_id, valor]) => ({
      pregunta_id,
      respuesta: valor.startsWith("R:") ? valor.slice(2) : null,
      no_realizada: valor === NO_REALIZADA,
    }));
}

/** Se puede registrar: hay tipo y, si es una corrección, motivo. */
export function puedeRegistrarChecklist(
  tipo: string,
  esCorreccion: boolean,
  motivo: string,
): boolean {
  return tipo !== "" && (!esCorreccion || motivo.trim() !== "");
}

/** El tipo que se propone al corregir: el de la Orden, si sigue vigente. */
export function tipoPropuesto(
  tipos: TipoEquipo[],
  tipoDeLaOrden: { id: string } | null | undefined,
): string {
  if (!tipoDeLaOrden) return "";
  return tipos.some((t) => t.id === tipoDeLaOrden.id && t.activo) ? tipoDeLaOrden.id : "";
}

/** Por qué no se puede completar un checklist, o null si se puede. */
export function motivoSinChecklist(
  catalogo: Pick<CatalogoChecklist, "tipos" | "origen"> | null,
): string | null {
  if (!catalogo) return "No se pudo leer el catálogo del checklist.";
  if (catalogo.tipos.some((t) => t.activo)) return null;
  if (catalogo.origen && !catalogo.origen.definido) {
    return "El checklist no está disponible: falta definir qué dato del catálogo de Ventas es el tipo de equipo.";
  }
  return "Todavía no hay tipos de equipo: Administración los actualiza desde el catálogo de Ventas.";
}

/** Texto del origen de los tipos para Configuración. */
export function textoOrigen(origen: OrigenTiposEquipo | undefined): string {
  if (!origen) return "";
  if (!origen.definido) return origen.aviso ?? "Columna de origen sin definir.";
  const fuente = origen.origen ?? "sin origen configurado";
  const fecha = origen.ultima_sincronizacion
    ? `última actualización ${origen.ultima_sincronizacion.slice(0, 16).replace("T", " ")}`
    : "nunca actualizado";
  return `Catálogo de Ventas (${origen.campo}) · ${fuente} · ${fecha}`;
}

/** Nuevo orden de presentación al mover una pregunta un lugar: la lista
 * queda numerada 1..n (sin empates) y se devuelven solo las preguntas cuyo
 * orden cambia, para guardarlas. [] si no se puede mover. */
export function moverPregunta(
  preguntas: PreguntaChecklist[],
  id: string,
  sentido: -1 | 1,
): PreguntaChecklist[] {
  const lista = [...preguntas].sort((a, b) => a.orden - b.orden || a.id.localeCompare(b.id));
  const i = lista.findIndex((p) => p.id === id);
  const j = i + sentido;
  if (i < 0 || j < 0 || j >= lista.length) return [];
  [lista[i], lista[j]] = [lista[j], lista[i]];
  return lista
    .map((p, k) => ({ ...p, orden: k + 1 }))
    .filter((p) => preguntas.find((q) => q.id === p.id)?.orden !== p.orden);
}
