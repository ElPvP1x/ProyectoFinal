# -*- coding: utf-8 -*-
"""
boveda.py
---------
Boveda cifrada para guardar las e.firma (.cer, .key y contrasena) de los
contribuyentes, y poder usarlas para la descarga masiva del SAT.

Diseno (todo se cifra en TU equipo; quien guarde el archivo solo ve basura):

  * UN archivo (`boveda.enc`). Adentro, un solo bloque cifrado con AES-256-GCM.
    Ni siquiera los RFC ni los nombres se ven sin la frase.
  * La llave sale de TU frase maestra con scrypt (lenta a proposito, para que
    adivinar la frase por fuerza bruta sea caro). La frase NO se guarda en ningun lado:
    si la olvidas, nadie puede recuperar la boveda.
  * El archivo se puede dejar en una carpeta sincronizada (OneDrive, Google Drive,
    Dropbox, un USB) para abrirlo desde cualquier computadora. Como el cifrado ocurre
    antes de salir de tu equipo, la nube solo guarda el archivo ya cifrado.
  * Control de version: cada guardado sube un contador. Si desde otro equipo alguien
    cambio la boveda, no se sobrescribe a ciegas: se avisa.
  * Se cierra sola tras unos minutos sin usarse; la llave vive solo en memoria.
  * Bitacora de accesos (sin secretos) dentro del mismo bloque cifrado.

AVISO: la e.firma tiene el mismo valor legal que la firma autografa del
contribuyente. Usala solo con su autorizacion por escrito. Esta boveda reduce el
riesgo, no lo elimina: una frase debil o una computadora con virus lo anulan.
"""
from __future__ import annotations

import base64
import hmac
import json
import os
import secrets
import shutil
import tempfile
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from cryptography import x509
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.x509.oid import ObjectIdentifier

FORMATO = "boveda-efirma"
VERSION = 1
MIN_FRASE = 12
N_SCRYPT, R_SCRYPT, P_SCRYPT = 2 ** 16, 8, 1
OID_RFC_CURP = ObjectIdentifier("2.5.4.45")     # x500UniqueIdentifier: "RFC / CURP"


class BovedaError(Exception):
    """Error que se le puede mostrar tal cual al usuario."""


def _b64(b: bytes) -> str:
    return base64.b64encode(b).decode("ascii")


def _ub64(s: str) -> bytes:
    return base64.b64decode(s.encode("ascii"))


# =============================================================================
# Certificado y llave (validacion)
# =============================================================================

def inspeccionar_cer(cer: bytes) -> Dict[str, Any]:
    """Lee el .cer (DER) y devuelve RFC, nombre, serie y vigencia."""
    try:
        c = x509.load_der_x509_certificate(cer)
    except ValueError as exc:
        raise BovedaError("El archivo .cer no es un certificado valido (debe ser el .cer del SAT).") from exc
    rfc = ""
    for atr in c.subject.get_attributes_for_oid(OID_RFC_CURP):
        rfc = str(atr.value).split("/")[0].strip().upper()
    nombre = ""
    for atr in c.subject:
        if atr.oid.dotted_string == "2.5.4.3":
            nombre = str(atr.value)
    try:
        serie = bytes.fromhex(f"{c.serial_number:x}").decode("ascii")
    except (ValueError, UnicodeDecodeError):
        serie = f"{c.serial_number:x}"
    inicio = c.not_valid_before_utc
    fin = c.not_valid_after_utc
    ahora = datetime.now(timezone.utc)
    return {"rfc": rfc, "nombre": nombre, "serie": serie,
            "inicia": inicio.date().isoformat(), "vence": fin.date().isoformat(),
            "vigente": inicio <= ahora <= fin, "dias_restantes": (fin - ahora).days}


def validar_llave(cer: bytes, key: bytes, password: str) -> None:
    """Comprueba que el .key abre con la contrasena y que corresponde al .cer."""
    certificado = x509.load_der_x509_certificate(cer)
    n_cert = certificado.public_key().public_numbers().n
    try:
        from Crypto.PublicKey import RSA          # pycryptodome: abre las .key del SAT
        try:
            n_llave = RSA.import_key(key, passphrase=password).n
        except (ValueError, IndexError, TypeError) as exc:
            raise BovedaError("La contrasena no abre el archivo .key (o el .key esta danado).") from exc
    except ImportError:
        from cryptography.hazmat.primitives import serialization
        try:
            n_llave = serialization.load_der_private_key(key, password.encode()).public_key().public_numbers().n
        except (ValueError, TypeError) as exc:
            raise BovedaError("La contrasena no abre el archivo .key (o el .key esta danado).") from exc
    if n_llave != n_cert:
        raise BovedaError("El .key no corresponde a ese .cer: son de e.firma distintas.")


# =============================================================================
# Boveda
# =============================================================================

class Boveda:
    def __init__(self, ruta: str, minutos_inactividad: float = 15):
        self.ruta = ruta
        self.minutos = float(minutos_inactividad)
        self._clave: Optional[bytes] = None
        self._datos: Optional[Dict[str, Any]] = None
        self._kdf: Optional[Dict[str, Any]] = None
        self._revision = 0
        self._ultimo = 0.0
        self._lock = threading.RLock()

    # ---- estado -----------------------------------------------------------
    def existe(self) -> bool:
        return os.path.isfile(self.ruta)

    def abierta(self) -> bool:
        with self._lock:
            if self._clave is not None and self.minutos > 0 \
                    and time.time() - self._ultimo > self.minutos * 60:
                self._cerrar()
            return self._clave is not None

    def _requiere(self) -> None:
        if not self.abierta():
            raise BovedaError("La boveda esta cerrada. Ingresa tu frase maestra.")
        self._ultimo = time.time()

    def _cerrar(self) -> None:
        self._clave, self._datos, self._kdf = None, None, None

    def bloquear(self) -> None:
        with self._lock:
            self._cerrar()

    # ---- cifrado ----------------------------------------------------------
    @staticmethod
    def _derivar(frase: str, kdf: Dict[str, Any]) -> bytes:
        return Scrypt(salt=_ub64(kdf["salt"]), length=32, n=kdf["n"], r=kdf["r"], p=kdf["p"]
                      ).derive(frase.encode("utf-8"))

    @staticmethod
    def _aad(kdf: Dict[str, Any], revision: int) -> bytes:
        return json.dumps({"f": FORMATO, "v": VERSION, "rev": revision, "salt": kdf["salt"],
                           "n": kdf["n"], "r": kdf["r"], "p": kdf["p"]}, sort_keys=True).encode()

    def _leer_archivo(self) -> Dict[str, Any]:
        try:
            with open(self.ruta, encoding="utf-8") as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            raise BovedaError("No se pudo leer el archivo de la boveda.") from exc
        if doc.get("formato") != FORMATO or doc.get("version") != VERSION:
            raise BovedaError("El archivo no es una boveda valida (o es de otra version).")
        return doc

    def _guardar(self) -> None:
        """Cifra todo y lo escribe de forma atomica, con respaldo del archivo anterior."""
        assert self._clave is not None and self._datos is not None and self._kdf is not None
        if self.existe():
            en_disco = self._leer_archivo()["revision"]
            if en_disco != self._revision:
                raise BovedaError("La boveda cambio desde otro equipo o sesion. Cierrala y vuelve a abrirla "
                                  "para no perder esos cambios.")
        nueva = self._revision + 1
        nonce = secrets.token_bytes(12)
        cifrado = AESGCM(self._clave).encrypt(
            nonce, json.dumps(self._datos, ensure_ascii=False).encode("utf-8"), self._aad(self._kdf, nueva))
        doc = {"formato": FORMATO, "version": VERSION, "revision": nueva, "kdf": {"alg": "scrypt", **self._kdf},
               "nonce": _b64(nonce), "datos": _b64(cifrado)}
        carpeta = os.path.dirname(os.path.abspath(self.ruta))
        os.makedirs(carpeta, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=carpeta, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(doc, fh)
        if self.existe():
            shutil.copy2(self.ruta, self.ruta + ".bak")
        os.replace(tmp, self.ruta)
        self._revision = nueva

    def _bitacora(self, accion: str, rfc: str = "") -> None:
        reg = {"cuando": datetime.now().isoformat(timespec="seconds"), "accion": accion, "rfc": rfc}
        log = self._datos.setdefault("bitacora", [])
        log.append(reg)
        del log[:-500]

    # ---- ciclo de vida ----------------------------------------------------
    def crear(self, frase: str) -> None:
        with self._lock:
            if self.existe():
                raise BovedaError("Ya existe una boveda en esa ruta.")
            if len(frase) < MIN_FRASE:
                raise BovedaError(f"La frase maestra debe tener al menos {MIN_FRASE} caracteres. "
                                  f"Usa una frase larga, no una palabra.")
            self._kdf = {"salt": _b64(secrets.token_bytes(16)), "n": N_SCRYPT, "r": R_SCRYPT, "p": P_SCRYPT}
            self._clave = self._derivar(frase, self._kdf)
            self._datos = {"contribuyentes": {}, "bitacora": []}
            self._revision = 0
            self._bitacora("boveda creada")
            self._guardar()
            self._ultimo = time.time()

    def desbloquear(self, frase: str) -> None:
        with self._lock:
            doc = self._leer_archivo()
            kdf = {k: doc["kdf"][k] for k in ("salt", "n", "r", "p")}
            if kdf["n"] > 2 ** 20:
                raise BovedaError("Parametros de la boveda fuera de lo esperado.")
            clave = self._derivar(frase, kdf)
            try:
                plano = AESGCM(clave).decrypt(_ub64(doc["nonce"]), _ub64(doc["datos"]),
                                              self._aad(kdf, doc["revision"]))
            except InvalidTag as exc:
                raise BovedaError("Frase maestra incorrecta (o el archivo fue alterado).") from exc
            self._clave, self._kdf, self._revision = clave, kdf, doc["revision"]
            self._datos = json.loads(plano.decode("utf-8"))
            self._bitacora("boveda abierta")
            self._guardar()
            self._ultimo = time.time()

    def _verificar_frase(self, frase: str) -> None:
        if not hmac.compare_digest(self._derivar(frase, self._kdf), self._clave):
            raise BovedaError("Frase maestra incorrecta.")

    def cambiar_frase(self, actual: str, nueva: str) -> None:
        with self._lock:
            self._requiere()
            self._verificar_frase(actual)
            if len(nueva) < MIN_FRASE:
                raise BovedaError(f"La frase nueva debe tener al menos {MIN_FRASE} caracteres.")
            self._kdf = {"salt": _b64(secrets.token_bytes(16)), "n": N_SCRYPT, "r": R_SCRYPT, "p": P_SCRYPT}
            self._clave = self._derivar(nueva, self._kdf)
            self._bitacora("frase maestra cambiada")
            self._guardar()

    # ---- contribuyentes ---------------------------------------------------
    @staticmethod
    def _publico(c: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in c.items() if k not in ("cer_b64", "key_b64", "password")}

    def listar(self) -> List[Dict[str, Any]]:
        with self._lock:
            self._requiere()
            lista = []
            for c in self._datos["contribuyentes"].values():
                vence = c.get("vence", "")
                try:
                    dias = (datetime.fromisoformat(vence).date() - datetime.now().date()).days
                except ValueError:
                    dias = None
                lista.append({**self._publico(c), "dias_restantes": dias, "vigente": dias is not None and dias >= 0})
            return sorted(lista, key=lambda x: x["rfc"])

    def agregar(self, cer: bytes, key: bytes, password: str, rfc: str = "", nombre: str = "",
                notas: str = "", permitir_vencida: bool = False) -> Dict[str, Any]:
        with self._lock:
            self._requiere()
            info = inspeccionar_cer(cer)
            rfc_cer = info["rfc"]
            rfc = (rfc or rfc_cer).strip().upper()
            if not rfc:
                raise BovedaError("No se pudo leer el RFC del certificado: captura el RFC.")
            if rfc_cer and rfc != rfc_cer:
                raise BovedaError(f"El RFC capturado ({rfc}) no coincide con el del certificado ({rfc_cer}).")
            if not info["vigente"] and not permitir_vencida:
                raise BovedaError(f"El certificado no esta vigente (vencio el {info['vence']}).")
            validar_llave(cer, key, password)
            ahora = datetime.now().isoformat(timespec="seconds")
            previo = self._datos["contribuyentes"].get(rfc, {})
            self._datos["contribuyentes"][rfc] = {
                "rfc": rfc, "nombre": nombre or previo.get("nombre") or info["nombre"],
                "tipo_persona": "moral" if len(rfc) == 12 else "fisica",
                "serie": info["serie"], "inicia": info["inicia"], "vence": info["vence"],
                "notas": notas or previo.get("notas", ""),
                "agregado": previo.get("agregado", ahora), "actualizado": ahora,
                "cer_b64": _b64(cer), "key_b64": _b64(key), "password": password}
            self._bitacora("e.firma agregada" if not previo else "e.firma reemplazada", rfc)
            self._guardar()
            return self._publico(self._datos["contribuyentes"][rfc])

    def eliminar(self, rfc: str) -> None:
        with self._lock:
            self._requiere()
            rfc = rfc.strip().upper()
            if rfc not in self._datos["contribuyentes"]:
                raise BovedaError("Ese RFC no esta en la boveda.")
            del self._datos["contribuyentes"][rfc]
            self._bitacora("e.firma eliminada", rfc)
            self._guardar()

    def obtener_fiel(self, rfc: str, motivo: str = "descarga SAT") -> Tuple[bytes, bytes, str]:
        """(cer, key, contrasena) para firmar. Queda en la bitacora."""
        with self._lock:
            self._requiere()
            c = self._datos["contribuyentes"].get(rfc.strip().upper())
            if not c:
                raise BovedaError("Ese RFC no esta en la boveda.")
            self._bitacora(f"uso de e.firma: {motivo}", c["rfc"])
            self._guardar()
            return _ub64(c["cer_b64"]), _ub64(c["key_b64"]), c["password"]

    def revelar_password(self, rfc: str, frase: str) -> str:
        """Mostrar la contrasena exige volver a escribir la frase maestra."""
        with self._lock:
            self._requiere()
            self._verificar_frase(frase)
            c = self._datos["contribuyentes"].get(rfc.strip().upper())
            if not c:
                raise BovedaError("Ese RFC no esta en la boveda.")
            self._bitacora("contrasena revelada", c["rfc"])
            self._guardar()
            return c["password"]

    def bitacora(self, limite: int = 100) -> List[Dict[str, str]]:
        with self._lock:
            self._requiere()
            return list(reversed(self._datos.get("bitacora", [])))[:limite]

    def respaldar(self, destino: str) -> str:
        """Copia el archivo YA CIFRADO. Es seguro guardarlo donde sea."""
        if not self.existe():
            raise BovedaError("Todavia no hay boveda que respaldar.")
        shutil.copy2(self.ruta, destino)
        return destino
