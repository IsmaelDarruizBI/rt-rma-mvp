/**
 * Tipos de la API del MVP.
 *
 * Espejan los DTOs de `app/backend/app/api/schemas.py`. Los importes y
 * cantidades viajan como string porque el backend usa Decimal: se
 * convierten a number solo para mostrarlos, nunca para operar.
 */

export type EstadoWorkflow =
  | "REQUERIMIENTO"
  | "EN_REVISION"
  | "HABILITADA"
  | "EN_COLA"
  | "EN_REPARACION"
  | "REPARACION_LISTA"
  | "ENTREGADA"
  /** Todos los Detalles cancelados, o cancelada sin Detalles. No es ENTREGADA. */
  | "CANCELADA";

export type OrigenOrden =
  | "CLIENTE_EXTERNO"
  | "RT_INTERNO"
  | "RMA_GARANTIA_REPARACION";

/** BR-REP-016: condición comercial derivada del Origen, no del Detalle. */
export type CondicionComercial =
  | "COBRABLE"
  | "NO_COBRABLE_AL_CLIENTE"
  | "NO_COBRABLE";

export type EstadoPago = "PENDIENTE" | "PARCIAL" | "PAGADO";

/** Momento comercial del cobro. Distinto del medio (`metodo`). */
export type TipoPago = "ANTICIPO" | "PAGO";

/** COMPLETO y CANCELADO son terminales. Un CANCELADO no se cobra ni se borra. */
export type EstadoDetalle = "DEFINIDO" | "EN_PROGRESO" | "COMPLETO" | "CANCELADO";

/**
 * Condición de bloqueo del Detalle, enviada por el backend. Es una
 * dimensión independiente del estado: la UI nunca la infiere del stock.
 * `REQUIERE_DEFINICION` se muestra pero su flujo no está implementado.
 */
export type CondicionDetalle =
  | "SIN_BLOQUEO"
  | "REQUIERE_DEFINICION"
  | "BLOQUEADO_POR_RECURSOS";

/** Control VIGENTE: tras un rechazo vuelve a PENDIENTE hasta el retrabajo. */
export type EstadoControl = "PENDIENTE" | "APROBADO";

/** Resultado de UN control registrado (aprobación o rechazo). */
export type ResultadoControl = "APROBADO" | "RECHAZADO";

/** Un control técnico tal como ocurrió (E14: nunca se reemplaza). */
export interface ControlTecnico {
  resultado: ResultadoControl;
  usuario_id: string;
  fecha: string;
  observaciones: string | null;
  ejecucion_id: string | null;
}

/** Quién canceló el Detalle, cuándo y por qué (PROC-REP-300/305). */
export interface Cancelacion {
  usuario_id: string;
  fecha: string;
  motivo: string;
  /**
   * INTERNA; RECHAZO_CLIENTE (rechazó la propuesta pendiente) o
   * DESISTIMIENTO_CLIENTE (la había autorizado y desistió después).
   */
  origen: OrigenCancelacion;
}

export type OrigenCancelacion =
  | "INTERNA"
  | "RECHAZO_CLIENTE"
  | "DESISTIMIENTO_CLIENTE";

/** Decisión que se REGISTRA: "sin respuesta" no es una decisión. */
export type ResultadoAutorizacion = "AUTORIZADO" | "RECHAZADO";

/** Canal provisorio del MVP (BR-REP-028 deja el canal pendiente). */
export type CanalComunicacion =
  | "PRESENCIAL"
  | "TELEFONO"
  | "WHATSAPP"
  | "EMAIL"
  | "OTRO";

/** Estado derivado por el backend para la definición vigente del Detalle. */
export type EstadoAutorizacion =
  | "NO_REQUERIDA"
  | "PENDIENTE"
  | "AUTORIZADO"
  | "RECHAZADO"
  | "SIN_DECISION";

/** Dónde está el Detalle respecto de la decisión del cliente (derivado). */
export type SituacionAutorizacion =
  | "NO_REQUERIDA"
  | "PENDIENTE_AUTORIZACION"
  | "AUTORIZADO_FACTIBLE"
  | "AUTORIZADO_SIN_STOCK"
  | "REQUIERE_REDEFINICION"
  | "EN_EJECUCION"
  | "COMPLETO"
  | "CANCELADO_POR_RECHAZO"
  | "CANCELADO_POR_DESISTIMIENTO"
  | "CANCELADO";

/** Una decisión del cliente registrada (PROC-REP-046). Nunca se reemplaza. */
export interface AutorizacionCliente {
  version_definicion: number;
  resultado: ResultadoAutorizacion;
  usuario_id: string;
  fecha: string;
  canal: CanalComunicacion;
  observaciones: string | null;
}

/**
 * Qué haría hoy el desistimiento total del cliente (lo calcula el backend):
 * pendientes que se rechazan, autorizados que se cancelan, lo COMPLETO que
 * se conserva y lo que lo impide (con eso no se aplica nada).
 */
export interface Desistimiento {
  rechazables: string[];
  desistibles: string[];
  conservados: string[];
  bloqueantes: { detalle_id: string; motivo: string }[];
}

/** Lo que Recepción envía por cada Detalle con respuesta del cliente. */
export interface DecisionDetalle {
  detalle_id: string;
  version_definicion: number;
  resultado: ResultadoAutorizacion;
}

/** Devolución física del equipo de una Orden CANCELADA (PROC-REP-270). */
export interface Devolucion {
  entregado_por: string;
  recibido_por: string;
  fecha: string;
  observaciones: string | null;
}

/** INTERRUMPIDO y COMPLETADO son los resultados terminales de PROC-REP-200. */
export type EstadoEjecucion = "EN_PROGRESO" | "COMPLETADO" | "INTERRUMPIDO";

export type EstadoToma = "ACTIVA" | "CERRADA";

export type RolUsuario =
  | "ADMINISTRADOR"
  | "RECEPCION"
  | "COORDINADOR_RMA"
  | "TECNICO";

export interface Usuario {
  id: string;
  nombre: string;
  rol: RolUsuario;
  activo: boolean;
}

export interface TipoReparacion {
  id: string;
  nombre: string;
  precio: string;
  puntaje: number;
  garantia_dias: number;
  activo: boolean;
}

export interface Estacion {
  id: string;
  nombre: string;
  activa: boolean;
}

export interface Cliente {
  id: string;
  nombre: string;
  telefono: string;
  email: string | null;
}

export interface Equipo {
  id: string;
  marca: string;
  modelo: string;
  falla_reportada: string;
  imei: string | null;
  numero_serie: string | null;
}

/** Insumo que el Tipo de Reparación del Detalle prevé consumir. */
export interface InsumoPrevisto {
  insumo_id: string;
  codigo: string;
  nombre: string;
  cantidad_prevista: string;
}

export interface Detalle {
  id: string;
  tipo_reparacion_id: string;
  /** Nombre del catálogo, resuelto por la API. No se persiste. */
  tipo_reparacion_nombre: string;
  precio: string;
  puntaje: number;
  garantia_dias: number;
  estado: EstadoDetalle;
  condicion: CondicionDetalle;
  control_estado: EstadoControl;
  control_usuario_id: string | null;
  control_fecha: string | null;
  control_observaciones: string | null;
  observaciones: string | null;
  /** Detalle de la Orden origen que motiva esta garantía (HP-REP-003). */
  detalle_origen_id: string | null;
  /** Definiciones reemplazadas por PROC-REP-127 (EXC-REP-004). */
  definiciones_anteriores: DefinicionAnterior[];
  /** Todos los controles registrados, del más antiguo al más reciente. */
  controles: ControlTecnico[];
  /** Reabierto por un control rechazado y todavía sin rehacer. */
  pendiente_de_retrabajo: boolean;
  /** Solo en un Detalle CANCELADO. */
  cancelacion: Cancelacion | null;
  /** Resuelto por la API contra el catálogo; no vive en el dominio. */
  insumos_previstos: InsumoPrevisto[];
  /** Definición vigente: 1 + las reemplazadas por PROC-REP-127. */
  version_definicion: number;
  /** Todas las decisiones del cliente, de cualquier versión. */
  autorizaciones: AutorizacionCliente[];
  estado_autorizacion: EstadoAutorizacion;
  situacion_autorizacion: SituacionAutorizacion;
}

/** Definición de un Detalle reemplazada por PROC-REP-127 (BR-REP-015). */
export interface DefinicionAnterior {
  tipo_reparacion_id: string;
  precio: string;
  puntaje: number;
  garantia_dias: number;
  reemplazada_en: string;
  usuario_id: string;
}

export interface Toma {
  id: string;
  usuario_id: string;
  estacion_id: string;
  estado: EstadoToma;
  inicio: string;
  fin: string | null;
}

export interface InsumoUtilizado {
  insumo_id: string;
  cantidad: string;
}

export interface Ejecucion {
  id: string;
  reparacion_detail_id: string;
  toma_orden_id: string;
  usuario_id: string;
  estado: EstadoEjecucion;
  inicio: string;
  fin: string | null;
  insumos_utilizados: InsumoUtilizado[];
  observaciones: string | null;
  /** PROC-REP-200 "Requiere redefinicion" (EXC-REP-004). */
  motivo_redefinicion: string | null;
}

export interface Pago {
  id: string;
  monto: string;
  tipo_pago: TipoPago;
  metodo: string;
  usuario_id: string;
  fecha: string;
}

export interface Documento {
  generado: boolean;
  fecha_generacion: string | null;
}

export interface Documentos {
  comprobante_recepcion: Documento;
  comprobante_final: Documento;
  garantia_reparacion: Documento;
}

export interface ResumenComercial {
  total: string;
  pagado: string;
  saldo: string;
  estado_pago: EstadoPago;
  puntaje_total: number;
  /** COBRABLE (cliente) / NO_COBRABLE_AL_CLIENTE (RT) / NO_COBRABLE. */
  condicion_comercial: CondicionComercial;
}

/**
 * Qué clase de referencia guarda una entrada del historial.
 *
 * PROCESS_NODE      → paso del recorrido del Business Process.
 * FUNCTIONAL_ACTION → capacidad transversal (ACC-REP-*), que no mueve
 *                     `current_process`.
 */
export type TipoReferencia = "PROCESS_NODE" | "FUNCTIONAL_ACTION";

export interface PasoHistorial {
  tipo_referencia: TipoReferencia;
  referencia_id: string;
  accion: string;
  fecha: string;
  usuario_id: string | null;
  reparacion_detail_id: string | null;
  ejecucion_id: string | null;
  pago_id: string | null;
  observacion: string | null;
  /** Compatibilidad: `null` cuando la entrada es transversal. */
  process_id: string | null;
}

export interface PasoProgreso {
  process_id: string;
  etiqueta: string;
  alcanzado: boolean;
}

/** Accion humana que la Orden admite ahora, segun el backend. */
export interface Accion {
  codigo: string;
  etiqueta: string;
  /** Todos los actores autorizados. Vacío = el negocio no definió rol. */
  roles: RolUsuario[];
  detalle_id: string | null;
  ejecucion_id: string | null;
  /**
   * `false` marca un nodo `actor: ACT-SYSTEM` (p. ej. Informar a Gestión
   * RT): no hay actor humano que autorizar y el comando no recibe
   * `usuario_id`. `true` (default) es el caso humano normal.
   */
  requiere_actor: boolean;
  /**
   * E2: si viene, es la ÚNICA persona que puede ejecutarla (el titular de
   * la toma activa en las acciones técnicas). `null` = cualquiera con el rol.
   */
  usuario_id: string | null;
}

/** Un insumo previsto ante el override (E3): lo que se confirma. */
export interface ImpactoStockInsumo {
  insumo_id: string;
  codigo: string;
  nombre: string;
  stock_fisico: string;
  reservado_otras_ordenes: string;
  reservado_esta_orden: string;
  disponible: string;
  requerido: string;
  disponible_resultante: string;
}

/** `GET .../resources/override-preview`: impacto de forzar un Detalle. */
export interface ImpactoOverride {
  orden_id: string;
  detalle_id: string;
  insumos: ImpactoStockInsumo[];
  deja_disponible_negativo: boolean;
  hay_reservas_de_otras_ordenes: boolean;
  advertencia: string;
}

/**
 * Detalle de la Orden origen de una garantía RMA (HP-REP-003). El nombre
 * del Tipo lo resuelve la API leyendo la Orden origen; no se persiste.
 */
export interface DetalleOrigen {
  id: string;
  tipo_reparacion_nombre: string;
}

export interface OrdenResumen {
  id: string;
  origen: OrigenOrden;
  /** Orden ENTREGADA de la que nace una garantía RMA; `null` si no aplica. */
  orden_origen_id: string | null;
  estado_workflow: EstadoWorkflow;
  current_process: string;
  prioridad: number;
  /** Nombre del Cliente, o identificación RT cuando no hay Cliente. */
  cliente_nombre: string;
  equipo: string;
  total: string;
  saldo: string;
  estado_pago: EstadoPago;
  created_at: string;
  updated_at: string;
}

export interface Orden {
  id: string;
  origen: OrigenOrden;
  estado_workflow: EstadoWorkflow;
  current_process: string;
  prioridad: number;
  /** `null` en RT_INTERNO: el equipo es de Rosario Tecno, no hay Cliente. */
  cliente: Cliente | null;
  equipo: Equipo;
  /** Contexto de Gestion RT (PROC-REP-020). `null` salvo en RT_INTERNO. */
  referencia_rt: string | null;
  /** Orden origen de una garantía RMA (HP-REP-003). `null` en los demás Origenes. */
  orden_origen_id: string | null;
  /** Detalles de la Orden origen identificados en PROC-REP-035 (garantía RMA). */
  detalles_origen_ids: string[];
  /** Los mismos Detalles origen, con el nombre de su Tipo (presentación). */
  detalles_origen: DetalleOrigen[];
  /**
   * PROC-REP-069: la revisión concluyó SIN_REPARACION. Lo deriva el backend
   * del historial; no es un estado de workflow.
   */
  finalizada_sin_reparacion: boolean;
  /**
   * E1: la Orden terminó su proceso (entregada o devuelta a Gestión RT) y
   * solo puede consultarse. Lo deriva el backend.
   */
  cerrada: boolean;
  reparaciones_detail: Detalle[];
  tomas: Toma[];
  /** E2: toma vigente (técnico, estación, inicio), o `null`. */
  toma_activa: Toma | null;
  ejecuciones: Ejecucion[];
  pagos: Pago[];
  documentos: Documentos;
  resumen: ResumenComercial;
  historial: PasoHistorial[];
  progreso: PasoProgreso[];
  acciones_disponibles: Accion[];
  /** Cancelaciones posibles ahora (Detalle u Orden), aparte del flujo. */
  acciones_cancelacion: Accion[];
  /** El Origen exige la decisión del cliente por Detalle (BR-REP-028). */
  autorizacion_requerida: boolean;
  /** Decisiones comerciales del cliente posibles ahora (decidir, desistir). */
  acciones_autorizacion: Accion[];
  /** Vista previa del desistimiento total (Cliente Externo con Detalles). */
  desistimiento: Desistimiento | null;
  /** Orden CANCELADA: devolución física registrada, o `null`. */
  devolucion: Devolucion | null;
  /** Orden CANCELADA con el equipo todavía en custodia. */
  devolucion_pendiente: boolean;
  created_at: string;
  updated_at: string;
  /** Solo lo devuelven notificar y registrar pago (PROC-REP-265). */
  puede_entregar?: boolean;
}

export interface Catalogos {
  tipos: TipoReparacion[];
  estaciones: Estacion[];
  usuarios: Usuario[];
}
