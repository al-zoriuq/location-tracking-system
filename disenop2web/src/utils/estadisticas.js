import { distanciaMetros } from "./viajes";

// Top speed is measured over windows of at least this many seconds.
// GPS noise is ~±3 m per axis: between two fixes 10 s apart that alone can
// fake ±3 km/h. Over >= 30 s the same error is diluted to about ±1 km/h.
export const VENTANA_VELOCIDAD_S = 30;

// Statistics of the route on screen. `tramos` is a list of point lists
// (one per trip), so a pass window that spans two trips never counts the
// jump between them as distance.
export function calcularEstadisticas(tramos) {
  let distanciaM = 0;
  let duracionS = 0;
  let maximaKmh = 0;
  let puntos = 0;

  for (const tramo of tramos) {
    puntos += tramo.length;
    if (tramo.length < 2) continue;

    for (let i = 1; i < tramo.length; i++) {
      distanciaM += distanciaMetros(tramo[i - 1], tramo[i]);
    }
    duracionS += (tramo[tramo.length - 1].fecha - tramo[0].fecha) / 1000;

    // Two pointers: for each i, the first j at least 30 s later. Straight-line
    // displacement i -> j (not the summed path, which would add up the noise
    // of every segment instead of averaging it out).
    let j = 1;
    for (let i = 0; i < tramo.length; i++) {
      j = Math.max(j, i + 1);
      while (j < tramo.length && (tramo[j].fecha - tramo[i].fecha) / 1000 < VENTANA_VELOCIDAD_S) {
        j++;
      }
      if (j >= tramo.length) break;
      const dtS = (tramo[j].fecha - tramo[i].fecha) / 1000;
      maximaKmh = Math.max(maximaKmh, (distanciaMetros(tramo[i], tramo[j]) / dtS) * 3.6);
    }
  }

  if (puntos === 0) return null;
  return {
    distanciaM,
    duracionS,
    promedioKmh: duracionS > 0 ? (distanciaM / duracionS) * 3.6 : 0,
    maximaKmh,
  };
}
