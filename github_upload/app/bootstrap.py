"""
Arranque de la app en modo nube (Streamlit Community Cloud) vs. modo local.

En local, script.py ya apunta a rutas reales en disco (CREDENTIALS_FILE junto
al código, SUNAT_DIR dentro de Gerencia_Supply_Preview) — este módulo no hace
nada. En la nube no hay ese disco compartido, así que hay que:
1. Materializar la credencial de la cuenta de servicio (para Sheets) desde
   st.secrets a un archivo temporal, y reasignar script.CREDENTIALS_FILE.
2. Descargar un espejo local de los PDFs de SUNAT (para que
   script._cargar_usd_pen_dict() siga funcionando exactamente igual, con su
   mismo cache por mtime, sin tocar su lógica) y reasignar script.SUNAT_DIR.

Reasignar esas constantes de módulo SÍ afecta a todas las funciones de
script.py que las leen (confirmado: son variables simples, nunca usadas como
default de un argumento) — con la única condición de que esto corra ANTES de
la primera vez que algo llame a Sheets/Drive en el proceso.
"""
import json
import tempfile
from pathlib import Path

import streamlit as st

import script
import drive_client


def _secret_dict(key: str) -> dict | None:
    try:
        valor = st.secrets[key]
    except Exception:
        return None
    return dict(valor) if valor else None


@st.cache_resource(show_spinner=False)
def bootstrap_sheets_credentials() -> str:
    """Corre una sola vez por proceso (thread-safe entre sesiones
    concurrentes). Si no hay secretos de nube configurados, no hace nada —
    dev local sigue usando credenciales.json tal cual. Se llama como primera
    línea ejecutable de streamlit_app.py, antes de cualquier login o llamada
    a Sheets."""
    sa = _secret_dict("gcp_service_account")
    if sa is None:
        return "local"

    tmp_dir = Path(tempfile.mkdtemp(prefix="app_secrets_"))
    sa_path = tmp_dir / "credenciales.json"
    sa_path.write_text(json.dumps(sa), encoding="utf-8")
    script.CREDENTIALS_FILE = sa_path
    return "cloud"


@st.cache_resource(show_spinner="Sincronizando tipo de cambio SUNAT desde Drive...")
def ensure_sunat_mirror() -> int:
    """Corre una sola vez por proceso, SIN parámetros a propósito — así el
    cache es compartido por todo el proceso sin importar qué usuario la
    dispare primero (SUNAT es data de referencia compartida y de solo
    lectura, da igual con el token de quién se descargue). Se llama recién
    después de un login exitoso (recién ahí hay credenciales de Drive en la
    sesión). En modo local no hace nada — SUNAT_DIR ya es una carpeta real
    en disco."""
    if bootstrap_sheets_credentials() != "cloud":
        return 0

    tmp_dir = Path(tempfile.mkdtemp(prefix="sunat_mirror_"))
    archivos = drive_client.list_files_in_folder(script.SUNAT_TC_FOLDER_ID)
    for archivo in archivos:
        if not archivo["name"].lower().endswith(".pdf"):
            continue
        contenido = drive_client.download_file_bytes(archivo["id"])
        (tmp_dir / archivo["name"]).write_bytes(contenido)

    script.SUNAT_DIR = tmp_dir
    return len(list(tmp_dir.glob("*.pdf")))
