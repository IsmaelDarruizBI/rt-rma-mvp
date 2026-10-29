/**
 * Equipo del ingreso: se busca en el catálogo técnico de modelos (propio
 * de RMA) y se elige una coincidencia; si no está, marca, modelo y
 * variante a mano. El color es opcional y va aparte: es del equipo
 * físico, no del modelo. IMEI y número de serie siguen en el formulario.
 *
 * El catálogo de Ventas ya no se usa para elegir: una Orden anterior que
 * tiene un producto de Ventas lo conserva mientras no se elija otro.
 */

import { useEffect, useId, useState } from "react";

import { ApiError } from "../../api/client";
import { obtenerModelosEquipo } from "../../api/modelosEquipo";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { ModeloEquipo } from "../../types/api";
import { descripcionEquipo } from "./catalogoEquipos";
import {
  type EquipoElegido,
  buscarModelos,
  elegirModelo,
  modoEfectivo,
  quitarModelo,
} from "./modelosEquipo";

// Una sola lectura por sesión, compartida por el alta y la corrección.
let pendiente: Promise<ModeloEquipo[]> | null = null;

export function useModelosEquipo() {
  const [modelos, setModelos] = useState<ModeloEquipo[]>([]);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let vigente = true;
    if (pendiente === null) pendiente = obtenerModelosEquipo();
    const pedido = pendiente;
    pedido
      .then((leidos) => vigente && setModelos(leidos))
      .catch((fallo) => {
        if (pendiente === pedido) pendiente = null;
        if (vigente) setError(fallo instanceof ApiError ? fallo.message : "sin conexión");
      })
      .finally(() => vigente && setCargando(false));
    return () => {
      vigente = false;
    };
  }, []);

  return { modelos, cargando, error };
}

const estiloNota = {
  margin: "0 0 0.6rem",
  fontSize: "0.75rem",
  color: colores.suave,
} as const;

const estiloGrilla = {
  display: "grid",
  columnGap: "0.6rem",
  gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 160px), 1fr))",
} as const;

export function SelectorEquipo({
  modelos,
  cargando,
  error,
  valor,
  onCambiar,
  deshabilitado = false,
}: {
  modelos: ModeloEquipo[];
  cargando: boolean;
  error: string | null;
  valor: EquipoElegido;
  onCambiar: (valor: EquipoElegido) => void;
  deshabilitado?: boolean;
}) {
  const grupo = useId();
  const hayCatalogo = modelos.length > 0;
  const enCatalogo = modoEfectivo(hayCatalogo, valor) === "catalogo";
  // Del producto de Ventas que se conserva no se cambia el color.
  const conservaVentas = enCatalogo && !valor.modeloId && valor.productoVentas;

  return (
    <div role="group" aria-label="Equipo">
      <div
        role="radiogroup"
        aria-label="Cómo se carga el equipo"
        style={{ display: "flex", gap: "1rem", flexWrap: "wrap", margin: "0 0 0.5rem" }}
      >
        {(
          [
            ["catalogo", "Buscar en el catálogo de modelos"],
            ["manual", "No está en la lista: cargar a mano"],
          ] as const
        ).map(([modo, texto]) => (
          <label
            key={modo}
            style={{ fontSize: "0.85rem", display: "flex", gap: "0.35rem", alignItems: "center" }}
          >
            <input
              type="radio"
              name={grupo}
              checked={(modo === "catalogo") === enCatalogo}
              disabled={
                deshabilitado ||
                (modo === "catalogo" && !hayCatalogo && !valor.modeloId && !valor.productoVentas)
              }
              onChange={() => onCambiar({ ...valor, modo })}
            />
            {texto}
          </label>
        ))}
      </div>

      {enCatalogo ? (
        <BusquedaModelo
          modelos={modelos}
          valor={valor}
          onCambiar={onCambiar}
          deshabilitado={deshabilitado}
        />
      ) : (
        <div style={estiloGrilla}>
          <Campo etiqueta="Marca">
            <input
              value={valor.marca}
              disabled={deshabilitado}
              onChange={(evento) => onCambiar({ ...valor, marca: evento.target.value })}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Modelo">
            <input
              value={valor.modelo}
              disabled={deshabilitado}
              placeholder="Galaxy S23"
              onChange={(evento) => onCambiar({ ...valor, modelo: evento.target.value })}
              style={estiloInput}
            />
          </Campo>
          <Campo etiqueta="Variante (si tiene)">
            <input
              value={valor.variante}
              disabled={deshabilitado}
              placeholder="Ultra, Pro, Plus…"
              onChange={(evento) => onCambiar({ ...valor, variante: evento.target.value })}
              style={estiloInput}
            />
          </Campo>
        </div>
      )}

      {!conservaVentas && (
        <Campo etiqueta="Color (opcional)">
          <input
            value={valor.color}
            disabled={deshabilitado}
            onChange={(evento) => onCambiar({ ...valor, color: evento.target.value })}
            style={estiloInput}
          />
        </Campo>
      )}

      <p aria-label="Catálogo de modelos" style={estiloNota}>
        {cargando
          ? "Cargando el catálogo de modelos…"
          : error
            ? `No se pudo leer el catálogo de modelos (${error}). Cargá el equipo a mano.`
            : hayCatalogo
              ? `Catálogo de modelos: ${modelos.length} modelos.`
              : "El catálogo de modelos está vacío: cargá el equipo a mano."}
      </p>
    </div>
  );
}

function BusquedaModelo({
  modelos,
  valor,
  onCambiar,
  deshabilitado,
}: {
  modelos: ModeloEquipo[];
  valor: EquipoElegido;
  onCambiar: (valor: EquipoElegido) => void;
  deshabilitado: boolean;
}) {
  const [consulta, setConsulta] = useState("");
  const listaId = useId();

  if (valor.modeloId) {
    return (
      <div
        aria-label="Equipo elegido"
        style={{
          display: "flex",
          alignItems: "center",
          gap: "0.6rem",
          flexWrap: "wrap",
          margin: "0 0 0.6rem",
        }}
      >
        <strong>{valor.nombreModelo ?? valor.modeloId}</strong>
        <Boton
          variante="secundario"
          disabled={deshabilitado}
          onClick={() => {
            setConsulta("");
            onCambiar(quitarModelo(valor));
          }}
        >
          Cambiar
        </Boton>
      </div>
    );
  }

  const coincidencias = buscarModelos(modelos, consulta);
  const elegir = (modelo: ModeloEquipo) => {
    setConsulta("");
    onCambiar(elegirModelo(valor, modelo));
  };

  return (
    <>
      {valor.productoVentas && (
        <p aria-label="Equipo elegido" style={estiloNota}>
          Se mantiene {descripcionEquipo(valor.productoVentas)} (catálogo de
          Ventas, código {valor.productoVentas.tipo_producto_id}). Buscá otro
          solo si hay que cambiarlo.
        </p>
      )}
      <Campo etiqueta="Buscar modelo">
        <input
          type="search"
          value={consulta}
          disabled={deshabilitado}
          placeholder="Marca, modelo, variante o N.º de modelo (ej.: 15 pro max, A2849)"
          aria-controls={listaId}
          autoComplete="off"
          onChange={(evento) => setConsulta(evento.target.value)}
          onKeyDown={(evento) => {
            if (evento.key === "Enter" && coincidencias.length > 0) {
              evento.preventDefault();
              elegir(coincidencias[0]);
            }
          }}
          style={estiloInput}
        />
      </Campo>
      {consulta.trim() !== "" &&
        (coincidencias.length ? (
          <ul
            id={listaId}
            aria-label="Modelos que coinciden"
            style={{
              listStyle: "none",
              margin: "-0.3rem 0 0.6rem",
              padding: 0,
              border: `1px solid ${colores.borde}`,
              borderRadius: 6,
              maxHeight: "16rem",
              overflowY: "auto",
            }}
          >
            {coincidencias.map((modelo) => (
              <li key={modelo.id}>
                <button
                  type="button"
                  disabled={deshabilitado}
                  onClick={() => elegir(modelo)}
                  style={{
                    width: "100%",
                    textAlign: "left",
                    padding: "0.45rem 0.6rem",
                    border: "none",
                    borderBottom: `1px solid ${colores.borde}`,
                    background: "#fff",
                    font: "inherit",
                    cursor: "pointer",
                  }}
                >
                  {modelo.nombre}
                  {modelo.numeros_modelo.length > 0 && (
                    <span style={{ color: colores.suave }}>
                      {" "}
                      · {modelo.numeros_modelo.join(", ")}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p id={listaId} style={estiloNota}>
            Sin coincidencias. Si no está, cargalo a mano.
          </p>
        ))}
      {!valor.productoVentas && consulta.trim() === "" && (
        <p style={estiloNota}>Escribí para buscar y elegí el modelo de la lista.</p>
      )}
    </>
  );
}
