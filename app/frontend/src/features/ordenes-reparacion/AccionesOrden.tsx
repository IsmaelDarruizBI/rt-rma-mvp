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

import { useEffect, useState } from "react";

import type { DatosRetiro } from "../../api/ordenes";
import {
  Boton,
  Campo,
  Panel,
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
  TipoReparacion,
  Usuario,
} from "../../types/api";
import { PendientesDeCierre } from "./CustodiaOrden";
import { nombreDeUsuario } from "./DetalleOrden";
import { Confirmacion } from "./PagosOrden";

export interface EjecutorAcciones {
  agregarDetalle: (tipoReparacionId: string) => void;
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
}

interface Props {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  tipos: TipoReparacion[];
  estaciones: Estacion[];
  ocupado: boolean;
  ejecutar: EjecutorAcciones;
}

/**
 * E1: una Orden cerrada solo se consulta. El backend ya no ofrece
 * acciones operativas (solo iniciar una garantía RMA, que crea OTRA Orden)
 * y las rechaza igual si llegan; esto solo lo explica.
 */
function AvisoOrdenCerrada({ orden }: { orden: Orden }) {
  const situacion =
    orden.estado_workflow === "ENTREGADA"
      ? "fue entregada"
      : orden.estado_workflow === "CANCELADA"
        ? orden.devolucion
          ? `fue cancelada y el equipo se devolvió a ${orden.devolucion.recibido_por}`
          : orden.custodia.estado === "NO_RECIBIDO"
            ? "fue cancelada (se registró que el equipo nunca ingresó)"
            : "fue cancelada sin devolución física registrada"
        : "fue devuelta a Gestión RT";
  return (
    <p
      role="status"
      style={{
        margin: "0 0 0.75rem",
        padding: "0.6rem 0.8rem",
        borderRadius: 6,
        border: `1px solid ${colores.ok}`,
        background: "#f3faf4",
        color: colores.texto,
        fontSize: "0.85rem",
      }}
    >
      <strong>Orden cerrada:</strong> {situacion}. Se puede consultar, pero
      no admite acciones operativas.
    </p>
  );
}

export function AccionesOrden({
  orden,
  actor,
  usuarios,
  tipos,
  estaciones,
  ocupado,
  ejecutar,
}: Props) {
  const acciones = orden.acciones_disponibles;

  if (acciones.length === 0) {
    return (
      <Panel titulo="Acción disponible">
        {orden.cerrada ? (
          <AvisoOrdenCerrada orden={orden} />
        ) : orden.pendientes_de_cierre.length > 0 ? (
          <PendientesDeCierre orden={orden} />
        ) : (
          <p style={{ margin: 0, color: colores.suave, fontSize: "0.9rem" }}>
            No hay acciones disponibles para el estado actual.
          </p>
        )}
      </Panel>
    );
  }

  const renderizar = (accion: Accion) => (
    <AccionUnica
      key={accion.codigo + (accion.detalle_id ?? "")}
      accion={accion}
      actor={actor}
      usuarios={usuarios}
      orden={orden}
      tipos={tipos}
      estaciones={estaciones}
      ocupado={ocupado}
      ejecutar={ejecutar}
    />
  );

  return (
    <Panel titulo="Acción disponible">
      {orden.cerrada && <AvisoOrdenCerrada orden={orden} />}
      {orden.devolucion_pendiente && (
        <p
          role="status"
          style={{
            margin: "0 0 0.75rem",
            padding: "0.6rem 0.8rem",
            borderRadius: 6,
            border: `1px solid ${colores.alerta}`,
            background: "#fff8e6",
            fontSize: "0.85rem",
          }}
        >
          <strong>Orden cancelada:</strong> el equipo sigue en custodia.
          Registrá su devolución para cerrar la Orden (sin cobro).
        </p>
      )}
      {agruparEnPares(acciones).map((grupo) =>
        grupo.length === 1 ? (
          renderizar(grupo[0])
        ) : (
          <div
            key={grupo.map((accion) => accion.codigo).join("|")}
            style={{
              display: "grid",
              columnGap: "1rem",
              // Lado a lado en escritorio; apiladas en pantallas angostas.
              gridTemplateColumns:
                "repeat(auto-fit, minmax(min(100%, 260px), 1fr))",
            }}
          >
            {grupo.map(renderizar)}
          </div>
        ),
      )}
    </Panel>
  );
}

/**
 * Cancelaciones de la Orden (PROC-REP-300/305/306), aparte de la acción del
 * flujo: son capacidades excepcionales, posibles en casi cualquier etapa.
 * Las publica el backend en `acciones_cancelacion`; acá solo se muestran,
 * con las mismas reglas de rol que el resto. Cancelar la Orden completa
 * pide confirmación.
 */
export function CancelacionesOrden({
  orden,
  actor,
  usuarios,
  tipos,
  estaciones,
  ocupado,
  ejecutar,
}: Props) {
  if (orden.acciones_cancelacion.length === 0) return null;
  return (
    <Panel titulo="Cancelaciones">
      <p
        style={{
          margin: "0 0 0.75rem",
          fontSize: "0.8rem",
          color: colores.suave,
        }}
      >
        Cancelar no borra nada: el Detalle queda CANCELADO con su motivo y
        deja de cobrarse. Lo ya realizado no se cancela.
      </p>
      {orden.acciones_cancelacion.map((accion) => (
        <AccionUnica
          key={accion.codigo + (accion.detalle_id ?? "")}
          accion={accion}
          actor={actor}
          usuarios={usuarios}
          orden={orden}
          tipos={tipos}
          estaciones={estaciones}
          ocupado={ocupado}
          ejecutar={ejecutar}
        />
      ))}
    </Panel>
  );
}

/**
 * Pares que se muestran juntos porque son las dos salidas de lo MISMO:
 * Completar e Interrumpir de una Ejecución (PROC-REP-200), y Aprobar o
 * Rechazar el control de un Detalle (PROC-REP-220/230). Es solo
 * presentación: qué acciones existen lo sigue decidiendo el backend.
 */
const PARES: [Set<string>, (accion: Accion) => string | null][] = [
  [
    new Set(["COMPLETAR_EJECUCION", "INTERRUMPIR_EJECUCION"]),
    (accion) => accion.ejecucion_id,
  ],
  [
    new Set(["APROBAR_CONTROL", "RECHAZAR_CONTROL"]),
    (accion) => accion.detalle_id,
  ],
];

function emparejan(anterior: Accion, accion: Accion): boolean {
  return PARES.some(
    ([codigos, clave]) =>
      codigos.has(anterior.codigo) &&
      codigos.has(accion.codigo) &&
      anterior.codigo !== accion.codigo &&
      clave(anterior) === clave(accion),
  );
}

function agruparEnPares(acciones: Accion[]): Accion[][] {
  const grupos: Accion[][] = [];
  for (const accion of acciones) {
    const anterior = grupos[grupos.length - 1];
    const empareja =
      anterior !== undefined &&
      anterior.length === 1 &&
      emparejan(anterior[0], accion);
    if (empareja) {
      anterior.push(accion);
    } else {
      grupos.push([accion]);
    }
  }
  return grupos;
}

function AccionUnica({
  accion,
  actor,
  usuarios,
  orden,
  tipos,
  estaciones,
  ocupado,
  ejecutar,
}: Props & { accion: Accion }) {
  // El backend manda TODOS los roles autorizados: un nodo puede declarar
  // actores_alternativos. Vacio = el negocio no definio rol (Registrar
  // Pago, BR-REP-017). Ocultar el boton es UX; la autoridad es el backend.
  //
  // requiere_actor: false marca un nodo actor: ACT-SYSTEM (p. ej.
  // Informar a Gestión RT): no hay ningún actor humano que elegir, así
  // que ni la habilitación ni el mensaje de rol dependen del actor demo.
  const rolHabilitado =
    !accion.requiere_actor ||
    (actor !== null &&
      (accion.roles.length === 0 || accion.roles.includes(actor.rol)));
  // E2: las acciones técnicas sobre la toma son solo de su titular.
  const titularAjeno =
    accion.usuario_id !== null &&
    actor !== null &&
    accion.usuario_id !== actor.id;
  const habilitada = rolHabilitado && !titularAjeno;

  return (
    <div
      style={{
        marginBottom: "0.9rem",
        paddingBottom: "0.9rem",
        borderBottom: `1px solid ${colores.borde}`,
      }}
    >
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>
        {accion.etiqueta}
      </p>
      {!rolHabilitado && accion.requiere_actor && (
        <p
          style={{
            margin: "0 0 0.5rem",
            fontSize: "0.8rem",
            color: colores.alerta,
          }}
        >
          Requiere el rol {accion.roles.join(" o ") || "—"}. Cambiá el
          actor demo para ejecutarla.
        </p>
      )}
      {rolHabilitado && titularAjeno && (
        <p
          style={{
            margin: "0 0 0.5rem",
            fontSize: "0.8rem",
            color: colores.alerta,
          }}
        >
          Orden tomada por otro técnico:{" "}
          {nombreDeUsuario(usuarios, accion.usuario_id)}. Solo el titular de
          la toma puede operarla.
        </p>
      )}
      <FormularioAccion
        accion={accion}
        orden={orden}
        tipos={tipos}
        estaciones={estaciones}
        deshabilitado={!habilitada || ocupado}
        ejecutar={ejecutar}
      />
    </div>
  );
}

function FormularioAccion({
  accion,
  orden,
  tipos,
  estaciones,
  deshabilitado,
  ejecutar,
}: {
  accion: Accion;
  orden: Orden;
  tipos: TipoReparacion[];
  estaciones: Estacion[];
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
          onConfirmar={(tipoId) => ejecutar.agregarDetalle(tipoId)}
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
          Esperar recursos (no forzar el Detalle)
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
          Revalidar disponibilidad de recursos
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
        <Boton
          disabled={deshabilitado || !accion.detalle_id}
          onClick={() =>
            accion.detalle_id && ejecutar.iniciarDetalle(accion.detalle_id)
          }
        >
          Iniciar y reservar insumos
        </Boton>
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
          onConfirmar={(insumosUtilizados, observaciones) =>
            accion.ejecucion_id &&
            ejecutar.interrumpirEjecucion(
              accion.ejecucion_id,
              insumosUtilizados,
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
          textoBoton={`Realizar revisión técnica del Detalle ${
            accion.detalle_id ?? ""
          }`}
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
              ? `Aprobar control del Detalle ${accion.detalle_id}`
              : "Aprobar control"
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
          Notificar al cliente
        </Boton>
      );

    case "REGISTRAR_PAGO":
      // Los cobros, anulaciones y devoluciones viven en "Pagos y
      // movimientos", con el catálogo de medios y el saldo a la vista.
      return (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          Registrá el pago en <strong>Pagos y movimientos</strong>.
        </p>
      );

    case "ENTREGAR":
      return (
        <FormularioEntrega
          orden={orden}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.entregar}
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
          textoBoton={`Rechazar control del Detalle ${accion.detalle_id ?? ""}`}
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
          etiqueta={`Motivo de la cancelación de ${accion.detalle_id ?? ""} (obligatorio)`}
          textoBoton={`Cancelar el Detalle ${accion.detalle_id ?? ""}`}
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
    return `¿Cancelar la Orden ${orden.id}? No tiene Detalles: queda CANCELADA.`;
  }
  return (
    `¿Cancelar la Orden ${orden.id}? Se cancelan ${pendientes} trabajo(s) ` +
    "pendiente(s). " +
    (completos > 0
      ? `Los ${completos} Detalle(s) ya realizados no se cancelan y siguen ` +
        "al control y la entrega."
      : "Sin trabajo realizado, la Orden queda CANCELADA.")
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
    orden.cliente?.nombre ?? "Gestión RT",
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
  deshabilitado,
  onConfirmar,
}: {
  orden: Orden;
  deshabilitado: boolean;
  onConfirmar: (retiro: DatosRetiro) => void;
}) {
  const [recibidoPor, setRecibidoPor] = useState("");
  const [identificacion, setIdentificacion] = useState("");
  const [observaciones, setObservaciones] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const enCustodia = orden.custodia.estado === "EN_CUSTODIA";
  const bloqueado = deshabilitado || !enCustodia;
  const titular = orden.cliente?.nombre ?? null;
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
  onConfirmar: (tipoReparacionId: string, detalleOrigenId: string | null) => void;
}) {
  const [tipoId, setTipoId] = useState(tipos[0]?.id ?? "");
  const [origenId, setOrigenId] = useState(detallesOrigen[0]?.id ?? "");
  const pideOrigen = detallesOrigen.length > 0;

  return (
    <div>
      {pideOrigen && (
        <Campo etiqueta="Detalle origen de la garantía">
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
                ? `Tipo de reparación (Detalle ${cantidadDetallesActual + 1})`
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
            </select>
          </Campo>
        </div>
        <div style={{ marginBottom: "0.6rem" }}>
          <Boton
            disabled={deshabilitado || !tipoId || (pideOrigen && !origenId)}
            onClick={() => onConfirmar(tipoId, pideOrigen ? origenId : null)}
          >
            Agregar Detalle
          </Boton>
        </div>
      </div>
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

function FormularioPrioridad({
  deshabilitado,
  onConfirmar,
}: {
  deshabilitado: boolean;
  onConfirmar: (prioridad: number) => void;
}) {
  const [prioridad, setPrioridad] = useState("1");

  return (
    <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end" }}>
      <div style={{ width: 120 }}>
        <Campo etiqueta="Prioridad">
          <input
            type="number"
            min={0}
            value={prioridad}
            onChange={(evento) => setPrioridad(evento.target.value)}
            disabled={deshabilitado}
            style={estiloInput}
          />
        </Campo>
      </div>
      <div style={{ marginBottom: "0.6rem" }}>
        <Boton
          disabled={deshabilitado}
          onClick={() => onConfirmar(Number(prioridad) || 0)}
        >
          Ingresar a la cola
        </Boton>
      </div>
    </div>
  );
}

/**
 * Salida de PROC-REP-200 que registra el formulario. Cada modo fija su
 * propuesta inicial de cantidades:
 *
 * - completar:   lo previsto (el caso habitual es usar todo);
 * - interrumpir: 0 (se registra solo lo realmente usado hasta ahora);
 * - redefinir:   lo previsto, y exige un motivo (EXC-REP-004).
 */
type ModoEjecucion = "completar" | "interrumpir" | "redefinir";

const MODOS_EJECUCION: Record<
  ModoEjecucion,
  {
    textoBoton: string;
    cantidadInicial: (previsto: InsumoPrevisto) => string;
    pideMotivo: boolean;
  }
> = {
  completar: {
    textoBoton: "Completar ejecución",
    cantidadInicial: (previsto) => previsto.cantidad_prevista,
    pideMotivo: false,
  },
  interrumpir: {
    textoBoton: "Interrumpir ejecución",
    cantidadInicial: () => "0",
    pideMotivo: false,
  },
  redefinir: {
    textoBoton: "Requiere redefinición",
    cantidadInicial: (previsto) => previsto.cantidad_prevista,
    pideMotivo: true,
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
  const { textoBoton, cantidadInicial, pideMotivo } = MODOS_EJECUCION[modo];
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
      {pideMotivo && (
        <Campo etiqueta="Motivo de la redefinición (obligatorio)">
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
        etiqueta={`Motivo del override del Detalle ${detalleId ?? ""} (obligatorio)`}
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
        Forzar el Detalle (override)
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
