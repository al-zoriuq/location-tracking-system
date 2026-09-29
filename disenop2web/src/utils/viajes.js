import { parsearFechaBogota, formatearDiaMes, formatearHoraCorta } from "./tiempo";

// Trip-splitting thresholds. They MUST match the constants in
// analisis_lugar.py (backend, Entrega 2) so both sides agree on which
// consecutive points belong to the same trip.
export const MAX_PAUSA_MS = 60 * 60 * 1000; // > 1 h without points -> new trip
export const MAX_SALTO_M = 1000; // > 1 km between points -> new trip
export const MAX_VELOCIDAD_KMH = 180; // faster -> GPS error, point discarded

const RADIO_TIERRA_M = 6371008.8;
const aRad = (grados) => (grados * Math.PI) / 180;

// Great-circle (Haversine) distance in meters between two {lat, lon}
export function distanciaMetros(a, b) {
  const dLat = aRad(b.lat - a.lat);
  const dLon = aRad(b.lon - a.lon);
  const h =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(aRad(a.lat)) * Math.cos(aRad(b.lat)) * Math.sin(dLon / 2) ** 2;
  return 2 * RADIO_TIERRA_M * Math.asin(Math.sqrt(h));
}

// API row -> point with numeric lat/lon and a parsed Date
export function normalizarPunto(fila) {
  return {
    ...fila,
    lat: Number(fila.latitud),
    lon: Number(fila.longitud),
    fecha: parsearFechaBogota(fila.timestamp_gps),
  };
}

// Splits rows (sorted by timestamp_gps ascending) into trips.
//
// Each point is compared against the LAST ACCEPTED point, in this order:
//   1. more than 1 h apart           -> start a new trip (no speed check,
//      a vehicle can reappear far away after being off for a while)
//   2. implied speed > 180 km/h      -> GPS error: discard the point
//   3. more than 1 km apart          -> start a new trip
//   4. otherwise                     -> same trip
// Comparing against the last ACCEPTED point (not the previous raw one)
// keeps a single wild point from also breaking the point after it.
//
// A trip's id is the timestamp of its first point: stable while the live
// 24 h window slides, unlike its position in the list.
export function separarEnViajes(filas) {
  const viajes = [];
  let actual = null;
  let ultimo = null;

  for (const fila of filas) {
    const punto = normalizarPunto(fila);
    if (!Number.isFinite(punto.lat) || !Number.isFinite(punto.lon)) continue;

    let distancia = 0;
    if (ultimo) {
      const dtMs = punto.fecha - ultimo.fecha;
      if (dtMs <= 0) continue; // duplicate or out-of-order timestamp

      if (dtMs > MAX_PAUSA_MS) {
        actual = null;
      } else {
        distancia = distanciaMetros(ultimo, punto);
        const kmh = (distancia / (dtMs / 1000)) * 3.6;
        if (kmh > MAX_VELOCIDAD_KMH) {
          actual.descartados += 1;
          continue;
        }
        if (distancia > MAX_SALTO_M) actual = null;
      }
    }

    if (!actual) {
      actual = { id: punto.timestamp_gps, puntos: [], distanciaM: 0, descartados: 0 };
      viajes.push(actual);
    } else {
      actual.distanciaM += distancia;
    }
    actual.puntos.push(punto);
    ultimo = punto;
  }

  return viajes.map((viaje) => ({
    ...viaje,
    inicio: viaje.puntos[0].fecha,
    fin: viaje.puntos[viaje.puntos.length - 1].fecha,
  }));
}

const formatoKm = new Intl.NumberFormat("es-CO", {
  minimumFractionDigits: 1,
  maximumFractionDigits: 1,
});

export const formatearKm = (metros) => `${formatoKm.format(metros / 1000)} km`;

// "Ruta 3 · 24/09 · 07:12–07:48 · 5,2 km"
export function etiquetaViaje(viaje, numero) {
  return [
    `Ruta ${numero}`,
    formatearDiaMes(viaje.inicio),
    `${formatearHoraCorta(viaje.inicio)}–${formatearHoraCorta(viaje.fin)}`,
    formatearKm(viaje.distanciaM),
  ].join(" · ");
}

// Speed (km/h) between the latest position and the previous point of the
// current trip, or null when there is no recent previous point (> 1 h).
export function velocidadEstimada(ubicacion, viaje) {
  if (!ubicacion || !viaje) return null;
  const actual = normalizarPunto(ubicacion);
  const anterior = [...viaje.puntos].reverse().find((p) => p.fecha < actual.fecha);
  if (!anterior) return null;
  const dtS = (actual.fecha - anterior.fecha) / 1000;
  if (dtS * 1000 > MAX_PAUSA_MS) return null;
  return (distanciaMetros(anterior, actual) / dtS) * 3.6;
}

// Position at an instant (Date or ms) on a time-ordered list of points, by
// linear interpolation between the two samples around it (same assumption as
// the backend: constant speed between consecutive points). null outside the
// route's time span. Binary search: O(log n), called ~60 times per second
// during playback (idea B).
export function posicionEnInstante(puntos, instante) {
  const t = typeof instante === "number" ? instante : instante.getTime();
  if (puntos.length === 0) return null;
  const primero = puntos[0].fecha.getTime();
  const ultimo = puntos[puntos.length - 1].fecha.getTime();
  if (t < primero || t > ultimo) return null;
  if (puntos.length === 1) return [puntos[0].lat, puntos[0].lon];

  // Last index whose time is <= t
  let bajo = 0;
  let alto = puntos.length - 1;
  while (bajo < alto) {
    const medio = Math.ceil((bajo + alto) / 2);
    if (puntos[medio].fecha.getTime() <= t) bajo = medio;
    else alto = medio - 1;
  }
  const a = puntos[bajo];
  const b = puntos[Math.min(bajo + 1, puntos.length - 1)];
  const dt = b.fecha - a.fecha;
  const f = dt > 0 ? (t - a.fecha.getTime()) / dt : 0;
  return [a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon)];
}
