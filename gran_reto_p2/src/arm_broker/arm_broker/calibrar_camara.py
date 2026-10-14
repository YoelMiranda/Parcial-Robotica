"""Calibra la cámara: píxel -> (x, y) mm de la mesa, con una homografía de 4 puntos.

NO mueve el brazo. Procedimiento (PASO_A_PASO_P2.md, paso 6):
  1. Lancen el broker real: lleva el brazo a la pose de observación. Ciérrenlo (Ctrl+C);
     el brazo se queda ahí. (Así solo el broker mueve el brazo.)
  2. Pongan los 4 cubos EXACTAMENTE en sus posiciones conocidas (pick_<color> del YAML).
  3. ros2 run arm_broker calibrar_camara --config <ruta>/broker_p2.yaml
Genera calibracion_camara.json (lo lee el broker) y calibracion.jpg (evidencia).
"""

import argparse
import json
import os
import sys
import time

import cv2
import numpy as np

from arm_broker import CamaraColoresReconocimiento as CAM
from arm_broker import DestinacionColores as DC


def leer_posiciones(ruta_yaml):
    pos = {c: list(v) for c, v in DC.POSICIONES_PICK.items()}
    if not ruta_yaml:
        return pos
    import yaml
    with open(ruta_yaml) as f:
        datos = yaml.safe_load(f) or {}
    params = {}
    for v in datos.values():
        if isinstance(v, dict) and 'ros__parameters' in v:
            params.update(v['ros__parameters'])
    for c in DC.COLORES:
        t = params.get(f'pick_{c}')
        if t:
            pos[c] = [float(x) for x in str(t).strip('[]').replace(',', ' ').split()]
    return pos


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--config', default='', help='broker_p2.yaml con pick_<color>')
    ap.add_argument('--indice', type=int, default=0)
    ap.add_argument('--salida', default='calibracion_camara.json')
    ap.add_argument('--cuadros', type=int, default=15)
    args = ap.parse_args(sys.argv[1:] if argv is None else argv)

    pos = leer_posiciones(args.config)
    try:
        cam = CAM.Camara(args.indice)
    except RuntimeError as e:
        print(f'❗ {e}. ¿El broker sigue corriendo y tiene la cámara?')
        return 1
    try:
        time.sleep(1.0)
        px, mm = {}, {}
        frame = None
        for c in DC.COLORES:
            r = CAM.localizar(cam, c, None, n_cuadros=args.cuadros)
            if r['encontrado']:
                px[c] = [r['u'], r['v']]
                mm[c] = pos[c]
                print(f'  {c:<9} píxel ({r["u"]:.0f}, {r["v"]:.0f}) -> mesa {pos[c]} mm')
            else:
                print(f'  {c:<9} NO detectado: {r.get("motivo")}')
        frames = cam.cuadros_nuevos(1)
        frame = frames[0] if frames else None
    finally:
        cam.cerrar()

    if len(px) < 4:
        print(f'❗ Se necesitan los 4 colores y se detectaron {len(px)}. Ajusten RANGOS_COLORES '
              '(python3 -m arm_broker.CamaraColoresReconocimiento <color>) y repitan.')
        return 2
    orden = list(px)
    src = np.array([px[c] for c in orden], dtype=np.float32)
    dst = np.array([mm[c] for c in orden], dtype=np.float32)
    H, _ = cv2.findHomography(src, dst)
    if H is None:
        print('❗ No se pudo calcular la homografía (¿puntos alineados?)')
        return 3
    errores = []
    for c in orden:
        x, y = CAM.pixel_a_mesa(H, *px[c])
        errores.append(float(np.hypot(x - mm[c][0], y - mm[c][1])))
    datos = {'H': H.tolist(), 'pixeles': px, 'mm': mm, 'fecha': time.strftime('%Y-%m-%d %H:%M:%S'),
             'error_reproyeccion_mm': errores,
             'nota': 'válida solo para la pose de observación con la que se tomó'}
    with open(args.salida, 'w') as f:
        json.dump(datos, f, indent=2)
    if frame is not None:
        for c in orden:
            u, v = px[c]
            cv2.circle(frame, (int(u), int(v)), 7, (0, 0, 0), -1)
            cv2.putText(frame, f'{c} {mm[c]}', (int(u) - 50, int(v) - 12),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
        cv2.imwrite(os.path.join(os.path.dirname(os.path.abspath(args.salida)), 'calibracion.jpg'), frame)
    print(f'✅ {args.salida} guardado · error de reproyección máx {max(errores):.2f} mm')
    return 0


if __name__ == '__main__':
    sys.exit(main())
