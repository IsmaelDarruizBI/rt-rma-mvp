/**
 * Búsqueda de clientes por DNI (UAT-010). Solo lee: primero nuestras
 * Órdenes y, si hay una fuente externa autorizada configurada, esa fuente.
 * El resultado se revisa antes de usarlo; nunca se guarda solo.
 */

import type { BusquedaCliente } from "../types/api";
import { get } from "./client";

export function buscarClientePorDni(
  dni: string,
  usuarioId: string,
  /** `false`: solo nuestra base (la comprobación previa al alta). */
  externa = true,
): Promise<BusquedaCliente> {
  const consulta = new URLSearchParams({
    dni,
    usuario_id: usuarioId,
    externa: String(externa),
  });
  return get<BusquedaCliente>(`/api/clients/lookup?${consulta}`);
}
