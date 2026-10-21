/**
 * Contenedor de la feature: carga datos, ejecuta comandos y decide qué
 * pantalla mostrar (listado o una Orden).
 *
 * Es el único componente con estado de verdad. Toda la lógica de negocio
 * vive en el backend: acá solo se llama a la API y se muestra lo que
 * devuelve, incluidas las acciones disponibles y la situación operativa.
 *
 * La pantalla de una Orden separa la información de lo que el empleado
 * hace: a la izquierda la cabecera y la información (cliente y equipo,
 * trabajos, autorización, ejecuciones e insumos, cobros, documentos,
 * historial); a la derecha, fijo, el panel de acciones («Próximo paso»,
 * «Otras acciones» y «Situaciones especiales»). En el celular es una sola
 * columna con el panel de acciones arriba, después de la cabecera.
 *
 * Qué pantalla se ve lo decide la URL (`#/inicio`, `#/ordenes`,
 * `#/ordenes/nueva`, `#/ordenes/OR-000001`, `#/taller`, `#/inventario`):
 * navegar solo lee, nunca envía comandos. La búsqueda, los filtros y el
 * usuario de demostración sobreviven a la navegación.
 */

import {
  type ReactNode,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import * as api from "../../api/ordenes";
import { ApiError } from "../../api/client";
import { Boton, Panel, colores, importe } from "../../components/ui";
import type {
  Accion,
  Estacion,
  MedioPago,
  Orden,
  OrdenResumen,
  Prioridad,
  RolUsuario,
  TipoReparacion,
  Usuario,
} from "../../types/api";
import {
  AccionesOrden,
  CancelacionesOrden,
  ComplementariasOrden,
  type EjecutorAcciones,
} from "./AccionesOrden";
import { InventarioPanel } from "../inventario/Inventario";
import { AutorizacionClienteOrden } from "./AutorizacionCliente";
import { PantallaInicio, PantallaTaller } from "./PantallasTrabajo";
import { CustodiaOrden } from "./CustodiaOrden";
import {
  Bloque,
  CabeceraOrden,
  DatosTecnicos,
  EjecucionesEInsumos,
  EjecucionesOrden,
  HistorialOrden,
  ProgresoHappyPath,
  TrabajosOrden,
} from "./DetalleOrden";
import { DocumentosOrden } from "./DocumentosOrden";
import {
  CUSTODIA,
  ESTADO_PAGO,
  ESTADO_TRABAJO,
  NOMBRE_ACCION,
  etiqueta,
  mensajeLegible,
} from "./etiquetas";
import { PagosYMovimientos } from "./PagosOrden";
import {
  FormularioAltaOrden,
  PantallaOrdenes,
  SelectorActor,
} from "./ListadoOrdenes";
import { type FiltrosListado, filtrosValidos } from "./listado";
import { type Ruta } from "./rutas";
import {
  elegirUsuarioDemo,
  guardarUsuarioDemo,
  leerUsuarioDemo,
} from "./usuarioDemo";
import { useRuta } from "./useRuta";
import {
  CODIGOS_SECUNDARIOS,
  type ErrorDeComando,
  LugarDeFormularios,
  MensajeDeComando,
  PASOS_RECOMENDADOS,
  ProveedorPresentacion,
  SeccionPlegable,
  accionesDeLaOrden,
  accionesPorLugar,
  claveDeAccion,
  puedeEjecutar,
} from "./presentacion";
import { INDICE_PASO_RECOMENDADO, ProximoPaso } from "./ProximoPaso";

type Informativa =
  | "cliente"
  | "trabajos"
  | "autorizacion"
  | "ejecuciones"
  | "cobros"
  | "documentos";

/**
 * Lo que se oculta en pantallas angostas y la grilla de la Orden: dos
 * columnas en escritorio (información | acciones, fijas al desplazarse),
 * una sola en el celular con las acciones arriba.
 */
const ESTILOS_RESPONSIVOS = `
@media (max-width: 520px) {
  .rt-solo-escritorio { display: none; }
}
.rt-orden {
  display: grid;
  gap: 0.75rem;
  grid-template-columns: minmax(0, 1fr);
  grid-template-areas: "cabecera" "acciones" "informacion";
}
.rt-orden-cabecera { grid-area: cabecera; min-width: 0; }
.rt-orden-acciones { grid-area: acciones; min-width: 0; display: grid; gap: 0.75rem; align-content: start; }
.rt-orden-informacion { grid-area: informacion; min-width: 0; display: grid; gap: 0.75rem; align-content: start; grid-template-columns: minmax(0, 1fr); }
@media (min-width: 960px) {
  .rt-orden {
    grid-template-columns: minmax(0, 1fr) minmax(360px, 420px);
    grid-template-rows: auto 1fr;
    grid-template-areas: "cabecera acciones" "informacion acciones";
    align-items: start;
  }
  .rt-orden-acciones {
    position: sticky;
    top: 0.75rem;
    box-sizing: border-box;
    max-height: calc(100vh - 2.5rem);
    overflow-y: auto;
    overscroll-behavior: contain;
    padding-bottom: 0.25rem;
  }
}
`;

/** Qué sección de información abre cada rol sin que la pida. */
const ABIERTA_POR_ROL: Partial<Record<RolUsuario, Informativa>> = {
  ADMINISTRADOR: "cobros",
};

// Búsqueda y filtros del listado: duran lo que la sesión del navegador.
const CLAVE_FILTROS = "rt-rma.filtrosOrdenes";

function leerFiltros(): FiltrosListado {
  try {
    const guardado = window.sessionStorage.getItem(CLAVE_FILTROS);
    return filtrosValidos(guardado ? JSON.parse(guardado) : null);
  } catch {
    return filtrosValidos(null);
  }
}

function guardarFiltros(filtros: FiltrosListado): void {
  try {
    window.sessionStorage.setItem(CLAVE_FILTROS, JSON.stringify(filtros));
  } catch {
    // Sin almacenamiento: los filtros duran mientras la pestaña esté abierta.
  }
}

export function PanelOrdenes() {
  const [usuarios, setUsuarios] = useState<Usuario[]>([]);
  const [tipos, setTipos] = useState<TipoReparacion[]>([]);
  const [estaciones, setEstaciones] = useState<Estacion[]>([]);
  const [medios, setMedios] = useState<MedioPago[]>([]);
  const [prioridades, setPrioridades] = useState<Prioridad[]>([]);
  const [actorId, setActorId] = useState("");

  const [ordenes, setOrdenes] = useState<OrdenResumen[]>([]);
  const [orden, setOrden] = useState<Orden | null>(null);

  const [error, setError] = useState<ErrorDeComando | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [ruta, navegar] = useRuta();
  const rutaActual = useRef<Ruta>(ruta);
  rutaActual.current = ruta;
  // La Orden pedida por URL que no existe.
  const [noEncontrada, setNoEncontrada] = useState<string | null>(null);
  const [listadoCargado, setListadoCargado] = useState(false);
  const [filtros, setFiltros] = useState<FiltrosListado>(leerFiltros);
  useEffect(() => guardarFiltros(filtros), [filtros]);

  // Lugares donde los paneles dibujan sus formularios con un portal.
  const [lugares, setLugares] = useState<Record<number, HTMLElement | null>>(
    {},
  );
  const [especiales, setEspeciales] = useState<HTMLElement | null>(null);
  const [otras, setOtras] = useState<HTMLElement | null>(null);
  const registradores = useRef(
    new Map<number, (elemento: HTMLElement | null) => void>(),
  );
  const registrarTarea = useCallback((indice: number) => {
    let registrar = registradores.current.get(indice);
    if (!registrar) {
      registrar = (elemento) =>
        setLugares((previos) =>
          previos[indice] === elemento
            ? previos
            : { ...previos, [indice]: elemento },
        );
      registradores.current.set(indice, registrar);
    }
    return registrar;
  }, []);

  const actor = usuarios.find((usuario) => usuario.id === actorId) ?? null;

  // Nombres de usuarios y estaciones, para decirlos así en los errores.
  const nombresConocidos = useRef<Record<string, string>>({});
  useEffect(() => {
    nombresConocidos.current = Object.fromEntries(
      [...usuarios, ...estaciones].map((item) => [item.id, item.nombre]),
    );
  }, [usuarios, estaciones]);

  // La Orden en pantalla, para recargarla si un comando choca (409) y para
  // traducir los mensajes de error con los nombres de sus pasos.
  const ordenEnPantalla = useRef<Orden | null>(null);
  useEffect(() => {
    ordenEnPantalla.current = orden;
  }, [orden]);

  const refrescarListado = useCallback(async () => {
    setOrdenes(await api.listarOrdenes());
    setListadoCargado(true);
  }, []);

  const elegirActor = useCallback((usuarioId: string) => {
    setActorId(usuarioId);
    guardarUsuarioDemo(usuarioId);
  }, []);

  useEffect(() => {
    async function cargar() {
      try {
        const [
          listaUsuarios,
          listaTipos,
          listaEstaciones,
          listaMedios,
          listaPrioridades,
        ] = await Promise.all([
          api.listarUsuarios(),
          api.listarTiposReparacion(),
          api.listarEstaciones(),
          api.listarMediosPago(),
          api.listarPrioridades(),
        ]);
        setUsuarios(listaUsuarios);
        setTipos(listaTipos);
        setEstaciones(listaEstaciones);
        setMedios(listaMedios);
        setPrioridades(listaPrioridades);
        // El usuario de demostración recordado, si sigue en el catálogo.
        setActorId(elegirUsuarioDemo(listaUsuarios, leerUsuarioDemo()));
      } catch (fallo) {
        setError(errorDe(fallo, null));
      }
    }
    void cargar();
  }, []);

  /**
   * Ejecuta un comando y deja la Orden devuelta como estado actual.
   *
   * Un 409 significa que la Orden no admitía el comando en su estado
   * REAL: otro usuario la cambió (CONFLICTO_CONCURRENTE), ya está cerrada
   * (ORDEN_CERRADA), la tiene otro técnico (TOMA_DE_OTRO_TECNICO), etc.
   * En todos los casos se recarga desde el backend para no seguir
   * operando sobre datos viejos. El error se muestra junto al formulario
   * desde el que se envió el comando.
   */
  const ejecutarComando = useCallback(
    async (comando: () => Promise<Orden>) => {
      const activo = document.activeElement;
      const clave =
        activo instanceof HTMLElement
          ? (activo.closest("[data-accion]")?.getAttribute("data-accion") ??
            null)
          : null;
      setOcupado(true);
      setError(null);
      try {
        const actualizada = await comando();
        ordenEnPantalla.current = actualizada;
        setOrden(actualizada);
        // Una Orden nueva (alta o garantía RMA) se abre en su propia URL.
        const actual = rutaActual.current;
        if (actual.pantalla !== "orden" || actual.ordenId !== actualizada.id) {
          navegar({ pantalla: "orden", ordenId: actualizada.id });
        }
        await refrescarListado();
      } catch (fallo) {
        const ordenId = ordenEnPantalla.current?.id ?? null;
        const conflicto = fallo instanceof ApiError && fallo.status === 409;
        let recargada = false;
        if (conflicto && ordenId) {
          try {
            setOrden(await api.obtenerOrden(ordenId));
            await refrescarListado();
            recargada = true;
          } catch {
            // Si la recarga tambien falla, queda el mensaje original.
          }
        }
        setError(
          errorDe(
            fallo,
            ordenEnPantalla.current,
            clave,
            recargada,
            nombresConocidos.current,
          ),
        );
      } finally {
        setOcupado(false);
      }
    },
    [refrescarListado, navegar],
  );

  const abrirOrden = useCallback(async (ordenId: string) => {
    setError(null);
    setNoEncontrada(null);
    try {
      const leida = await api.obtenerOrden(ordenId);
      // Si mientras tanto se navegó a otra pantalla, la respuesta ya no va.
      const actual = rutaActual.current;
      if (actual.pantalla === "orden" && actual.ordenId === ordenId) {
        ordenEnPantalla.current = leida;
        setOrden(leida);
      }
    } catch (fallo) {
      if (fallo instanceof ApiError && fallo.status === 404) {
        setOrden(null);
        setNoEncontrada(ordenId);
      } else {
        setError(errorDe(fallo, null));
      }
    }
  }, []);

  // La URL manda: abre la Orden pedida o vuelve al listado (solo lecturas).
  useEffect(() => {
    if (ruta.pantalla === "orden") {
      if (ordenEnPantalla.current?.id !== ruta.ordenId) {
        setOrden(null);
        void abrirOrden(ruta.ordenId);
      }
      return;
    }
    ordenEnPantalla.current = null;
    setOrden(null);
    setNoEncontrada(null);
    setError(null);
    if (ruta.pantalla === "ordenes") {
      refrescarListado().catch((fallo) => setError(errorDe(fallo, null)));
    }
  }, [ruta, abrirOrden, refrescarListado]);

  // A qué tarea de «Próximo paso» corresponde cada acción que el usuario
  // puede ejecutar (la lista la manda el backend en la situación).
  const tareaDeAccion = useMemo(() => {
    const mapa = new Map<string, { indice: number; unica: boolean }>();
    orden?.situacion?.tareas.forEach((tarea, indice) => {
      const propias = tarea.acciones.filter((accion) =>
        puedeEjecutar(accion, actor),
      );
      // Una opción secundaria (interrumpir) no le quita el título a la
      // principal: va plegada detrás de su propio botón.
      const principales = propias.filter(
        (accion) => !CODIGOS_SECUNDARIOS.has(accion.codigo),
      );
      propias.forEach((accion) =>
        mapa.set(claveDeAccion(accion), {
          indice,
          unica: principales.length <= 1,
        }),
      );
    });
    // Pasos recomendados que no son tareas del backend (el comprobante de
    // autorización): su propio lugar al principio de «Próximo paso».
    if (orden && !orden.cerrada) {
      accionesDeLaOrden(orden)
        .filter(
          (accion) =>
            accion.codigo in PASOS_RECOMENDADOS &&
            puedeEjecutar(accion, actor),
        )
        .forEach((accion) =>
          mapa.set(claveDeAccion(accion), {
            indice: INDICE_PASO_RECOMENDADO,
            unica: true,
          }),
        );
    }
    return mapa;
  }, [orden, actor]);

  const enProximoPaso = useCallback(
    (accion: Accion) => {
      const tarea = tareaDeAccion.get(claveDeAccion(accion));
      const lugar = tarea ? lugares[tarea.indice] : null;
      return tarea && lugar ? { lugar, unica: tarea.unica } : null;
    },
    [tareaDeAccion, lugares],
  );

  const idActor = actor?.id ?? "";
  const idOrden = orden?.id ?? "";
  // Se muestra la Orden de la URL, no otra que quedó de la pantalla anterior.
  const enDetalle = ruta.pantalla === "orden" && orden?.id === ruta.ordenId;

  const ejecutor: EjecutorAcciones = {
    agregarDetalle: (tipoId, otros) =>
      void ejecutarComando(() =>
        api.definirReparacion(idOrden, idActor, tipoId, otros),
      ),
    finalizarDefinicion: () =>
      void ejecutarComando(() => api.finalizarDefinicion(idOrden, idActor)),
    encolar: (prioridad) =>
      void ejecutarComando(() =>
        api.encolar(idOrden, idActor, prioridad),
      ),
    tomar: (estacionId) =>
      void ejecutarComando(() =>
        api.tomarOrden(idOrden, idActor, estacionId),
      ),
    iniciarDetalle: (detalleId) =>
      void ejecutarComando(() =>
        api.iniciarDetalle(idOrden, detalleId, idActor),
      ),
    completarEjecucion: (ejecucionId, insumosUtilizados, observaciones) =>
      void ejecutarComando(() =>
        api.completarEjecucion(
          idOrden,
          ejecucionId,
          idActor,
          insumosUtilizados,
          observaciones || null,
        ),
      ),
    esperarRecursos: () =>
      void ejecutarComando(() => api.esperarRecursos(idOrden)),
    consultarImpactoOverride: (detalleId) =>
      api.obtenerImpactoOverride(idOrden, detalleId),
    // Solo se invoca tras la confirmación explícita del impacto (E3).
    overrideRecursos: (detalleId, motivo) =>
      void ejecutarComando(() =>
        api.overrideRecursos(idOrden, detalleId, idActor, motivo, true),
      ),
    revalidarRecursos: () =>
      void ejecutarComando(() => api.revalidarRecursos(idOrden)),
    interrumpirEjecucion: (
      ejecucionId,
      insumosUtilizados,
      motivo,
      observaciones,
    ) =>
      void ejecutarComando(() =>
        api.interrumpirEjecucion(
          idOrden,
          ejecucionId,
          idActor,
          insumosUtilizados,
          motivo,
          observaciones || null,
        ),
      ),
    requerirRedefinicion: (
      ejecucionId,
      insumosUtilizados,
      motivo,
      observaciones,
    ) =>
      void ejecutarComando(() =>
        api.requerirRedefinicion(
          idOrden,
          ejecucionId,
          idActor,
          insumosUtilizados,
          motivo,
          observaciones || null,
        ),
      ),
    revisarDetalle: (detalleId, resultado) =>
      void ejecutarComando(() =>
        api.revisarDetalle(idOrden, detalleId, idActor, resultado),
      ),
    redefinirDetalle: (detalleId, tipoId) =>
      void ejecutarComando(() =>
        api.redefinirDetalle(idOrden, detalleId, idActor, tipoId),
      ),
    aprobarControl: (detalleId, observaciones) =>
      void ejecutarComando(() =>
        api.aprobarControl(idOrden, idActor, detalleId, observaciones || null),
      ),
    liberarOrden: () =>
      void ejecutarComando(() => api.liberarOrden(idOrden, idActor)),
    notificar: () =>
      void ejecutarComando(() => api.notificar(idOrden, idActor)),
    entregar: (retiro) =>
      void ejecutarComando(() => api.entregar(idOrden, idActor, retiro)),
    informarRt: () => void ejecutarComando(() => api.informarRt(idOrden)),
    devolverRt: () =>
      void ejecutarComando(() => api.devolverRt(idOrden, idActor)),
    enviarARevision: () =>
      void ejecutarComando(() => api.enviarARevision(idOrden, idActor)),
    realizarRevision: (resultado) =>
      void ejecutarComando(() =>
        api.realizarRevision(idOrden, idActor, resultado),
      ),
    agregarDetalleDesdeRevision: (tipoId, detalleOrigenId, otros) =>
      void ejecutarComando(() =>
        api.definirReparacionDesdeRevision(
          idOrden,
          idActor,
          tipoId,
          detalleOrigenId,
          otros,
        ),
      ),
    finalizarSinReparacion: (motivo, observaciones) =>
      void ejecutarComando(() =>
        api.finalizarSinReparacion(
          idOrden,
          idActor,
          motivo,
          observaciones || null,
        ),
      ),
    // Devuelve la NUEVA Orden de garantía: queda abierta en pantalla.
    iniciarGarantiaRma: (detalleOrigenIds) =>
      void ejecutarComando(() =>
        api.iniciarGarantiaRma(idOrden, idActor, detalleOrigenIds),
      ),
    rechazarControl: (detalleId, motivo) =>
      void ejecutarComando(() =>
        api.rechazarControl(idOrden, idActor, detalleId, motivo),
      ),
    registrarDevolucion: (retiro) =>
      void ejecutarComando(() =>
        api.registrarDevolucion(idOrden, idActor, retiro),
      ),
    cancelarDetalle: (detalleId, motivo) =>
      void ejecutarComando(() =>
        api.cancelarDetalle(idOrden, detalleId, idActor, motivo),
      ),
    cancelarOrden: (motivo) =>
      void ejecutarComando(() => api.cancelarOrden(idOrden, idActor, motivo)),
    cambiarPrioridad: (prioridad, motivo) =>
      void ejecutarComando(() =>
        api.cambiarPrioridad(idOrden, idActor, prioridad, motivo),
      ),
    liberarOrdenAjena: (motivo, insumosUtilizados) =>
      void ejecutarComando(() =>
        api.liberarOrdenAjena(idOrden, idActor, motivo, insumosUtilizados),
      ),
    ajustarGarantia: (detalleId, dias, motivo) =>
      void ejecutarComando(() =>
        api.ajustarGarantia(idOrden, detalleId, idActor, dias, motivo),
      ),
    registrarCheckin: (realizado) =>
      void ejecutarComando(() =>
        api.registrarCheckin(idOrden, idActor, realizado),
      ),
  };

  const contexto = {
    actor,
    enProximoPaso,
    especiales,
    otras,
    error,
  };

  // Tomar desde la cola del taller: el mismo comando que en la Orden. Si
  // sale bien, `ejecutarComando` abre la Orden tomada.
  const tomarDesdeCola = (ordenId: string, estacionId: string) =>
    ejecutarComando(() => api.tomarOrden(ordenId, idActor, estacionId));

  // Qué acciones van a «Otras acciones» y a «Situaciones especiales».
  const porLugar = orden
    ? accionesPorLugar(orden, actor)
    : { especiales: [], otras: [] };
  const abiertaPara = (seccion: Informativa) =>
    actor !== null && ABIERTA_POR_ROL[actor.rol] === seccion;

  // La sección del menú que corresponde a la pantalla actual.
  const seccion =
    ruta.pantalla === "nueva" || ruta.pantalla === "orden"
      ? "ordenes"
      : ruta.pantalla;

  return (
    <div
      style={{
        maxWidth: enDetalle ? 1360 : 1040,
        margin: "0 auto",
        padding: "1rem",
      }}
    >
      <style>{ESTILOS_RESPONSIVOS}</style>
      <header
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          gap: "0.75rem",
          flexWrap: "wrap",
          marginBottom: "1rem",
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: "1.4rem" }}>Rosario Tecno</h1>
          <p style={{ margin: 0, color: colores.suave }}>
            Gestión de reparaciones
          </p>
        </div>
        <SelectorActor
          usuarios={usuarios}
          actorId={actorId}
          onCambiar={elegirActor}
        />
      </header>

      <nav
        aria-label="Secciones"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "0.5rem",
          marginBottom: "0.75rem",
        }}
      >
        {(
          [
            ["inicio", "Inicio"],
            ["ordenes", "Órdenes"],
            ["taller", "Taller"],
            ["inventario", "Inventario"],
          ] as const
        ).map(([clave, nombre]) => (
          <Boton
            key={clave}
            variante={seccion === clave ? "primario" : "secundario"}
            onClick={() => {
              setError(null);
              navegar({ pantalla: clave });
            }}
          >
            {nombre}
          </Boton>
        ))}
        {/* En el celular «Órdenes» ya vuelve al listado. */}
        {(ruta.pantalla === "orden" || ruta.pantalla === "nueva") && (
          <span className="rt-solo-escritorio">
            <Boton
              variante="secundario"
              onClick={() => navegar({ pantalla: "ordenes" })}
            >
              ← Volver al listado
            </Boton>
          </span>
        )}
      </nav>

      {error && !enDetalle && <MensajeDeComando error={error} />}

      {ruta.pantalla === "inicio" ? (
        <PantallaInicio
          actor={actor}
          usuarios={usuarios}
          estaciones={estaciones}
          onIr={(pantalla) => navegar({ pantalla })}
        />
      ) : ruta.pantalla === "taller" ? (
        <PantallaTaller
          actor={actor}
          usuarios={usuarios}
          estaciones={estaciones}
          ocupado={ocupado}
          onIr={(pantalla) => navegar({ pantalla })}
          onTomar={tomarDesdeCola}
        />
      ) : ruta.pantalla === "inventario" ? (
        <InventarioPanel actor={actor} usuarios={usuarios} />
      ) : ruta.pantalla === "nueva" ? (
        <FormularioAltaOrden
          actor={actor}
          ocupado={ocupado}
          onCrearClienteExterno={(datos) =>
            void ejecutarComando(() => api.crearOrden(datos))
          }
          onCrearRtInterno={(datos) =>
            void ejecutarComando(() => api.crearOrdenRt(datos))
          }
          onCancelar={() => navegar({ pantalla: "ordenes" })}
        />
      ) : ruta.pantalla === "ordenes" ? (
        <PantallaOrdenes
          ordenes={ordenes}
          usuarios={usuarios}
          actor={actor}
          filtros={filtros}
          onFiltros={setFiltros}
          onNueva={() => navegar({ pantalla: "nueva" })}
          cargado={listadoCargado}
        />
      ) : noEncontrada === ruta.ordenId ? (
        <Panel>
          <h2 style={{ margin: "0 0 0.4rem", fontSize: "1.1rem" }}>
            No existe la orden «{ruta.ordenId}»
          </h2>
          <p style={{ margin: "0 0 0.8rem", color: colores.suave }}>
            Revisá el número o buscá la orden en el listado.
          </p>
          <Boton onClick={() => navegar({ pantalla: "ordenes" })}>
            Ir al listado de órdenes
          </Boton>
        </Panel>
      ) : !orden || !enDetalle ? (
        !error && (
          <Panel>
            <p style={{ margin: 0, color: colores.suave }}>
              Cargando la orden {ruta.ordenId}…
            </p>
          </Panel>
        )
      ) : (
        <ProveedorPresentacion value={contexto}>
          {/*
            minmax(0, 1fr): ningún contenido ancho (por ejemplo el
            historial) ensancha la pantalla en el celular.
          */}
          <div className="rt-orden">
            <div className="rt-orden-cabecera">
              <CabeceraOrden
                orden={orden}
                usuarios={usuarios}
                estaciones={estaciones}
              />
            </div>

            <aside className="rt-orden-acciones" aria-label="Acciones de la orden">
              <ProximoPaso
                orden={orden}
                actor={actor}
                usuarios={usuarios}
                registrarTarea={registrarTarea}
                errorGeneral={errorSinLugar(error, orden, actor)}
              />
              {porLugar.otras.length > 0 && (
                <SeccionPlegable
                  key={`${orden.id}-${actorId}-otras`}
                  titulo="Otras acciones"
                  resumen={nombresDe(porLugar.otras).join(" · ")}
                >
                  <LugarDeFormularios onElemento={setOtras} />
                </SeccionPlegable>
              )}
              {porLugar.especiales.length > 0 && (
                <SeccionPlegable
                  key={`${orden.id}-${actorId}-especiales`}
                  titulo="Situaciones especiales"
                  resumen={nombresDe(porLugar.especiales).join(" · ")}
                >
                  <p
                    style={{
                      margin: "0 0 0.8rem",
                      fontSize: "0.8rem",
                      color: colores.suave,
                    }}
                  >
                    Situaciones excepcionales. Cancelar no borra nada: el
                    trabajo queda cancelado con su motivo y deja de cobrarse.
                  </p>
                  <LugarDeFormularios onElemento={setEspeciales} />
                </SeccionPlegable>
              )}
            </aside>

            <div className="rt-orden-informacion">
              {/* Solo formularios: cada uno va a su lugar del panel. */}
              <AccionesOrden
                orden={orden}
                actor={actor}
                usuarios={usuarios}
                tipos={tipos}
                estaciones={estaciones}
                prioridades={prioridades}
                ocupado={ocupado}
                ejecutar={ejecutor}
              />
              <CancelacionesOrden
                orden={orden}
                actor={actor}
                usuarios={usuarios}
                tipos={tipos}
                estaciones={estaciones}
                prioridades={prioridades}
                ocupado={ocupado}
                ejecutar={ejecutor}
              />
              <ComplementariasOrden
                orden={orden}
                actor={actor}
                usuarios={usuarios}
                tipos={tipos}
                estaciones={estaciones}
                prioridades={prioridades}
                ocupado={ocupado}
                ejecutar={ejecutor}
              />

              <SeccionPlegable
                key={`${orden.id}-${actorId}-cliente`}
                titulo="Cliente y equipo"
                resumen={resumenCliente(orden)}
                abierta={abiertaPara("cliente")}
              >
                <CustodiaOrden
                  orden={orden}
                  actor={actor}
                  usuarios={usuarios}
                  ocupado={ocupado}
                  onRegistrar={(datos, equipo) =>
                    void ejecutarComando(() =>
                      api.registrarRecepcion(idOrden, idActor, datos, equipo),
                    )
                  }
                  onConfirmar={(observaciones) =>
                    void ejecutarComando(() =>
                      api.confirmarRecepcion(idOrden, idActor, observaciones),
                    )
                  }
                  onNoRecibido={(motivo) =>
                    void ejecutarComando(() =>
                      api.registrarEquipoNoRecibido(idOrden, idActor, motivo),
                    )
                  }
                  onObservar={(texto, interna) =>
                    void ejecutarComando(() =>
                      api.agregarObservacionRecepcion(
                        idOrden,
                        idActor,
                        texto,
                        interna,
                      ),
                    )
                  }
                />
              </SeccionPlegable>

              <SeccionPlegable
                key={`${orden.id}-trabajos`}
                titulo="Trabajos"
                resumen={resumenTrabajos(orden)}
                abierta
              >
                <TrabajosOrden orden={orden} usuarios={usuarios} />
              </SeccionPlegable>

              {orden.autorizacion_requerida &&
                orden.reparaciones_detail.length > 0 && (
                  <SeccionPlegable
                    key={`${orden.id}-${actorId}-autorizacion`}
                    titulo="Autorización del cliente"
                    resumen={resumenAutorizacion(orden)}
                    abierta={abiertaPara("autorizacion")}
                  >
                    <AutorizacionClienteOrden
                      orden={orden}
                      actor={actor}
                      usuarios={usuarios}
                      ocupado={ocupado}
                      onRegistrar={(canal, observaciones, decisiones) =>
                        void ejecutarComando(() =>
                          api.registrarDecisionCliente(
                            idOrden,
                            idActor,
                            canal,
                            observaciones || null,
                            decisiones,
                          ),
                        )
                      }
                      onDesistir={(detalleId, canal, motivo) =>
                        void ejecutarComando(() =>
                          api.desistir(
                            idOrden,
                            detalleId,
                            idActor,
                            canal,
                            motivo,
                          ),
                        )
                      }
                    />
                  </SeccionPlegable>
                )}

              <SeccionPlegable
                key={`${orden.id}-${actorId}-ejecuciones`}
                titulo="Ejecuciones e insumos"
                resumen={resumenEjecuciones(orden)}
                abierta={abiertaPara("ejecuciones")}
              >
                <EjecucionesEInsumos orden={orden} usuarios={usuarios} />
              </SeccionPlegable>

              <SeccionPlegable
                key={`${orden.id}-${actorId}-cobros`}
                titulo="Cobros"
                resumen={resumenCobros(orden)}
                abierta={abiertaPara("cobros")}
              >
                <PagosYMovimientos
                  orden={orden}
                  actor={actor}
                  usuarios={usuarios}
                  medios={medios}
                  ocupado={ocupado}
                  onPagar={(monto, metodo, referencia, operacionId) =>
                    void ejecutarComando(() =>
                      api.registrarPago(
                        idOrden,
                        idActor,
                        monto,
                        metodo,
                        referencia,
                        operacionId,
                      ),
                    )
                  }
                  onAnular={(pagoId, motivo) =>
                    void ejecutarComando(() =>
                      api.anularPago(idOrden, pagoId, idActor, motivo),
                    )
                  }
                  onDevolver={(datos) =>
                    void ejecutarComando(() =>
                      api.devolverDinero(idOrden, idActor, datos),
                    )
                  }
                  onDescontar={(tipo, valor, motivo) =>
                    void ejecutarComando(() =>
                      api.aplicarDescuento(idOrden, idActor, tipo, valor, motivo),
                    )
                  }
                />
              </SeccionPlegable>

              <SeccionPlegable
                key={`${orden.id}-${actorId}-documentos`}
                titulo="Documentos"
                resumen={resumenDocumentos(orden)}
                abierta={abiertaPara("documentos")}
              >
                <DocumentosOrden
                  orden={orden}
                  actor={actor}
                  usuarios={usuarios}
                  ocupado={ocupado}
                  onEmitirRecepcion={(motivo) =>
                    void ejecutarComando(() =>
                      api.emitirComprobanteRecepcion(idOrden, idActor, motivo),
                    )
                  }
                  onEmitirAutorizacion={() =>
                    void ejecutarComando(() =>
                      api.emitirComprobanteAutorizacion(idOrden, idActor),
                    )
                  }
                  onGenerarIngreso={(canal) =>
                    void ejecutarComando(() =>
                      api.generarComprobanteIngreso(idOrden, idActor, canal),
                    )
                  }
                />
              </SeccionPlegable>

              <SeccionPlegable
                key={`${orden.id}-historial`}
                titulo="Historial y datos técnicos"
                resumen={`${orden.historial.length} eventos registrados`}
              >
                <Bloque titulo="Datos técnicos">
                  <DatosTecnicos orden={orden} />
                </Bloque>
                <Bloque titulo="Recorrido técnico del proceso">
                  <ProgresoHappyPath orden={orden} />
                </Bloque>
                <Bloque titulo="Ejecuciones (técnico)">
                  <EjecucionesOrden orden={orden} />
                </Bloque>
                <Bloque titulo="Historial">
                  <HistorialOrden orden={orden} />
                </Bloque>
              </SeccionPlegable>
            </div>
          </div>
        </ProveedorPresentacion>
      )}

      {usuarios.length === 0 && !error && (
        <Panel>
          <p style={{ margin: 0, color: colores.suave }}>Cargando…</p>
        </Panel>
      )}
    </div>
  );
}

function errorDe(
  fallo: unknown,
  orden: Orden | null,
  clave: string | null = null,
  recargada = false,
  nombres: Record<string, string> = {},
): ErrorDeComando {
  if (!(fallo instanceof ApiError)) {
    return {
      mensaje: "Ocurrió un error inesperado.",
      tecnico: String(fallo),
      clave,
    };
  }
  const prefijo =
    fallo.codigo === "CONFLICTO_CONCURRENTE"
      ? "Otra operación modificó la Orden al mismo tiempo. "
      : "";
  const sufijo = recargada ? " Se recargó la Orden con su estado actual." : "";
  return {
    mensaje: `${prefijo}${mensajeLegible(fallo.message, orden, nombres)}` +
      sufijo,
    tecnico: fallo.message,
    clave,
  };
}

/**
 * El error que no tiene un formulario visible al lado (por ejemplo, la
 * acción ya no corresponde tras recargar): lo muestra «Próximo paso».
 */
function errorSinLugar(
  error: ErrorDeComando | null,
  orden: Orden,
  actor: Usuario | null,
): ErrorDeComando | null {
  if (error === null) return null;
  if (error.clave === null) return error;
  const visible = accionesDeLaOrden(orden).some(
    (accion) =>
      claveDeAccion(accion) === error.clave && puedeEjecutar(accion, actor),
  );
  return visible ? null : error;
}

/** Nombres (sin repetir) de un grupo de acciones, para el resumen. */
function nombresDe(acciones: Accion[]): string[] {
  return [
    ...new Set(
      acciones.map((accion) => NOMBRE_ACCION[accion.codigo] ?? accion.etiqueta),
    ),
  ];
}

function resumenTrabajos(orden: Orden): ReactNode {
  if (orden.reparaciones_detail.length === 0) {
    return orden.finalizada_sin_reparacion
      ? "Sin reparación"
      : "Todavía sin trabajos definidos";
  }
  return orden.reparaciones_detail
    .map(
      (detalle) =>
        `${detalle.tipo_reparacion_nombre} (${etiqueta(
          ESTADO_TRABAJO,
          detalle.estado,
        ).toLowerCase()})`,
    )
    .join(" · ");
}

/** [singular, plural] para el resumen de la autorización. */
const RESUMEN_AUTORIZACION: Record<string, [string, string]> = {
  PENDIENTE_COMPROBANTE_INGRESO: [
    "pendiente de comprobante de ingreso",
    "pendientes de comprobante de ingreso",
  ],
  AUTORIZADO: ["autorizado", "autorizados"],
  PENDIENTE: ["esperando al cliente", "esperando al cliente"],
  RECHAZADO: ["rechazado", "rechazados"],
  SIN_DECISION: ["sin decisión", "sin decisión"],
  NO_REQUERIDA: ["sin autorización requerida", "sin autorización requerida"],
};

function resumenAutorizacion(orden: Orden): string {
  const cuenta = new Map<string, number>();
  for (const detalle of orden.reparaciones_detail) {
    if (detalle.estado === "CANCELADO") continue;
    const estado = detalle.pendiente_comprobante_ingreso
      ? "PENDIENTE_COMPROBANTE_INGRESO"
      : detalle.estado_autorizacion;
    cuenta.set(estado, (cuenta.get(estado) ?? 0) + 1);
  }
  return (
    [...cuenta]
      .map(([estado, cantidad]) => {
        const [uno, varios] = RESUMEN_AUTORIZACION[estado] ?? [estado, estado];
        return `${cantidad} ${cantidad === 1 ? uno : varios}`;
      })
      .join(" · ") || "Sin trabajos vigentes"
  );
}

function resumenEjecuciones(orden: Orden): string {
  const cantidad = orden.ejecuciones.length;
  if (cantidad === 0) return "Todavía no se empezó ningún trabajo";
  const enCurso = orden.ejecuciones.some(
    (ejecucion) => ejecucion.estado === "EN_PROGRESO",
  );
  return `${cantidad} ejecución${cantidad === 1 ? "" : "es"}${
    enCurso ? " · una en curso" : ""
  }`;
}

function resumenCliente(orden: Orden): string {
  return [
    orden.cliente
      ? `${orden.cliente.nombre} · ${orden.cliente.telefono}`
      : `Equipo interno RT · ${orden.referencia_rt ?? "—"}`,
    `Equipo: ${etiqueta(CUSTODIA, orden.custodia.estado).toLowerCase()}`,
    orden.recepcion?.datos.estado_fisico,
  ]
    .filter(Boolean)
    .join(" · ");
}

function resumenCobros(orden: Orden): string {
  const { resumen } = orden;
  if (resumen.condicion_comercial !== "COBRABLE") {
    return "No se cobra al cliente";
  }
  const saldo = Number(resumen.saldo);
  return saldo < 0
    ? `Crédito a favor del cliente: ${importe(resumen.credito_a_favor)}`
    : `Saldo ${importe(resumen.saldo)} · pagado ${importe(resumen.pagado)} · ${etiqueta(
        ESTADO_PAGO,
        resumen.estado_pago,
      ).toLowerCase()}`;
}

function resumenDocumentos(orden: Orden): string {
  const cantidad = orden.documentos_emitidos.length;
  return cantidad === 0
    ? "Ningún documento emitido"
    : `${cantidad} documento${cantidad === 1 ? "" : "s"} emitido${cantidad === 1 ? "" : "s"}`;
}
