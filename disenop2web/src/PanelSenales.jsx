import { formatoHora } from "./zona.js";
import { nombreSenal, estadoSenal, velocidadTexto, htmlSenal, contarExcesos } from "./senales.js";

// Traffic signs seen during the route on screen, in the order they were passed:
// one section of the side panel, opened with the "Señales" toolbar button.
// The title folds/unfolds the list; the × closes the section (same as turning
// the toolbar button off). Picking a sign pans the map to it.
// Only shown for a route that has signs (App.jsx hides the section and its
// toolbar button otherwise).
export default function PanelSenales({
  senales,
  numeroRuta,
  seleccionada,
  onElegir,
  plegado,
  onPlegar,
  onCerrar,
}) {
  if (senales.length === 0) return null;

  const excesos = contarExcesos(senales);

  return (
    <section className={`senales-panel ${plegado ? "plegada" : ""}`} aria-label="Señales de tránsito de la ruta">
      <div className="seccion-cabecera">
        <button type="button" className="seccion-titulo" onClick={onPlegar} aria-expanded={!plegado}>
          <span className="seccion-flecha" aria-hidden="true">{plegado ? "▸" : "▾"}</span>
          Señales en la ruta {numeroRuta} · {senales.length}
          {excesos > 0 && (
            <span className="senales-excesos">
              {excesos} {excesos === 1 ? "exceso" : "excesos"}
            </span>
          )}
        </button>
        <button
          type="button"
          className="seccion-cerrar"
          onClick={onCerrar}
          aria-label="Cerrar las señales de tránsito"
          title="Cerrar"
        >
          &times;
        </button>
      </div>

      {!plegado && (
        <div className="senales-cuerpo">
          <>
              {/* The number of excesses is already in the title */}
              {excesos === 0 && <p className="senales-resumen">Sin excesos de velocidad</p>}
              <ul className="senales-lista">
                {senales.map((d) => {
                  const estado = estadoSenal(d);
                  const velocidad = velocidadTexto(d);
                  return (
                    <li key={d.id}>
                      <button
                        type="button"
                        className={`senal-item ${estado.clave} ${d.id === seleccionada ? "elegida" : ""}`}
                        aria-pressed={d.id === seleccionada}
                        onClick={() => onElegir(d)}
                      >
                        <span className="senal-item-icono" dangerouslySetInnerHTML={{ __html: htmlSenal(d) }} />
                        <span className="senal-item-nombre">{nombreSenal(d)}</span>
                        <span className="senal-item-hora">{formatoHora(d.fecha)}</span>
                        <span className="senal-item-detalle">
                          {velocidad ?? "Sin velocidad"}
                          <span className={`estado-senal ${estado.clave}`}>{estado.texto}</span>
                        </span>
                      </button>
                    </li>
                  );
                })}
              </ul>
          </>
        </div>
      )}
    </section>
  );
}
