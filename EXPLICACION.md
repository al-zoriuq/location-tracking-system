# Explicación técnica — Rastreo GPS (rama `marcela-test`)

Documento de apoyo para la sustentación. Cubre las dos entregas:

- **Entrega 1:** ¿dónde estuvo el vehículo dada una ventana de tiempo?
- **Entrega 2:** ¿cuándo pasó el vehículo por determinado lugar?

Todas las referencias `archivo:línea` corresponden al código del commit que agrega este archivo. El código está comentado en inglés; los textos de la interfaz y esta explicación, en español.

**Contenido**

1. [Arquitectura](#1-arquitectura)
2. [Entrega 1 paso a paso](#2-entrega-1-paso-a-paso)
3. [Entrega 2 paso a paso](#3-entrega-2-paso-a-paso)
4. [Zona horaria de principio a fin](#4-zona-horaria-de-principio-a-fin)
5. [Seguridad](#5-seguridad)
6. [Ideas adicionales implementadas](#6-ideas-adicionales-implementadas)
7. [Guion de demo de 5 minutos](#7-guion-de-demo-de-5-minutos)
8. [Las 15 preguntas más probables](#8-las-15-preguntas-más-probables)
9. [Limitaciones y mejoras futuras](#9-limitaciones-conocidas-y-mejoras-futuras)

---

## 1. Arquitectura

```
┌──────────────┐  UDP :5000   ┌───────────────┐  INSERT    ┌─────────────────────┐
│ App Android  │ ───────────▶ │ Sniffer (x4)  │ ─────────▶ │ RDS PostgreSQL      │
│ cada 10 s    │  (a las 4    │ snifferwpost- │ ON CONFLICT│ tabla `ubicaciones` │
└──────────────┘   EC2)       │ gresql.py     │ DO NOTHING └──────────┬──────────┘
                              └───────────────┘                       │ SELECT
                                                                      ▼ (parametrizado)
┌──────────────┐   HTTP       ┌───────────────┐  proxy     ┌─────────────────────┐
│ Navegador    │ ◀──────────▶ │ NGINX         │ ─────────▶ │ Flask + Gunicorn    │
│ React+Leaflet│  /  y /api/* │ (cada EC2)    │   :5001    │ servidorweb.py      │
└──────────────┘              └───────────────┘            └─────────────────────┘
```

### Captura (ya existía, no se modificó)

- **App Android.** Envía un paquete cada 10 s ([UbicacionService.kt:41](gpslink-android/app/src/main/java/com/example/gpslink/UbicacionService.kt#L41)) al puerto UDP 5000 ([:40](gpslink-android/app/src/main/java/com/example/gpslink/UbicacionService.kt#L40)).
  - El texto tiene la forma `Device: <id>, Lat: <lat>, Lon: <lon>, Timestamp GPS: yyyy-MM-dd HH:mm:ss.SSS XXX` ([:164-169](gpslink-android/app/src/main/java/com/example/gpslink/UbicacionService.kt#L164-L169)).
  - Se envía con un `DatagramSocket` ([:175](gpslink-android/app/src/main/java/com/example/gpslink/UbicacionService.kt#L175)).
- **Sniffer**, en cada una de las 4 EC2:
  - [snifferwpostgresql.py:64](snifferwpostgresql.py#L64): `recvfrom(1024)` recibe el paquete.
  - [:84-90](snifferwpostgresql.py#L84-L90): una expresión regular extrae los campos.
  - [:99-100](snifferwpostgresql.py#L99-L100): convierte el timestamp y le quita la zona horaria.
  - [:108-124](snifferwpostgresql.py#L108-L124): hace el `INSERT` parametrizado.
- **Deduplicación.** Las 4 EC2 reciben el mismo paquete, y `ON CONFLICT (device_id, timestamp_gps) DO NOTHING` ([:112](snifferwpostgresql.py#L112)) evita guardarlo 4 veces.

### Consulta (lo construido en esta rama)

**Backend**

| Archivo | Responsabilidad |
|---|---|
| [servidorweb.py](servidorweb.py) | Endpoints HTTP. Solo valida, llama al repositorio y serializa |
| [validacion.py](validacion.py) | Valida los parámetros de entrada (errores 400 en español) |
| [repositorio.py](repositorio.py) | Acceso a datos: `RepositorioRDS` (SQL) y `RepositorioDemo` (memoria) |
| [analisis_lugar.py](analisis_lugar.py) | Geometría de la Entrega 2 (funciones puras) |
| [tiempo_bogota.py](tiempo_bogota.py) | Única definición de "ahora en Bogotá" |
| [datos_demo.py](datos_demo.py) | Datos simulados determinísticos (`MODO_DEMO=1`) |
| [geocodificacion.py](geocodificacion.py) | Búsqueda de direcciones y lugares (OpenStreetMap: Photon y Nominatim) |

**Frontend** (`disenop2web/src/`)

| Archivo | Responsabilidad |
|---|---|
| `App.jsx` | Estado global, consultas periódicas y composición del mapa |
| `components/` | Un componente por panel o capa del mapa |
| `utils/` | Lógica sin interfaz: tiempo, viajes, lugar, mapa, estadísticas, paradas, URL, almacenamiento |

### Cómo encajan las dos entregas

Ambas leen la misma tabla y comparten:

- la validación de rangos (`leer_rango`, [validacion.py:41](validacion.py#L41));
- la resolución del dispositivo (`resolver_device_id`, [servidorweb.py:92](servidorweb.py#L92));
- los umbrales de "movimiento continuo": 1 h, 1 km y 180 km/h. Están definidos en [viajes.js:6-8](disenop2web/src/utils/viajes.js#L6-L8) y en [analisis_lugar.py:27-29](analisis_lugar.py#L27-L29), con un comentario de que deben coincidir.

En la interfaz, la Entrega 2 se llama **"Filtrar por ubicación"** y es una **capa encima** del estado de la Entrega 1: usa el rango de fechas si hay uno activo, y al salir no altera ni el rango ni la ruta fijada.

---

## 2. Entrega 1 paso a paso

**Pregunta:** ¿dónde estuvo el vehículo entre *Desde* y *Hasta*?

### 2.1 Clic en "Aplicar" (navegador)

1. `aplicar()` en [FiltroFechas.jsx:25](disenop2web/src/components/FiltroFechas.jsx#L25) arma los textos **sin pasar por `Date`**:
   - `textoDesde = "AAAA-MM-DD HH:MM:00"` ([:35](disenop2web/src/components/FiltroFechas.jsx#L35));
   - `textoHasta = "…:59"` ([:36](disenop2web/src/components/FiltroFechas.jsx#L36)), para que "08:30" incluya los puntos de 08:30:xx.
2. Validaciones antes de enviar:
   - Los `<input type="date">` tienen `max = hoy en Bogotá` ([:23](disenop2web/src/components/FiltroFechas.jsx#L23), [:76](disenop2web/src/components/FiltroFechas.jsx#L76), [:93](disenop2web/src/components/FiltroFechas.jsx#L93)).
   - Si Desde es futura, se muestra un error y no se aplica ([:39](disenop2web/src/components/FiltroFechas.jsx#L39)).
   - Si Hasta es futura, se ajusta a la hora actual y se avisa "Hasta se ajustó a la hora actual" ([:45-47](disenop2web/src/components/FiltroFechas.jsx#L45-L47)).
   - Si Desde ≥ Hasta, se muestra un error ([:52](disenop2web/src/components/FiltroFechas.jsx#L52)).
3. `onAplicar({desde, hasta})` ([:58](disenop2web/src/components/FiltroFechas.jsx#L58)) llega a `aplicarRango` ([App.jsx:405](disenop2web/src/App.jsx#L405)). Esta función quita la ruta fijada, vacía la lista y hace `setRango`.

### 2.2 Petición HTTP

4. El efecto del historial ([App.jsx:238-283](disenop2web/src/App.jsx#L238-L283)) se vuelve a ejecutar porque cambió `rango`.
   - `pedirJSON("historial-ubicaciones", {device_id, desde, hasta})` ([:244](disenop2web/src/App.jsx#L244)).
   - La URL se construye con `URLSearchParams` ([api.js:6-9](disenop2web/src/utils/api.js#L6-L9)), que codifica el espacio de la fecha.
   - Si la respuesta no es 2xx, se lanza el mensaje del backend ([api.js:19-22](disenop2web/src/utils/api.js#L19-L22)) y nunca se trata un error como si fueran datos.
5. **Con un rango activo no se consulta periódicamente** ([App.jsx:272](disenop2web/src/App.jsx#L272)). Como Hasta nunca es futura, el rango ya terminó y no pueden llegar puntos nuevos. En modo en vivo sí hay un `setInterval` cada 10 s ([:278](disenop2web/src/App.jsx#L278)).

### 2.3 Backend

6. `historial_ubicaciones()` ([servidorweb.py:125](servidorweb.py#L125)):
   - `leer_rango` ([validacion.py:41](validacion.py#L41)):
     - formato exacto con `strptime` ([:33](validacion.py#L33));
     - `desde` y `hasta` deben venir juntos ([:52](validacion.py#L52));
     - `desde < hasta` ([:56](validacion.py#L56)).
     - Cualquier fallo lanza `ErrorValidacion`, que el manejador convierte en un 400 en JSON ([servidorweb.py:68-70](servidorweb.py#L68-L70)).
   - `resolver_device_id` ([servidorweb.py:92-93](servidorweb.py#L92-L93)): usa el `device_id` recibido, o si no viene, el del registro más reciente **por `timestamp_gps`** ([repositorio.py:70-76](repositorio.py#L70-L76)), no por `id`. Con UDP, un paquete atrasado puede tener un `id` mayor y una hora GPS menor.
7. El SQL de `RepositorioRDS.historial` ([repositorio.py:94](repositorio.py#L94)):
   - **Con rango:** `WHERE device_id = %s AND timestamp_gps BETWEEN %s AND %s ORDER BY timestamp_gps ASC` ([:106](repositorio.py#L106)).
   - **Sin rango** (en vivo): `timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota') - make_interval(hours => %s)` ([:116-117](repositorio.py#L116-L117)).
   - Todos los valores viajan como parámetros `%s`.
8. `serializar()` ([servidorweb.py:58](servidorweb.py#L58)) convierte cada `datetime` a `"YYYY-MM-DD HH:MM:SS"`.

### 2.4 Separación en viajes (navegador)

9. `separarEnViajes()` ([viajes.js:46](disenop2web/src/utils/viajes.js#L46)) compara cada punto con el **último punto aceptado**:

| Regla | Línea | Resultado |
|---|---|---|
| Más de 1 h sin puntos | [:60](disenop2web/src/utils/viajes.js#L60) | Viaje nuevo (sin revisar velocidad: el vehículo pudo reaparecer lejos) |
| Velocidad implícita > 180 km/h | [:65](disenop2web/src/utils/viajes.js#L65) | Error de GPS: el punto se descarta y se cuenta |
| Salto > 1 km | [:69](disenop2web/src/utils/viajes.js#L69) | Viaje nuevo |
| Cualquier otro caso | — | Mismo viaje |

10. El `id` de cada viaje es el timestamp de su primer punto ([:74](disenop2web/src/utils/viajes.js#L74)), no su posición en la lista.
    - El selector usa ese `id` ([SelectorRutas.jsx:7](disenop2web/src/components/SelectorRutas.jsx#L7), [:20-25](disenop2web/src/components/SelectorRutas.jsx#L20-L25)).
    - Si la ruta fijada desaparece del periodo, se avisa ([App.jsx:252](disenop2web/src/App.jsx#L252)) y se vuelve al modo en vivo.

### 2.5 Dibujo

11. Elección de la ruta a mostrar:
    - Se muestra la fijada o, si no hay, la última ([App.jsx:432](disenop2web/src/App.jsx#L432)).
    - Solo la última ruta del modo en vivo está "en curso" ([:435](disenop2web/src/App.jsx#L435)). Cualquier otra termina en "Fin de ruta", nunca en "Actual".
12. Elementos del mapa:
    - La línea del recorrido ([:594](disenop2web/src/App.jsx#L594)), coloreada por CSS con `var(--accent)`.
    - El marcador de inicio en verde ([:598](disenop2web/src/App.jsx#L598)).
    - El marcador de fin en coral ([:601](disenop2web/src/App.jsx#L601)).
13. **Encuadre:** `AjustarVista` ([:58](disenop2web/src/App.jsx#L58)) recibe una `key` formada por el modo y el id de la ruta ([:512](disenop2web/src/App.jsx#L512), [:589](disenop2web/src/App.jsx#L589)).
    - React solo lo vuelve a montar, y por lo tanto solo encuadra con `fitBounds`, cuando cambia la ruta mostrada. Una actualización periódica no mueve el mapa.
    - `fitBounds` usa un relleno que evita la columna de paneles ([:66](disenop2web/src/App.jsx#L66)).
14. **Estado vacío:** "No hay registros en ese rango de fechas." ([:552](disenop2web/src/App.jsx#L552)).

---

## 3. Entrega 2 paso a paso

**Pregunta:** ¿cuándo pasó el vehículo por este lugar?

### 3.1 Por qué segmentos y no solo puntos (ejemplo numérico)

A 50 km/h el vehículo avanza 13,9 m/s. Con un punto cada 10 s, hay **139 m entre puntos**. Si el centro de un círculo de radio 50 m (100 m de diámetro) cae justo a la mitad entre dos muestras:

```
    punto k                 centro                punto k+1
  ────●───────────────(──────✕──────)───────────────●────
      ←────── 69,5 m ──────→        ←────── 69,5 m ──────→
                      ←─ 50 m ─→
```

- Ambos puntos quedan a **69,5 m del centro, fuera del círculo**, aunque el vehículo lo atravesó.
- Una consulta del tipo "puntos a menos de 50 m" diría que nunca pasó: es un **falso negativo**.
- El modo demo lo reproduce: hace 5 días a las 10:30 hay un cruce a 60 km/h (166,7 m entre puntos), con los puntos más cercanos a **83,3 m** de Uninorte.
  - Con radio 50 m, el sistema detecta **1 paso con 0 puntos dentro** y 6 s de duración: 100 m a 16,67 m/s.
  - La prueba es [tests/test_analisis_lugar.py:83](tests/test_analisis_lugar.py#L83).
  - Si se quitan los segmentos del algoritmo, esa prueba falla (se comprobó con una prueba de mutación).

### 3.2 La matemática de la intersección segmento–círculo

1. **Proyección local a metros**, con el centro C como origen ([analisis_lugar.py:50](analisis_lugar.py#L50)):
   `x = R·Δλ·cos φ₀`, `y = R·Δφ`.
   Para distancias de pocos kilómetros el error frente a Haversine es de centímetros, y el problema pasa a ser de geometría plana.
2. **Ecuación del segmento:** `P(t) = A + t·D`, con `t ∈ [0,1]`, `A` = primer punto relativo a C y `D = B − A`.
3. **Condición de estar sobre el borde:** `|A + t·D|² = r²`, que expandida da:

   ```
   (D·D)·t² + 2(A·D)·t + (A·A − r²) = 0
   ```

   Los coeficientes están en [analisis_lugar.py:72-74](analisis_lugar.py#L72-L74).
4. **Casos:**
   - Si el discriminante es menor que 0, la recta no toca el círculo ([:79-80](analisis_lugar.py#L79-L80)).
   - Si no, las raíces `t₁ ≤ t₂` ([:84-85](analisis_lugar.py#L84-L85)) se acotan: si `t₁ > 1` o `t₂ < 0`, la recta cruza el círculo pero fuera del segmento ([:86](analisis_lugar.py#L86)).
   - Si el segmento sí entra: `t_entrada = max(t₁, 0)` y `t_salida = min(t₂, 1)` ([:88](analisis_lugar.py#L88)).
5. **Tiempos por interpolación lineal**, suponiendo velocidad constante entre las dos muestras: `hora = t_k + t·(t_{k+1} − t_k)` ([:103-105](analisis_lugar.py#L103-L105), usada en [:183-184](analisis_lugar.py#L183-L184)).
6. **Momento más cercano:** `t* = clamp(−(A·D)/(D·D), 0, 1)` ([:99](analisis_lugar.py#L99)), con distancia `|A + t*·D|`.

**Ejemplo verificable** ([tests/test_analisis_lugar.py:58](tests/test_analisis_lugar.py#L58)): con A = (−100, 0), B = (100, 0) y r = 50, se tiene D = (200, 0) y la ecuación queda:

```
40000·t² − 40000·t + 7500 = 0
t = (40000 ± √(1,6·10⁹ − 1,2·10⁹)) / 80000 = (40000 ± 20000) / 80000
t₁ = 0,25   t₂ = 0,75
```

Es decir, el vehículo entra en x = −50 m y sale en x = +50 m.

### 3.3 Flujo completo

**En el navegador**

1. **"Filtrar por ubicación"** activa el filtro. El lugar se puede elegir de tres formas:
   - **Buscando una dirección o un sitio,** por ejemplo "Frisby calle 64" o "universidad del norte":
     - `BuscadorLugar` ([BuscadorLugar.jsx:16](disenop2web/src/components/BuscadorLugar.jsx#L16)) pide `buscar-lugar` ([:27](disenop2web/src/components/BuscadorLugar.jsx#L27)).
     - El backend valida el texto (3 a 100 caracteres, [validacion.py:112](validacion.py#L112)) y consulta Photon; si Photon no encuentra nada, consulta Nominatim ([geocodificacion.py:101-112](geocodificacion.py#L101-L112)).
     - Se quedan solo los resultados dentro del área de Barranquilla ([:121](geocodificacion.py#L121)), y aparece la lista para elegir.
     - Solo se busca al pulsar Enter o "Buscar", nunca en cada tecla, porque la política de uso de Nominatim prohíbe el autocompletado.
   - **Con un clic en el mapa.**
   - **Con un lugar guardado** (idea F).
   Elegir un resultado o un lugar guardado llama a `irALugar` ([App.jsx:355](disenop2web/src/App.jsx#L355)), que fija el lugar y encuadra el mapa. Los radios disponibles son 50, 100 y 200 m ([lugar.js:4](disenop2web/src/utils/lugar.js#L4)).
   - [CapaLugar.jsx:22](disenop2web/src/components/CapaLugar.jsx#L22) pone el cursor de mira.
   - El clic en el mapa solo actúa en este modo ([:26-28](disenop2web/src/components/CapaLugar.jsx#L26-L28)).
   - El marcador es arrastrable ([:62](disenop2web/src/components/CapaLugar.jsx#L62)).
   - El círculo se dibuja con `var(--accent)` semitransparente ([:52](disenop2web/src/components/CapaLugar.jsx#L52)).
2. **Clic en el mapa:** `fijarLugar` ([App.jsx:367](disenop2web/src/App.jsx#L367)).
3. **Consulta:** la **clave de consulta** ([App.jsx:288](disenop2web/src/App.jsx#L288)) reúne lugar, radio, rango activo y dispositivo.
   - El efecto pide `pasos-por-lugar` ([:303](disenop2web/src/App.jsx#L303)).
   - El resultado se guarda junto con la clave que lo produjo, así que nunca se muestra el resultado de un lugar anterior ([:315](disenop2web/src/App.jsx#L315)).

**En el backend**

4. `pasos_por_lugar()` ([servidorweb.py:149](servidorweb.py#L149)):
   - `leer_lugar` ([validacion.py:104](validacion.py#L104)): `lat` y `lon` obligatorios; `radio` de 20 a 2000 m.
   - Mismo `leer_rango` y mismo dispositivo que la Entrega 1.
   - Sin rango, se usan los últimos 30 días en hora de Bogotá ([servidorweb.py:22](servidorweb.py#L22), [:155-157](servidorweb.py#L155-L157)).
5. `segmentos_cerca` ([repositorio.py:122](repositorio.py#L122)):
   - Un **CTE** calcula `LAG()`/`LEAD()` sobre **todos** los puntos del dispositivo en la ventana ([:136-147](repositorio.py#L136-L147)), con `WINDOW w AS (ORDER BY timestamp_gps)`. Así, cada punto se une con su siguiente punto **real**.
   - **Después** se filtra por caja envolvente ([:151](repositorio.py#L151)): se conservan los segmentos cuya caja (`GREATEST`/`LEAST` de sus extremos) toca la caja del círculo ([analisis_lugar.py:108-113](analisis_lugar.py#L108-L113)).
   - En PostgreSQL, `GREATEST`/`LEAST` ignoran `NULL`: para el último punto, que no tiene siguiente, la caja es el punto mismo.
6. `analizar_pasos` ([analisis_lugar.py:221](analisis_lugar.py#L221)) llama a `detectar` ([:161](analisis_lugar.py#L161)), que genera dos tipos de detección:
   - **Por segmento:** para cada segmento válido ([:176](analisis_lugar.py#L176)): no más de 1 h, no más de 1 km y no más de 180 km/h ([:122](analisis_lugar.py#L122)). Si corta el círculo, genera una detección con entrada y salida interpoladas.
   - **Por punto:** cada punto dentro del círculo que **no sea un salto de GPS** ([:192](analisis_lugar.py#L192)). Un punto es salto si todos sus vecinos a menos de 1 h implican más de 180 km/h ([:130-146](analisis_lugar.py#L130-L146)). Así, un punto aislado real, por ejemplo tras 2 h sin señal, sí cuenta.
7. `agrupar` ([:197](analisis_lugar.py#L197)):
   - Une las detecciones separadas por 10 min o menos ([:202](analisis_lugar.py#L202)).
   - Suma el **tiempo realmente dentro** del círculo ([:207](analisis_lugar.py#L207)).
   - Es "parada" si ese tiempo llega a 5 min ([:234](analisis_lugar.py#L234)); si no, "paso".
   - Se eligió así y no por `salida − entrada`, porque dos cruces rápidos separados 5 min no son una parada ([tests/test_analisis_lugar.py:126](tests/test_analisis_lugar.py#L126)).
8. **Respuesta:** `{lugar, rango, total, pasos:[{entrada, salida, duracion_s, momento_mas_cercano, distancia_minima_m, puntos, tipo}]}`, en orden cronológico ([servidorweb.py:166](servidorweb.py#L166)).

**De vuelta en el navegador**

9. [ModoLugar.jsx:62](disenop2web/src/components/ModoLugar.jsx#L62) muestra el rango consultado, y [:74-75](disenop2web/src/components/ModoLugar.jsx#L74-L75) dice "El vehículo pasó N veces…" o el mensaje de estado vacío.
10. **Clic en un paso:** `seleccionarPaso` ([App.jsx:385](disenop2web/src/App.jsx#L385)).
    - Pide el historial de [entrada − 10 min, salida + 10 min] ([:393-394](disenop2web/src/App.jsx#L393-L394)).
    - `tramoEntre` ([lugar.js:14](disenop2web/src/utils/lugar.js#L14)) calcula el tramo dentro del círculo con los puntos de entrada y salida interpolados, y se dibuja grueso ([CapaLugar.jsx:46](disenop2web/src/components/CapaLugar.jsx#L46)).
    - Sus extremos quedan a 50,0 m del centro: el frontend interpola igual que el backend.
11. **"Salir del filtro por ubicación"** ([App.jsx:377](disenop2web/src/App.jsx#L377)) limpia solo el estado del lugar.

**El modo demo** implementa `segmentos_cerca` en memoria ([repositorio.py:199-206](repositorio.py#L199-L206)) con las mismas funciones `filas_con_vecinos` y `filtrar_por_caja`, así que la geometría es idéntica en los dos modos.

---

## 4. Zona horaria de principio a fin

| Etapa | Qué pasa | Dónde |
|---|---|---|
| Android | Formatea con desfase: `…:04.000 -05:00` | [UbicacionService.kt:164](gpslink-android/app/src/main/java/com/example/gpslink/UbicacionService.kt#L164) |
| Sniffer | `strptime(... %z)` y luego `replace(tzinfo=None)`: guarda la hora "de reloj" **sin zona** | [snifferwpostgresql.py:99-100](snifferwpostgresql.py#L99-L100) |
| Base de datos | `timestamp_gps` es un `timestamp` sin zona, en hora de Bogotá | — |
| SQL | "Ahora" es `NOW() AT TIME ZONE 'America/Bogota'`, del mismo tipo que la columna | [repositorio.py:116](repositorio.py#L116) |
| Python | `ahora_bogota()` con desfase fijo −05:00 | [tiempo_bogota.py:13](tiempo_bogota.py#L13), [:19](tiempo_bogota.py#L19) |
| JSON | Siempre `"YYYY-MM-DD HH:MM:SS"`, sin zona | [tiempo_bogota.py:24](tiempo_bogota.py#L24), [servidorweb.py:58](servidorweb.py#L58) |
| Navegador (entrada) | Se agrega `-05:00` explícito: `new Date("…T…-05:00")` | [tiempo.js:10-14](disenop2web/src/utils/tiempo.js#L10-L14) |
| Navegador (salida) | `Intl.DateTimeFormat` con `timeZone: "America/Bogota"` | [tiempo.js:18](disenop2web/src/utils/tiempo.js#L18) y siguientes |
| Navegador ("hoy") | Fecha de Bogotá, no del navegador | [tiempo.js:68](disenop2web/src/utils/tiempo.js#L68) |

**Qué estaba mal antes**

- **En el frontend:** se agregaba `"Z"`, así que 10:00 de Bogotá se leía como 10:00 UTC (05:00 en Bogotá). Todo se mostraba 5 h antes y el estado "en línea" nunca aparecía.
- **En el SQL:** con `NOW()` a secas, PostgreSQL interpretaba la columna en la zona de la sesión (UTC en RDS). La ventana de "24 h" cubría en realidad **19 h**.

**Por qué −05:00 fijo:** Colombia no tiene horario de verano desde 1993, así que el desfase fijo es exacto. En Windows, `ZoneInfo` exigiría el paquete `tzdata`.

**Verificación:** con el proceso de Node configurado en `Asia/Tokyo`, `getHours()` devolvía 13, pero la interfaz seguía mostrando 23:30 del 24/09 de Bogotá.

---

## 5. Seguridad

1. **Consultas parametrizadas.**
   - Ningún valor del usuario se concatena en el SQL: fechas, dispositivo, horas y caja viajan como `%s` ([repositorio.py:106](repositorio.py#L106), [:116-117](repositorio.py#L116-L117), [:151](repositorio.py#L151)).
   - Hay pruebas que capturan el SQL con un cursor falso y comprueban que los valores **no** aparecen en el texto ([tests/test_historial.py:161](tests/test_historial.py#L161), [tests/test_api_lugar.py:93](tests/test_api_lugar.py#L93)).
2. **Validación de entrada en el backend** ([validacion.py](validacion.py)):

   | Parámetro | Regla | Línea |
   |---|---|---|
   | `desde`, `hasta` | Formato exacto con `strptime` (rechaza el 30 de febrero) | [:33](validacion.py#L33) |
   | `horas` | Entero entre 1 y 720 | [:70](validacion.py#L70) |
   | `device_id` | `[\w-]{1,64}`, el mismo conjunto de caracteres que acepta el sniffer | [:23](validacion.py#L23) |
   | Coordenadas y radio | Finitos y dentro de su rango (rechaza `NaN`/`inf`) | [:99](validacion.py#L99) |

   Pruebas: [tests/test_historial.py:46](tests/test_historial.py#L46) y [tests/test_api_lugar.py:47](tests/test_api_lugar.py#L47).
3. **Errores sin filtrar detalles internos.**
   - Si la base de datos falla, se responde un 503 con un mensaje genérico; el detalle va solo al log del servidor ([servidorweb.py:74-77](servidorweb.py#L74-L77), prueba [tests/test_historial.py:111](tests/test_historial.py#L111)).
   - Los errores de validación son 400 en español ([servidorweb.py:68-70](servidorweb.py#L68-L70)).
   - Las conexiones se cierran siempre, en un `finally` ([repositorio.py:68](repositorio.py#L68)).
4. **Credenciales en `.env`.**
   - Se leen con `os.getenv` ([repositorio.py:40-50](repositorio.py#L40-L50)).
   - `.env` y `global-bundle.pem` están en `.gitignore`.
   - La conexión usa `sslmode=verify-full`.
   - `.env-template` documenta las variables sin sus valores.
5. **Modo demo aislado.** Con `MODO_DEMO=1`, `psycopg2` ni siquiera se importa ([repositorio.py:54](repositorio.py#L54)). Una prueba lo verifica en un intérprete donde importarlo falla a propósito ([tests/test_demo.py:153](tests/test_demo.py#L153)).
6. **Búsqueda de direcciones.**
   - El texto del usuario solo viaja como parámetro codificado (`urlencode`) hacia dos servidores **fijos** en el código ([geocodificacion.py:29-30](geocodificacion.py#L29-L30)). Nunca forma parte del host ni de la ruta, así que el endpoint no puede usarse para que el servidor haga peticiones a otros sitios (SSRF).
   - La aplicación se identifica ante los servicios con un `User-Agent` propio ([:21](geocodificacion.py#L21)), como exige la política de Nominatim.
   - Si los servicios fallan o responden con un formato inesperado, la API responde un 502 con un mensaje en español, nunca un 500 ([servidorweb.py:82-87](servidorweb.py#L82-L87)).
   - Las pruebas simulan las respuestas y no dependen de internet ([tests/test_busqueda.py](tests/test_busqueda.py)).
7. **Frontend.**
   - React escapa todo el texto mostrado, así que un nombre como `<script>` nunca se ejecuta.
   - Lo que viene de la URL ([estadoUrl.js:15-18](disenop2web/src/utils/estadoUrl.js#L15-L18)) y de `localStorage` ([lugaresGuardados.js:14](disenop2web/src/utils/lugaresGuardados.js#L14)) se valida como entrada externa.

---

## 6. Ideas adicionales implementadas

| Idea | Qué hace | Dónde |
|---|---|---|
| **A. Estadísticas** | Distancia (Haversine), duración, velocidad promedio y máxima. La máxima usa ventanas de 30 s o más en línea recta, para no confundir el ruido del GPS con picos (con 10 s daba 64,7 km/h en datos que nunca superan 60) | [estadisticas.js:6](disenop2web/src/utils/estadisticas.js#L6), [:29-37](disenop2web/src/utils/estadisticas.js#L29-L37); [App.jsx:479](disenop2web/src/App.jsx#L479) |
| **B. Reproducir** | Play/Pausa, barra de tiempo, 10x/60x/300x y hora simulada. El marcador es un `L.circleMarker` movido con `setLatLng` dentro de `requestAnimationFrame`, así que no re-renderiza `App`. La posición se interpola con búsqueda binaria | [Reproductor.jsx:31](disenop2web/src/components/Reproductor.jsx#L31), [:50](disenop2web/src/components/Reproductor.jsx#L50), [:58-69](disenop2web/src/components/Reproductor.jsx#L58-L69); [viajes.js:124](disenop2web/src/utils/viajes.js#L124) |
| **C. Paradas** | Tramos de 5 min o más dentro de 50 m de un punto **ancla**, marcados con "⏸ N min" | [paradas.js:16-25](disenop2web/src/utils/paradas.js#L16-L25); [App.jsx:487](disenop2web/src/App.jsx#L487) |
| **D. Enlace** | Rango, lugar, radio y ruta en la URL (`replaceState`), restaurados y validados al abrirla. "Copiar enlace" usa `navigator.clipboard` y, sin HTTPS, `execCommand` | [estadoUrl.js:27](disenop2web/src/utils/estadoUrl.js#L27), [:56](disenop2web/src/utils/estadoUrl.js#L56), [:78](disenop2web/src/utils/estadoUrl.js#L78); [App.jsx:107](disenop2web/src/App.jsx#L107), [:178](disenop2web/src/App.jsx#L178) |
| **E. Clic en la lista** | Vuela al punto, lo resalta y pausa el centrado. La lista es `React.memo` | [ListaPuntos.jsx:53](disenop2web/src/components/ListaPuntos.jsx#L53); [App.jsx:529](disenop2web/src/App.jsx#L529) |
| **F. Lugares guardados** | Guarda lugares con nombre en `localStorage`, con `try/catch` y validación; se consultan con un clic | [lugaresGuardados.js:28](disenop2web/src/utils/lugaresGuardados.js#L28), [:42](disenop2web/src/utils/lugaresGuardados.js#L42); [App.jsx:327](disenop2web/src/App.jsx#L327), [:363](disenop2web/src/App.jsx#L363) |

### Interfaz del mapa (FASE 5)

- **La gota.** Es un SVG con el ancla en la punta: `iconAnchor = [15, 38]` ([MarcadorActual.jsx:23](disenop2web/src/components/MarcadorActual.jsx#L23)), así que la punta marca la coordenada exacta. El clic hace `flyTo` a zoom 17 o mayor y abre un popup ([:35-55](disenop2web/src/components/MarcadorActual.jsx#L35-L55)).
- **Centrado automático.**
  - Hace `panTo` sin cambiar el zoom, y solo cuando el punto sale del 60 % central de la zona libre ([CentradoAutomatico.jsx:35-37](disenop2web/src/components/CentradoAutomatico.jsx#L35-L37)).
  - Arrastrar o hacer zoom lo pausa 15 s ([:21-24](disenop2web/src/components/CentradoAutomatico.jsx#L21-L24)).
  - Los movimientos del código se marcan en un `WeakSet` para no confundirlos con los del usuario ([mapa.js:12-29](disenop2web/src/utils/mapa.js#L12-L29)).
- **Zona libre.** Todo centrado y encuadre usa la parte del mapa que no tapa la columna de paneles ([mapa.js:41](disenop2web/src/utils/mapa.js#L41)), tanto en escritorio (columna a la izquierda) como en celular (columna arriba y plegable).

---

## 7. Guion de demo de 5 minutos

**Preparación:** sigue [README-dev.md](README-dev.md): `$env:MODO_DEMO="1"; python servidorweb.py` y `npm run dev`, y abre `http://localhost:5173`. Los datos demo se generan relativos a **hoy**, así que las fechas cambian según el día; aquí se indican como "hace N días".

| Minuto | Qué hacer | Qué decir |
|---|---|---|
| 0:00 | Mostrar la pantalla en vivo; esperar una actualización | "La gota es la última posición. Cada 10 s llega un punto nuevo; el mapa solo se desplaza si la gota sale del 60 % central, y respeta el zoom." |
| 0:30 | Arrastrar el mapa | "Si el usuario mueve el mapa, el centrado se pausa 15 s; aquí se ve la cuenta regresiva." |
| 0:45 | Clic en la gota | "Vuela a zoom 17 y muestra coordenadas, hora de Bogotá, hace cuánto y la velocidad estimada con el punto anterior." |
| 1:00 | **Entrega 1:** Desde = hace 7 días 07:00, Hasta = hace 7 días 08:30, Aplicar | "Consulta parametrizada con BETWEEN. El historial se separa en viajes: más de 1 h o 1 km, viaje nuevo; más de 180 km/h, error de GPS." |
| 1:30 | Señalar el inicio verde, el fin coral, "⏸ 8 min" y las estadísticas | "La ruta terminó, por eso es 'Fin de ruta' y no 'Actual'. Aquí hay una parada de 8 minutos en Uninorte." |
| 2:00 | Play a 60x | "Reproduce el recorrido; en la parada el marcador se queda quieto unos 8 segundos reales." |
| 2:20 | Desde = hace 9 días, Hasta = hoy 23:59, Aplicar | "Hasta es futura, así que se ajusta a la hora actual y avisa. El selector tiene todas las rutas del periodo." |
| 2:40 | Elegir la ruta de hace 8 días | "Aquí hubo un salto de GPS a 6 km: se descartó y la línea no salta al mar." |
| 3:00 | **Entrega 2:** "Filtrar por ubicación", buscar "universidad del norte", elegir el primer resultado y poner radio 50 m | "Consulta los pasos por el círculo con LEAD en SQL e intersección segmento–círculo en Python." |
| 3:30 | Señalar el paso de hace 5 días (6 s) | "Este cruce fue a 60 km/h: ningún punto quedó a menos de 50 m (el más cercano, a 83 m), pero el segmento sí atraviesa el círculo. Contando solo puntos, no aparecería." |
| 4:00 | Clic en el paso "Parada" | "Carga ±10 minutos alrededor y resalta el tramo dentro del círculo, con la entrada y la salida interpoladas." |
| 4:30 | Guardar "Uninorte" y pulsar "Copiar enlace" | "El lugar queda en localStorage, y el enlace guarda rango, lugar y radio en la URL." |
| 4:50 | "Salir del filtro por ubicación" | "Vuelve exactamente al estado anterior." |

---

## 8. Las 15 preguntas más probables

1. **¿Qué problema tenía `NOW()` y cómo se corrigió?**
   `NOW()` es un instante con zona, y la columna no tiene zona. PostgreSQL interpretaba la columna en UTC, así que la ventana de 24 h cubría en realidad 19 h de Bogotá. `NOW() AT TIME ZONE 'America/Bogota'` da la hora "de reloj" de Bogotá, del mismo tipo que la columna. → [repositorio.py:116](repositorio.py#L116)

2. **¿Cómo evitan la inyección SQL?**
   Todos los valores van como parámetros `%s`, que psycopg2 escapa. Además, `device_id` se valida con una expresión regular, y hay pruebas que verifican que los valores no aparecen en el texto del SQL. → [repositorio.py:106](repositorio.py#L106), [validacion.py:23](validacion.py#L23), [tests/test_historial.py:161](tests/test_historial.py#L161)

3. **¿Por qué la hora es correcta aunque el navegador esté en otro país?**
   Al leer, se agrega `-05:00` explícito, y al mostrar se formatea con `timeZone: "America/Bogota"`. Nunca se usa `getHours()`, que depende de la zona del navegador. → [tiempo.js:14](disenop2web/src/utils/tiempo.js#L14), [:18](disenop2web/src/utils/tiempo.js#L18)

4. **¿Cómo se separa el historial en viajes?**
   Más de 1 h sin puntos, o más de 1 km entre puntos, inicia un viaje nuevo. Una velocidad de más de 180 km/h se descarta como error de GPS. → [viajes.js:46-69](disenop2web/src/utils/viajes.js#L46-L69)

5. **¿Por qué comparar con el último punto *aceptado*?**
   En la secuencia A → G (error a 6 km) → B, comparar B con G también daría unos 2.000 km/h, y se perdería B, que es un punto bueno. Comparado con A, B se acepta. → [viajes.js:65](disenop2web/src/utils/viajes.js#L65)

6. **¿Por qué identificar los viajes por timestamp y no por índice?**
   En vivo, la ventana de 24 h se desliza: cuando sale un viaje viejo, los índices de todos los demás se corren. El timestamp del primer punto es estable. → [viajes.js:74](disenop2web/src/utils/viajes.js#L74)

7. **¿Por qué segmentos y no solo puntos?**
   A 50 km/h hay 139 m entre puntos; un círculo de 100 m de diámetro se cruza sin dejar ningún punto adentro. → [sección 3.1](#31-por-qué-segmentos-y-no-solo-puntos-ejemplo-numérico), [tests/test_analisis_lugar.py:83](tests/test_analisis_lugar.py#L83)

8. **Demuestre la intersección segmento–círculo.**
   `|A + tD|² = r²` da `(D·D)t² + 2(A·D)t + (A·A − r²) = 0`; las raíces se acotan a [0,1]. → [analisis_lugar.py:61-88](analisis_lugar.py#L61-L88), [sección 3.2](#32-la-matemática-de-la-intersección-segmentocírculo)

9. **¿Por qué `LEAD()` va en un CTE y el filtro de caja afuera?**
   `WHERE` se evalúa antes que las funciones de ventana. Si se filtrara primero, `LEAD()` devolvería el siguiente punto *dentro de la caja*, no el siguiente real. → [repositorio.py:136-151](repositorio.py#L136-L151)

10. **¿Cómo distinguen un punto aislado real de un error de GPS?**
    Es error si todos sus vecinos a menos de 1 h implican más de 180 km/h. Si sus vecinos están lejos en el tiempo, es un punto aislado real y cuenta. → [analisis_lugar.py:130-146](analisis_lugar.py#L130-L146), [:192](analisis_lugar.py#L192)

11. **¿Cómo agrupan detecciones y deciden "parada"?**
    Las detecciones a 10 min o menos forman un paso. Es parada si el tiempo *dentro* del círculo suma 5 min o más; no se usa entrada−salida, porque dos cruces rápidos no son una parada. → [analisis_lugar.py:197-207](analisis_lugar.py#L197-L207), [:234](analisis_lugar.py#L234)

12. **Con un rango de fechas activo, ¿por qué no se actualiza cada 10 s?**
    Hasta nunca es futura (se ajusta a "ahora"), así que el rango ya terminó y no pueden llegar puntos nuevos. → [App.jsx:272](disenop2web/src/App.jsx#L272)

13. **¿Cómo probaron sin tocar la base de datos compartida?**
    Con `MODO_DEMO=1` se usa un repositorio en memoria con datos determinísticos (semilla fija), con los mismos endpoints. Hay 74 pruebas con pytest, ninguna usa la base real. → [repositorio.py:30](repositorio.py#L30), [datos_demo.py:18](datos_demo.py#L18), [tests/test_demo.py:153](tests/test_demo.py#L153)

14. **¿Cómo sabe el centrado si el zoom lo hizo el usuario?**
    Todo movimiento del código se marca en un `WeakSet` hasta su `moveend`; un `zoomstart` sin marca es del usuario. → [mapa.js:12-29](disenop2web/src/utils/mapa.js#L12-L29), [CentradoAutomatico.jsx:21-24](disenop2web/src/components/CentradoAutomatico.jsx#L21-L24)

15. **¿Qué pasa si la base de datos se cae?**
    El backend responde un 503 en JSON con un mensaje genérico y cierra la conexión en un `finally`. El frontend revisa `response.ok` y muestra el mensaje sin romper el mapa. → [servidorweb.py:74-77](servidorweb.py#L74-L77), [repositorio.py:68](repositorio.py#L68), [api.js:19-22](disenop2web/src/utils/api.js#L19-L22)

---

## 9. Limitaciones conocidas y mejoras futuras

**Datos y captura**

- **El sniffer descarta el desfase sin convertirlo** a Bogotá ([snifferwpostgresql.py:100](snifferwpostgresql.py#L100)). La hora es correcta solo si el teléfono está en −05:00.
- **`timestamp_recepcion` usa la zona del servidor** (`datetime.now()`, [:75](snifferwpostgresql.py#L75)), probablemente UTC.
- **Mejora:** convertir con `astimezone` a Bogotá antes de quitar la zona. No se hizo porque el sniffer está fuera del alcance de estas entregas.

**Rendimiento**

- **Cada petición abre una conexión SSL nueva a la RDS.** Mejora: un pool de conexiones (`psycopg2.pool`).
- **En vivo se descargan las 24 h completas cada 10 s.** Mejora: consulta incremental (`desde = último timestamp recibido`).
- **La consulta por lugar recorre todos los puntos del dispositivo en la ventana.** Depende del índice único `(device_id, timestamp_gps)`, que existe por el `ON CONFLICT` pero no se verificó en la RDS.

**Modelo geométrico**

- **Entre dos muestras se asume una línea recta y velocidad constante.** En curvas cerradas, la entrada y la salida interpoladas son aproximadas.
- **La proyección equirectangular** es exacta para radios de hasta 2 km, pero no para distancias grandes.
- **Si el primer punto de un periodo es un error de GPS,** los siguientes se descartan hasta que la velocidad implícita baje de 180 km/h.
- **Una sola muestra atípica en medio de una parada (idea C)** la divide en dos.

**Aplicación**

- **"Ahora" en el frontend sale del reloj del navegador.** Si ese reloj está desfasado, el ajuste de Hasta será impreciso.
- **Solo se consulta un dispositivo** (el del registro más reciente); no hay selector de dispositivo en la interfaz, y el enlace compartible no incluye `device_id`.
- **`CORS(app)` acepta cualquier origen.** En producción el frontend y la API comparten origen, así que podría restringirse.
- **El frontend no tiene pruebas automatizadas** (no se agregaron dependencias). La lógica de `utils/` se verificó con scripts de Node sobre los datos demo.

**Búsqueda de direcciones**

- **Depende de los datos de OpenStreetMap.** Por ejemplo, "Frisby calle 64" encuentra un Frisby de la Calle 106, probablemente porque el de la Calle 64 no está registrado en el mapa. Por eso se muestran varios resultados para elegir, y siempre se puede marcar el lugar en el mapa.
- **Las direcciones con nomenclatura colombiana** ("Cra 51B # 79-10") se resuelven mal: OpenStreetMap ubica bien la calle, pero no el número de placa.
- **Necesita internet y depende de dos servicios gratuitos públicos,** que pueden fallar o limitar peticiones. La caché ([geocodificacion.py:100](geocodificacion.py#L100)) evita repetir búsquedas iguales. Mejora: un servicio comercial de geocodificación (como Google Places), que exigiría una clave de API.

**Despliegue**

- **`marcela-test` no se despliega:** los workflows solo despliegan `main` y `sthefany-test`. Esta versión corre en local.
- **Los datos demo** se generan relativos al día actual, y las sesiones "en vivo" se reinician a medianoche.
