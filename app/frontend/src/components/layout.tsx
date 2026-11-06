/**
 * Layout de la aplicación: sidebar con las cuatro secciones y una barra
 * superior con el título de la pantalla, sus acciones y el usuario.
 *
 * El sidebar se contrae a íconos en escritorio (la preferencia se recuerda)
 * y en el celular se abre sobre el contenido sin taparlo permanentemente.
 */

import { type ReactNode, useEffect, useRef, useState } from "react";

import {
  IconoContraer,
  IconoExpandir,
  IconoInicio,
  IconoInventario,
  IconoMas,
  IconoMenu,
  IconoOrdenes,
  IconoSalir,
  IconoTaller,
} from "./iconos";

export type Seccion = "inicio" | "ordenes" | "taller" | "inventario";

const SECCIONES: readonly { clave: Seccion; nombre: string; icono: () => ReactNode }[] = [
  { clave: "inicio", nombre: "Inicio", icono: IconoInicio },
  { clave: "ordenes", nombre: "Órdenes", icono: IconoOrdenes },
  { clave: "taller", nombre: "Taller", icono: IconoTaller },
  { clave: "inventario", nombre: "Inventario", icono: IconoInventario },
];

const CLAVE_CONTRAIDA = "rt-rma.sidebarContraida";

function leerContraida(): boolean {
  try {
    return window.localStorage.getItem(CLAVE_CONTRAIDA) === "1";
  } catch {
    return false;
  }
}

/** El contenido de la barra superior de la pantalla actual. */
export interface Barra {
  titulo: ReactNode;
  subtitulo?: ReactNode;
  acciones?: ReactNode;
}

export function Layout({
  seccion,
  onNavegar,
  usuario,
  onCerrarSesion,
  barra,
  children,
}: {
  seccion: Seccion;
  onNavegar: (seccion: Seccion) => void;
  usuario: { nombre: string; rol: string };
  onCerrarSesion: () => void;
  barra: Barra;
  children: ReactNode;
}) {
  const [contraida, setContraida] = useState(leerContraida);
  const [movilAbierta, setMovilAbierta] = useState(false);

  useEffect(() => {
    try {
      window.localStorage.setItem(CLAVE_CONTRAIDA, contraida ? "1" : "0");
    } catch {
      // Sin almacenamiento: la preferencia dura la sesión.
    }
  }, [contraida]);

  const clases = [
    "rt-app",
    contraida ? "rt-app--contraida" : "",
    movilAbierta ? "rt-app--movil-abierta" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <div className={clases}>
      <aside className="rt-sidebar" aria-label="Navegación principal">
        <div className="rt-sidebar__marca">
          <span className="rt-sidebar__logo">RT</span>
          <span className="rt-sidebar__texto">Rosario Tecno RMA</span>
        </div>
        <nav className="rt-sidebar__nav">
          {SECCIONES.map(({ clave, nombre, icono: Icono }) => (
            <button
              key={clave}
              type="button"
              className={`rt-sidebar__item${
                seccion === clave ? " rt-sidebar__item--activo" : ""
              }`}
              aria-current={seccion === clave ? "page" : undefined}
              title={contraida ? nombre : undefined}
              onClick={() => {
                setMovilAbierta(false);
                onNavegar(clave);
              }}
            >
              <Icono />
              <span className="rt-sidebar__texto">{nombre}</span>
            </button>
          ))}
        </nav>
        <div className="rt-sidebar__pie">
          <button
            type="button"
            className="rt-sidebar__item rt-boton-contraer"
            onClick={() => setContraida((valor) => !valor)}
            aria-label={contraida ? "Expandir el menú" : "Contraer el menú"}
            title={contraida ? "Expandir el menú" : undefined}
          >
            {contraida ? <IconoExpandir /> : <IconoContraer />}
            <span className="rt-sidebar__texto">Contraer menú</span>
          </button>
        </div>
      </aside>
      <div className="rt-velo" onClick={() => setMovilAbierta(false)} />

      <div className="rt-principal">
        <header className="rt-barra">
          <button
            type="button"
            className="rt-btn rt-btn--fantasma rt-btn--icono rt-boton-menu-movil"
            aria-label="Abrir el menú"
            onClick={() => setMovilAbierta(true)}
          >
            <IconoMenu />
          </button>
          <div className="rt-barra__titulo">
            <h1>{barra.titulo}</h1>
            {barra.subtitulo && <p>{barra.subtitulo}</p>}
          </div>
          {barra.acciones && (
            <div className="rt-barra__acciones">{barra.acciones}</div>
          )}
          <div className="rt-barra__usuario">
            <div className="rt-solo-escritorio" style={{ textAlign: "right" }}>
              <div style={{ fontWeight: 600 }}>{usuario.nombre}</div>
              <div style={{ color: "var(--rt-suave)" }}>{usuario.rol}</div>
            </div>
            <button
              type="button"
              className="rt-btn rt-btn--fantasma rt-btn--icono"
              aria-label="Cerrar sesión"
              title="Cerrar sesión"
              onClick={onCerrarSesion}
            >
              <IconoSalir />
            </button>
          </div>
        </header>
        <main className="rt-contenido">{children}</main>
      </div>
    </div>
  );
}

/** Un ítem del menú «Más acciones». */
export interface ItemMenu {
  clave: string;
  etiqueta: string;
  onElegir: () => void;
  /** Encabezado de grupo antes de este ítem. */
  grupo?: string;
}

/** Botón «Más» con un menú desplegable (teclado: Escape cierra). */
export function MenuAcciones({
  items,
  etiqueta = "Más acciones",
}: {
  items: ItemMenu[];
  etiqueta?: string;
}) {
  const [abierto, setAbierto] = useState(false);
  const raiz = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!abierto) return;
    const fuera = (evento: MouseEvent) => {
      if (!raiz.current?.contains(evento.target as Node)) setAbierto(false);
    };
    const tecla = (evento: KeyboardEvent) => {
      if (evento.key === "Escape") setAbierto(false);
    };
    document.addEventListener("mousedown", fuera);
    document.addEventListener("keydown", tecla);
    return () => {
      document.removeEventListener("mousedown", fuera);
      document.removeEventListener("keydown", tecla);
    };
  }, [abierto]);

  if (items.length === 0) return null;
  return (
    <div className="rt-menu" ref={raiz}>
      <button
        type="button"
        className="rt-btn"
        aria-haspopup="menu"
        aria-expanded={abierto}
        onClick={() => setAbierto((valor) => !valor)}
      >
        <IconoMas />
        <span>{etiqueta}</span>
      </button>
      {abierto && (
        <div className="rt-menu__lista" role="menu">
          {items.map((item, indice) => (
            <div key={item.clave}>
              {item.grupo && (
                <>
                  {indice > 0 && <hr className="rt-menu__separador" />}
                  <div className="rt-menu__grupo">{item.grupo}</div>
                </>
              )}
              <button
                type="button"
                role="menuitem"
                className="rt-menu__item"
                onClick={() => {
                  setAbierto(false);
                  item.onElegir();
                }}
              >
                {item.etiqueta}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
