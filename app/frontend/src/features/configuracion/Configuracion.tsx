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
import type { TipoReparacion, Usuario } from "../../types/api";

const CAMPOS: Record<string, string> = {
  nombre: "Nombre",
  precio: "Precio",
  puntaje: "Puntaje",
  garantia_dias: "Garantía (días)",
  activo: "Vigente",
  tipos_habilitados: "Tipos habilitados",
};

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
      <Campo etiqueta="Garantía (días)">
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

  if (actor?.rol !== "ADMINISTRADOR") {
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
      {error && <p role="alert">{error}</p>}
      {aviso && <p role="status">{aviso}</p>}

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
                <td style={{ padding: "0.25rem 0.5rem" }}>{tipo.garantia_dias}</td>
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
          inicial={{ nombre: "", precio: "", puntaje: 0, garantia_dias: 90, activo: true }}
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

      <section>
        <h3 style={{ margin: "0 0 0.5rem" }}>Auditoría de la configuración</h3>
        <Auditoria cambios={[...cambios].reverse()} />
      </section>
    </div>
  );
}
