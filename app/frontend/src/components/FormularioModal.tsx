/**
 * Altas y ediciones cortas en una ventana (Configuración v2, CFG-04).
 *
 * El modal se cierra solo si el comando salió bien; si falla, el error se
 * muestra adentro y lo escrito se conserva. Enter confirma (es un
 * formulario), Escape o Cancelar cierran sin guardar. Mientras guarda, los
 * campos quedan bloqueados. `useComando` unifica error, aviso y ocupado de
 * los comandos que no van en una ventana (interruptores de una fila).
 */

import {
  type FormEvent,
  type ReactNode,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";

import { Modal } from "./Modal";
import { Boton, colores } from "./ui";

export const mensajeDe = (causa: unknown) =>
  causa instanceof Error ? causa.message : String(causa);

export function FormularioModal({
  titulo,
  textoConfirmar,
  listo,
  onConfirmar,
  onCerrar,
  amplio = false,
  children,
}: {
  titulo: string;
  textoConfirmar: string;
  /** Si los datos alcanzan para confirmar. */
  listo: boolean;
  /** El comando; si falla, el modal muestra el error y queda abierto. */
  onConfirmar: () => Promise<unknown>;
  onCerrar: () => void;
  amplio?: boolean;
  children: ReactNode;
}) {
  const [error, setError] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const campos = useRef<HTMLFieldSetElement>(null);

  // QA D, M3: al guardar se bloquean los campos y se pierde el foco; si
  // falla, vuelve al primer campo para corregir sin salir del modal.
  useEffect(() => {
    if (error && !ocupado) {
      campos.current
        ?.querySelector<HTMLElement>("input:not([readonly]), select, textarea")
        ?.focus();
    }
  }, [error, ocupado]);

  const confirmar = async (evento: FormEvent) => {
    evento.preventDefault();
    if (!listo || ocupado) return;
    setOcupado(true);
    setError(null);
    try {
      await onConfirmar();
      onCerrar();
    } catch (causa) {
      setError(mensajeDe(causa));
      setOcupado(false);
    }
  };

  return (
    <Modal titulo={titulo} amplio={amplio} onCerrar={() => !ocupado && onCerrar()}>
      <form onSubmit={(evento) => void confirmar(evento)}>
        <fieldset ref={campos} disabled={ocupado} style={{ border: 0, margin: 0, padding: 0, minWidth: 0 }}>
          {children}
        </fieldset>
        {error && (
          <p role="alert" style={{ color: colores.error, fontSize: "0.85rem", margin: "0 0 0.6rem" }}>
            {error}
          </p>
        )}
        <div style={{ display: "flex", gap: "0.5rem", justifyContent: "flex-end", flexWrap: "wrap" }}>
          <Boton variante="secundario" disabled={ocupado} onClick={onCerrar}>
            Cancelar
          </Boton>
          <Boton type="submit" disabled={!listo || ocupado}>
            {ocupado ? "Guardando…" : textoConfirmar}
          </Boton>
        </div>
      </form>
    </Modal>
  );
}

/** Error, aviso y ocupado de los comandos de una pantalla. */
export function useComando() {
  const [error, setError] = useState<string | null>(null);
  const [aviso, setAviso] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);

  const ejecutar = useCallback(
    async <T,>(
      accion: () => Promise<T>,
      exito: string | ((resultado: T) => string),
    ): Promise<T | undefined> => {
      setOcupado(true);
      setError(null);
      setAviso(null);
      try {
        const resultado = await accion();
        setAviso(typeof exito === "function" ? exito(resultado) : exito);
        return resultado;
      } catch (causa) {
        setError(mensajeDe(causa));
        return undefined;
      } finally {
        setOcupado(false);
      }
    },
    [],
  );

  return { error, setError, aviso, setAviso, ocupado, ejecutar };
}

export function Mensajes({ error, aviso }: { error: string | null; aviso: string | null }) {
  return (
    <>
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
    </>
  );
}

/** El encabezado de un listado con su botón «+ Nuevo …» (si corresponde). */
export function EncabezadoListado({
  titulo,
  nuevo,
  onNuevo,
  children,
}: {
  titulo: string;
  /** Texto del botón; sin él no se ofrece el alta. */
  nuevo?: string;
  onNuevo?: () => void;
  children?: ReactNode;
}) {
  return (
    <div
      style={{
        display: "flex",
        alignItems: "center",
        justifyContent: "space-between",
        gap: "0.6rem",
        flexWrap: "wrap",
        margin: "0 0 0.5rem",
      }}
    >
      <h3 style={{ margin: 0 }}>{titulo}</h3>
      <div style={{ display: "flex", gap: "0.4rem", flexWrap: "wrap" }}>
        {children}
        {nuevo && onNuevo && <Boton onClick={onNuevo}>+ {nuevo}</Boton>}
      </div>
    </div>
  );
}
