#!/usr/bin/env python3
"""Parte B: tabla de las cinco ordenes dictadas por el docente.

  ros2 run jetcobot_voz tabla_ordenes evidencia_voz/registro_voz.csv                 # tabla markdown (ultimas 5)
  ros2 run jetcobot_voz tabla_ordenes evidencia_voz/registro_voz.csv --marcar 2 \
        --dicho "lleva el cubo rojo a su lugar" --esperado "ejecutar: rojo -> cuadro rojo" --correcta si

--marcar N es el numero de fila (1 = la primera orden de la sesion). Una orden es correcta SOLO si el
resultado final es el esperado, incluido el rechazo cuando corresponde rechazar.
"""
import argparse
import csv
import sys


def leer(ruta):
    with open(ruta, newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def escribir(ruta, filas):
    with open(ruta, 'w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=list(filas[0].keys()))
        w.writeheader()
        w.writerows(filas)


def decision(f):
    if not f.get('accion'):
        return '—'
    return (f'{f["accion"]} · {f["objeto"]} · {f["color"]} · {f["zona"]} · prio {f["prioridad"]} · '
            f'permitido={f["permitido"]}' + (f' · causa={f["causa"]}' if f.get('causa') not in ('', 'ninguna') else '')
            + (' · DEGRADADO' if f.get('degradado') in ('True', 'true', '1') else ''))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument('csv')
    ap.add_argument('--marcar', type=int, metavar='N')
    ap.add_argument('--dicho')
    ap.add_argument('--esperado')
    ap.add_argument('--correcta', choices=['si', 'no'])
    ap.add_argument('--ultimas', type=int, default=5)
    a = ap.parse_args(sys.argv[1:] if argv is None else argv)

    filas = leer(a.csv)
    if a.marcar:
        if not 1 <= a.marcar <= len(filas):
            print(f'no existe la fila {a.marcar} (hay {len(filas)})')
            return 1
        f = filas[a.marcar - 1]
        for campo, valor in (('dicho_real', a.dicho), ('resultado_esperado', a.esperado), ('correcta', a.correcta)):
            if valor is not None:
                f[campo] = valor
        escribir(a.csv, filas)
        print(f'fila {a.marcar} ({f["orden_id"]}) actualizada')
        return 0

    sel = filas[-a.ultimas:] if a.ultimas else filas
    print('| # | Lo que se dijo | Lo que transcribio el sistema | Decision del modelo | Lo que hizo el brazo | Esperado | ¿Correcta? |')
    print('|---|---|---|---|---|---|---|')
    ok = pend = 0
    for i, f in enumerate(sel, 1):
        c = (f.get('correcta') or '').lower()
        ok += c == 'si'
        pend += c not in ('si', 'no')
        modo = ' *(modo texto)*' if f.get('modo') == 'texto' else ''
        print(f'| {i} | {f.get("dicho_real") or "(sin marcar)"} | {f.get("transcripcion") or "—"}{modo} | {decision(f)} | '
              f'{f.get("detalle_brazo") or f.get("resultado") or "—"} | {f.get("resultado_esperado") or "—"} | {c.upper() or "PENDIENTE"} |')
    print(f'\n**Correctas: {ok} de {len(sel)}**' + (f' · ⚠ {pend} sin marcar' if pend else ''))
    return 0


if __name__ == '__main__':
    sys.exit(main())
