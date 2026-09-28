import { calcularDistanciaMetros } from "./geo.js";

// Seconds of history the speed is measured over. GPS noise is about +-3 m per
// axis: between two fixes 10 s apart that alone can fake +-3 km/h, and over 30 s
// it is diluted to about +-1 km/h (the same window the route's top speed uses).
export const VENTANA_VELOCIDAD_S = 30;
// Below this the vehicle is treated as stopped (GPS jitter while standing still)
export const VELOCIDAD_MINIMA_KMH = 3;

// puntos: the route's points ({lat, lon, fecha: Date}), oldest first.
// Returns km/h, or null when the route is too short to measure.
export function velocidadActual(puntos) {
  if (puntos.length < 2) return null;

  const ultimo = puntos[puntos.length - 1];
  const tUltimo = ultimo.fecha.getTime();

  // The most recent point that is at least VENTANA_VELOCIDAD_S older than the last one
  let i = puntos.length - 2;
  while (i >= 0 && tUltimo - puntos[i].fecha.getTime() < VENTANA_VELOCIDAD_S * 1000) i--;
  if (i < 0) return null;

  const dtS = (tUltimo - puntos[i].fecha.getTime()) / 1000;
  const metros = calcularDistanciaMetros(puntos[i].lat, puntos[i].lon, ultimo.lat, ultimo.lon);
  const kmh = (metros / dtS) * 3.6;
  return kmh < VELOCIDAD_MINIMA_KMH ? 0 : kmh;
}
