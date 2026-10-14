#!/usr/bin/env python3
"""SIMULADOR del servidor LAYA — SOLO PARA DESARROLLO Y PRUEBAS.

Imita POST /v1/systemone y GET /health (mismo formato y cabecera
X-Inference-Time-Ms) para probar el nodo sin el servidor del laboratorio.
Sus "decisiones" salen de reglas, no de un modelo: JAMÁS usarlo como evidencia
del examen. Permite simular carga (--paralelo), fallos y cuelgues.

  python3 -m jetcobot_interprete.laya_simulado --puerto 8000 --base-ms 35
  python3 -m jetcobot_interprete.laya_simulado --colgar-prob 0.2     # simula timeouts
"""
import argparse
import hashlib
import json
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .clasificador_palabras import clasificar, normalizar


def _decidir(frase):
    """Reglas del 'modelo' simulado: palabras clave + algo más de comprensión."""
    d = clasificar(frase)
    t = normalizar(frase)
    if d["accion"] == "ninguna" and d["permitido"] and (d["color"] != "ninguno" or d["objeto"] != "ninguno"):
        if not any(n in t.split() for n in ("no", "nunca")):
            d["accion"] = "recoger"                    # "necesito la pelota", "cubo azul zona b"
    if "quedate quieto" in t or "quieto" in t.split():
        d["accion"], d["prioridad"] = "detener", 5
    # error determinista ~8 % para que la tabla de exactitud no sea perfecta
    h = int(hashlib.md5(frase.encode()).hexdigest(), 16)
    if h % 100 < 8 and d["accion"] == "recoger":
        d["color"] = "ninguno"
    return d


def _responder_pregunta(qid, q, d):
    tipo = q.get("type")
    if tipo == "choice":
        etiqueta = d.get(qid, "ninguna")
        if etiqueta not in q["criteria"]:
            etiqueta = next(iter(q["criteria"]))
        return {"choice": etiqueta, "confidence": 0.8, "answer_confidence": 0.9}
    if tipo == "score":
        return {"score": float(d["prioridad"] - 1) + random.uniform(-0.3, 0.3), "confidence": 0.7}
    if tipo == "noul":
        return {"noul": 0.93 if not d["permitido"] else 0.04}
    return {}


class Handler(BaseHTTPRequestHandler):
    cfg = None
    gpu = None

    def log_message(self, *a):
        pass

    def _json(self, codigo, obj, extra=None):
        cuerpo = json.dumps(obj).encode()
        self.send_response(codigo)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        if self.path == "/health":
            return self._json(200, {"status": "ok"})
        self._json(404, {"detail": "no existe"})

    def do_POST(self):
        c = self.cfg
        if self.path != "/v1/systemone":
            return self._json(404, {"detail": "no existe"})
        if c.api_key and self.headers.get("Authorization") != "Bearer " + c.api_key:
            return self._json(401, {"detail": "invalid or missing bearer token"})
        try:
            n = int(self.headers.get("Content-Length", 0))
            req = json.loads(self.rfile.read(n))
            frase = req["state"] if isinstance(req["state"], str) else req["state"]["body"]
            preguntas = req["questions"]
        except (ValueError, KeyError, TypeError):
            return self._json(400, {"detail": "cuerpo inválido"})
        if random.random() < c.colgar_prob:
            time.sleep(c.colgar_s)
        if random.random() < c.fallar_prob:
            return self._json(500, {"detail": "inference failed"})
        with self.gpu:                       # la GPU atiende de a `paralelo` pedidos: cola bajo carga
            t = max(1.0, random.gauss(c.base_ms, c.base_ms * 0.15))
            time.sleep(t / 1000.0)
        d = _decidir(frase)
        answers = {qid: _responder_pregunta(qid, q, d) for qid, q in preguntas.items()}
        self._json(200, {"model": "laya-simulado", "answers": answers,
                         "usage": {"input_tokens": 80, "output_tokens": 0},
                         "routing": {"model": "multilingual", "reason": "simulado"}},
                   {"X-Inference-Time-Ms": "%.2f" % t,
                    "Server-Timing": "inference;dur=%.2f" % t})


def crear_servidor(host="127.0.0.1", puerto=0, base_ms=35.0, paralelo=1, fallar_prob=0.0,
                   colgar_prob=0.0, colgar_s=30.0, api_key=""):
    cfg = argparse.Namespace(base_ms=base_ms, fallar_prob=fallar_prob, colgar_prob=colgar_prob,
                             colgar_s=colgar_s, api_key=api_key)
    h = type("H", (Handler,), {"cfg": cfg, "gpu": threading.Semaphore(paralelo)})
    class Servidor(ThreadingHTTPServer):
        daemon_threads = True

        def handle_error(self, request, client_address):
            pass                      # el cliente se rindió (timeout): ruido esperado

    return Servidor((host, puerto), h)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--puerto", type=int, default=8000)
    ap.add_argument("--base-ms", type=float, default=35.0, help="tiempo de cálculo simulado")
    ap.add_argument("--paralelo", type=int, default=1, help="pedidos que la 'GPU' atiende a la vez")
    ap.add_argument("--fallar-prob", type=float, default=0.0)
    ap.add_argument("--colgar-prob", type=float, default=0.0)
    ap.add_argument("--colgar-s", type=float, default=30.0)
    ap.add_argument("--api-key", default="")
    a = ap.parse_args(argv)
    srv = crear_servidor(a.host, a.puerto, a.base_ms, a.paralelo, a.fallar_prob, a.colgar_prob, a.colgar_s, a.api_key)
    print("LAYA SIMULADO (solo pruebas) en http://%s:%d" % (a.host, a.puerto))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
