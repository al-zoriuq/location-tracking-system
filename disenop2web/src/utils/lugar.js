import { aTextoBogota, parsearFechaBogota } from "./tiempo";

export const RADIOS_M = [50, 100, 200, 500];
export const MARGEN_PASO_MS = 10 * 60 * 1000; // history shown around a pass: ±10 min

// "YYYY-MM-DD HH:MM:SS" (Bogota) shifted by some milliseconds
export function desplazarTexto(texto, ms) {
  return aTextoBogota(new Date(parsearFechaBogota(texto).getTime() + ms));
}

// Position at instant `fecha` on a time-ordered list of points, by linear
// interpolation between the two samples around it (same assumption as the
// backend: constant speed between consecutive points).
function posicionEn(puntos, fecha) {
  for (let i = 0; i < puntos.length - 1; i++) {
    const a = puntos[i];
    const b = puntos[i + 1];
    if (a.fecha <= fecha && fecha <= b.fecha) {
      const f = b.fecha - a.fecha ? (fecha - a.fecha) / (b.fecha - a.fecha) : 0;
      return [a.lat + f * (b.lat - a.lat), a.lon + f * (b.lon - a.lon)];
    }
  }
  return null;
}

// Stretch of the route between two instants (the part inside the circle),
// including the interpolated entry and exit positions.
export function tramoEntre(puntos, inicio, fin) {
  const tramo = [];
  const entrada = posicionEn(puntos, inicio);
  if (entrada) tramo.push(entrada);
  for (const p of puntos) {
    if (p.fecha > inicio && p.fecha < fin) tramo.push([p.lat, p.lon]);
  }
  const salida = posicionEn(puntos, fin);
  if (salida) tramo.push(salida);
  return tramo;
}

// 509 -> "8 min 29 s"
export function formatearDuracion(segundos) {
  if (segundos < 60) return `${segundos} s`;
  const horas = Math.floor(segundos / 3600);
  const minutos = Math.floor((segundos % 3600) / 60);
  const resto = segundos % 60;
  if (horas) return `${horas} h ${minutos} min`;
  return resto ? `${minutos} min ${resto} s` : `${minutos} min`;
}
