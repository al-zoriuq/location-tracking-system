// GET api/<ruta>?<parametros> relative to the app base URL, returning JSON.
// Empty parameters are left out. Non-2xx answers throw an Error carrying the
// backend's Spanish message and the HTTP status, so callers never mistake an
// error body for data.
export async function pedirJSON(ruta, parametros = {}) {
  const query = new URLSearchParams(
    Object.entries(parametros).filter(([, valor]) => valor != null && valor !== "")
  ).toString();
  const url = `${import.meta.env.BASE_URL}api/${ruta}${query ? `?${query}` : ""}`;

  const respuesta = await fetch(url);
  let datos = null;
  try {
    datos = await respuesta.json();
  } catch {
    // Body was not JSON (e.g. a proxy error page)
  }

  if (!respuesta.ok) {
    const error = new Error(datos?.error || `Error ${respuesta.status} del servidor`);
    error.status = respuesta.status;
    throw error;
  }
  return datos;
}
