// Error thrown by pedirJSON. `tipo` tells the UI which message to show:
//   "red"       no answer at all (offline, DNS failure, server unreachable)
//   "servidor"  5xx, or a 200 whose body is not valid JSON
//   "vacio"     404: the request was fine but there is nothing to return
//   "solicitud" any other 4xx: the server rejected the request, and
//               `mensaje` is the "error" text it sent back
export class ErrorApi extends Error {
  constructor(tipo, mensaje, estado = 0) {
    super(mensaje);
    this.tipo = tipo;
    this.estado = estado;
  }
}

export const MENSAJE_SIN_CONEXION =
  "Sin conexión con el servidor. Revisa tu internet; se reintentará automáticamente.";
export const MENSAJE_SERVIDOR = "El servidor tuvo un problema. Se reintentará automáticamente.";
export const MENSAJE_RECUPERADA = "Conexión recuperada.";

// fetch + JSON, with failures sorted into ErrorApi types.
export async function pedirJSON(url) {
  let respuesta;
  try {
    respuesta = await fetch(url);
  } catch {
    throw new ErrorApi("red", MENSAJE_SIN_CONEXION, 0);
  }

  if (respuesta.ok) {
    try {
      return await respuesta.json();
    } catch {
      throw new ErrorApi("servidor", MENSAJE_SERVIDOR, respuesta.status);
    }
  }

  // Error bodies from our backend are {"error": "..."}; anything else (an HTML
  // error page from a proxy, for instance) simply has no usable message.
  let mensajeServidor = null;
  try {
    mensajeServidor = (await respuesta.json()).error || null;
  } catch {
    // body was not JSON
  }

  if (respuesta.status === 404) {
    throw new ErrorApi("vacio", mensajeServidor || "No hay datos.", 404);
  }
  if (respuesta.status >= 500) {
    throw new ErrorApi("servidor", MENSAJE_SERVIDOR, respuesta.status);
  }
  throw new ErrorApi(
    "solicitud",
    mensajeServidor || "La solicitud no es válida.",
    respuesta.status
  );
}

// Picks the toast key and text for a failed request. The key decides which
// failures count as "the same problem" (see registrarFallo in useToasts.js):
// every offline failure shares one key, so losing the connection raises a
// single toast no matter how many requests were in flight.
export function describirFallo(error, contexto, mensajeServidor = MENSAJE_SERVIDOR) {
  if (!(error instanceof ErrorApi)) {
    return { clave: `${contexto}:inesperado`, mensaje: "Ocurrió un error inesperado." };
  }
  if (error.tipo === "red") {
    return { clave: "red", mensaje: MENSAJE_SIN_CONEXION };
  }
  if (error.tipo === "servidor") {
    return { clave: `${contexto}:servidor`, mensaje: mensajeServidor };
  }
  return { clave: `${contexto}:${error.mensaje}`, mensaje: error.mensaje };
}
