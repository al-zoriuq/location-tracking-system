import { formatoDistancia } from "./geo.js";
import { formatoDiaCorto, formatoHora } from "./zona.js";

// List of the times the vehicle was at the searched place, newest first, shown
// at the top of the sidebar. Picking one selects its ring on the map.
export default function PanelVisitas({ visitas, nombreLugar, rangoActivo, seleccionada, onElegir }) {
  if (visitas.length === 0) return null;

  return (
    <section className="visitas" aria-label="Visitas al lugar">
      <p className="visitas-titulo">
        Estuvo en «{nombreLugar}» · {visitas.length} {visitas.length === 1 ? "vez" : "veces"}
      </p>
      <p className="visitas-nota">
        {rangoActivo
          ? "Dentro del rango de fechas seleccionado."
          : "En las últimas 24 horas. Cambia el rango de fechas para ver otras visitas."}
      </p>

      <ul className="visitas-lista">
        {visitas.map((v) => (
          <li key={v.id}>
            <button
              type="button"
              className={`visita-item ${v.id === seleccionada ? "elegida" : ""}`}
              aria-pressed={v.id === seleccionada}
              onClick={() => onElegir(v)}
            >
              <span className="visita-dia">{formatoDiaCorto(v.cercano.fecha)}</span>
              <span className="visita-hora">{formatoHora(v.cercano.fecha)}</span>
              <span className="visita-detalle">
                Ruta {v.indiceRuta + 1} · a {formatoDistancia(v.cercano.distanciaM)} del punto buscado
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
