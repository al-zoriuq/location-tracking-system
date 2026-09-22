import "./App.css";
import { useState, useEffect, useRef, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// All GPS timestamps are stored as Barranquilla wall-clock time (no timezone
// in the database), so both parsing and display are pinned to this zone.
const ZONA = "America/Bogota";
const DESFASE_ZONA = "-05:00";
const OPCIONES_ZONA = { timeZone: ZONA };
const OPCIONES_HORA_CORTA = { timeZone: ZONA, hour: "2-digit", minute: "2-digit" };

const iconoActual = L.divIcon({
  className: "",
  html: '<div class="marker-current"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

const iconoInicio = L.divIcon({
  className: "",
  html: '<div class="marker-start"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

// End of a past route: same size as the start marker, different color, so a
// finished trip reads start -> end at a glance.
const iconoFin = L.divIcon({
  className: "",
  html: '<div class="marker-end"></div>',
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

// A "trip" is considered finished if this much time passes with no new GPS
// reading. The next reading after that gap starts a brand-new trip.
const UMBRAL_NUEVA_RUTA_MS = 60 * 60 * 1000; // 1 hour
const UMBRAL_NUEVA_RUTA_METROS = 1000; // 1 km
const RADIO_TIERRA_M = 6371000;
// Jumps implying more than this are treated as GPS glitches, not real travel
const VELOCIDAD_MAXIMA_KMH = 180;

// OSRM rejects very long coordinate lists, so the trip is matched in chunks.
const OSRM_MAX_PUNTOS = 100;
const OSRM_RADIO_M = 30;

// Haversine formula: straight-line distance in meters between two GPS
// coordinates, accounting for the Earth's curvature.
function calcularDistanciaMetros(lat1, lon1, lat2, lon2) {
  const toRad = (grados) => (grados * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return RADIO_TIERRA_M * c;
}

// Sends the raw GPS points to OSRM's map matching service and gets back the
// same trip snapped onto the actual road network. The original coordinates
// are never modified: this only affects the drawn line.
async function ajustarACarretera(puntos) {
  const tramos = [];
  // Chunks overlap by one point so the snapped line has no visible seams.
  for (let i = 0; i < puntos.length; i += OSRM_MAX_PUNTOS - 1) {
    const tramo = puntos.slice(i, i + OSRM_MAX_PUNTOS);
    if (tramo.length > 1) tramos.push(tramo);
  }

  const resultados = await Promise.all(
    tramos.map(async (tramo) => {
      const coords = tramo.map(([lat, lon]) => `${lon},${lat}`).join(";");
      const radios = tramo.map(() => OSRM_RADIO_M).join(";");
      const url =
        `https://router.project-osrm.org/match/v1/driving/${coords}` +
        `?geometries=geojson&overview=full&tidy=true&radiuses=${radios}`;

      const respuesta = await fetch(url);
      if (!respuesta.ok) return tramo;

      const datos = await respuesta.json();
      if (datos.code !== "Ok" || !datos.matchings || datos.matchings.length === 0) {
        return tramo;
      }

      return datos.matchings.flatMap((m) =>
        m.geometry.coordinates.map(([lon, lat]) => [lat, lon])
      );
    })
  );

  return resultados.flat();
}

function AjustarVista({ puntos, resetKey }) {
  const map = useMap();
  const yaAjustado = useRef(false);
  const resetKeyAnterior = useRef(resetKey);

  useEffect(() => {
    if (resetKey !== resetKeyAnterior.current) {
      yaAjustado.current = false;
      resetKeyAnterior.current = resetKey;
    }

    if (yaAjustado.current) return;

    if (puntos.length > 1) {
      map.fitBounds(puntos, { padding: [60, 60] });
      yaAjustado.current = true;
    } else if (puntos.length === 1) {
      map.setView(puntos[0], 13);
      yaAjustado.current = true;
    }
  }, [puntos, map, resetKey]);

  return null;
}

// Keeps the latest point centered while respecting whatever zoom level the
// user has chosen. Only active while the "Centrado" toggle is on.
function SeguirPunto({ lat, lon, activo }) {
  const map = useMap();

  useEffect(() => {
    if (!activo || lat == null || lon == null) return;
    map.setView([lat, lon], map.getZoom(), { animate: true });
  }, [lat, lon, activo, map]);

  return null;
}

function parsearFechaGPS(timestampTexto) {
  return new Date(timestampTexto.replace(" ", "T") + DESFASE_ZONA);
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

// Splits the full (chronological, oldest -> newest) history into separate
// "trips". A new trip starts whenever the gap between two consecutive
// readings exceeds UMBRAL_NUEVA_RUTA_MS.
function dividirEnRutas(historial) {
  if (historial.length === 0) return [];

  const rutas = [];
  let rutaActual = [historial[0]];

  for (let i = 1; i < historial.length; i++) {
    // Compared against the last accepted point, not historial[i - 1], so a
    // discarded point doesn't drag the next comparison with it.
    const anterior = rutaActual[rutaActual.length - 1];
    const actual = historial[i];

    const fechaAnterior = parsearFechaGPS(anterior.timestamp_gps);
    const fechaActual = parsearFechaGPS(actual.timestamp_gps);
    const diffMs = fechaActual - fechaAnterior;

    const distanciaM = calcularDistanciaMetros(
      Number(anterior.latitud),
      Number(anterior.longitud),
      Number(actual.latitud),
      Number(actual.longitud)
    );

    const diffHoras = diffMs / (1000 * 60 * 60);
    const velocidadKmh = diffHoras > 0 ? distanciaM / 1000 / diffHoras : Infinity;

    if (velocidadKmh > VELOCIDAD_MAXIMA_KMH) {
      // Physically impossible jump (GPS glitch): left out of the drawn
      // route, though the point still exists in the database.
      continue;
    }

    if (diffMs > UMBRAL_NUEVA_RUTA_MS || distanciaM > UMBRAL_NUEVA_RUTA_METROS) {
      rutas.push(rutaActual);
      rutaActual = [actual];
    } else {
      rutaActual.push(actual);
    }
  }

  rutas.push(rutaActual);
  return rutas;
}

// Shared scroll/keyboard/drag behaviour for the wheel pickers below.
const ALTO_ITEM = 34;

function useRueda(indice, total, onIndice) {
  const ref = useRef(null);

  useEffect(() => {
    if (ref.current) ref.current.scrollTop = indice * ALTO_ITEM;
  }, [indice]);

  const alHacerScroll = () => {
    if (!ref.current) return;
    clearTimeout(ref.current._timer);
    ref.current._timer = setTimeout(() => {
      if (!ref.current) return;
      const i = Math.round(ref.current.scrollTop / ALTO_ITEM);
      const acotado = Math.max(0, Math.min(total - 1, i));
      if (acotado !== indice) onIndice(acotado);
    }, 120);
  };

  // Arrow keys move one row at a time when the wheel has focus
  const alPresionarTecla = (e) => {
    if (e.key === "ArrowUp") {
      e.preventDefault();
      if (indice > 0) onIndice(indice - 1);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      if (indice < total - 1) onIndice(indice + 1);
    }
  };

  // Click-and-drag to scroll, matching the touch behaviour on mobile
  const alPresionarMouse = (e) => {
    const el = ref.current;
    if (!el) return;
    e.preventDefault();
    const yInicial = e.clientY;
    const scrollInicial = el.scrollTop;
    el.style.scrollSnapType = "none";

    const mover = (ev) => {
      el.scrollTop = scrollInicial - (ev.clientY - yInicial);
    };

    const soltar = () => {
      el.style.scrollSnapType = "y mandatory";
      const i = Math.round(el.scrollTop / ALTO_ITEM);
      const acotado = Math.max(0, Math.min(total - 1, i));
      onIndice(acotado);
      el.scrollTop = acotado * ALTO_ITEM;
      window.removeEventListener("mousemove", mover);
      window.removeEventListener("mouseup", soltar);
    };

    window.addEventListener("mousemove", mover);
    window.addEventListener("mouseup", soltar);
  };

  return { ref, alHacerScroll, alPresionarTecla, alPresionarMouse };
}

// Numeric wheel: min..max inclusive (e.g. 1-12 for hours, 0-59 for minutes)
function RuedaNumeros({ min = 0, max, valor, onChange }) {
  const valores = [];
  for (let i = min; i <= max; i++) valores.push(i);

  const indice = valor - min;
  const { ref, alHacerScroll, alPresionarTecla, alPresionarMouse } = useRueda(
    indice,
    valores.length,
    (i) => onChange(valores[i])
  );

  return (
    <div
      className="rueda"
      ref={ref}
      tabIndex={0}
      onScroll={alHacerScroll}
      onKeyDown={alPresionarTecla}
      onMouseDown={alPresionarMouse}
    >
      <div className="rueda-espaciador" />
      {valores.map((n) => (
        <div
          key={n}
          className={`rueda-item ${n === valor ? "activo" : ""}`}
          onClick={() => onChange(n)}
        >
          {String(n).padStart(2, "0")}
        </div>
      ))}
      <div className="rueda-espaciador" />
    </div>
  );
}

// Text wheel: same behaviour, arbitrary string options (AM / PM)
function RuedaOpciones({ opciones, valor, onChange }) {
  const indice = opciones.indexOf(valor);
  const { ref, alHacerScroll, alPresionarTecla, alPresionarMouse } = useRueda(
    indice,
    opciones.length,
    (i) => onChange(opciones[i])
  );

  return (
    <div
      className="rueda rueda-texto"
      ref={ref}
      tabIndex={0}
      onScroll={alHacerScroll}
      onKeyDown={alPresionarTecla}
      onMouseDown={alPresionarMouse}
    >
      <div className="rueda-espaciador" />
      {opciones.map((o) => (
        <div
          key={o}
          className={`rueda-item ${o === valor ? "activo" : ""}`}
          onClick={() => onChange(o)}
        >
          {o}
        </div>
      ))}
      <div className="rueda-espaciador" />
    </div>
  );
}

function App() {
  const [location, setLocation] = useState(null);
  const [historial, setHistorial] = useState([]);

  // null = "follow the most recent trip live". A number = pinned to that
  // specific trip index, regardless of new data arriving later.
  const [indiceRuta, setIndiceRuta] = useState(null);

  // Map view toggles
  const [centradoActivo, setCentradoActivo] = useState(false);
  const [snapActivo, setSnapActivo] = useState(false);
  const [rutaAjustada, setRutaAjustada] = useState(null);
  const [snapCargando, setSnapCargando] = useState(false);
  const [capasAbierto, setCapasAbierto] = useState(false);

  // Date/time range filter state
  const hoy = new Date().toLocaleDateString("en-CA", OPCIONES_ZONA);
  const [filtroAbierto, setFiltroAbierto] = useState(false);
  const [fechaDesde, setFechaDesde] = useState(hoy);
  const [horaDesde, setHoraDesde] = useState(12);
  const [minDesde, setMinDesde] = useState(0);
  const [meridianoDesde, setMeridianoDesde] = useState("AM");
  const [fechaHasta, setFechaHasta] = useState(hoy);
  const [horaHasta, setHoraHasta] = useState(11);
  const [minHasta, setMinHasta] = useState(59);
  const [meridianoHasta, setMeridianoHasta] = useState("PM");
  // null = live mode (last 24h). {desde, hasta} = explicit range applied.
  const [rangoActivo, setRangoActivo] = useState(null);

  const fechaGPS = location ? parsearFechaGPS(location.timestamp_gps) : null;
  const estado = calcularEstado(fechaGPS);

  const rutas = useMemo(() => dividirEnRutas(historial), [historial]);

  const siguiendoActual = indiceRuta === null;
  const indiceMostrado = siguiendoActual ? rutas.length - 1 : indiceRuta;
  const puntosRutaMostrada = rutas[indiceMostrado] || [];

  const ruta = puntosRutaMostrada.map((punto) => [
    Number(punto.latitud),
    Number(punto.longitud),
  ]);

  const historialReciente = [...puntosRutaMostrada].reverse();

  const ultimoPunto = ruta.length > 0 ? ruta[ruta.length - 1] : null;

  // Primitive key so the snapping effect only refires on real route changes,
  // not on every render (array literals get a new identity each time).
  const claveRuta = ultimoPunto
    ? `${indiceMostrado}:${ruta.length}:${ultimoPunto[0]},${ultimoPunto[1]}`
    : "";

  useEffect(() => {
    if (!snapActivo || ruta.length < 2) {
      setRutaAjustada(null);
      setSnapCargando(false);
      return;
    }

    let cancelado = false;
    setSnapCargando(true);

    ajustarACarretera(ruta)
      .then((ajustada) => {
        if (!cancelado) setRutaAjustada(ajustada);
      })
      .catch((error) => {
        console.error("Error ajustando la ruta a carretera:", error);
        if (!cancelado) setRutaAjustada(null);
      })
      .finally(() => {
        if (!cancelado) setSnapCargando(false);
      });

    return () => {
      cancelado = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapActivo, claveRuta]);

  // Snapped line when available, raw GPS line otherwise.
  const rutaDibujada = snapActivo && rutaAjustada ? rutaAjustada : ruta;

  const etiquetaRuta = useMemo(() => {
    if (puntosRutaMostrada.length === 0) return "";

    const primero = parsearFechaGPS(puntosRutaMostrada[0].timestamp_gps);
    const ultimo = parsearFechaGPS(
      puntosRutaMostrada[puntosRutaMostrada.length - 1].timestamp_gps
    );

    const rango =
      puntosRutaMostrada.length > 1
        ? `${primero.toLocaleDateString("es-CO", OPCIONES_ZONA)}, ${primero.toLocaleTimeString(
            "es-CO",
            OPCIONES_HORA_CORTA
          )} - ${ultimo.toLocaleTimeString("es-CO", OPCIONES_HORA_CORTA)}`
        : `${primero.toLocaleDateString("es-CO", OPCIONES_ZONA)}, ${primero.toLocaleTimeString(
            "es-CO",
            OPCIONES_HORA_CORTA
          )}`;

    return `Ruta ${indiceMostrado + 1} de ${rutas.length} · ${rango}`;
  }, [puntosRutaMostrada, indiceMostrado, rutas.length]);

  const verRutaAnterior = () => {
    setIndiceRuta(Math.max(0, indiceMostrado - 1));
  };

  const volverARutaActual = () => {
    setIndiceRuta(null);
  };

  const dosDigitos = (n) => String(n).padStart(2, "0");

  // Convert 12-hour + AM/PM into the 24-hour format PostgreSQL expects
  const a24Horas = (hora12, meridiano) => {
    if (meridiano === "AM") return hora12 === 12 ? 0 : hora12;
    return hora12 === 12 ? 12 : hora12 + 12;
  };

  const aplicarFiltro = () => {
    const h1 = a24Horas(horaDesde, meridianoDesde);
    const h2 = a24Horas(horaHasta, meridianoHasta);
    setRangoActivo({
      desde: `${fechaDesde} ${dosDigitos(h1)}:${dosDigitos(minDesde)}:00`,
      hasta: `${fechaHasta} ${dosDigitos(h2)}:${dosDigitos(minHasta)}:59`,
    });
    setIndiceRuta(null);
    setFiltroAbierto(false);
  };

  const quitarFiltro = () => {
    setRangoActivo(null);
    setIndiceRuta(null);
    setFiltroAbierto(false);
  };

  useEffect(() => {
    const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";
    document.title = `GPSLink - ${nombre}`;
  }, []);

  useEffect(() => {
    const obtenerUbicacion = async () => {
      try {
        const response = await fetch(import.meta.env.BASE_URL + "api/ultima-ubicacion");
        if (!response.ok) {
          setLocation(null);
          return;
        }
        const data = await response.json();
        setLocation(data);
      } catch (error) {
        console.error("Error obteniendo ubicación:", error);
        setLocation(null);
      }
    };

    const obtenerHistorial = async () => {
      try {
        let url = import.meta.env.BASE_URL + "api/historial-ubicaciones";
        if (rangoActivo) {
          url += `?desde=${encodeURIComponent(rangoActivo.desde)}&hasta=${encodeURIComponent(rangoActivo.hasta)}`;
        }
        const response = await fetch(url);
        if (!response.ok) {
          setHistorial([]);
          return;
        }
        const data = await response.json();
        setHistorial(Array.isArray(data) ? data : []);
      } catch (error) {
        console.error("Error obteniendo historial:", error);
        setHistorial([]);
      }
    };

    obtenerUbicacion();
    obtenerHistorial();

    // A fully past range can't receive new points, so stop polling the
    // history for it (the live marker keeps updating regardless).
    const rangoEsPasado =
      rangoActivo &&
      new Date(rangoActivo.hasta.replace(" ", "T") + DESFASE_ZONA) < new Date();

    const intervalo = setInterval(() => {
      obtenerUbicacion();
      if (!rangoEsPasado) obtenerHistorial();
    }, 10000);

    return () => clearInterval(intervalo);
  }, [rangoActivo]);

  const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";

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
        {location ? (
          <>
            <div className="panel">
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
                <span>{fechaGPS.toLocaleDateString("es-CO", OPCIONES_ZONA)}</span>
                <span>{fechaGPS.toLocaleTimeString("es-CO", OPCIONES_ZONA)}</span>
              </div>
              <p className="ip">IP: {location.ip_origen}</p>
            </div>

            {filtroAbierto ? (
              <div className="filtro-fecha">
                <div className="filtro-grupo">
                  <span className="filtro-label">Desde</span>
                  <input
                    type="date"
                    value={fechaDesde}
                    onChange={(e) => setFechaDesde(e.target.value)}
                  />
                  <div className="rueda-grupo">
                    <RuedaNumeros min={1} max={12} valor={horaDesde} onChange={setHoraDesde} />
                    <span className="rueda-separador">:</span>
                    <RuedaNumeros min={0} max={59} valor={minDesde} onChange={setMinDesde} />
                    <RuedaOpciones
                      opciones={["AM", "PM"]}
                      valor={meridianoDesde}
                      onChange={setMeridianoDesde}
                    />
                  </div>
                </div>

                <div className="filtro-grupo">
                  <span className="filtro-label">Hasta</span>
                  <input
                    type="date"
                    value={fechaHasta}
                    onChange={(e) => setFechaHasta(e.target.value)}
                  />
                  <div className="rueda-grupo">
                    <RuedaNumeros min={1} max={12} valor={horaHasta} onChange={setHoraHasta} />
                    <span className="rueda-separador">:</span>
                    <RuedaNumeros min={0} max={59} valor={minHasta} onChange={setMinHasta} />
                    <RuedaOpciones
                      opciones={["AM", "PM"]}
                      valor={meridianoHasta}
                      onChange={setMeridianoHasta}
                    />
                  </div>
                </div>

                <div className="filtro-acciones">
                  <button onClick={() => setFiltroAbierto(false)}>Cancelar</button>
                  {rangoActivo && <button onClick={quitarFiltro}>Ver en vivo</button>}
                  <button className="aplicar" onClick={aplicarFiltro}>
                    Aplicar
                  </button>
                </div>
              </div>
            ) : (
              <div
                style={{
                  position: "absolute",
                  top: "60px",
                  left: "50%",
                  transform: "translateX(-50%)",
                  zIndex: 1000,
                }}
              >
                <button className="filtro-toggle" onClick={() => setFiltroAbierto(true)}>
                  {rangoActivo ? "Rango: personalizado" : "Filtrar por fecha"}
                </button>
              </div>
            )}

            <div className="controles-mapa fab-columna">
              {capasAbierto && (
                <div className="capas-menu">
                  <p className="capas-titulo">Opciones del mapa</p>
                  <label className="capas-opcion">
                    <span>
                      Ajustar a vías
                      {snapCargando && <em> · ajustando…</em>}
                    </span>
                    <input
                      type="checkbox"
                      checked={snapActivo}
                      onChange={() => setSnapActivo(!snapActivo)}
                    />
                    <span className="interruptor" />
                  </label>
                </div>
              )}

              <button
                className={`fab ${capasAbierto ? "activo" : ""}`}
                onClick={() => setCapasAbierto(!capasAbierto)}
                aria-label="Opciones del mapa"
                title="Opciones del mapa"
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <polygon points="12 2 2 7 12 12 22 7 12 2" />
                  <polyline points="2 17 12 22 22 17" />
                  <polyline points="2 12 12 17 22 12" />
                </svg>
                {snapActivo && <span className="fab-punto" />}
              </button>

              <button
                className={`fab ${centradoActivo ? "activo" : ""}`}
                onClick={() => setCentradoActivo(!centradoActivo)}
                aria-label="Seguir punto actual"
                title="Mantiene el punto actual en el centro sin cambiar tu zoom"
              >
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
                  stroke="currentColor" strokeWidth="2" strokeLinecap="round">
                  <circle cx="12" cy="12" r="7" />
                  <circle cx="12" cy="12" r="2.5" fill={centradoActivo ? "currentColor" : "none"} />
                  <line x1="12" y1="1" x2="12" y2="4" />
                  <line x1="12" y1="20" x2="12" y2="23" />
                  <line x1="1" y1="12" x2="4" y2="12" />
                  <line x1="20" y1="12" x2="23" y2="12" />
                </svg>
              </button>
            </div>

            {ruta.length > 0 && (
              <div
                style={{
                  position: "absolute",
                  top: "12px",
                  left: "50%",
                  transform: "translateX(-50%)",
                  zIndex: 1000,
                  display: "flex",
                  alignItems: "center",
                  gap: "10px",
                  backgroundColor: "rgba(20, 16, 32, 0.85)",
                  padding: "8px 14px",
                  borderRadius: "10px",
                  fontFamily: "inherit",
                  fontSize: "13px",
                  color: "#e5dcff",
                  backdropFilter: "blur(4px)",
                }}
              >
                <button
                  onClick={verRutaAnterior}
                  disabled={indiceMostrado === 0}
                  style={{
                    background: "none",
                    border: "1px solid #7c3aed",
                    color: indiceMostrado === 0 ? "#5a5568" : "#e5dcff",
                    borderRadius: "6px",
                    padding: "4px 10px",
                    cursor: indiceMostrado === 0 ? "default" : "pointer",
                    opacity: indiceMostrado === 0 ? 0.5 : 1,
                  }}
                >
                  ← Ruta anterior
                </button>

                <span style={{ whiteSpace: "nowrap" }}>{etiquetaRuta}</span>

                {!siguiendoActual && (
                  <button
                    onClick={volverARutaActual}
                    style={{
                      background: "#7c3aed",
                      border: "none",
                      color: "white",
                      borderRadius: "6px",
                      padding: "4px 10px",
                      cursor: "pointer",
                    }}
                  >
                    Ruta actual →
                  </button>
                )}
              </div>
            )}

            {ruta.length > 1 && (
              <div className="legend">
                <div className="legend-item">
                  <span className="legend-dot start"></span> Inicio
                </div>
                <div className="legend-item">
                  <span className={`legend-dot ${siguiendoActual ? "current" : "end"}`}></span>
                  {siguiendoActual ? " Actual" : " Fin de ruta"}
                </div>
              </div>
            )}

            <MapContainer
              center={[Number(location.latitud), Number(location.longitud)]}
              zoom={13}
              scrollWheelZoom={true}
              className="map"
            >
              <TileLayer
                attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
                url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
              />

              <AjustarVista puntos={ruta} resetKey={indiceMostrado} />

              <SeguirPunto
                lat={ultimoPunto ? ultimoPunto[0] : null}
                lon={ultimoPunto ? ultimoPunto[1] : null}
                activo={centradoActivo}
              />

              {rutaDibujada.length > 1 && (
                <Polyline positions={rutaDibujada} color="#b37feb" weight={3} opacity={0.75} />
              )}

              {ruta.length > 1 && <Marker position={ruta[0]} icon={iconoInicio} />}

              {ruta.length > 0 && (
                <Marker
                  position={ruta[ruta.length - 1]}
                  icon={siguiendoActual ? iconoActual : iconoFin}
                />
              )}
            </MapContainer>

            <aside className="sidebar">
              <p className="sidebar-title">
                Historial de puntos ({historialReciente.length})
              </p>
              <div className="sidebar-list">
                {historialReciente.map((punto, index) => {
                  const fecha = parsearFechaGPS(punto.timestamp_gps);
                  const esInicio = index === historialReciente.length - 1;
                  const esActual = index === 0;
                  const claseFinal = siguiendoActual ? "current" : "end";
                  return (
                    <div className="sidebar-item" key={index}>
                      <div className="sidebar-item-header">
                        <span
                          className={`legend-dot ${esInicio ? "start" : esActual ? claseFinal : ""}`}
                        ></span>
                        <span className="sidebar-item-time">
                          {fecha.toLocaleDateString("es-CO", OPCIONES_ZONA)} ·{" "}
                          {fecha.toLocaleTimeString("es-CO", OPCIONES_ZONA)}
                        </span>
                      </div>
                      <div className="coord-row small">
                        <span className="coord-label">Lat</span>
                        <span>{Number(punto.latitud).toFixed(4)}</span>
                      </div>
                      <div className="coord-row small">
                        <span className="coord-label">Lon</span>
                        <span>{Number(punto.longitud).toFixed(4)}</span>
                      </div>
                      <p className="sidebar-item-ip">IP: {punto.ip_origen}</p>
                    </div>
                  );
                })}
              </div>
            </aside>
          </>
        ) : (
          <p className="empty-state">Cargando ubicación...</p>
        )}
      </div>
    </div>
  );
}

export default App;
