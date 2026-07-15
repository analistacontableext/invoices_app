"""
Dashboard de importaciones: se conecta en vivo a la hoja "data" de Google Sheets
(la misma que alimenta pipeline.py) y arma los cortes que pidió gerencia, con un
estilo inspirado en el dashboard de Looker Studio que ya usan: KPIs arriba,
evolución mensual en área con etiquetas, rankings con "Otros" en gris y valores
al final de la barra, filtro de moneda, y una tabla de facturas al detalle.

Categoría y "tipo de pedido" quedaron fuera a propósito: no existen como columna
en el Sheet ni en el maestro de proveedores — se agregan cuando haya de dónde
sacarlas.
"""
from datetime import datetime
from pathlib import Path

import altair as alt
import pandas as pd
import squarify
import streamlit as st

import script

# Paleta de marca (Arumateme.thmx), validada en OKLCH: L en banda 0.43-0.77,
# croma >= 0.10. Verde y terracota se re-saturaron/oscurecieron un poco desde
# el swatch original del manual (que eran demasiado claros para usarse como
# marca de gráfico) manteniendo el mismo tono (H).
COLOR_PRIMARIO = "#FA0082"
COLOR_SECUNDARIO = "#C080F4"
PALETA_CATEGORICA = ["#FA0082", "#FF9A00", "#2F9E5C", "#C080F4", "#BC658E", "#B26234"]
COLOR_OTROS = "#B5B5B5"  # gris neutro, a propósito fuera de la paleta de marca:
# "Otros" es un cajón de sastre, no una categoría real — no debe competir visualmente.

_COLUMNAS_NUMERICAS = (
    "cantidad", "costo_unitario", "importe", "tc",
    "costo_unitario_pen", "importe_pen", "due_days",
)

_MONEDAS = ["PEN (todo convertido)", "USD", "EUR"]


@st.cache_data(ttl=300, show_spinner="Cargando datos desde Google Sheets...")
def cargar_datos(_marcador_refresh: int = 0) -> pd.DataFrame:
    """_marcador_refresh solo existe para poder invalidar el caché a demanda
    (cambiarlo desde afuera cuenta como un argumento nuevo para @cache_data)."""
    sheet = script.conectar_google_sheets()
    if sheet is None:
        return pd.DataFrame()

    registros = sheet.get_all_records()
    df = pd.DataFrame(registros)
    if df.empty:
        return df

    for col in _COLUMNAS_NUMERICAS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    if "periodo" in df.columns:
        df["periodo_dt"] = pd.to_datetime(df["periodo"].astype(str), format="%Y%m", errors="coerce")

    if "invoice_date" in df.columns:
        df["invoice_date_dt"] = pd.to_datetime(df["invoice_date"], errors="coerce")

    return df


def _columnas_por_moneda(moneda_sel: str):
    """Devuelve (columna_importe, columna_costo_unitario, etiqueta) según el
    filtro de moneda. PEN usa las columnas ya convertidas (importe_pen); USD/EUR
    usan las columnas originales, ya filtradas a esa sola moneda."""
    if moneda_sel == "PEN (todo convertido)":
        return "importe_pen", "costo_unitario_pen", "S/."
    return "importe", "costo_unitario", moneda_sel


def _formato_compacto(valor: float) -> str:
    signo = "-" if valor < 0 else ""
    valor = abs(valor)
    if valor >= 1_000_000:
        return f"{signo}{valor/1_000_000:.1f} M"
    if valor >= 1_000:
        return f"{signo}{valor/1_000:.1f} mil"
    return f"{signo}{valor:,.0f}"


def _chart_ranking(df: pd.DataFrame, columna: str, valor: str, titulo: str,
                    etiqueta_moneda: str, color: str = COLOR_PRIMARIO, top_n: int = 9):
    """Bar chart de una sola serie (magnitud por categoría): mismo color en
    todas las barras, 'Otros' en gris, valor al final de cada barra, sin
    leyenda (el título ya dice qué es)."""
    agrupado = df.groupby(columna, dropna=False)[valor].sum().sort_values(ascending=False)
    top = agrupado.head(top_n)
    resto = agrupado.iloc[top_n:].sum()
    if resto > 0:
        top = pd.concat([top, pd.Series({"Otros": resto})])

    data = top.reset_index()
    data.columns = [columna, valor]
    data["_es_otros"] = data[columna] == "Otros"
    data["_etiqueta"] = data[valor].apply(_formato_compacto)
    orden = list(data[columna])

    base = alt.Chart(data)
    barras = base.mark_bar(cornerRadiusEnd=4).encode(
        x=alt.X(f"{valor}:Q", title=f"Importe ({etiqueta_moneda})"),
        y=alt.Y(
            f"{columna}:N", sort=orden, title=None,
            axis=alt.Axis(labelLimit=160, labelFontSize=12, labelPadding=6),
            scale=alt.Scale(paddingInner=0.35, paddingOuter=0.15),
        ),
        color=alt.condition("datum._es_otros", alt.value(COLOR_OTROS), alt.value(color)),
        tooltip=[
            alt.Tooltip(f"{columna}:N", title=columna.capitalize()),
            alt.Tooltip(f"{valor}:Q", title=f"Importe ({etiqueta_moneda})", format=",.2f"),
        ],
    )
    etiquetas = base.mark_text(align="left", dx=5, fontSize=11, color="#555").encode(
        x=alt.X(f"{valor}:Q"),
        y=alt.Y(f"{columna}:N", sort=orden),
        text="_etiqueta:N",
    )
    return (barras + etiquetas).properties(title=titulo, height=max(160, 34 * len(data))).configure_view(strokeWidth=0)


def _chart_movers(data: pd.DataFrame, color: str, titulo: str, direccion: str):
    """Barras horizontales de variación de precio (%) — 'ganadores/perdedores'
    al estilo dashboards de bolsa. Eje Y = código de producto (no descripción,
    para que se lean completos y sean exactos — la descripción va en el
    tooltip). Un clic en una barra selecciona ese código: queda expuesto en el
    evento de selección que devuelve st.altair_chart(on_select="rerun"), para
    que quien llama pueda usarlo y actualizar otro gráfico."""
    data = data.copy()
    data["codigo_producto"] = data["codigo_producto"].astype(str).str.strip()
    data["_etiqueta"] = data["variacion_pct"].apply(lambda v: f"{v:+.0f}%")
    orden = list(data["codigo_producto"])
    dx = 5 if direccion == "positivo" else -5
    align = "left" if direccion == "positivo" else "right"

    seleccion = alt.selection_point(name=f"sel_{direccion}", fields=["codigo_producto"], empty=False)

    base = alt.Chart(data)
    barras = base.mark_bar(cornerRadius=4, color=color).encode(
        x=alt.X("variacion_pct:Q", title="Variación (%)"),
        y=alt.Y("codigo_producto:N", sort=orden, title=None,
                axis=alt.Axis(labelLimit=140, labelFontSize=11),
                scale=alt.Scale(paddingInner=0.35, paddingOuter=0.15)),
        opacity=alt.condition(seleccion, alt.value(1.0), alt.value(0.75)),
        tooltip=[
            alt.Tooltip("codigo_producto:N", title="Código"),
            alt.Tooltip("descripcion:N", title="Descripción"),
            alt.Tooltip("precio_inicial:Q", title="Precio inicial", format=",.2f"),
            alt.Tooltip("precio_final:Q", title="Precio final", format=",.2f"),
            alt.Tooltip("variacion_pct:Q", title="Variación (%)", format="+.1f"),
        ],
    ).add_params(seleccion)
    etiquetas = base.mark_text(align=align, dx=dx, fontSize=10, color="#555").encode(
        x="variacion_pct:Q", y=alt.Y("codigo_producto:N", sort=orden), text="_etiqueta:N",
    )
    return (barras + etiquetas).properties(title=titulo, height=max(140, 34 * len(data))).configure_view(strokeWidth=0)


def _top_con_otros(df: pd.DataFrame, columna: str, valor: str, top_n: int,
                    columna_extra: str | None = None) -> pd.DataFrame:
    """Agrupa por `columna`, suma `valor`, se queda con el top_n y junta el
    resto en una fila 'Otros' — la agregación previa que necesitan los
    treemaps (y cualquier otro chart con el mismo patrón top-N + Otros)."""
    agg = {valor: (valor, "sum")}
    if columna_extra:
        agg[columna_extra] = (
            columna_extra,
            lambda s: s.mode().iat[0] if not s.mode().empty else (s.iloc[0] if len(s) else ""),
        )
    agrupado = df.groupby(columna, dropna=False).agg(**agg).reset_index()
    agrupado = agrupado.sort_values(valor, ascending=False)
    top = agrupado.head(top_n).copy()
    resto = agrupado[valor].iloc[top_n:].sum()
    if resto > 0:
        fila_otros = {columna: "Otros", valor: resto}
        if columna_extra:
            fila_otros[columna_extra] = ""
        top = pd.concat([top, pd.DataFrame([fila_otros])], ignore_index=True)
    top["_es_otros"] = top[columna] == "Otros"
    return top


def _chart_treemap(datos: pd.DataFrame, columna: str, valor: str, titulo: str,
                    etiqueta_moneda: str, columna_extra: str | None = None,
                    titulo_extra: str | None = None, titulo_columna: str | None = None):
    """Treemap: área proporcional al importe. A diferencia de un bar chart,
    con cientos de categorías (ej. PO de varios años) no hace falta rankear
    ni distorsiona la escala — 'Otros' es solo un rectángulo más, no una
    barra que tapa todo lo demás. `datos` ya debe venir agregado (una fila
    por categoría, ver `_top_con_otros`)."""
    datos = datos.copy()
    datos[columna] = datos[columna].astype(str)

    ancho, alto = 640.0, 380.0
    normalizados = squarify.normalize_sizes(datos[valor].values.astype(float), ancho, alto)
    rects = squarify.squarify(normalizados, 0, 0, ancho, alto)
    datos["x0"] = [r["x"] for r in rects]
    datos["x1"] = [r["x"] + r["dx"] for r in rects]
    datos["y0"] = [r["y"] for r in rects]
    datos["y1"] = [r["y"] + r["dy"] for r in rects]
    datos["_cx"] = (datos["x0"] + datos["x1"]) / 2
    datos["_cy"] = (datos["y0"] + datos["y1"]) / 2
    # Umbral por ancho/alto de celda (no por área): una franja muy angosta
    # pero larga tiene área "suficiente" y aun así el texto no entra.
    ancho_celda = datos["x1"] - datos["x0"]
    alto_celda = datos["y1"] - datos["y0"]
    datos["_mostrar_texto"] = (ancho_celda >= 55) & (alto_celda >= 18)
    if "_es_otros" not in datos.columns:
        datos["_es_otros"] = datos[columna] == "Otros"

    tooltip = [alt.Tooltip(f"{columna}:N", title=titulo_columna or columna.capitalize())]
    if columna_extra and columna_extra in datos.columns:
        tooltip.append(alt.Tooltip(f"{columna_extra}:N", title=titulo_extra or columna_extra.capitalize()))
    tooltip.append(alt.Tooltip(f"{valor}:Q", title=f"Importe ({etiqueta_moneda})", format=",.2f"))

    base = alt.Chart(datos)
    rects_chart = base.mark_rect(stroke="white", strokeWidth=2, cornerRadius=3).encode(
        x=alt.X("x0:Q", axis=None), x2="x1:Q",
        y=alt.Y("y0:Q", axis=None), y2="y1:Q",
        color=alt.condition("datum._es_otros", alt.value(COLOR_OTROS), alt.value(COLOR_PRIMARIO)),
        tooltip=tooltip,
    )
    # Mismo tooltip explícito en el texto: si no se define, Streamlit arma uno
    # solo con los campos internos (_cx, _cy) al pasar por encima del label.
    etiquetas_chart = base.transform_filter("datum._mostrar_texto").mark_text(
        fontSize=11, color="white", fontWeight="bold"
    ).encode(x="_cx:Q", y=alt.Y("_cy:Q", axis=None), text=f"{columna}:N", tooltip=tooltip)

    return (rects_chart + etiquetas_chart).properties(
        title=titulo, width=ancho, height=alto
    ).configure_view(strokeWidth=0)


def _chart_evolucion_total(df: pd.DataFrame, valor: str, etiqueta_moneda: str):
    """Area chart de una sola serie (total por mes), con etiqueta de valor en
    cada punto — así se ve el dashboard de referencia en Looker."""
    agrupado = df.groupby("periodo_dt", dropna=False)[valor].sum().reset_index()
    agrupado["_etiqueta"] = agrupado[valor].apply(_formato_compacto)

    area = alt.Chart(agrupado).mark_area(
        line={"color": COLOR_SECUNDARIO, "strokeWidth": 2},
        color=alt.Gradient(
            gradient="linear",
            stops=[
                alt.GradientStop(color=COLOR_SECUNDARIO, offset=0),
                alt.GradientStop(color="#FFFFFF", offset=1),
            ],
            x1=1, x2=1, y1=1, y2=0,
        ),
        opacity=0.5,
    ).encode(
        x=alt.X("periodo_dt:T", title="Mes", axis=alt.Axis(format="%b-%y", labelAngle=-45)),
        y=alt.Y(f"{valor}:Q", title=f"Importe ({etiqueta_moneda})"),
    )
    puntos = alt.Chart(agrupado).mark_point(color=COLOR_SECUNDARIO, filled=True, size=40).encode(
        x="periodo_dt:T",
        y=f"{valor}:Q",
        tooltip=[
            alt.Tooltip("periodo_dt:T", title="Mes", format="%Y-%m"),
            alt.Tooltip(f"{valor}:Q", title=f"Importe ({etiqueta_moneda})", format=",.2f"),
        ],
    )
    etiquetas = alt.Chart(agrupado).mark_text(dy=-10, fontSize=10, color="#555").encode(
        x="periodo_dt:T", y=f"{valor}:Q", text="_etiqueta:N",
    )
    return (area + puntos + etiquetas).properties(
        title=f"Evolución mensual de importaciones ({etiqueta_moneda})", height=320
    ).configure_view(strokeWidth=0)


def _chart_evolucion_por(df: pd.DataFrame, columna: str, valor: str, etiqueta_moneda: str, top_n: int = 6):
    """Line chart multi-serie (importe por mes, una línea por categoría), con
    las categorías más chicas agrupadas en 'Otros'."""
    top_categorias = (
        df.groupby(columna, dropna=False)[valor].sum().sort_values(ascending=False).head(top_n - 1).index
    )
    tmp = df.copy()
    tmp[columna] = tmp[columna].where(tmp[columna].isin(top_categorias), "Otros")
    agrupado = tmp.groupby(["periodo_dt", columna], dropna=False)[valor].sum().reset_index()
    orden = list(top_categorias) + (["Otros"] if "Otros" in agrupado[columna].unique() else [])
    rango = PALETA_CATEGORICA[: len(top_categorias)] + ([COLOR_OTROS] if "Otros" in orden else [])

    return (
        alt.Chart(agrupado, title=f"Evolución mensual ({etiqueta_moneda}) por {columna}")
        .mark_line(point=True, strokeWidth=2)
        .encode(
            x=alt.X("periodo_dt:T", title="Mes", axis=alt.Axis(format="%b-%y", labelAngle=-45)),
            y=alt.Y(f"{valor}:Q", title=f"Importe ({etiqueta_moneda})"),
            color=alt.Color(
                f"{columna}:N", title=columna.capitalize(), sort=orden,
                scale=alt.Scale(domain=orden, range=rango),
                legend=alt.Legend(orient="bottom", direction="horizontal", columns=3, labelLimit=140),
            ),
            tooltip=[
                alt.Tooltip("periodo_dt:T", title="Mes", format="%Y-%m"),
                alt.Tooltip(f"{columna}:N", title=columna.capitalize()),
                alt.Tooltip(f"{valor}:Q", title=f"Importe ({etiqueta_moneda})", format=",.2f"),
            ],
        )
        .properties(height=340)
        .configure_view(strokeWidth=0)
    )


def _tabla_facturas(df: pd.DataFrame, col_importe: str, etiqueta_moneda: str) -> pd.DataFrame:
    """Una fila por factura (no por línea): suma importes, promedia el tipo de
    cambio y marca si alguna línea es muestra — el mismo nivel de detalle que
    la tabla de facturas del dashboard de Looker."""
    cols_group = [c for c in ("po", "invoice", "proveedor", "marca", "invoice_date",
                               "due_date", "moneda", "incoterm") if c in df.columns]
    agg = {col_importe: "sum"}
    if "tc" in df.columns:
        agg["tc"] = "mean"
    if "sample" in df.columns:
        agg["sample"] = lambda s: "Sí" if (s.astype(str).str.upper() == "Y").any() else "No"

    tabla = df.groupby(cols_group, dropna=False).agg(agg).reset_index()
    tabla = tabla.rename(columns={
        col_importe: f"Importe ({etiqueta_moneda})",
        "tc": "TC prom.",
        "sample": "Muestra",
        "po": "PO", "invoice": "Factura", "proveedor": "Proveedor", "marca": "Marca",
        "invoice_date": "Fecha emisión", "due_date": "Fecha vcto.", "moneda": "Moneda",
        "incoterm": "Incoterm",
    })
    return tabla.sort_values(f"Importe ({etiqueta_moneda})", ascending=False)


_SIMBOLO_MONEDA = {"USD": "$", "EUR": "€", "PEN": "S/"}


def _resumen_general(df: pd.DataFrame):
    """Panel tipo 'pivot table' — total en soles, desglose por moneda y por
    muestra (sample), y métricas clave. Siempre se calcula con todas las
    monedas juntas (independiente del filtro de moneda de la pantalla), para
    que el desglose por moneda tenga sentido."""
    if df.empty or "importe_pen" not in df.columns:
        return

    total_pen = df["importe_pen"].sum()

    st.markdown("#### 🧾 Resumen general")
    with st.container(border=True):
        st.metric("Total PEN", f"S/ {total_pen:,.2f}")

        st.markdown("**Por moneda**")
        por_moneda = df.groupby("moneda", dropna=False).agg(
            pen=("importe_pen", "sum"), nativo=("importe", "sum")
        )
        for moneda, fila in por_moneda.sort_values("pen", ascending=False).iterrows():
            simbolo = _SIMBOLO_MONEDA.get(str(moneda).upper(), "")
            pct = (fila["pen"] / total_pen * 100) if total_pen else 0
            st.caption(
                f"{moneda}: {simbolo} {fila['nativo']:,.2f}  ·  S/ {fila['pen']:,.2f}  ({pct:.0f}%)"
            )

        if "sample" in df.columns and "invoice" in df.columns:
            st.markdown("**Muestras (sample)**")
            tmp = df.copy()
            tmp["_es_muestra"] = tmp["sample"].astype(str).str.strip().str.upper() == "Y"
            por_muestra = tmp.groupby("_es_muestra").agg(
                pen=("importe_pen", "sum"), facturas=("invoice", "nunique")
            )
            for es_muestra, etiqueta in ((True, "Sí"), (False, "No")):
                if es_muestra not in por_muestra.index:
                    continue
                fila = por_muestra.loc[es_muestra]
                pct = (fila["pen"] / total_pen * 100) if total_pen else 0
                st.caption(
                    f"{etiqueta}: S/ {fila['pen']:,.2f} ({pct:.0f}%)  ·  Facturas: {int(fila['facturas'])}"
                )

        st.markdown("**Métricas clave**")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Importaciones", df["po"].nunique() if "po" in df.columns else "—")
        c2.metric("Proveedores", df["proveedor"].nunique() if "proveedor" in df.columns else "—")
        c3.metric("EANs", df["codigo_producto"].nunique() if "codigo_producto" in df.columns else "—")
        c4.metric("Facturas", df["invoice"].nunique() if "invoice" in df.columns else "—")


def _tabla_pdf(data):
    from reportlab.lib import colors
    from reportlab.platypus import Table, TableStyle

    tabla = Table(data, hAlign="LEFT")
    tabla.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLOR_PRIMARIO)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FFE1E6")]),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#DDDDDD")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))
    return tabla


def generar_reporte_pdf(df: pd.DataFrame, descripcion_filtros: str) -> bytes:
    """
    Reporte ejecutivo en PDF: resumen narrativo (según los filtros aplicados),
    desglose por año, por moneda, por muestra, y top 5 proveedores/marcas.
    df debe venir SIN filtrar por moneda (necesita todas las monedas juntas
    para el desglose por moneda) pero SÍ con los demás filtros ya aplicados.
    """
    from io import BytesIO

    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Image

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
    )
    styles = getSampleStyleSheet()
    titulo_style = ParagraphStyle("TituloAruma", parent=styles["Title"], textColor=colors.HexColor(COLOR_PRIMARIO), fontSize=18)
    subtitulo_style = ParagraphStyle("Subtitulo", parent=styles["Normal"], textColor=colors.grey, fontSize=9)
    seccion_style = ParagraphStyle("Seccion", parent=styles["Heading2"], textColor=colors.HexColor(COLOR_PRIMARIO), fontSize=12, spaceBefore=14, spaceAfter=6)
    cuerpo_style = ParagraphStyle("Cuerpo", parent=styles["Normal"], fontSize=10, leading=14)

    elementos = []

    logo_path = Path(__file__).resolve().parent / "assets" / "logo_aruma.png"
    if logo_path.exists():
        elementos.append(Image(str(logo_path), width=3.2 * cm, height=1.6 * cm))
        elementos.append(Spacer(1, 0.3 * cm))

    elementos.append(Paragraph("Reporte ejecutivo de importaciones", titulo_style))
    elementos.append(Paragraph(f"Generado el {datetime.now().strftime('%d/%m/%Y %H:%M')}", subtitulo_style))
    elementos.append(Paragraph(f"Filtros aplicados: {descripcion_filtros}", subtitulo_style))
    elementos.append(Spacer(1, 0.5 * cm))

    if df.empty or "importe_pen" not in df.columns:
        elementos.append(Paragraph("No hay datos para los filtros seleccionados.", cuerpo_style))
        doc.build(elementos)
        buffer.seek(0)
        return buffer.getvalue()

    total_pen = df["importe_pen"].sum()
    n_facturas = df["invoice"].nunique() if "invoice" in df.columns else 0
    n_proveedores = df["proveedor"].nunique() if "proveedor" in df.columns else 0
    años = sorted(df["periodo_dt"].dt.year.dropna().unique().astype(int)) if "periodo_dt" in df.columns else []

    if len(años) > 1:
        rango_años = f"los años {años[0]} al {años[-1]}"
    elif años:
        rango_años = f"el año {años[0]}"
    else:
        rango_años = "el periodo seleccionado"

    resumen_txt = (
        f"Entre {rango_años}, las importaciones registradas totalizan "
        f"<b>S/ {total_pen:,.2f}</b>, distribuidas en <b>{n_facturas}</b> facturas "
        f"de <b>{n_proveedores}</b> proveedores."
    )
    elementos.append(Paragraph(resumen_txt, cuerpo_style))

    if len(años) > 1 and "periodo_dt" in df.columns:
        elementos.append(Paragraph("Desglose por año", seccion_style))
        por_año = df.groupby(df["periodo_dt"].dt.year).agg(
            pen=("importe_pen", "sum"), facturas=("invoice", "nunique")
        )
        data = [["Año", "Total (S/.)", "% del total", "Facturas"]]
        for año, fila in por_año.sort_index().iterrows():
            pct = (fila["pen"] / total_pen * 100) if total_pen else 0
            data.append([str(int(año)), f"{fila['pen']:,.2f}", f"{pct:.0f}%", str(int(fila["facturas"]))])
        elementos.append(_tabla_pdf(data))

    if "moneda" in df.columns:
        elementos.append(Paragraph("Desglose por moneda", seccion_style))
        por_moneda = df.groupby("moneda", dropna=False).agg(pen=("importe_pen", "sum"), nativo=("importe", "sum"))
        data = [["Moneda", "Monto nativo", "Equivalente S/.", "% del total"]]
        for moneda, fila in por_moneda.sort_values("pen", ascending=False).iterrows():
            pct = (fila["pen"] / total_pen * 100) if total_pen else 0
            simbolo = _SIMBOLO_MONEDA.get(str(moneda).upper(), "")
            data.append([str(moneda), f"{simbolo} {fila['nativo']:,.2f}", f"S/ {fila['pen']:,.2f}", f"{pct:.0f}%"])
        elementos.append(_tabla_pdf(data))

    if "sample" in df.columns and "invoice" in df.columns:
        elementos.append(Paragraph("Muestras (sample)", seccion_style))
        tmp = df.copy()
        tmp["_es_muestra"] = tmp["sample"].astype(str).str.strip().str.upper() == "Y"
        por_muestra = tmp.groupby("_es_muestra").agg(pen=("importe_pen", "sum"), facturas=("invoice", "nunique"))
        data = [["¿Es muestra?", "Total S/.", "% del total", "Facturas"]]
        for es_muestra, etiqueta in ((True, "Sí"), (False, "No")):
            if es_muestra not in por_muestra.index:
                continue
            fila = por_muestra.loc[es_muestra]
            pct = (fila["pen"] / total_pen * 100) if total_pen else 0
            data.append([etiqueta, f"{fila['pen']:,.2f}", f"{pct:.0f}%", str(int(fila["facturas"]))])
        elementos.append(_tabla_pdf(data))

    if "proveedor" in df.columns:
        elementos.append(Paragraph("Top 5 proveedores", seccion_style))
        top_prov = df.groupby("proveedor")["importe_pen"].sum().sort_values(ascending=False).head(5)
        data = [["Proveedor", "Total S/."]] + [[p, f"{v:,.2f}"] for p, v in top_prov.items()]
        elementos.append(_tabla_pdf(data))

    if "marca" in df.columns:
        elementos.append(Paragraph("Top 5 marcas", seccion_style))
        top_marca = df.groupby("marca")["importe_pen"].sum().sort_values(ascending=False).head(5)
        data = [["Marca", "Total S/."]] + [[m, f"{v:,.2f}"] for m, v in top_marca.items()]
        elementos.append(_tabla_pdf(data))

    doc.build(elementos)
    buffer.seek(0)
    return buffer.getvalue()


def render():
    col_refresh, col_info = st.columns([1, 4])
    with col_refresh:
        if st.button("🔄 Actualizar datos"):
            st.session_state["dash_refresh"] = st.session_state.get("dash_refresh", 0) + 1
            st.cache_data.clear()

    df = cargar_datos(st.session_state.get("dash_refresh", 0))

    with col_info:
        st.caption(f"Última carga: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} · "
                    f"los datos se refrescan solos cada 5 minutos, o al apretar el botón.")

    if df.empty:
        st.info("No hay datos en el Sheet todavía (o no se pudo conectar).")
        return

    col_f1, col_f2, col_f3, col_f4 = st.columns(4)
    with col_f1:
        años_disponibles = sorted(df["periodo_dt"].dt.year.dropna().unique().astype(int), reverse=True)
        años_sel = st.multiselect("Año", options=años_disponibles, default=años_disponibles)
    with col_f2:
        proveedores_sel = st.multiselect("Proveedor", options=sorted(df["proveedor"].dropna().unique()))
    with col_f3:
        marcas_sel = st.multiselect("Marca", options=sorted(df["marca"].dropna().unique()))
    with col_f4:
        moneda_sel = st.selectbox("Moneda", options=_MONEDAS)

    df_filtrado = df[df["periodo_dt"].dt.year.isin(años_sel)] if años_sel else df
    if proveedores_sel:
        df_filtrado = df_filtrado[df_filtrado["proveedor"].isin(proveedores_sel)]
    if marcas_sel:
        df_filtrado = df_filtrado[df_filtrado["marca"].isin(marcas_sel)]

    # Antes de que el filtro de moneda reduzca a una sola divisa: el resumen
    # general necesita ver todas las monedas juntas para el desglose por moneda.
    df_para_resumen = df_filtrado.copy()

    col_importe, col_costo_unit, etiqueta_moneda = _columnas_por_moneda(moneda_sel)
    if moneda_sel != "PEN (todo convertido)":
        df_filtrado = df_filtrado[df_filtrado["moneda"] == moneda_sel]

    if df_filtrado.empty:
        st.warning("No hay datos para los filtros seleccionados.")
        return

    _resumen_general(df_para_resumen)

    descripcion_filtros = (
        f"Años: {', '.join(str(a) for a in años_sel) if años_sel else 'todos'} · "
        f"Proveedores: {', '.join(proveedores_sel) if proveedores_sel else 'todos'} · "
        f"Marcas: {', '.join(marcas_sel) if marcas_sel else 'todas'} · "
        f"Moneda: {moneda_sel}"
    )
    st.download_button(
        "📄 Descargar reporte ejecutivo (PDF)",
        data=generar_reporte_pdf(df_para_resumen, descripcion_filtros),
        file_name=f"reporte_importaciones_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf",
        mime="application/pdf",
    )

    st.divider()

    total = df_filtrado[col_importe].sum()
    n_facturas = df_filtrado["invoice"].nunique() if "invoice" in df_filtrado.columns else None
    n_proveedores = df_filtrado["proveedor"].nunique() if "proveedor" in df_filtrado.columns else None
    n_marcas = df_filtrado["marca"].nunique() if "marca" in df_filtrado.columns else None

    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric(f"Total importado ({etiqueta_moneda})", f"{total:,.2f}")
    kpi2.metric("Total facturas", n_facturas if n_facturas is not None else "—")
    kpi3.metric("Total proveedores", n_proveedores if n_proveedores is not None else "—")
    kpi4.metric("Total marcas", n_marcas if n_marcas is not None else "—")

    st.divider()
    st.altair_chart(_chart_evolucion_total(df_filtrado, col_importe, etiqueta_moneda), use_container_width=True)

    st.divider()
    col_prov, col_marca = st.columns(2)
    with col_prov:
        st.altair_chart(
            _chart_ranking(df_filtrado, "proveedor", col_importe, "Top proveedores por importe",
                            etiqueta_moneda, color=COLOR_SECUNDARIO),
            use_container_width=True,
        )
    with col_marca:
        st.altair_chart(
            _chart_ranking(df_filtrado, "marca", col_importe, "Top marcas por importe", etiqueta_moneda),
            use_container_width=True,
        )

    st.divider()
    st.subheader("Total valorizado por…")
    dimension = st.radio(
        "Ver por", ["PO (IMP)", "Producto"], horizontal=True, label_visibility="collapsed"
    )
    if dimension == "PO (IMP)":
        datos_dim = _top_con_otros(df_filtrado, "po", col_importe, top_n=30)
        chart_dim = _chart_treemap(
            datos_dim, "po", col_importe, "Total valorizado por PO", etiqueta_moneda, titulo_columna="PO",
        )
    else:
        tmp = df_filtrado.copy()
        tmp["codigo_producto"] = (
            tmp["codigo_producto"].fillna("").astype(str).str.strip().replace("", "Sin código")
        )
        datos_dim = _top_con_otros(tmp, "codigo_producto", col_importe, top_n=30, columna_extra="descripcion")
        chart_dim = _chart_treemap(
            datos_dim, "codigo_producto", col_importe, "Total valorizado por código de producto",
            etiqueta_moneda, columna_extra="descripcion", titulo_extra="Descripción", titulo_columna="Código",
        )
    st.altair_chart(chart_dim, use_container_width=True)

    st.divider()
    st.subheader("Evolución mensual desglosada")
    dim_evolucion = st.radio(
        "Desglosar por", ["Marca", "Producto"], horizontal=True, key="dim_evolucion",
        label_visibility="collapsed",
    )
    columna_evolucion = {"Marca": "marca", "Producto": "descripcion"}[dim_evolucion]
    st.altair_chart(
        _chart_evolucion_por(df_filtrado, columna_evolucion, col_importe, etiqueta_moneda),
        use_container_width=True,
    )

    st.divider()
    st.subheader("Top marcas del mes")
    meses_disponibles = sorted(df_filtrado["periodo_dt"].dropna().unique(), reverse=True)
    if meses_disponibles:
        mes_sel = st.selectbox(
            "Mes", options=meses_disponibles, format_func=lambda d: pd.Timestamp(d).strftime("%Y-%m")
        )
        df_mes = df_filtrado[df_filtrado["periodo_dt"] == mes_sel]
        st.altair_chart(
            _chart_ranking(df_mes, "marca", col_importe, f"Top marcas — {pd.Timestamp(mes_sel).strftime('%Y-%m')}",
                            etiqueta_moneda, top_n=5),
            use_container_width=True,
        )

    st.divider()
    st.subheader("Histórico de precio por producto")
    st.caption("Eje de fechas: **invoice_date** (fecha real de cada factura, no el mes de 'periodo').")
    # Solo productos con código real: sin código no hay forma confiable de
    # identificar "el mismo producto" por descripción sola (varía de una
    # factura a otra). Los que no tienen código quedan pendientes de una
    # siguiente etapa de homologación. Las muestras (precio 0) se excluyen del
    # cálculo — igual que 'flg_cost_unit_var' en el Sheet, que mide variación
    # de precio unitario obviando muestras.
    df_con_codigo = df_filtrado[
        df_filtrado["codigo_producto"].notna()
        & (df_filtrado["codigo_producto"].astype(str).str.strip() != "")
        & df_filtrado["invoice_date_dt"].notna()
    ].copy()
    # Códigos como EANs numéricos ("8806358594473") pueden venir en el
    # DataFrame como int/float mientras que otros ("885190-11015-5") son
    # texto — deja la columna entera como string homogéneo. Sin esto, Altair
    # arma un selection_point con valores de tipo mixto por fila y falla con
    # SchemaValidationError al usar on_select en _chart_movers.
    df_con_codigo["codigo_producto"] = df_con_codigo["codigo_producto"].astype(str).str.strip()
    es_muestra = df_con_codigo["sample"].astype(str).str.strip().str.upper() == "Y"
    df_sin_muestras = df_con_codigo[~es_muestra]

    if df_sin_muestras.empty:
        st.caption("No hay productos con código registrado (sin contar muestras) en el rango filtrado.")
    else:
        # precio_inicial/final = primera y última FACTURA por fecha real
        # (invoice_date), no por mes — dos facturas del mismo mes en días
        # distintos ahora quedan en el orden cronológico correcto.
        df_ordenado = df_sin_muestras.sort_values("invoice_date_dt")
        extremos = (
            df_ordenado.groupby("codigo_producto")
            .agg(
                descripcion=("descripcion", lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0]),
                precio_inicial=(col_costo_unit, "first"),
                precio_final=(col_costo_unit, "last"),
                facturas=("invoice_date_dt", "nunique"),
            )
            .reset_index()
        )
        extremos = extremos[extremos["facturas"] >= 2]
        extremos["variacion_pct"] = extremos.apply(
            lambda r: ((r["precio_final"] - r["precio_inicial"]) / r["precio_inicial"] * 100)
            if r["precio_inicial"] else 0,
            axis=1,
        )
        top_n = 8
        aumentos = extremos[extremos["variacion_pct"] > 0].sort_values("variacion_pct", ascending=False).head(top_n)
        caidas = extremos[extremos["variacion_pct"] < 0].sort_values("variacion_pct", ascending=True).head(top_n)

        # Si en el run anterior se hizo clic en una barra de abajo, ese código
        # ya quedó guardado en session_state (por la key del chart) — se lee
        # ACÁ, antes de dibujar el selectbox, para que el clic mande sobre el
        # dropdown y el gráfico de arriba se actualice con lo que se clickeó.
        # La selección de un gráfico Vega-Lite es "pegajosa": sigue apareciendo
        # en session_state en los runs siguientes aunque el clic haya sido hace
        # rato. Por eso no basta con "el último de los dos que tenga algo": hay
        # que comparar contra lo que ya se procesó antes y quedarse solo con el
        # que realmente CAMBIÓ en este run — si no, un clic viejo en "caídas"
        # le puede ganar para siempre a un clic nuevo en "aumentos" (o viceversa).
        codigo_click = None
        for key_chart, nombre_sel in (("mov_aumentos", "sel_positivo"), ("mov_caidas", "sel_negativo")):
            evento = st.session_state.get(key_chart)
            codigo_actual = None
            if evento is not None:
                puntos = evento.get("selection", {}).get(nombre_sel, [])
                if puntos:
                    codigo_actual = puntos[0].get("codigo_producto")
            clave_prev = f"_prev_click_{key_chart}"
            if codigo_actual is not None and codigo_actual != st.session_state.get(clave_prev):
                codigo_click = codigo_actual
            st.session_state[clave_prev] = codigo_actual

        opciones = (
            df_sin_muestras.groupby("codigo_producto")["descripcion"]
            .agg(lambda s: s.mode().iat[0] if not s.mode().empty else s.iloc[0])
            .reset_index()
        )
        opciones["etiqueta"] = opciones["codigo_producto"].astype(str) + " - " + opciones["descripcion"].astype(str)
        opciones = opciones.sort_values("etiqueta")

        if codigo_click is not None and codigo_click in opciones["codigo_producto"].values:
            st.session_state["hist_precio_producto"] = opciones.loc[
                opciones["codigo_producto"] == codigo_click, "etiqueta"
            ].iloc[0]

        etiqueta_sel = st.selectbox(
            "Producto (código - descripción, busca por cualquiera de los dos; "
            "o haz clic en una barra de 'Mayores movimientos' más abajo)",
            options=opciones["etiqueta"],
            key="hist_precio_producto",
        )
        codigo_sel = opciones.loc[opciones["etiqueta"] == etiqueta_sel, "codigo_producto"].iloc[0]

        df_producto = (
            df_sin_muestras[df_sin_muestras["codigo_producto"] == codigo_sel]
            .groupby("invoice_date_dt", dropna=False)[col_costo_unit]
            .mean()
            .reset_index()
        )

        if len(df_producto) < 2:
            st.caption("Este producto solo tiene una factura (sin contar muestras) en el rango filtrado — no hay variación que graficar todavía.")
        else:
            varia = df_producto[col_costo_unit].round(4).nunique() > 1
            st.caption(f"¿Varió el precio unitario en el rango filtrado (sin contar muestras)? **{'Sí' if varia else 'No'}**")

        chart_precio = (
            alt.Chart(df_producto, title=f"Costo unitario ({etiqueta_moneda}) por factura — {etiqueta_sel}")
            .mark_line(point=True, strokeWidth=2, color=COLOR_PRIMARIO)
            .encode(
                x=alt.X("invoice_date_dt:T", title="Fecha de factura (invoice_date)",
                        axis=alt.Axis(format="%d-%b-%y", labelAngle=-45)),
                y=alt.Y(f"{col_costo_unit}:Q", title=f"Costo unitario ({etiqueta_moneda})"),
                tooltip=[
                    alt.Tooltip("invoice_date_dt:T", title="Fecha de factura", format="%d/%m/%Y"),
                    alt.Tooltip(f"{col_costo_unit}:Q", title=f"Costo unitario ({etiqueta_moneda})", format=",.2f"),
                ],
            )
            .properties(height=300)
            .configure_view(strokeWidth=0)
        )
        st.altair_chart(chart_precio, use_container_width=True)

        st.markdown("**Mayores movimientos de precio (sin muestras)** — haz clic en una barra para verla arriba")
        if extremos.empty:
            st.caption("Ningún producto tiene al menos 2 facturas (sin contar muestras) para comparar inicio vs. fin.")
        else:
            col_sube, col_baja = st.columns(2)
            with col_sube:
                if aumentos.empty:
                    st.caption("Ningún producto subió de precio en el rango filtrado.")
                else:
                    st.altair_chart(
                        _chart_movers(aumentos, color="#2F9E5C", titulo="Mayor aumento de precio", direccion="positivo"),
                        use_container_width=True,
                        on_select="rerun",
                        key="mov_aumentos",
                    )
            with col_baja:
                if caidas.empty:
                    st.caption("Ningún producto bajó de precio en el rango filtrado.")
                else:
                    st.altair_chart(
                        _chart_movers(caidas, color="#D64545", titulo="Mayor caída de precio", direccion="negativo"),
                        use_container_width=True,
                        on_select="rerun",
                        key="mov_caidas",
                    )

    st.divider()
    st.subheader("Por Incoterm")
    if "incoterm" in df_filtrado.columns:
        st.altair_chart(
            _chart_ranking(df_filtrado, "incoterm", col_importe, "Total valorizado por incoterm",
                            etiqueta_moneda, top_n=8),
            use_container_width=True,
        )

    st.divider()
    st.subheader("Facturas")
    tabla = _tabla_facturas(df_filtrado, col_importe, etiqueta_moneda)
    st.dataframe(
        tabla,
        use_container_width=True,
        hide_index=True,
        height=420,
        column_config={
            f"Importe ({etiqueta_moneda})": st.column_config.NumberColumn(format="%.2f"),
            "TC prom.": st.column_config.NumberColumn(format="%.3f"),
        },
    )
