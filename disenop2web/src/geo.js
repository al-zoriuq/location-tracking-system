const RADIO_TIERRA_M = 6371000;

// Haversine formula: straight-line distance in meters between two GPS
// coordinates, accounting for the Earth's curvature.
export function calcularDistanciaMetros(lat1, lon1, lat2, lon2) {
  const toRad = (grados) => (grados * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return RADIO_TIERRA_M * c;
}

// 85 -> "85 m", 1240 -> "1,2 km"
export function formatoDistancia(metros) {
  if (metros < 1000) return `${Math.round(metros)} m`;
  return `${(metros / 1000).toFixed(1).replace(".", ",")} km`;
}
