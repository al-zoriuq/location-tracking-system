package com.example.gpslink

import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.net.ConnectivityManager
import android.net.NetworkCapabilities
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import androidx.core.content.ContextCompat
import java.io.File
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.net.InetSocketAddress
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.UUID
import java.util.concurrent.Executors

// Runs independently of the Activity: keeps sending the location even with the
// app closed or the screen off, as long as Android (and the manufacturer's
// battery optimizer) doesn't kill the process.
//
// Data flow (plan of 2026-11-20): the phone is the ONLY device that talks to the server.
//   phone --route every 1 s--------------------------------------> server :5000
//   phone --GPS,lat,lon,kmh,epoch_ms every 1 s (if there is a Pi)-> Pi :5000
//   Pi    --DET,<id>,<sign>,<conf>,<MPU km/h|NA>,<age_ms> --------> phone :5001
//   Pi    --EST,<device>,<state>,<signs> every 5 s (broadcast while
//           it hasn't heard the phone: that's how the app finds it) -> phone :5001
//   phone --ACK,<id>---------------------------------------------> Pi :5000
//   phone --full detection line built HERE (phone position, time,
//           GPS speed, SI/EXCEDE) -------------------------------> server :5000
// Without a Pi the app works exactly the same, it just never receives detections.
class UbicacionService : Service() {

    companion object {
        const val CHANNEL_ID = "gpslink_ubicacion"
        const val NOTIF_ID = 1
        const val ACCION_ENVIAR_AHORA = "com.example.gpslink.ENVIAR_AHORA"
        const val ACCION_ESTADO = "com.example.gpslink.ESTADO"
    }

    private val KEY_DEVICE_ID = "device_id"

    // How often the GPS is asked for a fix, and the minimum time between two sends.
    private val INTERVALO_GPS_MS = 1_000L
    private val INTERVALO_MIN_ENVIO_MS = 900L

    // How often the watchdog checks that fixes keep arriving.
    private val INTERVALO_VIGILANCIA_MS = 5_000L

    private lateinit var locationManager: LocationManager
    private var escuchandoGps = false
    private var ultimaUbicacion: Location? = null
    private var ultimoFixMs = 0L      // elapsedRealtime of the last fix received
    private var ultimoEnvioMs = 0L    // elapsedRealtime of the last send

    // Sends happen in order, one at a time, off the main thread.
    private val red = Executors.newSingleThreadExecutor()

    // One socket for everything, bound to 5001 so the Pi can answer to a fixed port.
    @Volatile private var socket: DatagramSocket? = null
    @Volatile private var recibiendo = false
    private var hiloRecepcion: Thread? = null

    // Recent fixes, to place each detection where the car was WHEN the Pi saw the sign.
    private class Fix(val tMs: Long, val lat: Double, val lon: Double, val kmh: Float?)
    private val fixes = ArrayDeque<Fix>()

    // Store-and-forward for the server (no internet -> queue -> send when it's back).
    // Detections go first and are kept longer; route points: up to ~5 h at 1 per second.
    private val colaDetecciones by lazy { ColaEnvio(File(filesDir, "cola_detecciones.txt"), 2_000) }
    private val colaRuta by lazy { ColaEnvio(File(filesDir, "cola_ruta.txt"), 18_000) }
    private val LOTE_COLA = 40          // queued messages sent per second once online

    // Some phones drop broadcast packets unless the app holds this lock (Pi discovery).
    private var multicastLock: WifiManager.MulticastLock? = null

    // Detection ids already forwarded (the Pi repeats a DET until it gets the ACK).
    private val detVistas = object : LinkedHashMap<String, Boolean>(64, 0.75f, false) {
        override fun removeEldestEntry(eldest: MutableMap.MutableEntry<String, Boolean>?) = size > 200
    }

    // Generated once per install and reused forever after — lets the backend
    // tell apart this device's updates from any other device's, and lets the
    // 4 receiving EC2 instances deduplicate the same packet.
    private val deviceId: String by lazy { obtenerOCrearDeviceId() }

    private val listenerGps = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            ultimaUbicacion = location
            val ahora = SystemClock.elapsedRealtime()
            ultimoFixMs = ahora
            EstadoApp.ultimoFixMs = System.currentTimeMillis()
            EstadoApp.lat = location.latitude
            EstadoApp.lon = location.longitude
            EstadoApp.precisionM = if (location.hasAccuracy()) location.accuracy else -1f
            EstadoApp.velocidadKmh = if (location.hasSpeed()) location.speed * 3.6f else -1f
            EstadoApp.aviso = ""
            val kmh = if (location.hasSpeed()) location.speed * 3.6f else null
            synchronized(fixes) {
                fixes.addLast(Fix(ahora, location.latitude, location.longitude, kmh))
                while (fixes.size > 3_600) fixes.removeFirst()   // ~1 h at 1 fix per second
            }
            if (kmh != null) {
                Pipo.revisarVelocidad(kmh)
                NotificacionGps.revisarExceso(this@UbicacionService, kmh)
            }
            if (ahora - ultimoEnvioMs >= INTERVALO_MIN_ENVIO_MS) {
                ultimoEnvioMs = ahora
                enviar(location)
            }
        }

        override fun onProviderDisabled(provider: String) {
            actualizarEstado("El GPS está desactivado")
        }

        override fun onProviderEnabled(provider: String) {}

        @Deprecated("Deprecated in Java")
        override fun onStatusChanged(provider: String?, status: Int, extras: Bundle?) {}
    }

    private val handler = Handler(Looper.getMainLooper())
    private val vigilancia = object : Runnable {
        override fun run() {
            vigilar()
            handler.postDelayed(this, INTERVALO_VIGILANCIA_MS)
        }
    }

    override fun onCreate() {
        super.onCreate()
        locationManager = getSystemService(LOCATION_SERVICE) as LocationManager
        NotificacionGps.crearCanales(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Mandatory within a few seconds of starting a foreground service,
        // or Android kills it. The notification is what makes this legal:
        // it's how the user is kept aware location is being used.
        iniciarPrimerPlano()
        EstadoApp.servicioActivo = true

        abrirSocket()
        tomarMulticastLock()
        iniciarGps()
        // Pipo lives here too, so he keeps listening and warning with the screen off.
        Pipo.iniciar(this) { actualizarEstado() }
        // Pipo's bubble over other apps; once it's visible, try to get the mic back.
        BurbujaPipo.iniciar(this) { recuperarMicrofono() }
        BurbujaPipo.mostrar()

        when (intent?.action) {
            ACCION_ENVIAR_AHORA -> {
                val ubicacion = ultimaUbicacion
                if (ubicacion != null) enviar(ubicacion) else actualizarEstado("Todavía no hay posición GPS")
            }
            // Buttons on the notification.
            NotificacionGps.ACCION_PIPO -> Pipo.preguntarAhora()
            NotificacionGps.ACCION_PI_PAUSA -> comandoPi("PAUSA")
            NotificacionGps.ACCION_PI_REANUDA -> comandoPi("REANUDA")
        }

        // Avoid stacking a second watchdog if the service is (re)started.
        handler.removeCallbacks(vigilancia)
        handler.postDelayed(vigilancia, INTERVALO_VIGILANCIA_MS)

        // START_STICKY: ask Android to recreate this service if the system
        // kills it for memory — not a guarantee on every manufacturer's OS.
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        EstadoApp.servicioActivo = false
        handler.removeCallbacks(vigilancia)
        handler.removeCallbacksAndMessages(null)
        NotificacionGps.quitarAlerta(this)
        Pipo.detener()
        BurbujaPipo.ocultar()
        detenerGps()
        recibiendo = false
        socket?.close()
        try { multicastLock?.release() } catch (e: Exception) {}
        red.shutdown()
    }

    override fun onBind(intent: Intent?): IBinder? = null // not a bound service

    // --- GPS ---

    private fun iniciarGps() {
        if (escuchandoGps) return
        if (!locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
            actualizarEstado("El GPS está desactivado")
            return
        }
        try {
            // One fix per second and NO minimum distance: keeps sending even
            // when the phone stands still (e.g. a car at a red light).
            locationManager.requestLocationUpdates(
                LocationManager.GPS_PROVIDER,
                INTERVALO_GPS_MS,
                0f,
                listenerGps,
                Looper.getMainLooper()
            )
            escuchandoGps = true
            EstadoApp.gpsActivo = true
            actualizarEstado("Buscando señal GPS…")
        } catch (e: SecurityException) {
            actualizarEstado("Falta el permiso de ubicación")
        }
    }

    private fun detenerGps() {
        if (!escuchandoGps) return
        locationManager.removeUpdates(listenerGps)
        escuchandoGps = false
        EstadoApp.gpsActivo = false
    }

    // Retries the GPS if it couldn't start, and warns when fixes stop arriving
    // (indoors, tunnels...) instead of silently going quiet.
    private fun vigilar() {
        if (socket == null) abrirSocket()
        // Also flush the queue when no fixes arrive (e.g. parked indoors with internet).
        if (EstadoApp.enCola > 0 && hayInternet()) red.execute {
            vaciarColas()
            EstadoApp.enCola = colaDetecciones.tamano + colaRuta.tamano
        }
        if (!escuchandoGps) {
            iniciarGps()
            return
        }
        if (ultimoFixMs == 0L) return // still waiting for the first fix
        val segundos = (SystemClock.elapsedRealtime() - ultimoFixMs) / 1000
        if (segundos >= 5) {
            actualizarEstado("Sin señal GPS hace $segundos s (¿bajo techo?)")
        }
    }

    // --- Foreground service types ---

    // Location always; microphone too (Pipo's wake word) if the permission is granted.
    // Android 14+ only allows the microphone type while the app is on screen: if the
    // system restarts the service in the background, it goes on without the mic and
    // Pipo only speaks (warnings) until the app is opened again.
    private fun iniciarPrimerPlano() {
        val notif = NotificacionGps.construir(this)
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            startForeground(NOTIF_ID, notif)
            EstadoApp.microfonoEnServicio = true
            return
        }
        val mic = Build.VERSION.SDK_INT >= Build.VERSION_CODES.R &&
                ContextCompat.checkSelfPermission(this, android.Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        val ubicacion = ServiceInfo.FOREGROUND_SERVICE_TYPE_LOCATION
        if (mic && Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
            try {
                startForeground(NOTIF_ID, notif, ubicacion or ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
                EstadoApp.microfonoEnServicio = true
                return
            } catch (e: Exception) {
                // Started from the background: retry with location only (below).
            }
        }
        startForeground(NOTIF_ID, notif, ubicacion)
        // Android 10 has no microphone type: the mic works in any foreground service.
        EstadoApp.microfonoEnServicio = Build.VERSION.SDK_INT == Build.VERSION_CODES.Q
    }

    // The service came back without the mic (restarted in the background on Android
    // 14+). With Pipo's bubble on screen Android allows the microphone type again.
    private fun recuperarMicrofono() {
        if (EstadoApp.microfonoEnServicio || !Ajustes.pipoActivo(this)) return
        iniciarPrimerPlano()
        if (EstadoApp.microfonoEnServicio) Pipo.aplicarAjuste()
    }

    // --- Pipo's warnings for a new detection (main thread) ---

    private val PARE_ESPERA_MS = 10_000L

    // A detection the Pi kept while the phone was away arrives late: it still goes to
    // the server, but Pipo only speaks about signs seen in the last few seconds.
    private val AVISO_MAX_EDAD_MS = 10_000L

    private fun avisarDeteccion(senal: String, linea: String, tDeteccion: Long) {
        val edadMs = SystemClock.elapsedRealtime() - tDeteccion
        val vistaMs = System.currentTimeMillis() - edadMs
        Regex("^LIMITE\\s+(\\d+)$").find(senal.trim())?.groupValues?.get(1)?.toIntOrNull()?.let {
            if (vistaMs > EstadoApp.limiteMs) {   // never replace a newer limit with an old one
                EstadoApp.limiteKmh = it
                EstadoApp.limiteMs = vistaMs
            }
        }
        if (edadMs > AVISO_MAX_EDAD_MS) return
        Pipo.anunciarDeteccion(linea)
        // PARE: did the car stop? Lowest GPS speed in the 10 s after the sign.
        if (senal.trim().startsWith("PARE")) {
            handler.postDelayed({
                val minima = synchronized(fixes) {
                    fixes.filter { it.tMs >= tDeteccion - 1_000 && it.tMs <= tDeteccion + PARE_ESPERA_MS }
                        .mapNotNull { it.kmh }.minOrNull()
                }
                Pipo.resultadoPare(minima)
            }, PARE_ESPERA_MS - (SystemClock.elapsedRealtime() - tDeteccion).coerceIn(0, PARE_ESPERA_MS))
        }
    }

    // --- Notification / status ---

    // Tells the screen (if open) to refresh, and keeps the notification current so
    // there's still visible feedback with the app fully closed. The notification is only
    // rebuilt when what it shows changes: at most every 2 s as a Live Update (the speed
    // chip), every 5 s otherwise, and right away for a warning.
    private var ultimaClaveNotif = ""
    private var ultimaNotifMs = 0L

    private fun actualizarEstado(aviso: String? = null) {
        if (aviso != null) EstadoApp.aviso = aviso
        sendBroadcast(Intent(ACCION_ESTADO).setPackage(packageName))
        BurbujaPipo.refrescar()
        val clave = NotificacionGps.clave(this, aviso)
        val ahora = SystemClock.elapsedRealtime()
        val cada = if (NotificacionGps.puedeEnVivo(this)) 2_000L else 5_000L
        if (clave == ultimaClaveNotif || (aviso == null && ahora - ultimaNotifMs < cada)) return
        ultimaClaveNotif = clave
        ultimaNotifMs = ahora
        try {
            getSystemService(NotificationManager::class.java).notify(NOTIF_ID, NotificacionGps.construir(this, aviso))
        } catch (e: SecurityException) { }
    }

    // "Pausar Pi" / "Reanudar Pi" on the notification. The Pi answers with an EST
    // to port 5001, which the receive loop already handles.
    private fun comandoPi(comando: String) {
        val ip = Ajustes.ipPiEfectiva(this) ?: return
        red.execute { enviarUdp("CMD,$comando", ip, Ajustes.PUERTO_PI) }
    }

    // Ids already forwarded survive an app restart, so a detection the Pi resends
    // (its ACK got lost) is not stored twice with a slightly different time.
    private fun archivoDetVistas() = File(filesDir, "detecciones_vistas.txt")

    private fun cargarDetVistas() {
        try {
            archivoDetVistas().takeIf { it.exists() }?.readLines()?.filter { it.isNotBlank() }
                ?.forEach { detVistas[it] = true }
        } catch (e: Exception) { }
    }

    private fun guardarDetVistas() {
        try { archivoDetVistas().writeText(detVistas.keys.joinToString("\n")) } catch (e: Exception) { }
    }

    // Reads the device_id from SharedPreferences, or generates and stores a
    // new UUID the very first time the service ever runs on this install.
    private fun obtenerOCrearDeviceId(): String {
        val prefs = getSharedPreferences(Ajustes.PREFS_NAME, MODE_PRIVATE)
        val existente = prefs.getString(KEY_DEVICE_ID, null)
        if (existente != null) return existente

        val nuevo = UUID.randomUUID().toString()
        prefs.edit().putString(KEY_DEVICE_ID, nuevo).apply()
        return nuevo
    }

    // --- UDP ---

    private fun tomarMulticastLock() {
        if (multicastLock != null) return
        try {
            val wifi = applicationContext.getSystemService(WIFI_SERVICE) as WifiManager
            multicastLock = wifi.createMulticastLock("gpslink-pi").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (e: Exception) {
            // Without it discovery may fail on some phones; a saved Pi IP still works.
        }
    }

    @Synchronized
    private fun abrirSocket() {
        if (socket != null) return
        val s = try {
            DatagramSocket(null).apply {
                reuseAddress = true
                bind(InetSocketAddress(Ajustes.PUERTO_APP))
            }
        } catch (e: Exception) {
            // Port taken (should not happen): still send the route, just without Pi detections.
            EstadoApp.aviso = "No se pudo abrir el puerto ${Ajustes.PUERTO_APP} (sin detecciones de la Pi)"
            try { DatagramSocket() } catch (e2: Exception) { null }
        } ?: return
        socket = s
        recibiendo = true
        hiloRecepcion = Thread({ bucleRecepcion(s) }, "gpslink-recepcion").apply {
            isDaemon = true
            start()
        }
    }

    private fun bucleRecepcion(s: DatagramSocket) {
        val buf = ByteArray(2048)
        while (recibiendo && !s.isClosed) {
            try {
                val p = DatagramPacket(buf, buf.size)
                s.receive(p)
                val texto = String(p.data, 0, p.length, Charsets.UTF_8).trim()
                procesarMensajePi(texto, p.address)
            } catch (e: Exception) {
                if (!recibiendo || s.isClosed) break
            }
        }
    }

    // Messages the Pi sends to this phone (port 5001).
    private fun procesarMensajePi(texto: String, origen: InetAddress) {
        when {
            texto.startsWith("DET,") -> {
                // DET,<id>,<sign>,<conf>,<MPU km/h|NA>,<age_ms>
                val p = texto.split(",").map { it.trim() }
                if (p.size < 6) return
                val id = p[1]
                val edadMs = p[5].toLongOrNull() ?: 0L
                EstadoApp.piUltimoMs = System.currentTimeMillis()
                EstadoApp.piIpVista = origen.hostAddress ?: ""
                // No GPS fix yet (app just opened, indoors): without a position the
                // server can't place the sign, so it is NOT confirmed. The Pi keeps it and
                // sends it again once this phone has a fix and talks to it.
                if (synchronized(fixes) { fixes.isEmpty() }) {
                    EstadoApp.aviso = "Señal ${p[2]} esperando posición GPS"
                    handler.post { actualizarEstado() }
                    return
                }
                // Always confirm (also repeats), so the Pi stops resending.
                enviarUdp("ACK,$id", origen, Ajustes.PUERTO_PI)
                val nueva = synchronized(detVistas) {
                    if (detVistas.isEmpty()) cargarDetVistas()
                    if (detVistas.containsKey(id)) false else {
                        detVistas[id] = true
                        guardarDetVistas()
                        true
                    }
                }
                if (nueva) {
                    val tDeteccion = SystemClock.elapsedRealtime() - edadMs
                    val hora = System.currentTimeMillis() - edadMs
                    val linea = armarLineaDeteccion(p[2], p[3], p[4].toFloatOrNull(), tDeteccion, hora)
                    if (linea != null) {   // never null here: there is at least one fix
                        reenviarDeteccion(linea)
                        handler.post { avisarDeteccion(p[2], linea, tDeteccion) }
                    }
                }
            }
            texto.startsWith("EST,") -> {
                // EST,<device>,<ACTIVO|PAUSADO|APAGANDO>,<signs> — heartbeat every 5 s
                val p = texto.split(",")
                if (p.size >= 4) {
                    EstadoApp.piEstado = p[2].trim()
                    EstadoApp.piSenales = p[3].trim()
                }
                EstadoApp.piUltimoMs = System.currentTimeMillis()
                // Discovery: the Pi announces itself; with no Pi IP saved, use this one.
                EstadoApp.piIpVista = origen.hostAddress ?: ""
                handler.post { actualizarEstado() }
            }
        }
    }

    // Same rules the Pi used (pipeline_pi.py, linea_deteccion): GPS speed if the fix is
    // at most 3 s from the detection, else the Pi's MPU speed; EXCEDE above limit + 3 km/h.
    private fun armarLineaDeteccion(senal: String, conf: String, vMpu: Float?, tDet: Long, horaMs: Long): String? {
        val fix = synchronized(fixes) { fixes.minByOrNull { kotlin.math.abs(it.tMs - tDet) } } ?: return null
        val distMs = kotlin.math.abs(fix.tMs - tDet)
        val vGps = fix.kmh?.takeIf { distMs <= 3_000 && it <= 180f }
        val (usa, v) = when {
            vGps != null -> "GPS" to vGps
            vMpu != null -> "MPU" to vMpu
            else -> "NA" to null
        }
        val limite = Regex("^LIMITE\\s+(\\d+)$").find(senal)?.groupValues?.get(1)?.toIntOrNull()
        val cumple = if (limite != null && v != null) (if (v > limite + Ajustes.TOLERANCIA_KMH) "EXCEDE" else "SI") else "NA"
        val formato = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS XXX", Locale.US)
        formato.timeZone = TimeZone.getTimeZone("America/Bogota")
        fun num(x: Float?) = if (x == null) "NA" else String.format(Locale.US, "%.0f", x)
        var linea = "Device: $deviceId, Lat: ${fix.lat}, Lon: ${fix.lon}, " +
                "Timestamp GPS: ${formato.format(Date(horaMs))}, Senal: $senal, Conf: $conf, " +
                "Vel GPS: ${num(vGps)}, Vel MPU: ${num(vMpu)}, Usa: $usa, $cumple"
        if (distMs > 30_000) linea += ", pos-${distMs / 1000}s"   // old position, like the Pi did
        return linea
    }

    // The server stores the sign on this car's route by Device, so the line always
    // goes out with this phone's id, whatever the Pi wrote.
    private fun reenviarDeteccion(linea: String) {
        EstadoApp.detRecibidas++
        red.execute {
            if (hayInternet() && enviarAServidores(linea)) {
                EstadoApp.detReenviadas++
            } else {
                colaDetecciones.agregar(linea)
            }
            EstadoApp.enCola = colaDetecciones.tamano + colaRuta.tamano
            EstadoApp.ultimaDeteccion = linea
            EstadoApp.ultimaDeteccionMs = System.currentTimeMillis()
            EstadoApp.agregarReciente(linea)
            handler.post { actualizarEstado() }
        }
    }

    // True if it went out to at least one server.
    private fun enviarAServidores(linea: String): Boolean {
        var ok = 0
        for (ip in Ajustes.servidores(this)) {
            if (enviarUdp(linea + "\n", ip, Ajustes.PUERTO_SERVIDOR)) ok++
        }
        return ok > 0
    }

    // Android's own check that the network really reaches the internet (VALIDATED):
    // false on a hotspot whose phone lost its data, in a tunnel, etc.
    private fun hayInternet(): Boolean = try {
        val cm = getSystemService(CONNECTIVITY_SERVICE) as ConnectivityManager
        val caps = cm.activeNetwork?.let { cm.getNetworkCapabilities(it) }
        caps != null && caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED)
    } catch (e: Exception) {
        true   // if Android can't tell, send as before
    }

    // Runs on the network thread: sends a batch of queued messages (detections first).
    private fun vaciarColas() {
        for (cola in listOf(colaDetecciones, colaRuta)) {
            if (cola.tamano == 0) continue
            val lote = cola.sacar(LOTE_COLA)
            for ((i, linea) in lote.withIndex()) {
                if (!enviarAServidores(linea)) {
                    cola.devolver(lote.subList(i, lote.size))
                    return
                }
                if (cola === colaDetecciones) EstadoApp.detReenviadas++
                try { Thread.sleep(5) } catch (e: InterruptedException) { return }
            }
            return   // one batch per second keeps the live point on time
        }
    }

    private fun enviarUdp(texto: String, ip: String, puerto: Int): Boolean =
        try {
            enviarUdp(texto, InetAddress.getByName(ip), puerto)
        } catch (e: Exception) {
            false
        }

    private fun enviarUdp(texto: String, direccion: InetAddress, puerto: Int): Boolean {
        val s = socket ?: return false
        return try {
            val datos = texto.toByteArray(Charsets.UTF_8)
            s.send(DatagramPacket(datos, datos.size, direccion, puerto))
            true
        } catch (e: Exception) {
            false
        }
    }

    private fun enviar(location: Location) {
        val servidores = Ajustes.servidores(this)
        val ipPi = Ajustes.ipPiEfectiva(this)
        val kmh = if (location.hasSpeed()) String.format(Locale.US, "%.1f", location.speed * 3.6f) else "NA"
        // The Pi only needs position + GPS speed (it calibrates the MPU with it).
        val mensajePi = "GPS,${location.latitude},${location.longitude},$kmh,${location.time}"

        val formato = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS XXX", Locale.US)
        formato.timeZone = TimeZone.getTimeZone("America/Bogota")
        val timestamp = formato.format(Date(location.time))

        // Same message format as before (the server and the Pi already parse it).
        val mensaje = "Device: $deviceId, Lat: ${location.latitude}, Lon: ${location.longitude}, " +
                "Timestamp GPS: $timestamp\n"

        red.execute {
            if (socket == null) abrirSocket()
            val resultados = mutableListOf<String>()
            if (hayInternet()) {
                for (ip in servidores) {
                    val ok = enviarUdp(mensaje, ip, Ajustes.PUERTO_SERVIDOR)
                    resultados.add("Servidor $ip: " + if (ok) "enviado" else "error")
                }
                vaciarColas()
            } else {
                colaRuta.agregar(mensaje)
                resultados.add("Sin internet: guardado para enviar después")
            }
            EstadoApp.enCola = colaDetecciones.tamano + colaRuta.tamano
            EstadoApp.sinInternet = resultados.firstOrNull()?.startsWith("Sin internet") == true
            // The Pi needs the position for the speed and the place of each sign.
            if (ipPi != null) {
                val ok = enviarUdp(mensajePi, ipPi, Ajustes.PUERTO_PI)
                resultados.add("Raspberry $ipPi: " + if (ok) "enviado" else "error")
            }
            EstadoApp.enviados++
            EstadoApp.ultimoEnvioMs = System.currentTimeMillis()
            EstadoApp.resultadoEnvio = resultados.joinToString("\n")
            handler.post { actualizarEstado() }
        }
    }
}
