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

export default function AyudaModal({ onCerrar }) {
  return (
    <Modal titulo="Cómo usar esta página" onCerrar={onCerrar}>
      <section>
        <h3>Qué muestra</h3>
        <p>
          Dónde está el dispositivo ahora mismo, la ruta que ha recorrido y el
          historial de cada ubicación registrada.
        </p>
      </section>

      <section>
        <h3>Estado (arriba a la derecha)</h3>
        <p>
          Qué tan reciente es la última señal: «En línea» es 2 minutos o menos; si no,
          muestra hace cuánto llegó («hace 15 min», «hace 3 h»…).
        </p>
      </section>

      <section>
        <h3>El mapa</h3>
        <ul>
          <li><strong>Círculo morado que late:</strong> ubicación actual.</li>
          <li><strong>Verde:</strong> inicio de la ruta. <strong>Rojo:</strong> fin de
            una ruta pasada.</li>
          <li><strong>Línea morada:</strong> el camino recorrido.</li>
        </ul>
      </section>

      <section>
        <h3>Menú y botón de mira</h3>
        <p>
          El botón <strong>Menú</strong> (arriba a la derecha) tiene «Ajustar a vías»,
          que redibuja la ruta sobre las calles reales sin cambiar los puntos
          originales, y el acceso a esta ayuda. El botón de mira, sobre el mapa,
          mantiene la ubicación actual centrada; si mueves el mapa, vuelve solo tras
          unos segundos.
        </p>
      </section>

      <section>
        <h3>Fecha, lugar y rutas</h3>
        <p>
          Por defecto ves las últimas 24 horas; «Filtrar por fecha» permite elegir un
          rango. El buscador de lugar muestra solo las rutas que pasaron por ahí, con
          un círculo amarillo en cada visita. Una ruta es un viaje completo: termina
          cuando pasa más de 1 hora sin datos o el dispositivo salta más de 1 km.
          «Anterior»/«Siguiente» se mueven entre rutas, y tocar el título de la barra
          abre la lista completa para saltar a cualquiera.
        </p>
      </section>

      <section>
        <h3>Lista de ubicaciones</h3>
        <p>
          Junto al mapa (o debajo, en el celular) está el historial de puntos de la
          ruta vista, del más reciente al más antiguo, con fecha, hora y coordenadas.
        </p>
      </section>

      <section>
        <h3>Si algo falla</h3>
        <p>
          Un aviso arriba a la derecha indica problemas de conexión; la página
          reintenta sola cada 10 segundos.
        </p>
      </section>
    </Modal>
  );
}
