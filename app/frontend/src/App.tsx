import { useEffect, useState } from "react";

import { fetchHealth } from "./api/health";
import { AccesoRma } from "./auth/AccesoRma";
import { configuracionAuth } from "./auth/config";
import { PanelOrdenes } from "./features/ordenes-reparacion/PanelOrdenes";

// Demo solo con `npm run dev`; un build de producción exige Supabase Auth.
const AUTENTICACION = configuracionAuth({
  VITE_AUTH_MODO: import.meta.env.VITE_AUTH_MODO,
  VITE_SUPABASE_URL: import.meta.env.VITE_SUPABASE_URL,
  VITE_SUPABASE_PUBLISHABLE_KEY: import.meta.env.VITE_SUPABASE_PUBLISHABLE_KEY,
  DEV: import.meta.env.DEV,
});

type BackendStatus = "checking" | "connected" | "disconnected";

export default function App() {
  const [backendStatus, setBackendStatus] = useState<BackendStatus>("checking");

  useEffect(() => {
    let active = true;

    fetchHealth().then((isHealthy) => {
      if (active) {
        setBackendStatus(isHealthy ? "connected" : "disconnected");
      }
    });

    return () => {
      active = false;
    };
  }, []);

  if (AUTENTICACION.modo === "invalida") {
    return (
      <main
        style={{
          fontFamily: "system-ui, sans-serif",
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "0.5rem",
          padding: "0 1rem",
          textAlign: "center",
        }}
      >
        <h1 style={{ margin: 0 }}>Rosario Tecno</h1>
        <p role="alert" style={{ marginTop: "1.5rem", color: "#b42318" }}>
          Configuración de acceso incompleta. {AUTENTICACION.motivo}
        </p>
      </main>
    );
  }

  if (backendStatus === "disconnected") {
    return (
      <main
        style={{
          fontFamily: "system-ui, sans-serif",
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "0.5rem",
        }}
      >
        <h1 style={{ margin: 0 }}>Rosario Tecno</h1>
        <h2 style={{ margin: 0, fontWeight: 400 }}>RMA MVP</h2>
        <p style={{ marginTop: "1.5rem", color: "#b42318" }}>
          Backend: sin conexion. Levantá el backend en el puerto 8000.
        </p>
      </main>
    );
  }

  if (AUTENTICACION.modo === "supabase") {
    return <AccesoRma url={AUTENTICACION.url} clave={AUTENTICACION.clave} />;
  }
  return <PanelOrdenes />;
}
