package com.example.gpslink

import android.Manifest
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.os.Build
import android.os.Bundle
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.PopupMenu
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat

class MainActivity : AppCompatActivity() {

    private val PREFS_NAME = "LocationSmsPrefs"
    private val KEY_SERVIDOR = "servidor_predeterminado"

    private lateinit var tvServidorActual: TextView
    private lateinit var etServidor: EditText
    private lateinit var btnGuardarServidor: Button
    private lateinit var btnMenuOculto: Button
    private lateinit var tvEstado: TextView

    // Receives live status updates broadcast by UbicacionService, so the
    // screen shows something useful if the app happens to be open — but the
    // service itself does NOT depend on this Activity existing at all.
    private val estadoReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) {
            tvEstado.text = intent.getStringExtra(UbicacionService.EXTRA_ESTADO) ?: ""
        }
    }

    // --- Sequential permission chain: location -> notifications -> background ---
    // Android requires these as SEPARATE requests, in this order, never combined.

    private val permisoFondoLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ -> iniciarServicio() } // proceed either way; background just improves reliability

    private val permisoNotifLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { _ -> pedirPermisoFondoSiHaceFalta() }

    private val permisoUbicacionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (granted) {
            pedirPermisoNotifSiHaceFalta()
        } else {
            tvEstado.text = "Se necesita el permiso de ubicación"
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        tvServidorActual = findViewById(R.id.tvServidorActual)
        etServidor = findViewById(R.id.etServidor)
        btnGuardarServidor = findViewById(R.id.btnGuardarServidor)
        btnMenuOculto = findViewById(R.id.btnMenuOculto)
        tvEstado = findViewById(R.id.tvEstado)

        mostrarServidorGuardado()

        btnGuardarServidor.setOnClickListener { guardarServidor() }
        btnMenuOculto.setOnClickListener { mostrarMenuOculto(it) }

        pedirPermisosYArrancar()
    }

    override fun onStart() {
        super.onStart()
        ContextCompat.registerReceiver(
            this, estadoReceiver, IntentFilter(UbicacionService.ACCION_ESTADO),
            ContextCompat.RECEIVER_NOT_EXPORTED
        )
    }

    override fun onStop() {
        super.onStop()
        unregisterReceiver(estadoReceiver)
    }

    // --- Permission chain ---

    private fun pedirPermisosYArrancar() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.ACCESS_FINE_LOCATION)
            == PackageManager.PERMISSION_GRANTED
        ) {
            pedirPermisoNotifSiHaceFalta()
        } else {
            permisoUbicacionLauncher.launch(Manifest.permission.ACCESS_FINE_LOCATION)
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
            iniciarServicio()
        }
    }

    private fun iniciarServicio() {
        val intent = Intent(this, UbicacionService::class.java)
        ContextCompat.startForegroundService(this, intent)
    }

    // --- Hidden manual-send menu (3-dot icon) ---

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

    // --- Saved IP(s) ---

    private fun mostrarServidorGuardado() {
        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        val servidor = prefs.getString(KEY_SERVIDOR, null)
        tvServidorActual.text = if (servidor != null) {
            "IP(s) predeterminada(s): $servidor  (puerto 5000)"
        } else {
            getString(R.string.servidor_no_definido)
        }
    }

    private fun guardarServidor() {
        val texto = etServidor.text.toString().trim()
        val ips = texto.split(";").map { it.trim() }.filter { it.isNotEmpty() }

        if (ips.isEmpty()) {
            Toast.makeText(this, "Ingresa al menos una IP", Toast.LENGTH_SHORT).show()
            return
        }

        val prefs = getSharedPreferences(PREFS_NAME, MODE_PRIVATE)
        prefs.edit().putString(KEY_SERVIDOR, texto).apply()
        mostrarServidorGuardado()
        etServidor.text.clear()
        Toast.makeText(this, "IP(s) guardada(s)", Toast.LENGTH_SHORT).show()
    }
}
