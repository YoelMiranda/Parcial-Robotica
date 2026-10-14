"""Cliente minimo de transcripcion con Google AI Studio (Gemini). Sin dependencias de ROS.

Prueba rapida fuera de ROS (sirve para validar la clave):
    export GOOGLE_API_KEY=...          # nunca en el codigo
    python3 -m jetcobot_voz.gemini_stt audio.wav
"""
import base64
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FutTimeout

import requests

URL = 'https://generativelanguage.googleapis.com/v1beta/models/{modelo}:generateContent'
PROMPT = ('Transcribe literalmente este audio en espanol. Responde unicamente con el '
          'texto transcrito, sin comillas ni comentarios. No corrijas ni completes lo que '
          'se dijo. Si no hay voz inteligible responde exactamente: [SIN_VOZ]')
MIMES = {'.wav': 'audio/wav', '.mp3': 'audio/mp3', '.ogg': 'audio/ogg',
         '.flac': 'audio/flac', '.aac': 'audio/aac', '.m4a': 'audio/aac',
         '.aiff': 'audio/aiff', '.opus': 'audio/ogg'}
# Gemini acepta wav, mp3, aiff, aac, ogg, flac; con inline_data el cuerpo total debe ser < ~20 MB.
MAX_INLINE_BYTES = 12 * 1024 * 1024


class ErrorTranscripcion(Exception):
    """motivo: sin_clave | timeout | sin_internet | http_<codigo> | sin_voz | respuesta_invalida"""

    def __init__(self, motivo, detalle=''):
        super().__init__(f'{motivo}: {detalle}' if detalle else motivo)
        self.motivo = motivo
        self.detalle = detalle


def leer_clave(var_entorno='GOOGLE_API_KEY'):
    clave = os.environ.get(var_entorno, '').strip()
    if not clave:
        raise ErrorTranscripcion('sin_clave', f'la variable de entorno {var_entorno} no esta definida')
    return clave


def mime_de(ruta):
    return MIMES.get(os.path.splitext(ruta)[1].lower(), 'audio/wav')


def _llamar(audio_bytes, mime, api_key, modelo, timeout_s, pista=''):
    texto_prompt = PROMPT + (f' Contexto (solo para acertar la ortografia): es una orden para un '
                             f'brazo robotico y puede contener palabras como: {pista}.' if pista else '')
    cuerpo = {
        'contents': [{'parts': [
            {'text': texto_prompt},
            {'inline_data': {'mime_type': mime,
                             'data': base64.b64encode(audio_bytes).decode('ascii')}},
        ]}],
        'generationConfig': {'temperature': 0.0},
    }
    # gemini-2.5-flash "piensa" por defecto: para transcribir solo suma latencia -> se apaga.
    if '2.5-flash' in modelo:
        cuerpo['generationConfig']['thinkingConfig'] = {'thinkingBudget': 0}
    # La clave viaja en la cabecera: no aparece en URLs ni en logs.
    r = requests.post(URL.format(modelo=modelo),
                      headers={'x-goog-api-key': api_key, 'Content-Type': 'application/json'},
                      json=cuerpo, timeout=(min(3.0, timeout_s), timeout_s))
    if r.status_code != 200:
        raise ErrorTranscripcion(f'http_{r.status_code}', r.text[:200])
    try:
        texto = r.json()['candidates'][0]['content']['parts'][0]['text'].strip()
    except (KeyError, IndexError, ValueError) as e:
        raise ErrorTranscripcion('respuesta_invalida', repr(e))
    if not texto or texto == '[SIN_VOZ]':
        raise ErrorTranscripcion('sin_voz', 'el modelo no detecto voz inteligible')
    return texto


def transcribir(audio_bytes, mime, api_key, modelo, timeout_s, pista=''):
    """Devuelve el texto o lanza ErrorTranscripcion. Plazo TOTAL = timeout_s (duro)."""
    ex = ThreadPoolExecutor(max_workers=1)
    fut = ex.submit(_llamar, audio_bytes, mime, api_key, modelo, timeout_s, pista)
    try:
        return fut.result(timeout=timeout_s)
    except _FutTimeout:
        raise ErrorTranscripcion('timeout', f'sin respuesta en {timeout_s:.1f} s')
    except requests.exceptions.Timeout:
        raise ErrorTranscripcion('timeout', f'sin respuesta en {timeout_s:.1f} s')
    except requests.exceptions.ConnectionError as e:
        raise ErrorTranscripcion('sin_internet', type(e).__name__)
    finally:
        ex.shutdown(wait=False)


if __name__ == '__main__':
    if len(sys.argv) not in (2, 3):
        sys.exit('uso: python3 -m jetcobot_voz.gemini_stt audio.wav [modelo]')
    ruta = sys.argv[1]
    modelo = sys.argv[2] if len(sys.argv) == 3 else 'gemini-2.5-flash'
    with open(ruta, 'rb') as f:
        datos = f.read()
    t0 = time.time()
    try:
        print(transcribir(datos, mime_de(ruta), leer_clave(), modelo, 15.0))
        print(f'[{(time.time() - t0) * 1000:.0f} ms]')
    except ErrorTranscripcion as e:
        sys.exit(f'FALLO -> {e}')
