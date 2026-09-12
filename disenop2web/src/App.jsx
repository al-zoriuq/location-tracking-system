import "./App.css";
import { useState, useEffect } from "react";
import { MapContainer, TileLayer, Marker, Popup } from "react-leaflet";

import L from "leaflet";
import "leaflet/dist/leaflet.css";

import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";

const iconoMarcador = new L.Icon({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

function App() {
  const [location, setLocation] = useState(null);
  const fechaGPS = location ? new Date(location.timestamp_gps) : null;

  useEffect(() => {
    const nombresPorDominio = {
      "marcelamgps.duckdns.org": "Marcela",
      "tauficgps.duckdns.org": "Taufic",
      "sthefanygps.duckdns.org": "Sthefany",
    };
    const host = window.location.hostname;
    document.title = `GPSLink - ${nombresPorDominio[host] || "GPSLink"}`;
  }, []);

  useEffect(() => {
    const obtenerUbicacion = async () => {
      try {
        const response = await fetch("/api/ultima-ubicacion");

        const data = await response.json();

        console.log(data);

        setLocation(data);
      } catch (error) {
        console.error("Error obteniendo ubicación:", error);
      }
    };

    obtenerUbicacion();

    const intervalo = setInterval(obtenerUbicacion, 10000);

    return () => clearInterval(intervalo);
  }, []);

  return (
    <div className="centrado">
      {location && (
        <>
          <p>IP: {location.ip_origen}</p>
          <p>Latitud: {location.latitud}</p>
          <p>Longitud: {location.longitud}</p>
          <p>Fecha: {fechaGPS.toLocaleDateString("es-CO")}</p>
          <p>Hora: {fechaGPS.toLocaleTimeString("es-CO")}</p>

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

            <Marker
              position={[Number(location.latitud), Number(location.longitud)]}
              icon={iconoMarcador}
            >
              {/*<Popup>
                Ubicación actual
                <br />
                Latitud: {location.latitud}
                <br />
                Longitud: {location.longitud}
              </Popup>*/}
            </Marker>
          </MapContainer>
        </>
      )}

      {!location && <p>Cargando ubicación...</p>}
    </div>
  );
}

export default App;
