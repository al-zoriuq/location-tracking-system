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
        <h3>Última posición</h3>
        <p>
          La tarjeta de arriba a la izquierda muestra la dirección aproximada del último punto
          recibido, con su fecha y hora. La dirección se obtiene de OpenStreetMap a partir de las
          coordenadas, así que puede no coincidir exactamente con el número de la casa. En el
          celular la tarjeta está resumida en una línea: tócala para verla completa.
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
          <li>
            <strong>Pin en el mapa:</strong> el botón del pin, junto al campo de la lupa, te deja
            elegir un punto tocando el mapa (sale un aviso arriba; «Cancelar» o la tecla Esc lo
            anulan). Se muestran solo las rutas que pasaron a menos de 300 m de ese punto, con el
            área marcada con un recuadro punteado. Toca el pin para ver sus coordenadas o quitarlo;
            también se quita con la «x» del campo de lugar.
          </li>
        </ul>
        <p>Ambos filtros se pueden combinar.</p>
        <p>En el celular, los filtros están detrás del botón «Filtros», y el selector de fecha y hora se abre como una hoja desde abajo. Al aplicar el rango o elegir un lugar, la tarjeta se cierra y el botón «Filtros» muestra un resumen de lo aplicado; tócalo para abrirla otra vez. Al filtrar, el mapa se centra en la ruta.</p>
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
          <li>
            <strong>Señales de tránsito:</strong> las que detectó la cámara del dispositivo
            durante la ruta: límite de velocidad (círculo blanco con borde rojo y el número), pare
            (octágono rojo) y ceda el paso (triángulo invertido). Un límite con brillo rojo es un
            exceso de velocidad. Tócala para ver la hora, la velocidad medida por el GPS y por el
            sensor de movimiento (y cuál se usó), la confianza de la detección y si se cumplió.
          </li>
        </ul>
      </section>

      <section>
        <h3>Botones redondos</h3>
        <ul>
          <li>
            <strong>Ojo:</strong> oculta todos los paneles y deja solo el mapa.
          </li>
          <li>
            <strong>Lista:</strong> abre el historial de puntos, las señales de tránsito de la
            ruta y las visitas de un lugar. Se cierra con el mismo botón.
          </li>
          <li>
            <strong>Play:</strong> reproduce el recorrido de la ruta mostrada. La barra tiene
            pausa, un deslizador para saltar a cualquier momento y la velocidad (×60, ×300 o
            ×1200 veces el tiempo real).
          </li>
          <li>
            <strong>Capas:</strong> «Ajustar a vías» dibuja la ruta sobre las calles reales,
            «Mostrar paradas» activa o quita las paradas y «Mostrar señales» activa o quita las
            señales de tránsito.
          </li>
          <li>
            <strong>Mira:</strong> mantiene el punto actual en el centro sin cambiar tu zoom.
          </li>
        </ul>
      </section>

      <section>
        <h3>Historial de puntos</h3>
        <p>
          Está plegado para dejar espacio al mapa. Ábrelo con el botón de la lista: muestra
          los puntos de la ruta mostrada, del más reciente al más antiguo, con fecha, hora y
          coordenadas. El botón redondo con el ícono de lista abre el historial (y las visitas de un lugar): en el celular sube como una hoja desde abajo y en pantalla ancha se abre como un panel a la derecha. Se cierra tocando fuera de la hoja, su título o el mismo botón.
        </p>
      </section>

      <section>
        <h3>Señales de la ruta</h3>
        <p>
          Si el dispositivo detectó señales de tránsito, el panel de la lista muestra arriba
          «Señales en la ruta», con cuántas hubo y cuántos excesos de velocidad, y cada señal en el
          orden en que se pasó. «Cumple» y «Excede» se refieren al límite de velocidad; un pare o
          un ceda el paso salen «Sin evaluar». Toca una señal para ir a ella en el mapa (en el
          celular, la hoja se cierra para que la veas). Al cambiar de ruta, la lista cambia con ella.
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
