# -*- coding: utf-8 -*-
"""
perfiles.py
-----------
Perfil por contribuyente, construido solo a partir de sus CFDI.

No necesita credenciales ni captura previa: el RFC, el giro y el catalogo de
proveedores salen de las facturas que se procesan. Lo que el sistema propone,
el contador lo confirma UNA vez; de ahi en adelante es automatico.

Regla de oro: el sistema PROPONE, no decide. "Estrictamente indispensable"
(Art. 27 F-I LISR) es criterio del contador, no de un programa.

Archivo por contribuyente:  perfiles/<RFC>.json
"""
from __future__ import annotations

import json
import os
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

CARPETA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "perfiles")

# Decisiones posibles para un proveedor
SIEMPRE = "siempre_deducible"
NUNCA = "nunca_deducible"
REVISAR = "revisar"


def _norm(texto: Any) -> str:
    if texto is None:
        return ""
    s = unicodedata.normalize("NFKD", str(texto).strip().lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# =============================================================================
# CATALOGO DE GIROS
# =============================================================================
# Cada giro se reconoce por palabras que aparecen en el nombre del proveedor o
# en el concepto, y por claves del catalogo de productos y servicios del SAT.
# El puntaje se pondera por MONTO, no por numero de facturas: el insumo
# principal de un negocio es donde se va el dinero.

GIROS: Dict[str, Dict[str, Any]] = {
    "tortilleria": {
        "nombre": "Tortillería / molino de nixtamal",
        "palabras": ["harinera", "maseca", "minsa", "nixtamal", "masa", "tortilla",
                     "tortilladora", "tortillera", "harina de maiz"],
        "claves": ["50221300", "23153500", "50181900"],
    },
    "abarrotes": {
        "nombre": "Abarrotes / tienda",
        "palabras": ["abarrotes", "refrescos", "coca cola", "pepsi", "sabritas",
                     "bimbo", "lala", "distribuidora de alimentos", "mayoreo"],
        "claves": ["50000000", "50200000"],
    },
    "restaurante": {
        "nombre": "Restaurante / fonda",
        "palabras": ["carnes", "pollo", "verduras", "frutas", "mariscos",
                     "alimentos y bebidas", "cerveceria", "abastecedora de alimentos",
                     "desechables"],
        "claves": ["50190000", "90101500"],
    },
    "transporte": {
        "nombre": "Autotransporte / fletes",
        "palabras": ["autotransporte", "fletes", "transportes", "llantas", "casetas",
                     "peaje", "capufe", "refacciones diesel", "rastreo satelital"],
        "claves": ["78101800", "25172500", "15101500"],
    },
    "construccion": {
        "nombre": "Construcción",
        "palabras": ["cemento", "cemex", "varilla", "acero", "concreto", "materiales para construccion",
                     "ferreteria", "agregados", "arena", "grava", "block"],
        "claves": ["30111500", "30102400", "72100000"],
    },
    "taller": {
        "nombre": "Taller mecánico / automotriz",
        "palabras": ["autopartes", "refaccionaria", "lubricantes", "aceite automotriz",
                     "rectificadora", "hojalateria", "taller mecanico", "baleros"],
        "claves": ["25170000", "15121500"],
    },
    "despacho": {
        "nombre": "Servicios profesionales / despacho",
        "palabras": ["honorarios", "asesoria", "consultoria", "contable", "juridico",
                     "notaria", "software", "licencias", "hosting", "capacitacion"],
        "claves": ["80101500", "81112200", "84111500"],
    },
    "farmacia": {
        "nombre": "Farmacia",
        "palabras": ["farmaceutica", "medicamentos", "farmacia", "laboratorios",
                     "productos de salud"],
        "claves": ["51000000", "42000000"],
    },
    "agropecuario": {
        "nombre": "Agropecuario / ganadería",
        "palabras": ["semilla", "fertilizante", "agroquimicos", "forraje", "ganado",
                     "alimento balanceado", "veterinaria", "pecuaria", "riego"],
        "claves": ["10000000", "11121700"],
    },
    "belleza": {
        "nombre": "Estética / salón de belleza",
        "palabras": ["cosmeticos", "estetica", "belleza", "tinte", "peluqueria"],
        "claves": ["53131600"],
    },
    "papeleria": {
        "nombre": "Papelería / imprenta",
        "palabras": ["papeleria", "articulos de oficina", "imprenta", "papel bond",
                     "toner", "cartuchos"],
        "claves": ["44120000", "14111500"],
    },
}

# Gastos que cualquier negocio tiene: no distinguen el giro, por eso no puntuan.
GASTOS_GENERICOS = [
    "comision", "intereses", "manejo de cuenta", "cuotas imss", "infonavit",
    "telecomunicaciones", "telefonia", "energia", "electricidad", "cfe",
    "renta", "arrendamiento", "agua", "predial", "seguro", "facturacion",
]


def _es_generico(texto: str) -> bool:
    return any(p in texto for p in GASTOS_GENERICOS)


# =============================================================================
# PROPUESTA DE GIRO
# =============================================================================

def proponer_giro(df) -> Dict[str, Any]:
    """
    Propone el giro pesando por MONTO. Lo que el contribuyente EMITE pesa el
    triple que lo que compra: vender tortillas identifica mejor que comprar gas.
    Devuelve la propuesta con su evidencia, para que se pueda juzgar de un vistazo.
    """
    vacio = {"propuesto": None, "nombre": "", "confianza": 0.0, "evidencia": [],
             "candidatos": []}
    if df is None or df.empty:
        return vacio

    puntos: Dict[str, float] = {g: 0.0 for g in GIROS}
    pruebas: Dict[str, List[Tuple[float, str]]] = {g: [] for g in GIROS}
    total = 0.0

    for fila in df.to_dict("records"):
        monto = abs(float(fila.get("Total") or 0)) or abs(float(fila.get("Importe Base") or 0))
        if monto <= 0:
            continue
        peso = 3.0 if str(fila.get("Origen")) == "EMITIDAS" else 1.0
        total += monto * peso

        texto = _norm(f"{fila.get('Nombre Emisor') or ''} {fila.get('Descripcion') or ''}")
        if not texto or _es_generico(texto):
            continue
        claves = {c.strip() for c in str(fila.get("Claves ProdServ") or "").split(",") if c.strip()}

        for giro, cfg in GIROS.items():
            pega = any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", texto)
                       for p in cfg["palabras"])
            if not pega and claves:
                pega = any(c.startswith(tuple(cfg["claves"])) for c in claves)
            if pega:
                puntos[giro] += monto * peso
                pruebas[giro].append((monto, str(fila.get("Nombre Emisor") or
                                                 fila.get("Descripcion") or "")[:44]))

    if total <= 0 or not any(puntos.values()):
        return vacio

    orden = sorted(puntos.items(), key=lambda kv: kv[1], reverse=True)
    mejor, puntaje = orden[0]
    if puntaje <= 0:
        return vacio

    evidencia = []
    vistos = set()
    for monto, quien in sorted(pruebas[mejor], reverse=True):
        if quien in vistos:
            continue
        vistos.add(quien)
        evidencia.append(f"{quien} — ${monto:,.2f}")
        if len(evidencia) >= 4:
            break

    return {
        "propuesto": mejor,
        "nombre": GIROS[mejor]["nombre"],
        "confianza": round(puntaje / total, 3),
        "evidencia": evidencia,
        "candidatos": [{"giro": g, "nombre": GIROS[g]["nombre"],
                        "peso": round(p / total, 3)}
                       for g, p in orden[:3] if p > 0],
    }


# =============================================================================
# LECTURA Y ESCRITURA DEL PERFIL
# =============================================================================

def ruta_perfil(rfc: str) -> str:
    return os.path.join(CARPETA, f"{(rfc or 'SIN_RFC').upper()}.json")


def cargar_perfil(rfc: str) -> Dict[str, Any]:
    ruta = ruta_perfil(rfc)
    if os.path.exists(ruta):
        try:
            with open(ruta, "r", encoding="utf-8") as fh:
                datos = json.load(fh)
            if isinstance(datos, dict):
                return datos
        except (json.JSONDecodeError, OSError):
            pass
    return {"rfc": (rfc or "").upper(), "nombre": "", "tipo_persona": "",
            "giro": {}, "emisores": {}, "creado": None, "actualizado": None}


def guardar_perfil(perfil: Dict[str, Any]) -> str:
    os.makedirs(CARPETA, exist_ok=True)
    perfil["actualizado"] = datetime.now().isoformat(timespec="seconds")
    perfil.setdefault("creado", perfil["actualizado"])
    ruta = ruta_perfil(perfil.get("rfc", ""))
    with open(ruta, "w", encoding="utf-8") as fh:
        json.dump(perfil, fh, indent=2, ensure_ascii=False)
    return ruta


def rfc_contribuyente(df) -> str:
    """El RFC que aparece en todos los comprobantes (como emisor o receptor)."""
    if df is None or df.empty:
        return ""
    conteo: Dict[str, int] = {}
    for fila in df[["RFC Emisor", "RFC Receptor"]].to_dict("records"):
        vistos = {str(v).strip().upper() for v in fila.values()
                  if v and str(v).strip().upper() not in ("", "XAXX010101000")}
        for rfc in vistos:
            conteo[rfc] = conteo.get(rfc, 0) + 1
    if not conteo:
        return ""
    return max(sorted(conteo), key=lambda r: conteo[r])


def actualizar_perfil(df, config: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Crea o actualiza el perfil del contribuyente con lo que diga esta tanda.

    Nunca pisa lo que el contador ya confirmo: el giro confirmado y las
    decisiones por proveedor se respetan; solo se agregan los proveedores nuevos,
    que entran como 'revisar'.
    """
    config = config or {}
    rfc = str(config.get("rfc_contribuyente") or "").strip().upper() or rfc_contribuyente(df)
    perfil = cargar_perfil(rfc)
    perfil["rfc"] = rfc
    perfil["tipo_persona"] = ("fisica" if len(rfc) == 13 else
                              "moral" if len(rfc) == 12 else "")

    if df is not None and not df.empty:
        propio = df[(df["RFC Emisor"] == rfc) | (df["RFC Receptor"] == rfc)]
        for col_rfc, col_nom in (("RFC Emisor", "Nombre Emisor"),
                                 ("RFC Receptor", "Nombre Receptor")):
            coincide = propio[propio[col_rfc] == rfc]
            if not coincide.empty and col_nom in coincide.columns:
                nombres = [n for n in coincide[col_nom].dropna().astype(str) if n.strip()]
                if nombres:
                    perfil["nombre"] = nombres[0]
                    break

        # --- Giro: se propone siempre, pero lo confirmado manda -------------
        propuesta = proponer_giro(df)
        giro = dict(perfil.get("giro") or {})
        giro.update({k: propuesta[k] for k in
                     ("propuesto", "nombre", "confianza", "evidencia", "candidatos")})
        giro.setdefault("confirmado", None)
        perfil["giro"] = giro

        # --- Catalogo de proveedores ---------------------------------------
        emisores: Dict[str, Any] = dict(perfil.get("emisores") or {})
        gastos = df[df["Origen"].isin(["RECIBIDAS", "EGRESOS"])]
        for fila in gastos.to_dict("records"):
            emisor = str(fila.get("RFC Emisor") or "").strip().upper()
            if not emisor or emisor == rfc:
                continue
            monto = abs(float(fila.get("Total") or 0))
            ficha = emisores.get(emisor) or {"decision": REVISAR, "nombre": "",
                                             "veces": 0, "monto": 0.0}
            ficha["nombre"] = ficha["nombre"] or str(fila.get("Nombre Emisor") or "")
            ficha["veces"] = int(ficha.get("veces", 0)) + 1
            ficha["monto"] = round(float(ficha.get("monto", 0.0)) + monto, 2)
            ficha.setdefault("decision", REVISAR)
            emisores[emisor] = ficha
        perfil["emisores"] = emisores

    guardar_perfil(perfil)
    return perfil


def decision_emisor(perfil: Dict[str, Any], rfc_emisor: str) -> str:
    """Que dijo el contador sobre este proveedor la ultima vez."""
    ficha = (perfil.get("emisores") or {}).get(str(rfc_emisor or "").strip().upper())
    return str(ficha.get("decision")) if ficha else REVISAR


def resumen(perfil: Dict[str, Any]) -> Dict[str, Any]:
    """Version corta para el dashboard."""
    emisores = perfil.get("emisores") or {}
    cuenta: Dict[str, int] = {}
    for ficha in emisores.values():
        d = str(ficha.get("decision", REVISAR))
        cuenta[d] = cuenta.get(d, 0) + 1
    giro = perfil.get("giro") or {}
    return {
        "rfc": perfil.get("rfc", ""),
        "nombre": perfil.get("nombre", ""),
        "tipo_persona": perfil.get("tipo_persona", ""),
        "giro_confirmado": giro.get("confirmado"),
        "giro_propuesto": giro.get("propuesto"),
        "giro_nombre": (GIROS.get(giro.get("confirmado") or giro.get("propuesto") or "",
                                  {}).get("nombre", "")),
        "confianza": giro.get("confianza", 0),
        "evidencia": giro.get("evidencia", []),
        "candidatos": giro.get("candidatos", []),
        "emisores_total": len(emisores),
        "emisores_por_decision": cuenta,
        "archivo": ruta_perfil(perfil.get("rfc", "")),
    }
