package com.example.gpslink

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.drawable.GradientDrawable
import android.os.Build
import android.net.Uri
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.Button
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.PopupMenu
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import androidx.core.content.res.ResourcesCompat
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.updateLayoutParams
import androidx.core.view.updatePadding
import com.google.android.material.materialswitch.MaterialSwitch
import com.google.android.material.textfield.TextInputEditText
import java.net.DatagramPacket
import java.net.DatagramSocket
import java.net.InetAddress
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

class MainActivity : AppCompatActivity() {

    private lateinit var scroll: ScrollView
    private lateinit var contenido: View
    private lateinit var tvAviso: TextView
    private lateinit var anillo: AnilloVelocidad
    private lateinit var tvVelocidad: TextView
    private lateinit var tvLimite: TextView
    private lateinit var tvExceso: TextView
    private lateinit var tvExcesoDetalle: TextView
    private lateinit var tvPiEstado: TextView
    private lateinit var tvPiDetalle: TextView
    private lateinit var tvUbicEstado: TextView
    private lateinit var tvUbicDetalle: TextView
    private lateinit var tarjetaRecientes: View
    private lateinit var listaRecientes: LinearLayout
    private lateinit var tvSinRecientes: TextView
    private lateinit var panelAjustes: View
    private lateinit var etServidor: TextInputEditText
    private lateinit var etPi: TextInputEditText
    private lateinit var etUrlPipo: TextInputEditText
    private lateinit var tvDiagnostico: TextView
    private lateinit var barraPi: View

    // Pipo: card on the screen + sheet that comes up while you talk to him.
    private lateinit var orbePipo: OrbePipo
    private lateinit var tvPipoEstado: TextView
    private lateinit var tvPipoDialogo: TextView
    private lateinit var swPipo: MaterialSwitch
    private lateinit var capaPipo: View
    private lateinit var hojaPipo: View
    private lateinit var orbeHoja: OrbePipo
    private lateinit var tvHojaEstado: TextView
    private lateinit var ondasPipo: View
    private lateinit var tvHojaTexto: TextView
    private lateinit var btnPipoListo: View
    private var hojaAbajoBase = 0

    // Insets (status/navigation bar, keyboard) and the paddings from the layout.
    private var arribaBase = 0
    private var abajoBase = 0
    private var insetArriba = 0
    private var insetAbajo = 0
    private var insetTeclado = 0

    private var clavelista = ""   // what the recent-signs list was last drawn from
    private val horaCorta = SimpleDateFormat("H:mm", Locale.getDefault())

    // The screen refreshes on every service broadcast and once per second
    // (so "hace N s" keeps counting even when nothing new arrives).
    private val handler = Handler(Looper.getMainLooper())
    private val refresco = object : Runnable {
        override fun run() {
            pintar()
            handler.postDelayed(this, 1000)
        }
    }

    // The service itself does NOT depend on this Activity existing at all.
    private val estadoReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) = pintar()
    }

    // --- Sequential permission chain: location -> notifications -> background ---
    // Android requires these as SEPARATE requests, in this order, never combined.

    private val permisoFondoLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ -> pedirPermisoMicrofonoSiHaceFalta() } // proceed either way; background just improves reliability

    // Pipo hears his name through the mic. Without it he still speaks the warnings.
    private val permisoMicLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { concedido ->
        if (!concedido) Toast.makeText(this, R.string.pipo_permiso_mic, Toast.LENGTH_LONG).show()
        iniciarServicio()   // (re)start so the service gets the microphone type
    }

    private val permisoNotifLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ -> pedirPermisoFondoSiHaceFalta() }

    // Android 12+ ignores a request for FINE alone: both go together, and the user can
    // still pick "approximate", which is not enough for the route (needs the GPS).
    private val permisoUbicacionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { resultado ->
        when {
            resultado[Manifest.permission.ACCESS_FINE_LOCATION] == true -> pedirPermisoNotifSiHaceFalta()
            resultado[Manifest.permission.ACCESS_COARSE_LOCATION] == true -> {
                EstadoApp.aviso = "Falta el permiso de ubicación precisa (Ajustes → Apps → GPSLink → Ubicación)"
                pintar()
            }
            else -> {
                EstadoApp.aviso = "Se necesita el permiso de ubicación"
                pintar()
            }
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        scroll = findViewById(R.id.scroll)
        contenido = findViewById(R.id.contenido)
        tvAviso = findViewById(R.id.tvAviso)
        anillo = findViewById(R.id.anillo)
        tvVelocidad = findViewById(R.id.tvVelocidad)
        tvLimite = findViewById(R.id.tvLimite)
        tvExceso = findViewById(R.id.tvExceso)
        tvExcesoDetalle = findViewById(R.id.tvExcesoDetalle)
        tvPiEstado = findViewById(R.id.tvPiEstado)
        tvPiDetalle = findViewById(R.id.tvPiDetalle)
        tvUbicEstado = findViewById(R.id.tvUbicEstado)
        tvUbicDetalle = findViewById(R.id.tvUbicDetalle)
        tarjetaRecientes = findViewById(R.id.tarjetaRecientes)
        listaRecientes = findViewById(R.id.listaRecientes)
        tvSinRecientes = findViewById(R.id.tvSinRecientes)
        panelAjustes = findViewById(R.id.panelAjustes)
        etServidor = findViewById(R.id.etServidor)
        etPi = findViewById(R.id.etPi)
        etUrlPipo = findViewById(R.id.etUrlPipo)
        tvDiagnostico = findViewById(R.id.tvDiagnostico)
        barraPi = findViewById(R.id.barraPi)
        orbePipo = findViewById(R.id.orbePipo)
        tvPipoEstado = findViewById(R.id.tvPipoEstado)
        tvPipoDialogo = findViewById(R.id.tvPipoDialogo)
        swPipo = findViewById(R.id.swPipo)
        capaPipo = findViewById(R.id.capaPipo)
        hojaPipo = findViewById(R.id.hojaPipo)
        orbeHoja = findViewById(R.id.orbeHoja)
        tvHojaEstado = findViewById(R.id.tvHojaEstado)
        ondasPipo = findViewById(R.id.ondasPipo)
        tvHojaTexto = findViewById(R.id.tvHojaTexto)
        btnPipoListo = findViewById(R.id.btnPipoListo)
        hojaAbajoBase = hojaPipo.paddingBottom

        val raiz = findViewById<View>(R.id.raiz)
        raiz.background = FondoBrillos(this)

        // Edge-to-edge (Android 15+ draws behind the system bars): the title goes
        // below the status bar, the floating bar above the navigation bar, and the
        // list keeps room at the bottom for the bar (and the keyboard in settings).
        arribaBase = contenido.paddingTop
        abajoBase = contenido.paddingBottom
        ViewCompat.setOnApplyWindowInsetsListener(raiz) { _, insets ->
            val barras = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            insetArriba = barras.top
            insetAbajo = barras.bottom
            insetTeclado = insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
            ajustarMargenes()
            insets
        }

        cargarAjustesEnPantalla()

        val btnAjustes = findViewById<View>(R.id.btnAjustes)
        btnAjustes.setOnClickListener { alternarAjustes() }
        btnAjustes.setOnLongClickListener { mostrarMenuOculto(it); true }
        findViewById<Button>(R.id.btnGuardarServidor).setOnClickListener { guardarAjustes() }
        findViewById<View>(R.id.btnPiEstado).setOnClickListener { enviarComandoPi("ESTADO") }
        findViewById<View>(R.id.btnPiPausa).setOnClickListener { enviarComandoPi("PAUSA") }
        findViewById<View>(R.id.btnPiReanuda).setOnClickListener { enviarComandoPi("REANUDA") }
        findViewById<View>(R.id.btnPiApagar).setOnClickListener {
            AlertDialog.Builder(this)
                .setTitle("Apagar la Raspberry")
                .setMessage("¿Seguro? Para volver a encenderla hay que desconectarla y conectarla.")
                .setPositiveButton("Apagar") { _, _ -> enviarComandoPi("APAGAR") }
                .setNegativeButton("Cancelar", null)
                .show()
        }

        swPipo.isChecked = Ajustes.pipoActivo(this)
        swPipo.setOnCheckedChangeListener { _, activo ->
            Ajustes.guardarPipoActivo(this, activo)
            if (activo && !tienePermisoMic()) {
                permisoMicLauncher.launch(Manifest.permission.RECORD_AUDIO)
            } else {
                Pipo.aplicarAjuste()
            }
            pintar()
        }
        findViewById<View>(R.id.tarjetaPipo).setOnClickListener {
            when {
                !Ajustes.pipoActivo(this) -> Toast.makeText(this, "Activa a Pipo con el interruptor", Toast.LENGTH_SHORT).show()
                !EstadoApp.servicioActivo -> Toast.makeText(this, "Pipo arranca cuando la app empieza a enviar", Toast.LENGTH_SHORT).show()
                else -> Pipo.preguntarAhora()
            }
        }
        findViewById<View>(R.id.btnPipoCancelar).setOnClickListener { Pipo.cancelar() }
        btnPipoListo.setOnClickListener { Pipo.dejarDeEscuchar() }

        pedirPermisosYArrancar()
    }

    override fun onStart() {
        super.onStart()
        EstadoApp.appEnPantalla = true
        BurbujaPipo.alAbrirApp()
        // Back on screen: a service that lost the mic in the background can take it again.
        if (EstadoApp.servicioActivo && !EstadoApp.microfonoEnServicio &&
            Ajustes.pipoActivo(this) && tienePermisoMic()
        ) iniciarServicio()
        handler.postDelayed({ ofrecerBurbuja() }, 1_500)
        ContextCompat.registerReceiver(
            this, estadoReceiver, IntentFilter(UbicacionService.ACCION_ESTADO),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
        handler.post(refresco)
    }

    override fun onStop() {
        super.onStop()
        handler.removeCallbacks(refresco)
        unregisterReceiver(estadoReceiver)
        EstadoApp.appEnPantalla = false
        // Not for a rotation or a light/dark switch: the screen comes right back.
        if (!isChangingConfigurations) BurbujaPipo.mostrar()
    }

    // Asked once: Pipo's bubble needs "display over other apps".
    private fun ofrecerBurbuja() {
        if (isFinishing || !EstadoApp.appEnPantalla || !EstadoApp.servicioActivo) return
        if (!Ajustes.pipoActivo(this) || BurbujaPipo.permitida(this) || Ajustes.burbujaOfrecida(this)) return
        Ajustes.marcarBurbujaOfrecida(this)
        AlertDialog.Builder(this)
            .setTitle("Pipo flotante")
            .setMessage(
                "Cuando salgas de GPSLink, Pipo queda como una burbuja sobre las demás apps: " +
                "tócala para preguntarle y arrástrala a la X para quitarla. Así también sigue " +
                "escuchando «Pipo» aunque Android reinicie la app.\n\n" +
                "Para eso, permite «Mostrar sobre otras apps»."
            )
            .setPositiveButton("Permitir") { _, _ ->
                startActivity(
                    Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName"))
                )
            }
            .setNegativeButton("Ahora no", null)
            .show()
    }

    private fun ajustarMargenes() {
        val conBarra = barraPi.visibility == View.VISIBLE
        val barra = if (conBarra) dp(80f).toInt() else 0
        contenido.updatePadding(
            top = arribaBase + insetArriba,
            bottom = abajoBase + maxOf(insetAbajo + barra, insetTeclado)
        )
        barraPi.updateLayoutParams<FrameLayout.LayoutParams> { bottomMargin = dp(16f).toInt() + insetAbajo }
        hojaPipo.updatePadding(bottom = hojaAbajoBase + insetAbajo)
    }

    private fun alternarAjustes() {
        if (panelAjustes.visibility == View.VISIBLE) {
            panelAjustes.visibility = View.GONE
            currentFocus?.clearFocus()
        } else {
            panelAjustes.visibility = View.VISIBLE
            pintar()
            scroll.post { scroll.smoothScrollTo(0, panelAjustes.top) }
        }
    }

    // --- Drawing the live state ---

    private fun color(id: Int) = ContextCompat.getColor(this, id)

    private fun dp(v: Float) = v * resources.displayMetrics.density

    private fun haceTexto(ms: Long): String {
        val s = ((System.currentTimeMillis() - ms) / 1000).coerceAtLeast(0)
        return when {
            s < 60 -> "hace $s s"
            s < 3600 -> "hace ${s / 60} min"
            else -> "hace ${s / 3600} h"
        }
    }

    private fun pintar() {
        val e = EstadoApp
        val ahora = System.currentTimeMillis()
        val edadFix = if (e.ultimoFixMs > 0) (ahora - e.ultimoFixMs) / 1000 else -1
        val ipPi = Ajustes.ipPiEfectiva(this)
        val recientes = e.recientes()

        // Problems the user has to fix.
        val aviso = e.aviso.takeIf { it.contains("permiso") || it.contains("desactivado") }
        tvAviso.visibility = if (aviso != null) View.VISIBLE else View.GONE
        tvAviso.text = aviso ?: ""

        // --- Speed ring + last speed limit seen ---
        val v = if (edadFix in 0L..5L && e.velocidadKmh >= 0) e.velocidadKmh else null
        tvVelocidad.text = if (v != null) String.format(Locale.US, "%.0f", v) else "—"

        // The last limit stays on screen for 15 min (after that the car is
        // probably on another road). Its time is when the Pi saw it, so a detection
        // that arrives late (kept by the Pi while the phone was away) shows its age.
        val limite = e.limiteKmh.takeIf { it > 0 && ahora - e.limiteMs <= 15 * 60_000L }
        val excede = limite != null && v != null && v > limite + Ajustes.TOLERANCIA_KMH
        anillo.fraccion = if (v == null) 0f else v / (if (limite != null) limite * 2.5f else 120f)
        anillo.color = color(if (excede) R.color.excede else R.color.acento)

        if (limite != null) {
            tvLimite.visibility = View.VISIBLE
            dibujarSenal(tvLimite, "LIMITE $limite", grande = true)
            when {
                v == null -> texto(tvExceso, "Límite $limite", R.color.texto)
                excede -> texto(tvExceso, String.format(Locale.US, "%.0f por encima", v - limite), R.color.excede_texto)
                else -> texto(tvExceso, "Dentro del límite", R.color.cumple)
            }
            tvExcesoDetalle.text = haceTexto(e.limiteMs)
        } else {
            tvLimite.visibility = View.GONE
            texto(tvExceso, if (ipPi != null) "Sin límite aún" else "Solo ruta", R.color.texto)
            tvExcesoDetalle.text = if (e.ultimoFixMs > 0)
                String.format(Locale.US, "%.5f, %.5f", e.lat, e.lon) else "Sin posición todavía"
        }

        // --- Location widget ---
        when {
            !e.servicioActivo -> widget(tvUbicEstado, tvUbicDetalle, "Detenido", R.color.apagado, "no se envía nada")
            edadFix < 0 -> widget(tvUbicEstado, tvUbicDetalle, "Buscando", R.color.atencion, "señal GPS")
            edadFix > 5 -> widget(tvUbicEstado, tvUbicDetalle, "Sin GPS", R.color.atencion, "último fix ${haceTexto(e.ultimoFixMs)}")
            e.sinInternet -> widget(tvUbicEstado, tvUbicDetalle, "Sin internet", R.color.atencion, "${e.enCola} guardados")
            e.enviados > 0 -> widget(tvUbicEstado, tvUbicDetalle, "Enviando", R.color.texto,
                if (e.precisionM >= 0) String.format(Locale.US, "±%.0f m · %d puntos", e.precisionM, e.enviados)
                else "${e.enviados} puntos")
            else -> widget(tvUbicEstado, tvUbicDetalle, "Preparando", R.color.atencion, "cada 1 s")
        }

        // --- Raspberry widget ---
        val edadPi = if (e.piUltimoMs > 0) (ahora - e.piUltimoMs) / 1000 else -1
        val senales = e.piSenales.ifEmpty { e.detRecibidas.toString() }
        when {
            ipPi == null -> widget(tvPiEstado, tvPiDetalle, "Ninguna", R.color.apagado, "solo se envía la ruta")
            edadPi < 0 -> widget(tvPiEstado, tvPiDetalle, "Esperando", R.color.atencion, ipPi)
            edadPi > 15 -> widget(tvPiEstado, tvPiDetalle, "Sin respuesta", R.color.excede_texto, haceTexto(e.piUltimoMs))
            e.piEstado == "PAUSADO" -> widget(tvPiEstado, tvPiDetalle, "En pausa", R.color.atencion, "$senales señales")
            e.piEstado == "APAGANDO" -> widget(tvPiEstado, tvPiDetalle, "Apagando", R.color.apagado, "$senales señales")
            else -> widget(tvPiEstado, tvPiDetalle, "Conectada", R.color.texto, "$senales señales")
        }

        // --- Recent signs (only with a Pi, or if some arrived) ---
        tarjetaRecientes.visibility = if (ipPi != null || recientes.isNotEmpty()) View.VISIBLE else View.GONE
        pintarRecientes(recientes)

        // --- Floating bar with the Pi commands ---
        val verBarra = if (ipPi != null) View.VISIBLE else View.GONE
        if (barraPi.visibility != verBarra) {
            barraPi.visibility = verBarra
            ajustarMargenes()
        }

        pintarPipo()

        if (panelAjustes.visibility == View.VISIBLE) pintarDiagnostico(ipPi)
    }

    // --- Pipo ---

    private fun pintarPipo() {
        val activo = Ajustes.pipoActivo(this)
        val estado = if (activo) Pipo.estado else Pipo.Estado.APAGADO
        orbePipo.estado = estado
        if (swPipo.isChecked != activo) swPipo.isChecked = activo

        val detalle = Pipo.detalle
        tvPipoEstado.text = when (estado) {
            Pipo.Estado.APAGADO -> if (activo) "Arrancando…" else "Apagado · actívalo con el interruptor"
            Pipo.Estado.PREPARANDO -> detalle.ifBlank { "Preparándose…" }
            Pipo.Estado.DORMIDO -> if (detalle.isBlank() || detalle == "Di «Pipo»") "Di «Pipo» o tócame para preguntar" else detalle
            Pipo.Estado.ESCUCHANDO -> "Te escucho…"
            Pipo.Estado.PENSANDO -> "Pensando…"
            Pipo.Estado.HABLANDO -> "Hablando"
        }
        val frase = Pipo.ultimaFrase
        tvPipoDialogo.visibility = if (activo && frase.isNotBlank()) View.VISIBLE else View.GONE
        tvPipoDialogo.text = frase

        // The sheet: from "Pipo" until the answer has been spoken.
        val hoja = activo && Pipo.enConversacion
        if (hoja != (capaPipo.visibility == View.VISIBLE)) {
            if (hoja) {
                capaPipo.alpha = 0f
                capaPipo.visibility = View.VISIBLE
                capaPipo.animate().alpha(1f).setDuration(180).start()
                hojaPipo.translationY = dp(320f)
                hojaPipo.animate().translationY(0f).setDuration(260).start()
            } else {
                capaPipo.animate().alpha(0f).setDuration(180).withEndAction { capaPipo.visibility = View.GONE }.start()
                hojaPipo.animate().translationY(dp(320f)).setDuration(220).start()
            }
        }
        if (!hoja) return
        orbeHoja.estado = estado
        val (titulo, colorId) = when (estado) {
            Pipo.Estado.ESCUCHANDO -> "Te escucho…" to R.color.pipo_escucha
            Pipo.Estado.PENSANDO -> "Pensando…" to R.color.atencion
            Pipo.Estado.HABLANDO -> "Pipo responde" to R.color.pipo_habla
            else -> "Pipo" to R.color.texto_suave
        }
        texto(tvHojaEstado, titulo, colorId)
        ondasPipo.visibility = if (estado == Pipo.Estado.ESCUCHANDO) View.VISIBLE else View.GONE
        btnPipoListo.visibility = if (estado == Pipo.Estado.ESCUCHANDO) View.VISIBLE else View.GONE
        tvHojaTexto.text = when (estado) {
            Pipo.Estado.ESCUCHANDO -> if (detalle.isBlank()) "Habla ahora" else "“$detalle”"
            Pipo.Estado.PENSANDO -> "“${Pipo.ultimaPregunta}”"
            else -> Pipo.ultimaRespuesta.ifBlank { frase }
        }
    }

    private fun tienePermisoMic() = ContextCompat.checkSelfPermission(
        this, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED

    private fun texto(tv: TextView, t: String, colorId: Int) {
        tv.text = t
        tv.setTextColor(color(colorId))
    }

    private fun widget(estado: TextView, detalle: TextView, t: String, colorId: Int, d: String) {
        texto(estado, t, colorId)
        detalle.text = d
    }

    private fun pintarRecientes(recientes: List<EstadoApp.Deteccion>) {
        val clave = recientes.joinToString("|") { it.ms.toString() }
        if (clave == clavelista) return
        clavelista = clave
        listaRecientes.removeAllViews()
        tvSinRecientes.visibility = if (recientes.isEmpty()) View.VISIBLE else View.GONE
        recientes.take(4).forEachIndexed { i, d ->
            if (i > 0) listaRecientes.addView(View(this).apply {
                setBackgroundResource(R.drawable.separador)
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, dp(1f).toInt()))
            listaRecientes.addView(filaReciente(d))
        }
    }

    // One row: sign icon, name, speed (red if over the limit), time.
    private fun filaReciente(d: EstadoApp.Deteccion): View {
        val senal = campo(d.linea, "Senal") ?: "?"
        val vel = campo(d.linea, "Vel GPS")?.takeIf { it != "NA" }
            ?: campo(d.linea, "Vel MPU")?.takeIf { it != "NA" }
        val excede = d.linea.split(",").any { it.trim() == "EXCEDE" }

        val fila = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(0, dp(7f).toInt(), 0, dp(7f).toInt())
        }
        val icono = TextView(this).apply { gravity = Gravity.CENTER }
        dibujarSenal(icono, senal, grande = false)
        fila.addView(icono, LinearLayout.LayoutParams(dp(28f).toInt(), dp(28f).toInt()))

        val nombre = TextView(this).apply {
            text = nombreSenal(senal)
            setTextColor(color(R.color.texto))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
            maxLines = 1
        }
        fila.addView(nombre, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply {
            marginStart = dp(10f).toInt()
        })

        val velocidad = TextView(this).apply {
            text = if (vel != null) "$vel km/h" else "—"
            setTextColor(color(if (excede) R.color.excede_texto else R.color.texto_suave))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
        }
        fila.addView(velocidad)

        val hora = TextView(this).apply {
            text = horaCorta.format(Date(d.ms))
            setTextColor(color(R.color.texto_suave))
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 13f)
            gravity = Gravity.END
        }
        fila.addView(hora, LinearLayout.LayoutParams(dp(52f).toInt(), ViewGroup.LayoutParams.WRAP_CONTENT))
        return fila
    }

    private fun nombreSenal(senal: String) = when {
        senal.startsWith("LIMITE") -> senal.replace("LIMITE", "Límite")
        senal.startsWith("PARE") -> "Pare"
        senal.startsWith("CEDA") -> "Ceda el paso"
        else -> senal.lowercase(Locale.getDefault()).replaceFirstChar { it.uppercase() }
    }

    // Value of "Name: value" in a detection line.
    private fun campo(linea: String, nombre: String): String? =
        Regex("$nombre:\\s*([^,]+)").find(linea)?.groupValues?.get(1)?.trim()

    // Sign drawings: speed limit (white disc, red ring), PARE (red square),
    // CEDA (white disc, red ring, red text), anything else (yellow "!").
    private fun dibujarSenal(tv: TextView, senal: String, grande: Boolean) {
        val rojo = color(R.color.senal_rojo)
        val negro = Color.parseColor("#111111")
        val fondo = GradientDrawable()
        tv.typeface = ResourcesCompat.getFont(this, R.font.inter_bold)
        tv.includeFontPadding = false
        fun tam(g: Float, p: Float) = tv.setTextSize(TypedValue.COMPLEX_UNIT_SP, if (grande) g else p)
        when {
            senal.startsWith("LIMITE") -> {
                fondo.shape = GradientDrawable.OVAL
                fondo.setColor(Color.WHITE)
                fondo.setStroke(dp(if (grande) 6f else 3f).toInt(), rojo)
                tv.text = senal.removePrefix("LIMITE").trim().ifEmpty { "?" }
                tv.setTextColor(negro)
                tam(23f, 11f)
            }
            senal.startsWith("PARE") -> {
                fondo.shape = GradientDrawable.RECTANGLE
                fondo.cornerRadius = dp(if (grande) 14f else 8f)
                fondo.setColor(rojo)
                tv.text = "PARE"
                tv.setTextColor(Color.WHITE)
                tam(14f, 7f)
            }
            senal.startsWith("CEDA") -> {
                fondo.shape = GradientDrawable.OVAL
                fondo.setColor(Color.WHITE)
                fondo.setStroke(dp(if (grande) 6f else 3f).toInt(), rojo)
                tv.text = "CEDA"
                tv.setTextColor(rojo)
                tam(13f, 6.5f)
            }
            else -> {
                fondo.shape = GradientDrawable.OVAL
                fondo.setColor(Color.parseColor("#FFD166"))
                tv.text = "!"
                tv.setTextColor(negro)
                tam(23f, 13f)
            }
        }
        tv.background = fondo
    }

    private fun pintarDiagnostico(ipPi: String?) {
        val e = EstadoApp
        val lineas = mutableListOf<String>()
        if (e.resultadoEnvio.isNotEmpty()) lineas.add(e.resultadoEnvio)
        if (e.enCola > 0) lineas.add("En cola para el servidor: ${e.enCola}")
        lineas.add(when {
            ipPi == null -> "Raspberry: ninguna en este wifi"
            Ajustes.ipPi(this) == null -> "Raspberry: $ipPi (encontrada sola)"
            else -> "Raspberry: $ipPi"
        })
        if (ipPi != null || e.detRecibidas > 0)
            lineas.add("Señales recibidas ${e.detRecibidas} · reenviadas ${e.detReenviadas}")
        val id = getSharedPreferences(Ajustes.PREFS_NAME, MODE_PRIVATE).getString("device_id", null)
        if (id != null) lineas.add("Device: $id")
        tvDiagnostico.text = lineas.joinToString("\n")
    }

    // --- Permission chain ---

    private fun pedirPermisosYArrancar() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED
        ) {
            pedirPermisoNotifSiHaceFalta()
        } else {
            permisoUbicacionLauncher.launch(arrayOf(
                Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION
            ))
        }
    }

    private fun pedirPermisoNotifSiHaceFalta() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS)
            != PackageManager.PERMISSION_GRANTED
        ) {
            permisoNotifLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
        } else {
            pedirPermisoFondoSiHaceFalta()
        }
    }

    private fun pedirPermisoFondoSiHaceFalta() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
            ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_BACKGROUND_LOCATION)
            != PackageManager.PERMISSION_GRANTED
        ) {
            // On several devices/versions this dialog cannot grant "Allow all
            // the time" directly — it may redirect to Settings instead. If so,
            // the user needs to enable it manually there afterward.
            permisoFondoLauncher.launch(Manifest.permission.ACCESS_BACKGROUND_LOCATION)
        } else {
            pedirPermisoMicrofonoSiHaceFalta()
        }
    }

    private fun pedirPermisoMicrofonoSiHaceFalta() {
        if (Ajustes.pipoActivo(this) && !tienePermisoMic()) {
            permisoMicLauncher.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            iniciarServicio()
        }
    }

    private fun iniciarServicio() {
        val intent = Intent(this, UbicacionService::class.java)
        ContextCompat.startForegroundService(this, intent)
    }

    // --- Hidden manual-send menu (long press on the gear) ---

    private fun mostrarMenuOculto(anchor: View) {
        val popup = PopupMenu(this, anchor)
        popup.menuInflater.inflate(R.menu.menu_oculto, popup.menu)
        popup.setOnMenuItemClickListener { item ->
            if (item.itemId == R.id.miEnviarManual) {
                val intent = Intent(this, UbicacionService::class.java)
                    .setAction(UbicacionService.ACCION_ENVIAR_AHORA)
                ContextCompat.startForegroundService(this, intent)
                true
            } else {
                false
            }
        }
        popup.show()
    }

    // --- Raspberry Pi commands ---

    // Sends CMD,<comando> to the Pi and shows its answer
    // (EST,<device>,<ACTIVO|PAUSADO|APAGANDO>,<senales>).
    private fun enviarComandoPi(comando: String) {
        val ipPi = Ajustes.ipPiEfectiva(this) ?: return
        Thread {
            val respuesta = try {
                DatagramSocket().use { s ->
                    s.soTimeout = 2000
                    val datos = "CMD,$comando".toByteArray(Charsets.UTF_8)
                    s.send(DatagramPacket(datos, datos.size, InetAddress.getByName(ipPi), Ajustes.PUERTO_PI))
                    val buf = ByteArray(200)
                    val p = DatagramPacket(buf, buf.size)
                    s.receive(p)
                    String(p.data, 0, p.length, Charsets.UTF_8).trim()
                }
            } catch (e: Exception) {
                null
            }
            val partes = respuesta?.split(",") ?: emptyList()
            val texto = when {
                respuesta == null -> "La Raspberry no respondió. ¿Mismo wifi? ¿Detector encendido?"
                partes.size >= 4 && partes[0] == "EST" -> {
                    EstadoApp.piEstado = partes[2]
                    EstadoApp.piSenales = partes[3]
                    EstadoApp.piUltimoMs = System.currentTimeMillis()
                    val estado = when (partes[2]) {
                        "PAUSADO" -> "en pausa"
                        "APAGANDO" -> "apagándose"
                        else -> "activa"
                    }
                    "Raspberry $estado · ${partes[3]} señales"
                }
                else -> respuesta
            }
            runOnUiThread {
                Toast.makeText(this, texto, Toast.LENGTH_SHORT).show()
                pintar()
            }
        }.start()
    }

    // --- Saved IPs ---

    private fun cargarAjustesEnPantalla() {
        etServidor.setText(Ajustes.servidores(this).joinToString(";"))
        etPi.setText(Ajustes.ipPi(this) ?: "")
        etUrlPipo.setText(Ajustes.urlPipo(this))
    }

    private fun guardarAjustes() {
        val servidores = Ajustes.separar(etServidor.text?.toString() ?: "")
        val pi = etPi.text?.toString()?.trim() ?: ""
        if (servidores.isEmpty()) {
            Toast.makeText(this, "Escribe al menos la IP del servidor", Toast.LENGTH_SHORT).show()
            return
        }
        if (pi.isNotEmpty() && pi in servidores) {
            Toast.makeText(this, "La IP de la Raspberry no puede ser la del servidor", Toast.LENGTH_SHORT).show()
            return
        }
        Ajustes.guardar(this, servidores.joinToString(";"), pi)
        Ajustes.guardarUrlPipo(this, etUrlPipo.text?.toString() ?: "")
        EstadoApp.piUltimoMs = 0L
        EstadoApp.piEstado = ""
        EstadoApp.piSenales = ""
        cargarAjustesEnPantalla()
        currentFocus?.clearFocus()
        Toast.makeText(this, if (pi.isEmpty()) "Guardado (sin Raspberry)" else "Guardado", Toast.LENGTH_SHORT).show()
        pintar()
    }
}
