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
 * - DEC-AJ-14: cada insumo es un repuesto real (SKU). Su clasificación
 *   (categoría o subcategoría, fabricante, variante y código del
 *   fabricante) y los modelos compatibles (ninguno: universal) son
 *   opcionales y se cargan de a poco, con filtros para encontrar lo que
 *   falta clasificar. No cambian el stock.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { get, post, put } from "../../api/client";
import {
  EncabezadoListado,
  FormularioModal,
  Mensajes,
  mensajeDe,
  useComando,
} from "../../components/FormularioModal";
import { FiltrosClasificacion, useClasificacionInsumos } from "../../components/SelectorInsumo";
import { Boton, Campo, colores, estiloInput, importe } from "../../components/ui";
import { puede } from "../../lib/roles";
import type { Usuario } from "../../types/api";
import {
  type ClasificacionInsumos,
  type FiltroInsumos,
  agregarModelos,
  alternarModelo,
  buscarModelos,
  filtrarInsumos,
  nombreCategoria,
  nombreFabricante,
  nombreModeloClasificacion,
  opcionesCategoria,
  textoCompatibilidad,
} from "../inventario/clasificacion";
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
  /** DEC-AJ-14 (ausentes en un backend anterior). */
  categoria_id?: string | null;
  fabricante_id?: string | null;
  variante?: string | null;
  codigo_fabricante?: string | null;
  modelos_compatibles?: string[];
}

interface DatosInsumo {
  nombre: string;
  unidad: string;
  control: ControlInsumo;
  precio: string;
  stock_minimo: string;
  categoria_id: string;
  fabricante_id: string;
  variante: string;
  codigo_fabricante: string;
  /** Vacío: universal. */
  modelos_compatibles: string[];
}

const NUEVO: DatosInsumo = {
  nombre: "",
  unidad: "unidad",
  control: "SIN_LOTE",
  precio: "",
  stock_minimo: "",
  categoria_id: "",
  fabricante_id: "",
  variante: "",
  codigo_fabricante: "",
  modelos_compatibles: [],
};

function datosDe(insumo: InsumoAdmin): DatosInsumo {
  return {
    nombre: insumo.nombre,
    unidad: insumo.unidad ?? "",
    control: insumo.control,
    precio: insumo.precio ?? "",
    stock_minimo: insumo.stock_minimo ?? "",
    categoria_id: insumo.categoria_id ?? "",
    fabricante_id: insumo.fabricante_id ?? "",
    variante: insumo.variante ?? "",
    codigo_fabricante: insumo.codigo_fabricante ?? "",
    modelos_compatibles: insumo.modelos_compatibles ?? [],
  };
}

const celda = { paddingRight: "0.8rem" } as const;

export function InsumosAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<{ editable: boolean; insumos: InsumoAdmin[] } | null>(null);
  const [ventana, setVentana] = useState<{ insumo: InsumoAdmin | null; datos: DatosInsumo } | null>(
    null,
  );
  const [resaltado, setResaltado] = useState<string | null>(null);
  const [filtro, setFiltro] = useState<FiltroInsumos>({});
  const { error, setError, aviso, setAviso, ocupado, ejecutar } = useComando();
  const editaPrecio = puede(actor, "PRECIOS_GESTIONAR", ["ADMINISTRADOR"]);
  const clasificacion = useClasificacionInsumos();

  const cargar = useCallback(() => {
    get<{ editable: boolean; insumos: InsumoAdmin[] }>("/api/admin/supplies")
      .then(setDatos)
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [setError]);
  useEffect(cargar, [cargar]);

  const visibles = useMemo(
    () => (datos ? filtrarInsumos(datos.insumos, filtro, clasificacion) : []),
    [datos, filtro, clasificacion],
  );

  if (!datos) return <Mensajes error={error} aviso={aviso} />;
  const bloqueado = ocupado || !datos.editable;

  const guardado = (insumo: InsumoAdmin, texto: string) => {
    setDatos({ ...datos, insumos: conElemento(datos.insumos, insumo, (i) => i.id) });
    setResaltado(insumo.id);
    setError(null);
    setAviso(texto);
  };

  /**
   * La edición en la fila manda lo de la fila; la clasificación y la
   * compatibilidad no viajan y la API las conserva.
   */
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
  const cambiar = (cambios: Partial<DatosInsumo>) =>
    ventana && setVentana({ ...ventana, datos: { ...ventana.datos, ...cambios } });

  return (
    <section>
      <EncabezadoListado
        titulo="Insumos"
        nuevo={datos.editable ? "Nuevo insumo" : undefined}
        onNuevo={() => setVentana({ insumo: null, datos: NUEVO })}
      />
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        Cada insumo es un repuesto real, con su propio stock. El stock cambia solo con movimientos
        del inventario y un insumo nuevo empieza sin stock. Pasar un insumo a control por lote o
        serie deja su stock actual como «sin lote identificado»; volver atrás exige que sus lotes
        estén en cero. La clasificación y los modelos compatibles se cargan de a poco: sin modelos,
        el insumo es universal.
      </p>
      <Mensajes error={error} aviso={aviso} />
      <div style={{ marginBottom: "0.5rem" }}>
        <FiltrosClasificacion filtro={filtro} onCambiar={setFiltro} clasificacion={clasificacion} />
        <p style={{ margin: "0.3rem 0 0", fontSize: "0.75rem", color: colores.suave }}>
          {visibles.length} de {datos.insumos.length} insumos.
        </p>
      </div>
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem", minWidth: 900 }}>
          <thead>
            <tr>
              {[
                "Código",
                "Nombre",
                "Categoría",
                "Fabricante",
                "Variante",
                "Compatibilidad",
                "Unidad",
                "Stock",
                "Stock mínimo",
                "Control",
                "Precio",
                "Vigente",
                "",
              ].map((t) => (
                <th key={t} style={{ textAlign: "left", ...celda }}>
                  {t}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibles.map((insumo) => (
              <tr key={insumo.id} style={{ background: resaltado === insumo.id ? "#eff6ff" : undefined }}>
                <td style={celda}>
                  {insumo.id}
                  {insumo.codigo !== insumo.id && (
                    <span style={{ color: colores.suave }}> · {insumo.codigo}</span>
                  )}
                </td>
                <td style={celda}>
                  {insumo.nombre}
                  {insumo.codigo_fabricante && (
                    <div style={{ fontSize: "0.75rem", color: colores.suave }}>
                      Cód. fabricante {insumo.codigo_fabricante}
                    </div>
                  )}
                </td>
                <td style={celda}>
                  {nombreCategoria(insumo.categoria_id, clasificacion) ?? (
                    <span style={{ color: colores.suave }}>Sin clasificar</span>
                  )}
                </td>
                <td style={celda}>{nombreFabricante(insumo.fabricante_id, clasificacion) ?? "—"}</td>
                <td style={celda}>{insumo.variante || "—"}</td>
                <td style={celda} title={(insumo.modelos_compatibles ?? []).join(", ")}>
                  {textoCompatibilidad(insumo, clasificacion)}
                </td>
                <td style={celda}>{insumo.unidad ?? "—"}</td>
                <td style={{ ...celda, textAlign: "right" }}>{insumo.stock_fisico}</td>
                <td style={{ ...celda, textAlign: "right" }}>{insumo.stock_minimo ?? "—"}</td>
                <td style={celda}>
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
                <td style={celda}>{insumo.precio ? importe(insumo.precio) : "—"}</td>
                <td style={{ textAlign: "center", ...celda }}>
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
                      onClick={() => setVentana({ insumo, datos: datosDe(insumo) })}
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
          amplio
          onCerrar={() => setVentana(null)}
          onConfirmar={async () => {
            const { insumo, datos: d } = ventana;
            const comun = {
              nombre: d.nombre.trim(),
              unidad: d.unidad.trim() || null,
              control: d.control,
              stock_minimo: minimo.valor,
              categoria_id: d.categoria_id || null,
              fabricante_id: d.fabricante_id || null,
              variante: d.variante.trim() || null,
              codigo_fabricante: d.codigo_fabricante.trim() || null,
              modelos_compatibles: d.modelos_compatibles,
            };
            const resultado = insumo
              ? await put<InsumoAdmin>(`/api/admin/supplies/${encodeURIComponent(insumo.id)}`, {
                  ...cuerpo(insumo, {}),
                  ...comun,
                  precio: editaPrecio ? precio || null : insumo.precio,
                })
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
            <input value={ventana.datos.nombre} onChange={(e) => cambiar({ nombre: e.target.value })} style={estiloInput} />
          </Campo>
          <Campo etiqueta="Unidad">
            <input value={ventana.datos.unidad} onChange={(e) => cambiar({ unidad: e.target.value })} style={estiloInput} />
          </Campo>
          {!ventana.insumo && (
            <Campo etiqueta="Control">
              <select
                value={ventana.datos.control}
                onChange={(e) => cambiar({ control: e.target.value as ControlInsumo })}
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
              onChange={(e) => cambiar({ precio: e.target.value })}
              style={{ ...estiloInput, background: editaPrecio ? "#fff" : colores.fondo }}
            />
          </Campo>
          <Campo etiqueta="Stock mínimo (opcional)">
            <input
              inputMode="decimal"
              value={ventana.datos.stock_minimo}
              placeholder="Sin mínimo"
              aria-invalid={minimo.error !== null}
              onChange={(e) => cambiar({ stock_minimo: e.target.value })}
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
          <ClasificacionDelInsumo
            datos={ventana.datos}
            anterior={ventana.insumo}
            clasificacion={clasificacion}
            onCambiar={cambiar}
          />
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

/** DEC-AJ-14: categoría, fabricante, variante, código y compatibilidad. */
function ClasificacionDelInsumo({
  datos,
  anterior,
  clasificacion,
  onCambiar,
}: {
  datos: DatosInsumo;
  anterior: InsumoAdmin | null;
  clasificacion: ClasificacionInsumos;
  onCambiar: (cambios: Partial<DatosInsumo>) => void;
}) {
  // Lo dado de baja se ofrece solo si el insumo ya lo tenía.
  const categorias = opcionesCategoria(clasificacion, {
    soloVigentes: true,
    conservar: anterior?.categoria_id ?? null,
  });
  const fabricantes = clasificacion.fabricantes.filter(
    (f) => f.activo || f.id === anterior?.fabricante_id,
  );
  return (
    <fieldset style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, padding: "0.6rem", margin: "0 0 0.6rem" }}>
      <legend style={{ fontSize: "0.85rem" }}>Clasificación (opcional)</legend>
      <div style={{ display: "grid", gap: "0 0.6rem", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))" }}>
        <Campo etiqueta="Categoría o subcategoría">
          <select value={datos.categoria_id} onChange={(e) => onCambiar({ categoria_id: e.target.value })} style={estiloInput}>
            <option value="">Sin clasificar</option>
            {categorias.map((c) => (
              <option key={c.id} value={c.id}>
                {c.etiqueta}
                {c.activo ? "" : " (de baja)"}
              </option>
            ))}
          </select>
        </Campo>
        <Campo etiqueta="Fabricante o marca">
          <select value={datos.fabricante_id} onChange={(e) => onCambiar({ fabricante_id: e.target.value })} style={estiloInput}>
            <option value="">Sin fabricante</option>
            {fabricantes.map((f) => (
              <option key={f.id} value={f.id}>
                {f.nombre}
                {f.activo ? "" : " (de baja)"}
              </option>
            ))}
          </select>
        </Campo>
        <Campo etiqueta="Variante">
          <input
            value={datos.variante}
            placeholder="Con marco, negro…"
            onChange={(e) => onCambiar({ variante: e.target.value })}
            style={estiloInput}
          />
        </Campo>
        <Campo etiqueta="Código del fabricante o proveedor">
          <input
            value={datos.codigo_fabricante}
            placeholder="Para buscar"
            onChange={(e) => onCambiar({ codigo_fabricante: e.target.value })}
            style={estiloInput}
          />
        </Campo>
      </div>
      {clasificacion.categorias.length === 0 && clasificacion.fabricantes.length === 0 && (
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
          Las categorías y los fabricantes se dan de alta en sus secciones de Configuración.
        </p>
      )}
      <SelectorModelos
        seleccionados={datos.modelos_compatibles}
        previos={anterior?.modelos_compatibles ?? []}
        clasificacion={clasificacion}
        onCambiar={(modelos) => onCambiar({ modelos_compatibles: modelos })}
      />
    </fieldset>
  );
}

/**
 * Modelos compatibles: «Universal» o una lista elegida con búsqueda. Pensado
 * para muchos modelos: se filtra por nombre o código y se pueden agregar
 * todos los visibles de una vez («iPhone 14» agrega sus variantes). Un
 * modelo dado de baja no se agrega, pero se conserva si ya estaba.
 */
function SelectorModelos({
  seleccionados,
  previos,
  clasificacion,
  onCambiar,
}: {
  seleccionados: string[];
  previos: string[];
  clasificacion: ClasificacionInsumos;
  onCambiar: (modelos: string[]) => void;
}) {
  const [restringido, setRestringido] = useState(seleccionados.length > 0);
  const [buscar, setBuscar] = useState("");
  const visibles = buscarModelos(clasificacion.modelos, buscar);
  return (
    <div>
      <div style={{ display: "flex", gap: "1rem", flexWrap: "wrap", fontSize: "0.85rem", marginBottom: "0.4rem" }}>
        <label style={{ display: "flex", gap: "0.3rem", alignItems: "center" }}>
          <input
            type="radio"
            checked={!restringido}
            onChange={() => {
              setRestringido(false);
              onCambiar([]);
            }}
          />
          Universal: sirve para todos los modelos
        </label>
        <label style={{ display: "flex", gap: "0.3rem", alignItems: "center" }}>
          <input type="radio" checked={restringido} onChange={() => setRestringido(true)} />
          Solo para algunos modelos
        </label>
      </div>
      {restringido && (
        <>
          {seleccionados.length > 0 ? (
            <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap", marginBottom: "0.4rem" }}>
              {seleccionados.map((id) => (
                <button
                  key={id}
                  type="button"
                  className="rt-btn"
                  title="Quitar"
                  onClick={() => onCambiar(alternarModelo(seleccionados, id))}
                  style={{ fontSize: "0.75rem", padding: "0.1rem 0.4rem" }}
                >
                  {nombreModeloClasificacion(id, clasificacion)} ✕
                </button>
              ))}
            </div>
          ) : (
            <p style={{ margin: "0 0 0.4rem", fontSize: "0.8rem", color: colores.alerta }}>
              Elegí al menos un modelo; sin modelos el insumo queda universal.
            </p>
          )}
          <div style={{ display: "flex", gap: "0.4rem", alignItems: "flex-end", flexWrap: "wrap" }}>
            <label style={{ flex: "1 1 200px" }}>
              <span style={{ display: "block", fontSize: "0.75rem", color: colores.suave }}>Buscar modelo</span>
              <input value={buscar} placeholder="iPhone 14" onChange={(e) => setBuscar(e.target.value)} style={estiloInput} />
            </label>
            <Boton
              variante="secundario"
              disabled={!buscar.trim() || visibles.every((m) => !m.activo || seleccionados.includes(m.id))}
              onClick={() => onCambiar(agregarModelos(seleccionados, visibles))}
            >
              Agregar los {visibles.filter((m) => m.activo).length} visibles
            </Boton>
            <Boton variante="secundario" disabled={seleccionados.length === 0} onClick={() => onCambiar([])}>
              Quitar todos
            </Boton>
          </div>
          <div
            style={{
              maxHeight: 180,
              overflowY: "auto",
              border: `1px solid ${colores.borde}`,
              borderRadius: 6,
              padding: "0.3rem 0.5rem",
              marginTop: "0.4rem",
              fontSize: "0.85rem",
            }}
          >
            {visibles.map((m) => {
              const elegido = seleccionados.includes(m.id);
              const bloqueado = !m.activo && !elegido && !previos.includes(m.id);
              return (
                <label key={m.id} style={{ display: "flex", gap: "0.4rem", color: bloqueado ? colores.suave : undefined }}>
                  <input
                    type="checkbox"
                    checked={elegido}
                    disabled={bloqueado}
                    onChange={() => onCambiar(alternarModelo(seleccionados, m.id))}
                  />
                  {m.nombre}
                  <span style={{ color: colores.suave }}>
                    {m.id}
                    {m.activo ? "" : " · de baja"}
                  </span>
                </label>
              );
            })}
            {visibles.length === 0 && <span style={{ color: colores.suave }}>Ningún modelo coincide.</span>}
          </div>
        </>
      )}
    </div>
  );
}
