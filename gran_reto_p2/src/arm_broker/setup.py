from glob import glob
from setuptools import setup

package_name = 'arm_broker'

setup(
    name=package_name,
    version='2.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
        ('share/' + package_name + '/launch', glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Equipo',
    maintainer_email='equipo@esan.edu.pe',
    description='Broker del brazo (RB-2) con agarre autonomo para la Pregunta 2',
    license='MIT',
    entry_points={
        'console_scripts': [
            'broker = arm_broker.broker:main',
            'cliente = arm_broker.cliente:main',
            'cliente_integrado = arm_broker.cliente_integrado:main',
            'monitor_cola = arm_broker.monitor_cola:main',
            'calibrar_camara = arm_broker.calibrar_camara:main',
            'tabla_intentos = arm_broker.tabla_intentos:main',
            'probar_decisiones = arm_broker.probar_decisiones:main',
        ],
    },
)
