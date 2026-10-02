/**
 * Pantalla de una Orden: cabecera, resumen comercial, Detalles,
 * progreso del Happy Path, acción disponible e historial.
 */

import {
  Etiqueta,
  Panel,
  colores,
  fechaCorta,
  importe,
} from "../../components/ui";
import type { Orden } from "../../types/api";

const COLOR_ESTADO: Record<string, string> = {
  REQUERIMIENTO: colores.suave,
  EN_REVISION: colores.alerta,
  HABILITADA: colores.acento,
  EN_COLA: colores.acento,
  EN_REPARACION: colores.alerta,
  REPARACION_LISTA: colores.ok,
  ENTREGADA: colores.ok,
};

export function CabeceraOrden({ orden }: { orden: Orden }) {
  return (
    <Panel>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "flex-start",
          gap: "1rem",
          flexWrap: "wrap",
        }}
      >
        <div>
          <h2 style={{ margin: "0 0 0.3rem", fontSize: "1.3rem" }}>
            {orden.id}
          </h2>
          <p style={{ margin: 0, color: colores.suave }}>
            {orden.cliente
              ? `${orden.cliente.nombre} · ${orden.cliente.telefono}`
              : `Equipo interno RT · referencia ${orden.referencia_rt ?? "—"}`}
          </p>
          <p style={{ margin: "0.2rem 0 0", color: colores.suave }}>
            {orden.equipo.marca} {orden.equipo.modelo} —{" "}
            {orden.equipo.falla_reportada}
          </p>
          {orden.orden_origen_id && (
            <p style={{ margin: "0.2rem 0 0", color: colores.suave }}>
              Origen garantía: {orden.orden_origen_id}
              {orden.detalles_origen_ids.length > 0 &&
                ` / ${orden.detalles_origen_ids.join(", ")}`}
            </p>
          )}
        </div>
        <div style={{ textAlign: "right" }}>
          <p
            style={{
              margin: "0 0 0.3rem",
              fontSize: "0.75rem",
              color: colores.suave,
            }}
          >
            {orden.origen}
          </p>
          <Etiqueta
            color={COLOR_ESTADO[orden.estado_workflow] ?? colores.suave}
          >
            {orden.estado_workflow}
          </Etiqueta>
          <p
            style={{
              margin: "0.4rem 0 0",
              fontSize: "0.8rem",
              color: colores.suave,
              fontFamily: "ui-monospace, monospace",
            }}
          >
            {orden.current_process}
          </p>
        </div>
      </div>
    </Panel>
  );
}

const ETIQUETA_CONDICION_COMERCIAL: Record<string, string> = {
  COBRABLE: "Cobrable al cliente",
  NO_COBRABLE_AL_CLIENTE: "No cobrable (equipo RT interno)",
  NO_COBRABLE: "No cobrable (garantía)",
};

export function ResumenComercialOrden({ orden }: { orden: Orden }) {
  const { resumen } = orden;
  const esCobrable = resumen.condicion_comercial === "COBRABLE";
  const filas: [string, string][] = [
    [esCobrable ? "Total" : "Total (nominal)", importe(resumen.total)],
    ["Pagado", importe(resumen.pagado)],
    [esCobrable ? "Saldo" : "Saldo (nominal)", importe(resumen.saldo)],
    ["Estado de pago", resumen.estado_pago],
    ["Puntaje", String(resumen.puntaje_total)],
  ];

  return (
    <Panel titulo="Resumen comercial">
      <p
        style={{
          margin: "0 0 0.6rem",
          fontSize: "0.8rem",
          color: colores.suave,
        }}
      >
        {ETIQUETA_CONDICION_COMERCIAL[resumen.condicion_comercial] ??
          resumen.condicion_comercial}
        {!esCobrable &&
          ": el total/saldo son nominales, no una deuda a cobrar."}
      </p>
      <dl style={{ margin: 0, display: "grid", gap: "0.35rem" }}>
        {filas.map(([etiqueta, valor]) => (
          <div
            key={etiqueta}
            style={{ display: "flex", justifyContent: "space-between" }}
          >
            <dt style={{ color: colores.suave }}>{etiqueta}</dt>
            <dd style={{ margin: 0, fontWeight: 600 }}>{valor}</dd>
          </div>
        ))}
      </dl>
      <PagosOrden orden={orden} />
    </Panel>
  );
}

/** Historial de pagos: fecha, tipo, medio, monto y quién lo registró. */
function PagosOrden({ orden }: { orden: Orden }) {
  return (
    <div style={{ marginTop: "1rem" }}>
      <h4
        style={{
          margin: "0 0 0.5rem",
          fontSize: "0.8rem",
          textTransform: "uppercase",
          letterSpacing: "0.05em",
          color: colores.suave,
        }}
      >
        Pagos
      </h4>
      {orden.pagos.length === 0 ? (
        <p style={{ margin: 0, color: colores.suave, fontSize: "0.85rem" }}>
          Todavía no se registró ningún pago.
        </p>
      ) : (
        <table
          style={{
            width: "100%",
            borderCollapse: "collapse",
            fontSize: "0.82rem",
          }}
        >
          <thead>
            <tr style={{ textAlign: "left", color: colores.suave }}>
              <th style={{ padding: "0.2rem 0" }}>Fecha</th>
              <th>Tipo</th>
              <th>Medio</th>
              <th style={{ textAlign: "right" }}>Monto</th>
              <th>Usuario</th>
            </tr>
          </thead>
          <tbody>
            {orden.pagos.map((pago) => (
              <tr
                key={pago.id}
                style={{ borderTop: `1px solid ${colores.borde}` }}
              >
                <td style={{ padding: "0.3rem 0", whiteSpace: "nowrap" }}>
                  {fechaCorta(pago.fecha)}
                </td>
                <td>
                  <Etiqueta
                    color={
                      pago.tipo_pago === "ANTICIPO"
                        ? colores.alerta
                        : colores.ok
                    }
                  >
                    {pago.tipo_pago}
                  </Etiqueta>
                </td>
                <td>{pago.metodo}</td>
                <td style={{ textAlign: "right", fontWeight: 600 }}>
                  {importe(pago.monto)}
                </td>
                <td style={{ color: colores.suave }}>{pago.usuario_id}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

export function DetallesOrden({ orden }: { orden: Orden }) {
  if (orden.reparaciones_detail.length === 0) {
    return (
      <Panel titulo="Detalles de reparación">
        <p style={{ margin: 0, color: colores.suave, fontSize: "0.9rem" }}>
          Todavía no se definió ninguna reparación.
        </p>
      </Panel>
    );
  }

  return (
    <Panel titulo="Detalles de reparación">
      <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {orden.reparaciones_detail.map((detalle) => (
          <li
            key={detalle.id}
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: "0.5rem",
              padding: "0.4rem 0",
              borderBottom: `1px solid ${colores.borde}`,
            }}
          >
            <div>
              <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                {detalle.id}
              </div>
              <strong style={{ fontSize: "1rem" }}>
                {detalle.tipo_reparacion_nombre}
              </strong>
              {detalle.condicion !== "SIN_BLOQUEO" && (
                <div style={{ marginTop: "0.15rem" }}>
                  <Etiqueta color={colores.alerta}>
                    {detalle.condicion === "BLOQUEADO_POR_RECURSOS"
                      ? "Bloqueado por recursos"
                      : "Requiere definición"}
                  </Etiqueta>
                </div>
              )}
              {detalle.definiciones_anteriores.length > 0 && (
                <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                  Redefinido · anteriores:{" "}
                  {detalle.definiciones_anteriores
                    .map(
                      (anterior) =>
                        `${anterior.tipo_reparacion_id} (${anterior.precio})`,
                    )
                    .join(" → ")}
                </div>
              )}
              {detalle.detalle_origen_id && (
                <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                  Origen garantía: {orden.orden_origen_id} /{" "}
                  {detalle.detalle_origen_id}
                </div>
              )}
              <div
                style={{
                  fontSize: "0.7rem",
                  color: colores.suave,
                  fontFamily: "ui-monospace, monospace",
                }}
              >
                {detalle.tipo_reparacion_id}
              </div>
              <div
                style={{
                  fontSize: "0.8rem",
                  color: colores.suave,
                  marginTop: "0.35rem",
                }}
              >
                Garantía: {detalle.garantia_dias} días
              </div>
              <div style={{ fontSize: "0.8rem", color: colores.suave }}>
                Puntaje: {detalle.puntaje}
              </div>
              {detalle.insumos_previstos.length > 0 && (
                <div style={{ fontSize: "0.8rem", color: colores.suave }}>
                  Insumos previstos:{" "}
                  {detalle.insumos_previstos
                    .map(
                      (previsto) =>
                        `${previsto.nombre} × ${previsto.cantidad_prevista}`,
                    )
                    .join(", ")}
                </div>
              )}
            </div>
            <div style={{ textAlign: "right" }}>
              <div>{importe(detalle.precio)}</div>
              <div style={{ fontSize: "0.8rem" }}>
                <Etiqueta>{detalle.estado}</Etiqueta>{" "}
                <Etiqueta
                  color={
                    detalle.control_estado === "APROBADO"
                      ? colores.ok
                      : colores.suave
                  }
                >
                  control {detalle.control_estado}
                </Etiqueta>
              </div>
            </div>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function ProgresoHappyPath({ orden }: { orden: Orden }) {
  return (
    <Panel titulo="Progreso de la orden">
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
              border: `1px solid ${
                paso.alcanzado ? colores.ok : colores.borde
              }`,
            }}
          >
            {paso.process_id.replace("PROC-REP-", "")}
          </li>
        ))}
      </ol>
    </Panel>
  );
}

/**
 * Secuencia de eventos de la Orden.
 *
 * Conviven dos clases: los nodos del Business Process, que avanzan el
 * recorrido, y las capacidades transversales (ACC-REP-*), que dejan
 * traza sin moverlo. El badge PROC / ACC las distingue.
 *
 * Es una vista distinta de la tabla de Pagos del Resumen Comercial: ahí
 * está el estado económico, acá la secuencia de lo que fue pasando.
 */
/**
 * Ejecuciones de la Orden con su estado real. Una Ejecución INTERRUMPIDA
 * nunca se reabre: continuar el Detalle crea una Ejecución nueva, y todas
 * quedan listadas.
 */
export function EjecucionesOrden({ orden }: { orden: Orden }) {
  if (orden.ejecuciones.length === 0) return null;
  const COLOR: Record<string, string> = {
    EN_PROGRESO: colores.acento,
    COMPLETADO: colores.ok,
    INTERRUMPIDO: colores.alerta,
  };
  return (
    <Panel titulo={`Ejecuciones (${orden.ejecuciones.length})`}>
      <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {orden.ejecuciones.map((ejecucion) => (
          <li
            key={ejecucion.id}
            style={{
              display: "flex",
              justifyContent: "space-between",
              gap: "0.5rem",
              padding: "0.3rem 0",
              borderTop: `1px solid ${colores.borde}`,
              fontSize: "0.85rem",
            }}
          >
            <span>
              <strong>{ejecucion.id}</strong> · Detalle{" "}
              {ejecucion.reparacion_detail_id} · {ejecucion.usuario_id}
              {ejecucion.observaciones ? ` · ${ejecucion.observaciones}` : ""}
            </span>
            <Etiqueta color={COLOR[ejecucion.estado] ?? colores.suave}>
              {ejecucion.estado}
            </Etiqueta>
          </li>
        ))}
      </ul>
    </Panel>
  );
}

export function HistorialOrden({ orden }: { orden: Orden }) {
  return (
    <Panel titulo="Historial">
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.82rem",
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
            const transversal =
              paso.tipo_referencia === "FUNCTIONAL_ACTION";
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
                      background: transversal
                        ? colores.alerta
                        : colores.acento,
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
                <td style={{ color: colores.suave }}>
                  {paso.observacion ?? ""}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </Panel>
  );
}
