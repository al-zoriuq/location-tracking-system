import { RADIOS_M } from "./lugar";
import { aTextoBogota, parsearFechaBogota } from "./tiempo";

// Idea D: the shareable state lives in the URL query string:
//   ?desde=...&hasta=...   date range (Entrega 1)
//   &lat=...&lon=...&radio=...   place (Entrega 2)
//   &ruta=...              pinned trip id (timestamp of its first point)
// Everything read from the URL is validated: a hand-edited or stale link
// must never crash the app or send the backend a malformed query.

const PATRON_FECHA = /^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$/;

// Round-trip check: new Date() silently turns "2026-02-30" into March 2nd,
// so the text must format back to exactly itself to be a real date.
function fechaValida(texto) {
  if (!texto || !PATRON_FECHA.test(texto)) return false;
  const fecha = parsearFechaBogota(texto);
  return !Number.isNaN(fecha.getTime()) && aTextoBogota(fecha) === texto;
}

function numeroEn(texto, minimo, maximo) {
  if (texto === null || texto.trim() === "") return null;
  const valor = Number(texto);
  return Number.isFinite(valor) && valor >= minimo && valor <= maximo ? valor : null;
}

export function leerEstadoUrl(busqueda = window.location.search) {
  const q = new URLSearchParams(busqueda);
  const estado = { rango: null, lugar: null, radio: null, ruta: null };
  const ahora = new Date();

  // Same rules as the date filter: Desde not in the future, Hasta clamped
  // to now, Desde before Hasta
  const desde = q.get("desde");
  let hasta = q.get("hasta");
  if (fechaValida(desde) && fechaValida(hasta) && parsearFechaBogota(desde) <= ahora) {
    if (parsearFechaBogota(hasta) > ahora) hasta = aTextoBogota(ahora);
    if (parsearFechaBogota(desde) < parsearFechaBogota(hasta)) estado.rango = { desde, hasta };
  }

  const lat = numeroEn(q.get("lat"), -90, 90);
  const lon = numeroEn(q.get("lon"), -180, 180);
  if (lat !== null && lon !== null) estado.lugar = { lat, lon };

  const radio = numeroEn(q.get("radio"), 0, Infinity);
  if (RADIOS_M.includes(radio)) estado.radio = radio; // only the offered options

  const ruta = q.get("ruta");
  if (fechaValida(ruta)) estado.ruta = ruta;

  return estado;
}

// replaceState (not pushState): the URL follows the state without adding an
// entry to the browser history for every click
export function escribirEstadoUrl({ rango, lugar, radio, ruta }) {
  const q = new URLSearchParams();
  if (rango) {
    q.set("desde", rango.desde);
    q.set("hasta", rango.hasta);
  }
  if (lugar) {
    q.set("lat", lugar.lat.toFixed(6));
    q.set("lon", lugar.lon.toFixed(6));
    q.set("radio", String(radio));
  }
  if (ruta) q.set("ruta", ruta);

  const texto = q.toString();
  const nueva = `${window.location.pathname}${texto ? `?${texto}` : ""}${window.location.hash}`;
  const actual = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (nueva !== actual) window.history.replaceState(null, "", nueva);
}

// Copies text to the clipboard. navigator.clipboard only exists in secure
// contexts (https or localhost); over plain http it is undefined, so fall
// back to the older execCommand("copy") with a temporary textarea.
export async function copiarTexto(texto) {
  if (navigator.clipboard?.writeText) {
    try {
      await navigator.clipboard.writeText(texto);
      return true;
    } catch {
      // permission denied: try the fallback below
    }
  }
  const area = document.createElement("textarea");
  area.value = texto;
  area.setAttribute("readonly", "");
  area.style.position = "fixed";
  area.style.opacity = "0";
  document.body.appendChild(area);
  area.select();
  let copiado;
  try {
    copiado = document.execCommand("copy");
  } catch {
    copiado = false;
  }
  area.remove();
  return copiado;
}
