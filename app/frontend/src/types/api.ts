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
  | "ENTREGADA";

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

export type EstadoDetalle = "DEFINIDO" | "EN_PROGRESO" | "COMPLETO";

export type EstadoControl = "PENDIENTE" | "APROBADO";

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
  control_estado: EstadoControl;
  control_usuario_id: string | null;
  control_fecha: string | null;
  control_observaciones: string | null;
  observaciones: string | null;
  /** Detalle de la Orden origen que motiva esta garantía (HP-REP-003). */
  detalle_origen_id: string | null;
  /** Resuelto por la API contra el catálogo; no vive en el dominio. */
  insumos_previstos: InsumoPrevisto[];
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
  reparaciones_detail: Detalle[];
  tomas: Toma[];
  ejecuciones: Ejecucion[];
  pagos: Pago[];
  documentos: Documentos;
  resumen: ResumenComercial;
  historial: PasoHistorial[];
  progreso: PasoProgreso[];
  acciones_disponibles: Accion[];
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
