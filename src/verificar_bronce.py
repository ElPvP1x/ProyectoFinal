"""Cuenta los periodos (meses distintos) de la captura mas reciente de cada serie en datos/bronce."""
import json, pathlib, sys

RAIZ = pathlib.Path(__file__).resolve().parents[1]
MINIMO = 36

def meses(ruta):
    d = json.loads(ruta.read_text(encoding="utf-8"))
    if "bmx" in d:                                    # Banxico: fecha dd/mm/aaaa
        fechas = [o["fecha"] for o in d["bmx"]["series"][0].get("datos", [])]
        return {f[3:] for f in fechas}                # mm/aaaa
    if "Series" in d:                                 # INEGI: TIME_PERIOD aaaa/mm
        return {o["TIME_PERIOD"][:7] for o in d["Series"][0]["OBSERVATIONS"]}
    return set()

ok = True
for carpeta in sorted((RAIZ / "datos" / "bronce").glob("*/*")):
    snaps = sorted(carpeta.glob("*.json"))
    if not snaps:
        continue
    n = len(meses(snaps[-1]))
    estado = "OK" if n >= MINIMO else "FALTAN"
    ok &= n >= MINIMO
    print(f"{carpeta.parent.name}/{carpeta.name}: {n} periodos mensuales [{estado}]")
sys.exit(0 if ok else 1)
