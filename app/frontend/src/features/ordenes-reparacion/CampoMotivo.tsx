/**
 * Campo de motivo con el catálogo de su tipo (DEC-MI-15). Si el catálogo no
 * se puede leer, queda el texto libre de siempre.
 */

import { useEffect, useState } from "react";

import {
  listarMotivos,
  type MotivoOperativo,
  type TipoMotivo,
} from "../../api/operativa";
import { Campo, estiloInput } from "../../components/ui";
import { etiquetaDelTexto, type MotivoElegido, motivosVigentes } from "./motivos";

const cache = new Map<TipoMotivo, Promise<MotivoOperativo[]>>();

export function useMotivos(tipo: TipoMotivo): MotivoOperativo[] {
  const [motivos, setMotivos] = useState<MotivoOperativo[]>([]);
  useEffect(() => {
    let vigente = true;
    let pedido = cache.get(tipo);
    if (!pedido) {
      pedido = listarMotivos(tipo).catch(() => {
        cache.delete(tipo);
        return [];
      });
      cache.set(tipo, pedido);
    }
    void pedido.then((lista) => {
      if (vigente) setMotivos(lista);
    });
    return () => {
      vigente = false;
    };
  }, [tipo]);
  return motivos;
}

export function CampoMotivo({
  motivos,
  valor,
  onCambio,
  etiqueta,
  deshabilitado,
}: {
  motivos: MotivoOperativo[];
  valor: MotivoElegido;
  onCambio: (valor: MotivoElegido) => void;
  /** Etiqueta del texto libre (sin motivo de catálogo). */
  etiqueta: string;
  deshabilitado: boolean;
}) {
  const vigentes = motivosVigentes(motivos);
  return (
    <>
      {vigentes.length > 0 && (
        <Campo etiqueta="Motivo">
          <select
            value={valor.codigo ?? ""}
            onChange={(evento) =>
              onCambio({
                ...valor,
                codigo: evento.target.value || null,
              })
            }
            disabled={deshabilitado}
            style={estiloInput}
          >
            <option value="">Escribir el motivo…</option>
            {vigentes.map((motivo) => (
              <option key={motivo.codigo} value={motivo.codigo}>
                {motivo.nombre}
              </option>
            ))}
          </select>
        </Campo>
      )}
      <Campo etiqueta={etiquetaDelTexto(motivos, valor, etiqueta)}>
        <input
          value={valor.texto}
          onChange={(evento) =>
            onCambio({ ...valor, texto: evento.target.value })
          }
          disabled={deshabilitado}
          style={estiloInput}
        />
      </Campo>
    </>
  );
}
