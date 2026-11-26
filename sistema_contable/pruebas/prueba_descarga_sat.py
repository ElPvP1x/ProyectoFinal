"""
Prueba de descarga_sat.py con un SAT SIMULADO (no se contacta al SAT real) y e.firma sinteticas.
Recorre el flujo: boveda -> solicitar -> verificar -> descargar -> procesar el ZIP con el motor.
NO prueba el protocolo contra el servidor real del SAT: eso exige una e.firma verdadera.
"""
import base64, io, os, shutil, sys, tempfile, zipfile
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boveda as B
import descarga_sat as D
import procesador_cfdi as P
from utiles_prueba import cfdi_xml, e_firma_falsa

CLIENTE, PROV = "AAA010101AAA", "CCC010101CC2"
fallas = []
def espera(n, c, d=""):
    print(("OK   " if c else "FALLA"), f"{n:<50}", d)
    if not c: fallas.append(n)
def lanza(n, fn, texto):
    try:
        fn(); espera(n, False, "no lanzo error")
    except D.DescargaError as e:
        espera(n, texto.lower() in str(e).lower(), str(e)[:80])


from prueba_descarga_sat_api import SATSimulado, ZIP_B64   # noqa: E402


carpeta = tempfile.mkdtemp(prefix="descarga_prueba_")
v = B.Boveda(os.path.join(carpeta, "boveda.enc"))
v.crear("mi frase maestra muy larga 2026")
cer, key, pw = e_firma_falsa(rfc=CLIENTE)
v.agregar(cer, key, pw)
d = D.DescargaSAT(v, os.path.join(carpeta, "descargas"), api=SATSimulado)

lanza("fechas invertidas", lambda: d.solicitar(CLIENTE, date(2026, 9, 1), date(2026, 8, 1)), "anterior a la inicial")
lanza("fecha futura", lambda: d.solicitar(CLIENTE, date(2026, 8, 1), date(2099, 1, 1)), "futura")
lanza("recibidos cancelados en XML no existe", lambda: d.solicitar(CLIENTE, date(2026, 8, 1), date(2026, 8, 31), estado="Cancelado"), "solo entrega en xml")
lanza("RFC que no esta en la boveda", lambda: d.solicitar("ZZZ010101ZZZ", date(2026, 8, 1), date(2026, 8, 31)), "no esta en la boveda")

SATSimulado.rechazar_solicitud = True
lanza("el SAT rechaza: se explica el codigo", lambda: d.solicitar(CLIENTE, date(2026, 8, 1), date(2026, 8, 31)), "5002")
SATSimulado.rechazar_solicitud = False

sol = d.solicitar(CLIENTE, date(2026, 8, 1), date(2026, 8, 31), tipo="recibidos")
espera("solicitud aceptada y registrada", sol["id"] == "SOL-0001" and d.listar(CLIENTE)[0]["estado"] == "Aceptada")
llam = [x for x in SATSimulado.llamadas if x[0] == "solicitar"][-1]
espera("recibidos pide con rfc_receptor y fechas completas",
       llam[1] == "SolicitaDescargaRecibidos" and llam[5].get("rfc_receptor") == CLIENTE
       and llam[3].hour == 0 and llam[4].hour == 23 and llam[4].minute == 59, str(llam[5]))
espera("uso la e.firma de la boveda", ("fiel", len(cer), len(key), pw) in SATSimulado.llamadas)

lanza("descargar antes de que termine", lambda: d.descargar("SOL-0001"), "aun no esta terminada")
e1 = d.verificar("SOL-0001")
espera("primera verificacion: en proceso", e1["estado"] == "En proceso", e1["estado"])
e2 = d.verificar("SOL-0001")
espera("segunda verificacion: terminada con paquete", e2["estado"] == "Terminada" and e2["paquetes"] == ["PAQ-1"] and e2["numero_cfdis"] == 2)

e3 = d.descargar("SOL-0001")
ruta = e3["archivos"][0]
espera("el ZIP queda en descargas/RFC/tipo/", os.path.isfile(ruta) and f"{CLIENTE}{os.sep}recibidos" in ruta, os.path.relpath(ruta, carpeta))
espera("el ZIP es el que mando el SAT", zipfile.ZipFile(ruta).namelist() == ["a.xml", "b.xml"])
n_antes = len([x for x in SATSimulado.llamadas if x[0] == "descargar"])
d.descargar("SOL-0001")
espera("no vuelve a bajar lo que ya tiene", len([x for x in SATSimulado.llamadas if x[0] == "descargar"]) == n_antes)

emit = d.solicitar(CLIENTE, date(2026, 8, 1), date(2026, 8, 31), tipo="emitidos")
llam = [x for x in SATSimulado.llamadas if x[0] == "solicitar"][-1]
espera("emitidos pide con rfc_emisor", llam[1] == "SolicitaDescargaEmitidos" and llam[5].get("rfc_emisor") == CLIENTE)

acc = " | ".join(b["accion"] for b in v.bitacora(50))
espera("la boveda registra cada uso de la e.firma", acc.count("uso de e.firma") >= 5, str(acc.count("uso de e.firma")))

# ---- el ZIP descargado entra directo al motor ----
cfg = P.cargar_config(); cfg.update({"usar_perfiles": False, "rfc_contribuyente": CLIENTE, "convertir_a_mxn": False})
df, tot, _ = P.procesar_archivos(d.rutas_zip(["SOL-0001"]), cfg)
espera("el motor procesa el ZIP descargado", len(df) == 2 and tot["total_deducible"] == 3480.0, f"{len(df)} CFDI, deducible {tot['total_deducible']}")
lanza("procesar sin archivos descargados", lambda: d.rutas_zip([emit["id"]]), "no tienen archivos")

shutil.rmtree(carpeta, ignore_errors=True)
print("\nFALLAS:", fallas if fallas else "ninguna")
sys.exit(1 if fallas else 0)
