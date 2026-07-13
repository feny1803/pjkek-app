import streamlit as st
import pdfplumber
import re
import pandas as pd
import io
import gspread
from google.oauth2.service_account import Credentials

# --- 1. KONFIGURASI HALAMAN & TEMA ESTETIK KEK ---
st.set_page_config(
    page_title="Sistem Otomatisasi Data PJKEK - KEK Gresik", 
    page_icon="🏢", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# Kustomisasi CSS untuk menyamakan tema warna Corporate Blue KEK Gresik (Lebih Muda)
st.markdown("""
    <style>
        /* Background Sidebar Biru KEK yang Agak Lebih Muda */
        [data-testid="stSidebar"] {
            background-color: #136999 !important;
        }
        [data-testid="stSidebar"] .stMarkdown, [data-testid="stSidebar"] label {
            color: white !important;
        }
        /* Desain Tombol Ekstraksi */
        div.stButton > button:first-child {
            background-color: #136999;
            color: white;
            border-radius: 6px;
            border: none;
            padding: 0.6rem 2.5rem;
            font-weight: bold;
            font-size: 16px;
        }
        div.stButton > button:first-child:hover {
            background-color: #1d7aa8;
            color: white;
            border: none;
        }
        /* Penataan Info Box */
        .stAlert {
            border-radius: 8px;
        }
    </style>
""", unsafe_allow_html=True)

# ID Spreadsheet Database Anda
SPREADSHEET_ID = '10zL3C58Xi-I-ytICdzzHc7y04oPq2iKzcDCGL1oB8bs'

# --- 2. KONEKSI KE DATABASE GOOGLE SHEETS ---
@st.cache_resource
def init_gspread():
    scopes = ["https://www.googleapis.com/auth/spreadsheets"]
    secret_creds = dict(st.secrets["gcp_service_account"])
    creds = Credentials.from_service_account_info(secret_creds, scopes=scopes)
    return gspread.authorize(creds)

try:
    gc = init_gspread()
    sh = gc.open_by_key(SPREADSHEET_ID)
    worksheet = sh.get_worksheet(0)
    existing_filenames = set(worksheet.col_values(1))
except Exception as e:
    existing_filenames = set()
    worksheet = None

# --- 3. FUNGSI LOGIKA EKSTRAKSI PDF (DIPERBAIKI: NPWP & ALAMAT DITAMBAHKAN) ---
def extract_rincian_jkp(pdf):
    all_rows = []
    found_jkp_table = False
    for page in pdf.pages:
        tables = page.extract_tables()
        for table in tables:
            if not table or not table[0]: continue
            header = [str(cell).lower() for cell in table[0] if cell]

            if any("jenis" in h for h in header) and any("deskripsi" in h for h in header):
                found_jkp_table = True
            else:
                if not found_jkp_table: continue
                else: return all_rows

            for row in table[1:]:
                if not row or len(row) < 3: continue
                row = [cell.replace("\n", " ").strip() if cell else "" for cell in row]

                if re.match(r'^\d+$', row[0]):
                   all_rows.append({
                        "no": row[0],
                        "jenis": row[1],
                        "deskripsi": row[2],
                        "total_per_item": row[3].replace(",", "").replace(".", "") if row[3] else "0"
                    })
                elif len(all_rows) > 0 and (row[0] == "" or row[0] is None):
                    if len(row) > 1: all_rows[-1]["jenis"] += " " + row[1]
                    if len(row) > 2: all_rows[-1]["deskripsi"] += " " + row[2]
    return all_rows

def extract_pjkek_data(file_bytes, filename):
    full_text = ""
    last_page_text = ""
    with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
        for i, page in enumerate(pdf.pages):
            text = page.extract_text()
            if text: full_text += text + "\n"
            if i == len(pdf.pages) - 1: last_page_text = text if text else ""
        rincian_jkp = extract_rincian_jkp(pdf)

    # 1. KODE DAN NOMOR PJKEK
    kode_nomor = re.search(r'KODE DAN NOMOR PJKEK.*?(\d{3})\s*(?:(\d{2}))?\s*(\d{6})', full_text, re.DOTALL)
    kode_pjkek = kode_nomor.group(1) if kode_nomor else ""
    kode_tahun = kode_nomor.group(2) if kode_nomor and kode_nomor.group(2) else ""
    nomor_pjkek = kode_nomor.group(3) if kode_nomor else ""

    # 2. DETAIL (Kata setelah D. IDENTITAS)
    detail_match = re.search(r'D\.\s*IDENTITAS\s+([^\n\r:]+)', full_text)
    detail = detail_match.group(1).strip() if detail_match else ""

    # 3. ASAL JKP
    asal = re.search(r'B\.\s*ASAL JKP\s*:\s*([A-Z]+)', full_text)
    asal_jkp = asal.group(1) if asal else ""

    # 4. IDENTITAS PENERIMA (Section C) - REVISI: DITAMBAHKAN NPWP & ALAMAT
    penerima_section = re.search(r'C\..*?D\.', full_text, re.DOTALL)
    nama_penerima = npwp_penerima = alamat_penerima = nama_kpp_terdaftar = ""
    if penerima_section:
        p_text = penerima_section.group(0)
        
        n_match = re.search(r'NAMA\s*:\s*(.+)', p_text)
        if n_match: nama_penerima = n_match.group(1).strip()
        
        # Ekstraksi NPWP
        npwp_match = re.search(r'NPWP\s*:\s*([\d\.\-]+)', p_text)
        if npwp_match: npwp_penerima = npwp_match.group(1).strip()
        
        #
