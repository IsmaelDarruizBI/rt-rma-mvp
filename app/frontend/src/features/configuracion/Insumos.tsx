/**
 * Insumos (DEC-MI-13): Administración da de alta y edita nombre, unidad y
 * vigencia, con auditoría. El código no cambia y el stock no se edita
 * acá: solo cambia con movimientos del inventario (un insumo nuevo empieza
 * en cero). En la persistencia JSON (demo) es de solo lectura.
 */

import { useCallback, useEffect, useState } from "react";

import { get, post, put } from "../../api/client";
import { Boton, Campo, colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";

interface InsumoAdmin {
  id: string;
  codigo: string;
  nombre: string;
  unidad: string | null;
  stock_fisico: string;
  activo: boolean;
}

const mensaje = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

const VACIO = { clave: "", codigo: "", nombre: "", unidad: "" };

export function InsumosAdmin({ actor }: { actor: Usuario }) {
  const [datos, setDatos] = useState<{ editable: boolean; insumos: InsumoAdmin[] } | null>(null);
  const [nuevo, setNuevo] = useState(VACIO);
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const cargar = useCallback(() => {
    get<{ editable: boolean; insumos: InsumoAdmin[] }>("/api/admin/supplies")
      .then(setDatos)
      .catch((causa: unknown) => setError(mensaje(causa)));
  }, []);
  useEffect(cargar, [cargar]);

  const ejecutar = (accion: () => Promise<unknown>, exito: string) => {
    setOcupado(true);
    setError(null);
    setAviso(null);
    accion()
      .then(() => {
        setAviso(exito);
        cargar();
      })
      .catch((causa: unknown) => setError(mensaje(causa)))
      .finally(() => setOcupado(false));
  };

  if (!datos) return error ? <p role="alert">{error}</p> : null;
  const bloqueado = ocupado || !datos.editable;

  const editar = (insumo: InsumoAdmin, cambios: Partial<InsumoAdmin>) => {
    const editado = { ...insumo, ...cambios };
    ejecutar(
      () =>
        put(`/api/admin/supplies/${encodeURIComponent(insumo.id)}`, {
          usuario_id: actor.id,
          codigo: editado.codigo,
          nombre: editado.nombre,
          unidad: editado.unidad,
          activo: editado.activo,
        }),
      `Se guardó el insumo ${insumo.codigo}.`,
    );
  };

  return (
    <section>
      <h3 style={{ margin: "0 0 0.5rem" }}>Insumos</h3>
      <p style={{ margin: "0 0 0.5rem", fontSize: "0.8rem", color: colores.suave }}>
        El stock cambia solo con movimientos del inventario. Un insumo nuevo
        empieza sin stock.
      </p>
      {error && (
        <p role="alert" style={{ color: colores.error, fontSize: "0.85rem" }}>
          {error}
        </p>
      )}
      {aviso && (
        <p role="status" style={{ color: colores.ok, fontSize: "0.85rem" }}>
          {aviso}
        </p>
      )}
      <div style={{ overflowX: "auto" }}>
        <table style={{ borderCollapse: "collapse", fontSize: "0.85rem" }}>
          <thead>
            <tr>
              <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Código</th>
              <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Nombre</th>
              <th style={{ textAlign: "left", paddingRight: "0.8rem" }}>Unidad</th>
              <th style={{ paddingRight: "0.8rem" }}>Stock</th>
              <th>Vigente</th>
            </tr>
          </thead>
          <tbody>
            {datos.insumos.map((insumo) => (
              <tr key={insumo.id}>
                <td style={{ paddingRight: "0.8rem" }}>{insumo.codigo}</td>
                <td style={{ paddingRight: "0.8rem" }}>
                  <input
                    defaultValue={insumo.nombre}
                    aria-label={`Nombre de ${insumo.codigo}`}
                    disabled={bloqueado}
                    onBlur={(e) => {
                      const nombre = e.target.value.trim();
                      if (nombre && nombre !== insumo.nombre) editar(insumo, { nombre });
                    }}
                    style={{ ...estiloInput, minWidth: 180 }}
                  />
                </td>
                <td style={{ paddingRight: "0.8rem" }}>{insumo.unidad ?? "—"}</td>
                <td style={{ paddingRight: "0.8rem", textAlign: "right" }}>
                  {insumo.stock_fisico}
                </td>
                <td style={{ textAlign: "center" }}>
                  <input
                    type="checkbox"
                    aria-label={`${insumo.codigo}: vigente`}
                    checked={insumo.activo}
                    disabled={bloqueado}
                    onChange={(e) => editar(insumo, { activo: e.target.checked })}
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {datos.editable && (
        <div style={{ maxWidth: 420, marginTop: "0.8rem" }}>
          <h4 style={{ margin: "0 0 0.3rem" }}>Nuevo insumo</h4>
          {(
            [
              ["clave", "Identificador (por ejemplo INS-010)"],
              ["codigo", "Código (por ejemplo BAT-A54)"],
              ["nombre", "Nombre"],
              ["unidad", "Unidad (opcional)"],
            ] as const
          ).map(([campo, etiqueta]) => (
            <Campo key={campo} etiqueta={etiqueta}>
              <input
                value={nuevo[campo]}
                onChange={(e) => setNuevo({ ...nuevo, [campo]: e.target.value })}
                disabled={bloqueado}
                style={estiloInput}
              />
            </Campo>
          ))}
          <Boton
            disabled={
              bloqueado || !nuevo.clave.trim() || !nuevo.codigo.trim() || !nuevo.nombre.trim()
            }
            onClick={() => {
              ejecutar(
                () =>
                  post("/api/admin/supplies", {
                    usuario_id: actor.id,
                    clave: nuevo.clave.trim(),
                    codigo: nuevo.codigo.trim(),
                    nombre: nuevo.nombre.trim(),
                    unidad: nuevo.unidad.trim() || null,
                  }),
                `Se agregó el insumo ${nuevo.codigo.trim()}.`,
              );
              setNuevo(VACIO);
            }}
          >
            Agregar insumo
          </Boton>
        </div>
      )}
    </section>
  );
}
