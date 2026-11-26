# -*- coding: utf-8 -*-
"""
descarga_sat.py
---------------
Descarga masiva de CFDI del SAT (servicio web "Descarga Masiva de CFDI"), con la
e.firma del contribuyente guardada en la boveda (boveda.py). Los ZIP quedan en

    descargas/<RFC>/<emitidos|recibidos>/<desde>_<hasta>_<paquete>.zip

y el motor los lee tal cual (procesar_archivos ya entiende los ZIP del SAT).

Como funciona el SAT (es asincrono):
  1. SOLICITAR   -> el SAT devuelve un id de solicitud.
  2. VERIFICAR   -> la solicitud pasa de "Aceptada" a "En proceso" y luego a
                    "Terminada"; puede tardar de minutos a horas.
  3. DESCARGAR   -> con la solicitud terminada se bajan sus paquetes ZIP.

Notas de uso (confirma los limites vigentes en la documentacion del SAT):
  * Hay limites de solicitudes y de CFDI por solicitud, y el SAT rechaza repetir la
    misma solicitud dos veces. Pide periodos mensuales y no repitas.
  * Para recibidos, el SAT solo entrega XML de CFDI vigentes. Para saber cuales se
    cancelaron, pide tambien la METADATA (formato="Metadata") o activa la consulta de
    estatus en linea (`verificar_estatus_sat`).
  * La e.firma se descifra de la boveda solo mientras dura cada operacion; la boveda
    registra cada uso en su bitacora.

La libreria `cfdiclient` hace el protocolo SOAP y la firma. Aqui se aisla en
`api` para poder probar toda la logica con un SAT simulado.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, time as hora
from typing import Any, Dict, List, Optional

from boveda import BovedaError

ESTADOS_SOLICITUD = {"1": "Aceptada", "2": "En proceso", "3": "Terminada",
                     "4": "Error", "5": "Rechazada", "6": "Vencida"}
# Codigos de estatus del SAT mas comunes (segun su documentacion; confirmalos si cambian)
CODIGOS_SAT = {
    "5000": "Solicitud recibida con exito",
    "5002": "Se agotaron las solicitudes de por vida para ese rango: el SAT ya no acepta pedirlo otra vez",
    "5003": "Se excedio el tope maximo de resultados: acota el rango de fechas",
    "5004": "No se encontro informacion para ese rango",
    "5005": "Solicitud duplicada: ya existe una solicitud vigente igual",
    "300": "Usuario no valido (revisa la e.firma)",
    "301": "XML mal formado",
    "302": "Sello mal formado o invalido",
    "303": "El sello no corresponde al RFC solicitante",
}


class DescargaError(Exception):
    """Error que se le puede mostrar tal cual al usuario."""


def _api_real():
    try:
        import cfdiclient
        return cfdiclient
    except ImportError as exc:
        raise DescargaError("Falta instalar la libreria de descarga del SAT: pip install cfdiclient") from exc


class DescargaSAT:
    def __init__(self, boveda, carpeta: str, api: Any = None, verificar_tls: bool = True, timeout: int = 60):
        self.boveda = boveda
        self.carpeta = carpeta
        self._api = api
        self.verify = verificar_tls
        self.timeout = timeout
        self.ruta_registro = os.path.join(carpeta, "solicitudes.json")

    @property
    def api(self):
        if self._api is None:
            self._api = _api_real()
        return self._api

    # ---- registro de solicitudes ------------------------------------------
    def _leer(self) -> Dict[str, Dict[str, Any]]:
        try:
            with open(self.ruta_registro, encoding="utf-8") as fh:
                return json.load(fh)
        except (OSError, ValueError):
            return {}

    def _guardar(self, datos: Dict[str, Dict[str, Any]]) -> None:
        os.makedirs(self.carpeta, exist_ok=True)
        tmp = self.ruta_registro + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(datos, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, self.ruta_registro)

    def listar(self, rfc: Optional[str] = None) -> List[Dict[str, Any]]:
        reg = self._leer()
        filas = [v for v in reg.values() if not rfc or v["rfc"] == rfc.upper()]
        return sorted(filas, key=lambda v: v["creada"], reverse=True)

    def obtener(self, id_solicitud: str) -> Dict[str, Any]:
        reg = self._leer().get(id_solicitud)
        if not reg:
            raise DescargaError("Esa solicitud no existe en el registro local.")
        return reg

    # ---- e.firma y token --------------------------------------------------
    def _fiel_y_token(self, rfc: str, motivo: str):
        try:
            cer, key, pw = self.boveda.obtener_fiel(rfc, motivo)
        except BovedaError as exc:
            raise DescargaError(str(exc)) from exc
        try:
            fiel = self.api.Fiel(cer, key, pw)
            token = self.api.Autenticacion(fiel, verify=self.verify, timeout=self.timeout).obtener_token()
        except DescargaError:
            raise
        except Exception as exc:  # noqa: BLE001 - la libreria lanza excepciones genericas
            raise DescargaError(f"El SAT rechazo la autenticacion: {exc}") from exc
        return fiel, token

    @staticmethod
    def _explicar(cod: Optional[str], mensaje: Optional[str]) -> str:
        base = CODIGOS_SAT.get(str(cod), "")
        return f"[{cod}] {base or mensaje or 'sin detalle'}" + (f" ({mensaje})" if base and mensaje else "")

    # ---- 1. solicitar -----------------------------------------------------
    def solicitar(self, rfc: str, desde: date, hasta: date, tipo: str = "recibidos",
                  formato: str = "CFDI", estado: Optional[str] = "Vigente") -> Dict[str, Any]:
        rfc = rfc.strip().upper()
        if tipo not in ("recibidos", "emitidos"):
            raise DescargaError("El tipo debe ser 'recibidos' o 'emitidos'.")
        if formato not in ("CFDI", "Metadata"):
            raise DescargaError("El formato debe ser 'CFDI' (XML) o 'Metadata'.")
        if hasta < desde:
            raise DescargaError("La fecha final es anterior a la inicial.")
        if hasta > date.today():
            raise DescargaError("La fecha final no puede ser futura.")
        # El SAT acepta recibidos vigentes en XML; cancelados solo en Metadata
        if tipo == "recibidos" and formato == "CFDI" and estado not in (None, "Vigente"):
            raise DescargaError("De recibidos, el SAT solo entrega en XML los CFDI vigentes. "
                                "Pide la Metadata para ver los cancelados.")

        fiel, token = self._fiel_y_token(rfc, f"solicitud {tipo} {desde} a {hasta}")
        ini = datetime.combine(desde, hora(0, 0, 0))
        fin = datetime.combine(hasta, hora(23, 59, 59))
        try:
            if tipo == "recibidos":
                resp = self.api.SolicitaDescargaRecibidos(fiel, verify=self.verify, timeout=self.timeout
                                                          ).solicitar_descarga(
                    token, rfc, ini, fin, rfc_receptor=rfc, tipo_solicitud=formato, estado_comprobante=estado)
            else:
                resp = self.api.SolicitaDescargaEmitidos(fiel, verify=self.verify, timeout=self.timeout
                                                         ).solicitar_descarga(
                    token, rfc, ini, fin, rfc_emisor=rfc, tipo_solicitud=formato, estado_comprobante=estado)
        except Exception as exc:  # noqa: BLE001
            raise DescargaError(f"No se pudo enviar la solicitud al SAT: {exc}") from exc

        if str(resp.get("cod_estatus")) != "5000" or not resp.get("id_solicitud"):
            raise DescargaError("El SAT no acepto la solicitud: "
                                + self._explicar(resp.get("cod_estatus"), resp.get("mensaje")))
        entrada = {"id": resp["id_solicitud"], "rfc": rfc, "tipo": tipo, "formato": formato,
                   "desde": desde.isoformat(), "hasta": hasta.isoformat(), "estado_pedido": estado,
                   "estado": "Aceptada", "codigo_estado": "1", "numero_cfdis": None,
                   "paquetes": [], "archivos": [], "creada": datetime.now().isoformat(timespec="seconds"),
                   "actualizada": datetime.now().isoformat(timespec="seconds"), "mensaje": resp.get("mensaje") or ""}
        reg = self._leer()
        reg[entrada["id"]] = entrada
        self._guardar(reg)
        return entrada

    # ---- 2. verificar -----------------------------------------------------
    def verificar(self, id_solicitud: str) -> Dict[str, Any]:
        entrada = self.obtener(id_solicitud)
        fiel, token = self._fiel_y_token(entrada["rfc"], f"verificar {id_solicitud}")
        try:
            resp = self.api.VerificaSolicitudDescarga(fiel, verify=self.verify, timeout=self.timeout
                                                      ).verificar_descarga(token, entrada["rfc"], id_solicitud)
        except Exception as exc:  # noqa: BLE001
            raise DescargaError(f"No se pudo consultar la solicitud: {exc}") from exc
        if str(resp.get("cod_estatus")) != "5000":
            raise DescargaError("El SAT respondio: " + self._explicar(resp.get("cod_estatus"), resp.get("mensaje")))
        codigo = str(resp.get("estado_solicitud"))
        entrada.update({"codigo_estado": codigo, "estado": ESTADOS_SOLICITUD.get(codigo, f"Estado {codigo}"),
                        "numero_cfdis": int(resp["numero_cfdis"]) if str(resp.get("numero_cfdis") or "").isdigit() else None,
                        "paquetes": list(resp.get("paquetes") or entrada["paquetes"]),
                        "mensaje": resp.get("mensaje") or entrada.get("mensaje", ""),
                        "actualizada": datetime.now().isoformat(timespec="seconds")})
        reg = self._leer()
        reg[id_solicitud] = entrada
        self._guardar(reg)
        return entrada

    # ---- 3. descargar -----------------------------------------------------
    def descargar(self, id_solicitud: str) -> Dict[str, Any]:
        entrada = self.obtener(id_solicitud)
        if entrada["codigo_estado"] != "3":
            raise DescargaError(f"La solicitud aun no esta terminada (estado: {entrada['estado']}). Verificala primero.")
        if not entrada["paquetes"]:
            raise DescargaError("La solicitud terminada no trae paquetes (el SAT no encontro CFDI en ese rango).")
        fiel, token = self._fiel_y_token(entrada["rfc"], f"descargar {id_solicitud}")
        destino = os.path.join(self.carpeta, entrada["rfc"], entrada["tipo"])
        os.makedirs(destino, exist_ok=True)
        import base64
        archivos = list(entrada.get("archivos") or [])
        for paquete in entrada["paquetes"]:
            nombre = f"{entrada['desde']}_{entrada['hasta']}_{entrada['formato'].lower()}_{paquete}.zip"
            ruta = os.path.join(destino, nombre)
            if os.path.isfile(ruta) and ruta in archivos:
                continue                                    # ya bajado: no se repite
            try:
                resp = self.api.DescargaMasiva(fiel, verify=self.verify, timeout=self.timeout
                                               ).descargar_paquete(token, entrada["rfc"], paquete)
            except Exception as exc:  # noqa: BLE001
                raise DescargaError(f"No se pudo descargar el paquete {paquete}: {exc}") from exc
            if str(resp.get("cod_estatus")) != "5000" or not resp.get("paquete_b64"):
                raise DescargaError(f"Paquete {paquete}: " + self._explicar(resp.get("cod_estatus"), resp.get("mensaje")))
            with open(ruta, "wb") as fh:
                fh.write(base64.b64decode(resp["paquete_b64"]))
            archivos.append(ruta)
        entrada["archivos"] = archivos
        entrada["actualizada"] = datetime.now().isoformat(timespec="seconds")
        reg = self._leer()
        reg[id_solicitud] = entrada
        self._guardar(reg)
        return entrada

    def rutas_zip(self, ids: List[str]) -> List[str]:
        rutas: List[str] = []
        for i in ids:
            e = self.obtener(i)
            rutas.extend(r for r in e.get("archivos", []) if os.path.isfile(r))
        if not rutas:
            raise DescargaError("Esas solicitudes no tienen archivos descargados todavia.")
        return rutas
