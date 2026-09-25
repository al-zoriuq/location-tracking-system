import { useState, useEffect, useRef } from "react";

// The "Ruta 3 de 10 · ..." label of the route bar, as a button that opens the
// list of every route so any of them can be picked in one click instead of
// stepping through with Anterior / Siguiente.
//   opciones: [{ fecha, horario, puntos }], one per route, oldest first
//   indice:   the route being shown
//   onElegir: called with the index of the picked route
export default function SelectorRuta({ etiqueta, opciones, indice, onElegir }) {
  const [abierto, setAbierto] = useState(false);
  const raiz = useRef(null);
  const boton = useRef(null);
  const lista = useRef(null);

  // Click or tap anywhere else closes it
  useEffect(() => {
    if (!abierto) return;
    const alPresionar = (e) => {
      if (raiz.current && !raiz.current.contains(e.target)) setAbierto(false);
    };
    document.addEventListener("pointerdown", alPresionar);
    return () => document.removeEventListener("pointerdown", alPresionar);
  }, [abierto]);

  // On open, put the focus (and the scroll) on the route being shown
  useEffect(() => {
    if (!abierto || !lista.current) return;
    const actual = lista.current.querySelector('[aria-selected="true"]');
    if (actual) {
      actual.focus();
      actual.scrollIntoView({ block: "nearest" });
    }
  }, [abierto]);

  const cerrar = () => {
    setAbierto(false);
    if (boton.current) boton.current.focus();
  };

  const elegir = (i) => {
    onElegir(i);
    cerrar();
  };

  const alPresionarTecla = (e) => {
    if (e.key === "Escape") {
      e.stopPropagation();
      cerrar();
      return;
    }

    const opcionesDom = [...lista.current.querySelectorAll('[role="option"]')];
    const posicion = opcionesDom.indexOf(document.activeElement);
    let destino = null;
    if (e.key === "ArrowDown") destino = opcionesDom[Math.min(posicion + 1, opcionesDom.length - 1)];
    if (e.key === "ArrowUp") destino = opcionesDom[Math.max(posicion - 1, 0)];
    if (e.key === "Home") destino = opcionesDom[0];
    if (e.key === "End") destino = opcionesDom[opcionesDom.length - 1];
    if (destino) {
      e.preventDefault();
      destino.focus();
    }
  };

  return (
    <span className="nav-etiqueta" ref={raiz}>
      <button
        type="button"
        ref={boton}
        className="nav-selector"
        onClick={() => setAbierto(!abierto)}
        aria-haspopup="listbox"
        aria-expanded={abierto}
        aria-label={`${etiqueta}. Elegir otra ruta`}
        title="Elegir otra ruta"
      >
        <span className="nav-selector-texto">{etiqueta}</span>
        <span className="nav-selector-flecha" aria-hidden="true">{abierto ? "▴" : "▾"}</span>
      </button>

      {abierto && (
        <div className="rutas-menu" onKeyDown={alPresionarTecla}>
          {opciones.length > 2 && (
            <div className="rutas-atajos">
              <button type="button" onClick={() => elegir(0)}>« Primera</button>
              <button type="button" onClick={() => elegir(opciones.length - 1)}>Última »</button>
            </div>
          )}
          <div className="rutas-lista" role="listbox" aria-label="Rutas" ref={lista}>
            {opciones.map((o, i) => (
              <button
                key={i}
                type="button"
                role="option"
                aria-selected={i === indice}
                className={`ruta-opcion ${i === indice ? "elegida" : ""}`}
                onClick={() => elegir(i)}
              >
                <span className="ruta-opcion-numero">Ruta {i + 1}</span>
                <span className="ruta-opcion-detalle">{o.fecha} · {o.horario}</span>
                <span className="ruta-opcion-puntos">{o.puntos} {o.puntos === 1 ? "punto" : "puntos"}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </span>
  );
}
