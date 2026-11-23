import { useEffect, useRef, useState } from "react";

// Pipo on the web page: the same voice assistant as the app, asked about the
// active car. A floating orb opens a glass sheet with a text box and, where the
// browser supports it, the microphone; the answer is also read aloud.
// The server finds the car by its alias (it never sends device ids to the page).

// Colors per state, same as OrbePipo in the app: [body, body dark, glow, glow 2]
const COLORES = {
  dormido: ["#B79CFF", "#5B3FC4", "rgba(183,156,255,0.6)", "rgba(122,77,224,0.55)"],
  escuchando: ["#67E8F9", "#0E7490", "rgba(103,232,249,0.7)", "rgba(183,156,255,0.55)"],
  pensando: ["#FCD34D", "#B45309", "rgba(252,211,77,0.6)", "rgba(255,138,149,0.5)"],
  hablando: ["#FF9AD5", "#B0306E", "rgba(255,154,213,0.65)", "rgba(183,156,255,0.55)"],
};

const TEXTO_ESTADO = {
  dormido: "Pregúntame por el carro",
  escuchando: "Te escucho…",
  pensando: "Pensando…",
  hablando: "Respondiendo",
};

const Reconocimiento =
  typeof window !== "undefined" && (window.SpeechRecognition || window.webkitSpeechRecognition);

// Pipo's face on a canvas: glow, turning aurora, lit sphere, eyes and mouth.
// Same proportions and motion as the app's OrbePipo.
function Orbe({ estado, tamano }) {
  const lienzo = useRef(null);

  useEffect(() => {
    const c = lienzo.current;
    const dpr = window.devicePixelRatio || 1;
    c.width = tamano * dpr;
    c.height = tamano * dpr;
    const g = c.getContext("2d");
    g.scale(dpr, dpr);
    const quieto = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const inicio = performance.now();
    let cuadro;

    function dibujar(ahora) {
      const t = quieto ? 0 : (ahora - inicio) / 1000;
      const e = estado;
      const [col, col2, brillo, brillo2] = COLORES[e];
      const cx = tamano / 2;
      const cy = tamano / 2;
      const radio = tamano / 2;
      const [periodo, amplitud] = e === "escuchando" ? [1.1, 0.05] : [3.2, 0.025];
      const r = radio * 0.72 * (1 + amplitud * Math.sin((2 * Math.PI * t) / periodo));
      g.clearRect(0, 0, tamano, tamano);

      // Soft glow around the sphere
      const halo = g.createRadialGradient(cx, cy, radio * 0.6, cx, cy, radio);
      halo.addColorStop(0, brillo);
      halo.addColorStop(1, "rgba(0,0,0,0)");
      g.fillStyle = halo;
      g.beginPath();
      g.arc(cx, cy, radio, 0, 2 * Math.PI);
      g.fill();

      // Aurora: a turning ring of two colors
      const vuelta = e === "pensando" ? 1.6 : 6;
      const giro = 2 * Math.PI * ((t / vuelta) % 1);
      const aurora = g.createConicGradient(giro, cx, cy);
      aurora.addColorStop(0, "rgba(0,0,0,0)");
      aurora.addColorStop(0.25, brillo);
      aurora.addColorStop(0.5, "rgba(0,0,0,0)");
      aurora.addColorStop(0.75, brillo2);
      aurora.addColorStop(1, "rgba(0,0,0,0)");
      g.strokeStyle = aurora;
      g.lineWidth = radio * 0.14;
      g.beginPath();
      g.arc(cx, cy, r * 1.14, 0, 2 * Math.PI);
      g.stroke();

      // The sphere, lit from the top left
      const cuerpo = g.createRadialGradient(cx - r * 0.32, cy - r * 0.44, 0, cx - r * 0.32, cy - r * 0.44, r * 1.55);
      cuerpo.addColorStop(0, "rgba(255,255,255,0.9)");
      cuerpo.addColorStop(0.3, col);
      cuerpo.addColorStop(0.85, col2);
      g.fillStyle = cuerpo;
      g.beginPath();
      g.arc(cx, cy, r, 0, 2 * Math.PI);
      g.fill();

      // Face, in fractions of the sphere's box
      const x0 = cx - r;
      const y0 = cy - r;
      const d = r * 2;
      const ojoW = d * 0.11;
      const parpadeo = t % 4.5 >= 4.25 && t % 4.5 <= 4.4;
      const dormido = e === "dormido";
      const [ojoTop, ojoH] = dormido
        ? [0.45, 0.035]
        : e === "escuchando"
          ? [0.34, 0.21]
          : e === "pensando"
            ? [0.32, 0.14]
            : [0.36, 0.17];
      const h = parpadeo && !dormido ? d * 0.02 : d * ojoH;
      g.fillStyle = "#fff";
      for (const izq of [0.33, 0.56]) {
        g.beginPath();
        g.roundRect(x0 + d * izq, y0 + d * ojoTop + (d * ojoH - h) / 2, ojoW, h, ojoW * 0.4);
        g.fill();
      }

      g.strokeStyle = "#fff";
      g.lineCap = "round";
      g.lineWidth = Math.max(2, d * 0.04);
      g.beginPath();
      if (e === "hablando") {
        const abre = 0.35 + 0.9 * Math.abs(Math.sin((t * Math.PI) / 0.32));
        g.ellipse(x0 + d * 0.5, y0 + d * 0.62, d * 0.11, (d * 0.1 * abre) / 2, 0, 0, 2 * Math.PI);
        g.fill();
      } else if (e === "escuchando") {
        g.arc(x0 + d * 0.5, y0 + d * 0.62, d * 0.05, 0, 2 * Math.PI);
        g.stroke();
      } else if (e === "pensando") {
        g.moveTo(x0 + d * 0.44, y0 + d * 0.62);
        g.lineTo(x0 + d * 0.56, y0 + d * 0.62);
        g.stroke();
      } else {
        g.ellipse(x0 + d * 0.5, y0 + d * 0.57, d * 0.11, d * 0.09, 0, (20 * Math.PI) / 180, (160 * Math.PI) / 180);
        g.stroke();
      }

      if (!quieto) cuadro = requestAnimationFrame(dibujar);
    }
    cuadro = requestAnimationFrame(dibujar);
    return () => cancelAnimationFrame(cuadro);
  }, [estado, tamano]);

  return <canvas ref={lienzo} className="pipo-orbe" style={{ width: tamano, height: tamano }} aria-hidden="true" />;
}

function hablar(texto, alTerminar) {
  if (!("speechSynthesis" in window)) return alTerminar();
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(texto);
  u.lang = "es-CO";
  const voz = window.speechSynthesis.getVoices().find((v) => v.lang.startsWith("es"));
  if (voz) u.voice = voz;
  u.onend = alTerminar;
  u.onerror = alTerminar;
  window.speechSynthesis.speak(u);
}

export default function PipoWeb({ vehiculo, nombre, velocidadKmh, posicion }) {
  const [abierto, setAbierto] = useState(false);
  const [estado, setEstado] = useState("dormido");
  const [pregunta, setPregunta] = useState("");
  const [dialogo, setDialogo] = useState(null); // {pregunta, respuesta}
  const [conVoz, setConVoz] = useState(true);
  const escucha = useRef(null);
  const consulta = useRef(0);
  const campo = useRef(null);

  useEffect(() => {
    if (abierto) campo.current?.focus();
  }, [abierto]);

  // Closing the sheet stops everything Pipo was doing
  function cerrar() {
    consulta.current++;
    escucha.current?.abort();
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    setEstado("dormido");
    setAbierto(false);
  }

  useEffect(() => {
    function alTeclear(e) {
      if (e.key === "Escape") cerrar();
    }
    if (abierto) window.addEventListener("keydown", alTeclear);
    return () => window.removeEventListener("keydown", alTeclear);
  }, [abierto]);

  async function preguntar(texto) {
    const limpio = texto.trim();
    if (!limpio || !vehiculo) return;
    const mia = ++consulta.current;
    setPregunta("");
    setDialogo({ pregunta: limpio, respuesta: null });
    setEstado("pensando");

    let respuesta;
    try {
      const r = await fetch(import.meta.env.BASE_URL + "api/pipo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          vehiculo,
          origen: "web",
          pregunta: limpio,
          contexto: {
            velocidad_kmh: velocidadKmh,
            lat: posicion ? posicion[0] : null,
            lon: posicion ? posicion[1] : null,
          },
        }),
      });
      const datos = await r.json().catch(() => ({}));
      // The server also puts a speakable "respuesta" in its errors
      respuesta = datos.respuesta || `El servidor respondió con un error ${r.status}.`;
    } catch {
      respuesta = "No pude conectarme con el servidor. Revisa tu internet.";
    }
    if (mia !== consulta.current) return; // closed or asked again meanwhile

    setDialogo({ pregunta: limpio, respuesta });
    if (conVoz) {
      setEstado("hablando");
      hablar(respuesta, () => mia === consulta.current && setEstado("dormido"));
    } else {
      setEstado("dormido");
    }
  }

  function escuchar() {
    if (!Reconocimiento) return;
    if (estado === "escuchando") {
      escucha.current?.stop();
      return;
    }
    if ("speechSynthesis" in window) window.speechSynthesis.cancel();
    const rec = new Reconocimiento();
    rec.lang = "es-CO";
    rec.interimResults = true;
    rec.onresult = (e) => {
      const texto = Array.from(e.results).map((r) => r[0].transcript).join("");
      setPregunta(texto);
      if (e.results[e.results.length - 1].isFinal) preguntar(texto);
    };
    rec.onerror = () => setEstado("dormido");
    rec.onend = () => setEstado((s) => (s === "escuchando" ? "dormido" : s));
    escucha.current = rec;
    setEstado("escuchando");
    rec.start();
  }

  function enviar(e) {
    e.preventDefault();
    preguntar(pregunta);
  }

  return (
    <>
      {!abierto && (
        <button
          type="button"
          className="pipo-boton"
          onClick={() => setAbierto(true)}
          title="Preguntarle a Pipo"
          aria-label="Preguntarle a Pipo"
        >
          <Orbe estado="dormido" tamano={64} />
        </button>
      )}

      {abierto && (
        <div className="pipo-capa" onClick={cerrar}>
          <section
            className="pipo-hoja"
            role="dialog"
            aria-label="Pipo"
            onClick={(e) => e.stopPropagation()}
          >
            <span className="pipo-agarradera" aria-hidden="true" />
            <button type="button" className="pipo-cerrar" onClick={cerrar} aria-label="Cerrar Pipo">
              ×
            </button>

            <Orbe estado={estado} tamano={128} />
            <h2 className="pipo-nombre">Pipo</h2>
            <p className={`pipo-estado pipo-estado-${estado}`} aria-live="polite">
              {vehiculo ? TEXTO_ESTADO[estado] : "Elige un carro para preguntarme"}
            </p>
            {vehiculo && <p className="pipo-carro">Sobre {nombre || vehiculo}</p>}

            {dialogo && (
              <div className="pipo-dialogo" aria-live="polite">
                <p className="pipo-pregunta">{dialogo.pregunta}</p>
                {dialogo.respuesta && <p className="pipo-respuesta">{dialogo.respuesta}</p>}
              </div>
            )}

            <form className="pipo-formulario" onSubmit={enviar}>
              <input
                ref={campo}
                className="pipo-campo"
                type="text"
                value={pregunta}
                onChange={(e) => setPregunta(e.target.value)}
                placeholder="¿Cumplió el pare?"
                maxLength={500}
                disabled={!vehiculo}
                aria-label="Pregunta para Pipo"
              />
              {Reconocimiento && (
                <button
                  type="button"
                  className={`pipo-mic ${estado === "escuchando" ? "activo" : ""}`}
                  onClick={escuchar}
                  disabled={!vehiculo}
                  aria-pressed={estado === "escuchando"}
                  title={estado === "escuchando" ? "Dejar de escuchar" : "Preguntar con la voz"}
                  aria-label="Preguntar con la voz"
                >
                  <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
                    strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
                    <rect x="9" y="3" width="6" height="11" rx="3" />
                    <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
                  </svg>
                </button>
              )}
              <button
                type="submit"
                className="pipo-enviar"
                disabled={!vehiculo || !pregunta.trim() || estado === "pensando"}
              >
                Preguntar
              </button>
            </form>

            <label className="pipo-voz">
              <input type="checkbox" checked={conVoz} onChange={(e) => setConVoz(e.target.checked)} />
              Leer la respuesta en voz alta
            </label>
          </section>
        </div>
      )}
    </>
  );
}
