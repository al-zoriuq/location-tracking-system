import { useEffect, useMemo, useRef } from "react";
import { Marker, Popup } from "react-leaflet";
import L from "leaflet";
import { formatoDiaCorto } from "./zona.js";
import { nombreSenal, estadoSenal, velocidadTexto, htmlSenal } from "./senales.js";

// Time WITH seconds: several signs can be seen within the same minute
const OPCIONES_HORA_SEG = { timeZone: "America/Bogota", hour: "2-digit", minute: "2-digit", second: "2-digit" };

// Wait for VolarA's flight (0.8 s) before opening the popup of a sign picked in
// the sidebar, so Leaflet's auto-pan does not fight the flight.
const ESPERA_VUELO_MS = 900;

function icono(d, elegida) {
  return L.divIcon({
    className: "",
    html: `<div class="marker-senal${elegida ? " elegida" : ""}">${htmlSenal(d)}</div>`,
    iconSize: [30, 30],
    iconAnchor: [15, 15], // centered on the spot where the sign was seen
    popupAnchor: [0, -14],
  });
}

function km(v) {
  return v == null ? "—" : `${Math.round(v)}`;
}

// One road-sign marker per detection of the route on screen.
// seleccionada: id picked in the sidebar list; its popup opens after the flight.
export default function MarcadoresSenal({ senales, seleccionada, margenSuperior }) {
  const iconos = useMemo(
    () => senales.map((d) => icono(d, d.id === seleccionada)),
    [senales, seleccionada]
  );
  const marcadores = useRef({});

  useEffect(() => {
    if (seleccionada == null) return;
    const espera = setTimeout(() => marcadores.current[seleccionada]?.openPopup(), ESPERA_VUELO_MS);
    return () => clearTimeout(espera);
  }, [seleccionada]);

  return senales.map((d, i) => {
    const estado = estadoSenal(d);
    const velocidad = velocidadTexto(d);
    return (
      <Marker
        key={d.id}
        position={[d.lat, d.lon]}
        icon={iconos[i]}
        // Exceeded limits on top of the rest when they overlap
        zIndexOffset={d.cumplimiento === "EXCEDE" ? 600 : 500}
        ref={(m) => { if (m) marcadores.current[d.id] = m; else delete marcadores.current[d.id]; }}
      >
        <Popup className="popup-oscuro" autoPanPaddingTopLeft={[16, margenSuperior]}>
          <div className="popup-senal">
            <p className="popup-senal-titulo">
              {nombreSenal(d)}
              <span className={`estado-senal ${estado.clave}`}>{estado.texto}</span>
            </p>
            <p className="popup-parada-fila">
              <span>Hora</span>{" "}
              <b>{formatoDiaCorto(d.fecha)} · {d.fecha.toLocaleTimeString("es-CO", OPCIONES_HORA_SEG)}</b>
            </p>
            <p className="popup-parada-fila">
              <span>Velocidad</span> <b>{velocidad ?? "Sin dato"}</b>
            </p>
            <p className="popup-parada-fila">
              <span>GPS / MPU</span> <b>{km(d.vel_gps)} / {km(d.vel_mpu)} km/h</b>
            </p>
            <p className="popup-parada-fila">
              <span>Confianza</span> <b>{Math.round(Number(d.confianza) * 100)} %</b>
            </p>
            {d.edad_posicion_s > 0 && (
              <p className="popup-senal-nota">
                La posición es de {d.edad_posicion_s} s antes de la detección: el lugar exacto
                puede estar un poco más adelante en la ruta.
              </p>
            )}
          </div>
        </Popup>
      </Marker>
    );
  });
}
