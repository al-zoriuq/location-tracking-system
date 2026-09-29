import { calcularDistanciaMetros } from "./geo.js";
import { parsearFechaGPS } from "./zona.js";

// When was the vehicle at a place?
//
// A "visit" is an uninterrupted stretch of one route whose points fall inside
// the place's bounding box (the box Nominatim returned for a city, or the small
// box built around a single-point address). Leaving the box and coming back
// later, even within the same route, is a new visit.
//
// For each visit the exact spot is the recorded point that was closest to the
// place's center: for an address that is where the vehicle passed by, and for a
// whole city it is where it went nearest to the middle of it.
//
// rutas: the routes as produced by dividirEnRutas (arrays of database rows)
// lugar: {lat, lon, lat_min, lat_max, lon_min, lon_max}
// Returns the visits newest first. `indiceRuta` is the position of the route
// inside `rutas`, i.e. the "Ruta N" number minus one.
export function calcularVisitas(rutas, lugar) {
  if (!lugar) return [];

  const centroLat = Number.isFinite(lugar.lat) ? lugar.lat : (lugar.lat_min + lugar.lat_max) / 2;
  const centroLon = Number.isFinite(lugar.lon) ? lugar.lon : (lugar.lon_min + lugar.lon_max) / 2;

  const dentro = (p) => {
    const lat = Number(p.latitud);
    const lon = Number(p.longitud);
    return (
      lat >= lugar.lat_min && lat <= lugar.lat_max && lon >= lugar.lon_min && lon <= lugar.lon_max
    );
  };

  const visitas = [];

  rutas.forEach((puntos, indiceRuta) => {
    let tramo = [];

    const cerrarTramo = () => {
      if (tramo.length === 0) return;

      let cercano = null;
      for (const p of tramo) {
        const distanciaM = calcularDistanciaMetros(
          Number(p.latitud),
          Number(p.longitud),
          centroLat,
          centroLon
        );
        if (cercano === null || distanciaM < cercano.distanciaM) {
          cercano = { punto: p, distanciaM };
        }
      }

      visitas.push({
        id: `${indiceRuta}-${visitas.length}`,
        indiceRuta,
        llegada: parsearFechaGPS(tramo[0].timestamp_gps),
        salida: parsearFechaGPS(tramo[tramo.length - 1].timestamp_gps),
        cercano: {
          lat: Number(cercano.punto.latitud),
          lon: Number(cercano.punto.longitud),
          fecha: parsearFechaGPS(cercano.punto.timestamp_gps),
          distanciaM: cercano.distanciaM,
        },
        puntos: tramo.length,
      });
      tramo = [];
    };

    for (const p of puntos) {
      if (dentro(p)) tramo.push(p);
      else cerrarTramo();
    }
    cerrarTramo();
  });

  return visitas.sort((a, b) => b.llegada - a.llegada);
}
