"""
Revisor de facturas — v1 local.

Sube una factura, elige marca y PO, revisa/corrige los datos extraídos junto
a una vista previa del documento, y confirma la subida a Google Sheets.

Ejecutar con:
    streamlit run app/streamlit_app.py
(desde la carpeta scripts/google_cloud)
"""
import sys
from pathlib import Path

# script.py imprime emojis (⚠, 📦, 💰...) en muchos print() de diagnóstico.
# En la consola de Windows (cp1252) eso revienta con UnicodeEncodeError apenas
# alguna marca pasa por generar_nombre()/procesar() — se ve como "no se pudo
# procesar la factura" en la app sin ninguna pista de la causa real. Forzar
# UTF-8 en stdout/stderr acá, antes de importar nada más, lo evita para
# siempre sin tener que tocar cada print() de script.py.
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

_GOOGLE_CLOUD_DIR = Path(__file__).resolve().parent.parent
_APP_DIR = Path(__file__).resolve().parent
for _p in (_GOOGLE_CLOUD_DIR, _APP_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import base64
import hashlib
from datetime import datetime

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import auth
import bootstrap
import dashboard
import diagnostico
import pipeline
import script
import storage

# Primera línea "de verdad" del arranque: en modo nube materializa las
# credenciales de la cuenta de servicio (Sheets) desde st.secrets; en local
# no hace nada (script.py ya usa credenciales.json tal cual). Debe correr
# antes de cualquier llamada a Sheets/Drive en el proceso.
bootstrap.bootstrap_sheets_credentials()

_LOGO_PATH = _APP_DIR / "assets" / "logo_aruma.png"

st.set_page_config(page_title="Revisor de facturas — Aruma", page_icon="💄", layout="wide")

st.markdown(
    """
    <style>
    html, body, [class*="css"] { font-family: Calibri, 'Segoe UI', Tahoma, sans-serif; }
    </style>
    """,
    unsafe_allow_html=True,
)

st.session_state.setdefault("resultado", None)
st.session_state.setdefault("df_editado", None)
st.session_state.setdefault("historial", [])
st.session_state.setdefault("uploader_key", 0)
st.session_state.setdefault("sunat_uploader_key", 0)


def _limpiar_checkboxes_exclusion():
    """Los checkboxes 'excluir_<i>' quedan en session_state por su key; si no
    se limpian, un lote nuevo podría arrancar con archivos ya marcados para
    excluir solo porque comparten el mismo índice que el lote anterior."""
    for k in [k for k in st.session_state if k.startswith("excluir_")]:
        del st.session_state[k]


def _reset_formulario():
    if st.session_state["resultado"] is not None:
        pipeline.descartar(st.session_state["resultado"])
    st.session_state["resultado"] = None
    st.session_state["df_editado"] = None
    st.session_state["uploader_key"] += 1
    _limpiar_checkboxes_exclusion()


def _mostrar_preview_pdf(fuente, dom_id: str, height: int = 500):
    """Renderiza las páginas del PDF como imágenes y permite hacer zoom con
    Ctrl + rueda del mouse (scroll normal sigue desplazando la vista).
    fuente puede ser una ruta en disco o los bytes crudos del PDF.
    dom_id debe ser único por archivo cuando se muestran varios PDFs a la vez."""
    import fitz  # PyMuPDF

    if isinstance(fuente, (bytes, bytearray)):
        doc = fitz.open(stream=fuente, filetype="pdf")
    else:
        doc = fitz.open(fuente)
    imgs_html = []
    for page in doc:
        pix = page.get_pixmap(dpi=150)
        b64 = base64.b64encode(pix.tobytes("png")).decode("utf-8")
        imgs_html.append(
            f'<img src="data:image/png;base64,{b64}" style="width:100%;display:block;margin-bottom:8px;">'
        )
    doc.close()

    wrap_id = f"pdf-zoom-wrap-{dom_id}"
    inner_id = f"pdf-zoom-inner-{dom_id}"
    html = f"""
    <div id="{wrap_id}" style="overflow:auto; height:{height}px; border:1px solid rgba(128,128,128,0.3); border-radius:4px;">
      <div id="{inner_id}" style="transform-origin: 0 0;">
        {''.join(imgs_html)}
      </div>
    </div>
    <div style="font-size:12px; opacity:0.6; margin-top:4px;">Ctrl + rueda del mouse para hacer zoom</div>
    <script>
      (function() {{
        const wrap = document.getElementById('{wrap_id}');
        const inner = document.getElementById('{inner_id}');
        let scale = 1;
        wrap.addEventListener('wheel', function(e) {{
          if (e.ctrlKey) {{
            e.preventDefault();
            scale += (e.deltaY < 0 ? 0.1 : -0.1);
            scale = Math.min(Math.max(scale, 0.3), 4);
            inner.style.transform = 'scale(' + scale + ')';
          }}
        }}, {{ passive: false }});
      }})();
    </script>
    """
    components.html(html, height=height + 30, scrolling=True)


def _mostrar_preview_excel(staged_path: Path):
    df_excel = pd.read_excel(staged_path, header=None)
    st.dataframe(df_excel, use_container_width=True, height=500)


def _resumen_por_factura(df: pd.DataFrame) -> pd.DataFrame:
    """Totales por archivo/invoice/moneda, para comparar rápido contra el PDF.

    Cuando el parser de la marca extrae el total que la factura declara
    (columna 'total_factura_pdf' — hoy solo THEBALM/CISNE_NEGRO/HELLO_SUNDAY
    la traen, el resto queda NaN = "no disponible, no comparar"), se agrega
    una columna 'diferencia' para detectar facturas donde la suma de
    nuestras líneas no cuadra con lo que el PDF dice — señal de que algo se
    parseó mal o falta una línea."""
    columnas = ["nombre_archivo", "invoice", "moneda", "cantidad", "importe", "importe_pen"]
    if df.empty or not all(c in df.columns for c in columnas):
        return pd.DataFrame()

    tmp = df.copy()
    for col in ("cantidad", "importe", "importe_pen"):
        tmp[col] = pd.to_numeric(tmp[col], errors="coerce").fillna(0)

    agregaciones = dict(
        lineas=("cantidad", "count"),
        cantidad_total=("cantidad", "sum"),
        importe_total=("importe", "sum"),
        importe_total_pen=("importe_pen", "sum"),
    )
    if "total_factura_pdf" in tmp.columns:
        tmp["total_factura_pdf"] = pd.to_numeric(tmp["total_factura_pdf"], errors="coerce")
        agregaciones["total_factura_pdf"] = ("total_factura_pdf", "first")

    resumen = (
        tmp.groupby(["nombre_archivo", "invoice", "moneda"], dropna=False)
        .agg(**agregaciones)
        .reset_index()
        .round({"cantidad_total": 2, "importe_total": 2, "importe_total_pen": 2})
    )

    if "total_factura_pdf" in resumen.columns:
        resumen["diferencia"] = (resumen["importe_total"] - resumen["total_factura_pdf"]).round(2)

    if len(resumen) > 1:
        # Sumar importe_total solo tiene sentido si todo el lote está en la misma
        # moneda (sumar USD + EUR directamente sería incorrecto); importe_total_pen
        # sí es una moneda común y siempre se puede sumar.
        monedas_distintas = resumen["moneda"].nunique() > 1
        total_lote = pd.DataFrame(
            [{
                "nombre_archivo": "TOTAL DEL LOTE",
                "invoice": "",
                "moneda": "mixto" if monedas_distintas else resumen["moneda"].iloc[0],
                "lineas": resumen["lineas"].sum(),
                "cantidad_total": round(resumen["cantidad_total"].sum(), 2),
                "importe_total": float("nan") if monedas_distintas else round(resumen["importe_total"].sum(), 2),
                "importe_total_pen": round(resumen["importe_total_pen"].sum(), 2),
            }]
        )
        resumen = pd.concat([resumen, total_lote], ignore_index=True)

    return resumen


COLUMNAS_EDITABLES = {"cantidad", "costo_unitario", "tipo_codigo", "descripcion", "codigo_producto"}


def _recalcular_importes(df: pd.DataFrame) -> pd.DataFrame:
    """cantidad/costo_unitario son editables a mano — importe (y sus
    equivalentes en PEN) tienen que quedar siempre consistentes con lo que
    se tipeó, no con lo que el parser extrajo originalmente. Usa la 'tc' ya
    calculada (no vuelve a llamar calcular_conversion_pen(): esa función
    lee PDFs de SUNAT y pega contra el BCE por red, no algo para correr en
    cada tecla que se edita). 'id' nunca se toca acá, aunque se edite
    codigo_producto — la llave ya quedó fija desde que se generó."""
    df = df.copy()
    if "cantidad" not in df.columns or "costo_unitario" not in df.columns:
        return df
    cantidad = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    costo_unitario = pd.to_numeric(df["costo_unitario"], errors="coerce").fillna(0)
    df["cantidad"] = cantidad
    df["costo_unitario"] = costo_unitario
    df["importe"] = (cantidad * costo_unitario).round(2)
    if "tc" in df.columns:
        tc = pd.to_numeric(df["tc"], errors="coerce")
        df["costo_unitario_pen"] = (costo_unitario * tc).round(2)
        df["importe_pen"] = (df["importe"] * tc).round(2)
    return df


def _hay_cambios_sin_aplicar(df: pd.DataFrame) -> bool:
    """True si 'importe' quedó desalineado de cantidad × costo_unitario —
    o sea, el usuario editó una de esas dos columnas en el editor pero
    todavía no presionó 'Aplicar cambios'. Comparar esto directamente (en
    vez de diffear el DataFrame contra un snapshot anterior) evita falsos
    positivos por cambios de dtype que hace el propio data_editor."""
    if df.empty or not all(c in df.columns for c in ("cantidad", "costo_unitario", "importe")):
        return False
    cantidad = pd.to_numeric(df["cantidad"], errors="coerce").fillna(0)
    costo_unitario = pd.to_numeric(df["costo_unitario"], errors="coerce").fillna(0)
    importe_actual = pd.to_numeric(df["importe"], errors="coerce").fillna(0).round(2)
    importe_esperado = (cantidad * costo_unitario).round(2)
    return not (importe_actual == importe_esperado).all()


_MESES_NOMBRE = {
    "01": "Enero", "02": "Febrero", "03": "Marzo", "04": "Abril", "05": "Mayo", "06": "Junio",
    "07": "Julio", "08": "Agosto", "09": "Setiembre", "10": "Octubre", "11": "Noviembre", "12": "Diciembre",
}


def _nombre_periodo(periodo: str) -> str:
    """'202607' -> 'Julio 2026', para mostrarle al usuario un mes legible en
    vez del código YYYYMM interno."""
    if len(periodo) != 6:
        return periodo
    anio, mes = periodo[:4], periodo[4:]
    return f"{_MESES_NOMBRE.get(mes, mes)} {anio}"


def _encabezado(numero: int, texto: str):
    st.markdown(
        f"""
        <div style="display:flex; align-items:center; gap:10px; margin:6px 0 14px 0;">
          <div style="background:#FA0082; color:white; width:28px; height:28px; border-radius:50%;
                      display:flex; align-items:center; justify-content:center; font-weight:600; flex-shrink:0;">
            {numero}
          </div>
          <span style="font-size:1.3rem; font-weight:600;">{texto}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


usuario = auth.current_user()

with st.sidebar:
    if _LOGO_PATH.exists():
        st.image(str(_LOGO_PATH), width=120)
    st.divider()
    st.subheader("Historial de esta sesión")
    if not st.session_state["historial"]:
        st.caption("Aún no se ha subido ninguna factura.")
    for item in reversed(st.session_state["historial"]):
        st.caption(f"✅ {item['marca']} · {item['archivo']} · {item['lineas']} líneas · {item['usuario']}")

with st.container(border=True):
    col_logo, col_titulo = st.columns([1, 5], vertical_alignment="center")
    with col_logo:
        if _LOGO_PATH.exists():
            st.image(str(_LOGO_PATH), width=140)
    with col_titulo:
        st.markdown(
            "<h2 style='margin-bottom:0;'>Revisor de facturas de importación</h2>"
            "<p style='color:#BC658E; margin-top:0;'>Digitalización asistida de facturas de importación</p>",
            unsafe_allow_html=True,
        )

if not usuario:
    auth.render_login_prompt()
    st.stop()

# Recién acá hay credenciales de Drive en la sesión (se guardan en el login) —
# en modo nube arma el espejo local de SUNAT_DIR con lo que haya en Drive; en
# local no hace nada (SUNAT_DIR ya es una carpeta real). Cacheado a nivel de
# proceso: si otra sesión ya lo hizo, esto no vuelve a descargar nada.
bootstrap.ensure_sunat_mirror()

resumen_tc = script.resumen_tc_disponible()
if resumen_tc is None:
    st.warning(
        f"⚠️ No hay ningún PDF de tipo de cambio de SUNAT cargado todavía — "
        f"[descárgalo acá]({script.SUNAT_TC_URL}) (un mes por vez) antes de procesar facturas en USD/EUR."
    )
else:
    fecha_max_legible = datetime.strptime(resumen_tc["fecha_max"], "%Y-%m-%d").strftime("%d/%m/%Y")
    fecha_min_legible = datetime.strptime(resumen_tc["fecha_min"], "%Y-%m-%d").strftime("%d/%m/%Y")
    texto_tc = (
        f"💱 Tipo de cambio SUNAT disponible desde el **{fecha_min_legible}** hasta el "
        f"**{fecha_max_legible}** ({resumen_tc['dias_ultimo_mes']} día(s) registrado(s) en "
        f"{_nombre_periodo(resumen_tc['periodo_max'])})."
    )
    if resumen_tc["meses_faltantes"]:
        meses_txt = ", ".join(_nombre_periodo(p) for p in resumen_tc["meses_faltantes"])
        st.warning(
            f"{texto_tc} Faltan meses en el medio del rango: **{meses_txt}** — "
            f"[descárgalos acá]({script.SUNAT_TC_URL}) (un mes por vez)."
        )
    else:
        st.caption(f"{texto_tc} [Descargar más meses]({script.SUNAT_TC_URL})")

with st.expander("➕ Subir PDF de tipo de cambio de SUNAT"):
    st.caption(
        "Podés subir el PDF mensual de SUNAT en cualquier momento — no hace falta estar "
        "revisando una factura. El sistema detecta solo qué mes cubre."
    )
    archivo_sunat_manual = st.file_uploader(
        "PDF de tipo de cambio SUNAT",
        type=["pdf"],
        key=f"sunat_manual_{st.session_state['sunat_uploader_key']}",
    )
    if archivo_sunat_manual is not None:
        _, periodo_detectado = storage.guardar_pdf_sunat_auto(archivo_sunat_manual.getvalue())
        st.session_state["sunat_uploader_key"] += 1
        if periodo_detectado:
            st.success(f"Tipo de cambio de {_nombre_periodo(periodo_detectado)} cargado.")
        else:
            st.warning(
                "Se guardó el PDF pero no se pudo detectar el mes/año automáticamente — "
                "revísalo a mano en la carpeta sunat_tc."
            )
        st.rerun()

    if bootstrap.bootstrap_sheets_credentials() == "cloud":
        st.divider()
        if st.button("🔄 Refrescar tasas SUNAT desde Drive"):
            bootstrap.ensure_sunat_mirror.clear()
            bootstrap.ensure_sunat_mirror()
            st.rerun()
        st.caption(
            "Solo hace falta si alguien editó la carpeta 'sunat_tc' directo en Drive "
            "mientras la app llevaba rato corriendo sin reiniciarse."
        )

modo = st.segmented_control(
    "Sección",
    ["Revisar factura", "🆕 Nuevo proveedor", "📊 Dashboard"],
    default="Revisar factura",
    label_visibility="collapsed",
)
st.divider()

if modo == "📊 Dashboard":
    dashboard.render()

elif modo == "🆕 Nuevo proveedor":
    st.markdown(
        "Proveedor sin parser todavía, o le cambiaron la plantilla a su factura. "
        "Sube el/los PDF(s) aquí y descarga el JSON de cada uno — no toca Sheets ni "
        "mueve archivos, solo lee la estructura del documento. Pega ese JSON en una "
        "conversación para que se arregle el parser existente o se cree uno nuevo en `script.py`."
    )
    archivos_nuevo_proveedor = st.file_uploader(
        "PDF(s) del proveedor nuevo / factura que falló",
        type=["pdf"],
        accept_multiple_files=True,
        key="uploader_nuevo_proveedor",
    )
    for i, archivo in enumerate(archivos_nuevo_proveedor or []):
        with st.expander(archivo.name, expanded=True):
            _mostrar_preview_pdf(archivo.getvalue(), dom_id=f"np_{i}")
            st.download_button(
                "🔧 Exportar estructura del PDF (JSON)",
                data=diagnostico.exportar_estructura_pdf(archivo.getvalue(), nombre=archivo.name),
                file_name=f"{Path(archivo.name).stem}_estructura.json",
                mime="application/json",
                key=f"diagnostico_nuevo_{archivo.name}",
            )

else:
    if st.session_state["resultado"] is None:
        _encabezado(1, "Cargar factura")

        with st.container(border=True):
            col_a, col_b = st.columns(2)
            with col_a:
                # Agrupado por proveedor (mismo proveedor = mismo parser para
                # todas sus marcas) y con el proveedor en la etiqueta, para
                # poder buscar por cualquiera de los dos en el desplegable.
                marcas_ordenadas = sorted(
                    script.MARCAS.keys(), key=lambda m: (script.MARCAS[m]["proveedor"], m)
                )
                marca = st.selectbox(
                    "Marca / proveedor",
                    options=marcas_ordenadas,
                    format_func=lambda m: f"{script.MARCAS[m]['proveedor']} // {m}",
                )
            with col_b:
                marcas_hermanas = sorted(
                    m for m in script.MARCAS if script.MARCAS[m]["proveedor"] == script.MARCAS[marca]["proveedor"]
                )
                st.caption(" ")
                st.caption(
                    f"Proveedor: **{script.MARCAS[marca]['proveedor']}** "
                    f"({', '.join(marcas_hermanas)})"
                )

            uploaded_files = st.file_uploader(
                "Documento(s) de la factura (.pdf) — puedes arrastrar varios de golpe, "
                "incluso de distinto PO: se detecta automáticamente del nombre del archivo",
                type=["pdf"],
                accept_multiple_files=True,
                key=f"uploader_{st.session_state['uploader_key']}",
            )

            if uploaded_files:
                st.markdown("**Confirma el PO de cada archivo** (detectado del nombre; corrígelo si hace falta)")
                df_pos = pd.DataFrame(
                    [
                        {
                            "archivo": f.name,
                            "po": pipeline.detectar_po_desde_nombre(f.name) or "",
                        }
                        for f in uploaded_files
                    ]
                )
                # Key ligada a los archivos actuales (no fija): si cambia el lote
                # subido, el editor arranca con estado fresco en vez de arrastrar
                # una edición cacheada de una tabla con otra cantidad de filas
                # (eso hacía que el primer clic en "Procesar" fallara y el segundo sí).
                huella_lote = hashlib.md5(
                    "|".join(f.name for f in uploaded_files).encode()
                ).hexdigest()[:8]
                df_pos_editado = st.data_editor(
                    df_pos,
                    use_container_width=True,
                    hide_index=True,
                    disabled=["archivo"],
                    key=f"editor_pos_{st.session_state['uploader_key']}_{huella_lote}",
                )

                pos_normalizados = df_pos_editado["po"].astype(str).str.strip().str.upper()
                con_problema = ~pos_normalizados.map(lambda p: bool(pipeline.PO_PATTERN.match(p)))
                if con_problema.any():
                    st.warning(
                        f"{con_problema.sum()} archivo(s) con PO vacío o con formato raro "
                        f"(ej. IMP154-2025) — corrígelos en la tabla antes de procesar."
                    )

                if st.button("Procesar factura(s)", type="primary", disabled=con_problema.any()):
                    # Con lotes grandes esto puede tardar (parseo + Sheets); sin este
                    # aviso visible, un clic durante ese rato se siente "perdido" y
                    # invita a apretar de nuevo. El spinner deja claro que ya está
                    # trabajando con el primer clic.
                    with st.spinner(f"Procesando {len(uploaded_files)} archivo(s)... puede tardar unos segundos"):
                        try:
                            archivos = [
                                (f.name, f.getvalue(), po)
                                for f, po in zip(uploaded_files, pos_normalizados)
                            ]
                            resultado = pipeline.procesar_documentos(marca=marca, archivos=archivos)
                            st.session_state["resultado"] = resultado
                            st.session_state["df_editado"] = resultado.df.copy()
                            st.session_state["df_ajustes_editado"] = resultado.ajustes.copy()
                            st.session_state["orden_preview"] = list(range(len(resultado.archivos)))
                        except pipeline.POInvalidoError as e:
                            st.error(str(e))
                            st.stop()
                        except Exception as e:
                            st.error(f"No se pudo procesar la factura: {e}")
                            st.stop()
                    st.rerun()

    else:
        resultado = st.session_state["resultado"]

        nombres = ", ".join(a.nombre_final for a in resultado.archivos)
        pos_str = ", ".join(resultado.pos)
        _encabezado(2, f"Revisar: {resultado.marca} · PO {pos_str} ({len(resultado.archivos)} archivo(s))")
        st.caption(nombres)

        for advertencia in resultado.advertencias:
            st.warning(advertencia)

        col_pdf, col_tabla = st.columns([1, 1.4])

        with col_pdf:
            st.markdown("**Vista previa del/los documento(s)**")
            st.caption(
                "Usa ⬆️/⬇️ para subir la factura que estás revisando junto a su detalle de "
                "filas, sin tener que scrollear un lote largo cada vez."
            )
            n_archivos = len(resultado.archivos)
            if (
                "orden_preview" not in st.session_state
                or len(st.session_state["orden_preview"]) != n_archivos
            ):
                st.session_state["orden_preview"] = list(range(n_archivos))
            orden_preview = st.session_state["orden_preview"]

            for pos, i in enumerate(orden_preview):
                archivo = resultado.archivos[i]
                col_up, col_down, col_label = st.columns([0.09, 0.09, 0.82])
                with col_up:
                    if st.button("⬆️", key=f"subir_{i}", disabled=(pos == 0), help="Subir"):
                        orden_preview[pos], orden_preview[pos - 1] = orden_preview[pos - 1], orden_preview[pos]
                        st.rerun()
                with col_down:
                    if st.button("⬇️", key=f"bajar_{i}", disabled=(pos == n_archivos - 1), help="Bajar"):
                        orden_preview[pos], orden_preview[pos + 1] = orden_preview[pos + 1], orden_preview[pos]
                        st.rerun()
                with col_label:
                    st.caption(f"{pos + 1}/{n_archivos}")

                with st.expander(archivo.filename_original, expanded=(pos == 0)):
                    if archivo.staged_path.suffix.lower() == ".pdf":
                        _mostrar_preview_pdf(archivo.staged_path, dom_id=str(i))
                        st.download_button(
                            "🔧 Exportar estructura del PDF (JSON, para depurar el parser)",
                            data=diagnostico.exportar_estructura_pdf(
                                archivo.staged_path, nombre=archivo.filename_original
                            ),
                            file_name=f"{Path(archivo.filename_original).stem}_estructura.json",
                            mime="application/json",
                            key=f"diagnostico_{i}",
                            help="Si la extracción falló o se ve rara, descarga esto y pégalo "
                            "en una conversación para arreglar el parser o crear uno nuevo.",
                        )
                    else:
                        _mostrar_preview_excel(archivo.staged_path)

                    st.checkbox(
                        "🚫 Excluir del lote (no subir estas líneas; el JSON de arriba sirve para mandar a mejorar el parser)",
                        key=f"excluir_{i}",
                    )

        archivos_excluidos = {
            archivo.nombre_final
            for i, archivo in enumerate(resultado.archivos)
            if st.session_state.get(f"excluir_{i}", False)
        }

        with col_tabla:
            st.markdown("**Datos a subir a Google Sheets** (editable)")
            st.caption(
                "Solo se puede editar cantidad, costo_unitario, tipo_codigo, descripcion y "
                "codigo_producto — el resto son datos de identificación de la factura, no se "
                "tocan a mano. Después de editar cantidad/costo_unitario, presiona 'Aplicar "
                "cambios' para recalcular importe (y su versión en PEN) — no se recalcula solo en "
                "cada tecla porque con lotes grandes se sentía lento."
            )
            meses_tc_faltante = pipeline.meses_con_tc_faltante(st.session_state["df_editado"])
            if meses_tc_faltante:
                st.warning(
                    "⚠️ Falta el tipo de cambio oficial de SUNAT para "
                    + ", ".join(_nombre_periodo(p) for p in meses_tc_faltante)
                    + " — sube el PDF completo de ese mes (se descarga de la web de SUNAT) y el "
                    "sistema completa el resto solo."
                )
                for periodo in meses_tc_faltante:
                    archivo_sunat = st.file_uploader(
                        f"PDF de tipo de cambio SUNAT — {_nombre_periodo(periodo)}",
                        type=["pdf"],
                        key=f"sunat_{periodo}",
                    )
                    if archivo_sunat is not None:
                        storage.guardar_pdf_sunat(archivo_sunat.getvalue(), periodo)
                        st.session_state["df_editado"] = pipeline.recalcular_conversion_pen(
                            st.session_state["df_editado"]
                        )
                        st.success(f"Tipo de cambio de {_nombre_periodo(periodo)} cargado.")
                        st.rerun()

            df_base = st.session_state["df_editado"]
            # 'nombre_archivo'/'invoice'/'po' primero y siempre visibles: el buscador nativo de
            # Streamlit solo resalta la celda que matchea, no toda la fila (no hay forma de
            # cambiar eso desde acá) — dejar estas columnas al frente es lo que sí se puede hacer
            # para ubicar de un vistazo a qué factura pertenece la fila en la que estás parado.
            columnas_identificadoras = [c for c in ("nombre_archivo", "invoice", "po") if c in df_base.columns]
            column_order = columnas_identificadoras + [c for c in df_base.columns if c not in columnas_identificadoras]
            columnas_bloqueadas = [c for c in df_base.columns if c not in COLUMNAS_EDITABLES]

            df_editado_bruto = st.data_editor(
                df_base,
                num_rows="dynamic",
                use_container_width=True,
                height=520,
                column_order=column_order,
                disabled=columnas_bloqueadas,
                column_config={
                    "ya_en_sheet": st.column_config.CheckboxColumn(
                        "¿Ya existe en Sheet?", disabled=True
                    ),
                },
                key="editor_datos",
            )

            cambios_pendientes = _hay_cambios_sin_aplicar(df_editado_bruto)
            col_aplicar, col_aviso = st.columns([1, 3])
            with col_aplicar:
                if st.button("🔄 Aplicar cambios", disabled=not cambios_pendientes):
                    st.session_state["df_editado"] = _recalcular_importes(df_editado_bruto)
                    st.rerun()
            with col_aviso:
                if cambios_pendientes:
                    st.warning(
                        "✏️ Tienes cambios de cantidad/costo_unitario sin aplicar — presiona "
                        "'Aplicar cambios' para recalcular importe antes de revisar el resumen o confirmar."
                    )

            # El resumen y la confirmación usan la última versión APLICADA
            # (session_state), no el borrador crudo del editor — así nunca
            # se sube algo con importe desalineado de cantidad×costo_unitario.
            df_editado = st.session_state["df_editado"]

            if archivos_excluidos and "nombre_archivo" in df_editado.columns:
                n_filas_excluidas = df_editado["nombre_archivo"].isin(archivos_excluidos).sum()
                st.warning(
                    f"🚫 {len(archivos_excluidos)} archivo(s) excluido(s) del lote — "
                    f"{n_filas_excluidas} línea(s) no se subirán al confirmar."
                )

            st.markdown("**Resumen por factura** — compara estos totales contra el PDF")
            resumen = _resumen_por_factura(df_editado)
            if resumen.empty:
                st.caption("No hay suficientes datos para calcular el resumen.")
            else:
                resumen_mostrar = resumen.rename(columns={
                    "nombre_archivo": "archivo",
                    "cantidad_total": "cantidad",
                    "importe_total": "importe",
                    "importe_total_pen": "importe (PEN)",
                    "total_factura_pdf": "total en PDF",
                })
                column_config_resumen = {
                    "cantidad": st.column_config.NumberColumn(format="%,.2f"),
                    "importe": st.column_config.NumberColumn(format="%,.2f"),
                    "importe (PEN)": st.column_config.NumberColumn(format="%,.2f"),
                }

                tabla_resumen = resumen_mostrar
                if "diferencia" in resumen_mostrar.columns:
                    column_config_resumen["total en PDF"] = st.column_config.NumberColumn(format="%,.2f")
                    column_config_resumen["diferencia"] = st.column_config.NumberColumn(format="%,.2f")

                    def _resaltar_diferencia(fila):
                        hay_diferencia = pd.notna(fila.get("diferencia")) and abs(fila["diferencia"]) > 0.01
                        return ["background-color: #FFCDD2" if hay_diferencia else "" for _ in fila]

                    tabla_resumen = resumen_mostrar.style.apply(_resaltar_diferencia, axis=1)

                    if resumen["diferencia"].abs().gt(0.01).any():
                        st.error(
                            "⚠️ Alguna factura no cuadra contra su propio total declarado en el PDF "
                            "(columna 'diferencia', filas en rojo) — revísala antes de confirmar."
                        )

                st.dataframe(
                    tabla_resumen,
                    use_container_width=True,
                    hide_index=True,
                    column_config=column_config_resumen,
                )
                if "total_factura_pdf" not in resumen.columns:
                    st.caption(
                        "Esta marca todavía no extrae el total declarado en el PDF, así que no se "
                        "puede comparar automáticamente — compáralo a mano contra el documento."
                    )

            st.markdown("**Ajustes** (descuentos, créditos, cargos adicionales — ej. estanterías/acrílicos)")
            st.caption(
                "Lo detectado automáticamente aparece marcado como origen 'AUTO' — revísalo antes de "
                "confirmar. Para agregar uno a mano (ej. un crédito o cargo que el parser no detecta "
                "solo), usa el formulario: elige la factura y el tipo, escribe el monto y la fila se "
                "arma sola con los datos de esa factura. Usa CUSTOM para lo que no encaje en las otras "
                "categorías (ej. 'cargo por acrílicos') — ahí eliges vos el signo. Se guarda en la "
                "pestaña 'ajustes' del Sheet, separado de las líneas de producto."
            )
            nombres_archivo_lote = [a.nombre_final for a in resultado.archivos]

            col_archivo, col_categoria = st.columns([2, 1])
            with col_archivo:
                archivo_ajuste = st.selectbox(
                    "Factura", options=nombres_archivo_lote, key="ajuste_sel_archivo"
                )
            with col_categoria:
                categoria_ajuste = st.selectbox(
                    "Tipo de ajuste", options=list(pipeline.CATEGORIAS_AJUSTE), key="ajuste_sel_categoria"
                )
            es_custom = categoria_ajuste == "CUSTOM"

            with st.form("form_agregar_ajuste", clear_on_submit=True):
                if es_custom:
                    col_monto, col_signo = st.columns([1, 1])
                    with col_monto:
                        monto_ajuste = st.number_input(
                            "Monto (sin signo)", min_value=0.0, step=0.01, format="%.2f"
                        )
                    with col_signo:
                        signo_ajuste = st.radio(
                            "Signo", options=["Resta (-)", "Suma (+)"], horizontal=True
                        )
                    descripcion_ajuste = st.text_input(
                        "Descripción (obligatoria en CUSTOM, ej. 'Cargo por acrílicos')"
                    )
                else:
                    monto_ajuste = st.number_input(
                        "Monto (sin signo)", min_value=0.0, step=0.01, format="%.2f",
                        help="Escribe el monto siempre en positivo — el signo se aplica solo según el "
                        "tipo (DESCUENTO/CREDITO restan, CARGO suma).",
                    )
                    signo_ajuste = None
                    descripcion_ajuste = st.text_input("Descripción (ej. 'Marketing contribution')")
                agregar_ajuste = st.form_submit_button("➕ Agregar ajuste")

            if agregar_ajuste:
                if monto_ajuste == 0:
                    st.warning("El monto no puede ser 0 — no se agregó ningún ajuste.")
                elif es_custom and not descripcion_ajuste.strip():
                    st.warning("En CUSTOM la descripción es obligatoria — no se agregó ningún ajuste.")
                else:
                    if es_custom:
                        monto_con_signo = -monto_ajuste if signo_ajuste == "Resta (-)" else monto_ajuste
                    else:
                        monto_con_signo = (
                            -monto_ajuste if categoria_ajuste in ("DESCUENTO", "CREDITO") else monto_ajuste
                        )
                    fila_factura = resultado.df[resultado.df["nombre_archivo"] == archivo_ajuste]
                    primero = fila_factura.iloc[0] if not fila_factura.empty else {}
                    nueva_fila = {
                        "id": "",
                        "marca": resultado.marca,
                        "proveedor": resultado.proveedor,
                        "po": primero.get("po", ""),
                        "invoice": primero.get("invoice", ""),
                        "invoice_date": primero.get("invoice_date", ""),
                        "periodo": primero.get("periodo", ""),
                        "categoria": categoria_ajuste,
                        "descripcion": descripcion_ajuste.strip() or categoria_ajuste.title(),
                        "monto": monto_con_signo,
                        "origen": "MANUAL",
                        "nombre_archivo": archivo_ajuste,
                    }
                    st.session_state["df_ajustes_editado"] = pd.concat(
                        [st.session_state["df_ajustes_editado"], pd.DataFrame([nueva_fila])],
                        ignore_index=True,
                    )
                    st.rerun()

            df_ajustes_editado = st.data_editor(
                st.session_state["df_ajustes_editado"],
                num_rows="dynamic",
                use_container_width=True,
                column_config={
                    "categoria": st.column_config.SelectboxColumn(
                        "Categoría", options=list(pipeline.CATEGORIAS_AJUSTE), required=True
                    ),
                    "nombre_archivo": st.column_config.SelectboxColumn(
                        "Archivo", options=nombres_archivo_lote
                    ),
                    "monto": st.column_config.NumberColumn("Monto", format="%.2f"),
                    "origen": st.column_config.TextColumn("Origen", disabled=True),
                },
                key="editor_ajustes",
            )
            # Filas agregadas a mano (directo en la tabla, sin pasar por el
            # formulario) no traen marca/proveedor/origen — se completan solas
            # para que no dependa de que el usuario las tipee bien.
            if not df_ajustes_editado.empty:
                df_ajustes_editado["marca"] = resultado.marca
                df_ajustes_editado["proveedor"] = resultado.proveedor
                df_ajustes_editado["origen"] = df_ajustes_editado["origen"].where(
                    df_ajustes_editado["origen"].astype(str).str.strip() != "", "MANUAL"
                )
            st.session_state["df_ajustes_editado"] = df_ajustes_editado

            col_confirmar, col_descartar = st.columns(2)
            with col_confirmar:
                if st.button("✅ Confirmar y subir", type="primary"):
                    if cambios_pendientes:
                        st.error(
                            "✏️ Tienes cambios de cantidad/costo_unitario sin aplicar en la tabla de "
                            "arriba — presiona 'Aplicar cambios' antes de confirmar, si no vas a subir "
                            "importes desactualizados."
                        )
                        st.stop()
                    try:
                        ingesta = pipeline.confirmar_e_ingestar(
                            resultado, df_editado, archivos_excluidos, df_ajustes_editado
                        )
                        st.session_state["historial"].append(
                            {
                                "marca": resultado.marca,
                                "archivo": f"{len(ingesta.worked_paths)} archivo(s), PO {', '.join(resultado.pos)}",
                                "lineas": ingesta.insertados,
                                "usuario": usuario,
                            }
                        )
                        rutas = "\n".join(
                            f"- [{p.name}]({p.web_view_link})" if p.web_view_link else f"- {p.name}"
                            for p in ingesta.worked_paths
                        )
                        mensaje_ajustes = (
                            f" · {ingesta.ajustes_insertados} ajuste(s) insertado(s)"
                            f"{f', {ingesta.ajustes_duplicados} omitido(s) por duplicado' if ingesta.ajustes_duplicados else ''}."
                            if (ingesta.ajustes_insertados or ingesta.ajustes_duplicados) else ""
                        )
                        st.success(
                            f"Listo: {ingesta.insertados} filas insertadas, "
                            f"{ingesta.duplicados} omitidas por duplicado{mensaje_ajustes}\n\n"
                            f"Archivos movidos a:\n{rutas}"
                        )
                        st.session_state["resultado"] = None
                        st.session_state["df_editado"] = None
                        st.session_state["df_ajustes_editado"] = None
                        st.session_state["uploader_key"] += 1
                        _limpiar_checkboxes_exclusion()
                    except Exception as e:
                        st.error(f"No se pudo completar la subida: {e}")

            with col_descartar:
                if st.button("🗑️ Descartar y empezar de nuevo"):
                    _reset_formulario()
                    st.rerun()
