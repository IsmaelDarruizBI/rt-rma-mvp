/**
 * Pagos y movimientos de la Orden (FEAT-REP-007, BR-REP-017/038).
 *
 * Muestra la cuenta -Total, Pagado válido, Devuelto y Saldo o crédito a
 * favor- y la lista cronológica de pagos, anulaciones y devoluciones de
 * dinero. Los formularios aparecen solo si el backend los ofrece en
 * `acciones_financieras`; el backend vuelve a validar todo (rol, importe,
 * saldo, duplicados) igual.
 */

import { type ReactNode, useEffect, useState } from "react";

import type { DatosDevolucionDinero } from "../../api/ordenes";
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
  MedioPago,
  Orden,
  SituacionFinanciera,
  Usuario,
} from "../../types/api";
import { nombreDeUsuario } from "./DetalleOrden";

interface Props {
  orden: Orden;
  actor: Usuario | null;
  usuarios: Usuario[];
  medios: MedioPago[];
  ocupado: boolean;
  onPagar: (
    monto: string,
    metodo: string,
    referencia: string | null,
    operacionId: string,
  ) => void;
  onAnular: (pagoId: string, motivo: string) => void;
  onDevolver: (datos: DatosDevolucionDinero) => void;
}

const ETIQUETA_CONDICION_COMERCIAL: Record<string, string> = {
  COBRABLE: "Cobrable al cliente",
  NO_COBRABLE_AL_CLIENTE: "No cobrable (equipo RT interno)",
  NO_COBRABLE: "No cobrable (garantía)",
};

const AVISO: Record<
  SituacionFinanciera,
  { texto: (orden: Orden) => string; color: string } | null
> = {
  SALDO_PENDIENTE: {
    texto: (orden) =>
      `Saldo pendiente de cobro: ${importe(orden.resumen.saldo)}`,
    color: colores.alerta,
  },
  SALDO_A_FAVOR: {
    texto: (orden) =>
      `Saldo a favor del cliente: ${importe(orden.resumen.credito_a_favor)} · Devolución pendiente`,
    color: colores.error,
  },
  SALDADA: { texto: () => "Cuenta saldada", color: colores.ok },
  SIN_MOVIMIENTOS: null,
  NO_COBRABLE: null,
};

/** Clave del envío: un reintento del mismo formulario no duplica nada. */
function nuevaOperacion(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `op-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function nombreDeMedio(medios: MedioPago[], medioId: string | null): string {
  if (!medioId) return "—";
  return medios.find((medio) => medio.id === medioId)?.nombre ?? medioId;
}

export function habilitada(accion: Accion, actor: Usuario | null): boolean {
  return (
    actor !== null &&
    (accion.roles.length === 0 || accion.roles.includes(actor.rol))
  );
}

export function PagosYMovimientos(props: Props) {
  const { orden, medios, usuarios } = props;
  const { resumen } = orden;
  const cobrable = resumen.condicion_comercial === "COBRABLE";
  const saldo = Number(resumen.saldo);
  const filas: [string, string][] = [
    [cobrable ? "Total" : "Total (nominal)", importe(resumen.total)],
    ["Pagado válido", importe(resumen.pagado)],
    ["Devuelto", importe(resumen.devuelto)],
    [
      !cobrable
        ? "Saldo (nominal)"
        : saldo < 0
          ? "Crédito a favor del cliente"
          : "Saldo pendiente",
      importe(saldo < 0 ? resumen.credito_a_favor : resumen.saldo),
    ],
    ["Estado de pago", resumen.estado_pago],
    ["Puntaje", String(resumen.puntaje_total)],
  ];
  const aviso = AVISO[resumen.situacion_financiera];
  const acciones = orden.acciones_financieras;
  const cobro = acciones.find((a) => a.codigo === "REGISTRAR_PAGO");
  const devolucion = acciones.find(
    (a) => a.codigo === "REGISTRAR_DEVOLUCION_DINERO",
  );
  const anulaciones = acciones.filter((a) => a.codigo === "ANULAR_PAGO");

  return (
    <Panel titulo="Pagos y movimientos">
      <p
        style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}
      >
        {ETIQUETA_CONDICION_COMERCIAL[resumen.condicion_comercial] ??
          resumen.condicion_comercial}
        {!cobrable && ": el total/saldo son nominales, no una deuda a cobrar."}
      </p>
      {aviso && (
        <p
          role="status"
          style={{
            margin: "0 0 0.7rem",
            padding: "0.5rem 0.7rem",
            borderRadius: 6,
            border: `1px solid ${aviso.color}`,
            color: aviso.color,
            fontWeight: 600,
            fontSize: "0.9rem",
          }}
        >
          {aviso.texto(orden)}
        </p>
      )}
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
      <ListaMovimientos orden={orden} medios={medios} usuarios={usuarios} />
      {cobro && (
        <FormularioCobro
          key={`cobro-${orden.updated_at}`}
          accion={cobro}
          {...props}
        />
      )}
      {devolucion && (
        <FormularioDevolucionDinero
          key={`devolucion-${orden.updated_at}`}
          accion={devolucion}
          {...props}
        />
      )}
      {anulaciones.length > 0 && (
        <FormularioAnulacion
          key={`anulacion-${orden.updated_at}`}
          acciones={anulaciones}
          {...props}
        />
      )}
    </Panel>
  );
}

interface Fila {
  fecha: string;
  clave: string;
  movimiento: string;
  medio: string;
  importe: string;
  usuario: string;
  detalle: string;
  color: string;
  anulado?: boolean;
}

function ListaMovimientos({
  orden,
  medios,
  usuarios,
}: {
  orden: Orden;
  medios: MedioPago[];
  usuarios: Usuario[];
}) {
  const filas: Fila[] = [];
  for (const pago of orden.pagos) {
    filas.push({
      fecha: pago.fecha,
      clave: pago.id,
      movimiento: `Pago ${pago.tipo_pago} · ${pago.id}`,
      medio: nombreDeMedio(medios, pago.metodo),
      importe: importe(pago.monto),
      usuario: nombreDeUsuario(usuarios, pago.usuario_id),
      detalle: pago.referencia ?? "",
      color: pago.tipo_pago === "ANTICIPO" ? colores.alerta : colores.ok,
      anulado: !pago.vigente,
    });
    if (pago.anulacion) {
      filas.push({
        fecha: pago.anulacion.fecha,
        clave: `${pago.id}-anulacion`,
        movimiento: `Anulación de ${pago.id}`,
        medio: "—",
        importe: `−${importe(pago.monto)}`,
        usuario: nombreDeUsuario(usuarios, pago.anulacion.usuario_id),
        detalle: pago.anulacion.motivo,
        color: colores.texto,
      });
    }
  }
  for (const devolucion of orden.devoluciones_dinero) {
    filas.push({
      fecha: devolucion.fecha,
      clave: devolucion.id,
      movimiento: `Devolución desde ${devolucion.pago_id}`,
      medio: nombreDeMedio(medios, devolucion.medio),
      importe: `−${importe(devolucion.monto)}`,
      usuario: nombreDeUsuario(usuarios, devolucion.usuario_id),
      detalle: [devolucion.motivo, devolucion.referencia]
        .filter(Boolean)
        .join(" · "),
      color: colores.error,
    });
  }
  filas.sort((a, b) => a.fecha.localeCompare(b.fecha));

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
        Movimientos
      </h4>
      {filas.length === 0 ? (
        <p style={{ margin: 0, color: colores.suave, fontSize: "0.85rem" }}>
          Todavía no se registró ningún pago.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.82rem",
            }}
          >
            <thead>
              <tr style={{ textAlign: "left", color: colores.suave }}>
                <th style={{ padding: "0.2rem 0.3rem 0.2rem 0" }}>Fecha</th>
                <th>Movimiento</th>
                <th>Medio</th>
                <th style={{ textAlign: "right", paddingRight: "0.75rem" }}>
                  Importe
                </th>
                <th>Usuario</th>
                <th>Detalle</th>
              </tr>
            </thead>
            <tbody>
              {filas.map((fila) => (
                <tr
                  key={fila.clave}
                  style={{ borderTop: `1px solid ${colores.borde}` }}
                >
                  <td style={{ padding: "0.3rem 0.3rem 0.3rem 0", whiteSpace: "nowrap" }}>
                    {fechaCorta(fila.fecha)}
                  </td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    <Etiqueta color={fila.color}>{fila.movimiento}</Etiqueta>
                    {fila.anulado && (
                      <>
                        {" "}
                        <Etiqueta color={colores.texto}>ANULADO</Etiqueta>
                      </>
                    )}
                  </td>
                  <td>{fila.medio}</td>
                  <td
                    style={{
                      textAlign: "right",
                      paddingRight: "0.75rem",
                      whiteSpace: "nowrap",
                      fontWeight: 600,
                      textDecoration: fila.anulado ? "line-through" : "none",
                    }}
                  >
                    {fila.importe}
                  </td>
                  <td>{fila.usuario}</td>
                  <td style={{ color: colores.suave }}>{fila.detalle}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function Seccion({
  titulo,
  accion,
  actor,
  children,
}: {
  titulo: string;
  accion: Accion;
  actor: Usuario | null;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        marginTop: "1rem",
        paddingTop: "0.9rem",
        borderTop: `1px solid ${colores.borde}`,
      }}
    >
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>{titulo}</p>
      {!habilitada(accion, actor) && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.alerta }}>
          Requiere el rol {accion.roles.join(" o ")}. Cambiá el actor demo
          para registrarlo.
        </p>
      )}
      {children}
    </div>
  );
}

function SelectorMedio({
  medios,
  valor,
  onCambiar,
  deshabilitado,
  paraDevolucion = false,
}: {
  medios: MedioPago[];
  valor: string;
  onCambiar: (medio: string) => void;
  deshabilitado: boolean;
  paraDevolucion?: boolean;
}) {
  const opciones = medios.filter(
    (medio) => medio.activo && (!paraDevolucion || medio.admite_devolucion),
  );
  return (
    <select
      value={valor}
      disabled={deshabilitado}
      onChange={(evento) => onCambiar(evento.target.value)}
      style={estiloInput}
    >
      {opciones.map((medio) => (
        <option key={medio.id} value={medio.id}>
          {medio.nombre}
        </option>
      ))}
    </select>
  );
}

function FormularioCobro({
  accion,
  orden,
  actor,
  medios,
  ocupado,
  onPagar,
}: Props & { accion: Accion }) {
  const saldo = Number(orden.resumen.saldo);
  const [monto, setMonto] = useState(saldo > 0 ? orden.resumen.saldo : "");
  const [metodo, setMetodo] = useState(
    medios.find((medio) => medio.activo)?.id ?? "",
  );
  const [referencia, setReferencia] = useState("");
  const [operacion] = useState(nuevaOperacion);
  const deshabilitado = !habilitada(accion, actor) || ocupado;

  return (
    <Seccion titulo={accion.etiqueta} accion={accion} actor={actor}>
      {saldo <= 0 && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
          Seña antes de definir los trabajos: si después no se realizan, se
          devuelve.
        </p>
      )}
      <Campo
        etiqueta={
          saldo > 0
            ? `Importe (hasta ${importe(orden.resumen.saldo)})`
            : "Importe"
        }
      >
        <input
          value={monto}
          inputMode="decimal"
          disabled={deshabilitado}
          onChange={(evento) => setMonto(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Medio de pago">
        <SelectorMedio
          medios={medios}
          valor={metodo}
          onCambiar={setMetodo}
          deshabilitado={deshabilitado}
        />
      </Campo>
      <Campo etiqueta="Referencia (opcional)">
        <input
          value={referencia}
          disabled={deshabilitado}
          onChange={(evento) => setReferencia(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={deshabilitado || !monto.trim() || !metodo}
        onClick={() =>
          onPagar(monto.trim(), metodo, referencia.trim() || null, operacion)
        }
      >
        {accion.etiqueta}
      </Boton>
    </Seccion>
  );
}

function FormularioDevolucionDinero({
  accion,
  orden,
  actor,
  medios,
  ocupado,
  onDevolver,
}: Props & { accion: Accion }) {
  const credito = Number(orden.resumen.credito_a_favor);
  const pagos = orden.pagos.filter(
    (pago) => pago.vigente && Number(pago.devolvible) > 0,
  );
  const [pagoId, setPagoId] = useState(pagos[0]?.id ?? "");
  const pago = pagos.find((candidato) => candidato.id === pagoId);
  const sugerido = pago
    ? String(Math.min(credito, Number(pago.devolvible)))
    : "";
  const [monto, setMonto] = useState(sugerido);
  const [medio, setMedio] = useState(
    medios.find((m) => m.activo && m.admite_devolucion)?.id ?? "",
  );
  const [motivo, setMotivo] = useState("");
  const [referencia, setReferencia] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const [operacion] = useState(nuevaOperacion);
  const deshabilitado = !habilitada(accion, actor) || ocupado;

  useEffect(() => setMonto(sugerido), [sugerido]);
  useEffect(
    () => setConfirmando(false),
    [pagoId, monto, medio, motivo, referencia],
  );

  return (
    <Seccion titulo={accion.etiqueta} accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Registra dinero efectivamente devuelto. No modifica el pago
        original: queda vinculado a él.
      </p>
      <Campo etiqueta="Pago desde el que se devuelve">
        <select
          value={pagoId}
          disabled={deshabilitado}
          onChange={(evento) => setPagoId(evento.target.value)}
          style={estiloInput}
        >
          {pagos.map((candidato) => (
            <option key={candidato.id} value={candidato.id}>
              {candidato.id} · {importe(candidato.monto)} ·{" "}
              {nombreDeMedio(medios, candidato.metodo)} · disponible{" "}
              {importe(candidato.devolvible)}
            </option>
          ))}
        </select>
      </Campo>
      <Campo etiqueta={`Importe (crédito pendiente ${importe(orden.resumen.credito_a_favor)})`}>
        <input
          value={monto}
          inputMode="decimal"
          disabled={deshabilitado}
          onChange={(evento) => setMonto(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Medio de devolución">
        <SelectorMedio
          medios={medios}
          valor={medio}
          onCambiar={setMedio}
          deshabilitado={deshabilitado}
          paraDevolucion
        />
      </Campo>
      <Campo etiqueta="Motivo (obligatorio)">
        <input
          value={motivo}
          disabled={deshabilitado}
          onChange={(evento) => setMotivo(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Referencia de la operación (opcional)">
        <input
          value={referencia}
          disabled={deshabilitado}
          onChange={(evento) => setReferencia(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      {!confirmando ? (
        <Boton
          disabled={
            deshabilitado || !pagoId || !monto.trim() || !medio || !motivo.trim()
          }
          onClick={() => setConfirmando(true)}
        >
          Registrar devolución
        </Boton>
      ) : (
        <Confirmacion
          texto={`¿Confirmás que se devolvieron ${importe(monto)} al cliente desde ${pagoId}?`}
          ocupado={ocupado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={() =>
            onDevolver({
              pago_id: pagoId,
              monto: monto.trim(),
              medio,
              motivo: motivo.trim(),
              referencia: referencia.trim() || null,
              operacion_id: operacion,
            })
          }
        />
      )}
    </Seccion>
  );
}

function FormularioAnulacion({
  acciones,
  orden,
  actor,
  medios,
  ocupado,
  onAnular,
}: Props & { acciones: Accion[] }) {
  const [pagoId, setPagoId] = useState(acciones[0]?.pago_id ?? "");
  const [motivo, setMotivo] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  const accion = acciones[0];
  const deshabilitado = !habilitada(accion, actor) || ocupado;

  useEffect(() => setConfirmando(false), [pagoId, motivo]);

  const descripcion = (id: string | null) => {
    const pago = orden.pagos.find((candidato) => candidato.id === id);
    return pago
      ? `${pago.id} · ${pago.tipo_pago} · ${importe(pago.monto)} · ${nombreDeMedio(medios, pago.metodo)}`
      : (id ?? "");
  };

  return (
    <Seccion titulo="Anular un pago registrado por error" accion={accion} actor={actor}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Corrige un registro equivocado: el pago queda en el historial como
        anulado y deja de contar como pagado. No es una devolución de dinero.
      </p>
      <Campo etiqueta="Pago">
        <select
          value={pagoId}
          disabled={deshabilitado}
          onChange={(evento) => setPagoId(evento.target.value)}
          style={estiloInput}
        >
          {acciones.map((candidata) => (
            <option key={candidata.pago_id} value={candidata.pago_id ?? ""}>
              {descripcion(candidata.pago_id)}
            </option>
          ))}
        </select>
      </Campo>
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
          disabled={deshabilitado || !pagoId || !motivo.trim()}
          onClick={() => setConfirmando(true)}
        >
          Anular pago
        </Boton>
      ) : (
        <Confirmacion
          texto={`¿Confirmás la anulación de ${descripcion(pagoId)}? No se puede deshacer.`}
          ocupado={ocupado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={() => onAnular(pagoId, motivo.trim())}
        />
      )}
    </Seccion>
  );
}

export function Confirmacion({
  texto,
  ocupado,
  onConfirmar,
  onVolver,
}: {
  texto: string;
  ocupado: boolean;
  onConfirmar: () => void;
  onVolver: () => void;
}) {
  return (
    <div
      role="alertdialog"
      aria-label={texto}
      style={{
        padding: "0.6rem 0.8rem",
        borderRadius: 6,
        border: `1px solid ${colores.alerta}`,
        background: "#fff8e6",
        fontSize: "0.85rem",
      }}
    >
      <p style={{ margin: "0 0 0.5rem" }}>
        <strong>{texto}</strong>
      </p>
      <div style={{ display: "flex", gap: "0.5rem" }}>
        <Boton disabled={ocupado} onClick={onConfirmar}>
          Confirmar
        </Boton>
        <Boton variante="secundario" onClick={onVolver}>
          Volver
        </Boton>
      </div>
    </div>
  );
}
