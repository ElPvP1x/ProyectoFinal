"""Linaje y trazabilidad (E2): de un registro de Oro a su respuesta cruda en Bronce.

Cadena de custodia:
  Bronce  datos/bronce/<fuente>/<serie>/<captura>.json  + fila en manifiesto.csv (bytes y SHA-256)
  Plata   cada fila lleva origen, fecha_ingesta, archivo_bronce y sha256_bronce
  Oro     cada mes lleva fecha_ingesta y archivos_bronce; el detalle por serie esta en datos/oro/linaje.csv

Uso:  python src/linaje.py 2024-06      -> muestra los registros crudos de Bronce que formaron ese mes
"""
import csv, datetime as dt, hashlib, json, pathlib, sys
import pandas as pd

RAIZ = pathlib.Path(__file__).resolve().parents[1]


def sha256(ruta: pathlib.Path) -> str:
    return hashlib.sha256(ruta.read_bytes()).hexdigest()


def manifiesto(raiz=RAIZ) -> dict:
    """{(fuente, serie, archivo): sha256} segun datos/bronce/manifiesto.csv."""
    ruta = raiz / "datos" / "bronce" / "manifiesto.csv"
    if not ruta.exists():
        return {}
    with open(ruta, encoding="utf-8") as f:
        return {(r[1], r[2], r[3]): r[5] for r in csv.reader(f) if len(r) >= 6}


def fecha_ingesta(captura: str) -> str:
    """20261116T231052Z -> 2026-11-16T23:10:52Z"""
    return dt.datetime.strptime(captura, "%Y%m%dT%H%M%SZ").strftime("%Y-%m-%dT%H:%M:%SZ")


def ficha_archivo(raiz, ruta: pathlib.Path, verificar=True) -> dict:
    fuente, serie = ruta.parent.parent.name, ruta.parent.name
    h = sha256(ruta)
    if verificar:
        esperado = manifiesto(raiz).get((fuente, serie, ruta.name))
        if esperado is None:
            raise ValueError(f"{ruta.name} ({serie}) no esta en el manifiesto: no se puede probar su origen")
        if esperado != h:
            raise ValueError(f"{ruta.name} ({serie}) cambio despues de la captura: hash distinto al del manifiesto")
    return {"fuente": fuente, "serie": serie,
            "archivo_bronce": ruta.relative_to(raiz).as_posix(),
            "sha256_bronce": h, "fecha_ingesta": fecha_ingesta(ruta.stem)}


def tabla_mensual(raiz=RAIZ) -> pd.DataFrame:
    """Linaje largo: una fila por (mes, serie) con el archivo de Bronce y cuantos registros aporto."""
    filas = []
    for ruta in sorted((raiz / "datos" / "plata").glob("*.csv")):
        if ruta.stem.startswith("geo_"):   # la capa geoespacial lleva su linaje por punto (geo.py)
            continue
        d = pd.read_csv(ruta, parse_dates=["fecha"])
        if "archivo_bronce" not in d:
            continue
        d["mes"] = d["fecha"].dt.to_period("M").astype(str)
        g = d.groupby("mes")
        t = pd.DataFrame({
            "serie": ruta.stem,
            "archivo_bronce": g["archivo_bronce"].first(),
            "sha256_bronce": g["sha256_bronce"].first(),
            "fecha_ingesta": g["fecha_ingesta"].first(),
            "registros_bronce": g["imputado"].apply(lambda s: int((~s.astype(bool)).sum())),
            "registros_imputados": g["imputado"].apply(lambda s: int(s.astype(bool).sum())),
            "primera_fecha": g["fecha"].min().dt.date.astype(str),
            "ultima_fecha": g["fecha"].max().dt.date.astype(str),
        })
        filas.append(t.reset_index())
    cols = ["mes", "serie", "archivo_bronce", "sha256_bronce", "fecha_ingesta",
            "registros_bronce", "registros_imputados", "primera_fecha", "ultima_fecha"]
    return pd.concat(filas, ignore_index=True)[cols].sort_values(["mes", "serie"]) if filas else pd.DataFrame(columns=cols)


def _registros_crudos(ruta: pathlib.Path):
    d = json.loads(ruta.read_text(encoding="utf-8"))
    if "bmx" in d:
        return [(o.get("fecha"), o.get("dato"), dt.datetime.strptime(o["fecha"], "%d/%m/%Y"))
                for o in d["bmx"]["series"][0].get("datos", [])]
    if "Series" in d:
        return [(o.get("TIME_PERIOD"), o.get("OBS_VALUE"), dt.datetime.strptime(o["TIME_PERIOD"], "%Y/%m"))
                for o in d["Series"][0]["OBSERVATIONS"]]
    return []


def rastrear(mes: str, raiz=RAIZ) -> pd.DataFrame:
    """Registros crudos de Bronce (texto tal como llego) que formaron el mes de Oro indicado."""
    lin = pd.read_csv(raiz / "datos" / "oro" / "linaje.csv", dtype=str)
    lin = lin[lin["mes"] == mes]
    if lin.empty:
        raise KeyError(f"{mes} no esta en datos/oro/linaje.csv")
    salida = []
    for _, r in lin.iterrows():
        ruta = raiz / r["archivo_bronce"]
        if sha256(ruta) != r["sha256_bronce"]:
            raise ValueError(f"{r['archivo_bronce']}: el hash no coincide con el linaje")
        for f_txt, d_txt, f in _registros_crudos(ruta):
            if f.strftime("%Y-%m") == mes:
                salida.append({"serie": r["serie"], "archivo_bronce": r["archivo_bronce"],
                               "fecha_ingesta": r["fecha_ingesta"], "fecha_texto": f_txt, "dato_texto": d_txt})
    return pd.DataFrame(salida)


if __name__ == "__main__":
    mes = sys.argv[1] if len(sys.argv) > 1 else "2024-06"
    t = rastrear(mes)
    print(f"Mes {mes}: {len(t)} registros crudos de Bronce")
    for (serie, archivo, ing), g in t.groupby(["serie", "archivo_bronce", "fecha_ingesta"]):
        print(f"\n{serie}  <-  {archivo}  (ingesta {ing}, {len(g)} registros)")
        print(g[["fecha_texto", "dato_texto"]].head(5).to_string(index=False))
