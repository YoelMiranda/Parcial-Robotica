#!/usr/bin/env python3
"""Mide la latencia del servicio /interpretar_orden sobre el conjunto de frases.

Uso (con el nodo interprete_ordenes en ejecución, mismo ROS_DOMAIN_ID):

  # 1) escribir ANTES la predicción (regla del examen) y medir en calma:
  ros2 run jetcobot_interprete medir_latencia --frases frases.csv --escenario calma \
       --prediccion-mediana-ms 60 --prediccion-p95-ms 120 --laya-url http://IP:PUERTO

  # 2) bajo carga: ejecutar a la vez en todos los equipos (inicio sincronizado):
  ros2 run jetcobot_interprete medir_latencia --frases frases.csv --escenario carga \
       --prediccion-mediana-ms 150 --prediccion-p95-ms 400 --inicio 10:15:00

  # 3) comparar ambos escenarios:
  ros2 run jetcobot_interprete medir_latencia --comparar salida/resumen_calma.json salida/resumen_carga.json

Separación de tiempos por llamada:
  cliente_ms  = visto por quien llama al servicio (incluye DDS/ROS)
  total_ms    = dentro del nodo (petición -> decisión lista)
  rtt_ms      = ida y vuelta HTTP con LAYA (envío -> cuerpo recibido)
  servidor_ms = cálculo del modelo que informa el propio servidor
  red_ms      = rtt - servidor (red + serialización + cola en el servidor)
  ping_ms     = línea base: GET /health (red sin cálculo del modelo)
"""
import argparse
import csv
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from .clasificador_palabras import clasificar
from .estadistica import resumen

CAMPOS = ["accion", "objeto", "color", "zona", "prioridad", "permitido", "causa"]


# ------------------------------------------------------------------ utilidades
def leer_frases(ruta):
    with open(ruta, newline="", encoding="utf-8-sig") as f:
        filas = list(csv.DictReader(f))
    if not filas or "frase" not in filas[0]:
        sys.exit("El CSV debe tener una columna 'frase'.")
    for i, fila in enumerate(filas, 1):
        fila.setdefault("id", str(i))
        if not fila.get("id"):
            fila["id"] = str(i)
    return filas


def esperar_hasta(hhmmss):
    objetivo = datetime.strptime(hhmmss, "%H:%M:%S").time()
    ahora = datetime.now()
    destino = datetime.combine(ahora.date(), objetivo)
    falta = (destino - ahora).total_seconds()
    if falta < 0:
        print("La hora de inicio ya pasó; se empieza ahora.")
        return
    print("Esperando %.1f s hasta las %s para iniciar..." % (falta, hhmmss))
    time.sleep(falta)


def fmt(x):
    return "n/d" if x is None or x != x else "%.1f" % x


def tabla_resumen_md(res):
    filas = [("Tiempo visto por el cliente (ROS) [ms]", "cliente_ms"),
             ("Tiempo total dentro del nodo [ms]", "total_ms"),
             ("Ida y vuelta HTTP con LAYA (rtt) [ms]", "rtt_ms"),
             ("Cálculo del modelo (informado por el servidor) [ms]", "servidor_ms"),
             ("Red y cola = rtt − cálculo [ms]", "red_ms")]
    out = ["| Métrica | n | Mediana | P95 | Media | Mín | Máx |", "|---|---:|---:|---:|---:|---:|---:|"]
    for nombre, k in filas:
        r = res["metricas"][k]
        out.append("| %s | %d | %s | %s | %s | %s | %s |" % (
            nombre, r["n"], fmt(r["mediana"]), fmt(r["p95"]), fmt(r["media"]), fmt(r["min"]), fmt(r["max"])))
    return "\n".join(out)


def comparar(ruta_a, ruta_b):
    a, b = json.load(open(ruta_a, encoding="utf-8")), json.load(open(ruta_b, encoding="utf-8"))
    print("| Métrica | %s mediana | %s P95 | %s mediana | %s P95 | Δ mediana | Δ P95 |" % (
        a["escenario"], a["escenario"], b["escenario"], b["escenario"]))
    print("|---|---:|---:|---:|---:|---:|---:|")
    for nombre, k in [("Visto por el cliente (ROS)", "cliente_ms"), ("Total en el nodo", "total_ms"),
                      ("Ida y vuelta HTTP (rtt)", "rtt_ms"), ("Cálculo del modelo", "servidor_ms"),
                      ("Red y cola (rtt − cálculo)", "red_ms")]:
        ra, rb = a["metricas"][k], b["metricas"][k]
        print("| %s | %s | %s | %s | %s | %s | %s |" % (
            nombre, fmt(ra["mediana"]), fmt(ra["p95"]), fmt(rb["mediana"]), fmt(rb["p95"]),
            fmt(rb["mediana"] - ra["mediana"]), fmt(rb["p95"] - ra["p95"])))
    print("\nDegradadas: %s=%d/%d, %s=%d/%d" % (a["escenario"], a["degradadas"], a["llamadas"],
                                                  b["escenario"], b["degradadas"], b["llamadas"]))


# ------------------------------------------------------------------------ main
def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comparar", nargs=2, metavar=("RESUMEN_A", "RESUMEN_B"))
    ap.add_argument("--frases", help="CSV con columna 'frase' (y opcionalmente las columnas de verdad)")
    ap.add_argument("--escenario", default="calma", help="etiqueta: calma | carga")
    ap.add_argument("--repeticiones", type=int, default=1, help="pasadas completas sobre las frases")
    ap.add_argument("--hilos", type=int, default=1, help="llamadas simultáneas desde este equipo (carga sintética)")
    ap.add_argument("--calentamiento", type=int, default=3, help="llamadas iniciales descartadas")
    ap.add_argument("--timeout-cliente", type=float, default=10.0, help="espera máxima por llamada [s]")
    ap.add_argument("--laya-url", default="", help="http://IP:PUERTO para medir la línea base (GET /health)")
    ap.add_argument("--inicio", default="", help="HH:MM:SS: hora local para arrancar (sincronizar equipos)")
    ap.add_argument("--salida", default="salida")
    ap.add_argument("--prediccion-mediana-ms", type=float)
    ap.add_argument("--prediccion-p95-ms", type=float)
    ap.add_argument("--sin-prediccion", action="store_true",
                    help="omitir la predicción previa (el examen la exige: úsese solo en pruebas)")
    a = ap.parse_args(argv)

    if a.comparar:
        return comparar(*a.comparar)
    if not a.frases:
        ap.error("falta --frases")
    if not a.sin_prediccion and (a.prediccion_mediana_ms is None or a.prediccion_p95_ms is None):
        ap.error("Registre ANTES su predicción: --prediccion-mediana-ms y --prediccion-p95-ms "
                 "(el examen califica la diferencia entre lo predicho y lo medido).")

    import rclpy
    from rclpy.executors import MultiThreadedExecutor
    from rclpy.node import Node
    from jetcobot_interfaces.srv import InterpretarOrden

    frases = leer_frases(a.frases)
    os.makedirs(a.salida, exist_ok=True)

    rclpy.init()
    nodo = Node("medidor_latencia")
    cli = nodo.create_client(InterpretarOrden, "/interpretar_orden")
    ejec = MultiThreadedExecutor()
    ejec.add_node(nodo)
    threading.Thread(target=ejec.spin, daemon=True).start()
    if not cli.wait_for_service(timeout_sec=10.0):
        sys.exit("El servicio /interpretar_orden no aparece (¿ROS_DOMAIN_ID correcto? ¿nodo en ejecución?).")

    def llamar(frase):
        req = InterpretarOrden.Request()
        req.frase = frase
        ev = threading.Event()
        t0 = time.perf_counter()
        fut = cli.call_async(req)
        fut.add_done_callback(lambda _f: ev.set())
        if not ev.wait(a.timeout_cliente):
            return None, a.timeout_cliente * 1000.0
        return fut.result(), (time.perf_counter() - t0) * 1000.0

    # línea base de red
    ping = None
    if a.laya_url:
        from .cliente_laya import ClienteLaya
        try:
            c = ClienteLaya(a.laya_url)
            muestras = [c.ping_ms() for _ in range(20)]
            ping = resumen(muestras)
            print("Línea base GET /health: mediana %.1f ms, P95 %.1f ms" % (ping["mediana"], ping["p95"]))
        except Exception as e:
            print("No se pudo medir /health: %s" % e)

    for i in range(a.calentamiento):
        llamar(frases[i % len(frases)]["frase"])

    if a.inicio:
        esperar_hasta(a.inicio)

    tareas = [(rep, f) for rep in range(1, a.repeticiones + 1) for f in frases]

    def ejecutar(t):
        rep, f = t
        resp, cliente_ms = llamar(f["frase"])
        return rep, f, resp, cliente_ms

    t_ini = time.perf_counter()
    if a.hilos <= 1:
        resultados = [ejecutar(t) for t in tareas]
    else:
        with ThreadPoolExecutor(max_workers=a.hilos) as ex:
            resultados = list(ex.map(ejecutar, tareas))
    duracion = time.perf_counter() - t_ini

    # ---- CSV de decisiones + latencias ----
    gold_cols = [c for c in frases[0].keys() if c not in ("id", "frase")]
    cols = (["id", "repeticion", "escenario", "frase"] + ["gold_" + c for c in gold_cols]
            + ["laya_" + c for c in CAMPOS] + ["laya_fuente", "laya_degradado", "laya_detalle_error"]
            + ["kw_" + c for c in CAMPOS]
            + ["cliente_ms", "total_ms", "rtt_ms", "servidor_ms", "red_ms", "error_cliente"])
    ruta_csv = os.path.join(a.salida, "decisiones_%s.csv" % a.escenario)
    m = {k: [] for k in ("cliente_ms", "total_ms", "rtt_ms", "servidor_ms", "red_ms")}
    degradadas = errores = 0
    with open(ruta_csv, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for rep, f, resp, cliente_ms in resultados:
            fila = {"id": f["id"], "repeticion": rep, "escenario": a.escenario, "frase": f["frase"]}
            for c in gold_cols:
                fila["gold_" + c] = f[c]
            kw = clasificar(f["frase"])
            for c in CAMPOS:
                fila["kw_" + c] = kw[c]
            fila["cliente_ms"] = round(cliente_ms, 3)
            if resp is None:
                errores += 1
                fila["error_cliente"] = "sin respuesta del servicio en %.1f s" % a.timeout_cliente
            else:
                for c in CAMPOS:
                    fila["laya_" + c] = getattr(resp, c)
                fila["laya_fuente"] = resp.fuente
                fila["laya_degradado"] = resp.degradado
                fila["laya_detalle_error"] = resp.detalle_error
                fila["total_ms"] = round(resp.latencia_total_ms, 3)
                m["cliente_ms"].append(cliente_ms)
                m["total_ms"].append(resp.latencia_total_ms)
                if resp.degradado:
                    degradadas += 1
                else:
                    for k, v in (("rtt_ms", resp.latencia_rtt_ms), ("servidor_ms", resp.latencia_servidor_ms),
                                 ("red_ms", resp.latencia_red_ms)):
                        if v >= 0:
                            m[k].append(v)
                            fila[k] = round(v, 3)
            w.writerow(fila)

    res = {"escenario": a.escenario, "fecha": datetime.now().isoformat(timespec="seconds"),
           "frases": len(frases), "repeticiones": a.repeticiones, "hilos": a.hilos,
           "llamadas": len(resultados), "degradadas": degradadas, "sin_respuesta": errores,
           "duracion_s": round(duracion, 2), "ping_health_ms": ping,
           "metodo_percentil": "interpolación lineal (numpy.percentile)",
           "prediccion": {"mediana_ms": a.prediccion_mediana_ms, "p95_ms": a.prediccion_p95_ms},
           "metricas": {k: resumen(v) for k, v in m.items()}}
    if a.prediccion_mediana_ms is not None:
        real = res["metricas"]["cliente_ms"]
        res["prediccion"]["error_mediana_ms"] = real["mediana"] - a.prediccion_mediana_ms
        res["prediccion"]["error_p95_ms"] = real["p95"] - (a.prediccion_p95_ms or 0)
    with open(os.path.join(a.salida, "resumen_%s.json" % a.escenario), "w", encoding="utf-8") as fh:
        json.dump(res, fh, ensure_ascii=False, indent=2)
    md = ["### Latencia — escenario: %s" % a.escenario,
          "Llamadas: %d (frases=%d × repeticiones=%d, hilos=%d) · degradadas: %d · sin respuesta: %d · duración: %.1f s"
          % (len(resultados), len(frases), a.repeticiones, a.hilos, degradadas, errores, duracion), "",
          tabla_resumen_md(res)]
    if ping:
        md.append("\nLínea base de red (GET /health): mediana %.1f ms · P95 %.1f ms" % (ping["mediana"], ping["p95"]))
    if a.prediccion_mediana_ms is not None:
        p = res["prediccion"]
        md.append("\nPredicción vs medición (tiempo visto por el cliente): mediana predicha %.1f ms, medida %.1f ms "
                  "(Δ %+.1f); P95 predicho %.1f ms, medido %.1f ms (Δ %+.1f)" % (
                      a.prediccion_mediana_ms, res["metricas"]["cliente_ms"]["mediana"], p["error_mediana_ms"],
                      a.prediccion_p95_ms, res["metricas"]["cliente_ms"]["p95"], p["error_p95_ms"]))
    texto = "\n".join(md)
    with open(os.path.join(a.salida, "tabla_latencia_%s.md" % a.escenario), "w", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    print(texto)
    print("\nArchivos: %s, resumen_%s.json, tabla_latencia_%s.md" % (ruta_csv, a.escenario, a.escenario))
    ejec.shutdown()
    nodo.destroy_node()
    rclpy.shutdown()


if __name__ == "__main__":
    main()
