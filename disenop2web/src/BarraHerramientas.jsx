// Labelled map toolbar: Señales, Puntos, Reproducir, Capas.
// Vertical on the right of the map on wide screens; horizontal at the bottom
// in compact mode (phones). The centring and hide-panels buttons are NOT here:
// they sit on their own in the bottom-right corner (see App.jsx).

function Icono({ children }) {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      {children}
    </svg>
  );
}

export default function BarraHerramientas({
  senalesAbierto,
  puntosAbierto,
  onSenales,
  onPuntos,
  excesos,
  mostrarSenales,
  reproductorAbierto,
  puedeReproducir,
  onReproducir,
  capasAbierto,
  onCapas,
  snapActivo,
  menuCapas,
}) {
  return (
    <nav className="barra-herramientas" aria-label="Herramientas del mapa">
      {/* Only when the route on screen has traffic signs */}
      {mostrarSenales && (
        <button
          type="button"
          className={`barra-btn barra-btn-panel ${senalesAbierto ? "activo" : ""}`}
          onClick={onSenales}
          aria-pressed={senalesAbierto}
          title="Señales de tránsito de la ruta"
        >
          <Icono>
            <circle cx="12" cy="12" r="9" />
            <path d="M9.5 10.5h3v4" />
          </Icono>
          <span className="barra-texto">Señales</span>
          {excesos > 0 && (
            <span className="barra-globo" aria-label={`${excesos} ${excesos === 1 ? "exceso" : "excesos"} de velocidad`}>
              {excesos}
            </span>
          )}
        </button>
      )}

      <button
        type="button"
        className={`barra-btn barra-btn-panel ${puntosAbierto ? "activo" : ""}`}
        onClick={onPuntos}
        aria-pressed={puntosAbierto}
        title="Historial de puntos de la ruta"
      >
        <Icono>
          <line x1="8" y1="6" x2="21" y2="6" />
          <line x1="8" y1="12" x2="21" y2="12" />
          <line x1="8" y1="18" x2="21" y2="18" />
          <line x1="3" y1="6" x2="3.01" y2="6" />
          <line x1="3" y1="12" x2="3.01" y2="12" />
          <line x1="3" y1="18" x2="3.01" y2="18" />
        </Icono>
        <span className="barra-texto">Puntos</span>
      </button>

      <button
        type="button"
        className={`barra-btn ${reproductorAbierto ? "activo" : ""}`}
        onClick={onReproducir}
        disabled={!puedeReproducir}
        aria-pressed={reproductorAbierto}
        title="Reproduce el recorrido de la ruta mostrada"
      >
        <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" stroke="currentColor"
          strokeWidth="2" strokeLinejoin="round" aria-hidden="true">
          <polygon points="7 4 20 12 7 20 7 4" />
        </svg>
        <span className="barra-texto">Reproducir</span>
      </button>

      {/* The map options menu opens next to its button (left of it on wide
          screens, above it on phones), so no other button moves */}
      <div className="capas-ancla">
        {capasAbierto && menuCapas}
        <button
          type="button"
          className={`barra-btn ${capasAbierto ? "activo" : ""}`}
          onClick={onCapas}
          aria-expanded={capasAbierto}
          title="Opciones del mapa"
        >
          <Icono>
            <polygon points="12 2 2 7 12 12 22 7 12 2" />
            <polyline points="2 17 12 22 22 17" />
            <polyline points="2 12 12 17 22 12" />
          </Icono>
          <span className="barra-texto">Capas</span>
          {snapActivo && <span className="fab-punto" />}
        </button>
      </div>
    </nav>
  );
}
