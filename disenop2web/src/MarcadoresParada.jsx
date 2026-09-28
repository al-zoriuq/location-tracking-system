import { useMemo } from "react";
import { Marker, Tooltip } from "react-leaflet";
import L from "leaflet";
import { formatearHoraCorta } from "./utils/tiempo";

// "8 min", "1 h 5 min", "2 h"
export function duracionCorta(segundos) {
  const minutos = Math.round(segundos / 60);
  if (minutos < 60) return `${minutos} min`;
  const horas = Math.floor(minutos / 60);
  const resto = minutos % 60;
  return resto ? `${horas} h ${resto} min` : `${horas} h`;
}

// The pause symbol is drawn (two bars), not an emoji: emoji glyphs change
// with the operating system and can turn into colour pictures.
const SIMBOLO_PAUSA =
  '<svg width="9" height="10" viewBox="0 0 9 10" fill="currentColor" aria-hidden="true">' +
  '<rect x="0.5" y="0.5" width="3" height="9" rx="0.8"/>' +
  '<rect x="5.5" y="0.5" width="3" height="9" rx="0.8"/></svg>';

function iconoParada(parada) {
  return L.divIcon({
    className: "",
    html: `<div class="marker-parada">${SIMBOLO_PAUSA}${duracionCorta(parada.duracionS)}</div>`,
    iconSize: [70, 24],
    iconAnchor: [35, 12], // centered on the stop
  });
}

// One labelled marker per detected stop of the route on screen
export default function MarcadoresParada({ paradas }) {
  // Icons are built once per list of stops, so an unrelated re-render does
  // not make Leaflet replace every marker's DOM
  const iconos = useMemo(() => paradas.map(iconoParada), [paradas]);

  return paradas.map((parada, i) => (
    <Marker key={parada.inicio.getTime()} position={[parada.lat, parada.lon]} icon={iconos[i]}>
      <Tooltip direction="top" offset={[0, -12]}>
        Parada de {duracionCorta(parada.duracionS)} · {formatearHoraCorta(parada.inicio)}–
        {formatearHoraCorta(parada.fin)}
      </Tooltip>
    </Marker>
  ));
}
