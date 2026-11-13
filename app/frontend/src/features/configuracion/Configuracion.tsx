/**
 * Configuración de catálogos (DC23, DC23AUD, BR-REP-040), solo
 * Administración: Tipos de Reparación (alta, precio, puntaje, garantía,
 * vigencia) y Tipos habilitados por Mesa de trabajo. Cada cambio queda
 * auditado con el valor anterior y el nuevo; lo ya registrado en las
 * Órdenes no cambia. En el modo JSON los catálogos son de solo lectura.
 */

import { useCallback, useEffect, useState } from "react";

import * as api from "../../api/configuracion";
import type {
  CambioConfiguracion,
  CatalogoConfigurable,
  DatosTipo,
} from "../../api/configuracion";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type {
  PoliticaGarantiaRma,
  TipoReparacion,
  Usuario,
} from "../../types/api";
import { tieneRol } from "../../lib/roles";
import { MotivosOperativos, ParametrosOperativos } from "./Operativa";
import { Permisos } from "./Permisos";
import { PlantillasMensaje } from "./Plantillas";
import { UsuariosRoles } from "./UsuariosRoles";

const CAMPOS: Record<string, string> = {
  nombre: "Nombre",
  precio: "Precio",
  puntaje: "Puntaje",
  garantia_dias: "Garantía (días)",
  activo: "Vigente",
  tipos_habilitados: "Tipos habilitados",
  roles: "Roles",
  garantia_con_checkin: "Garantía con check-in (días)",
  garantia_sin_checkin: "Garantía sin check-in (días)",
  politica_garantia_rma: "Política en garantía RMA",
};

const POLITICAS_RMA: { valor: PoliticaGarantiaRma | ""; texto: string }[] = [
  { valor: "", texto: "Sin definir (como hasta ahora: el plazo del Tipo)" },
  { valor: "NUEVO_PLAZO", texto: "Nuevo plazo del Tipo" },
  { valor: "PLAZO_RESTANTE", texto: "Lo que le quedaba a la garantía original" },
  { valor: "SIN_GARANTIA", texto: "Sin nueva garantía" },
];

type Pestana =
  | "catalogos"
  | "motivos"
  | "parametros"
  | "plantillas"
  | "usuarios"
  | "permisos"
  | "auditoria";
const PESTANAS: { valor: Pestana; texto: string }[] = [
  { valor: "catalogos", texto: "Catálogos" },
  { valor: "motivos", texto: "Motivos" },
  { valor: "parametros", texto: "Parámetros" },
  { valor: "plantillas", texto: "Plantillas" },
  { valor: "usuarios", texto: "Usuarios y roles" },
  { valor: "permisos", texto: "Permisos" },
  { valor: "auditoria", texto: "Auditoría" },
];

/** Los booleanos se guardan como true/false: en pantalla, Sí o No. */
function valor(texto: string | null): string {
  if (texto === null) return "—";
  if (texto === "true") return "Sí";
  if (texto === "false") return "No";
  return texto;
}

function fecha(valor: string): string {
  return new Date(valor).toLocaleString("es-AR");
}

function Auditoria({ cambios }: { cambios: CambioConfiguracion[] }) {
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
          {fecha(c.fecha)} · {c.usuario_id} · {c.clave} ·{" "}
          {CAMPOS[c.campo] ?? c.campo}: {valor(c.valor_anterior)} →{" "}
          {valor(c.valor_nuevo)}
        </li>
      ))}
    </ul>
  );
}

function FormularioTipo({
  inicial,
  conCodigo,
  deshabilitado,
  onGuardar,
}: {
  inicial: DatosTipo;
  conCodigo: boolean;
  deshabilitado: boolean;
  onGuardar: (codigo: string, datos: DatosTipo) => void;
}) {
  const [codigo, setCodigo] = useState("");
  const [datos, setDatos] = useState<DatosTipo>(inicial);
  const listo =
    datos.nombre.trim() !== "" &&
    datos.precio.trim() !== "" &&
    Number(datos.precio) >= 0 &&
    (!conCodigo || codigo.trim() !== "");
  return (
    <div style={{ display: "grid", gap: "0.4rem", maxWidth: 420 }}>
      {conCodigo && (
        <Campo etiqueta="Código (por ejemplo TR-010)">
          <input
            value={codigo}
            onChange={(e) => setCodigo(e.target.value)}
            disabled={deshabilitado}
            style={estiloInput}
          />
        </Campo>
      )}
      <Campo etiqueta="Nombre">
        <input
          value={datos.nombre}
          onChange={(e) => setDatos({ ...datos, nombre: e.target.value })}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Precio">
        <input
          inputMode="decimal"
          value={datos.precio}
          onChange={(e) => setDatos({ ...datos, precio: e.target.value })}
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Puntaje">
        <input
          type="number"
          min={0}
          value={datos.puntaje}
          onChange={(e) =>
            setDatos({ ...datos, puntaje: Number(e.target.value) })
          }
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Garantía sin check-in exigible (días)">
        <input
          type="number"
          min={0}
          value={datos.garantia_dias}
          onChange={(e) =>
            setDatos({ ...datos, garantia_dias: Number(e.target.value) })
          }
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Garantía con check-in realizado (días)">
        <input
          type="number"
          min={0}
          value={datos.garantia_con_checkin}
          onChange={(e) =>
            setDatos({ ...datos, garantia_con_checkin: Number(e.target.value) })
          }
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Garantía con check-in no realizado (días)">
        <input
          type="number"
          min={0}
          value={datos.garantia_sin_checkin}
          onChange={(e) =>
            setDatos({ ...datos, garantia_sin_checkin: Number(e.target.value) })
          }
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
      <Campo etiqueta="Trabajos hechos dentro de una garantía RMA">
        <select
          value={datos.politica_garantia_rma ?? ""}
          onChange={(e) =>
            setDatos({
              ...datos,
              politica_garantia_rma:
                e.target.value === ""
                  ? null
                  : (e.target.value as PoliticaGarantiaRma),
            })
          }
          disabled={deshabilitado}
          style={estiloInput}
        >
          {POLITICAS_RMA.map((p) => (
            <option key={p.valor} value={p.valor}>
              {p.texto}
            </option>
          ))}
        </select>
      </Campo>
      {!conCodigo && (
        <label style={{ fontSize: "0.85rem" }}>
          <input
            type="checkbox"
            checked={datos.activo}
            onChange={(e) => setDatos({ ...datos, activo: e.target.checked })}
            disabled={deshabilitado}
          />{" "}
          Vigente (si no, no se ofrece para trabajos nuevos)
        </label>
      )}
      <Boton
        disabled={deshabilitado || !listo}
        onClick={() => onGuardar(codigo.trim(), datos)}
      >
        Guardar
      </Boton>
    </div>
  );
}

function datosDe(tipo: TipoReparacion): DatosTipo {
  return {
    nombre: tipo.nombre,
    precio: String(tipo.precio),
    puntaje: tipo.puntaje,
    garantia_dias: tipo.garantia_dias,
    activo: tipo.activo ?? true,
    garantia_con_checkin: tipo.garantia_con_checkin ?? 90,
    garantia_sin_checkin: tipo.garantia_sin_checkin ?? 30,
    politica_garantia_rma: tipo.politica_garantia_rma ?? null,
  };
}

export function ConfiguracionPanel({ actor }: { actor: Usuario | null }) {
  const [catalogo, setCatalogo] = useState<CatalogoConfigurable | null>(null);
  const [cambios, setCambios] = useState<CambioConfiguracion[]>([]);
  const [editando, setEditando] = useState<string | null>(null);
  const [mesas, setMesas] = useState<Record<string, string[]>>({});
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [pestana, setPestana] = useState<Pestana>("catalogos");

  const cargar = useCallback(() => {
    Promise.all([api.obtenerCatalogo(), api.obtenerCambios()])
      .then(([datos, auditoria]) => {
        setCatalogo(datos);
        setCambios(auditoria);
        setMesas(Object.fromEntries(datos.mesas.map((m) => [m.id, m.tipos])));
      })
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      );
  }, []);

  useEffect(cargar, [cargar]);

  const ejecutar = (comando: () => Promise<unknown>, mensaje: string) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    comando()
      .then(() => {
        setAviso(mensaje);
        setEditando(null);
        cargar();
      })
      .catch((causa: unknown) =>
        setError(causa instanceof Error ? causa.message : String(causa)),
      )
      .finally(() => setOcupado(false));
  };

  if (actor === null || !tieneRol(actor, "ADMINISTRADOR")) {
    return <p role="alert">Solo Administración gestiona la configuración.</p>;
  }
  if (!catalogo) {
    return error ? <p role="alert">{error}</p> : <p>Cargando…</p>;
  }
  const bloqueado = ocupado || !catalogo.editable;

  return (
    <div style={{ display: "grid", gap: "1.2rem" }}>
      {!catalogo.editable && (
        <p role="status" style={{ margin: 0 }}>
          Los catálogos se administran sobre la base de datos definitiva; en
          este entorno (modo JSON) son de solo lectura.
        </p>
      )}
      <nav role="tablist" style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        {PESTANAS.map((p) => (
          <button
            key={p.valor}
            type="button"
            role="tab"
            aria-selected={pestana === p.valor}
            onClick={() => setPestana(p.valor)}
            style={{
              padding: "0.3rem 0.8rem",
              borderRadius: 999,
              border: `1px solid ${colores.borde}`,
              background: pestana === p.valor ? colores.acento : "transparent",
              color: pestana === p.valor ? "#fff" : colores.texto,
              cursor: "pointer",
              fontFamily: "inherit",
            }}
          >
            {p.texto}
          </button>
        ))}
      </nav>
      {error && <p role="alert">{error}</p>}
      {aviso && <p role="status">{aviso}</p>}

      {pestana === "usuarios" && (
        <UsuariosRoles actor={actor} editable={catalogo.editable} onCambio={cargar} />
      )}
      {pestana === "permisos" && (
        <Permisos actor={actor} editable={catalogo.editable} onCambio={cargar} />
      )}
      {pestana === "motivos" && <MotivosOperativos actor={actor} />}
      {pestana === "parametros" && <ParametrosOperativos actor={actor} />}
      {pestana === "plantillas" && <PlantillasMensaje actor={actor} />}

      {pestana === "catalogos" && (
      <>
      <section>
        <h3 style={{ margin: "0 0 0.5rem" }}>Tipos de reparación</h3>
        <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
          Un cambio de precio, puntaje o garantía vale para los trabajos
          nuevos: los ya cargados conservan lo que se les aplicó.
        </p>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr>
              {["Código", "Nombre", "Precio", "Puntaje", "Garantía", "Vigente", ""].map(
                (titulo) => (
                  <th key={titulo} style={{ textAlign: "left", padding: "0.25rem 0.5rem" }}>
                    {titulo}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {catalogo.tipos.map((tipo) => (
              <tr key={tipo.id}>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.id}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.nombre}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.precio}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.puntaje}</td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {tipo.garantia_dias} · {tipo.garantia_con_checkin ?? 90}/
                  {tipo.garantia_sin_checkin ?? 30}
                </td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  {tipo.activo === false ? "No" : "Sí"}
                </td>
                <td style={{ padding: "0.25rem 0.5rem" }}>
                  <button
                    type="button"
                    disabled={bloqueado}
                    onClick={() =>
                      setEditando(editando === tipo.id ? null : tipo.id)
                    }
                  >
                    {editando === tipo.id ? "Cerrar" : "Editar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {editando && (
          <div style={{ marginTop: "0.6rem" }}>
            <h4 style={{ margin: "0 0 0.4rem" }}>Editar {editando}</h4>
            <FormularioTipo
              key={editando}
              inicial={datosDe(catalogo.tipos.find((t) => t.id === editando)!)}
              conCodigo={false}
              deshabilitado={bloqueado}
              onGuardar={(_codigo, datos) =>
                ejecutar(
                  () => api.editarTipo(actor.id, editando, datos),
                  `Se guardó ${editando}.`,
                )
              }
            />
            <h4 style={{ margin: "0.8rem 0 0.4rem" }}>Cambios de {editando}</h4>
            <Auditoria cambios={cambios.filter((c) => c.clave === editando)} />
          </div>
        )}
        <h4 style={{ margin: "0.8rem 0 0.4rem" }}>Nuevo tipo de reparación</h4>
        <FormularioTipo
          inicial={{
            nombre: "",
            precio: "",
            puntaje: 0,
            garantia_dias: 90,
            activo: true,
            garantia_con_checkin: 90,
            garantia_sin_checkin: 30,
            politica_garantia_rma: null,
          }}
          conCodigo
          deshabilitado={bloqueado}
          onGuardar={(codigo, datos) =>
            ejecutar(
              () => api.crearTipo(actor.id, codigo, datos),
              `Se creó ${codigo}.`,
            )
          }
        />
      </section>

      <section>
        <h3 style={{ margin: "0 0 0.5rem" }}>Mesas de trabajo</h3>
        {catalogo.mesas.map((mesa) => (
          <div key={mesa.id} style={{ marginBottom: "0.8rem" }}>
            <strong>
              {mesa.nombre} ({mesa.id})
            </strong>
            <div style={{ display: "flex", flexWrap: "wrap", gap: "0.6rem", margin: "0.3rem 0" }}>
              {catalogo.tipos.map((tipo) => (
                <label key={tipo.id} style={{ fontSize: "0.85rem" }}>
                  <input
                    type="checkbox"
                    disabled={bloqueado}
                    checked={(mesas[mesa.id] ?? []).includes(tipo.id)}
                    onChange={(e) =>
                      setMesas({
                        ...mesas,
                        [mesa.id]: e.target.checked
                          ? [...(mesas[mesa.id] ?? []), tipo.id]
                          : (mesas[mesa.id] ?? []).filter((t) => t !== tipo.id),
                      })
                    }
                  />{" "}
                  {tipo.nombre}
                </label>
              ))}
            </div>
            <Boton
              disabled={bloqueado}
              onClick={() =>
                ejecutar(
                  () => api.guardarTiposDeMesa(actor.id, mesa.id, mesas[mesa.id] ?? []),
                  `Se guardaron los tipos de ${mesa.nombre}.`,
                )
              }
            >
              Guardar tipos de la Mesa
            </Boton>
          </div>
        ))}
      </section>
      </>
      )}

      {pestana === "auditoria" && (
        <section>
          <h3 style={{ margin: "0 0 0.5rem" }}>Auditoría de la configuración</h3>
          <Auditoria cambios={[...cambios].reverse()} />
        </section>
      )}
    </div>
  );
}
