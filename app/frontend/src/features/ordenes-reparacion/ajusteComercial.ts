/**
 * Ajuste Comercial (DEC-AJ-10): reglas puras de presentación.
 *
 * - Un solo formulario para el descuento y la cortesía, de la Orden o de
 *   un trabajo, con la vista previa del precio original, el ajuste y el
 *   precio final (las mismas cuentas que el backend).
 * - El historial de cada destino: alta, cambio, retiro, corrección y
 *   reversión, con la evidencia de los importes y los recálculos.
 * - Qué registro se puede revertir o corregir: solo el vigente de su
 *   destino (el último no revertido, que no quita el ajuste).
 * - El aviso antes de redefinir o cancelar un trabajo con ajustes.
 * - Los comprobantes emitidos desde DEC-AJ-10: ajuste por trabajo y el de
 *   la Orden aparte, con su clase y sin motivo.
 *
 * Sin React ni DOM: se prueba con node --test. El backend valida todo.
 */

import type {
  AjusteEnDocumento,
  ClaseAjuste,
  DescuentoVigente,
  Orden,
  RecalculoAjuste,
  RegistroDescuento,
  TipoDescuento,
} from "../../types/api";

/** Permisos de cada clase y el de revertir (BR-REP-039, DEC-AJ-10). */
export const PERMISO_DE_CLASE: Record<ClaseAjuste, string> = {
  DESCUENTO: "DESCUENTO",
  CORTESIA: "CORTESIA",
};
export const PERMISO_REVERTIR = "AJUSTE_REVERTIR";
/** Predeterminados, por si la sesión no trae sus permisos. */
export const ROLES_AJUSTE = [
  "RECEPCION",
  "COORDINADOR_RMA",
  "ADMINISTRADOR",
] as const;
export const ROLES_REVERTIR = ["ADMINISTRADOR"] as const;

/** «Descuento» o «Cortesía». */
export function etiquetaClase(clase: ClaseAjuste | undefined | null): string {
  return clase === "CORTESIA" ? "Cortesía" : "Descuento";
}

/** «10 %» o «$ 5000» (sin formato de moneda: lo agrega la pantalla). */
export function textoValor(tipo: TipoDescuento, valor: string): string {
  return tipo === "PORCENTAJE" ? `${Number(valor)} %` : `$ ${Number(valor)}`;
}

const centavos = (valor: number) => Math.round(valor * 100) / 100;

/** Lo que descuenta un ajuste sobre una base (nunca más que la base). */
export function importeDeAjuste(
  base: number,
  tipo: TipoDescuento | null | undefined,
  valor: string | number | null | undefined,
): number {
  if (!tipo || valor === null || valor === undefined || base <= 0) return 0;
  const numero = Number(valor);
  const importe =
    tipo === "PORCENTAJE" ? Math.round(base * numero) / 100 : numero;
  return centavos(Math.min(importe, base));
}

/**
 * A qué se aplica el ajuste de un destino: el precio del trabajo o, para la
 * Orden, el subtotal menos los ajustes vigentes de los trabajos.
 */
export function baseDelDestino(
  orden: Pick<Orden, "reparaciones_detail" | "resumen">,
  detalleId: string | null,
): number {
  if (detalleId) {
    const detalle = orden.reparaciones_detail.find((d) => d.id === detalleId);
    return detalle && detalle.estado !== "CANCELADO"
      ? Number(detalle.precio)
      : 0;
  }
  const deTrabajos = (orden.resumen.ajustes_detalle ?? []).reduce(
    (suma, ajuste) => suma + Number(ajuste.importe),
    0,
  );
  return centavos(Number(orden.resumen.subtotal) - deTrabajos);
}

/** El ajuste vigente de un destino, como lo resume el backend. */
export function vigenteDelDestino(
  orden: Pick<Orden, "resumen">,
  detalleId: string | null,
): DescuentoVigente | null {
  if (detalleId) {
    return (
      (orden.resumen.ajustes_detalle ?? []).find(
        (ajuste) => ajuste.detalle_id === detalleId,
      ) ?? null
    );
  }
  return orden.resumen.descuento ?? null;
}

export interface VistaPrevia {
  valido: boolean;
  error: string | null;
  original: number;
  ajuste: number;
  final: number;
}

/** Vista previa del formulario: la misma validación que el backend. */
export function vistaPrevia(
  base: number,
  tipo: TipoDescuento,
  valor: string,
): VistaPrevia {
  const texto = valor.trim().replace(",", ".");
  const numero = Number(texto);
  let error: string | null = null;
  if (!/^\d+(?:\.\d{1,2})?$/.test(texto) || !(numero > 0)) {
    error = "Indicá un valor mayor que cero (hasta dos decimales).";
  } else if (tipo === "PORCENTAJE" && numero > 100) {
    error = "Un porcentaje no puede superar el 100 %.";
  } else if (tipo === "IMPORTE" && numero > base) {
    error = "El importe no puede superar el precio al que se aplica.";
  }
  const ajuste = error ? 0 : importeDeAjuste(base, tipo, numero);
  return {
    valido: error === null,
    error,
    original: base,
    ajuste,
    final: centavos(base - ajuste),
  };
}

// --- Registros: vigente, revertible y operación -----------------------------

const destinoDe = (registro: RegistroDescuento) => registro.detalle_id ?? null;

/** El último registro no revertido de ese destino (aunque quite). */
export function ultimoNoRevertido(
  registros: RegistroDescuento[],
  detalleId: string | null,
): RegistroDescuento | null {
  for (let i = registros.length - 1; i >= 0; i--) {
    const registro = registros[i];
    if (destinoDe(registro) === detalleId && !registro.reversion) {
      return registro;
    }
  }
  return null;
}

/** Solo el vigente de su destino se revierte o se corrige (DEC-AJ-10). */
export function esRevertible(
  registros: RegistroDescuento[],
  registro: RegistroDescuento,
): boolean {
  if (registro.reversion || registro.tipo === null || !registro.id) {
    return false;
  }
  return ultimoNoRevertido(registros, destinoDe(registro))?.id === registro.id;
}

export type Operacion = "ALTA" | "CAMBIO" | "QUITAR" | "CORRECCION";

export const ETIQUETA_OPERACION: Record<Operacion | "REVERSION" | "RECALCULO", string> = {
  ALTA: "Alta",
  CAMBIO: "Cambio",
  QUITAR: "Retiro",
  CORRECCION: "Corrección",
  REVERSION: "Reversión",
  RECALCULO: "Recálculo",
};

/**
 * Qué fue un registro cuando se hizo: corrección (enlazada), retiro, o
 * cambio si en ese momento ya regía otro ajuste en el destino; si no, alta.
 */
export function operacionDe(
  registros: RegistroDescuento[],
  indice: number,
): Operacion {
  const registro = registros[indice];
  if (registro.corrige_a) return "CORRECCION";
  if (registro.tipo === null) return "QUITAR";
  for (let i = indice - 1; i >= 0; i--) {
    const anterior = registros[i];
    if (destinoDe(anterior) !== destinoDe(registro)) continue;
    const revertidoAntes =
      anterior.reversion && anterior.reversion.fecha <= registro.fecha;
    if (revertidoAntes) continue;
    return anterior.tipo === null ? "ALTA" : "CAMBIO";
  }
  return "ALTA";
}

export interface EntradaHistorial {
  clave: string;
  fecha: string;
  operacion: Operacion | "REVERSION" | "RECALCULO";
  /** «Descuento 10 % · DET-002» o «Cortesía $ 5000 · Orden». */
  descripcion: string;
  /** Precio original, ajuste y final, si hay evidencia. */
  evidencia: string | null;
  motivo: string | null;
  usuarioId: string;
  /** El registro que se puede revertir o corregir desde esta entrada. */
  revertible: RegistroDescuento | null;
  revertido: boolean;
}

const nombreDestino = (detalleId: string | null | undefined) =>
  detalleId ? detalleId : "Orden";

function evidenciaDe(registro: RegistroDescuento): string | null {
  if (registro.precio_original === null || registro.precio_original === undefined) {
    return null;
  }
  return (
    `precio ${registro.precio_original} · ajuste ${registro.importe_aplicado}` +
    ` · final ${registro.precio_final}`
  );
}

function descripcionDe(registro: RegistroDescuento): string {
  const clase = etiquetaClase(registro.clase);
  const valor =
    registro.tipo && registro.valor
      ? `${clase} ${textoValor(registro.tipo, registro.valor)}`
      : `Sin ${clase.toLowerCase()}`;
  return `${valor} · ${nombreDestino(registro.detalle_id)}`;
}

function descripcionRecalculo(recalculo: RecalculoAjuste): string {
  const causa =
    recalculo.causa === "CANCELACION" ? "cancelación" : "redefinición";
  return (
    `Por ${causa} · ${nombreDestino(recalculo.detalle_id)} · ajuste ` +
    `${recalculo.ajuste_id}`
  );
}

/**
 * Todas las operaciones del ajuste, de la más antigua a la más reciente.
 * La reversión de un registro corregido no se repite: es parte de la
 * corrección.
 */
export function historialDeAjustes(
  orden: Pick<Orden, "descuentos"> & { recalculos_ajuste?: RecalculoAjuste[] },
): EntradaHistorial[] {
  const registros = orden.descuentos ?? [];
  const corregidos = new Set(
    registros.map((r) => r.corrige_a).filter((id): id is string => !!id),
  );
  const entradas: EntradaHistorial[] = [];
  registros.forEach((registro, indice) => {
    const operacion = operacionDe(registros, indice);
    entradas.push({
      clave: `${registro.id ?? indice}-${operacion}`,
      fecha: registro.fecha,
      operacion,
      descripcion:
        descripcionDe(registro) +
        (registro.corrige_a ? ` (corrige ${registro.corrige_a})` : ""),
      evidencia: evidenciaDe(registro),
      motivo: registro.motivo,
      usuarioId: registro.usuario_id,
      revertible: esRevertible(registros, registro) ? registro : null,
      revertido: !!registro.reversion,
    });
    if (registro.reversion && !corregidos.has(registro.id ?? "")) {
      entradas.push({
        clave: `${registro.id ?? indice}-REVERSION`,
        fecha: registro.reversion.fecha,
        operacion: "REVERSION",
        descripcion: `Revierte ${descripcionDe(registro)}`,
        evidencia: null,
        motivo: registro.reversion.motivo,
        usuarioId: registro.reversion.usuario_id,
        revertible: null,
        revertido: false,
      });
    }
  });
  (orden.recalculos_ajuste ?? []).forEach((recalculo, indice) => {
    entradas.push({
      clave: `recalculo-${indice}`,
      fecha: recalculo.fecha,
      operacion: "RECALCULO",
      descripcion: descripcionRecalculo(recalculo),
      evidencia:
        `precio ${recalculo.precio_anterior} → ${recalculo.precio_nuevo} · ` +
        `ajuste ${recalculo.importe_anterior} → ${recalculo.importe_nuevo}`,
      motivo: null,
      usuarioId: recalculo.usuario_id,
      revertible: null,
      revertido: false,
    });
  });
  // Estable: a igual fecha, el orden en que se registraron.
  return entradas
    .map((entrada, indice) => ({ entrada, indice }))
    .sort((a, b) =>
      a.entrada.fecha === b.entrada.fecha
        ? a.indice - b.indice
        : a.entrada.fecha < b.entrada.fecha
          ? -1
          : 1,
    )
    .map(({ entrada }) => entrada);
}

// --- Aviso de recálculo (redefinición o cancelación) -------------------------

/**
 * Los ajustes vigentes cuyo importe cambiaría si el trabajo pasa a
 * `precioNuevo` (0 al cancelarlo). Las mismas cuentas que el backend, que
 * deja el recálculo como evidencia.
 */
export function avisoRecalculo(
  orden: Pick<Orden, "reparaciones_detail" | "resumen">,
  detalleId: string,
  precioNuevo: number,
): string | null {
  const detalle = orden.reparaciones_detail.find((d) => d.id === detalleId);
  if (!detalle || detalle.estado === "CANCELADO") return null;
  const precio = Number(detalle.precio);
  const partes: string[] = [];
  const delTrabajo = vigenteDelDestino(orden, detalleId);
  const antesTrabajo = importeDeAjuste(precio, delTrabajo?.tipo, delTrabajo?.valor);
  const despuesTrabajo = importeDeAjuste(
    precioNuevo,
    delTrabajo?.tipo,
    delTrabajo?.valor,
  );
  if (delTrabajo && antesTrabajo !== despuesTrabajo) {
    partes.push(
      `${etiquetaClase(delTrabajo.clase)} del trabajo: ${antesTrabajo} → ${despuesTrabajo}`,
    );
  }
  const deLaOrden = vigenteDelDestino(orden, null);
  if (deLaOrden) {
    const base = baseDelDestino(orden, null);
    const baseNueva = centavos(
      base - precio + precioNuevo + antesTrabajo - despuesTrabajo,
    );
    const antes = importeDeAjuste(base, deLaOrden.tipo, deLaOrden.valor);
    const despues = importeDeAjuste(baseNueva, deLaOrden.tipo, deLaOrden.valor);
    if (antes !== despues) {
      partes.push(
        `${etiquetaClase(deLaOrden.clase)} de la Orden: ${antes} → ${despues}`,
      );
    }
  }
  if (partes.length === 0) return null;
  return (
    "Se recalcula el ajuste comercial vigente (queda registrado): " +
    partes.join("; ") +
    "."
  );
}

// --- Comprobantes ------------------------------------------------------------

/** «Cortesía 10 %» (la cortesía se imprime como cortesía). */
export function textoAjusteDocumento(ajuste: AjusteEnDocumento): string {
  return `${etiquetaClase(ajuste.clase)} ${ajuste.descripcion}`;
}

interface ConAjustes {
  ajustes_por_trabajo?: boolean;
  ajuste_orden?: AjusteEnDocumento | null;
}

interface TrabajoConAjuste {
  ajuste?: AjusteEnDocumento | null;
}

/** El comprobante se emitió con el ajuste por trabajo (desde DEC-AJ-10). */
export function conAjustesPorTrabajo(contenido: ConAjustes): boolean {
  return contenido.ajustes_por_trabajo === true;
}

/**
 * Las líneas de ajustes al pie de los trabajos: el total de los ajustes de
 * los trabajos (ya detallados en cada renglón) y el de la Orden aparte.
 * Sin motivo, usuario ni fecha (quedan en el registro interno).
 */
export function lineasDeAjustes(
  contenido: ConAjustes,
  trabajos: TrabajoConAjuste[],
): { etiqueta: string; importe: number }[] {
  const deTrabajos = trabajos.reduce(
    (suma, trabajo) => suma + Number(trabajo.ajuste?.importe ?? 0),
    0,
  );
  const lineas: { etiqueta: string; importe: number }[] = [];
  if (deTrabajos > 0) {
    lineas.push({ etiqueta: "Ajustes de los trabajos", importe: centavos(deTrabajos) });
  }
  if (contenido.ajuste_orden) {
    lineas.push({
      etiqueta: `${textoAjusteDocumento(contenido.ajuste_orden)} sobre la Orden`,
      importe: Number(contenido.ajuste_orden.importe),
    });
  }
  return lineas;
}
