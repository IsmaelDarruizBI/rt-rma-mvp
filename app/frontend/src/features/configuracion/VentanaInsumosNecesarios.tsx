/**
 * «Insumos necesarios» de un Tipo de reparación (DEC-AJ-14, D-14.4): los
 * insumos previstos concretos y los requisitos por categoría, en una
 * ventana. Con TIPO_REPARACION_GESTIONAR; de solo lectura en el modo JSON.
 *
 * Se guarda el conjunto completo (lo que se quita deja de preverse; un
 * requisito quitado queda inactivo). Las Órdenes ya cargadas no cambian:
 * un trabajo con la pieza elegida sigue con su elección.
 *
 * Las reglas están en `insumosNecesarios.ts`; la API las vuelve a validar.
 */

import { useState } from "react";

import * as api from "../../api/configuracion";
import type { InsumosNecesariosAdmin } from "../../api/configuracion";
import { FormularioModal } from "../../components/FormularioModal";
import { SelectorInsumo, useClasificacionInsumos } from "../../components/SelectorInsumo";
import { Boton, colores, estiloInput } from "../../components/ui";
import type { TipoReparacion, Usuario } from "../../types/api";
import { etiquetaInsumo, opcionesCategoria } from "../inventario/clasificacion";
import {
  type EditorInsumosNecesarios,
  type PrevistoDeTipo,
  type RequisitoDeTipo,
  editorInicial,
  insumosAgregables,
  moverLinea,
  previstosDelTipo,
  requisitosDelTipo,
  validarInsumosNecesarios,
} from "./insumosNecesarios";

const celda = { padding: "0.2rem 0.4rem", verticalAlign: "middle" } as const;

export function VentanaInsumosNecesarios({
  actor,
  tipo,
  datos,
  editable,
  onCerrar,
  onGuardado,
}: {
  actor: Usuario;
  tipo: TipoReparacion;
  datos: InsumosNecesariosAdmin;
  editable: boolean;
  onCerrar: () => void;
  onGuardado: (previstos: PrevistoDeTipo[], requisitos: RequisitoDeTipo[], cambios: number) => void;
}) {
  const leida = useClasificacionInsumos();
  // Las categorías de esta lectura (activas o no): un Tipo puede conservar
  // una dada de baja.
  const clasificacion = { ...leida, categorias: datos.categorias };
  const [editor, setEditor] = useState<EditorInsumosNecesarios>(() =>
    editorInicial(datos, tipo.id),
  );
  const { pedido, errores, sinCambios } = validarInsumosNecesarios(editor, datos, tipo.id);
  const actuales = previstosDelTipo(datos, tipo.id).map((p) => p.insumo_id);
  const vigentes = requisitosDelTipo(datos, tipo.id).map((r) => r.categoria_id);
  const elegidos = editor.previstos.map((fila) => fila.insumo_id);
  const agregables = insumosAgregables(datos.insumos, actuales).filter(
    (insumo) => !elegidos.includes(insumo.id),
  );
  const bloqueado = !editable;

  const cambiarPrevisto = (indice: number, cantidad: string) =>
    setEditor({
      ...editor,
      previstos: editor.previstos.map((fila, i) => (i === indice ? { ...fila, cantidad } : fila)),
    });
  const cambiarRequisito = (indice: number, cambio: Partial<{ categoria_id: string; cantidad: string }>) =>
    setEditor({
      ...editor,
      requisitos: editor.requisitos.map((fila, i) => (i === indice ? { ...fila, ...cambio } : fila)),
    });

  return (
    <FormularioModal
      amplio
      titulo={`Insumos necesarios · ${tipo.id} ${tipo.nombre}`}
      textoConfirmar={editable ? "Guardar" : "Cerrar"}
      listo={!editable || (pedido !== null && !sinCambios)}
      onCerrar={onCerrar}
      onConfirmar={async () => {
        if (!editable || pedido === null) return onCerrar();
        const resultado = await api.guardarInsumosNecesarios(actor.id, tipo.id, pedido);
        onGuardado(resultado.previstos, resultado.requisitos, resultado.cambios.length);
      }}
    >
      <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
        Los insumos previstos son SKU concretos que sirven para cualquier equipo. Una pieza que
        depende del modelo va como requisito por categoría: en cada trabajo se elige la pieza
        compatible antes de reservar. Los trabajos ya cargados no cambian.
        {!editable && " En este entorno (modo JSON) son de solo lectura."}
      </p>

      <h4 style={{ margin: "0 0 0.3rem" }}>Insumos previstos</h4>
      {editor.previstos.length === 0 ? (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", color: colores.suave }}>
          Ninguno.
        </p>
      ) : (
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", width: "100%", marginBottom: "0.5rem" }}>
          <tbody>
            {editor.previstos.map((fila, indice) => {
              const insumo = datos.insumos.find((i) => i.id === fila.insumo_id);
              const conservado =
                insumo !== undefined &&
                (!insumo.activo || (insumo.modelos_compatibles ?? []).length > 0);
              return (
                <tr key={fila.insumo_id}>
                  <td style={celda}>
                    {insumo ? etiquetaInsumo(insumo, clasificacion) : fila.insumo_id}
                    {conservado && (
                      <span style={{ display: "block", fontSize: "0.75rem", color: colores.alerta }}>
                        {insumo.activo ? "Depende del modelo" : "Dado de baja"}: se conserva, pero
                        no se podría agregar de nuevo.
                      </span>
                    )}
                  </td>
                  <td style={{ ...celda, width: "7rem" }}>
                    <input
                      aria-label={`Cantidad de ${insumo?.codigo ?? fila.insumo_id}`}
                      inputMode="decimal"
                      value={fila.cantidad}
                      readOnly={bloqueado}
                      onChange={(e) => cambiarPrevisto(indice, e.target.value)}
                      style={estiloInput}
                    />
                  </td>
                  <td style={{ ...celda, color: colores.suave }}>{insumo?.unidad ?? ""}</td>
                  <td style={celda}>
                    {editable && (
                      <Boton
                        variante="secundario"
                        onClick={() =>
                          setEditor({
                            ...editor,
                            previstos: editor.previstos.filter((_, i) => i !== indice),
                          })
                        }
                      >
                        Quitar
                      </Boton>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
      {editable && (
        <SelectorInsumo
          insumos={agregables}
          clasificacion={clasificacion}
          valor=""
          onCambiar={(insumoId) =>
            insumoId &&
            setEditor({
              ...editor,
              previstos: [...editor.previstos, { insumo_id: insumoId, cantidad: "1" }],
            })
          }
          etiqueta="Agregar un insumo previsto (solo vigentes y universales)"
          opcionVacia="Elegir el insumo…"
        />
      )}

      <h4 style={{ margin: "0.6rem 0 0.3rem" }}>Requisitos por categoría</h4>
      {editor.requisitos.length === 0 ? (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.85rem", color: colores.suave }}>
          Ninguno.
        </p>
      ) : (
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", width: "100%", marginBottom: "0.5rem" }}>
          <tbody>
            {editor.requisitos.map((fila, indice) => (
              <tr key={indice}>
                <td style={{ ...celda, color: colores.suave }}>{indice + 1}.</td>
                <td style={celda}>
                  <select
                    aria-label={`Categoría del requisito ${indice + 1}`}
                    value={fila.categoria_id}
                    disabled={bloqueado}
                    onChange={(e) => cambiarRequisito(indice, { categoria_id: e.target.value })}
                    style={estiloInput}
                  >
                    <option value="">Elegir la categoría…</option>
                    {opcionesCategoria(clasificacion, {
                      soloVigentes: true,
                      conservar: vigentes.includes(fila.categoria_id) ? fila.categoria_id : null,
                    }).map((opcion) => (
                      <option key={opcion.id} value={opcion.id}>
                        {opcion.esSubcategoria ? "  " : ""}
                        {opcion.etiqueta}
                        {opcion.activo ? "" : " (de baja)"}
                      </option>
                    ))}
                  </select>
                </td>
                <td style={{ ...celda, width: "7rem" }}>
                  <input
                    aria-label={`Cantidad del requisito ${indice + 1}`}
                    inputMode="decimal"
                    value={fila.cantidad}
                    readOnly={bloqueado}
                    onChange={(e) => cambiarRequisito(indice, { cantidad: e.target.value })}
                    style={estiloInput}
                  />
                </td>
                <td style={{ ...celda, whiteSpace: "nowrap" }}>
                  {editable && (
                    <>
                      <Boton
                        variante="secundario"
                        disabled={indice === 0}
                        onClick={() =>
                          setEditor({ ...editor, requisitos: moverLinea(editor.requisitos, indice, -1) })
                        }
                      >
                        <span aria-label="Subir">↑</span>
                      </Boton>{" "}
                      <Boton
                        variante="secundario"
                        disabled={indice === editor.requisitos.length - 1}
                        onClick={() =>
                          setEditor({ ...editor, requisitos: moverLinea(editor.requisitos, indice, 1) })
                        }
                      >
                        <span aria-label="Bajar">↓</span>
                      </Boton>{" "}
                      <Boton
                        variante="secundario"
                        onClick={() =>
                          setEditor({
                            ...editor,
                            requisitos: editor.requisitos.filter((_, i) => i !== indice),
                          })
                        }
                      >
                        Quitar
                      </Boton>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {editable && (
        <div style={{ margin: "0 0 0.6rem" }}>
          <Boton
            variante="secundario"
            onClick={() =>
              setEditor({
                ...editor,
                requisitos: [...editor.requisitos, { categoria_id: "", cantidad: "1" }],
              })
            }
          >
            + Agregar requisito
          </Boton>
        </div>
      )}

      {editable && errores.length > 0 && (
        <ul style={{ margin: "0 0 0.6rem", paddingLeft: "1.1rem", color: colores.error, fontSize: "0.8rem" }}>
          {errores.map((error) => (
            <li key={error}>{error}</li>
          ))}
        </ul>
      )}
      {editable && sinCambios && (
        <p style={{ margin: "0 0 0.6rem", fontSize: "0.8rem", color: colores.suave }}>
          Sin cambios para guardar.
        </p>
      )}
    </FormularioModal>
  );
}
