/**
 * Equipo del ingreso con el catálogo técnico de modelos (propio de RMA).
 *
 * Se busca por marca, modelo, variante o número de modelo del fabricante
 * («15 pro max», «A2849», «iphone 16e»), sin distinguir mayúsculas ni
 * acentos, y se elige una coincidencia. Si no está, se carga a mano con
 * marca, modelo y variante. Capacidad y color no identifican el tipo de
 * equipo: el color es opcional y va aparte. Una Orden anterior con un
 * producto del catálogo de Ventas lo conserva mientras no se elija otro.
 *
 * Solo lógica, sin React: la pantalla está en `SelectorEquipo.tsx`.
 */

import type { Equipo, ModeloEquipo } from "../../types/api";

/** Minúsculas, sin acentos y con los espacios colapsados. */
export function normalizar(texto: string): string {
  return texto
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/\s+/g, " ")
    .trim();
}

/** Todo lo que se puede buscar de un modelo, normalizado. */
function textoDe(modelo: ModeloEquipo): string {
  return normalizar([modelo.nombre, ...modelo.numeros_modelo].join(" "));
}

/**
 * Los modelos que tienen todas las palabras de la consulta (en cualquier
 * orden; «promax» también encuentra «Pro Max»). Primero los que tienen
 * cada palabra al comienzo de una palabra, después los de nombre más
 * corto: «15 pro» propone «iPhone 15 Pro» antes que «iPhone 15 Pro Max».
 */
export function buscarModelos(
  modelos: ModeloEquipo[],
  consulta: string,
  limite = 10,
): ModeloEquipo[] {
  const palabras = normalizar(consulta).split(" ").filter(Boolean);
  if (palabras.length === 0) return [];
  const candidatos = modelos.flatMap((modelo, indice) => {
    const texto = textoDe(modelo);
    const junto = texto.replace(/ /g, "");
    if (!palabras.every((palabra) => texto.includes(palabra) || junto.includes(palabra))) {
      return [];
    }
    const comienzos = palabras.filter((palabra) =>
      ` ${texto}`.includes(` ${palabra}`),
    ).length;
    return [{ modelo, comienzos, largo: modelo.nombre.length, indice }];
  });
  candidatos.sort(
    (a, b) => b.comienzos - a.comienzos || a.largo - b.largo || a.indice - b.indice,
  );
  return candidatos.slice(0, limite).map((candidato) => candidato.modelo);
}

// --- Lo que eligió Recepción ----------------------------------------------

export interface EquipoElegido {
  modo: "catalogo" | "manual";
  /** El modelo elegido del catálogo técnico. */
  modeloId: string | null;
  /** Lo que se ve al elegirlo (también si ya no se ofrece). */
  nombreModelo: string | null;
  /** Carga manual. */
  marca: string;
  modelo: string;
  variante: string;
  /** Opcional en los dos modos: es del equipo físico. */
  color: string;
  /**
   * Orden anterior con un producto del catálogo de Ventas: se conserva
   * (con su capacidad y color) mientras no se elija otro equipo.
   */
  productoVentas: Equipo | null;
}

export const EQUIPO_VACIO: EquipoElegido = {
  modo: "catalogo",
  modeloId: null,
  nombreModelo: null,
  marca: "",
  modelo: "",
  variante: "",
  color: "",
  productoVentas: null,
};

/** Para corregir el equipo de una Orden: parte de lo que tiene. */
export function equipoElegidoDe(equipo: Equipo): EquipoElegido {
  const base = {
    ...EQUIPO_VACIO,
    marca: equipo.marca,
    modelo: equipo.modelo,
    variante: equipo.variante ?? "",
    color: equipo.color ?? "",
  };
  if (equipo.modelo_tecnico_id) {
    return {
      ...base,
      modeloId: equipo.modelo_tecnico_id,
      nombreModelo: [equipo.marca, equipo.modelo, equipo.variante]
        .filter(Boolean)
        .join(" "),
    };
  }
  if (equipo.tipo_producto_id) return { ...base, productoVentas: equipo };
  return { ...base, modo: "manual" };
}

/** Elegir un modelo de la lista (deja de conservar el de Ventas). */
export function elegirModelo(
  elegido: EquipoElegido,
  modelo: ModeloEquipo,
): EquipoElegido {
  return {
    ...elegido,
    modo: "catalogo",
    modeloId: modelo.id,
    nombreModelo: modelo.nombre,
    productoVentas: null,
  };
}

/** «Cambiar»: vuelve a buscar sin modelo elegido. */
export function quitarModelo(elegido: EquipoElegido): EquipoElegido {
  return { ...elegido, modeloId: null, nombreModelo: null, productoVentas: null };
}

/**
 * Cómo se está cargando de verdad: sin catálogo (y sin nada que
 * conservar), a mano aunque se haya pedido el catálogo.
 */
export function modoEfectivo(
  hayCatalogo: boolean,
  elegido: EquipoElegido,
): "catalogo" | "manual" {
  if (elegido.modo === "manual") return "manual";
  return hayCatalogo || elegido.modeloId || elegido.productoVentas
    ? "catalogo"
    : "manual";
}

export type DatosDelEquipo =
  | { modelo_tecnico_id: string; color: string | null }
  | { tipo_producto_id: string }
  | { marca: string; modelo: string; variante: string | null; color: string | null };

/**
 * Lo que va al backend; `null` si falta elegir o completar algo. Del
 * producto de Ventas que se conserva no se manda el color: el backend
 * mantiene el que tenía.
 */
export function datosDelEquipo(
  hayCatalogo: boolean,
  elegido: EquipoElegido,
): DatosDelEquipo | null {
  const color = elegido.color.trim() || null;
  if (modoEfectivo(hayCatalogo, elegido) === "manual") {
    const marca = elegido.marca.trim();
    const modelo = elegido.modelo.trim();
    if (!marca || !modelo) return null;
    return { marca, modelo, variante: elegido.variante.trim() || null, color };
  }
  if (elegido.modeloId) return { modelo_tecnico_id: elegido.modeloId, color };
  if (elegido.productoVentas?.tipo_producto_id) {
    return { tipo_producto_id: elegido.productoVentas.tipo_producto_id };
  }
  return null;
}
