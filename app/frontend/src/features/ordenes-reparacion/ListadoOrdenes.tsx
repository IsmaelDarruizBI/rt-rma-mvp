/**
 * Listado de Órdenes y alta de una nueva.
 *
 * Crear una Orden es la única acción que no parte de una Orden
 * existente, así que vive acá (PROC-REP-010 -> 030 -> 040, ACT-RECEP).
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
    <Panel titulo="Nueva Orden (cliente externo)">
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
    </Panel>
  );
}

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
    <Panel titulo="Nueva Orden (equipo RT interno)">
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
    </Panel>
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
