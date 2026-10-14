# Gran Reto JetCobot — Pregunta 3: de la voz al movimiento

Workspace ROS 2 (Humble) que se monta **encima** de P1 (`gran_reto_p1`) y P2 (`gran_reto_p2`) sin modificarlas.
Paso a paso: [`PASO_A_PASO_P3.md`](PASO_A_PASO_P3.md).

```
src/jetcobot_voz/
  jetcobot_voz/
    transcriptor_voz.py     nodo (Parte A): voz -> Google AI Studio (plazo propio) -> ClienteIntegrado de la P2
                            (respaldo: modo texto por teclado). Registra audio, texto, decisión, resultado y tiempos
    gemini_stt.py           cliente de la nube (clave desde variable de entorno; plazo duro). `python3 -m jetcobot_voz.gemini_stt a.wav`
    tabla_ordenes.py        tabla de las 5 órdenes (Parte B) y anotación de lo esperado/correcto
    desglose_voz.py         desglose de tiempos (Parte C): une registro_voz.csv + intentos.csv de la P2 -> tabla, figura, análisis
    calibrar_microfono.py   sugiere umbral_rms
  config/transcriptor_voz.yaml     test/test_voz.py (6 pruebas sin ROS)
entorno_p3.sh   herramientas/sin_internet.sh   PREDICCIONES_P3.md   informe_P3.md
```

| Requisito del examen | Dónde |
|---|---|
| Nodo `transcriptor_voz`; audio de micrófono o archivo | `transcriptor_voz.py` (`archivo_audio` vacío = micrófono) |
| Transcripción en español con Google AI Studio | `gemini_stt.py` |
| Clave solo en variable de entorno | `api_key_env`; `.gitignore`; prueba `test_no_hay_clave_en_el_codigo` |
| Plazo propio; sin internet → modo texto y lo informa | `timeout_transcripcion_s`; `/estado_voz` y consola |
| Registrar transcripción junto al audio | `evidencia_voz/audio/<id>.wav|.txt`, `registro_voz.csv` |
| Texto entregado a `/interpretar_orden` | `ClienteIntegrado.enviar_frase` (P2) |
| 5 órdenes: dicho / transcrito / decisión / brazo | `tabla_ordenes` |
| Desglose captura→…→planificación, tabla + figura | `desglose_voz` |
| Etapa dominante y "reducir a la mitad" | texto de `desglose_voz.md` |
| Demostración sin internet | `herramientas/sin_internet.sh`, PASO_A_PASO §7 |

Pruebas sin ROS: `cd src/jetcobot_voz && python3 -m unittest discover -s test -v`
