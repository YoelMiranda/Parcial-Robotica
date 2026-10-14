from glob import glob
from setuptools import setup

package_name = 'jetcobot_voz'

setup(
    name=package_name,
    version='3.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/config', glob('config/*.yaml')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Equipo',
    maintainer_email='equipo@esan.edu.pe',
    description='Pregunta 3: de la voz al movimiento (transcriptor_voz, tabla de ordenes, desglose de tiempos)',
    license='MIT',
    entry_points={
        'console_scripts': [
            'transcriptor_voz = jetcobot_voz.transcriptor_voz:main',
            'tabla_ordenes = jetcobot_voz.tabla_ordenes:main',
            'desglose_voz = jetcobot_voz.desglose_voz:main',
            'calibrar_microfono = jetcobot_voz.calibrar_microfono:main',
        ],
    },
)
