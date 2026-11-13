/**
 * Lotes y series de un insumo (DEC-MI-10).
 *
 * El saldo de cada lote sale del libro; el «stock sin lote identificado» es
 * el físico menos los lotes: el stock que había antes de controlar el
 * insumo por lote, sin números inventados. La disponibilidad sigue siendo
 * una por insumo.
 */

import { useEffect, useState } from "react";

import { get } from "../../api/client";
import { Campo, colores, estiloInput } from "../../components/ui";

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

export function leerSaldos(insumoId: string): Promise<SaldosDeInsumo> {
  return get<SaldosDeInsumo>(
    `/api/inventory/${encodeURIComponent(insumoId)}/lots`,
  );
}

/** Saldos de un insumo; `version` fuerza releerlos después de operar. */
export function useSaldosLotes(
  insumoId: string | null,
  version = 0,
): SaldosDeInsumo | null {
  const [saldos, setSaldos] = useState<SaldosDeInsumo | null>(null);
  useEffect(() => {
    if (!insumoId) return;
    let vigente = true;
    leerSaldos(insumoId)
      .then((datos) => vigente && setSaldos(datos))
      .catch(() => vigente && setSaldos(null));
    return () => {
      vigente = false;
    };
  }, [insumoId, version]);
  return saldos;
}

export function LotesDelInsumo({ saldos }: { saldos: SaldosDeInsumo | null }) {
  if (!saldos) return null;
  return (
    <div style={{ margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
      <p style={{ margin: "0.6rem 0 0.3rem", fontWeight: 600, fontSize: "0.9rem" }}>
        Lotes · control: {NOMBRE_CONTROL[saldos.control]}
      </p>
      {saldos.control === "SIN_LOTE" && saldos.lotes.length === 0 ? (
        <p style={{ margin: 0, color: colores.suave }}>
          El insumo no se controla por lote.
        </p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: "1.1rem" }}>
          {saldos.lotes.map(({ lote, saldo }) => (
            <li key={lote.id}>
              {lote.serie ? "Serie" : "Lote"} {lote.numero}: {saldo}
              <span style={{ color: colores.suave }}>
                {" "}
                · {lote.origen === "COMPRA" ? "compra" : "ingreso manual"}
                {lote.referencia ? ` ${lote.referencia}` : ""}
              </span>
            </li>
          ))}
          <li>
            Stock sin lote identificado: {saldos.sin_lote_identificado}
          </li>
        </ul>
      )}
    </div>
  );
}

/** Elegir de dónde sale una cantidad: un lote con saldo o el stock sin
 * lote identificado (`""`). */
export function SelectorLote({
  saldos,
  valor,
  onCambio,
  etiqueta = "Lote de donde sale",
  deshabilitado = false,
}: {
  saldos: SaldosDeInsumo;
  valor: string;
  onCambio: (loteId: string) => void;
  etiqueta?: string;
  deshabilitado?: boolean;
}) {
  return (
    <Campo etiqueta={etiqueta}>
      <select
        value={valor}
        onChange={(e) => onCambio(e.target.value)}
        disabled={deshabilitado}
        style={estiloInput}
      >
        <option value="">
          Stock sin lote identificado ({saldos.sin_lote_identificado})
        </option>
        {saldos.lotes
          .filter(({ saldo }) => Number(saldo) > 0 || valor !== "")
          .map(({ lote, saldo }) => (
            <option key={lote.id} value={lote.id}>
              {lote.serie ? "Serie" : "Lote"} {lote.numero} ({saldo})
            </option>
          ))}
      </select>
    </Campo>
  );
}
