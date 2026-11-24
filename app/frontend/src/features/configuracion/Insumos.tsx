/**
 * Insumos (DEC-MI-13; Configuración v2, CFG-01, CFG-03 y CFG-04).
 *
 * - Alta y edición en una ventana, sin campos de código: la API genera el
 *   identificador (INS-NNN) y usa el mismo como código (D4).
 * - El precio se fija o cambia solo con PRECIOS_GESTIONAR (D3); sin él se
 *   ve y el alta va sin precio.
 * - El control por lote y la vigencia siguen en la fila (una sola acción).
 * - El stock no se edita acá: cambia con movimientos del inventario y un
 *   insumo nuevo empieza en cero. En la persistencia JSON es de solo
 *   lectura.
 * - DEC-AJ-11: el stock mínimo es opcional (vacío: sin mínimo) y se edita
 *   en la ventana, con el permiso de insumos y auditoría. Se compara con el
 *   disponible en Inventario, Inicio y Compras.
 */

import { useCallback, useEffect, useState } from "react";

import { get, post, put } from "../../api/client";
import {
  EncabezadoListado,
  FormularioModal,
  Mensajes,
  mensajeDe,
  useComando,
} from "../../components/FormularioModal";
import { Boton, Campo, colores, estiloInput, importe } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Usuario } from "../../types/api";
import { type ControlInsumo, NOMBRE_CONTROL } from "../inventario/lotes";
import { leerStockMinimo } from "../inventario/stockMinimo";
import { conElemento, precioValido } from "./listados";

interface InsumoAdmin {
  id: string;
  codigo: string;
  nombre: string;
  unidad: string | null;
  stock_fisico: string;
  activo: boolean;
  control: ControlInsumo;
  precio: string | null;
  /** DEC-AJ-11 (ausente en un backend anterior). */
  stock_minimo?: string | null;
}

interface DatosInsumo {
  nombre: string;
  unidad: string;
  control: ControlInsumo;
  precio: string;
  stock_minimo: string;
}

const NUEVO: DatosInsumo = {
  nombre: "",
  unidad: "unidad",
  control: "SIN_LOTE",
  precio: "",
  stock_minimo: "",
};

export function InsumosAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<{ editable: boolean; insumos: InsumoAdmin[] } | null>(null);
  const [ventana, setVentana] = useState<{ insumo: InsumoAdmin | null; datos: DatosInsumo } | null>(
    null,
  );
  const [resaltado, setResaltado] = useState<string | null>(null);
  const { error, setError, aviso, setAviso, ocupado, ejecutar } = useComando();
  const editaPrecio = puede(actor, "PRECIOS_GESTIONAR", ["ADMINISTRADOR"]);

  const cargar = useCallback(() => {
    get<{ editable: boolean; insumos: InsumoAdmin[] }>("/api/admin/supplies")
      .then(setDatos)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;

  const guardado = (insumo: InsumoAdmin, texto: string) => {
    setDatos({ ...datos, insumos: conElemento(datos.insumos, insumo, (i) => i.id) });
    setResaltado(insumo.id);
    setError(null);
    setAviso(texto);
  };

  /** La edición manda todo lo del insumo; el precio, el que tenía si no se cambió. */
  const cuerpo = (insumo: InsumoAdmin, cambios: Partial<InsumoAdmin>) => {
    const editado = { ...insumo, ...cambios };
    return {
      usuario_id: actor.id,
      codigo: editado.codigo,
      nombre: editado.nombre,
      unidad: editado.unidad,
      activo: editado.activo,
      control: editado.control,
      precio: editado.precio,
      stock_minimo: editado.stock_minimo ?? null,
    };
  };

  const editarEnFila = (insumo: InsumoAdmin, cambios: Partial<InsumoAdmin>) =>
    void ejecutar(
      () => put<InsumoAdmin>(`/api/admin/supplies/${encodeURIComponent(insumo.id)}`, cuerpo(insumo, cambios)),
      `Se guardó el insumo ${insumo.id}.`,
    ).then((i) => i && guardado(i, `Se guardó el insumo ${i.id}.`));

  const precio = ventana?.datos.precio.trim() ?? "";
  const minimo = leerStockMinimo(ventana?.datos.stock_minimo ?? "");
  const listo =
    ventana !== null &&
    ventana.datos.nombre.trim() !== "" &&
    (precio === "" || precioValido(precio)) &&
    minimo.error === null;

  return (
    <section>
      <EncabezadoListado
        titulo="Insumos"
        nuevo={datos.editable ? "Nuevo insumo" : undefined}
        onNuevo={() => setVentana({ insumo: null, datos: NUEVO })}
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        El stock cambia solo con movimientos del inventario. Un insumo nuevo
        empieza sin stock. Pasar un insumo a control por lote o serie deja su
        stock actual como «sin lote identificado»; volver atrás exige que sus
        lotes estén en cero.
      </p>
      <Mensajes error={error} aviso={aviso} />
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 620 }}>
          <thead>
            <tr>
              {["Código", "Nombre", "Unidad", "Stock", "Stock mínimo", "Control", "Precio", "Vigente", ""].map((t) => (
                <th key={t} style={{ textAlign: "left", paddingRight: "0.8rem" }}>
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {datos.insumos.map((insumo) => (
              <tr key={insumo.id} style={{ background: resaltado === insumo.id ? "#eff6ff" : undefined }}>
                <td style={{ paddingRight: "0.8rem" }}>
                  {insumo.id}
                  {insumo.codigo !== insumo.id && (
                    <span style={{ color: colores.suave }}> · {insumo.codigo}</span>
                  )}
                </td>
                <td style={{ paddingRight: "0.8rem" }}>{insumo.nombre}</td>
                <td style={{ paddingRight: "0.8rem" }}>{insumo.unidad ?? "—"}</td>
                <td style={{ paddingRight: "0.8rem", textAlign: "right" }}>{insumo.stock_fisico}</td>
                <td style={{ paddingRight: "0.8rem", textAlign: "right" }}>{insumo.stock_minimo ?? "—"}</td>
                <td style={{ paddingRight: "0.8rem" }}>
                  <select
                    value={insumo.control}
                    aria-label={`Control de ${insumo.id}`}
                    disabled={bloqueado}
                    onChange={(e) => editarEnFila(insumo, { control: e.target.value as ControlInsumo })}
                    style={estiloInput}
                  >
                    {(Object.keys(NOMBRE_CONTROL) as ControlInsumo[]).map((c) => (
                      <option key={c} value={c}>
                        {NOMBRE_CONTROL[c]}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{ paddingRight: "0.8rem" }}>
                  {insumo.precio ? importe(insumo.precio) : "—"}
                </td>
                <td style={{ textAlign: "center", paddingRight: "0.8rem" }}>
                  <input
                    type="checkbox"
                    aria-label={`${insumo.id}: vigente`}
                    checked={insumo.activo}
                    disabled={bloqueado}
                    onChange={(e) => editarEnFila(insumo, { activo: e.target.checked })}
                  />
                </td>
                <td>
                  {datos.editable && (
                    <Boton
                      variante="secundario"
                      disabled={bloqueado}
                      onClick={() =>
                        setVentana({
                          insumo,
                          datos: {
                            nombre: insumo.nombre,
                            unidad: insumo.unidad ?? "",
                            control: insumo.control,
                            precio: insumo.precio ?? "",
                            stock_minimo: insumo.stock_minimo ?? "",
                          },
                        })
                      }
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
          titulo={ventana.insumo ? `Editar ${ventana.insumo.id}` : "Nuevo insumo"}
          textoConfirmar={ventana.insumo ? "Guardar" : "Crear insumo"}
          listo={listo}
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const { insumo, datos: d } = ventana;
            const comun = {
              nombre: d.nombre.trim(),
              unidad: d.unidad.trim() || null,
              control: d.control,
              stock_minimo: minimo.valor,
            };
            const resultado = insumo
              ? await put<InsumoAdmin>(
                  `/api/admin/supplies/${encodeURIComponent(insumo.id)}`,
                  cuerpo(insumo, {
                    ...comun,
                    precio: editaPrecio ? precio || null : insumo.precio,
                  }),
                )
              : await post<InsumoAdmin>("/api/admin/supplies", {
                  usuario_id: actor.id,
                  ...comun,
                  ...(editaPrecio && precio ? { precio } : {}),
                });
            guardado(
              resultado,
              insumo
                ? `Se guardó el insumo ${resultado.id}.`
                : `Se creó ${resultado.id} ${resultado.nombre}.`,
            );
          }}
        >
          <Campo etiqueta="Nombre">
            <input
              value={ventana.datos.nombre}
              onChange={(e) => setVentana({ ...ventana, datos: { ...ventana.datos, nombre: e.target.value } })}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Unidad">
            <input
              value={ventana.datos.unidad}
              onChange={(e) => setVentana({ ...ventana, datos: { ...ventana.datos, unidad: e.target.value } })}
              style={estiloInput}
            />
          </Campo>
          {!ventana.insumo && (
            <Campo etiqueta="Control">
              <select
                value={ventana.datos.control}
                onChange={(e) =>
                  setVentana({
                    ...ventana,
                    datos: { ...ventana.datos, control: e.target.value as ControlInsumo },
                  })
                }
                style={estiloInput}
              >
                {(Object.keys(NOMBRE_CONTROL) as ControlInsumo[]).map((c) => (
                  <option key={c} value={c}>
                    {NOMBRE_CONTROL[c]}
                  </option>
                ))}
              </select>
            </Campo>
          )}
          <Campo etiqueta={editaPrecio ? "Precio (opcional)" : "Precio (lo cambia quien gestiona precios)"}>
            <input
              inputMode="decimal"
              value={ventana.datos.precio}
              readOnly={!editaPrecio}
              aria-readonly={!editaPrecio}
              onChange={(e) => setVentana({ ...ventana, datos: { ...ventana.datos, precio: e.target.value } })}
              style={{ ...estiloInput, background: editaPrecio ? "#fff" : colores.fondo }}
            />
          </Campo>
          <Campo etiqueta="Stock mínimo (opcional)">
            <input
              inputMode="decimal"
              value={ventana.datos.stock_minimo}
              placeholder="Sin mínimo"
              aria-invalid={minimo.error !== null}
              onChange={(e) =>
                setVentana({ ...ventana, datos: { ...ventana.datos, stock_minimo: e.target.value } })
              }
              style={estiloInput}
            />
          </Campo>
          <p
            style={{
              margin: "0 0 0.6rem",
              fontSize: "0.8rem",
              color: minimo.error ? colores.error : colores.suave,
            }}
          >
            {minimo.error ??
              "Se compara con el disponible (físico menos reservado). Por debajo, Inventario e Inicio avisan y Compras sugiere reponer hasta el mínimo; nunca se compra solo. Vacío: sin mínimo."}
          </p>
          {!ventana.insumo && (
            <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
              El código se asigna al guardar.
            </p>
          )}
        </FormularioModal>
      )}
    </section>
  );
}
