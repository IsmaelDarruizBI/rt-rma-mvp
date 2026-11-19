/**
 * Tipos de reparación y Mesas de trabajo (DC23, BR-REP-040; Configuración
 * v2, CFG-03 a CFG-06).
 *
 * - Alta y edición en una ventana, sin campo de código: la API lo genera
 *   (TR-NNN) y la confirmación lo informa.
 * - El precio exige PRECIOS_GESTIONAR (D3): sin él se ve pero no se edita,
 *   y el alta (que fija precio) no se ofrece.
 * - Garantías (CFG-06): solo los plazos con y sin check-in. El plazo
 *   genérico y la política RMA no se muestran ni se envían: la API los
 *   conserva.
 * - El listado se actualiza con lo que devuelve la API, sin recargar.
 * Lo ya registrado en las Órdenes no cambia: cada trabajo guardó su copia.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import type { CatalogoConfigurable, DatosTipo } from "../../api/configuracion";
import {
  EncabezadoListado,
  FormularioModal,
  Mensajes,
  mensajeDe,
  useComando,
} from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput, importe } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { TipoReparacion, Usuario } from "../../types/api";
import { conElemento, precioValido, textoGarantias } from "./listados";

const SOLO_ADMINISTRACION = ["ADMINISTRADOR"];

function datosDe(tipo: TipoReparacion): DatosTipo {
  return {
    nombre: tipo.nombre,
    precio: String(tipo.precio),
    puntaje: tipo.puntaje,
    activo: tipo.activo ?? true,
    garantia_con_checkin: tipo.garantia_con_checkin ?? 90,
    garantia_sin_checkin: tipo.garantia_sin_checkin ?? 30,
  };
}

const NUEVO: DatosTipo = {
  nombre: "",
  precio: "",
  puntaje: 0,
  activo: true,
  garantia_con_checkin: 90,
  garantia_sin_checkin: 30,
};

function CamposTipo({
  datos,
  onCambio,
  editaPrecio,
}: {
  datos: DatosTipo;
  onCambio: (datos: DatosTipo) => void;
  editaPrecio: boolean;
}) {
  const numero = (campo: keyof DatosTipo, etiqueta: string) => (
    <Campo etiqueta={etiqueta}>
      <input
        type="number"
        min={0}
        value={datos[campo] as number}
        onChange={(e) => onCambio({ ...datos, [campo]: Number(e.target.value) })}
        style={estiloInput}
      />
    </Campo>
  );
  return (
    <>
      <Campo etiqueta="Nombre">
        <input
          value={datos.nombre}
          onChange={(e) => onCambio({ ...datos, nombre: e.target.value })}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta={editaPrecio ? "Precio" : "Precio (lo cambia quien gestiona precios)"}>
        <input
          inputMode="decimal"
          value={datos.precio}
          readOnly={!editaPrecio}
          aria-readonly={!editaPrecio}
          onChange={(e) => onCambio({ ...datos, precio: e.target.value })}
          style={{ ...estiloInput, background: editaPrecio ? "#fff" : colores.fondo }}
        />
      </Campo>
      {numero("puntaje", "Puntaje")}
      {numero("garantia_con_checkin", "Garantía con check-in (días)")}
      {numero("garantia_sin_checkin", "Garantía sin check-in (días)")}
    </>
  );
}

export function TiposReparacion({
  actor,
  onCambio,
}: {
  actor: Usuario;
  /** Los tipos cambiaron (el alta de Órdenes los ofrece). */
  onCambio?: () => void;
}) {
  const [catalogo, setCatalogo] = useState<CatalogoConfigurable | null>(null);
  const [ventana, setVentana] = useState<{ tipo: TipoReparacion | null; datos: DatosTipo } | null>(
    null,
  );
  const [resaltado, setResaltado] = useState<string | null>(null);
  const { error, setError, aviso, setAviso, ocupado, ejecutar } = useComando();
  const editaPrecio = puede(actor, "PRECIOS_GESTIONAR", SOLO_ADMINISTRACION);

  const cargar = useCallback(() => {
    api.obtenerCatalogo().then(setCatalogo).catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!catalogo) return <Mensajes error={error} aviso={aviso} />;
  const editable = catalogo.editable;

  const guardado = (tipo: TipoReparacion, texto: string) => {
    setCatalogo({ ...catalogo, tipos: conElemento(catalogo.tipos, tipo, (t) => t.id) });
    setResaltado(tipo.id);
    setError(null);
    setAviso(texto);
    onCambio?.();
  };

  const listo =
    ventana !== null &&
    ventana.datos.nombre.trim() !== "" &&
    precioValido(ventana.datos.precio);

  return (
    <section>
      <EncabezadoListado
        titulo="Tipos de reparación"
        nuevo={editable && editaPrecio ? "Nuevo tipo" : undefined}
        onNuevo={() => setVentana({ tipo: null, datos: NUEVO })}
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Un cambio de precio, puntaje o garantía vale para los trabajos nuevos:
        los ya cargados conservan lo que se les aplicó.
        {!editable && " En este entorno (modo JSON) son de solo lectura."}
      </p>
      <Mensajes error={error} aviso={aviso} />
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 560 }}>
          <thead>
            <tr>
              {["Código", "Nombre", "Precio", "Puntaje", "Garantía (días)", "Vigente", ""].map((t) => (
                <th key={t} style={{ textAlign: "left", padding: "0.25rem 0.5rem" }}>
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {catalogo.tipos.map((tipo) => (
              <tr
                key={tipo.id}
                style={{ background: resaltado === tipo.id ? "#eff6ff" : undefined }}
              >
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.id}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.nombre}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{importe(String(tipo.precio))}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.puntaje}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{textoGarantias(tipo)}</td>
                <td style={{ padding: "0.25rem 0.5rem", textAlign: "center" }}>
                  <input
                    type="checkbox"
                    aria-label={`${tipo.nombre}: vigente`}
                    checked={tipo.activo !== false}
                    disabled={!editable || ocupado}
                    onChange={(e) =>
                      void ejecutar(
                        () =>
                          api.editarTipo(actor.id, tipo.id, {
                            ...datosDe(tipo),
                            activo: e.target.checked,
                          }),
                        `Se guardó ${tipo.id}.`,
                      ).then((t) => t && guardado(t, `Se guardó ${t.id}.`))
                    }
                  />
                </td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {editable && (
                    <Boton
                      variante="secundario"
                      disabled={ocupado}
                      onClick={() => setVentana({ tipo, datos: datosDe(tipo) })}
                    >
                      Editar
                    </Boton>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ventana && (
        <FormularioModal
          titulo={ventana.tipo ? `Editar ${ventana.tipo.id}` : "Nuevo tipo de reparación"}
          textoConfirmar={ventana.tipo ? "Guardar" : "Crear tipo"}
          listo={listo}
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const { tipo, datos } = ventana;
            const limpio = { ...datos, nombre: datos.nombre.trim(), precio: datos.precio.trim() };
            const resultado = tipo
              ? await api.editarTipo(actor.id, tipo.id, limpio)
              : await api.crearTipo(actor.id, limpio);
            guardado(
              resultado,
              tipo ? `Se guardó ${resultado.id}.` : `Se creó ${resultado.id} ${resultado.nombre}.`,
            );
          }}
        >
          <CamposTipo
            datos={ventana.datos}
            editaPrecio={editaPrecio}
            onCambio={(datos) => setVentana({ ...ventana, datos })}
          />
          {!ventana.tipo && (
            <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
              El código se asigna al guardar.
            </p>
          )}
        </FormularioModal>
      )}
    </section>
  );
}

/** Tipos de reparación habilitados en cada Mesa de trabajo (BR-REP-011). */
export function MesasTrabajo({ actor }: { actor: Usuario }) {
  const [catalogo, setCatalogo] = useState<CatalogoConfigurable | null>(null);
  const [mesas, setMesas] = useState<Record<string, string[]>>({});
  const { error, setError, aviso, ocupado, ejecutar } = useComando();

  const cargar = useCallback(() => {
    api
      .obtenerCatalogo()
      .then((datos) => {
        setCatalogo(datos);
        setMesas(Object.fromEntries(datos.mesas.map((m) => [m.id, m.tipos])));
      })
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!catalogo) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !catalogo.editable;

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Mesas de trabajo</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Los tipos de reparación que cada Mesa puede trabajar.
      </p>
      <Mensajes error={error} aviso={aviso} />
      {catalogo.mesas.map((mesa) => (
        <div key={mesa.id} style={{ marginBottom: "0.8rem" }}>
          <strong>
            {mesa.nombre} ({mesa.id})
          </strong>
          <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", margin: "0.3rem 0" }}>
            {catalogo.tipos.map((tipo) => (
              <label key={tipo.id} style={{ fontSize: "0.85rem" }}>
                <input
                  type="checkbox"
                  disabled={bloqueado}
                  checked={(mesas[mesa.id] ?? []).includes(tipo.id)}
                  onChange={(e) =>
                    setMesas({
                      ...mesas,
                      [mesa.id]: e.target.checked
                        ? [...(mesas[mesa.id] ?? []), tipo.id]
                        : (mesas[mesa.id] ?? []).filter((t) => t !== tipo.id),
                    })
                  }
                />{" "}
                {tipo.nombre}
              </label>
            ))}
          </div>
          <Boton
            disabled={bloqueado}
            onClick={() =>
              void ejecutar(
                () => api.guardarTiposDeMesa(actor.id, mesa.id, mesas[mesa.id] ?? []),
                `Se guardaron los tipos de ${mesa.nombre}.`,
              )
            }
          >
            Guardar tipos de la Mesa
          </Boton>
        </div>
      ))}
    </section>
  );
}
