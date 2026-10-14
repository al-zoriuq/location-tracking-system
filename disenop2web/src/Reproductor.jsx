import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { CircleMarker, useMap } from "react-leaflet";
import { posicionEnInstante } from "./utils/viajes.js";

// Speeds: seconds of route time per real second.
const VELOCIDADES = [60, 300, 1200];

const formatoHora = (ms) =>
  new Date(ms).toLocaleTimeString("es-CO", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    timeZone: "America/Bogota",
  });

export default function Reproductor({ puntos, onCerrar }) {
  const map = useMap();
  const inicio = puntos.length ? puntos[0].fecha.getTime() : 0;
  const fin = puntos.length ? puntos[puntos.length - 1].fecha.getTime() : 0;
  const [t, setT] = useState(inicio);
  const [reproduciendo, setReproduciendo] = useState(false);
  const [velocidad, setVelocidad] = useState(VELOCIDADES[1]);
  const velRef = useRef(velocidad);
  velRef.current = velocidad;

  // Restart when the route changes.
  useEffect(() => {
    setT(inicio);
    setReproduciendo(false);
  }, [inicio]);

  // Animation loop: only runs while playing.
  useEffect(() => {
    if (!reproduciendo) return undefined;
    let id;
    let previo = performance.now();
    const paso = (ahora) => {
      const dt = ahora - previo;
      previo = ahora;
      let terminado = false;
      setT((actual) => {
        const siguiente = actual + dt * velRef.current;
        if (siguiente >= fin) {
          terminado = true;
          return fin;
        }
        return siguiente;
      });
      if (terminado) setReproduciendo(false);
      else id = requestAnimationFrame(paso);
    };
    id = requestAnimationFrame(paso);
    return () => cancelAnimationFrame(id);
  }, [reproduciendo, fin]);

  const posicion = posicionEnInstante(puntos, t);
  const destino = map.getContainer().parentElement;

  const alternar = () => {
    if (!reproduciendo && t >= fin) setT(inicio);
    setReproduciendo(!reproduciendo);
  };

  const barra = (
    <div className="reproductor" role="group" aria-label="Reproductor de recorrido">
      <button type="button" className="repro-btn" onClick={alternar}
        aria-label={reproduciendo ? "Pausar" : "Reproducir"}>
        {reproduciendo ? (
          <svg width="14" height="14" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
            <rect x="2" y="1.5" width="2.8" height="9" rx="0.8" />
            <rect x="7.2" y="1.5" width="2.8" height="9" rx="0.8" />
          </svg>
        ) : (
          <svg width="14" height="14" viewBox="0 0 12 12" fill="currentColor" aria-hidden="true">
            <polygon points="3,1.5 10.5,6 3,10.5" />
          </svg>
        )}
      </button>
      <input type="range" className="repro-barra" min={inicio} max={fin} step={1000}
        value={Math.min(Math.max(t, inicio), fin)}
        onChange={(e) => setT(Number(e.target.value))}
        aria-label="Posici\u00f3n en el recorrido" />
      <span className="repro-hora">{formatoHora(t)}</span>
      <button type="button" className="repro-vel"
        onClick={() => setVelocidad(VELOCIDADES[(VELOCIDADES.indexOf(velocidad) + 1) % VELOCIDADES.length])}
        aria-label="Cambiar velocidad">
        &times;{velocidad}
      </button>
      <button type="button" className="repro-btn" onClick={onCerrar} aria-label="Cerrar reproductor">
        &times;
      </button>
    </div>
  );

  return (
    <>
      {posicion && (
        <CircleMarker center={posicion} radius={8}
          pathOptions={{ color: "#fff", weight: 2, fillColor: "#b37feb", fillOpacity: 1 }} />
      )}
      {destino && createPortal(barra, destino)}
    </>
  );
}
