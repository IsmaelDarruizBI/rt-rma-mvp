/**
 * Inventario operativo: existencias, movimientos, ingresos, ajustes y
 * revalidación de Órdenes que esperan recursos.
 *
 * Todo cálculo (reservado, disponible, faltantes) y toda regla (rol,
 * motivo, duplicados, confirmación) vive en el backend; acá se muestra lo
 * que devuelve y se piden confirmaciones antes de enviar.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/inventario";
import { ApiError } from "../../api/client";
import {
  Boton,
  Campo,
  Etiqueta,
  MensajeError,
  Panel,
  colores,
  estiloInput,
  fechaCorta,
} from "../../components/ui";
import type {
  DetalleInsumo,
  ResultadoRevalidacion,
  RolUsuario,
  SituacionInsumo,
  Usuario,
} from "../../types/api";
import { nombreDeUsuario } from "../ordenes-reparacion/DetalleOrden";
import { Confirmacion } from "../ordenes-reparacion/PagosOrden";

/** Provisorio, a validar con Rosario Tecno (el backend lo exige igual). */
const ROLES_GESTION: RolUsuario[] = ["ADMINISTRADOR", "COORDINADOR_RMA"];

const ETIQUETA_TIPO: Record<string, string> = {
  RESERVA: "Reserva",
  CONSUMO: "Consumo",
  LIBERACION_RESERVA: "Liberación de reserva",
  DEVOLUCION: "Devolución",
  INGRESO: "Ingreso",
  AJUSTE_POSITIVO: "Ajuste +",
  AJUSTE_NEGATIVO: "Ajuste −",
};

const COLOR_RESULTADO: Record<string, string> = {
  TRABAJABLE: colores.ok,
  SIGUE_ESPERANDO: colores.alerta,
  OTRA_INTERVENCION: colores.acento,
  SIN_CAMBIOS: colores.suave,
  ERROR: colores.error,
};

function nuevaOperacion(): string {
  return typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `op-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function mensajeDe(fallo: unknown): string {
  return fallo instanceof ApiError ? fallo.message : "Ocurrió un error inesperado.";
}

function cantidad(valor: string, insumo: SituacionInsumo): string {
  return insumo.unidad ? `${valor} ${insumo.unidad}` : valor;
}

const celda = { padding: "0.35rem 0.5rem 0.35rem 0", verticalAlign: "top" } as const;

export function InventarioPanel({
  actor,
  usuarios,
}: {
  actor: Usuario | null;
  usuarios: Usuario[];
}) {
  const [insumos, setInsumos] = useState<SituacionInsumo[]>([]);
  const [buscar, setBuscar] = useState("");
  const [soloFaltantes, setSoloFaltantes] = useState(false);
  const [seleccionado, setSeleccionado] = useState<string | null>(null);
  const [detalle, setDetalle] = useState<DetalleInsumo | null>(null);
  const [revalidacion, setRevalidacion] = useState<ResultadoRevalidacion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const puedeGestionar = actor !== null && ROLES_GESTION.includes(actor.rol);

  const recargar = useCallback(async () => {
    try {
      setInsumos(await api.listarInventario(buscar.trim() || null, soloFaltantes));
      if (seleccionado) setDetalle(await api.obtenerInsumo(seleccionado));
    } catch (fallo) {
      setError(mensajeDe(fallo));
    }
  }, [buscar, soloFaltantes, seleccionado]);

  useEffect(() => {
    void recargar();
  }, [recargar]);

  const operar = async (operacion: () => Promise<string>) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    try {
      setAviso(await operacion());
      await recargar();
    } catch (fallo) {
      setError(mensajeDe(fallo));
      await recargar();
    } finally {
      setOcupado(false);
    }
  };

  return (
    <div style={{ display: "grid", gap: "0.75rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
      <Panel titulo="Inventario">
        <div
          style={{
            display: "flex",
            gap: "0.6rem",
            alignItems: "flex-end",
            flexWrap: "wrap",
            marginBottom: "0.75rem",
          }}
        >
          <label style={{ flex: "1 1 220px" }}>
            <span style={{ display: "block", fontSize: "0.75rem", color: colores.suave }}>
              Buscar por código o nombre
            </span>
            <input
              value={buscar}
              onChange={(evento) => setBuscar(evento.target.value)}
              placeholder="Ej.: BAT, pantalla"
              style={estiloInput}
            />
          </label>
          <label style={{ display: "flex", gap: "0.35rem", alignItems: "center", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={soloFaltantes}
              onChange={(evento) => setSoloFaltantes(evento.target.checked)}
            />
            Solo faltantes
          </label>
          <Boton
            variante="secundario"
            disabled={!puedeGestionar || ocupado}
            onClick={() =>
              void operar(async () => {
                const resultado = await api.revalidarOrdenes(actor?.id ?? "");
                setRevalidacion(resultado);
                return `Revalidación: ${resultado.evaluadas} Orden(es) evaluada(s), ${resultado.trabajables} trabajable(s).`;
              })
            }
          >
            Revalidar órdenes esperando recursos
          </Boton>
        </div>
        {!puedeGestionar && (
          <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.alerta }}>
            Consulta para todos los roles. Ingresos, ajustes y revalidación
            requieren ADMINISTRADOR o COORDINADOR_RMA.
          </p>
        )}
        {error && <MensajeError mensaje={error} />}
        {aviso && (
          <p role="status" style={{ margin: "0.6rem 0", fontSize: "0.85rem", color: colores.ok }}>
            {aviso}
          </p>
        )}
        <TablaInsumos
          insumos={insumos}
          seleccionado={seleccionado}
          onSeleccionar={(insumoId) => setSeleccionado(insumoId)}
        />
      </Panel>

      {revalidacion && (
        <ResumenRevalidacion
          resultado={revalidacion}
          onCerrar={() => setRevalidacion(null)}
        />
      )}

      {seleccionado && detalle && detalle.insumo.id === seleccionado && (
        <DetalleDeInsumo
          detalle={detalle}
          usuarios={usuarios}
          puedeGestionar={puedeGestionar}
          ocupado={ocupado}
          onCerrar={() => {
            setSeleccionado(null);
            setDetalle(null);
          }}
          onIngreso={(valor, motivo, referencia) =>
            void operar(async () => {
              const r = await api.registrarIngreso(seleccionado, actor?.id ?? "", valor, {
                motivo,
                referencia,
                operacion_id: nuevaOperacion(),
              });
              return `Ingreso registrado (${r.movimiento.id}): físico ${r.insumo.stock_fisico}.`;
            })
          }
          onAjuste={(diferencia, motivo, referencia, confirmado) =>
            void operar(async () => {
              const r = await api.registrarAjuste(
                seleccionado,
                actor?.id ?? "",
                diferencia,
                { motivo, referencia, operacion_id: nuevaOperacion() },
                confirmado,
              );
              return `Ajuste registrado (${r.movimiento.id}): físico ${r.insumo.stock_fisico}, disponible ${r.insumo.disponible}.`;
            })
          }
        />
      )}
    </div>
  );
}

function TablaInsumos({
  insumos,
  seleccionado,
  onSeleccionar,
}: {
  insumos: SituacionInsumo[];
  seleccionado: string | null;
  onSeleccionar: (insumoId: string) => void;
}) {
  if (insumos.length === 0) {
    return (
      <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
        No hay insumos que coincidan.
      </p>
    );
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", minWidth: 640, borderCollapse: "collapse", fontSize: "0.85rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: colores.suave }}>
            <th style={celda}>Código</th>
            <th style={celda}>Nombre</th>
            <th style={{ ...celda, textAlign: "right" }}>Físico</th>
            <th style={{ ...celda, textAlign: "right" }}>Reservado</th>
            <th style={{ ...celda, textAlign: "right" }}>Disponible</th>
            <th style={celda}>Reservas</th>
            <th style={celda}>Estado</th>
            <th style={celda} />
          </tr>
        </thead>
        <tbody>
          {insumos.map((insumo) => (
            <tr
              key={insumo.id}
              style={{
                borderTop: `1px solid ${colores.borde}`,
                background: insumo.id === seleccionado ? "#f2f6ff" : undefined,
              }}
            >
              <td style={{ ...celda, fontFamily: "ui-monospace, monospace" }}>{insumo.codigo}</td>
              <td style={celda}>{insumo.nombre}</td>
              <td style={{ ...celda, textAlign: "right" }}>{cantidad(insumo.stock_fisico, insumo)}</td>
              <td style={{ ...celda, textAlign: "right" }}>{insumo.reservado}</td>
              <td
                style={{
                  ...celda,
                  textAlign: "right",
                  fontWeight: 600,
                  color: insumo.disponible_negativo ? colores.error : colores.texto,
                }}
              >
                {insumo.disponible}
              </td>
              <td style={{ ...celda, whiteSpace: "nowrap" }}>
                {insumo.ordenes_con_reserva > 0
                  ? `${insumo.ordenes_con_reserva} OR · ${insumo.detalles_con_reserva} Det.`
                  : "—"}
              </td>
              <td style={celda}>
                {insumo.faltante ? (
                  <Etiqueta color={colores.error}>
                    {insumo.fisico_negativo ? "FALTANTE FÍSICO" : "DISPONIBLE NEGATIVO"}
                  </Etiqueta>
                ) : (
                  <Etiqueta color={colores.ok}>OK</Etiqueta>
                )}
              </td>
              <td style={celda}>
                <Boton variante="secundario" onClick={() => onSeleccionar(insumo.id)}>
                  Ver
                </Boton>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ResumenRevalidacion({
  resultado,
  onCerrar,
}: {
  resultado: ResultadoRevalidacion;
  onCerrar: () => void;
}) {
  const cifras: [string, number, string][] = [
    ["Evaluadas", resultado.evaluadas, colores.texto],
    ["Trabajables", resultado.trabajables, colores.ok],
    ["Siguen esperando", resultado.siguen_esperando, colores.alerta],
    ["Otra intervención", resultado.otra_intervencion, colores.acento],
    ["Errores", resultado.errores, colores.error],
  ];
  return (
    <Panel titulo="Revalidación de recursos">
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
        {fechaCorta(resultado.fecha)} · no reserva stock: la reserva sigue
        ocurriendo al iniciar cada Detalle.
      </p>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.6rem" }}>
        {cifras.map(([etiqueta, valor, color]) => (
          <Etiqueta key={etiqueta} color={color}>
            {etiqueta}: {valor}
          </Etiqueta>
        ))}
      </div>
      {resultado.ordenes.length === 0 ? (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          Ninguna Orden espera recursos.
        </p>
      ) : (
        <ul style={{ listStyle: "none", margin: 0, padding: 0, fontSize: "0.85rem" }}>
          {resultado.ordenes.map((orden) => (
            <li key={orden.orden_id} style={{ padding: "0.35rem 0", borderTop: `1px solid ${colores.borde}` }}>
              <strong>{orden.orden_id}</strong>{" "}
              <Etiqueta color={COLOR_RESULTADO[orden.resultado] ?? colores.suave}>
                {orden.resultado}
              </Etiqueta>{" "}
              <span style={{ color: colores.suave }}>{orden.detalle}</span>
            </li>
          ))}
        </ul>
      )}
      <div style={{ marginTop: "0.6rem" }}>
        <Boton variante="secundario" onClick={onCerrar}>
          Cerrar resumen
        </Boton>
      </div>
    </Panel>
  );
}

function DetalleDeInsumo({
  detalle,
  usuarios,
  puedeGestionar,
  ocupado,
  onCerrar,
  onIngreso,
  onAjuste,
}: {
  detalle: DetalleInsumo;
  usuarios: Usuario[];
  puedeGestionar: boolean;
  ocupado: boolean;
  onCerrar: () => void;
  onIngreso: (cantidad: string, motivo: string, referencia: string | null) => void;
  onAjuste: (
    diferencia: string,
    motivo: string,
    referencia: string | null,
    confirmado: boolean,
  ) => void;
}) {
  const { insumo } = detalle;
  return (
    <Panel titulo={`Insumo ${insumo.codigo} · ${insumo.nombre}`}>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        <Etiqueta color={colores.texto}>Físico {cantidad(insumo.stock_fisico, insumo)}</Etiqueta>
        <Etiqueta color={colores.acento}>Reservado {insumo.reservado}</Etiqueta>
        <Etiqueta color={insumo.disponible_negativo ? colores.error : colores.ok}>
          Disponible {insumo.disponible}
        </Etiqueta>
      </div>
      {insumo.faltante && (
        <p
          role="alert"
          style={{
            margin: "0 0 0.75rem",
            padding: "0.5rem 0.7rem",
            borderRadius: 6,
            border: `1px solid ${colores.error}`,
            background: "#fff5f5",
            fontSize: "0.85rem",
          }}
        >
          {insumo.fisico_negativo
            ? "El stock físico es negativo: se consumió más de lo que había. "
            : "El disponible es negativo: hay más reservado que físico. "}
          Las reservas se conservan; corregilo con un ingreso o un ajuste
          positivo.
        </p>
      )}

      <Subtitulo>Reservas vigentes</Subtitulo>
      {detalle.reservas.length === 0 ? (
        <Vacio>Sin reservas activas.</Vacio>
      ) : (
        <ul style={{ margin: "0 0 0.6rem", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {detalle.reservas.map((reserva) => (
            <li key={reserva.movimiento_id}>
              {reserva.orden_id} · {reserva.detalle_id}: {reserva.cantidad}{" "}
              <span style={{ color: colores.suave }}>(desde {fechaCorta(reserva.fecha)})</span>
            </li>
          ))}
        </ul>
      )}

      {detalle.faltantes.length > 0 && (
        <>
          <Subtitulo>Faltantes registrados</Subtitulo>
          <ul style={{ margin: "0 0 0.6rem", paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
            {detalle.faltantes.map((faltante) => (
              <li key={`${faltante.fecha}-${faltante.origen}`}>
                {fechaCorta(faltante.fecha)} ·{" "}
                {ETIQUETA_TIPO[faltante.origen] ?? faltante.origen}
                {faltante.orden_id ? ` · ${faltante.orden_id}` : ""}:{" "}
                <span style={{ color: colores.suave }}>{faltante.descripcion}</span>
              </li>
            ))}
          </ul>
        </>
      )}

      {puedeGestionar ? (
        <div
          style={{
            display: "grid",
            gap: "1rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 260px), 1fr))",
            margin: "0.4rem 0 0.8rem",
          }}
        >
          <FormularioIngreso insumo={insumo} ocupado={ocupado} onConfirmar={onIngreso} />
          <FormularioAjuste insumo={insumo} ocupado={ocupado} onConfirmar={onAjuste} />
        </div>
      ) : (
        <p style={{ margin: "0.4rem 0 0.8rem", fontSize: "0.8rem", color: colores.alerta }}>
          Ingresos y ajustes: requieren ADMINISTRADOR o COORDINADOR_RMA.
        </p>
      )}

      <Subtitulo>Movimientos</Subtitulo>
      <TablaMovimientos detalle={detalle} usuarios={usuarios} />
      <div style={{ marginTop: "0.6rem" }}>
        <Boton variante="secundario" onClick={onCerrar}>
          Cerrar detalle
        </Boton>
      </div>
    </Panel>
  );
}

function Subtitulo({ children }: { children: string }) {
  return <p style={{ margin: "0.6rem 0 0.3rem", fontWeight: 600, fontSize: "0.9rem" }}>{children}</p>;
}

function Vacio({ children }: { children: string }) {
  return <p style={{ margin: "0 0 0.6rem", fontSize: "0.85rem", color: colores.suave }}>{children}</p>;
}

function TablaMovimientos({
  detalle,
  usuarios,
}: {
  detalle: DetalleInsumo;
  usuarios: Usuario[];
}) {
  if (detalle.movimientos.length === 0) return <Vacio>Todavía no hay movimientos.</Vacio>;
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ width: "100%", minWidth: 900, borderCollapse: "collapse", fontSize: "0.82rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: colores.suave }}>
            <th style={celda}>Fecha</th>
            <th style={celda}>Tipo</th>
            <th style={{ ...celda, textAlign: "right" }}>Cantidad</th>
            <th style={celda}>OR / Detalle</th>
            <th style={celda}>Responsable</th>
            <th style={celda}>Físico</th>
            <th style={celda}>Motivo / observación</th>
          </tr>
        </thead>
        <tbody>
          {[...detalle.movimientos].reverse().map((movimiento) => (
            <tr key={movimiento.id} style={{ borderTop: `1px solid ${colores.borde}` }}>
              <td style={{ ...celda, whiteSpace: "nowrap" }}>{fechaCorta(movimiento.fecha)}</td>
              <td style={{ ...celda, whiteSpace: "nowrap" }}>
                <Etiqueta
                  color={
                    movimiento.origen === "INVENTARIO" ? colores.acento : colores.suave
                  }
                >
                  {ETIQUETA_TIPO[movimiento.tipo] ?? movimiento.tipo}
                </Etiqueta>
              </td>
              <td style={{ ...celda, textAlign: "right", fontWeight: 600 }}>{movimiento.cantidad}</td>
              <td style={{ ...celda, whiteSpace: "nowrap" }}>
                {movimiento.orden_id ? `${movimiento.orden_id} · ${movimiento.detalle_id}` : "—"}
              </td>
              <td style={{ ...celda, whiteSpace: "nowrap" }}>
                {movimiento.usuario_id
                  ? nombreDeUsuario(usuarios, movimiento.usuario_id)
                  : "Sistema (proceso)"}
              </td>
              <td style={{ ...celda, whiteSpace: "nowrap" }}>
                {movimiento.stock_anterior !== null
                  ? `${movimiento.stock_anterior} → ${movimiento.stock_resultante}`
                  : "—"}
              </td>
              <td style={{ ...celda, color: colores.suave }}>
                {movimiento.observacion ?? ""}
                {movimiento.referencia ? ` · ref. ${movimiento.referencia}` : ""}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FormularioIngreso({
  insumo,
  ocupado,
  onConfirmar,
}: {
  insumo: SituacionInsumo;
  ocupado: boolean;
  onConfirmar: (cantidad: string, motivo: string, referencia: string | null) => void;
}) {
  const [valor, setValor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [referencia, setReferencia] = useState("");
  const numero = Number(valor);
  const valido = valor.trim() !== "" && Number.isFinite(numero) && numero > 0;
  return (
    <div style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, padding: "0.7rem" }}>
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>Registrar ingreso</p>
      <Campo etiqueta="Cantidad (mayor que cero)">
        <input value={valor} inputMode="decimal" onChange={(e) => setValor(e.target.value)} style={estiloInput} />
      </Campo>
      <Campo etiqueta="Motivo u origen (obligatorio)">
        <input value={motivo} onChange={(e) => setMotivo(e.target.value)} style={estiloInput} placeholder="Compra, devolución de proveedor…" />
      </Campo>
      <Campo etiqueta="Referencia (opcional)">
        <input value={referencia} onChange={(e) => setReferencia(e.target.value)} style={estiloInput} placeholder="N.º de remito" />
      </Campo>
      <Boton
        disabled={ocupado || !valido || !motivo.trim()}
        onClick={() => {
          onConfirmar(valor.trim(), motivo.trim(), referencia.trim() || null);
          setValor("");
          setMotivo("");
          setReferencia("");
        }}
      >
        Registrar ingreso
      </Boton>
      <p style={{ margin: "0.4rem 0 0", fontSize: "0.75rem", color: colores.suave }}>
        Suma al físico de {insumo.codigo}; las reservas no cambian.
      </p>
    </div>
  );
}

function FormularioAjuste({
  insumo,
  ocupado,
  onConfirmar,
}: {
  insumo: SituacionInsumo;
  ocupado: boolean;
  onConfirmar: (
    diferencia: string,
    motivo: string,
    referencia: string | null,
    confirmado: boolean,
  ) => void;
}) {
  const [valor, setValor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [referencia, setReferencia] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  useEffect(() => setConfirmando(false), [valor, motivo, referencia]);

  const diferencia = Number(valor);
  const valido = valor.trim() !== "" && Number.isFinite(diferencia) && diferencia !== 0;
  const fisicoResultante = Number(insumo.stock_fisico) + diferencia;
  const disponibleResultante = Number(insumo.disponible) + diferencia;
  const riesgoso = diferencia < 0;
  const dejaFaltante = disponibleResultante < 0;

  const enviar = () => {
    onConfirmar(valor.trim(), motivo.trim(), referencia.trim() || null, riesgoso);
    setValor("");
    setMotivo("");
    setReferencia("");
  };

  return (
    <div style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, padding: "0.7rem" }}>
      <p style={{ margin: "0 0 0.5rem", fontWeight: 600 }}>Registrar ajuste</p>
      <Campo etiqueta="Diferencia en unidades (+ suma, − resta)">
        <input value={valor} inputMode="decimal" onChange={(e) => setValor(e.target.value)} style={estiloInput} placeholder="-3 o 2" />
      </Campo>
      <Campo etiqueta="Motivo (obligatorio)">
        <input value={motivo} onChange={(e) => setMotivo(e.target.value)} style={estiloInput} placeholder="Conteo, rotura, extravío…" />
      </Campo>
      <Campo etiqueta="Referencia (opcional)">
        <input value={referencia} onChange={(e) => setReferencia(e.target.value)} style={estiloInput} />
      </Campo>
      {valido && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: dejaFaltante ? colores.error : colores.suave }}>
          Físico {insumo.stock_fisico} → {fisicoResultante} · disponible{" "}
          {insumo.disponible} → {disponibleResultante}
          {dejaFaltante &&
            ` · deja el disponible negativo; las reservas (${insumo.reservado}) se conservan.`}
        </p>
      )}
      {!confirmando ? (
        <Boton
          variante={riesgoso ? "secundario" : "primario"}
          disabled={ocupado || !valido || !motivo.trim() || fisicoResultante < 0}
          onClick={() => (riesgoso ? setConfirmando(true) : enviar())}
        >
          Registrar ajuste
        </Boton>
      ) : (
        <Confirmacion
          texto={
            dejaFaltante
              ? `¿Confirmás restar ${-diferencia} de ${insumo.codigo}? El disponible queda en ${disponibleResultante}: las reservas no se tocan y el faltante queda registrado.`
              : `¿Confirmás restar ${-diferencia} de ${insumo.codigo}? El físico queda en ${fisicoResultante}.`
          }
          ocupado={ocupado}
          onVolver={() => setConfirmando(false)}
          onConfirmar={enviar}
        />
      )}
      {fisicoResultante < 0 && valido && (
        <p style={{ margin: "0.4rem 0 0", fontSize: "0.75rem", color: colores.error }}>
          Un ajuste no puede dejar el físico por debajo de cero.
        </p>
      )}
    </div>
  );
}
