/**
 * Categorías de insumos y fabricantes de repuestos (DEC-AJ-14).
 *
 * - Categorías de dos niveles: una categoría («Baterías», «Módulos») y sus
 *   subcategorías («Módulos › OLED»). El nivel y la categoría se eligen en
 *   el alta y no cambian.
 * - Fabricantes: la marca del repuesto, distinta de la del equipo. No
 *   cambia el Tipo de Reparación ni el precio de venta.
 * - Alta y edición en una ventana, sin campos de código (CAT-NNN y FAB-NNN
 *   los asigna la API). No se borran: se dan de baja, y los insumos que ya
 *   los tienen los conservan.
 * - Con el permiso de insumos (INSUMO_GESTIONAR); en el modo JSON, de solo
 *   lectura.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/clasificacionInsumos";
import type { ClasificacionAdmin } from "../../api/clasificacionInsumos";
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
  type CategoriaInsumo,
  type FabricanteRepuesto,
  nombreRepetido,
  opcionesCategoria,
} from "../inventario/clasificacion";
import { conElemento } from "./listados";

function useClasificacionAdmin() {
  const [datos, setDatos] = useState<ClasificacionAdmin | null>(null);
  const comando = useComando();
  const { setError } = comando;
  const cargar = useCallback(() => {
    api
      .obtenerClasificacionAdmin()
      .then(setDatos)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);
  return { datos, setDatos, ...comando };
}

const celda = { padding: "0.25rem 0.5rem" } as const;

// --- Categorías ----------------------------------------------------------------

interface EdicionCategoria {
  categoria: CategoriaInsumo | null;
  nombre: string;
  padre: string;
}

export function CategoriasInsumoAdmin({ actor }: { actor: Usuario }) {
  const { datos, setDatos, error, setError, aviso, setAviso, ocupado, ejecutar } =
    useClasificacionAdmin();
  const [ventana, setVentana] = useState<EdicionCategoria | null>(null);
  const [resaltado, setResaltado] = useState<string | null>(null);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const editable = datos.editable;

  const guardada = (categoria: CategoriaInsumo, texto: string) => {
    setDatos({ ...datos, categorias: conElemento(datos.categorias, categoria, (c) => c.id) });
    setResaltado(categoria.id);
    setError(null);
    setAviso(texto);
  };
  const raices = datos.categorias.filter((c) => c.padre_id === null);
  const pares = ventana
    ? datos.categorias.filter(
        (c) => c.padre_id === (ventana.categoria ? ventana.categoria.padre_id : ventana.padre || null),
      )
    : [];
  const repetida = ventana && nombreRepetido(pares, ventana.nombre, ventana.categoria?.id);
  const listo = ventana !== null && ventana.nombre.trim() !== "" && !repetida;
  const porId = new Map(datos.categorias.map((c) => [c.id, c]));

  return (
    <section>
      <EncabezadoListado
        titulo="Categorías de insumos"
        nuevo={editable ? "Nueva categoría" : undefined}
        onNuevo={() => setVentana({ categoria: null, nombre: "", padre: "" })}
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Dos niveles: categoría (por ejemplo «Baterías» o «Módulos») y subcategoría («Módulos ›
        OLED»). Cada insumo sigue siendo un repuesto con su propio stock; la clasificación sirve
        para buscar, filtrar y elegir piezas. Una categoría no se borra: se da de baja y los
        insumos que la tienen la conservan.
        {!editable && " En este entorno (modo JSON) es de solo lectura."}
      </p>
      <Mensajes error={error} aviso={aviso} />
      {datos.categorias.length === 0 ? (
        <p style={{ fontSize: "0.85rem", color: colores.suave }}>Todavía no hay categorías.</p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 460 }}>
            <thead>
              <tr>
                {["Código", "Categoría", "Vigente", ""].map((t) => (
                  <th key={t} style={{ ...celda, textAlign: "left" }}>
                    {t}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {opcionesCategoria(datos).map((opcion) => {
                const categoria = porId.get(opcion.id)!;
                return (
                  <tr key={opcion.id} style={{ background: resaltado === opcion.id ? "#eff6ff" : undefined }}>
                    <td style={celda}>{opcion.id}</td>
                    <td style={{ ...celda, paddingLeft: opcion.esSubcategoria ? "1.5rem" : celda.padding }}>
                      {opcion.esSubcategoria ? `› ${categoria.nombre}` : <strong>{categoria.nombre}</strong>}
                      {categoria.activo && !opcion.activo && (
                        <span style={{ color: colores.suave }}> (su categoría está de baja)</span>
                      )}
                    </td>
                    <td style={{ ...celda, textAlign: "center" }}>
                      <input
                        type="checkbox"
                        aria-label={`${categoria.nombre}: vigente`}
                        checked={categoria.activo}
                        disabled={!editable || ocupado}
                        onChange={(e) =>
                          void ejecutar(
                            () =>
                              api.editarCategoria(actor.id, categoria.id, {
                                nombre: categoria.nombre,
                                activo: e.target.checked,
                              }),
                            `Se guardó ${categoria.id}.`,
                          ).then((c) => c && guardada(c, `Se guardó ${c.id}.`))
                        }
                      />
                    </td>
                    <td style={celda}>
                      {editable && (
                        <span style={{ display: "flex", gap: "0.3rem" }}>
                          <Boton
                            variante="secundario"
                            disabled={ocupado}
                            onClick={() => setVentana({ categoria, nombre: categoria.nombre, padre: "" })}
                          >
                            Editar
                          </Boton>
                          {!opcion.esSubcategoria && opcion.activo && (
                            <Boton
                              variante="secundario"
                              disabled={ocupado}
                              onClick={() => setVentana({ categoria: null, nombre: "", padre: categoria.id })}
                            >
                              Subcategoría
                            </Boton>
                          )}
                        </span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {ventana && (
        <FormularioModal
          titulo={
            ventana.categoria
              ? `Editar ${ventana.categoria.id}`
              : ventana.padre
                ? "Nueva subcategoría"
                : "Nueva categoría"
          }
          textoConfirmar={ventana.categoria ? "Guardar" : "Crear"}
          listo={listo}
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const resultado = ventana.categoria
              ? await api.editarCategoria(actor.id, ventana.categoria.id, {
                  nombre: ventana.nombre.trim(),
                  activo: ventana.categoria.activo,
                })
              : await api.crearCategoria(actor.id, {
                  nombre: ventana.nombre.trim(),
                  padre_id: ventana.padre || null,
                  activo: true,
                });
            guardada(
              resultado,
              ventana.categoria ? `Se guardó ${resultado.id}.` : `Se creó ${resultado.id} ${resultado.nombre}.`,
            );
          }}
        >
          {!ventana.categoria && (
            <Campo etiqueta="Nivel">
              <select
                value={ventana.padre}
                onChange={(e) => setVentana({ ...ventana, padre: e.target.value })}
                style={estiloInput}
              >
                <option value="">Categoría (primer nivel)</option>
                {raices
                  .filter((r) => r.activo)
                  .map((r) => (
                    <option key={r.id} value={r.id}>
                      Subcategoría de {r.nombre}
                    </option>
                  ))}
              </select>
            </Campo>
          )}
          <Campo etiqueta="Nombre">
            <input
              value={ventana.nombre}
              onChange={(e) => setVentana({ ...ventana, nombre: e.target.value })}
              placeholder={ventana.padre || ventana.categoria?.padre_id ? "OLED" : "Baterías"}
              style={estiloInput}
            />
          </Campo>
          <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: repetida ? colores.error : colores.suave }}>
            {repetida
              ? `Ya existe ${repetida.id} «${repetida.nombre}» en el mismo nivel.`
              : ventana.categoria
                ? "El código, el nivel y la categoría no cambian."
                : "El código se asigna al guardar."}
          </p>
        </FormularioModal>
      )}
    </section>
  );
}

// --- Fabricantes ------------------------------------------------------------------

export function FabricantesRepuestoAdmin({ actor }: { actor: Usuario }) {
  const { datos, setDatos, error, setError, aviso, setAviso, ocupado, ejecutar } =
    useClasificacionAdmin();
  const [ventana, setVentana] = useState<{ fabricante: FabricanteRepuesto | null; nombre: string } | null>(
    null,
  );
  const [resaltado, setResaltado] = useState<string | null>(null);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const editable = datos.editable;

  const guardado = (fabricante: FabricanteRepuesto, texto: string) => {
    setDatos({ ...datos, fabricantes: conElemento(datos.fabricantes, fabricante, (f) => f.id) });
    setResaltado(fabricante.id);
    setError(null);
    setAviso(texto);
  };
  const repetido = ventana && nombreRepetido(datos.fabricantes, ventana.nombre, ventana.fabricante?.id);
  const listo = ventana !== null && ventana.nombre.trim() !== "" && !repetido;

  return (
    <section>
      <EncabezadoListado
        titulo="Fabricantes de repuestos"
        nuevo={editable ? "Nuevo fabricante" : undefined}
        onNuevo={() => setVentana({ fabricante: null, nombre: "" })}
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        La marca o el fabricante del repuesto, distinto de la marca del equipo. No cambia el Tipo de
        Reparación ni el precio de venta: el costo es de cada insumo. No se borra: se da de baja.
        {!editable && " En este entorno (modo JSON) es de solo lectura."}
      </p>
      <Mensajes error={error} aviso={aviso} />
      {datos.fabricantes.length === 0 ? (
        <p style={{ fontSize: "0.85rem", color: colores.suave }}>Todavía no hay fabricantes.</p>
      ) : (
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 380 }}>
          <thead>
            <tr>
              {["Código", "Fabricante", "Vigente", ""].map((t) => (
                <th key={t} style={{ ...celda, textAlign: "left" }}>
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {datos.fabricantes.map((fabricante) => (
              <tr key={fabricante.id} style={{ background: resaltado === fabricante.id ? "#eff6ff" : undefined }}>
                <td style={celda}>{fabricante.id}</td>
                <td style={celda}>{fabricante.nombre}</td>
                <td style={{ ...celda, textAlign: "center" }}>
                  <input
                    type="checkbox"
                    aria-label={`${fabricante.nombre}: vigente`}
                    checked={fabricante.activo}
                    disabled={!editable || ocupado}
                    onChange={(e) =>
                      void ejecutar(
                        () =>
                          api.editarFabricante(actor.id, fabricante.id, {
                            nombre: fabricante.nombre,
                            activo: e.target.checked,
                          }),
                        `Se guardó ${fabricante.id}.`,
                      ).then((f) => f && guardado(f, `Se guardó ${f.id}.`))
                    }
                  />
                </td>
                <td style={celda}>
                  {editable && (
                    <Boton
                      variante="secundario"
                      disabled={ocupado}
                      onClick={() => setVentana({ fabricante, nombre: fabricante.nombre })}
                    >
                      Editar
                    </Boton>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {ventana && (
        <FormularioModal
          titulo={ventana.fabricante ? `Editar ${ventana.fabricante.id}` : "Nuevo fabricante"}
          textoConfirmar={ventana.fabricante ? "Guardar" : "Crear fabricante"}
          listo={listo}
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const datosFabricante = {
              nombre: ventana.nombre.trim(),
              activo: ventana.fabricante?.activo ?? true,
            };
            const resultado = ventana.fabricante
              ? await api.editarFabricante(actor.id, ventana.fabricante.id, datosFabricante)
              : await api.crearFabricante(actor.id, datosFabricante);
            guardado(
              resultado,
              ventana.fabricante ? `Se guardó ${resultado.id}.` : `Se creó ${resultado.id} ${resultado.nombre}.`,
            );
          }}
        >
          <Campo etiqueta="Nombre">
            <input
              value={ventana.nombre}
              onChange={(e) => setVentana({ ...ventana, nombre: e.target.value })}
              style={estiloInput}
            />
          </Campo>
          <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: repetido ? colores.error : colores.suave }}>
            {repetido
              ? `Ya existe ${repetido.id} «${repetido.nombre}».`
              : ventana.fabricante
                ? "El código no cambia."
                : "El código se asigna al guardar."}
          </p>
        </FormularioModal>
      )}
    </section>
  );
}
