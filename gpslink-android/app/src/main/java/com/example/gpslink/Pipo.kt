package com.example.gpslink

import android.Manifest
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.media.AudioManager
import android.media.ToneGenerator
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.speech.RecognitionListener
import android.speech.RecognizerIntent
import android.speech.SpeechRecognizer
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import androidx.core.content.ContextCompat
import org.json.JSONArray
import org.json.JSONObject
import org.vosk.LibVosk
import org.vosk.LogLevel
import org.vosk.Model
import org.vosk.Recognizer
import org.vosk.android.SpeechService
import java.io.File
import java.io.FileOutputStream
import java.net.HttpURLConnection
import java.net.URL
import java.util.Locale
import java.util.concurrent.Executors
import java.util.zip.ZipInputStream

// Pipo, the driver's voice assistant (P3-S5).
//
//   DORMIDO ---"Pipo"---> ESCUCHANDO ---question---> PENSANDO ---answer---> HABLANDO
//      ^  (Vosk, offline,       (Android's              (POST /api/pipo:         |
//      |   only knows "pipo")    SpeechRecognizer)        server + Groq)          |
//      +-------------------------------------------------------------------------+
//
// It also speaks on its own when a sign arrives from the Pi ("Límite 30, vas a 42…")
// and when the car keeps going over the last limit seen. Everything runs on the main
// thread except the network and the model download. Lives inside UbicacionService,
// so it keeps working with the screen off.
object Pipo {

    enum class Estado { APAGADO, PREPARANDO, DORMIDO, ESCUCHANDO, PENSANDO, HABLANDO }

    // Read by the screen.
    @Volatile var estado = Estado.APAGADO
        private set
    @Volatile var detalle = ""              // "Descargando voz 40 %", errors...
        private set
    @Volatile var ultimaPregunta = ""
        private set
    @Volatile var ultimaRespuesta = ""
        private set
    @Volatile var ultimaFrase = ""          // last thing Pipo said (answer or warning)
        private set
    // From "Pipo"/tap until the answer has been spoken: the screen shows the sheet.
    @Volatile var enConversacion = false
        private set
    @Volatile var nivelVoz = 0f             // mic level while listening (dB), for the waves
        private set

    // Offline Spanish model for the wake word (~40 MB, downloaded once on first use).
    private const val NOMBRE_MODELO = "vosk-model-small-es-0.42"
    private const val URL_MODELO = "https://alphacephei.com/vosk/models/$NOMBRE_MODELO.zip"

    // Words that wake Pipo up. The recognizer is limited to the ones its dictionary
    // has (anything else is "[unk]"), which keeps it light and avoids false alarms.
    private val PALABRAS_DESPERTAR = listOf("pipo", "pipó", "pipa")

    private const val REPETIR_AVISO_SENAL_MS = 20_000L   // same sign twice -> one warning
    private const val REPETIR_AVISO_VELOCIDAD_MS = 45_000L

    private val main = Handler(Looper.getMainLooper())
    private val red = Executors.newSingleThreadExecutor()
    // The ~40 MB model download has its own thread, so a question asked meanwhile
    // doesn't wait behind it.
    private val descarga = Executors.newSingleThreadExecutor()

    private var ctx: Context? = null
    private var alCambiar: () -> Unit = {}

    private var tts: TextToSpeech? = null
    private var ttsListo = false
    private var ttsFallo = false                  // the phone has no usable voice
    private val porDecir = ArrayDeque<String>()   // waits while Pipo listens/thinks
    private var hablando = 0                      // utterances still playing

    private var modelo: Model? = null
    private var cargandoModelo = false
    // Vosk's native library can't load on this phone (e.g. 16 KB memory pages):
    // no wake word, but tapping Pipo still works and the app keeps running.
    @Volatile private var voskNoDisponible = false
    private const val SIN_PALABRA = "En este celular no puedo oír «Pipo». Tócame para preguntarme."
    private var vosk: SpeechService? = null
    private var reconocedorVosk: Recognizer? = null
    private var reconocedor: SpeechRecognizer? = null
    private var ignorarHastaMs = 0L               // don't wake up from Pipo's own voice
    private var consulta = 0                      // a cancelled question ignores its late answer

    private var ultimoAvisoSenal = ""
    private var ultimoAvisoSenalMs = 0L
    private var ultimoAvisoVelMs = 0L

    // --- Lifecycle (called by UbicacionService) ---

    fun iniciar(contexto: Context, cambio: () -> Unit) {
        alCambiar = cambio
        if (ctx != null) { aplicarAjuste(); return }
        val app = contexto.applicationContext
        ctx = app
        ttsFallo = false
        tts = TextToSpeech(app) { status ->
            if (status == TextToSpeech.SUCCESS) configurarVoz()
            else { ttsFallo = true; soltarPendientes() }
        }
        aplicarAjuste()
    }

    fun detener() {
        alCambiar = {}   // the service is going away: don't touch its notification
        consulta++
        enConversacion = false
        main.removeCallbacksAndMessages(null)
        apagarMicrofono()
        tts?.shutdown()
        tts = null
        ttsListo = false
        porDecir.clear()
        hablando = 0
        cargandoModelo = false
        try { modelo?.close() } catch (e: Exception) {}
        modelo = null
        ctx = null
        cambiar(Estado.APAGADO, "")
    }

    // On/off from the screen (the setting is saved in Ajustes).
    fun aplicarAjuste() {
        val c = ctx ?: return
        if (!Ajustes.pipoActivo(c)) {
            consulta++
            apagarMicrofono()
            porDecir.clear()
            tts?.stop()
            hablando = 0
            enConversacion = false
            cambiar(Estado.APAGADO, "")
            return
        }
        if (estado == Estado.APAGADO) cambiar(Estado.PREPARANDO, "")
        prepararModelo()
        volverADormir()
    }

    // Tap on Pipo: ask without saying the wake word (also a fallback for noisy cars).
    fun preguntarAhora() {
        val c = ctx ?: return
        if (!Ajustes.pipoActivo(c)) return
        if (estado == Estado.ESCUCHANDO || estado == Estado.PENSANDO) return
        tts?.stop()
        hablando = 0
        despertar()
    }

    // "Cancelar" on the sheet: drop the question/answer and go back to sleep.
    fun cancelar() {
        consulta++
        apagarMicrofono()
        tts?.stop()
        porDecir.clear()
        hablando = 0
        enConversacion = false
        cambiar(Estado.DORMIDO, "")
        volverADormir()
    }

    // "Listo" on the sheet: the driver finished the question.
    fun dejarDeEscuchar() {
        reconocedor?.stopListening()
    }

    // --- Automatic warnings ---

    // A detection line just forwarded to the server (same format as the server's).
    fun anunciarDeteccion(linea: String) {
        val c = ctx ?: return
        if (!Ajustes.pipoActivo(c)) return
        val senal = campoLinea(linea, "Senal") ?: return
        val ahora = SystemClock.elapsedRealtime()
        if (senal == ultimoAvisoSenal && ahora - ultimoAvisoSenalMs < REPETIR_AVISO_SENAL_MS) return
        ultimoAvisoSenal = senal
        ultimoAvisoSenalMs = ahora

        val vel = (campoLinea(linea, "Vel GPS")?.toFloatOrNull()
            ?: campoLinea(linea, "Vel MPU")?.toFloatOrNull())
        val excede = linea.split(",").any { it.trim() == "EXCEDE" }
        val limite = Regex("^LIMITE\\s+(\\d+)$").find(senal)?.groupValues?.get(1)

        val frase = when {
            limite != null && excede && vel != null -> {
                ultimoAvisoVelMs = ahora
                "Ojo, el límite es de $limite y vas a ${vel.toInt()} kilómetros por hora. Baja la velocidad."
            }
            limite != null -> "Límite de $limite kilómetros por hora."
            senal.startsWith("PARE") -> "Pare adelante. Detén el carro por completo."
            senal.startsWith("CEDA") -> "Ceda el paso adelante. Mira bien antes de seguir."
            else -> "Ojo, señal de ${senal.lowercase(Locale("es"))}."
        }
        decir(frase)
    }

    // Called by the service ~10 s after a PARE with the lowest GPS speed since then.
    fun resultadoPare(velMinKmh: Float?) {
        val c = ctx ?: return
        if (!Ajustes.pipoActivo(c) || velMinKmh == null) return
        decir(if (velMinKmh <= 5f) "Bien hecho, hiciste el pare."
              else "No te detuviste en el pare. La próxima vez frena por completo.")
    }

    // Every GPS fix: warns again if the car stays over the last limit seen.
    fun revisarVelocidad(kmh: Float) {
        val c = ctx ?: return
        if (!Ajustes.pipoActivo(c)) return
        val limite = EstadoApp.limiteKmh
        if (limite <= 0 || System.currentTimeMillis() - EstadoApp.limiteMs > 15 * 60_000L) return
        if (kmh <= limite + Ajustes.TOLERANCIA_KMH) return
        val ahora = SystemClock.elapsedRealtime()
        if (ahora - ultimoAvisoVelMs < REPETIR_AVISO_VELOCIDAD_MS) return
        ultimoAvisoVelMs = ahora
        decir("Vas a ${kmh.toInt()} en zona de $limite.")
    }

    // --- Voice out (TextToSpeech) ---

    private fun configurarVoz() {
        val t = tts ?: return
        val idiomas = listOf(Locale("es", "CO"), Locale("es", "US"), Locale("es", "MX"), Locale("es", "ES"), Locale("es"))
        idiomas.firstOrNull {
            val r = t.setLanguage(it)
            r != TextToSpeech.LANG_MISSING_DATA && r != TextToSpeech.LANG_NOT_SUPPORTED
        }
        // Pipo is a man: a male Spanish voice if the phone has one (names vary by
        // brand), and a slightly lower pitch either way.
        try {
            t.voices?.filter { it.locale.language == "es" && !it.isNetworkConnectionRequired }
                ?.firstOrNull { v ->
                    val n = v.name.lowercase(Locale.US)
                    ("male" in n && "female" !in n) || n.contains("-esd-") || n.contains("-eed-")
                }?.let { t.setVoice(it) }
        } catch (e: Exception) { }
        t.setPitch(0.85f)
        t.setSpeechRate(1.05f)
        t.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
            override fun onStart(id: String?) {}
            override fun onDone(id: String?) { main.post { terminoFrase() } }
            @Deprecated("Deprecated in Java")
            override fun onError(id: String?) { main.post { terminoFrase() } }
        })
        ttsListo = true
        if (porDecir.isNotEmpty() && estado != Estado.ESCUCHANDO && estado != Estado.PENSANDO) soltarPendientes()
    }

    // Speaks now, or after the current question if Pipo is listening/thinking
    // (otherwise it would hear itself, or talk over the driver).
    private fun decir(texto: String) {
        porDecir.addLast(texto)
        if (estado != Estado.ESCUCHANDO && estado != Estado.PENSANDO) soltarPendientes()
    }

    private fun soltarPendientes() {
        val t = tts
        if (ttsFallo) {
            // Nothing can be spoken: drop it instead of staying "speaking" forever.
            porDecir.clear()
            hablando = 0
            enConversacion = false
            cambiar(Estado.DORMIDO, "Este celular no tiene voz en español (Ajustes → Texto a voz)")
            volverADormir()
            return
        }
        if (t == null || !ttsListo || porDecir.isEmpty()) {
            if (porDecir.isEmpty() && hablando == 0) volverADormir()
            return
        }
        apagarMicrofono()
        cambiar(Estado.HABLANDO, "")
        while (porDecir.isNotEmpty()) {
            val texto = porDecir.removeFirst()
            ultimaFrase = texto
            hablando++
            val r = t.speak(texto, TextToSpeech.QUEUE_ADD, null, "pipo-${SystemClock.elapsedRealtime()}-$hablando")
            if (r != TextToSpeech.SUCCESS) hablando--   // no onDone will come for it
        }
        if (hablando == 0) terminoFrase()
    }

    private fun terminoFrase() {
        hablando = (hablando - 1).coerceAtLeast(0)
        if (hablando > 0) return
        ignorarHastaMs = SystemClock.elapsedRealtime() + 800
        if (porDecir.isNotEmpty()) { soltarPendientes(); return }
        enConversacion = false
        volverADormir()
    }

    // --- Wake word (Vosk) ---

    private fun volverADormir() {
        val c = ctx ?: return
        if (!Ajustes.pipoActivo(c) || hablando > 0) return
        if (estado == Estado.ESCUCHANDO || estado == Estado.PENSANDO) return
        if (!tienePermisoMicrofono(c)) {
            cambiar(Estado.DORMIDO, "Sin permiso de micrófono: solo avisos")
            return
        }
        if (!EstadoApp.microfonoEnServicio) {
            cambiar(Estado.DORMIDO, "Abre la app para activar el micrófono")
            return
        }
        if (voskNoDisponible) {
            cambiar(Estado.DORMIDO, SIN_PALABRA)
            return
        }
        val m = modelo
        if (m == null) {
            if (!cargandoModelo) prepararModelo()
            if (estado != Estado.PREPARANDO) cambiar(Estado.PREPARANDO, detalle)
            return
        }
        if (vosk != null) { cambiar(Estado.DORMIDO, "Di «Pipo»"); return }
        try {
            // Vosk skips grammar words missing from the model (pipó isn't in vosk-model-small-es-0.42)
            val rec = Recognizer(m, 16_000f, JSONArray(PALABRAS_DESPERTAR + "[unk]").toString())
            val servicio = SpeechService(rec, 16_000f)
            servicio.startListening(oyentePalabra)
            reconocedorVosk = rec
            vosk = servicio
            cambiar(Estado.DORMIDO, "Di «Pipo»")
        } catch (e: LinkageError) {
            voskNoDisponible = true
            cambiar(Estado.DORMIDO, SIN_PALABRA)
        } catch (e: Exception) {
            cambiar(Estado.DORMIDO, "No se pudo abrir el micrófono")
        }
    }

    private val oyentePalabra = object : org.vosk.android.RecognitionListener {
        override fun onPartialResult(hypothesis: String?) = revisar(hypothesis, "partial")
        override fun onResult(hypothesis: String?) = revisar(hypothesis, "text")
        override fun onFinalResult(hypothesis: String?) = revisar(hypothesis, "text")
        override fun onError(exception: Exception?) {
            apagarMicrofono()
            main.postDelayed({ volverADormir() }, 2_000)
        }
        override fun onTimeout() {}

        private fun revisar(json: String?, clave: String) {
            if (json == null || vosk == null) return
            val texto = try { JSONObject(json).optString(clave) } catch (e: Exception) { "" }
            if (SystemClock.elapsedRealtime() < ignorarHastaMs) return
            if (texto.split(" ").any { it in PALABRAS_DESPERTAR }) despertar()
        }
    }

    private fun apagarMicrofono() {
        vosk?.let {
            try { it.stop(); it.shutdown() } catch (e: Exception) {}
        }
        vosk = null
        try { reconocedorVosk?.close() } catch (e: Exception) {}
        reconocedorVosk = null
        reconocedor?.let {
            try { it.cancel(); it.destroy() } catch (e: Exception) {}
        }
        reconocedor = null
    }

    // --- The question (Android's SpeechRecognizer, better at full sentences) ---

    private fun despertar() {
        val c = ctx ?: return
        apagarMicrofono()
        if (!tienePermisoMicrofono(c)) {
            decir("Necesito el permiso del micrófono para escucharte.")
            return
        }
        if (!SpeechRecognizer.isRecognitionAvailable(c)) {
            decir("Este celular no tiene reconocimiento de voz.")
            return
        }
        enConversacion = true
        nivelVoz = 0f
        cambiar(Estado.ESCUCHANDO, "")
        pitido()
        // A moment for Vosk to release the microphone and for the beep to end.
        main.postDelayed({ escucharPregunta() }, 350)
    }

    private fun escucharPregunta() {
        val c = ctx ?: return
        if (estado != Estado.ESCUCHANDO) return
        val sr = try { SpeechRecognizer.createSpeechRecognizer(c) } catch (e: Exception) { null }
        if (sr == null) { terminarPregunta(null); return }
        reconocedor = sr
        sr.setRecognitionListener(object : RecognitionListener {
            override fun onResults(results: Bundle?) {
                val texto = results?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                terminarPregunta(texto)
            }
            override fun onError(error: Int) = terminarPregunta(null)
            override fun onReadyForSpeech(params: Bundle?) {}
            override fun onBeginningOfSpeech() {}
            override fun onRmsChanged(rmsdB: Float) { nivelVoz = rmsdB }
            override fun onBufferReceived(buffer: ByteArray?) {}
            override fun onEndOfSpeech() {}
            override fun onPartialResults(partialResults: Bundle?) {
                val parcial = partialResults?.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION)?.firstOrNull()
                if (!parcial.isNullOrBlank()) cambiar(Estado.ESCUCHANDO, parcial)
            }
            override fun onEvent(eventType: Int, params: Bundle?) {}
        })
        val intent = Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM)
            .putExtra(RecognizerIntent.EXTRA_LANGUAGE, "es-CO")
            .putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true)
            .putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1)
        try { sr.startListening(intent) } catch (e: Exception) { terminarPregunta(null) }
    }

    private fun terminarPregunta(texto: String?) {
        if (estado != Estado.ESCUCHANDO) return
        reconocedor?.let { try { it.destroy() } catch (e: Exception) {} }
        reconocedor = null
        val pregunta = texto?.trim().orEmpty()
        if (pregunta.isEmpty()) {
            enConversacion = false
            cambiar(Estado.DORMIDO, "")
            decir("No te escuché bien. Dime «Pipo» y vuelve a preguntar.")
            return
        }
        ultimaPregunta = pregunta
        consultarServidor(pregunta)
    }

    // --- The answer (server: database + Groq) ---

    private fun consultarServidor(pregunta: String) {
        val c = ctx ?: return
        cambiar(Estado.PENSANDO, pregunta)
        val cuerpo = JSONObject()
            .put("device_id", Ajustes.deviceIdOCrear(c))
            .put("pregunta", pregunta)
            .put("contexto", contextoActual())
            .toString()
        val url = Ajustes.urlPipo(c)
        val miConsulta = ++consulta
        val local = respuestaLocal(pregunta)
        red.execute {
            val respuesta = try {
                val con = (URL(url).openConnection() as HttpURLConnection).apply {
                    requestMethod = "POST"
                    connectTimeout = 6_000
                    readTimeout = 25_000
                    doOutput = true
                    setRequestProperty("Content-Type", "application/json; charset=utf-8")
                }
                con.outputStream.use { it.write(cuerpo.toByteArray(Charsets.UTF_8)) }
                val codigo = con.responseCode
                val flujo = if (codigo in 200..299) con.inputStream else con.errorStream
                val texto = flujo?.bufferedReader(Charsets.UTF_8)?.use { it.readText() }.orEmpty()
                con.disconnect()
                // The server also puts a speakable "respuesta" in its errors. Anything that
                // isn't that JSON (404 page, Pipo turned off on the server) means the server
                // has no Pipo right now, which is not an internet problem.
                val json = try { JSONObject(texto) } catch (e: Exception) { null }
                json?.optString("respuesta")?.ifBlank { null }
                    ?: local
                    ?: if (codigo == 404 || json == null) "Ahora no puedo pensar respuestas: el servidor no tiene mi cerebro encendido. Igual te sigo avisando las señales."
                    else "El servidor respondió con un error $codigo."
            } catch (e: Exception) {
                local ?: "No pude conectarme con el servidor. Revisa el internet."
            }
            main.post {
                if (miConsulta != consulta || estado != Estado.PENSANDO) return@post   // cancelled
                ultimaRespuesta = respuesta
                cambiar(Estado.HABLANDO, "")
                porDecir.addFirst(respuesta)
                soltarPendientes()
            }
        }
    }

    // Simple questions the phone can answer by itself, used only when the server
    // can't (no internet, or Pipo is off on the server to save tokens).
    private fun respuestaLocal(pregunta: String): String? {
        val q = pregunta.lowercase(Locale("es"))
        val e = EstadoApp
        val ahora = System.currentTimeMillis()
        val v = if (e.ultimoFixMs > 0 && ahora - e.ultimoFixMs <= 5_000 && e.velocidadKmh >= 0) e.velocidadKmh.toInt() else null
        val limite = e.limiteKmh.takeIf { it > 0 && ahora - e.limiteMs <= 15 * 60_000L }
        return when {
            "límite" in q || "limite" in q || "máxima" in q || "maxima" in q ->
                if (limite != null) "El último límite que vi es de $limite kilómetros por hora." +
                        (if (v != null) " Vas a $v." else "")
                else "Todavía no he visto ninguna señal de límite."
            "velocidad" in q || "rápido" in q || "rapido" in q || "a cuánto" in q || "a cuanto" in q ->
                if (v != null) "Vas a $v kilómetros por hora." else "No tengo señal de GPS en este momento."
            "raspberry" in q || "cámara" in q || "camara" in q -> when {
                e.piUltimoMs == 0L -> "No hay ninguna Raspberry conectada."
                ahora - e.piUltimoMs > 15_000 -> "La Raspberry no responde hace un rato."
                e.piEstado == "PAUSADO" -> "La Raspberry está en pausa."
                else -> "La Raspberry está conectada y lleva ${e.piSenales.ifEmpty { "0" }} señales."
            }
            "señal" in q || "senal" in q || "señales" in q -> {
                val ultima = campoLinea(e.ultimaDeteccion, "Senal")
                if (ultima == null) "Todavía no he visto señales en este viaje."
                else "La última señal fue ${ultima.lowercase(Locale("es"))}, y van ${e.detRecibidas} en este viaje."
            }
            else -> null
        }
    }

    // What the phone knows right now; the server adds the history from the database.
    private fun contextoActual(): JSONObject {
        val e = EstadoApp
        val ahora = System.currentTimeMillis()
        val o = JSONObject()
        val fixReciente = e.ultimoFixMs > 0 && ahora - e.ultimoFixMs <= 5_000
        o.put("velocidad_kmh", if (fixReciente && e.velocidadKmh >= 0) e.velocidadKmh.toDouble() else JSONObject.NULL)
        o.put("limite_kmh", if (e.limiteKmh > 0 && ahora - e.limiteMs <= 15 * 60_000L) e.limiteKmh else JSONObject.NULL)
        o.put("lat", if (e.ultimoFixMs > 0) e.lat else JSONObject.NULL)
        o.put("lon", if (e.ultimoFixMs > 0) e.lon else JSONObject.NULL)
        o.put("raspberry", when {
            e.piUltimoMs == 0L -> "no conectada"
            ahora - e.piUltimoMs > 15_000 -> "sin respuesta"
            else -> e.piEstado.ifEmpty { "conectada" }
        })
        return o
    }

    // --- Wake-word model (downloaded once, then offline) ---

    private fun prepararModelo() {
        val c = ctx ?: return
        if (modelo != null || cargandoModelo || voskNoDisponible) return
        cargandoModelo = true
        val base = File(c.filesDir, "vosk")
        descarga.execute {
            // Load the native library first, so a phone that can't run it doesn't
            // download 40 MB for nothing. A LinkageError is not an Exception: uncaught,
            // it would close the whole app.
            val nativoOk = try { LibVosk.setLogLevel(LogLevel.WARNINGS); true } catch (e: Throwable) { false }
            if (!nativoOk) {
                main.post {
                    cargandoModelo = false
                    voskNoDisponible = true
                    cambiar(Estado.DORMIDO, SIN_PALABRA)
                }
                return@execute
            }
            val error = try {
                val carpeta = File(base, NOMBRE_MODELO)
                if (!File(carpeta, "listo").exists()) descargarModelo(base, carpeta)
                val m = Model(carpeta.absolutePath)
                main.post { modelo = m }
                null
            } catch (e: Exception) {
                "No se pudo bajar la voz de Pipo (¿internet?). Toca a Pipo para preguntarle."
            } catch (e: LinkageError) {
                voskNoDisponible = true
                SIN_PALABRA
            }
            main.post {
                cargandoModelo = false
                if (error != null) cambiar(Estado.DORMIDO, error)
                else if (estado == Estado.PREPARANDO) { cambiar(Estado.DORMIDO, ""); volverADormir() }
            }
        }
    }

    private fun descargarModelo(base: File, carpeta: File) {
        base.mkdirs()
        val zip = File(base, "modelo.zip")
        main.post { cambiar(Estado.PREPARANDO, "Descargando la voz de Pipo…") }
        val con = URL(URL_MODELO).openConnection() as HttpURLConnection
        con.connectTimeout = 10_000
        con.readTimeout = 30_000
        val total = con.contentLengthLong
        con.inputStream.use { entrada ->
            FileOutputStream(zip).use { salida ->
                val buf = ByteArray(64 * 1024)
                var leidos = 0L
                var ultimoPct = -1
                while (true) {
                    val n = entrada.read(buf)
                    if (n < 0) break
                    salida.write(buf, 0, n)
                    leidos += n
                    if (total > 0) {
                        val pct = (leidos * 100 / total).toInt()
                        if (pct != ultimoPct && pct % 5 == 0) {
                            ultimoPct = pct
                            main.post { cambiar(Estado.PREPARANDO, "Descargando la voz de Pipo $pct %") }
                        }
                    }
                }
            }
        }
        main.post { cambiar(Estado.PREPARANDO, "Preparando la voz de Pipo…") }
        carpeta.deleteRecursively()
        val raiz = base.canonicalPath + File.separator
        ZipInputStream(zip.inputStream().buffered()).use { z ->
            while (true) {
                val entrada = z.nextEntry ?: break
                val destino = File(base, entrada.name)
                if (!destino.canonicalPath.startsWith(raiz)) continue   // never outside the folder
                if (entrada.isDirectory) destino.mkdirs() else {
                    destino.parentFile?.mkdirs()
                    FileOutputStream(destino).use { z.copyTo(it) }
                }
            }
        }
        zip.delete()
        File(carpeta, "listo").writeText("ok")
    }

    // --- Small helpers ---

    private fun tienePermisoMicrofono(c: Context) =
        ContextCompat.checkSelfPermission(c, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun pitido() {
        try {
            val tono = ToneGenerator(AudioManager.STREAM_MUSIC, 70)
            tono.startTone(ToneGenerator.TONE_PROP_BEEP, 150)
            main.postDelayed({ tono.release() }, 400)
        } catch (e: Exception) { }
    }

    private fun cambiar(nuevo: Estado, texto: String) {
        estado = nuevo
        detalle = texto
        alCambiar()
    }
}

// Value of "Name: value" in a detection line ("…, Senal: LIMITE 30, Conf: 0.91, …").
fun campoLinea(linea: String, nombre: String): String? =
    Regex("$nombre:\\s*([^,]+)").find(linea)?.groupValues?.get(1)?.trim()
