### Latencia — escenario: calma
Llamadas: 50 (frases=50 × repeticiones=1, hilos=1) · degradadas: 0 · sin respuesta: 0 · duración: 12.3 s

| Métrica | n | Mediana | P95 | Media | Mín | Máx |
|---|---:|---:|---:|---:|---:|---:|
| Tiempo visto por el cliente (ROS) [ms] | 50 | 234.7 | 308.1 | 244.9 | 208.5 | 328.0 |
| Tiempo total dentro del nodo [ms] | 50 | 228.8 | 302.3 | 239.0 | 203.4 | 321.4 |
| Ida y vuelta HTTP con LAYA (rtt) [ms] | 50 | 227.5 | 301.0 | 237.8 | 202.1 | 320.4 |
| Cálculo del modelo (informado por el servidor) [ms] | 50 | 215.2 | 288.3 | 226.0 | 192.4 | 307.5 |
| Red y cola = rtt − cálculo [ms] | 50 | 11.1 | 18.5 | 11.8 | 7.9 | 22.1 |

Línea base de red (GET /health): mediana 6.8 ms · P95 13.9 ms

Predicción vs medición (tiempo visto por el cliente): mediana predicha 60.0 ms, medida 234.7 ms (Δ +174.7); P95 predicho 120.0 ms, medido 308.1 ms (Δ +188.1)
