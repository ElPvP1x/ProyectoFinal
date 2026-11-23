"""Flujo completo Bronce -> Plata -> Oro con puerta de calidad. Falla (exit 1) si la calidad no alcanza."""
import sys
import plata, oro, geo

MAX_PCT_CUARENTENA = 5.0   # objetivo de calidad: no mas de 5 % de registros a cuarentena
MIN_MESES = 36


def main() -> int:
    p = plata.ejecutar()
    print(f"Bronce: {p['registros_bronce']} registros | validos: {p['validos']} | cuarentena: {p['cuarentena']} ({p['pct_cuarentena']} %)")
    for k, v in p["motivos"].items():
        print(f"  cuarentena por {k}: {v}")
    for s, i in p["series"].items():
        print(f"  {s}: faltantes={i['faltantes']['faltantes']} ({i['faltantes']['mecanismo']}), "
              f"imputacion={i['metodo_imputacion']}, atipicos(consenso)={i['atipicos']['consenso_2_o_mas']}")
    o = oro.ejecutar()
    print(f"Oro: {o['meses_completos']} meses completos de {o['meses_integrados']}; variables: {', '.join(o['variables_conservadas'])}")
    if o["variables_descartadas"]:
        print("  descartadas:", o["variables_descartadas"])
    try:   # E2: fuente geoespacial (OSM + geoBoundaries)
        g = geo.ejecutar()
        print(f"Geo: {g['validos']} puntos validos, {g['cuarentena']} en cuarentena; {g['entidades']} entidades; {g['por_categoria']}")
    except FileNotFoundError as e:
        print("AVISO geo:", e, file=sys.stderr)
    fallas = []
    if p["pct_cuarentena"] > MAX_PCT_CUARENTENA:
        fallas.append(f"cuarentena {p['pct_cuarentena']} % > {MAX_PCT_CUARENTENA} %")
    if o["meses_completos"] < MIN_MESES:
        fallas.append(f"solo {o['meses_completos']} meses completos (< {MIN_MESES})")
    if fallas:
        print("PUERTA DE CALIDAD NO SUPERADA:", "; ".join(fallas), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
