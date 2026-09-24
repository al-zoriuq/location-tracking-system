import { useState } from "react";
import { MAX_NOMBRE } from "../utils/lugaresGuardados";

// Idea F: saved places as chips (one click runs the query) and, in place
// mode, a small form to save the current place under a name.
function LugaresGuardados({ lugares, puedeGuardar, onGuardar, onElegir, onEliminar, error }) {
  const [nombre, setNombre] = useState("");

  function guardar(evento) {
    evento.preventDefault();
    const limpio = nombre.trim();
    if (!limpio) return;
    onGuardar(limpio);
    setNombre("");
  }

  return (
    <div className="lugares-guardados">
      {lugares.length > 0 && (
        <ul className="chips">
          {lugares.map((l) => (
            <li key={l.nombre} className="chip">
              <button
                type="button"
                className="chip-nombre"
                title={`${l.lat.toFixed(5)}, ${l.lon.toFixed(5)} · ${l.radio} m`}
                onClick={() => onElegir(l)}
              >
                {l.nombre}
              </button>
              <button
                type="button"
                className="chip-quitar"
                aria-label={`Eliminar ${l.nombre}`}
                onClick={() => onEliminar(l.nombre)}
              >
                ×
              </button>
            </li>
          ))}
        </ul>
      )}

      {puedeGuardar && (
        <form className="guardar-lugar" onSubmit={guardar}>
          <input
            type="text"
            aria-label="Nombre del lugar"
            placeholder="Nombre (ej. Casa)"
            maxLength={MAX_NOMBRE}
            value={nombre}
            onChange={(e) => setNombre(e.target.value)}
          />
          <button type="submit" className="boton" disabled={!nombre.trim()}>
            Guardar
          </button>
        </form>
      )}

      {error && <p className="mensaje mensaje-aviso">{error}</p>}
    </div>
  );
}

export default LugaresGuardados;
