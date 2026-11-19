/**
 * Plantillas de WhatsApp (DEC-MI-08, BR-REP-044; Configuración v2, CFG-08).
 *
 * La interfaz ofrece solo Ingreso de equipo y Equipo listo para retirar
 * (DF-3), aquí y en las acciones de la Orden. Se edita su texto, finalidad
 * y vigencia en una ventana; no se dan de alta plantillas nuevas. Las demás
 * no se borran ni se desactivan: siguen en la base y en la API, y las
 * comunicaciones ya registradas conservan su texto. Solo se admiten las
 * variables de la lista. En la persistencia JSON son de solo lectura.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/comunicaciones";
import type { Finalidad, PlantillaMensaje, Plantillas } from "../../api/comunicaciones";
import { FormularioModal, Mensajes, mensajeDe, useComando } from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";
import { conElemento, esPlantillaVisible } from "./listados";

export function PlantillasMensaje({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<Plantillas | null>(null);
  const [editada, setEditada] = useState<PlantillaMensaje | null>(null);
  const { error, setError, aviso, setAviso } = useComando();

  const cargar = useCallback(() => {
    api
      .listarPlantillasAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const visibles = datos.plantillas.filter(esPlantillaVisible);

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Plantillas de WhatsApp</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Variables:{" "}
        {Object.entries(datos.variables)
          .map(([clave, texto]) => `{${clave}} (${texto})`)
          .join(" · ")}
      </p>
      <Mensajes error={error} aviso={aviso} />
      <ul style={{ paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
        {visibles.map((plantilla) => (
          <li key={plantilla.codigo} style={{ marginBottom: "0.5rem" }}>
            <strong>{plantilla.nombre}</strong> (
            {plantilla.finalidad === "COMERCIAL" ? "comercial" : "operativa"}
            {plantilla.activa ? "" : " · no vigente"})
            <div style={{ color: colores.suave, whiteSpace: "pre-wrap" }}>{plantilla.texto}</div>
            {datos.editable && (
              <Boton variante="secundario" onClick={() => setEditada({ ...plantilla })}>
                Editar
              </Boton>
            )}
          </li>
        ))}
      </ul>
      {editada && (
        <FormularioModal
          titulo={`Editar «${editada.nombre}»`}
          textoConfirmar="Guardar"
          amplio
          listo={editada.nombre.trim() !== "" && editada.texto.trim() !== ""}
          onCerrar={() => setEditada(null)}
          onConfirmar={async () => {
            const guardada = await api.editarPlantilla(actor.id, {
              ...editada,
              nombre: editada.nombre.trim(),
              texto: editada.texto.trim(),
            });
            setDatos({
              ...datos,
              plantillas: conElemento(datos.plantillas, guardada, (p) => p.codigo),
            });
            setError(null);
            setAviso(`Se guardó la plantilla «${guardada.nombre}».`);
          }}
        >
          <Campo etiqueta="Nombre">
            <input
              value={editada.nombre}
              onChange={(e) => setEditada({ ...editada, nombre: e.target.value })}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Finalidad">
            <select
              value={editada.finalidad}
              onChange={(e) => setEditada({ ...editada, finalidad: e.target.value as Finalidad })}
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
              rows={5}
              style={{ ...estiloInput, fontFamily: "inherit" }}
            />
          </Campo>
          <label style={{ display: "flex", gap: "0.4rem", margin: "0 0 0.6rem", fontSize: "0.85rem" }}>
            <input
              type="checkbox"
              checked={editada.activa}
              onChange={(e) => setEditada({ ...editada, activa: e.target.checked })}
            />
            Vigente
          </label>
        </FormularioModal>
      )}
    </section>
  );
}
