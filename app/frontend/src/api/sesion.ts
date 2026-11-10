/** El usuario de RMA de la sesión actual (Supabase Auth). */

import type { Usuario } from "../types/api";
import { get } from "./client";

export function obtenerUsuarioActual(): Promise<Usuario> {
  return get<Usuario>("/api/me");
}
