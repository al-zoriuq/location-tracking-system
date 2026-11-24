package com.example.gpslink

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.PixelFormat
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.WindowManager
import kotlin.math.hypot

// Pipo's floating bubble (like chat heads), shown over other apps while GPSLink is
// in the background. Besides being handy, a visible overlay window counts as "app in
// use" for Android 14+, so the service can get the microphone back after the system
// restarted it in the background (see UbicacionService.recuperarMicrofono).
//   tap: ask Pipo (tap again while listening: done talking)
//   drag: move it; it snaps to the nearest side
//   drag onto the X: hide it until the app is opened again
object BurbujaPipo {

    private var ctx: Context? = null
    private var wm: WindowManager? = null
    private var orbe: OrbePipo? = null
    private var params: WindowManager.LayoutParams? = null
    private var destino: DestinoX? = null
    private var alAparecer: () -> Unit = {}
    private var ocultaPorUsuario = false
    private val main = Handler(Looper.getMainLooper())

    // The window must be on screen before the service asks for the microphone.
    private val avisarAparicion = Runnable { if (orbe != null) alAparecer() }

    fun permitida(c: Context) =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.M || Settings.canDrawOverlays(c)

    // Called by UbicacionService; `aparecio` runs once the bubble is visible.
    fun iniciar(contexto: Context, aparecio: () -> Unit) {
        val app = contexto.applicationContext
        ctx = app
        wm = app.getSystemService(Context.WINDOW_SERVICE) as WindowManager
        alAparecer = aparecio
    }

    // Opening the app shows Pipo's card instead, and undoes "hidden with the X".
    fun alAbrirApp() {
        ocultaPorUsuario = false
        ocultar()
    }

    fun mostrar() {
        val c = ctx ?: return
        val w = wm ?: return
        if (orbe != null || ocultaPorUsuario || EstadoApp.appEnPantalla) return
        if (!EstadoApp.servicioActivo || !Ajustes.pipoActivo(c) || !permitida(c)) return

        val tam = dp(c, 64f)
        val pantalla = c.resources.displayMetrics
        val p = parametros(tam, tam).apply {
            gravity = Gravity.TOP or Gravity.START
            x = pantalla.widthPixels - tam - dp(c, 8f)
            y = pantalla.heightPixels / 3
        }
        val v = OrbePipo(c).apply {
            estado = Pipo.estado
            contentDescription = "Pipo"
            setOnTouchListener(Arrastre())
        }
        try {
            w.addView(v, p)
        } catch (e: Exception) {
            return   // permission revoked meanwhile
        }
        orbe = v
        params = p
        main.postDelayed(avisarAparicion, 500)
    }

    fun ocultar() {
        main.removeCallbacks(avisarAparicion)
        quitarDestino()
        orbe?.let { try { wm?.removeView(it) } catch (e: Exception) {} }
        orbe = null
        params = null
    }

    // Pipo's state changed (any thread): follow it, or go away if Pipo was turned off.
    fun refrescar() {
        main.post {
            val c = ctx ?: return@post
            if (!Ajustes.pipoActivo(c) || !EstadoApp.servicioActivo) ocultar()
            else orbe?.estado = Pipo.estado
        }
    }

    private fun tocar() {
        if (Pipo.estado == Pipo.Estado.ESCUCHANDO) Pipo.dejarDeEscuchar() else Pipo.preguntarAhora()
    }

    // --- Dragging ---

    private class Arrastre : View.OnTouchListener {
        private var x0 = 0
        private var y0 = 0
        private var toqueX = 0f
        private var toqueY = 0f
        private var movio = false

        @SuppressLint("ClickableViewAccessibility")
        override fun onTouch(v: View, e: MotionEvent): Boolean {
            val p = params ?: return false
            val c = ctx ?: return false
            when (e.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    x0 = p.x; y0 = p.y
                    toqueX = e.rawX; toqueY = e.rawY
                    movio = false
                }
                MotionEvent.ACTION_MOVE -> {
                    val dx = e.rawX - toqueX
                    val dy = e.rawY - toqueY
                    if (!movio && hypot(dx, dy) > dp(c, 10f)) {
                        movio = true
                        mostrarDestino()
                    }
                    if (movio) {
                        p.x = x0 + dx.toInt()
                        p.y = y0 + dy.toInt()
                        try { wm?.updateViewLayout(v, p) } catch (e: Exception) {}
                        destino?.resaltado = sobreDestino(e.rawX, e.rawY)
                    }
                }
                MotionEvent.ACTION_UP -> {
                    when {
                        !movio -> { v.performClick(); tocar() }
                        sobreDestino(e.rawX, e.rawY) -> { ocultaPorUsuario = true; ocultar(); return true }
                        else -> pegarAlBorde(v, p)
                    }
                    quitarDestino()
                }
                MotionEvent.ACTION_CANCEL -> quitarDestino()
            }
            return true
        }
    }

    private fun pegarAlBorde(v: View, p: WindowManager.LayoutParams) {
        val c = ctx ?: return
        val pantalla = c.resources.displayMetrics
        val margen = dp(c, 8f)
        val izquierda = p.x + v.width / 2 < pantalla.widthPixels / 2
        p.x = if (izquierda) margen else pantalla.widthPixels - v.width - margen
        p.y = p.y.coerceIn(dp(c, 48f), pantalla.heightPixels - v.height - dp(c, 48f))
        try { wm?.updateViewLayout(v, p) } catch (e: Exception) {}
    }

    // --- The X target at the bottom, only while dragging ---

    private fun mostrarDestino() {
        val c = ctx ?: return
        if (destino != null) return
        val tam = dp(c, 72f)
        val p = parametros(tam, tam).apply {
            gravity = Gravity.BOTTOM or Gravity.CENTER_HORIZONTAL
            y = dp(c, 72f)
            flags = flags or WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE
        }
        val v = DestinoX(c)
        try { wm?.addView(v, p); destino = v } catch (e: Exception) {}
    }

    private fun quitarDestino() {
        destino?.let { try { wm?.removeView(it) } catch (e: Exception) {} }
        destino = null
    }

    private fun sobreDestino(x: Float, y: Float): Boolean {
        val d = destino ?: return false
        val c = ctx ?: return false
        if (!d.isAttachedToWindow) return false
        val pos = IntArray(2)
        d.getLocationOnScreen(pos)
        val cx = pos[0] + d.width / 2f
        val cy = pos[1] + d.height / 2f
        return hypot(x - cx, y - cy) < dp(c, 64f)
    }

    private class DestinoX(context: Context) : View(context) {
        var resaltado = false
            set(v) { if (v != field) { field = v; invalidate() } }

        private val fondo = Paint(Paint.ANTI_ALIAS_FLAG)
        private val borde = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            color = 0x8CFFFFFF.toInt()
        }
        private val cruz = Paint(Paint.ANTI_ALIAS_FLAG).apply {
            style = Paint.Style.STROKE
            strokeCap = Paint.Cap.ROUND
            color = 0xFFFFFFFF.toInt()
        }

        override fun onDraw(canvas: Canvas) {
            val cx = width / 2f
            val cy = height / 2f
            val r = width / 2f * (if (resaltado) 0.98f else 0.8f)
            fondo.color = if (resaltado) 0xE6FF5A6E.toInt() else 0xB3170E2B.toInt()
            borde.strokeWidth = width * 0.03f
            cruz.strokeWidth = width * 0.05f
            canvas.drawCircle(cx, cy, r, fondo)
            canvas.drawCircle(cx, cy, r, borde)
            val l = r * 0.36f
            canvas.drawLine(cx - l, cy - l, cx + l, cy + l, cruz)
            canvas.drawLine(cx - l, cy + l, cx + l, cy - l, cruz)
        }
    }

    // --- Helpers ---

    @Suppress("DEPRECATION")
    private fun parametros(ancho: Int, alto: Int) = WindowManager.LayoutParams(
        ancho, alto,
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O)
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY
        else
            WindowManager.LayoutParams.TYPE_PHONE,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
        PixelFormat.TRANSLUCENT
    )

    private fun dp(c: Context, v: Float) = (v * c.resources.displayMetrics.density).toInt()
}
