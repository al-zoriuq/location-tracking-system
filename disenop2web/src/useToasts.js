import { useState, useRef, useCallback } from "react";

const MAX_TOASTS = 4;

// State for the toast stack (see Toasts.jsx for the UI).
//
//   mostrar(mensaje, tipo)     one-off toast; an identical one already on
//                              screen is not stacked again
//   registrarFallo(fuente, clave, mensaje)
//                              for requests that repeat (polling): raises the
//                              toast once when `fuente` starts failing, and
//                              stays quiet while it keeps failing the same way
//   registrarExito(fuente, mensajeRecuperada)
//                              `fuente` worked again; shows the recovery toast
//                              (if given) once nothing else is failing the
//                              same way
//
// `fuente` names who is asking ("ubicacion", "historial"...); `clave` names
// the problem, so two sources hitting the same problem share a single toast.
export function useToasts() {
  const [toasts, setToasts] = useState([]);
  const fallos = useRef({}); // fuente -> clave of its current failure
  const idSiguiente = useRef(1);

  const cerrar = useCallback((id) => {
    setToasts((lista) => lista.filter((t) => t.id !== id));
  }, []);

  const mostrar = useCallback((mensaje, tipo = "info") => {
    const id = idSiguiente.current++;
    setToasts((lista) => {
      if (lista.some((t) => t.mensaje === mensaje && t.tipo === tipo)) return lista;
      return [...lista, { id, mensaje, tipo }].slice(-MAX_TOASTS);
    });
  }, []);

  const registrarFallo = useCallback(
    (fuente, clave, mensaje) => {
      if (fallos.current[fuente] === clave) return;
      fallos.current[fuente] = clave;

      const yaAvisado = Object.entries(fallos.current).some(
        ([otra, claveOtra]) => otra !== fuente && claveOtra === clave
      );
      if (!yaAvisado) mostrar(mensaje, "error");
    },
    [mostrar]
  );

  const registrarExito = useCallback(
    (fuente, mensajeRecuperada) => {
      const clave = fallos.current[fuente];
      if (clave === undefined) return;
      delete fallos.current[fuente];

      const sigueFallando = Object.values(fallos.current).includes(clave);
      if (mensajeRecuperada && !sigueFallando) mostrar(mensajeRecuperada, "exito");
    },
    [mostrar]
  );

  return { toasts, mostrar, cerrar, registrarFallo, registrarExito };
}
