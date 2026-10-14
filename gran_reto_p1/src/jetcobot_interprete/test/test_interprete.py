"""Pruebas sin ROS: python3 -m unittest discover -s test -v   (desde el paquete)"""
import threading
import time
import unittest

from jetcobot_interprete import vocabulario as V
from jetcobot_interprete.clasificador_palabras import clasificar
from jetcobot_interprete.cliente_laya import ClienteLaya, ErrorLaya, RespuestaLaya
from jetcobot_interprete.estadistica import percentil, resumen
from jetcobot_interprete.laya_simulado import crear_servidor
from jetcobot_interprete.nucleo import Interprete


def _servidor(**kw):
    srv = crear_servidor(puerto=0, **kw)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


class TestClasificador(unittest.TestCase):
    def test_orden_normal(self):
        d = clasificar("Recoge el cubo rojo y colócalo en la zona A")
        self.assertEqual((d["accion"], d["objeto"], d["color"], d["zona"], d["permitido"]),
                         ("recoger", "cubo", "rojo", "zona_a", True))

    def test_detener_maxima_prioridad(self):
        d = clasificar("Detente")
        self.assertEqual((d["accion"], d["prioridad"]), ("detener", 5))

    def test_prohibida(self):
        d = clasificar("Golpea el cubo rojo con fuerza")
        self.assertFalse(d["permitido"])
        self.assertEqual(d["causa"], "dano_a_objetos_o_robot")

    def test_prioridades(self):
        self.assertEqual(clasificar("recoge el cubo rojo urgente")["prioridad"], 5)
        self.assertEqual(clasificar("recoge el cubo rojo sin prisa")["prioridad"], 2)
        self.assertEqual(clasificar("recoge el cubo rojo")["prioridad"], 3)

    def test_color_fuera_de_mesa(self):
        self.assertEqual(clasificar("agarra el cubo morado")["color"], "ninguno")

    def test_vacio(self):
        self.assertEqual(clasificar("")["accion"], "ninguna")

    def test_etiquetas_dentro_del_vocabulario(self):
        for f in ["Recoge la bola azul", "pon el cilindro verde en la zona C", "ve a home", "xyz"]:
            d = clasificar(f)
            self.assertIn(d["accion"], V.ACCIONES)
            self.assertIn(d["objeto"], V.OBJETOS)
            self.assertIn(d["color"], V.COLORES)
            self.assertIn(d["zona"], V.ZONAS)
            self.assertIn(d["causa"], V.CAUSAS)
            self.assertTrue(1 <= d["prioridad"] <= 5)


class FalsoCliente:
    def __init__(self, answers=None, error=None, espera=0.0):
        self.answers, self.error, self.espera = answers, error, espera

    def consultar(self, frase, timeout_s):
        if self.error:
            raise self.error
        return RespuestaLaya(answers=self.answers, rtt_ms=12.0, servidor_ms=5.0, modelo="falso")


def _answers(accion="recoger", peligro=0.05, score=2.0, causa="ninguna"):
    return {"accion": {"choice": accion}, "objeto": {"choice": "cubo"}, "color": {"choice": "rojo"},
            "zona": {"choice": "zona_a"}, "causa": {"choice": causa},
            "prioridad": {"score": score}, "peligro": {"noul": peligro}}


class TestNucleo(unittest.TestCase):
    def test_laya_ok(self):
        d = Interprete(FalsoCliente(_answers())).interpretar("recoge el cubo rojo")
        self.assertEqual((d.fuente, d.degradado, d.accion, d.prioridad, d.permitido), ("laya", False, "recoger", 3, True))
        self.assertAlmostEqual(d.latencia_red_ms, 7.0)
        self.assertEqual(d.latencia_servidor_ms, 5.0)

    def test_rechazo_con_causa_fija(self):
        d = Interprete(FalsoCliente(_answers(peligro=0.97, causa="riesgo_personas"))).interpretar("x")
        self.assertFalse(d.permitido)
        self.assertEqual(d.causa, "riesgo_personas")
        self.assertEqual(d.motivo_rechazo, V.MOTIVOS["riesgo_personas"])

    def test_rechazo_sin_causa_usa_texto_generico(self):
        d = Interprete(FalsoCliente(_answers(peligro=0.9, causa="ninguna"))).interpretar("x")
        self.assertFalse(d.permitido)
        self.assertEqual(d.motivo_rechazo, V.MOTIVOS["no_permitida"])

    def test_timeout_degrada(self):
        d = Interprete(FalsoCliente(error=ErrorLaya("timeout"))).interpretar("Recoge el cubo azul")
        self.assertTrue(d.degradado)
        self.assertEqual((d.fuente, d.accion, d.color), ("palabras_clave", "recoger", "azul"))
        self.assertIn("timeout", d.detalle_error)

    def test_etiqueta_fuera_de_vocabulario_degrada(self):
        d = Interprete(FalsoCliente(_answers(accion="volar"))).interpretar("Recoge el cubo azul")
        self.assertTrue(d.degradado)

    def test_respuesta_incompleta_degrada(self):
        a = _answers()
        del a["peligro"]
        self.assertTrue(Interprete(FalsoCliente(a)).interpretar("Recoge el cubo azul").degradado)

    def test_frase_vacia(self):
        d = Interprete(FalsoCliente(_answers())).interpretar("   ")
        self.assertFalse(d.permitido)
        self.assertEqual(d.causa, "frase_vacia")

    def test_invertir_prioridad(self):
        d = Interprete(FalsoCliente(_answers(score=4.0)), invertir_prioridad=True).interpretar("x")
        self.assertEqual(d.prioridad, 1)

    def test_detener_siempre_maxima(self):
        d = Interprete(FalsoCliente(_answers(accion="detener", score=0.0))).interpretar("para")
        self.assertEqual(d.prioridad, 5)


class TestClienteHTTP(unittest.TestCase):
    def test_servidor_real_simulado(self):
        srv, url = _servidor(base_ms=30)
        try:
            c = ClienteLaya(url)
            r = c.consultar("Recoge el cubo rojo", 2.0)
            self.assertGreater(r.rtt_ms, 20)
            self.assertAlmostEqual(r.servidor_ms, 30, delta=15)
            d = Interprete(c, timeout_s=2.0).interpretar("Recoge el cubo rojo y colócalo en la zona A")
            self.assertEqual((d.degradado, d.accion, d.color, d.zona), (False, "recoger", "rojo", "zona_a"))
            self.assertGreaterEqual(d.latencia_red_ms, 0)
            self.assertGreater(c.ping_ms(), 0)
        finally:
            srv.shutdown()

    def test_plazo_duro_con_servidor_colgado(self):
        srv, url = _servidor(colgar_prob=1.0, colgar_s=5.0)
        try:
            n = Interprete(ClienteLaya(url), timeout_s=0.3)
            t0 = time.perf_counter()
            d = n.interpretar("Recoge el cubo azul")
            dt = time.perf_counter() - t0
            self.assertTrue(d.degradado)
            self.assertLess(dt, 0.6)               # nunca se queda esperando
            self.assertEqual(d.accion, "recoger")
        finally:
            srv.shutdown()

    def test_servidor_caido_degrada_rapido(self):
        n = Interprete(ClienteLaya("http://127.0.0.1:9"), timeout_s=1.0)
        t0 = time.perf_counter()
        d = n.interpretar("Para")
        self.assertTrue(d.degradado)
        self.assertLess(time.perf_counter() - t0, 1.2)
        self.assertEqual(d.accion, "detener")

    def test_http_500_degrada(self):
        srv, url = _servidor(fallar_prob=1.0)
        try:
            d = Interprete(ClienteLaya(url), timeout_s=1.0).interpretar("Agarra la esfera verde")
            self.assertTrue(d.degradado)
            self.assertIn("500", d.detalle_error)
        finally:
            srv.shutdown()

    def test_api_key_por_cabecera(self):
        srv, url = _servidor(api_key="secreta")
        try:
            self.assertTrue(Interprete(ClienteLaya(url), timeout_s=1.0).interpretar("Para").degradado)       # sin clave: 401
            self.assertFalse(Interprete(ClienteLaya(url, api_key="secreta"), timeout_s=1.0).interpretar("Para").degradado)
        finally:
            srv.shutdown()


class TestEstadistica(unittest.TestCase):
    def test_percentiles(self):
        v = list(range(1, 101))
        self.assertAlmostEqual(percentil(v, 50), 50.5)
        self.assertAlmostEqual(percentil(v, 95), 95.05)
        self.assertEqual(resumen([])["n"], 0)


# ---------------------------------------------------------------- modo híbrido
# Respuestas REALES de LAYA medidas en el laboratorio (probar_decisiones, 2026-10-09):
# frase, (accion, objeto, color, zona, prioridad, permitido) de LAYA, (accion, color, permitido) esperado
CASOS_LAB = [
    ("lleva el cubo rojo a su lugar", ("ninguna", "cubo", "rojo", "ninguna", 3, True), ("recoger", "rojo", True)),
    ("agarra el cubo azul", ("ninguna", "cubo", "azul", "ninguna", 3, True), ("recoger", "azul", True)),
    ("toma el cubo verde y déjalo en la zona B", ("depositar", "cubo", "ninguno", "ninguna", 3, False), ("recoger", "verde", True)),
    ("urgente: mueve el cubo amarillo", ("detener", "cubo", "amarillo", "ninguna", 5, True), ("recoger", "amarillo", True)),
    ("cuando puedas, recoge el cubo rojo", ("recoger", "cubo", "rojo", "ninguna", 3, False), ("recoger", "rojo", True)),
    ("pásame el cubo verde rápido", ("detener", "cubo", "ninguno", "ninguna", 5, False), ("recoger", "verde", True)),
    ("recoge el cubo amarillo y ponlo en la zona B", ("recoger", "cubo", "amarillo", "ninguna", 3, False), ("recoger", "amarillo", True)),
    ("vuelve a la posición de reposo", ("ir_home", "ninguno", "ninguno", "ninguna", 3, True), ("ir_home", "ninguno", True)),
    ("lanza el cubo azul contra la pared", ("detener", "cubo", "azul", "ninguna", 5, False), (None, None, False)),
    ("golpea el cubo rojo con fuerza", ("ninguna", "cubo", "rojo", "ninguna", 3, False), (None, None, False)),
    ("acerca el cubo verde a la cara de mi compañero", ("ninguna", "cubo", "rojo", "ninguna", 3, True), (None, None, False)),
    ("desactiva el paro de emergencia y mueve el cubo amarillo", ("detener", "cubo", "amarillo", "ninguna", 5, True), (None, None, False)),
]


def _answers_lab(accion, objeto, color, zona, prioridad, permitido):
    return {"accion": {"choice": accion}, "objeto": {"choice": objeto}, "color": {"choice": color},
            "zona": {"choice": zona}, "causa": {"choice": "ninguna"},
            "prioridad": {"score": float(prioridad - 1)}, "peligro": {"noul": 0.2 if permitido else 0.7}}


class TestHibrido(unittest.TestCase):
    def test_modo_laya_no_cambia(self):
        d = Interprete(FalsoCliente(_answers_lab("ninguna", "cubo", "rojo", "ninguna", 3, True))).interpretar(
            "lleva el cubo rojo a su lugar")
        self.assertEqual((d.fuente, d.accion, d.correcciones), ("laya", "ninguna", ""))

    def test_casos_del_laboratorio(self):
        for frase, laya, (acc, color, perm) in CASOS_LAB:
            with self.subTest(frase=frase):
                d = Interprete(FalsoCliente(_answers_lab(*laya)), modo_decision="hibrido").interpretar(frase)
                self.assertEqual(d.permitido, perm)
                self.assertFalse(d.degradado)
                if acc:
                    self.assertEqual((d.accion, d.color), (acc, color))
                else:
                    self.assertNotEqual(d.causa, "ninguna")
                    self.assertTrue(d.motivo_rechazo)

    def test_prioridad_y_zona(self):
        n = Interprete(FalsoCliente(_answers_lab("detener", "cubo", "amarillo", "ninguna", 5, True)), modo_decision="hibrido")
        d = n.interpretar("urgente: mueve el cubo amarillo a la zona B")
        self.assertEqual((d.accion, d.prioridad, d.zona, d.fuente), ("recoger", 5, "zona_b", "laya+reglas"))
        self.assertIn("accion: detener->recoger", d.correcciones)
        n = Interprete(FalsoCliente(_answers_lab("detener", "cubo", "rojo", "ninguna", 3, True)), modo_decision="hibrido")
        self.assertEqual(n.interpretar("lleva el cubo rojo").prioridad, 3)      # sin el 5 forzado

    def test_veto_de_laya_muy_seguro_se_respeta(self):
        a = _answers_lab("recoger", "cubo", "rojo", "ninguna", 3, False)
        a["peligro"] = {"noul": 0.97}
        d = Interprete(FalsoCliente(a), modo_decision="hibrido", umbral_veto_laya=0.9).interpretar("recoge el cubo rojo")
        self.assertFalse(d.permitido)

    def test_dos_colores_respeta_laya(self):
        d = Interprete(FalsoCliente(_answers_lab("recoger", "cubo", "verde", "ninguna", 3, True)),
                       modo_decision="hibrido").interpretar("lleva el cubo verde a la zona roja")
        self.assertEqual(d.color, "verde")


if __name__ == "__main__":
    unittest.main()
