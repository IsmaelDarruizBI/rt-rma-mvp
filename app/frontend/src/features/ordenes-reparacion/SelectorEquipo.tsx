/**
 * Equipo del ingreso: del catálogo de Ventas (Modelo → Variante →
 * Capacidad → Color, solo combinaciones que existen) o, si no está, marca
 * y modelo a mano. El catálogo es la copia del backend: elegir un equipo
 * nunca consulta Google Sheets.
 *
 * Debajo, el estado de la copia (cuándo se sincronizó) y, para
 * Administración o Coordinación RMA, «Sincronizar catálogo».
 */

import { useCallback, useEffect, useId, useState } from "react";

import {
  obtenerCatalogoEquipos,
  sincronizarCatalogoEquipos,
} from "../../api/catalogoEquipos";
import { ApiError } from "../../api/client";
import { Boton, Campo, colores, estiloInput, fechaCorta } from "../../components/ui";
import type { CatalogoEquipos, Usuario } from "../../types/api";
import {
  cantidadDeProductos,
  descripcionEquipo,
  elegir,
  modoEfectivo,
  opcionesCapacidad,
  opcionesColor,
  opcionesModelo,
  opcionesVariante,
  productoElegido,
  type EquipoElegido,
  type Opcion,
  type SeleccionCatalogo,
} from "./catalogoEquipos";

const ROLES_SINCRONIZACION = ["ADMINISTRADOR", "COORDINADOR_RMA"];

const sinPuntoFinal = (texto: string) => texto.trim().replace(/\.$/, "");

// Una sola lectura por sesión, compartida por el alta y la corrección;
// se vuelve a pedir después de sincronizar.
let pendiente: Promise<CatalogoEquipos> | null = null;

export function useCatalogoEquipos() {
  const [catalogo, setCatalogo] = useState<CatalogoEquipos | null>(null);
  const [cargando, setCargando] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const cargar = useCallback(async (forzar = false) => {
    if (forzar || pendiente === null) pendiente = obtenerCatalogoEquipos();
    const pedido = pendiente;
    setCargando(true);
    setError(null);
    try {
      setCatalogo(await pedido);
    } catch (fallo) {
      if (pendiente === pedido) pendiente = null;
      setError(fallo instanceof ApiError ? fallo.message : "sin conexión");
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    void cargar();
  }, [cargar]);

  return { catalogo, cargando, error, recargar: () => cargar(true) };
}

function Selector({
  etiqueta,
  valor,
  opciones,
  deshabilitado,
  onElegir,
}: {
  etiqueta: string;
  valor: string;
  opciones: Opcion[];
  deshabilitado: boolean;
  onElegir: (valor: string) => void;
}) {
  return (
    <Campo etiqueta={etiqueta}>
      <select
        value={valor}
        disabled={deshabilitado || opciones.length === 0}
        onChange={(evento) => onElegir(evento.target.value)}
        style={estiloInput}
      >
        <option value="">{opciones.length ? "Elegí…" : "—"}</option>
        {opciones.map((opcion) => (
          <option key={opcion.valor} value={opcion.valor}>
            {opcion.etiqueta}
          </option>
        ))}
      </select>
    </Campo>
  );
}

const estiloNota = {
  margin: "0 0 0.6rem",
  fontSize: "0.75rem",
  color: colores.suave,
} as const;

export function SelectorEquipo({
  catalogo,
  cargando,
  error,
  valor,
  onCambiar,
  actor,
  onSincronizado,
  deshabilitado = false,
}: {
  catalogo: CatalogoEquipos | null;
  cargando: boolean;
  error: string | null;
  valor: EquipoElegido;
  onCambiar: (valor: EquipoElegido) => void;
  actor: Usuario | null;
  onSincronizado: () => void;
  deshabilitado?: boolean;
}) {
  const grupo = useId();
  const hayCatalogo = (catalogo?.modelos.length ?? 0) > 0;
  const conserva = valor.actual?.tipo_producto_id ? valor.actual : null;
  const enCatalogo = modoEfectivo(catalogo, valor) === "catalogo";
  const seleccion = valor.seleccion;
  const producto = catalogo && hayCatalogo ? productoElegido(catalogo, seleccion) : null;

  const nivel = (clave: keyof SeleccionCatalogo) => (elegido: string) => {
    if (!catalogo) return;
    onCambiar({ ...valor, seleccion: elegir(catalogo, seleccion, clave, elegido) });
  };

  return (
    <div role="group" aria-label="Equipo">
      <div
        role="radiogroup"
        aria-label="Cómo se carga el equipo"
        style={{ display: "flex", gap: "1rem", flexWrap: "wrap", margin: "0 0 0.5rem" }}
      >
        {(
          [
            ["catalogo", "Del catálogo de Ventas"],
            ["manual", "No está en el catálogo: cargar a mano"],
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
              disabled={deshabilitado || (modo === "catalogo" && !hayCatalogo && !conserva)}
              onChange={() => onCambiar({ ...valor, modo })}
            />
            {texto}
          </label>
        ))}
      </div>

      {enCatalogo && catalogo && hayCatalogo ? (
        <>
          <div
            style={{
              display: "grid",
              columnGap: "0.6rem",
              gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 140px), 1fr))",
            }}
          >
            <Selector
              etiqueta="Modelo"
              valor={seleccion.modelo}
              opciones={opcionesModelo(catalogo)}
              deshabilitado={deshabilitado}
              onElegir={nivel("modelo")}
            />
            <Selector
              etiqueta="Variante"
              valor={seleccion.variante}
              opciones={opcionesVariante(catalogo, seleccion)}
              deshabilitado={deshabilitado}
              onElegir={nivel("variante")}
            />
            <Selector
              etiqueta="Capacidad"
              valor={seleccion.capacidad}
              opciones={opcionesCapacidad(catalogo, seleccion)}
              deshabilitado={deshabilitado}
              onElegir={nivel("capacidad")}
            />
            <Selector
              etiqueta="Color"
              valor={seleccion.color}
              opciones={opcionesColor(catalogo, seleccion)}
              deshabilitado={deshabilitado}
              onElegir={nivel("color")}
            />
          </div>
          {producto ? (
            <p aria-label="Equipo elegido" style={{ ...estiloNota, color: colores.texto }}>
              {descripcionEquipo(producto)}
              <span style={{ color: colores.suave }}>
                {" "}
                · código de Ventas {producto.tipo_producto_id}
              </span>
            </p>
          ) : conserva && !seleccion.modelo ? (
            <p aria-label="Equipo elegido" style={estiloNota}>
              Se mantiene {descripcionEquipo(conserva)} (código de Ventas{" "}
              {conserva.tipo_producto_id}). Elegí otro solo si hay que cambiarlo.
            </p>
          ) : (
            <p style={estiloNota}>
              Elegí modelo, variante, capacidad y color. Si no aparece, cargalo a mano.
            </p>
          )}
        </>
      ) : enCatalogo && conserva ? (
        <p aria-label="Equipo elegido" style={estiloNota}>
          Se mantiene {descripcionEquipo(conserva)} (código de Ventas{" "}
          {conserva.tipo_producto_id}), aunque el catálogo no esté disponible.
        </p>
      ) : (
        <div
          style={{
            display: "grid",
            columnGap: "0.6rem",
            gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 180px), 1fr))",
          }}
        >
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
              onChange={(evento) => onCambiar({ ...valor, modelo: evento.target.value })}
              style={estiloInput}
            />
          </Campo>
        </div>
      )}

      <EstadoCatalogo
        catalogo={catalogo}
        cargando={cargando}
        error={error}
        actor={actor}
        onSincronizado={onSincronizado}
      />
    </div>
  );
}

function EstadoCatalogo({
  catalogo,
  cargando,
  error,
  actor,
  onSincronizado,
}: {
  catalogo: CatalogoEquipos | null;
  cargando: boolean;
  error: string | null;
  actor: Usuario | null;
  onSincronizado: () => void;
}) {
  const [sincronizando, setSincronizando] = useState(false);
  const [aviso, setAviso] = useState<{ texto: string; error: boolean } | null>(null);
  const estado = catalogo?.estado;
  const puedeSincronizar =
    !!actor && ROLES_SINCRONIZACION.includes(actor.rol) && !!estado?.sincronizable;

  async function sincronizar() {
    if (!actor) return;
    setSincronizando(true);
    setAviso(null);
    try {
      const resultado = await sincronizarCatalogoEquipos(actor.id);
      setAviso({
        texto:
          `Sincronizado: ${resultado.elegibles} equipos para elegir ` +
          `(${resultado.nuevos} nuevos, ${resultado.actualizados} con cambios, ` +
          `${resultado.dados_de_baja} dados de baja).`,
        error: false,
      });
    } catch (fallo) {
      setAviso({
        texto:
          fallo instanceof ApiError
            ? fallo.message
            : "No se pudo sincronizar. Se conserva el catálogo anterior.",
        error: true,
      });
    } finally {
      setSincronizando(false);
      onSincronizado();
    }
  }

  let texto: string;
  if (cargando && !catalogo) texto = "Cargando el catálogo de equipos…";
  else if (error) texto = `No se pudo leer el catálogo de equipos (${error}). Cargá marca y modelo a mano.`;
  else if (!estado?.habilitado) texto = "El catálogo de equipos no está habilitado: cargá marca y modelo a mano.";
  else if (!estado.ultima_exitosa)
    texto = "El catálogo de equipos de Ventas todavía no se sincronizó: cargá marca y modelo a mano.";
  else
    texto =
      `Catálogo de Ventas: ${catalogo ? cantidadDeProductos(catalogo) : 0} equipos · ` +
      `sincronizado el ${fechaCorta(estado.ultima_exitosa.finalizada_en)}`;
  const ultima = estado?.ultima;
  const fallida = ultima && ultima.resultado !== "EXITOSA" ? ultima : null;

  return (
    <div aria-label="Catálogo de equipos" style={{ ...estiloNota, display: "grid", gap: "0.3rem" }}>
      <span>{texto}</span>
      {fallida && (
        <span style={{ color: colores.alerta }}>
          Último intento ({fechaCorta(fallida.finalizada_en)}):{" "}
          {fallida.resultado === "FALLIDA" ? "no se pudo leer el origen" : "datos rechazados"}
          {fallida.mensaje ? ` — ${sinPuntoFinal(fallida.mensaje)}` : ""}. Se usa el catálogo
          anterior.
        </span>
      )}
      {aviso && (
        <span role={aviso.error ? "alert" : "status"} style={{ color: aviso.error ? colores.alerta : colores.texto }}>
          {aviso.texto}
        </span>
      )}
      {puedeSincronizar && (
        <div>
          <Boton variante="secundario" disabled={sincronizando} onClick={() => void sincronizar()}>
            {sincronizando ? "Sincronizando…" : "Sincronizar catálogo"}
          </Boton>
        </div>
      )}
    </div>
  );
}
