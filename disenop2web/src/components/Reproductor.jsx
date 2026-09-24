import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import { posicionEnInstante } from "../utils/viajes";
import { formatearFecha, formatearHora } from "../utils/tiempo";

const FACTORES = [10, 60, 300]; // playback speeds

// Idea B: plays the selected route back with a marker moving along it.
//
// Performance: the simulated clock changes ~60 times per second, so the
// marker is NOT a React component inside the map. This panel creates a plain
// Leaflet circleMarker on the map instance and moves it with setLatLng();
// each frame only re-renders this small panel, never the whole App (map,
// route, sidebar). The parent mounts it with key = route id, so changing
// route resets the playback and removes the marker (effect cleanup).
function Reproductor({ mapa, puntos, onReproduciendo }) {
  const inicio = puntos[0].fecha.getTime();
  const fin = puntos[puntos.length - 1].fecha.getTime();

  const [tiempo, setTiempo] = useState(inicio);
  const [reproduciendo, setReproduciendo] = useState(false);
  const [factor, setFactor] = useState(60);
  // The animation loop reads/writes the clock here, not through state, so
  // it always sees the latest value without restarting on every frame
  const tiempoRef = useRef(inicio);
  const marcadorRef = useRef(null);

  // Marker lifecycle: created once on the map, removed on unmount
  useEffect(() => {
    if (!mapa) return;
    const marcador = L.circleMarker([puntos[0].lat, puntos[0].lon], {
      radius: 8,
      weight: 3,
      className: "marcador-reproduccion",
      interactive: false,
    }).addTo(mapa);
    marcadorRef.current = marcador;
    return () => {
      marcador.remove();
      marcadorRef.current = null;
    };
    // Only when the map instance changes: new points of a live trip must
    // not recreate the marker
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [mapa]);

  // Move the marker whenever the simulated clock changes
  useEffect(() => {
    const posicion = posicionEnInstante(puntos, tiempo);
    if (posicion && marcadorRef.current) marcadorRef.current.setLatLng(posicion);
  }, [puntos, tiempo]);

  // Animation loop: simulated time advances (real elapsed ms) x factor
  useEffect(() => {
    if (!reproduciendo) return;
    let anterior = performance.now();
    let id;
    const cuadro = (ahora) => {
      const t = Math.min(fin, tiempoRef.current + (ahora - anterior) * factor);
      anterior = ahora;
      tiempoRef.current = t;
      setTiempo(t);
      if (t >= fin) {
        setReproduciendo(false); // reached the end of the route
        return;
      }
      id = requestAnimationFrame(cuadro);
    };
    id = requestAnimationFrame(cuadro);
    return () => cancelAnimationFrame(id);
  }, [reproduciendo, factor, fin]);

  // Tell the parent (it disables auto-centering while playing)
  useEffect(() => {
    onReproduciendo(reproduciendo);
    return () => onReproduciendo(false);
  }, [reproduciendo, onReproduciendo]);

  function alternar() {
    if (!reproduciendo && tiempoRef.current >= fin) {
      tiempoRef.current = inicio; // at the end: Play starts over
      setTiempo(inicio);
    }
    setReproduciendo(!reproduciendo);
  }

  function buscar(evento) {
    const t = Number(evento.target.value);
    tiempoRef.current = t;
    setTiempo(t);
  }

  const fechaSimulada = new Date(tiempo);

  return (
    <div className="card reproductor">
      <p className="card-title">Reproducir recorrido</p>

      <div className="reproductor-controles">
        <button type="button" className="boton boton-primario" onClick={alternar}>
          {reproduciendo ? "❚❚ Pausa" : "▶ Play"}
        </button>
        {FACTORES.map((f) => (
          <button
            key={f}
            type="button"
            className={`boton ${f === factor ? "boton-activo" : ""}`}
            aria-pressed={f === factor}
            onClick={() => setFactor(f)}
          >
            {f}x
          </button>
        ))}
      </div>

      <input
        type="range"
        className="reproductor-barra"
        aria-label="Momento del recorrido"
        min={inicio}
        max={fin}
        step={1000}
        value={tiempo}
        onChange={buscar}
      />

      <p className="reproductor-hora">
        {formatearFecha(fechaSimulada)} · {formatearHora(fechaSimulada)}
      </p>
    </div>
  );
}

export default Reproductor;
