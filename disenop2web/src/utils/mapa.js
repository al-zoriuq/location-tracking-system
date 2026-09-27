// Helpers shared by every piece of code that moves the Leaflet map.

// ---------------------------------------------------------------------------
// Programmatic vs. user movement
//
// Leaflet fires "zoomstart" both for a mouse-wheel zoom and for our own
// flyTo/fitBounds, so the event alone cannot tell who moved the map. Every
// move made by code goes through moverProgramaticamente(), which marks the
// map until the move ends; a zoomstart on an unmarked map came from the user.
// ("dragstart" needs no help: Leaflet only fires it for user drags.)
// ---------------------------------------------------------------------------
const enMovimientoProgramatico = new WeakSet();
const SEGURIDAD_MS = 4000; // clears the mark even if "moveend" never arrives

export function moverProgramaticamente(map, mover) {
  enMovimientoProgramatico.add(map);
  let terminado = false;
  const terminar = () => {
    if (terminado) return;
    terminado = true;
    clearTimeout(temporizador);
    enMovimientoProgramatico.delete(map);
  };
  const temporizador = setTimeout(terminar, SEGURIDAD_MS);
  map.once("moveend", terminar);
  mover();
}

export const esMovimientoProgramatico = (map) => enMovimientoProgramatico.has(map);

// ---------------------------------------------------------------------------
// Free area: the part of the map NOT covered by the floating controls column
//
// The column (.controles) sits on the left on desktop and across the top on
// phones. Centering on the whole map would leave the target (or its popup)
// under the cards, so we center on the free rectangle instead.
// ---------------------------------------------------------------------------
const MARGEN_PX = 12;

// Free rectangle in container pixels: {x0, y0, x1, y1}
export function zonaLibre(map) {
  const contenedor = map.getContainer();
  const ancho = contenedor.clientWidth;
  const alto = contenedor.clientHeight;
  const completa = { x0: 0, y0: 0, x1: ancho, y1: alto };

  const columna = contenedor.parentElement?.querySelector(".controles");
  // Panels hidden ("Ocultar paneles"): only a small button remains, the
  // whole map is free
  if (!columna || columna.classList.contains("controles-plegados")) return completa;

  // Union of the visible cards (the column box itself spans the full height
  // even when its cards are short)
  const rMapa = contenedor.getBoundingClientRect();
  const rColumna = columna.getBoundingClientRect();
  let derecha = 0;
  let abajo = 0;
  let hayTarjetas = false;
  for (const hijo of columna.children) {
    const r = hijo.getBoundingClientRect();
    if (!r.width || !r.height) continue;
    hayTarjetas = true;
    derecha = Math.max(derecha, r.right - rMapa.left);
    abajo = Math.max(abajo, Math.min(r.bottom, rColumna.bottom) - rMapa.top);
  }
  if (!hayTarjetas) return completa;

  // Never give away more than 80 % of the map, even with a huge column
  if (derecha >= 0.6 * ancho) {
    return { ...completa, y0: Math.min(abajo + MARGEN_PX, alto * 0.8) }; // column on top
  }
  return { ...completa, x0: Math.min(derecha + MARGEN_PX, ancho * 0.8) }; // column on the left
}

// Map center that places `latlng` in the middle of the free area at `zoom`
export function centroParaZonaLibre(map, latlng, zoom) {
  const z = zonaLibre(map);
  const contenedor = map.getContainer();
  const dx = (z.x0 + z.x1) / 2 - contenedor.clientWidth / 2;
  const dy = (z.y0 + z.y1) / 2 - contenedor.clientHeight / 2;
  return map.unproject(map.project(latlng, zoom).subtract([dx, dy]), zoom);
}

// Is `latlng` inside the central `fraccion` (60 %) of the free area?
export function dentroDeZonaCentral(map, latlng, fraccion = 0.6) {
  const z = zonaLibre(map);
  const p = map.latLngToContainerPoint(latlng);
  const mx = ((z.x1 - z.x0) * (1 - fraccion)) / 2;
  const my = ((z.y1 - z.y0) * (1 - fraccion)) / 2;
  return p.x >= z.x0 + mx && p.x <= z.x1 - mx && p.y >= z.y0 + my && p.y <= z.y1 - my;
}

// fitBounds options that keep the fitted route out from under the column
export function rellenoZonaLibre(map, extra = 40) {
  const z = zonaLibre(map);
  return { paddingTopLeft: [z.x0 + extra, z.y0 + extra], paddingBottomRight: [extra, extra] };
}
