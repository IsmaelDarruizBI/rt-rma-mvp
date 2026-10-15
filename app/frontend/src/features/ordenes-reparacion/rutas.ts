/**
 * Rutas de la aplicación en el hash de la URL (`#/ordenes/OR-000001`).
 *
 * El hash no viaja al servidor: una URL copiada, una recarga o los botones
 * Atrás y Adelante funcionan en cualquier hosting estático (Vercel
 * incluido) sin reglas de reescritura ni librerías de routing. Navegar solo
 * cambia el hash: nunca envía comandos al backend.
 */

export type Ruta =
  | { pantalla: "inicio" }
  | { pantalla: "ordenes" }
  | { pantalla: "nueva" }
  | { pantalla: "orden"; ordenId: string }
  | { pantalla: "taller" }
  | { pantalla: "inventario" };

/** Al entrar: las tareas del usuario. */
export const RUTA_INICIAL: Ruta = { pantalla: "inicio" };

/** `#/ordenes/OR-000001` -> la ruta; lo desconocido va al inicio. */
export function parsearRuta(hash: string): Ruta {
  const partes = hash
    .replace(/^#/, "")
    .split("?")[0]
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
  }
}

/** ¿El hash ya está escrito en su forma canónica? */
export function esCanonico(hash: string): boolean {
  return hash === hashDe(parsearRuta(hash));
}
