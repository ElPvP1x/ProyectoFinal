"""Extractor etico de capa Bronce: guarda la respuesta CRUDA tal cual llega, con fecha y hash."""
import hashlib, json, os, sys, time, datetime as dt, pathlib
import requests, yaml

UA = "ObservatorioAgro-Academico/0.1 (proyecto escolar; contacto en el README del repo)"
RAIZ = pathlib.Path(__file__).resolve().parents[1]

def guardar(fuente, serie, contenido: bytes):
    ahora = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    carpeta = RAIZ / "datos" / "bronce" / fuente / serie
    carpeta.mkdir(parents=True, exist_ok=True)
    ruta = carpeta / f"{ahora}.json"
    ruta.write_bytes(contenido)
    h = hashlib.sha256(contenido).hexdigest()
    with open(RAIZ / "datos" / "bronce" / "manifiesto.csv", "a", encoding="utf-8") as m:
        m.write(f"{ahora},{fuente},{serie},{ruta.name},{len(contenido)},{h}\n")
    return ruta

def banxico(f):
    token = os.environ.get(f["token_env"])
    if not token:
        sys.exit(f"Falta el secreto {f['token_env']}")
    hoy = dt.date.today().isoformat()
    for s in f["series"]:
        url = f"{f['url_base']}/{s['id']}/datos/{f['desde']}/{hoy}"
        r = requests.get(url, headers={"Bmx-Token": token, "User-Agent": UA, "Accept": "application/json"}, timeout=60)
        r.raise_for_status()
        n = len(r.json()["bmx"]["series"][0].get("datos", []))
        print(f"{s['id']}: {n} periodos ->", guardar(f["id"], s["nombre"], r.content))
        time.sleep(2)  # cortesia: no saturar el servidor

def main():
    cfg = yaml.safe_load(open(RAIZ / "config" / "fuentes.yml", encoding="utf-8"))
    for f in cfg["fuentes"]:
        if f.get("activa", True) is False:
            continue
        if f["id"] == "banxico_sie":
            banxico(f)

if __name__ == "__main__":
    main()
