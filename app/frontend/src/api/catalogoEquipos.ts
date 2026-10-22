/**
 * Catálogo de equipos de Ventas. El alta lee la copia del backend (nunca
 * el origen); sincronizar la actualiza desde el origen configurado
 * (Administración o Coordinación RMA).
 */

import type { CatalogoEquipos, SincronizacionCatalogo } from "../types/api";
import { get, post } from "./client";

export function obtenerCatalogoEquipos(): Promise<CatalogoEquipos> {
  return get<CatalogoEquipos>("/api/catalogs/equipment");
}

export function sincronizarCatalogoEquipos(
  usuarioId: string,
): Promise<SincronizacionCatalogo> {
  const consulta = new URLSearchParams({ usuario_id: usuarioId });
  return post<SincronizacionCatalogo>(
    `/api/catalogs/equipment/sync?${consulta}`,
    {},
  );
}
