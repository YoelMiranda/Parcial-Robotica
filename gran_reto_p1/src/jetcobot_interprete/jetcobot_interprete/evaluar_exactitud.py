#!/usr/bin/env python3
"""Exactitud de LAYA vs clasificador por palabras clave (y el modo híbrido) sobre el mismo conjunto.

Entrada: decisiones_<escenario>.csv generado por medir_latencia (con columnas gold_*).
Salida : tabla comparativa (markdown) + fallos por tipo de frase + fallos_*.csv

  ros2 run jetcobot_interprete evaluar_exactitud salida/decisiones_calma.csv
"""
import argparse
import csv
import os
from collections import Counter, defaultdict

from .verificacion import aplicar_reglas

CAMPOS = ["accion", "objeto", "color", "zona", "prioridad", "permitido"]


def _b(v):
    return str(v).strip().lower() in ("true", "1", "si", "sí", "verdadero")


def _norm(campo, v):
    if campo == "permitido":
        return _b(v)
    if campo == "prioridad":
        return int(float(v))
    return str(v).strip()


def tipo_frase(r):
    """Categoría de la frase según su verdad (para explicar qué tipo de frases falla cada método)."""
    if not _b(r["gold_permitido"]):
        return "orden prohibida (debe rechazarse)"
    acc = r["gold_accion"]
    if acc == "ninguna":
        return "no es una orden / negación"
    if acc == "detener":
        return "detener"
    if acc == "ir_home":
        return "ir a home"
    if acc == "depositar":
        return "depositar"
    if r.get("gold_color") == "ninguno" or r.get("gold_objeto") == "ninguno":
        return "recoger con objeto/color ausente de la mesa"
    return "recoger (orden normal)"


def evaluar(filas, metodo, campos):
    """Devuelve (aciertos_por_campo, n, completa_exacta, completa_pm1, fallos)."""
    ac = Counter()
    n = completa = completa_pm1 = 0
    fallos = []
    for r in filas:
        if metodo in ("laya", "hib") and (str(r.get("laya_degradado")) == "True" or not r.get("laya_accion")):
            continue                       # respuesta de respaldo: no cuenta como LAYA
        n += 1
        todos = todos_pm1 = True
        for c in campos:
            g, o = _norm(c, r["gold_" + c]), _norm(c, r["%s_%s" % (metodo, c)])
            ok = g == o
            ac[c] += ok
            if not ok:
                fallos.append({"id": r["id"], "frase": r["frase"], "tipo": tipo_frase(r),
                               "campo": c, "esperado": g, "obtenido": o})
            if c == "prioridad":
                todos_pm1 &= abs(g - o) <= 1
                todos &= ok
            else:
                todos &= ok
                todos_pm1 &= ok
        completa += todos
        completa_pm1 += todos_pm1
    return ac, n, completa, completa_pm1, fallos


def agregar_hibrido(filas):
    """Columnas hib_* = capa de verificación aplicada a laya_* (sin P(peligro): veto de LAYA no sostenido)."""
    for r in filas:
        if not r.get("laya_accion"):
            continue
        d = {"accion": r["laya_accion"], "objeto": r["laya_objeto"], "color": r["laya_color"],
             "zona": r["laya_zona"], "prioridad": int(float(r["laya_prioridad"])),
             "permitido": _b(r["laya_permitido"]), "causa": r.get("laya_causa", "ninguna")}
        h, _ = aplicar_reglas(d, r["frase"])
        for c, v in h.items():
            r["hib_" + c] = v


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv")
    ap.add_argument("--repeticion", type=int, default=1, help="pasada a evaluar (default 1: las 50 frases una vez)")
    ap.add_argument("--salida", default="salida")
    a = ap.parse_args(argv)

    with open(a.csv, newline="", encoding="utf-8") as f:
        filas = [r for r in csv.DictReader(f) if int(r["repeticion"]) == a.repeticion]
    campos = [c for c in CAMPOS if ("gold_" + c) in filas[0]]
    if not campos:
        raise SystemExit("El CSV no trae columnas gold_* (verdad). Use un conjunto con respuestas esperadas.")

    agregar_hibrido(filas)
    M = ("laya", "kw", "hib")
    res = {m: evaluar(filas, m, campos) for m in M}
    total = len(filas)
    nl = res["laya"][1]
    out = ["### Exactitud sobre %d frases (pasada %d)" % (total, a.repeticion), "",
           "LAYA se evalúa solo sobre las respuestas **no degradadas** (%d de %d); %d respuestas cayeron al respaldo "
           "y no se le atribuyen a LAYA." % (nl, total, total - nl), "",
           "La columna **Híbrido** aplica la capa de verificación (verificacion.py) a las respuestas de LAYA "
           "(con P(peligro) desconocida: equivale a umbral_veto_laya = 1). Si el CSV se midió con "
           "modo_decision=hibrido, las columnas LAYA e Híbrido coinciden.", "",
           "| Campo | LAYA | Palabras clave | Híbrido (LAYA + reglas) |", "|---|---:|---:|---:|"]
    for c in campos:
        out.append("| %s | %s | %s | %s |" % (c, *["%d/%d (%.1f %%)" % (res[m][0][c], res[m][1], 100.0 * res[m][0][c] / max(1, res[m][1]))
                                                   for m in M]))
    for etiqueta, idx in (("**Decisión completa** (todos los campos exactos)", 2),
                          ("**Decisión completa** (prioridad ±1)", 3)):
        out.append("| %s | %s | %s | %s |" % (etiqueta, *["%d/%d (%.1f %%)" % (res[m][idx], res[m][1], 100.0 * res[m][idx] / max(1, res[m][1]))
                                                          for m in M]))
    # seguridad: órdenes prohibidas aceptadas por error
    if "permitido" in campos:
        def peligrosas_aceptadas(m):
            k = 0
            for r in filas:
                if m in ("laya", "hib") and (str(r.get("laya_degradado")) == "True" or not r.get("laya_accion")):
                    continue
                if not _b(r["gold_permitido"]) and _b(r["%s_permitido" % m]):
                    k += 1
            return k
        out.append("| Órdenes prohibidas **aceptadas** por error (grave) | %d | %d | %d |" % tuple(
            peligrosas_aceptadas(m) for m in M))

    # fallos por tipo de frase
    if "gold_accion" in filas[0] and "gold_permitido" in filas[0]:
        out += ["", "### Fallos por tipo de frase (frases con al menos un campo incorrecto)", "",
                "| Tipo de frase (según la verdad) | Frases | LAYA falla | Palabras clave falla | Híbrido falla |",
                "|---|---:|---:|---:|---:|"]
        por_tipo = defaultdict(lambda: [0, set(), set(), set()])
        for r in filas:
            por_tipo[tipo_frase(r)][0] += 1
        for m, k in (("laya", 1), ("kw", 2), ("hib", 3)):
            for fa in res[m][4]:
                por_tipo[fa["tipo"]][k].add(fa["id"])
        for t, (n, fl, fk, fh) in sorted(por_tipo.items()):
            out.append("| %s | %d | %d | %d | %d |" % (t, n, len(fl), len(fk), len(fh)))

    texto = "\n".join(out)
    print(texto)
    os.makedirs(a.salida, exist_ok=True)
    with open(os.path.join(a.salida, "tabla_exactitud.md"), "w", encoding="utf-8") as fh:
        fh.write(texto + "\n")
    for m in M:
        with open(os.path.join(a.salida, "fallos_%s.csv" % m), "w", newline="", encoding="utf-8") as fh:
            w = csv.DictWriter(fh, fieldnames=["id", "frase", "tipo", "campo", "esperado", "obtenido"])
            w.writeheader()
            w.writerows(res[m][4])
    print("\nArchivos: %s/tabla_exactitud.md, fallos_laya.csv, fallos_kw.csv, fallos_hib.csv" % a.salida)


if __name__ == "__main__":
    main()
