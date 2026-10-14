# Uso:  source ~/gran_reto_p3_demo/entorno_p3.sh     (en CADA terminal del Jetson)
source /opt/ros/humble/setup.bash
source ~/gran_reto_p1/install/setup.bash                       # P1: jetcobot_interfaces + interprete
[ -f ~/gran_reto_p2/install/setup.bash ] && source ~/gran_reto_p2/install/setup.bash   # P2: broker + ClienteIntegrado
[ -f ~/gran_reto_p3_demo/install/setup.bash ] && source ~/gran_reto_p3_demo/install/setup.bash   # P3: transcriptor_voz
export ROS_DOMAIN_ID=52            # <-- EL DE SU EQUIPO/BRAZO (el mismo de P1 y P2). ¡Confírmenlo!
export LAYA=http://172.51.1.10:8000   # <-- IP:puerto que da el docente
# La clave de Google AI Studio NUNCA va en un archivo del repositorio. En cada terminal que
# lance transcriptor_voz (o probar la nube):
#     read -s -p "GOOGLE_API_KEY: " GOOGLE_API_KEY; export GOOGLE_API_KEY; echo
[ -z "${GOOGLE_API_KEY:-}" ] && echo "(aviso) GOOGLE_API_KEY no está definida en esta terminal: sin ella solo funcionará el modo texto"
# Carpeta de trabajo de la P3: aquí quedan evidencia_p2/ (broker), evidencia_voz/, evidencia_clientes/ y los bags.
# Separada de ~/demo_p2 para que los intentos de la demostración no se mezclen con los 10 de la P2.
mkdir -p ~/demo_p3 && cd ~/demo_p3
[ -f calibracion_camara.json ] || { cp ~/demo_p2/calibracion_camara.json . 2>/dev/null && echo "(copiada calibracion_camara.json de ~/demo_p2)"; }
