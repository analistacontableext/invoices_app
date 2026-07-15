"""
Login real con cuenta de Google (OAuth 2.0), restringido a una lista de
correos autorizados. Reemplaza el campo de texto libre de v1.

Requiere el archivo oauth_client.json (Client ID + Secret de un OAuth Client
tipo "Aplicación web", descargado desde Google Cloud Console) junto a script.py.
"""
import json
from pathlib import Path

import streamlit as st
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from google_auth_oauthlib.flow import Flow

_OAUTH_CLIENT_FILE = Path(__file__).resolve().parent.parent / "oauth_client.json"


def _redirect_uri_desde_secrets() -> str:
    # st.secrets puede no tener ni archivo secrets.toml en dev local (no todos
    # los Streamlit se comportan igual con .get() cuando no hay ningún secreto
    # configurado) — se envuelve en try/except para no romper el import acá.
    try:
        return st.secrets["oauth_client"]["redirect_uri"]
    except Exception:
        return "http://localhost:8501"


_REDIRECT_URI = _redirect_uri_desde_secrets()
_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    # Drive: para que cada usuario suba/lea archivos con su propia cuota, en vez
    # de depender de la cuenta de servicio (ver app/drive_client.py). Es un scope
    # amplio (no drive.file) porque la app necesita listar/leer carpetas que ya
    # existen y que el usuario no creó él mismo desde acá (facturas de otros,
    # PDFs de SUNAT ya subidos, etc.), no solo archivos nuevos.
    "https://www.googleapis.com/auth/drive",
]

# Correos autorizados a usar la app. Para sumar a alguien más del equipo,
# solo agrega su correo acá — no hace falta tocar nada más del código.
ALLOWLIST = {
    "analista.contable.ext@lindcorp.pe",
    "brian.campos@lindcorp.pe",
}

# Guarda el code_verifier (PKCE) de cada intento de login, indexado por el
# parámetro 'state'. No puede vivir en st.session_state: al hacer clic en el
# link el navegador sale por completo hacia accounts.google.com y vuelve con
# una petición nueva, que Streamlit trata como sesión nueva (se perdería todo
# lo que hubiera en session_state). Este diccionario vive a nivel de módulo,
# en el proceso del servidor, así que sí sobrevive esa ida y vuelta.
_verificadores_pendientes: dict[str, str] = {}


def _client_config() -> dict:
    # En Streamlit Cloud no existe oauth_client.json (queda afuera del repo a
    # propósito, ver .gitignore) — ahí se arma el mismo dict desde st.secrets.
    # En dev local sin secrets.toml, se cae al archivo físico de siempre.
    try:
        if "oauth_client" in st.secrets and "web" in st.secrets["oauth_client"]:
            return {"web": dict(st.secrets["oauth_client"]["web"])}
    except Exception:
        pass
    with open(_OAUTH_CLIENT_FILE, encoding="utf-8") as f:
        return json.load(f)


def _client_id() -> str:
    return _client_config()["web"]["client_id"]


def _flow() -> Flow:
    return Flow.from_client_config(
        _client_config(), scopes=_SCOPES, redirect_uri=_REDIRECT_URI,
        autogenerate_code_verifier=True,
    )


def current_user() -> str | None:
    """Procesa el resultado del login (si viene un ?code= en la URL) y
    devuelve el correo autenticado si ya hay sesión activa. No dibuja nada en
    pantalla — para eso está render_login_prompt()."""
    if "usuario_autenticado" in st.session_state:
        return st.session_state["usuario_autenticado"]

    params = st.query_params
    if "code" not in params:
        return None

    flow = _flow()
    flow.code_verifier = _verificadores_pendientes.pop(params.get("state", ""), None)
    try:
        flow.fetch_token(code=params["code"])
    except Exception as e:
        st.query_params.clear()
        st.error(f"No se pudo completar el login con Google: {e}")
        return None

    try:
        info = id_token.verify_oauth2_token(
            flow.credentials.id_token, google_requests.Request(), audience=_client_id()
        )
        email = info.get("email")
    except Exception as e:
        st.query_params.clear()
        st.error(f"No se pudo verificar la identidad de Google: {e}")
        return None

    st.query_params.clear()

    if email not in ALLOWLIST:
        st.error(f"Tu cuenta ({email}) no está autorizada para usar esta app todavía.")
        return None

    # Se guardan las credenciales OAuth completas (no solo el email) para que
    # app/drive_client.py pueda subir/leer archivos de Drive con la cuota de
    # este usuario en vez de la cuenta de servicio (ver Contexto en el plan de
    # migración a Drive API). refresh_token puede venir vacío si Google ya
    # tenía un consentimiento previo sin "prompt=consent" — no debería pasar acá
    # porque _flow()/authorization_url ya fuerza access_type="offline" +
    # prompt="consent", pero se guarda igual lo que haya.
    st.session_state["drive_credentials"] = {
        "token": flow.credentials.token,
        "refresh_token": flow.credentials.refresh_token,
        "token_uri": flow.credentials.token_uri,
        "client_id": flow.credentials.client_id,
        "client_secret": flow.credentials.client_secret,
        "scopes": flow.credentials.scopes,
    }
    st.session_state["usuario_autenticado"] = email
    st.rerun()


def render_login_prompt() -> None:
    """Muestra el botón de 'Iniciar sesión con Google' cuando no hay sesión activa."""
    flow = _flow()
    auth_url, state = flow.authorization_url(
        prompt="consent", access_type="offline", include_granted_scopes="true"
    )
    _verificadores_pendientes[state] = flow.code_verifier

    st.info("Inicia sesión con tu cuenta corporativa de Google para continuar.")
    # target="_self" a propósito: st.link_button abre en pestaña nueva, lo que
    # deja dos pestañas de la app abiertas (la original + la que vuelve logueada).
    st.markdown(
        f'<a href="{auth_url}" target="_self" style="display:inline-block; '
        f'padding:0.5rem 1.2rem; background:#FA0082; color:white; border-radius:8px; '
        f'text-decoration:none; font-weight:600;">🔐 Iniciar sesión con Google</a>',
        unsafe_allow_html=True,
    )
