import { useEffect } from "react";
import { CircleMarker, Popup, Tooltip, useMap } from "react-leaflet";
import { formatoDistancia } from "./geo.js";
import { formatoDiaCorto, formatoDiaLargo, formatoHora } from "./zona.js";

const COLOR_VISITA = "#ffd166";
const ZOOM_MINIMO_AL_VOLAR = 15;

// Text shown next to a visit: when the vehicle was closest to the place
function etiquetaVisita(v) {
  return `${formatoDiaCorto(v.cercano.fecha)} · ${formatoHora(v.cercano.fecha)}`;
}

// How long the vehicle stayed inside the place's area, "11 min" / "1 h 5 min"
function duracionTexto(v) {
  const minutos = Math.round((v.salida - v.llegada) / 60000);
  if (minutos < 1) return null;
  if (minutos < 60) return `${minutos} min`;
  return `${Math.floor(minutos / 60)} h${minutos % 60 ? ` ${minutos % 60} min` : ""}`;
}

// A ring on the exact recorded point where the vehicle passed the searched
// place, with the day and time. Visits of the route on screen are labelled
// permanently; the others show their label on hover and open the same popup.
// margenSuperior: height in px of the panels floating over the top of the map, so a
// popup that opens near the top makes the map pan instead of hiding under them.
export default function MarcadoresVisitas({ visitas, indiceRuta, seleccionada, onIrARuta, margenSuperior }) {
  return visitas.map((v) => {
    const enPantalla = v.indiceRuta === indiceRuta;
    const elegida = v.id === seleccionada;
    const duracion = duracionTexto(v);

    return (
      <CircleMarker
        // A Leaflet tooltip cannot change between permanent and hover after
        // mounting, so the key changes with it.
        key={`${v.id}-${enPantalla}`}
        center={[v.cercano.lat, v.cercano.lon]}
        radius={elegida ? 18 : 13}
        pathOptions={{
          color: COLOR_VISITA,
          weight: elegida ? 4 : 3,
          opacity: enPantalla ? 1 : 0.6,
          fillColor: COLOR_VISITA,
          fillOpacity: elegida ? 0.3 : 0.16,
        }}
      >
        <Tooltip permanent={enPantalla} direction="top" offset={[0, -12]} className="tooltip-visita">
          {etiquetaVisita(v)}
        </Tooltip>

        <Popup className="popup-visita" autoPanPaddingTopLeft={[16, margenSuperior]}>
          <strong className="popup-visita-dia">{formatoDiaLargo(v.cercano.fecha)}</strong>
          <span className="popup-visita-fila">
            Punto más cercano al lugar: <b>{formatoHora(v.cercano.fecha)}</b>{" "}
            (a {formatoDistancia(v.cercano.distanciaM)})
          </span>
          <span className="popup-visita-fila">
            Dentro del área: {formatoHora(v.llegada)}
            {v.puntos > 1 ? ` – ${formatoHora(v.salida)}` : ""}
            {duracion ? ` (${duracion})` : ""}
          </span>
          <span className="popup-visita-fila">Ruta {v.indiceRuta + 1}</span>
          {!enPantalla && (
            <button type="button" className="popup-visita-boton" onClick={() => onIrARuta(v)}>
              Ver esta ruta
            </button>
          )}
        </Popup>
      </CircleMarker>
    );
  });
}

// Flies the map to a spot whenever `destino` changes ({centro: [lat, lon], n}).
// Never zooms out: if the user is already closer than the minimum, that zoom is kept.
// The spot lands in the middle of the part of the map NOT covered by the panels on
// top: the map center is shifted up by half of `margenSuperior`.
export function VolarA({ destino, margenSuperior }) {
  const map = useMap();

  useEffect(() => {
    if (!destino) return;
    const zoom = Math.max(map.getZoom(), ZOOM_MINIMO_AL_VOLAR);
    const enPantalla = map.project(destino.centro, zoom).subtract([0, margenSuperior / 2]);
    map.flyTo(map.unproject(enPantalla, zoom), zoom, { duration: 0.8 });
    // Only a new destination triggers a flight, not a change of margin
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [destino, map]);

  return null;
}
