import { useEffect } from "react";

// How long each kind stays on screen. Errors last longer: they are the ones
// people need time to read.
const DURACION_MS = { error: 9000, aviso: 7000, exito: 5000, info: 5000 };

function Toast({ toast, onCerrar }) {
  useEffect(() => {
    const timer = setTimeout(() => onCerrar(toast.id), DURACION_MS[toast.tipo] ?? 5000);
    return () => clearTimeout(timer);
  }, [toast.id, toast.tipo, onCerrar]);

  return (
    <div className={`toast toast-${toast.tipo}`} role="alert">
      <p className="toast-mensaje">{toast.mensaje}</p>
      <button className="toast-cerrar" onClick={() => onCerrar(toast.id)} aria-label="Cerrar aviso">
        ×
      </button>
    </div>
  );
}

// Stack of dismissible messages. State lives in useToasts().
export default function Toasts({ toasts, onCerrar }) {
  if (toasts.length === 0) return null;

  return (
    <div className="toasts">
      {toasts.map((toast) => (
        <Toast key={toast.id} toast={toast} onCerrar={onCerrar} />
      ))}
    </div>
  );
}
