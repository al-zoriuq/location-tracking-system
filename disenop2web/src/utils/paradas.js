import { distanciaMetros } from "./viajes";

export const RADIO_PARADA_M = 50;
export const MIN_PARADA_S = 5 * 60;

// Idea C: stretches where the vehicle stayed >= 5 min within 50 m.
//
// Distances are measured against a fixed ANCHOR (the first point of the
// candidate stop), not point-to-point: in a traffic jam the vehicle may move
// only 3 m every 10 s, which point-to-point would never exceed 50 m, yet
// after a few minutes it is far from where it started.
//
// From anchor i, j grows while point j+1 is still within 50 m of i. If i..j
// lasts >= 5 min it is a stop (marked at the centroid of its points) and the
// search continues after j; otherwise it moves on to i+1.
export function detectarParadas(puntos) {
  const paradas = [];
  let i = 0;
  while (i < puntos.length) {
    let j = i;
    while (j + 1 < puntos.length && distanciaMetros(puntos[i], puntos[j + 1]) <= RADIO_PARADA_M) {
      j++;
    }
    const duracionS = (puntos[j].fecha - puntos[i].fecha) / 1000;
    if (duracionS >= MIN_PARADA_S) {
      const grupo = puntos.slice(i, j + 1);
      paradas.push({
        lat: grupo.reduce((suma, p) => suma + p.lat, 0) / grupo.length,
        lon: grupo.reduce((suma, p) => suma + p.lon, 0) / grupo.length,
        inicio: puntos[i].fecha,
        fin: puntos[j].fecha,
        duracionS,
      });
      i = j + 1;
    } else {
      i++;
    }
  }
  return paradas;
}
