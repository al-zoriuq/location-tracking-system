import "./App.css";
import { useState, useEffect } from "react";
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

function AjustarVista({ puntos }) {
  const map = useMap();

  useEffect(() => {
    if (puntos.length > 1) {
      map.fitBounds(puntos, { padding: [60, 60] });
    } else if (puntos.length === 1) {
      map.setView(puntos[0], 13);
    }
  }, [puntos, map]);

  return null;
}

function App() {
  const [location, setLocation] = useState(null);
  const [ruta, setRuta] = useState([]);
  const fechaGPS = location ? new Date(location.timestamp_gps) : null;

  useEffect(() => {
    const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";
    document.title = `GPSLink - ${nombre}`;
  }, []);

  useEffect(() => {
    const obtenerUbicacion = async () => {
      try {
        const response = await fetch(import.meta.env.BASE_URL + "api/ultima-ubicacion");
        const data = await response.json();
        setLocation(data);
      } catch (error) {
        console.error("Error obteniendo ubicación:", error);
      }
    };

    const obtenerHistorial = async () => {
      try {
        const response = await fetch(import.meta.env.BASE_URL + "api/historial-ubicaciones");
        const data = await response.json();
        const puntos = data.map((punto) => [
          Number(punto.latitud),
          Number(punto.longitud),
        ]);
        setRuta(puntos);
      } catch (error) {
        console.error("Error obteniendo historial:", error);
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
          <span className="dot"></span>
          {location ? "en línea" : "sin datos"}
        </div>
      </div>

      <div className="main">
        {location ? (
          <>
            <div className="panel">
              <p className="label">Última posición</p>
              <p className="coords">
                {Number(location.latitud).toFixed(4)}, {Number(location.longitud).toFixed(4)}
              </p>
              <div className="meta">
                <span>{fechaGPS.toLocaleDateString("es-CO")}</span>
                <span>{fechaGPS.toLocaleTimeString("es-CO")}</span>
              </div>
              <p className="ip">IP: {location.ip_origen}</p>
            </div>

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
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              <AjustarVista puntos={ruta} />

              {ruta.length > 1 && (
                <Polyline positions={ruta} color="#b37feb" weight={3} opacity={0.75} />
              )}

              {ruta.length > 1 && <Marker position={ruta[0]} icon={iconoInicio} />}

              <Marker
                position={[Number(location.latitud), Number(location.longitud)]}
                icon={iconoActual}
              />
            </MapContainer>
          </>
        ) : (
          <p className="empty-state">Cargando ubicación...</p>
        )}
      </div>
    </div>
  );
}

export default App;
