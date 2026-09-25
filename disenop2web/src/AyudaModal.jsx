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
          Esta página muestra dónde está el dispositivo en el mapa, la ruta que ha
          recorrido y una lista con cada ubicación registrada.
        </p>
      </section>

      <section>
        <h3>Estado (arriba a la derecha)</h3>
        <p>
          Indica qué tan reciente es la última ubicación recibida. «En línea» significa
          que llegó hace 2 minutos o menos. «Hace 15 min», «hace 3 h» o «hace 2 d»
          indican cuánto tiempo ha pasado desde la última señal. Si el dispositivo no
          envía datos, este indicador se va quedando «viejo».
        </p>
      </section>

      <section>
        <h3>El mapa</h3>
        <ul>
          <li>
            <strong>Círculo morado que late:</strong> la ubicación actual del dispositivo.
          </li>
          <li>
            <strong>Círculo verde:</strong> dónde empezó la ruta.
          </li>
          <li>
            <strong>Círculo rojo:</strong> dónde terminó una ruta pasada. Solo aparece
            cuando miras una ruta que ya acabó.
          </li>
          <li>
            <strong>Línea morada:</strong> el camino recorrido entre el inicio y el final.
          </li>
          <li>Puedes arrastrar el mapa y acercarlo o alejarlo con la rueda del ratón o con
            los dedos.</li>
        </ul>
      </section>

      <section>
        <h3>Botones del mapa</h3>
        <ul>
          <li>
            <strong>Botón de capas (pila de rombos):</strong> abre las opciones del mapa.
            «Ajustar a vías» redibuja la ruta sobre las calles y carreteras reales para que
            se vea más limpia. Los puntos originales no cambian.
          </li>
          <li>
            <strong>Botón de mira (círculo con líneas):</strong> «Centrado automático».
            Cuando está activo, el mapa se mueve solo para mantener la ubicación actual en
            el centro, sin cambiar tu zoom.
          </li>
        </ul>
      </section>

      <section>
        <h3>Filtrar por fecha y hora</h3>
        <p>
          Por defecto ves lo de las últimas 24 horas. Pulsa «Filtrar por fecha», elige
          «Desde» y «Hasta» (día y hora) y pulsa «Aplicar». No se pueden elegir fechas
          futuras ni un fin anterior al inicio. Para volver a lo más reciente, pulsa «Ver
          en vivo» o la «x» junto al filtro.
        </p>
      </section>

      <section>
        <h3>Buscar un lugar</h3>
        <p>
          Escribe una ciudad o dirección en el buscador y elige una opción de la lista.
          La página mostrará solo las rutas que pasaron por ese lugar. Las opciones
          marcadas con «Sin historial» son lugares por los que el dispositivo nunca ha
          pasado. Para quitar el filtro, pulsa la «x» junto al buscador.
        </p>
      </section>

      <section>
        <h3>Rutas: «Ruta 2 de 5»</h3>
        <p>
          Una ruta es un viaje completo. Se considera que una ruta terminó y empezó otra
          cuando pasa más de 1 hora sin datos, o cuando el dispositivo aparece a más de 1
          km de donde estaba. Con las flechas «Anterior» y «Actual» te mueves entre viajes:
          «Ruta 5 de 5» es la más reciente.
        </p>
      </section>

      <section>
        <h3>Lista de ubicaciones</h3>
        <p>
          A un lado del mapa (o debajo, en el celular) está la lista de puntos de la ruta
          que estás viendo, del más reciente al más antiguo, con su fecha, hora,
          coordenadas (latitud y longitud) y la dirección de red desde donde se envió. En
          el celular, pulsa el título «Historial de puntos» para abrirla o cerrarla.
        </p>
      </section>

      <section>
        <h3>Si algo falla</h3>
        <p>
          Cuando no hay conexión o el servidor tiene un problema, aparece un aviso
          arriba a la derecha. La página lo intenta de nuevo sola cada 10 segundos y te
          avisa cuando todo vuelva a funcionar.
        </p>
      </section>
    </Modal>
  );
}
