/**
 * «Insumos necesarios» de un Tipo de reparación (DEC-AJ-14, D-14.4), sin
 * React: lo que se edita, cómo se valida y qué se envía.
 *
 * - Insumos previstos concretos (insumo y cantidad, una línea por insumo).
 *   Lo que se agrega tiene que estar vigente y ser UNIVERSAL (sin modelos
 *   compatibles): una pieza que depende del modelo va como requisito por
 *   categoría. Lo que ya estaba se conserva aunque no lo sea.
 * - Requisitos (categoría o subcategoría y cantidad, uno por categoría, en
 *   el orden de la lista). Lo que se agrega tiene que estar vigente (una
 *   subcategoría de una categoría dada de baja cuenta como dada de baja).
 * - Cantidad mayor que cero, con hasta tres decimales.
 * - Se envía el conjunto completo: lo que no va se quita. Sin cambios no se
 *   guarda.
 *
 * La API (`services/configuracion.insumos_necesarios`) aplica las mismas
 * reglas y las vuelve a validar.
 */

import type { CategoriaInsumo, InsumoClasificable } from "../inventario/clasificacion";

export interface PrevistoDeTipo {
  tipo_reparacion_id: string;
  insumo_id: string;
  cantidad: string;
}

export interface RequisitoDeTipo {
  id: string;
  tipo_reparacion_id: string;
  categoria_id: string;
  cantidad: string;
  posicion: number;
  /** Un requisito quitado queda inactivo (nunca se borra). */
  activo: boolean;
}

export interface InsumoParaTipo extends InsumoClasificable {
  unidad: string;
  activo: boolean;
}

/** Lo mínimo de los datos de la API que usan estas reglas. */
export interface DatosInsumosNecesarios {
  previstos: readonly PrevistoDeTipo[];
  requisitos: readonly RequisitoDeTipo[];
  insumos: readonly InsumoParaTipo[];
  categorias: readonly CategoriaInsumo[];
}

export interface FilaPrevisto {
  insumo_id: string;
  cantidad: string;
}

export interface FilaRequisito {
  categoria_id: string;
  cantidad: string;
}

export interface EditorInsumosNecesarios {
  previstos: FilaPrevisto[];
  requisitos: FilaRequisito[];
}

export interface PedidoInsumosNecesarios {
  insumos: { insumo_id: string; cantidad: string }[];
  requisitos: { categoria_id: string; cantidad: string }[];
}

/** Tope de la columna (numeric(12, 3)). */
const TOPE_CANTIDAD = 1_000_000_000;

/**
 * La cantidad normalizada («1.5», «2»), con coma o punto decimal, mayor que
 * cero y con hasta tres decimales; `null` si no es válida.
 */
export function cantidadValida(texto: string): string | null {
  const limpio = texto.trim().replace(",", ".");
  if (!/^\d+(\.\d{1,3})?$/.test(limpio)) return null;
  const numero = Number(limpio);
  if (!(numero > 0) || numero >= TOPE_CANTIDAD) return null;
  return String(numero);
}

/** «1.000» → «1», «0.500» → «0.5» (para comparar y mostrar). */
export function normalizarCantidad(texto: string): string {
  const numero = Number(String(texto).trim().replace(",", "."));
  return Number.isFinite(numero) ? String(numero) : String(texto).trim();
}

/** Los previstos actuales del Tipo, ordenados por insumo. */
export function previstosDelTipo(datos: DatosInsumosNecesarios, tipoId: string): PrevistoDeTipo[] {
  return datos.previstos
    .filter((p) => p.tipo_reparacion_id === tipoId)
    .sort((a, b) => a.insumo_id.localeCompare(b.insumo_id));
}

/** Los requisitos vigentes del Tipo, en su orden. */
export function requisitosDelTipo(datos: DatosInsumosNecesarios, tipoId: string): RequisitoDeTipo[] {
  return datos.requisitos
    .filter((r) => r.tipo_reparacion_id === tipoId && r.activo)
    .sort((a, b) => a.posicion - b.posicion || a.categoria_id.localeCompare(b.categoria_id));
}

/** Lo que el editor muestra al abrirse: lo vigente del Tipo. */
export function editorInicial(datos: DatosInsumosNecesarios, tipoId: string): EditorInsumosNecesarios {
  return {
    previstos: previstosDelTipo(datos, tipoId).map((p) => ({
      insumo_id: p.insumo_id,
      cantidad: normalizarCantidad(p.cantidad),
    })),
    requisitos: requisitosDelTipo(datos, tipoId).map((r) => ({
      categoria_id: r.categoria_id,
      cantidad: normalizarCantidad(r.cantidad),
    })),
  };
}

/** «2 insumos · 1 requisito», «Sin insumos necesarios». */
export function resumenInsumosNecesarios(datos: DatosInsumosNecesarios, tipoId: string): string {
  const insumos = previstosDelTipo(datos, tipoId).length;
  const requisitos = requisitosDelTipo(datos, tipoId).length;
  const partes = [
    insumos ? `${insumos} ${insumos === 1 ? "insumo" : "insumos"}` : null,
    requisitos ? `${requisitos} ${requisitos === 1 ? "requisito" : "requisitos"}` : null,
  ].filter(Boolean);
  return partes.length ? partes.join(" · ") : "Sin insumos necesarios";
}

/** La categoría está vigente (y su padre, si es una subcategoría). */
export function categoriaVigente(
  categoriaId: string,
  categorias: readonly CategoriaInsumo[],
): boolean {
  const categoria = categorias.find((c) => c.id === categoriaId);
  if (!categoria || !categoria.activo) return false;
  if (!categoria.padre_id) return true;
  return categorias.find((c) => c.id === categoria.padre_id)?.activo ?? false;
}

/**
 * Los insumos que se pueden AGREGAR como previstos concretos: vigentes y
 * universales. `conservar`: los que el Tipo ya tiene (se siguen mostrando
 * aunque no cumplan).
 */
export function insumosAgregables<T extends InsumoParaTipo>(
  insumos: readonly T[],
  conservar: readonly string[] = [],
): T[] {
  return insumos.filter(
    (i) =>
      conservar.includes(i.id) ||
      (i.activo && (i.modelos_compatibles ?? []).length === 0),
  );
}

/** Mueve la línea `indice` un lugar (`-1` arriba, `1` abajo). */
export function moverLinea<T>(lista: readonly T[], indice: number, delta: -1 | 1): T[] {
  const destino = indice + delta;
  if (indice < 0 || indice >= lista.length || destino < 0 || destino >= lista.length) {
    return [...lista];
  }
  const copia = [...lista];
  [copia[indice], copia[destino]] = [copia[destino], copia[indice]];
  return copia;
}

export interface ValidacionInsumosNecesarios {
  /** Lo que se enviaría (null si hay errores). */
  pedido: PedidoInsumosNecesarios | null;
  errores: string[];
  /** El pedido es igual a lo vigente: no hay nada que guardar. */
  sinCambios: boolean;
}

/** Valida el editor con las reglas de la API y arma el pedido. */
export function validarInsumosNecesarios(
  editor: EditorInsumosNecesarios,
  datos: DatosInsumosNecesarios,
  tipoId: string,
): ValidacionInsumosNecesarios {
  const errores: string[] = [];
  const actuales = new Set(previstosDelTipo(datos, tipoId).map((p) => p.insumo_id));
  const vistos = new Set<string>();
  const insumos: PedidoInsumosNecesarios["insumos"] = [];
  editor.previstos.forEach((fila, indice) => {
    const linea = `Insumo ${indice + 1}`;
    const insumoId = fila.insumo_id.trim();
    if (!insumoId) {
      errores.push(`${linea}: falta elegir el insumo.`);
      return;
    }
    const insumo = datos.insumos.find((i) => i.id === insumoId);
    const nombre = insumo?.codigo ?? insumoId;
    if (vistos.has(insumoId)) {
      errores.push(`${nombre} está repetido: va una sola línea con la cantidad total.`);
    }
    vistos.add(insumoId);
    if (!actuales.has(insumoId)) {
      if (!insumo) errores.push(`No existe el insumo ${insumoId}.`);
      else if (!insumo.activo) errores.push(`${nombre} está dado de baja: no se agrega.`);
      else if ((insumo.modelos_compatibles ?? []).length > 0) {
        errores.push(
          `${nombre} solo sirve para algunos modelos: agregalo como requisito por categoría (la pieza se elige según el modelo del equipo).`,
        );
      }
    }
    const cantidad = cantidadValida(fila.cantidad);
    if (cantidad === null) {
      errores.push(`La cantidad de ${nombre} tiene que ser mayor que cero, con hasta tres decimales.`);
    } else {
      insumos.push({ insumo_id: insumoId, cantidad });
    }
  });

  const vigentes = new Set(requisitosDelTipo(datos, tipoId).map((r) => r.categoria_id));
  const pedidas = new Set<string>();
  const requisitos: PedidoInsumosNecesarios["requisitos"] = [];
  editor.requisitos.forEach((fila, indice) => {
    const linea = `Requisito ${indice + 1}`;
    const categoriaId = fila.categoria_id.trim();
    if (!categoriaId) {
      errores.push(`${linea}: falta elegir la categoría.`);
      return;
    }
    const categoria = datos.categorias.find((c) => c.id === categoriaId);
    const nombre = categoria?.nombre ?? categoriaId;
    if (pedidas.has(categoriaId)) {
      errores.push(`${nombre} está repetida: va un solo requisito con la cantidad total.`);
    }
    pedidas.add(categoriaId);
    if (!categoria) errores.push(`No existe la categoría ${categoriaId}.`);
    else if (!vigentes.has(categoriaId) && !categoriaVigente(categoriaId, datos.categorias)) {
      errores.push(`${nombre} está dada de baja: no se agrega como requisito.`);
    }
    const cantidad = cantidadValida(fila.cantidad);
    if (cantidad === null) {
      errores.push(`La cantidad de ${nombre} tiene que ser mayor que cero, con hasta tres decimales.`);
    } else {
      requisitos.push({ categoria_id: categoriaId, cantidad });
    }
  });

  const sinCambios = errores.length === 0 && mismoConjunto({ insumos, requisitos }, datos, tipoId);
  return {
    pedido: errores.length === 0 ? { insumos, requisitos } : null,
    errores,
    sinCambios,
  };
}

/**
 * Como la API: los previstos se comparan sin importar el orden; los
 * requisitos, en su orden (reordenarlos es un cambio).
 */
function mismoConjunto(
  pedido: PedidoInsumosNecesarios,
  datos: DatosInsumosNecesarios,
  tipoId: string,
): boolean {
  const texto = (lineas: { clave: string; cantidad: string }[]) =>
    lineas.map((l) => `${l.clave}x${normalizarCantidad(l.cantidad)}`).join(";");
  const ordenar = <T extends { clave: string }>(lineas: T[]) =>
    [...lineas].sort((a, b) => a.clave.localeCompare(b.clave));
  const previstosAntes = texto(
    ordenar(previstosDelTipo(datos, tipoId).map((p) => ({ clave: p.insumo_id, cantidad: p.cantidad }))),
  );
  const previstosDespues = texto(
    ordenar(pedido.insumos.map((p) => ({ clave: p.insumo_id, cantidad: p.cantidad }))),
  );
  const requisitosAntes = texto(
    requisitosDelTipo(datos, tipoId).map((r) => ({ clave: r.categoria_id, cantidad: r.cantidad })),
  );
  const requisitosDespues = texto(
    pedido.requisitos.map((r) => ({ clave: r.categoria_id, cantidad: r.cantidad })),
  );
  return previstosAntes === previstosDespues && requisitosAntes === requisitosDespues;
}

/** Los datos con lo que devolvió la API para el Tipo guardado. */
export function conInsumosDelTipo<T extends DatosInsumosNecesarios>(
  datos: T,
  tipoId: string,
  previstos: readonly PrevistoDeTipo[],
  requisitos: readonly RequisitoDeTipo[],
): T {
  return {
    ...datos,
    previstos: [...datos.previstos.filter((p) => p.tipo_reparacion_id !== tipoId), ...previstos],
    requisitos: [...datos.requisitos.filter((r) => r.tipo_reparacion_id !== tipoId), ...requisitos],
  };
}
