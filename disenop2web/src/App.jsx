import "./App.css";
import { useState, useEffect, useRef } from "react";
import { MapContainer, TileLayer, Marker, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// Custom marker icon for the CURRENT position (purple, pulsing).
// Built with a div + CSS instead of an image, so no extra asset files are needed.
const iconoActual = L.divIcon({
  className: "",
  html: '<div class="marker-current"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

// Custom marker icon for the START of the route (gold, static, no pulse).
const iconoInicio = L.divIcon({
  className: "",
  html: '<div class="marker-start"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

// Helper component: runs INSIDE the map (needs useMap hook) and auto-fits
// the view to show the whole route the FIRST time points arrive.
// After that first fit, it never touches the zoom/position again, so the
// user's manual zoom/pan is preserved on later data refreshes.
function AjustarVista({ puntos }) {
  const map = useMap();
  const yaAjustado = useRef(false); // true once we've done the initial fit

  useEffect(() => {
    if (yaAjustado.current) return; // skip if we already auto-fitted once

    if (puntos.length > 1) {
      // Multiple points: fit the map to show the entire route with some padding
      map.fitBounds(puntos, { padding: [60, 60] });
      yaAjustado.current = true;
    } else if (puntos.length === 1) {
      // Only one point: just center on it at a reasonable zoom level
      map.setView(puntos[0], 13);
      yaAjustado.current = true;
    }
  }, [puntos, map]);

  return null; // this component renders nothing visible, it only controls the map
}

// The backend stores timestamps in UTC (the EC2 server's system clock is UTC),
// but they come back as plain strings with no timezone marker, e.g.
// "2026-09-13 19:23:18.866782". JavaScript would otherwise assume that string
// is already in the browser's local time, which would be wrong.
// This explicitly marks it as UTC ("Z" suffix, ISO format), so toLocaleString/
// toLocaleDateString/toLocaleTimeString later convert it correctly to
// Colombia time (UTC-5). Shared by both the floating panel and the sidebar list.
function parsearFechaUTC(timestampTexto) {
  return new Date(timestampTexto.replace(" ", "T") + "Z");
}

// Given the timestamp of the last GPS reading, returns:
// - a human-readable relative time string in Spanish ("hace 5 min", etc.)
// - a status tier ("fresh" | "medium" | "old") used to pick the status dot color
function calcularEstado(fechaGPS) {
  if (!fechaGPS) {
    return { texto: "sin datos", tier: "old" };
  }

  const ahora = new Date();
  const diffMs = ahora - fechaGPS;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHoras = Math.floor(diffMin / 60);
  const diffDias = Math.floor(diffHoras / 24);

  // Fresh: 2 minutes or less -> show as "en línea"
  if (diffMin <= 2) {
    return { texto: "en línea", tier: "fresh" };
  }

  // Medium: under an hour -> show exact minutes
  if (diffMin < 60) {
    return { texto: `hace ${diffMin} min`, tier: "medium" };
  }

  // Stale: under a day -> show exact hours
  if (diffHoras < 24) {
    return { texto: `hace ${diffHoras} h`, tier: "old" };
  }

  // Very stale: show days
  return { texto: `hace ${diffDias} d`, tier: "old" };
}

function App() {
  const [location, setLocation] = useState(null); // latest GPS position from the API
  const [historial, setHistorial] = useState([]); // full history: raw objects (lat, lon, ip, timestamp)

  // Parse the latest location's timestamp once, reused for the panel and the status dot
  const fechaGPS = location ? parsearFechaUTC(location.timestamp_gps) : null;
  const estado = calcularEstado(fechaGPS); // { texto, tier } for the status indicator

  // Derive just the [lat, lng] pairs from the raw history, for the Polyline/markers.
  // Kept separate from `historial` because the sidebar list needs the full
  // objects (ip_origen, timestamp), while the map only needs coordinate pairs.
  const ruta = historial.map((punto) => [
    Number(punto.latitud),
    Number(punto.longitud),
  ]);

  // Set the browser tab title once, using the person's name from the build-time env var
  useEffect(() => {
    const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";
    document.title = `GPSLink - ${nombre}`;
  }, []);

  // Poll the backend every 10 seconds for the latest position and the route history
  useEffect(() => {
    // Fetch only the single latest location
    const obtenerUbicacion = async () => {
      try {
        const response = await fetch(import.meta.env.BASE_URL + "api/ultima-ubicacion");
        const data = await response.json();
        setLocation(data);
      } catch (error) {
        console.error("Error obteniendo ubicación:", error);
      }
    };

    // Fetch the recent history of points, used both for the route line and the sidebar list
    const obtenerHistorial = async () => {
      try {
        const response = await fetch(import.meta.env.BASE_URL + "api/historial-ubicaciones");
        const data = await response.json();
        setHistorial(data); // keep the raw objects; we need ip_origen and timestamp per point
      } catch (error) {
        console.error("Error obteniendo historial:", error);
      }
    };

    // Run both once immediately on load
    obtenerUbicacion();
    obtenerHistorial();

    // Then repeat every 10 seconds
    const intervalo = setInterval(() => {
      obtenerUbicacion();
      obtenerHistorial();
    }, 10000);

    // Cleanup: stop polling when the component unmounts
    return () => clearInterval(intervalo);
  }, []);

  const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";

  // Sidebar list: most recent point first (reverse of the chronological
  // order used for the route line, which goes oldest -> newest)
  const historialReciente = [...historial].reverse();

  return (
    <div className="app">
      {/* Top bar: app name + person's name + status indicator (dot + relative time) */}
      <div className="topbar">
        <div className="brand">
          GPSLink <span>· {nombre}</span>
        </div>
        <div className="status">
          <span className={`dot dot-${estado.tier}`}></span>
          {estado.texto}
        </div>
      </div>

      <div className="main">
        {location ? (
          <>
            {/* Floating info card with the latest coordinates and timestamp */}
            <div className="panel">
              <p className="label">Última posición</p>
              <div className="coords">
                <div className="coord-row">
                  <span className="coord-label">Lat</span>
                  <span>{Number(location.latitud).toFixed(4)}</span>
                </div>
                <div className="coord-row">
                  <span className="coord-label">Lon</span>
                  <span>{Number(location.longitud).toFixed(4)}</span>
                </div>
              </div>
              <div className="meta">
                <span>{fechaGPS.toLocaleDateString("es-CO")}</span>
                <span>{fechaGPS.toLocaleTimeString("es-CO")}</span>
              </div>
              <p className="ip">IP: {location.ip_origen}</p>
            </div>

            {/* Small legend explaining marker colors, only shown when there's a route to explain */}
            {ruta.length > 1 && (
              <div className="legend">
                <div className="legend-item">
                  <span className="legend-dot start"></span> Inicio
                </div>
                <div className="legend-item">
                  <span className="legend-dot current"></span> Actual
                </div>
              </div>
            )}

            <MapContainer
              center={[Number(location.latitud), Number(location.longitud)]}
              zoom={13}
              scrollWheelZoom={true}
              className="map"
            >
              {/* Base map tiles from OpenStreetMap (free, no API key required).
                  The dark/purple look comes from a CSS filter applied in App.css,
                  not from the tiles themselves. */}
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              {/* Controls the initial auto-zoom/center, see component above */}
              <AjustarVista puntos={ruta} />

              {/* Route line connecting all historical points, only drawn with 2+ points */}
              {ruta.length > 1 && (
                <Polyline positions={ruta} color="#b37feb" weight={3} opacity={0.75} />
              )}

              {/* Start marker: first point of the route */}
              {ruta.length > 1 && <Marker position={ruta[0]} icon={iconoInicio} />}

              {/* Current position marker: always shown */}
              <Marker
                position={[Number(location.latitud), Number(location.longitud)]}
                icon={iconoActual}
              />
            </MapContainer>

            {/* Sidebar: scrollable list of every recorded point, most recent first.
                Shows the same fields as the floating panel (lat, lon, date, time, IP)
                but as a running log instead of just the latest point. */}
            <aside className="sidebar">
              <p className="sidebar-title">Historial de puntos ({historialReciente.length})</p>
              <div className="sidebar-list">
                {historialReciente.map((punto, index) => {
                  const fecha = parsearFechaUTC(punto.timestamp_gps);
                  // In the reversed list: last item = oldest = start of route,
                  // first item = newest = current position
                  const esInicio = index === historialReciente.length - 1;
                  const esActual = index === 0;
                  return (
                    <div className="sidebar-item" key={index}>
                      <div className="sidebar-item-header">
                        {/* Colored dot matches the marker color on the map:
                            gold for start, purple for current, neutral for the rest */}
                        <span
                          className={`legend-dot ${esInicio ? "start" : esActual ? "current" : ""}`}
                        ></span>
                        <span className="sidebar-item-time">
                          {fecha.toLocaleDateString("es-CO")} · {fecha.toLocaleTimeString("es-CO")}
                        </span>
                      </div>
                      <div className="coord-row small">
                        <span className="coord-label">Lat</span>
                        <span>{Number(punto.latitud).toFixed(4)}</span>
                      </div>
                      <div className="coord-row small">
                        <span className="coord-label">Lon</span>
                        <span>{Number(punto.longitud).toFixed(4)}</span>
                      </div>
                      <p className="sidebar-item-ip">IP: {punto.ip_origen}</p>
                    </div>
                  );
                })}
              </div>
            </aside>
          </>
        ) : (
          <p className="empty-state">Cargando ubicación...</p>
        )}
      </div>
    </div>
  );
}

export default App;
