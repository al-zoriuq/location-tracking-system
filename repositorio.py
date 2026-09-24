"""Data access layer.

Two interchangeable implementations with the same methods:
- RepositorioRDS: the real PostgreSQL (RDS) database, parameterized SQL only.
- RepositorioDemo: deterministic in-memory data (datos_demo.py), for local
  development without touching the shared RDS.

The Flask endpoints only talk to this interface, so the same endpoint code
runs against both.

All datetimes going in and out are naive Bogota wall-clock time, the same
convention as the timestamp_gps column.
"""
import os
from contextlib import contextmanager
from datetime import timedelta

from tiempo_bogota import ahora_bogota


class ErrorBaseDatos(Exception):
    """The database could not be queried (the API answers HTTP 503)."""


def modo_demo_activo():
    return os.getenv("MODO_DEMO", "").strip() == "1"


def crear_repositorio():
    """Picks the implementation from the MODO_DEMO environment variable."""
    if modo_demo_activo():
        return RepositorioDemo()
    return RepositorioRDS()


class RepositorioRDS:
    """Reads from the shared RDS PostgreSQL. Read-only: never writes."""

    def __init__(self):
        self.config = {
            "host": os.getenv("rdshost"),
            "port": 5432,
            "database": os.getenv("rdsdbname"),
            "user": os.getenv("rdsuser"),
            "password": os.getenv("rdspass"),
            "sslmode": "verify-full",
            "sslrootcert": "./global-bundle.pem",
        }

    @contextmanager
    def _cursor(self):
        # Imported here so demo mode never needs psycopg2 or the certificate
        import psycopg2
        from psycopg2.extras import RealDictCursor

        try:
            conexion = psycopg2.connect(**self.config)
        except psycopg2.Error as error:
            raise ErrorBaseDatos(str(error)) from error
        try:
            with conexion.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
        except psycopg2.Error as error:
            raise ErrorBaseDatos(str(error)) from error
        finally:
            # Always release the connection, even if the query fails
            conexion.close()

    def ultimo_device_id(self):
        """Device of the most recent GPS point (by GPS time, not arrival order)."""
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT device_id
                FROM ubicaciones
                ORDER BY timestamp_gps DESC
                LIMIT 1
            """)
            fila = cursor.fetchone()
            return fila["device_id"] if fila else None

    def ultima_ubicacion(self, device_id):
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT device_id, ip_origen, latitud, longitud,
                       timestamp_gps, timestamp_recepcion
                FROM ubicaciones
                WHERE device_id = %s
                ORDER BY timestamp_gps DESC
                LIMIT 1
            """, (device_id,))
            return cursor.fetchone()

    def historial(self, device_id, desde=None, hasta=None, horas=24):
        """Points of one device, oldest first.

        With desde/hasta: that closed range. Without: the last 'horas' hours,
        where "now" is Bogota wall-clock time computed by PostgreSQL itself.
        """
        with self._cursor() as cursor:
            if desde is not None:
                cursor.execute("""
                    SELECT device_id, ip_origen, latitud, longitud, timestamp_gps
                    FROM ubicaciones
                    WHERE device_id = %s
                      AND timestamp_gps BETWEEN %s AND %s
                    ORDER BY timestamp_gps ASC
                """, (device_id, desde, hasta))
            else:
                # NOW() is a timestamptz; AT TIME ZONE turns it into Bogota
                # wall-clock time without zone, the same type as timestamp_gps.
                cursor.execute("""
                    SELECT device_id, ip_origen, latitud, longitud, timestamp_gps
                    FROM ubicaciones
                    WHERE device_id = %s
                      AND timestamp_gps >= (NOW() AT TIME ZONE 'America/Bogota')
                                           - make_interval(hours => %s)
                    ORDER BY timestamp_gps ASC
                """, (device_id, horas))
            return cursor.fetchall()


class RepositorioDemo:
    """Same interface as RepositorioRDS, backed by datos_demo.py."""

    def _puntos(self):
        import datos_demo
        return datos_demo.puntos_demo(ahora_bogota())

    def ultimo_device_id(self):
        puntos = self._puntos()
        if not puntos:
            return None
        return max(puntos, key=lambda p: p["timestamp_gps"])["device_id"]

    def ultima_ubicacion(self, device_id):
        puntos = [p for p in self._puntos() if p["device_id"] == device_id]
        if not puntos:
            return None
        ultimo = max(puntos, key=lambda p: p["timestamp_gps"])
        campos = ("device_id", "ip_origen", "latitud", "longitud",
                  "timestamp_gps", "timestamp_recepcion")
        return {c: ultimo[c] for c in campos}

    def historial(self, device_id, desde=None, hasta=None, horas=24):
        if desde is None:
            desde, hasta = ahora_bogota() - timedelta(hours=horas), None
        campos = ("device_id", "ip_origen", "latitud", "longitud", "timestamp_gps")
        return [
            {c: p[c] for c in campos}
            for p in self._puntos()
            if p["device_id"] == device_id
            and p["timestamp_gps"] >= desde
            and (hasta is None or p["timestamp_gps"] <= hasta)
        ]
