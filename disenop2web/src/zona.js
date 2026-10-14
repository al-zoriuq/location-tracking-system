// All GPS timestamps are stored as Barranquilla wall-clock time (no timezone
// in the database), so both parsing and display are pinned to this zone.
export const ZONA = "America/Bogota";
export const DESFASE_ZONA = "-05:00";
export const OPCIONES_ZONA = { timeZone: ZONA };
export const OPCIONES_HORA_CORTA = { timeZone: ZONA, hour: "2-digit", minute: "2-digit" };

// "2026-09-24 10:35:12.345" (database text) -> Date
export function parsearFechaGPS(timestampTexto) {
  return new Date(timestampTexto.replace(" ", "T") + DESFASE_ZONA);
}

// "10:35 a. m."
export function formatoHora(fecha) {
  return fecha.toLocaleTimeString("es-CO", OPCIONES_HORA_CORTA);
}

// Upper-case the first letter only: "jueves" -> "Jueves", "24 de sept" stays as is
function capitalizar(texto) {
  return texto.charAt(0).toUpperCase() + texto.slice(1);
}

// "Jue, 24 sept"
export function formatoDiaCorto(fecha) {
  return capitalizar(fecha.toLocaleDateString("es-CO", {
    timeZone: ZONA,
    weekday: "short",
    day: "numeric",
    month: "short",
  }));
}

// "Jueves, 24 de septiembre de 2026"
export function formatoDiaLargo(fecha) {
  return capitalizar(fecha.toLocaleDateString("es-CO", {
    timeZone: ZONA,
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
  }));
}
