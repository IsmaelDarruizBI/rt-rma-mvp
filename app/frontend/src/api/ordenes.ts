/**
 * Llamadas a la API de Ordenes y catalogos.
 *
 * Una funcion por intencion de usuario, con los mismos nombres que los
 * comandos del backend. Cada POST devuelve la Orden ya actualizada, asi
 * que la UI nunca tiene que recomponer el estado por su cuenta.
 */

import type {
  CanalComunicacion,
  DatosRecepcion,
  DecisionDetalle,
  DocumentoEmitido,
  DocumentosDeOrden,
  Estacion,
  ImpactoOverride,
  InsumoUtilizado,
  MedioPago,
  Orden,
  OrdenResumen,
  TipoDocumento,
  TipoReparacion,
  Usuario,
  VistaPreviaDocumento,
} from "../types/api";
import { get, post, put } from "./client";

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

export function listarMediosPago(): Promise<MedioPago[]> {
  return get<MedioPago[]>("/api/catalogs/payment-methods");
}

// --- Lectura de Ordenes ------------------------------------------------

export function listarOrdenes(): Promise<OrdenResumen[]> {
  return get<OrdenResumen[]>("/api/orders");
}

export function obtenerOrden(ordenId: string): Promise<Orden> {
  return get<Orden>(`/api/orders/${ordenId}`);
}

// --- Comandos del Happy Path -------------------------------------------

/** Equipo que se recibe. IMEI y número de serie son opcionales. */
export interface DatosEquipo {
  marca: string;
  modelo: string;
  falla_reportada: string;
  imei?: string | null;
  numero_serie?: string | null;
}

export interface DatosNuevaOrden {
  usuario_id: string;
  cliente: { nombre: string; telefono: string; email?: string | null };
  equipo: DatosEquipo;
  /** Condiciones del ingreso; la recepción física se confirma aparte. */
  recepcion?: DatosRecepcion;
}

/** PROC-REP-010 -> 030 -> 040 (Recepción). */
export function crearOrden(datos: DatosNuevaOrden): Promise<Orden> {
  return post<Orden>("/api/orders", datos);
}

export interface DatosNuevaOrdenRt {
  usuario_id: string;
  equipo: DatosEquipo;
  referencia_rt: string;
  recepcion?: DatosRecepcion;
}

/** PROC-REP-010 -> 020 -> 040 (Recepción, HP-REP-002). Sin Cliente. */
export function crearOrdenRt(datos: DatosNuevaOrdenRt): Promise<Orden> {
  return post<Orden>("/api/orders/rt-interno", datos);
}

/**
 * PROC-REP-045 -> 070 (Recepción): agrega UN Detalle. No genera el
 * comprobante, no valida factibilidad ni habilita: eso es
 * `finalizarDefinicion`.
 */
export function definirReparacion(
  ordenId: string,
  usuarioId: string,
  tipoReparacionId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/details`, {
    usuario_id: usuarioId,
    tipo_reparacion_id: tipoReparacionId,
  });
}

/**
 * Cierra la carga de Detalles (Recepción): [050 -> 060] -> 080 -> 090 ->
 * 140 | 100. Exige al menos un Detalle; en el camino de revisión no
 * regenera el comprobante.
 */
export function finalizarDefinicion(
  ordenId: string,
  usuarioId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/definition/finalize`, {
    usuario_id: usuarioId,
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
 * PROC-REP-190 -> 200 ("Requiere redefinicion") -> 210 -> 211 [-> 125]
 * (EXC-REP-004). Técnico propietario; el motivo es obligatorio.
 */
export function requerirRedefinicion(
  ordenId: string,
  ejecucionId: string,
  usuarioId: string,
  insumosUtilizados: InsumoUtilizado[],
  motivo: string,
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenId}/executions/${ejecucionId}/requires-redefinition`,
    {
      usuario_id: usuarioId,
      insumos_utilizados: insumosUtilizados,
      motivo,
      observaciones,
    },
  );
}

/** PROC-REP-126: revisión técnica de UN Detalle pendiente (Técnico). */
export function revisarDetalle(
  ordenId: string,
  detalleId: string,
  usuarioId: string,
  resultado: string,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenId}/details/${detalleId}/technical-review`,
    { usuario_id: usuarioId, resultado },
  );
}

/**
 * PROC-REP-127 -> 080 -> 090 [-> 140 | -> 100]: Recepción redefine el
 * mismo Detalle y se revalida la factibilidad.
 */
export function redefinirDetalle(
  ordenId: string,
  detalleId: string,
  usuarioId: string,
  tipoReparacionId: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/details/${detalleId}/redefine`, {
    usuario_id: usuarioId,
    tipo_reparacion_id: tipoReparacionId,
  });
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

/**
 * Registra un Pago (FEAT-REP-007 / BR-REP-017). `metodo` es un ID del
 * catálogo de medios; `operacionId` identifica el envío para que un
 * reintento no lo duplique.
 */
export function registrarPago(
  ordenId: string,
  usuarioId: string,
  monto: string,
  metodo: string,
  referencia: string | null = null,
  operacionId: string | null = null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/payments`, {
    usuario_id: usuarioId,
    monto,
    metodo,
    referencia,
    operacion_id: operacionId,
  });
}

/** Anula un Pago registrado por error (Administración, con motivo). */
export function anularPago(
  ordenId: string,
  pagoId: string,
  usuarioId: string,
  motivo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/payments/${pagoId}/void`, {
    usuario_id: usuarioId,
    motivo,
  });
}

export interface DatosDevolucionDinero {
  pago_id: string;
  monto: string;
  medio: string;
  motivo: string;
  referencia: string | null;
  operacion_id: string | null;
}

/** Devuelve dinero al cliente desde un Pago (saldo a favor, BR-REP-038). */
export function devolverDinero(
  ordenId: string,
  usuarioId: string,
  datos: DatosDevolucionDinero,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/refunds`, {
    usuario_id: usuarioId,
    ...datos,
  });
}

/** Quién retira el equipo y cómo se identifica (sin firma digital). */
export interface DatosRetiro {
  recibido_por: string;
  identificacion_receptor: string | null;
  observaciones: string | null;
}

/**
 * PROC-REP-280 -> 270 -> EVT-REP-999 (Administración o Recepción). Exige
 * la custodia confirmada y quién retira; emite el comprobante final y la
 * garantía.
 */
export function entregar(
  ordenId: string,
  usuarioId: string,
  retiro: DatosRetiro,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/deliver`, {
    usuario_id: usuarioId,
    ...retiro,
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
 * PROC-REP-035 -> 040 -> 045 (No) -> 055 -> 050 -> 060 (Recepción,
 * HP-REP-003). Una única garantía para 1..N Detalles de la Orden origen
 * ENTREGADA. Devuelve la NUEVA Orden, EN_REVISION y sin Detalles: la
 * revisión técnica es obligatoria. La Orden origen no se modifica.
 */
export function iniciarGarantiaRma(
  ordenOrigenId: string,
  usuarioId: string,
  detalleOrigenIds: string[],
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenOrigenId}/warranty-rma`, {
    usuario_id: usuarioId,
    detalle_origen_ids: detalleOrigenIds,
  });
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
 * PROC-REP-068 (Sí) -> 075 (Recepción): agrega UN Detalle luego de la
 * revisión. En una garantía RMA, `detalleOrigenId` indica a cuál de sus
 * Detalles origen corresponde (`null` fuera de una garantía).
 */
export function definirReparacionDesdeRevision(
  ordenId: string,
  usuarioId: string,
  tipoReparacionId: string,
  detalleOrigenId: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/review/details`, {
    usuario_id: usuarioId,
    tipo_reparacion_id: tipoReparacionId,
    detalle_origen_id: detalleOrigenId,
  });
}

/**
 * PROC-REP-068 (No) -> 069 (Recepción): la revisión concluye
 * SIN_REPARACION. El motivo es obligatorio. El cierre sigue según el
 * Origen (notificar o informar a Gestión RT).
 */
export function finalizarSinReparacion(
  ordenId: string,
  usuarioId: string,
  motivo: string,
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/review/without-repair`, {
    usuario_id: usuarioId,
    motivo,
    observaciones,
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
 * Impacto en el stock de forzar el Detalle (E3, solo lectura): stock
 * físico, reservado por otras Órdenes y por esta, disponible, requerido y
 * disponible resultante. Es lo que se muestra antes de confirmar.
 */
export function obtenerImpactoOverride(
  ordenId: string,
  detalleId: string,
): Promise<ImpactoOverride> {
  return get<ImpactoOverride>(
    `/api/orders/${ordenId}/details/${detalleId}/resources/override-preview`,
  );
}

/**
 * Override de recursos de UN Detalle bloqueado (Coordinador RMA,
 * BR-REP-003): capacidad transversal, también con factibilidad parcial.
 * Solo con la Orden detenida en PROC-REP-100 continúa 110 (Sí) -> 130 ->
 * 140. El motivo es obligatorio. Solo registra la autorización: no
 * reserva ni descuenta stock, ni toca reservas de otras Órdenes.
 *
 * E3: `confirmado` es la confirmación explícita del impacto mostrado; sin
 * ella el backend no aplica nada (409 CONFIRMACION_REQUERIDA).
 */
export function overrideRecursos(
  ordenId: string,
  detalleId: string,
  usuarioId: string,
  motivo: string,
  confirmado: boolean,
): Promise<Orden> {
  return post<Orden>(
    `/api/orders/${ordenId}/details/${detalleId}/resources/override`,
    { usuario_id: usuarioId, motivo, confirmado },
  );
}

/**
 * PROC-REP-120 -> 080 -> 090 [-> 140] (EXC-REP-001). Evento de sistema:
 * sin `usuario_id`. Solo válido desde PROC-REP-120.
 */
export function revalidarRecursos(ordenId: string): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/resources/revalidate`, {});
}

/**
 * Rechaza el control de UN Detalle (PROC-REP-230 "No" -> 235): se reabre
 * para retrabajo y la Orden vuelve a la cola. Motivo obligatorio.
 */
export function rechazarControl(
  ordenId: string,
  usuarioId: string,
  detalleId: string,
  motivo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/control/reject`, {
    usuario_id: usuarioId,
    detalle_id: detalleId,
    motivo,
  });
}

/** Cancela UN Detalle pendiente (PROC-REP-300). Motivo obligatorio. */
export function cancelarDetalle(
  ordenId: string,
  detalleId: string,
  usuarioId: string,
  motivo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/details/${detalleId}/cancel`, {
    usuario_id: usuarioId,
    motivo,
  });
}

/**
 * Cancela los trabajos pendientes de la Orden (PROC-REP-305 / 306). Lo
 * realizado sigue al cierre; sin trabajo realizado queda CANCELADA.
 */
export function cancelarOrden(
  ordenId: string,
  usuarioId: string,
  motivo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/cancel`, {
    usuario_id: usuarioId,
    motivo,
  });
}

/**
 * Decisión del cliente sobre uno o varios Detalles (PROC-REP-046/047).
 * Un Detalle sin respuesta no se envía: sigue pendiente. Cada decisión
 * lleva la versión de la definición que se le presentó al cliente.
 */
export function registrarDecisionCliente(
  ordenId: string,
  usuarioId: string,
  canal: CanalComunicacion,
  observaciones: string | null,
  decisiones: DecisionDetalle[],
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/authorizations`, {
    usuario_id: usuarioId,
    canal,
    observaciones,
    decisiones,
  });
}

/**
 * El cliente desiste de trabajos ya autorizados: de UN Detalle o, con
 * `detalleId` en `null`, de todos los cancelables (los pendientes se
 * rechazan). Si algo lo impide, el backend responde 409 y no cancela nada.
 */
export function desistir(
  ordenId: string,
  detalleId: string | null,
  usuarioId: string,
  canal: CanalComunicacion,
  motivo: string,
): Promise<Orden> {
  const ruta = detalleId
    ? `/api/orders/${ordenId}/details/${detalleId}/withdrawal`
    : `/api/orders/${ordenId}/withdrawal`;
  return post<Orden>(ruta, { usuario_id: usuarioId, canal, motivo });
}

/** Devolución física del equipo de una Orden CANCELADA (PROC-REP-270). */
export function registrarDevolucion(
  ordenId: string,
  usuarioId: string,
  retiro: DatosRetiro,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/return-equipment`, {
    usuario_id: usuarioId,
    ...retiro,
  });
}

// --- Recepción física y custodia ---------------------------------------

/**
 * Registra o corrige los datos del ingreso (antes de confirmar la
 * recepción). La versión anterior se conserva.
 */
export function registrarRecepcion(
  ordenId: string,
  usuarioId: string,
  datos: DatosRecepcion,
  equipo: DatosEquipo | null,
): Promise<Orden> {
  return put<Orden>(`/api/orders/${ordenId}/reception`, {
    usuario_id: usuarioId,
    ...datos,
    equipo,
  });
}

/** El equipo quedó físicamente en el local (custodia). */
export function confirmarRecepcion(
  ordenId: string,
  usuarioId: string,
  observaciones: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/reception/confirm`, {
    usuario_id: usuarioId,
    observaciones,
  });
}

/**
 * El equipo nunca ingresó (Orden cancelada, motivo obligatorio). Sin equipo
 * que devolver, la Orden cierra o espera la devolución del saldo a favor.
 */
export function registrarEquipoNoRecibido(
  ordenId: string,
  usuarioId: string,
  motivo: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/reception/not-received`, {
    usuario_id: usuarioId,
    motivo,
  });
}

/** Observación complementaria del ingreso (no reemplaza nada). */
export function agregarObservacionRecepcion(
  ordenId: string,
  usuarioId: string,
  texto: string,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/reception/notes`, {
    usuario_id: usuarioId,
    texto,
  });
}

// --- Documentos ----------------------------------------------------------

/** Documentos emitidos (con contenido) y qué se puede previsualizar. */
export function obtenerDocumentos(ordenId: string): Promise<DocumentosDeOrden> {
  return get<DocumentosDeOrden>(`/api/orders/${ordenId}/documents`);
}

export function obtenerDocumento(
  ordenId: string,
  documentoId: string,
): Promise<DocumentoEmitido> {
  return get<DocumentoEmitido>(
    `/api/orders/${ordenId}/documents/${documentoId}`,
  );
}

/** Contenido con los datos vigentes. No emite ni guarda nada. */
export function vistaPreviaDocumento(
  ordenId: string,
  tipo: TipoDocumento,
): Promise<VistaPreviaDocumento> {
  return get<VistaPreviaDocumento>(
    `/api/orders/${ordenId}/documents/preview/${tipo}`,
  );
}

/** Versión nueva del comprobante de recepción (con motivo si ya hay una). */
export function emitirComprobanteRecepcion(
  ordenId: string,
  usuarioId: string,
  motivo: string | null,
): Promise<Orden> {
  return post<Orden>(`/api/orders/${ordenId}/documents/reception-receipt`, {
    usuario_id: usuarioId,
    motivo,
  });
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
