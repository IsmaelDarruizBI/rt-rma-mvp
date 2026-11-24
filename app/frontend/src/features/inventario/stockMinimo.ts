/**
 * Stock mínimo por insumo (DEC-AJ-11), sin React. El backend calcula el
 * estado contra el DISPONIBLE (físico − reservado) y con lo que está en
 * camino (solicitudes pendientes y órdenes de compra abiertas); acá solo se
 * nombra, se valida lo que se carga y se arma la solicitud sugerida. No es
 * un faltante: «Solo faltantes» sigue aparte.
 */

export type EstadoReposicion =
  | "SIN_MINIMO"
  | "SUFICIENTE"
  | "BAJO_MINIMO"
  | "BAJO_MINIMO_REPOSICION_SOLICITADA";

export type OrigenSolicitud = "MANUAL" | "FALTANTE" | "STOCK_MINIMO";

export const NOMBRE_REPOSICION: Record<EstadoReposicion, string> = {
  SIN_MINIMO: "Sin mínimo",
  SUFICIENTE: "Suficiente",
  BAJO_MINIMO: "Bajo mínimo",
  BAJO_MINIMO_REPOSICION_SOLICITADA: "Bajo mínimo · reposición solicitada",
};

/** Tono del indicador: «alerta» sin reposición pedida, «aviso» con ella. */
export function tonoReposicion(
  estado: EstadoReposicion | undefined,
): "alerta" | "aviso" | null {
  if (estado === "BAJO_MINIMO") return "alerta";
  if (estado === "BAJO_MINIMO_REPOSICION_SOLICITADA") return "aviso";
  return null;
}

export function bajoMinimo(estado: EstadoReposicion | undefined): boolean {
  return tonoReposicion(estado) !== null;
}

/** Vacío (sin mínimo) o un número ≥ 0 con hasta tres decimales; admite
 * coma decimal. Devuelve el valor que se envía o el error. */
export function leerStockMinimo(
  texto: string,
): { valor: string | null; error: string | null } {
  const limpio = texto.trim().replace(",", ".");
  if (limpio === "") return { valor: null, error: null };
  if (!/^\d+(\.\d{1,3})?$/.test(limpio)) {
    return {
      valor: null,
      error: "El stock mínimo es un número mayor o igual a cero, con hasta tres decimales.",
    };
  }
  return { valor: limpio, error: null };
}

export const NOMBRE_ORIGEN: Record<OrigenSolicitud, string> = {
  MANUAL: "manual",
  FALTANTE: "por faltante",
  STOCK_MINIMO: "por stock mínimo",
};

export interface SugerenciaReposicion {
  insumo_id: string;
  sugerido: string;
  ordenes: string[];
  /** Ausentes en un backend anterior: se lee como faltante. */
  motivo?: "FALTANTE" | "STOCK_MINIMO";
  por_faltante?: string;
  por_minimo?: string;
  stock_minimo?: string | null;
}

/** Por qué se sugiere: faltante, mínimo o ambos. */
export function causaSugerencia(s: SugerenciaReposicion): string {
  if (s.motivo !== "STOCK_MINIMO") return "Por faltante";
  return Number(s.por_faltante ?? "0") > 0
    ? `Por faltante (${s.por_faltante}) y stock mínimo (${s.por_minimo})`
    : `Por stock mínimo (${s.stock_minimo ?? "?"})`;
}

/** La solicitud que se confirma desde la sugerencia, con su origen. */
export function solicitudDeSugerencia(s: SugerenciaReposicion): {
  insumo_id: string;
  cantidad: string;
  motivo: string;
  origen: "FALTANTE" | "STOCK_MINIMO";
  ordenes: string[];
} {
  const minimo = s.motivo === "STOCK_MINIMO";
  const faltante = !minimo || Number(s.por_faltante ?? "0") > 0;
  return {
    insumo_id: s.insumo_id,
    cantidad: s.sugerido,
    motivo:
      minimo && faltante
        ? "Faltante de Órdenes que esperan recursos y reposición hasta el stock mínimo."
        : minimo
          ? "Reposición hasta el stock mínimo."
          : "Faltante de Órdenes que esperan recursos.",
    origen: minimo ? "STOCK_MINIMO" : "FALTANTE",
    ordenes: s.ordenes,
  };
}

/** La línea de un insumo en una bandeja de Inicio: cantidades y, si tiene
 * mínimo, el mínimo y lo que está en camino. */
export function lineaInsumoBandeja(insumo: {
  disponible: string;
  stock_fisico: string;
  reservado: string;
  stock_minimo?: string | null;
  en_camino?: string;
}): string {
  const partes = [
    `Disponible ${insumo.disponible}`,
    `en stock ${insumo.stock_fisico}`,
    `reservado ${insumo.reservado}`,
  ];
  if (insumo.stock_minimo != null) {
    partes.push(`mínimo ${insumo.stock_minimo}`);
    if (Number(insumo.en_camino ?? "0") > 0) partes.push(`en camino ${insumo.en_camino}`);
  }
  return partes.join(" · ");
}
