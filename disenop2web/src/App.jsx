import "./App.css";
import PopupPosicion from "./PopupPosicion.jsx";
import { velocidadActual } from "./velocidad.js";
import { calcularEstadisticas } from "./utils/estadisticas.js";
import MarcadoresParada from "./MarcadoresParada.jsx";
import { normalizarPunto } from "./utils/viajes.js";
import { detectarParadas } from "./utils/paradas.js";
import MarcadoresVisitas, { VolarA } from "./MarcadoresVisitas.jsx";
import PanelVisitas from "./PanelVisitas.jsx";
import { calcularVisitas } from "./visitas.js";
import SelectorRuta from "./SelectorRuta.jsx";
import { formatearHoraCorta } from "./utils/tiempo.js";
import Toasts from "./Toasts.jsx";
import { useToasts } from "./useToasts.js";
import { pedirJSON, describirFallo, ErrorApi, MENSAJE_RECUPERADA } from "./api.js";
import { useState, useEffect, useRef, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Polyline, Popup, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";

// All GPS timestamps are stored as Barranquilla wall-clock time (no timezone
// in the database), so both parsing and display are pinned to this zone.
const ZONA = "America/Bogota";
const DESFASE_ZONA = "-05:00";
const OPCIONES_ZONA = { timeZone: ZONA };
const OPCIONES_HORA_CORTA = { timeZone: ZONA, hour: "2-digit", minute: "2-digit" };

// Current position while data keeps arriving: a pulsing dot
const iconoActual = L.divIcon({
  className: "",
  html: '<div class="marker-current"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

// Current position when the last point is old (the device stopped reporting): still and dim
const iconoActualInactivo = L.divIcon({
  className: "",
  html: '<div class="marker-current inactivo"></div>',
  iconSize: [18, 18],
  iconAnchor: [9, 9],
});

// Start of a route: a play triangle on green. The shape, not only the colour,
// tells it apart from the end flag and from the current-position dot.
const iconoInicio = L.divIcon({
  className: "",
  html:
    '<div class="marker-start">' +
    '<svg viewBox="0 0 10 10" width="10" height="10" aria-hidden="true">' +
    '<path d="M2.6 1.3 L8.4 5 L2.6 8.7 Z" fill="currentColor"/></svg></div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
});

// End of a past route: same size as the start marker, different color, so a
// finished trip reads start -> end at a glance.
// End of a finished route: a flag on coral, so a trip reads start -> end at a glance.
const iconoFin = L.divIcon({
  className: "",
  html:
    '<div class="marker-end">' +
    '<svg viewBox="0 0 12 12" width="12" height="12" aria-hidden="true">' +
    '<path d="M3 1.5 V10.8" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" fill="none"/>' +
    '<path d="M3.6 2 H9.6 L8.1 4.4 L9.6 6.8 H3.6 Z" fill="currentColor"/></svg></div>',
  iconSize: [22, 22],
  iconAnchor: [11, 11],
});

// A "trip" is considered finished if this much time passes with no new GPS
// reading. The next reading after that gap starts a brand-new trip.
const UMBRAL_NUEVA_RUTA_MS = 60 * 60 * 1000; // 1 hour
const UMBRAL_NUEVA_RUTA_METROS = 1000; // 1 km

// The live view shows the last VENTANA_VIVO_H hours. History is requested with
// a wider margin so a route that began before that window is not cut at its edge.
const VENTANA_VIVO_H = 24;
const MARGEN_VIVO_H = 72;
// With a place filter and no dates, look back this far.
const VENTANA_LUGAR_H = 720; // 30 days
// The backend stores GPS timestamps as Bogota wall-clock time, without zone.
const DESFASE_BOGOTA = "-05:00";
// A range of at least this many hours completes the routes on its edges by
// default; the user can change it with the checkbox in the filter panel.
const UMBRAL_COMPLETAR_H = 24;
// When completing, the range is requested this many hours wider on each side.
const MARGEN_RANGO_H = 72;

// "YYYY-MM-DD HH:MM:SS" (Bogota wall clock, as the backend sends it) <-> ms
const aMsBogota = (texto) => new Date(texto.replace(" ", "T") + DESFASE_BOGOTA).getTime();
const aTextoBogota = (ms) =>
  new Date(ms).toLocaleString("sv-SE", { timeZone: "America/Bogota" });

// In live mode the history is loaded once and then topped up with only the new
// points. A full reload happens every RECARGA_COMPLETA_MS as a safety net.
const RECARGA_COMPLETA_MS = 5 * 60 * 1000;

// Merges freshly fetched rows into the history already on screen, keyed by
// timestamp_gps, and drops rows older than the cutoff. Returns the same array
// when nothing changed, so React does not recompute the routes.
function fusionarHistorial(previo, nuevos, corteMs) {
  const porHora = new Map(previo.map((f) => [f.timestamp_gps, f]));
  let cambio = false;
  for (const f of nuevos) {
    if (!porHora.has(f.timestamp_gps)) {
      porHora.set(f.timestamp_gps, f);
      cambio = true;
    }
  }
  const fusionado = [...porHora.values()].filter(
    (f) => aMsBogota(f.timestamp_gps) >= corteMs
  );
  if (!cambio && fusionado.length === previo.length) return previo;
  return fusionado.sort((a, b) =>
    a.timestamp_gps < b.timestamp_gps ? -1 : a.timestamp_gps > b.timestamp_gps ? 1 : 0
  );
}
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

// Numeric wheel: min..max inclusive (e.g. 1-12 for hours, 0-59 for minutes).
// Infinite: the list is repeated REPETICIONES times, and scrolling near the
// top/bottom copy silently jumps back to the middle copy (same value), so
// it feels like it wraps around (59 -> 00) with no visible limit.
const REPETICIONES_RUEDA = 9;

function RuedaNumeros({ min = 0, max, valor, onChange }) {
  const valores = [];
  for (let i = min; i <= max; i++) valores.push(i);
  const L = valores.length;
  const bloqueMedio = Math.floor(REPETICIONES_RUEDA / 2);

  const ref = useRef(null);
  const montado = useRef(false);

  const indiceActual = () => Math.round((ref.current?.scrollTop ?? 0) / ALTO_ITEM) + 1;
  const aModulo = (i) => ((i % L) + L) % L;

  // First render: start centered on the requested value, in the middle copy
  useEffect(() => {
    if (ref.current && !montado.current) {
      ref.current.scrollTop = (bloqueMedio * L + (valor - min) - 1) * ALTO_ITEM;
      montado.current = true;
    }
  }, []);

  // If the value is changed from outside after mount, move to the nearest
  // occurrence of it instead of resetting to the middle copy.
  useEffect(() => {
    if (!ref.current || !montado.current) return;
    const actual = indiceActual();
    const actualMod = aModulo(actual);
    const objetivoMod = valor - min;
    if (actualMod !== objetivoMod) {
      ref.current.scrollTop = (actual - 1 + (objetivoMod - actualMod)) * ALTO_ITEM;
    }
  }, [valor]);

  // Once settled, if we drifted into the first or last couple of copies,
  // jump back near the middle at the same logical value (invisible to the user).
  const recentrar = () => {
    const el = ref.current;
    if (!el) return;
    const i = indiceActual();
    const bloque = Math.floor(i / L);
    if (bloque <= 1 || bloque >= REPETICIONES_RUEDA - 2) {
      el.scrollTop = (bloqueMedio * L + aModulo(i) - 1) * ALTO_ITEM;
    }
  };

  const confirmarDesdeScroll = () => {
    const el = ref.current;
    if (!el) return;
    const mod = aModulo(indiceActual());
    const nuevo = valores[mod];
    if (nuevo !== valor) onChange(nuevo);
    recentrar();
  };

  const alHacerScroll = () => {
    if (!ref.current) return;
    clearTimeout(ref.current._timer);
    ref.current._timer = setTimeout(confirmarDesdeScroll, 120);
  };

  const alPresionarTecla = (e) => {
    const el = ref.current;
    if (!el) return;
    if (e.key === "ArrowUp") {
      e.preventDefault();
      el.scrollTop -= ALTO_ITEM;
      confirmarDesdeScroll();
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      el.scrollTop += ALTO_ITEM;
      confirmarDesdeScroll();
    }
  };

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
      el.scrollTop = i * ALTO_ITEM;
      confirmarDesdeScroll();
      window.removeEventListener("mousemove", mover);
      window.removeEventListener("mouseup", soltar);
    };

    window.addEventListener("mousemove", mover);
    window.addEventListener("mouseup", soltar);
  };

  const filas = [];
  for (let bloque = 0; bloque < REPETICIONES_RUEDA; bloque++) {
    for (let idx = 0; idx < L; idx++) {
      filas.push({ clave: `${bloque}-${idx}`, n: valores[idx] });
    }
  }

  return (
    <div
      className="rueda"
      ref={ref}
      tabIndex={0}
      onScroll={alHacerScroll}
      onKeyDown={alPresionarTecla}
      onMouseDown={alPresionarMouse}
    >
      {filas.map(({ clave, n }) => (
        <div
          key={clave}
          className={`rueda-item ${n === valor ? "activo" : ""}`}
          onClick={() => onChange(n)}
        >
          {String(n).padStart(2, "0")}
        </div>
      ))}
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

// Leaflet only re-measures its container on window resizes. The map zone can
// also change size on its own (compact mode, scrollbars, the history list), so
// re-measure whenever the zone changes; otherwise the new area stays gray.
function AjustarTamano({ zonaRef }) {
  const map = useMap();
  useEffect(() => {
    const el = zonaRef.current;
    if (!el) return undefined;
    let cuadro = 0;
    const observador = new ResizeObserver(() => {
      cancelAnimationFrame(cuadro);
      cuadro = requestAnimationFrame(() => map.invalidateSize({ animate: false }));
    });
    observador.observe(el);
    return () => {
      cancelAnimationFrame(cuadro);
      observador.disconnect();
    };
  }, [map, zonaRef]);
  return null;
}

// Asks the backend if the device has EVER been inside the place's bounding
// box (whole history, not just the loaded date range). Resolves {visitado}.
function consultarLugarVisitado(lugar) {
  const parametros = new URLSearchParams({
    lat_min: lugar.lat_min,
    lat_max: lugar.lat_max,
    lon_min: lugar.lon_min,
    lon_max: lugar.lon_max,
  });
  return pedirJSON(import.meta.env.BASE_URL + `api/lugar-visitado?${parametros}`);
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
  const [panelExpandido, setPanelExpandido] = useState(false);
  const [filtrosVisibles, setFiltrosVisibles] = useState(false);
  const [visitaSel, setVisitaSel] = useState(null);
  const [vueloA, setVueloA] = useState(null);
  const [margenSuperior, setMargenSuperior] = useState(0);
  const [paradasVisibles, setParadasVisibles] = useState(true);
  const [lugarSinHistorial, setLugarSinHistorial] = useState(null); // name of a place never visited
  const [sinResultadosLugar, setSinResultadosLugar] = useState(false);
  const [historialCargado, setHistorialCargado] = useState(false);
  // Guards against out-of-order answers when a place is picked twice quickly
  const eleccionActual = useRef(0);
  const { toasts, cerrar, mostrar, registrarFallo, registrarExito } = useToasts();

  // Date/time range filter state
  const hoy = new Date().toLocaleDateString("en-CA", OPCIONES_ZONA);
  // Default end of the range: right now (the server rejects future dates)
  const [ahoraH, ahoraM] = formatearHoraCorta(new Date()).split(":").map(Number);
  const [filtroAbierto, setFiltroAbierto] = useState(false);
  const [fechaDesde, setFechaDesde] = useState(hoy);
  const [horaDesde, setHoraDesde] = useState(12);
  const [minDesde, setMinDesde] = useState(0);
  const [meridianoDesde, setMeridianoDesde] = useState("AM");
  const [fechaHasta, setFechaHasta] = useState(hoy);
  const [horaHasta, setHoraHasta] = useState(ahoraH % 12 || 12);
  const [minHasta, setMinHasta] = useState(ahoraM);
  const [meridianoHasta, setMeridianoHasta] = useState(ahoraH >= 12 ? "PM" : "AM");
  // null = live mode (last 24h). {desde, hasta} = explicit range applied.
  const [rangoActivo, setRangoActivo] = useState(null);
  // null = automatic; true/false = the user's choice in the filter panel
  const [completarManual, setCompletarManual] = useState(null);

  // Location filter state
  const [busquedaLugar, setBusquedaLugar] = useState("");
  const [sugerenciasLugar, setSugerenciasLugar] = useState([]);
  const [buscandoLugar, setBuscandoLugar] = useState(false);
  const [lugarActivo, setLugarActivo] = useState(null); // {nombre, lat_min, lat_max, lon_min, lon_max}

  const fechaGPS = location ? parsearFechaGPS(location.timestamp_gps) : null;
  const estado = calcularEstado(fechaGPS);

  const todasLasRutas = useMemo(() => dividirEnRutas(historial), [historial]);

  // A route "matches" a place if any of its points falls inside that
  // place's bounding box (city/town box, or the small radius box built
  // around a single-point address).
  const rutas = useMemo(() => {
    let base = todasLasRutas;

    if (rangoActivo) {
      // Completing: keep whole routes that have a point inside the range.
      // Not completing: the points were requested for the exact range, so the
      // routes are already cut at its edges.
      if (rangoActivo.completar) {
        base = base.filter((puntos) =>
          puntos.some(
            (p) => p.timestamp_gps >= rangoActivo.desde && p.timestamp_gps <= rangoActivo.hasta
          )
        );
      }
    } else if (!lugarActivo) {
      // Live mode: keep the routes that still have a point inside the live
      // window, and show them complete (never cut at the window edge).
      const corte = Date.now() - VENTANA_VIVO_H * 3600 * 1000;
      base = base.filter(
        (puntos) => aMsBogota(puntos[puntos.length - 1].timestamp_gps) >= corte
      );
    }

    if (!lugarActivo) return base;

    // A route matches a place if any of its points falls inside the box.
    return base.filter((puntos) =>
      puntos.some((p) => {
        const lat = Number(p.latitud);
        const lon = Number(p.longitud);
        return (
          lat >= lugarActivo.lat_min &&
          lat <= lugarActivo.lat_max &&
          lon >= lugarActivo.lon_min &&
          lon <= lugarActivo.lon_max
        );
      })
    );
  }, [todasLasRutas, lugarActivo, rangoActivo]);

  const siguiendoActual = indiceRuta === null;
  const indiceMostrado = siguiendoActual ? rutas.length - 1 : indiceRuta;
  const puntosRutaMostrada = rutas[indiceMostrado] || [];

  // Stops of the route on screen: at least 5 min within 50 m (see utils/paradas.js)
  const puntosNorm = useMemo(() => puntosRutaMostrada.map(normalizarPunto), [puntosRutaMostrada]);
  const paradas = useMemo(() => detectarParadas(puntosNorm), [puntosNorm]);

  // Distance, duration and speeds of the route on screen (for the popup)
  const estadisticasRuta = useMemo(
    () => (puntosNorm.length > 1 ? calcularEstadisticas([puntosNorm]) : null),
    [puntosNorm]
  );

  // Live = following the newest route and its last point is under 2 minutes old
  const ultimaLectura = puntosNorm[puntosNorm.length - 1];
  const enVivo =
    siguiendoActual && Boolean(ultimaLectura) && Date.now() - ultimaLectura.fecha.getTime() <= 120000;
  // A speed only means something while the device is reporting
  const velocidadActualKmh = enVivo ? velocidadActual(puntosNorm) : null;

  // Keep the chosen route stable while the live window slides: it is
  // remembered by the timestamp of its first point, because its position in
  // the list changes when old routes fall out of the window.
  const idRutaElegida = useRef(null);
  useEffect(() => {
    idRutaElegida.current =
      indiceRuta === null ? null : (rutas[indiceRuta]?.[0]?.timestamp_gps ?? null);
  }, [indiceRuta]);
  useEffect(() => {
    const id = idRutaElegida.current;
    if (id === null) return;
    const nuevo = rutas.findIndex((r) => r[0].timestamp_gps === id);
    setIndiceRuta(nuevo === -1 || nuevo >= rutas.length - 1 ? null : nuevo);
  }, [rutas]);

  const ruta = puntosRutaMostrada.map((punto) => [
    Number(punto.latitud),
    Number(punto.longitud),
  ]);

  const historialReciente = [...puntosRutaMostrada].reverse();

  // The layout follows the real size of the map zone, not the device type:
  // a narrow or short zone switches to the compact overlays.
  const zonaRef = useRef(null);
  const [compacto, setCompacto] = useState(false);
  const [bajo, setBajo] = useState(false);
  const hayUbicacion = Boolean(location);
  useEffect(() => {
    const el = zonaRef.current;
    if (!el) return undefined;
    const medir = () => {
      setCompacto(el.clientWidth < 640 || el.clientHeight < 460);
      setBajo(el.clientHeight < 380);
    };
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(el);
    return () => observador.disconnect();
  }, [hayUbicacion]);

  useEffect(() => {
    if (busquedaLugar.trim().length < 3) {
      setSugerenciasLugar([]);
      setSinResultadosLugar(false);
      setBuscandoLugar(false);
      return undefined;
    }

    let cancelado = false;
    setBuscandoLugar(true);
    setSinResultadosLugar(false);
    const timer = setTimeout(async () => {
      try {
        const data = await pedirJSON(
          import.meta.env.BASE_URL + `api/buscar-lugar?q=${encodeURIComponent(busquedaLugar)}`
        );
        if (cancelado) return;
        const lugares = Array.isArray(data) ? data : [];
        setSugerenciasLugar(lugares);
        setSinResultadosLugar(lugares.length === 0);
        registrarExito("busqueda", MENSAJE_RECUPERADA);

        // Mark each suggestion with / without history as the answers arrive.
        // A failed check only leaves that suggestion unmarked: picking it asks again.
        lugares.forEach((lugar, i) => {
          consultarLugarVisitado(lugar)
            .then(({ visitado }) => {
              if (cancelado) return;
              setSugerenciasLugar((lista) =>
                lista.map((l, k) => (k === i ? { ...l, visitado } : l))
              );
            })
            .catch((error) => console.error("Error comprobando el historial del lugar:", error));
        });
      } catch (error) {
        if (cancelado) return;
        const { clave, mensaje } = describirFallo(
          error,
          "busqueda",
          "No se pudo buscar el lugar. Intenta de nuevo."
        );
        registrarFallo("busqueda", clave, mensaje);
        setSugerenciasLugar([]);
      } finally {
        if (!cancelado) setBuscandoLugar(false);
      }
    }, 400);

    return () => {
      cancelado = true;
      clearTimeout(timer);
    };
  }, [busquedaLugar]);

  const elegirLugar = async (lugar) => {
    const eleccion = ++eleccionActual.current;
    setBusquedaLugar(lugar.nombre);
    setSugerenciasLugar([]);
    setSinResultadosLugar(false);
    setLugarSinHistorial(null);
    setIndiceRuta(null);

    try {
      const { visitado } = await consultarLugarVisitado(lugar);
      if (eleccion !== eleccionActual.current) return;

      if (visitado) {
        setLugarActivo(lugar);
      } else {
        setLugarActivo(null);
        setLugarSinHistorial(lugar.nombre);
        mostrar("Este lugar nunca se ha visitado.", "aviso");
      }
    } catch (error) {
      console.error("Error comprobando el historial del lugar:", error);
      if (eleccion !== eleccionActual.current) return;
      const { mensaje } = describirFallo(
        error,
        "lugar",
        "No se pudo comprobar si el lugar se ha visitado. Intenta de nuevo en unos segundos."
      );
      mostrar(mensaje, "error");
    }
  };

  const quitarLugar = () => {
    eleccionActual.current += 1;
    setLugarActivo(null);
    setLugarSinHistorial(null);
    setBusquedaLugar("");
    setSugerenciasLugar([]);
    setSinResultadosLugar(false);
    setIndiceRuta(null);
  };

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

  const verRutaSiguiente = () => {
    const siguiente = indiceMostrado + 1;
    setIndiceRuta(siguiente >= rutas.length - 1 ? null : siguiente);
  };

  // The newest route is always "following the live position" (null)
  const irARuta = (indice) => {
    setIndiceRuta(indice >= rutas.length - 1 ? null : indice);
  };

  // ----- Visits to the searched place -----
  const visitas = useMemo(() => calcularVisitas(rutas, lugarActivo), [rutas, lugarActivo]);

  // The selection belongs to the place it was made on, so a new search never
  // inherits a stale highlight
  const visitaElegida =
    visitaSel &&
    visitaSel.lugar === lugarActivo?.nombre &&
    visitas.some((v) => v.id === visitaSel.id)
      ? visitaSel.id
      : null;

  const elegirVisita = (visita) => {
    setVisitaSel({ lugar: lugarActivo?.nombre, id: visita.id });
    if (visita.indiceRuta !== indiceMostrado) irARuta(visita.indiceRuta);
    setVueloA({ centro: [visita.cercano.lat, visita.cercano.lon], n: Date.now() });
  };

  // Why there is nothing to show for the chosen place. Never leave it empty
  // without a reason: either it was never visited, or only outside the dates.
  const mensajeLugar = lugarSinHistorial
    ? "Este lugar nunca se ha visitado."
    : lugarActivo && historialCargado && rutas.length === 0
      ? rangoActivo
        ? "Se ha visitado antes, pero no en el rango de fechas seleccionado."
        : "Se ha visitado antes, pero no en los \u00faltimos 30 d\u00edas."
      : null;

  // Height of the panels floating over the top of the map, so popups and
  // flights keep clear of them
  useEffect(() => {
    const zona = zonaRef.current;
    const capa = zona ? zona.querySelector(".capa-superior") : null;
    if (!zona || !capa) return undefined;
    const medir = () => {
      const tope = capa.getBoundingClientRect().top;
      let bajo = 0;
      for (const hijo of capa.children) {
        bajo = Math.max(bajo, hijo.getBoundingClientRect().bottom - tope);
      }
      setMargenSuperior(Math.round(bajo));
    };
    medir();
    const observador = new ResizeObserver(medir);
    observador.observe(zona);
    for (const hijo of capa.children) observador.observe(hijo);
    return () => observador.disconnect();
  }, [hayUbicacion, compacto]);

  // One entry per route for the route picker
  const opcionesRutas = useMemo(() => {
    const hora = (f) =>
      f.toLocaleTimeString("es-CO", { ...OPCIONES_ZONA, hour: "2-digit", minute: "2-digit" });
    return rutas.map((puntos) => {
      const inicio = parsearFechaGPS(puntos[0].timestamp_gps);
      const fin = parsearFechaGPS(puntos[puntos.length - 1].timestamp_gps);
      return {
        fecha: inicio.toLocaleDateString("es-CO", OPCIONES_ZONA),
        horario: `${hora(inicio)} - ${hora(fin)}`,
        puntos: puntos.length,
      };
    });
  }, [rutas]);

  const volverARutaActual = () => {
    setIndiceRuta(null);
  };

  const dosDigitos = (n) => String(n).padStart(2, "0");

  // Convert 12-hour + AM/PM into the 24-hour format PostgreSQL expects
  const a24Horas = (hora12, meridiano) => {
    if (meridiano === "AM") return hora12 === 12 ? 0 : hora12;
    return hora12 === 12 ? 12 : hora12 + 12;
  };

  const rangoDelFormulario = () => {
    const h1 = a24Horas(horaDesde, meridianoDesde);
    const h2 = a24Horas(horaHasta, meridianoHasta);
    return {
      desde: `${fechaDesde} ${dosDigitos(h1)}:${dosDigitos(minDesde)}:00`,
      hasta: `${fechaHasta} ${dosDigitos(h2)}:${dosDigitos(minHasta)}:59`,
    };
  };

  // Automatic default: complete the routes when the typed range is long
  const { desde: formDesde, hasta: formHasta } = rangoDelFormulario();
  const completarAuto =
    (aMsBogota(formHasta) - aMsBogota(formDesde)) / 3600000 >= UMBRAL_COMPLETAR_H;
  const completarEfectivo = completarManual ?? completarAuto;

  const aplicarFiltro = () => {
    setRangoActivo({ ...rangoDelFormulario(), completar: completarEfectivo });
    setCompletarManual(null);
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
        const data = await pedirJSON(import.meta.env.BASE_URL + "api/ultima-ubicacion");
        setLocation(data);
        registrarExito("ubicacion", MENSAJE_RECUPERADA);
      } catch (error) {
        // 404 = the table is still empty: not a failure, there is just nothing to show
        if (error instanceof ErrorApi && error.tipo === "vacio") {
          setLocation(null);
          registrarExito("ubicacion");
          return;
        }
        const { clave, mensaje } = describirFallo(error, "ubicacion");
        registrarFallo("ubicacion", clave, mensaje);
        // On a network or server failure the last known position stays on screen
      }
    };

    const modoVivo = !rangoActivo && !lugarActivo;
    let cancelado = false; // a newer run of this effect supersedes this one
    setHistorialCargado(false);
    let ultimoTs = null; // newest timestamp_gps we hold (live mode)
    let ultimaCompletaMs = 0; // when the last full load happened

    const obtenerHistorial = async (completo = true) => {
      try {
        let url = import.meta.env.BASE_URL + "api/historial-ubicaciones";
        if (rangoActivo) {
          url += `?desde=${encodeURIComponent(rangoActivo.desde)}&hasta=${encodeURIComponent(rangoActivo.hasta)}`;
          // The server widens the range, clamped to its own "now", when asked
          if (rangoActivo.completar) url += `&margen_horas=${MARGEN_RANGO_H}`;
        } else if (modoVivo && !completo && ultimoTs) {
          // Incremental: only the points after the newest one we hold, minus one
          // minute of overlap (duplicates are dropped when merging). No upper bound.
          const desdeTxt = aTextoBogota(aMsBogota(ultimoTs) - 60 * 1000);
          url += `?despues_de=${encodeURIComponent(desdeTxt)}`;
        } else {
          const horas = lugarActivo ? VENTANA_LUGAR_H : MARGEN_VIVO_H;
          url += `?horas=${horas}`;
        }
        const data = await pedirJSON(url);
        if (cancelado) return;
        const filas = Array.isArray(data) ? data : [];
        registrarExito("historial", MENSAJE_RECUPERADA);
        setHistorialCargado(true);

        if (modoVivo && !completo) {
          if (filas.length) {
            const ultimo = filas[filas.length - 1].timestamp_gps;
            if (!ultimoTs || ultimo > ultimoTs) ultimoTs = ultimo;
          }
          setHistorial((previo) =>
            fusionarHistorial(previo, filas, Date.now() - MARGEN_VIVO_H * 3600 * 1000)
          );
        } else {
          ultimoTs = filas.length ? filas[filas.length - 1].timestamp_gps : null;
          ultimaCompletaMs = Date.now();
          setHistorial(filas);
        }
      } catch (error) {
        if (cancelado) return;
        const { clave, mensaje } = describirFallo(error, "historial");
        registrarFallo("historial", clave, mensaje);
        // A rejected request (e.g. an invalid range) leaves nothing valid to show;
        // network and server failures keep what is already on screen.
        if (completo && error instanceof ErrorApi && error.tipo === "solicitud") {
          setHistorial([]);
        }
      }
    };

    obtenerUbicacion();
    obtenerHistorial(true);

    // A fully past range can't receive new points, so stop polling the
    // history for it (the live marker keeps updating regardless).
    const rangoEsPasado = rangoActivo && aMsBogota(rangoActivo.hasta) < Date.now();

    const tick = () => {
      // Nothing to refresh while the tab is in the background
      if (document.hidden) return;
      obtenerUbicacion();
      if (lugarActivo || rangoEsPasado) return;
      const tocaCompleta = Date.now() - ultimaCompletaMs >= RECARGA_COMPLETA_MS;
      obtenerHistorial(!modoVivo || tocaCompleta);
    };

    const intervalo = setInterval(tick, 10000);
    const alCambiarVisibilidad = () => {
      if (!document.hidden) tick();
    };
    document.addEventListener("visibilitychange", alCambiarVisibilidad);

    return () => {
      cancelado = true;
      clearInterval(intervalo);
      document.removeEventListener("visibilitychange", alCambiarVisibilidad);
    };
  }, [rangoActivo, lugarActivo]);

  const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";

  return (
    <div className="app">
      <Toasts toasts={toasts} onCerrar={cerrar} />
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
            <div className={`mapa-zona ${compacto ? "compacto" : ""} ${bajo ? "bajo" : ""}`} ref={zonaRef}>
            <div className="capa-superior">
            <div className={`panel ${panelExpandido ? "expandido" : ""}`}>
              <button
                className="panel-resumen"
                onClick={() => setPanelExpandido(!panelExpandido)}
                aria-expanded={panelExpandido}
              >
                <span className={`dot dot-${estado.tier}`}></span>
                <span className="panel-resumen-texto">
                  {Number(location.latitud).toFixed(4)}, {Number(location.longitud).toFixed(4)} ·{" "}
                  {fechaGPS.toLocaleTimeString("es-CO", { ...OPCIONES_ZONA, hour: "2-digit", minute: "2-digit" })}
                </span>
                <span className="panel-flecha">{panelExpandido ? "▴" : "▾"}</span>
              </button>

              <div className="panel-detalle">
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
            </div>

            <div className={`superior ${filtrosVisibles ? "filtros-visibles" : ""}`}>
              <button
                className={`filtros-toggle-compacto ${rangoActivo || lugarActivo ? "activo" : ""}`}
                onClick={() => {
                  setFiltrosVisibles(!filtrosVisibles);
                  setFiltroAbierto(false);
                }}
                aria-expanded={filtrosVisibles}
              >
                Filtros
                {(rangoActivo || lugarActivo) && <span className="punto-filtro" />}
              </button>
              {ruta.length > 0 && (
                <div className="nav-rutas">
                  <button
                    className="nav-btn"
                    onClick={verRutaAnterior}
                    disabled={indiceMostrado === 0}
                    aria-label="Ruta anterior"
                  >
                    ← <span className="nav-texto">Anterior</span>
                  </button>
                  <SelectorRuta
                    etiqueta={etiquetaRuta}
                    opciones={opcionesRutas}
                    indice={indiceMostrado}
                    onElegir={irARuta}
                  />
                  <button
                    className="nav-btn"
                    onClick={verRutaSiguiente}
                    disabled={siguiendoActual}
                    aria-label="Ruta siguiente"
                  >
                    <span className="nav-texto">Siguiente</span> &rarr;
                  </button>
                  {/* Shortcut to the newest route; only useful when "Siguiente" is not already it */}
                  {indiceMostrado < rutas.length - 2 && (
                    <button className="nav-btn primario" onClick={volverARutaActual} aria-label="Ruta actual">
                      <span className="nav-texto">Actual</span> &raquo;
                    </button>
                  )}
                </div>
              )}

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

                <label className="filtro-completar">
                  <input
                    type="checkbox"
                    checked={completarEfectivo}
                    onChange={() => setCompletarManual(!completarEfectivo)}
                  />
                  <span>
                    Completar rutas en los bordes
                    {completarManual === null && <em> (automático)</em>}
                  </span>
                </label>

                <div className="filtro-acciones">
                  <button onClick={() => setFiltroAbierto(false)}>Cancelar</button>
                  {rangoActivo && <button onClick={quitarFiltro}>Ver en vivo</button>}
                  <button className="aplicar" onClick={aplicarFiltro}>
                    Aplicar
                  </button>
                </div>
              </div>
              ) : (
                <div className="filtros-chips">
                  <button className="filtro-toggle" onClick={() => setFiltroAbierto(true)}>
                    {rangoActivo ? "Rango personalizado" : "Filtrar por fecha"}
                  </button>
                  {rangoActivo && (
                    <button className="chip-quitar" onClick={quitarFiltro} aria-label="Quitar filtro de fecha">
                      x
                    </button>
                  )}
                </div>
              )}

              <div className="buscador-lugar">
                <input
                  type="text"
                  className="buscador-input"
                  placeholder="Filtrar por ciudad o direccion"
                  value={busquedaLugar}
                  onChange={(e) => {
                    setBusquedaLugar(e.target.value);
                    if (lugarActivo) setLugarActivo(null);
                    // Editing the text drops the previous verdict and any pending pick
                    eleccionActual.current += 1;
                    setLugarSinHistorial(null);
                  }}
                />
                {lugarActivo && (
                  <button className="chip-quitar" onClick={quitarLugar} aria-label="Quitar filtro de lugar">
                    x
                  </button>
                )}

                {sugerenciasLugar.length > 0 && (
                  <div className="sugerencias-lugar">
                    {sugerenciasLugar.map((s, i) => (
                      <button key={i} className="sugerencia-item" onClick={() => elegirLugar(s)}>
                        {s.nombre}
                        {s.visitado === false && (
                          <span className="chip-estado chip-sin-historial">Sin historial</span>
                        )}
                        {s.visitado === true && (
                          <span className="chip-estado chip-con-historial">Con historial</span>
                        )}
                      </button>
                    ))}
                  </div>
                )}
                {buscandoLugar && <span className="buscando-lugar">Buscando...</span>}
              {!buscandoLugar && sinResultadosLugar && (
                  <span className="buscando-lugar">No se encontr&oacute; ning&uacute;n lugar con ese nombre.</span>
                )}
              </div>

              {mensajeLugar && (
                <p className="lugar-mensaje" role="status">
                  {mensajeLugar}
                </p>
              )}
            </div>

            </div>

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
                  <label className="capas-opcion">
                    <span>
                      Mostrar paradas
                      {paradas.length > 0 && <em> &middot; {paradas.length}</em>}
                    </span>
                    <input
                      type="checkbox"
                      checked={paradasVisibles}
                      onChange={() => setParadasVisibles(!paradasVisibles)}
                    />
                    <span className="interruptor" />
                  </label>
                </div>
              )}

              {velocidadActualKmh !== null && (
                <div
                  className="velocidad-chip"
                  title="Velocidad estimada con los &uacute;ltimos puntos"
                  aria-label={`Velocidad estimada: ${Math.round(velocidadActualKmh)} km/h`}
                >
                  <b>{Math.round(velocidadActualKmh)}</b> km/h
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

            
            {ruta.length > 1 && (
              <div className="legend">
                <div className="legend-item">
                  <span className="legend-dot start"></span> Inicio
                </div>
                <div className="legend-item">
                  <span className={`legend-dot ${siguiendoActual ? "current" : "end"}`}></span>
                  {siguiendoActual ? " Actual" : " Fin de ruta"}
                </div>
                {visitas.length > 0 && (
                  <div className="legend-item">
                    <span className="legend-dot visita"></span> Pas&oacute; por el lugar
                  </div>
                )}
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
                  icon={siguiendoActual ? (enVivo ? iconoActual : iconoActualInactivo) : iconoFin}
                >
                  <Popup className="popup-oscuro" autoPanPaddingTopLeft={[16, margenSuperior]}>
                    <PopupPosicion
                      titulo={
                        siguiendoActual
                          ? enVivo
                            ? "Posici\u00f3n actual"
                            : "\u00daltima posici\u00f3n conocida"
                          : "Fin de la ruta"
                      }
                      punto={ultimaLectura}
                      velocidadKmh={velocidadActualKmh}
                      estadisticas={estadisticasRuta}
                      paradas={paradas.length}
                    />
                  </Popup>
                </Marker>
              )}
            <AjustarTamano zonaRef={zonaRef} />
            <MarcadoresVisitas
                visitas={visitas}
                indiceRuta={indiceMostrado}
                seleccionada={visitaElegida}
                onIrARuta={elegirVisita}
                margenSuperior={margenSuperior}
              />
              <VolarA destino={vueloA} margenSuperior={margenSuperior} />
            {paradasVisibles && <MarcadoresParada paradas={paradas} />}
            </MapContainer>
            </div>

            <aside className="sidebar">
              <PanelVisitas
                visitas={visitas}
                nombreLugar={lugarActivo ? lugarActivo.nombre : ""}
                rangoActivo={rangoActivo}
                seleccionada={visitaElegida}
                onElegir={elegirVisita}
              />
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
