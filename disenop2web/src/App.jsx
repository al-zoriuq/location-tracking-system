import "./App.css";
import { useState, useEffect, useRef, useMemo } from "react";
import { MapContainer, TileLayer, Marker, Polyline, useMap } from "react-leaflet";
import L from "leaflet";
import AyudaModal from "./AyudaModal.jsx";
import SelectorFechaHora from "./SelectorFechaHora.jsx";
import SelectorRuta from "./SelectorRuta.jsx";
import Toasts from "./Toasts.jsx";
import { useToasts } from "./useToasts.js";
import { pedirJSON, describirFallo, MENSAJE_RECUPERADA } from "./api.js";
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

// The public OSRM server (router.project-osrm.org) accepts at most 10
// coordinates and a 40 m search radius per map-matching request; anything
// above answers 400, so a trip is matched in small chunks.
const OSRM_MAX_PUNTOS = 10;
const OSRM_RADIO_M = 40;
const OSRM_CONCURRENCIA = 3; // requests in flight at once: the server is shared
const OSRM_MAX_TRAMOS = 60; // longer trips would need hundreds of requests: not snapped

// Answers already received, by request URL. The route is snapped again every
// time a point arrives (every 10 s in live mode), but only its last chunk
// changes, so the rest comes from here instead of asking the server again.
const cacheOSRM = new Map();
const CACHE_OSRM_MAX = 500;

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

// Matches one chunk of points onto the road network. Never rejects because of
// the server: a failed chunk keeps its raw points and reports why in `fallo`.
async function ajustarTramo(tramo, senal) {
  const coords = tramo.map(([lat, lon]) => `${lon},${lat}`).join(";");
  const radios = tramo.map(() => OSRM_RADIO_M).join(";");
  const url =
    `https://router.project-osrm.org/match/v1/driving/${coords}` +
    `?geometries=geojson&overview=full&tidy=true&radiuses=${radios}`;

  if (cacheOSRM.has(url)) return cacheOSRM.get(url);

  let resultado;
  try {
    let respuesta = await fetch(url, { signal: senal });
    if (respuesta.status === 429) {
      // Rate limited: wait a moment and try once more
      await new Promise((resolver) => setTimeout(resolver, 1000));
      respuesta = await fetch(url, { signal: senal });
    }
    if (!respuesta.ok) return { puntos: tramo, fallo: "servicio" };

    const datos = await respuesta.json();
    if (datos.code !== "Ok" || !datos.matchings || datos.matchings.length === 0) {
      resultado = { puntos: tramo, fallo: "sin-coincidencia" };
    } else {
      resultado = {
        puntos: datos.matchings.flatMap((m) =>
          m.geometry.coordinates.map(([lon, lat]) => [lat, lon])
        ),
        fallo: null,
      };
    }
  } catch (error) {
    if (senal.aborted) throw error; // superseded by a newer route: caller ignores it
    return { puntos: tramo, fallo: "servicio" };
  }

  // Only answers from the server are kept; a "servicio" failure is retried next time
  cacheOSRM.set(url, resultado);
  if (cacheOSRM.size > CACHE_OSRM_MAX) cacheOSRM.delete(cacheOSRM.keys().next().value);
  return resultado;
}

// Sends the raw GPS points to OSRM's map matching service and gets back the
// same trip snapped onto the actual road network. The original coordinates
// are never modified: this only affects the drawn line.
// Returns { puntos, fallo }: `fallo` is null when everything matched,
// "servicio" when OSRM itself failed, "sin-coincidencia" when it answered but
// could not match some points to a road, and "muy-larga" when the trip needs
// more than OSRM_MAX_TRAMOS requests. Failed chunks keep their raw points.
async function ajustarACarretera(puntos, senal) {
  const tramos = [];
  // Chunks overlap by one point so the snapped line has no visible seams.
  for (let i = 0; i < puntos.length; i += OSRM_MAX_PUNTOS - 1) {
    const tramo = puntos.slice(i, i + OSRM_MAX_PUNTOS);
    if (tramo.length > 1) tramos.push(tramo);
  }

  if (tramos.length > OSRM_MAX_TRAMOS) return { puntos, fallo: "muy-larga" };

  // A few workers take chunks in order, so the requests are not all sent at once
  const resultados = new Array(tramos.length);
  let siguiente = 0;
  const trabajador = async () => {
    while (siguiente < tramos.length && !senal.aborted) {
      const i = siguiente++;
      resultados[i] = await ajustarTramo(tramos[i], senal);
    }
  };
  await Promise.all(Array.from({ length: OSRM_CONCURRENCIA }, trabajador));
  if (senal.aborted) throw new DOMException("Ajuste cancelado", "AbortError");

  const fallos = resultados.map((r) => r.fallo);
  return {
    puntos: resultados.flatMap((r) => r.puntos),
    fallo: fallos.includes("servicio")
      ? "servicio"
      : fallos.includes("sin-coincidencia")
        ? "sin-coincidencia"
        : null,
  };
}

// Leaflet only re-measures itself on window resize. The map container also
// changes size when the history list is folded/unfolded on small screens, so
// watch the container itself.
function AjustarTamano() {
  const map = useMap();

  useEffect(() => {
    const observador = new ResizeObserver(() => map.invalidateSize());
    observador.observe(map.getContainer());
    return () => observador.disconnect();
  }, [map]);

  return null;
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

// While the "Centrado" toggle is on, the latest point stays in the middle of
// the map without ever changing the zoom the user chose. If the user moves the
// map away, it glides back to the point once they have left it alone for
// RETORNO_CENTRADO_MS.
const RETORNO_CENTRADO_MS = 4000;

function SeguirPunto({ lat, lon, activo }) {
  const map = useMap();
  const objetivo = useRef(null); // latest point to follow
  const temporizador = useRef(null); // pending "go back to the point"
  const tocando = useRef(false); // a finger / the mouse is down on the map

  // Follow the point as new readings arrive, unless the user is exploring
  useEffect(() => {
    objetivo.current = lat == null || lon == null ? null : [lat, lon];
    if (!activo || !objetivo.current) return;
    if (tocando.current || temporizador.current !== null) return; // the timer will bring it back
    map.panTo(objetivo.current, { animate: true });
  }, [lat, lon, activo, map]);

  // Any user gesture postpones the return; when they stop, count down again
  useEffect(() => {
    if (!activo) return;

    const contenedor = map.getContainer();

    const programarRetorno = () => {
      clearTimeout(temporizador.current);
      temporizador.current = setTimeout(() => {
        temporizador.current = null;
        if (!tocando.current && objetivo.current) map.panTo(objetivo.current, { animate: true });
      }, RETORNO_CENTRADO_MS);
    };
    const alPresionar = () => {
      tocando.current = true;
      clearTimeout(temporizador.current);
      temporizador.current = null;
    };
    const alSoltar = () => {
      if (!tocando.current) return;
      tocando.current = false;
      programarRetorno();
    };

    contenedor.addEventListener("pointerdown", alPresionar);
    contenedor.addEventListener("wheel", programarRetorno, { passive: true });
    contenedor.addEventListener("keydown", programarRetorno);
    // The button can be released outside the map after a drag
    window.addEventListener("pointerup", alSoltar);
    window.addEventListener("pointercancel", alSoltar);

    // Turning the toggle on brings the point to the center right away
    if (objetivo.current) map.panTo(objetivo.current, { animate: true });

    return () => {
      contenedor.removeEventListener("pointerdown", alPresionar);
      contenedor.removeEventListener("wheel", programarRetorno);
      contenedor.removeEventListener("keydown", programarRetorno);
      window.removeEventListener("pointerup", alSoltar);
      window.removeEventListener("pointercancel", alSoltar);
      clearTimeout(temporizador.current);
      temporizador.current = null;
      tocando.current = false;
    };
  }, [activo, map]);

  return null;
}

function parsearFechaGPS(timestampTexto) {
  return new Date(timestampTexto.replace(" ", "T") + DESFASE_ZONA);
}

// Current time in the project zone, formatted like the value of an
// <input type="datetime-local"> ("YYYY-MM-DDTHH:mm"). Strings in this format
// compare correctly with < and >.
function ahoraParaInput() {
  return new Date()
    .toLocaleString("sv-SE", OPCIONES_ZONA)
    .slice(0, 16)
    .replace(" ", "T");
}

// Returns the error text to show, or null when the range can be applied.
function validarRango(desde, hasta, ahora) {
  if (!desde || !hasta) return "Elige la fecha y hora de inicio y de fin.";
  if (hasta < desde) return "La fecha final no puede ser anterior a la inicial.";
  if (desde > ahora || hasta > ahora) return "No puedes elegir una fecha futura.";
  return null;
}

// True while the viewport matches a CSS media query (kept in sync on resize).
function useMediaQuery(consulta) {
  const [coincide, setCoincide] = useState(() => window.matchMedia(consulta).matches);

  useEffect(() => {
    const lista = window.matchMedia(consulta);
    const alCambiar = () => setCoincide(lista.matches);
    lista.addEventListener("change", alCambiar);
    return () => lista.removeEventListener("change", alCambiar);
  }, [consulta]);

  return coincide;
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
  const [ayudaAbierta, setAyudaAbierta] = useState(false);
  const { toasts, mostrar, cerrar, registrarFallo, registrarExito } = useToasts();
  // "cargando" | "ok" | "vacio" (database has no points yet) | "error"
  const [ubicacionEstado, setUbicacionEstado] = useState("cargando");
  // False until the history for the current range has arrived, so "no data"
  // messages don't flash while it is still loading
  const [historialCargado, setHistorialCargado] = useState(false);
  const vacioAvisado = useRef(null); // range key whose "no data" toast was already shown
  // Small screens: the history list sits under the map and can be folded
  const esMovil = useMediaQuery("(max-width: 900px)");
  const [listaAbierta, setListaAbierta] = useState(false);

  // Date/time range filter state
  const [filtroAbierto, setFiltroAbierto] = useState(false);
  // datetime-local values ("YYYY-MM-DDTHH:mm"), empty until the panel is first opened
  const [fechaDesde, setFechaDesde] = useState("");
  const [fechaHasta, setFechaHasta] = useState("");
  // Upper bound for both inputs: "now" in the project zone, refreshed on every open
  const [ahoraMax, setAhoraMax] = useState(ahoraParaInput);
  const [errorFiltro, setErrorFiltro] = useState("");
  const [campoFecha, setCampoFecha] = useState(null); // which picker is unfolded: "desde" | "hasta" | null
  // null = live mode (last 24h). {desde, hasta} = explicit range applied.
  const [rangoActivo, setRangoActivo] = useState(null);

  // Location filter state
  const [busquedaLugar, setBusquedaLugar] = useState("");
  const [sugerenciasLugar, setSugerenciasLugar] = useState([]);
  const [buscandoLugar, setBuscandoLugar] = useState(false);
  const [sinResultadosLugar, setSinResultadosLugar] = useState(false);
  const [lugarActivo, setLugarActivo] = useState(null); // {nombre, lat_min, lat_max, lon_min, lon_max}
  // Name of the chosen place when the database has no point inside it at all
  const [lugarSinHistorial, setLugarSinHistorial] = useState(null);
  const busquedaElegida = useRef(null); // text set by picking a suggestion: must not trigger a new search
  const eleccionActual = useRef(0); // ignores the answer of an older pick if a newer one was made

  const fechaGPS = location ? parsearFechaGPS(location.timestamp_gps) : null;
  const estado = calcularEstado(fechaGPS);

  const todasLasRutas = useMemo(() => dividirEnRutas(historial), [historial]);

  // A route "matches" a place if any of its points falls inside that
  // place's bounding box (city/town box, or the small radius box built
  // around a single-point address).
  const rutas = useMemo(() => {
    if (!lugarActivo) return todasLasRutas;
    return todasLasRutas.filter((puntos) =>
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
  }, [todasLasRutas, lugarActivo]);

  // Why there is nothing to show for the chosen place. Never leave it empty
  // without a reason: either it was never visited, or only outside the dates.
  const mensajeLugar = lugarSinHistorial
    ? "Este lugar nunca se ha visitado."
    : lugarActivo && historialCargado && rutas.length === 0
      ? rangoActivo
        ? "Se ha visitado antes, pero no en el rango de fechas seleccionado."
        : "Se ha visitado antes, pero no en las últimas 24 horas."
      : null;

  const siguiendoActual = indiceRuta === null;
  const indiceMostrado = siguiendoActual ? rutas.length - 1 : indiceRuta;
  const puntosRutaMostrada = rutas[indiceMostrado] || [];

  const ruta = puntosRutaMostrada.map((punto) => [
    Number(punto.latitud),
    Number(punto.longitud),
  ]);

  const historialReciente = [...puntosRutaMostrada].reverse();

  useEffect(() => {
    // The text was filled in by picking a suggestion: not a new search
    if (busquedaLugar === busquedaElegida.current) return;

    if (busquedaLugar.trim().length < 3) {
      setSugerenciasLugar([]);
      setSinResultadosLugar(false);
      setBuscandoLugar(false);
      return;
    }

    setBuscandoLugar(true);
    let cancelado = false;
    const timer = setTimeout(async () => {
      try {
        const data = await pedirJSON(
          import.meta.env.BASE_URL + `api/buscar-lugar?q=${encodeURIComponent(busquedaLugar)}`
        );
        if (cancelado) return;
        const lugares = Array.isArray(data) ? data : [];
        setSugerenciasLugar(lugares);
        setSinResultadosLugar(lugares.length === 0);
        registrarExito("buscar");

        // Mark each suggestion as with/without history as the answers arrive.
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
        console.error("Error buscando lugar:", error);
        if (cancelado) return;
        setSugerenciasLugar([]);
        setSinResultadosLugar(false);
        const { clave, mensaje } = describirFallo(
          error,
          "buscar",
          "El buscador de lugares no está disponible en este momento. Intenta de nuevo en unos segundos."
        );
        registrarFallo("buscar", clave, mensaje);
      } finally {
        if (!cancelado) setBuscandoLugar(false);
      }
    }, 400);

    return () => {
      cancelado = true;
      clearTimeout(timer);
    };
  }, [busquedaLugar, registrarFallo, registrarExito]);

  // Picking a suggestion first asks the backend if the place has any history at
  // all. Only then is the filter applied; otherwise the reason is shown instead.
  const elegirLugar = async (lugar) => {
    const eleccion = ++eleccionActual.current;
    busquedaElegida.current = lugar.nombre;
    setBusquedaLugar(lugar.nombre);
    setSugerenciasLugar([]);
    setSinResultadosLugar(false);
    setLugarActivo(null);
    setLugarSinHistorial(null);
    setIndiceRuta(null);

    try {
      const { visitado } = await consultarLugarVisitado(lugar);
      if (eleccion !== eleccionActual.current) return;

      if (visitado) {
        setLugarActivo(lugar);
      } else {
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
    eleccionActual.current++;
    busquedaElegida.current = null;
    setLugarActivo(null);
    setLugarSinHistorial(null);
    setBusquedaLugar("");
    setSugerenciasLugar([]);
    setIndiceRuta(null);
  };

  const ultimoPunto = ruta.length > 0 ? ruta[ruta.length - 1] : null;

  // Primitive key so the snapping effect only refires on real route changes,
  // not on every render (array literals get a new identity each time).
  // Identity of the route on screen: the timestamp of its first point
  const idRuta = puntosRutaMostrada.length > 0 ? puntosRutaMostrada[0].timestamp_gps : null;
  const claveRuta = ultimoPunto
    ? `${indiceMostrado}:${idRuta}:${ruta.length}:${ultimoPunto[0]},${ultimoPunto[1]}`
    : "";

  useEffect(() => {
    if (!snapActivo || ruta.length < 2) {
      setRutaAjustada(null);
      setSnapCargando(false);
      registrarExito("osrm");
      return;
    }

    let cancelado = false;
    const controlador = new AbortController();
    setSnapCargando(true);

    ajustarACarretera(ruta, controlador.signal)
      .then(({ puntos, fallo }) => {
        if (cancelado) return;
        setRutaAjustada({ idRuta, puntos });

        // The drawn line falls back to the raw GPS points, so these are warnings
        if (fallo === "servicio") {
          console.error("Error ajustando la ruta a carretera: el servicio OSRM no respondió bien");
          registrarFallo(
            "osrm",
            "osrm:servicio",
            "No se pudo ajustar la ruta a las vías (el servicio de mapas no responde). Se muestra la ruta original."
          );
        } else if (fallo === "muy-larga") {
          registrarFallo(
            "osrm",
            "osrm:larga",
            "Esta ruta es demasiado larga para ajustarla a las vías. Se muestra la ruta original."
          );
        } else if (fallo === "sin-coincidencia") {
          console.error("Error ajustando la ruta a carretera: OSRM no encontró vías cercanas");
          registrarFallo(
            "osrm",
            "osrm:coincidencia",
            "Parte de la ruta no se pudo ajustar a las vías. Se muestra tal como fue registrada."
          );
        } else {
          registrarExito("osrm");
        }
      })
      .catch((error) => {
        if (cancelado) return; // a newer route replaced this one
        console.error("Error ajustando la ruta a carretera:", error);
        setRutaAjustada(null);
        registrarFallo(
          "osrm",
          "osrm:red",
          "No se pudo ajustar la ruta a las vías (no hay conexión con el servicio de mapas). Se muestra la ruta original."
        );
      })
      .finally(() => {
        if (!cancelado) setSnapCargando(false);
      });

    return () => {
      cancelado = true;
      controlador.abort();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [snapActivo, claveRuta]);

  // Snapped line when it belongs to the route on screen, raw GPS line otherwise
  // (while a new route is being snapped, the previous route's line must not linger).
  const rutaDibujada =
    snapActivo && rutaAjustada && rutaAjustada.idRuta === idRuta ? rutaAjustada.puntos : ruta;

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

  // One line of description per route, for the "pick a route" list
  const opcionesRuta = useMemo(
    () =>
      rutas.map((puntos) => {
        const primero = parsearFechaGPS(puntos[0].timestamp_gps);
        const ultimo = parsearFechaGPS(puntos[puntos.length - 1].timestamp_gps);
        const hora = (fecha) => fecha.toLocaleTimeString("es-CO", OPCIONES_HORA_CORTA);
        return {
          fecha: primero.toLocaleDateString("es-CO", OPCIONES_ZONA),
          horario: puntos.length > 1 ? `${hora(primero)} - ${hora(ultimo)}` : hora(primero),
          puntos: puntos.length,
        };
      }),
    [rutas]
  );

  // Jump to any route. The newest one is the live one, so picking it returns to live mode.
  const irARuta = (indice) => {
    setIndiceRuta(indice >= rutas.length - 1 ? null : indice);
  };

  const verRutaAnterior = () => {
    setIndiceRuta(Math.max(0, indiceMostrado - 1));
  };

  // One route forward. Reaching the newest route goes back to "live" mode
  // (null), so from then on new points keep updating it.
  const verRutaSiguiente = () => {
    const siguiente = indiceMostrado + 1;
    setIndiceRuta(siguiente >= rutas.length - 1 ? null : siguiente);
  };

  const volverARutaActual = () => {
    setIndiceRuta(null);
  };

  const abrirFiltro = () => {
    const ahora = ahoraParaInput();
    setAhoraMax(ahora);
    setErrorFiltro("");
    setCampoFecha(null);
    // First time: today from 00:00 until now. Afterwards keep what was chosen.
    setFechaDesde((valor) => valor || `${ahora.slice(0, 10)}T00:00`);
    setFechaHasta((valor) => (valor && valor <= ahora ? valor : ahora));
    setFiltroAbierto(true);
  };

  const aplicarFiltro = () => {
    // "now" is re-read here: the panel may have been open for a while
    const error = validarRango(fechaDesde, fechaHasta, ahoraParaInput());
    if (error) {
      setErrorFiltro(error);
      return;
    }

    setErrorFiltro("");
    setRangoActivo({
      desde: `${fechaDesde.replace("T", " ")}:00`,
      hasta: `${fechaHasta.replace("T", " ")}:59`,
    });
    setHistorialCargado(false);
    setIndiceRuta(null);
    setFiltroAbierto(false);
  };

  const quitarFiltro = () => {
    setRangoActivo(null);
    setHistorialCargado(false);
    setIndiceRuta(null);
    setFiltroAbierto(false);
  };

  useEffect(() => {
    const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";
    document.title = `GPSLink - ${nombre}`;
  }, []);

  useEffect(() => {
    // The first history request of each range replaces data that belongs to a
    // different range, so if it fails the old points must not stay on screen.
    let primeraCarga = true;

    const obtenerUbicacion = async () => {
      try {
        const data = await pedirJSON(import.meta.env.BASE_URL + "api/ultima-ubicacion");
        setLocation(data);
        setUbicacionEstado("ok");
        registrarExito("ubicacion", MENSAJE_RECUPERADA);
      } catch (error) {
        if (error.tipo === "vacio") {
          // Not a failure: the database just has no points yet
          setLocation(null);
          setUbicacionEstado("vacio");
          registrarExito("ubicacion", MENSAJE_RECUPERADA);
          return;
        }

        console.error("Error obteniendo ubicación:", error);
        // Keep showing the last known position while the connection is down
        setUbicacionEstado("error");
        const { clave, mensaje } = describirFallo(error, "datos");
        registrarFallo("ubicacion", clave, mensaje);
      }
    };

    const obtenerHistorial = async () => {
      const esPrimera = primeraCarga;
      primeraCarga = false;

      try {
        let url = import.meta.env.BASE_URL + "api/historial-ubicaciones";
        if (rangoActivo) {
          url += `?desde=${encodeURIComponent(rangoActivo.desde)}&hasta=${encodeURIComponent(rangoActivo.hasta)}`;
        }
        const data = await pedirJSON(url);
        const puntos = Array.isArray(data) ? data : [];
        setHistorial(puntos);
        setHistorialCargado(true);
        registrarExito("historial", MENSAJE_RECUPERADA);

        // "No data" toast: once per range, not on every 10 s poll
        if (puntos.length === 0) {
          const claveRango = rangoActivo ? `${rangoActivo.desde}|${rangoActivo.hasta}` : "vivo";
          if (vacioAvisado.current !== claveRango) {
            vacioAvisado.current = claveRango;
            mostrar(
              rangoActivo
                ? "No hay ubicaciones en el rango de fechas seleccionado."
                : "No hay ubicaciones en las últimas 24 horas.",
              "aviso"
            );
          }
        } else {
          vacioAvisado.current = null;
        }
      } catch (error) {
        console.error("Error obteniendo historial:", error);
        if (esPrimera || error.tipo === "solicitud") setHistorial([]);

        // "solicitud" = the backend rejected the range: show its own explanation
        const { clave, mensaje } = describirFallo(error, "datos");
        registrarFallo("historial", clave, mensaje);
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
  }, [rangoActivo, mostrar, registrarFallo, registrarExito]);

  const nombre = import.meta.env.VITE_NOMBRE_PERSONA || "GPSLink";

  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <svg className="brand-icono" width="20" height="20" viewBox="0 0 24 24" fill="none"
            stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
            <path d="M12 21s-7-6.2-7-11.5A7 7 0 0 1 19 9.5C19 14.8 12 21 12 21z" />
            <circle cx="12" cy="9.5" r="2.5" />
          </svg>
          GPSLink <span>· {nombre}</span>
        </div>
        <div className="topbar-derecha">
          <div className="status">
            <span className={`dot dot-${estado.tier}`}></span>
            {estado.texto}
          </div>
          <button
            className="btn-ayuda"
            onClick={() => setAyudaAbierta(true)}
            aria-haspopup="dialog"
            aria-label="Ayuda: cómo usar esta página"
          >
            <span className="btn-ayuda-signo" aria-hidden="true">?</span>
            <span className="btn-ayuda-texto">Ayuda</span>
          </button>
        </div>
      </div>

      {ayudaAbierta && <AyudaModal onCerrar={() => setAyudaAbierta(false)} />}

      <Toasts toasts={toasts} onCerrar={cerrar} />

      <div className={`main ${listaAbierta ? "lista-abierta" : ""}`}>
        {location ? (
          <>
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

            <div className="superior">
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
                    opciones={opcionesRuta}
                    indice={indiceMostrado}
                    onElegir={irARuta}
                  />
                  <button
                    className="nav-btn"
                    onClick={verRutaSiguiente}
                    disabled={siguiendoActual}
                    aria-label="Ruta siguiente"
                  >
                    <span className="nav-texto">Siguiente</span> →
                  </button>
                  {/* Shortcut to the newest route; only useful when "Siguiente" is not already it */}
                  {indiceMostrado < rutas.length - 2 && (
                    <button
                      className="nav-btn primario"
                      onClick={volverARutaActual}
                      aria-label="Ir a la ruta actual, la más reciente"
                      title="Ir a la ruta más reciente"
                    >
                      <span className="nav-texto">Actual</span> »
                    </button>
                  )}
                </div>
              )}

              {filtroAbierto ? (
              <div className="filtro-fecha">
                <SelectorFechaHora
                  etiqueta="Desde"
                  valor={fechaDesde}
                  max={ahoraMax}
                  abierto={campoFecha === "desde"}
                  onAlternar={() => setCampoFecha(campoFecha === "desde" ? null : "desde")}
                  onChange={(valor) => {
                    setFechaDesde(valor);
                    setErrorFiltro("");
                  }}
                />

                <SelectorFechaHora
                  etiqueta="Hasta"
                  valor={fechaHasta}
                  min={fechaDesde || undefined}
                  max={ahoraMax}
                  abierto={campoFecha === "hasta"}
                  onAlternar={() => setCampoFecha(campoFecha === "hasta" ? null : "hasta")}
                  onChange={(valor) => {
                    setFechaHasta(valor);
                    setErrorFiltro("");
                  }}
                />

                {errorFiltro && (
                  <p className="filtro-error" role="alert">
                    {errorFiltro}
                  </p>
                )}

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
                  <button className="filtro-toggle" onClick={abrirFiltro}>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                      <rect x="3" y="5" width="18" height="16" rx="3" />
                      <line x1="3" y1="10" x2="21" y2="10" />
                      <line x1="8" y1="3" x2="8" y2="7" />
                      <line x1="16" y1="3" x2="16" y2="7" />
                    </svg>
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
                    eleccionActual.current++;
                    busquedaElegida.current = null;
                    setBusquedaLugar(e.target.value);
                    if (lugarActivo) setLugarActivo(null);
                    if (lugarSinHistorial) setLugarSinHistorial(null);
                  }}
                />
                {(lugarActivo || lugarSinHistorial) && (
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
                  <span className="buscando-lugar">
                    No se encontró ningún lugar con ese nombre.
                  </span>
                )}
              </div>

              {mensajeLugar && (
                <p className="lugar-mensaje" role="status">
                  {mensajeLugar}
                </p>
              )}
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
                aria-label="Mantener el punto centrado"
                aria-pressed={centradoActivo}
                title="Mantiene el punto actual en el centro sin cambiar tu zoom. Si mueves el mapa, vuelve solo tras unos segundos"
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

              <AjustarTamano />

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
              {esMovil ? (
                <button
                  className="sidebar-title sidebar-toggle"
                  onClick={() => setListaAbierta(!listaAbierta)}
                  aria-expanded={listaAbierta}
                  aria-controls="lista-historial"
                >
                  Historial de puntos ({historialReciente.length})
                  <span className="sidebar-flecha" aria-hidden="true">
                    {listaAbierta ? "▾" : "▴"}
                  </span>
                </button>
              ) : (
                <p className="sidebar-title">
                  Historial de puntos ({historialReciente.length})
                </p>
              )}
              <div className="sidebar-list" id="lista-historial">
                {historialReciente.length === 0 && historialCargado && (
                  <p className="sidebar-vacio">
                    {historial.length === 0
                      ? rangoActivo
                        ? "No hay ubicaciones en el rango de fechas seleccionado."
                        : "No hay ubicaciones en las últimas 24 horas."
                      : "Ninguna ruta pasa por el lugar elegido en este periodo."}
                  </p>
                )}
                {historialReciente.map((punto, index) => {
                  const fecha = parsearFechaGPS(punto.timestamp_gps);
                  const esInicio = index === historialReciente.length - 1;
                  const esActual = index === 0;
                  const claseFinal = siguiendoActual ? "current" : "end";
                  return (
                    <div className={`sidebar-item ${esActual ? "actual" : ""}`} key={index}>
                      <div className="sidebar-item-header">
                        <span
                          className={`legend-dot ${esInicio ? "start" : esActual ? claseFinal : ""}`}
                        ></span>
                        <span className="sidebar-item-time">
                          {fecha.toLocaleDateString("es-CO", OPCIONES_ZONA)} ·{" "}
                          {fecha.toLocaleTimeString("es-CO", OPCIONES_ZONA)}
                        </span>
                      </div>
                      <div className="coords-fila">
                        <div className="coord-row small">
                          <span className="coord-label">Lat</span>
                          <span>{Number(punto.latitud).toFixed(4)}</span>
                        </div>
                        <div className="coord-row small">
                          <span className="coord-label">Lon</span>
                          <span>{Number(punto.longitud).toFixed(4)}</span>
                        </div>
                      </div>
                      <p className="sidebar-item-ip">IP: {punto.ip_origen}</p>
                    </div>
                  );
                })}
              </div>
            </aside>
          </>
        ) : (
          <p className="empty-state">
            {ubicacionEstado === "vacio"
              ? "Aún no hay ubicaciones registradas."
              : ubicacionEstado === "error"
                ? "No se pudo cargar la ubicación. Reintentando…"
                : "Cargando ubicación..."}
          </p>
        )}
      </div>
    </div>
  );
}

export default App;
