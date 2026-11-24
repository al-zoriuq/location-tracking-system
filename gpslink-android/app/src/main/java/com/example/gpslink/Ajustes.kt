package com.example.gpslink

import android.content.Context

// Saved settings: the server IP(s) and the (optional) Raspberry Pi IP.
//
// Up to v1.1 everything lived in one string "PI_IP;SERVER_IP". From v1.2 the Pi has
// its own field, so the same app works in a car with a Pi and in one without:
// with no Pi IP saved, the app just sends its route to the server.
object Ajustes {
    const val PREFS_NAME = "LocationSmsPrefs"
    private const val KEY_SERVIDOR = "servidor_predeterminado"
    private const val KEY_PI = "ip_raspberry"
    private const val KEY_MIGRADO = "ajustes_v2"

    const val SERVIDOR_POR_DEFECTO = "52.71.39.197"

    // UDP ports: the server and the Pi listen on 5000; the app listens on 5001
    // for the Pi's detections (DET,...) and heartbeats (EST,...).
    const val PUERTO_SERVIDOR = 5000
    const val PUERTO_PI = 5000
    const val PUERTO_APP = 5001

    // Over the limit means more than limit + 3 km/h (same rule as the Pi and the server line).
    const val TOLERANCIA_KMH = 3

    fun servidores(ctx: Context): List<String> {
        migrar(ctx)
        val texto = prefs(ctx).getString(KEY_SERVIDOR, null) ?: SERVIDOR_POR_DEFECTO
        return separar(texto)
    }

    fun ipPi(ctx: Context): String? {
        migrar(ctx)
        return prefs(ctx).getString(KEY_PI, null)?.trim()?.takeIf { it.isNotEmpty() }
    }

    // The Pi to talk to: the saved IP, or the one found automatically (its broadcast
    // heartbeat) while it keeps talking. A stale discovery expires after 60 s.
    fun ipPiEfectiva(ctx: Context): String? {
        ipPi(ctx)?.let { return it }
        val vista = EstadoApp.piIpVista
        val reciente = System.currentTimeMillis() - EstadoApp.piUltimoMs <= 60_000
        return if (vista.isNotEmpty() && reciente) vista else null
    }

    fun guardar(ctx: Context, servidores: String, ipPi: String) {
        prefs(ctx).edit()
            .putString(KEY_SERVIDOR, separar(servidores).joinToString(";"))
            .putString(KEY_PI, ipPi.trim())
            .putBoolean(KEY_MIGRADO, true)
            .apply()
    }

    // --- Pipo (voice assistant) ---

    private const val KEY_PIPO = "pipo_activo"

    fun pipoActivo(ctx: Context): Boolean = prefs(ctx).getBoolean(KEY_PIPO, true)

    fun guardarPipoActivo(ctx: Context, activo: Boolean) {
        prefs(ctx).edit().putBoolean(KEY_PIPO, activo).apply()
    }

    // Pipo's floating bubble: the "display over other apps" explanation is shown once.
    private const val KEY_BURBUJA = "burbuja_ofrecida"

    fun burbujaOfrecida(ctx: Context): Boolean = prefs(ctx).getBoolean(KEY_BURBUJA, false)

    fun marcarBurbujaOfrecida(ctx: Context) {
        prefs(ctx).edit().putBoolean(KEY_BURBUJA, true).apply()
    }

    // Pipo asks the web server by its domain over https: Nginx answers 404 to a bare IP
    // and redirects http to https, which HttpURLConnection does not follow for a POST.
    private const val KEY_URL_PIPO = "url_pipo"
    const val URL_PIPO_POR_DEFECTO = "https://sthefanygps.duckdns.org/api/pipo"

    fun urlPipo(ctx: Context): String =
        prefs(ctx).getString(KEY_URL_PIPO, null)?.takeIf { it.isNotBlank() } ?: URL_PIPO_POR_DEFECTO

    fun guardarUrlPipo(ctx: Context, url: String) {
        prefs(ctx).edit().putString(KEY_URL_PIPO, normalizarUrlPipo(url)).apply()
    }

    // "midominio.org" -> "https://midominio.org/api/pipo"; a full URL is kept as typed.
    fun normalizarUrlPipo(texto: String): String {
        var url = texto.trim().trimEnd('/')
        if (url.isEmpty()) return ""
        if (!url.startsWith("http://") && !url.startsWith("https://")) url = "https://$url"
        if (!url.endsWith("/api/pipo")) url += "/api/pipo"
        return url
    }

    fun deviceId(ctx: Context): String? = prefs(ctx).getString("device_id", null)

    // Same id the service creates on its first run; Pipo may be asked before that.
    fun deviceIdOCrear(ctx: Context): String = deviceId(ctx)
        ?: java.util.UUID.randomUUID().toString().also {
            prefs(ctx).edit().putString("device_id", it).apply()
        }

    fun separar(texto: String): List<String> =
        texto.split(";", ",", " ").map { it.trim() }.filter { it.isNotEmpty() }

    // Local-network addresses (hotspot): these can only be the Pi, never the server.
    fun esIpLocal(ip: String): Boolean {
        val p = ip.split(".").mapNotNull { it.toIntOrNull() }
        if (p.size != 4) return false
        return p[0] == 10 || p[0] == 127 ||
                (p[0] == 192 && p[1] == 168) ||
                (p[0] == 172 && p[1] in 16..31)
    }

    // One-time move from the old "PI_IP;SERVER_IP" string to the two fields.
    private fun migrar(ctx: Context) {
        val prefs = prefs(ctx)
        if (prefs.getBoolean(KEY_MIGRADO, false)) return
        val viejo = prefs.getString(KEY_SERVIDOR, null)
        val editor = prefs.edit().putBoolean(KEY_MIGRADO, true)
        if (viejo != null) {
            val ips = separar(viejo)
            val pi = ips.firstOrNull { esIpLocal(it) }
            val resto = ips.filter { it != pi }
            editor.putString(KEY_SERVIDOR, resto.ifEmpty { listOf(SERVIDOR_POR_DEFECTO) }.joinToString(";"))
            if (pi != null) editor.putString(KEY_PI, pi)
        }
        editor.apply()
    }

    private fun prefs(ctx: Context) = ctx.getSharedPreferences(PREFS_NAME, Context.MODE_PRIVATE)
}

// Live state shared by the service (writes) and the screen (reads). Same process,
// so a plain object is enough; the service sends ACCION_ESTADO after each change.
object EstadoApp {
    @Volatile var servicioActivo = false
    @Volatile var gpsActivo = false
    @Volatile var aviso = ""                // e.g. "El GPS está desactivado"

    @Volatile var enviados = 0
    @Volatile var ultimoEnvioMs = 0L        // System.currentTimeMillis()
    @Volatile var ultimoFixMs = 0L
    @Volatile var lat = 0.0
    @Volatile var lon = 0.0
    @Volatile var precisionM = -1f
    @Volatile var velocidadKmh = -1f
    @Volatile var resultadoEnvio = ""       // "52.71.39.197: enviado" ...
    @Volatile var sinInternet = false
    @Volatile var enCola = 0                // messages waiting for internet (route + detections)

    @Volatile var piUltimoMs = 0L           // last DET/EST received from the Pi
    @Volatile var piIpVista = ""            // IP the Pi's last DET/EST came from (discovery)
    @Volatile var piEstado = ""             // ACTIVO | PAUSADO | APAGANDO
    @Volatile var piSenales = ""            // signs counted by the Pi
    @Volatile var detRecibidas = 0
    @Volatile var detReenviadas = 0
    @Volatile var ultimaDeteccion = ""      // the detection line as forwarded
    @Volatile var ultimaDeteccionMs = 0L

    @Volatile var limiteKmh = 0             // last speed limit seen (0 = none)
    @Volatile var limiteMs = 0L             // when it was seen (System.currentTimeMillis())
    @Volatile var microfonoEnServicio = false   // the service may use the mic (Pipo's wake word)
    @Volatile var appEnPantalla = false         // MainActivity is visible (Pipo's bubble hides)

    // Last few detections for the "Señales recientes" list, newest first.
    class Deteccion(val ms: Long, val linea: String)
    private val recientes = ArrayDeque<Deteccion>()

    @Synchronized
    fun agregarReciente(linea: String) {
        recientes.addFirst(Deteccion(System.currentTimeMillis(), linea))
        while (recientes.size > 5) recientes.removeLast()
    }

    @Synchronized
    fun recientes(): List<Deteccion> = recientes.toList()
}
