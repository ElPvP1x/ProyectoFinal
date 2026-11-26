"""SAT SIMULADO compartido por las pruebas (imita lo que usa descarga_sat de cfdiclient)."""
import base64, io, os, sys, zipfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utiles_prueba import cfdi_xml

CLIENTE, PROV = "AAA010101AAA", "CCC010101CC2"

# ---- ZIP que "entregara" el SAT simulado ----
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w") as z:
    z.writestr("a.xml", cfdi_xml("A" * 36, PROV, CLIENTE, 1000))
    z.writestr("b.xml", cfdi_xml("B" * 36, PROV, CLIENTE, 2000))
ZIP_B64 = base64.b64encode(buf.getvalue()).decode()


class SATSimulado:
    """Imita lo que usa descarga_sat de cfdiclient. Lleva la cuenta de lo que pidio el codigo."""
    llamadas = []
    verificaciones = 0
    n_solicitudes = 0
    rechazar_solicitud = False

    class Fiel:
        def __init__(self, cer, key, pw):
            SATSimulado.llamadas.append(("fiel", len(cer), len(key), pw))

    class Autenticacion:
        def __init__(self, fiel, verify=True, timeout=15): pass
        def obtener_token(self): return "TOKEN-FALSO"

    class _Solicita:
        def __init__(self, fiel, verify=True, timeout=15): pass
        def solicitar_descarga(self, token, rfc, ini, fin, **kw):
            SATSimulado.llamadas.append(("solicitar", self.__class__.__name__, rfc, ini, fin, kw))
            if SATSimulado.rechazar_solicitud:
                return {"id_solicitud": None, "cod_estatus": "5002", "mensaje": "Se agotaron"}
            SATSimulado.n_solicitudes += 1
            return {"id_solicitud": f"SOL-{SATSimulado.n_solicitudes:04d}", "cod_estatus": "5000", "mensaje": "Solicitud Aceptada"}

    class SolicitaDescargaRecibidos(_Solicita): pass
    class SolicitaDescargaEmitidos(_Solicita): pass

    class VerificaSolicitudDescarga:
        def __init__(self, fiel, verify=True, timeout=15): pass
        def verificar_descarga(self, token, rfc, id_):
            SATSimulado.verificaciones += 1
            if SATSimulado.verificaciones < 2:
                return {"cod_estatus": "5000", "estado_solicitud": "2", "numero_cfdis": "0", "mensaje": "", "paquetes": []}
            return {"cod_estatus": "5000", "estado_solicitud": "3", "numero_cfdis": "2", "mensaje": "", "paquetes": ["PAQ-1"]}

    class DescargaMasiva:
        def __init__(self, fiel, verify=True, timeout=15): pass
        def descargar_paquete(self, token, rfc, id_paquete):
            SATSimulado.llamadas.append(("descargar", id_paquete))
            return {"cod_estatus": "5000", "mensaje": "ok", "paquete_b64": ZIP_B64}


