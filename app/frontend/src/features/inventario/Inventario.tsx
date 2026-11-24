/**
 * Inventario operativo: existencias, movimientos, ingresos, ajustes y
 * revalidación de Órdenes que esperan recursos.
 *
 * Todo cálculo (reservado, disponible, faltantes, estado frente al stock
 * mínimo) y toda regla (rol, motivo, duplicados, confirmación) vive en el
 * backend; acá se muestra lo que devuelve y se piden confirmaciones antes
 * de enviar. El stock mínimo (DEC-AJ-11) no es un faltante: tiene su propio
 * filtro e indicador.
 *
 * DEC-AJ-14: cada insumo muestra su clasificación (categoría, fabricante,
 * variante) y su compatibilidad, y la lista se filtra por categoría (o «sin
 * clasificar»), fabricante y modelo compatible. Esos filtros se aplican
 * sobre la lista leída; la búsqueda por texto sigue en la API.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import * as api from "../../api/inventario";
import { ApiError } from "../../api/client";
import { OperacionesEstables } from "../../api/idempotencia";
import { VentanaConservada } from "../../components/Modal";
import { FiltrosClasificacion, useClasificacionInsumos } from "../../components/SelectorInsumo";
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
import { puede } from "../../lib/roles";
import {
  LotesDelInsumo,
  type SaldosDeInsumo,
  SelectorLote,
  useSaldosLotes,
} from "./lotes";
import {
  type ClasificacionInsumos,
  type FiltroInsumos,
  filtrarInsumos,
  filtraClasificacion,
  resumenClasificacion,
  textoCompatibilidad,
} from "./clasificacion";
import { NOMBRE_REPOSICION, tonoReposicion } from "./stockMinimo";

/** Provisorio, a validar con Rosario Tecno (el backend lo exige igual). */
const ROLES_GESTION: RolUsuario[] = ["ADMINISTRADOR", "COORDINADOR_RMA"];

/** Pausa al escribir antes de buscar: una lectura, no una por tecla. */
const ESPERA_BUSQUEDA_MS = 300;

/**
 * El último inventario completo leído: se ve enseguida al volver a la
 * pantalla y se reemplaza cuando llega la lectura nueva, que se hace siempre.
 */
let ultimoInventario: SituacionInsumo[] | null = null;

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

/**
 * E6 (B3): el `operacion_id` de un ingreso o ajuste es el mismo para los
 * mismos datos hasta que se registra. Así un reintento manda el mismo
 * cuerpo, conserva su clave de idempotencia y no se aplica dos veces.
 */
const operaciones = new OperacionesEstables();

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
  const [insumos, setInsumos] = useState<SituacionInsumo[] | null>(
    ultimoInventario,
  );
  const [buscar, setBuscar] = useState("");
  const [busqueda, setBusqueda] = useState("");
  const [soloFaltantes, setSoloFaltantes] = useState(false);
  const [bajoMinimo, setBajoMinimo] = useState(false);
  const [filtroClasificacion, setFiltroClasificacion] = useState<FiltroInsumos>({});
  const clasificacion = useClasificacionInsumos();
  const [seleccionado, setSeleccionado] = useState<string | null>(null);
  const [detalle, setDetalle] = useState<DetalleInsumo | null>(null);
  const [revalidacion, setRevalidacion] = useState<ResultadoRevalidacion | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const puedeGestionar = puede(actor, "STOCK_GESTIONAR", ROLES_GESTION);
  const visibles = useMemo(
    () => (insumos === null ? null : filtrarInsumos(insumos, filtroClasificacion, clasificacion)),
    [insumos, filtroClasificacion, clasificacion],
  );

  useEffect(() => {
    const espera = setTimeout(
      () => setBusqueda(buscar.trim()),
      ESPERA_BUSQUEDA_MS,
    );
    return () => clearTimeout(espera);
  }, [buscar]);

  // Solo la lectura más reciente se muestra: una vieja puede llegar después.
  const ultimaLectura = useRef(0);
  const recargar = useCallback(async () => {
    ultimaLectura.current += 1;
    const lectura = ultimaLectura.current;
    try {
      const [lista, elegido] = await Promise.all([
        api.listarInventario(busqueda || null, soloFaltantes, bajoMinimo),
        seleccionado ? api.obtenerInsumo(seleccionado) : null,
      ]);
      if (!busqueda && !soloFaltantes && !bajoMinimo) ultimoInventario = lista;
      if (lectura !== ultimaLectura.current) return;
      setInsumos(lista);
      if (elegido) setDetalle(elegido);
    } catch (fallo) {
      if (lectura === ultimaLectura.current) setError(mensajeDe(fallo));
    }
  }, [busqueda, soloFaltantes, bajoMinimo, seleccionado]);

  useEffect(() => {
    void recargar();
  }, [recargar]);

  /** Ejecuta una operación; `true` si se registró (cierra su ventana). */
  const operar = async (operacion: () => Promise<string>): Promise<boolean> => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    try {
      setAviso(await operacion());
      void recargar();
      return true;
    } catch (fallo) {
      setError(mensajeDe(fallo));
      void recargar();
      return false;
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
              Buscar por código, nombre o código del fabricante
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
          <label
            style={{ display: "flex", gap: "0.35rem", alignItems: "center", fontSize: "0.85rem" }}
            title="Disponible por debajo del stock mínimo, con o sin reposición solicitada"
          >
            <input
              type="checkbox"
              checked={bajoMinimo}
              onChange={(evento) => setBajoMinimo(evento.target.checked)}
            />
            Bajo mínimo
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
        <div style={{ marginBottom: "0.75rem" }}>
          <FiltrosClasificacion
            filtro={filtroClasificacion}
            onCambiar={setFiltroClasificacion}
            clasificacion={clasificacion}
            conTexto={false}
          />
          {filtraClasificacion(filtroClasificacion) && visibles !== null && insumos !== null && (
            <p style={{ margin: "0.3rem 0 0", fontSize: "0.75rem", color: colores.suave }}>
              {visibles.length} de {insumos.length} insumos con esa clasificación.
            </p>
          )}
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
        {visibles === null ? (
          !error && (
            <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
              Cargando el inventario…
            </p>
          )
        ) : (
          <TablaInsumos
            insumos={visibles}
            clasificacion={clasificacion}
            seleccionado={seleccionado}
            onSeleccionar={(insumoId) => setSeleccionado(insumoId)}
          />
        )}
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
          clasificacion={clasificacion}
          usuarios={usuarios}
          puedeGestionar={puedeGestionar}
          ocupado={ocupado}
          onCerrar={() => {
            setSeleccionado(null);
            setDetalle(null);
          }}
          error={error}
          onIngreso={(valor, motivo, referencia, lote) =>
            operar(async () => {
              const alcance = `ingreso:${seleccionado}`;
              const datos = { valor, motivo, referencia, lote };
              const r = await api.registrarIngreso(seleccionado, actor?.id ?? "", valor, {
                motivo,
                referencia,
                lote,
                operacion_id: operaciones.id(alcance, datos),
              });
              operaciones.olvidar(alcance, datos);
              return `Ingreso registrado (${r.movimiento.id}): físico ${r.insumo.stock_fisico}.`;
            })
          }
          onAjuste={(diferencia, motivo, referencia, confirmado, loteId) =>
            operar(async () => {
              // Sin `confirmado`: el ajuste que se confirma es el mismo.
              const alcance = `ajuste:${seleccionado}`;
              const datos = { diferencia, motivo, referencia, loteId };
              const r = await api.registrarAjuste(
                seleccionado,
                actor?.id ?? "",
                diferencia,
                {
                  motivo,
                  referencia,
                  lote_id: loteId,
                  operacion_id: operaciones.id(alcance, datos),
                },
                confirmado,
              );
              operaciones.olvidar(alcance, datos);
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
  clasificacion,
  seleccionado,
  onSeleccionar,
}: {
  insumos: SituacionInsumo[];
  clasificacion: ClasificacionInsumos;
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
      <table style={{ width: "100%", minWidth: 960, borderCollapse: "collapse", fontSize: "0.85rem" }}>
        <thead>
          <tr style={{ textAlign: "left", color: colores.suave }}>
            <th style={celda}>Código</th>
            <th style={celda}>Nombre</th>
            <th style={celda}>Clasificación</th>
            <th style={{ ...celda, textAlign: "right" }}>Físico</th>
            <th style={{ ...celda, textAlign: "right" }}>Reservado</th>
            <th style={{ ...celda, textAlign: "right" }}>Disponible</th>
            <th style={celda}>Reservas</th>
            <th style={celda}>Estado</th>
            <th style={{ ...celda, textAlign: "right" }}>Mínimo</th>
            <th style={celda}>Reposición</th>
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
              <td style={{ ...celda, fontSize: "0.8rem" }}>
                {resumenClasificacion(insumo, clasificacion)}
                <div style={{ color: colores.suave }} title={(insumo.modelos_compatibles ?? []).join(", ")}>
                  {textoCompatibilidad(insumo, clasificacion)}
                </div>
              </td>
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
              <td style={{ ...celda, textAlign: "right" }}>{insumo.stock_minimo ?? "—"}</td>
              <td style={celda}>
                <IndicadorReposicion insumo={insumo} />
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

/** DEC-AJ-11: «Bajo mínimo» (sin reposición pedida) y «reposición
 * solicitada» se distinguen por color; lo en camino se informa. */
function IndicadorReposicion({
  insumo,
  conEnCamino = true,
}: {
  insumo: SituacionInsumo;
  conEnCamino?: boolean;
}) {
  const tono = tonoReposicion(insumo.estado_reposicion);
  const enCamino =
    conEnCamino && Number(insumo.en_camino ?? "0") > 0 ? insumo.en_camino : null;
  if (tono === null) {
    return (
      <span style={{ color: colores.suave }}>
        {insumo.estado_reposicion === "SUFICIENTE" ? "Suficiente" : "—"}
        {enCamino ? ` · en camino ${enCamino}` : ""}
      </span>
    );
  }
  return (
    <span style={{ whiteSpace: "nowrap" }}>
      <Etiqueta color={tono === "alerta" ? colores.alerta : colores.acento}>
        {NOMBRE_REPOSICION[insumo.estado_reposicion ?? "SIN_MINIMO"].toUpperCase()}
      </Etiqueta>
      {enCamino && (
        <span style={{ marginLeft: "0.3rem", fontSize: "0.75rem", color: colores.suave }}>
          en camino {enCamino}
        </span>
      )}
    </span>
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
  clasificacion,
  usuarios,
  puedeGestionar,
  ocupado,
  onCerrar,
  onIngreso,
  onAjuste,
  error,
}: {
  detalle: DetalleInsumo;
  clasificacion: ClasificacionInsumos;
  usuarios: Usuario[];
  puedeGestionar: boolean;
  ocupado: boolean;
  onCerrar: () => void;
  onIngreso: (
    cantidad: string,
    motivo: string,
    referencia: string | null,
    lote: string | null,
  ) => Promise<boolean>;
  onAjuste: (
    diferencia: string,
    motivo: string,
    referencia: string | null,
    confirmado: boolean,
    loteId: string | null,
  ) => Promise<boolean>;
  /** El error de la última operación: se muestra en su ventana. */
  error: string | null;
}) {
  const { insumo } = detalle;
  const [ventana, setVentana] = useState<"ingreso" | "ajuste" | null>(null);
  // DEC-MI-10: se releen al cambiar el detalle (después de operar).
  const saldos = useSaldosLotes(insumo.id, detalle.movimientos.length);
  return (
    <Panel titulo={`Insumo ${insumo.codigo} · ${insumo.nombre}`}>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", color: colores.suave }}>
        {resumenClasificacion(insumo, clasificacion)}
        {insumo.codigo_fabricante ? ` · Cód. fabricante ${insumo.codigo_fabricante}` : ""} ·{" "}
        Compatible con: {textoCompatibilidad(insumo, clasificacion, 6)}
      </p>
      <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginBottom: "0.75rem" }}>
        <Etiqueta color={colores.texto}>Físico {cantidad(insumo.stock_fisico, insumo)}</Etiqueta>
        <Etiqueta color={colores.acento}>Reservado {insumo.reservado}</Etiqueta>
        <Etiqueta color={insumo.disponible_negativo ? colores.error : colores.ok}>
          Disponible {insumo.disponible}
        </Etiqueta>
        {insumo.stock_minimo != null && (
          <Etiqueta color={colores.texto}>Mínimo {insumo.stock_minimo}</Etiqueta>
        )}
        {Number(insumo.en_camino ?? "0") > 0 && (
          <Etiqueta color={colores.acento}>En camino {insumo.en_camino}</Etiqueta>
        )}
        {insumo.stock_minimo != null && (
          <IndicadorReposicion insumo={insumo} conEnCamino={false} />
        )}
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

      <LotesDelInsumo saldos={saldos} />

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
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", margin: "0.4rem 0 0.8rem" }}>
          <Boton onClick={() => setVentana("ingreso")} disabled={ocupado}>
            Registrar ingreso
          </Boton>
          <Boton variante="secundario" onClick={() => setVentana("ajuste")} disabled={ocupado}>
            Ajustar stock
          </Boton>
          <VentanaConservada
            abierta={ventana === "ingreso"}
            titulo={`Registrar ingreso · ${insumo.codigo}`}
            onCerrar={() => setVentana(null)}
          >
            <FormularioIngreso
              insumo={insumo}
              saldos={saldos}
              ocupado={ocupado}
              onConfirmar={async (...datos) => {
                if (await onIngreso(...datos)) setVentana(null);
              }}
            />
            {ventana === "ingreso" && error && <MensajeError mensaje={error} />}
          </VentanaConservada>
          <VentanaConservada
            abierta={ventana === "ajuste"}
            titulo={`Ajustar stock · ${insumo.codigo}`}
            onCerrar={() => setVentana(null)}
          >
            <FormularioAjuste
              insumo={insumo}
              saldos={saldos}
              ocupado={ocupado}
              onConfirmar={async (...datos) => {
                if (await onAjuste(...datos)) setVentana(null);
              }}
            />
            {ventana === "ajuste" && error && <MensajeError mensaje={error} />}
          </VentanaConservada>
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
  saldos,
  ocupado,
  onConfirmar,
}: {
  insumo: SituacionInsumo;
  saldos: SaldosDeInsumo | null;
  ocupado: boolean;
  onConfirmar: (
    cantidad: string,
    motivo: string,
    referencia: string | null,
    lote: string | null,
  ) => void;
}) {
  const [valor, setValor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [referencia, setReferencia] = useState("");
  const [lote, setLote] = useState("");
  const numero = Number(valor);
  const controlado = saldos !== null && saldos.control !== "SIN_LOTE";
  const serie = saldos?.control === "SERIE";
  const valido =
    valor.trim() !== "" &&
    Number.isFinite(numero) &&
    numero > 0 &&
    (!controlado || lote.trim() !== "") &&
    (!serie || numero === 1);
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
      {controlado && (
        <Campo
          etiqueta={
            serie
              ? "Número de serie (obligatorio; de a una unidad)"
              : "Número de lote (obligatorio)"
          }
        >
          <input value={lote} onChange={(e) => setLote(e.target.value)} style={estiloInput} />
        </Campo>
      )}
      <Boton
        disabled={ocupado || !valido || !motivo.trim()}
        onClick={() => {
          onConfirmar(
            valor.trim(),
            motivo.trim(),
            referencia.trim() || null,
            lote.trim() || null,
          );
          setValor("");
          setMotivo("");
          setReferencia("");
          setLote("");
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
  saldos,
  ocupado,
  onConfirmar,
}: {
  insumo: SituacionInsumo;
  saldos: SaldosDeInsumo | null;
  ocupado: boolean;
  onConfirmar: (
    diferencia: string,
    motivo: string,
    referencia: string | null,
    confirmado: boolean,
    loteId: string | null,
  ) => void;
}) {
  const [valor, setValor] = useState("");
  const [motivo, setMotivo] = useState("");
  const [referencia, setReferencia] = useState("");
  const [loteId, setLoteId] = useState("");
  const [confirmando, setConfirmando] = useState(false);
  useEffect(() => setConfirmando(false), [valor, motivo, referencia]);

  const diferencia = Number(valor);
  const valido = valor.trim() !== "" && Number.isFinite(diferencia) && diferencia !== 0;
  const fisicoResultante = Number(insumo.stock_fisico) + diferencia;
  const disponibleResultante = Number(insumo.disponible) + diferencia;
  const riesgoso = diferencia < 0;
  const dejaFaltante = disponibleResultante < 0;

  const enviar = () => {
    onConfirmar(
      valor.trim(),
      motivo.trim(),
      referencia.trim() || null,
      riesgoso,
      loteId || null,
    );
    setValor("");
    setMotivo("");
    setReferencia("");
    setLoteId("");
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
      {saldos && saldos.control !== "SIN_LOTE" && (
        <SelectorLote
          saldos={saldos}
          valor={loteId}
          onCambio={setLoteId}
          etiqueta="Lote ajustado"
        />
      )}
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
