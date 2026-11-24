/**
 * Clasificación de insumos (DEC-AJ-14): categorías de dos niveles,
 * fabricantes de repuestos y los modelos de equipo para la compatibilidad.
 *
 * La lectura (`/api/catalogs/supply-classification`) la usan Inventario,
 * Compras y la elección de piezas; la administración, Configuración con
 * INSUMO_GESTIONAR y solo sobre PostgreSQL.
 */

import type {
  CategoriaInsumo,
  ClasificacionInsumos,
  FabricanteRepuesto,
} from "../features/inventario/clasificacion";
import { get, post, put } from "./client";

export function obtenerClasificacion(): Promise<ClasificacionInsumos> {
  return get<ClasificacionInsumos>("/api/catalogs/supply-classification");
}

export interface ClasificacionAdmin extends ClasificacionInsumos {
  /** false en el modo JSON: los catálogos son de solo lectura. */
  editable: boolean;
}

export function obtenerClasificacionAdmin(): Promise<ClasificacionAdmin> {
  return get<ClasificacionAdmin>("/api/admin/supply-classification");
}

/** El código lo genera la API (CAT-NNN). `padre_id`: solo en el alta. */
export function crearCategoria(
  usuarioId: string,
  datos: { nombre: string; padre_id: string | null; activo: boolean },
): Promise<CategoriaInsumo> {
  return post<CategoriaInsumo>("/api/admin/supply-categories", { usuario_id: usuarioId, ...datos });
}

export function editarCategoria(
  usuarioId: string,
  codigo: string,
  datos: { nombre: string; activo: boolean },
): Promise<CategoriaInsumo> {
  return put<CategoriaInsumo>(`/api/admin/supply-categories/${encodeURIComponent(codigo)}`, {
    usuario_id: usuarioId,
    ...datos,
  });
}

/** El código lo genera la API (FAB-NNN). */
export function crearFabricante(
  usuarioId: string,
  datos: { nombre: string; activo: boolean },
): Promise<FabricanteRepuesto> {
  return post<FabricanteRepuesto>("/api/admin/supply-manufacturers", { usuario_id: usuarioId, ...datos });
}

export function editarFabricante(
  usuarioId: string,
  codigo: string,
  datos: { nombre: string; activo: boolean },
): Promise<FabricanteRepuesto> {
  return put<FabricanteRepuesto>(`/api/admin/supply-manufacturers/${encodeURIComponent(codigo)}`, {
    usuario_id: usuarioId,
    ...datos,
  });
}
