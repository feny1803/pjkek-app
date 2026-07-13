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
        
        # Ekstraksi Alamat (Mengambil baris teks di antara ALAMAT dan KODE KPP)
        alamat_match = re.search(r'ALAMAT\s*:\s*(.+?)(?=KODE KPP|$)', p_text, re.DOTALL)
        if alamat_match: alamat_penerima = alamat_match.group(1).replace("\n", " ").strip()
        
        kpp_match = re.search(r'KODE KPP TERDAFTAR\s*:\s*\d+\s+(.*)', p_text)
        if kpp_match: nama_kpp_terdaftar = kpp_match.group(1).strip()

    # 5. IDENTITAS BKP/JKP (Section D)
    bkp_section = re.search(r'D\..*?E\.', full_text, re.DOTALL)
    nama_bkp = ""
    if bkp_section:
        nb_match = re.search(r'NAMA\s*:\s*(.+)', bkp_section.group(0))
        if nb_match: nama_bkp = nb_match.group(1).strip()

    # 6. TANGGAL DOKUMEN
    dates_last_page = re.findall(r'\b\d{2}-\d{2}-\d{4}\b', last_page_text)
    tanggal_dokumen = dates_last_page[-1] if dates_last_page else ""

    return {
        "nama_file": filename, "kode_pjkek": kode_pjkek, "kode_tahun": kode_tahun,
        "nomor_pjkek": nomor_pjkek, "detail": detail, "asal_jkp": asal_jkp,
        "nama_penerima": nama_penerima, "npwp_penerima": npwp_penerima, "alamat_penerima": alamat_penerima,
        "nama_kpp_terdaftar": nama_kpp_terdaftar, "nama_bkp": nama_bkp, 
        "rincian_jkp": rincian_jkp, "tanggal_dokumen": tanggal_dokumen
    }

# --- 4. PANEL NAVIGASI UTAMA (SIDEBAR) ---
with st.sidebar:
    try:
        st.image("logo_kek.png", width=180)
    except:
        st.write("🏢 **SISTEM MONITORING PJKEK**")
        
    st.markdown("### 🏢 SISTEM PJKEK")
    menu_pilihan = st.radio(
        "Pilih Menu Halaman:",
        ["1. Panduan & Tutorial", "2. Unggah Dokumen (Upload PDF)"]
    )
    st.markdown("---")
    st.caption("Aplikasi Otomatisasi Input Data\nAdministrator KEK Gresik")
    st.caption("© KEK gresik 2026")

# --- 5. MANAGEMENT HALAMAN TAMPILAN ---

# === HALAMAN 1: TUTORIAL PENGGUNAAN ===
if menu_pilihan == "1. Panduan & Tutorial":
    st.title("Welcome to Monitoring & Analisis PJKEK Dashboard")
    st.subheader("Sistem Penginputan Otomatis Dokumen PJKEK Administrator KEK Gresik")
    
    st.markdown("""
    Aplikasi ini dirancang khusus untuk memfasilitasi pegawai **Administrator KEK Gresik** dalam melakukan efisiensi kerja. Melalui sistem ini, Anda tidak perlu lagi melakukan **perekaman data secara manual (*data entry manual*)** dari ribuan berkas PDF PJKEK ke dalam Excel atau Spreadsheet.
    
    Sistem akan mendeteksi komponen teks serta tabel rincian penyerahan Jasa Kena Pajak (JKP) secara otomatis, kemudian menyimpannya ke dalam database **Google Sheets** terpusat. Akumulasi data yang tersimpan di dalam database tersebut selanjutnya akan diolah secara *real-time* menjadi **Dashboard Monitoring Visual Interaktif**.
    """)
    
    st.markdown("---")
    st.markdown("### 📑 PANDUAN PENGGUNAAN (SOP PEGAWAI)")
    
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info("### 📂 Langkah 1\n**Buka Menu Upload**\n\nPilih menu **'2. Unggah Dokumen (Upload PDF)'** pada panel navigasi di sebelah kiri layar Anda.")
    with col2:
        st.info("### 📥 Langkah 2\n**Pilih Berkas PDF**\n\nSiapkan dokumen PDF PJKEK asli. Seret dan jatuhkan (*drag & drop*) berkas tersebut ke kotak pengunggahan yang tersedia. Anda dapat memproses banyak dokumen sekaligus.")
    with col3:
        st.info("### 🚀 Langkah 3\n**Simpan ke Database**\n\nKlik tombol **'Mulai Ekstraksi & Simpan'**. Tunggu hingga bilah kemajuan selesai memproses data dan memasukkannya ke spreadsheet terpusat.")

# === HALAMAN 2: PORTAL UPLOAD & PROSES DATA ===
elif menu_pilihan == "2. Unggah Dokumen (Upload PDF)":
    st.title("📄 Portal Unggah Dokumen PJKEK")
    st.subheader("Ekstraksi Data Otomatis ke Database Spreadsheet")
    st.write("Silakan unggah dokumen PDF PJKEK pada area di bawah ini untuk memulai perekaman data otomatis.")
    
    if worksheet is None:
        st.error("❌ Hubungan ke Database Google Sheets Terputus Lokal (Akan berfungsi normal setelah di-upload ke Streamlit Cloud dengan Secrets).")
    else:
        st.success("✅ Terkoneksi Aman: Database Google Sheets Siap Menerima Data baru")
    
    # Menyiapkan wadah form utama agar bisa di-reset dengan sempurna
    wadah_uploader = st.empty()
    
    uploaded_files = wadah_uploader.file_uploader(
        "Silakan seret berkas atau pilih berkas PDF PJKEK Anda di sini:", 
        type=["pdf"], 
        accept_multiple_files=True,
        key="pjkek_file_uploader"
    )

    if uploaded_files:
        st.info(f"📋 Terdeteksi: {len(uploaded_files)} dokumen siap diproses.")
        
        if st.button("🚀 Mulai Ekstraksi & Simpan"):
            if worksheet is None:
                st.error("Tidak dapat menyimpan data. Kunci Google Sheets API tidak ditemukan di komputer lokal.")
            else:
                new_data_rows = []
                skipped_files = 0
                
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for index, uploaded_file in enumerate(uploaded_files):
                    filename = uploaded_file.name
                    file_content = uploaded_file.read()
                    
                    clean_filename = re.sub(r'\s\(\d+\)\.pdf$', '.pdf', filename)

                    if clean_filename in existing_filenames:
                        st.warning(f"⚠️ Berkas Dilewati: '{clean_filename}' sudah terekam di database.")
                        skipped_files += 1
                        continue

                    status_text.text(f"⏳ Sedang memproses dokumen ({index+1}/{len(uploaded_files)}): {clean_filename}...")
                    
                    try:
                        data = extract_pjkek_data(file_content, clean_filename)
                        rincian = data.pop("rincian_jkp", [])
                        
                        # Menyusun kolom baris data baru beserta NPWP dan Alamat
                        if rincian:
                            for r in rincian:
                                new_data_rows.append([
                                    data["nama_file"], data["kode_pjkek"], data["kode_tahun"], data["nomor_pjkek"],
                                    data["detail"], data["asal_jkp"], data["nama_penerima"], data["npwp_penerima"],
                                    data["alamat_penerima"], data["nama_kpp_terdaftar"], data["nama_bkp"], 
                                    r["no"], r["jenis"], r["deskripsi"], r["total_per_item"], data["tanggal_dokumen"]
                                ])
                        else:
                            new_data_rows.append([
                                data["nama_file"], data["kode_pjkek"], data["kode_tahun"], data["nomor_pjkek"],
                                data["detail"], data["asal_jkp"], data["nama_penerima"], data["npwp_penerima"],
                                data["alamat_penerima"], data["nama_kpp_terdaftar"], data["nama_bkp"], 
                                "-", "-", "-", "0", data["tanggal_dokumen"]
                            ])
                    except Exception as e:
                        st.error(f"❌ Terjadi kesalahan pembacaan pada dokumen {clean_filename}: {e}")
                    
                    progress_bar.progress((index + 1) / len(uploaded_files))
                    
                status_text.text("Melakukan sinkronisasi data ke basis data terpusat...")
                
                total_uploaded = len(uploaded_files)
                total_added = total_uploaded - skipped_files
                total_rows = len(new_data_rows)

                if new_data_rows:
                    with st.spinner("Mengunggah data ke Google Sheets..."):
                        worksheet.append_rows(new_data_rows)
                    st.success(f"🎉 SINKRONISASI BERHASIL! {total_added} dokumen baru telah ditambahkan (Total {total_rows} baris transaksi baru berhasil terekam).")
                else:
                    st.info("ℹ️ Sinkronisasi selesai. Tidak ada data baru yang dimasukkan.") 
                
                # --- BERIKUT ADALAH TOMBOL UNTUK RESET / TAMBAH UNGGAHAN LAGI ---
                st.markdown("---")
                if st.button("🔄 Tambah Unggahan Baru Lagi"):
                    st.session_state["pjkek_file_uploader"] = [] # Bersihkan berkas lama secara paksa
                    st.rerun()
