import { etiquetaViaje } from "../utils/viajes";

// Trip picker: previous/next buttons plus a dropdown with every trip in the
// period. Trips are addressed by id (timestamp of their first point), never by
// index, because indexes shift when the live 24 h window slides.
function SelectorRutas({ viajes, seleccionadoId, fijado, enVivo, onSeleccionar }) {
  const indice = viajes.findIndex((v) => v.id === seleccionadoId);

  return (
    <div className="card selector">
      <p className="card-title">
        Rutas del periodo ({viajes.length})
        <span className="selector-modo">
          {fijado ? "Ruta fijada" : enVivo ? "Siguiendo la más reciente" : "Última del rango"}
        </span>
      </p>

      <select
        aria-label="Elegir ruta"
        value={seleccionadoId ?? ""}
        onChange={(e) => onSeleccionar(e.target.value)}
      >
        {viajes.map((viaje, i) => (
          <option key={viaje.id} value={viaje.id}>
            {etiquetaViaje(viaje, i + 1)}
          </option>
        ))}
      </select>

      <div className="botones">
        <button
          type="button"
          className="boton"
          disabled={indice <= 0}
          onClick={() => onSeleccionar(viajes[indice - 1].id)}
        >
          ← Ruta anterior
        </button>
        <button
          type="button"
          className="boton"
          disabled={indice < 0 || indice >= viajes.length - 1}
          onClick={() => onSeleccionar(viajes[indice + 1].id)}
        >
          Ruta siguiente →
        </button>
      </div>
    </div>
  );
}

export default SelectorRutas;
