/**
 * Reglas de pantalla de Compras (DEC-MI-09), sin React: quién gestiona, el
 * último costo de referencia y la recepción parcial (líneas, validación y
 * lo que se envía). La API valida todo de nuevo: una recepción nunca supera
 * lo pendiente y un insumo por serie lleva un número por unidad.
 */

import type {
  CostoCompra,
  LineaRecepcion,
  OrdenCompra,
} from "../../api/compras";
import { type ConRoles, puede } from "../../lib/roles.ts";
import type { RolUsuario } from "../../types/api";

export const GESTORES: RolUsuario[] = ["RECEPCION", "COORDINADOR_RMA", "ADMINISTRADOR"];

export interface LineaEditable {
  insumo_id: string;
  cantidad: string;
  costo: string;
  lote: string;
  series: string;
  diferencia: string;
}

/** Último costo real por insumo (los costos vienen del más reciente al
 * más antiguo). */
export function ultimosCostos(costos: CostoCompra[]): Record<string, string> {
  const ultimo: Record<string, string> = {};
  for (const costo of costos) ultimo[costo.insumo_id] ??= costo.costo_unitario;
  return ultimo;
}

/** Una línea por renglón con pendiente, con el costo acordado en la OC. */
export function lineasIniciales(orden: OrdenCompra): LineaEditable[] {
  return orden.renglones
    .filter((r) => Number(r.pendiente) > 0)
    .map((r) => ({
      insumo_id: r.insumo_id,
      cantidad: "",
      costo: orden.items.find((i) => i.insumo_id === r.insumo_id)?.costo_unitario ?? "0",
      lote: "",
      series: "",
      diferencia: "",
    }));
}

export function seriesDe(texto: string): string[] {
  return texto
    .split(/[\n,]/)
    .map((s) => s.trim())
    .filter(Boolean);
}

/** Errores de una recepción antes de enviarla (lista vacía: se puede). */
export function erroresDeRecepcion(orden: OrdenCompra, lineas: LineaEditable[]): string[] {
  const errores: string[] = [];
  const cargadas = lineas.filter((l) => l.cantidad.trim() !== "");
  if (!cargadas.some((l) => Number(l.cantidad) > 0)) {
    errores.push("Cargá la cantidad recibida de al menos un insumo.");
  }
  for (const linea of cargadas) {
    const cantidad = Number(linea.cantidad);
    const renglon = orden.renglones.find((r) => r.insumo_id === linea.insumo_id);
    const pendiente = Number(renglon?.pendiente ?? 0);
    if (!Number.isFinite(cantidad) || cantidad < 0) {
      errores.push(`${linea.insumo_id}: la cantidad no es válida.`);
      continue;
    }
    if (cantidad > pendiente) {
      errores.push(`${linea.insumo_id}: quedan ${renglon?.pendiente ?? "0"} pendientes.`);
    }
    if (!Number.isFinite(Number(linea.costo)) || Number(linea.costo) < 0) {
      errores.push(`${linea.insumo_id}: el costo no es válido.`);
    }
    const series = seriesDe(linea.series);
    if (series.length > 0) {
      if (series.length !== cantidad) {
        errores.push(`${linea.insumo_id}: va un número de serie por unidad (${cantidad}).`);
      }
      if (new Set(series).size !== series.length) {
        errores.push(`${linea.insumo_id}: hay números de serie repetidos.`);
      }
    }
  }
  return errores;
}

/** El costo cargado difiere del acordado en la OC (la API anota la
 * diferencia si no se explica). */
export function costoDistinto(orden: OrdenCompra, linea: LineaEditable): boolean {
  const acordado = orden.items.find((i) => i.insumo_id === linea.insumo_id)?.costo_unitario;
  return acordado !== undefined && Number(acordado) !== Number(linea.costo);
}

/** Lo que se envía: solo las líneas con cantidad mayor que cero. */
export function lineasParaRecibir(lineas: LineaEditable[]): LineaRecepcion[] {
  return lineas
    .filter((l) => Number(l.cantidad) > 0)
    .map((l) => ({
      insumo_id: l.insumo_id,
      cantidad: l.cantidad.trim(),
      costo_unitario: l.costo.trim(),
      lote: l.lote.trim() || null,
      series: seriesDe(l.series),
      diferencia: l.diferencia.trim() || null,
    }));
}

/** Avance de la OC: pedido, recibido y pendiente totales. */
export function avanceDeOrden(orden: OrdenCompra): { pedido: number; recibido: number; pendiente: number } {
  return orden.renglones.reduce(
    (total, r) => ({
      pedido: total.pedido + Number(r.pedido),
      recibido: total.recibido + Number(r.recibido),
      pendiente: total.pendiente + Number(r.pendiente),
    }),
    { pedido: 0, recibido: 0, pendiente: 0 },
  );
}

/**
 * Lo que el usuario puede hacer en Compras (Configuración v2, CFG-03, D5 y
 * DF-5). Con una API anterior (solo `COMPRAS_GESTIONAR`) ese permiso
 * habilita todo, como antes; sin lista de permisos deciden los roles.
 */
export interface AccionesCompras {
  solicitar: boolean;
  crearOc: boolean;
  confirmar: boolean;
  cancelar: boolean;
  recibir: boolean;
}

const CODIGOS_COMPRAS = {
  solicitar: "COMPRA_SOLICITAR",
  crearOc: "OC_CREAR",
  confirmar: "OC_CONFIRMAR",
  cancelar: "OC_CANCELAR",
  recibir: "COMPRA_RECIBIR",
} as const;

export function accionesDeCompras(usuario: ConRoles | null): AccionesCompras {
  const permisos = usuario?.permisos;
  const nuevos = Object.values(CODIGOS_COMPRAS) as string[];
  const apiAnterior =
    permisos !== undefined && !permisos.some((codigo) => nuevos.includes(codigo));
  const todo = puede(usuario, "COMPRAS_GESTIONAR", GESTORES);
  const resultado = {} as AccionesCompras;
  for (const [accion, codigo] of Object.entries(CODIGOS_COMPRAS)) {
    resultado[accion as keyof AccionesCompras] = apiAnterior
      ? todo
      : puede(usuario, codigo, GESTORES);
  }
  return resultado;
}

/** DF-5: cancelar una OC confirmada (o un borrador ajeno) exige cancelar;
 * quien crea OC descarta su propio borrador. Sin recepciones, siempre. */
export function puedeCancelarOrden(
  acciones: AccionesCompras,
  orden: Pick<OrdenCompra, "estado" | "creada_por">,
  usuarioId: string,
): boolean {
  if (orden.estado !== "BORRADOR" && orden.estado !== "CONFIRMADA") return false;
  if (acciones.cancelar) return true;
  return acciones.crearOc && orden.estado === "BORRADOR" && orden.creada_por === usuarioId;
}
