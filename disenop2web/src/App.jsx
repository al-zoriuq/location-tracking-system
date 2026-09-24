import "./App.css";
import { useState, useEffect, useRef, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Polyline, ZoomControl, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import FiltroFechas from "./components/FiltroFechas";
import SelectorRutas from "./components/SelectorRutas";
import { pedirJSON } from "./utils/api";
import { formatearFecha, formatearHora, parsearFechaBogota } from "./utils/tiempo";
import { separarEnViajes } from "./utils/viajes";

const INTERVALO_MS = 10000;
const CENTRO_BARRANQUILLA = [10.9878, -74.7889];

const iconoActual = L.divIcon({
  className: "",
  html: '<div class="marker-current"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

const iconoInicio = L.divIcon({
  className: "",
  html: '<div class="marker-start"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

const iconoFin = L.divIcon({
  className: "",
  html: '<div class="marker-end"></div>',
  iconSize: [14, 14],
  iconAnchor: [7, 7],
});

// Frames the map once when mounted. The parent gives it a key made of the
// mode and the trip id, so it re-frames only when the shown trip changes,
// never on a periodic refresh.
function AjustarVista({ puntos }) {
  const map = useMap();
  const yaAjustado = useRef(false);

  useEffect(() => {
    if (yaAjustado.current) return;

    if (puntos.length > 1) {
      map.fitBounds(puntos, { padding: [60, 60] });
      yaAjustado.current = true;
    } else if (puntos.length === 1) {
      map.setView(puntos[0], 15);
      yaAjustado.current = true;
    }
  }, [puntos, map]);

  return null;
}

function calcularEstado(fechaGPS) {
  if (!fechaGPS) {
    return { texto: "sin datos", tier: "old" };
  }

  const ahora = new Date();
  const diffMs = ahora - fechaGPS;
  const diffMin = Math.floor(diffMs / 60000);
  const diffHoras = Math.floor(diffMin / 60);
  const diffDias = Math.floor(diffHoras / 24);

  if (diffMin <= 2) {
    return { texto: "en línea", tier: "fresh" };
  }

  if (diffMin < 60) {
    return { texto: `hace ${diffMin} min`, tier: "medium" };
  }

  if (diffHoras < 24) {
    return { texto: `hace ${diffHoras} h`, tier: "old" };
  }

  return { texto: `hace ${diffDias} d`, tier: "old" };
}

function App() {
  const [location, setLocation] = useState(null);
  const [errorUbicacion, setErrorUbicacion] = useState(null);
  const [viajes, setViajes] = useState([]);
  const [historialCargado, setHistorialCargado] = useState(false);
  const [errorHistorial, setErrorHistorial] = useState(null);
  // null = live mode (last 24 h); otherwise {desde, hasta} in Bogota time
  const [rango, setRango] = useState(null);
  // Pinned trip id (timestamp of its first point); null = follow the latest
  const [viajeFijadoId, setViajeFijadoId] = useState(null);
  const [aviso, setAviso] = useState(null);

  // Mirror of viajeFijadoId readable from inside the polling callback, which
  // was created when the effect ran and would otherwise see a stale value.
  const fijadoRef = useRef(null);

  const deviceId = location?.device_id ?? null;
  const fechaGPS = location ? parsearFechaBogota(location.timestamp_gps) : null;
  const estado = calcularEstado(fechaGPS);

  const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";

  useEffect(() => {
    document.title = `GPSLink - ${nombre}`;
  }, [nombre]);

  function fijarViaje(id) {
    fijadoRef.current = id;
    setViajeFijadoId(id);
  }

  // Latest position: always polled (drives the status dot and live marker)
  useEffect(() => {
    let activo = true;

    const obtenerUbicacion = async () => {
      try {
        const data = await pedirJSON("ultima-ubicacion");
        if (!activo) return;
        setLocation(data);
        setErrorUbicacion(null);
      } catch (error) {
        if (!activo) return;
        if (error.status === 404) setLocation(null);
        setErrorUbicacion(error.message);
      }
    };

    obtenerUbicacion();
    const intervalo = setInterval(obtenerUbicacion, INTERVALO_MS);

    return () => {
      activo = false;
      clearInterval(intervalo);
    };
  }, []);

  // History: polled in live mode; fetched once for a date range, because a
  // range always ends in the past (Hasta is clamped to now), so no new points
  // can ever arrive in it.
  useEffect(() => {
    // Ignores answers that arrive after the mode or range changed
    let activo = true;

    const obtenerHistorial = async () => {
      try {
        const data = await pedirJSON("historial-ubicaciones", {
          device_id: deviceId,
          desde: rango?.desde,
          hasta: rango?.hasta,
        });
        if (!activo) return;

        const nuevos = separarEnViajes(data);
        if (fijadoRef.current && !nuevos.some((v) => v.id === fijadoRef.current)) {
          fijadoRef.current = null;
          setViajeFijadoId(null);
          setAviso("La ruta fijada ya no está en el periodo consultado. Se volvió al modo en vivo.");
        }
        setViajes(nuevos);
        setErrorHistorial(null);
      } catch (error) {
        if (activo) setErrorHistorial(error.message);
      } finally {
        if (activo) setHistorialCargado(true);
      }
    };

    obtenerHistorial();

    if (rango) {
      return () => {
        activo = false;
      };
    }

    const intervalo = setInterval(obtenerHistorial, INTERVALO_MS);
    return () => {
      activo = false;
      clearInterval(intervalo);
    };
  }, [rango, deviceId]);

  function aplicarRango(nuevoRango) {
    fijarViaje(null);
    setAviso(null);
    setViajes([]);
    setHistorialCargado(false);
    setRango(nuevoRango);
  }

  function verEnVivo() {
    fijarViaje(null);
    setAviso(null);
    if (rango) {
      setViajes([]);
      setHistorialCargado(false);
      setRango(null);
    }
  }

  function seleccionarViaje(id) {
    fijarViaje(id);
    setAviso(null);
  }

  const enVivo = rango === null;
  const ultimoViaje = viajes.length ? viajes[viajes.length - 1] : null;
  const viajeSeleccionado = viajes.find((v) => v.id === viajeFijadoId) ?? ultimoViaje;
  // Only the latest trip in live mode can still be growing; any other trip
  // (or any trip of a finished range) ends in "Fin de ruta", never "Actual".
  const viajeEnCurso = enVivo && viajeSeleccionado !== null && viajeSeleccionado === ultimoViaje;

  const ruta = useMemo(
    () => (viajeSeleccionado ? viajeSeleccionado.puntos.map((p) => [p.lat, p.lon]) : []),
    [viajeSeleccionado]
  );

  const posicionActual = location ? [Number(location.latitud), Number(location.longitud)] : null;
  const mostrarActual = enVivo && posicionActual !== null;
  const mostrarFin = ruta.length > 1 && !viajeEnCurso;

  const puntosVista = ruta.length ? ruta : mostrarActual ? [posicionActual] : [];
  const claveVista = `${rango ? `${rango.desde}|${rango.hasta}` : "vivo"}|${viajeSeleccionado?.id ?? "ninguno"}`;

  const puntosLista = viajeSeleccionado ? [...viajeSeleccionado.puntos].reverse() : [];

  // Both endpoints fail the same way when the database is down: say it once
  const errorUbicacionVisible = errorUbicacion !== errorHistorial ? errorUbicacion : null;

  let mensajeVacio = null;
  if (!historialCargado) {
    mensajeVacio = "Cargando recorrido...";
  } else if (!errorHistorial && viajes.length === 0) {
    mensajeVacio = rango
      ? "No hay registros en ese rango de fechas."
      : "No hay registros en las últimas 24 horas.";
  }

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          GPSLink <span>· {nombre}</span>
        </div>
        <div className="status">
          <span className={`dot dot-${estado.tier}`}></span>
          {estado.texto}
        </div>
      </div>

      <div className="main">
        <div className="mapa-contenedor">
          <MapContainer
            center={posicionActual ?? CENTRO_BARRANQUILLA}
            zoom={13}
            scrollWheelZoom={true}
            zoomControl={false}
            className="map"
          >
            <TileLayer
              attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <ZoomControl position="topright" />

            <AjustarVista key={claveVista} puntos={puntosVista} />

            {ruta.length > 1 && (
              <Polyline
                positions={ruta}
                pathOptions={{ className: "ruta-linea", weight: 3, opacity: 0.8 }}
              />
            )}

            {ruta.length > 1 && <Marker position={ruta[0]} icon={iconoInicio} />}

            {mostrarFin && <Marker position={ruta[ruta.length - 1]} icon={iconoFin} />}

            {mostrarActual && <Marker position={posicionActual} icon={iconoActual} />}
          </MapContainer>

          <div className="controles">
            {location && (
              <div className="card panel">
                <p className="label">Última posición</p>
                <div className="coords">
                  <div className="coord-row">
                    <span className="coord-label">Lat</span>
                    <span>{Number(location.latitud).toFixed(4)}</span>
                  </div>
                  <div className="coord-row">
                    <span className="coord-label">Lon</span>
                    <span>{Number(location.longitud).toFixed(4)}</span>
                  </div>
                </div>
                <div className="meta">
                  <span>{formatearFecha(fechaGPS)}</span>
                  <span>{formatearHora(fechaGPS)}</span>
                </div>
                <p className="ip">IP: {location.ip_origen}</p>
              </div>
            )}

            <FiltroFechas
              rango={rango}
              onAplicar={aplicarRango}
              onVerEnVivo={verEnVivo}
              puedeVolverEnVivo={!enVivo || viajeFijadoId !== null}
            />

            {viajes.length > 0 && (
              <SelectorRutas
                viajes={viajes}
                seleccionadoId={viajeSeleccionado?.id ?? null}
                fijado={viajeFijadoId !== null}
                enVivo={enVivo}
                onSeleccionar={seleccionarViaje}
              />
            )}

            {(aviso || errorHistorial || errorUbicacionVisible || mensajeVacio ||
              viajeSeleccionado?.descartados > 0) && (
              <div className="card mensajes">
                {aviso && <p className="mensaje mensaje-aviso">{aviso}</p>}
                {errorHistorial && <p className="mensaje mensaje-error">{errorHistorial}</p>}
                {errorUbicacionVisible && (
                  <p className="mensaje mensaje-error">{errorUbicacionVisible}</p>
                )}
                {mensajeVacio && <p className="mensaje">{mensajeVacio}</p>}
                {viajeSeleccionado?.descartados > 0 && (
                  <p className="mensaje">
                    Se descartaron {viajeSeleccionado.descartados} punto(s) con saltos
                    imposibles (error de GPS).
                  </p>
                )}
              </div>
            )}

            {(ruta.length > 1 || mostrarActual) && (
              <div className="card legend">
                {ruta.length > 1 && (
                  <div className="legend-item">
                    <span className="legend-dot start"></span> Inicio
                  </div>
                )}
                {mostrarFin && (
                  <div className="legend-item">
                    <span className="legend-dot end"></span> Fin de ruta
                  </div>
                )}
                {mostrarActual && (
                  <div className="legend-item">
                    <span className="legend-dot current"></span> Actual
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <aside className="sidebar">
          <p className="sidebar-title">Puntos de la ruta ({puntosLista.length})</p>
          <div className="sidebar-list">
            {puntosLista.map((punto, index) => {
              const esInicio = index === puntosLista.length - 1;
              const esFinal = index === 0;
              const claseFinal = viajeEnCurso ? "current" : "end";
              return (
                <div className="sidebar-item" key={punto.timestamp_gps}>
                  <div className="sidebar-item-header">
                    <span
                      className={`legend-dot ${esInicio ? "start" : esFinal ? claseFinal : ""}`}
                    ></span>
                    <span className="sidebar-item-time">
                      {formatearFecha(punto.fecha)} · {formatearHora(punto.fecha)}
                    </span>
                  </div>
                  <div className="coord-row small">
                    <span className="coord-label">Lat</span>
                    <span>{punto.lat.toFixed(4)}</span>
                  </div>
                  <div className="coord-row small">
                    <span className="coord-label">Lon</span>
                    <span>{punto.lon.toFixed(4)}</span>
                  </div>
                  <p className="sidebar-item-ip">IP: {punto.ip_origen}</p>
                </div>
              );
            })}
          </div>
        </aside>
      </div>
    </div>
  );
}

export default App;
