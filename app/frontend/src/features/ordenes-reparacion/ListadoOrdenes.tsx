/**
 * Listado de Órdenes (búsqueda, filtros y orden) y alta de una nueva.
 *
 * El listado trabaja sobre los resúmenes de `GET /api/orders`, que ya
 * traen la situación operativa de cada Orden calculada por el backend: no
 * pide cada Orden ni recalcula nada. Cada fila es un link a la URL de la
 * Orden, así que se puede abrir en otra pestaña o copiar.
 *
 * El alta vive en su propia pantalla (`#/ordenes/nueva`): primero se elige
 * el origen y después se muestra solo el formulario de ese origen.
 */

import { type ReactNode, useMemo, useState } from "react";

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
  BusquedaCliente,
  OrdenResumen,
  PersonaExterna,
  Usuario,
} from "../../types/api";
import type { DatosNuevaOrden, DatosNuevaOrdenRt } from "../../api/ordenes";
import { buscarClientePorDni } from "../../api/clientes";
import { ApiError } from "../../api/client";
import { normalizarDni } from "./clientes";
import {
  ESTADO_WORKFLOW,
  ORIGEN,
  ROL,
  SITUACION,
  etiqueta,
  hace,
} from "./etiquetas";
import {
  type CriterioOrden,
  FILTROS_INICIALES,
  type FiltroRapido,
  type FiltrosListado,
  aplicarListado,
  filtrosActivos,
} from "./listado";
import { hashDe } from "./rutas";

const ATAJOS: { valor: FiltroRapido; texto: string }[] = [
  { valor: "TODAS", texto: "Todas" },
  { valor: "ABIERTAS", texto: "Abiertas" },
  { valor: "MI_SECTOR", texto: "Pendientes de mi sector" },
  { valor: "CERRADAS", texto: "Cerradas" },
];

const CRITERIOS: { valor: CriterioOrden; texto: string }[] = [
  { valor: "INGRESO_RECIENTE", texto: "Ingreso: más reciente primero" },
  { valor: "INGRESO_ANTIGUO", texto: "Ingreso: más antigua primero" },
  { valor: "PRIORIDAD", texto: "Prioridad: más urgente primero" },
  { valor: "ACTIVIDAD", texto: "Última actividad" },
];

/** Color del chip de situación (el mismo criterio que la cabecera). */
export function colorDeSituacion(codigo: string | undefined): string {
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

export function nombreDe(
  usuarios: Usuario[],
  usuarioId: string | null,
): string {
  if (!usuarioId) return "";
  return usuarios.find((usuario) => usuario.id === usuarioId)?.nombre ?? usuarioId;
}

/** Opciones de un filtro: solo los valores que aparecen en las Órdenes. */
function opciones(
  valores: (string | null | undefined)[],
  nombre: (valor: string) => string,
): { valor: string; texto: string }[] {
  return [...new Set(valores.filter((valor): valor is string => !!valor))]
    .map((valor) => ({ valor, texto: nombre(valor) }))
    .sort((a, b) => a.texto.localeCompare(b.texto, "es"));
}

/**
 * La pantalla «Órdenes»: buscar, filtrar, ordenar y abrir. Los filtros los
 * guarda el contenedor, así que sobreviven a abrir una Orden y volver.
 */
export function PantallaOrdenes({
  ordenes,
  usuarios,
  actor,
  filtros,
  onFiltros,
  onNueva,
  cargado,
}: {
  ordenes: OrdenResumen[];
  usuarios: Usuario[];
  actor: Usuario | null;
  filtros: FiltrosListado;
  onFiltros: (filtros: FiltrosListado) => void;
  onNueva: () => void;
  cargado: boolean;
}) {
  const rol = actor?.rol ?? null;
  const visibles = useMemo(
    () => aplicarListado(ordenes, filtros, rol),
    [ordenes, filtros, rol],
  );
  const cambiar = (cambios: Partial<FiltrosListado>) =>
    onFiltros({ ...filtros, ...cambios });
  const activos = filtrosActivos(filtros);
  const [verFiltros, setVerFiltros] = useState(activos > 0);
  const hayAlgo =
    filtros.texto.trim() !== "" ||
    activos > 0 ||
    filtros.rapido !== FILTROS_INICIALES.rapido;

  const selector = (
    titulo: string,
    valor: string,
    alCambiar: (valor: string) => void,
    lista: { valor: string; texto: string }[],
    todos: string,
  ) => (
    <Campo etiqueta={titulo}>
      <select
        value={valor}
        onChange={(evento) => alCambiar(evento.target.value)}
        style={estiloInput}
      >
        <option value="">{todos}</option>
        {lista.map((opcion) => (
          <option key={opcion.valor} value={opcion.valor}>
            {opcion.texto}
          </option>
        ))}
      </select>
    </Campo>
  );

  return (
    <Panel>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.75rem",
          flexWrap: "wrap",
          marginBottom: "0.75rem",
        }}
      >
        <h2 style={{ margin: 0, fontSize: "1.2rem" }}>Órdenes</h2>
        <Boton onClick={onNueva}>+ Nueva orden</Boton>
      </div>

      <div style={{ display: "flex", gap: "0.4rem", marginBottom: "0.6rem" }}>
        <input
          type="search"
          aria-label="Buscar órdenes"
          value={filtros.texto}
          onChange={(evento) => cambiar({ texto: evento.target.value })}
          placeholder="Buscar OR, cliente, teléfono, equipo…"
          title="Número de OR, cliente, teléfono, marca o modelo, IMEI, número de serie o referencia RT"
          style={{ ...estiloInput, flex: 1, minWidth: 0 }}
        />
        {filtros.texto && (
          <Boton variante="secundario" onClick={() => cambiar({ texto: "" })}>
            Limpiar
          </Boton>
        )}
      </div>

      <div
        role="group"
        aria-label="Atajos"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.4rem",
          marginBottom: "0.6rem",
        }}
      >
        {ATAJOS.map((atajo) => (
          <button
            key={atajo.valor}
            type="button"
            aria-pressed={filtros.rapido === atajo.valor}
            onClick={() => cambiar({ rapido: atajo.valor })}
            style={{
              padding: "0.3rem 0.7rem",
              borderRadius: 999,
              border: `1px solid ${
                filtros.rapido === atajo.valor ? colores.acento : colores.borde
              }`,
              background:
                filtros.rapido === atajo.valor ? colores.acento : "#fff",
              color: filtros.rapido === atajo.valor ? "#fff" : colores.texto,
              fontSize: "0.85rem",
              fontFamily: "inherit",
              cursor: "pointer",
            }}
          >
            {atajo.texto}
            {atajo.valor === "MI_SECTOR" && rol ? ` (${ROL[rol]})` : ""}
          </button>
        ))}
      </div>

      <details
        open={verFiltros}
        onToggle={(evento) => setVerFiltros(evento.currentTarget.open)}
        style={{ marginBottom: "0.6rem" }}
      >
        <summary style={{ cursor: "pointer", fontSize: "0.85rem" }}>
          Filtros y orden
          {activos > 0 ? ` (${activos} activo${activos > 1 ? "s" : ""})` : ""}
        </summary>
        <div
          style={{
            display: "grid",
            columnGap: "0.6rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))",
            marginTop: "0.5rem",
          }}
        >
          {selector(
            "Situación",
            filtros.situacion,
            (situacion) => cambiar({ situacion }),
            opciones(
              ordenes.map((orden) => orden.situacion?.codigo),
              (codigo) => etiqueta(SITUACION, codigo),
            ),
            "Cualquiera",
          )}
          {selector(
            "Sector responsable",
            filtros.sector,
            (sector) => cambiar({ sector }),
            opciones(
              ordenes
                .filter((orden) => !orden.cerrada)
                .flatMap((orden) => orden.situacion?.roles ?? []),
              (rol) => etiqueta(ROL, rol),
            ),
            "Cualquiera",
          )}
          {selector(
            "Estado",
            filtros.estado,
            (estado) => cambiar({ estado }),
            opciones(
              ordenes.map((orden) => orden.estado_workflow),
              (estado) => etiqueta(ESTADO_WORKFLOW, estado),
            ),
            "Cualquiera",
          )}
          {selector(
            "Origen",
            filtros.origen,
            (origen) => cambiar({ origen }),
            opciones(
              ordenes.map((orden) => orden.origen),
              (origen) => etiqueta(ORIGEN, origen),
            ),
            "Cualquiera",
          )}
          {selector(
            "Técnico titular",
            filtros.tecnico,
            (tecnico) => cambiar({ tecnico }),
            opciones(
              ordenes.map((orden) => orden.tecnico_id),
              (id) => nombreDe(usuarios, id),
            ),
            "Cualquiera",
          )}
          <Campo etiqueta="Ordenar por">
            <select
              value={filtros.orden}
              onChange={(evento) =>
                cambiar({ orden: evento.target.value as CriterioOrden })
              }
              style={estiloInput}
            >
              {CRITERIOS.map((criterio) => (
                <option key={criterio.valor} value={criterio.valor}>
                  {criterio.texto}
                </option>
              ))}
            </select>
          </Campo>
        </div>
      </details>

      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.5rem",
          flexWrap: "wrap",
          fontSize: "0.85rem",
          color: colores.suave,
          margin: "0.4rem 0",
        }}
      >
        <span role="status">
          {cargado
            ? `${visibles.length} de ${ordenes.length} órdenes`
            : "Cargando órdenes…"}
        </span>
        {hayAlgo && (
          <Boton
            variante="secundario"
            onClick={() => onFiltros({ ...FILTROS_INICIALES, orden: filtros.orden })}
          >
            Limpiar búsqueda y filtros
          </Boton>
        )}
      </div>

      {cargado && visibles.length === 0 && (
        <p
          style={{
            margin: "0.5rem 0 0",
            padding: "0.8rem",
            borderRadius: 6,
            background: colores.fondo,
            fontSize: "0.9rem",
          }}
        >
          {ordenes.length === 0
            ? "Todavía no hay órdenes. Creá la primera con «Nueva orden»."
            : filtros.texto.trim()
              ? `No hay órdenes que coincidan con «${filtros.texto.trim()}» y los filtros elegidos.`
              : "No hay órdenes con los filtros elegidos."}
        </p>
      )}

      <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {visibles.map((orden) => (
          <FilaOrden key={orden.id} orden={orden} usuarios={usuarios} />
        ))}
      </ul>
    </Panel>
  );
}

/** Una Orden del listado: un link a su URL, con lo necesario para decidir. */
function FilaOrden({
  orden,
  usuarios,
}: {
  orden: OrdenResumen;
  usuarios: Usuario[];
}) {
  const situacion = orden.situacion;
  const leToca = situacion?.titular_id
    ? `${nombreDe(usuarios, situacion.titular_id)} (técnico titular)`
    : situacion?.responsable;
  const datos: ReactNode[] = [
    <span key="ingreso" title={fechaCorta(orden.created_at)}>
      Ingresó el {fechaCorta(orden.created_at)} ({hace(orden.created_at)})
    </span>,
  ];
  if (leToca && !orden.cerrada) {
    datos.push(
      <span key="toca">
        Le toca: <strong>{leToca}</strong>
      </span>,
    );
  }
  if (orden.tecnico_id && orden.tecnico_id !== situacion?.titular_id) {
    datos.push(
      <span key="tecnico">Técnico: {nombreDe(usuarios, orden.tecnico_id)}</span>,
    );
  }
  if (orden.prioridad_texto) {
    datos.push(<span key="prioridad">{orden.prioridad_texto}</span>);
  }
  return (
    <li style={{ borderTop: `1px solid ${colores.borde}` }}>
      <a
        href={hashDe({ pantalla: "orden", ordenId: orden.id })}
        style={{
          display: "block",
          padding: "0.65rem 0.2rem",
          color: "inherit",
          textDecoration: "none",
        }}
      >
        <span
          style={{
            display: "flex",
            justifyContent: "space-between",
            alignItems: "baseline",
            gap: "0.5rem",
            flexWrap: "wrap",
          }}
        >
          <span
            style={{
              display: "flex",
              alignItems: "center",
              gap: "0.45rem",
              flexWrap: "wrap",
            }}
          >
            <strong style={{ color: colores.acento }}>{orden.id}</strong>
            <Etiqueta color={colorDeSituacion(situacion?.codigo)}>
              {situacion?.titulo ?? etiqueta(ESTADO_WORKFLOW, orden.estado_workflow)}
            </Etiqueta>
          </span>
          {orden.cobrable && (
            <span style={{ fontSize: "0.85rem" }}>
              Saldo {importe(orden.saldo)}
            </span>
          )}
        </span>
        <span style={{ display: "block", marginTop: "0.2rem" }}>
          {orden.cliente_nombre}
          {orden.cliente_telefono ? ` · ${orden.cliente_telefono}` : ""} ·{" "}
          {orden.equipo}
        </span>
        {orden.origen === "RMA_GARANTIA_REPARACION" && orden.orden_origen_id && (
          <span
            style={{ display: "block", fontSize: "0.8rem", color: colores.suave }}
          >
            Garantía de la Orden {orden.orden_origen_id}
          </span>
        )}
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
          {datos}
        </span>
      </a>
    </li>
  );
}

/**
 * Origen elegido en el alta manual. RMA_GARANTIA_REPARACION no está:
 * no se crea desde cero, nace de una Orden entregada (HP-REP-003).
 */
type OrigenAlta = "" | "CLIENTE_EXTERNO" | "RT_INTERNO";

/**
 * Bloque "Nueva Orden": selector de origen y, debajo, solo el
 * formulario de ese origen. Cambiar el origen no envía nada al backend.
 */
export function FormularioAltaOrden({
  actor,
  ocupado,
  onCrearClienteExterno,
  onCrearRtInterno,
  onCancelar,
}: {
  actor: Usuario | null;
  ocupado: boolean;
  onCrearClienteExterno: (datos: DatosNuevaOrden) => void;
  onCrearRtInterno: (datos: DatosNuevaOrdenRt) => void;
  /** Volver al listado sin crear nada. */
  onCancelar?: () => void;
}) {
  const [origen, setOrigen] = useState<OrigenAlta>("");

  return (
    <Panel titulo="Nueva Orden">
      <Campo etiqueta="Origen del equipo">
        <select
          value={origen}
          onChange={(evento) => setOrigen(evento.target.value as OrigenAlta)}
          style={estiloInput}
        >
          <option value="">Seleccioná un origen...</option>
          <option value="CLIENTE_EXTERNO">Cliente externo</option>
          <option value="RT_INTERNO">Equipo RT interno</option>
        </select>
      </Campo>
      {origen === "CLIENTE_EXTERNO" && (
        <FormularioNuevaOrden
          actor={actor}
          ocupado={ocupado}
          onCrear={onCrearClienteExterno}
        />
      )}
      {origen === "RT_INTERNO" && (
        <FormularioNuevaOrdenRt
          actor={actor}
          ocupado={ocupado}
          onCrear={onCrearRtInterno}
        />
      )}
      {onCancelar && (
        <div
          style={{
            marginTop: "0.9rem",
            paddingTop: "0.9rem",
            borderTop: `1px solid ${colores.borde}`,
          }}
        >
          <Boton variante="secundario" onClick={onCancelar}>
            Cancelar y volver al listado
          </Boton>
        </div>
      )}
    </Panel>
  );
}

/**
 * Datos del ingreso físico, comunes a los dos orígenes: identificadores
 * del equipo (opcionales: no todo equipo tiene IMEI) y condiciones en que
 * se recibe. La recepción física se confirma después, en la Orden.
 */
interface Ingreso {
  imei: string;
  numeroSerie: string;
  estadoFisico: string;
  accesorios: string;
  /** Visibles: salen en el comprobante. */
  observaciones: string;
  /** Solo para el personal: nunca salen en un documento. */
  notasInternas: string;
}

function ingresoInicial(): Ingreso {
  return {
    imei: "",
    numeroSerie: "",
    estadoFisico: "Sin golpes ni marcas visibles.",
    accesorios: "Cargador",
    observaciones: "",
    notasInternas: "",
  };
}

function textoONulo(valor: string): string | null {
  return valor.trim() || null;
}

/** "Cargador, funda" -> ["Cargador", "funda"]. */
export function listaDeAccesorios(texto: string): string[] {
  return texto
    .split(",")
    .map((accesorio) => accesorio.trim())
    .filter(Boolean);
}

function datosDeIngreso(ingreso: Ingreso) {
  return {
    identificadores: {
      imei: textoONulo(ingreso.imei),
      numero_serie: textoONulo(ingreso.numeroSerie),
    },
    recepcion: {
      estado_fisico: textoONulo(ingreso.estadoFisico),
      accesorios: listaDeAccesorios(ingreso.accesorios),
      observaciones: textoONulo(ingreso.observaciones),
      notas_internas: textoONulo(ingreso.notasInternas),
    },
  };
}

/**
 * Datos del ingreso. El check-in no se pide acá: se registra antes de la
 * entrega, con la reparación lista (UAT-009).
 */
function CamposIngreso({
  ingreso,
  clienteExterno = false,
  onCambiar,
}: {
  ingreso: Ingreso;
  /** Cliente Externo: sigue con el comprobante de ingreso. */
  clienteExterno?: boolean;
  onCambiar: (ingreso: Ingreso) => void;
}) {
  const cambiar =
    (clave: keyof Ingreso) =>
    (evento: { target: { value: string } }) =>
      onCambiar({ ...ingreso, [clave]: evento.target.value });
  return (
    <>
      <div
        style={{
          display: "grid",
          columnGap: "0.6rem",
          gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 140px), 1fr))",
        }}
      >
        <Campo etiqueta="IMEI (si tiene)">
          <input
            value={ingreso.imei}
            onChange={cambiar("imei")}
            style={estiloInput}
            inputMode="numeric"
          />
        </Campo>
        {/* UAT-011: el alta de Cliente Externo no pide el número de serie
            (el dato sigue existiendo y otros orígenes lo cargan). */}
        {!clienteExterno && (
          <Campo etiqueta="N.º de serie (si tiene)">
            <input
              value={ingreso.numeroSerie}
              onChange={cambiar("numeroSerie")}
              style={estiloInput}
            />
          </Campo>
        )}
      </div>
      <Campo etiqueta="Estado físico al recibirlo">
        <textarea
          value={ingreso.estadoFisico}
          onChange={cambiar("estadoFisico")}
          rows={2}
          style={{ ...estiloInput, resize: "vertical" }}
        />
      </Campo>
      <Campo etiqueta="Accesorios recibidos (separados por coma)">
        <input
          value={ingreso.accesorios}
          onChange={cambiar("accesorios")}
          placeholder="Cargador, funda, chip"
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Observaciones del equipo (salen en el comprobante)">
        <input
          value={ingreso.observaciones}
          onChange={cambiar("observaciones")}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Notas internas (solo el personal; no salen en documentos)">
        <input
          value={ingreso.notasInternas}
          onChange={cambiar("notasInternas")}
          style={estiloInput}
        />
      </Campo>
      <p
        style={{
          margin: "0 0 0.6rem",
          fontSize: "0.75rem",
          color: colores.suave,
        }}
      >
        {clienteExterno
          ? "Después de crearla se cargan los trabajos y se genera el " +
            "comprobante de ingreso y autorización, que confirma la " +
            "recepción del equipo."
          : "La recepción física del equipo se confirma después, en la Orden."}
      </p>
    </>
  );
}

interface DatosElegidos {
  nombreApellido: string;
  telefono: string | null;
  clienteId: string | null;
}

/**
 * DNI y «Buscar datos» (UAT-010): primero nuestras Órdenes (un cliente que
 * ya vino) y, si hay una fuente externa autorizada, esa fuente. Nada se
 * completa solo: Recepción revisa, corrige y elige «Usar estos datos». La
 * carga manual sigue disponible siempre. El estado vive en el formulario:
 * «Crear Orden» también busca el DNI en nuestra base antes de crear.
 */
function BusquedaPorDni({
  dni,
  dniInvalido,
  puedeBuscar,
  buscando,
  resultado,
  error,
  clienteId,
  onDni,
  onBuscar,
  onUsar,
  onDescartar,
  onDesvincular,
}: {
  dni: string;
  dniInvalido: boolean;
  puedeBuscar: boolean;
  buscando: boolean;
  resultado: BusquedaCliente | null;
  error: string | null;
  clienteId: string | null;
  onDni: (dni: string) => void;
  onBuscar: () => void;
  onUsar: (datos: DatosElegidos) => void;
  onDescartar: () => void;
  onDesvincular: () => void;
}) {
  return (
    <div style={{ marginBottom: "0.6rem" }}>
      <div style={{ display: "flex", gap: "0.5rem", alignItems: "flex-end", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 10rem" }}>
          <Campo etiqueta="DNI (opcional)">
            <input
              value={dni}
              inputMode="numeric"
              autoComplete="off"
              onChange={(evento) => onDni(evento.target.value)}
              style={estiloInput}
            />
          </Campo>
        </div>
        <div style={{ marginBottom: "0.6rem" }}>
          <Boton variante="secundario" disabled={!puedeBuscar} onClick={onBuscar}>
            {buscando ? "Buscando…" : "Buscar datos"}
          </Boton>
        </div>
      </div>
      {dniInvalido && (
        <p role="alert" style={{ margin: "-0.3rem 0 0.5rem", fontSize: "0.8rem", color: colores.alerta }}>
          El DNI debe tener 7 u 8 dígitos (sin letras).
        </p>
      )}
      {clienteId && (
        <p style={{ margin: "-0.3rem 0 0.5rem", fontSize: "0.8rem", color: colores.ok }}>
          Cliente existente: la Orden queda vinculada a sus Órdenes anteriores.{" "}
          <button
            type="button"
            onClick={onDesvincular}
            style={{ border: 0, background: "none", padding: 0, color: colores.acento, cursor: "pointer", fontSize: "0.8rem", textDecoration: "underline" }}
          >
            Desvincular
          </button>
        </p>
      )}
      {error && (
        <p role="alert" style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.alerta }}>
          {error}
        </p>
      )}
      {resultado && (
        <RevisionDeDatos resultado={resultado} onUsar={onUsar} onDescartar={onDescartar} />
      )}
    </div>
  );
}

/** El resultado para revisar: nada se usa sin que Recepción lo elija. */
function RevisionDeDatos({
  resultado,
  onUsar,
  onDescartar,
}: {
  resultado: BusquedaCliente;
  onUsar: (datos: DatosElegidos) => void;
  onDescartar: () => void;
}) {
  return (
    <div
      role="region"
      aria-label="Datos encontrados"
      style={{
        border: `1px solid ${colores.borde}`,
        borderRadius: 6,
        padding: "0.5rem 0.7rem",
        margin: "0 0 0.6rem",
        background: colores.fondo,
        fontSize: "0.85rem",
      }}
    >
      <p style={{ margin: "0 0 0.4rem" }}>{resultado.mensaje}</p>
      {resultado.conocidos.map((conocido) => (
        <div key={conocido.cliente_id} style={{ margin: "0 0 0.5rem" }}>
          <strong>{conocido.nombre_apellido}</strong> · {conocido.telefono}
          {conocido.email ? ` · ${conocido.email}` : ""}
          <span style={{ color: colores.suave }}>
            {" "}
            · {conocido.ordenes === 1 ? "1 Orden" : `${conocido.ordenes} Órdenes`},
            la última {conocido.ultima_orden_id} ({fechaCorta(conocido.ultima_fecha)})
          </span>
          <div style={{ marginTop: "0.3rem" }}>
            <Boton
              variante="secundario"
              onClick={() =>
                onUsar({
                  nombreApellido: conocido.nombre_apellido,
                  telefono: conocido.telefono,
                  clienteId: conocido.cliente_id,
                })
              }
            >
              Usar estos datos
            </Boton>
          </div>
        </div>
      ))}
      {resultado.externos.map((persona, indice) => (
        <PersonaParaRevisar
          key={`${persona.nombre_apellido}-${indice}`}
          persona={persona}
          onUsar={onUsar}
        />
      ))}
      <Boton variante="secundario" onClick={onDescartar}>
        {resultado.conocidos.length || resultado.externos.length ? "Descartar" : "Cerrar"}
      </Boton>
    </div>
  );
}

/**
 * El nombre completo que devuelve una fuente externa, tal cual (no se
 * separa), editable antes de confirmarlo.
 */
function PersonaParaRevisar({
  persona,
  onUsar,
}: {
  persona: PersonaExterna;
  onUsar: (datos: DatosElegidos) => void;
}) {
  const [nombreApellido, setNombreApellido] = useState(persona.nombre_apellido);
  return (
    <div style={{ margin: "0 0 0.5rem" }}>
      <Campo etiqueta="Nombre y apellido según la fuente (revisalo)">
        <input
          value={nombreApellido}
          onChange={(evento) => setNombreApellido(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Boton
        variante="secundario"
        disabled={nombreApellido.trim() === ""}
        onClick={() =>
          onUsar({
            nombreApellido: nombreApellido.trim(),
            telefono: null,
            clienteId: null,
          })
        }
      >
        Usar estos datos
      </Boton>
    </div>
  );
}

/** Campos del alta de cliente externo (dentro de "Nueva Orden"). */
export function FormularioNuevaOrden({
  actor,
  ocupado,
  onCrear,
}: {
  actor: Usuario | null;
  ocupado: boolean;
  onCrear: (datos: DatosNuevaOrden) => void;
}) {
  const [nombreApellido, setNombreApellido] = useState("Cliente de Prueba");
  const [telefono, setTelefono] = useState("341-0000000");
  const [dni, setDni] = useState("");
  // Cliente que ya tiene Órdenes y cuyos datos eligió usar Recepción.
  const [clienteId, setClienteId] = useState<string | null>(null);
  const [buscando, setBuscando] = useState(false);
  const [resultado, setResultado] = useState<BusquedaCliente | null>(null);
  const [errorBusqueda, setErrorBusqueda] = useState<string | null>(null);
  // Para qué DNI ya se buscó (crear con un DNI nuevo lo busca antes).
  const [buscadoPara, setBuscadoPara] = useState<string | null>(null);
  const [marca, setMarca] = useState("Apple");
  const [modelo, setModelo] = useState("iPhone 14");
  const [falla, setFalla] = useState("La batería dura poco.");
  const [ingreso, setIngreso] = useState<Ingreso>(ingresoInicial);

  const esRecepcion = actor?.rol === "RECEPCION";
  const dniNormalizado = normalizarDni(dni);
  const dniInvalido = dni.trim() !== "" && dniNormalizado === null;
  const completo =
    nombreApellido.trim() && telefono.trim() && marca && modelo && falla && !dniInvalido;
  const puedeBuscar =
    actor !== null &&
    (actor.rol === "RECEPCION" || actor.rol === "ADMINISTRADOR") &&
    dniNormalizado !== null &&
    !buscando;

  async function buscar(externa: boolean): Promise<BusquedaCliente | null> {
    if (!actor || !dniNormalizado) return null;
    setBuscando(true);
    setErrorBusqueda(null);
    setResultado(null);
    try {
      const encontrado = await buscarClientePorDni(dniNormalizado, actor.id, externa);
      setBuscadoPara(dniNormalizado);
      // La comprobación previa al alta solo se muestra si ya es cliente.
      if (externa || encontrado.origen === "BASE") setResultado(encontrado);
      return encontrado;
    } catch (fallo) {
      // Una búsqueda fallida nunca impide crear la Orden.
      if (externa) {
        setErrorBusqueda(
          fallo instanceof ApiError
            ? fallo.message
            : "No se pudo buscar. Cargá los datos a mano.",
        );
      }
      return null;
    } finally {
      setBuscando(false);
    }
  }

  async function crear() {
    if (!actor) return;
    // Un DNI que ya es de un cliente se reutiliza: antes de crear se busca
    // en nuestra base (si no se buscó) y, si ya existe, se muestra para
    // elegirlo. Si la búsqueda falla, se crea igual (el backend tampoco
    // deja duplicar).
    if (dniNormalizado && !clienteId && buscadoPara !== dniNormalizado) {
      const encontrado = await buscar(false);
      if (encontrado?.origen === "BASE") return;
    }
    const { identificadores, recepcion } = datosDeIngreso(ingreso);
    onCrear({
      usuario_id: actor.id,
      cliente: {
        nombre_apellido: nombreApellido.trim(),
        telefono: telefono.trim(),
        dni: dniNormalizado,
        ...(clienteId ? { id: clienteId } : {}),
      },
      equipo: {
        marca,
        modelo,
        falla_reportada: falla,
        ...identificadores,
      },
      recepcion,
    });
  }

  return (
    <div>
      {!esRecepcion && (
        <p
          style={{
            margin: "0 0 0.6rem",
            fontSize: "0.8rem",
            color: colores.alerta,
          }}
        >
          La crea Recepción: elegí ese usuario arriba para cargarla.
        </p>
      )}
      <BusquedaPorDni
        dni={dni}
        dniInvalido={dniInvalido}
        puedeBuscar={puedeBuscar}
        buscando={buscando}
        resultado={resultado}
        error={errorBusqueda}
        clienteId={clienteId}
        onDni={(valor) => {
          setDni(valor);
          // Otro DNI ya no es el cliente elegido.
          setClienteId(null);
          setResultado(null);
          setErrorBusqueda(null);
        }}
        onBuscar={() => void buscar(true)}
        onUsar={(datos) => {
          setNombreApellido(datos.nombreApellido);
          if (datos.telefono) setTelefono(datos.telefono);
          setClienteId(datos.clienteId);
          setResultado(null);
        }}
        onDescartar={() => setResultado(null)}
        onDesvincular={() => setClienteId(null)}
      />
      <Campo etiqueta="Nombre y apellido">
        <input
          value={nombreApellido}
          autoComplete="off"
          onChange={(evento) => setNombreApellido(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Teléfono">
        <input
          value={telefono}
          onChange={(evento) => setTelefono(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Marca">
        <input
          value={marca}
          onChange={(evento) => setMarca(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Modelo">
        <input
          value={modelo}
          onChange={(evento) => setModelo(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Falla declarada por el cliente">
        <input
          value={falla}
          onChange={(evento) => setFalla(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <CamposIngreso ingreso={ingreso} clienteExterno onCambiar={setIngreso} />
      {!nombreApellido.trim() && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.alerta }}>
          Falta el nombre y apellido del cliente.
        </p>
      )}
      <Boton
        disabled={!esRecepcion || ocupado || buscando || !completo || !actor}
        onClick={() => void crear()}
      >
        Crear Orden
      </Boton>
    </div>
  );
}

/** Campos del alta de equipo RT interno (dentro de "Nueva Orden"). */
export function FormularioNuevaOrdenRt({
  actor,
  ocupado,
  onCrear,
}: {
  actor: Usuario | null;
  ocupado: boolean;
  onCrear: (datos: DatosNuevaOrdenRt) => void;
}) {
  const [marca, setMarca] = useState("Motorola");
  const [modelo, setModelo] = useState("Moto G84");
  const [falla, setFalla] = useState("No enciende.");
  const [referenciaRt, setReferenciaRt] = useState("RT-INGRESO-0001");
  const [ingreso, setIngreso] = useState<Ingreso>(ingresoInicial);

  const esRecepcion = actor?.rol === "RECEPCION";
  const completo = marca && modelo && falla && referenciaRt;

  return (
    <div>
      {!esRecepcion && (
        <p
          style={{
            margin: "0 0 0.6rem",
            fontSize: "0.8rem",
            color: colores.alerta,
          }}
        >
          La crea Recepción: elegí ese usuario arriba para cargarla.
        </p>
      )}
      <Campo etiqueta="Referencia de Gestión RT">
        <input
          value={referenciaRt}
          onChange={(evento) => setReferenciaRt(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Marca">
        <input
          value={marca}
          onChange={(evento) => setMarca(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Modelo">
        <input
          value={modelo}
          onChange={(evento) => setModelo(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Falla reportada">
        <input
          value={falla}
          onChange={(evento) => setFalla(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <CamposIngreso ingreso={ingreso} onCambiar={setIngreso} />
      <Boton
        disabled={!esRecepcion || ocupado || !completo || !actor}
        onClick={() => {
          if (!actor) return;
          const { identificadores, recepcion } = datosDeIngreso(ingreso);
          onCrear({
            usuario_id: actor.id,
            equipo: {
              marca,
              modelo,
              falla_reportada: falla,
              ...identificadores,
            },
            referencia_rt: referenciaRt,
            recepcion,
          });
        }}
      >
        Crear Orden RT
      </Boton>
    </div>
  );
}

export function SelectorActor({
  usuarios,
  actorId,
  onCambiar,
}: {
  usuarios: Usuario[];
  actorId: string;
  onCambiar: (usuarioId: string) => void;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        gap: "0.5rem",
        maxWidth: "100%",
      }}
    >
      <span
        title="Modo demostración: se elige el usuario, sin inicio de sesión. El servidor valida los permisos de cada acción."
        style={{
          fontSize: "0.8rem",
          color: colores.suave,
          whiteSpace: "nowrap",
        }}
      >
        Usuario (modo demo)
      </span>
      {/* Se achica antes de pasar a otra línea (pantallas angostas). */}
      <select
        value={actorId}
        onChange={(evento) => onCambiar(evento.target.value)}
        style={{
          ...estiloInput,
          width: "auto",
          minWidth: 0,
          flex: "0 1 auto",
        }}
      >
        {usuarios.map((usuario) => (
          <option key={usuario.id} value={usuario.id}>
            {usuario.nombre} · {ROL[usuario.rol] ?? usuario.rol}
          </option>
        ))}
      </select>
    </div>
  );
}
