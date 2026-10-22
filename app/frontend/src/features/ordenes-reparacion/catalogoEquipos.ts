/**
 * Selector de equipos del catálogo de Ventas: Modelo → Variante →
 * Capacidad → Color, siempre con las combinaciones que existen.
 *
 * Cada nivel ofrece solo lo que existe para lo elegido arriba; si hay una
 * sola opción, se elige sola; si cambia un nivel, lo de abajo se conserva
 * si sigue existiendo y si no, se borra. Los cuatro niveles juntos son UN
 * producto del catálogo: su `tp_id` sale de ahí, nunca se arma.
 *
 * Sin DOM ni React: se prueba con `npm test`.
 */

import type {
  CatalogoEquipos,
  CapacidadCatalogo,
  ColorCatalogo,
  Equipo,
  ModeloCatalogo,
  VarianteCatalogo,
} from "../../types/api";

/** Valor de la versión estándar en el selector (`variante: null`). */
export const VARIANTE_ESTANDAR = "__estandar__";
export const ETIQUETA_ESTANDAR = "Estándar";
export const ETIQUETA_COLOR_GENERICO = "Otro / sin especificar";
/** Valor del color genérico en el selector (`color: null`). */
export const COLOR_GENERICO = "__generico__";

/** Lo elegido en cada nivel ("" = todavía nada). */
export interface SeleccionCatalogo {
  modelo: string;
  variante: string;
  capacidad: string;
  color: string;
}

export const SELECCION_VACIA: SeleccionCatalogo = {
  modelo: "",
  variante: "",
  capacidad: "",
  color: "",
};

export interface Opcion {
  valor: string;
  etiqueta: string;
}

export function claveModelo(modelo: ModeloCatalogo): string {
  return `${modelo.marca}|${modelo.modelo}`;
}

function claveVariante(variante: VarianteCatalogo): string {
  return variante.variante ?? VARIANTE_ESTANDAR;
}

function claveColor(color: ColorCatalogo): string {
  return color.color ?? COLOR_GENERICO;
}

function hayVariasMarcas(catalogo: CatalogoEquipos): boolean {
  return new Set(catalogo.modelos.map((modelo) => modelo.marca)).size > 1;
}

function modeloDe(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): ModeloCatalogo | undefined {
  return catalogo.modelos.find(
    (modelo) => claveModelo(modelo) === seleccion.modelo,
  );
}

function varianteDe(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): VarianteCatalogo | undefined {
  return modeloDe(catalogo, seleccion)?.variantes.find(
    (variante) => claveVariante(variante) === seleccion.variante,
  );
}

function capacidadDe(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): CapacidadCatalogo | undefined {
  return varianteDe(catalogo, seleccion)?.capacidades.find(
    (capacidad) => capacidad.capacidad === seleccion.capacidad,
  );
}

function colorDe(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): ColorCatalogo | undefined {
  return capacidadDe(catalogo, seleccion)?.colores.find(
    (color) => claveColor(color) === seleccion.color,
  );
}

export function opcionesModelo(catalogo: CatalogoEquipos): Opcion[] {
  const conMarca = hayVariasMarcas(catalogo);
  return catalogo.modelos.map((modelo) => ({
    valor: claveModelo(modelo),
    etiqueta: conMarca ? `${modelo.marca} ${modelo.modelo}` : modelo.modelo,
  }));
}

export function opcionesVariante(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): Opcion[] {
  return (modeloDe(catalogo, seleccion)?.variantes ?? []).map((variante) => ({
    valor: claveVariante(variante),
    etiqueta: variante.variante ?? ETIQUETA_ESTANDAR,
  }));
}

export function opcionesCapacidad(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): Opcion[] {
  return (varianteDe(catalogo, seleccion)?.capacidades ?? []).map(
    (capacidad) => ({ valor: capacidad.capacidad, etiqueta: capacidad.capacidad }),
  );
}

export function opcionesColor(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): Opcion[] {
  return (capacidadDe(catalogo, seleccion)?.colores ?? []).map((color) => ({
    valor: claveColor(color),
    etiqueta: color.color ?? ETIQUETA_COLOR_GENERICO,
  }));
}

/**
 * La selección coherente con el catálogo: lo que ya no existe se borra
 * (con todo lo de abajo) y un nivel con una sola opción se elige solo.
 */
export function ajustarSeleccion(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): SeleccionCatalogo {
  const niveles: [
    keyof SeleccionCatalogo,
    (s: SeleccionCatalogo) => Opcion[],
  ][] = [
    ["modelo", () => opcionesModelo(catalogo)],
    ["variante", (s) => opcionesVariante(catalogo, s)],
    ["capacidad", (s) => opcionesCapacidad(catalogo, s)],
    ["color", (s) => opcionesColor(catalogo, s)],
  ];
  let resultado: SeleccionCatalogo = { ...SELECCION_VACIA };
  for (const [clave, opciones] of niveles) {
    const disponibles = opciones(resultado);
    const actual = seleccion[clave];
    if (disponibles.some((opcion) => opcion.valor === actual)) {
      resultado = { ...resultado, [clave]: actual };
    } else if (disponibles.length === 1) {
      resultado = { ...resultado, [clave]: disponibles[0].valor };
    } else {
      break;
    }
  }
  return resultado;
}

/**
 * Elegir un valor en un nivel. Lo de abajo se conserva si existe en la
 * nueva combinación (cambiar de Pro a Pro Max no borra «256 GB» ni
 * «Negro» si también existen); si no, se borra.
 */
export function elegir(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
  nivel: keyof SeleccionCatalogo,
  valor: string,
): SeleccionCatalogo {
  return ajustarSeleccion(catalogo, { ...seleccion, [nivel]: valor });
}

/** El producto elegido (los cuatro niveles), o `null`. */
export interface ProductoElegido {
  tipo_producto_id: string;
  marca: string;
  modelo: string;
  variante: string | null;
  capacidad: string;
  color: string | null;
}

export function productoElegido(
  catalogo: CatalogoEquipos,
  seleccion: SeleccionCatalogo,
): ProductoElegido | null {
  const modelo = modeloDe(catalogo, seleccion);
  const variante = varianteDe(catalogo, seleccion);
  const capacidad = capacidadDe(catalogo, seleccion);
  const color = colorDe(catalogo, seleccion);
  if (!modelo || !variante || !capacidad || !color) return null;
  return {
    tipo_producto_id: color.tipo_producto_id,
    marca: modelo.marca,
    modelo: modelo.modelo,
    variante: variante.variante,
    capacidad: capacidad.capacidad,
    color: color.color,
  };
}

/** Cuántos productos se pueden elegir. */
export function cantidadDeProductos(catalogo: CatalogoEquipos): number {
  return catalogo.modelos.reduce(
    (total, modelo) =>
      total +
      modelo.variantes.reduce(
        (suma, variante) =>
          suma +
          variante.capacidades.reduce(
            (parcial, capacidad) => parcial + capacidad.colores.length,
            0,
          ),
        0,
      ),
    0,
  );
}

// --- Lo que eligió Recepción: del catálogo o a mano ----------------------

export interface EquipoElegido {
  modo: "catalogo" | "manual";
  seleccion: SeleccionCatalogo;
  marca: string;
  modelo: string;
  /**
   * Corrección de una Orden que ya tiene un producto del catálogo: se
   * conserva si no se elige otro (aunque ya no esté en el catálogo).
   */
  actual: Equipo | null;
}

/**
 * Para el alta: del catálogo (mientras no haya catálogo, se carga a mano:
 * ver `modoEfectivo`). `manual`: lo que muestran Marca y Modelo.
 */
export function equipoElegidoInicial(manual: {
  marca: string;
  modelo: string;
}): EquipoElegido {
  return {
    modo: "catalogo",
    seleccion: SELECCION_VACIA,
    marca: manual.marca,
    modelo: manual.modelo,
    actual: null,
  };
}

/** Para corregir el equipo de una Orden: parte de lo que tiene. */
export function equipoElegidoDe(equipo: Equipo): EquipoElegido {
  return {
    modo: equipo.tipo_producto_id ? "catalogo" : "manual",
    seleccion: SELECCION_VACIA,
    marca: equipo.marca,
    modelo: equipo.modelo,
    actual: equipo.tipo_producto_id ? equipo : null,
  };
}

/**
 * Cómo se está cargando de verdad: «del catálogo» solo si hay catálogo
 * para elegir (o la Orden ya tiene un producto que se conserva); si no, a
 * mano, aunque se haya pedido el catálogo.
 */
export function modoEfectivo(
  catalogo: CatalogoEquipos | null,
  elegido: EquipoElegido,
): "catalogo" | "manual" {
  if (elegido.modo === "manual") return "manual";
  const hayCatalogo = (catalogo?.modelos.length ?? 0) > 0;
  return hayCatalogo || elegido.actual?.tipo_producto_id ? "catalogo" : "manual";
}

/**
 * Lo que va al backend: `{ tipo_producto_id }` o `{ marca, modelo }`; `null`
 * si todavía falta elegir o completar algo.
 */
export function datosDelEquipo(
  catalogo: CatalogoEquipos | null,
  elegido: EquipoElegido,
):
  | { tipo_producto_id: string }
  | { marca: string; modelo: string }
  | null {
  if (modoEfectivo(catalogo, elegido) === "manual") {
    const marca = elegido.marca.trim();
    const modelo = elegido.modelo.trim();
    return marca && modelo ? { marca, modelo } : null;
  }
  const producto = catalogo ? productoElegido(catalogo, elegido.seleccion) : null;
  if (producto) return { tipo_producto_id: producto.tipo_producto_id };
  const nadaElegido = !elegido.seleccion.modelo;
  if (nadaElegido && elegido.actual?.tipo_producto_id) {
    return { tipo_producto_id: elegido.actual.tipo_producto_id };
  }
  return null;
}

// --- Cómo se muestra un equipo --------------------------------------------

type DatosComerciales = Pick<Equipo, "marca" | "modelo"> &
  Partial<Pick<Equipo, "variante" | "capacidad" | "color">>;

/** «Apple iPhone 12 Pro Max» (marca, modelo y variante). */
export function nombreEquipo(equipo: DatosComerciales): string {
  return [equipo.marca, equipo.modelo, equipo.variante]
    .filter((parte) => parte && parte.trim())
    .join(" ");
}

/** El nombre con capacidad y color, si se conocen. */
export function descripcionEquipo(equipo: DatosComerciales): string {
  return [nombreEquipo(equipo), equipo.capacidad, equipo.color]
    .filter((parte) => parte && parte.trim())
    .join(" · ");
}
