"""Extractor geoespacial de capa Bronce (E2).

Dos fuentes abiertas, sin datos personales:
  * OpenStreetMap vía Overpass API: puntos de infraestructura contable y fiscal
    (despachos contables, asesores fiscales, oficinas del SAT y bancos). Licencia ODbL.
  * geoBoundaries (gbOpen, MEX ADM1): polígonos de las 32 entidades, derivados del
    Marco Geoestadístico del INEGI. Licencia CC BY 3.0 IGO.

Igual que el extractor de Banxico: se guarda la respuesta CRUDA con fecha y hash en
datos/bronce/manifiesto.csv. Una sola consulta por corrida y reintentos con espera
creciente, para respetar la política de uso de Overpass.
"""
import sys, time
import requests, yaml
from extractor import RAIZ, UA, guardar

ESPERAS = [30, 60, 120, 240]  # segundos entre reintentos (backoff exponencial)


def _pedir(metodo, url, **kw):
    for i, espera in enumerate([0] + ESPERAS):
        if espera:
            print(f"  reintento {i} en {espera} s", file=sys.stderr)
            time.sleep(espera)
        try:
            r = requests.request(metodo, url, headers={"User-Agent": UA}, timeout=240, **kw)
            if r.status_code in (429, 502, 503, 504):
                print(f"  {url}: HTTP {r.status_code} (servidor ocupado)", file=sys.stderr)
                continue
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            print(f"  {url}: {type(e).__name__}", file=sys.stderr)
    raise RuntimeError(f"sin respuesta de {url} tras {len(ESPERAS) + 1} intentos")


def overpass(f) -> int:
    filtros = "".join(f"nwr[{c}](area.mx);" for c in f["filtros"])
    consulta = (f'[out:json][timeout:180];area["ISO3166-1"="{f["pais"]}"][admin_level=2]->.mx;'
                f"({filtros});out center tags;")
    try:
        r = _pedir("POST", f["url_base"], data={"data": consulta})
        n = len(r.json()["elements"])
        if n == 0:
            raise ValueError("consulta sin elementos")
        print(f"overpass ({f['serie']}): {n} elementos ->", guardar(f["id"], f["serie"], r.content).name)
        return 0
    except Exception as e:
        print(f"ERROR overpass: {e}", file=sys.stderr)
        return 1


def geoboundaries(f) -> int:
    """Los polígonos casi no cambian: sólo se descargan si no hay captura previa."""
    carpeta = RAIZ / "datos" / "bronce" / f["id"] / f["serie"]
    if any(carpeta.glob("*.json")) and not f.get("forzar", False):
        print(f"geoboundaries ({f['serie']}): ya hay captura, se omite")
        return 0
    try:
        meta = _pedir("GET", f["url_base"]).json()
        r = _pedir("GET", meta["simplifiedGeometryGeoJSON"])
        n = len(r.json()["features"])
        if n != 32:
            raise ValueError(f"se esperaban 32 entidades y llegaron {n}")
        print(f"geoboundaries ({f['serie']}): {n} entidades, licencia {meta['boundaryLicense']} ->",
              guardar(f["id"], f["serie"], r.content).name)
        return 0
    except Exception as e:
        print(f"ERROR geoboundaries: {e}", file=sys.stderr)
        return 1


def denue(f) -> int:
    """Descarga masiva del DENUE (sector 54). Se guarda el zip tal cual llega."""
    import datetime as dt, io, zipfile
    carpeta = RAIZ / "datos" / "bronce" / f["id"] / f["serie"]
    previas = sorted(carpeta.glob("*.zip"))
    if previas and not f.get("forzar", False):
        edad = dt.datetime.now(dt.timezone.utc) - dt.datetime.strptime(previas[-1].stem, "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
        if edad.days < f.get("vigencia_dias", 90):
            print(f"denue ({f['serie']}): captura de hace {edad.days} dias, vigente; se omite")
            return 0
    try:
        r = _pedir("GET", f["url_base"])
        nombres = zipfile.ZipFile(io.BytesIO(r.content)).namelist()
        if not any(n.startswith("conjunto_de_datos/") and n.endswith(".csv") for n in nombres):
            raise ValueError(f"el zip no trae el conjunto de datos: {nombres}")
        print(f"denue ({f['serie']}): {len(r.content):,} bytes ->", guardar(f["id"], f["serie"], r.content, ext="zip").name)
        return 0
    except Exception as e:
        print(f"ERROR denue: {e}", file=sys.stderr)
        return 1


def main():
    cfg = yaml.safe_load(open(RAIZ / "config" / "fuentes.yml", encoding="utf-8"))
    fallos = 0
    for f in cfg["fuentes"]:
        if f.get("activa", True) is False:
            continue
        if f["id"] == "osm_overpass":
            fallos += overpass(f)
        elif f["id"] == "geoboundaries":
            fallos += geoboundaries(f)
        elif f["id"] == "inegi_denue":
            fallos += denue(f)
    sys.exit(1 if fallos else 0)


if __name__ == "__main__":
    main()
