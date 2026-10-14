#!/usr/bin/env bash
# Corta SOLO la salida a internet del Jetson (la red local con LAYA y el broker sigue viva).
#   bash herramientas/sin_internet.sh cortar      # borra la ruta por defecto (guarda copia)
#   bash herramientas/sin_internet.sh restaurar   # la devuelve
#   bash herramientas/sin_internet.sh estado      # ¿llego a internet? ¿llego a LAYA?
# Alternativa mas simple y sin sudo: desconectar fisicamente el cable/WiFi de SALIDA del router,
# o  -p forzar_texto:=true  (solo para ensayar; en la demo real muestren la desconexion de verdad).
set -u
LAYA_IP=$(echo "${LAYA:-http://172.51.1.10:8000}" | sed -E 's#https?://([^:/]+).*#\1#')
GUARDA=/tmp/ruta_default.txt
estado() {
  echo "--- ruta hacia LAYA ($LAYA_IP):"; ip route get "$LAYA_IP"
  echo "--- internet:"; if ping -c1 -W2 8.8.8.8 >/dev/null 2>&1; then echo "SI hay internet"; else echo "NO hay internet"; fi
  echo "--- LAYA:"; if curl -s -m 3 "${LAYA:-http://$LAYA_IP:8000}/health" >/dev/null 2>&1; then echo "LAYA responde"; else echo "LAYA no responde a /health (ok si el servidor no lo expone)"; fi
}
case "${1:-estado}" in
  cortar)
    if ip route get "$LAYA_IP" | grep -q " via "; then
      echo "⚠ LAYA se alcanza POR la ruta por defecto: cortarla tambien te dejaria sin LAYA. No lo hago."
      echo "  Desconecta el cable de salida del router o usa -p forzar_texto:=true."; exit 1
    fi
    ip route show default > "$GUARDA"; cat "$GUARDA"
    sudo ip route del default && echo "Ruta por defecto eliminada (copia en $GUARDA)"; estado ;;
  restaurar)
    [ -s "$GUARDA" ] || { echo "no hay copia en $GUARDA"; exit 1; }
    while read -r linea; do sudo ip route add $linea; done < "$GUARDA"; estado ;;
  *) estado ;;
esac
