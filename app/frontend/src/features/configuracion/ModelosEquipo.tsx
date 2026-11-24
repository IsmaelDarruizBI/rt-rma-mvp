/**
 * Modelos de equipo (DEC-AJ-12, D-12.5): el catálogo técnico de RMA.
 *
 * - Alta y edición en una ventana, sin campo de código: la API lo genera
 *   (MOD-NNNN, después del mayor existente) y la confirmación lo informa.
 * - Un modelo no se borra: se desactiva y deja de ofrecerse en el ingreso.
 * - No se admite otra marca + modelo + variante igual (la API lo valida;
 *   la pantalla avisa antes).
 * - Con permiso MODELO_EQUIPO_GESTIONAR (Administración por defecto); en el
 *   modo JSON es de solo lectura.
 * El catálogo de productos de Ventas es otra cosa y sigue siendo de solo
 * lectura.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import type { DatosModelo, ModeloAdmin, ModelosAdmin } from "../../api/configuracion";
import {
  EncabezadoListado,
  FormularioModal,
  Mensajes,
  mensajeDe,
  useComando,
} from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";
import {
  modeloRepetido,
  nombreModelo,
  numerosDeModelo,
} from "../ordenes-reparacion/precioModelo";
import { conElemento } from "./listados";

interface Edicion {
  modelo: ModeloAdmin | null;
  marca: string;
  nombre: string;
  variante: string;
  numeros: string;
  activo: boolean;
}

function edicionDe(modelo: ModeloAdmin | null): Edicion {
  return {
    modelo,
    marca: modelo?.marca ?? "Apple",
    nombre: modelo?.modelo ?? "",
    variante: modelo?.variante ?? "",
    numeros: (modelo?.numeros_modelo ?? []).join(", "),
    activo: modelo?.activo ?? true,
  };
}

function datosDe(edicion: Edicion): DatosModelo {
  return {
    marca: edicion.marca.trim(),
    modelo: edicion.nombre.trim(),
    variante: edicion.variante.trim() || null,
    numeros_modelo: numerosDeModelo(edicion.numeros),
    activo: edicion.activo,
  };
}

export function ModelosEquipoAdmin({ actor }: { actor: Usuario }) {
  const [lista, setLista] = useState<ModelosAdmin | null>(null);
  const [ventana, setVentana] = useState<Edicion | null>(null);
  const [filtro, setFiltro] = useState("");
  const [resaltado, setResaltado] = useState<string | null>(null);
  const { error, setError, aviso, setAviso, ocupado, ejecutar } = useComando();

  const cargar = useCallback(() => {
    api
      .obtenerModelosAdmin()
      .then(setLista)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!lista) return <Mensajes error={error} aviso={aviso} />;
  const editable = lista.editable;

  const guardado = (modelo: ModeloAdmin, texto: string) => {
    setLista({ ...lista, modelos: conElemento(lista.modelos, modelo, (m) => m.id) });
    setResaltado(modelo.id);
    setError(null);
    setAviso(texto);
  };

  const repetido =
    ventana &&
    modeloRepetido(
      lista.modelos,
      { marca: ventana.marca, modelo: ventana.nombre, variante: ventana.variante || null },
      ventana.modelo?.id,
    );
  const listo =
    ventana !== null &&
    ventana.marca.trim() !== "" &&
    ventana.nombre.trim() !== "" &&
    !repetido;
  const visibles = lista.modelos.filter((m) =>
    m.nombre.toLowerCase().includes(filtro.trim().toLowerCase()),
  );

  return (
    <section>
      <EncabezadoListado
        titulo="Modelos de equipo"
        nuevo={editable ? "Nuevo modelo" : undefined}
        onNuevo={() => setVentana(edicionDe(null))}
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        El catálogo técnico que se ofrece al ingresar un equipo y con el que se definen los
        precios por modelo. Un modelo no se borra: se desactiva. Las Órdenes guardan su copia.
        {!editable && " En este entorno (modo JSON) es de solo lectura."}
      </p>
      <Mensajes error={error} aviso={aviso} />
      <Campo etiqueta="Buscar">
        <input value={filtro} onChange={(e) => setFiltro(e.target.value)} style={estiloInput} />
      </Campo>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 520 }}>
          <thead>
            <tr>
              {["Código", "Modelo", "Números de modelo", "Vigente", ""].map((t) => (
                <th key={t} style={{ textAlign: "left", padding: "0.25rem 0.5rem" }}>
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibles.map((modelo) => (
              <tr
                key={modelo.id}
                style={{ background: resaltado === modelo.id ? "#eff6ff" : undefined }}
              >
                <td style={{ padding: "0.25rem 0.5rem" }}>{modelo.id}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{modelo.nombre}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {modelo.numeros_modelo.join(", ") || "—"}
                </td>
                <td style={{ padding: "0.25rem 0.5rem", textAlign: "center" }}>
                  <input
                    type="checkbox"
                    aria-label={`${modelo.nombre}: vigente`}
                    checked={modelo.activo}
                    disabled={!editable || ocupado}
                    onChange={(e) =>
                      void ejecutar(
                        () =>
                          api.editarModelo(actor.id, modelo.id, {
                            ...datosDe(edicionDe(modelo)),
                            activo: e.target.checked,
                          }),
                        `Se guardó ${modelo.id}.`,
                      ).then((m) => m && guardado(m, `Se guardó ${m.id}.`))
                    }
                  />
                </td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {editable && (
                    <Boton
                      variante="secundario"
                      disabled={ocupado}
                      onClick={() => setVentana(edicionDe(modelo))}
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
          titulo={ventana.modelo ? `Editar ${ventana.modelo.id}` : "Nuevo modelo de equipo"}
          textoConfirmar={ventana.modelo ? "Guardar" : "Crear modelo"}
          listo={listo}
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const datos = datosDe(ventana);
            const resultado = ventana.modelo
              ? await api.editarModelo(actor.id, ventana.modelo.id, datos)
              : await api.crearModelo(actor.id, datos);
            guardado(
              resultado,
              ventana.modelo
                ? `Se guardó ${resultado.id}.`
                : `Se creó ${resultado.id} ${resultado.nombre}.`,
            );
            setVentana(null);
          }}
        >
          <Campo etiqueta="Marca">
            <input
              value={ventana.marca}
              onChange={(e) => setVentana({ ...ventana, marca: e.target.value })}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Modelo">
            <input
              value={ventana.nombre}
              onChange={(e) => setVentana({ ...ventana, nombre: e.target.value })}
              placeholder="iPhone 18"
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Variante (vacía: la versión estándar)">
            <input
              value={ventana.variante}
              onChange={(e) => setVentana({ ...ventana, variante: e.target.value })}
              placeholder="Pro Max"
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Números de modelo del fabricante (opcional, separados por coma)">
            <input
              value={ventana.numeros}
              onChange={(e) => setVentana({ ...ventana, numeros: e.target.value })}
              placeholder="A3001, A3002"
              style={estiloInput}
            />
          </Campo>
          <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
            {repetido
              ? `Ya existe ${repetido.id} (${nombreModelo(repetido)}).`
              : ventana.modelo
                ? "El código no cambia."
                : "El código se asigna al guardar."}
          </p>
        </FormularioModal>
      )}
    </section>
  );
}
