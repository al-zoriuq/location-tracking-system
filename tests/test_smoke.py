import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import servidorweb


def test_app_existe():
    assert servidorweb.app is not None


def test_ruta_api_registrada():
    rutas = [str(regla) for regla in servidorweb.app.url_map.iter_rules()]
    assert any("api/ultima-ubicacion" in ruta for ruta in rutas)
