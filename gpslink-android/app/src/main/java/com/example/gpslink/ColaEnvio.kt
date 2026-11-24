package com.example.gpslink

import java.io.File

// Messages for the server that could not be sent (no internet), kept in order in a
// file so they survive the app being closed. They go out when internet comes back,
// with their original timestamp; the server already ignores a repeated point
// (ON CONFLICT on device + timestamp), so a resend never duplicates the route.
//
// The server does not confirm UDP, so "sent" here means "the phone had working
// internet when it sent it" (Android's VALIDATED network check).
class ColaEnvio(private val archivo: File, private val maximo: Int) {

    private val lineas = ArrayDeque<String>()

    init {
        try {
            if (archivo.exists()) archivo.readLines().filter { it.isNotBlank() }.forEach { lineas.addLast(it) }
            recortar()
        } catch (e: Exception) {
            lineas.clear()
        }
    }

    val tamano: Int @Synchronized get() = lineas.size

    @Synchronized
    fun agregar(linea: String) {
        val limpia = linea.trim()
        if (limpia.isEmpty()) return
        lineas.addLast(limpia)
        if (recortar()) guardarTodo() else try {
            archivo.appendText(limpia + "\n")
        } catch (e: Exception) { }
    }

    // Removes and returns up to n lines from the front (oldest first).
    @Synchronized
    fun sacar(n: Int): List<String> {
        if (lineas.isEmpty()) return emptyList()
        val lote = ArrayList<String>(minOf(n, lineas.size))
        while (lote.size < n && lineas.isNotEmpty()) lote.add(lineas.removeFirst())
        guardarTodo()
        return lote
    }

    // Puts lines back at the front (sending failed again), keeping their order.
    @Synchronized
    fun devolver(lote: List<String>) {
        for (i in lote.indices.reversed()) lineas.addFirst(lote[i])
        recortar()
        guardarTodo()
    }

    // Keeps the newest `maximo` lines. Returns true if something was dropped.
    private fun recortar(): Boolean {
        var quitadas = false
        while (lineas.size > maximo) { lineas.removeFirst(); quitadas = true }
        return quitadas
    }

    private fun guardarTodo() {
        try {
            archivo.writeText(if (lineas.isEmpty()) "" else lineas.joinToString("\n", postfix = "\n"))
        } catch (e: Exception) { }
    }
}
