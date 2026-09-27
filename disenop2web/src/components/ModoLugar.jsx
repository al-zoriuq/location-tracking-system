import { RADIOS_M, formatearDuracion } from "../utils/lugar";
import { formatearFecha, formatearHora, parsearFechaBogota } from "../utils/tiempo";

const fechaCorta = (texto) => {
  const fecha = parsearFechaBogota(texto);
  return `${formatearFecha(fecha)} ${formatearHora(fecha).slice(0, 5)}`;
};

// Panel of Entrega 2 ("Filtrar por ubicación"): place search, radius picker,
// queried period and the list of passes.
function ModoLugar({
  lugar,
  radio,
  onCambiarRadio,
  resultado,
  cargando,
  error,
  hayRango,
  pasoSeleccionado,
  onSeleccionarPaso,
  onSalir,
  buscador, // address/place search box, rendered first
  guardados, // idea F: saved places block, rendered under the radius picker
}) {
  const pasos = resultado?.pasos ?? [];

  return (
    <div className="card modo-lugar-panel">
      <p className="card-title">Filtrar por ubicación</p>

      {buscador}

      {!lugar && (
        <p className="mensaje">Busca una dirección o haz clic en el mapa para elegir el lugar.</p>
      )}

      <div className="radios" role="group" aria-label="Radio de búsqueda">
        {RADIOS_M.map((r) => (
          <button
            key={r}
            type="button"
            className={`boton ${r === radio ? "boton-primario" : ""}`}
            aria-pressed={r === radio}
            onClick={() => onCambiarRadio(r)}
          >
            {r} m
          </button>
        ))}
      </div>

      {guardados}

      {lugar && (
        <p className="filtro-estado">
          Lugar: {lugar.nombre ? `${lugar.nombre} · ` : ""}
          {lugar.lat.toFixed(5)}, {lugar.lon.toFixed(5)} (arrastra el marcador para moverlo)
        </p>
      )}

      {resultado && (
        <p className="filtro-estado">
          Consultado: {fechaCorta(resultado.rango.desde)} – {fechaCorta(resultado.rango.hasta)}
          {hayRango ? " (rango del filtro)" : " (últimos 30 días)"}
        </p>
      )}

      {error && <p className="mensaje mensaje-error">{error}</p>}
      {cargando && <p className="mensaje">Buscando pasos...</p>}

      {resultado && !cargando && !error && (
        <>
          <p className="resultado-total">
            {resultado.total === 0
              ? "El vehículo no pasó por este lugar en el rango elegido."
              : `El vehículo pasó ${resultado.total} ${resultado.total === 1 ? "vez" : "veces"} por este lugar`}
          </p>

          <ul className="lista-pasos">
            {pasos.map((paso) => {
              const entrada = parsearFechaBogota(paso.entrada);
              const salida = parsearFechaBogota(paso.salida);
              const activo = pasoSeleccionado?.entrada === paso.entrada;
              return (
                <li key={paso.entrada}>
                  <button
                    type="button"
                    className={`paso ${activo ? "paso-activo" : ""}`}
                    onClick={() => onSeleccionarPaso(paso)}
                  >
                    <span className="paso-fila">
                      <span>{formatearFecha(entrada)}</span>
                      <span className={`etiqueta etiqueta-${paso.tipo}`}>
                        {paso.tipo === "parada" ? "Parada" : "Paso"}
                      </span>
                    </span>
                    <span className="paso-fila paso-detalle">
                      <span>
                        {formatearHora(entrada)}–{formatearHora(salida)}
                      </span>
                      <span>{formatearDuracion(paso.duracion_s)}</span>
                    </span>
                    <span className="paso-detalle">
                      a {paso.distancia_minima_m.toLocaleString("es-CO")} m del centro
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}

      <div className="botones">
        <button type="button" className="boton" onClick={onSalir}>
          Salir del filtro por ubicación
        </button>
      </div>
    </div>
  );
}

export default ModoLugar;
