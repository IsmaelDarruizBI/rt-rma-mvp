/**
 * Pantalla de acceso (UAT).
 *
 * Solo look & feel y navegación por rol: valida credenciales dummy en el
 * frontend (`validarCredenciales`) y entrega el ID del usuario elegido. La
 * estructura visual -tarjeta de dos columnas, marca a la izquierda y
 * formulario a la derecha- es la que se reutilizará con la autenticación
 * definitiva; cambiará solo `onIngresar`.
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
  const [usuario, setUsuario] = useState("");
  const [contrasena, setContrasena] = useState("");
  const [error, setError] = useState<string | null>(null);

  const ingresar = (evento: FormEvent) => {
    evento.preventDefault();
    const resultado = validarCredenciales(usuario, contrasena, usuarios);
    if (!resultado.ok) {
      setError(resultado.mensaje);
      return;
    }
    setError(null);
    onIngresar(resultado.usuarioId);
  };

  const cargando = usuarios.length === 0;

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

        <form className="rt-login-formulario" onSubmit={ingresar} noValidate>
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
            <span style={estiloEtiqueta}>Usuario</span>
            <input
              name="usuario"
              autoComplete="username"
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

          {error && (
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
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={cargando}
            style={{
              padding: "0.7rem 1rem",
              borderRadius: 8,
              border: "none",
              background: colores.acento,
              color: "#fff",
              fontSize: "0.95rem",
              fontWeight: 600,
              fontFamily: "inherit",
              cursor: cargando ? "not-allowed" : "pointer",
              opacity: cargando ? 0.6 : 1,
            }}
          >
            {cargando ? "Cargando…" : "Iniciar sesión"}
          </button>
          <p
            style={{
              margin: "1rem 0 0",
              fontSize: "0.75rem",
              color: colores.suave,
            }}
          >
            Acceso de prueba (UAT). No es un inicio de sesión real.
          </p>
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
