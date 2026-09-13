import "./App.css";
import { useState, useEffect } from "react";
import { MapContainer, TileLayer, Marker, Polyline } from "react-leaflet";

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

        console.log(data);

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

            {ruta.length > 1 && (
              <Polyline positions={ruta} color="#2563eb" weight={4} opacity={0.8} />
            )}

            <Marker
              position={[Number(location.latitud), Number(location.longitud)]}
              icon={iconoMarcador}
            />
          </MapContainer>
        </>
      )}

      {!location && <p>Cargando ubicación...</p>}
    </div>
  );
}

export default App;
