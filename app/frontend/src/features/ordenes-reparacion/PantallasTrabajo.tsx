/**
 * Inicio por rol y taller: las bandejas de trabajo.
 *
 * Las arma el backend (`GET /api/work/inbox` y `/api/work/workshop`): qué
 * Órdenes van en cada bandeja, en qué orden y qué puede resolver el
 * usuario de demostración elegido. Acá solo se muestran: cada Orden es un
 * link a su detalle y, en la cola, quien puede tomarla lo hace con el
 * comando de siempre. Entrar a estas pantallas solo lee.
 */

import { type CSSProperties, type ReactNode, useEffect, useState } from "react";

import * as trabajo from "../../api/trabajo";
import {
  Boton,
  Etiqueta,
  Panel,
  colores,
  estiloInput,
  importe,
} from "../../components/ui";
import type {
  Bandeja,
  Bandejas,
  Estacion,
  ItemBandeja,
  Usuario,
} from "../../types/api";
import {
  antiguedadDe,
  estacionPropuesta,
  estadoDeTrabajo,
  lineaDeTarea,
  separarBandejas,
  totalPendiente,
  trabajosDe,
} from "./bandejas";
import { ROL, hace } from "./etiquetas";
import { colorDeSituacion, nombreDe } from "./ListadoOrdenes";
import { hashDe } from "./rutas";

/** A dónde se puede ir desde una bandeja, además de cada Orden. */
type Destino = "nueva" | "taller" | "inventario";

/** Bandejas donde importa la cuenta de la Orden. */
const DE_DINERO = ["COBROS", "CREDITO", "SALDOS"];

/** Las bandejas del usuario; se vuelven a pedir si cambia o con `recarga`. */
function useBandejas(
  vista: "inicio" | "taller",
  usuarioId: string,
  recarga: number,
): { datos: Bandejas | null; error: string | null } {
  const [datos, setDatos] = useState<Bandejas | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!usuarioId) return;
    let vigente = true;
    setError(null);
    const pedir =
      vista === "inicio" ? trabajo.obtenerBandejas : trabajo.obtenerTaller;
    pedir(usuarioId)
      .then((respuesta) => vigente && setDatos(respuesta))
      .catch(
        (fallo) =>
          vigente &&
          setError(fallo instanceof Error ? fallo.message : String(fallo)),
      );
    return () => {
      vigente = false;
    };
  }, [vista, usuarioId, recarga]);
  // Mientras llegan las del usuario recién elegido no se muestran otras.
  return { datos: datos?.usuario_id === usuarioId ? datos : null, error };
}

interface Comunes {
  usuarios: Usuario[];
  estaciones: Estacion[];
  onIr: (destino: Destino) => void;
}

/** `#/inicio`: lo que necesita la atención del usuario, según su rol. */
export function PantallaInicio({
  actor,
  usuarios,
  estaciones,
  onIr,
}: Comunes & { actor: Usuario | null }) {
  const { datos, error } = useBandejas("inicio", actor?.id ?? "", 0);
  if (error) return <AvisoDeCarga texto={`No se pudo cargar: ${error}`} />;
  if (!actor || !datos) return <AvisoDeCarga texto="Cargando tus tareas…" />;

  const { pendientes, vacias, seguimiento } = separarBandejas(datos.bandejas);
  const total = totalPendiente(datos.bandejas);
  return (
    <div style={columna}>
      <Panel>
        <div style={cabecera}>
          <div>
            <h2 style={{ margin: 0, fontSize: "1.2rem" }}>Inicio</h2>
            <p style={{ margin: "0.15rem 0 0", color: colores.suave }}>
              {actor.nombre} · {ROL[actor.rol]} ·{" "}
              {total === 0
                ? "sin tareas pendientes"
                : `${total} pendiente${total === 1 ? "" : "s"}`}
            </p>
          </div>
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
            {datos.rol === "RECEPCION" && (
              <Boton onClick={() => onIr("nueva")}>+ Nueva orden</Boton>
            )}
            {(datos.rol === "TECNICO" || datos.rol === "COORDINADOR_RMA") && (
              <Boton variante="secundario" onClick={() => onIr("taller")}>
                Ver el taller
              </Boton>
            )}
          </div>
        </div>
      </Panel>

      {pendientes.length === 0 ? (
        <Panel>
          <p style={{ margin: 0 }}>No tenés tareas pendientes.</p>
        </Panel>
      ) : (
        <div style={grilla}>
          {pendientes.map((bandeja) => (
            <TarjetaBandeja
              key={bandeja.codigo}
              bandeja={bandeja}
              usuarios={usuarios}
              estaciones={estaciones}
              onIr={onIr}
            />
          ))}
        </div>
      )}

      {vacias.length > 0 && (
        <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
          Sin pendientes: {vacias.map((bandeja) => bandeja.titulo).join(" · ")}
          .
        </p>
      )}

      {seguimiento.map((bandeja) => (
        <details key={bandeja.codigo} style={plegable}>
          <summary style={{ cursor: "pointer", fontWeight: 600 }}>
            {bandeja.titulo} ({bandeja.cantidad})
          </summary>
          <CuerpoBandeja
            bandeja={bandeja}
            usuarios={usuarios}
            estaciones={estaciones}
            onIr={onIr}
          />
        </details>
      ))}
    </div>
  );
}

/**
 * `#/taller`: primero las Órdenes tomadas por el técnico, después la cola
 * por prioridad (con «Tomar» si le corresponde) y lo que está en el
 * taller. Para los demás roles, la cola y las tomas activas.
 */
export function PantallaTaller({
  actor,
  usuarios,
  estaciones,
  ocupado,
  onIr,
  onTomar,
}: Comunes & {
  actor: Usuario | null;
  ocupado: boolean;
  onTomar: (ordenId: string, estacionId: string) => Promise<void>;
}) {
  const [recarga, setRecarga] = useState(0);
  const { datos, error } = useBandejas("taller", actor?.id ?? "", recarga);
  if (error) return <AvisoDeCarga texto={`No se pudo cargar: ${error}`} />;
  if (!actor || !datos) return <AvisoDeCarga texto="Cargando el taller…" />;

  // Si la toma sale bien se abre la Orden; si no (otro técnico la tomó
  // antes), se vuelve a leer el taller para mostrar lo que hay.
  const tomar = (ordenId: string, estacionId: string) =>
    void onTomar(ordenId, estacionId).then(() => setRecarga((n) => n + 1));

  return (
    <div style={columna}>
      <Panel>
        <h2 style={{ margin: 0, fontSize: "1.2rem" }}>Taller</h2>
        <p style={{ margin: "0.15rem 0 0", color: colores.suave }}>
          {actor.nombre} · {ROL[actor.rol]}
        </p>
      </Panel>
      {datos.bandejas.map((bandeja) => (
        <TarjetaBandeja
          key={bandeja.codigo}
          bandeja={bandeja}
          usuarios={usuarios}
          estaciones={estaciones}
          onIr={onIr}
          ocupado={ocupado}
          onTomar={tomar}
        />
      ))}
    </div>
  );
}

function AvisoDeCarga({ texto }: { texto: string }) {
  return (
    <Panel>
      <p style={{ margin: 0, color: colores.suave }}>{texto}</p>
    </Panel>
  );
}

interface PropsBandeja extends Comunes {
  bandeja: Bandeja;
  ocupado?: boolean;
  onTomar?: (ordenId: string, estacionId: string) => void;
}

function TarjetaBandeja(props: PropsBandeja) {
  const { bandeja } = props;
  return (
    <section
      aria-label={bandeja.titulo}
      style={{
        border: `1px solid ${colores.borde}`,
        borderRadius: 8,
        background: "#fff",
        padding: "0.9rem 1rem",
        minWidth: 0,
      }}
    >
      <div style={cabecera}>
        <h3 style={{ margin: 0, fontSize: "1rem" }}>{bandeja.titulo}</h3>
        <span
          aria-label={`${bandeja.cantidad} en la bandeja`}
          style={{
            minWidth: "1.6rem",
            padding: "0.1rem 0.5rem",
            borderRadius: 999,
            textAlign: "center",
            fontWeight: 700,
            background: bandeja.cantidad ? colores.acento : colores.fondo,
            color: bandeja.cantidad ? "#fff" : colores.suave,
          }}
        >
          {bandeja.cantidad}
        </span>
      </div>
      <CuerpoBandeja {...props} />
    </section>
  );
}

function CuerpoBandeja({
  bandeja,
  usuarios,
  estaciones,
  onIr,
  ocupado = false,
  onTomar,
}: PropsBandeja) {
  return (
    <>
      <p
        style={{
          margin: "0.3rem 0 0.4rem",
          fontSize: "0.8rem",
          color: colores.suave,
        }}
      >
        {bandeja.descripcion}
      </p>
      {bandeja.destino === "INVENTARIO" && (
        <div style={{ marginBottom: "0.4rem" }}>
          <Boton variante="secundario" onClick={() => onIr("inventario")}>
            Ir a Inventario
          </Boton>
        </div>
      )}
      {bandeja.cantidad === 0 && (
        <p style={{ margin: "0.3rem 0 0", fontSize: "0.85rem" }}>
          {bandeja.codigo === "MIS_TOMADAS"
            ? "No tenés órdenes tomadas."
            : "No hay órdenes en esta bandeja."}
        </p>
      )}
      <ul style={lista}>
        {bandeja.ordenes.map((item) => (
          <FilaBandeja
            key={item.orden.id}
            item={item}
            codigo={bandeja.codigo}
            usuarios={usuarios}
            estaciones={estaciones}
            ocupado={ocupado}
            onTomar={onTomar}
          />
        ))}
        {bandeja.insumos.map((insumo) => (
          <li key={insumo.id} style={{ ...fila, padding: "0.55rem 0.2rem" }}>
            <strong>{insumo.nombre}</strong>
            <span style={detalle}>
              Disponible {insumo.disponible} · en stock {insumo.stock_fisico}{" "}
              · reservado {insumo.reservado}
            </span>
          </li>
        ))}
      </ul>
    </>
  );
}

function FilaBandeja({
  item,
  codigo,
  usuarios,
  estaciones,
  ocupado,
  onTomar,
}: {
  item: ItemBandeja;
  codigo: string;
  usuarios: Usuario[];
  estaciones: Estacion[];
  ocupado: boolean;
  onTomar?: (ordenId: string, estacionId: string) => void;
}) {
  const orden = item.orden;
  const linea = lineaDeTarea(item, codigo);
  const edad = antiguedadDe(item, codigo);
  const trabajos = trabajosDe(item, codigo);
  const enCola = codigo === "COLA";
  const enTaller = codigo === "MIS_TOMADAS" || codigo === "EN_TALLER";
  const datos: ReactNode[] = [];
  if (enTaller) {
    const estacion = estaciones.find((e) => e.id === item.estacion_id);
    // En «Mis órdenes tomadas» el técnico es quien mira.
    const quien =
      codigo === "EN_TALLER" && orden.tecnico_id
        ? `Técnico: ${nombreDe(usuarios, orden.tecnico_id)}`
        : null;
    datos.push(
      [quien, estacion ? `Estación: ${estacion.nombre}` : null]
        .filter(Boolean)
        .join(" · "),
    );
    datos.push(
      item.trabajo_en_curso && item.en_curso_desde
        ? `En curso: ${item.trabajo_en_curso} (${hace(item.en_curso_desde)})`
        : "Sin trabajo en curso",
    );
  }
  // El dinero, solo en las bandejas de cobros.
  if (DE_DINERO.includes(codigo)) {
    if (orden.cobrable && Number(orden.saldo) > 0) {
      datos.push(`Saldo: ${importe(orden.saldo)}`);
    }
    if (Number(item.credito) > 0) {
      datos.push(`A favor del cliente: ${importe(item.credito)}`);
    }
  }

  return (
    <li style={fila}>
      <a href={hashDe({ pantalla: "orden", ordenId: orden.id })} style={enlace}>
        <span
          style={{
            display: "flex",
            alignItems: "center",
            gap: "0.4rem",
            flexWrap: "wrap",
          }}
        >
          <strong style={{ color: colores.acento }}>{orden.id}</strong>
          {enCola || enTaller ? (
            orden.prioridad_texto && (
              <Etiqueta color={colores.acento}>{orden.prioridad_texto}</Etiqueta>
            )
          ) : (
            orden.situacion && (
              <Etiqueta color={colorDeSituacion(orden.situacion.codigo)}>
                {orden.situacion.titulo}
              </Etiqueta>
            )
          )}
        </span>
        <span style={{ display: "block", marginTop: "0.15rem" }}>
          {orden.cliente_nombre} · {orden.equipo}
        </span>
        {(enCola || enTaller) && (
          <span style={detalle}>Falla: {item.falla}</span>
        )}
        {linea && (
          <span
            style={{
              display: "block",
              marginTop: "0.15rem",
              fontWeight: item.puede_resolver ? 600 : 400,
              color: item.puede_resolver ? colores.texto : colores.suave,
            }}
          >
            {linea}
          </span>
        )}
        {(enCola || enTaller || codigo === "RECURSOS") &&
          trabajos.length > 0 && (
            <span style={detalle}>
              Trabajos:{" "}
              {trabajos
                .map((t) => `${t.nombre} (${estadoDeTrabajo(t)})`)
                .join(" · ")}
            </span>
          )}
        {item.trabajos
          .filter((t) => t.faltantes.length > 0)
          .map((t) => (
            <span key={t.detalle_id} style={detalle}>
              Faltan para {t.nombre}: {t.faltantes.join(", ")}
            </span>
          ))}
        {datos.map((dato, indice) => (
          <span key={indice} style={detalle}>
            {dato}
          </span>
        ))}
        {item.condiciones.length > 0 && (
          <span style={{ ...detalle, color: colores.alerta }}>
            {item.condiciones.join(" · ")}
          </span>
        )}
        <span style={detalle}>
          {edad.texto} {hace(edad.fecha)}
        </span>
      </a>
      {enCola && item.puede_tomar && onTomar && (
        <FormularioTomar item={item} ocupado={ocupado} onTomar={onTomar} />
      )}
    </li>
  );
}

/** Tomar desde la cola: el mismo comando y la misma estación de siempre. */
function FormularioTomar({
  item,
  ocupado,
  onTomar,
}: {
  item: ItemBandeja;
  ocupado: boolean;
  onTomar: (ordenId: string, estacionId: string) => void;
}) {
  const [estacion, setEstacion] = useState(estacionPropuesta(item));
  if (item.estaciones.length === 0) {
    return (
      <p style={{ ...detalle, color: colores.alerta }}>
        Ninguna estación operativa puede hacer estos trabajos.
      </p>
    );
  }
  return (
    <div
      style={{
        display: "flex",
        gap: "0.5rem",
        alignItems: "center",
        flexWrap: "wrap",
        padding: "0 0.2rem 0.6rem",
      }}
    >
      {item.estaciones.length > 1 ? (
        <select
          aria-label={`Estación para ${item.orden.id}`}
          value={estacion ?? ""}
          onChange={(evento) => setEstacion(evento.target.value)}
          disabled={ocupado}
          style={{ ...estiloInput, width: "auto", maxWidth: "100%" }}
        >
          {item.estaciones.map((opcion) => (
            <option key={opcion.id} value={opcion.id}>
              {opcion.nombre}
            </option>
          ))}
        </select>
      ) : (
        <span style={{ fontSize: "0.85rem" }}>
          Estación: {item.estaciones[0].nombre}
        </span>
      )}
      <Boton
        disabled={ocupado || !estacion}
        onClick={() => estacion && onTomar(item.orden.id, estacion)}
      >
        Tomar
      </Boton>
    </div>
  );
}

const columna: CSSProperties = {
  display: "grid",
  gap: "0.75rem",
  gridTemplateColumns: "minmax(0, 1fr)",
};
const grilla: CSSProperties = {
  display: "grid",
  gap: "0.75rem",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 420px), 1fr))",
  alignItems: "start",
};
const cabecera: CSSProperties = {
  display: "flex",
  justifyContent: "space-between",
  alignItems: "center",
  gap: "0.75rem",
  flexWrap: "wrap",
};
const plegable: CSSProperties = {
  border: `1px solid ${colores.borde}`,
  borderRadius: 8,
  background: "#fff",
  padding: "0.7rem 1rem",
};
const lista: CSSProperties = { margin: 0, padding: 0, listStyle: "none" };
const fila: CSSProperties = { borderTop: `1px solid ${colores.borde}` };
const enlace: CSSProperties = {
  display: "block",
  padding: "0.55rem 0.2rem",
  color: "inherit",
  textDecoration: "none",
};
const detalle: CSSProperties = {
  display: "block",
  marginTop: "0.1rem",
  fontSize: "0.8rem",
  color: colores.suave,
};
