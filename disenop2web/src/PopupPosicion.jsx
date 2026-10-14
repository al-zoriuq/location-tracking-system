import { formatearFecha, formatearHora, haceCuanto } from "./utils/tiempo";
import { formatearKm } from "./utils/viajes";
import { duracionCorta } from "./MarcadoresParada.jsx";

const formatoKmh = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });

// Contents of the popup that opens when the last marker of the route is clicked:
// where and when, how fast (only while live), and the figures of the whole route.
export default function PopupPosicion({ titulo, punto, velocidadKmh, estadisticas, paradas }) {
  if (!punto) return null;

  return (
    <div className="popup-posicion">
      <strong className="popup-posicion-titulo">{titulo}</strong>
      <span className="popup-posicion-fila">
        {punto.lat.toFixed(5)}, {punto.lon.toFixed(5)}
      </span>
      <span className="popup-posicion-fila">
        {formatearFecha(punto.fecha)} &middot; {formatearHora(punto.fecha)}
      </span>
      <span className="popup-posicion-fila">{haceCuanto(punto.fecha)}</span>
      {velocidadKmh !== null && (
        <span className="popup-posicion-fila">
          Velocidad estimada: <b>{formatoKmh.format(velocidadKmh)} km/h</b>
        </span>
      )}

      {estadisticas && (
        <dl className="popup-posicion-estadisticas">
          <div>
            <dt>Distancia</dt>
            <dd>{formatearKm(estadisticas.distanciaM)}</dd>
          </div>
          <div>
            <dt>Duraci&oacute;n</dt>
            <dd>{duracionCorta(estadisticas.duracionS)}</dd>
          </div>
          <div>
            <dt>Vel. promedio</dt>
            <dd>{formatoKmh.format(estadisticas.promedioKmh)} km/h</dd>
          </div>
          <div>
            <dt>Vel. m&aacute;xima</dt>
            <dd>
              {estadisticas.maximaKmh > 0 ? `${formatoKmh.format(estadisticas.maximaKmh)} km/h` : "\u2014"}
            </dd>
          </div>
          <div>
            <dt>Paradas</dt>
            <dd>{paradas}</dd>
          </div>
        </dl>
      )}
    </div>
  );
}
