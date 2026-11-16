# ruff: noqa: E501  (mensajes largos)
"""Control de escalado del backend del UAT, después de cada publicación.

Solo lectura (``gcloud run services describe`` y ``revisions list``). Falla
(código 1) si algo deja una instancia encendida sin uso:

1. el servicio tiene un mínimo de instancias mayor que 0;
2. la plantilla (la de la próxima revisión) tiene un mínimo mayor que 0;
3. el tráfico no está 100 % en una sola revisión (o no en ``--esperada``);
4. queda alguna etiqueta (cada revisión etiquetada mantiene sus instancias
   mínimas aunque no reciba tráfico), salvo ``--permitir-etiquetas`` durante
   la prueba de una revisión nueva;
5. una revisión referenciada por el tráfico o por una etiqueta tiene un
   mínimo mayor que 0.

Las revisiones sin tráfico ni etiqueta conservan su mínimo (inmutable), pero
no levantan instancias: se listan solo como información.

    python supabase/scripts/validacion_uat/verificar_escalado_uat.py --esperada rt-rma-uat-api-00036-jis

Sin credenciales: usa la sesión de ``gcloud`` de quien lo ejecuta.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys

MIN_REVISION = "autoscaling.knative.dev/minScale"
MIN_SERVICIO = "run.googleapis.com/minScale"


def gcloud(*args: str) -> object:
    ejecutable = shutil.which("gcloud") or "gcloud"
    salida = subprocess.run(
        [ejecutable, *args, "--format=json"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return json.loads(salida)


def minimo(anotaciones: dict, clave: str) -> int:
    return int(anotaciones.get(clave, "0") or "0")


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--servicio", default="rt-rma-uat-api")
    p.add_argument("--proyecto", default="rosariotecno-460217")
    p.add_argument("--region", default="southamerica-east1")
    p.add_argument("--esperada", help="revisión que debe tener el 100 %%")
    p.add_argument(
        "--permitir-etiquetas",
        action="store_true",
        help="durante la prueba de una revisión nueva, antes de quitar su etiqueta",
    )
    a = p.parse_args()
    lugar = ["--project", a.proyecto, "--region", a.region]

    servicio = gcloud("run", "services", "describe", a.servicio, *lugar)
    revisiones = gcloud(
        "run", "revisions", "list", "--service", a.servicio, *lugar
    )
    minimos = {
        r["metadata"]["name"]: minimo(
            r["metadata"].get("annotations", {}), MIN_REVISION
        )
        for r in revisiones
    }
    trafico = servicio["status"].get("traffic", [])
    plantilla = servicio["spec"]["template"]["metadata"]
    fallas: list[str] = []

    n = minimo(servicio["metadata"].get("annotations", {}), MIN_SERVICIO)
    if n > 0:
        fallas.append(f"el servicio tiene mínimo {n}")
    n = minimo(plantilla.get("annotations", {}), MIN_REVISION)
    if n > 0:
        fallas.append(
            f"la plantilla tiene mínimo {n}: lo hereda la próxima revisión"
        )

    con_trafico = [t for t in trafico if t.get("percent")]
    if len(con_trafico) != 1 or con_trafico[0]["percent"] != 100:
        fallas.append(
            f"el tráfico no está 100 % en una revisión: {con_trafico}"
        )
    elif a.esperada and con_trafico[0]["revisionName"] != a.esperada:
        fallas.append(
            f"el 100 % está en {con_trafico[0]['revisionName']}, no en {a.esperada}"
        )

    etiquetas = [
        (t["tag"], t["revisionName"]) for t in trafico if t.get("tag")
    ]
    if etiquetas and not a.permitir_etiquetas:
        fallas.append(f"quedan etiquetas: {etiquetas}")

    referenciadas = {t["revisionName"] for t in trafico}
    for nombre in sorted(referenciadas):
        if minimos.get(nombre, 0) > 0:
            fallas.append(
                f"{nombre} recibe tráfico o tiene etiqueta y su mínimo es {minimos[nombre]}"
            )

    print(f"Servicio {a.servicio}: {len(revisiones)} revisiones")
    for t in trafico:
        print(
            f"  tráfico {t.get('percent', 0):>3} %  {t['revisionName']}"
            + (f"  etiqueta {t['tag']}" if t.get("tag") else "")
            + f"  mínimo {minimos.get(t['revisionName'], 0)}"
        )
    inactivas = sorted(
        r for r, m in minimos.items() if m > 0 and r not in referenciadas
    )
    print(
        f"  {len(inactivas)} revisiones sin tráfico ni etiqueta con mínimo > 0 "
        "(inmutable; sin instancias mientras no se las referencie)"
    )
    for f in fallas:
        print(f"FALLA: {f}")
    print("RESULTADO:", "OK" if not fallas else f"{len(fallas)} FALLAS")
    return 0 if not fallas else 1


if __name__ == "__main__":
    sys.exit(main())
