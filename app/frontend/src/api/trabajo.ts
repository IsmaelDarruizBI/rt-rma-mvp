/**
 * Bandejas de trabajo y taller: consultas de solo lectura.
 *
 * El backend decide qué Órdenes van en cada bandeja, en qué orden y qué
 * puede resolver el usuario elegido. Tomar una Orden sigue siendo el
 * comando de siempre (`tomarOrden` en `./ordenes`).
 */

import type { Bandejas } from "../types/api";
import { get } from "./client";

export function obtenerBandejas(usuarioId: string): Promise<Bandejas> {
  return get<Bandejas>(
    `/api/work/inbox?${new URLSearchParams({ usuario_id: usuarioId })}`,
  );
}

export function obtenerTaller(usuarioId: string): Promise<Bandejas> {
  return get<Bandejas>(
    `/api/work/workshop?${new URLSearchParams({ usuario_id: usuarioId })}`,
  );
}
