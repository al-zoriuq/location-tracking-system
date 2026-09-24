import { useEffect } from "react";
import { Circle, Marker, Polyline, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";

const iconoLugar = L.divIcon({
  className: "",
  html: '<div class="marker-lugar"></div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
});

// Map-side part of Entrega 2 (rendered inside <MapContainer>).
// Only while `activo`: crosshair cursor, a click sets the place, the marker
// can be dragged, and the circle shows the search radius. Outside this mode
// a map click does nothing new.
function CapaLugar({ activo, lugar, radio, onFijarLugar, rutaPaso, tramoResaltado }) {
  const map = useMap();

  useEffect(() => {
    if (!activo) return;
    const contenedor = map.getContainer();
    contenedor.classList.add("modo-lugar");
    return () => contenedor.classList.remove("modo-lugar");
  }, [activo, map]);

  useMapEvents({
    click(evento) {
      if (activo) onFijarLugar({ lat: evento.latlng.lat, lon: evento.latlng.lng });
    },
  });

  if (!activo) return null;

  return (
    <>
      {rutaPaso.length > 0 && (
        <Polyline
          positions={rutaPaso}
          pathOptions={{ className: "ruta-linea", weight: 3, opacity: 0.8 }}
        />
      )}

      {tramoResaltado.length > 1 && (
        <Polyline
          positions={tramoResaltado}
          pathOptions={{ className: "ruta-resaltada", weight: 7, opacity: 0.95 }}
        />
      )}

      {lugar && (
        <>
          <Circle
            center={[lugar.lat, lugar.lon]}
            radius={radio}
            pathOptions={{ className: "lugar-circulo", weight: 2 }}
          />
          <Marker
            position={[lugar.lat, lugar.lon]}
            icon={iconoLugar}
            draggable={true}
            eventHandlers={{
              dragend: (evento) => {
                const p = evento.target.getLatLng();
                onFijarLugar({ lat: p.lat, lon: p.lng });
              },
            }}
          />
        </>
      )}
    </>
  );
}

export default CapaLugar;
