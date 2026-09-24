import { Marker, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import { formatearFecha, formatearHora, haceCuanto } from "../utils/tiempo";
import { centroParaZonaLibre, moverProgramaticamente } from "../utils/mapa";

const ZOOM_DETALLE = 17;

// Inverted drop drawn in SVG (colors come from CSS classes, i.e. from the
// theme variables). Its tip is at (15, 38): that is the icon anchor, so the
// tip, not the middle of the drawing, sits exactly on the GPS coordinate.
// The halo is a separate element pulsing at the base, under the tip.
const iconoGota = L.divIcon({
  className: "",
  html: `
    <div class="gota">
      <span class="gota-halo"></span>
      <svg class="gota-svg" viewBox="0 0 30 40" width="30" height="40" aria-hidden="true">
        <path class="gota-cuerpo" d="M15 38 C15 38 3 24.5 3 15 A12 12 0 1 1 27 15 C27 24.5 15 38 15 38 Z" />
        <circle class="gota-centro" cx="15" cy="15" r="4.5" />
      </svg>
    </div>`,
  iconSize: [30, 40],
  iconAnchor: [15, 38],
  popupAnchor: [0, -36],
});

const formatoVelocidad = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });

// Current position marker. A click flies to it (zoom 17, or the current one
// if deeper), centered in the area not covered by the panels, and opens a
// popup with its details.
function MarcadorActual({ posicion, fecha, velocidadKmh }) {
  const map = useMap();

  function volar() {
    const zoom = Math.max(ZOOM_DETALLE, map.getZoom());
    moverProgramaticamente(map, () =>
      map.flyTo(centroParaZonaLibre(map, posicion, zoom), zoom, { duration: 0.8 })
    );
  }

  return (
    <Marker position={posicion} icon={iconoGota} eventHandlers={{ click: volar }}>
      <Popup autoPan={false} className="popup-gota">
        <p className="popup-titulo">Posición actual</p>
        <p>
          {posicion[0].toFixed(5)}, {posicion[1].toFixed(5)}
        </p>
        <p>
          {formatearFecha(fecha)} · {formatearHora(fecha)}
        </p>
        <p>{haceCuanto(fecha)}</p>
        <p>
          Velocidad estimada:{" "}
          {velocidadKmh === null ? "sin dato" : `${formatoVelocidad.format(velocidadKmh)} km/h`}
        </p>
      </Popup>
    </Marker>
  );
}

export default MarcadorActual;
