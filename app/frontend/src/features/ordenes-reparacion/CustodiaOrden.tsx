/**
 * Recepción física y custodia del equipo.
 *
 * Separa dos hechos que no se infieren uno del otro: el comprobante de
 * recepción emitido (un documento) y el equipo físicamente en el local
 * (la custodia, que Recepción confirma). Muestra los datos del ingreso,
 * sus correcciones y las observaciones complementarias. Los formularios
 * aparecen solo si el backend los ofrece en `acciones_custodia`.
 */

import { useEffect, useState } from "react";

import type { DatosEquipo } from "../../api/ordenes";
import {
  Boton,
  Campo,
  Etiqueta,
  Panel,
  colores,
  estiloInput,
  fechaCorta,
} from "../../components/ui";
import type {
  Accion,
  DatosRecepcion,
  EstadoCustodia,
  Orden,
  Usuario,
} from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";
import { listaDeAccesorios } from "./ListadoOrdenes";
import { Confirmacion, Seccion, habilitada } from "./PagosOrden";

interface Props {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  ocupado: boolean;
  onRegistrar: (datos: DatosRecepcion, equipo: DatosEquipo | null) => void;
  onConfirmar: (observaciones: string | null) => void;
  onNoRecibido: (motivo: string) => void;
  onObservar: (texto: string) => void;
}

const COLOR_CUSTODIA: Record<EstadoCustodia, string> = {
  PENDIENTE_CONFIRMACION: colores.alerta,
  SIN_REGISTRO: colores.error,
  EN_CUSTODIA: colores.ok,
  ENTREGADO: colores.texto,
  DEVUELTO: colores.texto,
  NO_RECIBIDO: colores.suave,
};

/** Texto del estado de custodia, con quién y cuándo si corresponde. */
function descripcionCustodia(orden: Orden, usuarios: Usuario[]): string {
  const { custodia } = orden;
  const salida = custodia.salida;
  const retira = salida
    ? `${salida.recibido_por}${
        salida.identificacion_receptor
          ? ` (${salida.identificacion_receptor})`
          : ""
      } el ${fechaCorta(salida.fecha)}, por ${nombreDeUsuario(usuarios, salida.entregado_por)}`
    : "";
  switch (custodia.estado) {
    case "PENDIENTE_CONFIRMACION":
      return "Recepción física pendiente de confirmar. El comprobante no la prueba: confirmala cuando el equipo esté en el local.";
    case "SIN_REGISTRO":
      return "Orden anterior al registro de recepción: no hay custodia confirmada. Regularizá los datos del ingreso y la confirmación antes de entregar o devolver el equipo.";
    case "EN_CUSTODIA":
      return custodia.confirmacion_requerida
        ? `Equipo en custodia: recepción confirmada por ${nombreDeUsuario(usuarios, custodia.confirmada_por)} el ${fechaCorta(custodia.confirmada_en ?? "")}`
        : "Equipo interno recibido por el circuito de Gestión RT (sin confirmación de recepción).";
    case "ENTREGADO":
      return salida
        ? `Entregado a ${retira}.`
        : "Entregado (Orden anterior al registro de quién retira).";
    case "DEVUELTO":
      return salida
        ? `Devuelto sin reparar a ${retira}.`
        : "Devuelto a Gestión RT.";
    case "NO_RECIBIDO": {
      const decision = orden.recepcion?.no_recibido;
      return decision
        ? `Equipo no recibido: lo registró ${nombreDeUsuario(usuarios, decision.usuario_id)} el ${fechaCorta(decision.fecha)} · Motivo: ${decision.motivo}`
        : "Equipo no recibido.";
    }
  }
}

function Fila({ etiqueta, valor }: { etiqueta: string; valor: string }) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "minmax(6.5rem, min(32%, 11rem)) minmax(0, 1fr)",
        gap: "0.5rem",
        padding: "0.2rem 0",
        fontSize: "0.85rem",
      }}
    >
      <span style={{ color: colores.suave }}>{etiqueta}</span>
      <span style={{ overflowWrap: "anywhere" }}>{valor}</span>
    </div>
  );
}

export function CustodiaOrden(props: Props) {
  const { orden, usuarios } = props;
  const { custodia, recepcion, equipo } = orden;
  const acciones = orden.acciones_custodia;
  const buscar = (codigo: string) =>
    acciones.find((accion) => accion.codigo === codigo);
  const registrar = buscar("REGISTRAR_DATOS_RECEPCION");
  const confirmar = buscar("CONFIRMAR_RECEPCION");
  const noRecibido = buscar("REGISTRAR_EQUIPO_NO_RECIBIDO");
  const observar = buscar("AGREGAR_OBSERVACION_RECEPCION");

  return (
    <Panel titulo="Recepción y custodia">
      <p
        role="status"
        style={{
          margin: "0 0 0.75rem",
          padding: "0.6rem 0.8rem",
          borderRadius: 6,
          border: `1px solid ${COLOR_CUSTODIA[custodia.estado]}`,
          fontSize: "0.85rem",
        }}
      >
        <Etiqueta color={COLOR_CUSTODIA[custodia.estado]}>
          {custodia.estado}
        </Etiqueta>{" "}
        {descripcionCustodia(orden, usuarios)}
      </p>
      <PendientesDeCierre orden={orden} />
      <p style={{ margin: "0 0 0.75rem", fontSize: "0.8rem", color: colores.suave }}>
        Comprobante de recepción:{" "}
        <strong>
          {custodia.comprobante_recepcion_emitido ? "emitido" : "no emitido"}
        </strong>{" "}
        (es un hecho aparte de la custodia).
      </p>

      <Fila etiqueta="Equipo" valor={`${equipo.marca} ${equipo.modelo}`} />
      <Fila etiqueta="IMEI" valor={equipo.imei ?? "—"} />
      <Fila etiqueta="N.º de serie" valor={equipo.numero_serie ?? "—"} />
      <Fila etiqueta="Falla declarada" valor={equipo.falla_reportada} />
      {recepcion ? (
        <>
          <Fila
            etiqueta="Estado físico"
            valor={recepcion.datos.estado_fisico ?? "No registrado"}
          />
          <Fila
            etiqueta="Accesorios"
            valor={
              recepcion.datos.accesorios.length
                ? recepcion.datos.accesorios.join(", ")
                : "Ninguno"
            }
          />
          <Fila
            etiqueta="Observaciones"
            valor={recepcion.datos.observaciones ?? "—"}
          />
          <Fila
            etiqueta={
              recepcion.registro === "REGULARIZACION"
                ? "Regularizado por"
                : "Registrado por"
            }
            valor={`${nombreDeUsuario(usuarios, recepcion.registrado_por)} · ${fechaCorta(recepcion.registrado_en)}`}
          />
          {recepcion.versiones_anteriores.length > 0 && (
            <details style={{ margin: "0.3rem 0", fontSize: "0.8rem" }}>
              <summary style={{ cursor: "pointer", color: colores.suave }}>
                Versiones anteriores de los datos del ingreso (
                {recepcion.versiones_anteriores.length})
              </summary>
              <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.1rem" }}>
                {recepcion.versiones_anteriores.map((version) => (
                  <li key={version.reemplazado_en} style={{ marginBottom: "0.3rem" }}>
                    {version.equipo.marca} {version.equipo.modelo}
                    {version.equipo.imei ? ` · IMEI ${version.equipo.imei}` : ""} ·{" "}
                    {version.datos.estado_fisico ?? "sin estado físico"} ·
                    accesorios:{" "}
                    {version.datos.accesorios.join(", ") || "ninguno"}
                    <br />
                    <span style={{ color: colores.suave }}>
                      Registrado por{" "}
                      {nombreDeUsuario(usuarios, version.registrado_por)} el{" "}
                      {fechaCorta(version.registrado_en)}; reemplazado por{" "}
                      {nombreDeUsuario(usuarios, version.reemplazado_por)} el{" "}
                      {fechaCorta(version.reemplazado_en)}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          )}
          {recepcion.notas.length > 0 && (
            <div style={{ marginTop: "0.4rem" }}>
              <p style={{ margin: "0 0 0.2rem", fontSize: "0.8rem", color: colores.suave }}>
                Observaciones complementarias
              </p>
              <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
                {recepcion.notas.map((nota) => (
                  <li key={nota.fecha + nota.texto}>
                    {nota.texto}{" "}
                    <span style={{ color: colores.suave }}>
                      ({nombreDeUsuario(usuarios, nota.usuario_id)},{" "}
                      {fechaCorta(nota.fecha)})
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      ) : (
        <p style={{ margin: "0.3rem 0 0", fontSize: "0.85rem", color: colores.suave }}>
          Sin datos de ingreso registrados (Orden anterior a este registro).
        </p>
      )}

      {confirmar && <FormularioConfirmacion {...props} accion={confirmar} />}
      {noRecibido && <FormularioNoRecibido {...props} accion={noRecibido} />}
      {registrar && <FormularioDatosIngreso {...props} accion={registrar} />}
      {observar && <FormularioNota {...props} accion={observar} />}
    </Panel>
  );
}

/**
 * Qué le falta a una Orden cancelada para cerrarse (lo calcula el backend):
 * definir la custodia, devolver el equipo, devolver el dinero.
 */
export function PendientesDeCierre({ orden }: { orden: Orden }) {
  if (orden.pendientes_de_cierre.length === 0) return null;
  return (
    <div
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
      <strong>Orden cancelada abierta.</strong> Para cerrarla:
      <ul style={{ margin: "0.3rem 0 0", paddingLeft: "1.1rem" }}>
        {orden.pendientes_de_cierre.map((pendiente) => (
          <li key={pendiente}>{pendiente}</li>
        ))}
      </ul>
    </div>
  );
}

/**
 * «Equipo no recibido»: el equipo nunca ingresó. Motivo obligatorio y
 * confirmación; el backend la rechaza si algo prueba que el equipo estuvo
 * en el local.
 */
function FormularioNoRecibido({
  orden,
  actor,
  ocupado,
  onNoRecibido,
  accion,
}: Props & { accion: Accion }) {
  const [motivo, setMotivo] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const deshabilitado = !habilitada(accion, actor) || ocupado;

  useEffect(() => setConfirmando(false), [motivo]);

  return (
    <Seccion titulo="Confirmar equipo no recibido" accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Solo si el equipo nunca ingresó físicamente al local. No se registra
        devolución física; la Orden cierra cuando la cuenta queda saldada.
      </p>
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          disabled={deshabilitado}
          onChange={(evento) => setMotivo(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      {!confirmando ? (
        <Boton
          variante="secundario"
          disabled={deshabilitado || !motivo.trim()}
          onClick={() => setConfirmando(true)}
        >
          Confirmar equipo no recibido
        </Boton>
      ) : (
        <Confirmacion
          texto={`¿Confirmás que el equipo de ${orden.id} nunca ingresó al local? La decisión no se puede cambiar.`}
          ocupado={ocupado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={() => onNoRecibido(motivo.trim())}
        />
      )}
    </Seccion>
  );
}

function FormularioConfirmacion({
  orden,
  actor,
  ocupado,
  onConfirmar,
  accion,
}: Props & { accion: Accion }) {
  const [observaciones, setObservaciones] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const regularizacion = orden.recepcion?.registro === "REGULARIZACION";
  const sinEstado = !orden.recepcion?.datos.estado_fisico;
  const deshabilitado = !habilitada(accion, actor) || ocupado || sinEstado;
  const faltaMotivo = regularizacion && !observaciones.trim();

  useEffect(() => setConfirmando(false), [observaciones]);

  return (
    <Seccion titulo="Confirmar la recepción física" accion={accion} actor={actor}>
      {sinEstado && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.alerta }}>
          Registrá primero el estado físico del equipo.
        </p>
      )}
      <Campo
        etiqueta={
          regularizacion
            ? "Motivo de la regularización (obligatorio)"
            : "Observaciones (opcional)"
        }
      >
        <input
          value={observaciones}
          disabled={deshabilitado}
          onChange={(evento) => setObservaciones(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      {!confirmando ? (
        <Boton
          disabled={deshabilitado || faltaMotivo}
          onClick={() => setConfirmando(true)}
        >
          Confirmar recepción física
        </Boton>
      ) : (
        <Confirmacion
          texto={`¿Confirmás que el equipo ${orden.equipo.marca} ${orden.equipo.modelo} de ${orden.id} está físicamente en el local?`}
          ocupado={ocupado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={() => onConfirmar(observaciones.trim() || null)}
        />
      )}
    </Seccion>
  );
}

function FormularioDatosIngreso({
  orden,
  actor,
  ocupado,
  onRegistrar,
  accion,
}: Props & { accion: Accion }) {
  const { equipo, recepcion } = orden;
  const [abierto, setAbierto] = useState(recepcion === null);
  const [marca, setMarca] = useState(equipo.marca);
  const [modelo, setModelo] = useState(equipo.modelo);
  const [falla, setFalla] = useState(equipo.falla_reportada);
  const [imei, setImei] = useState(equipo.imei ?? "");
  const [serie, setSerie] = useState(equipo.numero_serie ?? "");
  const [estado, setEstado] = useState(recepcion?.datos.estado_fisico ?? "");
  const [accesorios, setAccesorios] = useState(
    recepcion?.datos.accesorios.join(", ") ?? "",
  );
  const [observaciones, setObservaciones] = useState(
    recepcion?.datos.observaciones ?? "",
  );
  const deshabilitado = !habilitada(accion, actor) || ocupado;

  const titulo =
    recepcion === null
      ? "Regularizar: registrar los datos del ingreso"
      : "Corregir los datos del ingreso";

  if (!abierto) {
    return (
      <div style={{ marginTop: "0.8rem" }}>
        <Boton variante="secundario" onClick={() => setAbierto(true)}>
          {titulo}
        </Boton>
      </div>
    );
  }

  const campo = (
    etiqueta: string,
    valor: string,
    cambiar: (valor: string) => void,
  ) => (
    <Campo etiqueta={etiqueta}>
      <input
        value={valor}
        disabled={deshabilitado}
        onChange={(evento) => cambiar(evento.target.value)}
        style={estiloInput}
      />
    </Campo>
  );

  return (
    <Seccion titulo={titulo} accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Solo antes de confirmar la recepción. La versión anterior queda
        registrada.
      </p>
      <div
        style={{
          display: "grid",
          columnGap: "0.6rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))",
        }}
      >
        {campo("Marca", marca, setMarca)}
        {campo("Modelo", modelo, setModelo)}
        {campo("IMEI (si tiene)", imei, setImei)}
        {campo("N.º de serie (si tiene)", serie, setSerie)}
      </div>
      {campo("Falla declarada", falla, setFalla)}
      {campo("Estado físico", estado, setEstado)}
      {campo("Accesorios (separados por coma)", accesorios, setAccesorios)}
      {campo("Observaciones iniciales", observaciones, setObservaciones)}
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
        <Boton
          disabled={deshabilitado || !marca.trim() || !modelo.trim() || !falla.trim()}
          onClick={() =>
            onRegistrar(
              {
                estado_fisico: estado.trim() || null,
                accesorios: listaDeAccesorios(accesorios),
                observaciones: observaciones.trim() || null,
              },
              {
                marca: marca.trim(),
                modelo: modelo.trim(),
                falla_reportada: falla.trim(),
                imei: imei.trim() || null,
                numero_serie: serie.trim() || null,
              },
            )
          }
        >
          Guardar datos del ingreso
        </Boton>
        {recepcion !== null && (
          <Boton variante="secundario" onClick={() => setAbierto(false)}>
            Cerrar
          </Boton>
        )}
      </div>
    </Seccion>
  );
}

function FormularioNota({
  actor,
  ocupado,
  onObservar,
  accion,
}: Props & { accion: Accion }) {
  const [texto, setTexto] = useState("");
  const deshabilitado = !habilitada(accion, actor) || ocupado;
  return (
    <Seccion
      titulo="Agregar una observación complementaria"
      accion={accion}
      actor={actor}
    >
      <Campo etiqueta="Observación">
        <input
          value={texto}
          disabled={deshabilitado}
          onChange={(evento) => setTexto(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Boton
        variante="secundario"
        disabled={deshabilitado || !texto.trim()}
        onClick={() => {
          onObservar(texto.trim());
          setTexto("");
        }}
      >
        Agregar observación
      </Boton>
    </Seccion>
  );
}
