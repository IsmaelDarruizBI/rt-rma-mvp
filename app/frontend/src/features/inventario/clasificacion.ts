/**
 * Clasificación de insumos y compatibilidad con modelos (DEC-AJ-14), sin
 * React: etiquetas, filtros y la regla de compatibilidad para mostrar.
 *
 * - Cada insumo es un repuesto real (SKU): la clasificación no cambia su
 *   stock.
 * - Categoría → Subcategoría: dos niveles. El insumo guarda el más
 *   específico; la categoría padre se deriva.
 * - Sin modelos compatibles, el insumo es universal (sirve para todos).
 *
 * La regla vale igual en el backend (`services/clasificacion_insumos.py`),
 * que la vuelve a aplicar: acá solo decide qué ofrecer y cómo nombrarlo.
 */

export interface CategoriaInsumo {
  id: string;
  nombre: string;
  /** null: categoría de primer nivel. */
  padre_id: string | null;
  activo: boolean;
}

export interface FabricanteRepuesto {
  id: string;
  nombre: string;
  activo: boolean;
}

export interface ModeloClasificacion {
  id: string;
  marca: string;
  nombre: string;
  activo: boolean;
}

export interface ClasificacionInsumos {
  categorias: CategoriaInsumo[];
  fabricantes: FabricanteRepuesto[];
  modelos: ModeloClasificacion[];
}

export const CLASIFICACION_VACIA: ClasificacionInsumos = {
  categorias: [],
  fabricantes: [],
  modelos: [],
};

/** Lo que hace falta de un insumo (ausente en un backend anterior). */
export interface InsumoClasificable {
  id: string;
  codigo: string;
  nombre: string;
  activo?: boolean;
  categoria_id?: string | null;
  fabricante_id?: string | null;
  variante?: string | null;
  codigo_fabricante?: string | null;
  modelos_compatibles?: string[];
}

/** Valor del filtro de categoría que elige los insumos sin clasificar. */
export const SIN_CLASIFICAR = "__SIN_CLASIFICAR__";

export function esUniversal(insumo: InsumoClasificable): boolean {
  return (insumo.modelos_compatibles ?? []).length === 0;
}

/**
 * ¿Sirve para un equipo de ese modelo? Universal: siempre. Con modelos:
 * solo esos. Sin modelo técnico (null): solo los universales.
 */
export function compatibleCon(insumo: InsumoClasificable, modeloId: string | null): boolean {
  if (esUniversal(insumo)) return true;
  if (modeloId === null) return false;
  return (insumo.modelos_compatibles ?? []).includes(modeloId);
}

function categoriaDe(id: string | null | undefined, clasificacion: ClasificacionInsumos) {
  return id ? clasificacion.categorias.find((c) => c.id === id) ?? null : null;
}

/** La categoría de primer nivel (ella misma si no tiene padre). */
export function categoriaRaiz(id: string | null | undefined, clasificacion: ClasificacionInsumos): string | null {
  const categoria = categoriaDe(id, clasificacion);
  if (!categoria) return id ?? null;
  return categoria.padre_id ?? categoria.id;
}

/** «Módulos › OLED», «Baterías», el código si no se conoce, o null. */
export function nombreCategoria(
  id: string | null | undefined,
  clasificacion: ClasificacionInsumos,
): string | null {
  if (!id) return null;
  const categoria = categoriaDe(id, clasificacion);
  if (!categoria) return id;
  const padre = categoriaDe(categoria.padre_id, clasificacion);
  return padre ? `${padre.nombre} › ${categoria.nombre}` : categoria.nombre;
}

export function nombreFabricante(
  id: string | null | undefined,
  clasificacion: ClasificacionInsumos,
): string | null {
  if (!id) return null;
  return clasificacion.fabricantes.find((f) => f.id === id)?.nombre ?? id;
}

export function nombreModeloClasificacion(id: string, clasificacion: ClasificacionInsumos): string {
  return clasificacion.modelos.find((m) => m.id === id)?.nombre ?? id;
}

/** «INS-012 · Batería iPhone 14 · Acme · alta capacidad». */
export function etiquetaInsumo(insumo: InsumoClasificable, clasificacion: ClasificacionInsumos): string {
  return [
    insumo.codigo,
    insumo.nombre,
    nombreFabricante(insumo.fabricante_id, clasificacion),
    insumo.variante || null,
  ]
    .filter((parte): parte is string => Boolean(parte))
    .join(" · ");
}

/** La categoría, el fabricante y la variante, o «Sin clasificar». */
export function resumenClasificacion(
  insumo: InsumoClasificable,
  clasificacion: ClasificacionInsumos,
): string {
  const partes = [
    nombreCategoria(insumo.categoria_id, clasificacion),
    nombreFabricante(insumo.fabricante_id, clasificacion),
    insumo.variante || null,
  ].filter((parte): parte is string => Boolean(parte));
  return partes.length ? partes.join(" · ") : "Sin clasificar";
}

/**
 * «Universal», los nombres de los modelos (hasta `maximo`) o la cantidad:
 * «12 modelos».
 */
export function textoCompatibilidad(
  insumo: InsumoClasificable,
  clasificacion: ClasificacionInsumos,
  maximo = 2,
): string {
  const modelos = insumo.modelos_compatibles ?? [];
  if (modelos.length === 0) return "Universal";
  if (modelos.length > maximo) return `${modelos.length} modelos`;
  return modelos.map((m) => nombreModeloClasificacion(m, clasificacion)).join(", ");
}

export interface OpcionCategoria {
  id: string;
  etiqueta: string;
  activo: boolean;
  esSubcategoria: boolean;
}

/**
 * Las categorías en orden de árbol: cada categoría y después sus
 * subcategorías («Módulos», «Módulos › OLED»). Una subcategoría de una
 * categoría dada de baja cuenta como dada de baja. `soloVigentes` deja las
 * que se pueden asignar; `conservar` agrega la actual aunque no lo sea.
 */
export function opcionesCategoria(
  clasificacion: ClasificacionInsumos,
  { soloVigentes = false, conservar = null }: { soloVigentes?: boolean; conservar?: string | null } = {},
): OpcionCategoria[] {
  const raices = clasificacion.categorias.filter((c) => c.padre_id === null);
  const opciones: OpcionCategoria[] = [];
  for (const raiz of raices) {
    opciones.push({ id: raiz.id, etiqueta: raiz.nombre, activo: raiz.activo, esSubcategoria: false });
    for (const sub of clasificacion.categorias.filter((c) => c.padre_id === raiz.id)) {
      opciones.push({
        id: sub.id,
        etiqueta: `${raiz.nombre} › ${sub.nombre}`,
        activo: raiz.activo && sub.activo,
        esSubcategoria: true,
      });
    }
  }
  return opciones.filter((o) => !soloVigentes || o.activo || o.id === conservar);
}

export interface FiltroInsumos {
  /** Código, nombre, código del fabricante, variante, fabricante o categoría. */
  texto?: string;
  /** Una categoría (incluye sus subcategorías), una subcategoría o SIN_CLASIFICAR. */
  categoria?: string;
  fabricante?: string;
  /** Los compatibles con ese modelo (los universales incluidos). */
  modelo?: string;
  soloVigentes?: boolean;
}

function normalizar(texto: string): string {
  return texto
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .trim();
}

/** ¿El insumo está en esa categoría (o en una de sus subcategorías)? */
export function enCategoria(
  insumo: InsumoClasificable,
  categoria: string,
  clasificacion: ClasificacionInsumos,
): boolean {
  if (categoria === SIN_CLASIFICAR) return !insumo.categoria_id;
  if (!insumo.categoria_id) return false;
  return insumo.categoria_id === categoria || categoriaRaiz(insumo.categoria_id, clasificacion) === categoria;
}

export function filtrarInsumos<T extends InsumoClasificable>(
  insumos: readonly T[],
  filtro: FiltroInsumos,
  clasificacion: ClasificacionInsumos,
): T[] {
  const texto = normalizar(filtro.texto ?? "");
  return insumos.filter((insumo) => {
    if (filtro.soloVigentes && insumo.activo === false) return false;
    if (filtro.categoria && !enCategoria(insumo, filtro.categoria, clasificacion)) return false;
    if (filtro.fabricante && insumo.fabricante_id !== filtro.fabricante) return false;
    if (filtro.modelo && !compatibleCon(insumo, filtro.modelo)) return false;
    if (!texto) return true;
    const campos = [
      insumo.id,
      insumo.codigo,
      insumo.nombre,
      insumo.codigo_fabricante,
      insumo.variante,
      nombreFabricante(insumo.fabricante_id, clasificacion),
      nombreCategoria(insumo.categoria_id, clasificacion),
    ];
    return campos.some((campo) => campo && normalizar(campo).includes(texto));
  });
}

/** Hay algún filtro de clasificación puesto (además del texto). */
export function filtraClasificacion(filtro: FiltroInsumos): boolean {
  return Boolean(filtro.categoria || filtro.fabricante || filtro.modelo);
}

/** Modelos que coinciden con la búsqueda (nombre o código), en su orden. */
export function buscarModelos(
  modelos: readonly ModeloClasificacion[],
  texto: string,
): ModeloClasificacion[] {
  const buscado = normalizar(texto);
  if (!buscado) return [...modelos];
  return modelos.filter((m) => normalizar(`${m.nombre} ${m.id}`).includes(buscado));
}

/** Agrega o quita un modelo; el resultado queda ordenado, sin repetidos. */
export function alternarModelo(actuales: readonly string[], modeloId: string): string[] {
  const conjunto = new Set(actuales);
  if (conjunto.has(modeloId)) conjunto.delete(modeloId);
  else conjunto.add(modeloId);
  return [...conjunto].sort();
}

/** Los modelos de la búsqueda que se pueden agregar (vigentes y no elegidos). */
export function agregarModelos(actuales: readonly string[], visibles: readonly ModeloClasificacion[]): string[] {
  return [...new Set([...actuales, ...visibles.filter((m) => m.activo).map((m) => m.id)])].sort();
}

/**
 * El nombre ya está entre sus pares, sin distinguir mayúsculas ni espacios
 * de más (como la base, que sí distingue los acentos).
 */
export function nombreRepetido<T extends { id: string; nombre: string }>(
  pares: readonly T[],
  nombre: string,
  propio?: string,
): T | null {
  const clave = (texto: string) => texto.trim().split(/\s+/).join(" ").toLowerCase();
  const buscado = clave(nombre);
  if (!buscado) return null;
  return pares.find((p) => p.id !== propio && clave(p.nombre) === buscado) ?? null;
}
