"""Prueba de reglas_md.py con CFDI SINTETICOS (inventados, RFC ficticios). Uso: python pruebas/prueba_reglas_md.py"""
import json, os, shutil, sys, tempfile, uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import procesador_cfdi as P

CLIENTE = "AAA010101AAA"          # PM ficticia (12 caracteres)
PROV_PF = "BBBB010101BB1"         # PF ficticia (13)
PROV_PM = "CCC010101CC2"
EN69B = "DDD010101DD3"

def cfdi(idn, emisor, receptor, subtotal, iva=None, uso="G03", forma="03", metodo="PUE",
         desc="Servicio de consultoria fiscal", clave="80101500", tipo="I", fecha="2026-08-10T10:00:00",
         regimen_emisor="601", isr_ret=0.0, iva_ret=0.0, relacionado=None, rel_tipo=None, cp="28000"):
    iva = round(subtotal * 0.16, 2) if iva is None else iva
    total = round(subtotal + iva - isr_ret - iva_ret, 2)
    rel = ""
    if relacionado:
        rel = f'<cfdi:CfdiRelacionados TipoRelacion="{rel_tipo}"><cfdi:CfdiRelacionado UUID="{relacionado}"/></cfdi:CfdiRelacionados>'
    ret = ""
    if isr_ret or iva_ret:
        partes = ""
        if isr_ret: partes += f'<cfdi:Retencion Impuesto="001" Importe="{isr_ret}"/>'
        if iva_ret: partes += f'<cfdi:Retencion Impuesto="002" Importe="{iva_ret}"/>'
        ret = f'<cfdi:Retenciones>{partes}</cfdi:Retenciones>'
    tras = f'<cfdi:Traslados><cfdi:Traslado Impuesto="002" Importe="{iva}" TipoFactor="Tasa" TasaOCuota="0.160000"/></cfdi:Traslados>' if iva else ""
    imp = f'<cfdi:Impuestos TotalImpuestosTrasladados="{iva}" TotalImpuestosRetenidos="{isr_ret + iva_ret}">{ret}{tras}</cfdi:Impuestos>'
    u = idn.upper().ljust(36, "0")[:36]
    return u, f'''<?xml version="1.0" encoding="utf-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
 Version="4.0" TipoDeComprobante="{tipo}" Fecha="{fecha}" FormaPago="{forma}" MetodoPago="{metodo}"
 SubTotal="{subtotal}" Total="{total}" Moneda="MXN" LugarExpedicion="28000">
 {rel}
 <cfdi:Emisor Rfc="{emisor}" Nombre="Proveedor" RegimenFiscal="{regimen_emisor}"/>
 <cfdi:Receptor Rfc="{receptor}" Nombre="Cliente" DomicilioFiscalReceptor="{cp}" RegimenFiscalReceptor="601" UsoCFDI="{uso}"/>
 <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="{clave}" Cantidad="1" ClaveUnidad="E48" Descripcion="{desc}" ValorUnitario="{subtotal}" Importe="{subtotal}"/></cfdi:Conceptos>
 {imp}
 <cfdi:Complemento><tfd:TimbreFiscalDigital UUID="{u}"/></cfdi:Complemento>
</cfdi:Comprobante>''', u

lote = []   # (nombre, uuid, xml)
def caso(nombre, ident, **kw):
    u, xml, _ = cfdi(ident, **kw)
    lote.append((nombre, u, xml))
    return u

emi = dict(emisor=PROV_PM, receptor=CLIENTE)
u_ok = caso("normal", "n1", subtotal=1000, **emi)
caso("generico", "g1", subtotal=500, emisor=PROV_PM, receptor="XAXX010101000")
caso("otro_receptor", "o1", subtotal=500, emisor=PROV_PM, receptor="EEE010101EE4")
caso("s01", "s1", subtotal=500, uso="S01", **emi)
caso("lista69b", "b1", subtotal=500, emisor=EN69B, receptor=CLIENTE)
caso("otro_anio", "a1", subtotal=500, fecha="2025-12-20T10:00:00", **emi)
caso("inversion_computo", "i1", subtotal=10000, uso="I04", desc="Laptop equipo de computo", **emi)
caso("interes_con_uso_i", "i2", subtotal=1000, uso="I03", desc="Interes de financiamiento", **emi)
caso("restaurante_tarjeta", "r1", subtotal=1000, forma="04", desc="Consumo en restaurante", clave="90101501", **emi)
caso("restaurante_efectivo", "r2", subtotal=1000, forma="01", desc="Consumo en restaurante", clave="90101501", **emi)
caso("bar", "r3", subtotal=1000, forma="04", desc="Consumo en bar cerveza", clave="90101502", **emi)
caso("hotel", "h1", subtotal=2000, forma="04", desc="Hospedaje hotel una noche", clave="90111500", **emi)
u_orig = caso("factura_original", "f1", subtotal=3000, **emi)
caso("factura_sustituta", "f2", subtotal=3000, relacionado=u_orig, rel_tipo="04", **emi)
caso("nota_credito_sin_rel", "c1", subtotal=100, tipo="E", uso="G02", **emi)
caso("generica", "d1", subtotal=300, desc="Servicios", **emi)
caso("pue_99", "p1", subtotal=300, forma="99", metodo="PUE", **emi)
caso("honorarios_sin_ret", "h2", subtotal=4000, emisor=PROV_PF, receptor=CLIENTE, regimen_emisor="612")
caso("honorarios_ret_ok", "h3", subtotal=4000, emisor=PROV_PF, receptor=CLIENTE, regimen_emisor="612",
     isr_ret=400.0, iva_ret=426.67)
caso("honorarios_ret_mal", "h4", subtotal=4000, emisor=PROV_PF, receptor=CLIENTE, regimen_emisor="612",
     isr_ret=100.0, iva_ret=426.67)
caso("cp_distinto", "q1", subtotal=200, cp="99999", **emi)

# --- Casos de la segunda tanda: REP, topes, anticipos ---
u_ppd_pagada = caso("ppd_con_rep", "ppd1", subtotal=1000, metodo="PPD", forma="99", **emi)
caso("ppd_sin_rep", "ppd2", subtotal=1000, metodo="PPD", forma="99", **emi)
caso("auto_caro", "au1", subtotal=400000, uso="I03", desc="Automovil sedan", **emi)
caso("lentes", "le1", subtotal=4000, uso="D01", desc="Lentes graduados", forma="04", **emi)
caso("anticipo", "an1", subtotal=500, tipo="E", uso="G02", forma="30", relacionado=u_ok, rel_tipo="07", **emi)

rep_uuid = "REP1".ljust(36, "0")
rep_xml = f'''<?xml version="1.0" encoding="utf-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
 xmlns:pago20="http://www.sat.gob.mx/Pagos20" Version="4.0" TipoDeComprobante="P" Fecha="2026-08-20T10:00:00"
 SubTotal="0" Total="0" Moneda="XXX" LugarExpedicion="28000">
 <cfdi:Emisor Rfc="{PROV_PM}" Nombre="Proveedor" RegimenFiscal="601"/>
 <cfdi:Receptor Rfc="{CLIENTE}" Nombre="Cliente" DomicilioFiscalReceptor="28000" RegimenFiscalReceptor="601" UsoCFDI="CP01"/>
 <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="84111506" Cantidad="1" ClaveUnidad="ACT" Descripcion="Pago" ValorUnitario="0" Importe="0"/></cfdi:Conceptos>
 <cfdi:Complemento>
  <pago20:Pagos><pago20:Pago Monto="1160" FormaDePagoP="03"><pago20:DoctoRelacionado IdDocumento="{u_ppd_pagada}" ImpPagado="1160" NumParcialidad="1" ImpSaldoAnt="1160" ImpSaldoInsoluto="0"/></pago20:Pago></pago20:Pagos>
  <tfd:TimbreFiscalDigital UUID="{rep_uuid}"/>
 </cfdi:Complemento>
</cfdi:Comprobante>'''
lote.append(("rep_del_ppd", rep_uuid, rep_xml))

carpeta = tempfile.mkdtemp(prefix="cfdi_sint_")
for nombre, u, xml in lote:
    open(os.path.join(carpeta, nombre + ".xml"), "w", encoding="utf-8").write(xml)

cfg = P.cargar_config()
cfg.update({"rfc_contribuyente": CLIENTE, "ejercicio_fiscal": 2026, "rfc_69b_definitivos": [EN69B],
            "cp_contribuyente": "28000", "usar_perfiles": False, "convertir_a_mxn": False})
df, tot, diag = P.procesar_archivos([carpeta], cfg)
shutil.rmtree(carpeta, ignore_errors=True)

df["caso"] = df["Archivo XML"].str.replace(".xml", "", regex=False)
res = df.set_index("caso")
fallas = []
def espera(caso_, cond, msg):
    ok = bool(cond)
    print(("OK   " if ok else "FALLA"), f"{caso_:<24}", msg)
    if not ok: fallas.append(caso_)

r = lambda c: res.loc[c]
espera("normal", r("normal")["_Suma"] and r("normal")["Importe Computado"] == 1160, f"suma {r('normal')['Importe Computado']}")
espera("generico", not r("generico")["_Suma"] and r("generico")["Regla Aplicada"] == "Regla 7", r("generico")["Clasificacion"])
espera("otro_receptor", not r("otro_receptor")["_Suma"] and r("otro_receptor")["Regla Aplicada"] == "Regla 7", r("otro_receptor")["Motivo de Rechazo"][:60])
espera("s01", not r("s01")["_Suma"] and "S01" in r("s01")["Motivo de Rechazo"], r("s01")["Clasificacion"])
espera("lista69b", not r("lista69b")["_Suma"] and r("lista69b")["Regla Aplicada"] == "Regla 8", r("lista69b")["Clasificacion"])
espera("otro_anio", not r("otro_anio")["_Suma"] and r("otro_anio")["Regla Aplicada"] == "Regla 9", r("otro_anio")["Clasificacion"])
inv = r("inversion_computo")
espera("inversion_computo", not inv["_Suma"] and inv["Regla Aplicada"] == "Inversion" and inv["IVA Acreditable"] == 1600 and "30%" in inv["Motivo de Rechazo"],
       f"no suma, IVA acreditable {inv['IVA Acreditable']}")
rt = r("restaurante_tarjeta")
espera("restaurante_tarjeta", rt["_Suma"] and abs(rt["Importe Computado"] - 1160 * 0.085) < 0.02 and abs(rt["IVA Acreditable"] - 160 * 0.085) < 0.02,
       f"deduce {rt['Importe Computado']} IVA acred {rt['IVA Acreditable']}")
espera("restaurante_efectivo", not r("restaurante_efectivo")["_Suma"], r("restaurante_efectivo")["Motivo de Rechazo"][:60])
espera("bar", not r("bar")["_Suma"], r("bar")["Motivo de Rechazo"][:60])
espera("hotel", r("hotel")["_Suma"] and r("hotel")["Importe Computado"] == 2320, f"suma {r('hotel')['Importe Computado']}")
espera("factura_original", not r("factura_original")["_Suma"] and r("factura_original")["Regla Aplicada"] == "Sustitucion", r("factura_original")["Clasificacion"])
espera("factura_sustituta", r("factura_sustituta")["_Suma"], f"suma {r('factura_sustituta')['Importe Computado']}")
espera("nc_sin_relacion", "sin CFDI relacionado" in r("nota_credito_sin_rel")["Alertas"], r("nota_credito_sin_rel")["Alertas"][:60])
espera("generica", "generica" in r("generica")["Alertas"].lower(), r("generica")["Alertas"][:60])
espera("pue_99", "PUE con forma de pago 99" in r("pue_99")["Alertas"], r("pue_99")["Alertas"][:60])
espera("honorarios_sin_ret", "falta de retencion" in r("honorarios_sin_ret")["Alertas"], r("honorarios_sin_ret")["Alertas"][:60])
espera("honorarios_ret_ok", r("honorarios_ret_ok")["Alertas"] == "", repr(r("honorarios_ret_ok")["Alertas"]))
espera("honorarios_ret_mal", "ISR retenido" in r("honorarios_ret_mal")["Alertas"], r("honorarios_ret_mal")["Alertas"][:70])
espera("cp_distinto", "Codigo postal" in r("cp_distinto")["Alertas"], r("cp_distinto")["Alertas"][:60])

espera("interes_con_uso_i", r("interes_con_uso_i")["_Suma"], "los intereses con uso I03 siguen siendo gasto")
espera("ppd_con_rep", "sin REP" not in r("ppd_con_rep")["Alertas"], repr(r("ppd_con_rep")["Alertas"]))
espera("ppd_sin_rep", "PPD sin REP ligado" in r("ppd_sin_rep")["Alertas"], r("ppd_sin_rep")["Alertas"][:60])
espera("auto_caro", "tope de 175,000" in r("auto_caro")["Motivo de Rechazo"] and not r("auto_caro")["_Suma"],
       r("auto_caro")["Motivo de Rechazo"][100:190])
espera("lentes", "Lentes graduados" in r("lentes")["Alertas"] and "excede" in r("lentes")["Alertas"], r("lentes")["Alertas"][:70])
espera("anticipo", "Anticipo" in r("anticipo")["Alertas"], r("anticipo")["Alertas"][:50])
tp = tot.get("deducciones_personales_tope") or {}
espera("tope_global", tp.get("conteo") == 1 and abs(tp.get("tope_5_uma", 0) - 214090.75) < 0.01, str(tp.get("tope_5_uma")))
# Totales coherentes
print("\nTotal deducible:", tot["total_deducible"], "| IVA acreditable:", tot["iva_acreditable"],
      "| inversiones:", tot["total_inversiones"], "| sustituidas:", tot["conteo_sustituidas"],
      "| restaurantes:", tot["conteo_restaurantes"], "| alertas:", tot["conteo_alertas"])
ruta = P.exportar_excel(df, tot, os.path.join(tempfile.gettempdir(), "prueba_reglas.xlsx"))
print("Excel generado sin error:", os.path.exists(ruta))
print("\nFALLAS:", fallas if fallas else "ninguna")
sys.exit(1 if fallas else 0)
