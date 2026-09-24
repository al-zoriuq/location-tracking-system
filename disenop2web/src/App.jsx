import "./App.css";
import { useState, useEffect, useRef, useMemo, useCallback } from "react";
import { MapContainer, TileLayer, Marker, Polyline, ZoomControl, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import CapaLugar from "./components/CapaLugar";
import CentradoAutomatico from "./components/CentradoAutomatico";
import EstadisticasRuta from "./components/EstadisticasRuta";
import FiltroFechas from "./components/FiltroFechas";
import MarcadorActual from "./components/MarcadorActual";
import MarcadoresParada from "./components/MarcadoresParada";
import ModoLugar from "./components/ModoLugar";
import SelectorRutas from "./components/SelectorRutas";
import { pedirJSON } from "./utils/api";
import { calcularEstadisticas } from "./utils/estadisticas";
import { MARGEN_PASO_MS, desplazarTexto, tramoEntre } from "./utils/lugar";
import { centroParaZonaLibre, moverProgramaticamente, rellenoZonaLibre } from "./utils/mapa";
import { detectarParadas } from "./utils/paradas";
import { formatearFecha, formatearHora, parsearFechaBogota } from "./utils/tiempo";
import { separarEnViajes, velocidadEstimada } from "./utils/viajes";

const INTERVALO_MS = 10000;
const PAUSA_CENTRADO_MS = 15000; // auto-centering pause after a user drag/zoom
const CENTRO_BARRANQUILLA = [10.9878, -74.7889];

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
// never on a periodic refresh. It frames the area NOT covered by the panels
// and marks the move as programmatic (it must not pause auto-centering).
function AjustarVista({ puntos }) {
  const map = useMap();
  const yaAjustado = useRef(false);

  useEffect(() => {
    if (yaAjustado.current) return;

    if (puntos.length > 1) {
      moverProgramaticamente(map, () => map.fitBounds(puntos, rellenoZonaLibre(map)));
      yaAjustado.current = true;
    } else if (puntos.length === 1) {
      moverProgramaticamente(map, () =>
        map.setView(centroParaZonaLibre(map, puntos[0], 15), 15)
      );
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

  // Entrega 2 ("¿Cuándo pasó por aquí?") is an overlay on top of the state
  // above: it never changes rango or the pinned trip, so leaving it brings
  // back exactly what was on screen before.
  const [modoLugar, setModoLugar] = useState(false);
  const [lugar, setLugar] = useState(null); // {lat, lon}
  const [radioLugar, setRadioLugar] = useState(100);
  // Answer tagged with the query key that produced it: {clave, datos, error}
  const [resultadoLugar, setResultadoLugar] = useState(null);
  const [pasoSeleccionado, setPasoSeleccionado] = useState(null);
  const [rutaPaso, setRutaPaso] = useState(null); // trips around the selected pass
  const [errorPaso, setErrorPaso] = useState(null);
  // Increments on every pass request, so a slow answer for an older click is ignored
  const pedidoPasoRef = useRef(0);

  // Auto-centering on the live position (toggle + 15 s pause after the user
  // drags or zooms). ahoraTick only drives the "pausado (N s)" countdown.
  const [centradoActivo, setCentradoActivo] = useState(true);
  const [pausaHasta, setPausaHasta] = useState(null);
  const [ahoraTick, setAhoraTick] = useState(0);
  // Phones only: fold the controls column to free the map
  const [panelesVisibles, setPanelesVisibles] = useState(true);

  // Stable identity: CentradoAutomatico subscribes to map events with it
  const pausarCentrado = useCallback(() => {
    const ahora = Date.now();
    setPausaHasta(ahora + PAUSA_CENTRADO_MS);
    setAhoraTick(ahora);
  }, []);

  useEffect(() => {
    if (pausaHasta === null) return;
    const tic = setInterval(() => setAhoraTick(Date.now()), 1000);
    const fin = setTimeout(() => setPausaHasta(null), Math.max(0, pausaHasta - Date.now()));
    return () => {
      clearInterval(tic);
      clearTimeout(fin);
    };
  }, [pausaHasta]);

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

  // Query of Entrega 2 as a string key: the effect re-runs only when some
  // input really changes, and "loading" is simply "the stored answer belongs
  // to another key" (no extra state to keep in sync).
  const claveLugar =
    modoLugar && lugar
      ? JSON.stringify({
          lat: lugar.lat.toFixed(6),
          lon: lugar.lon.toFixed(6),
          radio: radioLugar,
          desde: rango?.desde,
          hasta: rango?.hasta,
          device_id: deviceId,
        })
      : null;

  useEffect(() => {
    if (!claveLugar) return;
    let activo = true;
    pedirJSON("pasos-por-lugar", JSON.parse(claveLugar))
      .then((datos) => {
        if (activo) setResultadoLugar({ clave: claveLugar, datos, error: null });
      })
      .catch((error) => {
        if (activo) setResultadoLugar({ clave: claveLugar, datos: null, error: error.message });
      });
    return () => {
      activo = false;
    };
  }, [claveLugar]);

  const resultadoVigente = resultadoLugar?.clave === claveLugar ? resultadoLugar : null;
  const cargandoLugar = claveLugar !== null && resultadoVigente === null;

  function limpiarPaso() {
    pedidoPasoRef.current += 1;
    setPasoSeleccionado(null);
    setRutaPaso(null);
    setErrorPaso(null);
  }

  function fijarLugar(nuevoLugar) {
    limpiarPaso();
    setLugar(nuevoLugar);
  }

  function cambiarRadio(radio) {
    limpiarPaso();
    setRadioLugar(radio);
  }

  function salirModoLugar() {
    limpiarPaso();
    setModoLugar(false);
    setLugar(null);
    setResultadoLugar(null);
  }

  // Loads the history from 10 min before the entry to 10 min after the exit
  async function seleccionarPaso(paso) {
    const pedido = ++pedidoPasoRef.current;
    setPasoSeleccionado(paso);
    setRutaPaso(null);
    setErrorPaso(null);
    try {
      const data = await pedirJSON("historial-ubicaciones", {
        device_id: deviceId,
        desde: desplazarTexto(paso.entrada, -MARGEN_PASO_MS),
        hasta: desplazarTexto(paso.salida, MARGEN_PASO_MS),
      });
      if (pedido === pedidoPasoRef.current) setRutaPaso(separarEnViajes(data));
    } catch (error) {
      if (pedido === pedidoPasoRef.current) {
        setRutaPaso([]);
        setErrorPaso(error.message);
      }
    }
  }

  function aplicarRango(nuevoRango) {
    limpiarPaso();
    fijarViaje(null);
    setAviso(null);
    setViajes([]);
    setHistorialCargado(false);
    setRango(nuevoRango);
  }

  function verEnVivo() {
    limpiarPaso();
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

  // Following the vehicle only makes sense while showing where it is now:
  // live mode, not choosing a place, and not looking at an older pinned trip.
  const centradoAplicable =
    mostrarActual && !modoLugar && (viajeFijadoId === null || viajeEnCurso);
  const centradoPausado = pausaHasta !== null;
  const segundosPausa = centradoPausado
    ? Math.max(0, Math.ceil((pausaHasta - ahoraTick) / 1000))
    : 0;

  // Selected pass (Entrega 2): its surrounding route and the stretch inside the circle
  const puntosPaso = useMemo(() => (rutaPaso ? rutaPaso.flatMap((v) => v.puntos) : []), [rutaPaso]);
  const lineasPaso = useMemo(
    () => (rutaPaso ? rutaPaso.map((v) => v.puntos.map((p) => [p.lat, p.lon])) : []),
    [rutaPaso]
  );
  const tramoResaltado = useMemo(
    () =>
      pasoSeleccionado && puntosPaso.length
        ? tramoEntre(
            puntosPaso,
            parsearFechaBogota(pasoSeleccionado.entrada),
            parsearFechaBogota(pasoSeleccionado.salida)
          )
        : [],
    [pasoSeleccionado, puntosPaso]
  );

  // Idea A: statistics of the route on screen (selected trip, or the trips
  // around the selected pass in place mode)
  const estadisticas = useMemo(() => {
    if (modoLugar) {
      return rutaPaso?.length ? calcularEstadisticas(rutaPaso.map((v) => v.puntos)) : null;
    }
    return viajeSeleccionado ? calcularEstadisticas([viajeSeleccionado.puntos]) : null;
  }, [modoLugar, rutaPaso, viajeSeleccionado]);

  // Idea C: stops (>= 5 min within 50 m) of the same route
  const paradas = useMemo(() => {
    const tramos = modoLugar
      ? (rutaPaso ?? []).map((v) => v.puntos)
      : viajeSeleccionado
        ? [viajeSeleccionado.puntos]
        : [];
    return tramos.flatMap(detectarParadas);
  }, [modoLugar, rutaPaso, viajeSeleccionado]);

  // What the map frames, and when: a new key re-frames (see AjustarVista).
  // In place mode, clicking the map to choose the place must NOT move it,
  // so only a loaded pass route is framed.
  let puntosVista;
  let claveVista;
  if (modoLugar) {
    puntosVista = lineasPaso.flat();
    claveVista = `lugar|${pasoSeleccionado?.entrada ?? "-"}|${rutaPaso ? "listo" : "cargando"}`;
  } else {
    puntosVista = ruta.length ? ruta : mostrarActual ? [posicionActual] : [];
    claveVista = `${rango ? `${rango.desde}|${rango.hasta}` : "vivo"}|${viajeSeleccionado?.id ?? "ninguno"}`;
  }

  const puntosLista = modoLugar
    ? [...puntosPaso].reverse()
    : viajeSeleccionado
      ? [...viajeSeleccionado.puntos].reverse()
      : [];

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

            {!modoLugar && ruta.length > 1 && (
              <Polyline
                positions={ruta}
                pathOptions={{ className: "ruta-linea", weight: 3, opacity: 0.8 }}
              />
            )}

            {!modoLugar && ruta.length > 1 && <Marker position={ruta[0]} icon={iconoInicio} />}

            {!modoLugar && mostrarFin && (
              <Marker position={ruta[ruta.length - 1]} icon={iconoFin} />
            )}

            <MarcadoresParada paradas={paradas} />

            <CapaLugar
              activo={modoLugar}
              lugar={lugar}
              radio={radioLugar}
              onFijarLugar={fijarLugar}
              rutaPaso={lineasPaso}
              tramoResaltado={tramoResaltado}
            />

            {mostrarActual && (
              <MarcadorActual
                posicion={posicionActual}
                fecha={fechaGPS}
                velocidadKmh={velocidadEstimada(location, ultimoViaje)}
              />
            )}

            <CentradoAutomatico
              lat={posicionActual?.[0] ?? null}
              lon={posicionActual?.[1] ?? null}
              activo={centradoActivo && centradoAplicable}
              pausado={centradoPausado}
              onPausar={pausarCentrado}
            />
          </MapContainer>

          <div className={`controles ${panelesVisibles ? "" : "controles-plegados"}`}>
            {/* Only visible on phones (CSS): folds the column to free the map */}
            <button
              type="button"
              className="boton boton-paneles"
              aria-expanded={panelesVisibles}
              onClick={() => setPanelesVisibles(!panelesVisibles)}
            >
              {panelesVisibles ? "Ocultar paneles ▴" : "Mostrar paneles ▾"}
            </button>

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
                <label className={`interruptor ${centradoAplicable ? "" : "interruptor-inactivo"}`}>
                  <input
                    type="checkbox"
                    checked={centradoActivo}
                    disabled={!centradoAplicable}
                    onChange={(e) => setCentradoActivo(e.target.checked)}
                  />
                  <span>Centrar en el vehículo</span>
                  {!centradoAplicable && <span className="interruptor-estado">(solo en vivo)</span>}
                  {centradoAplicable && centradoActivo && centradoPausado && (
                    <span className="interruptor-estado">pausado ({segundosPausa} s)</span>
                  )}
                </label>
              </div>
            )}

            <FiltroFechas
              rango={rango}
              onAplicar={aplicarRango}
              onVerEnVivo={verEnVivo}
              puedeVolverEnVivo={!enVivo || viajeFijadoId !== null}
            />

            {!modoLugar && (
              <div className="card">
                <button
                  type="button"
                  className="boton boton-primario boton-ancho"
                  onClick={() => setModoLugar(true)}
                >
                  ¿Cuándo pasó por aquí?
                </button>
              </div>
            )}

            {modoLugar && (
              <ModoLugar
                lugar={lugar}
                radio={radioLugar}
                onCambiarRadio={cambiarRadio}
                resultado={resultadoVigente?.datos ?? null}
                cargando={cargandoLugar}
                error={resultadoVigente?.error ?? errorPaso}
                hayRango={rango !== null}
                pasoSeleccionado={pasoSeleccionado}
                onSeleccionarPaso={seleccionarPaso}
                onSalir={salirModoLugar}
              />
            )}

            {!modoLugar && viajes.length > 0 && (
              <SelectorRutas
                viajes={viajes}
                seleccionadoId={viajeSeleccionado?.id ?? null}
                fijado={viajeFijadoId !== null}
                enVivo={enVivo}
                onSeleccionar={seleccionarViaje}
              />
            )}

            <EstadisticasRuta
              titulo={modoLugar ? "Recorrido del paso (±10 min)" : "Estadísticas de la ruta"}
              estadisticas={estadisticas}
            />

            {!modoLugar && (aviso || errorHistorial || errorUbicacionVisible || mensajeVacio ||
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

            {modoLugar && lugar && (
              <div className="card legend">
                <div className="legend-item">
                  <span className="legend-dot lugar"></span> Lugar ({radioLugar} m)
                </div>
                {tramoResaltado.length > 1 && (
                  <div className="legend-item">
                    <span className="legend-line"></span> Tramo dentro del círculo
                  </div>
                )}
                {paradas.length > 0 && (
                  <div className="legend-item">
                    <span className="legend-parada">⏸</span> Parada (≥ 5 min)
                  </div>
                )}
              </div>
            )}

            {!modoLugar && (ruta.length > 1 || mostrarActual) && (
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
                {paradas.length > 0 && (
                  <div className="legend-item">
                    <span className="legend-parada">⏸</span> Parada (≥ 5 min)
                  </div>
                )}
              </div>
            )}
          </div>
        </div>

        <aside className="sidebar">
          <p className="sidebar-title">
            {modoLugar ? "Puntos del paso" : "Puntos de la ruta"} ({puntosLista.length})
          </p>
          <div className="sidebar-list">
            {puntosLista.map((punto, index) => {
              const esInicio = index === puntosLista.length - 1;
              const esFinal = index === 0;
              const claseFinal = viajeEnCurso && !modoLugar ? "current" : "end";
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
