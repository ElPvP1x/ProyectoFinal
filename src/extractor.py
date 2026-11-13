"""Extractor etico de capa Bronce: guarda la respuesta CRUDA tal cual llega, con fecha y hash."""
import hashlib, json, os, sys, time, datetime as dt, pathlib
import requests, yaml

UA = "ObservatorioContabilidad-Academico/0.1 (proyecto escolar; contacto en el README del repo)"
RAIZ = pathlib.Path(__file__).resolve().parents[1]
PAUSA = 2  # segundos entre consultas: cortesia, no saturar el servidor

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
    fallos = 0
    for s in f["series"]:
        url = f"{f['url_base']}/{s['id']}/datos/{f['desde']}/{hoy}"
        try:
            r = requests.get(url, headers={"Bmx-Token": token, "User-Agent": UA, "Accept": "application/json"}, timeout=60)
            r.raise_for_status()
            datos = r.json()["bmx"]["series"][0].get("datos", [])
            if not datos:
                raise ValueError("serie vacia: revisar el id en el catalogo SIE")
            print(f"{s['id']} ({s['nombre']}): {len(datos)} observaciones ->", guardar(f["id"], s["nombre"], r.content).name)
        except Exception as e:
            fallos += 1
            print(f"ERROR {s['id']} ({s['nombre']}): {e}", file=sys.stderr)
        time.sleep(PAUSA)
    return fallos

def inegi(f):
    token = os.environ.get(f["token_env"])
    if not token:
        print(f"AVISO: falta {f['token_env']}, se omite {f['id']}", file=sys.stderr)
        return 0
    fallos = 0
    for s in f["series"]:
        # El token va en la URL por diseno de la API: nunca se imprime.
        url = f"{f['url_base']}/{s['id']}/es/{f['area']}/false/BIE/2.0/{token}?type=json"
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=60)
            r.raise_for_status()
            obs = r.json()["Series"][0]["OBSERVATIONS"]
            if not obs:
                raise ValueError("serie vacia: revisar el id en el BIE")
            print(f"{s['id']} ({s['nombre']}): {len(obs)} observaciones ->", guardar(f["id"], s["nombre"], r.content).name)
        except Exception as e:
            fallos += 1
            print(f"ERROR {s['id']} ({s['nombre']}): {type(e).__name__}", file=sys.stderr)
        time.sleep(PAUSA)
    return fallos

def main():
    cfg = yaml.safe_load(open(RAIZ / "config" / "fuentes.yml", encoding="utf-8"))
    fallos = 0
    for f in cfg["fuentes"]:
        if f.get("activa", True) is False:
            continue
        if f["id"] == "banxico_sie":
            fallos += banxico(f)
        elif f["id"] == "inegi_bie":
            fallos += inegi(f)
    sys.exit(1 if fallos else 0)

if __name__ == "__main__":
    main()
