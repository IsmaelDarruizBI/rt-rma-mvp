/**
 * Proveedores (DEC-MI-09): datos básicos que administra Administración, con
 * auditoría. No se borran: se desactivan. Solo sobre PostgreSQL.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/compras";
import type { Proveedor } from "../../api/compras";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";

const mensaje = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

const VACIO: Omit<Proveedor, "id"> & { id?: string } = {
  nombre: "",
  cuit: null,
  telefono: null,
  email: null,
  contacto: null,
  activo: true,
};

const CAMPOS = [
  ["nombre", "Nombre o razón social"],
  ["cuit", "CUIT (opcional)"],
  ["telefono", "Teléfono (opcional)"],
  ["email", "Correo (opcional)"],
  ["contacto", "Contacto (opcional)"],
] as const;

export function ProveedoresAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<{ editable: boolean; proveedores: Proveedor[] } | null>(null);
  const [editado, setEditado] = useState<typeof VACIO | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    api
      .proveedoresAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensaje(causa)));
  }, []);
  useEffect(cargar, [cargar]);

  if (!datos) return error ? <p role="alert">{error}</p> : null;
  if (!datos.editable) {
    return (
      <p style={{ color: colores.suave }}>
        Los proveedores se administran sobre la base PostgreSQL.
      </p>
    );
  }

  const guardar = () => {
    if (!editado) return;
    setOcupado(true);
    setError(null);
    setAviso(null);
    api
      .guardarProveedor(actor.id, editado)
      .then((p) => {
        setAviso(`Se guardó el proveedor ${p.nombre} (${p.id}).`);
        setEditado(null);
        cargar();
      })
      .catch((causa: unknown) => setError(mensaje(causa)))
      .finally(() => setOcupado(false));
  };

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Proveedores</h3>
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
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {datos.proveedores.map((p) => (
          <li key={p.id} style={{ marginBottom: "0.3rem" }}>
            <strong>{p.nombre}</strong> ({p.id}
            {p.activo ? "" : " · no vigente"})
            {p.telefono ? ` · ${p.telefono}` : ""}
            {p.email ? ` · ${p.email}` : ""}
            {p.contacto ? ` · ${p.contacto}` : ""}{" "}
            <Boton variante="secundario" disabled={ocupado} onClick={() => setEditado({ ...p })}>
              Editar
            </Boton>
          </li>
        ))}
        {datos.proveedores.length === 0 && (
          <li style={{ color: colores.suave }}>Sin proveedores.</li>
        )}
      </ul>
      {!editado && (
        <Boton disabled={ocupado} onClick={() => setEditado({ ...VACIO })}>
          Nuevo proveedor
        </Boton>
      )}
      {editado && (
        <div style={{ maxWidth: 420, marginTop: "0.6rem" }}>
          {CAMPOS.map(([campo, etiqueta]) => (
            <Campo key={campo} etiqueta={etiqueta}>
              <input
                value={editado[campo] ?? ""}
                onChange={(e) => setEditado({ ...editado, [campo]: e.target.value })}
                disabled={ocupado}
                style={estiloInput}
              />
            </Campo>
          ))}
          <label style={{ display: "flex", gap: "0.4rem", margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={editado.activo}
              onChange={(e) => setEditado({ ...editado, activo: e.target.checked })}
              disabled={ocupado}
            />
            Vigente
          </label>
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <Boton disabled={ocupado || !editado.nombre.trim()} onClick={guardar}>
              Guardar
            </Boton>
            <Boton variante="secundario" disabled={ocupado} onClick={() => setEditado(null)}>
              Cancelar
            </Boton>
          </div>
        </div>
      )}
    </section>
  );
}
