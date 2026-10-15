/**
 * La ruta actual (hash) como estado de React.
 *
 * Escucha `hashchange`, así que Atrás, Adelante, una URL pegada o una
 * recarga llevan a la pantalla correcta. `navegar` agrega una entrada al
 * historial (o la reemplaza, para normalizar la URL sin sumar pasos).
 */

import { useCallback, useEffect, useState } from "react";

import { type Ruta, esCanonico, hashDe, parsearRuta } from "./rutas";

export function useRuta(): [Ruta, (ruta: Ruta, reemplazar?: boolean) => void] {
  const [ruta, setRuta] = useState<Ruta>(() =>
    parsearRuta(window.location.hash),
  );

  useEffect(() => {
    // Una URL vacía, no canónica (`#/`, `#/ordenes/`) o desconocida se
    // normaliza sin agregar un paso al historial.
    const normalizar = () => {
      if (!esCanonico(window.location.hash)) {
        window.history.replaceState(
          null,
          "",
          hashDe(parsearRuta(window.location.hash)),
        );
      }
    };
    const alCambiar = () => {
      normalizar();
      setRuta(parsearRuta(window.location.hash));
    };
    window.addEventListener("hashchange", alCambiar);
    normalizar();
    return () => window.removeEventListener("hashchange", alCambiar);
  }, []);

  const navegar = useCallback((destino: Ruta, reemplazar = false) => {
    const hash = hashDe(destino);
    if (reemplazar) {
      window.history.replaceState(null, "", hash);
      setRuta(destino);
    } else if (window.location.hash !== hash) {
      window.location.hash = hash;
    } else {
      setRuta(destino);
    }
  }, []);

  return [ruta, navegar];
}
