import { useState } from "react";

const CLAVE_VISTA = "gpslink_bienvenida_vista";

// Short dismissible banner shown only the first time someone opens the page
// (remembered in localStorage). Gives a one-line orientation without the
// weight of the full Ayuda modal.
export default function Bienvenida() {
  const [visible, setVisible] = useState(() => {
    try {
      return !localStorage.getItem(CLAVE_VISTA);
    } catch {
      return false;
    }
  });

  if (!visible) return null;

  const cerrar = () => {
    setVisible(false);
    try {
      localStorage.setItem(CLAVE_VISTA, "1");
    } catch {
      // private browsing or storage disabled: just hide it for this visit
    }
  };

  return (
    <div className="bienvenida" role="status">
      <p>
        Aquí ves en el mapa dónde está el dispositivo, su recorrido y el
        historial de ubicaciones. Abre <strong>Menú</strong> para las demás
        funciones, o <strong>Ayuda</strong> dentro de él si necesitas más
        detalle.
      </p>
      <button type="button" className="bienvenida-cerrar" onClick={cerrar} aria-label="Cerrar">
        ×
      </button>
    </div>
  );
}
