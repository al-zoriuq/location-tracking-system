// Run with:  node --test disenop2web/src/velocidad.test.js
import test from "node:test";
import assert from "node:assert/strict";
import { velocidadActual } from "./velocidad.js";
import { calcularDistanciaMetros } from "./geo.js";

const punto = (lat, lon, seg) => ({ lat, lon, fecha: new Date(Date.UTC(2026, 8, 27, 13, 0, 0) + seg * 1000) });
const GRADOS_POR_METRO = 1 / 111195; // 1 grado de latitud ~ 111,2 km

// Vehicle heading north at a constant speed, one point every `cada` seconds
const conVelocidad = (kmh, n, cada = 10) =>
  Array.from({ length: n }, (_, i) => punto(10.9 + ((kmh / 3.6) * i * cada) * GRADOS_POR_METRO, -74.8, i * cada));

test("velocidad constante de 60 km/h con puntos cada 10 s", () => {
  const v = velocidadActual(conVelocidad(60, 20));
  assert.ok(Math.abs(v - 60) < 0.5, `salio ${v}`);
});

test("velocidad constante de 12 km/h (bicicleta) con puntos cada 5 s", () => {
  const v = velocidadActual(conVelocidad(12, 40, 5));
  assert.ok(Math.abs(v - 12) < 0.5, `salio ${v}`);
});

test("mide sobre la ventana de 30 s, no sobre el punto anterior", () => {
  // 20 min parado y, en los ultimos 30 s, acelera a 90 km/h: debe reflejarlo, no promediar
  const parado = Array.from({ length: 30 }, (_, i) => punto(10.9, -74.8, i * 10));
  const acelera = Array.from({ length: 4 }, (_, i) => punto(10.9 + ((90 / 3.6) * (i + 1) * 10) * GRADOS_POR_METRO, -74.8, 300 + i * 10));
  const v = velocidadActual([...parado, ...acelera]);
  assert.ok(Math.abs(v - 90) < 0.5, `salio ${v}`);
});

// Gaussian GPS noise of 3 m per axis (sigma), seeded so the test is repeatable.
// 3 m is the figure the route statistics (utils/estadisticas.js) already assume.
const ruidoGaussiano = (sigmaM, semilla = 12345) => {
  let s = semilla;
  const uniforme = () => (s = (s * 16807) % 2147483647) / 2147483647;
  return () => sigmaM * Math.sqrt(-2 * Math.log(uniforme() || 1e-12)) * Math.cos(2 * Math.PI * uniforme());
};
const vehiculoQuieto = (n, sigmaM) => {
  const ruido = ruidoGaussiano(sigmaM);
  return Array.from({ length: n }, (_, i) => punto(10.9 + ruido() * GRADOS_POR_METRO, -74.8 + ruido() * GRADOS_POR_METRO, i * 10));
};
// Speed from just the last two points (what the window is there to avoid)
const velocidadIngenua = (p) =>
  (calcularDistanciaMetros(p[p.length - 2].lat, p[p.length - 2].lon, p[p.length - 1].lat, p[p.length - 1].lon) / 10) * 3.6;

test("estando quieto, el ruido del GPS no inventa velocidad (en ningun punto final posible)", () => {
  const quieto = vehiculoQuieto(120, 3);
  for (let n = 4; n <= quieto.length; n++) {
    assert.equal(velocidadActual(quieto.slice(0, n)), 0, `con ${n} puntos dio ${velocidadActual(quieto.slice(0, n))}`);
  }
});

test("por que existe la ventana: con ruido de 3 m, usar solo los dos ultimos puntos si inventaria velocidad", () => {
  const quieto = vehiculoQuieto(120, 3);
  let peor = 0;
  for (let n = 2; n <= quieto.length; n++) peor = Math.max(peor, velocidadIngenua(quieto.slice(0, n)));
  assert.ok(peor > 3, `la version ingenua solo llego a ${peor.toFixed(1)} km/h`);
});

test("con ruido mas suave (1,5 m) tambien da 0", () => {
  const quieto = vehiculoQuieto(120, 1.5);
  assert.equal(velocidadActual(quieto), 0);
});

test("una ruta mas corta que la ventana no da velocidad", () => {
  assert.equal(velocidadActual(conVelocidad(60, 3)), null); // 20 s de recorrido
  assert.equal(velocidadActual([]), null);
  assert.equal(velocidadActual([punto(10.9, -74.8, 0)]), null);
});

test("con muestreo irregular usa el punto que cumple la ventana", () => {
  const p = [punto(10.9, -74.8, 0), punto(10.9 + 100 * GRADOS_POR_METRO, -74.8, 20), punto(10.9 + 500 * GRADOS_POR_METRO, -74.8, 60)];
  // el ultimo esta a 60 s del primero y a 40 s del segundo: usa el segundo (>= 30 s): 400 m / 40 s = 36 km/h
  assert.ok(Math.abs(velocidadActual(p) - 36) < 0.3);
});
