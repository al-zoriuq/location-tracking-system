import { useEffect, useState } from "react";
import { pedirJSON } from "./api.js";

// Coordinates are rounded like the server does (4 decimals, ~11 m): a parked
// device keeps the same key and never asks again, a moving one asks once per
// new spot (at most every 10 s, the refresh rate of the last position).
const DECIMALES = 4;
// After a failure, wait this long before asking for the same spot again
const REINTENTO_MS = 60 * 1000;

const clave = (lat, lon) =>
  Number.isFinite(lat) && Number.isFinite(lon)
    ? `${lat.toFixed(DECIMALES)},${lon.toFixed(DECIMALES)}`
    : null;

// Approximate address of a point, via /api/direccion.
// Returns { texto, estado } where estado is:
//   "cargando"  first request, nothing to show yet
//   "ok"        texto holds the address (the previous one stays while the next loads)
//   "sin-datos" the geocoder has no address for that spot
//   "error"     the request failed (texto keeps the last known address, if any)
export function useDireccion(lat, lon) {
  const [resultado, setResultado] = useState({ clave: null, texto: null, estado: "cargando" });
  const [intento, setIntento] = useState(0);
  const actual = clave(lat, lon);

  useEffect(() => {
    if (!actual) return;
    let cancelado = false;
    const [la, lo] = actual.split(",");

    pedirJSON(`${import.meta.env.BASE_URL}api/direccion?lat=${la}&lon=${lo}`)
      .then((datos) => {
        if (cancelado) return;
        setResultado(
          datos.direccion
            ? { clave: actual, texto: datos.direccion, estado: "ok" }
            : { clave: actual, texto: null, estado: "sin-datos" }
        );
      })
      .catch(() => {
        if (cancelado) return;
        setResultado((previo) => ({ ...previo, clave: actual, estado: "error" }));
      });

    return () => {
      cancelado = true;
    };
  }, [actual, intento]);

  // A failed spot is asked again after a while, even if the device does not move
  useEffect(() => {
    if (resultado.estado !== "error") return;
    const t = setTimeout(() => setIntento((n) => n + 1), REINTENTO_MS);
    return () => clearTimeout(t);
  }, [resultado]);

  if (!actual) return { texto: null, estado: "sin-datos" };
  // While a new spot loads, keep showing the previous address
  if (resultado.clave !== actual && resultado.texto) return { texto: resultado.texto, estado: "ok" };
  if (resultado.clave !== actual) return { texto: null, estado: "cargando" };
  return { texto: resultado.texto, estado: resultado.estado };
}

// Text for the card in each state
export function textoDireccion({ texto, estado }) {
  if (texto) return texto;
  if (estado === "cargando") return "Buscando dirección…";
  if (estado === "sin-datos") return "Sin dirección para este punto";
  return "Dirección no disponible";
}
