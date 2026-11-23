"""Fuente especializada geoespacial (E2): Bronce -> Plata -> Oro con GeoPandas.

Bronce  osm_overpass/infraestructura_contable_mx/<captura>.json   (puntos OSM, ODbL)
        geoboundaries/entidades_mx_adm1/<captura>.json             (32 entidades, CC BY 3.0 IGO)
Plata   datos/plata/geo_puntos.csv     un punto por elemento OSM: categoria, lon, lat, entidad + linaje
Oro     datos/oro/geo_entidades.csv    conteos y densidad por entidad + linaje
        docs/E2/mapa_infraestructura.png

Privacidad: de OSM sólo se conservan id, tipo, categoría y coordenadas. Nombres, teléfonos,
correos y direcciones se descartan al leer Bronce, y el producto final está agregado por entidad.
"""
import json, pathlib, re
import geopandas as gpd
import pandas as pd
import denue, linaje

RAIZ = pathlib.Path(__file__).resolve().parents[1]
CRS_MX = "EPSG:6372"  # Mexico ITRF2008 / LCC: áreas en metros
CAJA_MX = (-118.6, 14.3, -86.5, 32.8)  # lon_min, lat_min, lon_max, lat_max
CATEGORIAS = ["despacho_contable", "asesor_fiscal", "oficina_sat", "recaudacion_local", "banco"]


def categoria(tags: dict) -> str | None:
    if tags.get("office") == "accountant":
        return "despacho_contable"
    if tags.get("office") == "tax_advisor":
        return "asesor_fiscal"
    nombre = tags.get("name", "").lower()
    if "administración tributaria" in nombre or "administracion tributaria" in nombre or re.match(r"sat\b", nombre):
        return "oficina_sat"          # federal
    if tags.get("government") == "tax":
        return "recaudacion_local"    # recaudadoras y tesorerías estatales o municipales
    if tags.get("amenity") == "bank":
        return "banco"
    return None


def _ultima(raiz, fuente, serie, patron="*.json"):
    snaps = sorted((raiz / "datos" / "bronce" / fuente / serie).glob(patron))
    if not snaps:
        raise FileNotFoundError(f"no hay captura de {fuente}/{serie}: correr src/extractor_geo.py")
    return snaps[-1]


def leer_puntos(ruta: pathlib.Path, ficha: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Devuelve (validos, cuarentena). Sólo se leen campos no personales."""
    elems = json.loads(ruta.read_text(encoding="utf-8"))["elements"]
    filas = []
    for e in elems:
        lon, lat = (e.get("lon"), e.get("lat")) if e["type"] == "node" else \
                   (e.get("center", {}).get("lon"), e.get("center", {}).get("lat"))
        filas.append({"osm_tipo": e["type"], "osm_id": e["id"], "categoria": categoria(e.get("tags", {})),
                      "lon": lon, "lat": lat})
    df = pd.DataFrame(filas, columns=["osm_tipo", "osm_id", "categoria", "lon", "lat"])
    motivo = pd.Series("", index=df.index)
    motivo[df["categoria"].isna()] += "categoria_no_reconocida; "
    motivo[df["lon"].isna() | df["lat"].isna()] += "sin_coordenadas; "
    fuera = ~(df["lon"].between(CAJA_MX[0], CAJA_MX[2]) & df["lat"].between(CAJA_MX[1], CAJA_MX[3]))
    motivo[fuera & df["lon"].notna()] += "fuera_de_mexico; "
    motivo[df.duplicated(["osm_tipo", "osm_id"])] += "duplicado; "
    df = df.assign(**{k: v for k, v in ficha.items() if k not in ("fuente", "serie")})
    mal = motivo.ne("")
    return df[~mal].reset_index(drop=True), df[mal].assign(motivo=motivo[mal].str.rstrip("; ")).reset_index(drop=True)


def leer_entidades(ruta: pathlib.Path) -> gpd.GeoDataFrame:
    g = gpd.read_file(ruta)[["shapeName", "shapeISO", "geometry"]]
    g = g.rename(columns={"shapeName": "entidad", "shapeISO": "clave_iso"})
    g["entidad"] = g["entidad"].replace({"Distrito Federal": "Ciudad de México"})  # nombre oficial desde 2016
    g.loc[g["entidad"] == "Ciudad de México", "clave_iso"] = "MX-CMX"  # geoBoundaries le pone MX-MEX, igual que al Edomex
    return g.set_crs("EPSG:4326", allow_override=True)


def asignar_entidad(puntos: pd.DataFrame, entidades: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Unión espacial punto-en-polígono. Los puntos en la costa que caen fuera del polígono
    simplificado se asignan a la entidad más cercana (máximo 5 km) y se marcan."""
    gp = gpd.GeoDataFrame(puntos, geometry=gpd.points_from_xy(puntos["lon"], puntos["lat"]), crs="EPSG:4326")
    dentro = gpd.sjoin(gp, entidades[["entidad", "clave_iso", "geometry"]], how="left", predicate="within")
    dentro = dentro[~dentro.index.duplicated()].drop(columns="index_right")
    dentro["asignacion"] = "dentro"
    faltan = dentro["entidad"].isna()
    if faltan.any():
        cerca = gpd.sjoin_nearest(gp[faltan].to_crs(CRS_MX), entidades.to_crs(CRS_MX)[["entidad", "clave_iso", "geometry"]],
                                  how="left", max_distance=5000)
        cerca = cerca[~cerca.index.duplicated()]
        dentro.loc[faltan, ["entidad", "clave_iso"]] = cerca[["entidad", "clave_iso"]].to_numpy()
        dentro.loc[faltan, "asignacion"] = "mas_cercana_5km"
    dentro.loc[dentro["entidad"].isna(), "asignacion"] = "sin_entidad"
    return dentro


def resumir(puntos: gpd.GeoDataFrame, entidades: gpd.GeoDataFrame, lin_puntos: dict, lin_ent: dict) -> gpd.GeoDataFrame:
    conteo = pd.crosstab(puntos["entidad"], puntos["categoria"]).reindex(columns=CATEGORIAS, fill_value=0)
    ent = entidades.copy()
    ent["area_km2"] = ent.to_crs(CRS_MX).area / 1e6
    ent = ent.merge(conteo, left_on="entidad", right_index=True, how="left")
    ent[CATEGORIAS] = ent[CATEGORIAS].fillna(0).astype(int)
    ent["total"] = ent[CATEGORIAS].sum(axis=1)
    ent["contables_y_fiscales"] = ent[["despacho_contable", "asesor_fiscal", "oficina_sat", "recaudacion_local"]].sum(axis=1)
    ent["bancos_por_1000km2"] = 1000 * ent["banco"] / ent["area_km2"]
    ent["pct_nacional_bancos"] = 100 * ent["banco"] / max(ent["banco"].sum(), 1)
    # Linaje: cada fila apunta a los dos archivos de Bronce que la formaron
    ent["archivo_bronce_puntos"], ent["sha256_bronce_puntos"] = lin_puntos["archivo_bronce"], lin_puntos["sha256_bronce"]
    ent["archivo_bronce_entidades"], ent["sha256_bronce_entidades"] = lin_ent["archivo_bronce"], lin_ent["sha256_bronce"]
    ent["fecha_ingesta"] = max(lin_puntos["fecha_ingesta"], lin_ent["fecha_ingesta"])
    return ent.sort_values("entidad").reset_index(drop=True)


def mapa(ent: gpd.GeoDataFrame, puntos: gpd.GeoDataFrame, ruta: pathlib.Path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    e = ent.to_crs(CRS_MX)
    p = puntos.to_crs(CRS_MX)
    fig, ax = plt.subplots(figsize=(11, 7.5))
    e.plot(column="bancos_por_1000km2", cmap="Blues", scheme="Quantiles", k=5, legend=True, ax=ax,
           edgecolor="white", linewidth=0.6,
           legend_kwds={"title": "Bancos por 1,000 km²", "loc": "lower left", "fontsize": 9, "title_fontsize": 9,
                        "fmt": "{:.1f}", "frameon": False})
    escala = ax.get_legend()
    estilos = {"despacho_contable": ("#d23a2a", "o", "Despacho contable"),
               "asesor_fiscal": ("#e08a1e", "s", "Asesor fiscal"),
               "oficina_sat": ("#111111", "^", "Oficina del SAT"),
               "recaudacion_local": ("#7a5cc2", "v", "Recaudación estatal o municipal")}
    for cat, (color, marca, etiqueta) in estilos.items():
        sub = p[p["categoria"] == cat]
        if len(sub):
            sub.plot(ax=ax, color=color, marker=marca, markersize=18, label=f"{etiqueta} ({len(sub)})",
                     edgecolor="white", linewidth=0.4)
    nombres = tuple(v[2] for v in estilos.values())
    hs = [(h, l) for h, l in zip(*ax.get_legend_handles_labels()) if l.startswith(nombres)]
    ax.legend(*zip(*hs), loc="upper right", fontsize=9, frameon=False)
    ax.add_artist(escala)  # conserva la leyenda de la escala de color
    ax.set_axis_off()
    ax.set_title("Infraestructura contable y fiscal en OpenStreetMap, por entidad", fontsize=13, loc="left")
    fecha = ent["fecha_ingesta"].iloc[0][:10]
    fig.text(0.01, 0.01, f"Fuente: © colaboradores de OpenStreetMap (ODbL), captura {fecha}; límites: geoBoundaries / INEGI "
             "(CC BY 3.0 IGO). Densidad en clases por quintiles.", fontsize=8, color="#555")
    ruta.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(ruta, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _denue(raiz, entidades, ent, lin_e, dp, do, dq, con_mapa) -> dict:
    """Segunda fuente: DENUE. Si aun no hay captura (la baja GitHub Actions), se omite con aviso."""
    try:
        r = _ultima(raiz, "inegi_denue", "denue_sector54", "*.zip")
    except FileNotFoundError as e:
        print("AVISO denue:", e)
        return {"capturado": False}
    lin_d = linaje.ficha_archivo(raiz, r)
    validos, cuarentena = denue.leer(r, lin_d)
    pts = asignar_entidad(validos, entidades).rename(columns={"entidad": "entidad_geo"})
    pts = pts.rename(columns={"entidad_denue": "entidad"}) if "entidad_denue" in pts else pts
    pts.drop(columns="geometry").to_csv(dp / "geo_denue_contables.csv", index=False, encoding="utf-8")
    cuarentena.to_csv(dq / "geo_denue_cuarentena.csv", index=False, encoding="utf-8")
    municipios = denue.por_municipio(pts, lin_d, lin_e)
    municipios.to_csv(do / "geo_municipios.csv", index=False, encoding="utf-8")
    conteo = denue.por_entidad(pts[pts["entidad_geo"].notna()])
    for c in conteo.columns:
        ent[c] = ent["entidad"].map(conteo[c]).fillna(0).astype(int)
    ent["denue_por_1000km2"] = 1000 * ent["denue_contables"] / ent["area_km2"]
    ent["pct_nacional_denue"] = 100 * ent["denue_contables"] / max(ent["denue_contables"].sum(), 1)
    osm = ent["despacho_contable"] + ent["asesor_fiscal"]
    ent["cobertura_osm_pct"] = (100 * osm / ent["denue_contables"].where(ent["denue_contables"] > 0)).round(2)
    ent["archivo_bronce_denue"], ent["sha256_bronce_denue"] = lin_d["archivo_bronce"], lin_d["sha256_bronce"]
    ent["fecha_ingesta"] = ent["fecha_ingesta"].where(ent["fecha_ingesta"] > lin_d["fecha_ingesta"], lin_d["fecha_ingesta"])
    ent.drop(columns="geometry").to_csv(do / "geo_entidades.csv", index=False, encoding="utf-8")
    if con_mapa:
        denue.mapa(ent, raiz / "docs" / "E2" / "mapa_despachos_denue.png", lin_d["fecha_ingesta"])
    return {"capturado": True, "registros": int(len(validos) + len(cuarentena)), "validos": int(len(validos)),
            "cuarentena": int(len(cuarentena)),
            "por_clase": pts["clase"].value_counts().to_dict(),
            "de_11_o_mas_personas": int(pts["de_11_o_mas"].sum()),
            "concordancia_entidad_pct": denue.concordancia(pts),
            "asignacion": pts["asignacion"].value_counts().to_dict(),
            "osm_entre_denue_pct": round(100 * float(osm.sum()) / max(int(ent["denue_contables"].sum()), 1), 2),
            "municipios_con_despachos": int(len(municipios)),
            "linaje": lin_d}


def ejecutar(raiz=RAIZ, con_mapa=True) -> dict:
    r_pts = _ultima(raiz, "osm_overpass", "infraestructura_contable_mx")
    r_ent = _ultima(raiz, "geoboundaries", "entidades_mx_adm1")
    lin_p, lin_e = linaje.ficha_archivo(raiz, r_pts), linaje.ficha_archivo(raiz, r_ent)
    validos, cuarentena = leer_puntos(r_pts, lin_p)
    entidades = leer_entidades(r_ent)
    puntos = asignar_entidad(validos, entidades)
    ent = resumir(puntos[puntos["entidad"].notna()], entidades, lin_p, lin_e)

    dp, do, dq = (raiz / "datos" / c for c in ("plata", "oro", "cuarentena"))
    for d in (dp, do, dq):
        d.mkdir(parents=True, exist_ok=True)
    puntos.drop(columns="geometry").to_csv(dp / "geo_puntos.csv", index=False, encoding="utf-8")
    cuarentena.to_csv(dq / "geo_cuarentena.csv", index=False, encoding="utf-8")
    ent.drop(columns="geometry").to_csv(do / "geo_entidades.csv", index=False, encoding="utf-8")
    if con_mapa:
        mapa(ent, puntos[puntos["entidad"].notna()], raiz / "docs" / "E2" / "mapa_infraestructura.png")
    rep_denue = _denue(raiz, entidades, ent, lin_e, dp, do, dq, con_mapa)
    rep = {"elementos_bronce": int(len(validos) + len(cuarentena)), "validos": int(len(validos)),
           "cuarentena": int(len(cuarentena)),
           "motivos_cuarentena": cuarentena["motivo"].value_counts().to_dict() if len(cuarentena) else {},
           "por_categoria": puntos["categoria"].value_counts().to_dict(),
           "asignacion": puntos["asignacion"].value_counts().to_dict(),
           "entidades": int(len(ent)), "entidades_sin_despachos": int((ent["contables_y_fiscales"] == 0).sum()),
           "denue": rep_denue,
           "linaje": {"puntos": lin_p, "entidades": lin_e, "denue": rep_denue.get("linaje")}}
    (do / "geo_reporte.json").write_text(json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return rep


if __name__ == "__main__":
    r = ejecutar()
    print(json.dumps({k: v for k, v in r.items() if k != "linaje"}, indent=2, ensure_ascii=False))
