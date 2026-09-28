// Run with:  node --test disenop2web/src/saltos.test.js
import test from "node:test";
import assert from "node:assert/strict";
import { descartarSaltosAislados } from "./saltos.js";

// timestamp_gps text for "seconds after 08:00:00"
const ts = (seg) => {
  const h = String(8 + Math.floor(seg / 3600)).padStart(2, "0");
  const m = String(Math.floor((seg % 3600) / 60)).padStart(2, "0");
  const s = String(seg % 60).padStart(2, "0");
  return `2026-09-27 ${h}:${m}:${s}`;
};
const fila = (lat, lon, seg) => ({ latitud: lat, longitud: lon, timestamp_gps: ts(seg) });
// n points 10 s apart, moving north ~33 m per point
const ruta = (n, lat0, lon0, seg0 = 0) =>
  Array.from({ length: n }, (_, i) => fila(lat0 + i * 0.0003, lon0, seg0 + i * 10));

// Same rule the app uses to start a new route: > 1 h apart or > 1 km apart
const RADIO = 6371000;
const rad = (g) => (g * Math.PI) / 180;
const metros = (a, b) => {
  const dLat = rad(b.latitud - a.latitud);
  const dLon = rad(b.longitud - a.longitud);
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(rad(a.latitud)) * Math.cos(rad(b.latitud)) * Math.sin(dLon / 2) ** 2;
  return 2 * RADIO * Math.asin(Math.sqrt(h));
};
const segs = (f) => Number(f.timestamp_gps.slice(11, 13)) * 3600 + Number(f.timestamp_gps.slice(14, 16)) * 60 + Number(f.timestamp_gps.slice(17, 19));
const dividir = (filas) => {
  const rutas = [[filas[0]]];
  for (let i = 1; i < filas.length; i++) {
    const corte = segs(filas[i]) - segs(filas[i - 1]) > 3600 || metros(filas[i - 1], filas[i]) > 1000;
    if (corte) rutas.push([filas[i]]);
    else rutas[rutas.length - 1].push(filas[i]);
  }
  return rutas;
};

test("descarta un punto aislado lejano y conserva el resto en orden", () => {
  const r = ruta(60, 10.9, -74.8);
  r[30] = fila(11.4, -74.8, 300); // ~55 km lejos, y el siguiente vuelve
  const limpio = descartarSaltosAislados(r);
  assert.equal(limpio.length, 59);
  assert.ok(!limpio.includes(r[30]));
  assert.deepEqual(limpio.map((f) => f.timestamp_gps), r.filter((_, i) => i !== 30).map((f) => f.timestamp_gps));
});

test("sin filtro el pico parte la ruta en tres; con filtro queda una sola", () => {
  const r = ruta(60, 10.9, -74.8);
  r[30] = fila(11.4, -74.8, 300);
  assert.equal(dividir(r).length, 3);
  assert.equal(dividir(descartarSaltosAislados(r)).length, 1);
});

test("un traslado real (reaparece lejos y se queda) no se toca", () => {
  const a = ruta(20, 10.98, -74.8, 0);
  const b = ruta(20, 4.711, -74.0721, 200); // Bogota, 10 s despues del ultimo punto de A
  const todo = [...a, ...b];
  assert.equal(descartarSaltosAislados(todo), todo);
  assert.equal(dividir(descartarSaltosAislados(todo)).length, 2);
});

test("un traslado tras una pausa larga (caso Barranquilla -> Bogota) no se toca", () => {
  const todo = [
    fila(10.987654, -74.123456, 0),
    fila(10.9877, -74.1235, 10),
    fila(4.711, -74.0721, 60),
    fila(4.71105, -74.07215, 12600), // 3.5 h despues
  ];
  assert.equal(descartarSaltosAislados(todo), todo);
  assert.equal(dividir(todo).length, 3); // se corta por distancia y por tiempo, como antes
});

test("un salto entre dos puntos separados por mas de una hora no se toma por pico", () => {
  const a = ruta(10, 10.9, -74.8, 0);
  const lejos = fila(11.4, -74.8, 3 * 3600); // 3 h despues
  const vuelve = fila(10.9, -74.8, 3 * 3600 + 10);
  const todo = [...a, lejos, vuelve];
  assert.equal(descartarSaltosAislados(todo), todo);
});

test("no toca ni el primero ni el ultimo punto", () => {
  const r = ruta(10, 10.9, -74.8);
  r[0] = fila(11.4, -74.8, 0);
  r[9] = fila(11.4, -74.8, 90);
  assert.equal(descartarSaltosAislados(r), r);
});

test("dos puntos erroneos seguidos NO se detectan (limite conocido)", () => {
  const r = ruta(30, 10.9, -74.8);
  r[15] = fila(11.4, -74.8, 150);
  r[16] = fila(11.4001, -74.8, 160);
  assert.equal(descartarSaltosAislados(r).length, 30);
});

test("descarta varios picos aislados de una misma ruta", () => {
  const r = ruta(60, 10.9, -74.8);
  r[10] = fila(11.4, -74.8, 100);
  r[30] = fila(10.4, -74.8, 300);
  r[50] = fila(11.2, -74.6, 500);
  const limpio = descartarSaltosAislados(r);
  assert.equal(limpio.length, 57);
  assert.equal(dividir(limpio).length, 1);
});

test("muestreo espaciado a velocidad de autopista (1,7 km entre puntos) no se confunde con pico", () => {
  // 1 punto por minuto a ~100 km/h: cada paso supera 1 km, pero los vecinos estan a 3,4 km
  const r = Array.from({ length: 10 }, (_, i) => fila(10.9 + i * 0.015, -74.8, i * 60));
  assert.equal(descartarSaltosAislados(r), r);
});

test("devuelve el mismo arreglo si no descarta nada (para no recalcular)", () => {
  const r = ruta(30, 10.9, -74.8);
  assert.equal(descartarSaltosAislados(r), r);
});

test("con menos de tres puntos no hace nada", () => {
  const r = ruta(2, 10.9, -74.8);
  assert.equal(descartarSaltosAislados(r), r);
  assert.deepEqual(descartarSaltosAislados([]), []);
});
