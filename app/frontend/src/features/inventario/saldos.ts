/**
 * Saldos por lote de un insumo (DEC-MI-10), sin React. El saldo de cada
 * lote sale del libro; el «stock sin lote identificado» es el físico menos
 * los lotes. La disponibilidad sigue siendo una por insumo.
 */

export type ControlInsumo = "SIN_LOTE" | "LOTE" | "SERIE";

export interface SaldoLote {
  lote: {
    id: string;
    insumo_id: string;
    numero: string;
    serie: boolean;
    origen: "COMPRA" | "INGRESO_MANUAL";
    referencia: string | null;
    usuario_id: string;
    fecha: string;
  };
  saldo: string;
}

export interface SaldosDeInsumo {
  insumo_id: string;
  control: ControlInsumo;
  stock_fisico: string;
  lotes: SaldoLote[];
  sin_lote_identificado: string;
}

export const NOMBRE_CONTROL: Record<ControlInsumo, string> = {
  SIN_LOTE: "Sin lote",
  LOTE: "Por lote",
  SERIE: "Por número de serie",
};

export interface OpcionLote {
  valor: string;
  texto: string;
}

/** Opciones para elegir de dónde sale una cantidad: primero el stock sin
 * lote identificado (`""`), después los lotes con saldo. Un lote sin saldo
 * solo aparece si es el que ya estaba elegido (para no perderlo). */
export function opcionesDeLote(saldos: SaldosDeInsumo, elegido = ""): OpcionLote[] {
  return [
    { valor: "", texto: `Stock sin lote identificado (${saldos.sin_lote_identificado})` },
    ...saldos.lotes
      .filter(({ lote, saldo }) => Number(saldo) > 0 || lote.id === elegido)
      .map(({ lote, saldo }) => ({
        valor: lote.id,
        texto: `${lote.serie ? "Serie" : "Lote"} ${lote.numero} (${saldo})`,
      })),
  ];
}

/** Hay que mostrar el detalle por lote (el insumo se controla o tuvo lotes). */
export function muestraLotes(saldos: SaldosDeInsumo): boolean {
  return saldos.control !== "SIN_LOTE" || saldos.lotes.length > 0;
}

export function origenDelLote({ lote }: SaldoLote): string {
  const origen = lote.origen === "COMPRA" ? "compra" : "ingreso manual";
  return lote.referencia ? `${origen} ${lote.referencia}` : origen;
}

/** Los saldos cuadran con el físico: Σ lotes + sin lote = físico. */
export function saldosConciliados(saldos: SaldosDeInsumo): boolean {
  const lotes = saldos.lotes.reduce((total, { saldo }) => total + Number(saldo), 0);
  return Math.abs(lotes + Number(saldos.sin_lote_identificado) - Number(saldos.stock_fisico)) < 1e-9;
}
