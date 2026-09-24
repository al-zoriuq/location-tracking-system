import { useState } from "react";
import { aTextoBogota, hoyBogota, parsearFechaBogota } from "../utils/tiempo";

// Splits "YYYY-MM-DD HH:MM:SS" into the values of the date and time inputs
function separar(texto) {
  const [fecha, hora] = texto.split(" ");
  return { fecha, hora: hora.slice(0, 5) };
}

// Panel "Filtrar por fecha" (Entrega 1). All values are Bogota wall-clock
// time: the strings from the inputs are concatenated as-is and only turned
// into a Date (with the -05:00 offset) to compare against the current time.
function FiltroFechas({ rango, onAplicar, onVerEnVivo, puedeVolverEnVivo }) {
  const [desde, setDesde] = useState(() =>
    rango ? separar(rango.desde) : { fecha: hoyBogota(), hora: "00:00" }
  );
  const [hasta, setHasta] = useState(() =>
    rango ? separar(rango.hasta) : { fecha: hoyBogota(), hora: "23:59" }
  );
  const [error, setError] = useState(null);
  const [aviso, setAviso] = useState(null);

  const hoy = hoyBogota();

  function aplicar(evento) {
    evento.preventDefault();
    setError(null);
    setAviso(null);

    if (!desde.fecha || !desde.hora || !hasta.fecha || !hasta.hora) {
      setError("Completa la fecha y la hora de inicio y de fin.");
      return;
    }

    const textoDesde = `${desde.fecha} ${desde.hora.slice(0, 5)}:00`;
    let textoHasta = `${hasta.fecha} ${hasta.hora.slice(0, 5)}:59`;
    const ahora = new Date();

    if (parsearFechaBogota(textoDesde) > ahora) {
      setError("La fecha de inicio (Desde) no puede estar en el futuro.");
      return;
    }

    let nuevoAviso = null;
    if (parsearFechaBogota(textoHasta) > ahora) {
      // e.g. "today 23:59": nothing can exist after now, clamp it
      textoHasta = aTextoBogota(ahora);
      setHasta(separar(textoHasta));
      nuevoAviso = "Hasta se ajustó a la hora actual.";
    }

    if (parsearFechaBogota(textoDesde) >= parsearFechaBogota(textoHasta)) {
      setError("Desde debe ser anterior a Hasta.");
      return;
    }

    setAviso(nuevoAviso);
    onAplicar({ desde: textoDesde, hasta: textoHasta });
  }

  function verEnVivo() {
    setError(null);
    setAviso(null);
    onVerEnVivo();
  }

  return (
    <form className="card filtro" onSubmit={aplicar}>
      <p className="card-title">Filtrar por fecha</p>

      <div className="filtro-fila">
        <span className="filtro-etiqueta">Desde</span>
        <input
          type="date"
          aria-label="Fecha de inicio"
          max={hoy}
          value={desde.fecha}
          onChange={(e) => setDesde({ ...desde, fecha: e.target.value })}
        />
        <input
          type="time"
          aria-label="Hora de inicio"
          value={desde.hora}
          onChange={(e) => setDesde({ ...desde, hora: e.target.value })}
        />
      </div>

      <div className="filtro-fila">
        <span className="filtro-etiqueta">Hasta</span>
        <input
          type="date"
          aria-label="Fecha de fin"
          max={hoy}
          value={hasta.fecha}
          onChange={(e) => setHasta({ ...hasta, fecha: e.target.value })}
        />
        <input
          type="time"
          aria-label="Hora de fin"
          value={hasta.hora}
          onChange={(e) => setHasta({ ...hasta, hora: e.target.value })}
        />
      </div>

      {error && <p className="mensaje mensaje-error">{error}</p>}
      {aviso && <p className="mensaje mensaje-aviso">{aviso}</p>}

      <div className="botones">
        <button type="submit" className="boton boton-primario">
          Aplicar
        </button>
        <button
          type="button"
          className="boton"
          onClick={verEnVivo}
          disabled={!puedeVolverEnVivo}
        >
          Ver en vivo
        </button>
      </div>

      <p className="filtro-estado">
        {rango
          ? `Rango: ${rango.desde.slice(0, 16)} – ${rango.hasta.slice(0, 16)}`
          : "En vivo: últimas 24 h"}
      </p>
    </form>
  );
}

export default FiltroFechas;
