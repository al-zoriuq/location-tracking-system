package com.example.gpslink

import android.content.Context
import android.graphics.Canvas
import android.graphics.ColorFilter
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.PixelFormat
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.SweepGradient
import android.os.SystemClock
import android.graphics.drawable.Drawable
import android.util.AttributeSet
import android.view.View
import androidx.core.content.ContextCompat

// Speed ring: a faint full circle and, on top, an arc from 12 o'clock that grows
// with the speed. The screen sets `fraccion` (0..1) and `color`.
class AnilloVelocidad @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    private val grosor = 11f * resources.displayMetrics.density
    private val pista = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = grosor
        color = 0x1FFFFFFF
    }
    private val arco = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeWidth = grosor
        strokeCap = Paint.Cap.ROUND
        color = ContextCompat.getColor(context, R.color.acento)
    }
    private val caja = RectF()

    var fraccion = 0f
        set(v) { val n = v.coerceIn(0f, 1f); if (n != field) { field = n; invalidate() } }
    var color: Int
        get() = arco.color
        set(v) { if (v != arco.color) { arco.color = v; invalidate() } }

    override fun onDraw(canvas: Canvas) {
        val m = grosor / 2 + 2f
        caja.set(m, m, width - m, height - m)
        canvas.drawOval(caja, pista)
        if (fraccion > 0f) canvas.drawArc(caja, -90f, 360f * fraccion, false, arco)
    }
}

// Background: dark purple with three soft glows (violet top left, pink right,
// indigo bottom left), drawn once for the window size.
class FondoBrillos(context: Context) : Drawable() {

    private val base = ContextCompat.getColor(context, R.color.fondo)
    private val brillos = listOf(
        // color, center x, center y, radius x, radius y (fractions of the screen)
        Brillo(ContextCompat.getColor(context, R.color.brillo_morado), 0.20f, 0.08f, 0.60f, 0.40f),
        Brillo(ContextCompat.getColor(context, R.color.brillo_rosa), 1.00f, 0.40f, 0.55f, 0.35f),
        Brillo(ContextCompat.getColor(context, R.color.brillo_indigo), 0.00f, 0.95f, 0.70f, 0.45f),
    )
    private val pintura = Paint(Paint.ANTI_ALIAS_FLAG)
    private val matriz = Matrix()

    private class Brillo(val color: Int, val x: Float, val y: Float, val rx: Float, val ry: Float)

    override fun draw(canvas: Canvas) {
        val b = bounds
        val w = b.width().toFloat()
        // The glows are sized for a phone screen; on a long scroll they stay at the top.
        val h = minOf(b.height().toFloat(), w * 2.2f)
        canvas.drawColor(base)
        for (g in brillos) {
            val transparente = g.color and 0x00FFFFFF
            val shader = RadialGradient(0f, 0f, 1f, intArrayOf(g.color, transparente),
                floatArrayOf(0f, 0.7f), Shader.TileMode.CLAMP)
            matriz.reset()
            matriz.setScale(g.rx * w, g.ry * h)
            matriz.postTranslate(b.left + g.x * w, b.top + g.y * h)
            shader.setLocalMatrix(matriz)
            pintura.shader = shader
            canvas.drawRect(b, pintura)
        }
    }

    override fun setAlpha(alpha: Int) {}
    override fun setColorFilter(colorFilter: ColorFilter?) {}
    @Deprecated("Deprecated in Java")
    override fun getOpacity() = PixelFormat.OPAQUE
}

// Pipo's face: a glowing sphere with a turning aurora, eyes and a mouth. Color and
// motion follow his state (same look as the web page and the design canvas):
//   dormido violet, slow breath, eyes closed · escuchando turquoise, fast pulse,
//   eyes open · pensando amber, the aurora spins fast · hablando pink, the mouth
//   moves · apagado grey and still.
class OrbePipo @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    var estado = Pipo.Estado.DORMIDO
        set(v) { if (v != field) { field = v; invalidate() } }

    private class Colores(val c: Int, val c2: Int, val brillo: Int, val brillo2: Int)

    private fun colores() = when (estado) {
        Pipo.Estado.ESCUCHANDO -> Colores(0xFF67E8F9.toInt(), 0xFF0E7490.toInt(), 0xB367E8F9.toInt(), 0x8CB79CFF.toInt())
        Pipo.Estado.PENSANDO -> Colores(0xFFFCD34D.toInt(), 0xFFB45309.toInt(), 0x99FCD34D.toInt(), 0x80FF8A95.toInt())
        Pipo.Estado.HABLANDO -> Colores(0xFFFF9AD5.toInt(), 0xFFB0306E.toInt(), 0xA6FF9AD5.toInt(), 0x8CB79CFF.toInt())
        Pipo.Estado.APAGADO -> Colores(0xFF9A93B0.toInt(), 0xFF4B4560.toInt(), 0, 0)
        else -> Colores(0xFFB79CFF.toInt(), 0xFF5B3FC4.toInt(), 0x99B79CFF.toInt(), 0x8C7A4DE0.toInt())
    }

    private val inicio = SystemClock.uptimeMillis()
    private val halo = Paint(Paint.ANTI_ALIAS_FLAG)
    private val aurora = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val cuerpo = Paint(Paint.ANTI_ALIAS_FLAG)
    private val blanco = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFFFFFFFF.toInt() }
    private val trazo = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = 0xFFFFFFFF.toInt(); style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND
    }
    private val caja = RectF()
    private val PI2 = (Math.PI * 2).toFloat()

    // The animation stops while hidden (isShown); start it again when shown.
    override fun onVisibilityChanged(changedView: View, visibility: Int) {
        super.onVisibilityChanged(changedView, visibility)
        if (visibility == VISIBLE) invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val t = (SystemClock.uptimeMillis() - inicio) / 1000f
        val col = colores()
        val cx = width / 2f
        val cy = height / 2f
        val radio = minOf(width, height) / 2f
        val e = estado

        val (periodo, amplitud) = when (e) {
            Pipo.Estado.ESCUCHANDO -> 1.1f to 0.05f
            Pipo.Estado.APAGADO -> 1f to 0f
            else -> 3.2f to 0.025f
        }
        val r = radio * 0.72f * (1f + amplitud * kotlin.math.sin(PI2 * t / periodo))

        if (e != Pipo.Estado.APAGADO) {
            // Soft glow around the sphere.
            halo.shader = RadialGradient(cx, cy, radio, intArrayOf(col.brillo, col.brillo and 0x00FFFFFF),
                floatArrayOf(0.6f, 1f), Shader.TileMode.CLAMP)
            canvas.drawCircle(cx, cy, radio, halo)
            // Aurora: a turning ring of two colors.
            val vuelta = if (e == Pipo.Estado.PENSANDO) 1.6f else 6f
            val transp = col.brillo and 0x00FFFFFF
            aurora.shader = SweepGradient(cx, cy,
                intArrayOf(transp, col.brillo, transp, col.brillo2, transp), null)
            aurora.strokeWidth = radio * 0.14f
            canvas.save()
            canvas.rotate(360f * (t / vuelta % 1f), cx, cy)
            canvas.drawCircle(cx, cy, r * 1.14f, aurora)
            canvas.restore()
        }

        // The sphere, lit from the top left.
        cuerpo.shader = RadialGradient(cx - r * 0.32f, cy - r * 0.44f, r * 1.55f,
            intArrayOf(0xE6FFFFFF.toInt(), col.c, col.c2), floatArrayOf(0f, 0.3f, 0.85f), Shader.TileMode.CLAMP)
        canvas.drawCircle(cx, cy, r, cuerpo)

        // Face, in fractions of the sphere's box (same proportions as the canvas).
        val x0 = cx - r
        val y0 = cy - r
        val d = r * 2
        val ojoW = d * 0.11f
        val parpadeo = (t % 4.5f) in 4.25f..4.4f
        val dormido = e == Pipo.Estado.DORMIDO || e == Pipo.Estado.APAGADO
        val (ojoTop, ojoH) = when {
            dormido -> 0.45f to 0.035f
            e == Pipo.Estado.ESCUCHANDO -> 0.34f to 0.21f
            e == Pipo.Estado.PENSANDO -> 0.32f to 0.14f
            else -> 0.36f to 0.17f
        }
        val h = if (parpadeo && !dormido) d * 0.02f else d * ojoH
        for (izq in floatArrayOf(0.33f, 0.56f)) {
            caja.set(x0 + d * izq, y0 + d * ojoTop + (d * ojoH - h) / 2, x0 + d * izq + ojoW, y0 + d * ojoTop + (d * ojoH + h) / 2)
            canvas.drawRoundRect(caja, ojoW * 0.4f, ojoW * 0.4f, blanco)
        }

        trazo.strokeWidth = maxOf(2f, d * 0.04f)
        when (e) {
            Pipo.Estado.HABLANDO -> {
                val abre = 0.35f + 0.9f * kotlin.math.abs(kotlin.math.sin(t * Math.PI.toFloat() / 0.32f))
                val bh = d * 0.10f * abre
                caja.set(x0 + d * 0.39f, y0 + d * 0.62f - bh / 2, x0 + d * 0.61f, y0 + d * 0.62f + bh / 2)
                canvas.drawOval(caja, blanco)
            }
            Pipo.Estado.ESCUCHANDO -> canvas.drawCircle(x0 + d * 0.5f, y0 + d * 0.62f, d * 0.05f, trazo)
            Pipo.Estado.PENSANDO -> canvas.drawLine(x0 + d * 0.44f, y0 + d * 0.62f, x0 + d * 0.56f, y0 + d * 0.62f, trazo)
            else -> {
                caja.set(x0 + d * 0.39f, y0 + d * 0.48f, x0 + d * 0.61f, y0 + d * 0.66f)
                canvas.drawArc(caja, 20f, 140f, false, trazo)
            }
        }

        // Asleep he only breathes slowly: ~20 frames per second is enough and saves
        // battery (the bubble stays on screen the whole trip). Full rate when active.
        if (e != Pipo.Estado.APAGADO && isShown) {
            if (e == Pipo.Estado.DORMIDO || e == Pipo.Estado.PREPARANDO) postInvalidateDelayed(50)
            else postInvalidateOnAnimation()
        }
    }
}

// Voice waves under Pipo while he listens: 9 bars that follow the mic level.
class OndasVoz @JvmOverloads constructor(
    context: Context, attrs: AttributeSet? = null
) : View(context, attrs) {

    private val barra = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = 0xFF67E8F9.toInt() }
    private val caja = RectF()
    private val inicio = SystemClock.uptimeMillis()
    private var nivel = 0f

    // The animation stops while hidden (isShown); start it again when shown.
    override fun onVisibilityChanged(changedView: View, visibility: Int) {
        super.onVisibilityChanged(changedView, visibility)
        if (visibility == VISIBLE) invalidate()
    }

    override fun onDraw(canvas: Canvas) {
        val t = (SystemClock.uptimeMillis() - inicio) / 1000f
        // SpeechRecognizer's rms goes roughly from -2 (silence) to 10 (loud).
        val objetivo = ((Pipo.nivelVoz + 2f) / 12f).coerceIn(0.15f, 1f)
        nivel += (objetivo - nivel) * 0.25f
        val n = 9
        val ancho = width / (n * 2f - 1f)
        for (i in 0 until n) {
            val ola = 0.5f + 0.5f * kotlin.math.sin(t * (6f + i * 0.9f) + i)
            val alto = height * (0.2f + 0.8f * ola * nivel)
            val x = i * ancho * 2
            caja.set(x, (height - alto) / 2, x + ancho, (height + alto) / 2)
            canvas.drawRoundRect(caja, ancho / 2, ancho / 2, barra)
        }
        if (isShown) postInvalidateOnAnimation()
    }
}
