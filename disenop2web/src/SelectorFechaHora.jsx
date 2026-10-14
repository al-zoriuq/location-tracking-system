import { useState } from "react";

const MESES = [
  "enero", "febrero", "marzo", "abril", "mayo", "junio",
  "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
];
const MESES_CORTOS = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"];
const DIAS_SEMANA = ["L", "M", "M", "J", "V", "S", "D"]; // the week starts on Monday
const DIAS_CORTOS = ["dom", "lun", "mar", "mié", "jue", "vie", "sáb"];

const dos = (n) => String(n).padStart(2, "0");

// Values are "YYYY-MM-DDTHH:mm" strings (the same shape as <input
// type="datetime-local">), which compare correctly with < and >.
function partes(valor) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(valor || "");
  if (!m) return null;
  return { a: +m[1], m: +m[2] - 1, d: +m[3], h: +m[4], min: +m[5] };
}

function armar({ a, m, d, h, min }) {
  return `${a}-${dos(m + 1)}-${dos(d)}T${dos(h)}:${dos(min)}`;
}

function acotar(valor, min, max) {
  if (min && valor < min) return min;
  if (max && valor > max) return max;
  return valor;
}

function formatear({ a, m, d, h, min }) {
  const dia = DIAS_CORTOS[new Date(a, m, d).getDay()];
  const h12 = h % 12 || 12;
  return `${dia} ${d} ${MESES_CORTOS[m]} ${a} · ${h12}:${dos(min)} ${h < 12 ? "a. m." : "p. m."}`;
}

// Date + time picker: a month calendar plus labelled "Hora" / "Minutos" fields.
// `min` and `max` bound what can be picked; anything outside is greyed out and,
// for the time of day, clamped to the limit.
export default function SelectorFechaHora({ etiqueta, valor, min, max, abierto, onAlternar, onChange }) {
  const p = partes(valor);
  const referencia = p ?? partes(max) ?? { a: 2000, m: 0, d: 1, h: 0, min: 0 };
  const [mes, setMes] = useState({ a: referencia.a, m: referencia.m });

  const idPanel = `fh-${etiqueta.toLowerCase()}`;
  const hoyTexto = max ? max.slice(0, 10) : null;
  const minDia = min ? min.slice(0, 10) : null;
  const maxDia = max ? max.slice(0, 10) : null;

  const alternar = () => {
    // Opening shows the month of the current value
    if (!abierto) setMes({ a: referencia.a, m: referencia.m });
    onAlternar();
  };

  const cambiarMes = (delta) => {
    const fecha = new Date(mes.a, mes.m + delta, 1);
    setMes({ a: fecha.getFullYear(), m: fecha.getMonth() });
  };
  const primerDiaMes = `${mes.a}-${dos(mes.m + 1)}-01`;
  const ultimoDiaMes = `${mes.a}-${dos(mes.m + 1)}-${dos(new Date(mes.a, mes.m + 1, 0).getDate())}`;
  const puedeAtras = !minDia || primerDiaMes > minDia;
  const puedeAdelante = !maxDia || ultimoDiaMes < maxDia;

  const elegirDia = (d) => {
    const base = p ?? { h: 0, min: 0 };
    onChange(acotar(armar({ a: mes.a, m: mes.m, d, h: base.h, min: base.min }), min, max));
  };

  const cambiarHora = ({ h12, minutos, pm }) => {
    if (!p) return;
    const h24 = (h12 % 12) + (pm ? 12 : 0);
    onChange(acotar(armar({ ...p, h: h24, min: minutos }), min, max));
  };

  // Calendar cells: blanks up to the first weekday, then the days of the month
  const diasEnMes = new Date(mes.a, mes.m + 1, 0).getDate();
  const huecos = (new Date(mes.a, mes.m, 1).getDay() + 6) % 7;
  const celdas = [
    ...Array.from({ length: huecos }, () => null),
    ...Array.from({ length: diasEnMes }, (_, i) => i + 1),
  ];

  const h12 = p ? p.h % 12 || 12 : 12;
  const esPM = p ? p.h >= 12 : false;

  return (
    <div className="fh">
      <span className="filtro-label" id={`${idPanel}-etiqueta`}>{etiqueta}</span>

      <button
        type="button"
        className={`fh-campo ${abierto ? "abierto" : ""}`}
        onClick={alternar}
        aria-expanded={abierto}
        aria-controls={idPanel}
        aria-labelledby={`${idPanel}-etiqueta ${idPanel}-valor`}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
          strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
          <rect x="3" y="5" width="18" height="16" rx="3" />
          <line x1="3" y1="10" x2="21" y2="10" />
          <line x1="8" y1="3" x2="8" y2="7" />
          <line x1="16" y1="3" x2="16" y2="7" />
        </svg>
        <span id={`${idPanel}-valor`} className="fh-valor">{p ? formatear(p) : "Elegir fecha y hora"}</span>
        <span className="fh-flecha" aria-hidden="true">{abierto ? "▴" : "▾"}</span>
      </button>

      {abierto && (
        <div
          className="fh-panel"
          id={idPanel}
          role="group"
          aria-label={`Elegir fecha y hora: ${etiqueta}`}
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              onAlternar();
            }
          }}
        >
          <div className="fh-mes">
            <button type="button" className="fh-nav" onClick={() => cambiarMes(-1)}
              disabled={!puedeAtras} aria-label="Mes anterior">‹</button>
            <span className="fh-mes-nombre" aria-live="polite">{MESES[mes.m]} {mes.a}</span>
            <button type="button" className="fh-nav" onClick={() => cambiarMes(1)}
              disabled={!puedeAdelante} aria-label="Mes siguiente">›</button>
          </div>

          <div className="fh-semana" aria-hidden="true">
            {DIAS_SEMANA.map((d, i) => <span key={i}>{d}</span>)}
          </div>

          <div className="fh-dias">
            {celdas.map((d, i) => {
              if (d === null) return <span key={`h${i}`} />;
              const texto = `${mes.a}-${dos(mes.m + 1)}-${dos(d)}`;
              const fueraDeRango = (minDia && texto < minDia) || (maxDia && texto > maxDia);
              const elegido = p && texto === valor.slice(0, 10);
              return (
                <button
                  key={d}
                  type="button"
                  className={`fh-dia ${elegido ? "elegido" : ""} ${texto === hoyTexto ? "hoy" : ""}`}
                  disabled={fueraDeRango}
                  aria-pressed={!!elegido}
                  aria-label={`${d} de ${MESES[mes.m]} de ${mes.a}`}
                  onClick={() => elegirDia(d)}
                >
                  {d}
                </button>
              );
            })}
          </div>

          <div className="fh-hora">
            <label className="fh-hora-campo">
              <span>Hora</span>
              <select value={h12} disabled={!p}
                onChange={(e) => cambiarHora({ h12: +e.target.value, minutos: p.min, pm: esPM })}>
                {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
                  <option key={n} value={n}>{n}</option>
                ))}
              </select>
            </label>
            <span className="fh-dospuntos" aria-hidden="true">:</span>
            <label className="fh-hora-campo">
              <span>Minutos</span>
              <select value={p ? p.min : 0} disabled={!p}
                onChange={(e) => cambiarHora({ h12, minutos: +e.target.value, pm: esPM })}>
                {Array.from({ length: 60 }, (_, i) => i).map((n) => (
                  <option key={n} value={n}>{dos(n)}</option>
                ))}
              </select>
            </label>
            <label className="fh-hora-campo">
              <span>a. m. / p. m.</span>
              <select value={esPM ? "pm" : "am"} disabled={!p}
                onChange={(e) => cambiarHora({ h12, minutos: p.min, pm: e.target.value === "pm" })}>
                <option value="am">a. m.</option>
                <option value="pm">p. m.</option>
              </select>
            </label>
          </div>
          {!p && <p className="fh-ayuda">Elige primero un día en el calendario.</p>}

          <div className="fh-pie">
            {max && (
              <button type="button" className="fh-ahora" onClick={() => onChange(max)}>
                Ahora
              </button>
            )}
            <button type="button" className="fh-listo" onClick={onAlternar}>Listo</button>
          </div>
        </div>
      )}
    </div>
  );
}
