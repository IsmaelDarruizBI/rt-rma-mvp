/**
 * Llamadas a la API de Ordenes y catalogos.
 *
 * Una funcion por intencion de usuario, con los mismos nombres que los
 * comandos del backend. Cada POST devuelve la Orden ya actualizada, asi
 * que la UI nunca tiene que recomponer el estado por su cuenta.
 */

import type {
  Estacion,
  InsumoUtilizado,
  Orden,
  OrdenResumen,
  TipoReparacion,
  Usuario,
} from "../types/api";
import { get, post } from "./client";

// --- Catalogos ---------------------------------------------------------

export function listarTiposReparacion(): Promise<TipoReparacion[]> {
  return get<TipoReparacion[]>("/api/catalogs/repair-types");
}

export function listarEstaciones(): Promise<Estacion[]> {
  return get<Estacion[]>("/api/catalogs/stations");
}

export function listarUsuarios(): Promise<Usuario[]> {
  return get<Usuario[]>("/api/catalogs/users");
}

// --- Lectura de Ordenes ------------------------------------------------

export function listarOrdenes(): Promise<OrdenResumen[]> {
  return get<OrdenResumen[]>("/api/orders");
}

export function obtenerOrden(ordenId: string): Promise<Orden> {
  return get<Orden>(`/api/orders/${ordenId}`);
}

// --- Comandos del Happy Path -------------------------------------------

export interface DatosNuevaOrden {
  usuario_id: string;
  cliente: { nombre: string; telefono: string; email?: string | null };
  equipo: { marca: string; modelo: string; falla_reportada: string };
}

/** PROC-REP-010 -> 030 -> 040 (Recepción). */
export function crearOrden(datos: DatosNuevaOrden): Promise<Orden> {
  return post<Orden>("/api/orders", datos);
}

export interface DatosNuevaOrdenRt {
  usuario_id: string;
  equipo: { marca: string; modelo: string; falla_reportada: string };
  referencia_rt: string;
}

/** PROC-REP-010 -> 020 -> 040 (Recepción, HP-REP-002). Sin Cliente. */
export function crearOrdenRt(datos: DatosNuevaOrdenRt): Promise<Orden> {
  return post<Orden>("/api/orders/rt-interno", datos);
}

/**
 * PROC-REP-045 -> 070 y, si `finalizarDefinicion` (default `true`),
 * también 050 -> 060 -> 080 -> 090 -> 140 (Recepción).
 *
 * Con `finalizarDefinicion=false` (Multi-Detalle) agrega el Detalle sin
 * habilitar la Orden todavía, para poder definir más de uno.
 */
export function definirReparacion(
  ordenId: string,
  usuarioId: string,
  tipoReparacionId: string,
  finalizarDefinicion = true,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/details`, {
    usuario_id: usuarioId,
    tipo_reparacion_id: tipoReparacionId,
    finalizar_definicion: finalizarDefinicion,
  });
}

/** PROC-REP-150 -> 170 (Coordinador). */
export function encolar(
  ordenId: string,
  usuarioId: string,
  prioridad: number,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/queue`, {
    usuario_id: usuarioId,
    prioridad,
  });
}

/** PROC-REP-172 -> 180 (Técnico). */
export function tomarOrden(
  ordenId: string,
  usuarioId: string,
  estacionId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/take`, {
    usuario_id: usuarioId,
    estacion_id: estacionId,
  });
}

/** PROC-REP-181 -> 174 -> 185: reserva real (Técnico). */
export function iniciarDetalle(
  ordenId: string,
  detalleId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/details/${detalleId}/start`, {
    usuario_id: usuarioId,
  });
}

/** PROC-REP-190 -> 200 -> 210 -> 211 (Técnico propietario). */
export function completarEjecucion(
  ordenId: string,
  ejecucionId: string,
  usuarioId: string,
  insumosUtilizados: InsumoUtilizado[],
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenId}/executions/${ejecucionId}/complete`,
    {
      usuario_id: usuarioId,
      insumos_utilizados: insumosUtilizados,
      observaciones,
    },
  );
}

/**
 * PROC-REP-190 -> 200 (Interrumpido) -> 210 -> 211 (Técnico propietario,
 * VAR-REP-003). `insumosUtilizados` es lo realmente usado hasta ahora.
 */
export function interrumpirEjecucion(
  ordenId: string,
  ejecucionId: string,
  usuarioId: string,
  insumosUtilizados: InsumoUtilizado[],
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenId}/executions/${ejecucionId}/interrupt`,
    {
      usuario_id: usuarioId,
      insumos_utilizados: insumosUtilizados,
      observaciones,
    },
  );
}

/**
 * PROC-REP-220 -> 230, y 245 -> 240 recién cuando todos los Detalles
 * quedan APROBADO (Recepción). `detalleId` (Multi-Detalle) aprueba un
 * único Detalle; `null` preserva la aprobación en bloque.
 */
export function aprobarControl(
  ordenId: string,
  usuarioId: string,
  detalleId: string | null,
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/control/approve`, {
    usuario_id: usuarioId,
    detalle_id: detalleId,
    observaciones,
  });
}

/** PROC-REP-212 ("No") -> 213: liberar la Orden sin terminarla (Técnico). */
export function liberarOrden(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/release`, {
    usuario_id: usuarioId,
  });
}

/** PROC-REP-250 -> 260 -> 265 [-> 266] (Recepción). */
export function notificar(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/notify`, {
    usuario_id: usuarioId,
  });
}

/** Capacidad transversal FEAT-REP-007 / BR-REP-017, sin rol exigido. */
export function registrarPago(
  ordenId: string,
  usuarioId: string,
  monto: string,
  metodo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/payments`, {
    usuario_id: usuarioId,
    monto,
    metodo,
  });
}

/** PROC-REP-280 -> 270 -> EVT-REP-999 (Administrador). */
export function entregar(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/deliver`, {
    usuario_id: usuarioId,
  });
}

/**
 * PROC-REP-250 -> 290 (HP-REP-002, RT_INTERNO).
 *
 * PROC-REP-290 es `actor: ACT-SYSTEM`: no hay actor humano que
 * autorizar, así que este comando no envía `usuario_id`.
 */
export function informarRt(ordenId: string): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/inform-rt`, {});
}

/**
 * PROC-REP-035 -> 040 -> 045 -> 070 -> 050 -> 060 -> 080 -> 090 -> 140
 * (Recepción, HP-REP-003). Devuelve la NUEVA Orden de garantía RMA; la
 * Orden origen no se modifica.
 */
export function generarGarantiaRma(
  ordenOrigenId: string,
  detalleOrigenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenOrigenId}/details/${detalleOrigenId}/warranty-rma`,
    { usuario_id: usuarioId },
  );
}

/**
 * PROC-REP-035 -> 040 -> 045 (No) -> 055 -> 050 -> 060 (Recepción,
 * VAR-REP-001). Devuelve la NUEVA Orden de garantía, EN_REVISION y sin
 * Detalles.
 */
export function generarGarantiaRmaEnRevision(
  ordenOrigenId: string,
  detalleOrigenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenOrigenId}/details/${detalleOrigenId}/warranty-rma/review`,
    { usuario_id: usuarioId },
  );
}

/** PROC-REP-045 (No) -> 055 -> 050 [-> 060] (Recepción, VAR-REP-001/002). */
export function enviarARevision(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/send-to-review`, {
    usuario_id: usuarioId,
  });
}

/** PROC-REP-065 (Técnico): registra el resultado de la revisión. */
export function realizarRevision(
  ordenId: string,
  usuarioId: string,
  resultado: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/technical-review`, {
    usuario_id: usuarioId,
    resultado,
  });
}

/**
 * PROC-REP-068 (Sí) -> 075 y, con `finalizarDefinicion`, 080 -> 090 ->
 * 140 (Recepción). No repite el comprobante.
 */
export function definirReparacionDesdeRevision(
  ordenId: string,
  usuarioId: string,
  tipoReparacionId: string,
  finalizarDefinicion = true,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/review/details`, {
    usuario_id: usuarioId,
    tipo_reparacion_id: tipoReparacionId,
    finalizar_definicion: finalizarDefinicion,
  });
}

/**
 * PROC-REP-110 (No) -> 120 (EXC-REP-001). Evento de sistema: sin
 * `usuario_id`. Solo válido desde PROC-REP-100.
 */
export function esperarRecursos(ordenId: string): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/resources/wait`, {});
}

/**
 * PROC-REP-120 -> 080 -> 090 [-> 140] (EXC-REP-001). Evento de sistema:
 * sin `usuario_id`. Solo válido desde PROC-REP-120.
 */
export function revalidarRecursos(ordenId: string): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/resources/revalidate`, {});
}

/** PROC-REP-270 reutilizado (HP-REP-002, RT_INTERNO -> EVT-REP-999). */
export function devolverRt(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/return-rt`, {
    usuario_id: usuarioId,
  });
}
