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
  importe,
} from "../../components/ui";
import type {
  Accion,
  DetalleOrigen,
  Estacion,
  InsumoPrevisto,
  InsumoUtilizado,
  Orden,
  TipoReparacion,
  Usuario,
} from "../../types/api";

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
  registrarPago: (monto: string, metodo: string) => void;
  entregar: () => void;
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
    const terminada =
      orden.estado_workflow === "ENTREGADA" ||
      orden.current_process === "EVT-REP-999";
    return (
      <Panel titulo="Acción disponible">
        <p style={{ margin: 0, color: colores.suave, fontSize: "0.9rem" }}>
          {terminada
            ? "La Orden llegó al fin del proceso. El Happy Path terminó."
            : "No hay acciones disponibles para el estado actual."}
        </p>
      </Panel>
    );
  }

  const renderizar = (accion: Accion) => (
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
  );

  return (
    <Panel titulo="Acción disponible">
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
 * Completar e Interrumpir son las dos salidas habituales de la MISMA
 * Ejecución (PROC-REP-200): se muestran juntas. Es solo presentación: qué
 * acciones existen lo sigue decidiendo el backend.
 */
const CODIGOS_EN_PAR = new Set(["COMPLETAR_EJECUCION", "INTERRUMPIR_EJECUCION"]);

function agruparEnPares(acciones: Accion[]): Accion[][] {
  const grupos: Accion[][] = [];
  for (const accion of acciones) {
    const anterior = grupos[grupos.length - 1];
    const empareja =
      anterior !== undefined &&
      anterior.length === 1 &&
      CODIGOS_EN_PAR.has(anterior[0].codigo) &&
      CODIGOS_EN_PAR.has(accion.codigo) &&
      anterior[0].codigo !== accion.codigo &&
      anterior[0].ejecucion_id === accion.ejecucion_id;
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
  const habilitada =
    !accion.requiere_actor ||
    (actor !== null &&
      (accion.roles.length === 0 || accion.roles.includes(actor.rol)));

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
      {!habilitada && accion.requiere_actor && (
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
          detalleId={accion.detalle_id}
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

function FormularioMotivoOverride({
  deshabilitado,
  detalleId,
  onConfirmar,
}: {
  deshabilitado: boolean;
  detalleId: string | null;
  onConfirmar: (detalleId: string, motivo: string) => void;
}) {
  const [motivo, setMotivo] = useState("");

  return (
    <div>
      <Campo etiqueta={`Motivo del override del Detalle ${detalleId ?? ""} (obligatorio)`}>
        <input
          value={motivo}
          onChange={(evento) => setMotivo(evento.target.value)}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || motivo.trim() === "" || detalleId === null}
        onClick={() => detalleId !== null && onConfirmar(detalleId, motivo.trim())}
      >
        Forzar el Detalle (override)
      </Boton>
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
