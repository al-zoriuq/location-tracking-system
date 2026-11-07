// Run with:  node --test disenop2web/src/senales.test.js
import test from "node:test";
import assert from "node:assert/strict";
import {
  normalizarDeteccion,
  asignarSenalesARutas,
  nombreSenal,
  estadoSenal,
  velocidadTexto,
  contarExcesos,
  MARGEN_RUTA_MS,
} from "./senales.js";

const punto = (ts) => ({ timestamp_gps: ts, latitud: 11, longitud: -74.8 });
const det = (id, ts, extra = {}) =>
  normalizarDeteccion({ id, timestamp_evento: ts, latitud: "11.03", longitud: "-74.86", ...extra });

// Route A 09:00-09:10, route B starts 09:11 (split by distance, 1 min apart),
// route C 12:00-12:30
const RUTAS = [
  [punto("2026-11-06 09:00:00"), punto("2026-11-06 09:10:00")],
  [punto("2026-11-06 09:11:00"), punto("2026-11-06 09:20:00")],
  [punto("2026-11-06 12:00:00"), punto("2026-11-06 12:30:00")],
];

test("normaliza lat/lon y la hora de Bogota", () => {
  const d = det(1, "2026-11-03 07:50:28");
  assert.equal(d.lat, 11.03);
  assert.equal(d.lon, -74.86);
  assert.equal(d.fecha.toISOString(), "2026-11-03T12:50:28.000Z");
});

test("cada deteccion va a la ruta que la contiene, ordenadas por hora", () => {
  const r = asignarSenalesARutas(
    [det(2, "2026-11-06 12:15:00"), det(1, "2026-11-06 09:05:00"), det(3, "2026-11-06 12:01:00")],
    RUTAS
  );
  assert.deepEqual(r.map((l) => l.map((d) => d.id)), [[1], [], [3, 2]]);
});

test("entre dos rutas cercanas gana la mas proxima, sin repetir", () => {
  // 09:10:20 is 20 s after A ends and 40 s before B starts
  const r = asignarSenalesARutas([det(1, "2026-11-06 09:10:20")], RUTAS);
  assert.deepEqual(r.map((l) => l.length), [1, 0, 0]);
});

test("con pos-45s la deteccion puede caer poco despues del ultimo punto", () => {
  const r = asignarSenalesARutas([det(1, "2026-11-06 12:31:30")], RUTAS);
  assert.equal(r[2].length, 1);
});

test("lejos de toda ruta no se muestra", () => {
  const t = new Date(Date.parse("2026-11-06T12:30:00-05:00") + MARGEN_RUTA_MS + 1000);
  const ts = t.toLocaleString("sv-SE", { timeZone: "America/Bogota" });
  const r = asignarSenalesARutas([det(1, ts), det(2, "2026-11-06 15:00:00")], RUTAS);
  assert.deepEqual(r.map((l) => l.length), [0, 0, 0]);
});

test("sin rutas no falla", () => {
  assert.deepEqual(asignarSenalesARutas([det(1, "2026-11-06 09:05:00")], []), []);
});

test("nombres, estado y velocidad", () => {
  assert.equal(nombreSenal({ senal_tipo: "LIMITE", senal_valor: 30 }), "Límite 30 km/h");
  assert.equal(nombreSenal({ senal_tipo: "PARE" }), "Pare");
  assert.equal(nombreSenal({ senal_tipo: "CEDA" }), "Ceda el paso");
  assert.equal(nombreSenal({ senal_tipo: "ESCOLAR", senal_texto: "ESCOLAR" }), "Escolar");

  assert.equal(estadoSenal({ cumplimiento: "EXCEDE" }).clave, "excede");
  assert.equal(estadoSenal({ cumplimiento: "SI" }).clave, "cumple");
  assert.equal(estadoSenal({ cumplimiento: "NA" }).clave, "na");

  assert.equal(velocidadTexto({ velocidad: 41.4, vel_fuente: "GPS" }), "41 km/h (GPS)");
  assert.equal(velocidadTexto({ velocidad: null, vel_fuente: "NA" }), null);

  assert.equal(contarExcesos([{ cumplimiento: "EXCEDE" }, { cumplimiento: "SI" }, { cumplimiento: "EXCEDE" }]), 2);
});
