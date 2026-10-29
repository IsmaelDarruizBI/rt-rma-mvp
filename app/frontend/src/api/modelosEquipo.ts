/**
 * Catálogo técnico de modelos de equipo (propio de RMA, solo lectura).
 */

import type { ModeloEquipo } from "../types/api";
import { get } from "./client";

export function obtenerModelosEquipo(): Promise<ModeloEquipo[]> {
  return get<ModeloEquipo[]>("/api/catalogs/device-models");
}
