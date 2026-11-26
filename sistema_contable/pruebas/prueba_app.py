"""
Prueba de las rutas web (boveda, descarga SAT simulada) y de la consulta de estatus/cancelacion
con un SAT SIMULADO. No contacta al SAT. Todo con e.firma y CFDI sinteticos.
"""
import io, os, shutil, sys, tempfile, json

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(AQUI))
sys.path.insert(0, AQUI)
import app as A
import boveda as B
import descarga_sat as D
import estatus_sat as E
import procesador_cfdi as P
from utiles_prueba import cfdi_xml, e_firma_falsa
import prueba_descarga_sat_api as S      # SAT simulado compartido

CLIENTE, PROV = "AAA010101AAA", "CCC010101CC2"
fallas = []
def espera(n, c, d=""):
    print(("OK   " if c else "FALLA"), f"{n:<52}", d)
    if not c: fallas.append(n)

carpeta = tempfile.mkdtemp(prefix="app_prueba_")
A.BOVEDA = B.Boveda(os.path.join(carpeta, "boveda.enc"))
A.DESCARGA = D.DescargaSAT(A.BOVEDA, os.path.join(carpeta, "descargas"), api=S.SATSimulado)
A.app.config["TESTING"] = True
cli = A.app.test_client()
H = {"X-Sistema": "1"}
FRASE = "mi frase maestra muy larga 2026"

# ---- guardia de seguridad ----
espera("sin cabecera X-Sistema: 403", cli.get("/boveda/estado").status_code == 403)
espera("host ajeno (DNS rebinding): 403", cli.get("/boveda/estado", headers=H, base_url="http://evil.example.com").status_code == 403)
espera("con cabecera y host local: 200", cli.get("/boveda/estado", headers=H).status_code == 200)
espera("las paginas siguen abiertas", cli.get("/").status_code == 200 and cli.get("/contribuyentes").status_code == 200)

# ---- boveda por HTTP ----
j = cli.post("/boveda/crear", json={"frase": "corta"}, headers=H).get_json()
espera("frase corta se rechaza por HTTP", not j["ok"], j["error"][:50])
espera("crear", cli.post("/boveda/crear", json={"frase": FRASE}, headers=H).get_json()["ok"])
cli.post("/boveda/cerrar", headers=H)
espera("lista con la boveda cerrada: 401", cli.get("/boveda/lista", headers=H).status_code == 401)
espera("abrir con frase mala: 401", cli.post("/boveda/abrir", json={"frase": "otra frase muy distinta"}, headers=H).status_code == 401)
espera("abrir", cli.post("/boveda/abrir", json={"frase": FRASE}, headers=H).get_json()["ok"])

cer, key, pw = e_firma_falsa(rfc=CLIENTE)
r = cli.post("/boveda/agregar", headers=H, content_type="multipart/form-data",
             data={"cer": (io.BytesIO(cer), "a.cer"), "key": (io.BytesIO(key), "a.key"), "password": pw, "nombre": "Cliente SA"})
j = r.get_json()
espera("agregar e.firma por HTTP", j["ok"] and j["contribuyente"]["rfc"] == CLIENTE, str(j.get("error", "")))
espera("la respuesta no trae secretos", pw not in r.get_data(as_text=True) and "key_b64" not in r.get_data(as_text=True))
r = cli.get("/boveda/lista", headers=H)
espera("la lista no trae secretos", pw not in r.get_data(as_text=True) and "key_b64" not in r.get_data(as_text=True))
espera("revelar con frase mala: 401", cli.post("/boveda/revelar", json={"rfc": CLIENTE, "frase": "equivocada equivocada"}, headers=H).status_code == 401)
espera("revelar con la frase correcta", cli.post("/boveda/revelar", json={"rfc": CLIENTE, "frase": FRASE}, headers=H).get_json()["password"] == pw)

# ---- descarga SAT simulada por HTTP ----
j = cli.post("/sat/solicitar", json={"rfc": CLIENTE, "desde": "2026-08-01", "hasta": "2026-08-31", "tipo": "recibidos", "formato": "CFDI"}, headers=H).get_json()
espera("solicitar por HTTP", j["ok"] and j["solicitud"]["id"].startswith("SOL-"), str(j.get("error", "")))
sid = j["solicitud"]["id"]
espera("fecha mal escrita se explica", "AAAA-MM-DD" in cli.post("/sat/solicitar", json={"rfc": CLIENTE, "desde": "01/08/2026", "hasta": "2026-08-31"}, headers=H).get_json()["error"])
cli.post("/sat/verificar", json={"id": sid}, headers=H)
j = cli.post("/sat/verificar", json={"id": sid}, headers=H).get_json()
espera("verificar: terminada", j["ok"] and j["solicitud"]["estado"] == "Terminada")
j = cli.post("/sat/descargar", json={"id": sid}, headers=H).get_json()
espera("descargar por HTTP", j["ok"] and len(j["solicitud"]["archivos"]) == 1)
j = cli.post("/sat/procesar", json={"ids": [sid], "rfc": CLIENTE}, headers=H).get_json()
espera("procesar lo descargado devuelve el dashboard", j["ok"] and j["totales"]["total_deducible"] == 3480.0, str(j.get("error", "")))
idr = j["id_sesion"]
j2 = cli.get(f"/resultado/{idr}", headers=H).get_json()
espera("el resultado se puede reabrir (?resultado=)", j2["ok"] and j2["id_sesion"] == idr)
espera("la pagina principal sabe abrirlo", b"/resultado/" in cli.get("/").data)

# ---- cancelaciones: consulta de estatus con un SAT simulado ----
uuid_canc, uuid_nf, uuid_ok, uuid_proc = "C" * 36, "N" * 36, "V" * 36, "P" * 36
xmls = {"cancelada": cfdi_xml(uuid_canc, PROV, CLIENTE, 1000), "no_encontrada": cfdi_xml(uuid_nf, PROV, CLIENTE, 2000),
        "vigente": cfdi_xml(uuid_ok, PROV, CLIENTE, 3000), "en_proceso": cfdi_xml(uuid_proc, PROV, CLIENTE, 4000)}
dx = os.path.join(carpeta, "xml"); os.makedirs(dx)
for n, x in xmls.items():
    open(os.path.join(dx, n + ".xml"), "w", encoding="utf-8").write(x)

consultas = []
def sat_falso(emisor, receptor, total, uuid, timeout=15):
    consultas.append((emisor, receptor, E.total_sat(total), uuid))
    if uuid == uuid_canc:
        return {"codigo_estatus": "S - Comprobante obtenido satisfactoriamente.", "es_cancelable": "Cancelable sin aceptación",
                "estado": "Cancelado", "estatus_cancelacion": "Cancelado sin aceptación", "validacion_efos": "200"}
    if uuid == uuid_nf:
        return {"codigo_estatus": "N - 602: Comprobante no encontrado.", "es_cancelable": "", "estado": "No Encontrado",
                "estatus_cancelacion": "", "validacion_efos": ""}
    if uuid == uuid_proc:
        return {"codigo_estatus": "S - ok", "es_cancelable": "Cancelable con aceptación", "estado": "Vigente",
                "estatus_cancelacion": "En proceso", "validacion_efos": "200"}
    return {"codigo_estatus": "S - ok", "es_cancelable": "Cancelable sin aceptación", "estado": "Vigente",
            "estatus_cancelacion": "", "validacion_efos": "200"}

E.consultar = sat_falso
cfg = P.cargar_config()
cfg.update({"usar_perfiles": False, "rfc_contribuyente": CLIENTE, "convertir_a_mxn": False, "verificar_estatus_sat": True,
            "estatus_sat_cache": os.path.join(carpeta, "cache.json"), "estatus_sat_hilos": 2})
df, tot, diag = P.procesar_archivos([dx], cfg)
df["caso"] = df["Archivo XML"].str.replace(".xml", "", regex=False)
r = df.set_index("caso")
espera("la cancelada NO suma y se explica", not r.loc["cancelada", "_Suma"] and r.loc["cancelada", "Clasificacion"] == "Cancelado")
espera("la vigente suma", r.loc["vigente", "_Suma"] and r.loc["vigente", "Importe Computado"] == 3480.0)
espera("no encontrada: suma pero con alerta", r.loc["no_encontrada", "_Suma"] and "no encontro" in r.loc["no_encontrada", "Alertas"], r.loc["no_encontrada", "Alertas"][:50])
espera("cancelacion en proceso: alerta", "EN PROCESO" in r.loc["en_proceso", "Alertas"], r.loc["en_proceso", "Alertas"][:50])
espera("manda el total en formato SAT", ("CCC010101CC2", CLIENTE, "0000001160.000000", uuid_canc) in consultas)
espera("el resumen cuenta cancelados y no encontrados", tot["estatus_sat"]["cancelados"] == 1 and tot["estatus_sat"]["no_encontrados"] == 1, str(tot["estatus_sat"]))
n1 = len(consultas)
P.procesar_archivos([dx], cfg)
espera("la segunda corrida usa el cache (no repite)", len(consultas) == n1, f"{len(consultas)} consultas")

# si el SAT falla: no se inventa nada
def sat_caido(*a, **k):
    raise E.requests.ConnectionError("sin internet")
E.consultar = sat_caido
cfg["estatus_sat_cache"] = os.path.join(carpeta, "otro_cache.json")
E.time.sleep = lambda s: None
df2, tot2, diag2 = P.procesar_archivos([dx], cfg)
espera("SAT caido: todo conserva su estatus y se avisa", df2["_Suma"].all() and tot2["estatus_sat"]["errores"] == 4,
       f"errores={tot2['estatus_sat']['errores']}")

shutil.rmtree(carpeta, ignore_errors=True)
print("\nFALLAS:", fallas if fallas else "ninguna")
sys.exit(1 if fallas else 0)
