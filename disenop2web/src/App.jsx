import "./App.css";
import { useState, useEffect, useRef, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

const iconoActual = L.divIcon({
  className: "",
  html: '<div class="marker-current"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

const iconoInicio = L.divIcon({
  className: "",
  html: '<div class="marker-start"></div>',
  iconSize: [12, 12],
  iconAnchor: [6, 6],
});

// A "trip" is considered finished if this much time passes with no new GPS
// reading. The next reading after that gap starts a brand-new trip.
const UMBRAL_NUEVA_RUTA_MS = 60 * 60 * 1000; // 1 hour

function AjustarVista({ puntos, resetKey }) {
  const map = useMap();
  const yaAjustado = useRef(false);
  const resetKeyAnterior = useRef(resetKey);

  useEffect(() => {
    if (resetKey !== resetKeyAnterior.current) {
      yaAjustado.current = false;
      resetKeyAnterior.current = resetKey;
    }

    if (yaAjustado.current) return;

    if (puntos.length > 1) {
      map.fitBounds(puntos, { padding: [60, 60] });
      yaAjustado.current = true;
    } else if (puntos.length === 1) {
      map.setView(puntos[0], 13);
      yaAjustado.current = true;
    }
  }, [puntos, map, resetKey]);

  return null;
}

function parsearFechaUTC(timestampTexto) {
  return new Date(timestampTexto.replace(" ", "T") + "Z");
}

function calcularEstado(fechaGPS) {
  if (!fechaGPS) {
    return { texto: "sin datos", tier: "old" };
  }

  const ahora = new Date();
  const diffMs = ahora - fechaGPS;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHoras = Math.floor(diffMin / 60);
  const diffDias = Math.floor(diffHoras / 24);

  if (diffMin <= 2) {
    return { texto: "en línea", tier: "fresh" };
  }

  if (diffMin < 60) {
    return { texto: `hace ${diffMin} min`, tier: "medium" };
  }

  if (diffHoras < 24) {
    return { texto: `hace ${diffHoras} h`, tier: "old" };
  }

  return { texto: `hace ${diffDias} d`, tier: "old" };
}

// Splits the full (chronological, oldest -> newest) history into separate
// "trips". A new trip starts whenever the gap between two consecutive
// readings exceeds UMBRAL_NUEVA_RUTA_MS.
function dividirEnRutas(historial) {
  if (historial.length === 0) return [];

  const rutas = [];
  let rutaActual = [historial[0]];

  for (let i = 1; i < historial.length; i++) {
    const fechaAnterior = parsearFechaUTC(historial[i - 1].timestamp_gps);
    const fechaActual = parsearFechaUTC(historial[i].timestamp_gps);
    const diffMs = fechaActual - fechaAnterior;

    if (diffMs > UMBRAL_NUEVA_RUTA_MS) {
      rutas.push(rutaActual);
      rutaActual = [historial[i]];
    } else {
      rutaActual.push(historial[i]);
    }
  }

  rutas.push(rutaActual);
  return rutas;
}

function App() {
  const [location, setLocation] = useState(null);
  const [historial, setHistorial] = useState([]);

  // null = "follow the most recent trip live". A number = pinned to that
  // specific trip index, regardless of new data arriving later.
  const [indiceRuta, setIndiceRuta] = useState(null);

  const fechaGPS = location ? parsearFechaUTC(location.timestamp_gps) : null;
  const estado = calcularEstado(fechaGPS);

  const rutas = useMemo(() => dividirEnRutas(historial), [historial]);

  const siguiendoActual = indiceRuta === null;
  const indiceMostrado = siguiendoActual ? rutas.length - 1 : indiceRuta;
  const puntosRutaMostrada = rutas[indiceMostrado] || [];

  const ruta = puntosRutaMostrada.map((punto) => [
    Number(punto.latitud),
    Number(punto.longitud),
  ]);

  const historialReciente = [...puntosRutaMostrada].reverse();

  const etiquetaRuta = useMemo(() => {
    if (puntosRutaMostrada.length === 0) return "";

    const primero = parsearFechaUTC(puntosRutaMostrada[0].timestamp_gps);
    const ultimo = parsearFechaUTC(
      puntosRutaMostrada[puntosRutaMostrada.length - 1].timestamp_gps
    );

    const rango =
      puntosRutaMostrada.length > 1
        ? `${primero.toLocaleDateString("es-CO")}, ${primero.toLocaleTimeString("es-CO", {
            hour: "2-digit",
            minute: "2-digit",
          })} - ${ultimo.toLocaleTimeString("es-CO", { hour: "2-digit", minute: "2-digit" })}`
        : `${primero.toLocaleDateString("es-CO")}, ${primero.toLocaleTimeString("es-CO", {
            hour: "2-digit",
            minute: "2-digit",
          })}`;

    return `Ruta ${indiceMostrado + 1} de ${rutas.length} · ${rango}`;
  }, [puntosRutaMostrada, indiceMostrado, rutas.length]);

  const verRutaAnterior = () => {
    setIndiceRuta(Math.max(0, indiceMostrado - 1));
  };

  const volverARutaActual = () => {
    setIndiceRuta(null);
  };

  useEffect(() => {
    const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";
    document.title = `GPSLink - ${nombre}`;
  }, []);

  useEffect(() => {
    const obtenerUbicacion = async () => {
      try {
        const response = await fetch(import.meta.env.BASE_URL + "api/ultima-ubicacion");
        if (!response.ok) {
          setLocation(null);
          return;
        }
        const data = await response.json();
        setLocation(data);
      } catch (error) {
        console.error("Error obteniendo ubicación:", error);
        setLocation(null);
      }
    };

    const obtenerHistorial = async () => {
      try {
        const response = await fetch(import.meta.env.BASE_URL + "api/historial-ubicaciones");
        if (!response.ok) {
          setHistorial([]);
          return;
        }
        const data = await response.json();
        setHistorial(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error("Error obteniendo historial:", error);
        setHistorial([]);
      }
    };

    obtenerUbicacion();
    obtenerHistorial();

    const intervalo = setInterval(() => {
      obtenerUbicacion();
      obtenerHistorial();
    }, 10000);

    return () => clearInterval(intervalo);
  }, []);

  const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";

  return (
    <div className="app">
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

            {rutas.length > 0 && (
              <div
                style={{
                  position: "absolute",
                  top: "12px",
                  left: "50%",
                  transform: "translateX(-50%)",
                  zIndex: 1000,
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  backgroundColor: "rgba(20, 16, 32, 0.85)",
                  padding: "8px 14px",
                  borderRadius: "10px",
                  fontFamily: "inherit",
                  fontSize: "13px",
                  color: "#e5dcff",
                  backdropFilter: "blur(4px)",
                }}
              >
                <button
                  onClick={verRutaAnterior}
                  disabled={indiceMostrado === 0}
                  style={{
                    background: "none",
                    border: "1px solid #7c3aed",
                    color: indiceMostrado === 0 ? "#5a5568" : "#e5dcff",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    cursor: indiceMostrado === 0 ? "default" : "pointer",
                    opacity: indiceMostrado === 0 ? 0.5 : 1,
                  }}
                >
                  ← Ruta anterior
                </button>

                <span style={{ whiteSpace: "nowrap" }}>{etiquetaRuta}</span>

                {!siguiendoActual && (
                  <button
                    onClick={volverARutaActual}
                    style={{
                      background: "#7c3aed",
                      border: "none",
                      color: "white",
                      borderRadius: "6px",
                      padding: "4px 10px",
                      cursor: "pointer",
                    }}
                  >
                    Ruta actual →
                  </button>
                )}
              </div>
            )}

            {ruta.length > 1 && (
              <div className="legend">
                <div className="legend-item">
                  <span className="legend-dot start"></span> Inicio
                </div>
                <div className="legend-item">
                  <span className="legend-dot current"></span>
                  {siguiendoActual ? " Actual" : " Fin de ruta"}
                </div>
              </div>
            )}

            <MapContainer
              center={[Number(location.latitud), Number(location.longitud)]}
              zoom={13}
              scrollWheelZoom={true}
              className="map"
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              <AjustarVista puntos={ruta} resetKey={indiceMostrado} />

              {ruta.length > 1 && (
                <Polyline positions={ruta} color="#b37feb" weight={3} opacity={0.75} />
              )}

              {ruta.length > 1 && <Marker position={ruta[0]} icon={iconoInicio} />}

              {ruta.length > 0 && (
                <Marker position={ruta[ruta.length - 1]} icon={iconoActual} />
              )}
            </MapContainer>

            <aside className="sidebar">
              <p className="sidebar-title">
                Historial de puntos ({historialReciente.length})
              </p>
              <div className="sidebar-list">
                {historialReciente.map((punto, index) => {
                  const fecha = parsearFechaUTC(punto.timestamp_gps);
                  const esInicio = index === historialReciente.length - 1;
                  const esActual = index === 0;
                  return (
                    <div className="sidebar-item" key={index}>
                      <div className="sidebar-item-header">
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
