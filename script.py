# ══════════════════════════════════════════════════════════════════
# IMPORTS
# ══════════════════════════════════════════════════════════════════

import pdfplumber
import pandas as pd
import re
import shutil
import time
import math
from pathlib import Path
from datetime import datetime, timedelta
from time import perf_counter
import gspread
from google.oauth2.service_account import Credentials

# ══════════════════════════════════════════════════════════════════
# CONFIG - SELECCIÓN DE MARCAS
# ══════════════════════════════════════════════════════════════════

# Opciones:
#   - "TOTAL": Limpia Google Sheets, genera CSV desde cero e ingesta todo
#   - "INCREMENTAL": Solo ingesta facturas nuevas (idempotente, respeta cuota)
#   - "SOLO_CSV": Solo genera CSV, no ingesta a Google Sheets

MODO_INGESTA = "INCREMENTAL"  # Cambia a "TOTAL" para recarga completa

# Para el modo TOTAL: ¿generar CSV también?
GENERAR_CSV_EN_TOTAL = True  # True: genera CSV, False: solo ingesta a Sheets

# Opciones:
#   - "ALL": Procesa todas las marcas
#   - ["LANEIGE"]: Procesa solo una marca
#   - ["BETER", "REVOX_B77", "PIXI"]: Procesa múltiples marcas específicas

MARCAS_A_PROCESAR = ["TOCOBO"]  # Ejemplo: solo BETER

# ══════════════════════════════════════════════════════════════════
# CONFIG - RUTAS
# ══════════════════════════════════════════════════════════════════

BASE_PATH = Path(r"G:\Mi unidad\Arquitectura_de_datos\DataBase\data")


# Estructura: cada marca tiene su proveedor (carpeta madre)
# "worked_folder_id" = ID de la carpeta 'worked' en Google Drive para esa marca
# (obtenido de la hoja 'rutas', generada por el script de Apps Script que escanea
# facturas_pdf). Se usa desde la app (app/storage.py) para subir por Drive API en
# vez de depender de la ruta local sincronizada — "ruta" se mantiene para el batch
# original (script.py, que sigue leyendo/escribiendo en el filesystem local).
MARCAS = {
    "LANEIGE": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/AMOREPACIFIC_CORPORATION/LANEIGE",
        "proveedor": "AMOREPACIFIC_CORPORATION",
        "worked_folder_id": "143usoUnYMcxxwomC-TYeWYO_BfhZkIfq"
    },
    "ANASTASIA_BEVERLY_HILLS": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/ANASTASIA_BEVERLY_HILLS/ANASTASIA_BEVERLY_HILLS",
        "proveedor": "ANASTASIA_BEVERLY_HILLS",
        "worked_folder_id": "1M49lquP9JX-WXfbji97WsOzgUrmX92je"
    },
    "BEAUTY_CREATIONS": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/BEBELLA_INC/BEAUTY_CREATIONS",
        "proveedor": "BEBELLA_INC",
        "worked_folder_id": "1aKUhaR8dHzv8vScwni7Ttyzoby6WfiuD"
    },
    "BOLDIFY": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/BOLDIFY_INC/BOLDIFY",
        "proveedor": "BOLDIFY_INC",
        "worked_folder_id": "1BHWiCLsGSKSTI_Fq2WDY126C9ivrVWrD"
    },
    "COSRX": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/COSRX_INC/COSRX",
        "proveedor": "COSRX_INC",
        "worked_folder_id": "1G9YJVmAADlWVwzsXb2jJYO1wgvakz1Xl"
    },
    "KOCOSTAR": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/FIRSTMARKET_CO_LTD/KOCOSTAR",
        "proveedor": "FIRSTMARKET_CO_LTD",
        "worked_folder_id": "1bFBZbYcIgU7UQJ0OuoIbjC45qyb02z5L"
    },
    "FLOOKY": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/FLOOKY_INTERNATIONAL_LTD/FLOOKY",
        "proveedor": "FLOOKY_INTERNATIONAL_LTD",
        "worked_folder_id": "1_AtXRjVgokiM5LE4E_e3o56Xgt56rgdD"
    },
    "TONY_MOLY_HOLIKA_HOLIKA": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/HYUNDAI_C_SQUARE/TONY_MOLY_HOLIKA_HOLIKA",
        "proveedor": "HYUNDAI_C_SQUARE",
        "worked_folder_id": "1pW6nyhWmV5lmQVBZg-6pIMr7H2kk1uca"
    },
    "BETER": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/INDUSTRIAS_BETER_SA/BETER",
        "proveedor": "INDUSTRIAS_BETER_SA",
        "worked_folder_id": "1A8m_nGum1xvT3mvWZaiGhOkgrDmgjuoT"
    },
    "PETRIZZIO": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/LABORATORIOS_PETRIZZIO_LTDA/PETRIZZIO",
        "proveedor": "LABORATORIOS_PETRIZZIO_LTDA",
        "worked_folder_id": "1NfXRECkbTgCnYqK21VAb83QRftmDvV24"
    },
    "MARIO_BADESCU": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/MARIO_BADESCU_SKIN_CARE_INC/MARIO_BADESCU",
        "proveedor": "MARIO_BADESCU_SKIN_CARE_INC",
        "worked_folder_id": "1ZLWUNFb8qGaxgX8tIT6DcB2acTsZpW9S"
    },
    "OLAPLEX": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/OLAPLEX_INC/OLAPLEX",
        "proveedor": "OLAPLEX_INC",
        "worked_folder_id": "1wKnFdld5xjEh8ysUxkZQeR9l77u5vpUs"
    },
    "PIXI": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/PIXI_INC/PIXI",
        "proveedor": "PIXI_INC",
        "worked_folder_id": "1_HAmWhI62nwI9etC-SG9ZjR_q8OMw1zr"
    },
    "REVOX_B77": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/REVUELE_LTD/REVOX_B77",
        "proveedor": "REVUELE_LTD",
        "worked_folder_id": "1nsHuV3T1q6D-HCFiObrIXupjZYwQjzB-"
    },
    "TOCOBO": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/SILICON2_CO_LTD/TOCOBO",
        "proveedor": "SILICON2_CO_LTD",
        "worked_folder_id": "1rFVK5ZvUAZ-pUjq7yzbUBPL5KrlhjUqJ"
    },
    "TIRTIR": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/SILICON2_CO_LTD/TIRTIR",
        "proveedor": "SILICON2_CO_LTD",
        "worked_folder_id": "149yJH8hvG38zvPRBCmDhb673ZzJpzgfN"
    },
    "MEDICUBE": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/SILICON2_CO_LTD/MEDICUBE",
        "proveedor": "SILICON2_CO_LTD",
        "worked_folder_id": "1KMyK6c1E6r5vICn-691VPaV3f_ykzf8v"
    },
    "SLICK_HAIR": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/SLICK_HAIR_COMPANY/SLICK_HAIR",
        "proveedor": "SLICK_HAIR_COMPANY",
        "worked_folder_id": "1QzX20XySxqmJOZ1N0Bv-qv7ntsqfqS7f"
    },
    "THEBALM": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/THEBALM_COSMETICS/THEBALM",
        "proveedor": "THEBALM_COSMETICS",
        "worked_folder_id": "1GjrsFy7R0JkGxQQkx6q0YXZLSYrFObT2"
    },
    "CISNE_NEGRO": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/OCEANIC_TRADE_INVESTMENT/CISNE_NEGRO",
        "proveedor": "OCEANIC_TRADE_INVESTMENT",
        "worked_folder_id": "1tfWGTe9-gNLqfCihs9Y7StUtdv-D2b6R"
    },
    "HELLO_SUNDAY": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/HELLO_SUNDAY_VENTURES/HELLO_SUNDAY",
        "proveedor": "HELLO_SUNDAY_VENTURES",
        "worked_folder_id": "1k5GuEFZFiueYT-58Wt-H_YuszWLdY0aB"
    },
    "EARTH_RHYTHM": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/EARTH_RHYTHM_PRIVATE_LIMITED/EARTH_RHYTHM",
        "proveedor": "EARTH_RHYTHM_PRIVATE_LIMITED",
        "worked_folder_id": "1DW_3iQBjaapWpwxA9IHcmZweLHlh-xzJ"
    },
    "NEW_STUDIO": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/TWEEZERMAN_INTERNATIONAL/NEW_STUDIO",
        "proveedor": "TWEEZERMAN_INTERNATIONAL",
        "worked_folder_id": "1OGIKBo9Yw81UpGME3qacpZdF1pssWFD9"
    },
    "7_DAYS": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/SOFIS_SRL/7_DAYS",
        "proveedor": "SOFIS_SRL",
        "worked_folder_id": "18J6UUhcrz3MfuNlOPjPqeZJ14qb9gWk5"
    },
    "FOAMOUS": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/BEYOND_PERFUME_SAS/FOAMOUS",
        "proveedor": "BEYOND_PERFUME_SAS",
        "worked_folder_id": "11d4c8wj1SUuAmPag2QXi8OYfftNDzMPc"
    },
    "COZI_LIFE": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/TANTUC_ASIA_LTD/COZI_LIFE",
        "proveedor": "TANTUC_ASIA_LTD",
        "worked_folder_id": "1sY-pCV13c-nRpCx1Ge_gj0dzbULl8SPP"
    },
    "LATAM_CHINA": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/LATAM_CHINA_TRADING/LATAM_CHINA",
        "proveedor": "LATAM_CHINA_TRADING",
        "worked_folder_id": "1sZhL-e8ifN-HsjNfBRktwsRlrk3ZVNF-"
    },
    "FUJIAN_OUKANG": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/FUJIAN_OUKANG_CO_LTD/FUJIAN_OUKANG",
        "proveedor": "FUJIAN_OUKANG_CO_LTD",
        "worked_folder_id": "1O22C0m060k4mjNWYqP5s1xRT2NL9THNv"
    },
    "BORLA": {
        "ruta": BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/facturas_pdf/FUJIAN_OUKANG_CO_LTD/BORLA",
        "proveedor": "FUJIAN_OUKANG_CO_LTD",
        "worked_folder_id": "1rDpv4aSb5xSZWG-4iZiedZrre5yQLqhS"
    },
}
OUTPUT_PATH = BASE_PATH / "silver/importaciones/csv"
OUTPUT_PATH.mkdir(parents=True, exist_ok=True)

# ══════════════════════════════════════════════════════════════════
# CONFIG - GOOGLE SHEETS (NUEVO)
# ══════════════════════════════════════════════════════════════════

# ID de tu Google Sheet (el que ya creaste con las 23 columnas)
GOOGLE_SHEET_ID = "1gW4EU0kpf9yOPTuyTvQPb5VNltyJ989lJAJ9Xls_VFs"

# Ruta de tu archivo JSON de credenciales (debe estar junto al script o en ruta fija)
CREDENTIALS_FILE = Path(__file__).parent / "credenciales.json"

# Carpeta con los PDFs de tipo de cambio de SUNAT (debe vivir en el Drive compartido,
# no en el perfil local de un usuario, para que funcione igual en cualquier máquina)
SUNAT_DIR = BASE_PATH / "bronze/importaciones/Gerencia_Supply_Preview/sunat_tc"

# ID de Drive de la carpeta de arriba — usado por la app desplegada (sin acceso a
# filesystem local) vía app/drive_client.py + app/bootstrap.py.
SUNAT_TC_FOLDER_ID = "1zuRY7ctCmdIOXW9gsA5XXt9K67v1Qvxu"

# Página de SUNAT donde se descarga el PDF mensual de tipo de cambio (solo deja
# bajar un mes por vez) — se linkea desde la app cuando falta un mes.
SUNAT_TC_URL = "https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias"

# Caches de tipo de cambio en memoria (vida del proceso): el tipo de cambio de una
# fecha pasada no cambia una vez publicado, así que no hay motivo para releer todos
# los PDFs de SUNAT ni volver a pegarle al XML del BCE en cada llamada de
# calcular_conversion_pen(). _SUNAT_RATES_CACHE guarda las tasas ya extraídas de
# cada PDF por ruta+mtime (si el archivo no cambió, no se vuelve a parsear; un PDF
# nuevo o modificado sí). _EUR_USD_CACHE se llena una sola vez por proceso.
_SUNAT_RATES_CACHE = {}
_EUR_USD_CACHE = None





# ══════════════════════════════════════════════════════════════════
# VALIDACIÓN DE MARCAS A PROCESAR
# ══════════════════════════════════════════════════════════════════

def obtener_marcas_a_procesar():
    """Retorna un diccionario con las marcas a procesar según la configuración"""
    
    if MARCAS_A_PROCESAR == "ALL":
        print("✅ Modo: PROCESAR TODAS LAS MARCAS")
        return MARCAS
    
    elif isinstance(MARCAS_A_PROCESAR, list):
        # Verificar que todas las marcas existan
        marcas_validas = {}
        marcas_no_encontradas = []
        
        for marca in MARCAS_A_PROCESAR:
            if marca in MARCAS:
                marcas_validas[marca] = MARCAS[marca]
            else:
                marcas_no_encontradas.append(marca)
        
        if marcas_no_encontradas:
            print(f"⚠ ADVERTENCIA: Las siguientes marcas no existen: {marcas_no_encontradas}")
            print(f"📋 Marcas disponibles: {list(MARCAS.keys())}")
        
        if not marcas_validas:
            print("❌ ERROR: No hay marcas válidas para procesar")
            return {}
        
        print(f"✅ Modo: PROCESAR MARCAS ESPECÍFICAS: {list(marcas_validas.keys())}")
        return marcas_validas
    
    elif isinstance(MARCAS_A_PROCESAR, str):
        # Una sola marca como string
        if MARCAS_A_PROCESAR in MARCAS:
            print(f"✅ Modo: PROCESAR UNA MARCA: {MARCAS_A_PROCESAR}")
            return {MARCAS_A_PROCESAR: MARCAS[MARCAS_A_PROCESAR]}
        else:
            print(f"❌ ERROR: La marca '{MARCAS_A_PROCESAR}' no existe")
            print(f"📋 Marcas disponibles: {list(MARCAS.keys())}")
            return {}
    
    else:
        print("❌ ERROR: Configuración MARCAS_A_PROCESAR inválida")
        print("   Usar: 'ALL', 'MARCA', o ['MARCA1', 'MARCA2']")
        return {}

# ══════════════════════════════════════════════════════════════════
# UTILS
# ══════════════════════════════════════════════════════════════════

def extraer_texto_pdf(ruta_pdf):
    texto = ""
    with pdfplumber.open(ruta_pdf) as pdf:
        for pagina in pdf.pages:
            t = pagina.extract_text()
            if t:
                texto += "\n" + t
    return texto


def euro_to_float(valor):
    return float(valor.replace(".", "").replace(",", "."))


def normalizar_incoterm(texto):
    texto = texto.upper()

    mapa = {
        "EX WORKS": "EXW",
        "EXW": "EXW",
        "FOB": "FOB",
        "CIF": "CIF",
        "DAP": "DAP",
        "DDP": "DDP"
    }

    for k, v in mapa.items():
        if k in texto:
            return v

    return "por_completar"

def pzz_to_float(valor):
    """Convierte formato brasileño (1.621,62) o europeo (2,31) a float.
       También maneja casos raros como 181,.20"""
    if not valor or valor == '':
        return 0.0
    
    valor_str = str(valor).strip()
    
    # Si ya es número, devolver directamente
    if isinstance(valor, (int, float)) and not isinstance(valor, str):
        return float(valor)
    
    # Caso especial: "181,.20" (coma y punto invertidos)
    if ',.' in valor_str:
        valor_str = valor_str.replace(',.', '.')
        return float(valor_str)
    
    # Contar comas y puntos para decidir el formato
    tiene_coma = ',' in valor_str
    tiene_punto = '.' in valor_str
    
    # Caso: "2,31" (coma decimal, sin punto miles)
    if tiene_coma and not tiene_punto:
        return float(valor_str.replace(',', '.'))
    
    # Caso: "2.31" (punto decimal, formato inglés)
    if tiene_punto and not tiene_coma:
        return float(valor_str)
    
    # Caso: "1.621,62" (punto miles, coma decimal)
    if tiene_punto and tiene_coma:
        sin_puntos = valor_str.replace('.', '')
        con_punto_decimal = sin_puntos.replace(',', '.')
        return float(con_punto_decimal)
    
    # Fallback
    try:
        return float(valor_str)
    except ValueError:
        return 0.0


def _es_numero_explicito(texto):
    """
    True si el texto es un número real (incluye 0, y negativos escritos como
    '-24.121' o en notación contable '(4546.45)'); False si es basura como un
    guion suelto, vacío, o texto no numérico.

    Sirve para no confundir un precio/importe explícitamente en 0 (típico de
    facturas de muestras) con una fila basura que solo trae un '-' de relleno
    — varios parsers calculan 0.0 como valor por defecto en ambos casos, y sin
    este chequeo no hay forma de distinguirlos. No toca la detección de
    negativos reales, que se usará más adelante para descuentos.
    """
    if texto is None:
        return False
    limpio = str(texto).strip()
    if not limpio:
        return False
    if limpio.startswith('(') and limpio.endswith(')'):
        limpio = limpio[1:-1].strip()
    elif limpio.startswith('-'):
        limpio = limpio[1:].strip()
    limpio = limpio.replace(',', '').replace('$', '').strip()
    return bool(limpio) and limpio.replace('.', '', 1).isdigit()


def _normalizar_numero_moneda(texto):
    """Convierte un número con separador de miles/decimales ambiguo a float.
    Necesario porque algunos proveedores (ej. CISNE_NEGRO) mezclan formato
    US ("$0.53", "$3,180.00") y formato europeo ("$0,53", "$3.180,00")
    incluso entre facturas de la MISMA plantilla — tratar todo como un solo
    formato corrompe el número (ej. "$0.53" tratado como europeo da 53.0).
    Detecta el separador decimal por cuál aparece último en el string."""
    limpio = str(texto).replace('$', '').strip()
    if ',' in limpio and '.' in limpio:
        if limpio.rfind(',') > limpio.rfind('.'):
            limpio = limpio.replace('.', '').replace(',', '.')
        else:
            limpio = limpio.replace(',', '')
    elif ',' in limpio:
        limpio = limpio.replace(',', '.')
    return limpio


def _extraer_total_por_ultimo_monto_dolar(texto):
    """Heurística para el total declarado en la factura (para comparar
    contra la suma de nuestras líneas en la app): el total general suele
    ser el último monto con '$' del documento — los renglones de ítems no
    lo llevan, solo el resumen final (Subtotal/Other Charges/TOTAL) sí, y
    TOTAL es el último de esos tres."""
    montos = re.findall(r'\$([\d.,]+)', texto)
    if not montos:
        return None
    try:
        return float(_normalizar_numero_moneda(montos[-1]))
    except ValueError:
        return None


# El monto SIEMPRE tiene que terminar en exactamente 2 decimales (".XX" o
# ",XX") — es lo que distingue un monto real ("13,834.15") de basura que
# "TOTAL ... <número>" agarra por error (números de página, pesos, %, IDs:
# "1.0", "3", "96032930.0"). Sin este filtro, probado contra facturas reales
# de LANEIGE/ANASTASIA/COSRX/KOCOSTAR/TONY_MOLY/BETER/PETRIZZIO/PIXI/
# SLICK_HAIR, la heurística devolvía un número — pero el equivocado, lo que
# es peor que no devolver nada (dispara una alerta roja de "no cuadra" falsa).
_MONTO_2_DECIMALES = r'(\d[\d.,]*[.,]\d{2})\b'

# Patrones específicos (etiqueta inequívoca de "esto es EL total") — se
# prueban primero, con la primera aparición.
_PATRONES_TOTAL_ESPECIFICOS = [
    rf'GRAND\s*TOTAL[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}',
    rf'TOTAL\s*AMOUNT(?:\s*DUE)?[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}',
    rf'TOTAL\s*DUE[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}',
    rf'INVOICE\s*TOTAL[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}',
    rf'IMPORTE\s*TOTAL[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}',
    rf'TOTAL\s*A\s*PAGAR[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}',
    rf'TOTAL\s*(?:USD|EUR|PEN)[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}',
]

# Fallback genérico: cualquier "TOTAL: monto" que no sea "Sub Total"/"Tax
# Total"/"Freight Total"/etc. — un desglose de Subtotal/Tax/Shipping/Total
# siempre termina con el total real al final, así que se toma la ÚLTIMA
# aparición (con re.search, la primera "Tax Total 0.00" le ganaba a la
# "Total 6,020.00" real que venía después — visto en SLICK_HAIR real).
_PATRON_TOTAL_FALLBACK = rf'(?<![A-Za-z])(?:SUB\s*|TAX\s*|FREIGHT\s*|SHIPPING\s*)?TOTAL[^\n\d]{{0,20}}\$?\s*{_MONTO_2_DECIMALES}'


def _extraer_total_generico(texto):
    """Heurística best-effort para el total que la factura declara, para
    los parsers que todavía no tienen un patrón a medida verificado contra
    facturas reales — prueba patrones específicos ("GRAND TOTAL", "TOTAL
    DUE"...) primero, y si ninguno matchea cae a buscar la ÚLTIMA aparición
    de "TOTAL: monto" que no sea Sub/Tax/Freight/Shipping Total. Exige que
    el monto tenga 2 decimales (ver _MONTO_2_DECIMALES) — sin eso, "TOTAL
    ... <número>" agarra basura (números de página, pesos, IDs). Puede
    seguir fallando en plantillas raras devolviendo None (no confundir con
    las funciones a medida de THEBALM/CISNE_NEGRO/HELLO_SUNDAY, que sí
    están verificadas contra facturas reales)."""
    if not texto:
        return None
    for patron in _PATRONES_TOTAL_ESPECIFICOS:
        m = re.search(patron, texto, re.IGNORECASE)
        if m:
            try:
                return float(_normalizar_numero_moneda(m.group(1)))
            except ValueError:
                continue

    matches = list(re.finditer(_PATRON_TOTAL_FALLBACK, texto, re.IGNORECASE))
    for m in reversed(matches):
        etiqueta = m.group(0)
        if re.match(r'^(SUB|TAX|FREIGHT|SHIPPING)', etiqueta, re.IGNORECASE):
            continue
        try:
            return float(_normalizar_numero_moneda(m.group(1)))
        except ValueError:
            continue
    return None


def _extraer_total_petrizzio(texto):
    """PETRIZZIO trae DOS líneas de total: "Total CIF $USD 19.615,20" (la
    suma de las líneas de mercadería, la que coincide con nuestra suma) y
    "Total Cláusula $USD 20.492,21" (un ajuste aparte, más grande) — el
    fallback genérico agarraba la última y era la equivocada. Acá se busca
    puntual "Total <incoterm> $USD <monto>"."""
    m = re.search(r'Total\s+(?:CIF|FOB|EXW|CFR|CPT)\s*\$?\s*USD\s*([\d.,]+)', texto, re.IGNORECASE)
    if m:
        try:
            return float(_normalizar_numero_moneda(m.group(1)))
        except ValueError:
            pass
    return _extraer_total_generico(texto)


def limpiar_precio(texto):
    t = texto
    t = t.replace('L', '1').replace('O', '0').replace('J', '1')
    t = t.replace("'", '').replace('\\', '')
    t = t.replace(',', '.')
    parts = t.split('.')
    if len(parts) >= 2:
        t = parts[0] + '.' + ''.join(parts[1:])
    t = t.strip('.')
    try:
        val = float(t)
        if 0.5 <= val <= 20.0:
            return round(val, 2)
    except:
        pass
    return None


def extraer_precios_de_pagina(page):
    words = page.extract_words()
    precio_tokens = [w for w in words if 440 <= w['x0'] <= 470]
    
    tokens_por_fila = {}
    for w in precio_tokens:
        top_key = round(w['top'] / 3) * 3
        if top_key not in tokens_por_fila:
            tokens_por_fila[top_key] = []
        tokens_por_fila[top_key].append((w['x0'], w['text']))
    
    tops_sorted = sorted(tokens_por_fila.keys())
    filas_fusionadas = {}
    skip = set()
    
    for i, top in enumerate(tops_sorted):
        if top in skip:
            continue
        tokens = tokens_por_fila[top][:]
        if i + 1 < len(tops_sorted):
            next_top = tops_sorted[i + 1]
            if next_top - top <= 4:
                tokens += tokens_por_fila[next_top]
                skip.add(next_top)
        tokens.sort(key=lambda x: x[0])
        filas_fusionadas[top] = tokens
    
    precios = []
    for top in sorted(filas_fusionadas.keys()):
        tokens = filas_fusionadas[top]
        raw = ''.join(t[1] for t in tokens)
        valor = limpiar_precio(raw)
        if valor is not None:
            precios.append(valor)
    return precios

# ══════════════════════════════════════════════════════════════════
# AJUSTES (descuentos / créditos / cargos) — integrado a la app
# ══════════════════════════════════════════════════════════════════
# Se detecta al mismo tiempo que se revisa la factura en la app, con
# categoría (DESCUENTO / CREDITO / CARGO — un crédito es saldo a favor, un
# cargo es un cobro adicional como estantería/acrílicos, ambos tan comunes
# como el descuento clásico) y se guarda en la pestaña "ajustes" del MISMO
# spreadsheet que "data", para poder cruzarlo por marca/po/invoice en
# reportería.

def detectar_ajustes(pdf_file, marca, df_excel=None):
    """
    Busca líneas de ajuste (descuento, crédito, cargo adicional) en una
    factura — montos que no son parte de las líneas de producto pero sí
    afectan el total a pagar. Devuelve una lista de (descripcion, monto,
    categoria). La detección automática es solo una sugerencia: siempre se
    verifica en la app antes de guardarse, y de ahí también se puede agregar
    a mano cualquier ajuste que el patrón automático no capture.
    """
    ajustes = []

    if marca == "THEBALM":
        texto = extraer_texto_pdf(pdf_file)
        for linea in texto.split('\n'):
            m = re.search(r'(Discount[^\n]*?)\s+(-?\$?[\d,]+\.\d{2})\s*$', linea, re.IGNORECASE)
            if m:
                monto = float(m.group(2).replace('$', '').replace(',', ''))
                if monto != 0:
                    ajustes.append((m.group(1).strip(), monto, "DESCUENTO"))

    elif marca == "BEAUTY_CREATIONS":
        texto = extraer_texto_pdf(pdf_file)
        match = re.search(r'(discount)\s+([-\d,]+\.\d{2})', texto, re.IGNORECASE)
        if match:
            monto = float(match.group(2).replace(',', ''))
            if monto != 0:
                ajustes.append((match.group(1).strip(), monto, "DESCUENTO"))

    elif marca == "PETRIZZIO":
        texto = extraer_texto_pdf(pdf_file)
        match = re.search(r'(DESCUENTO).*?([-\d]+[.,]\d{2})', texto, re.IGNORECASE | re.DOTALL)
        if match:
            monto = float(match.group(2).replace('.', '').replace(',', '.'))
            if monto != 0:
                ajustes.append((match.group(1).strip(), monto, "DESCUENTO"))

    elif marca == "PIXI":
        texto = extraer_texto_pdf(pdf_file)
        match = re.search(r'(Testers\s+Allowance).*?\([\$]*([\d,]+\.\d{2})\)', texto, re.IGNORECASE | re.DOTALL)
        if match:
            monto = -float(match.group(2).replace(',', ''))
            if monto != 0:
                ajustes.append((match.group(1).strip(), monto, "DESCUENTO"))

    elif marca == "REVOX_B77" and df_excel is not None:
        for i in range(len(df_excel)):
            for j in range(len(df_excel.columns)):
                celda = str(df_excel.iloc[i, j]) if pd.notna(df_excel.iloc[i, j]) else ""
                if 'Invoice Discount Amount' in celda:
                    if j + 1 < len(df_excel.columns):
                        valor = df_excel.iloc[i, j + 1]
                        if pd.notna(valor) and valor != 0:
                            ajustes.append(("Invoice Discount Amount", float(valor), "DESCUENTO"))
                    break

    return ajustes


def conectar_hoja_ajustes():
    """Conecta a la pestaña 'ajustes' del MISMO spreadsheet que 'data'
    (GOOGLE_SHEET_ID) — la crea si no existe. Se llama 'ajustes' (no
    'descuentos') porque cubre 3 categorías: DESCUENTO, CREDITO y CARGO."""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        if not CREDENTIALS_FILE.exists():
            print(f"⚠ Archivo de credenciales no encontrado en: {CREDENTIALS_FILE}")
            return None

        creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=scopes)
        client = gspread.authorize(creds)
        spreadsheet = client.open_by_key(GOOGLE_SHEET_ID)
        try:
            sheet = spreadsheet.worksheet("ajustes")
        except gspread.WorksheetNotFound:
            sheet = spreadsheet.add_worksheet(title="ajustes", rows=1000, cols=13)
            print("📝 Pestaña 'ajustes' creada en el spreadsheet principal")

        if not sheet.row_values(1):
            encabezados = [
                "id", "marca", "proveedor", "po", "invoice", "invoice_date", "periodo",
                "categoria", "descripcion", "monto", "origen", "nombre_archivo", "fecha_carga"
            ]
            sheet.insert_row(encabezados, 1)
            print("📝 Encabezados creados en pestaña 'ajustes'")

        return sheet
    except Exception as e:
        print(f"⚠ Error conectando a pestaña 'descuentos': {e}")
        return None


def obtener_ids_existentes_ajustes(sheet):
    if not sheet:
        return set()
    try:
        col_a = sheet.col_values(1)
        return set(col_a[1:])
    except:
        return set()


def insertar_ajustes_en_sheet(sheet, registros, ids_existentes):
    """Inserta ajustes nuevos en la pestaña 'descuentos' (idempotente por id)."""
    if not sheet or not registros:
        return 0, 0

    orden_columnas = [
        "id", "marca", "proveedor", "po", "invoice", "invoice_date", "periodo",
        "categoria", "descripcion", "monto", "origen", "nombre_archivo", "fecha_carga"
    ]

    nuevos = 0
    duplicados = 0
    filas = []
    for registro in registros:
        registro_id = registro.get("id")
        if not registro_id:
            continue
        if registro_id in ids_existentes:
            duplicados += 1
            continue
        filas.append([registro.get(col, "") for col in orden_columnas])
        ids_existentes.add(registro_id)
        nuevos += 1

    if filas:
        sheet.append_rows(filas, value_input_option="USER_ENTERED")

    return nuevos, duplicados


def formatear_tiempo(segundos):
    """Convierte segundos a formato mm:ss o ss.ms"""
    if segundos < 60:
        return f"{segundos:.2f}s"
    else:
        minutos = int(segundos // 60)
        segs = segundos % 60
        return f"{minutos}m {segs:.2f}s"

# ══════════════════════════════════════════════════════════════════
# GOOGLE SHEETS - CONEXIÓN Y UTILS
# ══════════════════════════════════════════════════════════════════

def conectar_google_sheets():
    """Conecta a Google Sheets usando el archivo de credenciales"""
    try:
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"
        ]
        
        if not CREDENTIALS_FILE.exists():
            print(f"⚠ Archivo de credenciales no encontrado en: {CREDENTIALS_FILE}")
            print("   La ingesta a Google Sheets no estará disponible")
            return None
        
        creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=scopes)
        client = gspread.authorize(creds)
        sheet = client.open_by_key(GOOGLE_SHEET_ID).worksheet("data")
        
        # Verificar/crear encabezados
        if not sheet.row_values(1):
            encabezados = [
                "id", "marca", "proveedor", "invoice", "invoice_date", "due_date",
                "po", "incoterm", "periodo", "item", "codigo_producto", "tipo_codigo",
                "descripcion", "cantidad", "costo_unitario", "moneda", "importe",
                "sample", "nombre_archivo", "due_days"
            ]
            sheet.insert_row(encabezados, 1)
            print("📝 Encabezados creados en Google Sheets")
        
        return sheet
    except Exception as e:
        print(f"⚠ Error conectando a Google Sheets: {e}")
        return None

def obtener_ids_existentes(sheet):
    """Obtiene todos los IDs existentes para evitar duplicados"""
    if not sheet:
        return set()
    try:
        col_a = sheet.col_values(1)
        return set(col_a[1:])  # Saltar encabezado
    except:
        return set()

def insertar_en_sheet(sheet, registros, ids_existentes):
    """Inserta registros nuevos en Google Sheets (idempotente)"""
    if not sheet or not registros:
        return 0, 0
    
    nuevos = 0
    duplicados = 0
    
    orden_columnas = [
        "id", "marca", "proveedor", "invoice", "invoice_date", "due_date",
        "po", "incoterm", "periodo", "item", "codigo_producto", "tipo_codigo",
        "descripcion", "cantidad", "costo_unitario", "moneda", "importe",
        "sample", "nombre_archivo", "due_days"
    ]
    
    for registro in registros:
        registro_id = registro.get("id")
        if not registro_id:
            continue
        
        if registro_id in ids_existentes:
            duplicados += 1
        else:
            fila = [registro.get(col, "") for col in orden_columnas]
            sheet.append_row(fila, value_input_option="USER_ENTERED")
            ids_existentes.add(registro_id)
            nuevos += 1
    
    return nuevos, duplicados

# ══════════════════════════════════════════════════════════════════
# FUNCIÓN UNIVERSAL - DETECCIÓN DE SAMPLE
# ══════════════════════════════════════════════════════════════════

PATRONES_SAMPLE = [
    "SAMPLE",
    "MUESTRA",
    "TEST",
    "WITHOUT COMMERCIAL VALUE",
    "SIN VALOR COMERCIAL",
    "NOT FOR RESALE",
    "NOT FOR SALE",
    "FREE SAMPLE",
    "SAMPLES",
    "MUESTRAS",
    "SHOWROOM",
    "EXHIBITION",
    "NO COMMERCIAL VALUE",
    "VALUE FOR CUSTOMS PURPOSES ONLY",
    "DO NOT PAY INVOICE",
    "FREE OF CHARGE",
    "NO CHARGE",
]

def detectar_sample(texto):
    """
    Detecta si un PDF es sample/muestra.
    Retorna "Y" si es sample, "N" si no.
    """
    texto_upper = texto.upper()
    
    # Patrones fuertes (indican sample real casi seguro)
    patrones_fuertes = [
        "SAMPLES - NOT FOR RE-SALE",
        "SAMPLES -NOT FOR RE-SALE",
        "SAMPLES NOT FOR RESALE",
        "FREE SAMPLE",
        "NO COMMERCIAL VALUE",
        "VALUE FOR CUSTOMS PURPOSES ONLY",
        "DO NOT PAY INVOICE",
        "FREE OF CHARGE",
        "NO CHARGE",
        "MUESTRAS SIN VALOR COMERCIAL",
        "SIN VALOR COMERCIAL",
        "WITHOUT COMMERCIAL VALUE",
        "GRATIS",  # Terms GRATIS aparece en samples
    ]
    
    for patron in patrones_fuertes:
        if patron in texto_upper:
            return "Y"
    
    # Patrones débiles (requieren contexto adicional)
    patrones_debiles = [
        "SAMPLE",
        "MUESTRA",
        "SHOWROOM",
        "EXHIBITION",
    ]
    
    for patron in patrones_debiles:
        if patron in texto_upper:
            # Para "SAMPLE": verificar que no sea falso positivo
            if patron == "SAMPLE":
                # Si ya detectamos patrones fuertes arriba, no llegamos aquí
                # Si solo aparece "SAMPLE" sin contexto, podría ser falso positivo
                if "NOT FOR" not in texto_upper and "GRATIS" not in texto_upper and "WITHOUT" not in texto_upper:
                    continue
            # Para "TEST": verificar que no sea "TESTER"
            if patron == "TEST":
                if "TESTER" in texto_upper:
                    continue
            
            return "Y"
    
    return "N"

# ══════════════════════════════════════════════════════════════════
# VALIDACIÓN DE FACTURAS
# ══════════════════════════════════════════════════════════════════

# Configuración de patrones para detectar documentos NO válidos
# Puedes agregar o quitar patrones según necesites
PATRONES_NO_FACTURA = [
    "SUNAT",
    "DUA",
    "LEVANTE",
    "CONSULTA DE AUTORIZACIÓN",
    "Orden de Compra",
    "Proforma Invoice",
    "MODALIDAD DE DESPACHO ADUANERO",
    "NÚMERO DE DECLARACIÓN",
    "FECHA DE NUMERACIÓN",
    "RUC-",
    "COMITENTE:",
    "MANIFIESTO DE CARGA",
    "DECLARACIÓN ADUANERA",
    "LEVANTE ADUANERO",
    # Puedes agregar más patrones aquí
]

# Configuración de patrones que SÍ indican una factura válida (opcional pero recomendado)
PATRONES_SI_FACTURA = [
    "INVOICE",
    "FACTURA",
    "ORDER NUMBER",
    "PURCHASE ORDER",
    "BILL TO",
    "SHIP TO",
    "TOTAL",
    "SUBTOTAL",
    "ITEM",
    "DESCRIPTION",
    "QUANTITY",
    "PRICE",
    "AMOUNT"
]

def es_factura_valida(pdf_path, verbose=False):
    """
    Verifica si el PDF es una factura de compra válida.
    """
    try:
        texto = extraer_texto_pdf(pdf_path)
        texto_upper = texto.upper()
        
        # 0. Verificar si es SOLO Packing List (primera línea)
        primera_linea = texto.strip().split('\n')[0].upper() if texto.strip() else ""
        if "PACKING LIST" in primera_linea:
            if verbose:
                print(f"   🔍 Detectado PACKING LIST como primera línea")
            return False, "solo_packing_list"
        
        # 1. Verificar patrones NO factura (invalida inmediatamente)
        # Usar \b para buscar palabra completa, no substring
        for patron in PATRONES_NO_FACTURA:
            # Buscar como palabra completa (con límites de palabra)
            if re.search(r'\b' + re.escape(patron) + r'\b', texto_upper):
                if verbose:
                    print(f"   🔍 Detectado patrón NO válido: '{patron}'")
                return False, f"contiene_{patron.lower().replace(' ', '_')}"
        
        # 2. Verificar que tenga al menos un patrón de factura válida
        tiene_patron_valido = False
        for patron in PATRONES_SI_FACTURA:
            if patron in texto_upper:
                tiene_patron_valido = True
                break
        
        # 3. Verificar que tenga un mínimo de contenido
        if len(texto.strip()) < 100:
            return False, "texto_insuficiente"
        
        if not tiene_patron_valido:
            if verbose:
                print(f"   ⚠ Advertencia: No se encontraron patrones típicos de factura")
        
        return True, None
        
    except Exception as e:
        print(f"   ⚠ Error validando {pdf_path.name}: {e}")
        return False, "error_lectura"
# ══════════════════════════════════════════════════════════════════
# RENOMBRE
# ══════════════════════════════════════════════════════════════════

def generar_nombre(pdf, marca, proveedor):
    # REVOX_B77 en Excel (formato antiguo): manejar primero (NO usar extraer_texto_pdf).
    # REVOX_B77 en PDF (formato vigente) sigue de largo hasta la sección genérica de abajo.
    if marca == "REVOX_B77" and pdf.suffix.lower() == ".xlsx":
        try:
            import time
            time.sleep(0.5)
            
            df = pd.read_excel(pdf, header=None)
            nombre_original = pdf.name
            
            # ========== EXTRAER PO DEL NOMBRE ORIGINAL ==========
            po = None
            po_match = re.search(r'^(IMP\d+-\d{4})_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
            else:
                # Fallback: buscar en el contenido
                for i in range(min(30, len(df))):
                    row = df.iloc[i]
                    for j in range(len(row)):
                        val = str(row[j]) if pd.notna(row[j]) else ""
                        match = re.search(r'(IMP\d+-\d{4})', val)
                        if match:
                            po = match.group(1)
                            break
                    if po:
                        break
            
            if not po:
                po = "IMP000-0000"
            
            # ========== EXTRAER INVOICE ==========
            invoice = None
            for i in range(min(20, len(df))):
                row = df.iloc[i]
                for j in range(len(row)):
                    val = str(row[j]) if pd.notna(row[j]) else ""
                    # Buscar "No." seguido de número
                    if 'No.' in val:
                        for k in range(j, min(j+5, len(row))):
                            if pd.notna(row[k]):
                                num_str = str(row[k]).strip()
                                if re.match(r'^\d{7,10}$', num_str):
                                    invoice = num_str
                                    break
                    # Buscar número de 7-10 dígitos directamente
                    nums = re.findall(r'\b(\d{7,10})\b', val)
                    if nums and len(nums[0]) >= 7 and len(nums[0]) <= 10:
                        invoice = nums[0]
                        break
                if invoice:
                    break
            
            if not invoice:
                # Intentar del nombre
                name_parts = nombre_original.split('_')
                for part in name_parts:
                    if re.match(r'^\d{7,10}$', part):
                        invoice = part
                        break
                if not invoice:
                    invoice = "0000000"
            
            # ========== EXTRAER FECHA Y PERIODO ==========
            fecha_dt = None
            for i in range(min(25, len(df))):
                row = df.iloc[i]
                for j in range(len(row)):
                    val = str(row[j]) if pd.notna(row[j]) else ""
                    # Buscar YYYY-MM-DD
                    match = re.search(r'(\d{4}-\d{2}-\d{2})', val)
                    if match:
                        try:
                            fecha_dt = datetime.strptime(match.group(1), "%Y-%m-%d")
                            break
                        except:
                            pass
                    # Buscar DD.MM.YYYY
                    match = re.search(r'(\d{2}\.\d{2}\.\d{4})', val)
                    if match:
                        try:
                            fecha_dt = datetime.strptime(match.group(1), "%d.%m.%Y")
                            break
                        except:
                            pass
                    # Buscar DD/MM/YYYY
                    match = re.search(r'(\d{2}/\d{2}/\d{4})', val)
                    if match:
                        try:
                            fecha_dt = datetime.strptime(match.group(1), "%d/%m/%Y")
                            break
                        except:
                            pass
                if fecha_dt:
                    break
            
            if fecha_dt:
                periodo = fecha_dt.strftime("%Y%m")
            else:
                # Intentar del nombre
                name_parts = nombre_original.split('_')
                for part in name_parts:
                    if re.match(r'^\d{6}$', part):
                        periodo = part
                        break
                else:
                    periodo = "000000"
            
            # ========== GENERAR NOMBRE FINAL ==========
            # Formato: {po}_{marca}_{invoice}_{periodo}.xlsx
            nombre_final = f"{po}_{marca}_{invoice}_{periodo}.xlsx"
            print(f"   📝 Nombre generado: {nombre_final}")
            return nombre_final

        except Exception as e:
            print(f"   ⚠ Error generando nombre para {pdf.name}: {e}")
            return None

    # Para el resto de marcas (PDF) - TODO ESTO SIGUE IGUAL
    try:
        texto = extraer_texto_pdf(pdf)

        if marca == "LANEIGE":
            # Extraer invoice (10 dígitos)
            invoice_match = re.search(r'Invoice No\. and date\s*\n\s*[\w,\s-]+\s+(\d{7,12})', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000000"
            
            # Extraer fecha (formato MMM.DD,YYYY)
            fecha_match = re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.(\d{1,2}),(\d{4})', texto, re.IGNORECASE)
            if fecha_match:
                meses = {'JAN':'01','FEB':'02','MAR':'03','APR':'04','MAY':'05','JUN':'06',
                        'JUL':'07','AUG':'08','SEP':'09','OCT':'10','NOV':'11','DEC':'12'}
                mes = meses[fecha_match.group(1).upper()[:3]]
                dia = fecha_match.group(2)
                anio = fecha_match.group(3)
                periodo = f"{anio}{mes}"
            else:
                periodo = "000000"
            
            # Extraer PO del NOMBRE ORIGINAL del archivo
            po = None
            nombre_original = pdf.name
            # Patrón: IMP###-YYYY o IMP###-###-YYYY (termina en YYYY seguido de _)
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
            
            # Nuevo formato: {po}_LANEIGE_{invoice}_{periodo}.pdf
            if po:
                return f"{po}_{marca}_{invoice}_{periodo}.pdf"
            else:
                return f"{marca}_{invoice}_{periodo}.pdf"
        
        elif marca == "SLICK_HAIR":
            texto = extraer_texto_pdf(pdf)
            
            # Invoice: soporta SI-xxxxx o SO-xxxxx
            invoice_match = re.search(r'(SI-\d+|SO-\d+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"
            
            # Fecha: soporta 28Apr2025 o 14/08/2024
            fecha_match = re.search(r'(\d{1,2}[A-Za-z]+\d{4})', texto)
            if fecha_match:
                fecha_dt = datetime.strptime(fecha_match.group(1), "%d%b%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                fecha_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', texto)
                if fecha_match:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%d/%m/%Y")
                    periodo = fecha_dt.strftime("%Y%m")
                else:
                    periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "REVOX_B77":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'Invoice No\.:\s*(\d+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"

            fecha_match = re.search(r'Document Date:\s*(\d{2}/\d{2}/\d{4})', texto)
            if fecha_match:
                fecha_dt = datetime.strptime(fecha_match.group(1), "%d/%m/%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "7_DAYS":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'INVOICE\s*(?:№|Nr\.)?\s*(\d+)\s+(\d{2}[./]\d{2}[./]\d{4})', texto)
            if invoice_match:
                invoice = invoice_match.group(1)
                fecha_dt = datetime.strptime(invoice_match.group(2).replace('/', '.'), "%d.%m.%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                invoice = "0000000"
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "FOAMOUS":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'INVOICE\s*(?:NO\.|N°)\s*(FAC\|[\d|]+)', texto)
            if invoice_match:
                # "|" no es válido en nombres de archivo de Windows.
                invoice = re.sub(r'[^A-Za-z0-9_-]+', '_', invoice_match.group(1))
            else:
                invoice = "0000000"

            fecha_match = re.search(r'^DATE\s+(\d{2}/\d{2}/\d{4})', texto, re.MULTILINE)
            if fecha_match:
                fecha_dt = datetime.strptime(fecha_match.group(1), "%d/%m/%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "COZI_LIFE":
            texto = extraer_texto_pdf(pdf)
            texto = re.sub(r'(\d)\s+([.,]\d)', r'\1\2', texto)

            invoice_match = re.search(r'IV No\.\s*:\s*(\S+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"

            fecha_match = re.search(r'Date\s*:\s*([A-Za-z]{3,9})\.?\s*(\d{1,2}),\s*(\d{4})', texto)
            if fecha_match:
                mes_str, dia, anio = fecha_match.groups()
                try:
                    fecha_dt = datetime.strptime(f"{mes_str[:3]} {dia} {anio}", "%b %d %Y")
                    periodo = fecha_dt.strftime("%Y%m")
                except ValueError:
                    periodo = "000000"
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "LATAM_CHINA":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'POR LA FACTURA NO\.\s*(\S+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"

            meses_es = {
                'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4, 'MAYO': 5, 'JUNIO': 6,
                'JULIO': 7, 'AGOSTO': 8, 'SETIEMBRE': 9, 'SEPTIEMBRE': 9, 'OCTUBRE': 10,
                'NOVIEMBRE': 11, 'DICIEMBRE': 12,
            }
            fecha_match = re.search(r'FECHA:\s*(\d{1,2})\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{4})', texto)
            if fecha_match:
                dia, mes_nombre, anio = fecha_match.groups()
                mes = meses_es.get(mes_nombre.strip().upper())
                periodo = f"{anio}{mes:02d}" if mes else "000000"
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca in ("FUJIAN_OUKANG", "BORLA"):
            texto = extraer_texto_pdf(pdf)

            meses_en = {
                'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                'JUL': 7, 'AUG': 8, 'SEP': 9, 'SPE': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
            }
            fecha_match = re.search(r'Date:\s*(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{2})', texto, re.IGNORECASE)
            if fecha_match:
                dia, mes_str, anio2 = fecha_match.groups()
                mes = meses_en.get(mes_str.strip().upper())
                if mes:
                    fecha_dt = datetime(2000 + int(anio2), mes, int(dia))
                    periodo = fecha_dt.strftime("%Y%m")
                    invoice_match = re.search(r'Invoice No:\s*([A-Za-z0-9\s-]+?)\s+Page', texto)
                    invoice = (
                        invoice_match.group(1).replace(' ', '').strip()
                        if invoice_match else f"PI_{fecha_dt.strftime('%Y%m%d')}"
                    )
                else:
                    periodo = "000000"
                    invoice = "0000000"
            else:
                periodo = "000000"
                invoice = "0000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca in ["TIRTIR", "TOCOBO", "MEDICUBE"]:
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'No\.\s*:\s*([A-Z0-9]+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"
            
            fecha_match = re.search(r'Date\s*:\s*(\d{4}-\d{2}-\d{2})', texto)
            if fecha_match:
                fecha_dt = datetime.strptime(fecha_match.group(1), "%Y-%m-%d")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "OLAPLEX":
            texto = extraer_texto_pdf(pdf)
            
            # Intentar Formato 1: #INV#####
            invoice_match = re.search(r'#INV(\d{6,})', texto)
            if invoice_match:
                invoice = f"INV{invoice_match.group(1)}"
            else:
                # Intentar Formato 2: SO######
                so_match = re.search(r'\b(SO\d{6,})\b', texto)
                if so_match:
                    invoice = so_match.group(1)
                else:
                    invoice = "000000"
            
            # Fecha: primera fecha M/D/YYYY
            periodo = "000000"
            fechas = re.findall(r'(\d{1,2}/\d{1,2}/\d{4})', texto)
            if fechas:
                try:
                    fecha_dt = datetime.strptime(fechas[0], "%m/%d/%Y")
                    periodo = fecha_dt.strftime("%Y%m")
                except:
                    pass
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "THEBALM":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'Invoice\s*#\s*(\S+)', texto)
            if not invoice_match:
                invoice_match = re.search(r'Order\s*#\s*(\S+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"

            fecha_match = re.search(r'(?<!Ship to )Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
            if fecha_match:
                try:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
                    periodo = fecha_dt.strftime("%Y%m")
                except:
                    periodo = "000000"
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "CISNE_NEGRO":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'Invoice No:\s*([^\n]+)', texto)
            invoice = invoice_match.group(1).strip() if invoice_match else "0000000"
            # El invoice trae espacios/guiones raros (ej. "PI-PERGLM240807-7 IMP108"),
            # no sirve tal cual para un nombre de archivo.
            invoice_seguro = re.sub(r'[^A-Za-z0-9_-]+', '_', invoice)

            fecha_match = re.search(r'Date:\s*(\d{4})-\s*([A-Za-z]+)\s+the\s+(\d{1,2})(?:st|nd|rd|th)?', texto)
            if fecha_match:
                try:
                    anio, mes_abr, dia = fecha_match.groups()
                    fecha_dt = datetime.strptime(f"{anio}-{mes_abr[:3]}-{dia}", "%Y-%b-%d")
                    periodo = fecha_dt.strftime("%Y%m")
                except ValueError:
                    periodo = "000000"
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice_seguro}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "HELLO_SUNDAY":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'Invoice\s+(FVR\d+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"

            fecha_match = re.search(r'^\s*(\d{1,2}) de ([A-Za-z]+) de (\d{4})', texto, re.MULTILINE)
            if fecha_match:
                try:
                    dia, mes_ingles, anio = fecha_match.groups()
                    fecha_dt = datetime.strptime(f"{dia} {mes_ingles} {anio}", "%d %B %Y")
                    periodo = fecha_dt.strftime("%Y%m")
                except ValueError:
                    periodo = "000000"
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "EARTH_RHYTHM":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'INVOICE\s+NO\s*:-\s*(\S+)', texto, re.IGNORECASE)
            invoice = invoice_match.group(1) if invoice_match else "0000000"
            # El invoice trae barras (ej. "ER/23-24/EX/0100"), no sirve tal
            # cual para un nombre de archivo.
            invoice_seguro = re.sub(r'[^A-Za-z0-9_-]+', '_', invoice)

            fecha_match = re.search(r'DATE\s*:-\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
            if fecha_match:
                try:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%d/%m/%Y")
                    periodo = fecha_dt.strftime("%Y%m")
                except ValueError:
                    periodo = "000000"
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice_seguro}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "NEW_STUDIO":
            texto = extraer_texto_pdf(pdf)

            invoice_match = re.search(r'Number\s+(IN_\d+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"

            fecha_match = re.search(r'Invoice date\s+(\d{2}/\d{2}/\d{4})', texto)
            if fecha_match:
                try:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
                    periodo = fecha_dt.strftime("%Y%m")
                except ValueError:
                    periodo = "000000"
            else:
                periodo = "000000"

            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "PIXI":
            texto = extraer_texto_pdf(pdf)

            # Usar INV en lugar de SO
            invoice_match = re.search(r'INV(\d+)', texto)
            if invoice_match:
                invoice = f"INV{invoice_match.group(1)}"
            else:
                # Fallback a SO si no hay INV
                so_match = re.search(r'SO(\d+)', texto)
                invoice = f"SO{so_match.group(1)}" if so_match else "0000000"
            
            fecha_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', texto)
            if fecha_match:
                fecha_raw = fecha_match.group(1)
                partes = fecha_raw.split('/')
                if int(partes[0]) > 12:
                    fecha_dt = datetime.strptime(fecha_raw, "%d/%m/%Y")
                else:
                    fecha_dt = datetime.strptime(fecha_raw, "%m/%d/%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final
        
        elif marca == "FLOOKY":
            texto = extraer_texto_pdf(pdf)
            
            # Invoice: C + 6-7 dígitos
            invoice_match = re.search(r'INVOICE\s+NO\.:\s*(C\d{6,7})', texto, re.IGNORECASE)
            invoice = invoice_match.group(1) if invoice_match else "0000000"
            
            # Fecha: DD-MM-YYYY
            fecha_match = re.search(r'INVOICE\s+DATE:\s*(\d{2}-\d{2}-\d{4})', texto, re.IGNORECASE)
            if fecha_match:
                try:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%d-%m-%Y")
                    periodo = fecha_dt.strftime("%Y%m")
                except:
                    try:
                        fecha_dt = datetime.strptime(fecha_match.group(1), "%m-%d-%Y")
                        periodo = fecha_dt.strftime("%Y%m")
                    except:
                        periodo = "000000"
            else:
                periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final
        
        elif marca == "KOCOSTAR":
            invoice_match = re.search(r'PI No\.\s+(\S+)', texto)
            if not invoice_match:
                invoice_match = re.search(r'P/I No\.\s+(\S+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"
            
            fecha_match = re.search(r'Date\s+(\d{2}-\d{2}-\d{4})', texto)
            if fecha_match:
                try:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%d-%m-%Y")
                except:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%m-%d-%Y")
            else:
                fecha_match = re.search(r'Date\s+([A-Za-z]+)-(\d{1,2})-(\d{4})', texto)
                if fecha_match:
                    meses = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
                            'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
                    mes = meses.get(fecha_match.group(1).capitalize()[:3], '01')
                    dia = fecha_match.group(2).zfill(2)
                    anio = fecha_match.group(3)
                    fecha_dt = datetime.strptime(f"{anio}-{mes}-{dia}", "%Y-%m-%d")
                else:
                    fecha_dt = None
            
            periodo = fecha_dt.strftime("%Y%m") if fecha_dt else "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final
                    
        elif marca == "COSRX":
            texto = extraer_texto_pdf(pdf)
            
            # Invoice: buscar GLAMBRANDS_XXXX
            invoice = None
            
            # Formato 1: GLAMBRANDS_08 (IMP154)
            inv_match = re.search(r'(GLAMBRANDS_\d+)\s+\(([^)]+)\)', texto)
            if inv_match:
                parte1 = inv_match.group(1)
                parte2 = inv_match.group(2)
                invoice = f"{parte1}_{parte2}"
            
            # Formato 2: GLAMBRANDS_2356_02 o GLAMBRANDS_1850_05(FOC)
            if not invoice:
                inv_match = re.search(r'(GLAMBRANDS_\d+(?:_\d+)?)(?:\(FOC\))?', texto)
                if inv_match:
                    invoice = inv_match.group(1)
                    if '(FOC)' in texto:
                        invoice = f"{invoice}_FOC"
            
            if not invoice:
                invoice = "0000000"
            
            # Fecha: YYYY-MM-DD
            fecha_match = re.search(r'(\d{4}-\d{2}-\d{2})', texto)
            if fecha_match:
                fecha_dt = datetime.strptime(fecha_match.group(1), "%Y-%m-%d")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                # Intentar MM/DD/YYYY
                fecha_match = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
                if fecha_match:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
                    periodo = fecha_dt.strftime("%Y%m")
                else:
                    periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final
                
        elif marca == "BEAUTY_CREATIONS":
            texto = extraer_texto_pdf(pdf)
            
            # Validar que sea factura real (tiene "Invoice" en alguna parte)
            es_factura = False
            with pdfplumber.open(str(pdf)) as p:
                if p.pages:
                    texto_pag1 = p.pages[0].extract_text()
                    if texto_pag1 and 'Invoice' in texto_pag1:
                        es_factura = True
            
            if not es_factura:
                raise ValueError("No es factura (sin 'Invoice' en página 1)")
            
            # ========== EXTRACCIÓN DE INVOICE (CORREGIDO) ==========
            invoice = None
            
            # Patrón 1: "DateInvoice #4/23/202532139" (fecha + número pegados)
            inv_match = re.search(r'Invoice\s*#?\s*[\d/]+?(\d{5,})', texto)
            if inv_match:
                invoice = inv_match.group(1).zfill(7)
            
            # Patrón 2: "#32139" (número solo después de #)
            if not invoice:
                inv_match = re.search(r'#\s*(\d{5,})', texto)
                if inv_match:
                    invoice = inv_match.group(1).zfill(7)
            
            # Patrón 3: Buscar en tablas del PDF
            if not invoice:
                with pdfplumber.open(str(pdf)) as p:
                    if p.pages:
                        tablas = p.pages[0].extract_tables()
                        for tabla in tablas:
                            if tabla:
                                for fila in tabla:
                                    for celda in fila:
                                        if celda and isinstance(celda, str):
                                            nums = re.findall(r'\b(\d{5,})\b', celda)
                                            for n in nums:
                                                if n not in ['90670', '20601266416', '15012', '15036', '90210', '90660']:
                                                    invoice = n.zfill(7)
                                                    break
                                        if invoice:
                                            break
                                if invoice:
                                    break
                            if invoice:
                                break
            
            # ========== EXTRACCIÓN DE FECHA (CORREGIDO) ==========
            fecha = None
            
            # Buscar todas las fechas en formato MM/DD/YYYY
            fechas = re.findall(r'\b(\d{1,2}/\d{1,2}/\d{4})\b', texto)
            
            if fechas:
                # Filtrar fechas que NO sean "Due Date"
                for f in fechas:
                    idx = texto.find(f)
                    contexto = texto[max(0, idx-20):idx].upper()
                    if 'DUE' not in contexto:
                        fecha = f
                        break
                
                # Si todas son "Due Date", usar la primera
                if not fecha and fechas:
                    fecha = fechas[0]
            
            if not invoice or not fecha:
                raise ValueError("No se pudo extraer invoice o fecha")
            
            # Normalizar fecha a MM/DD/YYYY para el cálculo del periodo
            partes = fecha.split('/')
            if len(partes) == 3:
                mes, dia, anio = partes
                periodo = f"{anio}{mes.zfill(2)}"
            else:
                periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        # En la función generar_nombre(), sección ANASTASIA_BEVERLY_HILLS:
        elif marca == "ANASTASIA_BEVERLY_HILLS":
            # Validar que no sea Samples - AHORA SOLO MARCA, NO RECHAZA
            es_samples = bool(re.search(r'Samples.*Not\s+for\s+re-sale', texto, re.IGNORECASE))
            
            invoice_match = re.search(r'Invoice\s*#\s*(\d+)', texto)
            invoice = invoice_match.group(1) if invoice_match else "0000000"
            
            fecha_match = re.search(r'Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
            if fecha_match:
                fecha_raw = fecha_match.group(1)
                periodo = datetime.strptime(fecha_raw, "%m/%d/%Y").strftime("%Y%m")
            else:
                periodo = "000000"
            
            # Si es sample, NO levantar error, solo continuar
            if es_samples:
                print(f"   🔬 Detectado SAMPLE: {pdf.name}")
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "BETER":
            texto = extraer_texto_pdf(pdf)
            
            # Invoice: soporta ambos formatos
            invoice = None
            
            # Formato normal: "Invoice nº: 30013436"
            inv_match = re.search(r"Invoice\s*nº:\s*(\d+)", texto, re.IGNORECASE)
            if inv_match:
                invoice = inv_match.group(1)
            
            # Formato FOC: "INVOICE 1312343"
            if not invoice:
                inv_match = re.search(r'INVOICE\s+(\d+)', texto, re.IGNORECASE)
                if inv_match:
                    invoice = inv_match.group(1)
            
            invoice = invoice if invoice else "0000000"
            
            # Fecha: soporta ambos formatos
            fecha = None
            fecha_match = re.search(r"Date:\s*(\d{2}/\d{2}/\d{4})", texto)
            if fecha_match:
                fecha = fecha_match.group(1)
            else:
                fecha_match = re.search(r'(\d{2}/\d{2}/\d{4})', texto)
                if fecha_match:
                    fecha = fecha_match.group(1)
            
            periodo = datetime.strptime(fecha, "%d/%m/%Y").strftime("%Y%m") if fecha else "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "BOLDIFY":
            texto = extraer_texto_pdf(pdf)
            
            # Formato nuevo: Invoice no.: CI0409GL
            invoice_match = re.search(r'Invoice\s+no\.:\s*(\S+)', texto, re.IGNORECASE)
            if invoice_match:
                invoice = invoice_match.group(1)
            else:
                # Formato original: Bill to...Invoice XXXXX
                invoice_match = re.search(r'Bill to.*?Invoice\s+([A-Z0-9]+(?:-[A-Z]+)?)', texto, re.IGNORECASE | re.DOTALL)
                invoice = invoice_match.group(1) if invoice_match else "0000000"
            
            # Formato nuevo: Invoice date: 04/09/2026
            fecha_match = re.search(r'Invoice\s+date:\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
            if fecha_match:
                fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                # Formato original: Date Mon DD, YYYY
                fecha_match = re.search(r'Date\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})', texto, re.IGNORECASE)
                if fecha_match:
                    fecha_dt = datetime.strptime(fecha_match.group(1), "%b %d, %Y")
                    periodo = fecha_dt.strftime("%Y%m")
                else:
                    periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

# En la función generar_nombre(), sección MARIO_BADESCU (aproximadamente línea 1030)

        elif marca == "MARIO_BADESCU":
            # Buscar Invoice # o Invoice# - AHORA SOPORTA SALTO DE LÍNEA
            # Patrón 1: "Invoice #" en una línea y el número en la siguiente
            invoice = None
            
            # Buscar patrón con posible salto de línea (usando DOTALL)
            invoice_match = re.search(r"Invoice\s+#?\s*\n?\s*(\d{6})", texto, re.IGNORECASE | re.DOTALL)
            if invoice_match:
                invoice = invoice_match.group(1)
            else:
                # Fallback: cualquier número de 6 dígitos que no sea 1150 (la dirección)
                todos_los_numeros = re.findall(r"\b(\d{6})\b", texto)
                # Filtrar para excluir 1150 y números de dirección
                invoice = next((n for n in todos_los_numeros if n not in ["1150", "012600", "346502", "062600", "041600", "282500", "062601", "343500", "040600", "083600"]), None)
            
            if not invoice:
                print(f"   ⚠ No se pudo extraer invoice para {pdf.name}")
                return None
            
            # Buscar fecha (soportando salto de línea después de "Date")
            fecha_match = re.search(r"Date\s+\n?\s*(\d{1,2}/\d{1,2}/\d{4})", texto, re.IGNORECASE | re.DOTALL)
            if not fecha_match:
                # Fallback: cualquier fecha en la primera página
                fecha_match = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", texto)
            
            if fecha_match:
                fecha_raw = fecha_match.group(1)
                # Convertir de MM/DD/YYYY a periodo YYYYMM
                fecha_dt = datetime.strptime(fecha_raw, "%m/%d/%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "PETRIZZIO":
            texto = extraer_texto_pdf(pdf)
            
            # Formato muestras: buscar REF IMP012_2025-2
            lineas = texto.split('\n')
            invoice = None
            
            for i, linea in enumerate(lineas):
                if 'REF.' in linea.upper():
                    if i + 1 < len(lineas):
                        ref_linea = lineas[i + 1].strip()
                        if re.match(r'^IMP\d+_\d+', ref_linea):
                            invoice = ref_linea
                    break
            
            # Formato original: buscar Nº
            if not invoice:
                inv_match = re.search(r"Nº\s*(\d+)", texto)
                invoice = inv_match.group(1) if inv_match else "000000"
            
            # Fecha
            fecha = None
            fecha_match = re.search(r"Emisión\s*:\s*(\d{2}-\d{2}-\d{4})", texto)
            if fecha_match:
                fecha_dt = datetime.strptime(fecha_match.group(1), "%d-%m-%Y")
                periodo = fecha_dt.strftime("%Y%m")
            else:
                # Formato muestras: "23 1 2025"
                fecha_match = re.search(r'(\d{1,2})\s+(\d{1,2})\s+(\d{4})', texto)
                if fecha_match:
                    dia, mes, anio = fecha_match.group(1), fecha_match.group(2), fecha_match.group(3)
                    periodo = f"{anio}{mes.zfill(2)}"
                else:
                    periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

        elif marca == "TONY_MOLY_HOLIKA_HOLIKA":
            # Patrón más flexible para capturar el invoice completo
            # Busca: CI_HHB_ARUMA + números + _ + fecha + _ + IMP + números + (opcional _SEA u otros) + _sent
            invoice_match = re.search(r"(CI_HHB_ARUMA\d+_?\d{6}_IMP\d+(?:_[A-Z]+)?_sent)", texto)
            
            if not invoice_match:
                # Intento alternativo: permitir comillas simples
                invoice_match = re.search(r"(CI_HHB_ARUMA\d+_?'?\d{6}_IMP\d+(?:_[A-Z]+)?_sent)", texto)
            
            if not invoice_match:
                # Intento más genérico: cualquier cosa que empiece con CI_HHB_ARUMA hasta _sent
                invoice_match = re.search(r"(CI_HHB_ARUMA\d+_.*?_sent)", texto)
            
            if invoice_match:
                raw_invoice = invoice_match.group(1).strip()
                invoice = raw_invoice.replace("'", "").replace(" ", "_")
                print(f"   📋 Invoice extraído: {invoice}")
            else:
                invoice = "UNKNOWN"
                print(f"   ⚠ No se pudo extraer invoice para {pdf.name}")
            
            # Fecha
            fecha_match = re.search(r"Issued Date:\s*(\d{2}\.\d{2}\.\d{2})", texto)
            if fecha_match:
                dt = datetime.strptime(fecha_match.group(1), "%y.%m.%d")
                periodo = dt.strftime("%Y%m")
                print(f"   📅 Fecha extraída: {fecha_match.group(1)} → periodo: {periodo}")
            else:
                periodo = "000000"
            
            nombre_final = f"{marca}_{invoice}_{periodo}.pdf"

            # Extraer PO del nombre original
            po = None
            nombre_original = pdf.name
            po_match = re.search(r'(IMP\d+(?:-\d+)?-(\d{4}))_', nombre_original)
            if po_match:
                po = po_match.group(1)
                print(f"   📦 PO extraído del nombre original: {po}")
                return f"{po}_{nombre_final}"
            else:
                return nombre_final

    except Exception as e:
        print(f"⚠ {marca}: Error generando nombre para {pdf.name} → {e}")
        return None

# ══════════════════════════════════════════════════════════════════
# PARSER PIXI 
# ══════════════════════════════════════════════════════════════════

def parse_pixi(pdf_file, marca, proveedor):
    nombre_archivo = pdf_file.name
    
    texto = extraer_texto_pdf(pdf_file)
    
    # Invoice: priorizar INV, sino SO
    invoice_match = re.search(r'INV(\d+)', texto)
    if invoice_match:
        invoice = f"INV{invoice_match.group(1)}"
    else:
        so_match = re.search(r'#?SO(\d+)', texto)
        invoice = f"SO{so_match.group(1)}" if so_match else None
    
    if not invoice:
        return []
    
    # Fecha
    fecha_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', texto)
    if fecha_match:
        fecha_raw = fecha_match.group(1)
        partes = fecha_raw.split('/')
        if int(partes[0]) > 12:
            fecha_dt = datetime.strptime(fecha_raw, "%d/%m/%Y")
        else:
            fecha_dt = datetime.strptime(fecha_raw, "%m/%d/%Y")
        fecha = fecha_dt.strftime("%d/%m/%Y")
        periodo = fecha_dt.strftime("%Y%m")
    else:
        return []
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # Due Date
    due_match = re.search(r'End of Month\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
    if not due_match:
        due_match = re.search(r'Due Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
    if due_match:
        due_raw = due_match.group(1)
        partes = due_raw.split('/')
        if int(partes[0]) > 12:
            due_dt = datetime.strptime(due_raw, "%d/%m/%Y")
        else:
            due_dt = datetime.strptime(due_raw, "%m/%d/%Y")
        due = due_dt.strftime("%d/%m/%Y")
    else:
        due = fecha
    
    incoterm = "EXW"
    moneda = "USD"
    sample = detectar_sample(texto)
    total_factura_pdf = _extraer_total_generico(texto)

    registros = []
    lineas = texto.split('\n')

    for i, linea in enumerate(lineas):
        linea_clean = linea.strip()

        # Formato A: código cantidad precio total
        m_a = re.match(r'^(\d{5})\s+(\d{1,3}(?:,\d{3})*)\s+\$([\d,]+\.\d{2})\s+\$([\d,]+\.\d{2})$', linea_clean)
        if m_a:
            codigo = m_a.group(1)
            cantidad = int(m_a.group(2).replace(',', ''))
            precio = float(m_a.group(3).replace(',', ''))
            importe = float(m_a.group(4).replace(',', ''))
            
            descripcion = ""
            if i + 1 < len(lineas):
                sig_linea = lineas[i + 1].strip()
                if not re.match(r'^\d{5}\s', sig_linea):
                    descripcion = sig_linea
            
            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": codigo,
                "codigo_producto": None,
                "tipo_codigo": None,
                "descripcion": descripcion,
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": moneda,
                "importe": importe,
                "sample": sample,
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })
            continue
        
        # Formato B: código con más campos
        if re.match(r'^\d{5}\s', linea_clean):
            partes = linea_clean.split()
            if len(partes) >= 6:
                codigo = partes[0]
                
                cantidad = None
                for p in partes:
                    if p.isdigit() and len(p) <= 4:
                        cantidad = int(p)
                        break
                
                precio = None
                for p in partes:
                    if p.startswith('$'):
                        precio = float(p.replace('$', '').replace(',', ''))
                        break
                
                descripcion = ""
                if i + 1 < len(lineas):
                    sig_linea = lineas[i + 1].strip()
                    if not re.match(r'^\d{5}\s', sig_linea):
                        descripcion = sig_linea
                        descripcion = re.sub(r'\s+\d+$', '', descripcion)
                
                if cantidad and precio:
                    importe = round(cantidad * precio, 2)
                    
                    registros.append({
                        "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                        "marca": marca,
                        "proveedor": proveedor,
                        "invoice": invoice,
                        "invoice_date": fecha,
                        "due_date": due,
                        "po": po,
                        "incoterm": incoterm,
                        "periodo": periodo,
                        "item": codigo,
                        "codigo_producto": None,
                        "tipo_codigo": None,
                        "descripcion": descripcion,
                        "cantidad": cantidad,
                        "costo_unitario": precio,
                        "moneda": moneda,
                        "importe": importe,
                        "sample": sample,
                        "nombre_archivo": nombre_archivo,
                        "total_factura_pdf": total_factura_pdf,
                    })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER THEBALM
# ══════════════════════════════════════════════════════════════════

def parse_thebalm(pdf_file, marca, proveedor):
    """theBalm Cosmetics: proveedor de una sola marca (confirmado revisando
    facturas de 2024 y 2025 — nunca mezcla otras marcas en la misma
    factura). Dos plantillas conviven: "Commercial Invoice" (con columnas
    Country of Origin / HS Code, encabezado "Order #") y la "Invoice"
    estándar más reciente (sin esas columnas, encabezado "Invoice #"). En
    ambas, la tabla de items a veces envuelve la descripción en 2 líneas
    (ej. "(0693-145)" en línea aparte) — por eso se usa extract_tables() en
    vez de extract_text(), que mantiene esa celda unida."""
    nombre_archivo = pdf_file.name

    texto = extraer_texto_pdf(pdf_file)

    # Invoice: "Invoice # S481006" (formato vigente) o "Order # S480787"
    # (Commercial Invoice, formato antiguo)
    invoice_match = re.search(r'Invoice\s*#\s*(\S+)', texto)
    if not invoice_match:
        invoice_match = re.search(r'Order\s*#\s*(\S+)', texto)
    invoice = invoice_match.group(1) if invoice_match else None

    if not invoice:
        return []

    # Fecha: "Date 8/26/2024" — cuidado de no matchear "Ship to Date ..."
    fecha_match = re.search(r'(?<!Ship to )Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
    if not fecha_match:
        return []
    fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")

    # No se observó fecha de vencimiento explícita en ninguna plantilla (Terms: Prepaid)
    due = fecha
    due_days = 0

    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = "FOB"
    moneda = "USD"
    tipo_codigo = "UPC"
    total_factura_pdf = _extraer_total_por_ultimo_monto_dolar(texto)

    # ========== ITEMS (vía extract_tables) ==========
    # pdfplumber junta TODAS las filas de datos en una sola fila de tabla:
    # cada celda trae sus N valores separados por '\n' (no hay líneas
    # divisorias entre ítems en esta plantilla, solo alrededor del header).
    # Item Number/Quantity/Rate nunca envuelven, así que su cantidad de
    # líneas es la cuenta real de filas (N). La descripción sí puede
    # envolver en una línea aparte (un código de estilo entre paréntesis o
    # un código de barras suelto) — esas líneas de continuación no traen
    # ninguna señal fiable en común salvo que NO son el inicio de un ítem
    # nuevo, así que se pegan a la línea anterior.
    registros = []
    contador_codigos = {}

    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables():
                header_idx = None
                for i, fila in enumerate(tabla):
                    celdas = [str(c).strip().upper() if c else "" for c in fila]
                    if "ITEM" in celdas and any("ITEM NUMBER" in c for c in celdas):
                        header_idx = i
                        break
                if header_idx is None:
                    continue
                if len(tabla) <= header_idx + 1 or len(tabla[header_idx + 1]) < 4:
                    continue

                fila_datos = tabla[header_idx + 1]
                codigos = [l.strip() for l in str(fila_datos[1] or "").split('\n') if l.strip()]
                qtys = [l.strip() for l in str(fila_datos[2] or "").split('\n') if l.strip()]
                rates = [l.strip() for l in str(fila_datos[3] or "").split('\n') if l.strip()]
                n = len(codigos)
                if n == 0 or len(qtys) != n or len(rates) != n:
                    continue

                descripciones = []
                for linea in str(fila_datos[0] or "").split('\n'):
                    linea = linea.strip()
                    if not linea:
                        continue
                    # Continuación si: es solo un código entre paréntesis, un
                    # código de barras suelto (con o sin guion pegado, ej.
                    # "-681619821356"), o si la línea anterior dejó un
                    # paréntesis sin cerrar (ej. "...(Committed, Charming," +
                    # "Sincere) - 681619814112" en la línea siguiente).
                    paren_sin_cerrar = bool(descripciones) and descripciones[-1].count('(') > descripciones[-1].count(')')
                    es_continuacion = (
                        bool(re.fullmatch(r'\(.*\)', linea))
                        or bool(re.fullmatch(r'-?\d{6,}', linea))
                        or paren_sin_cerrar
                    )
                    if es_continuacion and descripciones:
                        descripciones[-1] = f"{descripciones[-1]} {linea}"
                    else:
                        descripciones.append(linea)
                if len(descripciones) != n:
                    # No se pudo alinear la descripción con confianza —
                    # mejor no inventar datos que insertar filas mal armadas.
                    continue

                for codigo, qty_str, rate_str, descripcion in zip(codigos, qtys, rates, descripciones):
                    codigo = codigo.strip()
                    if not codigo or not re.match(r'^\d{6,}$', codigo):
                        continue

                    qty_limpio = qty_str.replace(',', '').strip()
                    if not qty_limpio.replace('.', '', 1).isdigit():
                        continue
                    cantidad = int(float(qty_limpio))

                    rate_limpio = rate_str.replace('$', '').replace(',', '').strip()
                    if not _es_numero_explicito(rate_limpio):
                        continue
                    precio = float(rate_limpio)

                    if codigo not in contador_codigos:
                        contador_codigos[codigo] = 0
                    contador_codigos[codigo] += 1
                    codigo_unico = codigo if contador_codigos[codigo] == 1 else f"{codigo}_{contador_codigos[codigo]}"

                    importe = round(cantidad * precio, 2)

                    registros.append({
                        "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo_unico}",
                        "marca": marca,
                        "proveedor": proveedor,
                        "invoice": invoice,
                        "invoice_date": fecha,
                        "due_date": due,
                        "due_days": due_days,
                        "po": po,
                        "incoterm": incoterm,
                        "periodo": periodo,
                        "item": codigo_unico,
                        "codigo_producto": codigo,
                        "tipo_codigo": tipo_codigo,
                        "descripcion": descripcion,
                        "cantidad": cantidad,
                        "costo_unitario": precio,
                        "moneda": moneda,
                        "importe": importe,
                        "sample": "Y" if precio == 0 else detectar_sample(texto),
                        "nombre_archivo": nombre_archivo,
                        "total_factura_pdf": total_factura_pdf,
                    })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER CISNE_NEGRO
# ══════════════════════════════════════════════════════════════════

def parse_cisne_negro(pdf_file, marca, proveedor):
    """CISNE_NEGRO: accesorios de maquillaje de marca propia (código ARU-*),
    fabricados por Oceanic Trade & Investment Co., Ltd. A diferencia de
    theBalm, acá extract_tables() arma la tabla de items limpia (fila por
    fila, sin celdas con varias líneas pegadas). Las muestras vienen con
    precio normal (no 0), marcadas por texto "SAMPLES WITHOUT COMMERCIAL
    VALUE" / "MUESTRAS SIN VALOR COMERCIAL" — se usa detectar_sample(texto)
    por documento, no la regla de precio==0."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    # Fecha: "Date: 2024-Aug the 7th" (a veces con el mes completo, "July" en
    # vez de "Jul") — quitar sufijo ordinal del día y truncar el mes a 3
    # letras para strptime.
    fecha_match = re.search(r'Date:\s*(\d{4})-\s*([A-Za-z]+)\s+the\s+(\d{1,2})(?:st|nd|rd|th)?', texto)
    if not fecha_match:
        return []
    anio, mes_texto, dia = fecha_match.groups()
    try:
        fecha_dt = datetime.strptime(f"{anio}-{mes_texto[:3]}-{dia}", "%Y-%b-%d")
    except ValueError:
        return []
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")

    invoice_match = re.search(r'Invoice No:\s*([^\n]+)', texto)
    invoice = invoice_match.group(1).strip() if invoice_match else None
    if not invoice:
        return []

    # PO del nombre del archivo (convención de siempre, no del contenido del PDF)
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = "FOB"
    moneda = "USD"
    tipo_codigo = "SKU"
    sample = detectar_sample(texto)
    total_factura_pdf = _extraer_total_por_ultimo_monto_dolar(texto)

    registros = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables():
                header_idx = None
                idx = {}
                for i, fila in enumerate(tabla):
                    celdas = [str(c).strip().upper() if c else "" for c in fila]
                    if any("ITEM NO." in c for c in celdas) and any("PRODUCT NAME" in c for c in celdas):
                        header_idx = i
                        # Columnas por NOMBRE, no por posición fija: la
                        # plantilla a veces omite "Product Size" (9 columnas
                        # en vez de 10, corriendo todo lo de la derecha), y a
                        # veces el encabezado viene partido en 2-3 filas (ej.
                        # "FOB USD" en una fila y "Price" recién en la
                        # siguiente) por cómo envuelve esa celda — por eso se
                        # revisan también la fila anterior y la siguiente.
                        filas_header = [fila]
                        if i > 0:
                            filas_header.append(tabla[i - 1])
                        if i + 1 < len(tabla):
                            filas_header.append(tabla[i + 1])
                        for fila_h in filas_header:
                            for ci, celda in enumerate(fila_h):
                                c = str(celda).strip().upper() if celda else ""
                                if "ITEM NO." in c and "codigo" not in idx:
                                    idx["codigo"] = ci
                                elif "PRODUCT NAME" in c and "nombre" not in idx:
                                    idx["nombre"] = ci
                                elif "PRODUCT DETAILS" in c and "detalle" not in idx:
                                    idx["detalle"] = ci
                                elif ("FOB" in c or "PRICE" in c) and "precio" not in idx:
                                    idx["precio"] = ci
                                elif "QUANTITY" in c and "cantidad" not in idx:
                                    idx["cantidad"] = ci
                        break
                if header_idx is None or not all(k in idx for k in ("codigo", "nombre", "precio", "cantidad")):
                    continue

                for fila in tabla[header_idx + 1:]:
                    if not fila or len(fila) <= max(idx.values()):
                        continue
                    if "SUB TOTAL" in str(fila[0] or "").upper():
                        break

                    codigo = str(fila[idx["codigo"]]).strip() if fila[idx["codigo"]] else ""
                    if not codigo:
                        continue

                    nombre_producto = (
                        str(fila[idx["nombre"]]).replace('\n', ' ').strip() if fila[idx["nombre"]] else ""
                    )
                    detalle = (
                        str(fila[idx["detalle"]]).replace('\n', ' ').strip()
                        if "detalle" in idx and fila[idx["detalle"]] else ""
                    )
                    descripcion = f"{nombre_producto} — {detalle}".strip(" —")

                    precio_str = _normalizar_numero_moneda(fila[idx["precio"]]) if fila[idx["precio"]] else ""
                    if not _es_numero_explicito(precio_str):
                        continue
                    precio = float(precio_str)

                    qty_match = re.search(r'([\d,]+)', str(fila[idx["cantidad"]]) if fila[idx["cantidad"]] else "")
                    if not qty_match:
                        continue
                    cantidad = int(qty_match.group(1).replace(',', ''))
                    if cantidad == 0:
                        continue

                    importe = round(cantidad * precio, 2)

                    registros.append({
                        "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                        "marca": marca,
                        "proveedor": proveedor,
                        "invoice": invoice,
                        "invoice_date": fecha,
                        "due_date": fecha,
                        "po": po,
                        "incoterm": incoterm,
                        "periodo": periodo,
                        "item": codigo,
                        "codigo_producto": codigo,
                        "tipo_codigo": tipo_codigo,
                        "descripcion": descripcion,
                        "cantidad": cantidad,
                        "costo_unitario": precio,
                        "moneda": moneda,
                        "importe": importe,
                        "sample": sample,
                        "nombre_archivo": nombre_archivo,
                        "total_factura_pdf": total_factura_pdf,
                    })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER HELLO_SUNDAY
# ══════════════════════════════════════════════════════════════════

def parse_hello_sunday(pdf_file, marca, proveedor):
    """HELLO_SUNDAY: proveedor español (Hello Sunday Ventures, S.L.), factura
    en EUR. A diferencia de CISNE_NEGRO, esta plantilla NO tiene líneas de
    tabla (extract_tables() no encuentra nada) pero el texto plano sale en
    perfecto orden de lectura, una línea por ítem — se parsea por regex
    sobre extraer_texto_pdf() en vez de extract_tables(). Algunas líneas son
    kits/displays sin GTIN propio (ej. "TRAVEL SET", "Marketing Display"):
    para esas se usa el número de referencia ("No.") como código, con
    tipo_codigo="REF" en vez de "GTIN". Formato numérico siempre europeo
    (punto de miles, coma decimal) en todas las facturas vistas."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    invoice_match = re.search(r'Invoice\s+(FVR\d+)', texto)
    invoice = invoice_match.group(1) if invoice_match else None
    if not invoice:
        return []

    # Fecha de emisión: primera fecha "D de Month de YYYY" del documento
    # (aparece pegada al título, antes de la sección "Due Date").
    fecha_match = re.search(r'^\s*(\d{1,2}) de ([A-Za-z]+) de (\d{4})', texto, re.MULTILINE)
    if not fecha_match:
        return []
    dia, mes_ingles, anio = fecha_match.groups()
    try:
        fecha_dt = datetime.strptime(f"{dia} {mes_ingles} {anio}", "%d %B %Y")
    except ValueError:
        return []
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")

    due_match = re.search(r'Due Date.*?(\d{1,2}) de ([A-Za-z]+) de (\d{4})', texto, re.DOTALL)
    if due_match:
        try:
            due_dt = datetime.strptime(f"{due_match.group(1)} {due_match.group(2)} {due_match.group(3)}", "%d %B %Y")
            due = due_dt.strftime("%d/%m/%Y")
            due_days = (due_dt - fecha_dt).days
        except ValueError:
            due, due_days = fecha, 0
    else:
        due, due_days = fecha, 0

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = "EXW"
    moneda = "EUR"

    def _num_eu(s):
        return float(s.replace('.', '').replace(',', '.'))

    total_match = re.search(r'Total\s*€\s*Incl\.\s*VAT\s+([\d.,]+)', texto)
    total_factura_pdf = _num_eu(total_match.group(1)) if total_match else None

    patron_con_gtin = re.compile(
        r'^(\d{5,8})\s+(\d{8,14})\s+(.+?)\s+(\d{2}/\d{2}/\d{2})\s+([\d.,]+)\s+([\d.,]+)\s*'
        r'\s+(?:[\d.,]+%?\s+)?(\d+)%\s+([\d.,]+)\s*$'
    )
    patron_sin_gtin = re.compile(
        r'^(\d{5,8})\s+([A-Za-z].+?)\s+(\d{2}/\d{2}/\d{2})\s+([\d.,]+)\s+([\d.,]+)\s*'
        r'\s+(?:[\d.,]+%?\s+)?(\d+)%\s+([\d.,]+)\s*$'
    )

    registros = []
    contador_codigos = {}
    for linea in texto.split('\n'):
        linea_limpia = linea.replace('€', '').strip()
        if not linea_limpia:
            continue

        m = patron_con_gtin.match(linea_limpia)
        if m:
            _ref, gtin, descripcion, _fecha_envio, cantidad_str, precio_str, _vat, _importe_str = m.groups()
            codigo = gtin
            tipo_codigo = "GTIN"
        else:
            m = patron_sin_gtin.match(linea_limpia)
            if not m:
                continue
            ref, descripcion, _fecha_envio, cantidad_str, precio_str, _vat, _importe_str = m.groups()
            codigo = ref
            tipo_codigo = "REF"

        descripcion = descripcion.strip()
        cantidad = int(round(_num_eu(cantidad_str)))
        if cantidad == 0:
            continue
        precio = _num_eu(precio_str)
        importe = round(cantidad * precio, 2)

        if codigo not in contador_codigos:
            contador_codigos[codigo] = 0
        contador_codigos[codigo] += 1
        codigo_unico = codigo if contador_codigos[codigo] == 1 else f"{codigo}_{contador_codigos[codigo]}"

        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo_unico}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": due,
            "due_days": due_days,
            "po": po,
            "incoterm": incoterm,
            "periodo": periodo,
            "item": codigo_unico,
            "codigo_producto": codigo,
            "tipo_codigo": tipo_codigo,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": importe,
            "sample": "Y" if precio == 0 else detectar_sample(texto),
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER EARTH_RHYTHM
# ══════════════════════════════════════════════════════════════════

def parse_earth_rhythm(pdf_file, marca, proveedor):
    """EARTH RHYTHM PRIVATE LIMITED (India), proveedor de una sola marca.
    Igual que CISNE_NEGRO, extract_tables() arma la tabla de items limpia
    (fila por fila)."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    invoice_match = re.search(r'INVOICE\s+NO\s*:-\s*(\S+)', texto, re.IGNORECASE)
    invoice = invoice_match.group(1) if invoice_match else None
    if not invoice:
        return []

    fecha_match = re.search(r'DATE\s*:-\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
    if not fecha_match:
        return []
    fecha_dt = datetime.strptime(fecha_match.group(1), "%d/%m/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")

    # PO del nombre del archivo (convención de siempre, no del contenido del PDF)
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = "EXW"
    moneda = "USD"
    tipo_codigo = "SKU"
    sample = detectar_sample(texto)

    total_match = re.search(r'Total\s+Invoice\s+Value\s*([\d,]+\.\d{2})', texto, re.IGNORECASE)
    total_factura_pdf = float(total_match.group(1).replace(',', '')) if total_match else _extraer_total_generico(texto)

    registros = []
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            for tabla in page.extract_tables():
                header_idx = None
                idx = {}
                for i, fila in enumerate(tabla):
                    celdas = [str(c).strip().upper() if c else "" for c in fila]
                    if any("PRODUCT NAME" in c for c in celdas) and "SKU" in celdas:
                        header_idx = i
                        for ci, c in enumerate(celdas):
                            if "PRODUCT NAME" in c:
                                idx["nombre"] = ci
                            elif c == "SKU":
                                idx["codigo"] = ci
                            elif "CATEGORY" in c:
                                idx["categoria"] = ci
                            elif "RATE" in c:
                                idx["precio"] = ci
                            elif c == "UNITS":
                                idx["cantidad"] = ci
                        break
                if header_idx is None or not all(k in idx for k in ("codigo", "nombre", "precio", "cantidad")):
                    continue

                for fila in tabla[header_idx + 1:]:
                    if not fila or len(fila) <= max(idx.values()):
                        continue

                    codigo = str(fila[idx["codigo"]]).strip() if fila[idx["codigo"]] else ""
                    if not codigo:
                        continue

                    nombre_producto = (
                        str(fila[idx["nombre"]]).replace('\n', ' ').strip() if fila[idx["nombre"]] else ""
                    )
                    categoria = (
                        str(fila[idx["categoria"]]).replace('\n', ' ').strip()
                        if "categoria" in idx and fila[idx["categoria"]] else ""
                    )
                    descripcion = f"{nombre_producto} — {categoria}".strip(" —")

                    precio_str = str(fila[idx["precio"]]).replace(',', '').strip() if fila[idx["precio"]] else ""
                    if not _es_numero_explicito(precio_str):
                        continue
                    precio = float(precio_str)

                    cantidad_str = str(fila[idx["cantidad"]]).replace(',', '').strip() if fila[idx["cantidad"]] else ""
                    if not cantidad_str.replace('.', '', 1).isdigit():
                        continue
                    cantidad = int(float(cantidad_str))
                    if cantidad == 0:
                        continue

                    importe = round(cantidad * precio, 2)

                    registros.append({
                        "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                        "marca": marca,
                        "proveedor": proveedor,
                        "invoice": invoice,
                        "invoice_date": fecha,
                        "due_date": fecha,
                        "po": po,
                        "incoterm": incoterm,
                        "periodo": periodo,
                        "item": codigo,
                        "codigo_producto": codigo,
                        "tipo_codigo": tipo_codigo,
                        "descripcion": descripcion,
                        "cantidad": cantidad,
                        "costo_unitario": precio,
                        "moneda": moneda,
                        "importe": importe,
                        "sample": sample,
                        "nombre_archivo": nombre_archivo,
                        "total_factura_pdf": total_factura_pdf,
                    })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER NEW_STUDIO (TWEEZERMAN_INTERNATIONAL)
# ══════════════════════════════════════════════════════════════════

def parse_new_studio(pdf_file, marca, proveedor):
    """NEW_STUDIO: línea "ARUMA PERU" (marca propia) facturada por
    Tweezerman International LLC. El texto sale en buen orden de lectura
    por ítem, pero la descripción a veces envuelve en 2 líneas (ej.
    "ARUMA PERU - PREMIUM EYE APP" + "10 PACK" aparte) y cada ítem trae 2
    líneas de metadata después (Country of Origin / Tariff code) — se arma
    un buffer por ítem uniendo todo hasta el próximo código (\\d\\d-\\d\\d\\d\\d)
    y se busca el patrón de datos adentro con re.search (no re.match), así
    la metadata sobrante al final no rompe el match."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    invoice_match = re.search(r'Number\s+(IN_\d+)', texto)
    invoice = invoice_match.group(1) if invoice_match else None
    if not invoice:
        return []

    fecha_match = re.search(r'Invoice date\s+(\d{2}/\d{2}/\d{4})', texto)
    if not fecha_match:
        return []
    fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")

    due_match = re.search(r'Due date\s+(\d{2}/\d{2}/\d{4})', texto)
    if due_match:
        due_dt = datetime.strptime(due_match.group(1), "%m/%d/%Y")
        due = due_dt.strftime("%d/%m/%Y")
        due_days = (due_dt - fecha_dt).days
    else:
        due, due_days = fecha, 0

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm_match = re.search(r'Delivery terms\s+(\w+)', texto)
    incoterm = incoterm_match.group(1).upper() if incoterm_match else "FOB"
    moneda = "USD"
    tipo_codigo = "SKU"
    sample = detectar_sample(texto)

    total_match = re.search(r'([\d,]+\.\d{2})\s+USD\s*$', texto, re.MULTILINE)
    total_factura_pdf = float(total_match.group(1).replace(',', '')) if total_match else _extraer_total_generico(texto)

    lineas = [l.strip() for l in texto.split('\n')]
    bloques = []
    buffer = None
    for linea in lineas:
        if re.match(r'^\d{2}-\d{4}\s', linea):
            if buffer:
                bloques.append(buffer)
            buffer = linea
        elif buffer is not None:
            buffer += ' ' + linea
    if buffer:
        bloques.append(buffer)

    # Variante con "Packing slip No." (2 campos de referencia antes de las cantidades)
    patron_item_con_ps = re.compile(
        r'^(\d{2}-\d{4})\s+(.+?)\s+(PS_\S+)\s+(\S+)\s+'
        r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+EA\s+'
        r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+'
        r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})'
    )
    # Variante sin "Packing slip No." (1 solo campo de referencia)
    patron_item_sin_ps = re.compile(
        r'^(\d{2}-\d{4})\s+(.+?)\s+(\S+)\s+'
        r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})\s+EA\s+'
        r'([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+'
        r'([\d,]+\.\d{2})\s+([\d,]+\.\d{2})'
    )

    registros = []
    contador_codigos = {}
    for bloque in bloques:
        m = patron_item_con_ps.search(bloque)
        if m:
            codigo = m.group(1)
            descripcion = m.group(2).strip()
            cantidad_ordenada_str = m.group(5)
            cantidad_enviada_str = m.group(6)
            precio_str = m.group(8)
        else:
            m = patron_item_sin_ps.search(bloque)
            if not m:
                continue
            codigo = m.group(1)
            descripcion = m.group(2).strip()
            cantidad_ordenada_str = m.group(4)
            cantidad_enviada_str = m.group(5)
            precio_str = m.group(7)

        # Se prioriza la cantidad enviada; si el proveedor no la registra
        # (queda en 0.00, visto en algunas facturas finales), se usa la
        # cantidad ordenada, que es la que realmente se facturó.
        cantidad_str = (
            cantidad_enviada_str
            if float(cantidad_enviada_str.replace(',', '')) != 0
            else cantidad_ordenada_str
        )

        cantidad = int(float(cantidad_str.replace(',', '')))
        if cantidad == 0:
            continue
        precio = float(precio_str)
        importe = round(cantidad * precio, 2)

        if codigo not in contador_codigos:
            contador_codigos[codigo] = 0
        contador_codigos[codigo] += 1
        codigo_unico = codigo if contador_codigos[codigo] == 1 else f"{codigo}_{contador_codigos[codigo]}"

        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo_unico}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": due,
            "due_days": due_days,
            "po": po,
            "incoterm": incoterm,
            "periodo": periodo,
            "item": codigo_unico,
            "codigo_producto": codigo,
            "tipo_codigo": tipo_codigo,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": importe,
            "sample": sample,
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER 7_DAYS
# ══════════════════════════════════════════════════════════════════

def _num_7_days(s):
    """Los montos de 7_DAYS mezclan formato US (1,548.00) y europeo
    (2 769,60) incluso entre facturas del mismo proveedor (SOFIS SRL) —
    se reutiliza el detector de separador decimal por posición (el mismo
    usado para CISNE_NEGRO) tras quitar espacios de miles."""
    limpio = str(s).replace(' ', '').replace('\xa0', '')
    return float(_normalizar_numero_moneda(limpio))


def parse_7_days(pdf_file, marca, proveedor):
    """7_DAYS: proveedor SOFIS SRL (Italia). Cada ítem es una sola línea de
    texto plano en buen orden de lectura; el regex NO intenta capturar el
    país de origen por separado (a veces sale pegado a la palabra anterior
    sin espacio, ej. "25 g" truncado en "2CHINA" — artefacto de extracción
    del PDF) sino que lo deja como parte de la descripción, y ancla el
    match por el Material Code (8-14 dígitos) y Custom code (6-12 dígitos)
    que sí salen siempre limpios. La fecha viene con "." o "/" según la
    factura, y el número de invoice puede venir precedido de "№" o "Nr."."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    invoice_match = re.search(r'INVOICE\s*(?:№|Nr\.)?\s*(\d+)\s+(\d{2}[./]\d{2}[./]\d{4})', texto)
    if not invoice_match:
        return []
    invoice = invoice_match.group(1)
    fecha_dt = datetime.strptime(invoice_match.group(2).replace('/', '.'), "%d.%m.%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    due, due_days = fecha, 0

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = "FOB"
    moneda = "EUR"
    tipo_codigo = "EAN"
    sample = detectar_sample(texto)

    total_match = re.search(r'Total:\s*([\d\s,.]+)EUR', texto)
    total_factura_pdf = _num_7_days(total_match.group(1)) if total_match else _extraer_total_generico(texto)

    patron_item = re.compile(
        r'^(\d+)\s+(.+?)\s+(\d{8,14})\s+(\d{6,12})\s+'
        r'([\d,.]+)\s+([\d,.]+)\s+([\d,]+)\s+([\d,.]+)\s+([\d,.]+)\s*$'
    )

    registros = []
    contador_codigos = {}
    for linea in texto.split('\n'):
        linea = linea.strip()
        if not linea:
            continue
        m = patron_item.match(linea)
        if not m:
            continue

        codigo = m.group(3)
        descripcion = m.group(2).strip()
        cantidad = int(m.group(7).replace(',', ''))
        if cantidad == 0:
            continue
        precio = _num_7_days(m.group(8))
        importe = round(cantidad * precio, 2)

        if codigo not in contador_codigos:
            contador_codigos[codigo] = 0
        contador_codigos[codigo] += 1
        codigo_unico = codigo if contador_codigos[codigo] == 1 else f"{codigo}_{contador_codigos[codigo]}"

        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo_unico}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": due,
            "due_days": due_days,
            "po": po,
            "incoterm": incoterm,
            "periodo": periodo,
            "item": codigo_unico,
            "codigo_producto": codigo,
            "tipo_codigo": tipo_codigo,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": importe,
            "sample": sample,
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER FOAMOUS
# ══════════════════════════════════════════════════════════════════

def parse_foamous(pdf_file, marca, proveedor):
    """FOAMOUS: proveedor BEYOND PERFUME SAS (Francia), factura en EUR. El
    EAN de cada ítem no sale en la misma línea del producto sino en la línea
    siguiente ("Perfume Foam Batch Code {lote} {ean con espacios}") — se usa
    lookahead de una línea. Los kits/displays sin EAN propio (ej. "DISPLAY
    12") solo traen el lote en esa línea siguiente, sin dígitos de barcode;
    para esos se usa el lote como código con tipo_codigo="REF". El regex de
    ítem exige que los 3 últimos campos numéricos tengan punto decimal
    (unit price/amount/net amount) — así nunca confunde la línea de
    ítem con la línea de EAN de abajo (que son solo grupos de dígitos
    enteros sin punto). El total_factura_pdf es el GRAND TOTAL literal:
    puede salir en 0.00 si hay un 100% de "MARKETING CONTRIBUTION" (crédito
    promocional) que no se refleja en las líneas de detalle — es intencional,
    para que la app marque la diferencia y el usuario decida cómo tratarla."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    invoice_match = re.search(r'INVOICE\s*(?:NO\.|N°)\s*(FAC\|[\d|]+)', texto)
    if not invoice_match:
        return []
    invoice = invoice_match.group(1)

    fecha_match = re.search(r'^DATE\s+(\d{2}/\d{2}/\d{4})', texto, re.MULTILINE)
    if not fecha_match:
        return []
    fecha_dt = datetime.strptime(fecha_match.group(1), "%d/%m/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")

    due_match = re.search(r'DUE DATE\s+(\d{2}/\d{2}/\d{4})', texto)
    if due_match:
        due_dt = datetime.strptime(due_match.group(1), "%d/%m/%Y")
        due = due_dt.strftime("%d/%m/%Y")
        due_days = (due_dt - fecha_dt).days
    else:
        due, due_days = fecha, 0

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = "EXW"
    moneda = "EUR"
    sample = detectar_sample(texto)

    total_match = re.search(r'GRAND TOTAL\s+([\d.,]+)', texto)
    total_factura_pdf = float(total_match.group(1).replace(',', '')) if total_match else _extraer_total_generico(texto)

    patron_item = re.compile(r'^(.+?)\s+(\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s+(\d+\.\d+)\s*$')
    patron_batch = re.compile(r'Batch Code\s+(\S+)(?:\s+([\d\s]+))?\s*$')

    lineas = [l.strip() for l in texto.split('\n')]
    registros = []
    contador_codigos = {}
    i = 0
    while i < len(lineas):
        m = patron_item.match(lineas[i])
        if not m:
            i += 1
            continue

        descripcion = m.group(1).strip()
        cantidad = int(m.group(2))
        precio = float(m.group(3))
        if cantidad == 0:
            i += 1
            continue
        importe = round(cantidad * precio, 2)

        codigo = None
        tipo_codigo = "EAN"
        if i + 1 < len(lineas):
            bm = patron_batch.search(lineas[i + 1])
            if bm:
                batch, ean_raw = bm.group(1), bm.group(2)
                if ean_raw and ean_raw.strip():
                    codigo = ean_raw.replace(' ', '').strip()
                else:
                    codigo = batch
                    tipo_codigo = "REF"
                i += 1

        if codigo is None:
            codigo = re.sub(r'[^A-Z0-9]+', '_', descripcion.upper()).strip('_')
            tipo_codigo = "REF"

        if codigo not in contador_codigos:
            contador_codigos[codigo] = 0
        contador_codigos[codigo] += 1
        codigo_unico = codigo if contador_codigos[codigo] == 1 else f"{codigo}_{contador_codigos[codigo]}"

        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo_unico}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": due,
            "due_days": due_days,
            "po": po,
            "incoterm": incoterm,
            "periodo": periodo,
            "item": codigo_unico,
            "codigo_producto": codigo,
            "tipo_codigo": tipo_codigo,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": importe,
            "sample": sample,
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })

        i += 1

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER COZI_LIFE
# ══════════════════════════════════════════════════════════════════

def parse_cozi_life(pdf_file, marca, proveedor):
    """COZI_LIFE: proveedor Tantuc Asia LTD. (Taiwán), factura en USD. El
    texto extraído inserta un espacio espurio justo antes del separador
    decimal/miles en varios montos (ej. "2 .88" en vez de "2.88", "2 ,880"
    en vez de "2,880") — artefacto de extracción del PDF; se limpia con un
    solo re.sub sobre todo el texto antes de parsear nada. El EAN de cada
    ítem sale en la línea siguiente ("EAN CODE: ...") en vez de la misma
    línea del producto — se usa lookahead de 1 línea, igual que FOAMOUS."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)
    texto = re.sub(r'(\d)\s+([.,]\d)', r'\1\2', texto)

    invoice_match = re.search(r'IV No\.\s*:\s*(\S+)', texto)
    if not invoice_match:
        return []
    invoice = invoice_match.group(1)

    fecha_match = re.search(r'Date\s*:\s*([A-Za-z]{3,9})\.?\s*(\d{1,2}),\s*(\d{4})', texto)
    if not fecha_match:
        return []
    mes_str, dia, anio = fecha_match.groups()
    try:
        fecha_dt = datetime.strptime(f"{mes_str[:3]} {dia} {anio}", "%b %d %Y")
    except ValueError:
        return []
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    due, due_days = fecha, 0

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm_match = re.search(r'Incoterm\s*:\s*(\w+)', texto)
    incoterm = incoterm_match.group(1).upper() if incoterm_match else "FOB"
    moneda = "USD"
    sample = detectar_sample(texto)

    total_match = re.search(r'Total:\s*US\$\s*([\d,]+(?:\.\d+)?)', texto)
    total_factura_pdf = float(total_match.group(1).replace(',', '')) if total_match else _extraer_total_generico(texto)

    patron_item = re.compile(r'^(\d+)\s+(\S+)\s+(.+?)\s+(\d+)\s+PCS\s+([\d.,]+)\s+([\d.,]+)\s*$')
    patron_ean = re.compile(r'EAN CODE:\s*(\d+)', re.IGNORECASE)

    lineas = [l.strip() for l in texto.split('\n')]
    registros = []
    contador_codigos = {}
    i = 0
    while i < len(lineas):
        m = patron_item.match(lineas[i])
        if not m:
            i += 1
            continue

        codigo_sku = m.group(2)
        descripcion = m.group(3).strip()
        cantidad = int(m.group(4))
        if cantidad == 0:
            i += 1
            continue
        precio = float(m.group(5).replace(',', ''))
        importe = round(cantidad * precio, 2)

        codigo = codigo_sku
        tipo_codigo = "SKU"
        if i + 1 < len(lineas):
            em = patron_ean.search(lineas[i + 1])
            if em:
                codigo = em.group(1)
                tipo_codigo = "EAN"
                i += 1

        if codigo not in contador_codigos:
            contador_codigos[codigo] = 0
        contador_codigos[codigo] += 1
        codigo_unico = codigo if contador_codigos[codigo] == 1 else f"{codigo}_{contador_codigos[codigo]}"

        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo_unico}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": due,
            "due_days": due_days,
            "po": po,
            "incoterm": incoterm,
            "periodo": periodo,
            "item": codigo_unico,
            "codigo_producto": codigo,
            "tipo_codigo": tipo_codigo,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": importe,
            "sample": sample,
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })
        i += 1

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER LATAM_CHINA
# ══════════════════════════════════════════════════════════════════

def parse_latam_china(pdf_file, marca, proveedor):
    """LATAM_CHINA: proveedor LATAM-CHINA TRADING CO., LIMITED, factura en
    español con precios en USD. La columna "Modelo" viene vacía en algunos
    ítems (un número suelto en su lugar, ej. "325" para "Hisopos" en el
    único documento visto) — se usa igual como código, sin asumir que
    siempre tenga letras."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    invoice_match = re.search(r'POR LA FACTURA NO\.\s*(\S+)', texto)
    invoice = invoice_match.group(1) if invoice_match else None
    if not invoice:
        return []

    meses_es = {
        'ENERO': 1, 'FEBRERO': 2, 'MARZO': 3, 'ABRIL': 4, 'MAYO': 5, 'JUNIO': 6,
        'JULIO': 7, 'AGOSTO': 8, 'SETIEMBRE': 9, 'SEPTIEMBRE': 9, 'OCTUBRE': 10,
        'NOVIEMBRE': 11, 'DICIEMBRE': 12,
    }
    fecha_match = re.search(r'FECHA:\s*(\d{1,2})\s+([A-Za-zÁÉÍÓÚáéíóú]+)\s+(\d{4})', texto)
    if not fecha_match:
        return []
    dia, mes_nombre, anio = fecha_match.groups()
    mes = meses_es.get(mes_nombre.strip().upper())
    if not mes:
        return []
    fecha_dt = datetime(int(anio), mes, int(dia))
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    due, due_days = fecha, 0

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm_match = re.search(r'Termino de Compra:\s*(\w+)', texto, re.IGNORECASE)
    incoterm = incoterm_match.group(1).upper() if incoterm_match else "FOB"
    moneda = "USD"
    tipo_codigo = "REF"
    sample = detectar_sample(texto)

    total_match = re.search(r'VENTA TOTAL\s*\$\s*\$([\d,]+\.\d{2})', texto)
    total_factura_pdf = float(total_match.group(1).replace(',', '')) if total_match else _extraer_total_generico(texto)

    patron_item = re.compile(r'^(\d+)\s+(.+?)\s+(\S+)\s+([\d,]+)\s+\$([\d.]+)\s+\$([\d,]+\.\d{2})\s*$')

    registros = []
    contador_codigos = {}
    for linea in texto.split('\n'):
        linea = linea.strip()
        m = patron_item.match(linea)
        if not m:
            continue

        descripcion = m.group(2).strip()
        codigo = m.group(3)
        cantidad = int(m.group(4).replace(',', ''))
        if cantidad == 0:
            continue
        precio = float(m.group(5))
        importe = round(cantidad * precio, 2)

        if codigo not in contador_codigos:
            contador_codigos[codigo] = 0
        contador_codigos[codigo] += 1
        codigo_unico = codigo if contador_codigos[codigo] == 1 else f"{codigo}_{contador_codigos[codigo]}"

        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo_unico}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": due,
            "due_days": due_days,
            "po": po,
            "incoterm": incoterm,
            "periodo": periodo,
            "item": codigo_unico,
            "codigo_producto": codigo,
            "tipo_codigo": tipo_codigo,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": importe,
            "sample": sample,
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER FUJIAN_OUKANG (compartido con BORLA — mismo fabricante, Fujian
# Oukang Co., Ltd, pero cada línea de producto quedó en su propia carpeta
# de marca histórica)
# ══════════════════════════════════════════════════════════════════

def parse_fujian_oukang(pdf_file, marca, proveedor):
    """FUJIAN_OUKANG y BORLA comparten este parser aunque sus plantillas de
    PDF difieren bastante: FUJIAN_OUKANG es una Proforma Invoice nativa
    (descripción repartida en varias líneas, sin número de factura propio,
    línea numérica propia "$precio cantidad $ monto"); BORLA es un Excel
    de factura+packing list convertido a PDF por el usuario (sí trae
    "Invoice No:", fecha con guiones en vez de barras, y la línea numérica
    viene como "cantidad $precio $monto", a veces con texto suelto antes
    como "1-20 of 20 3 pcs for a set"). Se prueban ambos formatos de línea
    numérica en cascada (primero el de FUJIAN_OUKANG, si no matchea el de
    BORLA) y la fecha admite tanto "/" como "-" como separador. La fecha
    llegó una vez como "13/SPE/25" (typo del proveedor por "SEP"/
    septiembre) — se agrega "SPE" como alias de septiembre. Si no hay
    número de factura explícito (caso FUJIAN_OUKANG) se sintetiza uno a
    partir de la fecha (PI_YYYYMMDD). FUJIAN_OUKANG además trae a veces un
    crédito por saldo a favor de un pedido anterior ("over paid...") que la
    propia factura ya resta de su "Total Amount" — total_factura_pdf toma
    ese total ya neto, así que puede diferir de la suma de líneas de
    producto (que solo sabe de la venta bruta) hasta que ese crédito se
    cargue como ajuste CUSTOM en la app."""
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    meses_en = {
        'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
        'JUL': 7, 'AUG': 8, 'SEP': 9, 'SPE': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12,
    }
    fecha_match = re.search(r'Date:\s*(\d{1,2})[/-]([A-Za-z]{3})[/-](\d{2})', texto, re.IGNORECASE)
    if not fecha_match:
        return []
    dia, mes_str, anio2 = fecha_match.groups()
    mes = meses_en.get(mes_str.strip().upper())
    if not mes:
        return []
    fecha_dt = datetime(2000 + int(anio2), mes, int(dia))
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    due, due_days = fecha, 0

    invoice_match = re.search(r'Invoice No:\s*([A-Za-z0-9\s-]+?)\s+Page', texto)
    invoice = invoice_match.group(1).replace(' ', '').strip() if invoice_match else f"PI_{fecha_dt.strftime('%Y%m%d')}"

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = "FOB"
    moneda = "USD"
    tipo_codigo = "REF"
    sample = detectar_sample(texto)

    # Variante FUJIAN_OUKANG: "$precio cantidad $ monto".
    num_match = re.search(r'\$([\d.]+)\s+(\d+)\s+\$\s*([\d,]+\.\d{2})', texto)
    if num_match:
        precio = float(num_match.group(1))
        cantidad = int(num_match.group(2))
        amount = float(num_match.group(3).replace(',', ''))
    else:
        # Variante BORLA: "cantidad $precio $monto" (a veces con texto
        # suelto antes, ej. "1-20 of 20 3 pcs for a set").
        num_match = re.search(r'(\d[\d,]*)\s+\$([\d.,]+)\s+\$([\d,]+\.\d{2})\s*$', texto, re.MULTILINE)
        if not num_match:
            return []
        cantidad = int(num_match.group(1).replace(',', ''))
        precio = float(num_match.group(2).replace(',', ''))
        amount = float(num_match.group(3).replace(',', ''))

    if cantidad == 0:
        return []
    importe = round(cantidad * precio, 2)

    total_match = re.search(r'Total Amount\s*\$\s*([\d,]+\.\d{2})', texto)
    total_factura_pdf = float(total_match.group(1).replace(',', '')) if total_match else round(amount, 2)

    lineas = [l.strip() for l in texto.split('\n')]
    idx_header = next((i for i, l in enumerate(lineas) if 'Description' in l), None)
    num_texto = num_match.group(0).strip()
    idx_num = next((i for i, l in enumerate(lineas) if num_texto in l), None)

    desc_lineas = []
    if idx_header is not None and idx_num is not None and idx_num > idx_header:
        desc_lineas = [l for l in lineas[idx_header + 1:idx_num] if l.strip()]

    descripcion = ' | '.join(desc_lineas) if desc_lineas else "Sin descripción"
    nombre_producto = desc_lineas[0] if desc_lineas else "ITEM"
    codigo = re.sub(r'[^A-Z0-9]+', '_', nombre_producto.upper()).strip('_') or "ITEM"

    registro = {
        "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
        "marca": marca,
        "proveedor": proveedor,
        "invoice": invoice,
        "invoice_date": fecha,
        "due_date": due,
        "due_days": due_days,
        "po": po,
        "incoterm": incoterm,
        "periodo": periodo,
        "item": codigo,
        "codigo_producto": codigo,
        "tipo_codigo": tipo_codigo,
        "descripcion": descripcion,
        "cantidad": cantidad,
        "costo_unitario": precio,
        "moneda": moneda,
        "importe": importe,
        "sample": sample,
        "nombre_archivo": nombre_archivo,
        "total_factura_pdf": total_factura_pdf,
    }
    return [registro]

# ══════════════════════════════════════════════════════════════════
# PARSER SLICK_HAIR
# ══════════════════════════════════════════════════════════════════

def parse_slick_hair(pdf_file, marca, proveedor):
    nombre_archivo = pdf_file.name
    
    texto = extraer_texto_pdf(pdf_file)
    
    # Invoice: soporta SI-xxxxx o SO-xxxxx
    invoice_match = re.search(r'(SI-\d+|SO-\d+)', texto)
    invoice = invoice_match.group(1) if invoice_match else None
    
    if not invoice:
        return []
    
    # Fecha: soporta 28Apr2025 o 14/08/2024
    fecha_match = re.search(r'(\d{1,2}[A-Za-z]+\d{4})', texto)
    if fecha_match:
        fecha_raw = fecha_match.group(1)
        fecha_dt = datetime.strptime(fecha_raw, "%d%b%Y")
    else:
        fecha_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', texto)
        if fecha_match:
            fecha_raw = fecha_match.group(1)
            fecha_dt = datetime.strptime(fecha_raw, "%d/%m/%Y")
        else:
            return []
    
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Due Date
    due_match = re.search(r'Due Date:\s*(\d{1,2}\s+[A-Za-z]+\s+\d{4})', texto)
    if due_match:
        due_raw = due_match.group(1)
        due_dt = datetime.strptime(due_raw, "%d %b %Y")
        due = due_dt.strftime("%d/%m/%Y")
    else:
        due_match = re.search(r'Due Date:\s*(\d{1,2}/\d{1,2}/\d{4})', texto)
        if due_match:
            due_dt = datetime.strptime(due_match.group(1), "%d/%m/%Y")
            due = due_dt.strftime("%d/%m/%Y")
        else:
            due = fecha
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    incoterm = "FOB"
    moneda = "USD"
    total_factura_pdf = _extraer_total_generico(texto)

    # Palabras clave para ignorar líneas
    ignorar = ['Due', 'Subtotal', 'Total', 'Amount', 'Tax', 'Freight', 'Payment', 'BSB', 'Bank', 'SWIFT',
               'CARRETERA', 'PANAMERICA', 'KM', 'PASILLO', 'PUERTA', 'PUNTA', 'HERMOSA', 'South', 'Melbourne',
               'Peru', 'PO Number', 'ABN', 'Suite', 'Buckhurst', 'Subtotal', 'TOTALUSD', 'AmountDue']
    
    registros = []
    lineas = texto.split('\n')
    
    def separar_codigo_descripcion(item_code):
        """Separa el código de la descripción"""
        # Lista de códigos conocidos
        codigos_conocidos = ['HWS', 'EHB', 'GS1', 'CRC', 'CLC', 'SLICKSTICK', 'CREASELESSCLIPS', 
                            'PREMIUMCLAWCLIP', 'HAIRWAXSTICK', 'GS1-SS1', 'GS1-CRC', 'CRC-SFP', 
                            'EHB-SFP', 'GS1-HWS', 'SS1-SFP']
        
        # Verificar si el código completo está en la lista de códigos conocidos
        if item_code in codigos_conocidos:
            return item_code, item_code
        
        # Buscar guiones
        if '-' in item_code:
            partes = item_code.split('-')
            
            # Caso especial: códigos compuestos como GS1-CRC-CreaselessClips
            if len(partes) >= 3 and partes[0] in ['GS1', 'CRC', 'EHB', 'HWS']:
                # Los primeros 2 segmentos son el código
                codigo = '-'.join(partes[:2])
                descripcion = ' '.join(partes[2:])
                return codigo, descripcion
            # Caso simple: HWS-WaxStick
            elif len(partes) >= 2:
                codigo = partes[0]
                descripcion = ' '.join(partes[1:])
                return codigo, descripcion
        
        # Si no hay guión o es código simple
        return item_code, item_code
    
    for linea in lineas:
        linea_clean = linea.strip()
        if not linea_clean:
            continue
        
        # Saltar líneas con palabras clave
        if any(palabra in linea_clean for palabra in ignorar):
            continue
        
        # Solo procesar líneas que contengan números con decimales
        if not re.search(r'\d+\.\d+', linea_clean):
            continue
        
        partes = linea_clean.split()
        if len(partes) < 4:
            continue
        
        # Buscar números
        numeros = []
        for p in partes:
            if re.match(r'^[\d,]+\.?\d*$', p.replace(',', '')):
                numeros.append(float(p.replace(',', '')))
        
        if len(numeros) >= 2:
            cantidad = numeros[0]
            precio = numeros[1]
            importe = numeros[2] if len(numeros) >= 3 else cantidad * precio
            
            # El primer elemento es el código completo
            item_code = partes[0]
            
            # Separar código de descripción
            item, descripcion = separar_codigo_descripcion(item_code)
            
            # Si no se pudo separar, intentar con el texto entre código y números
            if descripcion == item_code or not descripcion:
                descripcion_partes = []
                for p in partes[1:]:
                    if re.match(r'^[\d,]+\.?\d*$', p.replace(',', '')):
                        break
                    descripcion_partes.append(p)
                if descripcion_partes:
                    descripcion = ' '.join(descripcion_partes).strip()
                else:
                    descripcion = item_code
            
            registros.append({
                # OJO: usa item_code (el texto completo tal como aparece en la
                # factura, ej. "CRC-SFP-MASTERCARTONS") y no 'item' (el código ya
                # recortado, ej. "CRC-SFP") — dos líneas distintas de la misma
                # factura pueden compartir el código corto (el pack al por mayor
                # "CRC-SFP-MASTERCARTONS" y la unidad suelta "CRC-SFP"), y con el
                # código recortado ambas generaban el mismo id y una se perdía
                # como "duplicada".
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": item,
                "codigo_producto": None,
                "tipo_codigo": None,
                "descripcion": descripcion,
                "cantidad": int(cantidad),
                "costo_unitario": round(precio, 2),
                "moneda": moneda,
                "importe": round(importe, 2),
                "sample": detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER TIRTIR_TOCOBO
# ══════════════════════════════════════════════════════════════════

def parse_silicon2(pdf_file, marca, proveedor):
    nombre_archivo = pdf_file.name
    
    registros = []
    
    with pdfplumber.open(pdf_file) as pdf:
        texto_completo = ""
        for page in pdf.pages:
            texto_completo += page.extract_text() + "\n"
        
        # Invoice
        invoice_match = re.search(r'No\.\s*:\s*([A-Z0-9]+)', texto_completo)
        invoice = invoice_match.group(1) if invoice_match else None
        
        # Fecha
        fecha_match = re.search(r'Date\s*:\s*(\d{4}-\d{2}-\d{2})', texto_completo)
        if not invoice or not fecha_match:
            return []
        
        fecha_dt = datetime.strptime(fecha_match.group(1), "%Y-%m-%d")
        fecha = fecha_dt.strftime("%d/%m/%Y")
        periodo = fecha_dt.strftime("%Y%m")
        
        # Extraer PO del nombre del archivo
        po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
        po = po_match.group(1) if po_match else None
        
        # Incoterm
        incoterm_match = re.search(r'FREIGHT TERMS\s+(\w+)', texto_completo)
        incoterm = incoterm_match.group(1) if incoterm_match else "FOB"
        
        moneda = "USD"
        total_factura_pdf = None

        # Extraer tabla de items
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                if not table or len(table) < 2:
                    continue

                # Buscar encabezado
                header = table[0]
                if header and len(header) >= 7 and header[0] == 'IDX':
                    # Procesar filas de datos
                    for row in table[1:]:
                        if not row or len(row) < 7:
                            continue

                        idx = row[0]
                        if not idx or idx == 'TOTAL' or not str(idx).isdigit():
                            # La fila TOTAL de esta misma tabla trae el total
                            # declarado — más confiable que buscarlo con regex
                            # en el texto completo.
                            if idx == 'TOTAL' and row[6]:
                                total_str = str(row[6]).replace(',', '').strip()
                                if total_str.replace('.', '', 1).isdigit():
                                    total_factura_pdf = float(total_str)
                            continue
                        
                        descripcion = str(row[1]).replace('\n', ' ').strip() if row[1] else ""
                        brand = str(row[2]).strip() if row[2] else ""
                        
                        # Limpiar cantidad (convertir a entero)
                        qty_str = str(row[4]).replace(',', '').strip() if row[4] else "0"
                        cantidad = int(float(qty_str)) if qty_str.replace('.', '').isdigit() else 0
                        
                        # Limpiar precio (quitar comas, convertir a float)
                        price_str = str(row[5]).replace(',', '').strip() if row[5] else "0"
                        precio = float(price_str) if price_str.replace('.', '').isdigit() else 0.0
                        
                        # Limpiar importe (quitar comas, convertir a float)
                        amount_str = str(row[6]).replace(',', '').strip() if row[6] else "0"
                        importe = float(amount_str) if amount_str.replace('.', '').isdigit() else 0.0

                        # precio 0 es válido y esperado en facturas de muestras (sample) —
                        # sólo se descarta la fila si de plano no hay cantidad (fila vacía/basura).
                        if cantidad == 0:
                            continue
                        
                        registros.append({
                            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{idx}",
                            "marca": brand,
                            "proveedor": proveedor,
                            "invoice": invoice,
                            "invoice_date": fecha,
                            "due_date": fecha,
                            "po": po,
                            "incoterm": incoterm,
                            "periodo": periodo,
                            "item": idx,
                            "codigo_producto": None,
                            "tipo_codigo": None,
                            "descripcion": descripcion,
                            "cantidad": cantidad,
                            "costo_unitario": precio,
                            "moneda": moneda,
                            "importe": importe,
                            # Regla del negocio: precio unitario 0 = muestra, sin excepción,
                            # sin importar si el texto del documento dice "sample" o no.
                            # Se evalúa por línea (no por documento completo) porque una
                            # misma factura puede traer ítems pagados y de regalo mezclados.
                            "sample": "Y" if precio == 0 else detectar_sample(texto_completo),
                            "nombre_archivo": nombre_archivo,
                            "total_factura_pdf": total_factura_pdf,
                        })

    # La fila TOTAL puede aparecer después de las filas de ítems en la
    # tabla, así que recién acá se sabe su valor — se completa en todos
    # los registros ya armados.
    for r in registros:
        r["total_factura_pdf"] = total_factura_pdf

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER OLAPLEX
# ══════════════════════════════════════════════════════════════════

def parse_olaplex(pdf_file, marca, proveedor):
    from datetime import timedelta
    
    nombre_archivo = pdf_file.name
    
    texto = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                texto += page_text + "\n"
    
    # ========== CABECERA ==========
    invoice = None
    
    # Formato 1: #INV121763
    inv_match = re.search(r'#INV(\d{6,})', texto)
    if inv_match:
        invoice = f"INV{inv_match.group(1)}"
    
    # Formato 2: SO######
    if not invoice:
        so_match = re.search(r'\b(SO\d{6,})\b', texto)
        if so_match:
            invoice = so_match.group(1)
    
    if not invoice:
        return []
    
    # Fecha
    fecha_dt = None
    # Formato 1: Invoice Date 9/24/2025
    fecha_match = re.search(r'Invoice Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
    if fecha_match:
        fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
    else:
        # Formato 2: primera fecha M/D/YYYY
        fechas = re.findall(r'(\d{1,2}/\d{1,2}/\d{4})', texto)
        if fechas:
            try:
                fecha_dt = datetime.strptime(fechas[0], "%m/%d/%Y")
            except:
                pass
    
    if not fecha_dt:
        return []
    
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Due Date
    due = fecha
    due_days = 0
    
    # Formato 1: Due Date explícito
    due_match = re.search(r'Due Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
    if due_match:
        due_dt = datetime.strptime(due_match.group(1), "%m/%d/%Y")
        due = due_dt.strftime("%d/%m/%Y")
        due_days = (due_dt - fecha_dt).days
    
    # Formato 2: Net XX
    if due_days == 0:
        net_match = re.search(r'Net\s+(\d+)', texto)
        if net_match:
            due_days = int(net_match.group(1))
            due_dt = fecha_dt + timedelta(days=due_days)
            due = due_dt.strftime("%d/%m/%Y")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # Incoterm
    incoterm = "EXW"
    if re.search(r'\bFOB\b', texto, re.IGNORECASE):
        incoterm = "FOB"
    
    moneda = "USD"
    tipo_codigo = "UPC"
    total_factura_pdf = _extraer_total_generico(texto)

    # ========== DETECCIÓN DE FORMATO ==========
    # Formato nuevo: "Item Qty Unit Price Tax Amount"
    es_formato_nuevo = "Item" in texto and "Qty" in texto and "Unit Price" in texto and "Tax" in texto
    
    # ========== ITEMS ==========
    registros = []
    lineas = texto.split('\n')
    
    if es_formato_nuevo:
        # Formato: CODIGO DESCRIPCION CANTIDAD $PRECIO 0% $AMOUNT
        inicio = None
        for i, linea in enumerate(lineas):
            if 'Item' in linea and 'Qty' in linea:
                inicio = i + 1
                break
        
        if inicio:
            items_raw = []
            buffer = None
            
            for i in range(inicio, len(lineas)):
                l = lineas[i].strip()
                
                if 'Subtotal' in l:
                    if buffer:
                        items_raw.append(buffer)
                    break
                
                if not l:
                    continue
                
                es_nuevo = bool(re.match(r'^\d{8}\s', l))
                
                if es_nuevo:
                    if buffer:
                        items_raw.append(buffer)
                    buffer = l
                else:
                    if buffer:
                        buffer += ' ' + l
            
            if buffer:
                items_raw.append(buffer)
            
            for item_text in items_raw:
                m = re.match(
                    r'^(\d{8})\s+'
                    r'(.+?)\s+'
                    r'([\d,]+)\s+'
                    r'\$?([\d.]+)\s+'
                    r'0%\s+'
                    r'\$?([\d,]+(?:\.\d{2})?)',
                    item_text
                )
                
                if m:
                    codigo = m.group(1)
                    descripcion = m.group(2).strip()
                    cantidad = int(m.group(3).replace(',', ''))
                    precio = float(m.group(4))
                    importe = round(cantidad * precio, 2)
                    
                    registros.append({
                        "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                        "marca": marca,
                        "proveedor": proveedor,
                        "invoice": invoice,
                        "invoice_date": fecha,
                        "due_date": due,
                        "due_days": due_days,
                        "po": po,
                        "incoterm": incoterm,
                        "periodo": periodo,
                        "item": str(codigo),
                        "codigo_producto": codigo,
                        "tipo_codigo": tipo_codigo,
                        "descripcion": descripcion,
                        "cantidad": cantidad,
                        "costo_unitario": precio,
                        "moneda": moneda,
                        "importe": importe,
                        "sample": detectar_sample(texto),
                        "nombre_archivo": nombre_archivo,
                        "total_factura_pdf": total_factura_pdf,
                    })
    else:
        # ========== FORMATO ORIGINAL ==========
        es_formato1 = bool(re.search(r'#INV\d{6,}', texto))
        patron_f1 = re.compile(
            r'(\d{8})\s+'
            r'(.+?)\s+'
            r'(\d+)\s+'
            r'\$([\d.]+)\s+'
            r'0%\s+'
            r'\$([\d,]+(?:\.\d{2})?)'
        )
        patron_f2 = re.compile(
            r'^\d+\s+'
            r'(\d{8})\s+'
            r'(.+?)\s+'
            r'[A-Z]{2}\s+'
            r'\d{4}\.\d{2}\.\d{4}\s+'
            r'(\d+)\s+'
            r'EA\s+'
            r'\$([\d.]+)\s+'
            r'\$([\d,]+(?:\.\d{2})?)'
        )
        
        patron = patron_f1 if es_formato1 else patron_f2
        
        for i, linea in enumerate(lineas):
            linea = linea.strip()
            if not linea:
                continue
            
            m = patron.search(linea)
            if not m:
                continue
            
            codigo = m.group(1)
            descripcion = m.group(2).strip()
            cantidad = int(m.group(3))
            precio = float(m.group(4))
            
            if es_formato1 and i + 1 < len(lineas):
                sig_linea = lineas[i + 1].strip()
                if sig_linea and not patron.search(sig_linea) and not any(x in sig_linea.upper() for x in ['TOTAL', 'AMOUNT', 'TAX', 'PLEASE', 'ECCN', 'LICENSE']):
                    if not re.search(r'\d{8}', sig_linea):
                        descripcion = f"{descripcion} {sig_linea}".strip()
            
            importe = round(cantidad * precio, 2)
            
            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "due_days": due_days,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": str(codigo),
                "codigo_producto": codigo,
                "tipo_codigo": tipo_codigo,
                "descripcion": descripcion,
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": moneda,
                "importe": importe,
                "sample": detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER FLOOKY
# ══════════════════════════════════════════════════════════════════

def parse_flooky(pdf_file, marca, proveedor):
    nombre_archivo = pdf_file.name
    
    texto = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                texto += page_text + "\n"
    
    # ════════════════════════════════════════════════════════════
    # CABECERA DESDE TEXTO
    # ════════════════════════════════════════════════════════════
    
    # Invoice
    invoice_match = re.search(r'INVOICE\s+NO\.:\s*(\S+)', texto, re.IGNORECASE)
    invoice = invoice_match.group(1) if invoice_match else None
    
    # Fecha
    fecha_match = re.search(r'INVOICE\s+DATE:\s*(\d{2}-\d{2}-\d{4})', texto, re.IGNORECASE)
    fecha_dt = None
    if fecha_match:
        fecha_str = fecha_match.group(1)
        try:
            fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
        except ValueError:
            try:
                fecha_dt = datetime.strptime(fecha_str, "%m-%d-%Y")
            except ValueError:
                pass
    
    if not invoice or not fecha_dt:
        return []
    
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # ════════════════════════════════════════════════════════════
    # VALORES FIJOS
    # ════════════════════════════════════════════════════════════
    
    incoterm = "FOB"
    moneda = "USD"
    tipo_codigo = "BARCODE"
    total_factura_pdf = _extraer_total_generico(texto)

    # ════════════════════════════════════════════════════════════
    # DETECCIÓN DE FORMATO (¿tiene columna BAR CODE?)
    # ════════════════════════════════════════════════════════════
    
    tiene_barcode = False
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tablas = page.extract_tables()
            for tabla in tablas:
                for fila in tabla:
                    if fila[0] and 'ITEM NO.' in str(fila[0]).upper():
                        if any('BAR CODE' in str(c).upper() for c in fila if c):
                            tiene_barcode = True
                        break
    
    # ════════════════════════════════════════════════════════════
    # EXTRACCIÓN DE ITEMS DESDE TABLA
    # ════════════════════════════════════════════════════════════
    
    registros = []
    contador_codigos = {}  # ← Para manejar duplicados
    
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            tablas = page.extract_tables()
            
            for tabla in tablas:
                # Buscar fila de encabezado
                header_idx = None
                for i, fila in enumerate(tabla):
                    if fila[0] and 'ITEM NO.' in str(fila[0]).upper():
                        header_idx = i
                        break
                
                if header_idx is None:
                    continue
                
                # Determinar índices según formato
                if tiene_barcode:
                    # ITEM(0) | Supplier(1) | PIC(2) | DESC(3) | ITEM_NAME(4) | COLOR(5) | SEGMENT(6) | BARCODE(7) | COUNTRY(8) | COMP(9) | QTY(10) | UNIT(11) | PRICE(12) | AMOUNT(13) | IMG(14)
                    idx_item = 1
                    idx_desc = 3
                    idx_name = 4
                    idx_color = 5
                    idx_barcode = 7
                    idx_qty = 10
                    idx_price = 12
                else:
                    # ITEM(0) | Supplier(1) | PIC(2) | DESC(3) | ITEM_NAME(4) | COLOR(5) | SEGMENT(6) | COUNTRY(7) | COMP(8) | QTY(9) | UNIT(10) | PRICE(11) | AMOUNT(12) | IMG(13)
                    idx_item = 1
                    idx_desc = 3
                    idx_name = 4
                    idx_color = 5
                    idx_barcode = None
                    idx_qty = 9
                    idx_price = 11
                
                # Procesar filas
                for fila in tabla[header_idx + 1:]:
                    if not fila or len(fila) <= idx_item:
                        continue
                    
                    item_code = str(fila[idx_item]).strip() if fila[idx_item] else ""
                    
                    # Saltar vacíos, None, totales
                    if not item_code or item_code == 'None' or 'TOTAL' in str(fila[0]).upper():
                        continue
                    
                    # Contar ocurrencias para manejar duplicados
                    if item_code not in contador_codigos:
                        contador_codigos[item_code] = 0
                    contador_codigos[item_code] += 1
                    
                    # Si es duplicado, agregar sufijo _2, _3, etc.
                    if contador_codigos[item_code] > 1:
                        item_code_unico = f"{item_code}_{contador_codigos[item_code]}"
                    else:
                        item_code_unico = item_code
                    
                    # Extraer campos
                    descripcion_pdf = str(fila[idx_desc]).replace('\n', ' ').strip() if len(fila) > idx_desc and fila[idx_desc] else ""
                    item_name = str(fila[idx_name]).replace('\n', ' ').strip() if len(fila) > idx_name and fila[idx_name] else ""
                    color = str(fila[idx_color]).strip() if len(fila) > idx_color and fila[idx_color] else ""
                    qty_str = str(fila[idx_qty]).strip() if len(fila) > idx_qty and fila[idx_qty] else "0"
                    price_str = str(fila[idx_price]).strip() if len(fila) > idx_price and fila[idx_price] else "$0.00"
                    
                    # Barcode
                    codigo_producto = None
                    if tiene_barcode and idx_barcode is not None:
                        barcode_val = str(fila[idx_barcode]).strip() if len(fila) > idx_barcode and fila[idx_barcode] else ""
                        if barcode_val and barcode_val.isdigit() and len(barcode_val) >= 12:
                            codigo_producto = barcode_val
                    
                    # Construir descripción limpia
                    descripcion = descripcion_pdf
                    if item_name and item_name != descripcion_pdf and item_name not in descripcion:
                        descripcion = f"{descripcion} {item_name}".strip()
                    if color and color.upper() not in descripcion.upper():
                        descripcion = f"{descripcion} {color}".strip()
                    
                    # Limpiar cantidad
                    cantidad = int(qty_str.replace(',', '')) if qty_str.replace(',', '').isdigit() else 0
                    
                    # Limpiar precio
                    precio = float(price_str.replace('$', '').replace(' ', '').replace(',', ''))
                    
                    # ✅ IMPORTE = CANTIDAD * PRECIO UNITARIO
                    importe = round(cantidad * precio, 2)
                    
                    item_id = f"{marca}_{invoice}_{periodo}_{item_code_unico}"
                    
                    registros.append({
                        "id": item_id,
                        "marca": marca,
                        "proveedor": proveedor,
                        "invoice": invoice,
                        "invoice_date": fecha,
                        "due_date": fecha,
                        "po": po,
                        "incoterm": incoterm,           # ← Siempre "FOB"
                        "periodo": periodo,
                        "item": str(item_code_unico),
                        "codigo_producto": codigo_producto,  # ← Barcode si existe, None si no
                        "tipo_codigo": tipo_codigo,     # ← "BARCODE"
                        "descripcion": descripcion,
                        "cantidad": cantidad,
                        "costo_unitario": precio,
                        "moneda": moneda,
                        "importe": importe,
                        "sample": detectar_sample(texto),
                        "nombre_archivo": nombre_archivo,
                        "total_factura_pdf": total_factura_pdf,
                    })
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER LANEIGE
# ══════════════════════════════════════════════════════════════════

def parse_laneige(pdf_file, marca, proveedor):
    from datetime import timedelta
    
    nombre_archivo = pdf_file.name
    
    # ========== TEXTO COMPLETO (para detectar_sample) ==========
    texto_completo = ""
    with pdfplumber.open(pdf_file) as p:
        for page in p.pages:
            page_text = page.extract_text()
            if page_text:
                texto_completo += page_text + "\n"
    
    # ========== CABECERA (PÁGINA 1) ==========
    with pdfplumber.open(pdf_file) as p:
        texto_pag1 = p.pages[0].extract_text()
    
    # Invoice
    inv_match = re.search(r'Invoice No\. and date\s*\n\s*[\w,\s-]+\s+(\d{7,12})', texto_pag1)
    invoice = inv_match.group(1) if inv_match else None
    
    # Fecha
    fecha_match = re.search(r'(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\.(\d{1,2}),(\d{4})', texto_pag1, re.IGNORECASE)
    if not fecha_match or not invoice:
        return []
    
    meses = {'JAN':'01','FEB':'02','MAR':'03','APR':'04','MAY':'05','JUN':'06',
             'JUL':'07','AUG':'08','SEP':'09','OCT':'10','NOV':'11','DEC':'12'}
    mes = meses[fecha_match.group(1).upper()[:3]]
    dia = fecha_match.group(2)
    anio = fecha_match.group(3)
    
    fecha_dt = datetime.strptime(f"{dia}/{mes}/{anio}", "%d/%m/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    due_dt = fecha_dt + timedelta(days=45)
    due = due_dt.strftime("%d/%m/%Y")
    
    incoterm = "EXW"
    # Extraer PO del nombre del archivo (formato: {po}_LANEIGE_{invoice}_{periodo}.pdf)
    po = None
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_LANEIGE_\d+_\d{6}\.pdf$', nombre_archivo)
    if po_match:
        po = po_match.group(1)
    total_factura_pdf = _extraer_total_generico(texto_completo)
    
    # ========== PATRONES ==========
    # Patrón original: números sin espacios
    patron_original = r"^(\d{10})\s+(\d{9,13})\s+(\d{9,13})\s+(.+?)\s+([\d\s,]+?)\s+EA\s+([\d\s,]+?\.\d{2})\s+[\d\s,]+\.\d{2}(?:\s+\d+)?$"
    
    # Patrón alternativo: números con espacios (ej: 1 ,186, 9 .60)
    patron_alternativo = r"^(\d{10})\s+(\d{9,13})\s+(\d{9,13})\s+(.+?)\s+([\d\s,]+?)\s+EA\s+([\d\s.]+?)\s+([\d\s,]+\.\d{2})"
    
    registros = []
    
    # ========== BUSCAR ITEMS EN TODAS LAS PÁGINAS ==========
    with pdfplumber.open(pdf_file) as p:
        for num_pagina, page in enumerate(p.pages, 1):
            texto_pagina = page.extract_text()
            if not texto_pagina:
                continue
            
            # Verificar si es Packing List (páginas 3+ suelen serlo)
            primeras_lineas = texto_pagina.strip().split('\n')[:3]
            if any("PACKING LIST" in l.upper() for l in primeras_lineas):
                continue
            
            # Verificar si tiene encabezado de items (HS-NO., BARCODE, etc.)
            tiene_encabezado_items = bool(re.search(r'HS-NO\.\s+BARCODE\s+ITEM\s+NO\.', texto_pagina))
            
            lineas = [l.strip() for l in texto_pagina.split('\n') if l.strip()]
            
            for linea in lineas:
                # Saltar encabezados
                if re.match(r'^(HS-NO\.|U/PRICE|BARCODE|\(USD\)|COMMERCIAL INVOICE)', linea):
                    continue
                
                # Intentar primero patrón original
                m = re.match(patron_original, linea)
                patron_usado = "original"
                
                # Si no, intentar patrón alternativo
                if not m:
                    m = re.match(patron_alternativo, linea)
                    patron_usado = "alternativo"
                
                if not m:
                    continue
                
                hs_code = m.group(1)
                num1 = m.group(2)
                num2 = m.group(3)
                
                # Determinar cuál es item y cuál es barcode
                if len(num1) >= 13:
                    barcode = num1
                    item_no = num2
                else:
                    item_no = num1
                    barcode = num2
                
                # La descripción en patrón alternativo incluye el CONTENT al final
                descripcion_con_content = m.group(4)
                qty_raw = m.group(5)
                
                if patron_usado == "original":
                    precio_raw = m.group(6)
                else:
                    precio_raw = m.group(6)  # En alternativo, grupo 6 es precio, grupo 7 es amount
                
                # Separar descripción del CONTENT (formato: "LA LSM BERRY 20G 2 0 G")
                # El content es lo último: número + G/ML/EA
                desc_match = re.match(r"(.+?)\s+(\d[\d\s]*)\s*(?:G|ML|EA)\s*$", descripcion_con_content)
                if desc_match:
                    descripcion = desc_match.group(1).strip()
                    content = desc_match.group(2).replace(" ", "")
                else:
                    descripcion = descripcion_con_content.strip()
                    content = ""
                
                # Limpiar cantidad
                qty = int(qty_raw.replace(" ", "").replace(",", ""))
                
                # Limpiar precio
                precio = float(precio_raw.replace(" ", "").replace(",", ""))
                
                # Verificar que sea un precio razonable (evitar capturar totals)
                if precio > 1000:
                    continue
                
                importe = round(qty * precio, 2)
                
                registros.append({
                    "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_no}_{barcode}",
                    "marca": marca,
                    "proveedor": proveedor,
                    "invoice": invoice,
                    "invoice_date": fecha,
                    "due_date": due,
                    "po": po,
                    "incoterm": incoterm,
                    "periodo": periodo,
                    "item": item_no,
                    "codigo_producto": barcode,
                    "tipo_codigo": "BARCODE",
                    "descripcion": descripcion,
                    "cantidad": qty,
                    "costo_unitario": precio,
                    "moneda": "USD",
                    "importe": importe,
                    "sample": detectar_sample(texto_completo),
                    "nombre_archivo": nombre_archivo,
                    "total_factura_pdf": total_factura_pdf,
                })
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER KOCOSTAR 
# ══════════════════════════════════════════════════════════════════

def parse_kocostar(pdf_file, marca, proveedor):
    nombre_archivo = pdf_file.name
    
    texto = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                texto += page_text + "\n"
    
    # ════════════════════════════════════════════════════════════
    # CABECERA
    # ════════════════════════════════════════════════════════════
    
    # Invoice: PI No. > P/I No. > FM##-XX##-#### (con letras)
    invoice_match = re.search(r'PI No\.\s+(\S+)', texto)
    if not invoice_match:
        invoice_match = re.search(r'P/I No\.\s+(\S+)', texto)
    if not invoice_match:
        invoice_match = re.search(r'(FM\d{2}-[A-Za-z]+\d{2}-\d{4})', texto)
    invoice = invoice_match.group(1) if invoice_match else None
    
    # FECHA: MMM-DD-YYYY > DD-MM-YYYY > MM-DD-YYYY
    fecha_match = re.search(r'Date\s+([A-Za-z]+-\d{1,2}-\d{4})', texto)
    fecha_dt = None
    if fecha_match:
        meses = {'Jan':'01','Feb':'02','Mar':'03','Apr':'04','May':'05','Jun':'06',
                 'Jul':'07','Aug':'08','Sep':'09','Oct':'10','Nov':'11','Dec':'12'}
        partes = fecha_match.group(1).split('-')
        mes = meses.get(partes[0].capitalize()[:3], '01')
        dia = partes[1].zfill(2)
        anio = partes[2]
        try:
            fecha_dt = datetime.strptime(f"{anio}-{mes}-{dia}", "%Y-%m-%d")
        except ValueError:
            pass
    else:
        fecha_match = re.search(r'Date\s+(\d{2}-\d{2}-\d{4})', texto)
        if fecha_match:
            fecha_str = fecha_match.group(1)
            try:
                fecha_dt = datetime.strptime(fecha_str, "%d-%m-%Y")
            except ValueError:
                try:
                    fecha_dt = datetime.strptime(fecha_str, "%m-%d-%Y")
                except ValueError:
                    pass
    
    if not invoice or not fecha_dt:
        return []
    
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # ════════════════════════════════════════════════════════════
    # VALORES FIJOS
    # ════════════════════════════════════════════════════════════
    
    incoterm = "FOB"
    moneda = "USD"
    tipo_codigo = "EAN"
    total_factura_pdf = _extraer_total_generico(texto)

    # ════════════════════════════════════════════════════════════
    # PATRONES (4 FORMATOS)
    # ════════════════════════════════════════════════════════════
    
    # F4: CODE + SKU + Desc + EAN + Unit + Qty + Carton + $ d .cc + $ d cc.cc
    # KO05B 1019810 Mascarilla Facial 4 Mask Hyaluronic 8809328325183 400 1,600 4 $ 0 .35 $ 5 60.00
    patron_f4 = re.compile(
        r'(KO\d+[A-Z]?)\s+'             # 1. CODE
        r'(\d{7})\s+'                    # 2. SKU
        r'(.+?)\s+'                      # 3. Descripción
        r'(8809\d{9})\s+'               # 4. EAN
        r'(\d+)\s+'                      # 5. Unit
        r'([\d,]+)\s+'                   # 6. Qty pcs ← CANTIDAD REAL
        r'([\d,]+)\s+'                   # 7. Carton
        r'\$\s*(\d+)\s*\.\s*(\d+)\s+'  # 8,9. Price (dólares, centavos)
        r'\$\s*(\d+)\s*(\d+\.\d{2})'   # 10,11. Amount (dólares, centavos)
    )
    
    # F3: KOCOSTAR al inicio + SKU + Korea (sin $ en precios)
    # KOCOSTAR4 Mask Hyaluronic 3307.90.9000 8809328325183 1019810 400 Korea 5,200 13 0.35 1,820.00
    patron_f3 = re.compile(
        r'KOCOSTAR\s*(.+?)\s+'
        r'(\d{4}\.\d{2}\.\d{4})\s+'
        r'(\d{13})\s+'
        r'(\d{7})\s+'
        r'(\d+)\s+'
        r'Korea\s+'
        r'([\d,]+)\s+'
        r'([\d,]+)\s+'
        r'([\d.]+)\s+'
        r'([\d,]+(?:\.\d{2})?)'
    )
    
    # F2: Sin KOCOSTAR al inicio, con $ en precios
    # Mascarilla Facial 4 Mask Collagen 3307.90.9000 8809328325190 400 6,400 16 $ 0.35 $ 2 ,240.00
    patron_f2 = re.compile(
        r'(.+?)\s+'
        r'(\d{4}\.\d{2}\.\d{4})\s+'
        r'(\d{13})\s+'
        r'(\d+)\s+'
        r'([\d,]+)\s+'
        r'([\d,]+)\s+'
        r'\$\s*([\d.]+)\s+'
        r'\$\s*([\d\s,]+(?:\.\d{2})?)'
    )
    
    # F1: CODE + SKU + descripción (antiguo, precios juntos $0.35)
    # KO05B  1234567  Mascarilla Facial Collagen  8809328325190  5200  $0.35
    patron_f1 = re.compile(
        r'(KO\d+[A-Z]?)\s+'
        r'(\d{7})\s+'
        r'(.+?)\s+'
        r'(8809\d{9})\s+'
        r'([\d,]+)\s+'
        r'\$\s*([\d.]+)'
    )
    
    def limpiar_numero_espaciado(valor):
        limpio = re.sub(r'[^\d.]', '', valor)
        return float(limpio) if limpio else 0.0
    
    # ════════════════════════════════════════════════════════════
    # PARSEO DE ITEMS
    # ════════════════════════════════════════════════════════════
    
    registros = []
    lineas = texto.split('\n')
    lineas_items = [l.strip() for l in lineas if l.strip() and '8809' in l]
    lineas_items = [l for l in lineas_items if not any(x in l.upper() for x in ['DESCRIPTION', 'SERIES', 'TOTAL', 'AMOUNT', 'PRODUCTO', 'BRAND'])]
    
    for linea in lineas_items:
        descripcion = ""
        ean = None
        cantidad = None
        precio = None
        
        # Intentar F4 (precios separados: $ 0 .35)
        m = patron_f4.search(linea)
        if m:
            descripcion = m.group(3).strip()
            ean = m.group(4)
            cantidad = int(m.group(6).replace(',', ''))
            precio = float(f"{m.group(8)}.{m.group(9)}")
        else:
            # Intentar F3 (KOCOSTAR + SKU + Korea)
            m = patron_f3.search(linea)
            if m:
                descripcion = f"KOCOSTAR {m.group(1).strip()}"
                ean = m.group(3)
                cantidad = int(m.group(6).replace(',', ''))
                precio = float(m.group(8))
            else:
                # Intentar F2 (con $ en precios)
                m = patron_f2.search(linea)
                if m:
                    descripcion = m.group(1).strip()
                    ean = m.group(3)
                    cantidad = int(m.group(5).replace(',', ''))
                    precio = float(m.group(7))
                else:
                    # Intentar F1 (CODE + SKU antiguo)
                    m = patron_f1.search(linea)
                    if m:
                        descripcion = m.group(3).strip()
                        ean = m.group(4)
                        cantidad = int(m.group(5).replace(',', ''))
                        precio = float(m.group(6))
                    else:
                        # Fallback genérico
                        ean_match = re.search(r'(8809\d{9})', linea)
                        if not ean_match:
                            continue
                        
                        ean = ean_match.group(1)
                        
                        # Buscar todos los números
                        numeros = re.findall(r'[\d,]+', linea)
                        numeros_limpios = []
                        for n in numeros:
                            n_clean = n.replace(',', '')
                            if n_clean.isdigit():
                                numeros_limpios.append(int(n_clean))
                        
                        numeros_filtrados = [n for n in numeros_limpios if n != int(ean)]
                        numeros_filtrados = [n for n in numeros_filtrados if n >= 100 or n in [35, 60, 75, 82]]
                        
                        cantidad = max(numeros_filtrados) if numeros_filtrados else None
                        
                        precio_match = re.search(r'\$\s*(\d+)\s*\.\s*(\d+)', linea)
                        if precio_match:
                            precio = float(f"{precio_match.group(1)}.{precio_match.group(2)}")
                        else:
                            precio_match = re.search(r'\b([0-9]+\.[0-9]{2})\b', linea)
                            if precio_match:
                                precio = float(precio_match.group(1))
                            else:
                                for n in numeros_limpios:
                                    if n in [35, 60, 75, 82]:
                                        precio = n / 100
                                        break
                        
                        if not descripcion:
                            # Extraer texto antes del EAN como descripción
                            partes = linea.split(ean)
                            if len(partes) >= 2:
                                descripcion = partes[0].strip()
                                # Quitar CODE y SKU si están al inicio
                                descripcion = re.sub(r'^KO\d+[A-Z]?\s+\d{7}\s+', '', descripcion).strip()
        
        if not ean or not cantidad or not precio:
            continue
        
        # ✅ IMPORTE = CANTIDAD * PRECIO UNITARIO
        importe_calculado = round(cantidad * precio, 2)
        
        item_id = f"{marca}_{invoice}_{periodo}_{ean}_{ean}"
        
        registros.append({
            "id": item_id,
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": fecha,
            "po": po,
            "incoterm": incoterm,           # ← Siempre "FOB"
            "periodo": periodo,
            "item": str(ean),
            "codigo_producto": ean,
            "tipo_codigo": tipo_codigo,     # ← Siempre "EAN"
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": importe_calculado,
            "sample": detectar_sample(texto),
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })
    
    return registros
 
# ══════════════════════════════════════════════════════════════════
# PARSER COSRX 
# ══════════════════════════════════════════════════════════════════

def parse_cosrx(pdf_file, marca, proveedor):
    """
    Parsea facturas de COSRX
    Soporta:
    - Items que empiezan con COSRX: COSRX 113020205 Low pH... 126 $4.90 $617.40
    - Items sin COSRX: 113020205 Low pH Good Morning Gel Cleanser 150 mL 630 $4.90 $3,087.00
    """
    nombre_archivo = pdf_file.name
    
    texto = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                texto += page_text + "\n"
    
    # ========== CABECERA ==========
    invoice = None
    
    # Formato 1: GLAMBRANDS_08 (IMP154)
    inv_match = re.search(r'(GLAMBRANDS_\d+)\s+\(([^)]+)\)', texto)
    if inv_match:
        invoice = f"{inv_match.group(1)}_{inv_match.group(2)}"
    
    # Formato 2: GLAMBRANDS_2356_02 o GLAMBRANDS_1850_05(FOC)
    if not invoice:
        inv_match = re.search(r'(GLAMBRANDS_\d+(?:_\d+)?)(?:\(FOC\))?', texto)
        if inv_match:
            invoice = inv_match.group(1)
            if '(FOC)' in texto:
                invoice = f"{invoice}_FOC"
    
    if not invoice:
        return []
    
    # Fecha: YYYY-MM-DD
    fecha_match = re.search(r'(\d{4}-\d{2}-\d{2})', texto)
    if not fecha_match:
        return []
    
    fecha_dt = datetime.strptime(fecha_match.group(1), "%Y-%m-%d")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    anio = str(fecha_dt.year)
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    due = fecha
    due_days = 0
    
    # Incoterm
    incoterm = "FOB"
    if re.search(r'\bFCA\b', texto, re.IGNORECASE):
        incoterm = "FCA"
    elif re.search(r'\bEXW\b', texto, re.IGNORECASE):
        incoterm = "EXW"
    elif re.search(r'\bCIF\b', texto, re.IGNORECASE):
        incoterm = "CIF"
    
    moneda = "USD"
    total_factura_pdf = _extraer_total_generico(texto)

    # ========== ITEMS ==========
    registros = []
    lineas = texto.split('\n')

    # Encontrar el inicio de la sección de items (después de "Description of Goods")
    inicio_items = None
    for i, linea in enumerate(lineas):
        if 'Description of Goods' in linea:
            inicio_items = i + 1
            break
    
    if inicio_items is None:
        return []
    
    # Patrón para items: CODIGO(9digitos) DESCRIPCION [VOLUMEN] CANTIDAD $PRECIO $AMOUNT
    patron_item = re.compile(
        r'^(\d{9})\s+'                            # 1. Código 9 dígitos
        r'(.+?)\s+'                               # 2. Descripción (non-greedy)
        r'([\d,]+(?:\s*[\d,]+)*)\s+'             # 3. Cantidad
        r'\$?([\d.]+)\s+'                         # 4. Precio
        r'\$?([\d,]+(?:\.\d{2})?)'               # 5. Amount
    )
    
    for i in range(inicio_items, len(lineas)):
        linea = lineas[i].strip()
        
        # Saltar líneas no relevantes
        if not linea:
            continue
        if linea == 'COSRX':
            continue
        if linea.startswith('COSRX '):
            # Quitar el prefijo COSRX para procesar
            linea = linea[6:].strip()
        if 'TOTAL' in linea.upper():
            break
        if 'Account Information' in linea:
            break
        if 'Bank' in linea and 'Hana' in linea:
            break
        
        m = patron_item.match(linea)
        if m:
            codigo = m.group(1)
            descripcion = m.group(2).strip()
            cantidad_raw = m.group(3)
            precio = float(m.group(4))
            
            # Limpiar cantidad
            cantidad = int(cantidad_raw.replace(',', '').replace(' ', ''))

            # precio == 0 solo ocurre acá si el regex capturó un '0'/'0.00' real
            # (el patrón exige dígitos, un '-' de relleno nunca llega a matchear),
            # así que un precio explícito en 0 (muestra) no se descarta.
            if cantidad == 0:
                continue
            if precio > 10000:
                continue
            
            descripcion = re.sub(r'\s+', ' ', descripcion).strip()
            importe = round(cantidad * precio, 2)
            
            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "due_days": due_days,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": codigo,
                "codigo_producto": codigo,
                "tipo_codigo": "SKU",
                "descripcion": descripcion,
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": moneda,
                "importe": importe,
                "sample": detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER BOLDIFY
# ══════════════════════════════════════════════════════════════════

def parse_boldify(pdf_file, marca, proveedor):
    """
    Parsea facturas de BOLDIFY
    Soporta 2 formatos:
    - Formato original: Items Quantity Price Amount
    - Formato nuevo: Product or service SKU Qty Rate Amount
    """
    nombre_archivo = pdf_file.name
    
    texto = ""
    with pdfplumber.open(pdf_file) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                texto += page_text + "\n"
    
    # ========== DETECCIÓN DE FORMATO ==========
    es_formato_nuevo = "Product or service" in texto and "SKU" in texto
    
    if es_formato_nuevo:
        # ========== FORMATO NUEVO ==========
        return _parse_boldify_nuevo(pdf_file, marca, proveedor, texto, nombre_archivo)
    else:
        # ========== FORMATO ORIGINAL ==========
        return _parse_boldify_original(pdf_file, marca, proveedor, texto, nombre_archivo)


def _parse_boldify_nuevo(pdf_file, marca, proveedor, texto, nombre_archivo):
    """Parsea el formato nuevo: Product or service SKU Qty Rate Amount"""
    
    # ========== CABECERA ==========
    # Invoice: CI0409GL
    invoice_match = re.search(r'Invoice\s+no\.:\s*(\S+)', texto, re.IGNORECASE)
    invoice = invoice_match.group(1) if invoice_match else None
    
    # Fecha: 04/09/2026
    fecha_match = re.search(r'Invoice\s+date:\s*(\d{2}/\d{2}/\d{4})', texto, re.IGNORECASE)
    if not fecha_match:
        return []
    
    fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Due date: Due on receipt → misma fecha
    due = fecha
    due_days = 0
    
    terms_match = re.search(r'Terms:\s*(.+?)(?:\n|$)', texto, re.IGNORECASE)
    if terms_match:
        terms = terms_match.group(1).strip()
        if 'net' in terms.lower():
            net_match = re.search(r'Net\s+(\d+)', terms, re.IGNORECASE)
            if net_match:
                due_days = int(net_match.group(1))
                due_dt = fecha_dt + timedelta(days=due_days)
                due = due_dt.strftime("%d/%m/%Y")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # Incoterm
    incoterm = "EXW"
    if re.search(r'\bFOB\b', texto, re.IGNORECASE):
        incoterm = "FOB"
    
    moneda = "USD"
    total_factura_pdf = _extraer_total_generico(texto)

    # ========== ITEMS ==========
    registros = []

    # Buscar sección de items (después de "Product or service SKU Qty Rate Amount" hasta "Total")
    items_section = re.search(
        r'Product\s+or\s+service\s+SKU\s+Qty\s+Rate\s+Amount\s*\n(.*?)(?:Total|$)',
        texto, re.DOTALL | re.IGNORECASE
    )
    
    if not items_section:
        return []
    
    items_text = items_section.group(1)
    lineas = [l.strip() for l in items_text.split('\n') if l.strip()]
    
    for linea in lineas:
        # Patrón: DESCRIPCION SKU CANTIDAD $PRECIO $AMOUNT
        m = re.match(
            r'^(.+?)\s+'                     # 1. Descripción
            r'([A-Z0-9_]+)\s+'               # 2. SKU
            r'([\d,]+)\s+'                   # 3. Cantidad
            r'\$?([\d.]+)\s+'                # 4. Precio
            r'\$?([\d,]+(?:\.\d{2})?)',      # 5. Amount
            linea
        )
        
        if m:
            descripcion = m.group(1).strip()
            item_code = m.group(2).strip()
            cantidad = int(m.group(3).replace(',', ''))
            precio = float(m.group(4))

            # Validaciones (el regex exige dígitos para precio, así que un
            # precio explícito en 0 -muestra- ya no se confunde con basura)
            if cantidad == 0:
                continue
            if precio > 10000:
                continue
            
            importe = round(cantidad * precio, 2)
            
            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "due_days": due_days,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": item_code,
                "codigo_producto": item_code,
                "tipo_codigo": "SKU",
                "descripcion": descripcion,
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": moneda,
                "importe": importe,
                "sample": "Y" if "SAMPLES" in texto.upper() or "SAMPLE" in texto.upper() else detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })
    
    return registros


def _parse_boldify_original(pdf_file, marca, proveedor, texto, nombre_archivo):
    """Parsea el formato original: Items Quantity Price Amount"""
    
    # ========== CABECERA ==========
    invoice_match = re.search(r'Bill to.*?Invoice\s+([A-Z0-9]+(?:-[A-Z]+)?)', texto, re.IGNORECASE | re.DOTALL)
    invoice = invoice_match.group(1) if invoice_match else None
    
    fecha_match = re.search(r'Date\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})', texto, re.IGNORECASE)
    if not fecha_match:
        return []
    
    fecha_dt = datetime.strptime(fecha_match.group(1), "%b %d, %Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    due = fecha
    due_days = 0
    
    due_match = re.search(r'Due date\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})', texto, re.IGNORECASE)
    if due_match:
        due = datetime.strptime(due_match.group(1), "%b %d, %Y").strftime("%d/%m/%Y")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    incoterm = "EXW"
    incoterm_match = re.search(r'INCOTERM:\s*(\w+)', texto, re.IGNORECASE)
    if incoterm_match:
        incoterm = incoterm_match.group(1)
    if re.search(r'\bFOB\b', texto, re.IGNORECASE):
        incoterm = "FOB"
    
    moneda = "USD"
    total_factura_pdf = _extraer_total_generico(texto)

    # ========== ITEMS ==========
    patron_item_linea = re.compile(
        r'([A-Z0-9_]+)\s+(\d+)\s+\$([\d,.]+)\s+\$([\d,.]+)',
        re.IGNORECASE
    )
    
    registros = []
    
    items_section_match = re.search(r'Items\s+Quantity\s+Price\s+Amount(.*?)Subtotal', texto, re.DOTALL | re.IGNORECASE)
    
    if not items_section_match:
        return []
    
    items_texto = items_section_match.group(1)
    lineas = [l.strip() for l in items_texto.split('\n') if l.strip()]
    
    i = 0
    while i < len(lineas):
        linea_actual = lineas[i]
        match_datos = patron_item_linea.search(linea_actual)
        
        if match_datos:
            codigo = match_datos.group(1)
            cantidad = int(match_datos.group(2))
            precio = float(match_datos.group(3).replace(',', ''))
            importe_calculado = round(cantidad * precio, 2)
            
            descripcion = ""
            if i + 1 < len(lineas):
                sig_linea = lineas[i + 1]
                if not patron_item_linea.search(sig_linea):
                    descripcion = sig_linea
                    i += 1
            
            descripcion = re.sub(r'\s+', ' ', descripcion).strip()
            
            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "due_days": due_days,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": codigo,
                "codigo_producto": codigo,
                "tipo_codigo": "SKU",
                "descripcion": descripcion,
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": moneda,
                "importe": importe_calculado,
                "sample": "Y" if "SAMPLES" in texto.upper() else detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })
        
        i += 1
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER BEAUTY
# ══════════════════════════════════════════════════════════════════

def parse_beauty(pdf_file, marca, proveedor):

    nombre_archivo = pdf_file.name

    texto = extraer_texto_pdf(pdf_file)

    # ========== EXTRACCIÓN DE INVOICE ==========
    invoice = None
    
    # Patrón 1: "DateInvoice #4/23/202532139" (fecha + número pegados)
    inv_match = re.search(r'Invoice\s*#?\s*[\d/]+?(\d{5,})', texto)
    if inv_match:
        invoice = inv_match.group(1).zfill(7)
    
    # Patrón 2: "#0039259" (número con # delante)
    if not invoice:
        inv_match = re.search(r'#\s*(\d{5,})', texto)
        if inv_match:
            invoice = inv_match.group(1).zfill(7)
    
    # Patrón 3: Buscar en tablas del PDF
    if not invoice:
        with pdfplumber.open(pdf_file) as p:
            if p.pages:
                tablas = p.pages[0].extract_tables()
                for tabla in tablas:
                    if tabla:
                        for fila in tabla:
                            for celda in fila:
                                if celda and isinstance(celda, str):
                                    nums = re.findall(r'\b(\d{5,})\b', celda)
                                    for n in nums:
                                        if n not in ['90670', '20601266416', '15012', '15036', '90210', '90660']:
                                            invoice = n.zfill(7)
                                            break
                                if invoice:
                                    break
                        if invoice:
                            break
                    if invoice:
                        break

    if not invoice:
        print(f"   ⚠ No se pudo extraer invoice de {nombre_archivo}")
        return []

    # ========== EXTRACCIÓN DE FECHA ==========
    fecha_raw = None
    
    # Buscar fecha en formato MM/DD/YYYY
    fecha_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', texto)
    if fecha_match:
        fecha_raw = fecha_match.group(1)
    
    if not fecha_raw:
        print(f"   ⚠ No se pudo extraer fecha de {nombre_archivo}")
        return []

    fecha_dt = datetime.strptime(fecha_raw, "%m/%d/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")

    # ========== EXTRACCIÓN DE DUE DATE (Net XX) ==========
    due_days = 0
    due = fecha  # Por defecto igual a invoice_date
    
    # Si contiene "Net 60" → due_days = 60 y due_date = invoice_date + 60
    if 'Net 60' in texto:
        due_days = 60
        due_dt = fecha_dt + timedelta(days=60)
        due = due_dt.strftime("%d/%m/%Y")
    else:
        # Si no hay Net, buscar Due Date explícito
        due_match = re.search(r'Due\s+Date:\s*(\d{1,2}/\d{1,2}/\d{4})', texto)
        if due_match:
            due = datetime.strptime(due_match.group(1), "%m/%d/%Y").strftime("%d/%m/%Y")

    # ========== EXTRACCIÓN DE PO ==========
    # Extraer PO del nombre del archivo (formato: {po}_BEAUTY_CREATIONS_{invoice}_{periodo}.pdf)
    po = None
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_BEAUTY_CREATIONS_\d+_\d{6}\.pdf$', nombre_archivo)
    if po_match:
        po = po_match.group(1)
        print(f"   📦 PO extraído del nombre: {po}")

    # ========== EXTRACCIÓN DE INCOTERM (REGLA SIMPLE: FOB o EXW) ==========
    incoterm = "EXW"  # Default
    
    # Si contiene FOB → FOB, sino EXW
    if re.search(r'\bFOB\b', texto, re.IGNORECASE):
        incoterm = "FOB"

    total_factura_pdf = _extraer_total_generico(texto)

    # ========== DETECCIÓN DE FORMATO ==========
    es_formato_nuevo = "Item Code" in texto and ("Description UPC" in texto or "Description" in texto)
    
    registros = []

    if es_formato_nuevo:
        # ========== FORMATO NUEVO: Item Code | Description | UPC | Quantity | Unit Price USD | Amount USD ==========
        
        # Procesar página por página
        with pdfplumber.open(pdf_file) as p:
            for page_num, page in enumerate(p.pages, 1):
                page_text = page.extract_text()
                if not page_text:
                    continue
                
                # Si la página solo tiene números sueltos, saltarla
                lineas_pagina = [l.strip() for l in page_text.split('\n') if l.strip()]
                lineas_con_texto = [l for l in lineas_pagina if re.search(r'[A-Za-z]{3,}', l)]
                if len(lineas_con_texto) < 3:
                    continue
                
                # Buscar la sección de items en esta página (soporta varios encabezados)
                items_section = re.search(
                    r'(?:Item\s+Code\s+Description\s+UPC|Quantity\s+Item\s+Description\s+UPC)\s+(?:Quantity\s+Unit\s+Price\s+USD\s+Amount\s+USD|Rate\s+Amount)(.*?)(?:\*LOS PRODUCTOS|\*INCOTERM|Total|Payments/Credits|Balance Due|Due Date|Subtotal|$)',
                    page_text, re.DOTALL | re.IGNORECASE
                )
                
                if not items_section:
                    continue
                
                items_text = items_section.group(1)
                
                # Dividir en líneas y limpiar
                lineas = [l.strip() for l in items_text.split('\n') if l.strip()]
                
                # Filtrar líneas no relevantes
                lineas_filtradas = []
                for l in lineas:
                    # Saltar encabezados repetidos
                    if re.match(r'^(Quantity\s+Unit|Unit\s+Price\s+USD|Item\s+Code|Quantity\s+Item)', l, re.IGNORECASE):
                        continue
                    # Saltar líneas que solo contienen metadatos
                    if any(x in l.upper() for x in ['*LOS PRODUCTOS', '*INCOTERM', 'TOTAL', 'PAYMENTS/CREDITS', 'BALANCE DUE', 'SUBTOTAL', 'MERCURIO', 'DUE DATE', 'SHIPPING']):
                        continue
                    # Saltar líneas vacías o muy cortas
                    if len(l) < 10:
                        continue
                    lineas_filtradas.append(l)
                
                # Reconstruir items (un item puede ocupar 2 líneas)
                items_reconstruidos = []
                buffer = None
                
                for l in lineas_filtradas:
                    # Detectar si es inicio de nuevo item
                    es_nuevo_item = bool(re.match(r'^[A-Z0-9][A-Z0-9\-]+(?:\s)', l))
                    
                    if es_nuevo_item:
                        if buffer:
                            items_reconstruidos.append(buffer)
                        buffer = l
                    else:
                        if buffer:
                            buffer += ' ' + l
                        else:
                            pass
                
                if buffer:
                    items_reconstruidos.append(buffer)
                
                # Parsear cada item
                for item_text in items_reconstruidos:
                    # Limpiar "..." que indican continuación
                    item_limpio = item_text.replace('...', ' ').strip()
                    item_limpio = re.sub(r'\s+', ' ', item_limpio)
                    
                    # Intentar extraer con patrón principal (formato nuevo)
                    m = re.match(
                        r'^([A-Z0-9][A-Z0-9\-]+)\s+'           # 1. Item Code
                        r'(.+?)\s+'                              # 2. Descripción
                        r'(\d[\d\s]*\d{3})\s+'                  # 3. UPC
                        r'([\d,]+)\s+'                           # 4. Cantidad
                        r'([\d.]+)\s+'                           # 5. Precio unitario
                        r'([\d,]+(?:\.\d{2})?)',                 # 6. Amount
                        item_limpio
                    )
                    
                    if not m:
                        # Patrón alternativo: UPC sin espacios
                        m = re.match(
                            r'^([A-Z0-9][A-Z0-9\-]+)\s+'        # 1. Item Code
                            r'(.+?)\s+'                           # 2. Descripción
                            r'(\d{10,14})\s+'                     # 3. UPC
                            r'([\d,]+)\s+'                        # 4. Cantidad
                            r'([\d.]+)\s+'                        # 5. Precio
                            r'([\d,]+(?:\.\d{2})?)',              # 6. Amount
                            item_limpio
                        )
                    
                    if not m:
                        # Patrón para formato alternativo: CANTIDAD CODIGO DESCRIPCION UPC PRECIO AMOUNT
                        m = re.match(
                            r'^([\d,]+)\s+'                       # 1. Cantidad
                            r'([A-Z0-9][A-Z0-9\-]+)\s+'          # 2. Item Code
                            r'(.+?)\s+'                            # 3. Descripción
                            r'(\d{10,14})\s+'                      # 4. UPC
                            r'\$?([\d.]+)\s*(?:USD)?\s*'          # 5. Precio
                            r'\$?([\d,]+(?:\.\d{2})?)',           # 6. Amount
                            item_limpio
                        )
                        if m:
                            cantidad = int(m.group(1).replace(',', ''))
                            item_code = m.group(2).strip()
                            descripcion = m.group(3).strip()
                            upc = m.group(4).replace(' ', '')
                            precio = float(m.group(5))

                            # precio == 0 es válido (muestra); el regex ya exige dígitos
                            if cantidad > 0 and upc.isdigit() and len(upc) >= 10:
                                descripcion = re.sub(r'\s+', ' ', descripcion).strip()
                                importe = round(cantidad * precio, 2)
                                
                                registros.append({
                                    "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}_{upc}",
                                    "marca": marca,
                                    "proveedor": proveedor,
                                    "invoice": invoice,
                                    "invoice_date": fecha,
                                    "due_date": due,
                                    "due_days": due_days,
                                    "po": po,
                                    "incoterm": incoterm,
                                    "periodo": periodo,
                                    "item": item_code,
                                    "codigo_producto": upc,
                                    "tipo_codigo": "UPC",
                                    "descripcion": descripcion,
                                    "cantidad": cantidad,
                                    "costo_unitario": precio,
                                    "moneda": "USD",
                                    "importe": importe,
                                    "sample": detectar_sample(texto),
                                    "nombre_archivo": nombre_archivo,
                                    "total_factura_pdf": total_factura_pdf,
                                })
                            continue
                    
                    if m:
                        item_code = m.group(1).strip()
                        descripcion = m.group(2).strip()
                        upc = m.group(3).replace(' ', '')
                        cantidad = int(m.group(4).replace(',', ''))
                        precio = float(m.group(5))

                        # precio == 0 es válido (muestra); el regex ya exige dígitos
                        if cantidad == 0:
                            continue
                        
                        if not upc.isdigit() or len(upc) < 10:
                            continue
                        
                        descripcion = re.sub(r'\s+', ' ', descripcion).strip()
                        if descripcion.startswith(item_code):
                            descripcion = descripcion[len(item_code):].strip()
                        
                        importe = round(cantidad * precio, 2)
                        
                        registros.append({
                            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}_{upc}",
                            "marca": marca,
                            "proveedor": proveedor,
                            "invoice": invoice,
                            "invoice_date": fecha,
                            "due_date": due,
                            "due_days": due_days,
                            "po": po,
                            "incoterm": incoterm,
                            "periodo": periodo,
                            "item": item_code,
                            "codigo_producto": upc,
                            "tipo_codigo": "UPC",
                            "descripcion": descripcion,
                            "cantidad": cantidad,
                            "costo_unitario": precio,
                            "moneda": "USD",
                            "importe": importe,
                            "sample": detectar_sample(texto),
                            "nombre_archivo": nombre_archivo,
                            "total_factura_pdf": total_factura_pdf,
                        })

    else:
        # ========== FORMATO ORIGINAL: Quantity Item Description ==========
        inicio = re.search(r"Quantity\s+Item\s+Description", texto)
        if not inicio:
            print(f"   ⚠ No se encontró sección de items en {nombre_archivo}")
            return []

        texto_detalle = texto[inicio.end():]
        lineas = [l.strip() for l in texto_detalle.split("\n") if l.strip()]

        bloques = []
        actual = []

        for l in lineas:
            if any(x in l for x in ["Subtotal", "Total"]):
                continue
            if re.match(r"^\d{6,7}$", l.strip()):
                continue

            if re.match(r"^\d[\d,]*\s+[A-Z0-9\-]+[\s$]", l) or re.match(r"^\d[\d,]*\s+[A-Z0-9\-]+\s", l):
                if actual:
                    bloques.append(actual)
                actual = [l]
            else:
                if actual:
                    actual.append(l)

        if actual:
            bloques.append(actual)

        for b in bloques:
            bloque_texto = ' '.join(b)

            upc = ""
            precio = 0.0
            cantidad = 0
            item = ""
            descripcion = ""

            m = re.match(
                r"^([\d,]+)\s+([A-Z0-9\-]+)\s+(.*?)\s+(\d{10,14})\s+\$(\d+\.\d{2})\s+USD",
                bloque_texto
            )
            if m:
                cantidad = int(m.group(1).replace(",", ""))
                item = m.group(2)
                descripcion = m.group(3).strip()
                upc = m.group(4)
                precio = float(m.group(5))

            if not m:
                m = re.match(
                    r"^([\d,]+)\s+([A-Z0-9\-]+)\s+(.*?)\s+(\d{10,14})\s+\$(\d+\.\d{2})\s+\$",
                    bloque_texto
                )
                if m:
                    cantidad = int(m.group(1).replace(",", ""))
                    item = m.group(2)
                    descripcion = m.group(3).strip()
                    upc = m.group(4)
                    precio = float(m.group(5))

            if not m:
                m = re.match(
                    r"^([\d,]+)\s+([A-Z0-9\-]+)\s+(.*?)\s+\$(\d+\.\d{2})\s+USD",
                    bloque_texto
                )
                if m:
                    cantidad = int(m.group(1).replace(",", ""))
                    item = m.group(2)
                    descripcion = m.group(3).strip()
                    precio = float(m.group(4))

            if not m:
                m = re.match(
                    r"^([\d,]+)\s+([A-Z0-9\-]+)\s+(.*?)\s+\$(\d+\.\d{2})\s+\$",
                    bloque_texto
                )
                if m:
                    cantidad = int(m.group(1).replace(",", ""))
                    item = m.group(2)
                    descripcion = m.group(3).strip()
                    precio = float(m.group(4))

            if not m:
                continue

            if len(b) > 1:
                resto = ' '.join(b[1:])
                descripcion = descripcion + ' ' + resto if descripcion else resto

            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item}_{upc if upc else 'SIN_UPC'}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "due_days": due_days,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": item,
                "codigo_producto": upc if upc else "SIN_UPC",
                "tipo_codigo": "UPC",
                "descripcion": descripcion.strip(),
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": "USD",
                "importe": round(cantidad * precio, 2),
                "sample": detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER ANASTASIA BEVERLY HILLS
# ══════════════════════════════════════════════════════════════════

def parse_anastasia(pdf_file, marca, proveedor):
    from datetime import timedelta
    
    nombre_archivo = pdf_file.name
    
    texto = extraer_texto_pdf(pdf_file)
    
    # --- Cabecera ---
    invoice_match = re.search(r'Invoice\s*#\s*(\d+)', texto)
    invoice = invoice_match.group(1) if invoice_match else None
    
    fecha_match = re.search(r'Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
    if not fecha_match or not invoice:
        return []
    
    fecha_dt = datetime.strptime(fecha_match.group(1), "%m/%d/%Y")
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Due Date
    due_match = re.search(r'Due\s+Date\s+(\d{1,2}/\d{1,2}/\d{4})', texto)
    if due_match:
        due_dt = datetime.strptime(due_match.group(1), "%m/%d/%Y")
        due = due_dt.strftime("%d/%m/%Y")
    else:
        terms_match = re.search(r'Terms\s+Net\s+(\d+)', texto)
        if terms_match:
            net_days = int(terms_match.group(1))
            due_dt = fecha_dt + timedelta(days=net_days)
            due = due_dt.strftime("%d/%m/%Y")
        else:
            due = fecha
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # INCOTerm
    incoterm_match = re.search(r'(?<!\w)(EXW|FOB|CIF|DDP|DAP)(?!\w)', texto)
    incoterm = incoterm_match.group(1) if incoterm_match else "por_completar"
    total_factura_pdf = _extraer_total_generico(texto)

    # --- Detectar formato ---
    es_formato3 = "Item Number" in texto and "Unit Price" in texto and "Total Value" in texto
    es_formato2 = "L... Description" in texto
    es_formato1 = "Item QTY Units" in texto
    
    # --- Extraer items según formato ---
    items_raw = []
    
    if es_formato3:
        # ========== FORMATO 3: Item Number | UPC | Item | HTS | coo | QTY | Unit Price | Total Value ==========
        inicio_items = texto.find("Item Number")
        fin_items = texto.find("Total Amount", inicio_items)
        if fin_items == -1:
            fin_items = len(texto)
        
        cuerpo_items = texto[inicio_items:fin_items]
        lineas = [l.strip() for l in cuerpo_items.split('\n') if l.strip()]
        lineas = lineas[1:]  # Saltar encabezado
        
        # Reconstruir items con descripciones partidas
        buffer = None
        
        for l in lineas:
            # Detectar si es una nueva línea de item (empieza con ABH01-)
            es_nuevo_item = bool(re.match(r'ABH01-\d+', l))
            es_encabezado = any(x in l for x in ['Total Amount', 'Page', 'Commercial Invoice', 'Anastasia Beverly Hills'])
            
            if es_encabezado:
                continue
            
            if es_nuevo_item:
                if buffer:
                    items_raw.append(buffer)
                buffer = l
            else:
                if buffer:
                    buffer += " " + l
        
        if buffer:
            items_raw.append(buffer)
        
        # Parsear items del formato 3
        registros = []
        
        for item_texto in items_raw:
            # Patrón para formato 3: ABH01 | UPC | Desc | HTS | COO | QTY | Price | Total
            # La descripción puede ser larga y el HTS/COO pueden estar partidos
            m = re.search(
                r'(ABH01-\d+)\s+'          # 1. Item
                r'(\d{12,13})\s+'          # 2. UPC
                r'(.+?)\s+'                # 3. Descripción (non-greedy)
                r'(\d{4}\.\d{2}\.\d{4})\s+' # 4. HTS Code
                r'([A-Z]{2})\s+'           # 5. COO
                r'(\d+)\s+'                # 6. QTY
                r'([\d.]+)\s+'             # 7. Unit Price
                r'([\d,]+(?:\.\d{2})?)',   # 8. Total Value
                item_texto
            )
            
            if m:
                item_code = m.group(1)
                upc = m.group(2)
                descripcion = m.group(3).strip()
                cantidad = int(m.group(6))
                precio = float(m.group(7))
                
                # Limpiar descripción
                descripcion = re.sub(r'\s+', ' ', descripcion).strip()
                descripcion = re.sub(r'\s*-\s*$', '', descripcion)
                
                importe = round(cantidad * precio, 2)
                
                registros.append({
                    "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}_{upc}",
                    "marca": marca,
                    "proveedor": proveedor,
                    "invoice": invoice,
                    "invoice_date": fecha,
                    "due_date": due,
                    "po": po,
                    "incoterm": incoterm,
                    "periodo": periodo,
                    "item": item_code,
                    "codigo_producto": upc if upc else "SIN_UPC",
                    "tipo_codigo": "UPC",
                    "descripcion": descripcion,
                    "cantidad": cantidad,
                    "costo_unitario": precio,
                    "moneda": "USD",
                    "importe": importe,
                    "sample": detectar_sample(texto),
                    "nombre_archivo": nombre_archivo,
                    "total_factura_pdf": total_factura_pdf,
                })
            else:
                # Fallback: intentar sin HTS/COO
                m = re.search(
                    r'(ABH01-\d+)\s+'          # 1. Item
                    r'(\d{12,13})\s+'          # 2. UPC
                    r'(.+?)\s+'                # 3. Descripción
                    r'(\d+)\s+'                # 4. QTY
                    r'([\d.]+)\s+'             # 5. Unit Price
                    r'([\d,]+(?:\.\d{2})?)',   # 6. Total Value
                    item_texto
                )
                
                if m:
                    item_code = m.group(1)
                    upc = m.group(2)
                    descripcion = m.group(3).strip()
                    cantidad = int(m.group(4))
                    precio = float(m.group(5))
                    
                    descripcion = re.sub(r'\s+', ' ', descripcion).strip()
                    importe = round(cantidad * precio, 2)
                    
                    registros.append({
                        "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}_{upc}",
                        "marca": marca,
                        "proveedor": proveedor,
                        "invoice": invoice,
                        "invoice_date": fecha,
                        "due_date": due,
                        "po": po,
                        "incoterm": incoterm,
                        "periodo": periodo,
                        "item": item_code,
                        "codigo_producto": upc if upc else "SIN_UPC",
                        "tipo_codigo": "UPC",
                        "descripcion": descripcion,
                        "cantidad": cantidad,
                        "costo_unitario": precio,
                        "moneda": "USD",
                        "importe": importe,
                        "sample": detectar_sample(texto),
                        "nombre_archivo": nombre_archivo,
                        "total_factura_pdf": total_factura_pdf,
                    })
    
    elif es_formato2:
        # ========== FORMATO 2: Simplificado ==========
        inicio_items = texto.find("L... Description")
        if inicio_items == -1:
            inicio_items = texto.find("Item Number UPC")
        fin_items = texto.find("Subtotal", inicio_items)
        if fin_items == -1:
            fin_items = texto.find("Total", inicio_items)
        
        if inicio_items == -1 or fin_items == -1:
            return []
        
        cuerpo_items = texto[inicio_items:fin_items]
        lineas = [l.strip() for l in cuerpo_items.split('\n') if l.strip()]
        lineas = lineas[1:]
        
        lineas_filtradas = []
        for l in lineas:
            if re.match(r'^L\.\.\.\s+Description', l):
                continue
            if re.match(r'^(Date|Invoice|Anastasia|8900|Pico|United|Page|Terms|Due|PO|Ship|Bill|Total Units|AV\.|INT\.|Lima|Peru)', l):
                continue
            lineas_filtradas.append(l)
        
        items_raw = []
        buffer = None
        
        for l in lineas_filtradas:
            tiene_datos = re.match(r'^\d+\s+.*?\d+\s+Each\s+[\d.]+\s+[\d,]+\.\d{2}\s+ABH01-\d+\s+\d{12,13}', l)
            
            if tiene_datos:
                if buffer:
                    items_raw.append(buffer)
                buffer = l
            else:
                if buffer and not l.startswith("Shipping") and not l.startswith("Total") and not l.startswith("Subtotal"):
                    buffer += " " + l
        
        if buffer:
            items_raw.append(buffer)
        
        registros = []
        
        for item_texto in items_raw:
            m = re.search(
                r'(?:^\d+\s+)?(.+?)\s+(\d+)\s+Each\s+([\d.]+)\s+([\d,]+(?:\.\d{2}))\s+(ABH01-\d+)\s+(\d{12,13})',
                item_texto
            )
            
            if m:
                descripcion = m.group(1).strip()
                cantidad = int(m.group(2))
                precio = float(m.group(3))
                item_code = m.group(5)
                upc = m.group(6)
                
                resto = item_texto[m.end():].strip()
                if resto:
                    descripcion = descripcion + " " + resto
                
                descripcion = re.sub(r'\s*-\s*$', '', descripcion)
                descripcion = re.sub(r'\s+', ' ', descripcion).strip()
                importe = round(cantidad * precio, 2)
                
                registros.append({
                    "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}_{upc}",
                    "marca": marca,
                    "proveedor": proveedor,
                    "invoice": invoice,
                    "invoice_date": fecha,
                    "due_date": due,
                    "po": po,
                    "incoterm": incoterm,
                    "periodo": periodo,
                    "item": item_code,
                    "codigo_producto": upc if upc else "SIN_UPC",
                    "tipo_codigo": "UPC",
                    "descripcion": descripcion,
                    "cantidad": cantidad,
                    "costo_unitario": precio,
                    "moneda": "USD",
                    "importe": importe,
                    "sample": detectar_sample(texto),
                    "nombre_archivo": nombre_archivo,
                    "total_factura_pdf": total_factura_pdf,
                })
    
    elif es_formato1:
        # ========== FORMATO 1: Completo ==========
        inicio_items = texto.find("Item QTY Units")
        fin_items = texto.find("Subtotal")
        if inicio_items == -1 or fin_items == -1:
            return []
        
        cuerpo_items = texto[inicio_items:fin_items]
        lineas = [l.strip() for l in cuerpo_items.split('\n') if l.strip()]
        lineas = lineas[1:]
        
        items_raw = []
        buffer = None
        
        for l in lineas:
            tiene_codigo = re.search(r'ABH01-\d+', l)
            tiene_encabezado = re.match(r'^(Item|Commercial|Date|Invoice|Page|Anastasia|8900|Pico|United|Terms|Due|PO|Shipping|Ship|Bill|Total Units|AV\.|INT\.|Lima|Peru|S\.O\.|Sales Order|Subtotal|Total)', l)
            
            if tiene_encabezado:
                continue
            
            if tiene_codigo:
                if buffer:
                    items_raw.append(buffer)
                buffer = l
            else:
                if buffer:
                    buffer += " " + l
        
        if buffer:
            items_raw.append(buffer)
        
        registros = []
        
        for item_texto in items_raw:
            m = re.search(
                r'^(.+?)\s+(\d+)\s+Each\s+([\d.]+)\s+([\d,]+(?:\.\d{2}))\s+(ABH01-\d+)\s+(\d{12,13})\s+(\d{4}\.\d{2}\.\d{4})\s+([A-Z]{2})\b',
                item_texto
            )
            
            if m:
                descripcion = m.group(1).strip()
                cantidad = int(m.group(2))
                precio = float(m.group(3))
                item_code = m.group(5)
                upc = m.group(6)
                
                resto = item_texto[m.end():].strip()
                if resto:
                    descripcion = descripcion + " " + resto
                
                descripcion = re.sub(r'\s*-\s*$', '', descripcion)
                descripcion = re.sub(r'\s+', ' ', descripcion).strip()
                importe = round(cantidad * precio, 2)
                
                registros.append({
                    "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_code}_{upc}",
                    "marca": marca,
                    "proveedor": proveedor,
                    "invoice": invoice,
                    "invoice_date": fecha,
                    "due_date": due,
                    "po": po,
                    "incoterm": incoterm,
                    "periodo": periodo,
                    "item": item_code,
                    "codigo_producto": upc if upc else "SIN_UPC",
                    "tipo_codigo": "UPC",
                    "descripcion": descripcion,
                    "cantidad": cantidad,
                    "costo_unitario": precio,
                    "moneda": "USD",
                    "importe": importe,
                    "sample": detectar_sample(texto),
                    "nombre_archivo": nombre_archivo,
                    "total_factura_pdf": total_factura_pdf,
                })
    
    else:
        print(f"   ⚠ Formato no reconocido para {nombre_archivo}")
        return []
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER BETER
# ══════════════════════════════════════════════════════════════════

def parse_beter(pdf_file, marca, proveedor):
    nombre_archivo = pdf_file.name

    texto = extraer_texto_pdf(pdf_file)

    # ========== EXTRACCIÓN DE INVOICE ==========
    invoice = None
    
    # Formato 1: "INVOICE 1312343" (nuevo)
    inv_match = re.search(r'INVOICE\s+(\d+)', texto)
    if inv_match:
        invoice = inv_match.group(1)
    
    # Formato 2: "Invoice nº: 30019339" (original)
    if not invoice:
        inv_match = re.search(r"Invoice\s+nº:\s*(\d+)", texto)
        if inv_match:
            invoice = inv_match.group(1)
    
    if not invoice:
        return []

    # ========== EXTRACCIÓN DE FECHA ==========
    fecha = None
    fecha_match = re.search(r"Date:\s*(\d{2}/\d{2}/\d{4})", texto)
    if fecha_match:
        fecha = fecha_match.group(1)
    
    if not fecha:
        return []

    # ========== EXTRACCIÓN DE DUE DATE ==========
    due = None
    due_match = re.search(r"Expiry Date:\s*(\d{2}/\d{2}/\d{4})", texto)
    if due_match:
        due = due_match.group(1)
    else:
        due = fecha

    # ========== EXTRACCIÓN DE PO ==========
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    # ========== EXTRACCIÓN DE INCOTERM ==========
    incoterm = normalizar_incoterm(texto)
    
    # ========== EXTRACCIÓN DE PERIODO ==========
    periodo = datetime.strptime(fecha, "%d/%m/%Y").strftime("%Y%m")
    total_factura_pdf = _extraer_total_generico(texto)

    # ========== DETECCIÓN DE FORMATO ==========
    es_formato_nuevo = "H.S. Code" in texto and ("Euro disc." in texto or "Euro" in texto)
    
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    registros = []

    if es_formato_nuevo:
        # ========== FORMATO NUEVO ==========
        # Encabezado: H.S. Code Description Ref. EAN Code Quantity Euro disc. Total
        # Item: HS_CODE DESCRIPCION REF EAN CANTIDAD PRECIO DESCUENTO TOTAL
        
        for l in lineas:
            # Solo procesar líneas que empiezan con dígitos (HS Code)
            if not re.match(r'^\d{6,12}\s', l):
                continue
            
            # Saltar líneas que son direcciones (contienen "LA MOLINA", "LIMA", etc.)
            if any(x in l.upper() for x in ['LA MOLINA', 'LIMA -', 'BARCELONA', 'PÁGINA', 'PAGE']):
                continue
            
            # Patrón: HS_CODE DESCRIPCION REF EAN CANTIDAD PRECIO DESCUENTO TOTAL
            m = re.match(
                r"^(\d{6,12})\s+"                      # 1. HS Code (6-12 dígitos)
                r"(.+?)\s+"                            # 2. Descripción
                r"([A-Z0-9][A-Z0-9\-\.]+)\s+"          # 3. Ref (ej: 2-03-297-0)
                r"(\d{13})\s+"                         # 4. EAN (13 dígitos)
                r"([\d\.]+)\s+"                        # 5. Cantidad
                r"([\d\.]+,\d+)\s+"                    # 6. Precio (formato europeo)
                r"[\d\.]+,\d+\s+"                      # 7. Descuento (ignorar)
                r"([\d\.]+,\d+)$",                     # 8. Total
                l
            )
            
            if m:
                descripcion = m.group(2).strip()
                ref = m.group(3)
                ean = m.group(4)
                cantidad = euro_to_float(m.group(5))
                precio = euro_to_float(m.group(6))
                
                registros.append({
                    "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{ref}_{ean}",
                    "marca": marca,
                    "proveedor": proveedor,
                    "invoice": invoice,
                    "invoice_date": fecha,
                    "due_date": due,
                    "po": po,
                    "incoterm": incoterm,
                    "periodo": periodo,
                    "item": ref,
                    "codigo_producto": ean,
                    "tipo_codigo": "EAN",
                    "descripcion": descripcion,
                    "cantidad": cantidad,
                    "costo_unitario": precio,
                    "moneda": "EUR",
                    "importe": round(cantidad * precio, 2),
                    "sample": detectar_sample(texto),
                    "nombre_archivo": nombre_archivo,
                    "total_factura_pdf": total_factura_pdf,
                })
    else:
        # ========== FORMATO ORIGINAL ==========
        for l in lineas:
            m = re.match(
                r"^(\d+)\s+(.*?)\s+([A-Z0-9\-]+)\s+(\d{13})\s+([\d\.]+)\s+([\d,]+)\s+([\d,]+)\s+([\d\.]+,\d+)$",
                l
            )

            if not m:
                continue

            cantidad = euro_to_float(m.group(5))
            precio = euro_to_float(m.group(6))

            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{m.group(3)}_{m.group(4)}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": due,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": m.group(3),
                "codigo_producto": m.group(4),
                "tipo_codigo": "EAN",
                "descripcion": m.group(2),
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": "EUR",
                "importe": round(cantidad * precio, 2),
                "sample": detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER MARIO BADESCU
# ══════════════════════════════════════════════════════════════════

def parse_mario(pdf_file, marca, proveedor):
    nombre_archivo = pdf_file.name

    texto = extraer_texto_pdf(pdf_file)
    
    # --- Extracción de Cabecera ---
    # Buscar invoice de 6 dígitos después de "Invoice #" o "Invoice#"
    invoice_match = re.search(r"Invoice\s+#?\s*(\d{6})", texto, re.IGNORECASE)
    if invoice_match:
        invoice = invoice_match.group(1)
    else:
        # Fallback: cualquier número de 6 dígitos que no sea 1150
        todos_los_numeros = re.findall(r"\b(\d{6})\b", texto)
        invoice = next((n for n in todos_los_numeros if n != "1150"), None)
    
    # Extraer fecha y convertir de MM/DD/YYYY a DD/MM/YYYY
    fecha_match = re.search(r"\b(\d{1,2})/(\d{1,2})/(\d{4})\b", texto)
    if fecha_match:
        mes, dia, anio = fecha_match.groups()
        fecha = f"{dia}/{mes}/{anio}"  # Ahora es DD/MM/YYYY
    else:
        fecha = None
    
    # Búsqueda más flexible de Due Date
    due_match = re.search(r"NET\s+\d+\s+(\d{1,2}/\d{1,2}/\d{4})", texto)
    if due_match:
        due_raw = due_match.group(1)
        due_parts = due_raw.split('/')
        if len(due_parts) == 3:
            mes, dia, anio = due_parts
            due = f"{dia}/{mes}/{anio}"  # Convertir a DD/MM/YYYY
        else:
            due = None
    else:
        due = None

    if not invoice or not fecha:
        return []

    # Extraer periodo desde la fecha (ya está en DD/MM/YYYY)
    periodo = datetime.strptime(fecha, "%d/%m/%Y").strftime("%Y%m")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    total_factura_pdf = _extraer_total_generico(texto)

    # --- Extracción de Detalle ---
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    registros = []

    for l in lineas:
        # Saltamos líneas que no son items
        if "BATCH#" in l or "Total" in l or "Page" in l or "Balance Due" in l or "Payments/Credits" in l:
            continue
            
        # Regex para capturar: Item | Descripcion | Cantidad | UPC(12-13 digitos) | Precio | Total
        m = re.match(
            r"^(\d+)\s+(.*?)\s+([\d,]+)\s+(\d{12,13})\s+([\d\.]+)\s+([\d,]+\.\d{2})",
            l
        )

        if m:
            item = m.group(1)
            descripcion = m.group(2).strip()
            cantidad = float(m.group(3).replace(",", ""))
            upc = m.group(4)
            precio = float(m.group(5))

            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item}_{upc if upc else 'SIN_UPC'}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,  # ← Ahora usa el invoice correcto de 6 dígitos
                "invoice_date": fecha,
                "due_date": due,
                "po": po,
                "incoterm": "EXW",
                "periodo": periodo,
                "item": item,
                "codigo_producto": upc if upc else "SIN_UPC",
                "tipo_codigo": "UPC",
                "descripcion": descripcion,
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": "USD",
                "importe": round(cantidad * precio, 2),
                "sample": detectar_sample(texto),
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })

    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER PETRIZZIO
# ══════════════════════════════════════════════════════════════════

def parse_petrizzio(pdf_file, marca, proveedor):
    from datetime import timedelta

    nombre_archivo = pdf_file.name

    texto = extraer_texto_pdf(pdf_file)
    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    
    # ========== DETECCIÓN DE FORMATO ==========
    # Formato muestras: tiene "MUESTRAS SIN VALOR" y "COMMERCIAL INVOICE" sin "Nº"
    es_formato_muestras = "MUESTRAS SIN VALOR" in texto.upper() or ("COMMERCIAL INVOICE" in texto.upper() and "CÓDIGOS" in texto.upper())
    
    if es_formato_muestras:
        # ========== FORMATO MUESTRAS ==========
        return _parse_petrizzio_muestras(pdf_file, marca, proveedor, texto, lineas, nombre_archivo)
    else:
        # ========== FORMATO ORIGINAL ==========
        return _parse_petrizzio_original(pdf_file, marca, proveedor, texto, lineas, nombre_archivo)


def _parse_petrizzio_muestras(pdf_file, marca, proveedor, texto, lineas, nombre_archivo):
    """Parsea facturas de muestras de PETRIZZIO"""
    from datetime import timedelta
    
    # --- Invoice: buscar REF en línea siguiente a "REF." ---
    invoice = None
    for i, linea in enumerate(lineas):
        if 'REF.' in linea.upper():
            if i + 1 < len(lineas):
                ref_linea = lineas[i + 1].strip()
                if re.match(r'^IMP\d+_\d+', ref_linea):
                    invoice = ref_linea
            break
    
    if not invoice:
        inv_match = re.search(r'(IMP\d+_\d+-\d+)', texto)
        if inv_match:
            invoice = inv_match.group(1)
    
    if not invoice:
        return []
    
    # --- Fecha: "23 1 2025" ---
    fecha_match = re.search(r'(\d{1,2})\s+(\d{1,2})\s+(\d{4})', texto)
    if not fecha_match:
        return []
    
    dia, mes, anio = fecha_match.group(1), fecha_match.group(2), fecha_match.group(3)
    fecha_dt = datetime(int(anio), int(mes), int(dia))
    fecha_emision = fecha_dt.strftime("%d/%m/%Y")
    due_date = (fecha_dt + timedelta(days=45)).strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # --- Incoterm ---
    incoterm = "CIF"
    if re.search(r'\bEXW\b', texto) or 'EWX' in texto:
        incoterm = "EXW"
    elif re.search(r'\bFOB\b', texto):
        incoterm = "FOB"
    total_factura_pdf = _extraer_total_petrizzio(texto)

    # --- Items ---
    registros = []
    codigos_procesados = set()

    for l in lineas:
        l = l.strip()
        if not l:
            continue

        # Saltar líneas no relevantes
        if any(p in l.upper() for p in ["NOTA:", "MUESTRAS SIN", "DESCUENTO", "TOTAL", "PESO", "FIRMA", "BANK", "INFORMACION", "CÓDIGOS", "CODE ARTICLE"]):
            continue
        
        # Patrón: CODIGO CANTIDAD DESCRIPCION PRECIO TOTAL
        m = re.match(
            r'^(\d{4,6})\s+'           # 1. Código
            r'(\d+)\s*'                # 2. Cantidad
            r'(.+?)\s+'                # 3. Descripción
            r'([\d,]+)\s+'             # 4. Precio unitario
            r'([\d,]+(?:\.\d{2})?)$',  # 5. Total
            l
        )
        
        if m:
            codigo = m.group(1)
            cantidad = int(m.group(2))
            descripcion = m.group(3).strip()
            precio = float(m.group(4).replace(',', '.'))
            
            if codigo in codigos_procesados:
                continue
            codigos_procesados.add(codigo)
            
            importe = round(cantidad * precio, 2)
            
            registros.append({
                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha_emision,
                "due_date": due_date,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": codigo,
                "codigo_producto": None,
                "tipo_codigo": None,
                "descripcion": descripcion,
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": "USD",
                "importe": importe,
                "sample": "Y",
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })
    
    return registros


def _parse_petrizzio_original(pdf_file, marca, proveedor, texto, lineas, nombre_archivo):
    """Parsea facturas originales de PETRIZZIO (sin cambios)"""
    from datetime import timedelta
    
    # --- Cabecera ---
    invoice_match = re.search(r"Nº\s*(\d+)", texto)
    invoice = invoice_match.group(1) if invoice_match else "000000"
    
    fecha_match = re.search(r"Emisión\s*:\s*(\d{2}-\d{2}-\d{4})", texto)
    
    if not fecha_match: 
        return []
    
    fecha_dt = datetime.strptime(fecha_match.group(1), "%d-%m-%Y")
    fecha_emision = fecha_dt.strftime("%d/%m/%Y")
    due_date = (fecha_dt + timedelta(days=45)).strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    total_factura_pdf = _extraer_total_petrizzio(texto)

    registros = []
    codigos_procesados = set()

    for l in lineas:
        if any(p in l for p in ["Total", "Monto", "SON:", "Código Cant.", "Flete", "Seguros", "Beneficiario", "Precio Neto", "Valor Total"]):
            continue
        
        codigo = None
        cantidad = None
        descripcion = None
        precio = None
        
        m = re.match(r"^(\d{4,6})\s+(\d+(?:\.\d+)?)\s+(.*?)\s+([\d\.]+,\d{2})\s+([\d\.]+[.,]\d{2})$", l)
        
        if m:
            codigo = m.group(1)
            cantidad = float(m.group(2).replace(".", ""))
            descripcion = m.group(3).strip()
            precio = pzz_to_float(m.group(4))
        
        if not m:
            m = re.match(r"^(\d{4,6})\s+(\d+(?:\.\d+)?)\s+(.*?)\s+([\d\.]+,\d{2})\s*$", l)
            if m:
                codigo = m.group(1)
                cantidad = float(m.group(2).replace(".", ""))
                descripcion = m.group(3).strip()
                valor_total = pzz_to_float(m.group(4))
                if cantidad > 0:
                    precio = round(valor_total / cantidad, 4)
        
        if not m:
            partes = l.split()
            if len(partes) >= 4 and partes[0].isdigit() and len(partes[0]) >= 4:
                try:
                    codigo = partes[0]
                    cantidad = float(partes[1].replace(".", ""))
                    descripcion = ' '.join(partes[2:-1])
                    valor_total = pzz_to_float(partes[-1])
                    if cantidad > 0:
                        precio = round(valor_total / cantidad, 4)
                except:
                    continue
        
        if not codigo or cantidad == 0 or not precio:
            continue
        
        if codigo in codigos_procesados:
            continue
        codigos_procesados.add(codigo)
        
        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha_emision,
            "due_date": due_date,
            "po": po,
            "incoterm": "CIF",
            "periodo": periodo,
            "item": codigo,
            "codigo_producto": None,
            "tipo_codigo": None,
            "descripcion": descripcion,
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": "USD",
            "importe": round(cantidad * precio, 2),
            "sample": detectar_sample(texto),
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })
    
    # Fallback con tablas
    if not registros:
        with pdfplumber.open(pdf_file) as pdf:
            for page in pdf.pages:
                tablas = page.extract_tables()
                for tabla in tablas:
                    for fila in tabla:
                        if not fila or fila[0] is None:
                            continue
                        
                        codigo = str(fila[0]).strip() if fila[0] else ""
                        if not codigo.isdigit() or len(codigo) < 4:
                            continue
                        if any(p in str(fila[0]).upper() for p in ["TOTAL", "MONTO", "SON:", "CÓDIGO", "PRECIO"]):
                            continue
                        
                        try:
                            cantidad = float(str(fila[1]).replace(".", "").replace(",", ".")) if len(fila) > 1 and fila[1] else 0
                            descripcion = str(fila[2]).strip() if len(fila) > 2 and fila[2] else ""
                            valor_total_raw = str(fila[3]) if len(fila) > 3 and fila[3] else ""
                            # pzz_to_float no distingue un '0.00' real de un '-' de relleno
                            # (ambos le dan 0.0), así que hay que chequear el texto crudo
                            # antes de convertirlo para no confundir una muestra con basura.
                            valor_total_es_numero = _es_numero_explicito(valor_total_raw)
                            valor_total = pzz_to_float(valor_total_raw) if valor_total_es_numero else 0.0

                            if cantidad > 0 and valor_total > 0:
                                precio = round(valor_total / cantidad, 4)
                            else:
                                precio = 0.0

                            if cantidad == 0 or not valor_total_es_numero:
                                continue
                            
                            if codigo in codigos_procesados:
                                continue
                            codigos_procesados.add(codigo)
                            
                            registros.append({
                                "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{codigo}",
                                "marca": marca,
                                "proveedor": proveedor,
                                "invoice": invoice,
                                "invoice_date": fecha_emision,
                                "due_date": due_date,
                                "po": po,
                                "incoterm": "CIF",
                                "periodo": periodo,
                                "item": codigo,
                                "codigo_producto": None,
                                "tipo_codigo": None,
                                "descripcion": descripcion,
                                "cantidad": cantidad,
                                "costo_unitario": precio,
                                "moneda": "USD",
                                "importe": round(cantidad * precio, 2),
                                "sample": detectar_sample(texto),
                                "nombre_archivo": nombre_archivo,
                                "total_factura_pdf": total_factura_pdf,
                            })
                        except (ValueError, IndexError):
                            continue
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER TONY_MOLY_HOLIKA_HOLIKA
# ══════════════════════════════════════════════════════════════════

def parse_tony_moly(pdf_file, marca, proveedor):
    from datetime import timedelta
    from collections import defaultdict
    
    nombre_archivo = pdf_file.name
    
    texto = extraer_texto_pdf(pdf_file)
    
    # --- Cabecera ---
    invoice_match = re.search(r"(CI_HHB_ARUMA\d+_?\d{6}_IMP\d+(?:_[A-Z]+)?_sent)", texto)
    
    if not invoice_match:
        invoice_match = re.search(r"(CI_HHB_ARUMA\d+_?'?\d{6}_IMP\d+(?:_[A-Z]+)?_sent)", texto)
    
    if not invoice_match:
        invoice_match = re.search(r"(CI_HHB_ARUMA\d+_.*?_sent)", texto)
    
    if invoice_match:
        invoice = invoice_match.group(1).replace("'", "").replace(" ", "_")
        print(f"   📋 Invoice: {invoice}")
    else:
        invoice = "UNKNOWN"
        print(f"   ⚠ No se pudo extraer invoice")
    
    # Extraer fecha
    fecha_raw = re.search(r"Issued Date:\s*(\d{2}\.\d{2}\.\d{2})", texto)
    if not fecha_raw:
        return []
    
    fecha_dt = datetime.strptime(fecha_raw.group(1), "%y.%m.%d")
    fecha_emision = fecha_dt.strftime("%d/%m/%Y")
    due_date = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Extraer PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    if po:
        print(f"   📦 PO extraído del nombre: {po}")
    
    # ========== NUEVO: Extraer marca desde el campo * BRAND ==========
    brand_match = re.search(r"\*\s*BRAND\s*:\s*([^\n]+)", texto, re.IGNORECASE)
    marca_desde_pdf = None
    if brand_match:
        marcas_raw = brand_match.group(1).strip()
        # Limpiar y normalizar: "TONYMOLY, HOLIKA HOLIKA" -> ["TONYMOLY", "HOLIKA HOLIKA"]
        marcas_limpias = [m.strip().upper().replace(" ", "_") for m in marcas_raw.split(",")]
        marca_desde_pdf = marcas_limpias
        print(f"   🏷 Marcas desde PDF: {marca_desde_pdf}")
    else:
        print(f"   ⚠ No se encontró campo '* BRAND' en el PDF, usando marca de ruta: {marca}")
    # ================================================================

    total_factura_pdf = _extraer_total_generico(texto)

    # --- Extracción de tabla ---
    inicio_tabla = texto.find("BRAND PRODUCT CODE")
    fin_tabla = texto.find("Total")
    cuerpo = texto[inicio_tabla:fin_tabla]
    
    # Primera pasada: extraer todas las líneas sin generar ID aún
    lineas_raw = []
    lineas = [l.strip() for l in cuerpo.split('\n') if any(m in l for m in ["TONYMOLY", "HOLIKA HOLIKA"])]

    for linea in lineas:
        # Patrón actualizado: capturamos también la marca de la línea
        patron = r"^(TONYMOLY|HOLIKA HOLIKA)\s+([A-Z0-9]+)\s+(\d{13}|.*?)\s+(.*?)\s+([\d,.]+)\s+pcs"
        
        m = re.search(patron, linea)
        
        if m:
            brand_linea = m.group(1).strip().upper().replace(" ", "_")  # "TONYMOLY" o "HOLIKA_HOLIKA"
            item = m.group(2)
            barcode = m.group(3).strip()
            descripcion_sucia = m.group(4).strip()
            qty_raw = m.group(5).strip()

            if re.search(r"\d$", descripcion_sucia):
                ultimo_digito = descripcion_sucia[-1]
                descripcion = descripcion_sucia[:-1].strip()
                cantidad_final = ultimo_digito + qty_raw.replace(",", "")
            else:
                descripcion = descripcion_sucia
                cantidad_final = qty_raw.replace(",", "")

            cantidad = int(float(cantidad_final))
            
            # Extraer precio
            precio_match = re.search(r"\$\s*([\d\s\.]+)\s+\$", linea)
            if precio_match:
                precio_raw = precio_match.group(1).replace(" ", "")
                precio = float(precio_raw) if precio_raw else 0.0
            else:
                precio = 0.0

            # Guardar datos crudos (con la marca individual)
            lineas_raw.append({
                "brand_linea": brand_linea,
                "item": item,
                "barcode": barcode,
                "descripcion": descripcion,
                "cantidad": cantidad,
                "precio": precio
            })
    
    # --- Segunda pasada: Contar duplicados por (item, barcode) y asignar sufijos ---
    conteo = defaultdict(int)
    
    for raw in lineas_raw:
        key = (raw["item"], raw["barcode"])
        conteo[key] += 1
    
    contador_actual = defaultdict(int)
    
    # Construir registros
    registros = []
    for raw in lineas_raw:
        key = (raw["item"], raw["barcode"])
        
        # Sufijo para duplicados
        if conteo[key] > 1:
            contador_actual[key] += 1
            sufijo = f"_{contador_actual[key]:02d}"
        else:
            sufijo = ""
        
        # ========== DECISIÓN DE MARCA ==========
        # Prioridad:
        # 1. Marca individual de la línea (si existe y no está vacía)
        # 2. Primera marca del campo * BRAND del PDF
        # 3. Marca proveniente de la ruta (parámetro)
        if raw["brand_linea"] and raw["brand_linea"] != "":
            marca_registro = raw["brand_linea"]
        elif marca_desde_pdf and len(marca_desde_pdf) > 0:
            marca_registro = marca_desde_pdf[0]  # Usar la primera marca del PDF
        else:
            marca_registro = marca  # Fallback a la marca de la ruta
        
        # Construir ID
        id_base = f"{marca_registro}_{po}_{periodo}_{raw['item']}_{raw['barcode']}"
        id_final = id_base + sufijo
        
        registros.append({
            "id": id_final,
            "marca": marca_registro,  # ← Ahora usa la marca individual de la línea
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha_emision,
            "due_date": due_date,
            "po": po,
            "incoterm": "FOB",
            "periodo": periodo,
            "item": raw['item'],
            "codigo_producto": raw['barcode'],
            "tipo_codigo": "EAN",
            "descripcion": raw['descripcion'],
            "cantidad": raw['cantidad'],
            "costo_unitario": raw['precio'],
            "moneda": "USD",
            "importe": round(raw['cantidad'] * raw['precio'], 2),
            "sample": detectar_sample(texto),
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })
        
        if sufijo:
            print(f"   🔄 Duplicado: {raw['item']}_{raw['barcode']}{sufijo} ({raw['brand_linea']}, cant: {raw['cantidad']})")
    
    if not registros:
        print(f"   ⚠ No se extrajeron items para {nombre_archivo}")
    
    return registros

# ══════════════════════════════════════════════════════════════════
# PARSER REVOX_B77 (CORREGIDO)
# ══════════════════════════════════════════════════════════════════

def parse_REVOX_B77_excel(excel_file, marca, proveedor):
    nombre_archivo = excel_file.name
    
    df = pd.read_excel(excel_file, header=None)
    
    # ========== BUSCAR FILA DE ENCABEZADO ==========
    header_row = None
    for i in range(min(40, len(df))):
        row = df.iloc[i]
        row_str = ' '.join([str(v) for v in row.values if pd.notna(v)])
        # Buscar encabezados conocidos
        if 'Article' in row_str and 'Item name' in row_str:
            header_row = i
            break
        if 'Item No.' in row_str and 'Description' in row_str:
            header_row = i
            break
        if 'Item No. Revuele' in row_str:
            header_row = i
            break
    
    if header_row is None:
        print(f"   ⚠ No se encontró fila de encabezado en {nombre_archivo}")
        return []
    
    # ========== DETECTAR COLUMNAS ==========
    header = df.iloc[header_row]
    col_article = None
    col_item_name = None
    col_unit = None
    col_qty = None
    col_price = None
    col_amount = None
    col_custom_code = None
    col_batch = None
    col_expiry = None
    col_origin = None
    
    for j, val in enumerate(header):
        if pd.notna(val):
            val_str = str(val).strip()
            if 'Article' in val_str or 'Item No.' in val_str:
                col_article = j
            elif 'Item name' in val_str or 'Description' in val_str:
                col_item_name = j
            elif 'Unit' in val_str and 'price' not in val_str:
                col_unit = j
            elif 'Quantity' in val_str or 'Q-ty' in val_str:
                col_qty = j
            elif 'Unit price' in val_str or 'Net Unit Price' in val_str:
                col_price = j
            elif 'Total price' in val_str or 'Amount' in val_str:
                col_amount = j
            elif 'Batch' in val_str:
                col_batch = j
            elif 'Expiry' in val_str:
                col_expiry = j
            elif 'Custom code' in val_str:
                col_custom_code = j
            elif 'Origin' in val_str:
                col_origin = j
    
    # ========== EXTRAER DATOS DE CABECERA ==========
    # PO del nombre del archivo
    po_match = re.search(r'^(IMP\d+-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None
    
    # Invoice: buscar en filas superiores
    invoice = None
    for i in range(min(15, len(df))):
        row = df.iloc[i]
        for j, val in enumerate(row):
            if pd.notna(val):
                val_str = str(val).strip()
                # Buscar "No." seguido de número
                if 'No.' in val_str:
                    # Buscar en la misma fila
                    for k in range(j, min(j+5, len(row))):
                        if pd.notna(row[k]):
                            num_str = str(row[k]).strip()
                            if re.match(r'^\d{7,10}$', num_str):
                                invoice = num_str
                                break
                # Buscar número de 7-10 dígitos directamente
                nums = re.findall(r'\b(\d{7,10})\b', val_str)
                if nums and len(nums[0]) >= 7:
                    # Verificar que no sea RUC (20601266416 tiene 11 dígitos)
                    if len(nums[0]) <= 10:
                        invoice = nums[0]
                        break
        if invoice:
            break
    
    # Si no se encontró invoice, usar el del nombre o placeholder
    if not invoice:
        # Intentar extraer del nombre
        name_parts = nombre_archivo.split('_')
        if len(name_parts) >= 3:
            # Intentar encontrar un número de 7-10 dígitos
            for part in name_parts:
                if re.match(r'^\d{7,10}$', part):
                    invoice = part
                    break
        if not invoice:
            invoice = "0000000"
    
    # Fecha
    fecha_dt = None
    for i in range(min(25, len(df))):
        row = df.iloc[i]
        for val in row:
            if pd.notna(val):
                val_str = str(val).strip()
                # Buscar YYYY-MM-DD
                match = re.search(r'(\d{4}-\d{2}-\d{2})', val_str)
                if match:
                    try:
                        fecha_dt = datetime.strptime(match.group(1), "%Y-%m-%d")
                        break
                    except:
                        pass
                # Buscar DD.MM.YYYY
                match = re.search(r'(\d{2}\.\d{2}\.\d{4})', val_str)
                if match:
                    try:
                        fecha_dt = datetime.strptime(match.group(1), "%d.%m.%Y")
                        break
                    except:
                        pass
                # Buscar DD/MM/YYYY
                match = re.search(r'(\d{2}/\d{2}/\d{4})', val_str)
                if match:
                    try:
                        fecha_dt = datetime.strptime(match.group(1), "%d/%m/%Y")
                        break
                    except:
                        pass
        if fecha_dt:
            break
    
    if not fecha_dt:
        # Intentar extraer del nombre del archivo
        name_parts = nombre_archivo.split('_')
        for part in name_parts:
            if re.match(r'^\d{6}$', part):
                try:
                    fecha_dt = datetime.strptime(part, "%Y%m")
                    break
                except:
                    pass
        
        if not fecha_dt:
            print(f"   ⚠ No se encontró fecha en {nombre_archivo}")
            return []
    
    fecha = fecha_dt.strftime("%d/%m/%Y")
    periodo = fecha_dt.strftime("%Y%m")
    
    # Incoterm
    incoterm = "EXW"
    for i in range(len(df)):
        row = df.iloc[i]
        for val in row:
            if pd.notna(val):
                val_str = str(val).strip()
                if 'EXW' in val_str:
                    incoterm = "EXW"
                    break
                elif 'FOB' in val_str:
                    incoterm = "FOB"
                    break
                elif 'CIF' in val_str:
                    incoterm = "CIF"
                    break
        if incoterm != "EXW":
            break
    
    moneda = "EUR"
    sample = "Y" if "SAMPLE" in str(df.values).upper() or "MUESTRA" in str(df.values).upper() else "N"

    # Total declarado: buscar una fila con "Total" (no "Subtotal") y tomar el
    # último valor numérico de esa fila.
    total_factura_pdf = None
    for i in range(len(df)):
        row = df.iloc[i]
        row_str = ' '.join(str(v).strip() for v in row.values if pd.notna(v))
        if re.search(r'\bTotal\b', row_str, re.IGNORECASE) and 'sub' not in row_str.lower():
            numeros_fila = []
            for v in row.values:
                if pd.notna(v):
                    try:
                        numeros_fila.append(float(v))
                    except (TypeError, ValueError):
                        continue
            if numeros_fila:
                total_factura_pdf = numeros_fila[-1]
                break

    # ========== EXTRAER ITEMS ==========
    registros = []
    i = header_row + 1
    while i < len(df):
        row = df.iloc[i]
        
        # Verificar si es fila de item
        item_no = None
        if col_article is not None and pd.notna(row[col_article]):
            val = str(row[col_article]).strip()
            if re.match(r'^\d{6,8}$', val):
                item_no = val
        
        if not item_no:
            i += 1
            continue
        
        # Verificar si llegamos a totales
        row_str = ' '.join([str(v) for v in row.values if pd.notna(v)])
        if 'Total' in row_str or 'Amount EUR' in row_str:
            break
        
        # Extraer descripción
        descripcion = ""
        if col_item_name is not None and pd.notna(row[col_item_name]):
            descripcion = str(row[col_item_name]).strip()
        
        # Si no hay descripción, buscar en columnas siguientes
        if not descripcion or len(descripcion) < 5:
            for j in range(col_item_name + 1 if col_item_name else 0, min(col_item_name + 10 if col_item_name else len(row), len(row))):
                if j < len(row) and pd.notna(row[j]):
                    val = str(row[j]).strip()
                    if val and len(val) > len(descripcion):
                        descripcion = val
                        break
        
        # Extraer cantidad
        cantidad = 0
        if col_qty is not None and pd.notna(row[col_qty]):
            try:
                cantidad = int(float(row[col_qty]))
            except:
                cantidad = 0
        
        # Extraer precio
        precio = 0.0
        if col_price is not None and pd.notna(row[col_price]):
            try:
                precio = float(row[col_price])
            except:
                precio = 0.0
        
        # Extraer importe
        importe = 0.0
        if col_amount is not None and pd.notna(row[col_amount]):
            try:
                importe = float(row[col_amount])
            except:
                importe = 0.0
        
        # Extraer custom code
        custom_code = ""
        if col_custom_code is not None and pd.notna(row[col_custom_code]):
            custom_code = str(row[col_custom_code]).strip()
        
        if cantidad > 0 or importe > 0:
            id_base = f"{marca}_{po}_{invoice}_{periodo}_{item_no}"
            
            registros.append({
                "id": id_base,
                "marca": marca,
                "proveedor": proveedor,
                "invoice": invoice,
                "invoice_date": fecha,
                "due_date": fecha,
                "po": po,
                "incoterm": incoterm,
                "periodo": periodo,
                "item": str(item_no),
                "codigo_producto": custom_code if custom_code else None,
                "tipo_codigo": "CUSTOM_CODE" if custom_code else None,
                "descripcion": descripcion[:300] if descripcion else "",
                "cantidad": cantidad,
                "costo_unitario": precio,
                "moneda": moneda,
                "importe": importe,
                "sample": sample,
                "nombre_archivo": nombre_archivo,
                "total_factura_pdf": total_factura_pdf,
            })
        
        i += 1

    return registros


def parse_REVOX_B77(pdf_file, marca, proveedor):
    """
    Plantilla nueva de REVOX_B77 en PDF (exportada de Microsoft Dynamics 365
    Business Central) — reemplaza los Excel que usaban antes. Cada línea de
    ítem viene como: No. ItemInterno Barcode Descripción Cantidad"Pcs" Precio
    Importe CódigoAduana+País, todo en una sola línea de texto; si la
    descripción es larga, el resto se va a una línea suelta aparte que se
    ignora (ya se capturó suficiente descripción en la primera línea).
    """
    nombre_archivo = pdf_file.name
    texto = extraer_texto_pdf(pdf_file)

    invoice_match = re.search(r'Invoice No\.:\s*(\d+)', texto)
    invoice = invoice_match.group(1) if invoice_match else None
    if not invoice:
        return []

    fecha_match = re.search(r'Document Date:\s*(\d{2}/\d{2}/\d{4})', texto)
    if not fecha_match:
        return []
    fecha = fecha_match.group(1)
    periodo = datetime.strptime(fecha, "%d/%m/%Y").strftime("%Y%m")

    # "Date of payment: 11.08.26" -> DD.MM.YY (año a 2 dígitos)
    due_match = re.search(r'Date of payment:\s*(\d{2})\.(\d{2})\.(\d{2})', texto)
    due = f"{due_match.group(1)}/{due_match.group(2)}/20{due_match.group(3)}" if due_match else fecha

    po_match = re.search(r'^(IMP\d+(?:-\d+)?-\d{4})_', nombre_archivo)
    po = po_match.group(1) if po_match else None

    incoterm = normalizar_incoterm(texto)

    moneda_match = re.search(r'Total\s+([A-Z]{3})\s+Excl\.\s+VAT', texto)
    moneda = moneda_match.group(1) if moneda_match else "EUR"

    sample = detectar_sample(texto)

    total_match = re.search(r'Total\s+[A-Z]{3}\s+Incl\.\s+VAT\s+([\d,]+\.\d+)', texto)
    total_factura_pdf = float(total_match.group(1).replace(',', '')) if total_match else _extraer_total_generico(texto)

    lineas = [l.strip() for l in texto.split("\n") if l.strip()]
    patron_item = re.compile(
        r"^\d+\s+"                 # No. de línea correlativo (no es un código, se descarta)
        r"(\d+)\s+"                # Item interno (Revuele Item)
        r"(\d{13})\s+"             # Barcode / EAN-13
        r"(.+?)\s+"                # Descripción (no-greedy; puede continuar en la línea siguiente)
        r"([\d,]+\.\d+)Pcs\s+"     # Cantidad, con "Pcs" pegado sin espacio
        r"([\d.]+)\s+"             # Precio unitario neto
        r"([\d,]+\.\d+)\s+"        # Importe
        r"(\S+)$"                  # Código de aduana + país pegados (ej. 34013000BG)
    )

    registros = []
    for l in lineas:
        m = patron_item.match(l)
        if not m:
            continue

        item_interno, barcode, descripcion, cantidad_str, precio_str, importe_str, _custom_pais = m.groups()
        cantidad = float(cantidad_str.replace(",", ""))
        precio = float(precio_str.replace(",", ""))
        importe = float(importe_str.replace(",", ""))

        registros.append({
            "id": f"{marca}_{po if po else 'SIN_PO'}_{invoice}_{periodo}_{item_interno}_{barcode}",
            "marca": marca,
            "proveedor": proveedor,
            "invoice": invoice,
            "invoice_date": fecha,
            "due_date": due,
            "po": po,
            "incoterm": incoterm,
            "periodo": periodo,
            "item": item_interno,
            "codigo_producto": barcode,
            "tipo_codigo": "EAN",
            "descripcion": descripcion[:300],
            "cantidad": cantidad,
            "costo_unitario": precio,
            "moneda": moneda,
            "importe": round(importe, 2),
            "sample": sample,
            "nombre_archivo": nombre_archivo,
            "total_factura_pdf": total_factura_pdf,
        })

    return registros

# ══════════════════════════════════════════════════════════════════
# ROUTER
# ══════════════════════════════════════════════════════════════════

def _marcar_muestra_en_id(registros):
    """
    Le agrega '_Y' o '_N' al id de cada línea según si es una muestra
    ('sample' == 'Y') o no. Sin esto, una línea de una factura de muestra
    (precio 0) puede terminar con el mismo id que la línea de una factura
    real con precio si coinciden marca/po/invoice/periodo/item, y una pisa a
    la otra en el Sheet (deduplicación por id).
    """
    for r in registros:
        if not r.get("id"):
            continue
        sufijo = "Y" if str(r.get("sample", "")).strip().upper() == "Y" else "N"
        r["id"] = f"{r['id']}_{sufijo}"
    return registros


def parse_document(file_path, marca, proveedor):
    """
    Router unificado para PDF y Excel. Delega en _parse_document_bruto() y le
    agrega el sufijo _Y/_N de muestra al id antes de devolver los registros.
    """
    return _marcar_muestra_en_id(_parse_document_bruto(file_path, marca, proveedor))


def _parse_document_bruto(file_path, marca, proveedor):
    """
    Router real (sin el sufijo de muestra en el id) — no llamar directo desde
    afuera, usar parse_document().
    """
    # REVOX_B77: PDF es la plantilla vigente; Excel se mantiene por compatibilidad
    # con archivos antiguos que puedan quedar pendientes de procesar.
    if marca == "REVOX_B77":
        if file_path.suffix.lower() == '.pdf':
            return parse_REVOX_B77(file_path, marca, proveedor)
        elif file_path.suffix.lower() == '.xlsx':
            return parse_REVOX_B77_excel(file_path, marca, proveedor)
        return []

    # Para el resto de marcas, solo PDF
    if file_path.suffix.lower() != '.pdf':
        return []

    if marca == "7_DAYS":
        return parse_7_days(file_path, marca, proveedor)
    elif marca == "FOAMOUS":
        return parse_foamous(file_path, marca, proveedor)
    elif marca == "COZI_LIFE":
        return parse_cozi_life(file_path, marca, proveedor)
    elif marca == "LATAM_CHINA":
        return parse_latam_china(file_path, marca, proveedor)
    elif marca in ("FUJIAN_OUKANG", "BORLA"):
        return parse_fujian_oukang(file_path, marca, proveedor)
    elif marca == "LANEIGE":
        return parse_laneige(file_path, marca, proveedor)
    elif marca == "BEAUTY_CREATIONS":
        return parse_beauty(file_path, marca, proveedor)
    elif marca == "BETER":
        return parse_beter(file_path, marca, proveedor)
    elif marca == "MARIO_BADESCU":
        return parse_mario(file_path, marca, proveedor)
    elif marca == "PETRIZZIO":
        return parse_petrizzio(file_path, marca, proveedor)
    elif marca == "TONY_MOLY_HOLIKA_HOLIKA":
        return parse_tony_moly(file_path, marca, proveedor)
    elif marca == "ANASTASIA_BEVERLY_HILLS":
        return parse_anastasia(file_path, marca, proveedor)
    elif marca == "BOLDIFY":
        return parse_boldify(file_path, marca, proveedor)
    elif marca == "COSRX":
        return parse_cosrx(file_path, marca, proveedor)
    elif marca == "KOCOSTAR":
        return parse_kocostar(file_path, marca, proveedor)
    elif marca == "FLOOKY":
        return parse_flooky(file_path, marca, proveedor)
    elif marca == "OLAPLEX":
        return parse_olaplex(file_path, marca, proveedor)
    elif marca in ["TIRTIR", "TOCOBO", "MEDICUBE"]:
        return parse_silicon2(file_path, marca, proveedor)
    elif marca == "SLICK_HAIR":
        return parse_slick_hair(file_path, marca, proveedor)
    elif marca == "PIXI":
        return parse_pixi(file_path, marca, proveedor)
    elif marca == "THEBALM":
        return parse_thebalm(file_path, marca, proveedor)
    elif marca == "CISNE_NEGRO":
        return parse_cisne_negro(file_path, marca, proveedor)
    elif marca == "HELLO_SUNDAY":
        return parse_hello_sunday(file_path, marca, proveedor)
    elif marca == "EARTH_RHYTHM":
        return parse_earth_rhythm(file_path, marca, proveedor)
    elif marca == "NEW_STUDIO":
        return parse_new_studio(file_path, marca, proveedor)
    return []

# Mantener parse_pdf por compatibilidad (opcional)
def parse_pdf(pdf_file, marca, proveedor):
    return parse_document(pdf_file, marca, proveedor)

# ══════════════════════════════════════════════════════════════════
# CONVERSIÓN A PEN Y DUE_DAYS (reutilizable por el batch y por la app de revisión)
# ══════════════════════════════════════════════════════════════════

def _extraer_tasas_de_pdf_sunat(pdf_path):
    """Parsea un solo PDF mensual de SUNAT y devuelve {fecha (YYYY-MM-DD): usd_pen}."""
    import pdfplumber

    meses = {'ENERO':1,'FEBRERO':2,'MARZO':3,'ABRIL':4,'MAYO':5,'JUNIO':6,
             'JULIO':7,'AGOSTO':8,'SETIEMBRE':9,'SEPTIEMBRE':9,'OCTUBRE':10,'NOVIEMBRE':11,'DICIEMBRE':12}

    tasas = {}
    with pdfplumber.open(pdf_path) as pdf:
        texto = pdf.pages[0].extract_text()

        # Extraer periodo (ej: "ENERO - 2025")
        periodo_match = re.search(r'(\w+)\s*-\s*(\d{4})', texto)
        if not periodo_match:
            return tasas

        mes_nombre = periodo_match.group(1).upper()
        anio = int(periodo_match.group(2))
        mes = meses.get(mes_nombre, 1)

        # Extraer tabla de tasas
        tabla = pdf.pages[0].extract_table()
        for fila in tabla:
            for i in range(0, len(fila), 3):
                if i+2 < len(fila) and fila[i] and fila[i].strip().isdigit():
                    dia = int(fila[i].strip())
                    venta = float(fila[i+2].strip())
                    usd_pen = round(venta, 4)
                    fecha = f"{anio}-{mes:02d}-{dia:02d}"
                    tasas[fecha] = usd_pen
    return tasas


def _cargar_usd_pen_dict():
    """Junta las tasas USD/PEN de todos los PDFs de SUNAT en SUNAT_DIR,
    reusando lo ya parseado en _SUNAT_RATES_CACHE (por ruta+mtime) — solo se
    vuelve a leer un PDF si es nuevo o si cambió desde la última vez."""
    global _SUNAT_RATES_CACHE
    usd_pen_dict = {}
    for pdf_path in SUNAT_DIR.glob("*.pdf"):
        try:
            mtime = pdf_path.stat().st_mtime
            clave = str(pdf_path)
            cacheado = _SUNAT_RATES_CACHE.get(clave)
            if cacheado is not None and cacheado[0] == mtime:
                tasas = cacheado[1]
            else:
                tasas = _extraer_tasas_de_pdf_sunat(pdf_path)
                _SUNAT_RATES_CACHE[clave] = (mtime, tasas)
            usd_pen_dict.update(tasas)
        except Exception as e:
            print(f"      ⚠ Error leyendo {pdf_path.name}: {e}")
    return usd_pen_dict


def _cargar_eur_usd_dict():
    """Descarga el XML de tipo de cambio de referencia EUR/USD del BCE una
    sola vez por proceso (_EUR_USD_CACHE) — las tasas de fechas pasadas no
    cambian, así que no hay que volver a pegarle a la red en cada llamada."""
    global _EUR_USD_CACHE
    if _EUR_USD_CACHE is not None:
        return _EUR_USD_CACHE

    import requests

    BCE_URL = "https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/usd.xml"
    eur_usd_dict = {}

    try:
        response = requests.get(BCE_URL, timeout=30)
        response.raise_for_status()
        contenido = response.text

        # Buscar patrones en el XML
        patron = r'<Obs\s+TIME_PERIOD="([^"]+)"\s+OBS_VALUE="([^"]+)"'
        matches = re.findall(patron, contenido)

        if not matches:
            # Intentar con orden inverso
            patron2 = r'<Obs\s+OBS_VALUE="([^"]+)"\s+TIME_PERIOD="([^"]+)"'
            matches = re.findall(patron2, contenido)
            for valor, fecha in matches:
                eur_usd_dict[fecha] = float(valor)
        else:
            for fecha, valor in matches:
                eur_usd_dict[fecha] = float(valor)

    except Exception as e:
        print(f"   ⚠ Error descargando XML del BCE: {e}")

    _EUR_USD_CACHE = eur_usd_dict
    return eur_usd_dict


def resumen_tc_disponible():
    """Rango de meses con tipo de cambio USD/PEN cargado (a partir de los
    PDFs de SUNAT en SUNAT_DIR) más los meses faltantes DENTRO de ese
    rango — para que la app avise apenas arranca, antes de procesar
    cualquier factura, si el analista se está por quedar corto con datos
    recientes. Incluye la fecha exacta (día) más reciente disponible, no
    solo el mes — un mes puede aparecer en el rango con datos parciales
    (ej. el PDF se subió a mitad de mes), y solo viendo el día exacto se
    puede confirmar si ese mes está completo o no. Devuelve None si no hay
    ningún PDF de SUNAT."""
    usd_pen_dict = _cargar_usd_pen_dict()
    if not usd_pen_dict:
        return None

    fechas = sorted(usd_pen_dict.keys())
    fecha_min, fecha_max = fechas[0], fechas[-1]

    periodos = sorted({f"{fecha[:4]}{fecha[5:7]}" for fecha in usd_pen_dict.keys()})
    periodo_min, periodo_max = periodos[0], periodos[-1]

    todos_los_meses = []
    anio, mes = int(periodo_min[:4]), int(periodo_min[4:])
    anio_fin, mes_fin = int(periodo_max[:4]), int(periodo_max[4:])
    while (anio, mes) <= (anio_fin, mes_fin):
        todos_los_meses.append(f"{anio}{mes:02d}")
        mes += 1
        if mes > 12:
            mes = 1
            anio += 1

    periodos_set = set(periodos)
    meses_faltantes = [p for p in todos_los_meses if p not in periodos_set]

    dias_ultimo_mes = sorted(f for f in fechas if f.startswith(f"{periodo_max[:4]}-{periodo_max[4:]}"))

    return {
        "fecha_min": fecha_min,
        "fecha_max": fecha_max,
        "dias_ultimo_mes": len(dias_ultimo_mes),
        "periodo_min": periodo_min,
        "periodo_max": periodo_max,
        "meses_faltantes": meses_faltantes,
    }


def calcular_conversion_pen(df):
    """
    Agrega columnas 'tc', 'costo_unitario_pen' e 'importe_pen' al DataFrame,
    usando USD/PEN de PDFs de SUNAT y EUR/USD del XML del BCE. Ambas fuentes
    se cachean en memoria por proceso (ver _cargar_usd_pen_dict/
    _cargar_eur_usd_dict) — llamar esta función varias veces (ej. cada vez
    que la app recalcula tras subir un PDF de SUNAT que faltaba) no vuelve a
    releer PDFs ya vistos ni a pegarle de nuevo a la red del BCE.
    """
    if df.empty or 'invoice_date' not in df.columns or 'moneda' not in df.columns:
        return df

    print("\n💰 Calculando conversión a PEN usando fuentes oficiales...")

    from datetime import timedelta

    print("   📄 Extrayendo USD/PEN desde PDFs de SUNAT...")
    usd_pen_dict = _cargar_usd_pen_dict()
    print(f"   ✅ USD/PEN cargadas: {len(usd_pen_dict)} fechas")

    print("   📄 Extrayendo EUR/USD desde BCE...")
    eur_usd_dict = _cargar_eur_usd_dict()

    print(f"   ✅ EUR/USD cargadas: {len(eur_usd_dict)} fechas")

    # ========== 3. FUNCIÓN PARA BUSCAR TASA MÁS CERCANA (hacia atrás) ==========
    def obtener_tasa_mas_cercana(fecha_buscar, dict_tasas, max_dias_atras=5):
        """
        Busca la tasa más cercana disponible (menor o igual a fecha_buscar,
        hasta max_dias_atras de ventana — cubre fines de semana/feriados
        cortos). Retorna None si no hay datos en esa ventana: NO cae de
        vuelta a "la tasa más antigua disponible en todo el diccionario"
        (ese fallback existía antes acá, pero como casi cualquier fecha de
        búsqueda es mayor que la fecha más antigua del dict, en la práctica
        SIEMPRE se disparaba — así que un mes realmente faltante (ej. una
        factura de un mes futuro sin PDF de SUNAT todavía) terminaba con una
        tasa de hace años aplicada en silencio, en vez de quedar en None
        para que la app detecte el hueco y pida subir el PDF que falta).
        """
        if not dict_tasas:
            return None

        fecha_buscar_str = fecha_buscar.strftime("%Y-%m-%d")

        # Si existe exactamente, usarla
        if fecha_buscar_str in dict_tasas:
            return dict_tasas[fecha_buscar_str]

        # Buscar hacia atrás día por día
        fecha_temp = fecha_buscar
        for _ in range(max_dias_atras):
            fecha_temp -= timedelta(days=1)
            fecha_temp_str = fecha_temp.strftime("%Y-%m-%d")
            if fecha_temp_str in dict_tasas:
                return dict_tasas[fecha_temp_str]

        return None

    # ========== 4. APLICAR CONVERSIÓN FILA POR FILA ==========
    tc_list = []
    costo_pen_list = []
    importe_pen_list = []

    fechas_procesadas = {}  # Cache para evitar recalcular misma fecha

    for idx, row in df.iterrows():
        fecha_str = row.get('invoice_date')
        moneda = row.get('moneda', '')

        if pd.isna(fecha_str) or not moneda or moneda not in ['USD', 'EUR']:
            tc_list.append(None)
            costo_pen_list.append(None)
            importe_pen_list.append(None)
            continue

        try:
            fecha_obj = datetime.strptime(fecha_str, "%d/%m/%Y")

            # Verificar cache
            cache_key = (fecha_str, moneda)
            if cache_key in fechas_procesadas:
                tc = fechas_procesadas[cache_key]
            else:
                if moneda == 'USD':
                    tasa_usd = obtener_tasa_mas_cercana(fecha_obj, usd_pen_dict)
                    tc = tasa_usd if tasa_usd is not None else None
                    fechas_procesadas[cache_key] = tc

                elif moneda == 'EUR':
                    tasa_eur_usd = obtener_tasa_mas_cercana(fecha_obj, eur_usd_dict)
                    tasa_usd_pen = obtener_tasa_mas_cercana(fecha_obj, usd_pen_dict)

                    if tasa_eur_usd is not None and tasa_usd_pen is not None:
                        tc = tasa_eur_usd * tasa_usd_pen  # Tasa cruzada EUR → PEN
                    else:
                        tc = None
                    fechas_procesadas[cache_key] = tc

                else:
                    tc = None
                    fechas_procesadas[cache_key] = tc

            tc_list.append(tc)

            # Calcular valores en PEN si hay tasa
            if tc is not None:
                costo = row.get('costo_unitario', 0)
                importe = row.get('importe', 0)

                costo_pen = costo * tc if pd.notna(costo) else None
                importe_pen = importe * tc if pd.notna(importe) else None

                costo_pen_list.append(round(costo_pen, 2) if costo_pen is not None else None)
                importe_pen_list.append(round(importe_pen, 2) if importe_pen is not None else None)
            else:
                costo_pen_list.append(None)
                importe_pen_list.append(None)

        except Exception as e:
            tc_list.append(None)
            costo_pen_list.append(None)
            importe_pen_list.append(None)

    # Asignar columnas al DataFrame
    df['tc'] = tc_list
    df['costo_unitario_pen'] = costo_pen_list
    df['importe_pen'] = importe_pen_list

    # ========== 5. MOSTRAR RESUMEN ==========
    registros_con_tc = df['tc'].notna().sum()
    print(f"   ✅ Registros con tasa aplicada: {registros_con_tc} de {len(df)}")

    if registros_con_tc > 0:
        # Mostrar muestra
        muestra = df[df['tc'].notna()][['invoice_date', 'moneda', 'importe', 'tc', 'importe_pen']].head(5)
        if not muestra.empty:
            print(f"\n   📊 Ejemplo de conversión:")
            print(muestra.to_string())

        # Estadísticas por moneda
        print(f"\n   📊 Estadísticas por moneda:")
        for moneda in ['USD', 'EUR']:
            mask_moneda = df['moneda'] == moneda
            mask_tc = df['tc'].notna()
            count = (mask_moneda & mask_tc).sum()
            total = mask_moneda.sum()
            if total > 0:
                pct = (count / total) * 100
                print(f"      • {moneda}: {count}/{total} registros ({pct:.1f}%)")

    return df


def calcular_due_days(df):
    """
    Agrega la columna 'due_days' (diferencia en días entre due_date e invoice_date).
    """
    if df.empty or "invoice_date" not in df.columns or "due_date" not in df.columns:
        return df

    print("\n📅 Calculando due_days (diferencia entre due_date e invoice_date)...")

    # Guardar copia original de fechas en string (para preservar formato)
    df["_invoice_date_str"] = df["invoice_date"]
    df["_fecha_str"] = df["due_date"]

    # Convertir a datetime para calcular diferencia
    df["invoice_date_dt"] = pd.to_datetime(df["invoice_date"], format="%d/%m/%Y", errors='coerce')
    df["due_date_dt"] = pd.to_datetime(df["due_date"], format="%d/%m/%Y", errors='coerce')

    # Calcular diferencia en días
    df["due_days"] = (df["due_date_dt"] - df["invoice_date_dt"]).dt.days

    # Reemplazar NaN con 0
    df["due_days"] = df["due_days"].fillna(0).astype(int)

    # Mostrar estadísticas
    print(f"   ✅ due_days calculado - Rango: {df['due_days'].min()} a {df['due_days'].max()} días")
    print(f"   📊 Media: {df['due_days'].mean():.1f} días | Mediana: {df['due_days'].median():.0f} días")

    # Restaurar fechas originales en formato string (para Google Sheets)
    df["invoice_date"] = df["_invoice_date_str"]
    df["due_date"] = df["_fecha_str"]

    # Eliminar columnas temporales
    df = df.drop(columns=["_invoice_date_str", "_fecha_str", "invoice_date_dt", "due_date_dt"])

    # Mostrar muestra
    muestra = df[["invoice_date", "due_date", "due_days"]].head(5)
    if not muestra.empty:
        print(f"\n   📊 Ejemplo de cálculo:")
        print(muestra.to_string())

    return df

# ══════════════════════════════════════════════════════════════════
# PIPELINE
# ══════════════════════════════════════════════════════════════════

def procesar():
    todos = []
    
    # Obtener marcas a procesar según configuración
    marcas_a_procesar = obtener_marcas_a_procesar()
    
    if not marcas_a_procesar:
        print("❌ No hay marcas para procesar. Verifica la configuración MARCAS_A_PROCESAR")
        return pd.DataFrame(), {}
    
    # Estadísticas globales
    tiempos_facturas = []
    facturas_procesadas = 0
    facturas_con_error = 0
    facturas_omitidas = 0
    inicio_total = perf_counter()
    
    # Resumen por marca
    resumen_marcas = {}

    for marca, config in marcas_a_procesar.items():
        path = config["ruta"]
        proveedor = config["proveedor"]
        
        print(f"\n{'='*60}")
        print(f"📦 PROCESANDO MARCA: {marca} (Proveedor: {proveedor})")
        print(f"{'='*60}")
        
        raw = path / "raw"
        worked = path / "worked"
        worked.mkdir(exist_ok=True)
        
        # Verificar que la carpeta raw existe
        if not raw.exists():
            print(f"⚠ CARPETA NO ENCONTRADA: {raw}")
            continue
        
        # Estadísticas por marca
        facturas_marca = 0
        tiempo_marca = 0
        omitidas_marca = 0
        
        # Listar archivos encontrados (PDF y Excel)
        archivos_raw = []
        archivos_raw.extend(raw.glob("*.pdf"))
        archivos_raw.extend(raw.glob("*.xlsx"))
        
        if archivos_raw:
            print(f"📄 Documentos encontrados en raw: {len(archivos_raw)}")
        else:
            print(f"📄 No hay documentos en raw para {marca}")

        # MOVER + RENOMBRAR
        for archivo in archivos_raw:
            inicio_factura = perf_counter()
            try:
                # Para REVOX_B77 en Excel
                if marca == "REVOX_B77" and archivo.suffix.lower() == '.xlsx':
                    nombre_final = generar_nombre(archivo, marca, proveedor)
                    if nombre_final is None:
                        print(f"   ⚠ {archivo.name}: No se pudo generar nombre - omitido")
                        facturas_con_error += 1
                        facturas_omitidas += 1
                        omitidas_marca += 1
                        continue
                    
                    destino = worked / nombre_final
                    if destino.exists():
                        print(f"   🔄 Reemplazando versión anterior: {nombre_final}")
                        destino.unlink()
                    shutil.move(str(archivo), str(destino))
                    print(f"   ✅ Excel renombrado: {nombre_final}")
                    
                    tiempo_factura = perf_counter() - inicio_factura
                    tiempos_facturas.append(tiempo_factura)
                    facturas_procesadas += 1
                    facturas_marca += 1
                    tiempo_marca += tiempo_factura
                    continue
                
                # Para PDFs: validar y renombrar
                if archivo.suffix.lower() == '.pdf':
                    es_valida, razon = es_factura_valida(archivo, verbose=True)
                    
                    if not es_valida:
                        print(f"   🚫 {archivo.name}: Documento NO factura ({razon}) - omitido")
                        facturas_con_error += 1
                        facturas_omitidas += 1
                        omitidas_marca += 1
                        continue
                    
                    nombre_final = generar_nombre(archivo, marca, proveedor)
                    if nombre_final is None:
                        print(f"   ⚠ {archivo.name}: No se pudo generar nombre - omitido")
                        facturas_con_error += 1
                        facturas_omitidas += 1
                        omitidas_marca += 1
                        continue
                    
                    destino = worked / nombre_final
                    if destino.exists():
                        print(f"   🔄 Reemplazando versión anterior: {nombre_final}")
                        destino.unlink()
                    shutil.move(str(archivo), str(destino))
                    print(f"   ✅ Nueva versión guardada: {nombre_final}")
                    
                    tiempo_factura = perf_counter() - inicio_factura
                    tiempos_facturas.append(tiempo_factura)
                    facturas_procesadas += 1
                    facturas_marca += 1
                    tiempo_marca += tiempo_factura
                    
                    print(f"   📁 {nombre_final} (⏱ {tiempo_factura:.2f}s)")
                
            except Exception as e:
                facturas_con_error += 1
                print(f"   ❌ Error {archivo.name}: {e}")

        # LEER WORKED
        archivos_worked = []
        archivos_worked.extend(worked.glob("*.pdf"))
        archivos_worked.extend(worked.glob("*.xlsx"))
        
        if archivos_worked:
            print(f"📄 Procesando {len(archivos_worked)} documentos en worked...")
            for doc in archivos_worked:
                try:
                    print(f"   🔍 Procesando: {doc.name}")
                    print(f"   📁 Extensión: {doc.suffix}")
                    print(f"   🏷 Marca: {marca}")
                    
                    inicio_parse = perf_counter()
                    registros = parse_document(doc, marca, proveedor)
                    tiempo_parse = perf_counter() - inicio_parse
                    
                    print(f"   📊 Registros encontrados: {len(registros)}")
                    
                    todos.extend(registros)
                    
                    if len(registros) > 0:
                        print(f"   ✅ {doc.name}: {len(registros)} items (⏱ {tiempo_parse:.2f}s)")
                    else:
                        print(f"   ⚠ {doc.name}: No se extrajeron items")
                    
                except Exception as e:
                    print(f"   ❌ Error parseando {doc.name}: {e}")
        
        # Guardar resumen por marca
        if facturas_marca > 0:
            resumen_marcas[marca] = {
                "facturas": facturas_marca,
                "omitidas": omitidas_marca,
                "tiempo_total": tiempo_marca,
                "tiempo_promedio": tiempo_marca / facturas_marca if facturas_marca > 0 else 0
            }
            print(f"\n📊 {marca}: {facturas_marca} documentos procesados, {omitidas_marca} omitidas en {formatear_tiempo(tiempo_marca)}")
        else:
            if omitidas_marca > 0:
                print(f"\n📊 {marca}: {omitidas_marca} documentos omitidos")
            else:
                print(f"\n📊 {marca}: No se procesaron documentos")

        tiempo_total = perf_counter() - inicio_total
    
    # Calcular estadísticas
    if tiempos_facturas:
        tiempo_promedio = sum(tiempos_facturas) / len(tiempos_facturas)
        factura_mas_rapida = min(tiempos_facturas)
        factura_mas_lenta = max(tiempos_facturas)
    else:
        tiempo_promedio = factura_mas_rapida = factura_mas_lenta = 0

    # Mostrar resumen de ejecución
    print("\n" + "═" * 60)
    print("📊 RESUMEN DE EJECUCIÓN")
    print("═" * 60)
    
    print(f"\n⏱ TIEMPO TOTAL: {formatear_tiempo(tiempo_total)}")
    print(f"📄 DOCUMENTOS PROCESADOS (movidos a worked): {facturas_procesadas}")
    print(f"🚫 DOCUMENTOS OMITIDOS (permanecen en raw): {facturas_omitidas}")
    print(f"⚠ TOTAL DE ERRORES: {facturas_con_error}")
    
    if tiempos_facturas:
        print(f"⏱ TIEMPO PROMEDIO POR DOCUMENTO: {tiempo_promedio:.2f}s")
        print(f"⚡ DOCUMENTO MÁS RÁPIDO: {factura_mas_rapida:.2f}s")
        print(f"🐌 DOCUMENTO MÁS LENTO: {factura_mas_lenta:.2f}s")
    
    # Mostrar resumen por marca
    if resumen_marcas:
        print("\n" + "─" * 60)
        print("📊 RESUMEN POR MARCA:")
        print("─" * 60)
        for marca, stats in sorted(resumen_marcas.items()):
            print(f"  • {marca}: {stats['facturas']} documentos | "
                  f"Omitidas: {stats.get('omitidas', 0)} | "
                  f"Total: {formatear_tiempo(stats['tiempo_total'])} | "
                  f"Prom: {stats['tiempo_promedio']:.2f}s")
        
    # Procesar DataFrame
    df = pd.DataFrame(todos)
    if not df.empty:
        df = df.drop_duplicates(subset=["id"])
        
        # ========== LIMPIEZA DE NaN PARA GOOGLE SHEETS ==========
        for col in df.columns:
            if df[col].dtype in ['float64', 'int64']:
                df[col] = df[col].fillna(0)
            else:
                df[col] = df[col].fillna("")
        
        columnas_numericas = ["cantidad", "costo_unitario", "importe", "due_days"]
        for col in columnas_numericas:
            if col in df.columns:
                df[col] = df[col].fillna(0)
        
        # 👇 AGREGAR FECHA DE CARGA AQUÍ 👇
        df['fecha_carga'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        print(f"\n📊 Registros únicos después de deduplicación: {len(df)}")

    # ========== CONVERSIÓN A PEN Y DUE_DAYS ==========
    df = calcular_conversion_pen(df)
    df = calcular_due_days(df)

    # ========== INGESTA SEGÚN MODO ==========
    
    # MODO TOTAL: Limpia y recarga todo
    if MODO_INGESTA == "TOTAL":
        print("\n" + "═" * 60)
        print("🔥 MODO TOTAL: LIMPIANDO Y RECARGANDO GOOGLE SHEETS")
        print("═" * 60)
        
        if df.empty:
            print("⚠ No hay datos para cargar")
        else:
            sheet = conectar_google_sheets()
            
            if sheet:
                # 1. Limpiar todas las filas (excepto encabezados)
                print("🧹 Limpiando datos existentes en Google Sheets...")
                try:
                    todas_filas = sheet.get_all_values()
                    if len(todas_filas) > 1:
                        # Obtener la última columna con datos (para limpiar todo)
                        ultima_columna = sheet.col_count
                        # Convertir número de columna a letra (ej: 26 -> Z, 27 -> AA)
                        def col_num_to_letter(col_num):
                            letra = ""
                            while col_num > 0:
                                col_num -= 1
                                letra = chr(65 + col_num % 26) + letra
                                col_num //= 26
                            return letra
                        
                        ultima_letra = col_num_to_letter(ultima_columna)
                        rango_limpieza = f"A2:{ultima_letra}{len(todas_filas)}"
                        sheet.batch_clear([rango_limpieza])
                        print(f"   ✅ Borradas {len(todas_filas) - 1} filas (columnas A hasta {ultima_letra})")
                except Exception as e:
                    print(f"   ⚠ Error al limpiar: {e}")
                
                # 2. Generar CSV si está configurado
                if GENERAR_CSV_EN_TOTAL:
                    output_file = OUTPUT_PATH / "facturas_importaciones_total.csv"
                    df.to_csv(output_file, index=False)
                    print(f"\n💾 CSV generado: {output_file}")
                    print(f"📦 Filas: {len(df)}")
                
                # 3. Insertar todos los registros en lotes
                print(f"\n📤 Insertando {len(df)} registros en Google Sheets...")
                
                registros = df.to_dict('records')
                nuevos, duplicados = insertar_todos_los_registros(sheet, registros)
                
                print(f"\n📊 RESULTADO CARGA TOTAL:")
                print(f"   ✅ Insertados: {nuevos}")
                print(f"   ⏭️ No insertados: {duplicados}")
    
    # MODO INCREMENTAL: Solo facturas nuevas
    elif MODO_INGESTA == "INCREMENTAL":
        print("\n" + "═" * 60)
        print("📤 MODO INCREMENTAL: SOLO FACTURAS NUEVAS")
        print("═" * 60)
        
        if df.empty:
            print("⚠ No hay datos para procesar")
        else:
            sheet = conectar_google_sheets()
            
            if sheet:
                ids_existentes = obtener_ids_existentes(sheet)
                print(f"📊 IDs existentes en Google Sheets: {len(ids_existentes)}")
                print(f"📦 Registros a procesar: {len(df)}")
                
                registros = df.to_dict('records')
                nuevos, duplicados = insertar_en_sheet_incremental(sheet, registros, ids_existentes)
                
                print(f"\n📊 RESULTADO INCREMENTAL:")
                print(f"   ✅ Nuevos insertados: {nuevos}")
                print(f"   ⏭️ Duplicados omitidos: {duplicados}")
    
    # MODO SOLO CSV: Solo guardar archivo local
    elif MODO_INGESTA == "SOLO_CSV":
        print("\n" + "═" * 60)
        print("💾 MODO SOLO CSV: GUARDANDO ARCHIVO LOCAL")
        print("═" * 60)
        
        if not df.empty:
            output_file = OUTPUT_PATH / "facturas_importaciones.csv"
            df.to_csv(output_file, index=False)
            print(f"✅ CSV guardado: {output_file}")
            print(f"📦 Filas: {len(df)}")
        else:
            print("⚠ No hay datos para guardar")
    
    else:
        print(f"\n⚠ MODO DE INGESTA NO RECONOCIDO: {MODO_INGESTA}")
        print("   Opciones válidas: 'TOTAL', 'INCREMENTAL', 'SOLO_CSV'")
    
    # Mostrar estadísticas adicionales del DataFrame si hay datos
    if not df.empty:
        print(f"\n📊 PROCESANDO DATAFRAME:")
        print(f"  • Registros únicos: {len(df)}")
        print(f"  • Columnas: {list(df.columns)}")
        
        # Mostrar resumen de due_days si existe (solo para verificación)
        if "due_days" in df.columns:
            print(f"  • due_days calculado - Media: {df['due_days'].mean():.1f} días | Máx: {df['due_days'].max()} días")
    else:
        print("\n⚠ ATENCIÓN: No se generaron registros")

    # ========== AHORRO DE TIEMPO ESTIMADO ==========
    print("\n" + "═" * 60)
    print("⏱ AHORRO DE TIEMPO ESTIMADO")
    print("═" * 60)
    
    # Calcular total de facturas reales (documentos en worked)
    total_facturas_reales = 0
    for marca, config in marcas_a_procesar.items():
        path = config["ruta"]
        worked_path = path / "worked"
        if worked_path.exists():
            total_facturas_reales += len(list(worked_path.glob("*.pdf"))) + len(list(worked_path.glob("*.xlsx")))
    
    # Tiempo manual estimado por factura: entre 45 y 60 minutos
    tiempo_manual_min = 45  # minutos
    tiempo_manual_max = 60  # minutos
    tiempo_manual_promedio = (tiempo_manual_min + tiempo_manual_max) / 2
    
    # Tiempo automático (de la ejecución)
    tiempo_auto_promedio_minutos = tiempo_promedio / 60 if tiempos_facturas else 0
    
    # Ahorro por factura
    ahorro_por_factura_min = tiempo_manual_promedio - tiempo_auto_promedio_minutos
    ahorro_total_minutos = ahorro_por_factura_min * total_facturas_reales if total_facturas_reales > 0 else 0
    ahorro_total_horas = ahorro_total_minutos / 60
    jornadas_8h = ahorro_total_horas / 8 if ahorro_total_horas > 0 else 0
    
    print(f"\n📊 COMPARATIVA POR FACTURA:")
    print(f"   • Tiempo manual estimado: {tiempo_manual_promedio:.0f} minutos")
    print(f"   • Tiempo automático: {tiempo_auto_promedio_minutos:.2f} minutos")
    print(f"   • Ahorro por factura: {ahorro_por_factura_min:.1f} minutos")
    
    if total_facturas_reales > 0:
        print(f"\n💰 AHORRO TOTAL:")
        print(f"   • Facturas procesadas: {total_facturas_reales}")
        print(f"   • Ahorro total: {ahorro_total_horas:.1f} horas")
        print(f"   🔥 EQUIVALENTE A: {jornadas_8h:.1f} jornadas laborales de 8 horas 🔥")
        
        print(f"\n📈 RANGO ESTIMADO (según complejidad):")
        ahorro_min_horas = ((tiempo_manual_min - tiempo_auto_promedio_minutos) * total_facturas_reales) / 60
        ahorro_max_horas = ((tiempo_manual_max - tiempo_auto_promedio_minutos) * total_facturas_reales) / 60
        print(f"   • Ahorro mínimo: {ahorro_min_horas:.1f} horas ({ahorro_min_horas/8:.1f} jornadas)")
        print(f"   • Ahorro máximo: {ahorro_max_horas:.1f} horas ({ahorro_max_horas/8:.1f} jornadas)")
    
    print("\n" + "═" * 60)
    print("✅ PROCESO COMPLETADO")
    print("═" * 60)

    return df, {
        "tiempo_total": tiempo_total,
        "facturas_procesadas": facturas_procesadas,
        "facturas_omitidas": facturas_omitidas,
        "facturas_error": facturas_con_error,
        "tiempo_promedio": tiempo_promedio if tiempos_facturas else 0,
        "mas_rapida": factura_mas_rapida if tiempos_facturas else 0,
        "mas_lenta": factura_mas_lenta if tiempos_facturas else 0,
        "tiempos": tiempos_facturas,
        "resumen_marcas": resumen_marcas
    }

# ══════════════════════════════════════════════════════════════════
# FUNCIONES DE INGESTA PARA GOOGLE SHEETS (CON LIMPIEZA DE NaN Y FORMATO GOOGLE SHEETS)
# ══════════════════════════════════════════════════════════════════

def limpiar_valor(val, col_name=None):
    """Convierte NaN a None, y formatea para Google Sheets"""
    import math
    
    # NaN handling
    if isinstance(val, float) and math.isnan(val):
        return None
    if isinstance(val, str) and val.lower() == 'nan':
        return None
    if pd.isna(val):
        return None
    
    # FORZAR COMO TEXTO (evita que Google Sheets elimine ceros a la izquierda)
    if col_name in ["invoice", "item", "codigo_producto"] and val is not None:
        return str(val)  # Convertir a string explícitamente
    
    # CAPITALIZAR MARCA Y PROVEEDOR (con siglas en mayúscula)
    if col_name in ["marca", "proveedor"] and isinstance(val, str):
        val = val.replace('_', ' ')
        palabras = val.split()
        palabras_procesadas = []
        for p in palabras:
            if p.upper() in ['SA', 'LTD', 'INC', 'LLC', 'CO', 'CORP']:
                palabras_procesadas.append(p.upper())
            else:
                palabras_procesadas.append(p.capitalize())
        return ' '.join(palabras_procesadas)
    
    # FECHAS: Convertir DD/MM/YYYY -> YYYY-MM-DD
    if col_name in ["invoice_date", "due_date"] and val:
        try:
            fecha_obj = datetime.strptime(str(val), "%d/%m/%Y")
            return fecha_obj.strftime("%Y-%m-%d")
        except:
            return val
    
    # DECIMALES: Asegurar punto decimal
    if col_name in ["costo_unitario", "importe"] and isinstance(val, (int, float)):
        if math.isnan(val):
            return None
        if col_name == "importe":
            return "{:.2f}".format(val).replace(",", ".")
        return str(val).replace(",", ".")
    
    # CANTIDAD: entero limpio
    if col_name == "cantidad" and isinstance(val, (int, float)):
        if math.isnan(val):
            return None
        return int(val) if val == int(val) else val
    
    return val


def insertar_todos_los_registros(sheet, registros):
    """Inserta TODOS los registros (usado en modo TOTAL) - con formato Google Sheets"""
    if not sheet or not registros:
        return 0, 0
    
    orden_columnas = [
    "id", "marca", "proveedor", "invoice", "invoice_date", "due_date",
    "po", "incoterm", "periodo", "item", "codigo_producto", "tipo_codigo",
    "descripcion", "cantidad", "costo_unitario", "moneda", "importe",
    "sample", "nombre_archivo", "due_days", "fecha_carga",
    "tc", "costo_unitario_pen", "importe_pen"
]
    
    # Convertir a filas con formato correcto
    filas = []
    for reg in registros:
        fila = []
        for col in orden_columnas:
            val = reg.get(col, "")
            val = limpiar_valor(val, col)
            
            # Conversión final para números
            if isinstance(val, float):
                if math.isnan(val):
                    val = None
                else:
                    # Para Google Sheets, números como string o número directo
                    if col in ["costo_unitario", "importe"]:
                        val = float(val)  # Mantener como número
                    else:
                        val = int(val) if val == int(val) else val
            fila.append(val)
        filas.append(fila)
    
    # Insertar por lotes de 20
    batch_size = 20
    insertados = 0
    total_batches = (len(filas) + batch_size - 1) // batch_size
    
    print(f"   📦 Total lotes: {total_batches}")
    print(f"   ⏱ Tiempo estimado: ~{total_batches * 15} segundos")
    
    for i in range(0, len(filas), batch_size):
        lote = filas[i:i + batch_size]
        batch_num = i // batch_size + 1
        
        print(f"   📥 Lote {batch_num}/{total_batches}: {len(lote)} registros...", end=" ", flush=True)
        
        # Limpiar NaN dentro del lote
        lote_limpio = []
        for fila in lote:
            fila_limpia = []
            for v in fila:
                if isinstance(v, float) and math.isnan(v):
                    fila_limpia.append(None)
                else:
                    fila_limpia.append(v)
            lote_limpio.append(fila_limpia)
        
        try:
            sheet.append_rows(lote_limpio, value_input_option="USER_ENTERED")
            insertados += len(lote)
            print("✅")
        except Exception as e:
            print(f"❌ Error: {e}")
            # Fallback: insertar uno por uno
            for fila in lote_limpio:
                try:
                    sheet.append_row(fila, value_input_option="USER_ENTERED")
                    insertados += 1
                    time.sleep(0.5)
                except Exception as e2:
                    print(f"      ⚠ Fila fallida: {fila[0] if fila[0] else 'unknown'} - {e2}")
        
        # Esperar entre lotes
        if i + batch_size < len(filas):
            print(f"      ⏳ Esperando 15s antes del siguiente lote...")
            time.sleep(15)
    
    return insertados, len(registros) - insertados


def insertar_en_sheet_incremental(sheet, registros, ids_existentes):
    """Inserta solo registros nuevos (modo incremental) - con formato Google Sheets"""
    if not sheet or not registros:
        return 0, 0
    
    orden_columnas = [
    "id", "marca", "proveedor", "invoice", "invoice_date", "due_date",
    "po", "incoterm", "periodo", "item", "codigo_producto", "tipo_codigo",
    "descripcion", "cantidad", "costo_unitario", "moneda", "importe",
    "sample", "nombre_archivo", "due_days", "fecha_carga",
    "tc", "costo_unitario_pen", "importe_pen"
    ]
    
    # Filtrar solo los nuevos
    nuevos_registros = []
    for reg in registros:
        reg_id = reg.get("id")
        if reg_id and reg_id not in ids_existentes:
            nuevos_registros.append(reg)
    
    if not nuevos_registros:
        print("   📌 No hay registros nuevos para insertar")
        return 0, len(registros)
    
    print(f"   📦 Registros nuevos: {len(nuevos_registros)}")
    
    # Convertir a filas con formato correcto
    filas = []
    for reg in nuevos_registros:
        fila = []
        for col in orden_columnas:
            val = reg.get(col, "")
            val = limpiar_valor(val, col)
            
            # Conversión final para números
            if isinstance(val, float):
                if math.isnan(val):
                    val = None
                else:
                    if col in ["costo_unitario", "importe"]:
                        val = float(val)
                    else:
                        val = int(val) if val == int(val) else val
            fila.append(val)
        filas.append(fila)
    
    # Para incremental, lotes de 20
    batch_size = 20
    insertados = 0
    total_batches = (len(filas) + batch_size - 1) // batch_size
    
    for i in range(0, len(filas), batch_size):
        lote = filas[i:i + batch_size]
        batch_num = i // batch_size + 1
        
        print(f"   📥 Lote {batch_num}/{total_batches}: {len(lote)} registros...", end=" ", flush=True)
        
        # Limpiar NaN dentro del lote
        lote_limpio = []
        for fila in lote:
            fila_limpia = []
            for v in fila:
                if isinstance(v, float) and math.isnan(v):
                    fila_limpia.append(None)
                else:
                    fila_limpia.append(v)
            lote_limpio.append(fila_limpia)
        
        try:
            sheet.append_rows(lote_limpio, value_input_option="USER_ENTERED")
            insertados += len(lote)
            print("✅")
        except Exception as e:
            print(f"❌ Error: {e}")
            # Fallback: uno por uno
            for fila in lote_limpio:
                try:
                    sheet.append_row(fila, value_input_option="USER_ENTERED")
                    insertados += 1
                    time.sleep(1)
                except Exception as e2:
                    print(f"      ⚠ Fila fallida: {fila[0] if fila[0] else 'unknown'} - {e2}")
        
        # Espera entre lotes
        if i + batch_size < len(filas):
            print(f"      ⏳ Esperando 10s antes del siguiente lote...")
            time.sleep(10)
    
    return insertados, len(registros) - insertados

# ══════════════════════════════════════════════════════════════════
# EJECUCIÓN
# ══════════════════════════════════════════════════════════════════

if __name__ == "__main__":

    inicio_programa = perf_counter()

    df_final, estadisticas = procesar()

    tiempo_total = perf_counter() - inicio_programa

    print("\n" + "═" * 60)
    print("✅ PROCESO DE FACTURAS COMPLETADO")
    print("═" * 60)
    print(f"📊 Registros en memoria: {len(df_final)}")
    print(f"⏱ Tiempo total: {formatear_tiempo(estadisticas['tiempo_total'])}")