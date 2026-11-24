/**
 * Compras (DEC-MI-09): Solicitud -> Orden de compra -> Recepciones ->
 * Ingreso de stock.
 *
 * - Nada se compra solo: una sugerencia por faltante se convierte en
 *   solicitud cuando alguien la confirma.
 * - Las órdenes de compra no se aprueban: se crean y se confirman (quién y
 *   cuándo queda registrado).
 * - Las recepciones son parciales o totales, nunca más de lo pendiente; el
 *   costo real lo registra quien recibe; con lote o números de serie si el
 *   insumo lo exige. Cada línea genera su ingreso de stock.
 * - El último costo es la referencia; cada recepción conserva su costo.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import * as api from "../../api/compras";
import type {
  OrdenCompra,
  Proveedor,
  SolicitudCompra,
  SugerenciaCompra,
} from "../../api/compras";
import { listarInventario } from "../../api/inventario";
import { SelectorInsumo, useClasificacionInsumos } from "../../components/SelectorInsumo";
import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import {
  type AccionesCompras,
  accionesDeCompras,
  puedeCancelarOrden,
  costoDistinto,
  erroresDeRecepcion,
  lineasIniciales,
  lineasParaRecibir,
  ultimosCostos,
} from "./recepcion";
import type { LineaEditable } from "./recepcion";
import type { SituacionInsumo, Usuario } from "../../types/api";
import {
  NOMBRE_ORIGEN,
  causaSugerencia,
  solicitudDeSugerencia,
} from "../inventario/stockMinimo";
import { useSaldosLotes } from "../inventario/lotes";
import { type ClasificacionInsumos, etiquetaInsumo } from "../inventario/clasificacion";

const mensajeDe = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

type Pestana = "solicitudes" | "ordenes" | "costos";

export function ComprasPanel({ actor }: { actor: Usuario | null }) {
  const [disponible, setDisponible] = useState<boolean | null>(null);
  const [pestana, setPestana] = useState<Pestana>("solicitudes");
  const [insumos, setInsumos] = useState<SituacionInsumo[]>([]);
  // DEC-AJ-14: la clasificación para nombrar, buscar y filtrar insumos.
  const clasificacion = useClasificacionInsumos();
  const [proveedores, setProveedores] = useState<Proveedor[]>([]);
  const [solicitudes, setSolicitudes] = useState<SolicitudCompra[]>([]);
  const [sugerencias, setSugerencias] = useState<SugerenciaCompra[]>([]);
  const [ordenes, setOrdenes] = useState<OrdenCompra[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  // CFG-03 (D5, DF-5): cada acción de Compras con su permiso.
  const gestiona = accionesDeCompras(actor);

  const cargar = useCallback(() => {
    api
      .estado()
      .then(({ disponible: ok }) => {
        setDisponible(ok);
        if (!ok) return;
        return Promise.all([
          listarInventario(null, false)
            .then(setInsumos)
            .catch(() => setInsumos([])),
          api.proveedores().then(setProveedores),
          api.solicitudes().then(setSolicitudes),
          api.sugerencias().then(setSugerencias),
          api.ordenes().then(setOrdenes),
        ]);
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, []);
  useEffect(cargar, [cargar]);

  const ejecutar = (accion: () => Promise<unknown>, exito: string) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    return accion()
      .then(() => {
        setAviso(exito);
        cargar();
        return true;
      })
      .catch((causa: unknown) => {
        setError(mensajeDe(causa));
        return false;
      })
      .finally(() => setOcupado(false));
  };

  if (disponible === null) {
    return error ? <p role="alert">{error}</p> : <p>Cargando compras…</p>;
  }
  if (!disponible) {
    return (
      <p style={{ color: colores.suave }}>
        Compras funciona sobre la base PostgreSQL; en este entorno de
        demostración no está disponible.
      </p>
    );
  }

  const nombreInsumo = (id: string) => {
    const insumo = insumos.find((i) => i.id === id);
    return insumo ? etiquetaInsumo(insumo, clasificacion) : id;
  };
  const nombreProveedor = (id: string) =>
    proveedores.find((p) => p.id === id)?.nombre ?? id;
  const idActor = actor?.id ?? "";

  return (
    <div>
      <nav role="tablist" style={{ display: "flex", gap: "0.4rem", marginBottom: "0.8rem" }}>
        {(
          [
            ["solicitudes", "Solicitudes"],
            ["ordenes", "Órdenes de compra"],
            ["costos", "Costos"],
          ] as const
        ).map(([valor, texto]) => (
          <button
            key={valor}
            type="button"
            role="tab"
            aria-selected={pestana === valor}
            onClick={() => setPestana(valor)}
            style={{
              padding: "0.35rem 0.8rem",
              borderRadius: 6,
              border: `1px solid ${colores.borde}`,
              background: pestana === valor ? colores.acento : "transparent",
              color: pestana === valor ? "#fff" : colores.texto,
              cursor: "pointer",
            }}
          >
            {texto}
          </button>
        ))}
      </nav>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {aviso && (
        <p role="status" style={{ color: colores.ok, fontSize: "0.85rem" }}>
          {aviso}
        </p>
      )}
      {pestana === "solicitudes" && (
        <Solicitudes
          solicitudes={solicitudes}
          sugerencias={sugerencias}
          insumos={insumos}
          clasificacion={clasificacion}
          nombreInsumo={nombreInsumo}
          gestiona={gestiona}
          ocupado={ocupado}
          onCrear={(datos) =>
            ejecutar(
              () => api.crearSolicitud({ usuario_id: idActor, ...datos }),
              "Solicitud registrada.",
            )
          }
          onDescartar={(id, motivo) =>
            ejecutar(
              () => api.descartarSolicitud(id, idActor, motivo),
              `Solicitud ${id} descartada.`,
            )
          }
        />
      )}
      {pestana === "ordenes" && (
        <Ordenes
          ordenes={ordenes}
          proveedores={proveedores}
          solicitudes={solicitudes}
          insumos={insumos}
          clasificacion={clasificacion}
          nombreInsumo={nombreInsumo}
          nombreProveedor={nombreProveedor}
          gestiona={gestiona}
          ocupado={ocupado}
          idActor={idActor}
          ejecutar={ejecutar}
        />
      )}
      {pestana === "costos" && (
        <Costos
          insumos={insumos}
          clasificacion={clasificacion}
          nombreInsumo={nombreInsumo}
          nombreProveedor={nombreProveedor}
        />
      )}
    </div>
  );
}

// --- Solicitudes ---------------------------------------------------------------

function Solicitudes({
  solicitudes,
  sugerencias,
  insumos,
  clasificacion,
  nombreInsumo,
  gestiona,
  ocupado,
  onCrear,
  onDescartar,
}: {
  solicitudes: SolicitudCompra[];
  sugerencias: SugerenciaCompra[];
  insumos: SituacionInsumo[];
  clasificacion: ClasificacionInsumos;
  nombreInsumo: (id: string) => string;
  gestiona: AccionesCompras;
  ocupado: boolean;
  onCrear: (datos: {
    insumo_id: string;
    cantidad: string;
    motivo: string;
    origen?: "MANUAL" | "FALTANTE" | "STOCK_MINIMO";
    ordenes?: string[];
  }) => Promise<boolean>;
  onDescartar: (id: string, motivo: string) => Promise<boolean>;
}) {
  const [insumo, setInsumo] = useState("");
  const [cantidad, setCantidad] = useState("");
  const [motivo, setMotivo] = useState("");
  const [descartando, setDescartando] = useState<string | null>(null);
  const [motivoDescarte, setMotivoDescarte] = useState("");

  return (
    <section>
      <h3 style={{ margin: "0 0 0.4rem" }}>Sugerencias de reposición</h3>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        Lo que piden las Órdenes que esperan recursos y, si el insumo tiene
        stock mínimo, lo necesario para alcanzarlo; menos lo disponible y lo
        que ya está en camino (solicitudes pendientes y órdenes de compra
        abiertas). Nada se compra solo: confirmá cada solicitud.
      </p>
      {sugerencias.length === 0 ? (
        <p style={{ fontSize: "0.85rem", color: colores.suave }}>Nada para reponer.</p>
      ) : (
        <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {sugerencias.map((s) => (
            <li key={s.insumo_id} style={{ marginBottom: "0.3rem" }}>
              {nombreInsumo(s.insumo_id)}: sugerido {s.sugerido} · {causaSugerencia(s)} (demanda{" "}
              {s.demanda_bloqueada}, disponible {s.disponible}
              {s.stock_minimo != null ? `, mínimo ${s.stock_minimo}` : ""}, en camino {s.en_camino})
              {s.ordenes.length > 0 ? ` · ${s.ordenes.join(", ")}` : ""}{" "}
              {gestiona.solicitar && (
                <Boton
                  variante="secundario"
                  disabled={ocupado}
                  onClick={() => void onCrear(solicitudDeSugerencia(s))}
                >
                  Crear solicitud
                </Boton>
              )}
            </li>
          ))}
        </ul>
      )}

      <h3 style={{ margin: "0.8rem 0 0.4rem" }}>Solicitudes</h3>
      {solicitudes.length === 0 ? (
        <p style={{ fontSize: "0.85rem", color: colores.suave }}>Sin solicitudes.</p>
      ) : (
        <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {solicitudes.map((s) => (
            <li key={s.id} style={{ marginBottom: "0.3rem" }}>
              <strong>{s.id}</strong> · {nombreInsumo(s.insumo_id)} · {s.cantidad} ·{" "}
              {NOMBRE_ORIGEN[s.origen] ?? s.origen} · {s.estado}
              {s.orden_compra_id ? ` (${s.orden_compra_id})` : ""} · {s.motivo}
              {s.motivo_descarte ? ` · descartada: ${s.motivo_descarte}` : ""}
              <span style={{ color: colores.suave }}> · {fechaCorta(s.fecha)}</span>{" "}
              {gestiona.solicitar && s.estado === "PENDIENTE" && descartando !== s.id && (
                <Boton variante="secundario" disabled={ocupado} onClick={() => setDescartando(s.id)}>
                  Descartar
                </Boton>
              )}
              {descartando === s.id && (
                <span style={{ display: "inline-flex", gap: "0.3rem" }}>
                  <input
                    aria-label="Motivo del descarte"
                    value={motivoDescarte}
                    onChange={(e) => setMotivoDescarte(e.target.value)}
                    style={{ ...estiloInput, width: 220 }}
                  />
                  <Boton
                    disabled={ocupado || !motivoDescarte.trim()}
                    onClick={() =>
                      void onDescartar(s.id, motivoDescarte.trim()).then((ok) => {
                        if (ok) {
                          setDescartando(null);
                          setMotivoDescarte("");
                        }
                      })
                    }
                  >
                    Confirmar
                  </Boton>
                </span>
              )}
            </li>
          ))}
        </ul>
      )}

      {gestiona.solicitar && (
        <div style={{ maxWidth: 420, marginTop: "0.6rem" }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>Nueva solicitud</h4>
          <SelectorInsumo
            insumos={insumos}
            clasificacion={clasificacion}
            valor={insumo}
            onCambiar={setInsumo}
            soloVigentes
          />
          <Campo etiqueta="Cantidad">
            <input value={cantidad} inputMode="decimal" onChange={(e) => setCantidad(e.target.value)} style={estiloInput} />
          </Campo>
          <Campo etiqueta="Motivo">
            <input value={motivo} onChange={(e) => setMotivo(e.target.value)} style={estiloInput} />
          </Campo>
          <Boton
            disabled={ocupado || !insumo || !(Number(cantidad) > 0) || !motivo.trim()}
            onClick={() =>
              void onCrear({ insumo_id: insumo, cantidad: cantidad.trim(), motivo: motivo.trim() }).then(
                (ok) => {
                  if (ok) {
                    setCantidad("");
                    setMotivo("");
                  }
                },
              )
            }
          >
            Registrar solicitud
          </Boton>
        </div>
      )}
    </section>
  );
}

// --- Órdenes de compra -----------------------------------------------------------

function Ordenes({
  ordenes,
  proveedores,
  solicitudes,
  insumos,
  clasificacion,
  nombreInsumo,
  nombreProveedor,
  gestiona,
  ocupado,
  idActor,
  ejecutar,
}: {
  ordenes: OrdenCompra[];
  proveedores: Proveedor[];
  solicitudes: SolicitudCompra[];
  insumos: SituacionInsumo[];
  clasificacion: ClasificacionInsumos;
  nombreInsumo: (id: string) => string;
  nombreProveedor: (id: string) => string;
  gestiona: AccionesCompras;
  ocupado: boolean;
  idActor: string;
  ejecutar: (accion: () => Promise<unknown>, exito: string) => Promise<boolean>;
}) {
  const [elegida, setElegida] = useState<string | null>(null);
  const [nueva, setNueva] = useState(false);
  const orden = ordenes.find((o) => o.id === elegida) ?? null;
  return (
    <section>
      {gestiona.crearOc && !nueva && (
        <Boton disabled={ocupado} onClick={() => setNueva(true)}>
          Nueva orden de compra
        </Boton>
      )}
      {nueva && (
        <NuevaOrden
          proveedores={proveedores.filter((p) => p.activo)}
          solicitudes={solicitudes.filter((s) => s.estado === "PENDIENTE")}
          insumos={insumos.filter((i) => i.activo)}
          clasificacion={clasificacion}
          nombreInsumo={nombreInsumo}
          ocupado={ocupado}
          onCancelar={() => setNueva(false)}
          onCrear={(datos) =>
            ejecutar(
              () => api.crearOrden({ usuario_id: idActor, ...datos }),
              "Orden de compra creada (borrador): confirmala para recibir.",
            ).then((ok) => {
              if (ok) setNueva(false);
            })
          }
        />
      )}
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem", marginTop: "0.6rem" }}>
        {ordenes.map((o) => (
          <li key={o.id} style={{ marginBottom: "0.3rem" }}>
            <button
              type="button"
              onClick={() => setElegida(o.id === elegida ? null : o.id)}
              style={{ background: "none", border: "none", color: colores.acento, cursor: "pointer", padding: 0 }}
            >
              {o.id}
            </button>{" "}
            · {nombreProveedor(o.proveedor_id)} · {o.estado} · creada por {o.creada_por}
            {o.confirmada_por ? ` · confirmada por ${o.confirmada_por}` : ""}
          </li>
        ))}
        {ordenes.length === 0 && <li style={{ color: colores.suave }}>Sin órdenes de compra.</li>}
      </ul>
      {orden && (
        <DetalleOrdenCompra
          orden={orden}
          nombreInsumo={nombreInsumo}
          nombreProveedor={nombreProveedor}
          gestiona={gestiona}
          ocupado={ocupado}
          idActor={idActor}
          ejecutar={ejecutar}
        />
      )}
    </section>
  );
}

function NuevaOrden({
  proveedores,
  solicitudes,
  insumos,
  clasificacion,
  nombreInsumo,
  ocupado,
  onCancelar,
  onCrear,
}: {
  proveedores: Proveedor[];
  solicitudes: SolicitudCompra[];
  insumos: SituacionInsumo[];
  clasificacion: ClasificacionInsumos;
  nombreInsumo: (id: string) => string;
  ocupado: boolean;
  onCancelar: () => void;
  onCrear: (datos: {
    proveedor_id: string;
    items: api.ItemOrdenCompra[];
    solicitudes: string[];
    observaciones: string | null;
  }) => void;
}) {
  const [proveedor, setProveedor] = useState("");
  const [items, setItems] = useState<api.ItemOrdenCompra[]>([]);
  const [incluidas, setIncluidas] = useState<string[]>([]);
  const [observaciones, setObservaciones] = useState("");
  const [ultimos, setUltimos] = useState<Record<string, string>>({});
  useEffect(() => {
    api
      .costos()
      .then((lista) => setUltimos(ultimosCostos(lista)))
      .catch(() => setUltimos({}));
  }, []);

  const agregar = (insumoId: string, cantidad = "1") =>
    setItems((actual) =>
      actual.some((i) => i.insumo_id === insumoId)
        ? actual
        : [...actual, { insumo_id: insumoId, cantidad, costo_unitario: ultimos[insumoId] ?? "0" }],
    );
  const valido =
    proveedor !== "" &&
    items.length > 0 &&
    items.every((i) => Number(i.cantidad) > 0 && Number(i.costo_unitario) >= 0);

  return (
    <div style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, padding: "0.7rem", maxWidth: 620 }}>
      <h4 style={{ margin: "0 0 0.4rem" }}>Nueva orden de compra</h4>
      <Campo etiqueta="Proveedor">
        <select value={proveedor} onChange={(e) => setProveedor(e.target.value)} style={estiloInput}>
          <option value="">Elegir…</option>
          {proveedores.map((p) => (
            <option key={p.id} value={p.id}>
              {p.nombre}
            </option>
          ))}
        </select>
      </Campo>
      {proveedores.length === 0 && (
        <p style={{ fontSize: "0.8rem", color: colores.alerta }}>
          No hay proveedores vigentes: los da de alta Administración en Configuración.
        </p>
      )}
      {solicitudes.length > 0 && (
        <fieldset style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, fontSize: "0.85rem" }}>
          <legend>Incluir solicitudes pendientes</legend>
          {solicitudes.map((s) => (
            <label key={s.id} style={{ display: "flex", gap: "0.4rem" }}>
              <input
                type="checkbox"
                checked={incluidas.includes(s.id)}
                onChange={(e) => {
                  if (e.target.checked) {
                    setIncluidas([...incluidas, s.id]);
                    agregar(s.insumo_id, s.cantidad);
                  } else {
                    setIncluidas(incluidas.filter((id) => id !== s.id));
                  }
                }}
              />
              {s.id} · {nombreInsumo(s.insumo_id)} · {s.cantidad}
            </label>
          ))}
        </fieldset>
      )}
      <SelectorInsumo
        etiqueta="Agregar insumo (una línea por insumo)"
        insumos={insumos}
        clasificacion={clasificacion}
        valor=""
        onCambiar={(id) => id && agregar(id)}
      />
      {items.map((item, indice) => (
        <div key={item.insumo_id} style={{ display: "flex", gap: "0.4rem", alignItems: "end" }}>
          <span style={{ flex: 2, fontSize: "0.85rem" }}>{nombreInsumo(item.insumo_id)}</span>
          <Campo etiqueta="Cantidad">
            <input
              value={item.cantidad}
              inputMode="decimal"
              onChange={(e) =>
                setItems(items.map((it, i) => (i === indice ? { ...it, cantidad: e.target.value } : it)))
              }
              style={estiloInput}
            />
          </Campo>
          <Campo
            etiqueta={`Costo unitario${ultimos[item.insumo_id] ? ` (último ${ultimos[item.insumo_id]})` : ""}`}
          >
            <input
              value={item.costo_unitario}
              inputMode="decimal"
              onChange={(e) =>
                setItems(items.map((it, i) => (i === indice ? { ...it, costo_unitario: e.target.value } : it)))
              }
              style={estiloInput}
            />
          </Campo>
          <Boton variante="secundario" onClick={() => setItems(items.filter((_, i) => i !== indice))}>
            Quitar
          </Boton>
        </div>
      ))}
      <Campo etiqueta="Observaciones (opcional)">
        <input value={observaciones} onChange={(e) => setObservaciones(e.target.value)} style={estiloInput} />
      </Campo>
      <div style={{ display: "flex", gap: "0.4rem" }}>
        <Boton
          disabled={ocupado || !valido}
          onClick={() =>
            onCrear({
              proveedor_id: proveedor,
              items,
              solicitudes: incluidas,
              observaciones: observaciones.trim() || null,
            })
          }
        >
          Crear orden de compra
        </Boton>
        <Boton variante="secundario" disabled={ocupado} onClick={onCancelar}>
          Cancelar
        </Boton>
      </div>
    </div>
  );
}

function DetalleOrdenCompra({
  orden,
  nombreInsumo,
  nombreProveedor,
  gestiona,
  ocupado,
  idActor,
  ejecutar,
}: {
  orden: OrdenCompra;
  nombreInsumo: (id: string) => string;
  nombreProveedor: (id: string) => string;
  gestiona: AccionesCompras;
  ocupado: boolean;
  idActor: string;
  ejecutar: (accion: () => Promise<unknown>, exito: string) => Promise<boolean>;
}) {
  const [motivoCancelacion, setMotivoCancelacion] = useState("");
  const recibible = orden.estado === "CONFIRMADA" || orden.estado === "PARCIAL";
  const cancelable = puedeCancelarOrden(gestiona, orden, idActor);
  return (
    <div style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, padding: "0.7rem", marginTop: "0.6rem" }}>
      <h4 style={{ margin: "0 0 0.4rem" }}>
        {orden.id} · {nombreProveedor(orden.proveedor_id)} · {orden.estado}
      </h4>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        Creada por {orden.creada_por} el {fechaCorta(orden.creada_en)}
        {orden.confirmada_en ? ` · confirmada por ${orden.confirmada_por} el ${fechaCorta(orden.confirmada_en)}` : ""}
        {orden.motivo_cancelacion ? ` · cancelada: ${orden.motivo_cancelacion}` : ""}
        {orden.solicitudes.length > 0 ? ` · solicitudes ${orden.solicitudes.join(", ")}` : ""}
      </p>
      <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", marginBottom: "0.5rem" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Insumo</th>
            <th style={{ paddingRight: "0.8rem" }}>Costo acordado</th>
            <th style={{ paddingRight: "0.8rem" }}>Pedido</th>
            <th style={{ paddingRight: "0.8rem" }}>Recibido</th>
            <th>Pendiente</th>
          </tr>
        </thead>
        <tbody>
          {orden.renglones.map((r) => (
            <tr key={r.insumo_id}>
              <td style={{ paddingRight: "0.8rem" }}>{nombreInsumo(r.insumo_id)}</td>
              <td style={{ textAlign: "right", paddingRight: "0.8rem" }}>
                {orden.items.find((i) => i.insumo_id === r.insumo_id)?.costo_unitario}
              </td>
              <td style={{ textAlign: "right", paddingRight: "0.8rem" }}>{r.pedido}</td>
              <td style={{ textAlign: "right", paddingRight: "0.8rem" }}>{r.recibido}</td>
              <td style={{ textAlign: "right" }}>{r.pendiente}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {orden.recepciones.length > 0 && (
        <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {orden.recepciones.map((r) => (
            <li key={r.id}>
              {r.id} · {fechaCorta(r.fecha)} · {r.usuario_id}
              {r.remito ? ` · remito ${r.remito}` : ""}:{" "}
              {r.lineas
                .map(
                  (l) =>
                    `${nombreInsumo(l.insumo_id)} ${l.cantidad} a ${l.costo_unitario}` +
                    (l.lote ? ` lote ${l.lote}` : "") +
                    (l.series.length ? ` series ${l.series.join(", ")}` : "") +
                    (l.diferencia ? ` (${l.diferencia})` : ""),
                )
                .join("; ")}
            </li>
          ))}
        </ul>
      )}
      {gestiona.confirmar && orden.estado === "BORRADOR" && (
        <Boton
          disabled={ocupado}
          onClick={() => void ejecutar(() => api.confirmarOrden(orden.id, idActor), `${orden.id} confirmada.`)}
        >
          Confirmar la orden de compra
        </Boton>
      )}
      {gestiona.recibir && recibible && (
        <FormularioRecepcion
          orden={orden}
          nombreInsumo={nombreInsumo}
          ocupado={ocupado}
          onRecibir={(datos) =>
            ejecutar(
              () => api.recibir(orden.id, { usuario_id: idActor, ...datos }),
              `Recepción registrada en ${orden.id}: el stock ya se actualizó.`,
            )
          }
        />
      )}
      {cancelable && (
        <div style={{ display: "flex", gap: "0.4rem", alignItems: "end", marginTop: "0.6rem", maxWidth: 520 }}>
          <Campo etiqueta="Motivo para cancelar (sin recepciones)">
            <input value={motivoCancelacion} onChange={(e) => setMotivoCancelacion(e.target.value)} style={estiloInput} />
          </Campo>
          <Boton
            variante="secundario"
            disabled={ocupado || !motivoCancelacion.trim()}
            onClick={() =>
              void ejecutar(
                () => api.cancelarOrden(orden.id, idActor, motivoCancelacion.trim()),
                `${orden.id} cancelada.`,
              )
            }
          >
            Cancelar la orden
          </Boton>
        </div>
      )}
    </div>
  );
}

function FormularioRecepcion({
  orden,
  nombreInsumo,
  ocupado,
  onRecibir,
}: {
  orden: OrdenCompra;
  nombreInsumo: (id: string) => string;
  ocupado: boolean;
  onRecibir: (datos: {
    lineas: api.LineaRecepcion[];
    remito: string | null;
    observaciones: string | null;
  }) => Promise<boolean>;
}) {
  const pendientes = orden.renglones.filter((r) => Number(r.pendiente) > 0);
  const inicial = useMemo(
    () => lineasIniciales(orden),
    [orden.id, orden.recepciones.length],
  );
  const [lineas, setLineas] = useState<LineaEditable[]>(inicial);
  const [remito, setRemito] = useState("");
  const [observaciones, setObservaciones] = useState("");
  useEffect(() => setLineas(inicial), [inicial]);

  const errores = erroresDeRecepcion(orden, lineas);
  const hayCarga = lineas.some((l) => l.cantidad.trim() !== "");
  const cambiar = (indice: number, cambio: Partial<LineaEditable>) =>
    setLineas(lineas.map((l, i) => (i === indice ? { ...l, ...cambio } : l)));

  return (
    <div style={{ marginTop: "0.6rem" }}>
      <h4 style={{ margin: "0 0 0.3rem" }}>Registrar recepción</h4>
      {lineas.map((linea, indice) => (
        <LineaRecepcionForm
          key={linea.insumo_id}
          linea={linea}
          pendiente={pendientes[indice]?.pendiente ?? "0"}
          costoDistinto={costoDistinto(orden, linea)}
          nombre={nombreInsumo(linea.insumo_id)}
          onCambio={(cambio) => cambiar(indice, cambio)}
        />
      ))}
      <div style={{ display: "flex", gap: "0.4rem", maxWidth: 520 }}>
        <Campo etiqueta="Remito (opcional)">
          <input value={remito} onChange={(e) => setRemito(e.target.value)} style={estiloInput} />
        </Campo>
        <Campo etiqueta="Observaciones (opcional)">
          <input value={observaciones} onChange={(e) => setObservaciones(e.target.value)} style={estiloInput} />
        </Campo>
      </div>
      {hayCarga && errores.length > 0 && (
        <ul role="alert" style={{ color: colores.error, fontSize: "0.8rem", margin: "0.3rem 0" }}>
          {errores.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      <Boton
        disabled={ocupado || errores.length > 0}
        onClick={() =>
          void onRecibir({
            lineas: lineasParaRecibir(lineas),
            remito: remito.trim() || null,
            observaciones: observaciones.trim() || null,
          }).then((ok) => {
            if (ok) {
              setRemito("");
              setObservaciones("");
            }
          })
        }
      >
        Registrar recepción
      </Boton>
    </div>
  );
}

function LineaRecepcionForm({
  linea,
  pendiente,
  costoDistinto: distinto,
  nombre,
  onCambio,
}: {
  linea: LineaEditable;
  pendiente: string;
  costoDistinto: boolean;
  nombre: string;
  onCambio: (cambio: Partial<LineaEditable>) => void;
}) {
  const saldos = useSaldosLotes(linea.insumo_id);
  const control = saldos?.control ?? "SIN_LOTE";
  return (
    <fieldset style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, marginBottom: "0.4rem" }}>
      <legend style={{ fontSize: "0.85rem" }}>
        {nombre} · pendiente {pendiente}
      </legend>
      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        <Campo etiqueta="Cantidad recibida">
          <input value={linea.cantidad} inputMode="decimal" onChange={(e) => onCambio({ cantidad: e.target.value })} style={estiloInput} />
        </Campo>
        <Campo etiqueta="Costo unitario real">
          <input value={linea.costo} inputMode="decimal" onChange={(e) => onCambio({ costo: e.target.value })} style={estiloInput} />
        </Campo>
        {control === "LOTE" && (
          <Campo etiqueta="Lote (obligatorio)">
            <input value={linea.lote} onChange={(e) => onCambio({ lote: e.target.value })} style={estiloInput} />
          </Campo>
        )}
        {control === "SERIE" && (
          <Campo etiqueta="Números de serie (uno por unidad, separados por coma)">
            <input value={linea.series} onChange={(e) => onCambio({ series: e.target.value })} style={estiloInput} />
          </Campo>
        )}
        <Campo etiqueta={distinto ? "Diferencia con el costo acordado (opcional)" : "Diferencia (opcional)"}>
          <input value={linea.diferencia} onChange={(e) => onCambio({ diferencia: e.target.value })} style={estiloInput} />
        </Campo>
      </div>
    </fieldset>
  );
}

// --- Costos ------------------------------------------------------------------------

function Costos({
  insumos,
  clasificacion,
  nombreInsumo,
  nombreProveedor,
}: {
  insumos: SituacionInsumo[];
  clasificacion: ClasificacionInsumos;
  nombreInsumo: (id: string) => string;
  nombreProveedor: (id: string) => string;
}) {
  const [insumo, setInsumo] = useState("");
  const [lista, setLista] = useState<api.CostoCompra[]>([]);
  useEffect(() => {
    api
      .costos(insumo || undefined)
      .then(setLista)
      .catch(() => setLista([]));
  }, [insumo]);
  return (
    <section>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        El último costo de compra es la referencia operativa; cada recepción
        conserva su costo. Los precios de los insumos los configura
        Administración.
      </p>
      <div style={{ maxWidth: 720 }}>
        <SelectorInsumo
          insumos={insumos}
          clasificacion={clasificacion}
          valor={insumo}
          onCambiar={setInsumo}
          opcionVacia="Todos"
        />
      </div>
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {lista.map((c, i) => (
          <li key={`${c.orden_compra_id}-${c.recepcion_id}-${c.insumo_id}-${i}`}>
            {fechaCorta(c.fecha)} · {nombreInsumo(c.insumo_id)} · {c.cantidad} a{" "}
            <strong>{c.costo_unitario}</strong> · {nombreProveedor(c.proveedor_id)} ·{" "}
            {c.orden_compra_id}/{c.recepcion_id}
          </li>
        ))}
        {lista.length === 0 && <li style={{ color: colores.suave }}>Sin compras recibidas.</li>}
      </ul>
    </section>
  );
}
