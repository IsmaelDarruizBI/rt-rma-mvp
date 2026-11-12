/**
 * Contenedor de la feature: carga datos, ejecuta comandos y decide qué
 * pantalla mostrar (listado o una Orden).
 *
 * Es el único componente con estado de verdad. Toda la lógica de negocio
 * vive en el backend: acá solo se llama a la API y se muestra lo que
 * devuelve, incluidas las acciones disponibles y la situación operativa.
 *
 * Todas las pantallas comparten el layout (sidebar + barra superior). En
 * una Orden, las acciones que el usuario puede ejecutar están en la barra
 * superior (las excepcionales, en «Más acciones») y cada una abre su
 * formulario en una ventana superpuesta; a la derecha, «Pendientes» dice
 * lo que falta resolver. En el celular es una sola columna.
 *
 * Qué pantalla se ve lo decide la URL (`#/inicio`, `#/ordenes`,
 * `#/ordenes/nueva`, `#/ordenes/OR-000001`, `#/taller`, `#/inventario`):
 * navegar solo lee, nunca envía comandos. La búsqueda, los filtros y el
 * usuario de demostración sobreviven a la navegación.
 *
 * Sin sesión de demostración se muestra el acceso (``LoginDemo``, UAT): es
 * solo look & feel y navegación por rol, no autenticación.
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
import {
  PantallaInicio,
  PantallaTaller,
  olvidarBandejas,
} from "./PantallasTrabajo";
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
import { FotosOrden, resumenFotos } from "./FotosOrden";
import {
  CUSTODIA,
  ESTADO_PAGO,
  ESTADO_TRABAJO,
  nombreDeAccion,
  ROL,
  etiqueta,
  mensajeLegible,
} from "./etiquetas";
import { PagosYMovimientos } from "./PagosOrden";
import { FormularioAltaOrden, PantallaOrdenes } from "./ListadoOrdenes";
import { LoginDemo } from "./LoginDemo";
import { type FiltrosListado, filtrosValidos } from "./listado";
import { type Ruta } from "./rutas";
import {
  borrarUsuarioDemo,
  elegirUsuarioDemo,
  guardarUsuarioDemo,
  leerUsuarioDemo,
} from "./usuarioDemo";
import { useRuta } from "./useRuta";
import {
  type AccionRegistrada,
  AnfitrionAcciones,
  EVENTO_ABRIR_ACCION,
  type ErrorDeComando,
  MensajeDeComando,
  ProveedorPresentacion,
  SeccionPlegable,
  accionesDeLaOrden,
  claveDeAccion,
  puedeEjecutar,
} from "./presentacion";
import { Pendientes } from "./Pendientes";
import {
  CODIGOS_ESPECIALES,
  clavesDeTareas,
  organizarBarra,
} from "./acciones";
import { Layout, MenuAcciones, type Seccion } from "../../components/layout";
import { Modal } from "../../components/Modal";

type Informativa =
  | "cliente"
  | "trabajos"
  | "autorizacion"
  | "ejecuciones"
  | "cobros"
  | "documentos";

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

/** Una sesión real (Supabase Auth): el usuario lo decidió el backend. */
export interface SesionReal {
  usuarioId: string;
  cerrar: () => void;
}

export function PanelOrdenes({ sesion }: { sesion?: SesionReal } = {}) {
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

  // Acciones registradas por sus formularios y la que está abierta.
  const [registradas, setRegistradas] = useState<
    ReadonlyMap<string, AccionRegistrada>
  >(new Map());
  const [abierta, setAbierta] = useState<string | null>(null);
  const registrar = useCallback((registrada: AccionRegistrada) => {
    setRegistradas((previas) => {
      const nuevas = new Map(previas);
      nuevas.set(registrada.clave, registrada);
      return nuevas;
    });
  }, []);
  const quitar = useCallback((clave: string, contenedor: HTMLElement) => {
    setRegistradas((previas) => {
      if (previas.get(clave)?.contenedor !== contenedor) return previas;
      const nuevas = new Map(previas);
      nuevas.delete(clave);
      return nuevas;
    });
  }, []);
  useEffect(() => {
    const abrir = (evento: Event) =>
      setAbierta((evento as CustomEvent<string>).detail);
    window.addEventListener(EVENTO_ABRIR_ACCION, abrir);
    return () => window.removeEventListener(EVENTO_ABRIR_ACCION, abrir);
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

  // Cerrar sesión: olvida el usuario y vuelve al acceso. Se cierra la Orden
  // abierta para que el próximo usuario no herede la pantalla anterior.
  const cerrarSesion = useCallback(() => {
    if (!sesion) borrarUsuarioDemo();
    olvidarBandejas();
    setActorId("");
    setOrden(null);
    setError(null);
    navegar({ pantalla: "inicio" });
    sesion?.cerrar();
  }, [navegar, sesion]);

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
        // Con sesión real, el usuario de la sesión. En demo, el recordado
        // si sigue en el catálogo; si no, se muestra el acceso.
        setActorId(
          sesion
            ? sesion.usuarioId
            : elegirUsuarioDemo(listaUsuarios, leerUsuarioDemo()),
        );
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
        // Hecho: la ventana de la acción se cierra; la pantalla ya se
        // actualizó con la Orden devuelta.
        setAbierta(null);
        // Una Orden nueva (alta o garantía RMA) se abre en su propia URL. El
        // listado no se pide acá: se vuelve a leer al entrar a esa pantalla.
        const actual = rutaActual.current;
        if (actual.pantalla !== "orden" || actual.ordenId !== actualizada.id) {
          navegar({ pantalla: "orden", ordenId: actualizada.id });
        }
      } catch (fallo) {
        const ordenId = ordenEnPantalla.current?.id ?? null;
        const conflicto = fallo instanceof ApiError && fallo.status === 409;
        let recargada = false;
        if (conflicto && ordenId) {
          try {
            setOrden(await api.obtenerOrden(ordenId));
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
    [navegar],
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
      resultado,
    ) =>
      void ejecutarComando(() =>
        api.interrumpirEjecucion(
          idOrden,
          ejecucionId,
          idActor,
          insumosUtilizados,
          motivo,
          observaciones || null,
          resultado?.estadoTrabajo ?? null,
          resultado ? resultado.reversible : null,
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
    iniciarGarantiaRma: (detalleOrigenIds, excepciones) =>
      void ejecutarComando(() =>
        api.iniciarGarantiaRma(
          idOrden,
          idActor,
          detalleOrigenIds,
          excepciones,
        ),
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

  const contexto = useMemo(
    () => ({ actor, error, registrar, quitar }),
    [actor, error, registrar, quitar],
  );

  // Tomar desde la cola del taller: el mismo comando que en la Orden. Si
  // sale bien, `ejecutarComando` abre la Orden tomada.
  const tomarDesdeCola = (ordenId: string, estacionId: string) =>
    ejecutarComando(() => api.tomarOrden(ordenId, idActor, estacionId));

  const abiertaPara = (seccion: Informativa) =>
    actor !== null && ABIERTA_POR_ROL[actor.rol] === seccion;

  // La sección del menú que corresponde a la pantalla actual.
  const seccion: Seccion =
    ruta.pantalla === "nueva" || ruta.pantalla === "orden"
      ? "ordenes"
      : ruta.pantalla;

  // La barra de acciones de la Orden: solo lo que el usuario puede hacer
  // (sus formularios se registraron), primero lo que resuelve una tarea.
  const botonesVisibles = useBotonesVisibles();
  const barraOrden =
    orden && enDetalle
      ? organizarBarra(
          [...registradas.values()].map(({ clave, accion }) => ({
            clave,
            accion,
          })),
          clavesDeTareas(orden, actor),
          botonesVisibles,
        )
      : { visibles: [], menu: [] };
  const accionAbierta = abierta ? (registradas.get(abierta) ?? null) : null;
  const nombreAccion = (accion: Accion) => nombreDeAccion(accion);

  // Con sesión real, mientras llegan los catálogos (o si fallaron).
  if (actor === null && sesion) {
    return (
      <div style={{ maxWidth: 880, margin: "2rem auto", padding: "0 1rem" }}>
        {error ? (
          <>
            <MensajeDeComando error={error} />
            <Boton variante="secundario" onClick={cerrarSesion}>
              Cerrar sesión
            </Boton>
          </>
        ) : (
          <p role="status">Cargando…</p>
        )}
      </div>
    );
  }

  // Sin sesión de demostración: pantalla de acceso (desarrollo local).
  if (actor === null) {
    return (
      <>
        <LoginDemo usuarios={usuarios} onIngresar={elegirActor} />
        {error && (
          <div style={{ maxWidth: 880, margin: "-1rem auto 1.5rem", padding: "0 1rem" }}>
            <MensajeDeComando error={error} />
          </div>
        )}
      </>
    );
  }

  const tituloOrdenes = {
    titulo: "Órdenes",
    subtitulo: "Órdenes de reparación",
    acciones: (
      <Boton onClick={() => navegar({ pantalla: "nueva" })}>+ Nueva orden</Boton>
    ),
  };
  const barra =
    ruta.pantalla === "inicio"
      ? { titulo: "Inicio", subtitulo: "Tus tareas de hoy" }
      : ruta.pantalla === "taller"
        ? { titulo: "Taller", subtitulo: "Cola de trabajo y órdenes en reparación" }
        : ruta.pantalla === "inventario"
          ? { titulo: "Inventario", subtitulo: "Stock, reservas y movimientos" }
          : ruta.pantalla === "orden"
            ? {
                titulo: `Orden ${ruta.ordenId}`,
                subtitulo: orden && enDetalle ? resumenCliente(orden) : undefined,
                acciones: (
                  <>
                    <button
                      type="button"
                      className="rt-btn rt-btn--fantasma rt-solo-escritorio"
                      onClick={() => navegar({ pantalla: "ordenes" })}
                    >
                      ← Órdenes
                    </button>
                    {barraOrden.visibles.map(({ clave, accion }, indice) => (
                      <button
                        key={clave}
                        type="button"
                        className={`rt-btn${indice === 0 ? " rt-btn--primario" : ""}`}
                        disabled={ocupado}
                        title={nombreAccion(accion)}
                        onClick={() => setAbierta(clave)}
                      >
                        <span className="rt-btn__texto">{nombreAccion(accion)}</span>
                      </button>
                    ))}
                    <MenuAcciones
                      items={barraOrden.menu.map(({ clave, accion }, indice) => {
                        const especial = CODIGOS_ESPECIALES.has(accion.codigo);
                        const anterior = barraOrden.menu[indice - 1];
                        const grupo =
                          indice === 0
                            ? especial
                              ? "Situaciones especiales"
                              : "Otras acciones"
                            : especial &&
                                !CODIGOS_ESPECIALES.has(anterior.accion.codigo)
                              ? "Situaciones especiales"
                              : undefined;
                        return {
                          clave,
                          etiqueta: nombreAccion(accion),
                          grupo,
                          onElegir: () => setAbierta(clave),
                        };
                      })}
                    />
                  </>
                ),
              }
            : tituloOrdenes;

  return (
    <Layout
      seccion={seccion}
      onNavegar={(destino) => {
        setError(null);
        navegar({ pantalla: destino });
      }}
      usuario={{ nombre: actor.nombre, rol: ROL[actor.rol] ?? actor.rol }}
      onCerrarSesion={cerrarSesion}
      barra={barra}
    >
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
      ) : ruta.pantalla === "ordenes" || ruta.pantalla === "nueva" ? (
        <>
          <PantallaOrdenes
            ordenes={ordenes}
            usuarios={usuarios}
            actor={actor}
            filtros={filtros}
            onFiltros={setFiltros}
            onNueva={() => navegar({ pantalla: "nueva" })}
            cargado={listadoCargado}
          />
          {ruta.pantalla === "nueva" && (
            <Modal
              titulo="Nueva orden"
              amplio
              onCerrar={() => navegar({ pantalla: "ordenes" })}
            >
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
              {error && <MensajeDeComando error={error} />}
            </Modal>
          )}
        </>
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
          <div className="rt-orden">
            <aside className="rt-orden__lateral" aria-label="Pendientes de la orden">
              <Pendientes
                orden={orden}
                actor={actor}
                usuarios={usuarios}
                onResolver={setAbierta}
                abrible={(clave) => registradas.has(clave)}
                nombreAccion={nombreAccion}
                errorGeneral={errorSinLugar(error, orden, actor)}
              />
            </aside>

            <div className="rt-orden__principal">
              <CabeceraOrden
                orden={orden}
                usuarios={usuarios}
                estaciones={estaciones}
              />

              {/* Solo formularios: cada uno se abre en su ventana. */}
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
                key={`${orden.id}-trabajos`}
                titulo="Trabajos"
                resumen={resumenTrabajos(orden)}
                abierta
              >
                <TrabajosOrden orden={orden} usuarios={usuarios} />
              </SeccionPlegable>

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
                key={`${orden.id}-${actorId}-fotos`}
                titulo="Fotos del equipo"
                resumen={resumenFotos(orden)}
              >
                <FotosOrden
                  orden={orden}
                  actor={actor}
                  usuarios={usuarios}
                  ocupado={ocupado}
                  onSubir={async (fotos) => {
                    // Una por una: si falla una, las anteriores ya quedaron
                    // y la pantalla las muestra.
                    let subidas = 0;
                    await ejecutarComando(async () => {
                      let actualizada = orden;
                      for (const foto of fotos) {
                        try {
                          actualizada = await api.subirFoto(
                            idOrden,
                            idActor,
                            foto.archivo,
                            foto.nombre,
                          );
                          subidas += 1;
                        } catch (fallo) {
                          if (actualizada !== orden) setOrden(actualizada);
                          throw fallo;
                        }
                      }
                      return actualizada;
                    });
                    return subidas;
                  }}
                />
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
                  onDescontar={(tipo, valor, motivo, clase) =>
                    void ejecutarComando(() =>
                      api.aplicarDescuento(
                        idOrden,
                        idActor,
                        tipo,
                        valor,
                        motivo,
                        clase,
                      ),
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
          <AnfitrionAcciones
                titulo={nombreAccion}
                abierta={accionAbierta}
            onCerrar={() => setAbierta(null)}
          />
        </ProveedorPresentacion>
      )}
    </Layout>
  );
}

/**
 * Cuántas acciones entran como botón en la barra según el ancho: el resto
 * va a «Más acciones». Solo cambia dónde se ven, no cuáles hay.
 */
function useBotonesVisibles(): number {
  const calcular = () =>
    window.innerWidth >= 1400 ? 3 : window.innerWidth >= 1150 ? 2 : 1;
  const [cantidad, setCantidad] = useState(calcular);
  useEffect(() => {
    const alCambiar = () => setCantidad(calcular());
    window.addEventListener("resize", alCambiar);
    return () => window.removeEventListener("resize", alCambiar);
  }, []);
  return cantidad;
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
      ? `${orden.cliente.nombre_apellido} · ${orden.cliente.telefono}`
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
