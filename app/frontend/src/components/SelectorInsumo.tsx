/**
 * Selección de insumos con búsqueda y filtros de clasificación (DEC-AJ-14).
 *
 * - `useClasificacionInsumos`: categorías, fabricantes y modelos, leídos una
 *   vez por sesión de la pantalla. Si la API no los da (backend anterior),
 *   queda vacía y todo se nombra como antes.
 * - `FiltrosClasificacion`: texto, categoría (o «Sin clasificar»),
 *   fabricante y modelo compatible.
 * - `SelectorInsumo`: los filtros más la lista resultante, con la
 *   clasificación en cada opción («INS-012 · Batería iPhone 14 · Acme ·
 *   alta capacidad»). Reutilizable para elegir la pieza de un trabajo:
 *   `modelo` deja solo las compatibles con el modelo del equipo y
 *   `categoria`, las de un requisito.
 */

import { useEffect, useMemo, useState } from "react";

import { obtenerClasificacion } from "../api/clasificacionInsumos";
import {
  CLASIFICACION_VACIA,
  type ClasificacionInsumos,
  type FiltroInsumos,
  type InsumoClasificable,
  SIN_CLASIFICAR,
  compatibleCon,
  etiquetaInsumo,
  filtrarInsumos,
  opcionesCategoria,
} from "../features/inventario/clasificacion";
import { colores, estiloInput } from "./ui";

let enMemoria: ClasificacionInsumos | null = null;

export function useClasificacionInsumos(): ClasificacionInsumos {
  const [clasificacion, setClasificacion] = useState<ClasificacionInsumos>(
    enMemoria ?? CLASIFICACION_VACIA,
  );
  useEffect(() => {
    let vigente = true;
    obtenerClasificacion()
      .then((leida) => {
        enMemoria = leida;
        if (vigente) setClasificacion(leida);
      })
      .catch(() => undefined);
    return () => {
      vigente = false;
    };
  }, []);
  return clasificacion;
}

const etiquetaFiltro = { display: "block", fontSize: "0.75rem", color: colores.suave } as const;

export function FiltrosClasificacion({
  filtro,
  onCambiar,
  clasificacion,
  conTexto = true,
  conModelo = true,
  conSinClasificar = true,
  textoAyuda = "Código, nombre, fabricante o variante",
}: {
  filtro: FiltroInsumos;
  onCambiar: (filtro: FiltroInsumos) => void;
  clasificacion: ClasificacionInsumos;
  conTexto?: boolean;
  conModelo?: boolean;
  conSinClasificar?: boolean;
  textoAyuda?: string;
}) {
  const categorias = opcionesCategoria(clasificacion);
  return (
    <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", alignItems: "flex-end" }}>
      {conTexto && (
        <label style={{ flex: "2 1 180px" }}>
          <span style={etiquetaFiltro}>Buscar</span>
          <input
            value={filtro.texto ?? ""}
            placeholder={textoAyuda}
            onChange={(e) => onCambiar({ ...filtro, texto: e.target.value })}
            style={estiloInput}
          />
        </label>
      )}
      {(categorias.length > 0 || conSinClasificar) && (
        <label style={{ flex: "1 1 150px" }}>
          <span style={etiquetaFiltro}>Categoría</span>
          <select
            value={filtro.categoria ?? ""}
            onChange={(e) => onCambiar({ ...filtro, categoria: e.target.value || undefined })}
            style={estiloInput}
          >
            <option value="">Todas</option>
            {conSinClasificar && <option value={SIN_CLASIFICAR}>Sin clasificar</option>}
            {categorias.map((c) => (
              <option key={c.id} value={c.id}>
                {c.esSubcategoria ? "  " : ""}
                {c.etiqueta}
                {c.activo ? "" : " (de baja)"}
              </option>
            ))}
          </select>
        </label>
      )}
      {clasificacion.fabricantes.length > 0 && (
        <label style={{ flex: "1 1 130px" }}>
          <span style={etiquetaFiltro}>Fabricante</span>
          <select
            value={filtro.fabricante ?? ""}
            onChange={(e) => onCambiar({ ...filtro, fabricante: e.target.value || undefined })}
            style={estiloInput}
          >
            <option value="">Todos</option>
            {clasificacion.fabricantes.map((f) => (
              <option key={f.id} value={f.id}>
                {f.nombre}
                {f.activo ? "" : " (de baja)"}
              </option>
            ))}
          </select>
        </label>
      )}
      {conModelo && clasificacion.modelos.length > 0 && (
        <label style={{ flex: "1 1 170px" }}>
          <span style={etiquetaFiltro}>Compatible con</span>
          <select
            value={filtro.modelo ?? ""}
            onChange={(e) => onCambiar({ ...filtro, modelo: e.target.value || undefined })}
            style={estiloInput}
          >
            <option value="">Cualquier modelo</option>
            {clasificacion.modelos.map((m) => (
              <option key={m.id} value={m.id}>
                {m.nombre}
                {m.activo ? "" : " (de baja)"}
              </option>
            ))}
          </select>
        </label>
      )}
    </div>
  );
}

export function SelectorInsumo<T extends InsumoClasificable>({
  insumos,
  clasificacion,
  valor,
  onCambiar,
  etiqueta = "Insumo",
  opcionVacia = "Elegir…",
  soloVigentes = false,
  modelo,
  categoria,
}: {
  insumos: readonly T[];
  clasificacion: ClasificacionInsumos;
  valor: string;
  onCambiar: (insumoId: string) => void;
  etiqueta?: string;
  opcionVacia?: string;
  soloVigentes?: boolean;
  /** Fijo: solo los compatibles con este modelo (null: equipo sin modelo, solo universales). */
  modelo?: string | null;
  /** Fijo: solo los de esta categoría o subcategoría (un requisito). */
  categoria?: string;
}) {
  const [filtro, setFiltro] = useState<FiltroInsumos>({});
  const fijo = modelo !== undefined;
  const visibles = useMemo(() => {
    const base = filtrarInsumos(
      insumos,
      { ...filtro, soloVigentes, categoria: categoria ?? filtro.categoria },
      clasificacion,
    );
    if (!fijo) return base;
    return base.filter((i) => compatibleCon(i, modelo ?? null));
  }, [insumos, filtro, soloVigentes, categoria, clasificacion, fijo, modelo]);
  const elegido = insumos.find((i) => i.id === valor);
  // El elegido se sigue mostrando aunque un filtro lo oculte.
  const opciones = elegido && !visibles.includes(elegido) ? [elegido, ...visibles] : visibles;
  return (
    <fieldset style={{ border: `1px solid ${colores.borde}`, borderRadius: 6, padding: "0.5rem", margin: "0 0 0.6rem" }}>
      <legend style={{ fontSize: "0.8rem", color: colores.suave }}>{etiqueta}</legend>
      <FiltrosClasificacion
        filtro={filtro}
        onCambiar={setFiltro}
        clasificacion={clasificacion}
        conModelo={!fijo}
        conSinClasificar={categoria === undefined}
      />
      <select
        aria-label={etiqueta}
        value={valor}
        onChange={(e) => onCambiar(e.target.value)}
        style={{ ...estiloInput, marginTop: "0.4rem" }}
      >
        <option value="">
          {opcionVacia} ({visibles.length} de {insumos.length})
        </option>
        {opciones.map((i) => (
          <option key={i.id} value={i.id}>
            {etiquetaInsumo(i, clasificacion)}
          </option>
        ))}
      </select>
    </fieldset>
  );
}
