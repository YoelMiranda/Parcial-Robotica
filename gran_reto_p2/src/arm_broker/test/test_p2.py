"""Pruebas SIN ROS de la Pregunta 2.

  cd ~/gran_reto_p2/src/arm_broker && python3 -m unittest discover -s test -v
"""
import math
import os
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from arm_broker import fk, ik  # noqa: E402
from arm_broker.brazo import BrazoSimulado, ParadaSolicitada  # noqa: E402
from arm_broker.CamaraColoresReconocimiento import CamaraSimulada, localizar_simulado  # noqa: E402
from arm_broker.evidencia import Evidencia  # noqa: E402
from arm_broker.nucleo_p2 import ConfigMesa, EjecutorAgarre, ErrorAgarre, admitir_agarre  # noqa: E402
from arm_broker.planificador_moveit import ErrorPlanificacion, interpolar  # noqa: E402
from arm_broker.politicas import SegundaPolitica  # noqa: E402


def goal(**kw):
    base = dict(accion='recoger', objeto='cubo', color='rojo', zona='ninguna', permitido=True,
                causa='ninguna', motivo_rechazo='', priority=3)
    base.update(kw)
    return SimpleNamespace(**base)


def q_observacion():
    p = (210.0, 5.0, 240.0)
    s = ik.semilla_natural(p)
    return ik.resolver(p, ik.yaw_herramienta(s), [s], simetria_deg=0)['q']


class TestIK(unittest.TestCase):
    def test_numpy_igual_a_fk_rb2(self):
        q = [0.3, -0.2, -1.1, 0.5, 0.2, 1.0]
        T = ik.matriz(q)
        self.assertAlmostEqual(math.dist(T[:3, 3], fk.fk(q)), 0.0, places=6)

    def test_toda_la_mesa_tiene_ik(self):
        m = ConfigMesa()
        q0 = q_observacion()
        yaw = ik.yaw_herramienta(q0)
        for xy in list(m.posiciones_pick.values()) + list(m.destinos.values()):
            for z in (m.z_agarre, m.z_seguro, m.z_soltar):
                r = ik.resolver((xy[0], xy[1], z), yaw, [q0])
                self.assertTrue(r['ok'], (xy, z, r['motivo']))
                self.assertLess(math.dist(fk.fk(r['q']), (xy[0], xy[1], z)), 2.0)
                self.assertLess(ik.inclinacion_deg(r['q']), 3.0)

    def test_fuera_de_alcance(self):
        r = ik.resolver((600, 0, 100), 0.0, [q_observacion()])
        self.assertFalse(r['ok'])


class TestAdmision(unittest.TestCase):
    def setUp(self):
        self.m = ConfigMesa()

    def test_ok_mismo_color(self):
        ok, mot, dest, _ = admitir_agarre(goal(), self.m)
        self.assertTrue(ok, mot)
        self.assertEqual(dest, 'rojo')

    def test_no_permitida_con_causa(self):
        ok, mot, _, _ = admitir_agarre(goal(permitido=False, causa='dano_a_objetos_o_robot',
                                            motivo_rechazo='Rechazada: la orden dañaría objetos o al robot.'), self.m)
        self.assertFalse(ok)
        self.assertIn('NO PERMITIDA', mot)
        self.assertIn('dano_a_objetos_o_robot', mot)

    def test_objeto_ausente(self):
        ok, mot, _, _ = admitir_agarre(goal(objeto='esfera'), self.m)
        self.assertFalse(ok)
        self.assertIn('no está sobre la mesa', mot)

    def test_color_desconocido(self):
        ok, mot, _, _ = admitir_agarre(goal(color='ninguno'), self.m)
        self.assertFalse(ok)

    def test_zona_b_es_azul_y_zona_a_no_existe(self):
        self.assertEqual(admitir_agarre(goal(zona='zona_b'), self.m)[2], 'azul')
        ok, mot, _, _ = admitir_agarre(goal(zona='zona_a'), self.m)
        self.assertFalse(ok)
        self.assertIn('ZONA A', mot)

    def test_sin_objeto_pero_con_color(self):
        ok, _, dest, _ = admitir_agarre(goal(objeto='ninguno', color='verde'), self.m)
        self.assertTrue(ok)
        self.assertEqual(dest, 'verde')

    def test_charla_y_home(self):
        self.assertFalse(admitir_agarre(goal(accion='ninguna'), self.m)[0])
        self.assertEqual(admitir_agarre(goal(accion='ir_home'), self.m)[2], 'reposo')

    def test_rechazar_sin_zona(self):
        self.m.destino_si_falta = 'rechazar'
        self.assertFalse(admitir_agarre(goal(), self.m)[0])


class TestPolitica(unittest.TestCase):
    def test_mayor_prioridad_primero(self):
        p = SegundaPolitica(8.0)
        mk = lambda pr, t: SimpleNamespace(priority=pr, espera_s=t, t_llegada=-t)  # noqa: E731
        pend = [mk(2, 1.0), mk(5, 0.1), mk(3, 2.0)]
        self.assertEqual(p.siguiente(pend), 1)


class TestEjecutor(unittest.TestCase):
    def _ejecutor(self, ausentes=(), falla_moveit=False, exigir=False):
        m = ConfigMesa(t_pinza_s=0.01, exigir_moveit=exigir)
        q0 = q_observacion()
        brazo = BrazoSimulado(q_inicial=q0, velocidad=100)
        brazo.vel_rad_s = 20.0          # prueba rápida
        cam = CamaraSimulada(m.posiciones_pick, ausentes)

        def plan(a, b):
            if falla_moveit:
                raise ErrorPlanificacion('sin move_group')
            return interpolar(a, b, pasos=20)

        return EjecutorAgarre(brazo, m, q0, ik.yaw_herramienta(q0), plan,
                              lambda c, img=None: localizar_simulado(cam, c), parada=None, log=lambda *_: None)

    def test_agarre_completo(self):
        e = self._ejecutor()
        r = e.ejecutar_agarre('amarillo', 'verde')
        self.assertEqual(r['destino'], 'verde')
        self.assertEqual(r['planificador'], 'moveit')
        self.assertGreaterEqual(r['error_fk_mm'], 0.0)
        self.assertLess(r['error_fk_mm'], 15.0)
        for k in ('t_percepcion_s', 't_ik_s', 't_planificacion_s', 't_movimiento_s'):
            self.assertGreater(r[k], 0.0, k)
        self.assertTrue(e.esta_en_reposo(e.brazo.leer_angulos()))

    def test_color_no_visible_aborta_con_causa(self):
        e = self._ejecutor(ausentes=('verde',))
        with self.assertRaises(ErrorAgarre) as cm:
            e.ejecutar_agarre('verde', 'verde')
        self.assertIn('no encontró', str(cm.exception))

    def test_sin_moveit_interpola(self):
        r = self._ejecutor(falla_moveit=True).ejecutar_agarre('rojo', 'rojo')
        self.assertEqual(r['planificador'], 'interpolacion')

    def test_exigir_moveit(self):
        with self.assertRaises(ErrorAgarre):
            self._ejecutor(falla_moveit=True, exigir=True).ejecutar_agarre('rojo', 'rojo')

    def test_parada(self):
        e = self._ejecutor()
        ev = threading.Event()
        ev.set()
        e.parada = ev
        with self.assertRaises(ParadaSolicitada):
            e.ejecutar_agarre('azul', 'azul')

    def test_slot_mas_cercano(self):
        e = self._ejecutor()
        xy, metodo = e.posicion_pick('rojo', {'xy_mm': (262.0, 50.0)})   # rojo puesto donde iba el azul
        self.assertEqual(xy, e.mesa.posiciones_pick['azul'])
        self.assertIn('slot_azul', metodo)
        with self.assertRaises(ErrorAgarre):
            e.posicion_pick('rojo', {'xy_mm': (220.0, 5.0)})              # en el centro: ninguna posición


class TestEvidencia(unittest.TestCase):
    def test_csv(self):
        with tempfile.TemporaryDirectory() as d:
            ev = Evidencia(d)
            self.assertEqual(ev.intento({'client_id': 'a', 'pos_fk_mm': [1.0, 2.0, 3.0]}), 1)
            self.assertEqual(ev.intento({'client_id': 'b'}), 2)
            self.assertEqual(Evidencia(d).n_intento, 2)


if __name__ == '__main__':
    unittest.main()
