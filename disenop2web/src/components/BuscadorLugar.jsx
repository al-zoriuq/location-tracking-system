import { useRef, useState } from "react";
import { pedirJSON } from "../utils/api";

// Search box of the location filter: "frisby calle 64" -> list of places to
// pick from (backend /api/buscar-lugar, OpenStreetMap data).
// It searches on Enter / button click, never on every keystroke: the
// geocoders' usage policy forbids autocomplete-style request bursts.
function BuscadorLugar({ onElegir }) {
  const [texto, setTexto] = useState("");
  const [resultados, setResultados] = useState(null); // null = no search yet
  const [cargando, setCargando] = useState(false);
  const [error, setError] = useState(null);
  // A slow answer to an older search must not replace a newer one
  const pedidoRef = useRef(0);

  async function buscar(evento) {
    evento.preventDefault();
    const consulta = texto.trim();
    if (consulta.length < 3) {
      setError("Escribe al menos 3 caracteres para buscar.");
      return;
    }
    const pedido = ++pedidoRef.current;
    setCargando(true);
    setError(null);
    try {
      const datos = await pedirJSON("buscar-lugar", { q: consulta });
      if (pedido === pedidoRef.current) setResultados(datos.resultados);
    } catch (fallo) {
      if (pedido === pedidoRef.current) {
        setResultados(null);
        setError(fallo.message);
      }
    } finally {
      if (pedido === pedidoRef.current) setCargando(false);
    }
  }

  function elegir(resultado) {
    onElegir({ lat: resultado.lat, lon: resultado.lon, nombre: resultado.nombre });
    setTexto(resultado.nombre);
    setResultados(null);
  }

  return (
    <div className="buscador">
      <form className="buscador-form" onSubmit={buscar}>
        <input
          type="search"
          aria-label="Buscar dirección o lugar"
          placeholder="Dirección o lugar (ej. Frisby calle 64)"
          maxLength={100}
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
        />
        <button type="submit" className="boton boton-primario" disabled={cargando}>
          {cargando ? "..." : "Buscar"}
        </button>
      </form>

      {error && <p className="mensaje mensaje-error">{error}</p>}

      {resultados && resultados.length === 0 && (
        <p className="mensaje">
          No se encontraron lugares con ese nombre en Barranquilla. Prueba con otras palabras
          o marca el lugar en el mapa.
        </p>
      )}

      {resultados && resultados.length > 0 && (
        <ul className="buscador-resultados">
          {resultados.map((r) => (
            <li key={`${r.nombre}|${r.lat}|${r.lon}`}>
              <button type="button" className="buscador-resultado" onClick={() => elegir(r)}>
                <span className="buscador-nombre">{r.nombre}</span>
                {r.detalle && <span className="buscador-detalle">{r.detalle}</span>}
              </button>
            </li>
          ))}
        </ul>
      )}

      <p className="buscador-fuente">Búsqueda en Barranquilla · datos de OpenStreetMap</p>
    </div>
  );
}

export default BuscadorLugar;
