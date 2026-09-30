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

import { useState } from "react";

import {
  Boton,
  Campo,
  Panel,
  colores,
  estiloInput,
} from "../../components/ui";
import type {
  Accion,
  Estacion,
  InsumoPrevisto,
  InsumoUtilizado,
  Orden,
  TipoReparacion,
  Usuario,
} from "../../types/api";

export interface EjecutorAcciones {
  definirReparacion: (
    tipoReparacionId: string,
    finalizarDefinicion: boolean,
  ) => void;
  encolar: (prioridad: number) => void;
  tomar: (estacionId: string) => void;
  iniciarDetalle: (detalleId: string) => void;
  completarEjecucion: (
    ejecucionId: string,
    insumosUtilizados: InsumoUtilizado[],
    observaciones: string,
  ) => void;
  aprobarControl: (detalleId: string | null, observaciones: string) => void;
  liberarOrden: () => void;
  notificar: () => void;
  registrarPago: (monto: string, metodo: string) => void;
  entregar: () => void;
}

interface Props {
  orden: Orden;
  actor: Usuario | null;
  tipos: TipoReparacion[];
  estaciones: Estacion[];
  ocupado: boolean;
  ejecutar: EjecutorAcciones;
}

export function AccionesOrden({
  orden,
  actor,
  tipos,
  estaciones,
  ocupado,
  ejecutar,
}: Props) {
  const acciones = orden.acciones_disponibles;

  if (acciones.length === 0) {
    return (
      <Panel titulo="Acción disponible">
        <p style={{ margin: 0, color: colores.suave, fontSize: "0.9rem" }}>
          {orden.estado_workflow === "ENTREGADA"
            ? "La Orden fue entregada. El Happy Path terminó."
            : "No hay acciones disponibles para el estado actual."}
        </p>
      </Panel>
    );
  }

  return (
    <Panel titulo="Acción disponible">
      {acciones.map((accion) => (
        <AccionUnica
          key={accion.codigo + (accion.detalle_id ?? "")}
          accion={accion}
          actor={actor}
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

function AccionUnica({
  accion,
  actor,
  orden,
  tipos,
  estaciones,
  ocupado,
  ejecutar,
}: Props & { accion: Accion }) {
  // El backend manda TODOS los roles autorizados: un nodo puede declarar
  // actores_alternativos. Vacio = el negocio no definio rol (Registrar
  // Pago, BR-REP-017). Ocultar el boton es UX; la autoridad es el backend.
  const habilitada =
    actor !== null &&
    (accion.roles.length === 0 || accion.roles.includes(actor.rol));

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
      {!habilitada && (
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
    case "DEFINIR_REPARACION":
      return (
        <FormularioDefinirReparacion
          tipos={tipos}
          cantidadDetallesActual={orden.reparaciones_detail.length}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.definirReparacion}
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
      return (
        <FormularioPago
          saldo={orden.resumen.saldo}
          deshabilitado={deshabilitado}
          onConfirmar={ejecutar.registrarPago}
        />
      );

    case "ENTREGAR":
      return (
        <Boton disabled={deshabilitado} onClick={ejecutar.entregar}>
          Entregar equipo
        </Boton>
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

/**
 * Definir Detalles de la reparación (Multi-Detalle).
 *
 * "Finalizar la definición" viene tildado por defecto: con un solo
 * Detalle, confirmar se comporta exactamente como antes (agrega el
 * Detalle Y habilita la Orden en el mismo paso). Para cargar más de
 * uno, Recepción destilda la casilla en los Detalles que no son el
 * último — la Orden sigue en REQUERIMIENTO y el formulario se vuelve a
 * mostrar para el siguiente.
 */
function FormularioDefinirReparacion({
  tipos,
  cantidadDetallesActual,
  deshabilitado,
  onConfirmar,
}: {
  tipos: TipoReparacion[];
  cantidadDetallesActual: number;
  deshabilitado: boolean;
  onConfirmar: (tipoReparacionId: string, finalizarDefinicion: boolean) => void;
}) {
  const [tipoId, setTipoId] = useState(tipos[0]?.id ?? "");
  const [finalizar, setFinalizar] = useState(true);

  return (
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
        <label
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
            fontSize: "0.85rem",
            marginTop: "0.3rem",
          }}
        >
          <input
            type="checkbox"
            checked={finalizar}
            onChange={(evento) => setFinalizar(evento.target.checked)}
            disabled={deshabilitado}
          />
          Finalizar la definición (habilita la Orden)
        </label>
      </div>
      <div style={{ marginBottom: "0.6rem" }}>
        <Boton
          disabled={deshabilitado || !tipoId}
          onClick={() => onConfirmar(tipoId, finalizar)}
        >
          Confirmar
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
 * PROC-REP-200: el técnico confirma o modifica lo realmente utilizado.
 *
 * Los insumos y sus cantidades vienen de la API (`insumos_previstos` del
 * Detalle). La UI propone la cantidad prevista y deja corregirla; si el
 * Detalle no prevé ninguno, se envía una lista vacía. Nunca inventa un
 * insumo ni conoce ningún ID de catálogo.
 */
function FormularioEjecucion({
  previstos,
  deshabilitado,
  onConfirmar,
}: {
  previstos: InsumoPrevisto[];
  deshabilitado: boolean;
  onConfirmar: (
    insumosUtilizados: InsumoUtilizado[],
    observaciones: string,
  ) => void;
}) {
  const [cantidades, setCantidades] = useState<Record<string, string>>(() =>
    Object.fromEntries(
      previstos.map((previsto) => [
        previsto.insumo_id,
        previsto.cantidad_prevista,
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
          Este Detalle no prevé insumos: se completará sin consumo.
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
        onClick={() => onConfirmar(utilizados(), observaciones)}
      >
        Completar ejecución
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

function FormularioPago({
  saldo,
  deshabilitado,
  onConfirmar,
}: {
  saldo: string;
  deshabilitado: boolean;
  onConfirmar: (monto: string, metodo: string) => void;
}) {
  const [monto, setMonto] = useState(saldo);
  const [metodo, setMetodo] = useState("EFECTIVO");

  return (
    <div>
      <Campo etiqueta="Monto">
        <input
          value={monto}
          onChange={(evento) => setMonto(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Medio de pago">
        <input
          value={metodo}
          onChange={(evento) => setMetodo(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado}
        onClick={() => onConfirmar(monto, metodo)}
      >
        Registrar pago
      </Boton>
    </div>
  );
}
