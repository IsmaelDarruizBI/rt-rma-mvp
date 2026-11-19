/**
 * Proveedores (DEC-MI-09; Configuración v2, CFG-03 y CFG-04): datos
 * básicos con auditoría, con el permiso PROVEEDOR_GESTIONAR. Alta y edición
 * en una ventana; el código lo genera la API (PRV-NNNN). No se borran: se
 * desactivan. Solo sobre PostgreSQL.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/compras";
import type { Proveedor } from "../../api/compras";
import {
  EncabezadoListado,
  FormularioModal,
  Mensajes,
  mensajeDe,
  useComando,
} from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";
import { conElemento } from "./listados";

type Editable = Omit<Proveedor, "id"> & { id?: string };

const VACIO: Editable = {
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
  const [editado, setEditado] = useState<Editable | null>(null);
  const [resaltado, setResaltado] = useState<string | null>(null);
  const { error, setError, aviso, setAviso } = useComando();

  const cargar = useCallback(() => {
    api
      .proveedoresAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  if (!datos.editable) {
    return (
      <p style={{ color: colores.suave }}>
        Los proveedores se administran sobre la base PostgreSQL.
      </p>
    );
  }

  return (
    <section>
      <EncabezadoListado
        titulo="Proveedores"
        nuevo="Nuevo proveedor"
        onNuevo={() => setEditado({ ...VACIO })}
      />
      <Mensajes error={error} aviso={aviso} />
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {datos.proveedores.map((p) => (
          <li
            key={p.id}
            style={{ marginBottom: "0.3rem", background: resaltado === p.id ? "#eff6ff" : undefined }}
          >
            <strong>{p.nombre}</strong> ({p.id}
            {p.activo ? "" : " · no vigente"})
            {p.telefono ? ` · ${p.telefono}` : ""}
            {p.email ? ` · ${p.email}` : ""}
            {p.contacto ? ` · ${p.contacto}` : ""}{" "}
            <Boton variante="secundario" onClick={() => setEditado({ ...p })}>
              Editar
            </Boton>
          </li>
        ))}
        {datos.proveedores.length === 0 && <li style={{ color: colores.suave }}>Sin proveedores.</li>}
      </ul>
      {editado && (
        <FormularioModal
          titulo={editado.id ? `Editar ${editado.id}` : "Nuevo proveedor"}
          textoConfirmar={editado.id ? "Guardar" : "Crear proveedor"}
          listo={editado.nombre.trim() !== ""}
          onCerrar={() => setEditado(null)}
          onConfirmar={async () => {
            const proveedor = await api.guardarProveedor(actor.id, editado);
            setDatos({
              ...datos,
              proveedores: conElemento(datos.proveedores, proveedor, (x) => x.id),
            });
            setResaltado(proveedor.id);
            setError(null);
            setAviso(
              editado.id
                ? `Se guardó el proveedor ${proveedor.nombre} (${proveedor.id}).`
                : `Se creó el proveedor ${proveedor.id} ${proveedor.nombre}.`,
            );
          }}
        >
          {CAMPOS.map(([campo, etiqueta]) => (
            <Campo key={campo} etiqueta={etiqueta}>
              <input
                value={editado[campo] ?? ""}
                onChange={(e) => setEditado({ ...editado, [campo]: e.target.value })}
                style={estiloInput}
              />
            </Campo>
          ))}
          <label style={{ display: "flex", gap: "0.4rem", margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={editado.activo}
              onChange={(e) => setEditado({ ...editado, activo: e.target.checked })}
            />
            Vigente
          </label>
          {!editado.id && (
            <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
              El código se asigna al guardar.
            </p>
          )}
        </FormularioModal>
      )}
    </section>
  );
}
