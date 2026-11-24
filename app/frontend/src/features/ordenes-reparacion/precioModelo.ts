/**
 * Precio por modelo, precio manual y precio pendiente (DEC-AJ-12), sin React.
 *
 * - El precio de un Tipo depende del modelo técnico del equipo de la Orden
 *   cuando el Tipo tiene «precio por modelo». Sin precio para ese modelo (o
 *   sin modelo técnico) la pantalla dice «Sin precio para este modelo»:
 *   nunca muestra el precio único como si fuera el del modelo.
 * - Quien tiene PRECIO_MANUAL puede cargar un precio con motivo; si no, el
 *   trabajo queda con el precio pendiente de definir.
 * - Un trabajo pendiente se muestra «Precio pendiente de definir», nunca
 *   como $0.
 *
 * La API valida todo de nuevo: esto solo decide qué mostrar y qué enviar.
 */

export const PERMISO_PRECIO_MANUAL = "PRECIO_MANUAL";
export const SIN_PRECIO_PARA_EL_MODELO = "Sin precio para este modelo";
export const PRECIO_PENDIENTE = "Precio pendiente de definir";

export type OrigenPrecio =
  | "CATALOGO"
  | "CATALOGO_MODELO"
  | "MANUAL"
  | "OTROS"
  | "PENDIENTE";

export interface TipoConPrecio {
  precio: string;
  precio_por_modelo?: boolean;
  precios_modelo?: Record<string, string>;
}

export type PrecioDeTipo =
  | { estado: "UNICO" | "MODELO"; precio: string }
  | { estado: "SIN_PRECIO"; precio: null };

/** El precio de catálogo del Tipo para el modelo (sin respaldo). */
export function precioDelTipo(
  tipo: TipoConPrecio,
  modeloId: string | null | undefined,
): PrecioDeTipo {
  if (!tipo.precio_por_modelo) return { estado: "UNICO", precio: String(tipo.precio) };
  const precio = modeloId ? tipo.precios_modelo?.[modeloId] : undefined;
  return precio === undefined
    ? { estado: "SIN_PRECIO", precio: null }
    : { estado: "MODELO", precio: String(precio) };
}

/** «$ 60.000» o «Sin precio para este modelo». */
export function textoPrecioDelTipo(
  tipo: TipoConPrecio,
  modeloId: string | null | undefined,
  formato: (importe: string) => string = (x) => x,
): string {
  const resuelto = precioDelTipo(tipo, modeloId);
  return resuelto.precio === null ? SIN_PRECIO_PARA_EL_MODELO : formato(resuelto.precio);
}

export interface PedidoPrecioManual {
  precio: string;
  precio_motivo: string;
}

export interface EstadoPrecioManual {
  precio: string;
  motivo: string;
}

export const SIN_MANUAL: EstadoPrecioManual = { precio: "", motivo: "" };

/** Importe con coma o punto decimal y hasta dos decimales. */
export function normalizarImporte(texto: string): string | null {
  const limpio = texto.trim().replace(",", ".");
  return /^\d+(\.\d{1,2})?$/.test(limpio) ? limpio : null;
}

/**
 * Qué se envía con el trabajo. `null` si no corresponde un precio manual
 * (hay precio de catálogo, no tiene el permiso o no cargó nada: queda
 * pendiente). Error si cargó solo una parte o el importe no es válido.
 */
export function pedidoPrecioManual(
  tipo: TipoConPrecio | undefined,
  modeloId: string | null | undefined,
  puedeManual: boolean,
  estado: EstadoPrecioManual,
): { pedido: PedidoPrecioManual | null; error: string | null } {
  if (!tipo || !puedeManual || precioDelTipo(tipo, modeloId).precio !== null) {
    return { pedido: null, error: null };
  }
  const precio = estado.precio.trim();
  const motivo = estado.motivo.trim();
  if (!precio && !motivo) return { pedido: null, error: null };
  const importe = normalizarImporte(precio);
  if (importe === null) return { pedido: null, error: "Precio inválido (hasta dos decimales)." };
  if (!motivo) return { pedido: null, error: "El precio manual exige un motivo." };
  return { pedido: { precio: importe, precio_motivo: motivo }, error: null };
}

export interface DetalleConPrecio {
  precio: string;
  origen_precio?: OrigenPrecio | null;
  precio_pendiente?: boolean;
}

export function esPrecioPendiente(detalle: DetalleConPrecio): boolean {
  return detalle.precio_pendiente === true || detalle.origen_precio === "PENDIENTE";
}

/** El precio de un trabajo: nunca «$0» si está pendiente. */
export function textoPrecioDelDetalle(
  detalle: DetalleConPrecio,
  formato: (importe: string) => string = (x) => x,
): string {
  return esPrecioPendiente(detalle) ? PRECIO_PENDIENTE : formato(detalle.precio);
}

/** La marca del origen del precio, si hay que mostrarla. */
export function etiquetaOrigenPrecio(origen: OrigenPrecio | null | undefined): string | null {
  switch (origen) {
    case "MANUAL":
      return "Precio manual";
    case "PENDIENTE":
      return "Precio pendiente";
    default:
      return null;
  }
}

/** Suma de los precios ignorando los pendientes (no son importes). */
export function hayPreciosPendientes(detalles: readonly DetalleConPrecio[]): boolean {
  return detalles.some(esPrecioPendiente);
}

// --- Configuración: grilla de precios por modelo ----------------------------

export interface CambioPrecioModelo {
  modelo_equipo_id: string;
  /** `null`: retira el precio del modelo. */
  precio: string | null;
}

/**
 * Los cambios de la grilla respecto de los precios vigentes. Una celda vacía
 * retira el precio; una sin cambios no se envía. Devuelve los modelos con
 * un importe inválido aparte.
 */
export function cambiosDePrecios(
  vigentes: Record<string, string>,
  editados: Record<string, string>,
): { cambios: CambioPrecioModelo[]; invalidos: string[] } {
  const cambios: CambioPrecioModelo[] = [];
  const invalidos: string[] = [];
  for (const [modelo, texto] of Object.entries(editados)) {
    const anterior = vigentes[modelo];
    if (texto.trim() === "") {
      if (anterior !== undefined) cambios.push({ modelo_equipo_id: modelo, precio: null });
      continue;
    }
    const importe = normalizarImporte(texto);
    if (importe === null) {
      invalidos.push(modelo);
      continue;
    }
    if (anterior === undefined || Number(anterior) !== Number(importe)) {
      cambios.push({ modelo_equipo_id: modelo, precio: importe });
    }
  }
  return { cambios, invalidos };
}

// --- Configuración: modelos de equipo ----------------------------------------

export interface ModeloAdministrable {
  id: string;
  marca: string;
  modelo: string;
  variante?: string | null;
  numeros_modelo?: string[];
  activo?: boolean;
}

function normalizar(texto: string | null | undefined): string {
  return (texto ?? "").split(/\s+/).filter(Boolean).join(" ").toLocaleLowerCase("es");
}

/** Otro modelo con la misma marca, modelo y variante (la API lo rechaza). */
export function modeloRepetido(
  modelos: readonly ModeloAdministrable[],
  datos: { marca: string; modelo: string; variante?: string | null },
  propio?: string,
): ModeloAdministrable | null {
  const clave = [datos.marca, datos.modelo, datos.variante].map(normalizar).join("|");
  return (
    modelos.find(
      (m) => m.id !== propio && [m.marca, m.modelo, m.variante].map(normalizar).join("|") === clave,
    ) ?? null
  );
}

/** «Apple iPhone 15 Pro Max». */
export function nombreModelo(modelo: { marca: string; modelo: string; variante?: string | null }): string {
  return [modelo.marca, modelo.modelo, modelo.variante].filter(Boolean).join(" ");
}

/** Los números de modelo escritos separados por comas o espacios. */
export function numerosDeModelo(texto: string): string[] {
  return texto
    .split(/[,\s]+/)
    .map((x) => x.trim())
    .filter(Boolean);
}
