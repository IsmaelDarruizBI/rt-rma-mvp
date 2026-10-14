/**
 * Llamadas a la API de inventario operativo.
 *
 * El backend calcula reservado y disponible y valida rol, motivo,
 * duplicados y confirmaciones; acá solo se arma el request.
 */

import type {
  DetalleInsumo,
  MovimientoInventario,
  ResultadoMovimientoStock,
  ResultadoRevalidacion,
  SituacionInsumo,
  TipoMovimientoInsumo,
} from "../types/api";
import { get, post } from "./client";

function consulta(parametros: Record<string, string | null | undefined>) {
  const valores = Object.entries(parametros).filter(
    (par): par is [string, string] => Boolean(par[1]),
  );
  return valores.length ? `?${new URLSearchParams(valores)}` : "";
}

export function listarInventario(
  buscar: string | null,
  soloFaltantes: boolean,
): Promise<SituacionInsumo[]> {
  return get<SituacionInsumo[]>(
    `/api/inventory${consulta({
      buscar,
      solo_faltantes: soloFaltantes ? "true" : null,
    })}`,
  );
}

export function obtenerInsumo(insumoId: string): Promise<DetalleInsumo> {
  return get<DetalleInsumo>(`/api/inventory/${insumoId}`);
}

export function listarMovimientos(
  insumoId: string | null,
  tipo: TipoMovimientoInsumo | null,
): Promise<MovimientoInventario[]> {
  return get<MovimientoInventario[]>(
    `/api/inventory/movements${consulta({ insumo_id: insumoId, tipo })}`,
  );
}

export interface DatosMovimientoStock {
  motivo: string;
  referencia: string | null;
  /** Clave del envío: un reintento no se aplica dos veces. */
  operacion_id: string;
}

/** Ingreso de existencias (Administración o Coordinación). */
export function registrarIngreso(
  insumoId: string,
  usuarioId: string,
  cantidad: string,
  datos: DatosMovimientoStock,
): Promise<ResultadoMovimientoStock> {
  return post<ResultadoMovimientoStock>(`/api/inventory/${insumoId}/receipts`, {
    usuario_id: usuarioId,
    cantidad,
    ...datos,
  });
}

/**
 * Ajuste como diferencia de unidades (+ suma, − resta). `confirmado` es la
 * confirmación explícita que el backend exige en todo ajuste negativo.
 */
export function registrarAjuste(
  insumoId: string,
  usuarioId: string,
  diferencia: string,
  datos: DatosMovimientoStock,
  confirmado: boolean,
): Promise<ResultadoMovimientoStock> {
  return post<ResultadoMovimientoStock>(
    `/api/inventory/${insumoId}/adjustments`,
    { usuario_id: usuarioId, diferencia, confirmado, ...datos },
  );
}

/** Revalida las Órdenes que esperan recursos con el stock actual. */
export function revalidarOrdenes(
  usuarioId: string,
): Promise<ResultadoRevalidacion> {
  return post<ResultadoRevalidacion>("/api/inventory/revalidate-orders", {
    usuario_id: usuarioId,
  });
}
