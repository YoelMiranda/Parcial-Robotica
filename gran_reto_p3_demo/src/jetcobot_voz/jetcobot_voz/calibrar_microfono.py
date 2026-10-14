#!/usr/bin/env python3
"""Calcula `umbral_rms` para transcriptor_voz: 3 s de SILENCIO y 3 s HABLANDO como en la demo.

  ros2 run jetcobot_voz calibrar_microfono --dispositivo plughw:1,0
"""
import argparse
import statistics
import subprocess
import time

import numpy as np


def _rms_bloques(dispositivo, sr, seg):
    raw = subprocess.run(['arecord', '-q', '-D', dispositivo, '-f', 'S16_LE', '-r', str(sr), '-c', '1',
                          '-t', 'raw', '-d', str(seg)], stdout=subprocess.PIPE, check=True).stdout
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    n = int(sr * 0.1)
    return [float(np.sqrt(np.mean(x[i:i + n] ** 2))) for i in range(0, len(x) - n + 1, n)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--dispositivo', default='default')
    ap.add_argument('--sr', type=int, default=16000)
    a = ap.parse_args()
    input('1) Silencio total en el laboratorio (como estara durante la demo). Enter para grabar 3 s... ')
    ruido = _rms_bloques(a.dispositivo, a.sr, 3)
    input('2) Ahora HABLA con voz normal durante 3 s (ej. "lleva el cubo rojo a su lugar"). Enter para grabar... ')
    time.sleep(0.2)
    habla = _rms_bloques(a.dispositivo, a.sr, 3)
    r_max, h_med = max(ruido), statistics.median(sorted(habla)[len(habla) // 2:])
    print(f'\nRuido: maximo {r_max:.0f} | Voz: mediana de los bloques fuertes {h_med:.0f}')
    if h_med < 2 * r_max:
        print('⚠ La voz apenas supera el ruido: acerca el microfono, sube la ganancia (alsamixer) o reduce el ruido.')
    print(f'umbral_rms sugerido: {(r_max * h_med) ** 0.5:.0f}   (ponlo en config/transcriptor_voz.yaml)')


if __name__ == '__main__':
    main()
