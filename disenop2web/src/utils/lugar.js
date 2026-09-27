import { aTextoBogota, parsearFechaBogota } from "./tiempo";
import { posicionEnInstante } from "./viajes";

export const RADIOS_M = [50, 100, 200];
export const MARGEN_PASO_MS = 10 * 60 * 1000; // history shown around a pass: ±10 min

// "YYYY-MM-DD HH:MM:SS" (Bogota) shifted by some milliseconds
export function desplazarTexto(texto, ms) {
  return aTextoBogota(new Date(parsearFechaBogota(texto).getTime() + ms));
}

// Stretch of the route between two instants (the part inside the circle),
// including the interpolated entry and exit positions.
export function tramoEntre(puntos, inicio, fin) {
  const tramo = [];
  const entrada = posicionEnInstante(puntos, inicio);
  if (entrada) tramo.push(entrada);
  for (const p of puntos) {
    if (p.fecha > inicio && p.fecha < fin) tramo.push([p.lat, p.lon]);
  }
  const salida = posicionEnInstante(puntos, fin);
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
