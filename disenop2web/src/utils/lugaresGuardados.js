import { RADIOS_M } from "./lugar";

// Idea F: named places ("Casa", "Uninorte") kept in this browser.
//
// localStorage can fail in three ways: it may not exist, reading may throw
// (storage blocked by the user or a policy) and writing may throw (Safari
// private mode, quota exceeded). Every access is wrapped in try/catch and
// the app keeps working without it. What is read is validated like any
// external input: it may have been edited by hand.

const CLAVE = "gpslink.lugares";
export const MAX_NOMBRE = 40;

function lugarValido(l) {
  return (
    l !== null &&
    typeof l === "object" &&
    typeof l.nombre === "string" &&
    l.nombre.trim().length > 0 &&
    l.nombre.length <= MAX_NOMBRE &&
    Number.isFinite(l.lat) &&
    Math.abs(l.lat) <= 90 &&
    Number.isFinite(l.lon) &&
    Math.abs(l.lon) <= 180
  );
}

export function leerLugares() {
  try {
    const texto = window.localStorage.getItem(CLAVE);
    const datos = texto ? JSON.parse(texto) : [];
    if (!Array.isArray(datos)) return [];
    return datos
      .filter(lugarValido)
      .map((l) => ({ ...l, radio: RADIOS_M.includes(l.radio) ? l.radio : 100 }));
  } catch {
    return []; // unavailable or corrupted: start empty
  }
}

// Returns false if the list could not be persisted
export function escribirLugares(lista) {
  try {
    window.localStorage.setItem(CLAVE, JSON.stringify(lista));
    return true;
  } catch {
    return false;
  }
}

// Adds or replaces (same name, case-insensitive) a place
export function conLugar(lista, nuevo) {
  const clave = nuevo.nombre.toLocaleLowerCase("es");
  return [...lista.filter((l) => l.nombre.toLocaleLowerCase("es") !== clave), nuevo];
}
