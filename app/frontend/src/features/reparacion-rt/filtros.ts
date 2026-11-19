/**
 * Reparación RT: filtros en la URL y presentación (funciones puras).
 *
 * Los filtros viven en el hash (`#/reparacion-rt?q=13+pro&sede=Centro`):
 * una URL copiada, una recarga o Atrás muestran el mismo listado. La
 * búsqueda y el filtrado se ejecutan en el backend; acá solo se arma el
 * pedido y se rotula la respuesta.
 *
 * Toda relación con una Orden es una COINCIDENCIA SUGERIDA rotulada con su
 * criterio: nunca se presenta como vínculo, Orden activa ni historial del
 * producto (DEC-RT-03).
 */

import type {
  AvisoProductoRt,
  CoincidenciaSugerida,
  CriterioCoincidencia,
  EstadoCopiaRt,
  ProductoRtResumen,
} from "../../api/productosRt";
import { ESTADO_WORKFLOW, ORIGEN, etiqueta } from "../ordenes-reparacion/etiquetas.ts";

export type FiltroOrdenRma = "" | "SIN_COINCIDENCIAS" | "CON_SUGERENCIAS";

export interface FiltrosRt {
  q: string;
  /** Sedes exactas; "" es «sin sede». */
  sedes: string[];
  ordenRma: FiltroOrdenRma;
  /** También los que salieron de Reparación, eliminados o ausentes. */
  incluirFuera: boolean;
  pagina: number;
}

export const FILTROS_RT_INICIALES: FiltrosRt = {
  q: "",
  sedes: [],
  ordenRma: "",
  incluirFuera: false,
  pagina: 1,
};

export const TAMANO_PAGINA = 50;

const ORDENES_RMA: readonly FiltroOrdenRma[] = [
  "",
  "SIN_COINCIDENCIAS",
  "CON_SUGERENCIAS",
];

/** La consulta del hash (`q=...&sede=...`) como filtros válidos. */
export function filtrosDeConsulta(consulta: string): FiltrosRt {
  const parametros = new URLSearchParams(consulta.replace(/^\?/, ""));
  const ordenRma = (parametros.get("orden_rma") ?? "") as FiltroOrdenRma;
  const pagina = Number.parseInt(parametros.get("pagina") ?? "1", 10);
  const sedes: string[] = [];
  for (const sede of parametros.getAll("sede")) {
    const limpia = sede.trim();
    if (!sedes.includes(limpia)) sedes.push(limpia);
  }
  return {
    q: (parametros.get("q") ?? "").trim().slice(0, 200),
    sedes,
    ordenRma: ORDENES_RMA.includes(ordenRma) ? ordenRma : "",
    incluirFuera: parametros.get("fuera") === "1",
    pagina: Number.isFinite(pagina) && pagina > 1 ? pagina : 1,
  };
}

/** Los filtros como consulta canónica del hash ("" sin filtros). */
export function consultaDeFiltros(filtros: FiltrosRt): string {
  const parametros = new URLSearchParams();
  if (filtros.q.trim()) parametros.set("q", filtros.q.trim());
  for (const sede of filtros.sedes) parametros.append("sede", sede);
  if (filtros.ordenRma) parametros.set("orden_rma", filtros.ordenRma);
  if (filtros.incluirFuera) parametros.set("fuera", "1");
  if (filtros.pagina > 1) parametros.set("pagina", String(filtros.pagina));
  return parametros.toString();
}

/** La forma canónica de una consulta (para normalizar la URL). */
export function normalizarConsultaRt(consulta: string): string {
  return consultaDeFiltros(filtrosDeConsulta(consulta));
}

/** El pedido al backend (`GET /api/rt-products`). */
export function parametrosApi(
  filtros: FiltrosRt,
  tamano = TAMANO_PAGINA,
): URLSearchParams {
  const parametros = new URLSearchParams();
  if (filtros.q.trim()) parametros.set("q", filtros.q.trim());
  for (const sede of filtros.sedes) parametros.append("sede", sede);
  if (filtros.ordenRma) parametros.set("orden_rma", filtros.ordenRma);
  if (filtros.incluirFuera) parametros.set("incluir_fuera", "true");
  parametros.set("pagina", String(filtros.pagina));
  parametros.set("tamano", String(tamano));
  return parametros;
}

/** Cambia un filtro y vuelve a la primera página. */
export function conFiltro(
  filtros: FiltrosRt,
  cambio: Partial<Omit<FiltrosRt, "pagina">>,
): FiltrosRt {
  return { ...filtros, ...cambio, pagina: 1 };
}

/** Marca o desmarca una sede (varias a la vez). */
export function alternarSede(filtros: FiltrosRt, sede: string): FiltrosRt {
  const sedes = filtros.sedes.includes(sede)
    ? filtros.sedes.filter((s) => s !== sede)
    : [...filtros.sedes, sede];
  return conFiltro(filtros, { sedes });
}

export function filtrosActivos(filtros: FiltrosRt): boolean {
  return consultaDeFiltros({ ...filtros, pagina: 1 }) !== "";
}

export function totalPaginas(total: number, tamano = TAMANO_PAGINA): number {
  return Math.max(1, Math.ceil(total / tamano));
}

// --- Presentación ------------------------------------------------------------

/** «iPhone 13 Pro 256 GB Graphite», o el TipoProducto si no se encontró. */
export function etiquetaEquipo(producto: {
  modelo: string | null;
  capacidad: string | null;
  color: string | null;
  descripcion_tipo?: string | null;
}): string {
  const partes = [producto.modelo, producto.capacidad, producto.color].filter(
    (parte): parte is string => Boolean(parte),
  );
  if (partes.length) return partes.join(" ");
  return producto.descripcion_tipo || "Equipo sin TipoProducto en el catálogo";
}

/** Los últimos dígitos del IMEI, para el listado («…4 5678»). */
export function imeiAbreviado(imei: string | null): string {
  if (!imei) return "—";
  const limpio = imei.replace(/\s+/g, "");
  if (limpio.length <= 5) return limpio;
  return `…${limpio.slice(-5, -4)} ${limpio.slice(-4)}`;
}

/** El valor de un filtro de sede, con su nombre. */
export function nombreSede(sede: string | null): string {
  return sede === null || sede === "" ? "Sin sede" : sede;
}

export const CRITERIO: Record<CriterioCoincidencia, string> = {
  REFERENCIA_RT: "referencia RT",
  IMEI: "IMEI",
};

/** «sugerida por referencia RT e IMEI». */
export function textoCriterios(criterios: CriterioCoincidencia[]): string {
  const orden: CriterioCoincidencia[] = ["REFERENCIA_RT", "IMEI"];
  const textos = orden
    .filter((c) => criterios.includes(c))
    .map((c) => CRITERIO[c]);
  if (textos.length === 0) return "sugerida por coincidencia";
  if (textos.length === 1) return `sugerida por ${textos[0]}`;
  return `sugerida por ${textos[0]} e ${textos[1]}`;
}

/** «¿OR-000041? En cola (sugerida por referencia RT)»: siempre con signos
 *  de pregunta y el criterio; nunca como «la Orden del producto». */
export function textoCoincidencia(coincidencia: CoincidenciaSugerida): string {
  const estado = etiqueta(ESTADO_WORKFLOW, coincidencia.estado_workflow);
  const cerrada = coincidencia.cerrada ? ", cerrada" : "";
  return `¿${coincidencia.orden_id}? ${estado}${cerrada} (${textoCriterios(
    coincidencia.criterios,
  )})`;
}

export function origenDeOrden(origen: string): string {
  return etiqueta(ORIGEN, origen);
}

/** Resumen de las coincidencias de un producto, para la fila del listado. */
export function resumenCoincidencias(producto: ProductoRtResumen): string {
  const coincidencias = producto.coincidencias_sugeridas;
  if (!coincidencias.length) return "Sin coincidencias";
  if (coincidencias.length === 1) return textoCoincidencia(coincidencias[0]);
  return `${coincidencias.length} coincidencias sugeridas`;
}

export const AVISO: Record<AvisoProductoRt, string> = {
  SIN_IMEI: "Sin IMEI en Gestión RT: se busca por ID o modelo.",
  IMEI_INVALIDO: "El IMEI no tiene 15 dígitos: no se usa para sugerir Órdenes.",
  IMEI_VERIFICADOR_INCORRECTO:
    "El dígito verificador del IMEI no coincide (se informa; se usa igual).",
  IMEI_REPETIDO:
    "Otro producto tiene el mismo IMEI: no se usa para sugerir Órdenes.",
  TIPO_NO_ENCONTRADO:
    "El TipoProducto no está en el catálogo de Ventas: faltan modelo, capacidad y color.",
  TIPO_ELIMINADO: "El TipoProducto está eliminado en Ventas.",
  SEDE_NO_CONFIRMADA: "La sede no es una de las confirmadas.",
  CONFLICTO_ORIGEN:
    "El ID vino repetido en Gestión RT: se muestran los datos anteriores.",
  CAMBIO_IDENTIDAD: "Cambió el IMEI o el TipoProducto de este ID en Gestión RT.",
  FUERA_DE_REPARACION: "Ya no está en Reparación en Gestión RT.",
  ELIMINADO_EN_ORIGEN: "Eliminado en Gestión RT.",
  AUSENTE_DEL_ORIGEN: "La última actualización no lo trajo de Gestión RT.",
};

export function textoAviso(aviso: AvisoProductoRt): string {
  return AVISO[aviso] ?? aviso;
}

export type NivelCopia =
  | "no_habilitada"
  | "sin_origen"
  | "nunca"
  | "error_sin_copia"
  | "error_con_copia"
  | "desactualizada"
  | "al_dia";

/** En qué estado está la copia, para el encabezado de la pantalla. */
export function nivelCopia(copia: EstadoCopiaRt): NivelCopia {
  if (!copia.habilitado) return "no_habilitada";
  const fallo =
    copia.ultima !== null && copia.ultima.resultado !== "EXITOSA";
  if (copia.datos_del === null) {
    if (fallo) return "error_sin_copia";
    return copia.sincronizable ? "nunca" : "sin_origen";
  }
  if (fallo) return "error_con_copia";
  return copia.desactualizada ? "desactualizada" : "al_dia";
}

/** «hace 3 h», «hace 2 días»: la antigüedad de los datos. */
export function hace(iso: string, ahora: Date = new Date()): string {
  const minutos = Math.max(
    0,
    Math.round((ahora.getTime() - new Date(iso).getTime()) / 60000),
  );
  if (minutos < 1) return "recién";
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.round(minutos / 60);
  if (horas < 48) return `hace ${horas} h`;
  return `hace ${Math.round(horas / 24)} días`;
}

/** Lo principal de un intento EXITOSA, en una línea. */
export function resumenSincronizacion(contadores: Record<string, number>): string {
  const n = (clave: string) => contadores[clave] ?? 0;
  const partes = [`${n("en_reparacion")} en reparación`];
  for (const [clave, texto] of [
    ["nuevos", "nuevos"],
    ["salieron", "salieron"],
    ["volvieron", "volvieron"],
    ["eliminados", "eliminados"],
    ["ausentes", "ausentes"],
  ] as const) {
    if (n(clave)) partes.push(`${n(clave)} ${texto}`);
  }
  return partes.join(" · ");
}
