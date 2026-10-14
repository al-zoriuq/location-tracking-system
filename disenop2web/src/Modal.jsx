import { useEffect, useRef } from "react";

const SELECTOR_FOCO =
  'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Accessible modal shell: closes with Esc, outside click or its close button,
// keeps keyboard focus inside while open and gives focus back to whatever
// opened it. Reusable for any dialog content.
export function Modal({ titulo, onCerrar, children }) {
  const dialogoRef = useRef(null);
  const onCerrarRef = useRef(onCerrar);

  useEffect(() => {
    onCerrarRef.current = onCerrar;
  });

  useEffect(() => {
    const previo = document.activeElement;
    const dialogo = dialogoRef.current;
    const overflowPrevio = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    dialogo.focus();

    const alPresionarTecla = (e) => {
      if (e.key === "Escape") {
        e.stopPropagation();
        onCerrarRef.current();
        return;
      }
      if (e.key !== "Tab") return;

      // Focus trap: wrap around at both ends of the dialog
      const enfocables = dialogo.querySelectorAll(SELECTOR_FOCO);
      if (enfocables.length === 0) {
        e.preventDefault();
        return;
      }
      const primero = enfocables[0];
      const ultimo = enfocables[enfocables.length - 1];
      if (e.shiftKey && (document.activeElement === primero || document.activeElement === dialogo)) {
        e.preventDefault();
        ultimo.focus();
      } else if (!e.shiftKey && document.activeElement === ultimo) {
        e.preventDefault();
        primero.focus();
      }
    };

    document.addEventListener("keydown", alPresionarTecla);
    return () => {
      document.removeEventListener("keydown", alPresionarTecla);
      document.body.style.overflow = overflowPrevio;
      if (previo && previo.focus) previo.focus();
    };
  }, []);

  return (
    <div
      className="modal-fondo"
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onCerrar();
      }}
    >
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="modal-titulo"
        tabIndex={-1}
        ref={dialogoRef}
      >
        <div className="modal-cabecera">
          <h2 id="modal-titulo">{titulo}</h2>
          <button className="modal-cerrar" onClick={onCerrar} aria-label="Cerrar">
            ×
          </button>
        </div>
        <div className="modal-cuerpo">{children}</div>
        <div className="modal-pie">
          <button className="modal-entendido" onClick={onCerrar}>
            Entendido
          </button>
        </div>
      </div>
    </div>
  );
}
