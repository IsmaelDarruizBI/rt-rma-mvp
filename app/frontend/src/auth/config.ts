/**
 * Cómo se inicia sesión en este build.
 *
 * - `demo`: el acceso de prueba de siempre (usuarios ficticios validados
 *   en el navegador). Solo para desarrollo local (`npm run dev`).
 * - `supabase`: usuario y contraseña con Supabase Auth (cada usuario tiene una
 *   identidad interna, ver `usuario.ts`; los empleados no usan su correo). Es el único modo
 *   admitido en un build de producción (UAT): sin configuración, la app
 *   muestra el error en lugar de caer al acceso de prueba.
 *
 * La clave publicable de Supabase es pública por diseño (va en el
 * navegador); nunca se usa una clave de servicio.
 */

import { DOMINIO_USUARIOS_POR_DEFECTO, dominioValido } from "./usuario.ts";

export interface EntornoAuth {
  VITE_AUTH_MODO?: string;
  VITE_SUPABASE_URL?: string;
  VITE_SUPABASE_PUBLISHABLE_KEY?: string;
  /** Dominio de las identidades internas (opcional; por defecto reservado). */
  VITE_AUTH_DOMINIO_USUARIOS?: string;
  /** `import.meta.env.DEV`: true con el servidor de desarrollo de Vite. */
  DEV: boolean;
}

export type ConfiguracionAuth =
  | { modo: "demo" }
  | { modo: "supabase"; url: string; clave: string; dominio: string }
  | { modo: "invalida"; motivo: string };

export function configuracionAuth(entorno: EntornoAuth): ConfiguracionAuth {
  const pedido = (entorno.VITE_AUTH_MODO ?? "").trim().toLowerCase();
  const modo = pedido || (entorno.DEV ? "demo" : "supabase");

  if (modo === "demo") {
    if (!entorno.DEV) {
      return {
        modo: "invalida",
        motivo:
          "El acceso de prueba solo existe en desarrollo local: este build " +
          "necesita VITE_AUTH_MODO=supabase.",
      };
    }
    return { modo: "demo" };
  }
  if (modo !== "supabase") {
    return { modo: "invalida", motivo: `VITE_AUTH_MODO desconocido: ${modo}.` };
  }
  const url = (entorno.VITE_SUPABASE_URL ?? "").trim().replace(/\/+$/, "");
  const clave = (entorno.VITE_SUPABASE_PUBLISHABLE_KEY ?? "").trim();
  if (!url || !clave) {
    return {
      modo: "invalida",
      motivo:
        "Falta configurar el acceso: VITE_SUPABASE_URL y " +
        "VITE_SUPABASE_PUBLISHABLE_KEY.",
    };
  }
  if (!url.startsWith("https://") && !entorno.DEV) {
    return { modo: "invalida", motivo: "VITE_SUPABASE_URL debe usar https." };
  }
  if (clave.startsWith("sb_secret_") || rolDeClaveJwt(clave) === "service_role") {
    return {
      modo: "invalida",
      motivo: "La clave configurada es secreta: usá la clave publicable.",
    };
  }
  const dominio = (
    entorno.VITE_AUTH_DOMINIO_USUARIOS ?? DOMINIO_USUARIOS_POR_DEFECTO
  )
    .trim()
    .toLowerCase();
  if (!dominioValido(dominio)) {
    return {
      modo: "invalida",
      motivo: "VITE_AUTH_DOMINIO_USUARIOS no es un dominio válido.",
    };
  }
  return { modo: "supabase", url, clave, dominio };
}

/** El `role` de una clave antigua en formato JWT (`anon` o `service_role`). */
function rolDeClaveJwt(clave: string): string | null {
  const partes = clave.split(".");
  if (partes.length !== 3) return null;
  try {
    const base64 = partes[1].replace(/-/g, "+").replace(/_/g, "/");
    const datos = JSON.parse(atob(base64.padEnd(Math.ceil(base64.length / 4) * 4, "=")));
    return typeof datos.role === "string" ? datos.role : null;
  } catch {
    return null;
  }
}
