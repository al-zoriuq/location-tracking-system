package com.example.gpslink

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Intent
import android.location.Location
import android.location.LocationListener
import android.location.LocationManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import androidx.core.app.NotificationCompat
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone

// Runs independently of the Activity: keeps sending the location every 10
// seconds even with the app closed or the screen off, as long as Android
// (and the manufacturer's battery optimizer) doesn't kill the process.
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
    private val PUERTO_FIJO = 5000
    private val INTERVALO_AUTOMATICO_MS = 10_000L

    private lateinit var locationManager: LocationManager
    private var cicloEnCurso = false

    private val handler = Handler(Looper.getMainLooper())
    private val loopRunnable = object : Runnable {
        override fun run() {
            intentarEnvio()
            handler.postDelayed(this, INTERVALO_AUTOMATICO_MS)
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
        startForeground(NOTIF_ID, construirNotificacion("Enviando tu ubicación cada 10 segundos"))

        if (intent?.action == ACCION_ENVIAR_AHORA) {
            intentarEnvio() // one-off immediate send, outside the normal 10s cadence
        }

        // Avoid stacking a second loop if the service is (re)started while
        // one is already running.
        handler.removeCallbacks(loopRunnable)
        handler.post(loopRunnable)

        // START_STICKY: ask Android to recreate this service if the system
        // kills it for memory — not a guarantee on every manufacturer's OS.
        return START_STICKY
    }

    override fun onDestroy() {
        super.onDestroy()
        handler.removeCallbacks(loopRunnable)
    }

    override fun onBind(intent: Intent?): IBinder? = null // not a bound service

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
            .build()

    // Pushes the latest status two ways: a broadcast (for the Activity's UI,
    // if it happens to be open) and the notification text itself (so there's
    // still visible feedback even with the app fully closed).
    private fun actualizarEstado(texto: String) {
        sendBroadcast(Intent(ACCION_ESTADO).putExtra(EXTRA_ESTADO, texto).setPackage(packageName))
        getSystemService(NotificationManager::class.java).notify(NOTIF_ID, construirNotificacion(texto))
    }

    private fun intentarEnvio() {
        if (cicloEnCurso) return

        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val servidor = prefs.getString(KEY_SERVIDOR, null)

        if (servidor == null) {
            actualizarEstado("Sin IP guardada todavía")
            return
        }
        if (!locationManager.isProviderEnabled(LocationManager.GPS_PROVIDER)) {
            actualizarEstado("El GPS está desactivado")
            return
        }

        cicloEnCurso = true
        actualizarEstado("Obteniendo posición GPS…")

        val listener = object : LocationListener {
            override fun onLocationChanged(location: Location) {
                locationManager.removeUpdates(this)
                enviarPorUdp(servidor, location)
            }
        }

        locationManager.requestSingleUpdate(
            LocationManager.GPS_PROVIDER,
            listener,
            Looper.getMainLooper()
        )
    }

    private fun enviarPorUdp(servidorGuardado: String, location: Location) {
        val ips = servidorGuardado.split(";").map { it.trim() }.filter { it.isNotEmpty() }

        val formato = SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS XXX", Locale.getDefault())
        formato.timeZone = TimeZone.getTimeZone("America/Bogota")
        val timestamp = formato.format(Date(location.time))

        val mensaje = "Lat: ${location.latitude}, Lon: ${location.longitude}, " +
                "Timestamp GPS: $timestamp\n"

        Thread {
            val resultados = mutableListOf<String>()
            for (ip in ips) {
                try {
                    val socket = DatagramSocket()
                    try {
                        val direccion = InetAddress.getByName(ip)
                        val datos = mensaje.toByteArray(Charsets.UTF_8)
                        val paquete = DatagramPacket(datos, datos.size, direccion, PUERTO_FIJO)
                        socket.send(paquete)
                    } finally {
                        socket.close()
                    }
                    resultados.add("$ip: enviado")
                } catch (e: Exception) {
                    resultados.add("$ip: error (${e.message})")
                }
            }
            actualizarEstado(resultados.joinToString("\n"))
            cicloEnCurso = false
        }.start()
    }
}
