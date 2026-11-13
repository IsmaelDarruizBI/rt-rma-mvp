/**
 * Plantillas de WhatsApp (DEC-MI-08, BR-REP-044). Administración edita el
 * texto, la finalidad y la vigencia; cada cambio queda auditado. Solo se
 * admiten las variables de la lista. Una plantilla comercial exige el
 * consentimiento expreso del cliente para usarse. En la persistencia JSON
 * (demo) son de solo lectura.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/comunicaciones";
import type { Finalidad, PlantillaMensaje, Plantillas } from "../../api/comunicaciones";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";

const mensaje = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

const VACIA: PlantillaMensaje = {
  codigo: "",
  nombre: "",
  finalidad: "OPERATIVA",
  texto: "",
  activa: true,
};

export function PlantillasMensaje({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<Plantillas | null>(null);
  const [editada, setEditada] = useState<PlantillaMensaje | null>(null);
  const [nueva, setNueva] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    api
      .listarPlantillasAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensaje(causa)));
  }, []);
  useEffect(cargar, [cargar]);

  if (!datos) {
    return error ? <p role="alert">{error}</p> : null;
  }
  const bloqueado = ocupado || !datos.editable;

  const guardar = () => {
    if (!editada) return;
    setOcupado(true);
    setError(null);
    setAviso(null);
    (nueva ? api.crearPlantilla : api.editarPlantilla)(actor.id, editada)
      .then(() => {
        setAviso(`Se guardó la plantilla «${editada.nombre}».`);
        setEditada(null);
        setNueva(false);
        cargar();
      })
      .catch((causa: unknown) => setError(mensaje(causa)))
      .finally(() => setOcupado(false));
  };

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Plantillas de WhatsApp</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Variables:{" "}
        {Object.entries(datos.variables)
          .map(([clave, texto]) => `{${clave}} (${texto})`)
          .join(" · ")}
      </p>
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
        {datos.plantillas.map((plantilla) => (
          <li key={plantilla.codigo} style={{ marginBottom: "0.5rem" }}>
            <strong>{plantilla.nombre}</strong> ({plantilla.codigo} ·{" "}
            {plantilla.finalidad === "COMERCIAL" ? "comercial" : "operativa"}
            {plantilla.activa ? "" : " · no vigente"})
            <div style={{ color: colores.suave, whiteSpace: "pre-wrap" }}>
              {plantilla.texto}
            </div>
            {datos.editable && (
              <Boton
                variante="secundario"
                disabled={bloqueado}
                onClick={() => {
                  setEditada({ ...plantilla });
                  setNueva(false);
                }}
              >
                Editar
              </Boton>
            )}
          </li>
        ))}
      </ul>
      {datos.editable && !editada && (
        <Boton
          disabled={bloqueado}
          onClick={() => {
            setEditada({ ...VACIA });
            setNueva(true);
          }}
        >
          Nueva plantilla
        </Boton>
      )}
      {editada && (
        <div style={{ maxWidth: 560, marginTop: "0.6rem" }}>
          {nueva && (
            <Campo etiqueta="Código">
              <input
                value={editada.codigo}
                onChange={(e) => setEditada({ ...editada, codigo: e.target.value })}
                disabled={bloqueado}
                style={estiloInput}
              />
            </Campo>
          )}
          <Campo etiqueta="Nombre">
            <input
              value={editada.nombre}
              onChange={(e) => setEditada({ ...editada, nombre: e.target.value })}
              disabled={bloqueado}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Finalidad">
            <select
              value={editada.finalidad}
              onChange={(e) =>
                setEditada({ ...editada, finalidad: e.target.value as Finalidad })
              }
              disabled={bloqueado}
              style={estiloInput}
            >
              <option value="OPERATIVA">Operativa (avisos de la Orden)</option>
              <option value="COMERCIAL">Comercial (exige consentimiento)</option>
            </select>
          </Campo>
          <Campo etiqueta="Texto">
            <textarea
              value={editada.texto}
              onChange={(e) => setEditada({ ...editada, texto: e.target.value })}
              rows={4}
              disabled={bloqueado}
              style={{ ...estiloInput, fontFamily: "inherit" }}
            />
          </Campo>
          <label style={{ display: "flex", gap: "0.4rem", margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={editada.activa}
              onChange={(e) => setEditada({ ...editada, activa: e.target.checked })}
              disabled={bloqueado}
            />
            Vigente
          </label>
          <div style={{ display: "flex", gap: "0.4rem" }}>
            <Boton
              disabled={
                bloqueado ||
                !editada.nombre.trim() ||
                !editada.texto.trim() ||
                (nueva && !editada.codigo.trim())
              }
              onClick={guardar}
            >
              Guardar
            </Boton>
            <Boton variante="secundario" disabled={ocupado} onClick={() => setEditada(null)}>
              Cancelar
            </Boton>
          </div>
        </div>
      )}
    </section>
  );
}
