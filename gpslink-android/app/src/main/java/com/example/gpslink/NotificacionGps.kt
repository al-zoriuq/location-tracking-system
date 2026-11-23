package com.example.gpslink

import android.Manifest
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Typeface
import android.graphics.drawable.Icon
import android.os.Build
import android.os.SystemClock
import androidx.annotation.RequiresApi
import androidx.core.app.NotificationCompat
import androidx.core.content.ContextCompat

// The service's notifications.
//
// 1. The ongoing one (it keeps the foreground service alive):
//    - Android 16+ : a Live Update. Speed in a chip on the status bar, shown at the top
//      of the lock screen, and a bar from 0 to above the limit with a mark on the limit.
//    - Older phones: a regular notification with the speed, the limit and the Pi.
//    Both carry the "Preguntar a Pipo" and "Pausar/Reanudar Pi" buttons.
// 2. A separate red alert ("Baja la velocidad") only while the car is over the limit.
//    It sounds at most every 45 s and goes away by itself a few seconds after slowing down.
object NotificacionGps {
    const val CANAL = UbicacionService.CHANNEL_ID
    const val CANAL_ALERTA = "gpslink_exceso"
    const val ID = UbicacionService.NOTIF_ID
    const val ID_ALERTA = 2

    const val ACCION_PIPO = "com.example.gpslink.PREGUNTAR_PIPO"
    const val ACCION_PI_PAUSA = "com.example.gpslink.PI_PAUSA"
    const val ACCION_PI_REANUDA = "com.example.gpslink.PI_REANUDA"

    private const val LIMITE_VIGENTE_MS = 15 * 60_000L   // same as the ring and Pipo
    private const val FIX_FRESCO_MS = 5_000L

    // --- Channels ---

    fun crearCanales(ctx: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(
            NotificationChannel(CANAL, "Envío de ubicación", NotificationManager.IMPORTANCE_LOW).apply {
                description = "Velocidad, límite y estado de la Raspberry mientras se envía la ruta"
            }
        )
        nm.createNotificationChannel(
            NotificationChannel(CANAL_ALERTA, "Alertas de velocidad", NotificationManager.IMPORTANCE_HIGH).apply {
                description = "Aviso rojo cuando vas por encima del último límite visto"
                enableVibration(true)
                vibrationPattern = longArrayOf(0, 250, 150, 250)
            }
        )
    }

    // --- What the notification shows, computed from EstadoApp ---

    private class Datos(
        val titulo: String,
        val lineaLimite: String?,   // "Límite 30 · 17 por encima" (null without a limit)
        val piTxt: String,
        val chip: String?,          // "47 km/h" for the status-bar chip
        val v: Int?,
        val limite: Int?,
        val excede: Boolean,
        val piPausada: Boolean,
        val hayPi: Boolean,
    ) {
        // Changes only when something visible changes (throttling in the service).
        val clave get() = "$titulo|$lineaLimite|$piTxt|$chip|$piPausada|$hayPi"
    }

    private fun velocidadActual(): Int? {
        val e = EstadoApp
        val fresco = e.ultimoFixMs > 0 && System.currentTimeMillis() - e.ultimoFixMs <= FIX_FRESCO_MS
        return if (fresco && e.velocidadKmh >= 0) Math.round(e.velocidadKmh) else null
    }

    private fun limiteVigente(): Int? {
        val e = EstadoApp
        return e.limiteKmh.takeIf { it > 0 && System.currentTimeMillis() - e.limiteMs <= LIMITE_VIGENTE_MS }
    }

    private fun datos(ctx: Context, aviso: String?): Datos {
        val e = EstadoApp
        val ahora = System.currentTimeMillis()
        val v = velocidadActual()
        val limite = limiteVigente()
        val excede = v != null && limite != null && v > limite + Ajustes.TOLERANCIA_KMH

        val ipPi = Ajustes.ipPiEfectiva(ctx)
        val edadPi = if (e.piUltimoMs > 0) (ahora - e.piUltimoMs) / 1000 else -1
        val senales = e.piSenales.ifEmpty { e.detRecibidas.toString() }
        val piTxt = when {
            ipPi == null -> "Sin Raspberry · solo ruta"
            edadPi < 0 -> "Esperando la Raspberry"
            edadPi > 15 -> "Raspberry sin respuesta"
            e.piEstado == "PAUSADO" -> "Raspberry en pausa · $senales señales"
            e.piEstado == "APAGANDO" -> "Raspberry apagándose"
            else -> "Raspberry conectada · $senales señales"
        }

        val edadFix = if (e.ultimoFixMs > 0) (ahora - e.ultimoFixMs) / 1000 else -1
        val titulo = when {
            !aviso.isNullOrEmpty() -> aviso
            e.aviso.isNotEmpty() && edadFix < 0 -> e.aviso
            edadFix < 0 -> "Buscando señal GPS…"
            edadFix > 5 -> "Sin señal GPS hace $edadFix s"
            e.sinInternet -> "Sin internet · ${e.enCola} guardados"
            excede -> "$v km/h en zona de $limite"
            v != null -> "Enviando · $v km/h"
            else -> "Enviando ubicación"
        }
        val lineaLimite = when {
            limite == null -> null
            excede -> "Límite $limite · ${v!! - limite} por encima"
            else -> "Límite $limite · dentro del límite"
        }
        return Datos(
            titulo = titulo,
            lineaLimite = lineaLimite,
            piTxt = piTxt,
            chip = v?.let { "$it km/h" },
            v = v,
            limite = limite,
            excede = excede,
            piPausada = e.piEstado == "PAUSADO",
            hayPi = ipPi != null,
        )
    }

    fun clave(ctx: Context, aviso: String?): String = datos(ctx, aviso).clave

    // --- The ongoing notification ---

    fun construir(ctx: Context, aviso: String? = null): Notification {
        val d = datos(ctx, aviso)
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.BAKLAVA) enVivo(ctx, d) else tablero(ctx, d)
    }

    // N1: older phones (and Android 16 with Live Updates turned off: it just shows normally).
    private fun tablero(ctx: Context, d: Datos): Notification {
        val cuerpo = listOfNotNull(d.lineaLimite, d.piTxt).joinToString("\n")
        val b = NotificationCompat.Builder(ctx, CANAL)
            .setSmallIcon(R.drawable.ic_notificacion)
            .setColor(ContextCompat.getColor(ctx, R.color.acento_fuerte))
            .setContentTitle(d.titulo)
            .setContentText(d.lineaLimite ?: d.piTxt)
            .setStyle(NotificationCompat.BigTextStyle().bigText(cuerpo))
            .setContentIntent(abrirApp(ctx))
            .setOngoing(true)            // the user can't swipe it away by accident
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(NotificationCompat.CATEGORY_NAVIGATION)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
        d.limite?.let { b.setLargeIcon(senalLimite(ctx, it)) }
        acciones(ctx, d).forEach { (texto, pi) -> b.addAction(R.drawable.ic_notificacion, texto, pi) }
        return b.build()
    }

    // N2: Android 16 Live Update. The progress bar and the chip text exist from Android 16
    // (API 36); asking to be promoted (chip on the status bar, top of the lock screen) only
    // from Android 16 QPR2 (36.1). On 36.0 it shows as a normal notification with the bar.
    @RequiresApi(Build.VERSION_CODES.BAKLAVA)
    private fun enVivo(ctx: Context, d: Datos): Notification {
        val b = Notification.Builder(ctx, CANAL)
            .setSmallIcon(R.drawable.ic_notificacion)
            .setColor(ContextCompat.getColor(ctx, R.color.acento_fuerte))
            .setContentTitle(d.titulo)
            .setContentText(d.piTxt)
            .setContentIntent(abrirApp(ctx))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(Notification.CATEGORY_NAVIGATION)
            .setVisibility(Notification.VISIBILITY_PUBLIC)
        if (Build.VERSION.SDK_INT_FULL >= Build.VERSION_CODES_FULL.BAKLAVA_1) b.setRequestPromotedOngoing(true)
        d.chip?.let { b.setShortCriticalText(it) }

        val limite = d.limite
        if (limite != null) {
            // 0 ... limit (lilac) ... limit x2.5 (red); the bar fills up to the current speed.
            val max = maxOf((limite * 2.5f).toInt(), limite + 30, 60)
            val lila = ContextCompat.getColor(ctx, R.color.acento)
            val rojo = ContextCompat.getColor(ctx, R.color.excede)
            b.setStyle(
                Notification.ProgressStyle()
                    .setProgressSegments(listOf(
                        Notification.ProgressStyle.Segment(limite).setColor(lila),
                        Notification.ProgressStyle.Segment(max - limite).setColor(rojo),
                    ))
                    .setProgressPoints(listOf(Notification.ProgressStyle.Point(limite).setColor(android.graphics.Color.WHITE)))
                    .setStyledByProgress(true)
                    .setProgress((d.v ?: 0).coerceIn(0, max))
            )
            b.setSubText("límite $limite")
        } else {
            b.setStyle(Notification.BigTextStyle().bigText(d.piTxt))
        }
        acciones(ctx, d).forEach { (texto, pi) ->
            b.addAction(Notification.Action.Builder(Icon.createWithResource(ctx, R.drawable.ic_notificacion), texto, pi).build())
        }
        return b.build()
    }

    // Live Updates can be turned off per app in Android's settings; then the same
    // notification just shows as a normal one.
    fun puedeEnVivo(ctx: Context): Boolean =
        Build.VERSION.SDK_INT >= Build.VERSION_CODES.BAKLAVA &&
                Build.VERSION.SDK_INT_FULL >= Build.VERSION_CODES_FULL.BAKLAVA_1 &&
                ctx.getSystemService(NotificationManager::class.java).canPostPromotedNotifications()

    private fun abrirApp(ctx: Context): PendingIntent = PendingIntent.getActivity(
        ctx, 0, Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
        PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
    )

    private fun alServicio(ctx: Context, accion: String, codigo: Int): PendingIntent {
        val intent = Intent(ctx, UbicacionService::class.java).setAction(accion)
        val flags = PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            PendingIntent.getForegroundService(ctx, codigo, intent, flags)
        else PendingIntent.getService(ctx, codigo, intent, flags)
    }

    private fun acciones(ctx: Context, d: Datos): List<Pair<String, PendingIntent>> {
        val lista = mutableListOf<Pair<String, PendingIntent>>()
        val mic = ContextCompat.checkSelfPermission(ctx, Manifest.permission.RECORD_AUDIO) ==
                PackageManager.PERMISSION_GRANTED
        if (Ajustes.pipoActivo(ctx) && mic) lista += "Preguntar a Pipo" to alServicio(ctx, ACCION_PIPO, 10)
        if (d.hayPi) {
            lista += if (d.piPausada) "Reanudar Pi" to alServicio(ctx, ACCION_PI_REANUDA, 12)
            else "Pausar Pi" to alServicio(ctx, ACCION_PI_PAUSA, 11)
        }
        return lista
    }

    // --- N3: the red over-the-limit alert ---

    private const val SONAR_CADA_MS = 45_000L
    private const val QUITAR_TRAS_MS = 3_000L    // under the limit this long -> alert goes away
    private const val ACTUALIZAR_CADA_MS = 2_000L

    private var alertaVisible = false
    private var ultimoSonidoMs = 0L
    private var ultimaAlertaMs = 0L
    private var bajoDesdeMs = 0L

    // Every GPS fix (main thread).
    fun revisarExceso(ctx: Context, kmh: Float) {
        val limite = limiteVigente()
        val ahora = SystemClock.elapsedRealtime()
        val v = Math.round(kmh)
        if (limite == null || v <= limite + Ajustes.TOLERANCIA_KMH) {
            if (!alertaVisible) return
            if (limite == null) { quitarAlerta(ctx); return }
            if (bajoDesdeMs == 0L) bajoDesdeMs = ahora
            if (ahora - bajoDesdeMs >= QUITAR_TRAS_MS) quitarAlerta(ctx)
            return
        }
        bajoDesdeMs = 0L
        val sonar = ahora - ultimoSonidoMs >= SONAR_CADA_MS
        if (alertaVisible && !sonar && ahora - ultimaAlertaMs < ACTUALIZAR_CADA_MS) return
        if (!puedeNotificar(ctx)) return
        if (sonar) ultimoSonidoMs = ahora
        ultimaAlertaMs = ahora
        alertaVisible = true

        val n = NotificationCompat.Builder(ctx, CANAL_ALERTA)
            .setSmallIcon(R.drawable.ic_notificacion)
            .setColor(ContextCompat.getColor(ctx, R.color.excede))
            .setSubText("Exceso de velocidad")
            .setContentTitle("Baja la velocidad")
            .setContentText("Vas a $v en zona de $limite")
            .setLargeIcon(senalLimite(ctx, limite))
            .setContentIntent(abrirApp(ctx))
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_ALARM)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOnlyAlertOnce(!sonar)
            .setSilent(!sonar)
            .setAutoCancel(true)
            .setTimeoutAfter(30_000)   // safety net if GPS fixes stop while over the limit
            .build()
        try {
            ctx.getSystemService(NotificationManager::class.java).notify(ID_ALERTA, n)
        } catch (e: SecurityException) { }
    }

    fun quitarAlerta(ctx: Context) {
        alertaVisible = false
        bajoDesdeMs = 0L
        ctx.getSystemService(NotificationManager::class.java).cancel(ID_ALERTA)
    }

    private fun puedeNotificar(ctx: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
                ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) ==
                PackageManager.PERMISSION_GRANTED

    // A small speed-limit sign (white disc, red ring, the number) for the large icon.
    private val cacheSenal = HashMap<Int, Bitmap>()

    private fun senalLimite(ctx: Context, limite: Int): Bitmap = cacheSenal.getOrPut(limite) {
        val tam = (64 * ctx.resources.displayMetrics.density).toInt().coerceAtLeast(64)
        val bmp = Bitmap.createBitmap(tam, tam, Bitmap.Config.ARGB_8888)
        val c = Canvas(bmp)
        val r = tam / 2f
        val p = Paint(Paint.ANTI_ALIAS_FLAG)
        p.color = ContextCompat.getColor(ctx, R.color.senal_rojo)
        c.drawCircle(r, r, r, p)
        p.color = 0xFFFFFFFF.toInt()
        c.drawCircle(r, r, r * 0.76f, p)
        p.color = 0xFF111111.toInt()
        p.typeface = Typeface.create(Typeface.DEFAULT, Typeface.BOLD)
        p.textAlign = Paint.Align.CENTER
        val texto = limite.toString()
        p.textSize = r * (if (texto.length >= 3) 0.68f else 0.86f)
        val y = r - (p.descent() + p.ascent()) / 2
        c.drawText(texto, r, y, p)
        bmp
    }
}
