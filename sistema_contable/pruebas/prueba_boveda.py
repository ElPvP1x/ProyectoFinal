"""Prueba de boveda.py con e.firma SINTETICAS (certificados autofirmados generados aqui, sin valor legal)."""
import json, os, shutil, sys, tempfile, time
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import boveda as B
from utiles_prueba import e_firma_falsa
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier


fallas = []
def espera(nombre, cond, detalle=""):
    print(("OK   " if cond else "FALLA"), f"{nombre:<46}", detalle)
    if not cond:
        fallas.append(nombre)

def lanza(nombre, fn, texto):
    try:
        fn()
        espera(nombre, False, "no lanzo error")
    except B.BovedaError as e:
        espera(nombre, texto.lower() in str(e).lower(), str(e)[:70])


carpeta = tempfile.mkdtemp(prefix="boveda_prueba_")
ruta = os.path.join(carpeta, "boveda.enc")
FRASE = "mi frase maestra muy larga 2026"
v = B.Boveda(ruta)

lanza("frase corta se rechaza", lambda: v.crear("corta"), "al menos")
v.crear(FRASE)
espera("boveda creada y abierta", v.existe() and v.abierta())
v.bloquear()
espera("bloquear la cierra", not v.abierta())
lanza("sin abrir no se puede listar", v.listar, "cerrada")
lanza("frase incorrecta", lambda: v.desbloquear("otra frase totalmente distinta"), "incorrecta")
v.desbloquear(FRASE)

cer, key, pw = e_firma_falsa()
info = v.agregar(cer, key, pw, notas="cliente de prueba")
espera("agregar valida y lee el RFC del .cer", info["rfc"] == "AAA010101AAA" and info["tipo_persona"] == "moral", str(info["vence"]))
espera("lee el nombre y la serie", info["nombre"].startswith("EMPRESA") and info["serie"] == "30001000000500003416", info["serie"])

lanza("contrasena del .key incorrecta", lambda: v.agregar(cer, key, "mala-contrasena"), "contrasena no abre")
cer2, key2, _ = e_firma_falsa(rfc="BBB020202BBB", password="otra")
lanza(".key de otra e.firma", lambda: v.agregar(cer, key2, "otra"), "no corresponde")
lanza("RFC capturado distinto al del .cer", lambda: v.agregar(cer2, key2, "otra", rfc="ZZZ010101ZZZ"), "no coincide")
cer_v, key_v, pw_v = e_firma_falsa(rfc="CCC030303CCC", dias_validez=30, desde=-400)
lanza("certificado vencido se rechaza", lambda: v.agregar(cer_v, key_v, pw_v), "no esta vigente")
lanza("el .cer no es un certificado", lambda: v.agregar(b"basura", key, pw), "no es un certificado")
v.agregar(cer2, key2, "otra", nombre="Segundo cliente")

lista = v.listar()
espera("listar devuelve 2 y sin secretos", len(lista) == 2 and all("password" not in c and "key_b64" not in c and "cer_b64" not in c for c in lista),
       ", ".join(c["rfc"] for c in lista))
espera("dias restantes y vigente", lista[0]["vigente"] and lista[0]["dias_restantes"] > 300, str(lista[0]["dias_restantes"]))

# lo que queda en disco no revela nada
crudo = open(ruta, "rb").read()
espera("el archivo no contiene RFC, nombre ni contrasena en claro",
       all(x not in crudo for x in (b"AAA010101AAA", b"EMPRESA", pw.encode(), b"clave-de-prueba")))

c, k, p = v.obtener_fiel("aaa010101aaa")
espera("obtener_fiel devuelve lo mismo que se guardo", (c, k, p) == (cer, key, pw))
lanza("revelar contrasena con frase mala", lambda: v.revelar_password("AAA010101AAA", "frase equivocada larga"), "incorrecta")
espera("revelar contrasena con la frase correcta", v.revelar_password("AAA010101AAA", FRASE) == pw)
acciones = " | ".join(b["accion"] for b in v.bitacora())
espera("la bitacora registra usos y revelaciones", "uso de e.firma" in acciones and "contrasena revelada" in acciones)
espera("la bitacora no guarda secretos", pw not in json.dumps(v.bitacora()))

# reabrir desde cero (como en otra computadora con el mismo archivo)
copia = os.path.join(carpeta, "otra_compu.enc")
v.respaldar(copia)
w = B.Boveda(copia)
w.desbloquear(FRASE)
espera("abrir la copia en otro equipo", len(w.listar()) == 2)

# cambiar frase
v.cambiar_frase(FRASE, "una frase nueva igual de larga 2027")
v.bloquear()
lanza("la frase vieja ya no abre", lambda: v.desbloquear(FRASE), "incorrecta")
v.desbloquear("una frase nueva igual de larga 2027")
espera("los datos sobreviven al cambio de frase", len(v.listar()) == 2)

# conflicto entre equipos
a = B.Boveda(os.path.join(carpeta, "compartida.enc")); a.crear(FRASE)
b = B.Boveda(os.path.join(carpeta, "compartida.enc")); b.desbloquear(FRASE)
a.eliminar_ok = None
cer3, key3, pw3 = e_firma_falsa(rfc="DDD040404DDD", password="x3")
b.agregar(cer3, key3, "x3")
lanza("cambio concurrente en otro equipo no se pisa", lambda: a.agregar(cer2, key2, "otra"), "cambio desde otro equipo")

# archivo alterado
with open(ruta) as fh:
    doc = json.load(fh)
d = bytearray(B._ub64(doc["datos"])); d[10] ^= 1; doc["datos"] = B._b64(bytes(d))
alterado = os.path.join(carpeta, "alterada.enc"); json.dump(doc, open(alterado, "w"))
lanza("archivo alterado se detecta", lambda: B.Boveda(alterado).desbloquear("una frase nueva igual de larga 2027"), "alterado")

# cierre por inactividad
t = B.Boveda(os.path.join(carpeta, "t.enc"), minutos_inactividad=0.001); t.crear(FRASE)
time.sleep(0.2)
espera("se cierra sola por inactividad", not t.abierta())

# eliminar
v.eliminar("BBB020202BBB")
espera("eliminar quita el RFC", [c["rfc"] for c in v.listar()] == ["AAA010101AAA"])

shutil.rmtree(carpeta, ignore_errors=True)
print("\nFALLAS:", fallas if fallas else "ninguna")
sys.exit(1 if fallas else 0)
