import { Marker, Tooltip } from "react-leaflet";
import L from "leaflet";
import { formatearDuracion } from "../utils/lugar";
import { formatearHoraCorta } from "../utils/tiempo";

// Short label for the map: "8 min", "1 h 5 min"
function duracionCorta(segundos) {
  const minutos = Math.round(segundos / 60);
  return minutos < 60 ? `${minutos} min` : `${Math.floor(minutos / 60)} h ${minutos % 60} min`;
}

function iconoParada(parada) {
  return L.divIcon({
    className: "",
    html: `<div class="marker-parada">⏸ ${duracionCorta(parada.duracionS)}</div>`,
    iconSize: [74, 22],
    iconAnchor: [37, 11], // centered on the stop
  });
}

// Idea C: one labeled marker per detected stop of the route on screen
function MarcadoresParada({ paradas }) {
  return paradas.map((parada) => (
    <Marker
      key={parada.inicio.getTime()}
      position={[parada.lat, parada.lon]}
      icon={iconoParada(parada)}
    >
      <Tooltip direction="top" offset={[0, -12]}>
        Parada de {formatearDuracion(Math.round(parada.duracionS))} ·{" "}
        {formatearHoraCorta(parada.inicio)}–{formatearHoraCorta(parada.fin)}
      </Tooltip>
    </Marker>
  ));
}

export default MarcadoresParada;
