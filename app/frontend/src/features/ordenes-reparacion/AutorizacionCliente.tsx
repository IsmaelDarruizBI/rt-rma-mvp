/**
 * Autorización del cliente por Detalle (BR-REP-028, PROC-REP-046/047).
 *
 * Recepción registra lo que el cliente respondió sobre cada Detalle de su
 * definición vigente: Autorizar, Rechazar o Dejar pendiente. "Dejar
 * pendiente" no es una decisión: ese Detalle no se envía y sigue esperando,
 * sin bloquear a los demás.
 *
 * El estado y la situación de cada Detalle los calcula el backend
 * (`estado_autorizacion`, `situacion_autorizacion`); acá solo se muestran.
 * Que la decisión pueda registrarse lo publica `acciones_autorizacion`, y
 * el backend vuelve a validar todo (rol, versión, duplicados) igual.
 */

import { useEffect, useState } from "react";

import {
  Boton,
  Campo,
  Etiqueta,
  Panel,
  colores,
  estiloInput,
  fechaCorta,
  importe,
} from "../../components/ui";
import type {
  Accion,
  AutorizacionCliente,
  CanalComunicacion,
  DecisionDetalle,
  Detalle,
  EstadoAutorizacion,
  Orden,
  ResultadoAutorizacion,
  SituacionAutorizacion,
  Usuario,
} from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";

type Eleccion = ResultadoAutorizacion | "PENDIENTE";

const CANALES: { valor: CanalComunicacion; etiqueta: string }[] = [
  { valor: "PRESENCIAL", etiqueta: "Presencial" },
  { valor: "TELEFONO", etiqueta: "Teléfono" },
  { valor: "WHATSAPP", etiqueta: "WhatsApp" },
  { valor: "EMAIL", etiqueta: "Email" },
  { valor: "OTRO", etiqueta: "Otro" },
];

const ESTADO: Record<EstadoAutorizacion, { texto: string; color: string }> = {
  NO_REQUERIDA: { texto: "No requerida", color: colores.suave },
  PENDIENTE: { texto: "Pendiente", color: colores.alerta },
  AUTORIZADO: { texto: "Autorizado", color: colores.ok },
  RECHAZADO: { texto: "Rechazado", color: colores.error },
  SIN_DECISION: { texto: "Sin decisión registrada", color: colores.suave },
};

const SITUACION: Record<SituacionAutorizacion, string> = {
  NO_REQUERIDA: "—",
  PENDIENTE_AUTORIZACION: "Espera al cliente: no se ejecuta",
  AUTORIZADO_FACTIBLE: "Puede continuar",
  AUTORIZADO_SIN_STOCK: "Autorizado, sin stock: espera recursos",
  REQUIERE_REDEFINICION: "Requiere redefinición",
  EN_EJECUCION: "En ejecución",
  COMPLETO: "Completo",
  CANCELADO_POR_RECHAZO: "Cancelado por rechazo del cliente",
  CANCELADO_POR_DESISTIMIENTO:
    "Cancelado: el cliente desistió después de autorizar",
  CANCELADO: "Cancelado (interno)",
};

const ELECCIONES: { valor: Eleccion; etiqueta: string }[] = [
  { valor: "AUTORIZADO", etiqueta: "Autorizar" },
  { valor: "RECHAZADO", etiqueta: "Rechazar" },
  { valor: "PENDIENTE", etiqueta: "Dejar pendiente" },
];

interface Props {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  ocupado: boolean;
  onRegistrar: (
    canal: CanalComunicacion,
    observaciones: string,
    decisiones: DecisionDetalle[],
  ) => void;
  /** `detalleId` en `null`: desiste de todos los trabajos cancelables. */
  onDesistir: (
    detalleId: string | null,
    canal: CanalComunicacion,
    motivo: string,
  ) => void;
}

export function AutorizacionClienteOrden({
  orden,
  actor,
  usuarios,
  ocupado,
  onRegistrar,
  onDesistir,
}: Props) {
  if (!orden.autorizacion_requerida || orden.reparaciones_detail.length === 0)
    return null;

  const accion = orden.acciones_autorizacion.find(
    (candidata) => candidata.codigo === "REGISTRAR_DECISION_CLIENTE",
  );
  const desistimientos = orden.acciones_autorizacion.filter((candidata) =>
    candidata.codigo.startsWith("DESISTIR_"),
  );
  return (
    <Panel titulo="Autorización del cliente">
      <TablaAutorizaciones orden={orden} usuarios={usuarios} />
      {accion ? (
        <FormularioDecision
          key={orden.updated_at}
          orden={orden}
          actor={actor}
          rolesPermitidos={accion.roles}
          ocupado={ocupado}
          onRegistrar={onRegistrar}
        />
      ) : (
        <p style={{ margin: "0.6rem 0 0", fontSize: "0.85rem", color: colores.suave }}>
          {hayPendientes(orden)
            ? "La decisión se registra una vez finalizada la definición de los Detalles."
            : "No hay Detalles esperando la decisión del cliente."}
        </p>
      )}
      {desistimientos.length > 0 && (
        <FormularioDesistimiento
          key={`desistir-${orden.updated_at}`}
          orden={orden}
          actor={actor}
          acciones={desistimientos}
          ocupado={ocupado}
          onDesistir={onDesistir}
        />
      )}
    </Panel>
  );
}

const TODOS = "__TODOS__";

/**
 * Desistimiento posterior a la autorización: el cliente ya no quiere un
 * trabajo que había autorizado (o ninguno de los que quedan). Qué se
 * cancelaría y qué lo impide lo calcula el backend (`orden.desistimiento`);
 * acá solo se muestra y se confirma.
 */
function FormularioDesistimiento({
  orden,
  actor,
  acciones,
  ocupado,
  onDesistir,
}: {
  orden: Orden;
  actor: Usuario | null;
  acciones: Accion[];
  ocupado: boolean;
  onDesistir: Props["onDesistir"];
}) {
  const [alcance, setAlcance] = useState("");
  const [canal, setCanal] = useState<CanalComunicacion>("PRESENCIAL");
  const [motivo, setMotivo] = useState("");
  const [confirmando, setConfirmando] = useState(false);

  useEffect(() => setConfirmando(false), [alcance, canal, motivo]);

  const roles = acciones[0]?.roles ?? [];
  const rolHabilitado =
    actor !== null && (roles.length === 0 || roles.includes(actor.rol));
  const total = acciones.some((accion) => accion.codigo === "DESISTIR_TODO");
  const porDetalle = acciones.filter(
    (accion) => accion.codigo === "DESISTIR_DETALLE" && accion.detalle_id,
  );
  const nombre = (detalleId: string) => {
    const detalle = orden.reparaciones_detail.find((d) => d.id === detalleId);
    return detalle
      ? `${detalle.id} · ${detalle.tipo_reparacion_nombre}`
      : detalleId;
  };
  const vista = orden.desistimiento;
  const bloqueantes = alcance === TODOS ? (vista?.bloqueantes ?? []) : [];
  const deshabilitado = !rolHabilitado || ocupado;
  const listo =
    alcance !== "" && motivo.trim() !== "" && bloqueantes.length === 0;

  return (
    <div
      style={{
        marginTop: "1rem",
        paddingTop: "0.9rem",
        borderTop: `1px solid ${colores.borde}`,
      }}
    >
      <p style={{ margin: "0 0 0.3rem", fontWeight: 600 }}>
        El cliente desiste de trabajos ya autorizados
      </p>
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
        La autorización anterior queda en el historial; el trabajo se cancela
        (no se cobra). Lo COMPLETO no se toca y una ejecución en curso no se
        interrumpe.
      </p>
      {!rolHabilitado && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.alerta }}>
          Requiere el rol {roles.join(" o ")}. Cambiá el actor demo para
          registrarlo.
        </p>
      )}
      <Campo etiqueta="¿De qué desiste?">
        <select
          value={alcance}
          disabled={deshabilitado}
          onChange={(evento) => setAlcance(evento.target.value)}
          style={estiloInput}
        >
          <option value="">Elegí…</option>
          {porDetalle.map((accion) => (
            <option key={accion.detalle_id} value={accion.detalle_id ?? ""}>
              Solo {nombre(accion.detalle_id ?? "")}
            </option>
          ))}
          {total && (
            <option value={TODOS}>
              De todos los trabajos cancelables
            </option>
          )}
        </select>
      </Campo>
      {alcance === TODOS && vista && (
        <ul style={{ margin: "0 0 0.6rem", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {vista.desistibles.length > 0 && (
            <li>
              Se cancelan por desistimiento:{" "}
              {vista.desistibles.map(nombre).join(", ")}
            </li>
          )}
          {vista.rechazables.length > 0 && (
            <li>
              Se rechazan (estaban pendientes):{" "}
              {vista.rechazables.map(nombre).join(", ")}
            </li>
          )}
          {vista.conservados.length > 0 && (
            <li>
              Se conservan (completos, siguen al cierre):{" "}
              {vista.conservados.map(nombre).join(", ")}
            </li>
          )}
        </ul>
      )}
      {bloqueantes.length > 0 && (
        <div
          role="alert"
          style={{
            margin: "0 0 0.6rem",
            padding: "0.5rem 0.7rem",
            borderRadius: 6,
            border: `1px solid ${colores.error}`,
            background: "#fff5f5",
            color: colores.error,
            fontSize: "0.85rem",
          }}
        >
          <strong>No se puede registrar ahora.</strong> Primero hay que
          resolver:
          <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.1rem" }}>
            {bloqueantes.map((bloqueo) => (
              <li key={bloqueo.detalle_id}>
                {nombre(bloqueo.detalle_id)}: {bloqueo.motivo}
              </li>
            ))}
          </ul>
        </div>
      )}
      <Campo etiqueta="Canal de comunicación">
        <select
          value={canal}
          disabled={deshabilitado}
          onChange={(evento) =>
            setCanal(evento.target.value as CanalComunicacion)
          }
          style={estiloInput}
        >
          {CANALES.map((opcion) => (
            <option key={opcion.valor} value={opcion.valor}>
              {opcion.etiqueta}
            </option>
          ))}
        </select>
      </Campo>
      <Campo etiqueta="Motivo (obligatorio)">
        <textarea
          value={motivo}
          disabled={deshabilitado}
          onChange={(evento) => setMotivo(evento.target.value)}
          rows={2}
          style={estiloInput}
        />
      </Campo>
      {!confirmando ? (
        <Boton
          disabled={deshabilitado || !listo}
          onClick={() => setConfirmando(true)}
        >
          Registrar desistimiento
        </Boton>
      ) : (
        <div
          role="alertdialog"
          aria-label="Confirmar el desistimiento del cliente"
          style={{
            padding: "0.6rem 0.8rem",
            borderRadius: 6,
            border: `1px solid ${colores.error}`,
            background: "#fff5f5",
            fontSize: "0.85rem",
          }}
        >
          <p style={{ margin: "0 0 0.4rem" }}>
            <strong>
              {alcance === TODOS
                ? "¿Confirmás que el cliente desiste de todos los trabajos cancelables?"
                : `¿Confirmás que el cliente desiste de ${nombre(alcance)}?`}
            </strong>{" "}
            Se cancela y no se puede deshacer.
          </p>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Boton
              disabled={ocupado}
              onClick={() =>
                onDesistir(
                  alcance === TODOS ? null : alcance,
                  canal,
                  motivo.trim(),
                )
              }
            >
              Confirmar
            </Boton>
            <Boton variante="secundario" onClick={() => setConfirmando(false)}>
              Volver
            </Boton>
          </div>
        </div>
      )}
    </div>
  );
}

function hayPendientes(orden: Orden): boolean {
  return orden.reparaciones_detail.some(
    (detalle) => detalle.estado_autorizacion === "PENDIENTE",
  );
}

function decisionVigente(detalle: Detalle): AutorizacionCliente | undefined {
  return [...detalle.autorizaciones]
    .reverse()
    .find((registro) => registro.version_definicion === detalle.version_definicion);
}

function TablaAutorizaciones({
  orden,
  usuarios,
}: {
  orden: Orden;
  usuarios: Usuario[];
}) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{
          width: "100%",
          borderCollapse: "collapse",
          fontSize: "0.85rem",
        }}
      >
        <thead>
          <tr style={{ textAlign: "left", color: colores.suave }}>
            <th style={celdaTitulo}>Detalle</th>
            <th style={celdaTitulo}>Precio</th>
            <th style={celdaTitulo}>Definición</th>
            <th style={celdaTitulo}>Autorización</th>
            <th style={celdaTitulo}>Situación</th>
          </tr>
        </thead>
        <tbody>
          {orden.reparaciones_detail.map((detalle) => {
            const vigente = decisionVigente(detalle);
            const anteriores = detalle.autorizaciones.filter(
              (registro) => registro !== vigente,
            );
            const estado = ESTADO[detalle.estado_autorizacion];
            return (
              <tr key={detalle.id} style={{ verticalAlign: "top" }}>
                <td style={celda}>
                  <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                    {detalle.id}
                  </div>
                  {detalle.tipo_reparacion_nombre}
                </td>
                <td style={celda}>{importe(detalle.precio)}</td>
                <td style={celda}>
                  v{detalle.version_definicion}
                  {detalle.version_definicion > 1 && (
                    <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                      redefinido
                    </div>
                  )}
                </td>
                <td style={celda}>
                  <Etiqueta color={estado.color}>{estado.texto}</Etiqueta>
                  {vigente && (
                    <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                      {nombreDeUsuario(usuarios, vigente.usuario_id)} ·{" "}
                      {fechaCorta(vigente.fecha)} · {vigente.canal}
                      {vigente.observaciones && ` · ${vigente.observaciones}`}
                    </div>
                  )}
                  {anteriores.length > 0 && (
                    <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                      Anteriores (no vigentes):{" "}
                      {anteriores
                        .map(
                          (registro) =>
                            `v${registro.version_definicion} ${registro.resultado}`,
                        )
                        .join(", ")}
                    </div>
                  )}
                </td>
                <td style={celda}>
                  <span
                    style={{
                      color:
                        detalle.situacion_autorizacion === "AUTORIZADO_FACTIBLE"
                          ? colores.ok
                          : detalle.situacion_autorizacion ===
                              "PENDIENTE_AUTORIZACION"
                            ? colores.alerta
                            : colores.texto,
                      fontWeight:
                        detalle.situacion_autorizacion === "AUTORIZADO_FACTIBLE"
                          ? 600
                          : 400,
                    }}
                  >
                    {SITUACION[detalle.situacion_autorizacion]}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

const celdaTitulo = {
  padding: "0.3rem 0.4rem",
  borderBottom: `1px solid ${colores.borde}`,
  fontWeight: 600,
  fontSize: "0.75rem",
} as const;

const celda = {
  padding: "0.4rem",
  borderBottom: `1px solid ${colores.borde}`,
} as const;

function FormularioDecision({
  orden,
  actor,
  rolesPermitidos,
  ocupado,
  onRegistrar,
}: {
  orden: Orden;
  actor: Usuario | null;
  rolesPermitidos: string[];
  ocupado: boolean;
  onRegistrar: Props["onRegistrar"];
}) {
  const pendientes = orden.reparaciones_detail.filter(
    (detalle) => detalle.estado_autorizacion === "PENDIENTE",
  );
  const [elecciones, setElecciones] = useState<Record<string, Eleccion>>(
    () => Object.fromEntries(pendientes.map((d) => [d.id, "PENDIENTE"])),
  );
  const [canal, setCanal] = useState<CanalComunicacion>("PRESENCIAL");
  const [observaciones, setObservaciones] = useState("");
  const [confirmando, setConfirmando] = useState(false);

  // Si cambia lo que se elige, hay que volver a confirmar.
  useEffect(() => setConfirmando(false), [elecciones, canal, observaciones]);

  const rolHabilitado =
    actor !== null &&
    (rolesPermitidos.length === 0 || rolesPermitidos.includes(actor.rol));
  const con = (resultado: Eleccion) =>
    pendientes.filter((detalle) => elecciones[detalle.id] === resultado);
  const autorizar = con("AUTORIZADO");
  const rechazar = con("RECHAZADO");
  const sinRespuesta = con("PENDIENTE");
  const hayDecision = autorizar.length + rechazar.length > 0;

  const elegirTodos = (eleccion: Eleccion) =>
    setElecciones(Object.fromEntries(pendientes.map((d) => [d.id, eleccion])));

  const registrar = () =>
    onRegistrar(
      canal,
      observaciones.trim(),
      [...autorizar, ...rechazar].map((detalle) => ({
        detalle_id: detalle.id,
        version_definicion: detalle.version_definicion,
        resultado: elecciones[detalle.id] as ResultadoAutorizacion,
      })),
    );

  return (
    <div style={{ marginTop: "0.9rem" }}>
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>
        Registrar la decisión del cliente
      </p>
      {!rolHabilitado && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.alerta }}>
          Requiere el rol {rolesPermitidos.join(" o ")}. Cambiá el actor demo
          para registrarla.
        </p>
      )}
      {pendientes.map((detalle) => (
        <fieldset
          key={detalle.id}
          disabled={!rolHabilitado || ocupado}
          style={{
            border: `1px solid ${colores.borde}`,
            borderRadius: 6,
            margin: "0 0 0.5rem",
            padding: "0.4rem 0.6rem",
          }}
        >
          <legend style={{ fontSize: "0.8rem", padding: "0 0.25rem" }}>
            {detalle.id} · {detalle.tipo_reparacion_nombre} ·{" "}
            {importe(detalle.precio)} · v{detalle.version_definicion}
          </legend>
          <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap" }}>
            {ELECCIONES.map((opcion) => (
              <label key={opcion.valor} style={{ fontSize: "0.85rem" }}>
                <input
                  type="radio"
                  name={`decision-${detalle.id}`}
                  checked={elecciones[detalle.id] === opcion.valor}
                  onChange={() =>
                    setElecciones((actuales) => ({
                      ...actuales,
                      [detalle.id]: opcion.valor,
                    }))
                  }
                />{" "}
                {opcion.etiqueta}
              </label>
            ))}
          </div>
        </fieldset>
      ))}
      {pendientes.length > 1 && (
        <div
          style={{
            display: "flex",
            gap: "0.5rem",
            flexWrap: "wrap",
            marginBottom: "0.6rem",
          }}
        >
          <Boton
            variante="secundario"
            disabled={!rolHabilitado || ocupado}
            onClick={() => elegirTodos("AUTORIZADO")}
          >
            Autorizar todos los pendientes
          </Boton>
          <Boton
            variante="secundario"
            disabled={!rolHabilitado || ocupado}
            onClick={() => elegirTodos("RECHAZADO")}
          >
            Rechazar todos los pendientes
          </Boton>
        </div>
      )}
      <Campo etiqueta="Canal de comunicación">
        <select
          value={canal}
          disabled={!rolHabilitado || ocupado}
          onChange={(evento) =>
            setCanal(evento.target.value as CanalComunicacion)
          }
          style={estiloInput}
        >
          {CANALES.map((opcion) => (
            <option key={opcion.valor} value={opcion.valor}>
              {opcion.etiqueta}
            </option>
          ))}
        </select>
      </Campo>
      <Campo etiqueta="Referencia / observaciones (opcional)">
        <textarea
          value={observaciones}
          disabled={!rolHabilitado || ocupado}
          onChange={(evento) => setObservaciones(evento.target.value)}
          rows={2}
          style={estiloInput}
        />
      </Campo>
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
        Se registra con {actor ? `${actor.nombre} (${actor.id})` : "el actor demo"}{" "}
        y la fecha y hora actuales. Un Detalle rechazado se cancela (no se
        cobra); los que quedan pendientes no se ejecutan, pero no frenan a
        los autorizados.
      </p>
      {!confirmando ? (
        <Boton
          disabled={!rolHabilitado || ocupado || !hayDecision}
          onClick={() => setConfirmando(true)}
        >
          Registrar decisión
        </Boton>
      ) : (
        <div
          role="alertdialog"
          aria-label="Confirmar la decisión del cliente"
          style={{
            padding: "0.6rem 0.8rem",
            borderRadius: 6,
            border: `1px solid ${colores.alerta}`,
            background: "#fff8e6",
            fontSize: "0.85rem",
          }}
        >
          <p style={{ margin: "0 0 0.4rem" }}>
            <strong>¿Confirmás la decisión del cliente?</strong>
          </p>
          <ul style={{ margin: "0 0 0.6rem", paddingLeft: "1.1rem" }}>
            {autorizar.length > 0 && (
              <li>Se autorizan: {autorizar.map((d) => d.id).join(", ")}</li>
            )}
            {rechazar.length > 0 && (
              <li style={{ color: colores.error }}>
                Se rechazan y cancelan: {rechazar.map((d) => d.id).join(", ")}
              </li>
            )}
            {sinRespuesta.length > 0 && (
              <li>
                Siguen pendientes: {sinRespuesta.map((d) => d.id).join(", ")}
              </li>
            )}
          </ul>
          <div style={{ display: "flex", gap: "0.5rem" }}>
            <Boton disabled={ocupado} onClick={registrar}>
              Confirmar
            </Boton>
            <Boton variante="secundario" onClick={() => setConfirmando(false)}>
              Volver
            </Boton>
          </div>
        </div>
      )}
      {!hayDecision && (
        <p style={{ margin: "0.4rem 0 0", fontSize: "0.8rem", color: colores.suave }}>
          Elegí Autorizar o Rechazar en al menos un Detalle: "Dejar pendiente"
          no registra nada.
        </p>
      )}
    </div>
  );
}
