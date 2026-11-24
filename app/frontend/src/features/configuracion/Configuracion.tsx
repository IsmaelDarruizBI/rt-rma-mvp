/**
 * Configuración por funcionalidad (Configuración v2, CFG-05; DC23,
 * DC23AUD, BR-REP-040).
 *
 * Un índice agrupado (Taller, Inventario y compras, Comunicación,
 * Comprobantes, Sistema)
 * con una ruta por subsección (`#/configuracion/insumos`). Cada subsección
 * se ve con su permiso, no con un rol: Administración puede delegar los
 * catálogos operativos a Recepción o Coordinación RMA desde Permisos. Lo
 * sensible (usuarios, permisos, recargos y la auditoría completa) sigue
 * siendo de Administración. Cada catálogo muestra su propio historial.
 * La API valida todo de nuevo.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import type { CambioConfiguracion, EntidadConfiguracion } from "../../api/configuracion";
import { leerParametros } from "../../api/operativa";
import { Mensajes, mensajeDe } from "../../components/FormularioModal";
import { colores } from "../../components/ui";
import type { Usuario } from "../../types/api";
import { ChecklistAdmin } from "./Checklist";
import { DatosEmpresaAdmin, TerminosCondicionesAdmin } from "./Comprobantes";
import { InsumosAdmin } from "./Insumos";
import { MotivosOperativos, RecargosMedioPago } from "./Operativa";
import { Permisos } from "./Permisos";
import { PlantillasMensaje } from "./Plantillas";
import { ProveedoresAdmin } from "./Proveedores";
import {
  ENTIDAD_DE_SECCION,
  type SeccionConfiguracion,
  definicionDe,
  gruposDe,
  puedeVerSeccion,
  seccionAMostrar,
  seccionesPermitidas,
} from "./secciones";
import { ModelosEquipoAdmin } from "./ModelosEquipo";
import { MesasTrabajo, TiposReparacion } from "./TiposReparacion";
import { UsuariosRoles } from "./UsuariosRoles";

const CAMPOS: Record<string, string> = {
  codigo: "Código",
  nombre: "Nombre",
  precio: "Precio",
  puntaje: "Puntaje",
  garantia_dias: "Garantía sin check-in registrado (días)",
  activo: "Vigente",
  activa: "Vigente",
  tipos_habilitados: "Tipos habilitados",
  roles: "Roles",
  garantia_con_checkin: "Garantía con check-in (días)",
  garantia_sin_checkin: "Garantía sin check-in (días)",
  politica_garantia_rma: "Política en garantía RMA",
  unidad: "Unidad",
  control: "Control",
  texto: "Texto",
  finalidad: "Finalidad",
  requiere_descripcion: "Exige descripción",
  // DEC-AJ-09: datos de la empresa y versiones de los términos.
  razon_social: "Razón social",
  cuit: "CUIT",
  direccion: "Dirección",
  telefono: "Teléfono",
  email: "Email",
  horario: "Horario de atención",
  pie_comprobante: "Pie de los comprobantes",
  version: "Versión vigente",
  // DEC-AJ-12.
  precio_por_modelo: "Precio por modelo",
  marca: "Marca",
  modelo: "Modelo",
  variante: "Variante",
  numeros_modelo: "Números de modelo",
};

/** Los booleanos se guardan como true/false: en pantalla, Sí o No. */
function valor(texto: string | null): string {
  if (texto === null) return "—";
  if (texto === "true") return "Sí";
  if (texto === "false") return "No";
  return texto;
}

function ListaDeCambios({ cambios }: { cambios: CambioConfiguracion[] }) {
  if (cambios.length === 0) {
    return (
      <p style={{ margin: 0, fontSize: "0.85rem", color: colores.suave }}>
        Sin cambios registrados.
      </p>
    );
  }
  return (
    <ul style={{ margin: 0, paddingLeft: "1.1rem", fontSize: "0.85rem" }}>
      {cambios.map((c, i) => (
        <li key={i}>
          {new Date(c.fecha).toLocaleString("es-AR")} · {c.usuario_id} · {c.clave} ·{" "}
          {CAMPOS[c.campo] ?? c.campo}: {valor(c.valor_anterior)} → {valor(c.valor_nuevo)}
        </li>
      ))}
    </ul>
  );
}

/** El historial de una entidad: lo ve quien la administra. */
function Historial({ entidad }: { entidad: EntidadConfiguracion }) {
  const [abierto, setAbierto] = useState(false);
  const [cambios, setCambios] = useState<CambioConfiguracion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (!abierto) return;
    api
      .obtenerCambios(entidad)
      .then((lista) => setCambios([...lista].reverse()))
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, [abierto, entidad]);
  return (
    <details
      style={{ marginTop: "1rem" }}
      onToggle={(evento) => setAbierto((evento.target as HTMLDetailsElement).open)}
    >
      <summary style={{ cursor: "pointer", fontSize: "0.85rem" }}>Historial de cambios</summary>
      <div style={{ marginTop: "0.4rem" }}>
        {error && <p role="alert">{error}</p>}
        {cambios ? <ListaDeCambios cambios={cambios} /> : !error && <p>Cargando…</p>}
      </div>
    </details>
  );
}

function AuditoriaCompleta() {
  const [cambios, setCambios] = useState<CambioConfiguracion[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    api
      .obtenerCambios()
      .then((lista) => setCambios([...lista].reverse()))
      .catch((causa: unknown) => setError(mensajeDe(causa)));
  }, []);
  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Auditoría de la configuración</h3>
      <Mensajes error={error} aviso={null} />
      {cambios ? <ListaDeCambios cambios={cambios} /> : !error && <p>Cargando…</p>}
    </section>
  );
}

/** Usuarios y Permisos: se administran sobre PostgreSQL (DC23). */
function useEditableDelSistema(activo: boolean): boolean {
  const [editable, setEditable] = useState(true);
  useEffect(() => {
    if (!activo) return;
    leerParametros()
      .then((datos) => setEditable(datos.editable))
      .catch(() => setEditable(true));
  }, [activo]);
  return editable;
}

function Indice({
  actor,
  actual,
  onNavegar,
}: {
  actor: Usuario;
  actual: SeccionConfiguracion | null;
  onNavegar: (seccion: SeccionConfiguracion) => void;
}) {
  return (
    <nav aria-label="Secciones de Configuración" style={{ display: "grid", gap: "0.5rem" }}>
      {gruposDe(seccionesPermitidas(actor)).map(({ grupo, secciones }) => (
        <div key={grupo} style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap", alignItems: "center" }}>
          <span style={{ fontSize: "0.75rem", color: colores.suave, minWidth: 140 }}>{grupo}</span>
          {secciones.map((s) => (
            <a
              key={s.id}
              href={`#/configuracion/${s.id}`}
              aria-current={actual === s.id ? "page" : undefined}
              onClick={(evento) => {
                evento.preventDefault();
                onNavegar(s.id);
              }}
              style={{
                padding: "0.3rem 0.8rem",
                borderRadius: 999,
                border: `1px solid ${colores.borde}`,
                background: actual === s.id ? colores.acento : "transparent",
                color: actual === s.id ? "#fff" : colores.texto,
                textDecoration: "none",
                fontSize: "0.85rem",
              }}
            >
              {s.titulo}
            </a>
          ))}
        </div>
      ))}
    </nav>
  );
}

export function ConfiguracionPanel({
  actor,
  seccion,
  onNavegar,
  onCambio,
}: {
  actor: Usuario | null;
  seccion?: SeccionConfiguracion;
  onNavegar: (seccion: SeccionConfiguracion) => void;
  /** Cambiaron permisos, roles o tipos: la app vuelve a leerlos. */
  onCambio: () => void;
}) {
  const actual = seccionAMostrar(actor, seccion);
  const sistema = actual === "usuarios" || actual === "permisos";
  const editableSistema = useEditableDelSistema(sistema && actor !== null);
  const alCambiar = useCallback(() => onCambio(), [onCambio]);

  if (actor === null) return <p role="alert">Ingresá para ver la configuración.</p>;
  if (actual === null) {
    return <p role="alert">Tu usuario no tiene permisos de configuración.</p>;
  }
  const permitida = puedeVerSeccion(actor, actual);
  const entidad = ENTIDAD_DE_SECCION[actual] as EntidadConfiguracion | undefined;

  return (
    <div style={{ display: "grid", gap: "1.2rem", gridTemplateColumns: "minmax(0, 1fr)" }}>
      <Indice actor={actor} actual={actual} onNavegar={onNavegar} />
      {!permitida ? (
        <p role="alert">No tenés permiso para «{definicionDe(actual).titulo}».</p>
      ) : (
        <div style={{ minWidth: 0 }}>
          {actual === "tipos-reparacion" && <TiposReparacion actor={actor} onCambio={alCambiar} />}
          {actual === "modelos-equipo" && <ModelosEquipoAdmin actor={actor} />}
          {actual === "mesas" && <MesasTrabajo actor={actor} />}
          {actual === "motivos" && <MotivosOperativos actor={actor} />}
          {actual === "checklist" && <ChecklistAdmin actor={actor} />}
          {actual === "insumos" && <InsumosAdmin actor={actor} />}
          {actual === "proveedores" && <ProveedoresAdmin actor={actor} />}
          {actual === "plantillas" && <PlantillasMensaje actor={actor} />}
          {actual === "empresa" && <DatosEmpresaAdmin actor={actor} />}
          {actual === "terminos" && <TerminosCondicionesAdmin actor={actor} />}
          {actual === "usuarios" && (
            <UsuariosRoles actor={actor} editable={editableSistema} onCambio={alCambiar} />
          )}
          {actual === "permisos" && (
            <Permisos actor={actor} editable={editableSistema} onCambio={alCambiar} />
          )}
          {actual === "recargos" && <RecargosMedioPago actor={actor} />}
          {actual === "auditoria" && <AuditoriaCompleta />}
          {entidad && <Historial key={entidad} entidad={entidad} />}
        </div>
      )}
    </div>
  );
}
