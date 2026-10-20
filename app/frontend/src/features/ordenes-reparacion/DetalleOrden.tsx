/**
 * Pantalla de una Orden: cabecera compacta, trabajos y datos técnicos.
 *
 * La cabecera y los trabajos hablan en términos del negocio; los códigos
 * (nodos, enums, IDs) quedan en «Historial y datos técnicos».
 */

import type { ReactNode } from "react";

import {
  Etiqueta,
  Panel,
  colores,
  fechaCorta,
  importe,
} from "../../components/ui";
import type { Detalle, Estacion, Orden, Usuario } from "../../types/api";
import { EtapasNegocio } from "./ProximoPaso";
import {
  CANAL,
  CONDICION_TRABAJO,
  CONTROL,
  EJECUCION,
  ESTADO_TRABAJO,
  ESTADO_WORKFLOW,
  etiqueta,
  etiquetaAutorizacion,
  hace,
} from "./etiquetas";

/** "Nombre" si el usuario está en el catálogo; si no, su ID. */
export function nombreDeUsuario(
  usuarios: Usuario[],
  usuarioId: string | null,
): string {
  if (usuarioId === null) return "—";
  const usuario = usuarios.find((candidato) => candidato.id === usuarioId);
  return usuario ? usuario.nombre : usuarioId;
}

function nombreDeEstacion(estaciones: Estacion[], estacionId: string): string {
  return (
    estaciones.find((candidata) => candidata.id === estacionId)?.nombre ??
    estacionId
  );
}

/** Color del chip de situación: alerta si espera algo, error si cancelada. */
function colorDeSituacion(codigo: string | undefined): string {
  if (!codigo) return colores.suave;
  if (codigo === "CERRADA") return colores.texto;
  if (codigo.startsWith("CANCELADA")) return colores.error;
  if (codigo === "LISTA_PARA_ENTREGAR") return colores.ok;
  if (
    codigo.startsWith("ESPERANDO") ||
    codigo.startsWith("PENDIENTE") ||
    codigo === "REQUIERE_REVISION_TECNICA"
  ) {
    return colores.alerta;
  }
  return colores.acento;
}

/**
 * Qué pasa, a quién le toca, quién la tiene y desde cuándo. Sin nodos,
 * enums ni IDs internos.
 */
export function CabeceraOrden({
  orden,
  usuarios = [],
  estaciones = [],
}: {
  orden: Orden;
  usuarios?: Usuario[];
  estaciones?: Estacion[];
}) {
  const situacion = orden.situacion;
  const toma = orden.toma_activa;
  const titular = situacion?.tareas[0]?.acciones.find(
    (accion) => accion.usuario_id,
  )?.usuario_id;
  const responsable = titular
    ? `${nombreDeUsuario(usuarios, titular)} (técnico titular)`
    : situacion?.responsable;
  const desde = situacion?.desde ?? null;
  const datos: ReactNode[] = [];
  if (responsable && !orden.cerrada) {
    datos.push(
      <>
        Le toca: <strong>{responsable}</strong>
        {toma && toma.usuario_id === titular
          ? ` · ${nombreDeEstacion(estaciones, toma.estacion_id)}`
          : ""}
      </>,
    );
  }
  if (toma && toma.usuario_id !== titular) {
    datos.push(
      <>
        Técnico: {nombreDeUsuario(usuarios, toma.usuario_id)} ·{" "}
        {nombreDeEstacion(estaciones, toma.estacion_id)}
      </>,
    );
  }
  if (orden.prioridad_texto) {
    datos.push(<>{orden.prioridad_texto}</>);
  }
  // En el celular solo el tiempo relativo; la fecha queda en el tooltip.
  if (desde) {
    datos.push(
      <span title={fechaCorta(desde)}>
        En esta situación{" "}
        <span className="rt-solo-escritorio">desde {fechaCorta(desde)} </span>
        ({hace(desde)})
      </span>,
    );
  }
  datos.push(
    <span title={fechaCorta(orden.created_at)}>
      Ingresó{" "}
      <span className="rt-solo-escritorio">
        el {fechaCorta(orden.created_at)}{" "}
      </span>
      ({hace(orden.created_at)})
    </span>,
  );

  return (
    <Panel>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.5rem",
          flexWrap: "wrap",
        }}
      >
        <h2 style={{ margin: 0, fontSize: "1.3rem" }}>{orden.id}</h2>
        <Etiqueta color={colorDeSituacion(situacion?.codigo)}>
          {situacion?.titulo ?? etiqueta(ESTADO_WORKFLOW, orden.estado_workflow)}
        </Etiqueta>
      </div>
      <p style={{ margin: "0.35rem 0 0", fontSize: "0.95rem" }}>
        {orden.cliente
          ? `${orden.cliente.nombre} · ${orden.cliente.telefono}`
          : `Equipo interno RT · ${orden.referencia_rt ?? "sin referencia"}`}
      </p>
      <p style={{ margin: "0.15rem 0 0", color: colores.suave }}>
        {orden.equipo.marca} {orden.equipo.modelo} —{" "}
        {orden.equipo.falla_reportada}
      </p>
      {orden.orden_origen_id && (
        <p style={{ margin: "0.15rem 0 0", color: colores.suave }}>
          Garantía de la Orden {orden.orden_origen_id}
          {orden.detalles_origen.length > 0 &&
            ` (${orden.detalles_origen
              .map((origen) => origen.tipo_reparacion_nombre)
              .join(", ")})`}
        </p>
      )}
      <p
        style={{
          margin: "0.5rem 0 0",
          fontSize: "0.82rem",
          color: colores.suave,
          display: "flex",
          flexWrap: "wrap",
          columnGap: "0.9rem",
          rowGap: "0.15rem",
        }}
      >
        {datos.map((dato, indice) => (
          <span key={indice}>{dato}</span>
        ))}
      </p>
      {situacion && <EtapasNegocio etapas={situacion.etapas} />}
    </Panel>
  );
}

/** Un título chico dentro de una sección. */
export function Bloque({
  titulo,
  children,
}: {
  titulo: string;
  children: ReactNode;
}) {
  return (
    <div style={{ marginTop: "0.9rem" }}>
      <p style={{ margin: "0 0 0.4rem", fontWeight: 600, fontSize: "0.9rem" }}>
        {titulo}
      </p>
      {children}
    </div>
  );
}

function Linea({ children }: { children: ReactNode }) {
  return (
    <div
      style={{
        fontSize: "0.8rem",
        color: colores.suave,
        marginTop: "0.15rem",
        overflowWrap: "anywhere",
      }}
    >
      {children}
    </div>
  );
}

/**
 * Los trabajos de la Orden: definición, autorización, ejecución y control
 * de cada uno, en un solo lugar.
 */
export function TrabajosOrden({
  orden,
  usuarios,
}: {
  orden: Orden;
  usuarios: Usuario[];
}) {
  if (orden.reparaciones_detail.length === 0) {
    // PROC-REP-069: la conclusión y su motivo quedan en el historial.
    const conclusion = orden.finalizada_sin_reparacion
      ? orden.historial.find((paso) => paso.referencia_id === "PROC-REP-069")
      : undefined;
    return (
      <div style={{ fontSize: "0.9rem", color: colores.suave }}>
        {orden.finalizada_sin_reparacion
          ? "La revisión concluyó sin reparación."
          : "Todavía no se definió ningún trabajo."}
        {conclusion?.observacion && (
          <p style={{ margin: "0.3rem 0 0", color: colores.texto }}>
            {conclusion.observacion}
          </p>
        )}
      </div>
    );
  }
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {orden.reparaciones_detail.map((detalle) => (
        <Trabajo
          key={detalle.id}
          orden={orden}
          detalle={detalle}
          usuarios={usuarios}
        />
      ))}
    </ul>
  );
}

function Trabajo({
  orden,
  detalle,
  usuarios,
}: {
  orden: Orden;
  detalle: Detalle;
  usuarios: Usuario[];
}) {
  const cancelado = detalle.estado === "CANCELADO";
  const ejecuciones = orden.ejecuciones.filter(
    (ejecucion) => ejecucion.reparacion_detail_id === detalle.id,
  );
  const decision = [...detalle.autorizaciones]
    .reverse()
    .find((registro) => registro.version_definicion === detalle.version_definicion);
  const cobrable = orden.resumen.condicion_comercial === "COBRABLE";
  const condicion = CONDICION_TRABAJO[detalle.condicion];

  return (
    <li
      style={{
        padding: "0.6rem 0",
        borderBottom: `1px solid ${colores.borde}`,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "0.5rem",
          flexWrap: "wrap",
        }}
      >
        <strong style={{ fontSize: "1rem" }}>
          {detalle.tipo_reparacion_nombre}
        </strong>
        <span
          style={{
            ...(cancelado
              ? { textDecoration: "line-through", color: colores.suave }
              : {}),
          }}
        >
          {cobrable ? importe(detalle.precio) : "Sin cargo"}
        </span>
      </div>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.3rem",
          marginTop: "0.3rem",
        }}
      >
        <Etiqueta
          color={
            cancelado
              ? colores.error
              : detalle.estado === "COMPLETO"
                ? colores.ok
                : detalle.estado === "EN_PROGRESO"
                  ? colores.acento
                  : colores.suave
          }
        >
          {etiqueta(ESTADO_TRABAJO, detalle.estado)}
        </Etiqueta>
        {condicion && !cancelado && (
          <Etiqueta color={colores.alerta}>{condicion}</Etiqueta>
        )}
        {orden.autorizacion_requerida &&
          !cancelado &&
          detalle.estado_autorizacion !== "NO_REQUERIDA" && (
            <Etiqueta
              color={
                detalle.estado_autorizacion === "PENDIENTE"
                  ? colores.alerta
                  : colores.suave
              }
            >
              {etiquetaAutorizacion(detalle)}
            </Etiqueta>
          )}
        {detalle.estado === "COMPLETO" && (
          <Etiqueta
            color={
              detalle.control_estado === "APROBADO" ? colores.ok : colores.suave
            }
          >
            {etiqueta(CONTROL, detalle.control_estado)}
          </Etiqueta>
        )}
        {detalle.pendiente_de_retrabajo && (
          <Etiqueta color={colores.alerta}>Retrabajo pendiente</Etiqueta>
        )}
      </div>
      {decision && (
        <Linea>
          {detalle.autorizado_en_ingreso
            ? `Autorizado con el comprobante de ingreso (${etiqueta(CANAL, decision.canal)})`
            : `${decision.resultado === "AUTORIZADO" ? "Autorizado" : "Rechazado"} por el cliente ${etiqueta(CANAL, decision.canal)}`}{" "}
          · lo registró {nombreDeUsuario(usuarios, decision.usuario_id)} el{" "}
          {fechaCorta(decision.fecha)}
        </Linea>
      )}
      {detalle.insumos_previstos.length > 0 && !cancelado && (
        <Linea>
          Insumos previstos:{" "}
          {detalle.insumos_previstos
            .map((previsto) => `${previsto.nombre} × ${previsto.cantidad_prevista}`)
            .join(", ")}
        </Linea>
      )}
      {ejecuciones.map((ejecucion) => (
        <Linea key={ejecucion.id}>
          Reparación {etiqueta(EJECUCION, ejecucion.estado)} ·{" "}
          {nombreDeUsuario(usuarios, ejecucion.usuario_id)} ·{" "}
          {fechaCorta(ejecucion.inicio)}
          {ejecucion.fin ? ` a ${fechaCorta(ejecucion.fin)}` : ""}
          {ejecucion.motivo_interrupcion
            ? ` · Interrumpida: ${ejecucion.motivo_interrupcion}`
            : ""}
          {ejecucion.observaciones ? ` · ${ejecucion.observaciones}` : ""}
          {ejecucion.motivo_redefinicion
            ? ` · Requiere redefinición: ${ejecucion.motivo_redefinicion}`
            : ""}
        </Linea>
      ))}
      {detalle.controles.map((control, indice) => (
        <Linea key={`${control.fecha}-${indice}`}>
          Control{" "}
          <span
            style={{
              fontWeight: 600,
              color:
                control.resultado === "APROBADO" ? colores.ok : colores.error,
            }}
          >
            {control.resultado === "APROBADO" ? "aprobado" : "rechazado"}
          </span>{" "}
          por {nombreDeUsuario(usuarios, control.usuario_id)} ·{" "}
          {fechaCorta(control.fecha)}
          {control.observaciones && ` · ${control.observaciones}`}
        </Linea>
      ))}
      {detalle.cancelacion && (
        <Linea>
          <span style={{ color: colores.error }}>
            {detalle.cancelacion.origen === "RECHAZO_CLIENTE"
              ? "El cliente lo rechazó"
              : detalle.cancelacion.origen === "DESISTIMIENTO_CLIENTE"
                ? "El cliente desistió después de autorizarlo"
                : "Cancelado"}{" "}
            · registró {nombreDeUsuario(usuarios, detalle.cancelacion.usuario_id)}{" "}
            · {fechaCorta(detalle.cancelacion.fecha)} ·{" "}
            {detalle.cancelacion.motivo} (no se cobra)
          </span>
        </Linea>
      )}
      {detalle.definiciones_anteriores.length > 0 && (
        <Linea>
          Redefinido {detalle.definiciones_anteriores.length} vez
          {detalle.definiciones_anteriores.length > 1 ? "es" : ""} (el detalle
          está en los datos técnicos)
        </Linea>
      )}
      {!cancelado && (
        <Linea>
          Garantía: {detalle.garantia_dias} días desde la entrega
          {detalle.garantia_dias_sugerida !== null &&
          detalle.garantia_dias_sugerida !== undefined &&
          detalle.garantia_dias_sugerida !== detalle.garantia_dias
            ? ` (sugerida: ${detalle.garantia_dias_sugerida})`
            : ""}
          {(detalle.ajustes_garantia ?? []).map((ajuste) => (
            <span key={ajuste.fecha} style={{ display: "block" }}>
              Ajustada de {ajuste.dias_anteriores} a {ajuste.dias_nuevos} días
              por {nombreDeUsuario(usuarios, ajuste.usuario_id)} el{" "}
              {fechaCorta(ajuste.fecha)} · {ajuste.motivo}
            </span>
          ))}
        </Linea>
      )}
    </li>
  );
}

/**
 * Los identificadores y estados internos, para soporte: no se muestran en
 * la vista principal, pero nada se pierde.
 */
export function DatosTecnicos({ orden }: { orden: Orden }) {
  const filas: [string, string][] = [
    ["Origen", orden.origen],
    ["Estado de workflow", orden.estado_workflow],
    ["Paso actual", orden.current_process],
    ["Situación", orden.situacion?.codigo ?? "—"],
    ["Prioridad", String(orden.prioridad)],
    ["Toma activa", orden.toma_activa?.id ?? "—"],
    ["Puntaje total", String(orden.resumen.puntaje_total)],
  ];
  return (
    <div style={{ fontSize: "0.8rem" }}>
      <dl
        style={{
          margin: 0,
          display: "grid",
          gridTemplateColumns: "minmax(7rem, max-content) minmax(0, 1fr)",
          gap: "0.2rem 0.8rem",
        }}
      >
        {filas.map(([nombre, valor]) => (
          <div key={nombre} style={{ display: "contents" }}>
            <dt style={{ color: colores.suave }}>{nombre}</dt>
            <dd
              style={{
                margin: 0,
                fontFamily: "ui-monospace, monospace",
                overflowWrap: "anywhere",
              }}
            >
              {valor}
            </dd>
          </div>
        ))}
      </dl>
      {orden.reparaciones_detail.length > 0 && (
        <ul
          style={{
            margin: "0.5rem 0 0",
            paddingLeft: "1.1rem",
            fontFamily: "ui-monospace, monospace",
          }}
        >
          {orden.reparaciones_detail.map((detalle) => (
            <li key={detalle.id}>
              {detalle.id} · {detalle.tipo_reparacion_id} · v
              {detalle.version_definicion} · {detalle.estado} ·{" "}
              {detalle.condicion} · control {detalle.control_estado} · puntaje{" "}
              {detalle.puntaje}
              {detalle.definiciones_anteriores.map((anterior) => (
                <div key={anterior.reemplazada_en}>
                  antes: {anterior.tipo_reparacion_id} ({anterior.precio}) ·
                  reemplazada {fechaCorta(anterior.reemplazada_en)} por{" "}
                  {anterior.usuario_id}
                </div>
              ))}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function ProgresoHappyPath({ orden }: { orden: Orden }) {
  return (
    <ol
      style={{
        margin: 0,
        padding: 0,
        listStyle: "none",
        display: "flex",
        flexWrap: "wrap",
        gap: "0.3rem",
      }}
    >
      {orden.progreso.map((paso) => (
        <li
          key={paso.process_id}
          title={`${paso.process_id} — ${paso.etiqueta}`}
          style={{
            padding: "0.2rem 0.45rem",
            borderRadius: 4,
            fontSize: "0.7rem",
            fontFamily: "ui-monospace, monospace",
            background: paso.alcanzado ? colores.ok : colores.fondo,
            color: paso.alcanzado ? "#fff" : colores.suave,
            border: `1px solid ${paso.alcanzado ? colores.ok : colores.borde}`,
          }}
        >
          {paso.process_id.replace("PROC-REP-", "")}
        </li>
      ))}
    </ol>
  );
}

/**
 * Ejecuciones de la Orden con su estado real. Una Ejecución INTERRUMPIDA
 * nunca se reabre: continuar el Detalle crea una Ejecución nueva, y todas
 * quedan listadas.
 */
/**
 * Ejecuciones e insumos en términos del negocio: qué trabajo, quién, cuándo,
 * cómo terminó, qué insumos usó y por qué se interrumpió. Los IDs quedan en
 * «Historial y datos técnicos».
 */
export function EjecucionesEInsumos({
  orden,
  usuarios,
}: {
  orden: Orden;
  usuarios: Usuario[];
}) {
  if (orden.ejecuciones.length === 0) {
    return (
      <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
        Todavía no se empezó ningún trabajo.
      </p>
    );
  }
  return (
    <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
      {orden.ejecuciones.map((ejecucion) => {
        const detalle = orden.reparaciones_detail.find(
          (candidato) => candidato.id === ejecucion.reparacion_detail_id,
        );
        const nombreInsumo = (insumoId: string) =>
          detalle?.insumos_previstos.find(
            (previsto) => previsto.insumo_id === insumoId,
          )?.nombre ?? insumoId;
        const usados = ejecucion.insumos_utilizados.filter(
          (insumo) => Number(insumo.cantidad) > 0,
        );
        return (
          <li
            key={ejecucion.id}
            style={{
              padding: "0.5rem 0",
              borderBottom: `1px solid ${colores.borde}`,
              fontSize: "0.85rem",
            }}
          >
            <strong>
              {detalle?.tipo_reparacion_nombre ?? ejecucion.reparacion_detail_id}
            </strong>{" "}
            <Etiqueta
              color={
                ejecucion.estado === "EN_PROGRESO"
                  ? colores.acento
                  : ejecucion.estado === "COMPLETADO"
                    ? colores.ok
                    : colores.alerta
              }
            >
              {etiqueta(EJECUCION, ejecucion.estado)}
            </Etiqueta>
            <Linea>
              {nombreDeUsuario(usuarios, ejecucion.usuario_id)} · desde{" "}
              {fechaCorta(ejecucion.inicio)}
              {ejecucion.fin ? ` hasta ${fechaCorta(ejecucion.fin)}` : ""}
            </Linea>
            {ejecucion.estado === "EN_PROGRESO" ? (
              detalle && detalle.insumos_previstos.length > 0 && (
                <Linea>
                  Insumos reservados:{" "}
                  {detalle.insumos_previstos
                    .map(
                      (previsto) =>
                        `${previsto.nombre} × ${Number(previsto.cantidad_prevista)}`,
                    )
                    .join(", ")}
                </Linea>
              )
            ) : (
              <Linea>
                Insumos utilizados:{" "}
                {usados.length
                  ? usados
                      .map(
                        (insumo) =>
                          `${nombreInsumo(insumo.insumo_id)} × ${Number(insumo.cantidad)}`,
                      )
                      .join(", ")
                  : "ninguno"}
              </Linea>
            )}
            {ejecucion.motivo_interrupcion && (
              <Linea>Motivo de la interrupción: {ejecucion.motivo_interrupcion}</Linea>
            )}
            {ejecucion.observaciones && (
              <Linea>Observaciones: {ejecucion.observaciones}</Linea>
            )}
            {ejecucion.motivo_redefinicion && (
              <Linea>Pidió redefinición: {ejecucion.motivo_redefinicion}</Linea>
            )}
          </li>
        );
      })}
    </ul>
  );
}

export function EjecucionesOrden({ orden }: { orden: Orden }) {
  if (orden.ejecuciones.length === 0) {
    return (
      <p style={{ margin: 0, fontSize: "0.8rem", color: colores.suave }}>
        Sin ejecuciones.
      </p>
    );
  }
  return (
    <ul
      style={{
        margin: 0,
        padding: 0,
        listStyle: "none",
        fontSize: "0.8rem",
        fontFamily: "ui-monospace, monospace",
      }}
    >
      {orden.ejecuciones.map((ejecucion) => (
        <li key={ejecucion.id} style={{ padding: "0.15rem 0" }}>
          {ejecucion.id} · {ejecucion.reparacion_detail_id} ·{" "}
          {ejecucion.usuario_id} · {ejecucion.estado}
        </li>
      ))}
    </ul>
  );
}

/**
 * Secuencia de eventos de la Orden.
 *
 * Conviven dos clases: los nodos del Business Process, que avanzan el
 * recorrido, y las capacidades transversales (ACC-REP-*), que dejan
 * traza sin moverlo. El badge PROC / ACC las distingue.
 */
export function HistorialOrden({ orden }: { orden: Orden }) {
  return (
    // En pantallas angostas la tabla se desplaza dentro de su contenedor.
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          minWidth: 560,
          borderCollapse: "collapse",
          fontSize: "0.8rem",
        }}
      >
        <thead>
          <tr style={{ textAlign: "left", color: colores.suave }}>
            <th style={{ padding: "0.2rem 0" }}>Fecha</th>
            <th>Referencia</th>
            <th>Acción</th>
            <th>Usuario</th>
            <th>Detalle</th>
          </tr>
        </thead>
        <tbody>
          {orden.historial.map((paso, indice) => {
            const transversal = paso.tipo_referencia === "FUNCTIONAL_ACTION";
            return (
              <tr
                key={`${paso.referencia_id}-${indice}`}
                style={{ borderTop: `1px solid ${colores.borde}` }}
              >
                <td style={{ padding: "0.3rem 0", whiteSpace: "nowrap" }}>
                  {fechaCorta(paso.fecha)}
                </td>
                <td style={{ whiteSpace: "nowrap" }}>
                  <span
                    title={
                      transversal
                        ? "Capacidad transversal: no avanza el proceso"
                        : "Nodo del Business Process"
                    }
                    style={{
                      display: "inline-block",
                      marginRight: "0.4rem",
                      padding: "0.05rem 0.3rem",
                      borderRadius: 3,
                      fontSize: "0.65rem",
                      fontWeight: 700,
                      color: "#fff",
                      background: transversal ? colores.alerta : colores.acento,
                    }}
                  >
                    {transversal ? "ACC" : "PROC"}
                  </span>
                  <span style={{ fontFamily: "ui-monospace, monospace" }}>
                    {paso.referencia_id}
                  </span>
                </td>
                <td>{paso.accion}</td>
                <td style={{ color: colores.suave }}>
                  {paso.usuario_id ?? "sistema"}
                </td>
                <td style={{ color: colores.suave }}>{paso.observacion ?? ""}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
