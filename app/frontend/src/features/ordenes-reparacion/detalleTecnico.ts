/**
 * BF-07 (D-01, 23/11/2026): quién ve la información técnica en el detalle de
 * la Orden (antecedentes del equipo, ejecuciones y movimientos de insumos,
 * devoluciones de insumos, insumos previstos por trabajo y los bloques
 * técnicos del historial).
 *
 * Lo decide el permiso configurable DETALLE_TECNICO_CONSULTAR, que llega con
 * la sesión. Sin la lista de permisos (una API anterior) rigen sus roles
 * predeterminados, los mismos del backend: Técnico, Coordinación RMA y
 * Administración. Con varios roles se aplica la unión.
 *
 * Es solo PRESENTACIÓN: la API sigue devolviendo esos datos a quien consulta
 * la Orden. No es un control de seguridad.
 */

import { puede, type ConRoles } from "../../lib/roles.ts";

export const PERMISO_DETALLE_TECNICO = "DETALLE_TECNICO_CONSULTAR";

export const VEN_DETALLE_TECNICO: readonly string[] = [
  "TECNICO",
  "COORDINADOR_RMA",
  "ADMINISTRADOR",
];

export function veDetalleTecnico(actor: ConRoles | null): boolean {
  return puede(actor, PERMISO_DETALLE_TECNICO, VEN_DETALLE_TECNICO);
}
