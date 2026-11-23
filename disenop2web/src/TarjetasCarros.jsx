import { useDireccion, textoDireccion } from "./useDireccion.js";

// Segmented control in the top bar: both cars on the map, or only one of them.
// Picking a car also makes it the active one (the one the tools work on).
export function SelectorCarros({ carros, activo, verAmbos, onAmbos, onCarro }) {
  return (
    <div className="selector-carros" role="group" aria-label="Carros en el mapa">
      <button
        type="button"
        className={verAmbos ? "activo" : ""}
        aria-pressed={verAmbos}
        onClick={onAmbos}
        title="Ver los dos carros en el mapa"
      >
        Ambos
      </button>
      {carros.map((carro) => {
        const elegido = !verAmbos && carro.vehiculo === activo;
        return (
          <button
            key={carro.vehiculo}
            type="button"
            className={elegido ? "activo" : ""}
            aria-pressed={elegido}
            onClick={() => onCarro(carro.vehiculo)}
            title={`Ver solo ${carro.nombre}`}
            aria-label={`Ver solo ${carro.nombre}`}
            style={{ "--color-carro": carro.color }}
          >
            <span className="selector-carros-color" aria-hidden="true" />
            {/* Full name ("Vehículo A01") on wide screens, only the alias ("A01") on phones */}
            <span className="selector-carros-texto">
              <span className="selector-carros-largo">{carro.nombre}</span>
              <span className="selector-carros-corto">{carro.vehiculo}</span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

// Card of one car over the top of the map: its colour, name (alias), status,
// approximate address, time of the last point and speed (while reporting).
// The active car is highlighted; tapping another card makes it active, and
// tapping the active one flies the map to it.
export function TarjetaCarro({ carro, activa, estado, hora, fecha, fechaCorta, velocidadKmh, onElegir }) {
  const direccion = useDireccion(Number(carro.latitud), Number(carro.longitud));
  const texto = textoDireccion(direccion);

  return (
    <button
      type="button"
      className={`tarjeta-carro ${activa ? "activa" : ""}`}
      style={{ "--color-carro": carro.color }}
      onClick={() => onElegir(carro)}
      aria-pressed={activa}
      title={activa ? `Centrar el mapa en ${carro.nombre}` : `Ver las rutas de ${carro.nombre}`}
    >
      <span className="tarjeta-carro-cabecera">
        <span className="tarjeta-carro-color" aria-hidden="true" />
        {/* Full name; only the alias when the two cards sit side by side on a phone */}
        <span className="tarjeta-carro-id">
          <span className="tarjeta-carro-largo">{carro.nombre}</span>
          <span className="tarjeta-carro-corto">{carro.vehiculo}</span>
        </span>
        <span className="tarjeta-carro-estado">
          <span className={`dot dot-${estado.tier}`} aria-hidden="true" />
          <span className="tarjeta-carro-estado-texto">{estado.texto}</span>
        </span>
      </span>
      <span
        className={`tarjeta-carro-direccion ${direccion.texto ? "" : "sin-texto"}`}
        title={`${texto} (dirección aproximada)`}
      >
        {texto}
      </span>
      <span className="tarjeta-carro-meta">
        <span className="tarjeta-carro-cuando">{fecha ? `${fecha} · ${hora}` : hora}</span>
        {/* Side-by-side cards (phones): the time if it is from today, otherwise only the day */}
        <span className="tarjeta-carro-cuando-corto">{fecha ? fechaCorta : hora}</span>
        {velocidadKmh !== null && (
          <span className="tarjeta-carro-vel">
            <b>{Math.round(velocidadKmh)}</b> km/h
          </span>
        )}
      </span>
    </button>
  );
}
