"""Utiles de prueba: e.firma SINTETICAS (autofirmadas, sin valor legal) y un CFDI de mentira."""
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID, ObjectIdentifier


def e_firma_falsa(rfc="AAA010101AAA", nombre="EMPRESA DE PRUEBA SA DE CV", password="clave-de-prueba-123",
                  dias_validez=365, desde=-10):
    llave = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    sujeto = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, nombre),
                        x509.NameAttribute(ObjectIdentifier("2.5.4.45"), f"{rfc} / XXXX010101HXXXXX00")])
    inicio = datetime.now(timezone.utc) + timedelta(days=desde)
    cert = (x509.CertificateBuilder().subject_name(sujeto).issuer_name(sujeto).public_key(llave.public_key())
            .serial_number(int.from_bytes(b"30001000000500003416", "big")).not_valid_before(inicio)
            .not_valid_after(inicio + timedelta(days=dias_validez)).sign(llave, hashes.SHA256()))
    cer = cert.public_bytes(serialization.Encoding.DER)
    key = llave.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                              serialization.BestAvailableEncryption(password.encode()))
    return cer, key, password


def cfdi_xml(uuid, emisor, receptor, subtotal, fecha="2026-08-10T10:00:00", forma="03", uso="G03",
             desc="Servicio de consultoria fiscal"):
    iva = round(subtotal * 0.16, 2)
    total = round(subtotal + iva, 2)
    return f'''<?xml version="1.0" encoding="utf-8"?>
<cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" xmlns:tfd="http://www.sat.gob.mx/TimbreFiscalDigital"
 Version="4.0" TipoDeComprobante="I" Fecha="{fecha}" FormaPago="{forma}" MetodoPago="PUE"
 SubTotal="{subtotal}" Total="{total}" Moneda="MXN" LugarExpedicion="28000">
 <cfdi:Emisor Rfc="{emisor}" Nombre="Proveedor" RegimenFiscal="601"/>
 <cfdi:Receptor Rfc="{receptor}" Nombre="Cliente" DomicilioFiscalReceptor="28000" RegimenFiscalReceptor="601" UsoCFDI="{uso}"/>
 <cfdi:Conceptos><cfdi:Concepto ClaveProdServ="80101500" Cantidad="1" ClaveUnidad="E48" Descripcion="{desc}" ValorUnitario="{subtotal}" Importe="{subtotal}"/></cfdi:Conceptos>
 <cfdi:Impuestos TotalImpuestosTrasladados="{iva}"><cfdi:Traslados><cfdi:Traslado Impuesto="002" Importe="{iva}" TipoFactor="Tasa" TasaOCuota="0.160000"/></cfdi:Traslados></cfdi:Impuestos>
 <cfdi:Complemento><tfd:TimbreFiscalDigital UUID="{uuid}"/></cfdi:Complemento>
</cfdi:Comprobante>'''
