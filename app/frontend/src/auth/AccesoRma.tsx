/**
 * Acceso con Supabase Auth (UAT y producción).
 *
 * 1. Usuario y contraseña contra Supabase Auth (sin registro público: las
 *    cuentas las crea Administración). El usuario se traduce a la identidad
 *    interna de su cuenta (`usuario.ts`); nunca se muestra.
 * 2. Con la sesión, `GET /api/me` dice quién es en RMA (rol y nombre los
 *    decide el backend, desde PostgreSQL).
 * 3. La aplicación de siempre (`PanelOrdenes`) con ese usuario. Cada pedido
 *    lleva el token vigente; si la API responde 401, la sesión se cierra y
 *    vuelve el acceso con el aviso.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { ApiError, usarToken } from "../api/client";
import { obtenerUsuarioActual } from "../api/sesion";
import { PantallaAcceso } from "../features/ordenes-reparacion/LoginDemo";
import { PanelOrdenes } from "../features/ordenes-reparacion/PanelOrdenes";
import { EVENTO_SESION_VENCIDA, GestorSesion } from "./sesion";
import { crearClienteAuth } from "./supabase";

type Estado =
  | { tipo: "verificando" }
  | { tipo: "fuera" }
  | { tipo: "dentro"; usuarioId: string };

const SESION_VENCIDA = "Tu sesión venció. Volvé a iniciar sesión.";

export function AccesoRma({
  url,
  clave,
  dominio,
}: {
  url: string;
  clave: string;
  dominio: string;
}) {
  const gestor = useMemo(
    () => new GestorSesion(crearClienteAuth(url, clave), { dominio }),
    [url, clave, dominio],
  );
  const [estado, setEstado] = useState<Estado>({ tipo: "verificando" });
  const [aviso, setAviso] = useState<string | null>(null);

  // Cada pedido a la API lleva el token vigente (renovado por el cliente).
  useEffect(() => {
    usarToken(() => gestor.token());
    return () => usarToken(null);
  }, [gestor]);

  /** Con la sesión abierta, quién es en RMA; si no puede operar, sale. */
  const entrar = useCallback(async (): Promise<string | null> => {
    try {
      const usuario = await obtenerUsuarioActual();
      setAviso(null);
      setEstado({ tipo: "dentro", usuarioId: usuario.id });
      return null;
    } catch (fallo) {
      await gestor.cerrar();
      setEstado({ tipo: "fuera" });
      if (fallo instanceof ApiError) {
        return fallo.status === 401 ? SESION_VENCIDA : fallo.message;
      }
      return "No se pudo iniciar sesión.";
    }
  }, [gestor]);

  // Una sesión guardada de antes entra directo.
  useEffect(() => {
    let vigente = true;
    void gestor.token().then(async (token) => {
      if (!vigente) return;
      if (!token) {
        setEstado({ tipo: "fuera" });
        return;
      }
      const fallo = await entrar();
      if (vigente && fallo) setAviso(fallo);
    });
    return () => {
      vigente = false;
    };
  }, [gestor, entrar]);

  // La API rechazó la sesión (vencida o revocada): de vuelta al acceso.
  useEffect(() => {
    const alVencer = () => {
      void gestor.cerrar();
      setEstado({ tipo: "fuera" });
      setAviso(SESION_VENCIDA);
    };
    window.addEventListener(EVENTO_SESION_VENCIDA, alVencer);
    return () => window.removeEventListener(EVENTO_SESION_VENCIDA, alVencer);
  }, [gestor]);

  const cerrarSesion = useCallback(() => {
    void gestor.cerrar().then(() => {
      setAviso(null);
      setEstado({ tipo: "fuera" });
    });
  }, [gestor]);

  if (estado.tipo === "verificando") {
    return (
      <p role="status" style={{ padding: "2rem", textAlign: "center" }}>
        Verificando la sesión…
      </p>
    );
  }
  if (estado.tipo === "fuera") {
    return (
      <PantallaAcceso
        campoUsuario={{ etiqueta: "Usuario", tipo: "text", autoComplete: "username" }}
        aviso={aviso}
        onIngresar={async (usuario, contrasena) => {
          setAviso(null);
          const resultado = await gestor.iniciar(usuario, contrasena);
          if (!resultado.ok) return resultado.mensaje;
          return entrar();
        }}
      />
    );
  }
  return (
    <PanelOrdenes
      key={estado.usuarioId}
      sesion={{ usuarioId: estado.usuarioId, cerrar: cerrarSesion }}
    />
  );
}
