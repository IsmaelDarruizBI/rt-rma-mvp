/**
 * Rutas de la aplicación en el hash de la URL (`#/ordenes/OR-000001`).
 *
 * El hash no viaja al servidor: una URL copiada, una recarga o los botones
 * Atrás y Adelante funcionan en cualquier hosting estático (Vercel
 * incluido) sin reglas de reescritura ni librerías de routing. Navegar solo
 * cambia el hash: nunca envía comandos al backend.
 *
 * Reparación RT lleva sus filtros en la consulta del hash
 * (`#/reparacion-rt?sede=Centro`) y la ficha abierta en la ruta
 * (`#/reparacion-rt/900001?...`), siempre en forma canónica.
 */

import {
  esSeccionConfiguracion,
  type SeccionConfiguracion,
} from "../configuracion/secciones.ts";
import { normalizarConsultaRt } from "../reparacion-rt/filtros.ts";

export type Ruta =
  | { pantalla: "inicio" }
  | { pantalla: "ordenes" }
  | { pantalla: "nueva" }
  | { pantalla: "orden"; ordenId: string }
  | { pantalla: "taller" }
  | { pantalla: "inventario" }
  | { pantalla: "reportes" }
  | { pantalla: "compras" }
  | { pantalla: "configuracion"; seccion?: SeccionConfiguracion }
  | { pantalla: "reparacion-rt"; consulta: string; productoId?: string };

/** Al entrar: las tareas del usuario. */
export const RUTA_INICIAL: Ruta = { pantalla: "inicio" };

/** `#/ordenes/OR-000001` -> la ruta; lo desconocido va al inicio. */
export function parsearRuta(hash: string): Ruta {
  const [camino, ...resto] = hash.replace(/^#/, "").split("?");
  const partes = camino
    .split("/")
    .filter(Boolean)
    .map((parte) => {
      try {
        return decodeURIComponent(parte);
      } catch {
        return parte;
      }
    });
  if (partes.length === 1) {
    if (partes[0] === "inicio") return { pantalla: "inicio" };
    if (partes[0] === "taller") return { pantalla: "taller" };
    if (partes[0] === "inventario") return { pantalla: "inventario" };
    if (partes[0] === "reportes") return { pantalla: "reportes" };
    if (partes[0] === "compras") return { pantalla: "compras" };
    if (partes[0] === "configuracion") return { pantalla: "configuracion" };
  }
  // CFG-05: cada subsección de Configuración tiene su ruta.
  if (
    partes[0] === "configuracion" &&
    partes.length === 2 &&
    esSeccionConfiguracion(partes[1])
  ) {
    return { pantalla: "configuracion", seccion: partes[1] };
  }
  if (partes[0] === "reparacion-rt" && partes.length <= 2) {
    const consulta = normalizarConsultaRt(resto.join("?"));
    const productoId = partes[1]?.trim();
    return productoId
      ? { pantalla: "reparacion-rt", consulta, productoId }
      : { pantalla: "reparacion-rt", consulta };
  }
  if (partes[0] === "ordenes") {
    if (partes.length === 1) return { pantalla: "ordenes" };
    if (partes.length === 2 && partes[1] === "nueva") {
      return { pantalla: "nueva" };
    }
    if (partes.length === 2 && partes[1].trim()) {
      return { pantalla: "orden", ordenId: partes[1].trim() };
    }
  }
  return RUTA_INICIAL;
}

/** La ruta como hash, lista para un `href` o `location.hash`. */
export function hashDe(ruta: Ruta): string {
  switch (ruta.pantalla) {
    case "inicio":
      return "#/inicio";
    case "ordenes":
      return "#/ordenes";
    case "taller":
      return "#/taller";
    case "nueva":
      return "#/ordenes/nueva";
    case "orden":
      return `#/ordenes/${encodeURIComponent(ruta.ordenId)}`;
    case "inventario":
      return "#/inventario";
    case "reportes":
      return "#/reportes";
    case "compras":
      return "#/compras";
    case "configuracion":
      return ruta.seccion
        ? `#/configuracion/${ruta.seccion}`
        : "#/configuracion";
    case "reparacion-rt": {
      const producto = ruta.productoId
        ? `/${encodeURIComponent(ruta.productoId)}`
        : "";
      return `#/reparacion-rt${producto}${ruta.consulta ? `?${ruta.consulta}` : ""}`;
    }
  }
}

/** ¿El hash ya está escrito en su forma canónica? */
export function esCanonico(hash: string): boolean {
  return hash === hashDe(parsearRuta(hash));
}
