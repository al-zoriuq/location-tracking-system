import { formatearDuracion } from "../utils/lugar";
import { formatearKm } from "../utils/viajes";

const formatoKmh = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 0 });

// Idea A: distance, duration, average and top speed of the route on screen
function EstadisticasRuta({ titulo, estadisticas }) {
  if (!estadisticas) return null;
  const { distanciaM, duracionS, promedioKmh, maximaKmh } = estadisticas;

  return (
    <div className="card">
      <p className="card-title">{titulo}</p>
      <dl className="estadisticas">
        <div>
          <dt>Distancia</dt>
          <dd>{formatearKm(distanciaM)}</dd>
        </div>
        <div>
          <dt>Duración</dt>
          <dd>{formatearDuracion(Math.round(duracionS))}</dd>
        </div>
        <div>
          <dt>Vel. promedio</dt>
          <dd>{formatoKmh.format(promedioKmh)} km/h</dd>
        </div>
        <div>
          <dt>Vel. máxima</dt>
          <dd>{maximaKmh > 0 ? `${formatoKmh.format(maximaKmh)} km/h` : "—"}</dd>
        </div>
      </dl>
    </div>
  );
}

export default EstadisticasRuta;
