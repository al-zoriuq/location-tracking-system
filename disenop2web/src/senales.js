import { parsearFechaGPS } from "./zona.js";

// A sign seen a little before the first point or after the last one of a route
// (the ESP32 can send a position up to ~1 min old, "pos-45s") still belongs to
// it. Signs further away from every route are not shown.
export const MARGEN_RUTA_MS = 2 * 60 * 1000;

// API row -> detection with numeric lat/lon and a parsed Date
export function normalizarDeteccion(fila) {
  return {
    ...fila,
    lat: Number(fila.latitud),
    lon: Number(fila.longitud),
    fecha: parsearFechaGPS(fila.timestamp_evento),
  };
}

// Splits the detections among the routes on screen by time.
// rutas: arrays of API points (timestamp_gps), each sorted ascending.
// Returns one array per route, in the same order, each sorted by time.
// A detection inside a route's time span goes to that route; otherwise to the
// closest route within MARGEN_RUTA_MS (two routes can be only a minute apart
// when they were split by distance); otherwise it is left out.
export function asignarSenalesARutas(detecciones, rutas) {
  const tramos = rutas.map((puntos) => ({
    inicio: parsearFechaGPS(puntos[0].timestamp_gps).getTime(),
    fin: parsearFechaGPS(puntos[puntos.length - 1].timestamp_gps).getTime(),
  }));
  const porRuta = rutas.map(() => []);

  for (const d of detecciones) {
    const t = d.fecha.getTime();
    let mejor = -1;
    let mejorDistancia = Infinity;

    tramos.forEach(({ inicio, fin }, i) => {
      const distancia = t < inicio ? inicio - t : t > fin ? t - fin : 0;
      if (distancia <= MARGEN_RUTA_MS && distancia < mejorDistancia) {
        mejor = i;
        mejorDistancia = distancia;
      }
    });

    if (mejor !== -1) porRuta[mejor].push(d);
  }

  porRuta.forEach((lista) => lista.sort((a, b) => a.fecha - b.fecha));
  return porRuta;
}

// "LIMITE" 30 -> "Límite 30 km/h", "PARE" -> "Pare", "CEDA" -> "Ceda el paso"
export function nombreSenal(d) {
  switch (d.senal_tipo) {
    case "LIMITE":
      return d.senal_valor != null ? `Límite ${d.senal_valor} km/h` : "Límite de velocidad";
    case "PARE":
      return "Pare";
    case "CEDA":
      return "Ceda el paso";
    default: {
      const texto = (d.senal_texto || d.senal_tipo || "Señal").toLowerCase();
      return texto.charAt(0).toUpperCase() + texto.slice(1);
    }
  }
}

// SI / EXCEDE / NA -> css class + text
export function estadoSenal(d) {
  if (d.cumplimiento === "EXCEDE") return { clave: "excede", texto: "Excede" };
  if (d.cumplimiento === "SI") return { clave: "cumple", texto: "Cumple" };
  return { clave: "na", texto: "Sin evaluar" };
}

// 41 -> "41 km/h (GPS)"; no speed -> null
export function velocidadTexto(d) {
  if (d.velocidad == null) return null;
  const fuente = d.vel_fuente === "GPS" || d.vel_fuente === "MPU" ? ` (${d.vel_fuente})` : "";
  return `${Math.round(d.velocidad)} km/h${fuente}`;
}

export function contarExcesos(lista) {
  return lista.filter((d) => d.cumplimiento === "EXCEDE").length;
}

// Small road-sign drawing (HTML string) used by both the map marker and the
// list in the sidebar, so both look the same.
export function htmlSenal(d) {
  const excede = d.cumplimiento === "EXCEDE" ? " excede" : "";
  switch (d.senal_tipo) {
    case "LIMITE":
      return `<span class="senal senal-limite${excede}">${d.senal_valor ?? "?"}</span>`;
    case "PARE":
      return (
        '<span class="senal senal-pare">' +
        '<svg viewBox="0 0 24 24" aria-hidden="true"><polygon points="7,1 17,1 23,7 23,17 17,23 7,23 1,17 1,7" ' +
        'fill="#d7263d" stroke="#fff" stroke-width="1.6"/></svg><b>PARE</b></span>'
      );
    case "CEDA":
      return (
        '<span class="senal senal-ceda">' +
        '<svg viewBox="0 0 24 22" aria-hidden="true"><polygon points="1.5,1.5 22.5,1.5 12,20.5" ' +
        'fill="#fff" stroke="#d7263d" stroke-width="3" stroke-linejoin="round"/></svg></span>'
      );
    default:
      return `<span class="senal senal-otra${excede}">!</span>`;
  }
}
