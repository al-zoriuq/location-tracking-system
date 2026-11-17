package com.example.gpslink

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.os.SystemClock
import androidx.core.app.NotificationCompat
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
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
// The GPS is listened to continuously (one fix per second, no minimum
// distance) and every NEW fix is sent right away. The location keeps flowing
// even when the phone stands still, which the Raspberry Pi needs to compute
// the speed (it only uses points that are 3 s old or less).
class UbicacionService : Service() {

    companion object {
        const val CHANNEL_ID = "gpslink_ubicacion"
        const val NOTIF_ID = 1
        const val ACCION_ENVIAR_AHORA = "com.example.gpslink.ENVIAR_AHORA"
        const val ACCION_ESTADO = "com.example.gpslink.ESTADO"
        const val EXTRA_ESTADO = "texto"
    }

    private val PREFS_NAME = "LocationSmsPrefs"
    private val KEY_SERVIDOR = "servidor_predeterminado"
    private val KEY_DEVICE_ID = "device_id"
    private val PUERTO_FIJO = 5000

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
    @Volatile private var enviados = 0

    // Sends happen in order, one at a time, off the main thread.
    private val red = Executors.newSingleThreadExecutor()

    // Generated once per install and reused forever after — lets the backend
    // tell apart this device's updates from any other device's, and lets the
    // 4 receiving EC2 instances deduplicate the same packet.
    private val deviceId: String by lazy { obtenerOCrearDeviceId() }

    private val listenerGps = object : LocationListener {
        override fun onLocationChanged(location: Location) {
            ultimaUbicacion = location
            val ahora = SystemClock.elapsedRealtime()
            ultimoFixMs = ahora
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
        crearCanalNotificacion()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        // Mandatory within a few seconds of starting a foreground service,
        // or Android kills it. The notification is what makes this legal:
        // it's how the user is kept aware location is being used.
        startForeground(NOTIF_ID, construirNotificacion("Enviando tu ubicación cada segundo"))

        iniciarGps()

        if (intent?.action == ACCION_ENVIAR_AHORA) {
            val ubicacion = ultimaUbicacion
            if (ubicacion != null) enviar(ubicacion) else actualizarEstado("Todavía no hay posición GPS")
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
        handler.removeCallbacks(vigilancia)
        detenerGps()
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
            actualizarEstado("Obteniendo posición GPS…")
        } catch (e: SecurityException) {
            actualizarEstado("Falta el permiso de ubicación")
        }
    }

    private fun detenerGps() {
        if (!escuchandoGps) return
        locationManager.removeUpdates(listenerGps)
        escuchandoGps = false
    }

    // Retries the GPS if it couldn't start, and warns when fixes stop arriving
    // (indoors, tunnels...) instead of silently going quiet.
    private fun vigilar() {
        if (!escuchandoGps) {
            iniciarGps()
            return
        }
        if (ultimoFixMs == 0L) return // still waiting for the first fix
        val segundos = (SystemClock.elapsedRealtime() - ultimoFixMs) / 1000
        if (segundos >= 5) {
            actualizarEstado("Sin señal GPS hace $segundos s (¿bajo techo?). Enviados: $enviados")
        }
    }

    // --- Notification / status ---

    private fun crearCanalNotificacion() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val canal = NotificationChannel(
                CHANNEL_ID, "Envío de ubicación", NotificationManager.IMPORTANCE_LOW
            )
            getSystemService(NotificationManager::class.java).createNotificationChannel(canal)
        }
    }

    private fun construirNotificacion(texto: String) =
        NotificationCompat.Builder(this, CHANNEL_ID)
            .setContentTitle("GPSLink activo")
            .setContentText(texto)
            .setSmallIcon(android.R.drawable.ic_menu_mylocation)
            .setOngoing(true) // the user can't swipe-dismiss it away by accident
            .setOnlyAlertOnce(true)
            .build()

    // Pushes the latest status two ways: a broadcast (for the Activity's UI,
    // if it happens to be open) and the notification text itself (so there's
    // still visible feedback even with the app fully closed).
    private fun actualizarEstado(texto: String) {
        sendBroadcast(Intent(ACCION_ESTADO).putExtra(EXTRA_ESTADO, texto).setPackage(packageName))
        getSystemService(NotificationManager::class.java).notify(NOTIF_ID, construirNotificacion(texto))
    }

    // Reads the device_id from SharedPreferences, or generates and stores a
    // new UUID the very first time the service ever runs on this install.
    private fun obtenerOCrearDeviceId(): String {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val existente = prefs.getString(KEY_DEVICE_ID, null)
        if (existente != null) return existente

        val nuevo = UUID.randomUUID().toString()
        prefs.edit().putString(KEY_DEVICE_ID, nuevo).apply()
        return nuevo
    }

    // --- UDP send ---

    private fun enviar(location: Location) {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val servidorGuardado = prefs.getString(KEY_SERVIDOR, null)
        if (servidorGuardado == null) {
            actualizarEstado("Sin IP guardada todavía")
            return
        }
        val ips = servidorGuardado.split(";").map { it.trim() }.filter { it.isNotEmpty() }

        val formato = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS XXX", Locale.US)
        formato.timeZone = TimeZone.getTimeZone("America/Bogota")
        val timestamp = formato.format(Date(location.time))

        // Same message format as before (the server and the Pi already parse it).
        val mensaje = "Device: $deviceId, Lat: ${location.latitude}, Lon: ${location.longitude}, " +
                "Timestamp GPS: $timestamp\n"

        red.execute {
            val resultados = mutableListOf<String>()
            for (ip in ips) {
                try {
                    DatagramSocket().use { socket ->
                        val direccion = InetAddress.getByName(ip)
                        val datos = mensaje.toByteArray(Charsets.UTF_8)
                        socket.send(DatagramPacket(datos, datos.size, direccion, PUERTO_FIJO))
                    }
                    resultados.add("$ip: enviado")
                } catch (e: Exception) {
                    resultados.add("$ip: error (${e.message})")
                }
            }
            enviados++
            val hora = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
            val texto = "[$hora] envío #$enviados\n" + resultados.joinToString("\n")
            handler.post { actualizarEstado(texto) }
        }
    }
}
