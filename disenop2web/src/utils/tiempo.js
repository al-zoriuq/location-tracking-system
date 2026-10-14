// Time zone handling for the whole frontend.
//
// The backend sends timestamps as "YYYY-MM-DD HH:MM:SS" in Bogota wall-clock
// time WITHOUT zone. Colombia is UTC-05:00 all year (no daylight saving), so
// we attach that offset explicitly when parsing, and always format with
// timeZone "America/Bogota". Never use getHours()/getDate(): they return the
// BROWSER's zone, which is wrong for a user outside Colombia.

export const ZONA_BOGOTA = "America/Bogota";
const DESFASE_BOGOTA = "-05:00";

// "2026-09-24 07:12:00" (Bogota) -> Date (an absolute instant)
export function parsearFechaBogota(texto) {
  return new Date(texto.replace(" ", "T") + DESFASE_BOGOTA);
}

const formatoHora = new Intl.DateTimeFormat("es-CO", {
  timeZone: ZONA_BOGOTA,
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

const formatoHoraCorta = new Intl.DateTimeFormat("es-CO", {
  timeZone: ZONA_BOGOTA,
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

// Machine-readable parts (en-CA gives zero-padded ISO-like numbers)
const formatoPartes = new Intl.DateTimeFormat("en-CA", {
  timeZone: ZONA_BOGOTA,
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
  hourCycle: "h23",
});

export const formatearHora = (fecha) => formatoHora.format(fecha); // 07:12:05
export const formatearHoraCorta = (fecha) => formatoHoraCorta.format(fecha); // 07:12

function partesBogota(fecha) {
  const partes = {};
  for (const { type, value } of formatoPartes.formatToParts(fecha)) {
    partes[type] = value;
  }
  return partes;
}

// Dates are assembled from numeric parts: the "es-CO" locale ignores
// month: "2-digit" and would print 24/9 instead of 24/09.
export function formatearFecha(fecha) {
  const p = partesBogota(fecha);
  return `${p.day}/${p.month}/${p.year}`; // 24/09/2026
}

export function formatearDiaMes(fecha) {
  const p = partesBogota(fecha);
  return `${p.day}/${p.month}`; // 24/09
}

// Today's date in Bogota as "YYYY-MM-DD" (the format of <input type="date">)
export function hoyBogota(fecha = new Date()) {
  const p = partesBogota(fecha);
  return `${p.year}-${p.month}-${p.day}`;
}

// A Date as the backend format "YYYY-MM-DD HH:MM:SS" in Bogota time
export function aTextoBogota(fecha) {
  const p = partesBogota(fecha);
  return `${p.year}-${p.month}-${p.day} ${p.hour}:${p.minute}:${p.second}`;
}

// "hace 3 min", "hace 2 h"... relative to now
export function haceCuanto(fecha, ahora = new Date()) {
  const segundos = Math.max(0, Math.floor((ahora - fecha) / 1000));
  if (segundos < 60) return `hace ${segundos} s`;
  const minutos = Math.floor(segundos / 60);
  if (minutos < 60) return `hace ${minutos} min`;
  const horas = Math.floor(minutos / 60);
  if (horas < 24) return `hace ${horas} h`;
  return `hace ${Math.floor(horas / 24)} d`;
}
