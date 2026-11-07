import { formatoHora } from "./zona.js";
import { nombreSenal, estadoSenal, velocidadTexto, htmlSenal, contarExcesos } from "./senales.js";

// Traffic signs seen during the route on screen, in the order they were passed,
// shown at the top of the sidebar. Picking one flies the map to it.
// hayDetecciones: the loaded period has signs on some route; when it has none at
// all (e.g. a phone without camera) the section is not shown.
export default function PanelSenales({ senales, numeroRuta, hayDetecciones, seleccionada, onElegir }) {
  if (!hayDetecciones) return null;

  const excesos = contarExcesos(senales);

  return (
    <section className="senales-panel" aria-label="Señales de tránsito de la ruta">
      <p className="senales-titulo">
        Señales en la ruta {numeroRuta} · {senales.length}
      </p>
      {senales.length === 0 ? (
        <p className="senales-nota">No se detectaron señales de tránsito en esta ruta.</p>
      ) : (
        <>
          <p className={`senales-resumen ${excesos ? "con-excesos" : ""}`}>
            {excesos === 0
              ? "Sin excesos de velocidad"
              : `${excesos} ${excesos === 1 ? "exceso" : "excesos"} de velocidad`}
          </p>
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
      )}
    </section>
  );
}
