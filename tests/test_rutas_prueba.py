import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pruebas"))

import insertar_rutas_prueba as ins


class CursorFalso:
    def __init__(self):
        self.ejecutadas = []
        self.rowcount = 1

    def execute(self, sql, params=None):
        self.ejecutadas.append((sql, params))

    def close(self):
        pass


class ConexionFalsa:
    def __init__(self):
        self.cursor_falso = CursorFalso()
        self.commits = 0
        self.cerrada = False

    def cursor(self):
        return self.cursor_falso

    def commit(self):
        self.commits += 1

    def rollback(self):
        pass

    def close(self):
        self.cerrada = True


@pytest.fixture
def bd_de_pruebas(monkeypatch):
    monkeypatch.setattr(ins, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("rdsdbname", "locationtracker_test")
    con = ConexionFalsa()
    monkeypatch.setattr(ins, "conectar", lambda: con)
    monkeypatch.setattr(sys, "argv", ["insertar_rutas_prueba.py", "--si"])
    return con


def test_candado_rechaza_la_base_de_produccion(monkeypatch):
    monkeypatch.setattr(ins, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("rdsdbname", "p2database")

    def prohibido():
        raise AssertionError("no debe conectarse a la base de produccion")
    monkeypatch.setattr(ins, "conectar", prohibido)
    monkeypatch.setattr(sys, "argv", ["insertar_rutas_prueba.py", "--si"])

    with pytest.raises(SystemExit) as salida:
        ins.main()
    assert "ABORTADO" in str(salida.value)


def test_candado_rechaza_base_sin_definir(monkeypatch):
    monkeypatch.setattr(ins, "load_dotenv", lambda *a, **k: None)
    monkeypatch.delenv("rdsdbname", raising=False)
    monkeypatch.setattr(sys, "argv", ["insertar_rutas_prueba.py", "--si"])
    with pytest.raises(SystemExit):
        ins.main()


def test_dry_run_no_se_conecta(monkeypatch, capsys):
    monkeypatch.setattr(ins, "load_dotenv", lambda *a, **k: None)
    monkeypatch.setenv("rdsdbname", "locationtracker_test")

    def prohibido():
        raise AssertionError("dry-run no debe conectarse")
    monkeypatch.setattr(ins, "conectar", prohibido)
    monkeypatch.setattr(sys, "argv", ["insertar_rutas_prueba.py", "--dry-run"])

    ins.main()
    assert "dry-run" in capsys.readouterr().out


def test_inserta_todas_las_lecturas_como_el_sniffer(bd_de_pruebas):
    ins.main()

    ejecutadas = bd_de_pruebas.cursor_falso.ejecutadas
    assert len(ejecutadas) == 942
    sql, params = ejecutadas[0]
    assert "ON CONFLICT (device_id, timestamp_gps) DO NOTHING" in sql
    device, ip, lat, lon, ts_gps, ts_recepcion = params
    assert device == "device-prueba-001"
    # naive datetime (Bogota wall-clock), exactly what the sniffer stores
    assert ts_gps.tzinfo is None and ts_gps == ts_recepcion
    assert bd_de_pruebas.commits == 1 and bd_de_pruebas.cerrada


def test_borrar_solo_toca_el_device_indicado(bd_de_pruebas, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["insertar_rutas_prueba.py", "--borrar", "--si", "--device", "abc"])
    ins.main()

    ejecutadas = bd_de_pruebas.cursor_falso.ejecutadas
    assert ejecutadas == [(ins.SQL_BORRAR, ("abc",))]
    assert bd_de_pruebas.commits == 1


def test_todas_las_fechas_son_pasadas():
    from datetime import datetime
    from enviar_rutas_prueba import BOGOTA, construir_lecturas
    ahora = datetime.now(BOGOTA)
    lecturas, _ = construir_lecturas()
    assert all(fecha < ahora for fecha, _, _ in lecturas)
