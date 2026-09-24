import { memo } from "react";
import { formatearFecha, formatearHora } from "../utils/tiempo";

// Sidebar: points of the route on screen, newest first. Clicking one flies
// the map to it (idea E).
//
// memo(): re-renders only when its props change. The parent passes a
// memoized list and a useCallback handler, so frequent parent re-renders
// (e.g. the playback clock of idea B) do not re-render hundreds of items.
function ListaPuntos({ titulo, puntos, claseFinal, resaltado, onElegir }) {
  return (
    <aside className="sidebar">
      <p className="sidebar-title">
        {titulo} ({puntos.length})
      </p>
      <div className="sidebar-list">
        {puntos.map((punto, index) => {
          const esInicio = index === puntos.length - 1;
          const esFinal = index === 0;
          const activo = punto.timestamp_gps === resaltado;
          return (
            <button
              type="button"
              className={`sidebar-item ${activo ? "sidebar-item-activo" : ""}`}
              key={punto.timestamp_gps}
              onClick={() => onElegir(punto)}
            >
              <span className="sidebar-item-header">
                <span
                  className={`legend-dot ${esInicio ? "start" : esFinal ? claseFinal : ""}`}
                ></span>
                <span className="sidebar-item-time">
                  {formatearFecha(punto.fecha)} · {formatearHora(punto.fecha)}
                </span>
              </span>
              <span className="coord-row small">
                <span className="coord-label">Lat</span>
                <span>{punto.lat.toFixed(4)}</span>
              </span>
              <span className="coord-row small">
                <span className="coord-label">Lon</span>
                <span>{punto.lon.toFixed(4)}</span>
              </span>
              <span className="sidebar-item-ip">IP: {punto.ip_origen}</span>
            </button>
          );
        })}
      </div>
    </aside>
  );
}

export default memo(ListaPuntos);
