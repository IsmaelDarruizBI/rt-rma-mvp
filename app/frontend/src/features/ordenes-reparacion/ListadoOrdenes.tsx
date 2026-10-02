/**
 * Listado de Órdenes y alta de una nueva.
 *
 * Crear una Orden es la única acción que no parte de una Orden
 * existente, así que vive acá (PROC-REP-010 -> 030 -> 040, ACT-RECEP).
 * El alta es un único bloque: primero se elige el origen y después se
 * muestra solo el formulario de ese origen.
 */

import { useState } from "react";

import {
  Boton,
  Campo,
  Etiqueta,
  Panel,
  colores,
  estiloInput,
  importe,
} from "../../components/ui";
import type { OrdenResumen, Usuario } from "../../types/api";
import type { DatosNuevaOrden, DatosNuevaOrdenRt } from "../../api/ordenes";

export function ListadoOrdenes({
  ordenes,
  onAbrir,
}: {
  ordenes: OrdenResumen[];
  onAbrir: (ordenId: string) => void;
}) {
  if (ordenes.length === 0) {
    return (
      <Panel titulo="Órdenes">
        <p style={{ margin: 0, color: colores.suave, fontSize: "0.9rem" }}>
          Todavía no hay Órdenes. Creá la primera con el formulario de al
          lado.
        </p>
      </Panel>
    );
  }

  return (
    <Panel titulo={`Órdenes (${ordenes.length})`}>
      <ul style={{ margin: 0, padding: 0, listStyle: "none" }}>
        {ordenes.map((orden) => (
          <li
            key={orden.id}
            style={{ borderBottom: `1px solid ${colores.borde}` }}
          >
            <button
              onClick={() => onAbrir(orden.id)}
              style={{
                width: "100%",
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: "0.75rem",
                padding: "0.6rem 0",
                background: "none",
                border: "none",
                cursor: "pointer",
                font: "inherit",
                textAlign: "left",
              }}
            >
              <span>
                <strong>{orden.id}</strong>
                <span
                  style={{
                    display: "block",
                    fontSize: "0.8rem",
                    color: colores.suave,
                  }}
                >
                  {orden.cliente_nombre} · {orden.equipo}
                </span>
                {orden.origen === "RMA_GARANTIA_REPARACION" && (
                  <span
                    style={{
                      display: "block",
                      fontSize: "0.75rem",
                      color: colores.suave,
                    }}
                  >
                    Garantía RMA de {orden.orden_origen_id ?? "—"}
                  </span>
                )}
              </span>
              <span style={{ textAlign: "right" }}>
                <Etiqueta>{orden.estado_workflow}</Etiqueta>
                <span
                  style={{
                    display: "block",
                    fontSize: "0.8rem",
                    color: colores.suave,
                    marginTop: "0.2rem",
                  }}
                >
                  saldo {importe(orden.saldo)}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ul>
    </Panel>
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
}: {
  actor: Usuario | null;
  ocupado: boolean;
  onCrearClienteExterno: (datos: DatosNuevaOrden) => void;
  onCrearRtInterno: (datos: DatosNuevaOrdenRt) => void;
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
    </Panel>
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
  const [nombre, setNombre] = useState("Cliente de Prueba");
  const [telefono, setTelefono] = useState("341-0000000");
  const [marca, setMarca] = useState("Apple");
  const [modelo, setModelo] = useState("iPhone 14");
  const [falla, setFalla] = useState("La batería dura poco.");

  const esRecepcion = actor?.rol === "RECEPCION";
  const completo = nombre && telefono && marca && modelo && falla;

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
          Requiere el rol RECEPCION. Cambiá el actor demo para crearla.
        </p>
      )}
      <Campo etiqueta="Cliente">
        <input
          value={nombre}
          onChange={(evento) => setNombre(evento.target.value)}
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
      <Campo etiqueta="Falla reportada">
        <input
          value={falla}
          onChange={(evento) => setFalla(evento.target.value)}
          style={estiloInput}
        />
      </Campo>
      <Boton
        disabled={!esRecepcion || ocupado || !completo || !actor}
        onClick={() =>
          actor &&
          onCrear({
            usuario_id: actor.id,
            cliente: { nombre, telefono },
            equipo: {
              marca,
              modelo,
              falla_reportada: falla,
            },
          })
        }
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
          Requiere el rol RECEPCION. Cambiá el actor demo para crearla.
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
      <Boton
        disabled={!esRecepcion || ocupado || !completo || !actor}
        onClick={() =>
          actor &&
          onCrear({
            usuario_id: actor.id,
            equipo: {
              marca,
              modelo,
              falla_reportada: falla,
            },
            referencia_rt: referenciaRt,
          })
        }
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
    <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
      <span style={{ fontSize: "0.8rem", color: colores.suave }}>
        Actor demo
      </span>
      <select
        value={actorId}
        onChange={(evento) => onCambiar(evento.target.value)}
        style={{ ...estiloInput, width: "auto" }}
      >
        {usuarios.map((usuario) => (
          <option key={usuario.id} value={usuario.id}>
            {usuario.nombre} ({usuario.rol})
          </option>
        ))}
      </select>
    </div>
  );
}
