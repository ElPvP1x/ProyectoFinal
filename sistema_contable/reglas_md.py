# -*- coding: utf-8 -*-
"""
reglas_md.py
------------
Reglas fiscales tomadas de la investigacion "Lo que el contador revisa, descarta
y corrige a mano en las facturas de sus clientes" (19-nov-2026) que el motor aun
no aplicaba. Todo se puede apagar o ajustar desde config_reglas.json.

Cada regla cita su fundamento. Lo marcado [Ley] se verifico en el texto oficial
segun la investigacion; lo marcado [Practica] es costumbre de los despachos, no
obligacion textual, y por eso solo genera una ALERTA (no excluye el CFDI).

Rechazos (el CFDI no suma):
  Regla 7  RFC generico, factura a nombre de otro RFC, uso S01       [Ley: CFF 29-A]
  Regla 8  Proveedor en lista 69-B definitiva                         [Ley: CFF 69-B]
  Regla 9  CFDI de otro ejercicio                                     [Ley: LISR 27-XVIII]
No suman pero tampoco se rechazan:
  Inversion (uso I01-I08): se deprecia, no se deduce en el mes        [Ley: LISR 34]
  Sustitucion (relacion 04): la factura original se reemplazo         [Ley: CFF 29-A]
Deduccion parcial:
  Restaurante: 8.5 % si se pago con tarjeta o monedero                [Ley: LISR 28-XX]
Alertas (no cambian la suma): ver `alertas()`.
"""
from __future__ import annotations

import csv
import os
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

RFC_GENERICO = "XAXX010101000"

# Uso del CFDI de inversiones -> (descripcion, tasa anual de depreciacion o None)
# Tasas [Ley: LISR 34]. Para I06-I08 la investigacion no da tasa: no se inventa.
USOS_INVERSION: Dict[str, Tuple[str, Optional[float]]] = {
    "I01": ("Construcciones", 0.05),
    "I02": ("Mobiliario y equipo de oficina", 0.10),
    "I03": ("Equipo de transporte", 0.25),
    "I04": ("Equipo de computo", 0.30),
    "I05": ("Dados, troqueles, moldes, matrices y herramental", 0.35),
    "I06": ("Comunicaciones telefonicas", None),
    "I07": ("Comunicaciones satelitales", None),
    "I08": ("Otra maquinaria y equipo", None),
}

MOTIVOS_MD = {
    "generico": "Regla 7 - Factura a PUBLICO EN GENERAL (RFC generico XAXX010101000): no esta a "
                "nombre del contribuyente, no es deducible ni acreditable (CFF 29-A). Pedir factura nominativa.",
    "otro_receptor": "Regla 7 - El receptor es {receptor}, no el contribuyente ({rfc}). No es deducible "
                     "ni acreditable (CFF 29-A). Pedir sustitucion de la factura.",
    "s01": "Regla 7 - Uso del CFDI S01 (Sin efectos fiscales): el receptor declaro que no la usara para deducir.",
    "69b": "Regla 8 - Proveedor {rfc} en la lista 69-B DEFINITIVA del SAT: la factura no produce efecto "
           "fiscal (CFF 69-B). Hay 30 dias para probar que la operacion existio o corregir.",
    "ejercicio": "Regla 9 - CFDI de {anio}, fuera del ejercicio {ejercicio}: no se deduce en este "
                 "ejercicio (LISR 27-XVIII). Reubicarlo.",
    "inversion": "Inversion (uso {uso} - {desc}): no se deduce en el mes, se deprecia{tasa}. "
                 "Va a activo fijo (LISR 34). El IVA si cuenta como acreditable segun su destino.",
    "sustituida": "Factura SUSTITUIDA: otro CFDI (relacion 04) la reemplaza. Solo cuenta la nueva, "
                  "para no deducir dos veces.",
    "restaurante": "Restaurante: solo se deduce el {pct} pagado con tarjeta o monedero electronico "
                   "(LISR 28-XX). El resto no es deducible, ni su IVA acreditable.",
    "restaurante_forma": "Restaurante pagado con '{forma}': solo es deducible con tarjeta de credito, "
                         "debito, de servicios o monedero electronico (LISR 28-XX).",
}

PALABRAS_GENERICAS = {
    "servicio", "servicios", "consumo", "consumos", "varios", "venta", "ventas",
    "compra", "compras", "mercancia", "mercancias", "producto", "productos",
    "gasto", "gastos", "pago", "concepto", "otros",
}
# Facturas con uso I0x que NO son la compra del bien: son gasto del mes (LISR 36-I: reparaciones y mantenimiento)
PALABRAS_NO_INVERSION = ["interes", "intereses", "financiamiento", "comision", "comisiones", "seguro",
                         "mantenimiento", "reparacion", "reparaciones", "renta", "arrendamiento",
                         "refaccion", "refacciones", "gasolina"]
PALABRAS_BAR = ("bar", "cantina", "cerveza", "vino", "licor", "alcohol")


def _norm(texto: Any) -> str:
    t = unicodedata.normalize("NFKD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t).strip()


def _palabra(desc: str, palabra: str) -> bool:
    p = _norm(palabra)
    if not p or not desc:
        return False
    return bool(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", desc))


# =============================================================================
# Lista 69-B
# =============================================================================

def cargar_69b(cfg: Dict[str, Any], carpeta: str) -> Tuple[Set[str], Set[str]]:
    """
    Devuelve (definitivos, presuntos). Fuentes, de menor a mayor prioridad:
      * config: "rfc_69b_definitivos" y "rfc_69b_presuntos" (listas de RFC)
      * archivo CSV del SAT (por defecto lista_69b.csv junto a la aplicacion,
        o la ruta de "archivo_69b"): columnas RFC y "Situacion del contribuyente".
        Sin columna de situacion, todos se toman como definitivos.
    El sistema no descarga la lista: el SAT la publica y la cambia seguido.
    """
    defin = {str(r).strip().upper() for r in cfg.get("rfc_69b_definitivos", []) if str(r).strip()}
    presu = {str(r).strip().upper() for r in cfg.get("rfc_69b_presuntos", []) if str(r).strip()}
    ruta = str(cfg.get("archivo_69b") or "lista_69b.csv")
    if not os.path.isabs(ruta):
        ruta = os.path.join(carpeta, ruta)
    if not os.path.isfile(ruta):
        return defin, presu
    texto = None
    for cod in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            with open(ruta, encoding=cod, newline="") as fh:
                texto = fh.read()
            break
        except UnicodeDecodeError:
            continue
    if not texto:
        return defin, presu
    filas = list(csv.reader(texto.splitlines()))
    # el encabezado puede no estar en la primera linea (el SAT agrega titulos)
    ini = next((i for i, f in enumerate(filas) if any(_norm(c) == "rfc" for c in f)), None)
    if ini is None:
        return defin, presu
    enc = [_norm(c) for c in filas[ini]]
    i_rfc = enc.index("rfc")
    i_sit = next((i for i, c in enumerate(enc) if c.startswith("situacion")), None)
    for fila in filas[ini + 1:]:
        if len(fila) <= i_rfc:
            continue
        rfc = fila[i_rfc].strip().upper()
        if not re.fullmatch(r"[A-Z&\xd1]{3,4}\d{6}[A-Z0-9]{3}", rfc):
            continue
        sit = _norm(fila[i_sit]) if i_sit is not None and len(fila) > i_sit else "definitivo"
        if "definitiv" in sit:
            defin.add(rfc)
        elif "presunt" in sit:
            presu.add(rfc)
    return defin, presu


# =============================================================================
# Contexto: todo lo que las reglas necesitan, armado una sola vez
# =============================================================================

@dataclass
class Contexto:
    rfc_certero: str = ""
    definitivos: Set[str] = field(default_factory=set)
    presuntos: Set[str] = field(default_factory=set)
    ejercicio: Optional[int] = None
    cp_contribuyente: str = ""
    regimen_contribuyente: str = ""
    separar_inversiones: bool = True
    rechazar_generico: bool = True
    rest_modo: str = "parcial"            # "parcial" | "rechazar"
    rest_pct: float = 0.085
    rest_palabras: List[str] = field(default_factory=list)
    rest_claves: Tuple[str, ...] = ()
    rest_formas: Set[str] = field(default_factory=set)
    alertas_activas: bool = True
    no_inversion: List[str] = field(default_factory=list)
    tope_auto: float = 175000.0
    tope_auto_electrico: float = 250000.0
    tope_lentes: float = 2500.0


def construir_contexto(cfg: Dict[str, Any], carpeta: str) -> Contexto:
    defin, presu = cargar_69b(cfg, carpeta)
    ej = cfg.get("ejercicio_fiscal")
    try:
        ej = int(ej) if ej not in (None, "", 0) else None
    except (TypeError, ValueError):
        ej = None
    rest = cfg.get("restaurantes", {}) or {}
    return Contexto(
        rfc_certero=str(cfg.get("_rfc_certero", "") or "").strip().upper(),
        definitivos=defin, presuntos=presu, ejercicio=ej,
        cp_contribuyente=str(cfg.get("cp_contribuyente", "") or "").strip(),
        regimen_contribuyente=str(cfg.get("regimen_contribuyente", "") or "").strip(),
        separar_inversiones=bool(cfg.get("separar_inversiones", True)),
        rechazar_generico=bool(cfg.get("rechazar_rfc_generico", True)),
        rest_modo=str(rest.get("modo", "parcial")).lower(),
        rest_pct=float(rest.get("porcentaje", 0.085)),
        rest_palabras=[_norm(p) for p in rest.get("palabras", ["restaurante", "restaurant",
                       "consumo en restaurante", "alimentos y bebidas"]) if _norm(p)],
        rest_claves=tuple(str(c).strip() for c in rest.get("claves_prodserv", ["90101501"]) if str(c).strip()),
        rest_formas={str(f).strip().zfill(2) for f in rest.get("formas_pago", ["04", "05", "28", "29"])},
        alertas_activas=bool(cfg.get("alertas", True)),
        no_inversion=[_norm(p) for p in cfg.get("palabras_no_inversion", PALABRAS_NO_INVERSION) if _norm(p)],
        tope_auto=float(cfg.get("tope_auto", 175000.0)),
        tope_auto_electrico=float(cfg.get("tope_auto_electrico", 250000.0)),
        tope_lentes=float(cfg.get("tope_lentes", 2500.0)),
    )


# =============================================================================
# Reglas
# =============================================================================

def rechazo_formal(f, ctx: Contexto) -> Optional[Tuple[str, str, str]]:
    """(clasificacion, regla, motivo) si el gasto recibido no cumple lo formal; si no, None."""
    receptor = str(f.get("RFC Receptor") or "").strip().upper()
    emisor = str(f.get("RFC Emisor") or "").strip().upper()
    uso = str(f.get("Uso CFDI") or "").strip().upper()

    if ctx.rechazar_generico and receptor == RFC_GENERICO:
        return "Rechazado", "Regla 7", MOTIVOS_MD["generico"]
    if ctx.rfc_certero and receptor and receptor != ctx.rfc_certero:
        return "Rechazado", "Regla 7", MOTIVOS_MD["otro_receptor"].format(
            receptor=receptor, rfc=ctx.rfc_certero)
    if uso == "S01":
        return "Rechazado", "Regla 7", MOTIVOS_MD["s01"]
    if emisor and emisor in ctx.definitivos:
        return "Rechazado", "Regla 8", MOTIVOS_MD["69b"].format(rfc=emisor)
    if ctx.ejercicio:
        fecha = f.get("Fecha Emision")
        anio = getattr(fecha, "year", None)
        if anio and anio != ctx.ejercicio:
            return "Rechazado", "Regla 9", MOTIVOS_MD["ejercicio"].format(
                anio=anio, ejercicio=ctx.ejercicio)
    return None


def inversion(f, ctx: Contexto) -> Optional[Tuple[str, str]]:
    """(descripcion, texto_tasa) si el CFDI declara uso de inversion (I01-I08)."""
    if not ctx.separar_inversiones:
        return None
    uso = str(f.get("Uso CFDI") or "").strip().upper()
    if uso in USOS_INVERSION:
        # El uso lo declara el receptor sobre el BIEN, pero la factura puede ser de algo que
        # si es gasto del mes (intereses, seguro, mantenimiento): esas no son inversion.
        desc_f = f.get("_Descripcion_Norm") or _norm(f.get("Descripcion"))
        if any(_palabra(desc_f, p) for p in ctx.no_inversion):
            return None
        desc, tasa = USOS_INVERSION[uso]
        extra = ""
        if uso == "I03":   # automoviles: solo se deprecia hasta el tope [Ley: LISR 36-II]
            sub = float(f.get("Subtotal") or 0) - float(f.get("Descuento") or 0)
            electrico = any(_palabra(desc_f, w) for w in ("electrico", "hibrido", "electrica", "hibrida"))
            tope = ctx.tope_auto_electrico if electrico else ctx.tope_auto
            if sub > tope:
                extra = (f". El precio ({sub:,.2f}) pasa el tope de {tope:,.0f} (LISR 36-II): solo se "
                         f"deprecia el {tope / sub:.2%} y los gastos del auto y su IVA van en esa proporcion")
        return desc, (f" ({tasa:.0%} anual)" if tasa else "") + extra
    return None


def es_restaurante(f, ctx: Contexto) -> bool:
    """Restaurante por clave del SAT (XML) o por la descripcion. Los bares nunca califican."""
    if ctx.rest_modo != "parcial":
        return False
    desc = f.get("_Descripcion_Norm") or _norm(f.get("Descripcion"))
    if any(_palabra(desc, p) for p in PALABRAS_BAR):
        return False
    claves = [c.strip() for c in str(f.get("Claves ProdServ") or "").split(",") if c.strip()]
    if ctx.rest_claves and any(c.startswith(ctx.rest_claves) for c in claves):
        return True
    return any((p in desc) if " " in p else _palabra(desc, p) for p in ctx.rest_palabras)


def marcar_sustituidos(df) -> "pd.Series":  # noqa: F821
    """True en las facturas que otra factura vigente reemplaza con relacion 04."""
    import pandas as pd
    if df.empty or "UUID Sustituidos" not in df.columns:
        return pd.Series(False, index=df.index)
    reemplazados: Set[str] = set()
    for _, r in df.iterrows():
        estatus = _norm(r.get("Estatus"))
        if estatus.startswith("cancel") and "cancelable" not in estatus:
            continue  # una sustituta cancelada no reemplaza nada
        for u in str(r.get("UUID Sustituidos") or "").split(","):
            u = u.strip().upper()
            if u:
                reemplazados.add(u)
    return df["UUID"].astype(str).str.upper().isin(reemplazados)


# =============================================================================
# Alertas: avisos al contador que NO cambian la suma
# =============================================================================

def alertas(f, ctx: Contexto, tope_tolerancia: float = 1.0) -> List[str]:
    if not ctx.alertas_activas:
        return []
    out: List[str] = []
    tipo = str(f.get("Tipo Comprobante") or "")
    origen = str(f.get("Origen") or "").upper()
    desc = f.get("_Descripcion_Norm") or _norm(f.get("Descripcion"))
    emisor = str(f.get("RFC Emisor") or "").strip().upper()
    es_xml = bool(str(f.get("Version CFDI") or "").strip())
    subtotal = float(f.get("Subtotal") or 0) - float(f.get("Descuento") or 0)
    iva = float(f.get("IVA") or 0)
    isr_ret = float(f.get("ISR Retenido") or 0)
    iva_ret = float(f.get("IVA Retenido") or 0)
    receptor = str(f.get("RFC Receptor") or "").strip().upper()
    gasto = origen in ("RECIBIDAS", "EGRESOS")

    # Notas de credito sin CFDI relacionado: no se pueden ligar a la factura original
    if tipo == "E" and es_xml and not str(f.get("Tipo Relacion") or "").strip():
        out.append("Nota de credito sin CFDI relacionado: pedir la relacion 01 (LIVA 7)")

    # Descripcion generica
    if gasto and tipo == "I" and desc:
        if desc in PALABRAS_GENERICAS or len(desc) < 4:
            out.append("Descripcion generica: pedir detalle de lo comprado (CFF 29-A-V)")

    # PUE/PPD incongruentes con la forma de pago
    forma = str(f.get("Forma Pago") or "")
    metodo = str(f.get("Metodo Pago") or "")
    if gasto and tipo == "I":
        if metodo == "PUE" and forma == "99":
            out.append("PUE con forma de pago 99 (Por definir): incongruente, pedir correccion")
        if metodo == "PPD" and forma not in ("", "99"):
            out.append(f"PPD con forma de pago {forma}: deberia ser 99 (Por definir)")

    # Retenciones: persona moral que paga a persona fisica con honorarios o renta
    if gasto and tipo == "I" and es_xml and subtotal > 0:
        regimen_emisor = str(f.get("Regimen Emisor") or "").strip()
        pm_receptor = len(receptor) == 12
        pf_emisor = len(emisor) == 13
        if pm_receptor and pf_emisor and regimen_emisor in ("612", "606", "626") and iva > 0 \
                and not isr_ret and not iva_ret:
            out.append("Posible falta de retencion (ISR 10 % o 1.25 % RESICO; IVA 2/3) si es honorario "
                       "o renta: revisar (LISR 27-V, 106, 116; RLIVA 3)")
        if isr_ret and regimen_emisor in ("612", "606"):
            esperado = round(subtotal * 0.10, 2)
            resico = round(subtotal * 0.0125, 2)
            if abs(isr_ret - esperado) > tope_tolerancia and abs(isr_ret - resico) > tope_tolerancia:
                out.append(f"ISR retenido {isr_ret:,.2f} no coincide con el 10 % de la base ({esperado:,.2f})")
        if iva_ret and iva > 0:
            dos_tercios = round(iva * 2 / 3, 2)
            transporte = round(subtotal * 0.04, 2)
            total_iva = round(iva, 2)
            if all(abs(iva_ret - v) > tope_tolerancia for v in (dos_tercios, transporte, total_iva)):
                out.append(f"IVA retenido {iva_ret:,.2f} no coincide con 2/3 del IVA ({dos_tercios:,.2f}), "
                           f"4 % de fletes ({transporte:,.2f}) ni el IVA completo")

    # Datos del receptor contra la constancia del contribuyente (solo si se capturaron)
    if gasto and es_xml:
        if ctx.cp_contribuyente and str(f.get("CP Receptor") or "").strip() \
                and str(f.get("CP Receptor")).strip() != ctx.cp_contribuyente:
            out.append(f"Codigo postal del receptor ({f.get('CP Receptor')}) distinto al de la constancia "
                       f"({ctx.cp_contribuyente}): pedir sustitucion (CFF 29-A)")
        if ctx.regimen_contribuyente and str(f.get("Regimen Receptor") or "").strip() \
                and str(f.get("Regimen Receptor")).strip() != ctx.regimen_contribuyente:
            out.append(f"Regimen del receptor ({f.get('Regimen Receptor')}) distinto al de la constancia "
                       f"({ctx.regimen_contribuyente}): pedir sustitucion (CFF 29-A)")

    # Estatus consultado en el SAT (solo existe si se activo verificar_estatus_sat)
    est = str(f.get("Estatus SAT Consulta") or "")
    canc = str(f.get("Cancelacion SAT") or "")
    if est.lower().startswith("no encontrado"):
        out.append("El SAT no encontro este CFDI: revisa UUID, RFC y total (con divisa, el total debe ser "
                   "el original) o puede no estar timbrado")
    if est == "Vigente" and canc and "proceso" in _norm(canc):
        out.append(f"Cancelacion EN PROCESO ({canc}): vigila el resultado antes de deducirla")
    efos = str(f.get("EFOS SAT") or "").strip()
    if efos and efos != "200":
        out.append(f"El SAT reporta validacion EFOS con codigo {efos} (distinto de 200): confirma si el "
                   f"emisor esta en la lista 69-B (CFF 69-B)")

    # PPD: ligar con su complemento de pago (REP) dentro de la tanda [Ley: LIVA 5-III]
    if tipo == "I" and metodo == "PPD" and origen in ("RECIBIDAS", "EGRESOS", "EMITIDAS"):
        if f.get("_Tiene_REP"):
            pass
        elif f.get("_Hay_REP_en_tanda"):
            out.append("PPD sin REP ligado en esta tanda: el IVA no es acreditable hasta que se pague (LIVA 5-III)")
        else:
            out.append("PPD: no se cargo ningun REP (archivo de Pagos); sin el, su IVA no es acreditable")

    # Anticipos: no deducir dos veces [Ley: LISR 27-XVIII]. El procedimiento de CFDI es regla SAT.
    rel = str(f.get("Tipo Relacion") or "")
    if "07" in [x.strip() for x in rel.split(",")] or (tipo == "E" and forma == "30"):
        out.append("Anticipo (relacion 07 / forma 30): registrar una sola vez entre la factura del anticipo "
                   "y la de la operacion total; el anticipo se deduce en su ano si la factura total llega "
                   "a mas tardar el ultimo dia del ano siguiente (LISR 27-XVIII)")

    # Lentes: tope por persona al ano [Ley: RLISR 264]
    uso_f = str(f.get("Uso CFDI") or "").strip().upper()
    if uso_f.startswith("D") and (_palabra(desc, "lentes") or _palabra(desc, "lente")):
        base_lentes = float(f.get("Subtotal") or 0) - float(f.get("Descuento") or 0)
        txt = f"Lentes graduados: tope de {ctx.tope_lentes:,.0f} por persona al ano (RLISR 264)"
        if base_lentes > ctx.tope_lentes:
            txt += f"; esta factura ({base_lentes:,.2f}) lo excede"
        out.append(txt)

    # 69-B presunto: todavia no es definitivo, pero hay que vigilarlo
    if gasto and emisor and emisor in ctx.presuntos:
        out.append(f"Proveedor {emisor} en lista 69-B como PRESUNTO: vigilar y juntar pruebas de la operacion")
    return out
