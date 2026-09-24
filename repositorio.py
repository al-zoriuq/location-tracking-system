"""Data access layer.

Two interchangeable implementations with the same methods:
- RepositorioRDS: the real PostgreSQL (RDS) database, parameterized SQL only.
- RepositorioDemo: deterministic in-memory data (datos_demo.py), for local
  development without touching the shared RDS.

The Flask endpoints only talk to this interface, so the same endpoint code
runs against both.
"""
import os
from contextlib import contextmanager
from datetime import timedelta

from tiempo_bogota import ahora_bogota


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

        conexion = psycopg2.connect(**self.config)
        try:
            with conexion.cursor(cursor_factory=RealDictCursor) as cursor:
                yield cursor
        finally:
            # Always release the connection, even if the query fails
            conexion.close()

    def ultima_ubicacion(self):
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT device_id, ip_origen, latitud, longitud,
                       timestamp_gps, timestamp_recepcion
                FROM ubicaciones
                ORDER BY id DESC
                LIMIT 1
            """)
            return cursor.fetchone()

    def historial(self, horas):
        with self._cursor() as cursor:
            cursor.execute("""
                SELECT ip_origen, latitud, longitud, timestamp_gps
                FROM ubicaciones
                WHERE timestamp_gps >= NOW() - (%s || ' hours')::interval
                ORDER BY timestamp_gps ASC
            """, (horas,))
            return cursor.fetchall()


class RepositorioDemo:
    """Same interface as RepositorioRDS, backed by datos_demo.py."""

    def _puntos(self):
        import datos_demo
        return datos_demo.puntos_demo(ahora_bogota())

    def ultima_ubicacion(self):
        puntos = self._puntos()
        if not puntos:
            return None
        ultimo = max(puntos, key=lambda p: p["id"])  # mirrors ORDER BY id DESC
        campos = ("device_id", "ip_origen", "latitud", "longitud",
                  "timestamp_gps", "timestamp_recepcion")
        return {c: ultimo[c] for c in campos}

    def historial(self, horas):
        corte = ahora_bogota() - timedelta(hours=horas)
        campos = ("ip_origen", "latitud", "longitud", "timestamp_gps")
        return [{c: p[c] for c in campos}
                for p in self._puntos() if p["timestamp_gps"] >= corte]
