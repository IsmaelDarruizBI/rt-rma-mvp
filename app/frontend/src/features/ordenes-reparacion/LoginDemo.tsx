/**
 * Pantalla de acceso (UAT).
 *
 * `PantallaAcceso` es la tarjeta de dos columnas (marca a la izquierda,
 * formulario a la derecha) que usan los dos modos: `LoginDemo` (desarrollo
 * local: credenciales dummy validadas en el frontend) y el acceso con
 * Supabase Auth (email y contraseña).
 */

import { useState, type FormEvent } from "react";

import { colores, estiloInput } from "../../components/ui";
import type { Usuario } from "../../types/api";
import { validarCredenciales } from "./usuarioDemo";

const ESTILOS_LOGIN = `
.rt-login {
  min-height: 100vh;
  box-sizing: border-box;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 1.5rem 1rem;
}
.rt-login-tarjeta {
  width: 100%;
  max-width: 880px;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  background: #fff;
  border: 1px solid ${colores.borde};
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 12px 32px rgba(16, 24, 40, 0.08);
}
.rt-login-marca {
  background: linear-gradient(160deg, #0f2a4a 0%, #1f4f8a 100%);
  color: #fff;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  padding: 2.5rem 2rem;
  min-height: 420px;
}
.rt-login-logo {
  width: 168px;
  height: 168px;
  border: 2px dashed rgba(255, 255, 255, 0.45);
  border-radius: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  text-align: center;
  font-size: 0.8rem;
  color: rgba(255, 255, 255, 0.75);
}
.rt-login-formulario {
  padding: 2.5rem 2.25rem;
  display: flex;
  flex-direction: column;
  justify-content: center;
}
@media (max-width: 720px) {
  .rt-login-tarjeta { grid-template-columns: minmax(0, 1fr); }
  .rt-login-marca { min-height: 0; padding: 1.75rem 1.5rem; }
  .rt-login-logo { width: 112px; height: 112px; }
  .rt-login-formulario { padding: 1.75rem 1.5rem; }
}
`;

export function LoginDemo({
  usuarios,
  onIngresar,
}: {
  /** Catálogo de usuarios de demostración (del backend). */
  usuarios: Usuario[];
  onIngresar: (usuarioId: string) => void;
}) {
  return (
    <PantallaAcceso
      campoUsuario={{ etiqueta: "Usuario", tipo: "text", autoComplete: "username" }}
      cargando={usuarios.length === 0}
      nota="Acceso de prueba (desarrollo local). No es un inicio de sesión real."
      onIngresar={(usuario, contrasena) => {
        const resultado = validarCredenciales(usuario, contrasena, usuarios);
        if (!resultado.ok) return resultado.mensaje;
        onIngresar(resultado.usuarioId);
        return null;
      }}
    />
  );
}

/** La tarjeta de acceso; `onIngresar` devuelve el error a mostrar o `null`. */
export function PantallaAcceso({
  campoUsuario,
  cargando = false,
  nota,
  aviso,
  onIngresar,
}: {
  campoUsuario: { etiqueta: string; tipo: "text" | "email"; autoComplete: string };
  cargando?: boolean;
  nota?: string;
  /** Un aviso previo (por ejemplo, la sesión venció). */
  aviso?: string | null;
  onIngresar: (
    usuario: string,
    contrasena: string,
  ) => string | null | Promise<string | null>;
}) {
  const [usuario, setUsuario] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  const ingresar = async (evento: FormEvent) => {
    evento.preventDefault();
    if (enviando) return;
    setEnviando(true);
    try {
      const fallo = await onIngresar(usuario, contrasena);
      setError(fallo);
      if (fallo) setContrasena("");
    } finally {
      setEnviando(false);
    }
  };
  const mensaje = error ?? aviso ?? null;

  return (
    <div className="rt-login">
      <style>{ESTILOS_LOGIN}</style>
      <section className="rt-login-tarjeta" aria-label="Acceso al sistema">
        <div className="rt-login-marca">
          {/* Reservado para el logo de Rosario Tecno (se entrega luego). */}
          <div className="rt-login-logo" aria-label="Logo de Rosario Tecno">
            Logo
            <br />
            Rosario Tecno
          </div>
        </div>

        <form
          className="rt-login-formulario"
          onSubmit={(evento) => void ingresar(evento)}
          noValidate
        >
          <h1 style={{ margin: 0, fontSize: "1.6rem", color: colores.texto }}>
            Sistema de Gestión
          </h1>
          <p style={{ margin: "0.25rem 0 0", fontSize: "1.05rem" }}>
            Servicio Técnico
          </p>
          <p
            style={{
              margin: "0.15rem 0 1.75rem",
              color: colores.suave,
              fontWeight: 600,
              letterSpacing: "0.02em",
            }}
          >
            Rosario Tecno
          </p>

          <label style={{ display: "block", marginBottom: "0.9rem" }}>
            <span style={estiloEtiqueta}>{campoUsuario.etiqueta}</span>
            <input
              name="usuario"
              type={campoUsuario.tipo}
              autoComplete={campoUsuario.autoComplete}
              autoFocus
              value={usuario}
              onChange={(evento) => setUsuario(evento.target.value)}
              style={estiloCampo}
            />
          </label>
          <label style={{ display: "block", marginBottom: "1.1rem" }}>
            <span style={estiloEtiqueta}>Contraseña</span>
            <input
              name="contrasena"
              type="password"
              autoComplete="current-password"
              value={contrasena}
              onChange={(evento) => setContrasena(evento.target.value)}
              style={estiloCampo}
            />
          </label>

          {mensaje && (
            <p
              role="alert"
              style={{
                margin: "0 0 1rem",
                padding: "0.55rem 0.75rem",
                borderRadius: 8,
                border: `1px solid ${colores.error}`,
                background: "#fff5f5",
                color: colores.error,
                fontSize: "0.85rem",
              }}
            >
              {mensaje}
            </p>
          )}

          <button
            type="submit"
            disabled={cargando || enviando}
            style={{
              padding: "0.7rem 1rem",
              borderRadius: 8,
              border: "none",
              background: colores.acento,
              color: "#fff",
              fontSize: "0.95rem",
              fontWeight: 600,
              fontFamily: "inherit",
              cursor: cargando || enviando ? "not-allowed" : "pointer",
              opacity: cargando || enviando ? 0.6 : 1,
            }}
          >
            {cargando ? "Cargando…" : enviando ? "Ingresando…" : "Iniciar sesión"}
          </button>
          {nota && (
            <p
              style={{
                margin: "1rem 0 0",
                fontSize: "0.75rem",
                color: colores.suave,
              }}
            >
              {nota}
            </p>
          )}
        </form>
      </section>
    </div>
  );
}

const estiloEtiqueta = {
  display: "block",
  fontSize: "0.8rem",
  color: colores.suave,
  marginBottom: "0.3rem",
} as const;

const estiloCampo = {
  ...estiloInput,
  padding: "0.6rem 0.75rem",
  fontSize: "0.95rem",
} as const;
