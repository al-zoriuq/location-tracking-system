import { calcularDistanciaMetros } from "./geo.js";
import { parsearFechaGPS } from "./zona.js";

// A single GPS point that lands far away while the next one is back where the
// vehicle was is a glitch, not a trip. Dropping it keeps one route from being
// cut into three (before / the stray point / after) and keeps it out of the
// distance, stops and speed figures.
//
// A point is a stray "spike" only when ALL of these hold:
//   - it is more than SALTO_MIN_M from the previous kept point AND from the next one
//   - those two neighbours are within SALTO_MIN_M of each other (the vehicle came back)
//   - both gaps in time are continuous (no longer than PAUSA_MAX_MS)
// A real relocation (the vehicle reappears far away and stays there) never
// matches, because its neighbours are far from each other.
//
// Known limit: two or more stray points in a row are not detected.
export const SALTO_MIN_M = 1000; // same distance that starts a new route
export const PAUSA_MAX_MS = 60 * 60 * 1000; // same gap that starts a new route

// rows: database rows sorted by timestamp_gps ascending.
// Returns the same array when nothing is dropped, so memoized consumers do
// not recompute.
export function descartarSaltosAislados(filas) {
  if (filas.length < 3) return filas;

  const lat = filas.map((f) => Number(f.latitud));
  const lon = filas.map((f) => Number(f.longitud));
  const t = filas.map((f) => parsearFechaGPS(f.timestamp_gps).getTime());
  const distancia = (a, b) => calcularDistanciaMetros(lat[a], lon[a], lat[b], lon[b]);

  const conservados = [0];
  for (let i = 1; i < filas.length - 1; i++) {
    const previo = conservados[conservados.length - 1];
    const siguiente = i + 1;

    const continuo = t[i] - t[previo] <= PAUSA_MAX_MS && t[siguiente] - t[i] <= PAUSA_MAX_MS;
    const esPico =
      continuo &&
      distancia(previo, i) > SALTO_MIN_M &&
      distancia(i, siguiente) > SALTO_MIN_M &&
      distancia(previo, siguiente) <= SALTO_MIN_M;

    if (!esPico) conservados.push(i);
  }
  conservados.push(filas.length - 1);

  return conservados.length === filas.length ? filas : conservados.map((i) => filas[i]);
}
