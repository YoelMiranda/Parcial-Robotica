"""Pruebas SIN ROS:  cd src/jetcobot_voz && python3 -m unittest discover -s test -v"""
import csv
import os
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from jetcobot_voz import desglose_voz, gemini_stt, tabla_ordenes   # noqa: E402


class TestNube(unittest.TestCase):
    def test_sin_clave(self):
        os.environ.pop('X_CLAVE_INEXISTENTE', None)
        with self.assertRaises(gemini_stt.ErrorTranscripcion) as c:
            gemini_stt.leer_clave('X_CLAVE_INEXISTENTE')
        self.assertEqual(c.exception.motivo, 'sin_clave')

    def test_plazo_duro(self):
        original = gemini_stt._llamar
        gemini_stt._llamar = lambda *a, **k: time.sleep(3) or 'tarde'
        try:
            t0 = time.time()
            with self.assertRaises(gemini_stt.ErrorTranscripcion) as c:
                gemini_stt.transcribir(b'x', 'audio/wav', 'k', 'm', 0.3)
            self.assertEqual(c.exception.motivo, 'timeout')
            self.assertLess(time.time() - t0, 1.0)
        finally:
            gemini_stt._llamar = original

    def test_cuerpo_http_sin_pensar_y_clave_en_cabecera(self):
        from unittest import mock
        cap = {}

        class R:
            status_code, text = 200, ''

            def json(self):
                return {'candidates': [{'content': {'parts': [{'text': ' hola '}]}}]}

        def post(url, headers=None, json=None, timeout=None):
            cap.update(url=url, h=headers, j=json)
            return R()
        with mock.patch('requests.post', post):
            self.assertEqual(gemini_stt.transcribir(b'x', 'audio/wav', 'CLAVE', 'gemini-2.5-flash', 5), 'hola')
        self.assertNotIn('CLAVE', cap['url'])
        self.assertEqual(cap['h']['x-goog-api-key'], 'CLAVE')
        self.assertEqual(cap['j']['generationConfig']['thinkingConfig']['thinkingBudget'], 0)

    def test_no_hay_clave_en_el_codigo(self):
        base = os.path.join(os.path.dirname(__file__), '..', 'jetcobot_voz')
        for n in os.listdir(base):
            if n.endswith('.py'):
                self.assertNotIn('AIza', open(os.path.join(base, n), encoding='utf-8').read())


class TestDesglose(unittest.TestCase):
    def _datos(self):
        t0 = 1000.0
        reg = [{'orden_id': 'o1', 'modo': 'voz', 'pedido_id': 'p1', 'transcripcion': 'toma el cubo rojo',
                't_origen_epoch': t0, 't_captura_ms': '1050', 't_transcripcion_ms': '1500',
                't_ini_envio_epoch': t0 + 2.6},
               {'orden_id': 'o2', 'modo': 'texto', 'pedido_id': 'p2'},
               {'orden_id': 'o3', 'modo': 'voz', 'pedido_id': 'p3'}]       # p3 rechazada: sin intento
        it = [{'pedido_id': 'p1', 't_envio_epoch': t0 + 2.9, 't_espera_s': 0.5, 't_preparacion_s': 0.0,
               't_percepcion_s': 0.5, 't_ik_s': 0.3, 't_planificacion_s': 0.2,
               'inicio_movimiento_epoch': t0 + 2.9 + 0.005 + 0.5 + 0.5 + 0.3 + 0.2}]
        return reg, it

    def test_etapas_y_total(self):
        reg, it = self._datos()
        filas = desglose_voz.calcular(reg, it, avisar=lambda *_: None)
        self.assertEqual(len(filas), 1)
        f = filas[0]
        self.assertAlmostEqual(f['captura'], 1.05)
        self.assertAlmostEqual(f['transcripcion'], 1.5)
        self.assertAlmostEqual(f['decision'], 0.3, places=3)
        self.assertAlmostEqual(f['total'], 4.405, places=3)
        suma = sum(f[e] for e in desglose_voz.ETAPAS) + f['sin_atribuir']
        self.assertAlmostEqual(suma, f['total'], places=6)

    def test_dominante(self):
        reg, it = self._datos()
        med = desglose_voz.resumir(desglose_voz.calcular(reg, it, avisar=lambda *_: None))
        self.assertIn('Transcripcion', desglose_voz.analisis_texto(med)[0])


class TestTabla(unittest.TestCase):
    def test_marcar(self):
        with tempfile.TemporaryDirectory() as d:
            ruta = os.path.join(d, 'r.csv')
            with open(ruta, 'w', newline='', encoding='utf-8') as f:
                w = csv.DictWriter(f, fieldnames=['orden_id', 'transcripcion', 'dicho_real', 'resultado_esperado', 'correcta'])
                w.writeheader()
                w.writerow({'orden_id': 'o1', 'transcripcion': 'hola'})
            self.assertEqual(tabla_ordenes.main([ruta, '--marcar', '1', '--dicho', 'hola', '--correcta', 'si']), 0)
            self.assertEqual(tabla_ordenes.leer(ruta)[0]['correcta'], 'si')


if __name__ == '__main__':
    unittest.main()
