/**
 * Acciones que la Orden admite ahora.
 *
 * La lista NO se calcula acá: la manda el backend en
 * `acciones_disponibles`. El frontend solo decide cuáles mostrarle al
 * actor seleccionado y qué formulario necesita cada una.
 *
 * Ocultar un botón es comodidad, no seguridad: el backend valida el rol
 * igual (PROC-REP V1.3 define el actor de cada nodo).
 */

import { type ReactNode, useEffect, useId, useState } from "react";

import {
  type DatosRetiro,
  TIPO_REPARACION_OTROS,
  type TrabajoOtros,
} from "../../api/ordenes";
import {
  Boton,
  Campo,
  colores,
  estiloInput,
  importe,
} from "../../components/ui";
import type {
  Accion,
  DetalleOrigen,
  Estacion,
  ImpactoOverride,
  InsumoPrevisto,
  InsumoUtilizado,
  Orden,
  Prioridad,
  TipoReparacion,
  Usuario,
} from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";
import {
  NOMBRE_ACCION,
  descripcionCheckin,
  nombreAccion,
  nombreTrabajo,
} from "./etiquetas";
import { Confirmacion } from "./PagosOrden";
import {
  CODIGOS_SECUNDARIOS,
  TituloAccion,
  UbicacionAccion,
} from "./presentacion";
import { opcionDePrioridad, prioridadPropuesta } from "./prioridad";

export interface EjecutorAcciones {
  /** `otros`: descripción y precio de un trabajo «Otros». */
  agregarDetalle: (tipoReparacionId: string, otros: TrabajoOtros | null) => void;
  finalizarDefinicion: () => void;
  encolar: (prioridad: number) => void;
  tomar: (estacionId: string) => void;
  iniciarDetalle: (detalleId: string) => void;
  completarEjecucion: (
    ejecucionId: string,
    insumosUtilizados: InsumoUtilizado[],
    observaciones: string,
  ) => void;
  esperarRecursos: () => void;
  revalidarRecursos: () => void;
  /** E3: impacto en el stock, para mostrarlo ANTES de confirmar. */
  consultarImpactoOverride: (detalleId: string) => Promise<ImpactoOverride>;
  /** Solo se llama con la confirmación explícita del impacto (E3). */
  overrideRecursos: (detalleId: string, motivo: string) => void;
  interrumpirEjecucion: (
    ejecucionId: string,
    insumosUtilizados: InsumoUtilizado[],
    motivo: string,
    observaciones: string,
  ) => void;
  requerirRedefinicion: (
    ejecucionId: string,
    insumosUtilizados: InsumoUtilizado[],
    motivo: string,
    observaciones: string,
  ) => void;
  revisarDetalle: (detalleId: string, resultado: string) => void;
  redefinirDetalle: (detalleId: string, tipoReparacionId: string) => void;
  aprobarControl: (detalleId: string | null, observaciones: string) => void;
  liberarOrden: () => void;
  notificar: () => void;
  /** PROC-REP-280 -> 270: con quién retira (exige custodia confirmada). */
  entregar: (retiro: DatosRetiro) => void;
  informarRt: () => void;
  devolverRt: () => void;
  iniciarGarantiaRma: (detalleOrigenIds: string[]) => void;
  enviarARevision: () => void;
  realizarRevision: (resultado: string) => void;
  agregarDetalleDesdeRevision: (
    tipoReparacionId: string,
    detalleOrigenId: string | null,
    otros: TrabajoOtros | null,
  ) => void;
  finalizarSinReparacion: (motivo: string, observaciones: string) => void;
  /** PROC-REP-235: reabre el Detalle para retrabajo. */
  rechazarControl: (detalleId: string, motivo: string) => void;
  /** PROC-REP-270 sobre una Orden CANCELADA. */
  registrarDevolucion: (retiro: DatosRetiro) => void;
  /** PROC-REP-300. */
  cancelarDetalle: (detalleId: string, motivo: string) => void;
  /** PROC-REP-305 / 306 (pide confirmación antes). */
  cancelarOrden: (motivo: string) => void;
  /** En cola o en reparación: no vuelve a encolar. */
  cambiarPrioridad: (prioridad: number, motivo: string | null) => void;
  /** La Orden de OTRO técnico: con motivo; ya confirmado en el formulario. */
  liberarOrdenAjena: (motivo: string, insumosUtilizados: InsumoUtilizado[]) => void;
  ajustarGarantia: (detalleId: string, dias: number, motivo: string) => void;
  /** Antes de entregar: si se pudieron verificar las funciones básicas. */
  registrarCheckin: (realizado: boolean) => void;
}

interface Props {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  tipos: TipoReparacion[];
  estaciones: Estacion[];
  prioridades: Prioridad[];
  ocupado: boolean;
  ejecutar: EjecutorAcciones;
}

/**
 * Las acciones del flujo que la Orden admite ahora (`acciones_disponibles`).
 *
 * La lista la manda el backend. Cada formulario se ubica solo: el de la
 * tarea pendiente va a «Próximo paso», el excepcional a «Otras acciones»
 * y el resto queda acá. Registrar un pago vive en «Cobros», con el saldo
 * y los medios de pago.
 */
export function AccionesOrden(props: Props) {
  // Registrar un pago vive en «Cobros»; generar el comprobante de ingreso,
  // en «Documentos» (con su visor, el PDF y WhatsApp).
  const acciones = props.orden.acciones_disponibles.filter(
    (accion) =>
      accion.codigo !== "REGISTRAR_PAGO" &&
      accion.codigo !== "GENERAR_COMPROBANTE_INGRESO",
  );
  return (
    <>
      {acciones.map((accion) => (
        <AccionUnica
          key={accion.codigo + (accion.detalle_id ?? "")}
          accion={accion}
          {...props}
        />
      ))}
    </>
  );
}

/**
 * Cancelaciones de la Orden (PROC-REP-300/305/306), aparte de la acción del
 * flujo: son capacidades excepcionales, posibles en casi cualquier etapa.
 * Las publica el backend en `acciones_cancelacion`; van a «Otras acciones».
 * Cancelar la Orden completa pide confirmación.
 */
export function CancelacionesOrden(props: Props) {
  return (
    <>
      {props.orden.acciones_cancelacion.map((accion) => (
        <AccionUnica
          key={accion.codigo + (accion.detalle_id ?? "")}
          accion={accion}
          {...props}
        />
      ))}
    </>
  );
}

/**
 * Capacidades que no avanzan el proceso (`acciones_complementarias`):
 * cambiar la prioridad, liberar la Orden de otro técnico y ajustar el plazo
 * de garantía de un trabajo. Van a «Otras acciones» o, la liberación, a
 * «Situaciones especiales».
 */
export function ComplementariasOrden(props: Props) {
  return (
    <>
      {props.orden.acciones_complementarias.map((accion) => (
        <AccionUnica
          key={accion.codigo + (accion.detalle_id ?? "")}
          accion={accion}
          {...props}
        />
      ))}
    </>
  );
}

/**
 * Una acción con su formulario. Si el usuario actual no puede ejecutarla
 * (rol o titular de la toma) no se dibuja: «Próximo paso» dice a quién le
 * toca. Ocultarla es comodidad, no seguridad: el backend valida igual.
 */
function AccionUnica({
  accion,
  orden,
  usuarios,
  tipos,
  estaciones,
  prioridades,
  ocupado,
  ejecutar,
}: Props & { accion: Accion }) {
  const formulario = (
    <FormularioAccion
      accion={accion}
      orden={orden}
      usuarios={usuarios}
      tipos={tipos}
      estaciones={estaciones}
      prioridades={prioridades}
      deshabilitado={ocupado}
      ejecutar={ejecutar}
    />
  );
  return (
    <UbicacionAccion accion={accion}>
      <div
        style={{
          marginBottom: "0.9rem",
          paddingBottom: "0.9rem",
          borderBottom: `1px solid ${colores.borde}`,
        }}
      >
        {CODIGOS_SECUNDARIOS.has(accion.codigo) ? (
          // La tarea ya dice en qué trabajo: el botón va corto.
          <OpcionSecundaria
            titulo={NOMBRE_ACCION[accion.codigo] ?? accion.etiqueta}
          >
            {formulario}
          </OpcionSecundaria>
        ) : (
          <>
            <TituloAccion>{nombreAccion(orden, accion)}</TituloAccion>
            {formulario}
          </>
        )}
      </div>
    </UbicacionAccion>
  );
}

/**
 * Otra salida de la misma tarea, menos habitual (interrumpir junto a
 * completar): un botón secundario a la vista que despliega su formulario.
 */
function OpcionSecundaria({
  titulo,
  children,
}: {
  titulo: string;
  children: ReactNode;
}) {
  const [abierta, setAbierta] = useState(false);
  if (!abierta) {
    return (
      <Boton variante="secundario" onClick={() => setAbierta(true)}>
        {titulo}
      </Boton>
    );
  }
  return (
    <div
      style={{
        padding: "0.7rem 0.8rem",
        borderRadius: 6,
        border: `1px solid ${colores.alerta}`,
        background: "#fffaf0",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
          gap: "0.5rem",
          marginBottom: "0.5rem",
        }}
      >
        <strong>{titulo}</strong>
        <button
          type="button"
          onClick={() => setAbierta(false)}
          style={{
            border: "none",
            background: "none",
            padding: 0,
            color: colores.acento,
            textDecoration: "underline",
            cursor: "pointer",
            font: "inherit",
            fontSize: "0.85rem",
          }}
        >
          Volver
        </button>
      </div>
      {children}
    </div>
  );
}

function FormularioAccion({
  accion,
  orden,
  usuarios,
  tipos,
  estaciones,
  prioridades,
  deshabilitado,
  ejecutar,
}: {
  accion: Accion;
  orden: Orden;
  usuarios: Usuario[];
  tipos: TipoReparacion[];
  estaciones: Estacion[];
  prioridades: Prioridad[];
  deshabilitado: boolean;
  ejecutar: EjecutorAcciones;
}) {
  switch (accion.codigo) {
    case "AGREGAR_DETALLE":
      return (
        <FormularioAgregarDetalle
          tipos={tipos}
          cantidadDetallesActual={orden.reparaciones_detail.length}
          detallesOrigen={[]}
          deshabilitado={deshabilitado}
          onConfirmar={(tipoId, _origen, otros) =>
            ejecutar.agregarDetalle(tipoId, otros)
          }
        />
      );

    case "FINALIZAR_DEFINICION":
      return (
        <FormularioFinalizarDefinicion
          orden={orden}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.finalizarDefinicion}
        />
      );

    case "ESPERAR_RECURSOS":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.esperarRecursos}>
          Dejar esperando repuestos (sin forzar el trabajo)
        </Boton>
      );

    case "OVERRIDE_RECURSOS":
      return (
        <FormularioMotivoOverride
          deshabilitado={deshabilitado || accion.detalle_id === null}
          orden={orden}
          detalleId={accion.detalle_id}
          consultarImpacto={ejecutar.consultarImpactoOverride}
          onConfirmar={ejecutar.overrideRecursos}
        />
      );

    case "REVALIDAR_RECURSOS":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.revalidarRecursos}>
          Revalidar la disponibilidad de repuestos
        </Boton>
      );

    case "ENVIAR_A_REVISION":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.enviarARevision}>
          Enviar a revisión técnica
        </Boton>
      );

    case "REALIZAR_REVISION":
      return (
        <FormularioResultadoRevision
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.realizarRevision}
        />
      );

    case "AGREGAR_DETALLE_DESDE_REVISION":
      return (
        <FormularioAgregarDetalle
          tipos={tipos}
          cantidadDetallesActual={orden.reparaciones_detail.length}
          detallesOrigen={orden.detalles_origen}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.agregarDetalleDesdeRevision}
        />
      );

    case "FINALIZAR_SIN_REPARACION":
      return (
        <FormularioSinReparacion
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.finalizarSinReparacion}
        />
      );

    case "ENCOLAR":
      return (
        <FormularioPrioridad
          prioridades={prioridades}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.encolar}
        />
      );

    case "TOMAR":
      return (
        <SelectorSimple
          etiqueta="Estación de trabajo"
          opciones={estaciones.map((estacion) => ({
            valor: estacion.id,
            texto: estacion.nombre,
          }))}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.tomar}
        />
      );

    case "INICIAR_DETALLE":
      return (
        <div>
          {accion.bloqueo && (
            <p
              role="status"
              style={{
                margin: "0 0 0.5rem",
                padding: "0.5rem 0.7rem",
                borderRadius: 6,
                border: `1px solid ${colores.alerta}`,
                background: "#fff8e6",
                fontSize: "0.85rem",
              }}
            >
              <strong>{accion.bloqueo}.</strong>
              {accion.bloqueo.startsWith("Debe confirmarse") && (
                <> La confirma Recepción, desde «Cliente y equipo».</>
              )}
            </p>
          )}
          <Boton
            disabled={
              deshabilitado || !accion.detalle_id || accion.bloqueo !== null
            }
            onClick={() =>
              accion.detalle_id && ejecutar.iniciarDetalle(accion.detalle_id)
            }
          >
            Iniciar y reservar insumos
          </Boton>
        </div>
      );

    case "COMPLETAR_EJECUCION":
      return (
        <FormularioEjecucion
          modo="completar"
          previstos={insumosPrevistosDe(orden, accion.ejecucion_id)}
          deshabilitado={deshabilitado || !accion.ejecucion_id}
          onConfirmar={(insumosUtilizados, observaciones) =>
            accion.ejecucion_id &&
            ejecutar.completarEjecucion(
              accion.ejecucion_id,
              insumosUtilizados,
              observaciones,
            )
          }
        />
      );

    case "INTERRUMPIR_EJECUCION":
      return (
        <FormularioEjecucion
          modo="interrumpir"
          previstos={insumosPrevistosDe(orden, accion.ejecucion_id)}
          deshabilitado={deshabilitado || !accion.ejecucion_id}
          onConfirmar={(insumosUtilizados, observaciones, motivo) =>
            accion.ejecucion_id &&
            ejecutar.interrumpirEjecucion(
              accion.ejecucion_id,
              insumosUtilizados,
              motivo,
              observaciones,
            )
          }
        />
      );

    case "REQUIERE_REDEFINICION":
      return (
        <FormularioEjecucion
          modo="redefinir"
          previstos={insumosPrevistosDe(orden, accion.ejecucion_id)}
          deshabilitado={deshabilitado || !accion.ejecucion_id}
          onConfirmar={(insumosUtilizados, observaciones, motivo) =>
            accion.ejecucion_id &&
            ejecutar.requerirRedefinicion(
              accion.ejecucion_id,
              insumosUtilizados,
              motivo,
              observaciones,
            )
          }
        />
      );

    case "REVISAR_DETALLE":
      return (
        <FormularioResultadoRevision
          deshabilitado={deshabilitado || !accion.detalle_id}
          textoBoton={`Registrar la revisión de ${nombreTrabajo(
            orden,
            accion.detalle_id,
          )}`}
          onConfirmar={(resultado) =>
            accion.detalle_id &&
            ejecutar.revisarDetalle(accion.detalle_id, resultado)
          }
        />
      );

    case "REDEFINIR_DETALLE":
      return (
        <FormularioRedefinirDetalle
          tipos={tipos}
          detalle={orden.reparaciones_detail.find(
            (candidato) => candidato.id === accion.detalle_id,
          )}
          deshabilitado={deshabilitado || !accion.detalle_id}
          onConfirmar={(tipoId) =>
            accion.detalle_id &&
            ejecutar.redefinirDetalle(accion.detalle_id, tipoId)
          }
        />
      );

    case "APROBAR_CONTROL":
      return (
        <FormularioObservaciones
          deshabilitado={deshabilitado}
          textoBoton={
            accion.detalle_id
              ? `Aprobar ${nombreTrabajo(orden, accion.detalle_id)}`
              : "Aprobar el control"
          }
          onConfirmar={(observaciones) =>
            ejecutar.aprobarControl(accion.detalle_id, observaciones)
          }
        />
      );

    case "LIBERAR_ORDEN":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.liberarOrden}>
          Liberar la Orden
        </Boton>
      );

    case "NOTIFICAR":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.notificar}>
          Avisar al cliente
        </Boton>
      );

    case "ENTREGAR":
      return (
        <FormularioEntrega
          orden={orden}
          bloqueo={accion.bloqueo}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.entregar}
        />
      );

    case "REGISTRAR_CHECKIN":
      return (
        <FormularioCheckin
          orden={orden}
          usuarios={usuarios}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.registrarCheckin}
        />
      );

    case "INFORMAR_RT":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.informarRt}>
          Informar resultado a Gestión RT
        </Boton>
      );

    case "INICIAR_GARANTIA_RMA":
      return (
        <FormularioGarantiaRma
          orden={orden}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.iniciarGarantiaRma}
        />
      );

    case "DEVOLVER_RT":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.devolverRt}>
          Devolver equipo a Gestión RT
        </Boton>
      );

    case "RECHAZAR_CONTROL":
      return (
        <FormularioMotivo
          deshabilitado={deshabilitado || accion.detalle_id === null}
          etiqueta="Motivo del rechazo (obligatorio)"
          textoBoton={`Rechazar ${nombreTrabajo(orden, accion.detalle_id)}`}
          onConfirmar={(motivo) =>
            accion.detalle_id &&
            ejecutar.rechazarControl(accion.detalle_id, motivo)
          }
        />
      );

    case "REGISTRAR_DEVOLUCION":
      return (
        <FormularioDevolucion
          orden={orden}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.registrarDevolucion}
        />
      );

    case "CANCELAR_DETALLE":
      return (
        <FormularioMotivo
          deshabilitado={deshabilitado || accion.detalle_id === null}
          etiqueta="Motivo de la cancelación (obligatorio)"
          textoBoton={`Cancelar ${nombreTrabajo(orden, accion.detalle_id)}`}
          onConfirmar={(motivo) =>
            accion.detalle_id &&
            ejecutar.cancelarDetalle(accion.detalle_id, motivo)
          }
        />
      );

    case "CANCELAR_ORDEN":
      return (
        <FormularioMotivo
          deshabilitado={deshabilitado}
          etiqueta="Motivo de la cancelación de la Orden (obligatorio)"
          textoBoton="Cancelar la Orden"
          confirmar={() => window.confirm(mensajeCancelarOrden(orden))}
          onConfirmar={ejecutar.cancelarOrden}
        />
      );

    case "CAMBIAR_PRIORIDAD":
      return (
        <FormularioCambioPrioridad
          actual={orden.prioridad}
          prioridades={prioridades}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.cambiarPrioridad}
        />
      );

    case "LIBERAR_ORDEN_AJENA":
      return (
        <FormularioLiberacionAjena
          orden={orden}
          usuarios={usuarios}
          estaciones={estaciones}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.liberarOrdenAjena}
        />
      );

    case "AJUSTAR_GARANTIA":
      return (
        <FormularioGarantia
          orden={orden}
          detalleId={accion.detalle_id}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.ajustarGarantia}
        />
      );

    default:
      return (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          Acción «{accion.codigo}» sin formulario en esta versión.
        </p>
      );
  }
}

// --- Formularios --------------------------------------------------------

/** Texto de la confirmación antes de cancelar la Orden completa. */
function mensajeCancelarOrden(orden: Orden): string {
  const pendientes = orden.reparaciones_detail.filter(
    (detalle) => detalle.estado === "DEFINIDO",
  ).length;
  const completos = orden.reparaciones_detail.filter(
    (detalle) => detalle.estado === "COMPLETO",
  ).length;
  if (orden.reparaciones_detail.length === 0) {
    return `¿Cancelar la Orden ${orden.id}? No tiene trabajos: queda cancelada.`;
  }
  return (
    `¿Cancelar la Orden ${orden.id}? Se cancelan ${pendientes} trabajo(s) ` +
    "pendiente(s). " +
    (completos > 0
      ? `Los ${completos} trabajo(s) ya realizados no se cancelan y siguen ` +
        "al control y la entrega."
      : "Sin trabajo realizado, la Orden queda cancelada.")
  );
}

/**
 * Un motivo obligatorio y un botón. `confirmar` (opcional) se consulta
 * antes de enviar: si devuelve `false`, no se hace nada.
 */
function FormularioMotivo({
  deshabilitado,
  etiqueta,
  textoBoton,
  confirmar,
  onConfirmar,
}: {
  deshabilitado: boolean;
  etiqueta: string;
  textoBoton: string;
  confirmar?: () => boolean;
  onConfirmar: (motivo: string) => void;
}) {
  const [motivo, setMotivo] = useState("");

  return (
    <div>
      <Campo etiqueta={etiqueta}>
        <input
          value={motivo}
          onChange={(evento) => setMotivo(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || motivo.trim() === ""}
        onClick={() => {
          if (confirmar && !confirmar()) return;
          onConfirmar(motivo.trim());
        }}
      >
        {textoBoton}
      </Boton>
    </div>
  );
}

/** Devolución física del equipo de una Orden CANCELADA: quién lo recibe. */
function FormularioDevolucion({
  orden,
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  deshabilitado: boolean;
  onConfirmar: (retiro: DatosRetiro) => void;
}) {
  const [recibidoPor, setRecibidoPor] = useState(
    orden.cliente?.nombre_apellido ?? "Gestión RT",
  );
  const [identificacion, setIdentificacion] = useState("");
  const [observaciones, setObservaciones] = useState("");

  return (
    <div>
      <Campo etiqueta="Recibe el equipo (obligatorio)">
        <input
          value={recibidoPor}
          onChange={(evento) => setRecibidoPor(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="DNI u otra identificación (si corresponde)">
        <input
          value={identificacion}
          onChange={(evento) => setIdentificacion(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Observaciones">
        <input
          value={observaciones}
          onChange={(evento) => setObservaciones(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || recibidoPor.trim() === ""}
        onClick={() =>
          onConfirmar({
            recibido_por: recibidoPor.trim(),
            identificacion_receptor: identificacion.trim() || null,
            observaciones: observaciones.trim() || null,
          })
        }
      >
        Registrar la devolución (sin cobro)
      </Boton>
      <p style={{ margin: "0.4rem 0 0", fontSize: "0.75rem", color: colores.suave }}>
        Se emite el comprobante de devolución sin reparación. La Orden sigue
        CANCELADA.
      </p>
    </div>
  );
}

/**
 * Entrega del equipo (PROC-REP-280 -> 270): quién retira, su
 * identificación y observaciones, con confirmación. El backend exige la
 * custodia confirmada, el control aprobado y la cuenta saldada; acá solo
 * se avisa si la custodia falta. Al confirmar se emiten el comprobante
 * final y la garantía.
 */
function FormularioEntrega({
  orden,
  bloqueo,
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  /** Por ejemplo, falta el check-in: el backend la rechaza igual. */
  bloqueo: string | null;
  deshabilitado: boolean;
  onConfirmar: (retiro: DatosRetiro) => void;
}) {
  const [recibidoPor, setRecibidoPor] = useState("");
  const [identificacion, setIdentificacion] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const enCustodia = orden.custodia.estado === "EN_CUSTODIA";
  const bloqueado = deshabilitado || !enCustodia || bloqueo !== null;
  const titular = orden.cliente?.nombre_apellido ?? null;
  const devolucion = orden.finalizada_sin_reparacion;

  useEffect(
    () => setConfirmando(false),
    [recibidoPor, identificacion, observaciones],
  );

  const retira = `${recibidoPor.trim()}${
    identificacion.trim() ? ` (${identificacion.trim()})` : ""
  }`;

  return (
    <div>
      {!enCustodia && (
        <p
          role="status"
          style={{
            margin: "0 0 0.6rem",
            padding: "0.5rem 0.7rem",
            borderRadius: 6,
            border: `1px solid ${colores.alerta}`,
            background: "#fff8e6",
            fontSize: "0.85rem",
          }}
        >
          La recepción física del equipo no está confirmada. Confirmala (o
          regularizala) en <strong>Recepción y custodia</strong> antes de
          entregar.
        </p>
      )}
      {bloqueo && (
        <p
          role="status"
          style={{
            margin: "0 0 0.6rem",
            padding: "0.5rem 0.7rem",
            borderRadius: 6,
            border: `1px solid ${colores.alerta}`,
            background: "#fff8e6",
            fontSize: "0.85rem",
          }}
        >
          <strong>{bloqueo}.</strong>{" "}
          {bloqueo.includes("check-in") &&
            "Indicá en «Registrar el check-in» si se pudieron verificar las " +
              "funciones básicas del equipo: define la garantía de cada trabajo."}
        </p>
      )}
      <Campo etiqueta="Retira el equipo (obligatorio)">
        <input
          value={recibidoPor}
          onChange={(evento) => setRecibidoPor(evento.target.value)}
          disabled={bloqueado}
          style={estiloInput}
        />
      </Campo>
      {titular && (
        <div style={{ margin: "-0.3rem 0 0.6rem" }}>
          <Boton
            variante="secundario"
            disabled={bloqueado}
            onClick={() => setRecibidoPor(titular)}
          >
            Retira el titular ({titular})
          </Boton>
        </div>
      )}
      <Campo etiqueta="DNI u otra identificación (si corresponde)">
        <input
          value={identificacion}
          onChange={(evento) => setIdentificacion(evento.target.value)}
          disabled={bloqueado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Observaciones de la entrega">
        <input
          value={observaciones}
          onChange={(evento) => setObservaciones(evento.target.value)}
          disabled={bloqueado}
          style={estiloInput}
        />
      </Campo>
      {!confirmando ? (
        <Boton
          disabled={bloqueado || recibidoPor.trim() === ""}
          onClick={() => setConfirmando(true)}
        >
          {devolucion ? "Devolver el equipo (sin reparación)" : "Entregar equipo"}
        </Boton>
      ) : (
        <Confirmacion
          texto={`¿Confirmás la ${
            devolucion ? "devolución" : "entrega"
          } del equipo a ${retira}? Se emiten el comprobante final${
            devolucion ? "" : " y la garantía"
          }, y la Orden queda cerrada.`}
          ocupado={deshabilitado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={() =>
            onConfirmar({
              recibido_por: recibidoPor.trim(),
              identificacion_receptor: identificacion.trim() || null,
              observaciones: observaciones.trim() || null,
            })
          }
        />
      )}
    </div>
  );
}

/**
 * ¿Se pudieron verificar las funciones básicas del equipo? (check-in).
 * Define la garantía sugerida de cada trabajo: 90 días si sí, 30 si no.
 */
function CampoCheckin({
  valor,
  deshabilitado = false,
  onCambiar,
}: {
  valor: "" | "si" | "no";
  deshabilitado?: boolean;
  onCambiar: (valor: "si" | "no") => void;
}) {
  // Un grupo de radios por formulario: puede haber dos en la misma pantalla.
  const grupo = useId();
  return (
    <fieldset
      style={{
        border: `1px solid ${colores.borde}`,
        borderRadius: 6,
        margin: "0 0 0.6rem",
        padding: "0.4rem 0.7rem 0.5rem",
      }}
    >
      <legend style={{ fontSize: "0.85rem", padding: "0 0.3rem" }}>
        ¿Se pudieron verificar las funciones básicas del equipo?
      </legend>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
        {(
          [
            ["si", "Sí — garantía de 90 días"],
            ["no", "No — garantía de 30 días"],
          ] as const
        ).map(([opcion, texto]) => (
          <label
            key={opcion}
            style={{ display: "flex", gap: "0.35rem", alignItems: "center" }}
          >
            <input
              type="radio"
              name={`checkin-${grupo}`}
              checked={valor === opcion}
              disabled={deshabilitado}
              onChange={() => onCambiar(opcion)}
            />
            {texto}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

/**
 * Check-in antes de la entrega, con la reparación lista (UAT-009). Define
 * la garantía de cada trabajo sin pisar los plazos ajustados a mano. Se
 * puede volver a registrar hasta entregar; avisar y cobrar no dependen de
 * él, pero en Cliente Externo la entrega lo exige.
 */
function FormularioCheckin({
  orden,
  usuarios,
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  usuarios: Usuario[];
  deshabilitado: boolean;
  onConfirmar: (realizado: boolean) => void;
}) {
  const actual = orden.recepcion?.datos.checkin ?? null;
  const [valor, setValor] = useState<"" | "si" | "no">(
    actual === true ? "si" : actual === false ? "no" : "",
  );
  const registros = orden.recepcion?.registros_checkin ?? [];
  const ultimo = registros.length ? registros[registros.length - 1] : null;
  const ajustados = orden.reparaciones_detail.filter(
    (detalle) =>
      detalle.estado !== "CANCELADO" && (detalle.ajustes_garantia ?? []).length > 0,
  );
  const sinCambios = valor === "" || (valor === "si") === actual;
  return (
    <div>
      {actual !== null && (
        <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
          Registrado: {descripcionCheckin(actual)}
          {ultimo
            ? ` · ${nombreDeUsuario(usuarios, ultimo.usuario_id)}`
            : " · en el ingreso"}
          . Se puede cambiar hasta entregar.
        </p>
      )}
      <CampoCheckin valor={valor} deshabilitado={deshabilitado} onCambiar={setValor} />
      {ajustados.length > 0 && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
          Conservan su plazo ajustado a mano:{" "}
          {ajustados
            .map((detalle) => `${detalle.tipo_reparacion_nombre} (${detalle.garantia_dias} días)`)
            .join(", ")}
          .
        </p>
      )}
      <Boton
        disabled={deshabilitado || sinCambios}
        onClick={() => onConfirmar(valor === "si")}
      >
        Registrar el check-in
      </Boton>
    </div>
  );
}

/**
 * Agregar UN Detalle de la reparación (Multi-Detalle).
 *
 * Solo agrega: finalizar la definición es otra acción (otro botón), que
 * el backend publica recién cuando hay al menos un Detalle. En una
 * garantía RMA, luego de la revisión, se elige a cuál de los Detalles
 * origen corresponde el nuevo (sin relación 1:1).
 */
function FormularioAgregarDetalle({
  tipos,
  cantidadDetallesActual,
  detallesOrigen,
  deshabilitado,
  onConfirmar,
}: {
  tipos: TipoReparacion[];
  cantidadDetallesActual: number;
  detallesOrigen: DetalleOrigen[];
  deshabilitado: boolean;
  onConfirmar: (
    tipoReparacionId: string,
    detalleOrigenId: string | null,
    otros: TrabajoOtros | null,
  ) => void;
}) {
  const [tipoId, setTipoId] = useState(tipos[0]?.id ?? "");
  const [origenId, setOrigenId] = useState(detallesOrigen[0]?.id ?? "");
  const [descripcion, setDescripcion] = useState("");
  const [precio, setPrecio] = useState("");
  const pideOrigen = detallesOrigen.length > 0;
  // «Otros»: una reparación no tipificada, con descripción y precio manual.
  const esOtros = tipoId === TIPO_REPARACION_OTROS;
  const precioValido = /^\d+(?:[.,]\d{1,2})?$/.test(precio.trim());
  const otrosCompleto = !esOtros || (descripcion.trim() !== "" && precioValido);

  return (
    <div>
      {pideOrigen && (
        <Campo etiqueta="Trabajo original de la garantía">
          <select
            value={origenId}
            onChange={(evento) => setOrigenId(evento.target.value)}
            disabled={deshabilitado}
            style={estiloInput}
          >
            {detallesOrigen.map((origen) => (
              <option key={origen.id} value={origen.id}>
                {origen.id} · {origen.tipo_reparacion_nombre}
              </option>
            ))}
          </select>
        </Campo>
      )}
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
        <div style={{ flex: 1 }}>
          <Campo
            etiqueta={
              cantidadDetallesActual > 0
                ? `Tipo de reparación (trabajo ${cantidadDetallesActual + 1})`
                : "Tipo de reparación"
            }
          >
            <select
              value={tipoId}
              onChange={(evento) => setTipoId(evento.target.value)}
              disabled={deshabilitado}
              style={estiloInput}
            >
              {tipos.map((tipo) => (
                <option key={tipo.id} value={tipo.id}>
                  {tipo.nombre} — {tipo.precio}
                </option>
              ))}
              <option value={TIPO_REPARACION_OTROS}>
                Otros — Reparación no tipificada (precio manual)
              </option>
            </select>
          </Campo>
        </div>
        {!esOtros && (
          <div style={{ marginBottom: "0.6rem" }}>
            <Boton
              disabled={deshabilitado || !tipoId || (pideOrigen && !origenId)}
              onClick={() => onConfirmar(tipoId, pideOrigen ? origenId : null, null)}
            >
              Agregar trabajo
            </Boton>
          </div>
        )}
      </div>
      {esOtros && (
        <>
          <Campo etiqueta="Descripción del trabajo (obligatoria)">
            <input
              value={descripcion}
              onChange={(evento) => setDescripcion(evento.target.value)}
              disabled={deshabilitado}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Precio (obligatorio)">
            <input
              value={precio}
              onChange={(evento) => setPrecio(evento.target.value)}
              disabled={deshabilitado}
              inputMode="decimal"
              placeholder="15000"
              style={estiloInput}
            />
          </Campo>
          <Boton
            disabled={deshabilitado || !otrosCompleto || (pideOrigen && !origenId)}
            onClick={() => {
              onConfirmar(tipoId, pideOrigen ? origenId : null, {
                descripcion: descripcion.trim(),
                precio: precio.trim().replace(",", "."),
              });
              setDescripcion("");
              setPrecio("");
              setTipoId(tipos[0]?.id ?? "");
            }}
          >
            Agregar trabajo «Otros»
          </Boton>
        </>
      )}
    </div>
  );
}

/**
 * Cierra la carga de Detalles. Muestra lo ya cargado para que Recepción
 * confirme; comprobante, factibilidad y habilitación los resuelve el
 * backend al finalizar.
 */
function FormularioFinalizarDefinicion({
  orden,
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  deshabilitado: boolean;
  onConfirmar: () => void;
}) {
  return (
    <div>
      <p style={{ margin: "0 0 0.3rem", fontSize: "0.85rem" }}>
        Detalles cargados ({orden.reparaciones_detail.length}):
      </p>
      <ul
        style={{
          margin: "0 0 0.6rem",
          paddingLeft: "1.1rem",
          fontSize: "0.85rem",
          color: colores.suave,
        }}
      >
        {orden.reparaciones_detail.map((detalle) => (
          <li key={detalle.id}>
            {detalle.id} · {detalle.tipo_reparacion_nombre} ·{" "}
            {importe(detalle.precio)}
          </li>
        ))}
      </ul>
      <Boton disabled={deshabilitado} onClick={onConfirmar}>
        Finalizar definición
      </Boton>
    </div>
  );
}

/** PROC-REP-068 (No) -> 069: motivo obligatorio, observaciones opcionales. */
function FormularioSinReparacion({
  deshabilitado,
  onConfirmar,
}: {
  deshabilitado: boolean;
  onConfirmar: (motivo: string, observaciones: string) => void;
}) {
  const [motivo, setMotivo] = useState("");
  const [observaciones, setObservaciones] = useState("");

  return (
    <div>
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          onChange={(evento) => setMotivo(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Observaciones">
        <input
          value={observaciones}
          onChange={(evento) => setObservaciones(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || motivo.trim() === ""}
        onClick={() => onConfirmar(motivo.trim(), observaciones.trim())}
      >
        Finalizar sin reparación
      </Boton>
    </div>
  );
}

/**
 * HP-REP-003: una única garantía RMA para 1..N Detalles de la Orden
 * entregada. La revisión técnica es obligatoria: la Orden nueva nace en
 * revisión y sus Detalles se definen después.
 */
function FormularioGarantiaRma({
  orden,
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  deshabilitado: boolean;
  onConfirmar: (detalleOrigenIds: string[]) => void;
}) {
  const [elegidos, setElegidos] = useState<string[]>([]);

  const alternar = (detalleId: string, marcado: boolean) =>
    setElegidos((actuales) =>
      marcado
        ? [...actuales, detalleId]
        : actuales.filter((id) => id !== detalleId),
    );

  return (
    <div>
      <p style={{ margin: "0 0 0.3rem", fontSize: "0.85rem" }}>
        Detalles cubiertos por la garantía (al menos uno):
      </p>
      {orden.reparaciones_detail.map((detalle) => (
        <label
          key={detalle.id}
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
            fontSize: "0.85rem",
            marginBottom: "0.3rem",
          }}
        >
          <input
            type="checkbox"
            checked={elegidos.includes(detalle.id)}
            onChange={(evento) => alternar(detalle.id, evento.target.checked)}
            disabled={deshabilitado}
          />
          {detalle.id} · {detalle.tipo_reparacion_nombre}
        </label>
      ))}
      <div style={{ marginTop: "0.4rem" }}>
        <Boton
          disabled={deshabilitado || elegidos.length === 0}
          onClick={() =>
            onConfirmar(
              orden.reparaciones_detail
                .map((detalle) => detalle.id)
                .filter((id) => elegidos.includes(id)),
            )
          }
        >
          Iniciar garantía RMA
        </Boton>
      </div>
    </div>
  );
}

function SelectorSimple({
  etiqueta,
  opciones,
  deshabilitado,
  onConfirmar,
}: {
  etiqueta: string;
  opciones: { valor: string; texto: string }[];
  deshabilitado: boolean;
  onConfirmar: (valor: string) => void;
}) {
  const [valor, setValor] = useState(opciones[0]?.valor ?? "");

  return (
    <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
      <div style={{ flex: 1 }}>
        <Campo etiqueta={etiqueta}>
          <select
            value={valor}
            onChange={(evento) => setValor(evento.target.value)}
            disabled={deshabilitado}
            style={estiloInput}
          >
            {opciones.map((opcion) => (
              <option key={opcion.valor} value={opcion.valor}>
                {opcion.texto}
              </option>
            ))}
          </select>
        </Campo>
      </div>
      <div style={{ marginBottom: "0.6rem" }}>
        <Boton
          disabled={deshabilitado || !valor}
          onClick={() => onConfirmar(valor)}
        >
          Confirmar
        </Boton>
      </div>
    </div>
  );
}

/**
 * PROC-REP-150: propone la prioridad predeterminada del catálogo
 * (4 — Normal) y la registra recién al confirmar; se puede elegir 1, 2 o 3.
 */
function FormularioPrioridad({
  prioridades,
  deshabilitado,
  onConfirmar,
}: {
  prioridades: Prioridad[];
  deshabilitado: boolean;
  onConfirmar: (prioridad: number) => void;
}) {
  const [elegida, setElegida] = useState<number | null>(null);
  const prioridad = elegida ?? prioridadPropuesta(prioridades);

  return (
    <div
      style={{
        display: "flex",
        gap: "0.5rem",
        alignItems: "flex-end",
        flexWrap: "wrap",
      }}
    >
      <div style={{ width: 180, maxWidth: "100%" }}>
        <Campo etiqueta="Prioridad">
          <select
            value={prioridad ?? ""}
            onChange={(evento) => setElegida(Number(evento.target.value))}
            disabled={deshabilitado || prioridad === null}
            style={estiloInput}
          >
            {prioridades.map((opcion) => (
              <option key={opcion.valor} value={opcion.valor}>
                {opcionDePrioridad(opcion)}
              </option>
            ))}
          </select>
        </Campo>
      </div>
      <div style={{ marginBottom: "0.6rem" }}>
        <Boton
          disabled={deshabilitado || prioridad === null}
          onClick={() => prioridad !== null && onConfirmar(prioridad)}
        >
          Ingresar a la cola
        </Boton>
      </div>
    </div>
  );
}

/**
 * Cambiar la prioridad de una Orden que ya está en el taller. No es
 * ingresarla a la cola (eso ya pasó): la cola se reordena sola.
 */
function FormularioCambioPrioridad({
  actual,
  prioridades,
  deshabilitado,
  onConfirmar,
}: {
  actual: number;
  prioridades: Prioridad[];
  deshabilitado: boolean;
  onConfirmar: (prioridad: number, motivo: string | null) => void;
}) {
  const opciones = prioridades.filter((opcion) => opcion.valor !== actual);
  const [elegida, setElegida] = useState<number | null>(null);
  const [motivo, setMotivo] = useState("");
  const prioridad = elegida ?? opciones[0]?.valor ?? null;
  return (
    <div>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        Hoy: prioridad {actual}. Queda registrado quién la cambió y cuándo.
      </p>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <div style={{ width: 200, maxWidth: "100%" }}>
          <Campo etiqueta="Nueva prioridad">
            <select
              value={prioridad ?? ""}
              onChange={(evento) => setElegida(Number(evento.target.value))}
              disabled={deshabilitado || prioridad === null}
              style={estiloInput}
            >
              {opciones.map((opcion) => (
                <option key={opcion.valor} value={opcion.valor}>
                  {opcionDePrioridad(opcion)}
                </option>
              ))}
            </select>
          </Campo>
        </div>
        <div style={{ flex: "1 1 12rem" }}>
          <Campo etiqueta="Motivo (opcional)">
            <input
              value={motivo}
              onChange={(evento) => setMotivo(evento.target.value)}
              disabled={deshabilitado}
              style={estiloInput}
            />
          </Campo>
        </div>
      </div>
      <Boton
        disabled={deshabilitado || prioridad === null}
        onClick={() =>
          prioridad !== null && onConfirmar(prioridad, motivo.trim() || null)
        }
      >
        Cambiar la prioridad
      </Boton>
    </div>
  );
}

/**
 * Liberar la Orden que tiene OTRO técnico. Avisa quién la tiene, pide el
 * motivo y una confirmación explícita. Si hay una reparación en curso, se
 * interrumpe: se registra lo usado hasta ahí (se consume) y lo reservado
 * vuelve al stock. La Orden vuelve a la cola.
 */
function FormularioLiberacionAjena({
  orden,
  usuarios,
  estaciones,
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  usuarios: Usuario[];
  estaciones: Estacion[];
  deshabilitado: boolean;
  onConfirmar: (motivo: string, insumosUtilizados: InsumoUtilizado[]) => void;
}) {
  const toma = orden.toma_activa;
  const enCurso = orden.ejecuciones.find(
    (ejecucion) => ejecucion.estado === "EN_PROGRESO",
  );
  const previstos = insumosPrevistosDe(orden, enCurso?.id ?? null);
  const [motivo, setMotivo] = useState("");
  const [confirmado, setConfirmado] = useState(false);
  const [cantidades, setCantidades] = useState<Record<string, string>>({});
  if (!toma) return null;
  const titular = nombreDeUsuario(usuarios, toma.usuario_id);
  const estacion =
    estaciones.find((candidata) => candidata.id === toma.estacion_id)?.nombre ??
    toma.estacion_id;
  const utilizados = previstos
    .map((previsto) => ({
      insumo_id: previsto.insumo_id,
      cantidad: cantidades[previsto.insumo_id] ?? "0",
    }))
    .filter((insumo) => Number(insumo.cantidad) > 0);
  return (
    <div>
      <p
        role="alert"
        style={{
          margin: "0 0 0.6rem",
          padding: "0.5rem 0.7rem",
          borderRadius: 6,
          border: `1px solid ${colores.alerta}`,
          background: "#fffaf0",
          fontSize: "0.85rem",
        }}
      >
        La Orden la tiene <strong>{titular}</strong> ({estacion}).
        Liberarla la devuelve a la cola
        {enCurso ? " e interrumpe la reparación en curso" : ""}. Queda
        registrado quién la liberó y por qué.
        {enCurso && (
          <span style={{ display: "block", marginTop: "0.3rem" }}>
            Los insumos que indiques como ya usados se consumen; los
            reservados que no se usaron se liberan y vuelven al stock.
          </span>
        )}
      </p>
      {enCurso &&
        previstos.map((previsto) => (
          <Campo
            key={previsto.insumo_id}
            etiqueta={`${previsto.nombre} ya usado (previsto: ${previsto.cantidad_prevista})`}
          >
            <input
              value={cantidades[previsto.insumo_id] ?? "0"}
              onChange={(evento) =>
                setCantidades((actual) => ({
                  ...actual,
                  [previsto.insumo_id]: evento.target.value,
                }))
              }
              disabled={deshabilitado}
              inputMode="decimal"
              style={estiloInput}
            />
          </Campo>
        ))}
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          onChange={(evento) => setMotivo(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <label
        style={{
          display: "flex",
          gap: "0.4rem",
          alignItems: "flex-start",
          margin: "0 0 0.6rem",
          fontSize: "0.85rem",
        }}
      >
        <input
          type="checkbox"
          checked={confirmado}
          onChange={(evento) => setConfirmado(evento.target.checked)}
          disabled={deshabilitado}
        />
        Confirmo que libero la Orden que tiene {titular}.
      </label>
      <Boton
        disabled={deshabilitado || !confirmado || motivo.trim() === ""}
        onClick={() => onConfirmar(motivo.trim(), utilizados)}
      >
        Liberar la Orden de {titular}
      </Boton>
    </div>
  );
}

/**
 * Plazo definitivo de garantía de un trabajo (antes de la entrega). La
 * sugerida (90 días con check-in, 30 sin; el del catálogo hasta
 * registrarlo) se conserva y el check-in no pisa el ajuste; el plazo corre
 * desde la entrega.
 */
function FormularioGarantia({
  orden,
  detalleId,
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  detalleId: string | null;
  deshabilitado: boolean;
  onConfirmar: (detalleId: string, dias: number, motivo: string) => void;
}) {
  const detalle = orden.reparaciones_detail.find((d) => d.id === detalleId);
  const [dias, setDias] = useState(String(detalle?.garantia_dias ?? ""));
  const [motivo, setMotivo] = useState("");
  if (!detalle) return null;
  const valor = Number(dias);
  const valido =
    /^\d+$/.test(dias.trim()) && valor <= 730 && valor !== detalle.garantia_dias;
  return (
    <div>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        Hoy: {detalle.garantia_dias} días
        {detalle.garantia_dias_sugerida !== null &&
        detalle.garantia_dias_sugerida !== undefined &&
        detalle.garantia_dias_sugerida !== detalle.garantia_dias
          ? ` (sugerida: ${detalle.garantia_dias_sugerida})`
          : ""}
        . Corre desde la entrega del equipo.
      </p>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <div style={{ width: 140 }}>
          <Campo etiqueta="Días de garantía">
            <input
              value={dias}
              onChange={(evento) => setDias(evento.target.value)}
              disabled={deshabilitado}
              inputMode="numeric"
              style={estiloInput}
            />
          </Campo>
        </div>
        <div style={{ flex: "1 1 12rem" }}>
          <Campo etiqueta="Motivo (obligatorio)">
            <input
              value={motivo}
              onChange={(evento) => setMotivo(evento.target.value)}
              disabled={deshabilitado}
              style={estiloInput}
            />
          </Campo>
        </div>
      </div>
      <Boton
        disabled={deshabilitado || !valido || motivo.trim() === ""}
        onClick={() => onConfirmar(detalle.id, valor, motivo.trim())}
      >
        Ajustar la garantía
      </Boton>
    </div>
  );
}

/**
 * Salida de PROC-REP-200 que registra el formulario. Cada modo fija su
 * propuesta inicial de cantidades:
 *
 * - completar:   lo previsto (el caso habitual es usar todo);
 * - interrumpir: 0 (se registra solo lo realmente usado hasta ahora), y
 *                pide el motivo de la interrupción;
 * - redefinir:   lo previsto, y exige un motivo (EXC-REP-004).
 */
type ModoEjecucion = "completar" | "interrumpir" | "redefinir";

const MODOS_EJECUCION: Record<
  ModoEjecucion,
  {
    textoBoton: string;
    cantidadInicial: (previsto: InsumoPrevisto) => string;
    /** Etiqueta del motivo obligatorio, si el modo lo pide. */
    motivo: string | null;
  }
> = {
  completar: {
    textoBoton: "Registrar la reparación",
    cantidadInicial: (previsto) => previsto.cantidad_prevista,
    motivo: null,
  },
  interrumpir: {
    textoBoton: "Interrumpir la reparación",
    cantidadInicial: () => "0",
    motivo: "Motivo de la interrupción (obligatorio)",
  },
  redefinir: {
    textoBoton: "Pedir la redefinición del trabajo",
    cantidadInicial: (previsto) => previsto.cantidad_prevista,
    motivo: "Motivo de la redefinición (obligatorio)",
  },
};

/**
 * PROC-REP-200: el técnico confirma o modifica lo realmente utilizado.
 *
 * Los insumos vienen de la API (`insumos_previstos` del Detalle). La UI
 * propone una cantidad según el modo y deja corregirla; si el Detalle no
 * prevé ninguno, se envía una lista vacía. Nunca inventa un insumo ni
 * conoce ningún ID de catálogo.
 */
function FormularioEjecucion({
  modo,
  previstos,
  deshabilitado,
  onConfirmar,
}: {
  modo: ModoEjecucion;
  previstos: InsumoPrevisto[];
  deshabilitado: boolean;
  onConfirmar: (
    insumosUtilizados: InsumoUtilizado[],
    observaciones: string,
    motivo: string,
  ) => void;
}) {
  const {
    textoBoton,
    cantidadInicial,
    motivo: etiquetaMotivo,
  } = MODOS_EJECUCION[modo];
  const pideMotivo = etiquetaMotivo !== null;
  const [motivo, setMotivo] = useState("");
  const [cantidades, setCantidades] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      previstos.map((previsto) => [
        previsto.insumo_id,
        cantidadInicial(previsto),
      ]),
    ),
  );
  const [observaciones, setObservaciones] = useState("");

  const utilizados = (): InsumoUtilizado[] =>
    previstos
      .map((previsto) => ({
        insumo_id: previsto.insumo_id,
        cantidad: cantidades[previsto.insumo_id] ?? "0",
      }))
      .filter((insumo) => Number(insumo.cantidad) > 0);

  return (
    <div>
      {previstos.length === 0 ? (
        <p
          style={{
            margin: "0 0 0.6rem",
            fontSize: "0.8rem",
            color: colores.suave,
          }}
        >
          Este Detalle no prevé insumos: se registrará sin consumo.
        </p>
      ) : (
        previstos.map((previsto) => (
          <Campo
            key={previsto.insumo_id}
            etiqueta={
              previsto.nombre +
              " (" +
              previsto.codigo +
              ") — previsto: " +
              previsto.cantidad_prevista
            }
          >
            <input
              value={cantidades[previsto.insumo_id] ?? ""}
              onChange={(evento) =>
                setCantidades((actual) => ({
                  ...actual,
                  [previsto.insumo_id]: evento.target.value,
                }))
              }
              disabled={deshabilitado}
              style={estiloInput}
            />
          </Campo>
        ))
      )}
      {etiquetaMotivo && (
        <Campo etiqueta={etiquetaMotivo}>
          <input
            value={motivo}
            onChange={(evento) => setMotivo(evento.target.value)}
            disabled={deshabilitado}
            style={estiloInput}
          />
        </Campo>
      )}
      <Campo etiqueta="Observaciones">
        <input
          value={observaciones}
          onChange={(evento) => setObservaciones(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || (pideMotivo && motivo.trim() === "")}
        onClick={() => onConfirmar(utilizados(), observaciones, motivo.trim())}
      >
        {textoBoton}
      </Boton>
    </div>
  );
}

/** Insumos previstos del Detalle al que pertenece esa Ejecución. */
function insumosPrevistosDe(
  orden: Orden,
  ejecucionId: string | null,
): InsumoPrevisto[] {
  const ejecucion = orden.ejecuciones.find(
    (candidata) => candidata.id === ejecucionId,
  );
  if (!ejecucion) return [];

  const detalle = orden.reparaciones_detail.find(
    (candidato) => candidato.id === ejecucion.reparacion_detail_id,
  );
  return detalle?.insumos_previstos ?? [];
}

/**
 * E3: antes de forzar el Detalle se muestra el impacto en el stock -físico,
 * reservado, disponible, requerido y resultante- y se exige confirmarlo
 * explícitamente. El backend también exige la confirmación: esto no es la
 * única protección, y las reservas de otras Órdenes nunca se tocan.
 */
function FormularioMotivoOverride({
  deshabilitado,
  orden,
  detalleId,
  consultarImpacto,
  onConfirmar,
}: {
  deshabilitado: boolean;
  orden: Orden;
  detalleId: string | null;
  consultarImpacto: (detalleId: string) => Promise<ImpactoOverride>;
  onConfirmar: (detalleId: string, motivo: string) => void;
}) {
  const [motivo, setMotivo] = useState("");
  const [confirmado, setConfirmado] = useState(false);
  const [impacto, setImpacto] = useState<ImpactoOverride | null>(null);
  const [errorImpacto, setErrorImpacto] = useState<string | null>(null);

  // Se recalcula cada vez que la Orden cambia: el stock y las reservas
  // pudieron moverse, y una confirmación vieja ya no vale.
  useEffect(() => {
    if (detalleId === null) return;
    let vigente = true;
    setImpacto(null);
    setConfirmado(false);
    setErrorImpacto(null);
    consultarImpacto(detalleId)
      .then((resultado) => vigente && setImpacto(resultado))
      .catch(
        (fallo: unknown) =>
          vigente &&
          setErrorImpacto(
            fallo instanceof Error
              ? fallo.message
              : "No se pudo calcular el impacto en el stock.",
          ),
      );
    return () => {
      vigente = false;
    };
    // consultarImpacto se recrea en cada render del panel: lo que importa
    // es la Orden (id y version) y el Detalle.
  }, [orden.id, orden.updated_at, detalleId]);

  const listo =
    !deshabilitado &&
    detalleId !== null &&
    impacto !== null &&
    confirmado &&
    motivo.trim() !== "";

  return (
    <div>
      <ImpactoEnStock impacto={impacto} error={errorImpacto} />
      <Campo
        etiqueta="Motivo para forzar el trabajo sin stock (obligatorio)"
      >
        <input
          value={motivo}
          onChange={(evento) => setMotivo(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <label
        style={{
          display: "flex",
          gap: "0.5rem",
          alignItems: "flex-start",
          margin: "0 0 0.6rem",
          fontSize: "0.85rem",
        }}
      >
        <input
          type="checkbox"
          checked={confirmado}
          onChange={(evento) => setConfirmado(evento.target.checked)}
          disabled={deshabilitado || impacto === null}
        />
        <span>
          Confirmo el override con este impacto en el stock
          {impacto?.deja_disponible_negativo
            ? ", aunque el disponible quede en negativo."
            : "."}
        </span>
      </label>
      <Boton
        disabled={!listo}
        onClick={() =>
          detalleId !== null && listo && onConfirmar(detalleId, motivo.trim())
        }
      >
        Forzar el trabajo sin stock
      </Boton>
    </div>
  );
}

function ImpactoEnStock({
  impacto,
  error,
}: {
  impacto: ImpactoOverride | null;
  error: string | null;
}) {
  if (error) {
    return (
      <p style={{ margin: "0 0 0.6rem", color: colores.error }}>{error}</p>
    );
  }
  if (impacto === null) {
    return (
      <p style={{ margin: "0 0 0.6rem", color: colores.suave }}>
        Calculando el impacto en el stock…
      </p>
    );
  }

  const celda = { padding: "0.25rem 0.5rem", textAlign: "right" as const };
  return (
    <div style={{ margin: "0 0 0.75rem" }}>
      {impacto.insumos.length === 0 ? (
        <p style={{ margin: "0 0 0.4rem", color: colores.suave }}>
          El Detalle no prevé insumos.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              borderCollapse: "collapse",
              fontSize: "0.8rem",
              width: "100%",
            }}
          >
            <thead>
              <tr style={{ color: colores.suave }}>
                <th style={{ ...celda, textAlign: "left" }}>Insumo</th>
                <th style={celda}>Físico</th>
                <th style={celda}>Reservado otras OR</th>
                <th style={celda}>Reservado esta OR</th>
                <th style={celda}>Disponible</th>
                <th style={celda}>Requerido</th>
                <th style={celda}>Disponible resultante</th>
              </tr>
            </thead>
            <tbody>
              {impacto.insumos.map((insumo) => (
                <tr
                  key={insumo.insumo_id}
                  style={{ borderTop: `1px solid ${colores.borde}` }}
                >
                  <td style={{ ...celda, textAlign: "left" }}>
                    {insumo.nombre} ({insumo.codigo})
                  </td>
                  <td style={celda}>{insumo.stock_fisico}</td>
                  <td style={celda}>{insumo.reservado_otras_ordenes}</td>
                  <td style={celda}>{insumo.reservado_esta_orden}</td>
                  <td style={celda}>{insumo.disponible}</td>
                  <td style={celda}>{insumo.requerido}</td>
                  <td
                    style={{
                      ...celda,
                      fontWeight: 600,
                      color:
                        Number(insumo.disponible_resultante) < 0
                          ? colores.error
                          : colores.ok,
                    }}
                  >
                    {insumo.disponible_resultante}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p
        style={{
          margin: "0.4rem 0 0",
          fontSize: "0.8rem",
          color: impacto.deja_disponible_negativo
            ? colores.error
            : colores.suave,
        }}
      >
        {impacto.advertencia}
      </p>
    </div>
  );
}

function FormularioResultadoRevision({
  deshabilitado,
  textoBoton = "Registrar la revisión",
  onConfirmar,
}: {
  deshabilitado: boolean;
  textoBoton?: string;
  onConfirmar: (resultado: string) => void;
}) {
  const [resultado, setResultado] = useState("");

  return (
    <div>
      <Campo etiqueta="Resultado de la revisión (obligatorio)">
        <input
          value={resultado}
          onChange={(evento) => setResultado(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || resultado.trim() === ""}
        onClick={() => onConfirmar(resultado.trim())}
      >
        {textoBoton}
      </Boton>
    </div>
  );
}

/**
 * PROC-REP-127 (EXC-REP-004): Recepción elige la nueva definición del
 * MISMO Detalle. Muestra el Tipo vigente; confirmar el mismo Tipo también
 * es una redefinición (nuevo snapshot, override previo invalidado).
 */
function FormularioRedefinirDetalle({
  tipos,
  detalle,
  deshabilitado,
  onConfirmar,
}: {
  tipos: TipoReparacion[];
  detalle: Orden["reparaciones_detail"][number] | undefined;
  deshabilitado: boolean;
  onConfirmar: (tipoReparacionId: string) => void;
}) {
  const [tipoId, setTipoId] = useState(
    detalle?.tipo_reparacion_id ?? tipos[0]?.id ?? "",
  );
  const elegido = tipos.find((tipo) => tipo.id === tipoId);

  return (
    <div>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem" }}>
        Detalle {detalle?.id ?? "—"} · Tipo actual:{" "}
        <strong>{detalle?.tipo_reparacion_nombre ?? "—"}</strong> (
        {detalle?.precio ?? "—"})
      </p>
      <Campo etiqueta="Nuevo tipo de reparación">
        <select
          value={tipoId}
          onChange={(evento) => setTipoId(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        >
          {tipos.map((tipo) => (
            <option key={tipo.id} value={tipo.id}>
              {tipo.nombre} — {tipo.precio}
            </option>
          ))}
        </select>
      </Campo>
      {elegido && (
        <p
          style={{
            margin: "0 0 0.5rem",
            fontSize: "0.8rem",
            color: colores.suave,
          }}
        >
          Nueva definición: {elegido.nombre} ({elegido.precio})
        </p>
      )}
      <Boton
        disabled={deshabilitado || !tipoId}
        onClick={() => onConfirmar(tipoId)}
      >
        Redefinir reparación
      </Boton>
    </div>
  );
}

function FormularioObservaciones({
  deshabilitado,
  textoBoton,
  onConfirmar,
}: {
  deshabilitado: boolean;
  textoBoton: string;
  onConfirmar: (observaciones: string) => void;
}) {
  const [observaciones, setObservaciones] = useState("");

  return (
    <div>
      <Campo etiqueta="Observaciones">
        <input
          value={observaciones}
          onChange={(evento) => setObservaciones(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado}
        onClick={() => onConfirmar(observaciones)}
      >
        {textoBoton}
      </Boton>
    </div>
  );
}
