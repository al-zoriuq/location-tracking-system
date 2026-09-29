import { Modal } from "./Modal.jsx";

export default function AyudaModal({ onCerrar }) {
  return (
    <Modal titulo="Cómo usar esta página" onCerrar={onCerrar}>
      <section>
        <h3>Estado (arriba a la derecha)</h3>
        <p>
          Indica qué tan reciente es la última ubicación. «En línea» significa que llegó hace
          2 minutos o menos; «hace 3 h» o «hace 2 d» indican cuánto tiempo lleva sin señal.
        </p>
      </section>

      <section>
        <h3>Rutas</h3>
        <p>
          Una ruta es un viaje completo. Empieza otra cuando pasa más de 1 hora sin datos o
          el dispositivo aparece a más de 1 km. Con las flechas te mueves entre rutas, «Actual»
          salta a la más reciente y el título abre la lista de todas, con fecha, horario y
          cantidad de puntos.
        </p>
      </section>

      <section>
        <h3>Filtros</h3>
        <ul>
          <li>
            <strong>Fecha:</strong> «Filtrar por fecha» (el campo con el calendario) tiene dos campos, «Desde» y «Hasta».
            Cada uno abre un calendario con la hora. No se aceptan fechas futuras, y «Hasta» debe ser posterior a «Desde»: si no lo es, sale un aviso y, si aplicas así, el mapa queda sin rutas hasta que corrijas las fechas. Para volver
            a lo más reciente, usa «Ver en vivo» o la «x».
          </li>
          <li>
            <strong>Lugar:</strong> escribe una ciudad o dirección en el campo de la lupa y elige una opción. Solo se
            muestran las rutas que pasaron por allí. «Sin historial» marca lugares donde el
            dispositivo nunca estuvo. Cada paso queda con un círculo amarillo; tócalo para ver
            el detalle.
          </li>
        </ul>
        <p>Ambos filtros se pueden combinar.</p>
      </section>

      <section>
        <h3>Marcadores</h3>
        <ul>
          <li><strong>Triángulo verde:</strong> inicio de la ruta.</li>
          <li>
            <strong>Círculo hueco (verde o rojo):</strong> ese extremo de la ruta está cortado por el
            filtro de fechas, no es el inicio o el final real del viaje. La barra de rutas dice
            «recortada». Bajo la barra sale un aviso ámbar con el botón «Ver viaje completo», que muestra el viaje entero.
          </li>
          <li><strong>Bandera roja:</strong> final de la ruta. Con un filtro de fecha o de lugar siempre se ve la bandera, aunque sea la última ruta de la lista.</li>
          <li>
            <strong>Círculo morado:</strong> posición actual, solo en modo en vivo (sin filtros de fecha ni de lugar). Se pone gris si la última señal
            tiene más de 2 minutos. Tócalo para ver estadísticas de la ruta.
          </li>
          <li>
            <strong>Velocidad estimada:</strong> aparece en vivo, calculada con los últimos 30
            segundos.
          </li>
          <li>
            <strong>Pausa con minutos:</strong> una parada, es decir, al menos 5 minutos dentro
            de un radio de 50 m. Tócala para ver la hora de llegada y de salida.
          </li>
        </ul>
      </section>

      <section>
        <h3>Botones redondos</h3>
        <ul>
          <li>
            <strong>Capas:</strong> «Ajustar a vías» dibuja la ruta sobre las calles reales y
            «Mostrar paradas» activa o quita las paradas.
          </li>
          <li>
            <strong>Ojo:</strong> oculta todos los paneles y deja solo el mapa.
          </li>
          <li>
            <strong>Play:</strong> reproduce el recorrido de la ruta mostrada. La barra tiene
            pausa, un deslizador para saltar a cualquier momento y la velocidad (×60, ×300 o
            ×1200 veces el tiempo real).
          </li>
          <li>
            <strong>Mira:</strong> mantiene el punto actual en el centro sin cambiar tu zoom.
          </li>
        </ul>
      </section>

      <section>
        <h3>Historial de puntos</h3>
        <p>
          Está plegado para dejar espacio al mapa. Toca «Historial de puntos» para abrirlo: muestra
          los puntos de la ruta mostrada, del más reciente al más antiguo, con fecha, hora y
          coordenadas. En el celular no hay barra: el botón redondo con el ícono de lista abre el historial (y las visitas de un lugar) como una hoja sobre el mapa. Se cierra tocando fuera de la hoja, su título o el mismo botón.
        </p>
      </section>

      <section>
        <h3>Si algo falla</h3>
        <p>
          Si no hay conexión o el servidor tiene un problema, sale un aviso. La página reintenta
          sola cada 10 segundos y avisa cuando todo vuelve a funcionar.
        </p>
      </section>
    </Modal>
  );
}
