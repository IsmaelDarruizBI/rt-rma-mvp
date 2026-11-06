import { useEffect, useState } from "react";

import { fetchHealth } from "./api/health";
import { PanelOrdenes } from "./features/ordenes-reparacion/PanelOrdenes";

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

  return <PanelOrdenes />;
}
