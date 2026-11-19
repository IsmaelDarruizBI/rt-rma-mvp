/**
 * Reparación RT (etapa 1): los productos de Gestión RT en reparación.
 *
 * - Consulta una COPIA de Gestión RT: la fecha de los datos siempre está a
 *   la vista y, si la última actualización falló, se muestra la copia
 *   anterior con el aviso.
 * - Actualizar trae los datos de Gestión RT a pedido (solo Administración,
 *   DEC-RT-05). Nada se escribe en Gestión RT.
 * - Búsqueda (ID, IMEI o sus últimos dígitos, modelo) y filtros por sede,
 *   coincidencias con Órdenes y «los que salieron», en la URL.
 * - Toda relación con una Orden es una COINCIDENCIA SUGERIDA, con su
 *   criterio: nunca un vínculo, la Orden del producto ni su historial
 *   (DEC-RT-03). Crear una Orden desde un producto llega en la etapa 2.
 */

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useState,
} from "react";

import { ApiError } from "../../api/client";
import {
  type CoincidenciaSugerida,
  type EstadoCopiaRt,
  type FichaProductoRt as Ficha,
  type ListadoProductosRt,
  type ProductoRtResumen,
  type SincronizacionProductosRt,
  listarProductosRt,
  obtenerProductoRt,
  sincronizarProductosRt,
} from "../../api/productosRt";
import { Modal } from "../../components/Modal";
import {
  Boton,
  Etiqueta,
  MensajeError,
  Panel,
  colores,
  estiloInput,
  fechaCorta,
} from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Usuario } from "../../types/api";
import { hashDe } from "../ordenes-reparacion/rutas";
import {
  type FiltroOrdenRma,
  type FiltrosRt,
  alternarSede,
  conFiltro,
  consultaDeFiltros,
  etiquetaEquipo,
  filtrosActivos,
  filtrosDeConsulta,
  hace,
  imeiAbreviado,
  nivelCopia,
  nombreSede,
  origenDeOrden,
  parametrosApi,
  resumenCoincidencias,
  resumenSincronizacion,
  textoAviso,
  textoCoincidencia,
  totalPaginas,
} from "./filtros";

const mensajeDe = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

const TODOS = ["RECEPCION", "COORDINADOR_RMA", "TECNICO", "ADMINISTRADOR"];

export function ReparacionRtPanel({
  actor,
  consulta,
  productoId,
  onNavegar,
}: {
  actor: Usuario | null;
  consulta: string;
  productoId?: string;
  onNavegar: (consulta: string, productoId?: string) => void;
}) {
  const filtros = filtrosDeConsulta(consulta);
  const [listado, setListado] = useState<ListadoProductosRt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busqueda, setBusqueda] = useState(filtros.q);
  const [sincronizando, setSincronizando] = useState(false);
  const [resultado, setResultado] =
    useState<SincronizacionProductosRt | null>(null);
  const [errorSync, setErrorSync] = useState<string | null>(null);
  const [recarga, setRecarga] = useState(0);
  const sincroniza = puede(actor, "PRODUCTOS_RT_SINCRONIZAR", [
    "ADMINISTRADOR",
  ]);

  // La búsqueda escrita sigue a la URL (Atrás, un link pegado).
  useEffect(() => setBusqueda(filtros.q), [filtros.q]);

  useEffect(() => {
    let vigente = true;
    setError(null);
    listarProductosRt(parametrosApi(filtrosDeConsulta(consulta)))
      .then((respuesta) => {
        if (vigente) setListado(respuesta);
      })
      .catch((causa: unknown) => {
        if (vigente) setError(mensajeDe(causa));
      });
    return () => {
      vigente = false;
    };
  }, [consulta, recarga]);

  const aplicar = useCallback(
    (nuevos: FiltrosRt) => onNavegar(consultaDeFiltros(nuevos)),
    [onNavegar],
  );

  const actualizar = () => {
    if (!actor) return;
    setSincronizando(true);
    setResultado(null);
    setErrorSync(null);
    sincronizarProductosRt(actor.id)
      .then((intento) => setResultado(intento))
      .catch((causa: unknown) => {
        setErrorSync(
          causa instanceof ApiError && causa.codigo === "SINCRONIZACION_EN_CURSO"
            ? "Ya hay una actualización en curso: esperá a que termine."
            : mensajeDe(causa),
        );
      })
      .finally(() => {
        setSincronizando(false);
        setRecarga((n) => n + 1);
      });
  };

  if (listado === null) {
    return error ? (
      <MensajeError mensaje={error} />
    ) : (
      <p role="status">Cargando productos de Gestión RT…</p>
    );
  }

  const { copia } = listado;
  const nivel = nivelCopia(copia);
  if (nivel === "no_habilitada") {
    return (
      <p style={{ color: colores.suave }}>
        Reparación RT funciona sobre la base PostgreSQL; en este entorno de
        demostración no está disponible.
      </p>
    );
  }

  const enviarBusqueda = (evento: FormEvent) => {
    evento.preventDefault();
    aplicar(conFiltro(filtros, { q: busqueda }));
  };
  const paginas = totalPaginas(listado.total, listado.tamano);
  const totalSedes = listado.sedes.reduce((suma, s) => suma + s.cantidad, 0);

  return (
    <div style={{ display: "grid", gap: "0.75rem" }}>
      <EncabezadoCopia
        copia={copia}
        nivel={nivel}
        puedeActualizar={sincroniza && copia.sincronizable}
        sincronizando={sincronizando}
        onActualizar={actualizar}
      />
      {errorSync && <MensajeError mensaje={errorSync} />}
      {resultado && <ResultadoActualizacion intento={resultado} />}
      {error && <MensajeError mensaje={error} />}

      <Panel>
        <form
          role="search"
          onSubmit={enviarBusqueda}
          style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}
        >
          <input
            type="search"
            aria-label="Buscar por ID, IMEI o modelo"
            placeholder="Buscar por ID, IMEI o modelo…"
            value={busqueda}
            maxLength={200}
            onChange={(e) => setBusqueda(e.target.value)}
            style={{ ...estiloInput, flex: "1 1 14rem", width: "auto" }}
          />
          <Boton type="submit" variante="secundario">
            Buscar
          </Boton>
        </form>

        <div
          role="group"
          aria-label="Sede"
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.35rem",
            marginTop: "0.6rem",
          }}
        >
          <Chip
            activo={filtros.sedes.length === 0}
            onClick={() => aplicar(conFiltro(filtros, { sedes: [] }))}
          >
            Todas {totalSedes}
          </Chip>
          {listado.sedes.map((s) => {
            const valor = s.sede ?? "";
            return (
              <Chip
                key={valor}
                activo={filtros.sedes.includes(valor)}
                onClick={() => aplicar(alternarSede(filtros, valor))}
                aviso={!s.confirmada}
              >
                {s.confirmada ? "" : "Otra: "}
                {nombreSede(s.sede)} {s.cantidad}
              </Chip>
            );
          })}
        </div>

        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.6rem 1rem",
            alignItems: "center",
            marginTop: "0.6rem",
            fontSize: "0.85rem",
          }}
        >
          <label style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
            Orden RMA
            <select
              value={filtros.ordenRma}
              onChange={(e) =>
                aplicar(
                  conFiltro(filtros, {
                    ordenRma: e.target.value as FiltroOrdenRma,
                  }),
                )
              }
              style={{ ...estiloInput, width: "auto" }}
            >
              <option value="">Todas</option>
              <option value="SIN_COINCIDENCIAS">Sin coincidencias</option>
              <option value="CON_SUGERENCIAS">
                Con coincidencias sugeridas
              </option>
            </select>
          </label>
          <label style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={filtros.incluirFuera}
              onChange={(e) =>
                aplicar(conFiltro(filtros, { incluirFuera: e.target.checked }))
              }
            />
            Mostrar los que salieron de Reparación
          </label>
          {filtrosActivos(filtros) && (
            <button
              type="button"
              className="rt-btn rt-btn--fantasma"
              onClick={() => onNavegar("")}
            >
              Quitar filtros
            </button>
          )}
        </div>
      </Panel>

      <Panel>
        <p
          style={{ margin: "0 0 0.4rem", fontSize: "0.85rem", color: colores.suave }}
          aria-live="polite"
        >
          {listado.total === 1
            ? "1 producto"
            : `${listado.total} productos`}
          {filtros.incluirFuera ? " (incluye los que salieron)" : " en reparación"}
        </p>
        {listado.productos.length === 0 ? (
          <p style={{ color: colores.suave }}>
            {copia.datos_del === null
              ? "Todavía no hay datos de Gestión RT."
              : filtrosActivos(filtros)
                ? "No hay productos que coincidan con la búsqueda y los filtros."
                : "No hay productos en reparación en los datos de Gestión RT."}
          </p>
        ) : (
          <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
            {listado.productos.map((producto) => (
              <FilaProducto
                key={producto.producto_id}
                producto={producto}
                onAbrir={() => onNavegar(consulta, producto.producto_id)}
              />
            ))}
          </ul>
        )}
        {paginas > 1 && (
          <nav
            aria-label="Páginas"
            style={{
              display: "flex",
              gap: "0.5rem",
              alignItems: "center",
              justifyContent: "flex-end",
              marginTop: "0.6rem",
              fontSize: "0.85rem",
            }}
          >
            <Boton
              variante="secundario"
              disabled={filtros.pagina <= 1}
              onClick={() => aplicar({ ...filtros, pagina: filtros.pagina - 1 })}
            >
              Anterior
            </Boton>
            <span>
              Página {filtros.pagina} de {paginas}
            </span>
            <Boton
              variante="secundario"
              disabled={filtros.pagina >= paginas}
              onClick={() => aplicar({ ...filtros, pagina: filtros.pagina + 1 })}
            >
              Siguiente
            </Boton>
          </nav>
        )}
      </Panel>

      {productoId && (
        <FichaProductoRt
          productoId={productoId}
          actor={actor}
          onCerrar={() => onNavegar(consulta)}
        />
      )}
    </div>
  );
}

function Chip({
  activo,
  aviso = false,
  onClick,
  children,
}: {
  activo: boolean;
  aviso?: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={activo}
      onClick={onClick}
      style={{
        padding: "0.25rem 0.7rem",
        borderRadius: 999,
        border: `1px solid ${activo ? colores.acento : aviso ? colores.alerta : colores.borde}`,
        background: activo ? colores.acento : "transparent",
        color: activo ? "#fff" : aviso ? colores.alerta : colores.texto,
        fontSize: "0.8rem",
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function EncabezadoCopia({
  copia,
  nivel,
  puedeActualizar,
  sincronizando,
  onActualizar,
}: {
  copia: EstadoCopiaRt;
  nivel: ReturnType<typeof nivelCopia>;
  puedeActualizar: boolean;
  sincronizando: boolean;
  onActualizar: () => void;
}) {
  const enReparacion = copia.ultima_exitosa?.contadores.en_reparacion;
  const fallo = copia.ultima;
  let aviso: { color: string; texto: string } | null = null;
  if (nivel === "error_con_copia" && fallo && copia.datos_del) {
    aviso = {
      color: colores.alerta,
      texto: `La última actualización falló el ${fechaCorta(fallo.finalizada_en)}: ${
        fallo.mensaje ?? fallo.resultado
      } Se muestran los datos del ${fechaCorta(copia.datos_del)}`,
    };
  } else if (nivel === "error_sin_copia" && fallo) {
    aviso = {
      color: colores.error,
      texto: `La actualización falló el ${fechaCorta(fallo.finalizada_en)}: ${
        fallo.mensaje ?? fallo.resultado
      } Todavía no hay datos de Gestión RT.`,
    };
  } else if (nivel === "desactualizada") {
    aviso = {
      color: colores.alerta,
      texto: `Los datos tienen más de ${copia.antiguedad_aviso_horas} h. ${
        puedeActualizar ? "Actualizalos" : "Pedí a Administración que los actualice"
      } para ver el estado de hoy.`,
    };
  }
  return (
    <Panel>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <p style={{ margin: 0 }} role="status">
          {copia.datos_del ? (
            <>
              Datos de Gestión RT del <strong>{fechaCorta(copia.datos_del)}</strong>{" "}
              <span style={{ color: colores.suave }}>({hace(copia.datos_del)})</span>
              {enReparacion !== undefined && <> · {enReparacion} en reparación</>}
            </>
          ) : nivel === "sin_origen" ? (
            "No hay un origen de Gestión RT configurado en este entorno: no hay datos para mostrar."
          ) : puedeActualizar ? (
            "Todavía no se trajeron los datos de Gestión RT: usá Actualizar."
          ) : (
            "Todavía no se trajeron los datos de Gestión RT: pedí a Administración que los actualice."
          )}
        </p>
        {puedeActualizar && (
          <Boton onClick={onActualizar} disabled={sincronizando}>
            {sincronizando ? "Actualizando…" : "Actualizar"}
          </Boton>
        )}
      </div>
      {aviso && (
        <p
          role="alert"
          style={{
            margin: "0.6rem 0 0",
            padding: "0.5rem 0.7rem",
            borderRadius: 6,
            border: `1px solid ${aviso.color}`,
            color: aviso.color,
            fontSize: "0.85rem",
          }}
        >
          {aviso.texto}
        </p>
      )}
    </Panel>
  );
}

function ResultadoActualizacion({
  intento,
}: {
  intento: SincronizacionProductosRt;
}) {
  return (
    <Panel>
      <p style={{ margin: 0, color: colores.ok }} role="status">
        Actualizado: {resumenSincronizacion(intento.contadores)}.
      </p>
      {intento.avisos.length > 0 && (
        <details style={{ marginTop: "0.4rem", fontSize: "0.85rem" }}>
          <summary>{intento.avisos.length} avisos de la actualización</summary>
          <ul style={{ margin: "0.4rem 0 0", paddingLeft: "1.1rem" }}>
            {intento.avisos.map((aviso) => (
              <li key={aviso}>{aviso}</li>
            ))}
          </ul>
        </details>
      )}
    </Panel>
  );
}

function FilaProducto({
  producto,
  onAbrir,
}: {
  producto: ProductoRtResumen;
  onAbrir: () => void;
}) {
  const fuera = !producto.en_reparacion || producto.eliminado_en_origen || !producto.presente_en_origen;
  const coincidencias = producto.coincidencias_sugeridas.length > 0;
  return (
    <li style={{ borderTop: `1px solid ${colores.borde}` }}>
      <button
        type="button"
        onClick={onAbrir}
        style={{
          display: "block",
          width: "100%",
          textAlign: "left",
          padding: "0.6rem 0.2rem",
          background: "transparent",
          border: 0,
          color: "inherit",
          font: "inherit",
          cursor: "pointer",
        }}
      >
        <span
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: "0.45rem",
            alignItems: "center",
          }}
        >
          <strong style={{ color: colores.acento }}>{producto.producto_id}</strong>
          <Etiqueta>{nombreSede(producto.sede)}</Etiqueta>
          {fuera && <Etiqueta color={colores.alerta}>{producto.estado_gestion_rt || "Fuera de Reparación"}</Etiqueta>}
          {producto.avisos.length > 0 && !fuera && (
            <Etiqueta color={colores.alerta}>
              {producto.avisos.length === 1 ? "1 aviso" : `${producto.avisos.length} avisos`}
            </Etiqueta>
          )}
        </span>
        <span style={{ display: "block", marginTop: "0.2rem", overflowWrap: "anywhere" }}>
          {etiquetaEquipo(producto)}
        </span>
        <span
          style={{
            display: "flex",
            flexWrap: "wrap",
            columnGap: "0.8rem",
            rowGap: "0.1rem",
            marginTop: "0.2rem",
            fontSize: "0.8rem",
            color: colores.suave,
          }}
        >
          <span>IMEI {imeiAbreviado(producto.imei)}</span>
          {producto.en_reparacion_desde && (
            <span>En reparación desde el {fechaCorta(producto.en_reparacion_desde)}</span>
          )}
          <span style={{ color: coincidencias ? colores.alerta : colores.suave }}>
            Orden RMA: {resumenCoincidencias(producto)}
          </span>
        </span>
      </button>
    </li>
  );
}

function Dato({ etiqueta, valor }: { etiqueta: string; valor: ReactNode }) {
  return (
    <div style={{ minWidth: 0 }}>
      <dt style={{ fontSize: "0.75rem", color: colores.suave }}>{etiqueta}</dt>
      <dd style={{ margin: 0, overflowWrap: "anywhere" }}>{valor ?? "—"}</dd>
    </div>
  );
}

const fecha = (iso: string | null) => (iso ? fechaCorta(iso) : "—");

function FichaProductoRt({
  productoId,
  actor,
  onCerrar,
}: {
  productoId: string;
  actor: Usuario | null;
  onCerrar: () => void;
}) {
  const [ficha, setFicha] = useState<Ficha | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let vigente = true;
    setFicha(null);
    setError(null);
    obtenerProductoRt(productoId)
      .then((respuesta) => {
        if (vigente) setFicha(respuesta);
      })
      .catch((causa: unknown) => {
        if (vigente) setError(mensajeDe(causa));
      });
    return () => {
      vigente = false;
    };
  }, [productoId]);
  const veOrdenes = puede(actor, "ORDENES_CONSULTAR", TODOS);

  return (
    <Modal titulo={`Producto RT ${productoId}`} amplio onCerrar={onCerrar}>
      {error && <MensajeError mensaje={error} />}
      {!ficha && !error && <p role="status">Cargando…</p>}
      {ficha && (
        <div style={{ display: "grid", gap: "1rem" }}>
          <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
            Datos de Gestión RT del {fecha(ficha.copia.datos_del)} · Solo
            consulta: RMA no modifica Gestión RT.
          </p>
          {ficha.producto.avisos.length > 0 && (
            <ul
              role="list"
              aria-label="Avisos"
              style={{ margin: 0, paddingLeft: "1.1rem", color: colores.alerta, fontSize: "0.85rem" }}
            >
              {ficha.producto.avisos.map((aviso) => (
                <li key={aviso}>{textoAviso(aviso)}</li>
              ))}
            </ul>
          )}
          <DatosTecnicos ficha={ficha} />
          <CoincidenciasSugeridas
            coincidencias={ficha.producto.coincidencias_sugeridas}
            veOrdenes={veOrdenes}
          />
          <section>
            <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.3rem" }}>Historial</h3>
            <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
              Sin vínculos verificables con Órdenes de RMA: este producto no
              tiene historial en RMA. Las coincidencias sugeridas no son
              historial.
            </p>
          </section>
        </div>
      )}
    </Modal>
  );
}

function DatosTecnicos({ ficha }: { ficha: Ficha }) {
  const p = ficha.producto;
  const imei = p.imei
    ? `${p.imei}${p.imei_valido ? "" : " (no válido)"}${p.imei_repetido ? " (repetido)" : ""}`
    : "Sin IMEI";
  return (
    <section>
      <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.4rem" }}>Datos técnicos</h3>
      <dl
        style={{
          margin: 0,
          display: "grid",
          gap: "0.6rem 1rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 12rem), 1fr))",
        }}
      >
        <Dato etiqueta="ID RT" valor={p.producto_id} />
        <Dato etiqueta="IMEI" valor={imei} />
        <Dato etiqueta="Equipo" valor={etiquetaEquipo(p)} />
        <Dato etiqueta="Capacidad" valor={p.capacidad} />
        <Dato etiqueta="Color" valor={p.color} />
        <Dato
          etiqueta="Categoría"
          valor={[p.categoria, p.subcategoria].filter(Boolean).join(" · ") || null}
        />
        <Dato etiqueta="TipoProducto (Ventas)" valor={p.tipo_producto_id} />
        <Dato etiqueta="Batería" valor={p.bateria} />
        <Dato etiqueta="Detalle estético" valor={p.detalle_estetico} />
        <Dato etiqueta="Defecto (Gestión RT)" valor={p.defecto} />
        <Dato etiqueta="Tipo de reparación (Gestión RT)" valor={p.tipo_reparacion_origen} />
        <Dato etiqueta="Repuesto (Gestión RT)" valor={p.repuesto} />
        <Dato etiqueta="Toma RT" valor={p.toma_rt} />
        <Dato etiqueta="Sede" valor={nombreSede(p.sede)} />
        <Dato etiqueta="Estado en Gestión RT" valor={p.estado_gestion_rt || "—"} />
        <Dato etiqueta="Alta en Gestión RT" valor={fecha(p.creado_en_origen)} />
        <Dato etiqueta="En reparación desde" valor={fecha(p.en_reparacion_desde)} />
        {p.salio_de_reparacion_en && (
          <Dato etiqueta="Salió de Reparación" valor={fecha(p.salio_de_reparacion_en)} />
        )}
        <Dato etiqueta="Visto por primera vez" valor={fecha(p.primera_vez_visto_en)} />
        {p.cambio_identidad && p.identidad_anterior && (
          <Dato
            etiqueta="Identidad anterior"
            valor={`IMEI ${p.identidad_anterior.imei ?? "—"} · TipoProducto ${
              p.identidad_anterior.tipo_producto_id ?? "—"
            }`}
          />
        )}
      </dl>
    </section>
  );
}

function CoincidenciasSugeridas({
  coincidencias,
  veOrdenes,
}: {
  coincidencias: CoincidenciaSugerida[];
  veOrdenes: boolean;
}) {
  return (
    <section>
      <h3 style={{ fontSize: "0.95rem", margin: "0 0 0.3rem" }}>
        Órdenes RMA: coincidencias sugeridas
      </h3>
      <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.suave }}>
        Coinciden por referencia RT o por IMEI. Son solo sugerencias: ninguna
        Orden está vinculada a este producto.
      </p>
      {coincidencias.length === 0 ? (
        <p style={{ margin: 0, fontSize: "0.85rem" }}>Sin coincidencias.</p>
      ) : (
        <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
          {coincidencias.map((c) => (
            <li key={c.orden_id} style={{ marginBottom: "0.25rem" }}>
              {veOrdenes ? (
                <a href={hashDe({ pantalla: "orden", ordenId: c.orden_id })}>
                  {textoCoincidencia(c)}
                </a>
              ) : (
                textoCoincidencia(c)
              )}
              <span style={{ color: colores.suave }}>
                {" "}
                · {origenDeOrden(c.origen)} · ingresó el {fechaCorta(c.creada_en)}
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
