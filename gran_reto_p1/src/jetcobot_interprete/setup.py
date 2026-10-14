from glob import glob
from setuptools import setup

package_name = "jetcobot_interprete"

setup(
    name=package_name,
    version="1.0.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", glob("launch/*.py")),
        ("share/" + package_name + "/config", glob("config/*.yaml")),
        ("share/" + package_name + "/datos", glob("datos/*.csv")),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="Equipo",
    maintainer_email="equipo@esan.edu.pe",
    description="Interprete de ordenes en lenguaje natural (LAYA + respaldo por palabras clave)",
    license="MIT",
    entry_points={
        "console_scripts": [
            "interprete_ordenes = jetcobot_interprete.interprete_ordenes:main",
            "medir_latencia = jetcobot_interprete.medir_latencia:main",
            "evaluar_exactitud = jetcobot_interprete.evaluar_exactitud:main",
            "laya_simulado = jetcobot_interprete.laya_simulado:main",
        ],
    },
)
