# Informe — Pregunta 3: de la voz al movimiento

**Equipo N.º:** ____  **Integrantes:** ____________________  **ROS_DOMAIN_ID:** ____  **Brazo:** arm-__
**Fecha:** ___/___/2026  **Servidor LAYA:** ____________  **Modelo de transcripción:** ____________  **`timeout_transcripcion_s`:** ____

> Todo número sale de `evidencia_voz/registro_voz.csv`, `evidencia_voz/desglose_voz.csv`, `evidencia_p2/intentos.csv` o del bag.

## 1. Parte A — `transcriptor_voz`
* Clave por variable de entorno `GOOGLE_API_KEY`; `git grep AIza` vacío: ____
* Plazo propio y paso a modo texto: `timeout_transcripcion_s` = ____ s; motivos que lo activan: `sin_internet`, `timeout`, `http_*`, `sin_clave`, `sin_voz`.
* Registro de audio + transcripción: `evidencia_voz/audio/*.wav|.txt`, `registro_voz.csv`.
* Cadena aguas abajo reutilizada sin cambios: `ClienteIntegrado` → `/interpretar_orden` → `move_arm`. Regla del publicador único: el transcriptor no publica al brazo.

## 2. Parte B — cinco órdenes dictadas
<!-- Pegar la salida de: ros2 run jetcobot_voz tabla_ordenes evidencia_voz/registro_voz.csv -->

Análisis: ¿qué orden falló y en qué etapa (transcripción, decisión, admisión del broker, percepción)? ____________

## 3. Parte C — dónde se va el tiempo
<!-- Pegar desglose_voz.md e insertar desglose_voz.png -->

Definiciones usadas (ver PASO_A_PASO_P3 §6): ____________
Predicho vs medido (PREDICCIONES_P3.md): ____________

* **Etapa dominante (con números):** ____________
* **Reducir a la mitad el tiempo voz → movimiento:** etapa sobre la que trabajaría: ____; ahorro que se obtendría (mediana): ____ ms;
  ¿alcanza sola? ____; **qué dejaríamos de obtener a cambio:** ____________

## 4. Operación sin internet
Video (enlace): ____________ · Evidencia de la desconexión (`ping`/`sin_internet.sh estado`): ____________ · Fila del registro (`modo=texto`): ____________
Tiempo desde que se pidió la orden hasta que se activó el modo texto: ____ s

## 5. Limitaciones
* ____________
