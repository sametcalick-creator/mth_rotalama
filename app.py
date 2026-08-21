"""
MTH Personelleri - Günlük İş Planlama Dashboard
"""

import streamlit as st
import pandas as pd
import numpy as np
import folium
from folium import plugins
from streamlit_folium import st_folium
from shapely.geometry import Point, shape
from io import BytesIO
from datetime import datetime, timedelta
import datetime as dt_module
import math
import json
import base64
import os
import glob
import re
import unicodedata
import plotly.express as px
import plotly.graph_objects as go
from functools import lru_cache
import colorsys
import random
from pdf_bulten import generate_pdf_bulletin, get_kpi_unit_and_format
from sonuc_analiz import (
    fen_isleri_excel_oku, kontak_excel_oku, isim_listesi_oku,
    build_sutun_haritasi, prepare_sonuc_data, compute_sonuc_rapor,
    saniye_formatla, saniye_to_saat, format_tr_number, safe_numeric_mean, safe_numeric_sum,
    kvkk_sutun_kontrol, export_sonuc_excel
)

# ============================================================
# SAYFA AYARLARI
# ============================================================

st.set_page_config(
    page_title="Ekip İş Planlama Dashboard",
    page_icon="🗺️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============================================================
# EKİP RENKLERİ (havuz - en fazla 20 ekip desteklenir)
# ============================================================
EKIP_RENK_HAVUZU = [
    ("Ekip1", "#e74c3c"),   ("Ekip2", "#3498db"),   ("Ekip3", "#2ecc71"),
    ("Ekip4", "#f39c12"),   ("Ekip5", "#9b59b6"),   ("Ekip6", "#1abc9c"),
    ("Ekip7", "#e67e22"),   ("Ekip8", "#e84393"),   ("Ekip9", "#00cec9"),
    ("Ekip10", "#6c5ce7"),  ("Ekip11", "#fd79a8"),  ("Ekip12", "#a29bfe"),
    ("Ekip13", "#ffeaa7"),  ("Ekip14", "#55efc4"),  ("Ekip15", "#74b9ff"),
    ("Ekip16", "#dfe6e9"),  ("Ekip17", "#b2bec3"),  ("Ekip18", "#636e72"),
    ("Ekip19", "#d63031"),  ("Ekip20", "#0984e3"),
]
ATANMAMIS_RENK = "#95a5a6"  # Gri

def aktif_ekipler(sayi):
    """Kullanıcının seçtiği ekip sayısına göre ekip adı-renk dict'i döner."""
    return dict(EKIP_RENK_HAVUZU[:sayi])


# ============================================================
# YARDIMCI FONKSİYONLAR
# ============================================================

def clean_text_for_json(val):
    if val is None or pd.isna(val):
        return ""
    s = str(val)
    try:
        s = unicodedata.normalize("NFC", s)
    except Exception:
        pass
    try:
        s = s.encode("utf-8", "ignore").decode("utf-8", "ignore")
    except Exception:
        pass
    s = s.replace("\r\n", " ").replace("\n", " ").replace("\r", " ").replace("\t", " ")
    s = s.replace("\\", "/")
    s = s.replace('"', "'")
    clean_chars = []
    for ch in s:
        code = ord(ch)
        if 0xD800 <= code <= 0xDFFF:
            continue
        if code < 32 or (127 <= code <= 159):
            continue
        clean_chars.append(ch)
    return "".join(clean_chars).strip()


def sanitize_plotly_dict(obj):
    if isinstance(obj, dict):
        return {k: sanitize_plotly_dict(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [sanitize_plotly_dict(v) for v in obj]
    elif isinstance(obj, str):
        return clean_text_for_json(obj)
    else:
        return obj

def koordinat_temizle(val):
    """Koordinat değerindeki virgülleri noktaya çevirir ve float'a dönüştürür."""
    if pd.isna(val):
        return np.nan
    if isinstance(val, (int, float)):
        return float(val)
    try:
        return float(str(val).strip().replace(",", "."))
    except (ValueError, TypeError):
        return np.nan


def koordinatlari_dogrula(df):

    istatistik = {"toplam_once": len(df), "takas": 0, "gecersiz": 0}

    # Türkiye koordinat sınırları
    ENLEM_MIN, ENLEM_MAX = 35.5, 42.5   # Kuzey-Güney
    BOYLAM_MIN, BOYLAM_MAX = 25.5, 45.0  # Doğu-Batı

    
    takas_mask = (df["Enlem"] >= BOYLAM_MIN) & (df["Enlem"] <= BOYLAM_MAX) & \
                 (df["Boylam"] >= ENLEM_MIN) & (df["Boylam"] <= ENLEM_MAX)
                 
    istatistik["takas"] = takas_mask.sum()
    if istatistik["takas"] > 0:
        df.loc[takas_mask, ["Enlem", "Boylam"]] = df.loc[takas_mask, ["Boylam", "Enlem"]].values

    
    gecerli_mask = (
        (df["Enlem"] >= ENLEM_MIN) & (df["Enlem"] <= ENLEM_MAX) &
        (df["Boylam"] >= BOYLAM_MIN) & (df["Boylam"] <= BOYLAM_MAX)
    )
    istatistik["gecersiz"] = (~gecerli_mask).sum()
    df = df[gecerli_mask].reset_index(drop=True)

    istatistik["toplam_sonra"] = len(df)
    return df, istatistik


def jitter_uygula(df):
    
    JITTER_YARICAP = 0.00012  # ~13 metre (derece cinsinden)

  
    df["Enlem_Gosterim"] = df["Enlem"].copy()
    df["Boylam_Gosterim"] = df["Boylam"].copy()

   
    grup_sayilari = df.groupby(["Enlem", "Boylam"])["Enlem"].transform("size")
    mask = grup_sayilari > 1

    if mask.any():
        sira = df[mask].groupby(["Enlem", "Boylam"]).cumcount()
        grup_buyuklugu = grup_sayilari[mask]
        acilar = (2 * np.pi * sira) / grup_buyuklugu
        
        df.loc[mask, "Enlem_Gosterim"] += JITTER_YARICAP * np.sin(acilar)
        df.loc[mask, "Boylam_Gosterim"] += JITTER_YARICAP * np.cos(acilar)

    return df


def haversine_mesafe(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1_r, lon1_r = np.radians(lat1), np.radians(lon1)
    lat2_r, lon2_r = np.radians(lat2), np.radians(lon2)
    dlat = lat2_r - lat1_r
    dlon = lon2_r - lon1_r
    a = np.sin(dlat / 2) ** 2 + np.cos(lat1_r) * np.cos(lat2_r) * np.sin(dlon / 2) ** 2
    c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1 - a))
    return R * c


def excel_oku(uploaded_file):
    try:
        df = pd.read_excel(uploaded_file, engine="openpyxl")
    except Exception as e:
        return None, None, f"❌ **Excel dosyası okunamadı!**\n\nDosya bozuk olabilir veya formatı (xlsx/xls) desteklenmiyor olabilir.\nHata detayı: `{str(e)}`"

    if df.empty:
        return None, None, None, "⚠️ **Yüklenen Excel dosyası boş!**\n\nLütfen içinde veri olan bir dosya yükleyin."

    # --- KVKK SÜTUN KONTROLÜ ---
    kvkk_err = kvkk_sutun_kontrol(df.columns)
    if kvkk_err:
        return None, None, None, f"❌ **{kvkk_err}**"

  
    sutun_haritasi = {}
    bulunan_sutunlar = df.columns.tolist()

    for col in bulunan_sutunlar:
        col_str = str(col).strip()
        cl = col_str.lower().replace(" ", "_").replace("ı", "i").replace("ş", "s").replace("ç", "c").replace("ö", "o").replace("ü", "u")
        
        
        if cl in ["hizmet_noktasi_no", "hizmet_noktasi", "tesisat_no", "tesisat_numarasi", "hizmet_no"]:
            sutun_haritasi["Hizmet_Noktasi_No"] = col
        
        
        elif cl in ["enlem/boylam", "enlem_boylam", "enlem/boylem"]:
            sutun_haritasi["Enlem_Boylam"] = col
        elif cl == "enlem":
            sutun_haritasi["Enlem"] = col
        elif cl == "boylam":
            sutun_haritasi["Boylam"] = col

   
    if "Hizmet_Noktasi_No" not in sutun_haritasi:
        for col in bulunan_sutunlar:
            cl = str(col).lower().replace(" ", "_").replace("ı", "i").replace("ş", "s")
            # "hizmet" ve "no" geçsin ama "anlasma" geçmesin
            if "hizmet" in cl and "no" in cl and "anlasma" not in cl:
                sutun_haritasi["Hizmet_Noktasi_No"] = col
                break

    
    if "Enlem_Boylam" not in sutun_haritasi and ("Enlem" not in sutun_haritasi or "Boylam" not in sutun_haritasi):
        for col in bulunan_sutunlar:
            cl = str(col).strip().lower()
            if "enlem" in cl and "boylam" in cl:
                sutun_haritasi["Enlem_Boylam"] = col
                break

   
    for col in bulunan_sutunlar:
        cl_str = str(col).strip()
        cl = cl_str.lower().replace("ı", "i").replace("ş", "s").replace("ç", "c").replace("ö", "o").replace("ü", "u")
        

        if "bolge" in cl or "region" in cl or ("lge" in cl and len(cl) < 10):
            if "Bolge" not in sutun_haritasi: sutun_haritasi["Bolge"] = col
        
       
        if (cl == "il" or cl == "i̇l" or cl == "sehir" or cl == "city" or " il" in " " + cl) and "ilce" not in cl and "ilçe" not in cl:
            if "Il" not in sutun_haritasi: sutun_haritasi["Il"] = col
            
    
    if "Ilce" not in sutun_haritasi:
        for col in bulunan_sutunlar:
            cl = str(col).strip().lower()
            if "ilce" in cl or "ilçe" in cl or "district" in cl or "lce" in cl:
                sutun_haritasi["Ilce"] = col
                break

    if "Bolge" not in sutun_haritasi and len(bulunan_sutunlar) > 0:
        sutun_haritasi["Bolge"] = bulunan_sutunlar[0]
    if "Il" not in sutun_haritasi and len(bulunan_sutunlar) > 1:
        sutun_haritasi["Il"] = bulunan_sutunlar[1]
    if "Ilce" not in sutun_haritasi and len(bulunan_sutunlar) > 2:
        sutun_haritasi["Ilce"] = bulunan_sutunlar[2]

    eksik = []
    if "Hizmet_Noktasi_No" not in sutun_haritasi: eksik.append("Hizmet Noktası No (veya Tesisat No)")
    if "Enlem_Boylam" not in sutun_haritasi and ("Enlem" not in sutun_haritasi or "Boylam" not in sutun_haritasi): 
        eksik.append("Enlem/Boylam (veya ayrı Enlem ve Boylam)")

    if eksik:
        hata_mesaji = "### ❌ Eksik Sütun Hatası\n\nExcel dosyanızda aşağıdaki zorunlu sütunlar bulunamadı:\n\n"
        for e in eksik:
            hata_mesaji += f"- **{e}**\n"
        hata_mesaji += f"\n\n**Sizin Excel'deki Sütunlar:** `{', '.join([str(c) for c in bulunan_sutunlar])}`"
        hata_mesaji += "\n\n💡 *Lütfen Excel'deki başlıkları yukarıdaki isimlerle uyumlu olacak şekilde düzeltip tekrar yükleyin.*"
        return None, None, None, hata_mesaji

    try:
        sonuc = pd.DataFrame()
        sonuc["Tesisat_No"] = df[sutun_haritasi["Hizmet_Noktasi_No"]].apply(
            lambda x: str(int(x)) if pd.notna(x) and isinstance(x, (float, int)) else str(x)
        )

        if "Enlem_Boylam" in sutun_haritasi:
            eb_str = df[sutun_haritasi["Enlem_Boylam"]].astype(str).str.strip()
            parcalar = eb_str.str.split("/", expand=True)
            if len(parcalar.columns) >= 2:
                sonuc["Enlem"] = pd.to_numeric(parcalar[0].str.strip().str.replace(",", "."), errors='coerce')
                sonuc["Boylam"] = pd.to_numeric(parcalar[1].str.strip().str.replace(",", "."), errors='coerce')
            else:
                sonuc["Enlem"] = np.nan
                sonuc["Boylam"] = np.nan
        else:
            sonuc["Enlem"] = pd.to_numeric(df[sutun_haritasi["Enlem"]].astype(str).str.replace(",", "."), errors='coerce')
            sonuc["Boylam"] = pd.to_numeric(df[sutun_haritasi["Boylam"]].astype(str).str.replace(",", "."), errors='coerce')

        enlem_valid = sonuc["Enlem"].dropna()
        if not enlem_valid.empty and enlem_valid.median() > 100:
            sonuc["Enlem"] = sonuc["Enlem"] / 1e8
        boylam_valid = sonuc["Boylam"].dropna()
        if not boylam_valid.empty and boylam_valid.median() > 100:
            sonuc["Boylam"] = sonuc["Boylam"] / 1e8

        sonuc["Bolge"] = df[sutun_haritasi.get("Bolge", "")].astype(str) if "Bolge" in sutun_haritasi else ""
        sonuc["Il"] = df[sutun_haritasi.get("Il", "")].astype(str) if "Il" in sutun_haritasi else ""
        sonuc["Ilce"] = df[sutun_haritasi.get("Ilce", "")].astype(str) if "Ilce" in sutun_haritasi else ""
        sonuc["Ekip"] = "Atanmamış"

        opsiyonel_eslestirme = {
            "Sayac_Seri_No": ["sayac_seri_no", "sayac seri no", "sayaç seri"],
            "Adres": ["adres", "address", "gizli_adres", "gizli_ad_soyad"],
            "Sayac_Tip_Adi": ["sayac_tipi", "sayac tipi", "sayaç tipi", "sayac_tip_adi", "sayac_tipi_adi"],
            "AG_OG": ["ag/og", "ag_og", "agog", "ag_og_adi"],
            "Saha_Aktivitesi_Yonergeleri": ["saha_aktivitesi_yonergeleri", "saha aktivitesi yonergeleri", "yonerge"],
            "Rezerv_Kwh": ["rezerv_kwh", "rezerv kwh"],
            "Ihbar_Sekli_2": ["ihbar_sekli_2", "ihbar sekli 2", "ihbar", "ihbar_sekli_adi"],
            "Tahakkuk_Carpani": ["tahakkuk_carpani", "tahakkuk carpani", "carpan"],
            "Hizmet_Nok_Tip_Kodu": ["hizmet_nok_tip_kodu", "hizmet nok tip kodu", "hizmet_anl_tip_adi", "hizmet_nok_tip_adi"],
            "Aktivite_Olusturulma_Tarihi": ["aktivite_olusturulma_tarihi", "aktivite olusturulma tarihi", "is_olusturma_tarihi", "iş oluşturma tarihi", "aktivite_oluşturulma_tarihi", "aktivite_olusturma_tarihi"],
            "Aktivite_Olusturan_Birim": ["aktivite_olusturan_birim", "aktivite oluşturan birim", "is_olusturan_birim", "iş oluşturan birim", "birim"],
            "Saha_Aktivite_Ozet": ["saha_aktivite_ozet"],
            "Kofra_No": ["kofra_no"],
            "Kurulu_Guc": ["kurulu_guc", "kurulu güç", "kuruluguc", "kurulu guc"],
        }
        for hedef_ad, aranacaklar in opsiyonel_eslestirme.items():
            for col in bulunan_sutunlar:
                cl_norm = str(col).lower().replace(" ", "_").replace("ı", "i").replace("ş", "s").replace("ç", "c").replace("ü", "u").replace("ö", "o").replace("İ", "i").replace("\u0307", "")
                if cl_norm in [a.replace(" ", "_") for a in aranacaklar]:
                    if hedef_ad in ["Sayac_Seri_No", "Tahakkuk_Carpani"]:
                        sonuc[hedef_ad] = df[col].astype(str).str.strip().str.replace(r'\.0$', '', regex=True).replace('nan', '')
                    elif hedef_ad == "Aktivite_Olusturulma_Tarihi":
                        sonuc[hedef_ad] = pd.to_datetime(df[col], errors='coerce').dt.date
                    elif hedef_ad in ["Kofra_No", "Kurulu_Guc"]:
                        sonuc[hedef_ad] = pd.to_numeric(df[col], errors='coerce')
                    else:
                        sonuc[hedef_ad] = df[col].astype(str).replace("nan", "")
                    break
            if hedef_ad not in sonuc.columns:
                if hedef_ad == "Aktivite_Olusturulma_Tarihi":
                    sonuc[hedef_ad] = pd.NaT
                elif hedef_ad in ["Kofra_No", "Kurulu_Guc"]:
                    sonuc[hedef_ad] = np.nan
                else:
                    sonuc[hedef_ad] = ""

        tarife_map = {
            "E-AYD": "Aydınlatma",
            "E-DTR": "Trafo",
            "E-MES": "Mesken",
            "E-SAN": "Sanayi",
            "E-TAR": "Tarımsal",
            "E-TIC": "Ticarethane"
        }
        if "Hizmet_Nok_Tip_Kodu" in sonuc.columns:
            sonuc["Tarife"] = sonuc["Hizmet_Nok_Tip_Kodu"].map(tarife_map).fillna(sonuc["Hizmet_Nok_Tip_Kodu"])
        else:
            sonuc["Tarife"] = ""

        for col in ["AG_OG", "Tarife", "Ihbar_Sekli_2", "Saha_Aktivitesi_Yonergeleri"]:
            if col in sonuc.columns:
                sonuc[col] = sonuc[col].replace(["", "nan", "NaN", "None", None, np.nan], "Boş")
                sonuc[col] = sonuc[col].fillna("Boş")

        koordinatsiz_mask = sonuc["Enlem"].isna() | sonuc["Boylam"].isna() | (sonuc["Enlem"] == 0) | (sonuc["Boylam"] == 0)
        koordinatsiz_df = sonuc[koordinatsiz_mask].copy()
        
        sonuc = sonuc[~koordinatsiz_mask].reset_index(drop=True)
        koordinatsiz_df = koordinatsiz_df.reset_index(drop=True)
        
        if len(sonuc) == 0:
            return None, None, None, "❌ **Geçerli Koordinat Yok!**\n\nExcel'deki tüm Enlem/Boylam değerleri boş veya geçersiz (0) görünüyor."

        sonuc, istatistik = koordinatlari_dogrula(sonuc)

        sonuc = jitter_uygula(sonuc)

        return sonuc, istatistik, koordinatsiz_df, None

    except Exception as e:
        return None, None, None, f"❌ **Veri işleme hatası!**\n\nSütunlar bulundu ancak veriler işlenirken bir sorun çıktı.\nHata: `{str(e)}`"


# ============================================================
# İŞLEM SÜRELERİ ve İŞLETME KOORDİNATLARI
# ============================================================

@st.cache_data
def islem_sureleri_oku():
    """İşlem Süreleri ve İşletme Koordinatları Excel dosyasını otomatik okur.
    Returns: (is_sureleri, km_sureleri, isletme_koordinatlari) veya (None, None, None)
    """
    uygulama_dizini = os.path.dirname(os.path.abspath(__file__))
    
    # Dosyayı bul
    dosya_yolu = None
    for pattern in ["*İşlem*Süreleri*.xlsx", "*islem*sureleri*.xlsx", "*Islem*Sureleri*.xlsx"]:
        bulunanlar = glob.glob(os.path.join(uygulama_dizini, pattern))
        if bulunanlar:
            dosya_yolu = bulunanlar[0]
            break
    
    if dosya_yolu is None:
        koor_files = glob.glob(os.path.join(uygulama_dizini, "*İşletme*Koordinat*.xlsx")) + glob.glob(os.path.join(uygulama_dizini, "*isletme*koordinat*.xlsx"))
        if not koor_files:
            return None, None, None
        dosya_yolu = koor_files[0]
    
    try:
        xl = pd.ExcelFile(dosya_yolu, engine="openpyxl")
        df = xl.parse(xl.sheet_names[0])
    except Exception:
        return None, None, None
    
    # --- 1. İŞ SÜRELERİ ---
    is_sureleri = {}
    if len(df.columns) >= 3:
        is_kalemi_col = df.columns[0]    # İŞ KALEMİ
        ilk_is_col = df.columns[1]       # Kofradaki İlk İş İçin Harcanan Süre
        diger_col = df.columns[2]        # Kofradaki Diğer İşler İçin Harcanan Süre
        
        for _, row in df.iterrows():
            kalemi = row[is_kalemi_col]
            if pd.notna(kalemi) and str(kalemi).strip():
                ilk_v = row[ilk_is_col]
                diger_v = row[diger_col]
                try:
                    ilk_sure = float(ilk_v) if pd.notna(ilk_v) else 5.0
                    diger_sure = float(diger_v) if pd.notna(diger_v) else 1.0
                    is_sureleri[str(kalemi).strip()] = {"ilk_is": ilk_sure, "diger": diger_sure}
                except (ValueError, TypeError):
                    continue
    
    # --- 2. BÖLGE KM SÜRELERİ ---
    km_sureleri = {}
    bolge_col_idx = 6   # Farklı Kofralar Arasında KM Başına Eklenecek Yol Süresi (Dakika)
    
    for _, row in df.iterrows():
        bval = row.iloc[bolge_col_idx] if len(row) > bolge_col_idx else None
        if pd.notna(bval) and str(bval).strip():
            bstr = str(bval).strip()
            # Başlık satırını ve not satırını atla
            if bstr.lower() in ["bölge", "bolge"] or bstr.startswith("Not:"):
                continue
            km_0_5 = row.iloc[7] if len(row) > 7 and pd.notna(row.iloc[7]) else 2.5
            km_5_20 = row.iloc[8] if len(row) > 8 and pd.notna(row.iloc[8]) else 2.0
            km_20_ustu = row.iloc[9] if len(row) > 9 and pd.notna(row.iloc[9]) else 1.0
            try:
                km_sureleri[bstr] = {
                    "km_0_5": float(km_0_5),
                    "km_5_20": float(km_5_20),
                    "km_20_ustu": float(km_20_ustu)
                }
            except (ValueError, TypeError):
                continue
    
    def parse_isletme_koordinatlari_from_df(target_df):
        coords = {}
        header_row_idx = None
        ilce_col, bolge_col, enlem_col, boylam_col = None, None, None, None
        
        for r_idx in range(min(5, len(target_df))):
            row_vals = [str(x).strip().upper() if pd.notna(x) else "" for x in target_df.iloc[r_idx].values]
            for c_idx, val in enumerate(row_vals):
                if ("ILCE" in val or "İLÇE" in val) and ilce_col is None:
                    ilce_col = c_idx
                elif ("BOLGE" in val or "BÖLGE" in val) and bolge_col is None:
                    bolge_col = c_idx
                elif "ENLEM" in val and enlem_col is None:
                    enlem_col = c_idx
                elif "BOYLAM" in val and boylam_col is None:
                    boylam_col = c_idx
            if ilce_col is not None and enlem_col is not None and boylam_col is not None:
                header_row_idx = r_idx
                break
        
        if header_row_idx is None:
            ilce_col = 12 if len(target_df.columns) > 12 else (1 if len(target_df.columns) > 1 else None)
            bolge_col = 13 if len(target_df.columns) > 13 else (2 if len(target_df.columns) > 2 else None)
            enlem_col = 14 if len(target_df.columns) > 14 else (3 if len(target_df.columns) > 3 else None)
            boylam_col = 15 if len(target_df.columns) > 15 else (4 if len(target_df.columns) > 4 else None)
            start_r = 0
        else:
            start_r = header_row_idx + 1

        for r_idx in range(start_r, len(target_df)):
            row = target_df.iloc[r_idx]
            ilce_val = row.iloc[ilce_col] if ilce_col is not None and len(row) > ilce_col else None
            bolge_val = row.iloc[bolge_col] if bolge_col is not None and len(row) > bolge_col else ""
            enlem_val = row.iloc[enlem_col] if enlem_col is not None and len(row) > enlem_col else None
            boylam_val = row.iloc[boylam_col] if boylam_col is not None and len(row) > boylam_col else None
            
            if (pd.notna(ilce_val) and str(ilce_val).strip() not in ["", "nan", "İLÇE", "ILCE"]
                and pd.notna(enlem_val) and pd.notna(boylam_val)):
                try:
                    enlem_f = float(enlem_val)
                    boylam_f = float(boylam_val)
                    if enlem_f > 0 and boylam_f > 0:
                        key = (str(ilce_val).strip().upper(), str(bolge_val).strip() if pd.notna(bolge_val) else "")
                        if key not in coords:
                            coords[key] = {"enlem": enlem_f, "boylam": boylam_f}
                except (ValueError, TypeError):
                    continue
        return coords

    isletme_koordinatlari = {}
    koor_files = glob.glob(os.path.join(uygulama_dizini, "*İşletme*Koordinat*.xlsx")) + glob.glob(os.path.join(uygulama_dizini, "*isletme*koordinat*.xlsx"))
    for kf in koor_files:
        try:
            xl_k = pd.ExcelFile(kf, engine="openpyxl")
            df_k = xl_k.parse(xl_k.sheet_names[0])
            coords_k = parse_isletme_koordinatlari_from_df(df_k)
            if coords_k:
                isletme_koordinatlari.update(coords_k)
                break
        except Exception:
            continue

    if not isletme_koordinatlari and df is not None:
        isletme_koordinatlari = parse_isletme_koordinatlari_from_df(df)

    return is_sureleri, km_sureleri, isletme_koordinatlari


def isletme_koordinat_bul(ilce, bolge, isletme_koordinatlari):
    """İlçe ve Bölge bazlı işletme merkez koordinatlarını bulur."""
    if isletme_koordinatlari is None:
        return None
    
    ilce_upper = str(ilce).strip().upper()
    bolge_str = str(bolge).strip()
    
    key = (ilce_upper, bolge_str)
    if key in isletme_koordinatlari:
        return isletme_koordinatlari[key]
    
    for (k_ilce, k_bolge), coords in isletme_koordinatlari.items():
        if k_ilce == ilce_upper:
            return coords
    
    for (k_ilce, k_bolge), coords in isletme_koordinatlari.items():
        if k_bolge == bolge_str and k_ilce in ["MERKEZ", "METROPOL"]:
            return coords
    
    for (k_ilce, k_bolge), coords in isletme_koordinatlari.items():
        if k_bolge == bolge_str:
            return coords
    
    return None


def rota_sirala(df_isler, baslangic_enlem, baslangic_boylam):
    """Nearest Neighbor algoritması ile işleri en yakından uzağa sıralar.
    Başlangıç noktasından (işletme merkezi) başlar, her adımda en yakın atanmamış işe gider.
    Returns: sıralı index listesi
    """
    if df_isler.empty:
        return []
    
    kalan = set(df_isler.index.tolist())
    sirali_indexler = []
    mevcut_lat = baslangic_enlem
    mevcut_lon = baslangic_boylam
    
    while kalan:
        kalan_list = list(kalan)
        mesafeler = haversine_mesafe(
            mevcut_lat, mevcut_lon,
            df_isler.loc[kalan_list, "Enlem"].values,
            df_isler.loc[kalan_list, "Boylam"].values
        )
        en_yakin_pos = np.argmin(mesafeler)
        en_yakin_idx = kalan_list[en_yakin_pos]
        
        sirali_indexler.append(en_yakin_idx)
        mevcut_lat = df_isler.loc[en_yakin_idx, "Enlem"]
        mevcut_lon = df_isler.loc[en_yakin_idx, "Boylam"]
        kalan.remove(en_yakin_idx)
    
    return sirali_indexler


def yol_suresi_hesapla(mesafe_km, bolge_km):
    """İki nokta arasındaki mesafeye göre yol süresini dakika cinsinden hesaplar."""
    if mesafe_km >= 100 or np.isnan(mesafe_km):
        return 15.0  # Sabit 15 dakika
    elif mesafe_km <= 5:
        return mesafe_km * bolge_km.get("km_0_5", 2.5)
    elif mesafe_km <= 20:
        return mesafe_km * bolge_km.get("km_5_20", 2.0)
    else:
        return mesafe_km * bolge_km.get("km_20_ustu", 1.0)


def sure_ve_saat_hesapla(df_sirali, sirali_indexler, baslangic_enlem, baslangic_boylam,
                          bolge, is_sureleri, km_sureleri):
    """Sıralı işler için yol süresi, işlem süresi ve varış saatini hesaplar.
    Returns: dict listeleri {sira, yol_suresi, islem_suresi, varis_saati, toplam_sure}
    """
    bolge_km = km_sureleri.get(str(bolge).strip(), {"km_0_5": 2.5, "km_5_20": 2.0, "km_20_ustu": 1.0})
    
    sonuclar = []
    baslangic_saat = datetime(2026, 1, 1, 8, 15, 0)  # 08:15
    kumulatif_dakika = 0.0
    
    onceki_lat = baslangic_enlem
    onceki_lon = baslangic_boylam
    onceki_kofra = None
    
    mola_kullanildi = False
    
    for sira_no, idx in enumerate(sirali_indexler, 1):
        row = df_sirali.loc[idx]
        if isinstance(row, pd.DataFrame):
            row = row.iloc[0]
        
        # Yol süresi
        lat_curr = float(row["Enlem"])
        lon_curr = float(row["Boylam"])
        mesafe = haversine_mesafe(onceki_lat, onceki_lon, lat_curr, lon_curr)
        if isinstance(mesafe, np.ndarray):
            mesafe = float(mesafe[0])
        else:
            mesafe = float(mesafe)
        yol_dk = yol_suresi_hesapla(mesafe, bolge_km) * 1.35
        
        kumulatif_dakika += yol_dk
        varis_dt = baslangic_saat + timedelta(minutes=kumulatif_dakika)
        
        # Öğle Molası Kontrolü (12:00 sonrasına denk gelirse 90 dk ekle)
        if not mola_kullanildi and varis_dt.time() >= datetime.strptime("12:00", "%H:%M").time():
            mola_saati = varis_dt.strftime("%H:%M")
            kumulatif_dakika += 90.0
            mola_kullanildi = True
            varis_dt = baslangic_saat + timedelta(minutes=kumulatif_dakika)
            sonuclar.append({
                "idx": "MOLA",
                "sira": sira_no - 0.5,
                "yol_suresi": 0.0,
                "islem_suresi": 90.0,
                "varis_saati": mola_saati,
                "mesafe_km": 0.0,
                "is_mola": True
            })
            
        varis_str = varis_dt.strftime("%H:%M")
        
        # İşlem süresi
        aktivite = str(row.get("Saha_Aktivite_Ozet", "")).strip() if pd.notna(row.get("Saha_Aktivite_Ozet", "")) else ""
        kofra = row.get("Kofra_No", np.nan)
        
        sureler = is_sureleri.get(aktivite, {"ilk_is": 5.0, "diger": 1.0}) if is_sureleri else {"ilk_is": 5.0, "diger": 1.0}
        
        # Kofra mantığı: önceki işle aynı kofra ise "diğer", farklı ise "ilk iş"
        kofra_gecerli = pd.notna(kofra) and kofra != 0 and str(kofra).strip() not in ["", "0", "0.0"]
        onceki_gecerli = pd.notna(onceki_kofra) and onceki_kofra != 0 and str(onceki_kofra).strip() not in ["", "0", "0.0"]
        
        if (onceki_gecerli and kofra_gecerli 
            and str(int(float(kofra))) == str(int(float(onceki_kofra)))):
            islem_dk = sureler["diger"]
        else:
            islem_dk = sureler["ilk_is"]
        
        kumulatif_dakika += islem_dk
        
        sonuclar.append({
            "idx": idx,
            "sira": sira_no,
            "yol_suresi": round(yol_dk, 1),
            "islem_suresi": round(islem_dk, 1),
            "varis_saati": varis_str,
            "mesafe_km": round(mesafe, 2),
        })
        
        onceki_lat = row["Enlem"]
        onceki_lon = row["Boylam"]
        onceki_kofra = kofra
    
    return sonuclar, round(kumulatif_dakika, 1)


def doluluk_orani_hesapla(toplam_sure_dakika):
    """Doluluk oranını hesaplar. %100 = 480 dakika (8 saat)."""
    return round((toplam_sure_dakika / 480.0) * 100, 1) if toplam_sure_dakika > 0 else 0.0


def ekip_rotalama_hesapla(df, ekip_adi, is_sureleri, km_sureleri, isletme_koordinatlari):
    """Bir ekip için rotalama, süre hesabı ve doluluk oranı hesaplar.
    Returns: (sirali_indexler, sonuclar_list, toplam_sure, doluluk, baslangic_koor) veya None
    """
    ekip_df = df[df["Ekip"] == ekip_adi].copy()
    if ekip_df.empty:
        return None
    
    # Bölge ve İlçe belirle (en sık geçen)
    bolge = ekip_df["Bolge"].mode().iloc[0] if not ekip_df["Bolge"].mode().empty else ""
    ilce = ekip_df["Ilce"].mode().iloc[0] if not ekip_df["Ilce"].mode().empty else ""
    
    # İşletme koordinatlarını bul
    isletme = isletme_koordinat_bul(ilce, bolge, isletme_koordinatlari)
    if isletme is None:
        # Fallback: ekipteki ilk işin koordinatını kullan
        isletme = {"enlem": ekip_df.iloc[0]["Enlem"], "boylam": ekip_df.iloc[0]["Boylam"]}
    
    # Rotalama
    sirali_indexler = rota_sirala(ekip_df, isletme["enlem"], isletme["boylam"])
    
    # Süre hesabı
    sonuclar, toplam_sure = sure_ve_saat_hesapla(
        df, sirali_indexler, isletme["enlem"], isletme["boylam"],
        bolge, is_sureleri, km_sureleri
    )
    
    for r in sonuclar:
        r["ekip_adi"] = ekip_adi
    
    doluluk = doluluk_orani_hesapla(toplam_sure)
    
    return sirali_indexler, sonuclar, toplam_sure, doluluk, isletme


def otomatik_doluluk_atama(df, hedef_lat, hedef_lon, hedef_doluluk_yuzde,
                            ilce, bolge, is_sureleri, km_sureleri, isletme_koordinatlari):
    """Doluluk oranına göre otomatik iş atama.
    Arayüzde seçilen/aranan hizmet noktasına en yakın işlerden başlayarak
    hedef doluluk oranına ulaşana kadar iş ekler."""
    hedef_dakika = (hedef_doluluk_yuzde / 100.0) * 480.0
    
    # Öğle molası için 90 dakika hedefe eklenir (eğer çalışma 12:00'ı geçecekse)
    if hedef_dakika > 225.0:
        hedef_dakika += 90.0
        
    # İşletme koordinatlarını bul (ekibin sabah başlangıç noktası)
    isletme = isletme_koordinat_bul(ilce, bolge, isletme_koordinatlari)
    if isletme is None:
        start_lat = hedef_lat if (hedef_lat is not None and pd.notna(hedef_lat)) else (df["Enlem"].mean() if not df.empty else 36.887)
        start_lon = hedef_lon if (hedef_lon is not None and pd.notna(hedef_lon)) else (df["Boylam"].mean() if not df.empty else 30.709)
        isletme = {"enlem": start_lat, "boylam": start_lon}
    
    # Seçim merkezi: Aranan/seçilen hizmet noktası (varsa), yoksa İşletme merkez koordinatı
    if hedef_lat is not None and pd.notna(hedef_lat) and hedef_lon is not None and pd.notna(hedef_lon):
        ref_lat, ref_lon = hedef_lat, hedef_lon
    else:
        ref_lat, ref_lon = isletme["enlem"], isletme["boylam"]

    atanmamis = df[df["Ekip"] == "Atanmamış"].copy()
    if atanmamis.empty:
        return []
    
    # Aday işleri seçilen hizmet noktasına en yakından uzağa doğru sırala
    atanmamis["_mesafe_hn"] = haversine_mesafe(ref_lat, ref_lon, atanmamis["Enlem"], atanmamis["Boylam"])
    atanmamis = atanmamis.sort_values("_mesafe_hn")
    
    secilen_indexler = []
    
    for idx in atanmamis.index:
        yeni_secilen = secilen_indexler + [idx]
        temp_df = df.loc[yeni_secilen]
        
        sirali_idx = rota_sirala(temp_df, isletme["enlem"], isletme["boylam"])
        _, toplam_sure = sure_ve_saat_hesapla(
            temp_df, sirali_idx, isletme["enlem"], isletme["boylam"],
            bolge, is_sureleri, km_sureleri
        )
        
        # Hedef doluluk süresine ulaşıldığında dur
        if secilen_indexler and (toplam_sure > hedef_dakika * 1.02 or (hedef_doluluk_yuzde <= 100 and toplam_sure >= hedef_dakika)):
            break
        
        secilen_indexler = yeni_secilen
        if toplam_sure >= hedef_dakika:
            break
    
    return secilen_indexler


# ============================================================
# HARİTA FONKSİYONU
# ============================================================

def harita_olustur(df, ekip_renkleri, arama_noktasi=None, goster_rezerv_kwh=False, is_sureleri=None, km_sureleri=None, isletme_koordinatlari=None):
    """Folium haritası - ekip bazlı katmanlarla toggle desteği, arama noktası ve rota okları."""
    # İndeks çakışmalarını önlemek için indeksi sıfırla
    df = df.reset_index(drop=True)
    
    merkez_lat = df["Enlem"].mean()
    merkez_lon = df["Boylam"].mean()
    zoom = 12

    # Arama noktası varsa oraya zoom
    if arama_noktasi is not None:
        merkez_lat, merkez_lon = arama_noktasi
        zoom = 17

    m = folium.Map(location=[merkez_lat, merkez_lon], zoom_start=zoom, tiles="OpenStreetMap")

    # Draw plugini
    draw = plugins.Draw(
        export=False, position="topleft",
        draw_options={
            "polyline": False, "circle": False, "circlemarker": False, "marker": False,
            "polygon": {"allowIntersection": False, "showArea": True},
            "rectangle": {"showArea": True},
        },
        edit_options={"edit": False}
    )
    draw.add_to(m)

    # Fullscreen eklentisi
    plugins.Fullscreen(
        position="topleft",
        title="Tam Ekran",
        title_cancel="Tam Ekrandan Çık",
        force_separate_button=True
    ).add_to(m)

    # --- Ekip bazlı FeatureGroup'lar (toggle için) ---
    cluster_ayar = {"maxClusterRadius": 40, "disableClusteringAtZoom": 17, "spiderfyOnMaxZoom": True}

    # Atanmamış grubu (FeatureGroup)
    fg_atanmamis = folium.FeatureGroup(name=f"⬤ Atanmamış", show=True)

    # Ekip grupları
    ekip_gruplari = {}
    for ekip_adi, renk in ekip_renkleri.items():
        fg = folium.FeatureGroup(name=f'<span style="color:{renk}">⬤</span> {ekip_adi}', show=True)
        ekip_gruplari[ekip_adi] = fg

    # Vektörize HTML Popup ve Tooltip Oluşturma
    df_temp = df.copy()
            
    for col in ["AG_OG", "Tarife", "Ihbar_Sekli_2", "Saha_Aktivitesi_Yonergeleri", "Tahakkuk_Carpani", "Saha_Aktivite_Ozet"]:
        if col in df_temp.columns:
            df_temp[col] = df_temp[col].replace(["", "nan", "NaN", "None", None, np.nan], "Boş")
            df_temp[col] = df_temp[col].fillna("Boş")
        else:
            df_temp[col] = "Boş"

    # Kofra No için string dönüşümü
    if "Kofra_No" in df_temp.columns:
        df_temp["Kofra_No_Str"] = df_temp["Kofra_No"].apply(
            lambda x: str(int(x)) if pd.notna(x) and x != 0 else "Boş"
        )
    else:
        df_temp["Kofra_No_Str"] = "Boş"

    if "Kurulu_Guc" in df_temp.columns:
        df_temp["Kurulu_Guc_Str"] = df_temp["Kurulu_Guc"].apply(
            lambda x: f"{x} kW" if pd.notna(x) else "Boş"
        )
    else:
        df_temp["Kurulu_Guc_Str"] = "Boş"
            
    popup_series = (
        "<b>Ekip:</b> " + df_temp["Ekip"].astype(str) + "<br>"
        "<b>İlçe:</b> " + df_temp["Ilce"].astype(str) + "<br>"
        "<b>Tesisat:</b> " + df_temp["Tesisat_No"].astype(str) + "<br>"
        "<b>Aktivite:</b> " + df_temp["Saha_Aktivite_Ozet"].astype(str) + "<br>"
        "<b>Kofra:</b> " + df_temp["Kofra_No_Str"].astype(str) + "<br>"
        "<b>Kurulu Güç:</b> " + df_temp["Kurulu_Guc_Str"].astype(str) + "<br>"
        "<b>AG/OG:</b> " + df_temp["AG_OG"].astype(str) + "<br>"
        "<b>Tarife:</b> " + df_temp["Tarife"].astype(str) + "<br>"
        "<b>Yönerge:</b> " + df_temp["Saha_Aktivitesi_Yonergeleri"].astype(str)
    )
    popup_series = popup_series.str.replace("<br><b>Yönerge:</b> Boş", "", regex=False)

    if "Aktivite_Olusturan_Birim" in df_temp.columns:
        popup_series += "<br><b>Oluşturan Birim:</b> " + df_temp["Aktivite_Olusturan_Birim"].astype(str).replace(["nan", "", "None"], "Belirtilmemiş")
    if goster_rezerv_kwh and "Rezerv_Kwh" in df_temp.columns:
        popup_series += "<br><b>Rezerv Kwh:</b> " + df_temp["Rezerv_Kwh"].astype(str)
    if "Aktivite_Olusturulma_Tarihi" in df_temp.columns:
        popup_series += "<br><b>Oluşturulma Tarihi:</b> " + df_temp["Aktivite_Olusturulma_Tarihi"].astype(str).replace(["nan", "NaT", "None"], "Belirtilmemiş")
        
    popup_series = popup_series.str.replace("<br><b>Oluşturan Birim:</b> Belirtilmemiş", "", regex=False)
    popup_series = popup_series.str.replace("<br><b>Oluşturan Birim:</b> Boş", "", regex=False)
    
    df_temp["popup_html_val"] = popup_series
    df_temp["tooltip_val"] = df_temp["Tesisat_No"].astype(str) + " - " + df_temp["Ekip"].astype(str)

    # FastMarkerCluster ile Vektörize Hızlı Renderlama (Optimizasyon)
    callback = """
    function (row) {
        var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {color: row[2], fill: true, fillColor: row[2], fillOpacity: 0.85, radius: 8});
        var popup = L.popup({maxWidth: 250}).setContent(row[3]);
        marker.bindPopup(popup);
        marker.bindTooltip(row[4]);
        return marker;
    };
    """

    # --- İşletme Merkezleri Katmanı ---
    fg_isletmeler = folium.FeatureGroup(name="🏠 İşletme Merkezleri", show=True)
    if isletme_koordinatlari:
        eklenen_isletmeler = set()
        for (k_ilce, k_bolge), coords in isletme_koordinatlari.items():
            pos_key = (round(coords["enlem"], 5), round(coords["boylam"], 5))
            if pos_key not in eklenen_isletmeler:
                eklenen_isletmeler.add(pos_key)
                folium.Marker(
                    location=[coords["enlem"], coords["boylam"]],
                    icon=folium.Icon(color="darkblue", icon="home", prefix="fa"),
                    popup=f"🏢 <b>İşletme Merkezi</b><br><b>İlçe:</b> {k_ilce}<br><b>Bölge:</b> {k_bolge}",
                    tooltip=f"🏠 İşletme Merkezi - {k_ilce}"
                ).add_to(fg_isletmeler)

    for ekip, group in df_temp.groupby("Ekip"):
        if ekip == "Atanmamış":
            renk = ATANMAMIS_RENK
            hedef_fg = fg_atanmamis
        else:
            renk = ekip_renkleri.get(ekip, "#333333")
            hedef_fg = ekip_gruplari.get(ekip, fg_atanmamis)
            
        data_kume = group[["Enlem_Gosterim", "Boylam_Gosterim"]].copy()
        data_kume["renk"] = renk
        data_kume["popup"] = group["popup_html_val"]
        data_kume["tooltip"] = group["tooltip_val"]
        
        icon_js = f"""
        function(cluster) {{
            var childCount = cluster.getChildCount();
            return new L.DivIcon({{
                html: '<div style="background-color:{renk}d9;border-radius:50%;width:40px;height:40px;display:flex;align-items:center;justify-content:center;color:white;font-size:14px;font-weight:bold;border:3px solid {renk};box-shadow:0 0 10px {renk}80;"><span>' + childCount + '</span></div>',
                className: 'marker-cluster-custom',
                iconSize: new L.Point(40, 40)
            }});
        }}
        """
        
        fmc = plugins.FastMarkerCluster(
            data_kume.values.tolist(), 
            callback=callback,
            icon_create_function=icon_js,
            **cluster_ayar
        )
        fmc.add_to(hedef_fg)

        # Rota oklarını çiz (Sadece atanmış ekipler ve süre verileri varsa)
        if ekip != "Atanmamış" and is_sureleri is not None:
            rota_sonuc = ekip_rotalama_hesapla(df, ekip, is_sureleri, km_sureleri, isletme_koordinatlari)
            if rota_sonuc is not None:
                sirali_idx, _, _, _, isletme_koor = rota_sonuc
                
                path_coords = []
                if isletme_koor and "enlem" in isletme_koor and "boylam" in isletme_koor:
                    isletme_lat = float(isletme_koor["enlem"])
                    isletme_lon = float(isletme_koor["boylam"])
                    path_coords.append([isletme_lat, isletme_lon])
                    
                    # Ekibin rotasının başladığı İşletme konumuna ev ikonu ekle
                    folium.Marker(
                        location=[isletme_lat, isletme_lon],
                        icon=folium.Icon(color="darkblue", icon="home", prefix="fa"),
                        popup=f"🏠 <b>{ekip} Başlangıç Noktası (İşletme)</b>",
                        tooltip=f"🏠 {ekip} İşletme Merkezi"
                    ).add_to(hedef_fg)
                
                for idx in sirali_idx:
                    if idx in group.index:
                        item = group.loc[idx]
                        if isinstance(item, pd.DataFrame):
                            item = item.iloc[0]
                        try:
                            lat_v = float(item["Enlem_Gosterim"])
                            lon_v = float(item["Boylam_Gosterim"])
                            if pd.notna(lat_v) and pd.notna(lon_v):
                                path_coords.append([lat_v, lon_v])
                        except (ValueError, TypeError):
                            continue
                
                if len(path_coords) > 1:
                    # Çizgilerin kesin görünmesi için hem PolyLine hem AntPath ekle
                    folium.PolyLine(
                        locations=path_coords,
                        color=renk,
                        weight=5,
                        opacity=0.85,
                        tooltip=f"🛣️ {ekip} Rotası"
                    ).add_to(hedef_fg)
                    
                    plugins.AntPath(
                        locations=path_coords,
                        color=renk,
                        weight=5,
                        opacity=0.9,
                        delay=1000,
                        dash_array=[10, 20],
                        tooltip=f"🛣️ {ekip} Hareket Rotası"
                    ).add_to(hedef_fg)

    # Grupları haritaya ekle
    fg_isletmeler.add_to(m)
    fg_atanmamis.add_to(m)
    for fg in ekip_gruplari.values():
        fg.add_to(m)

    # Arama noktası varsa özel marker
    if arama_noktasi is not None:
        folium.Marker(
            location=arama_noktasi,
            icon=folium.Icon(color="red", icon="star", prefix="fa"),
            popup="📍 Aranan Hizmet Noktası",
            tooltip="📍 Aranan Nokta"
        ).add_to(m)

    # LayerControl — ekipleri açıp kapatma
    folium.LayerControl(collapsed=False).add_to(m)

    return m


def koordinat_sirasi_tespit(geometry):
    """Leaflet Draw'dan gelen GeoJSON koordinatlarının sırasını tespit eder."""
    try:
        coords = geometry.get("coordinates", [])
        if geometry.get("type") == "Polygon" and coords:
            first_point = coords[0][0]
            if first_point[0] > 35:
                return "lat_lng"
            else:
                return "lng_lat"
    except (IndexError, TypeError, KeyError):
        pass
    return "lng_lat"


def polygon_koordinatlarini_duzelt(geometry):
    """Eğer koordinatlar [lat, lng] sırasındaysa [lng, lat]'e çevirir."""
    sira = koordinat_sirasi_tespit(geometry)
    if sira == "lat_lng":
        yeni_coords = []
        for ring in geometry["coordinates"]:
            yeni_ring = [[p[1], p[0]] for p in ring]
            yeni_coords.append(yeni_ring)
        geometry = dict(geometry)
        geometry["coordinates"] = yeni_coords
    return geometry


def alan_icindeki_isleri_bul(df, geojson_data):
    """Çizilen alanın içindeki atanmamış işleri bulur. Vektörize bounding box ile hızlandırılmış versiyon."""
    if not geojson_data:
        return []

    secilen_indexler = []
    hata_olustu = False
    
    atanmamis_mask = df["Ekip"] == "Atanmamış"
    if not atanmamis_mask.any():
        return []
        
    df_atanmamis = df[atanmamis_mask]
    
    for feature in geojson_data.get("features", []):
        try:
            duzeltilmis_geom = polygon_koordinatlarini_duzelt(feature["geometry"])
            cizim = shape(duzeltilmis_geom)
            
            minx, miny, maxx, maxy = cizim.bounds
            bbox_mask = (df_atanmamis["Boylam_Gosterim"] >= minx) & \
                        (df_atanmamis["Boylam_Gosterim"] <= maxx) & \
                        (df_atanmamis["Enlem_Gosterim"] >= miny) & \
                        (df_atanmamis["Enlem_Gosterim"] <= maxy)
                        
            adaylar = df_atanmamis[bbox_mask]
            
            if not adaylar.empty:
                import shapely
                pts = shapely.points(adaylar["Boylam_Gosterim"].values, adaylar["Enlem_Gosterim"].values)
                contains_mask = shapely.contains(cizim, pts)
                secilen_indexler.extend(adaylar[contains_mask].index.tolist())
        except Exception as e:
            hata_olustu = True
            continue

    if hata_olustu and not secilen_indexler:
        st.warning("⚠️ Çizilen alanın geometrisi okunamadı. Lütfen alanı tekrar çizmeyi deneyin.")

    return list(set(secilen_indexler))


def en_yakin_isleri_bul(df, hedef_lat, hedef_lon, adet):
    """Hedef noktaya en yakın atanmamış işleri bulur. Vektörize mesafe hesabı kullanır."""
    atanmamis = df[df["Ekip"] == "Atanmamış"].copy()
    if atanmamis.empty:
        return []

    atanmamis["mesafe"] = haversine_mesafe(hedef_lat, hedef_lon, atanmamis["Enlem"], atanmamis["Boylam"])
    atanmamis = atanmamis.sort_values("mesafe")
    return atanmamis.head(adet).index.tolist()


# ============================================================
# TABLO ve EXPORT FONKSİYONLARI
# ============================================================

def mola_satiri_ekle(sonuc, rotalama_verileri):
    """Mola satırını tabloya düzenli şekilde yerleştirir."""
    if rotalama_verileri is not None:
        mola_satirlari = [r for r in rotalama_verileri if r.get("is_mola")]
        if mola_satirlari:
            yeni_satirlar = []
            for mola in mola_satirlari:
                yeni_satir = {col: "" for col in sonuc.columns}
                if "Sıra" in sonuc.columns: yeni_satir["Sıra"] = mola["sira"]
                if "Varış Saati" in sonuc.columns: yeni_satir["Varış Saati"] = mola["varis_saati"]
                if "İşlem Süresi (dk)" in sonuc.columns: yeni_satir["İşlem Süresi (dk)"] = mola["islem_suresi"]
                if "Toplam Süre (dk)" in sonuc.columns: yeni_satir["Toplam Süre (dk)"] = mola["islem_suresi"]
                if "Aktivite Tipi" in sonuc.columns: yeni_satir["Aktivite Tipi"] = "🍽️ ÖĞLE MOLASI (90 dk)"
                if "Atandığı Ekip" in sonuc.columns: yeni_satir["Atandığı Ekip"] = mola.get("ekip_adi", "")
                
                yeni_satirlar.append(yeni_satir)
            
            sonuc = pd.concat([sonuc, pd.DataFrame(yeni_satirlar)], ignore_index=True)
    return sonuc

def sira_duzelt(df):
    """Sort_values sonrasında 'Sıra' sütunundaki float 'Mola' numaralarını 'Mola' yazısına çevirir."""
    if "Sıra" in df.columns:
        df["Sıra"] = df["Sıra"].apply(
            lambda x: "Mola" if isinstance(x, float) and not x.is_integer() else (int(x) if pd.notna(x) and x != "" else "")
        )
    return df

def tablo_sutunlari_hazirla(df_kaynak, rotalama_verileri=None):
    """Dashboard tablosu için sütunları hazırlar. Rotalama verileri varsa ek sütunlar eklenir."""
    sonuc = pd.DataFrame()
    
    # Rotalama sırası varsa önce onu koy
    if rotalama_verileri is not None:
        idx_to_sira = {}
        idx_to_varis = {}
        idx_to_yol = {}
        idx_to_islem = {}
        idx_to_mesafe = {}
        idx_to_toplam = {}
        for r in rotalama_verileri:
            idx_to_sira[r["idx"]] = r["sira"]
            idx_to_varis[r["idx"]] = r["varis_saati"]
            idx_to_yol[r["idx"]] = r["yol_suresi"]
            idx_to_islem[r["idx"]] = r["islem_suresi"]
            idx_to_mesafe[r["idx"]] = r["mesafe_km"]
            idx_to_toplam[r["idx"]] = round(r["yol_suresi"] + r["islem_suresi"], 1)
        sonuc["Sıra"] = df_kaynak.index.map(lambda x: idx_to_sira.get(x, ""))
        sonuc["Varış Saati"] = df_kaynak.index.map(lambda x: idx_to_varis.get(x, ""))
    
    sonuc["Tesisat No"] = df_kaynak["Tesisat_No"].values
    sonuc["Bölge"] = df_kaynak["Bolge"].values
    sonuc["İlçe"] = df_kaynak["Ilce"].values
    sonuc["Atandığı Ekip"] = df_kaynak["Ekip"].values
    
    if "Saha_Aktivite_Ozet" in df_kaynak.columns:
        sonuc["Aktivite Tipi"] = df_kaynak["Saha_Aktivite_Ozet"].values
    
    if "Kofra_No" in df_kaynak.columns:
        sonuc["Kofra No"] = df_kaynak["Kofra_No"].apply(
            lambda x: str(int(x)) if pd.notna(x) and x != 0 else ""
        ).values
    
    if rotalama_verileri is not None:
        sonuc["Mesafe (KM)"] = df_kaynak.index.map(lambda x: idx_to_mesafe.get(x, ""))
        sonuc["Yol Süresi (dk)"] = df_kaynak.index.map(lambda x: idx_to_yol.get(x, ""))
        sonuc["İşlem Süresi (dk)"] = df_kaynak.index.map(lambda x: idx_to_islem.get(x, ""))
        sonuc["Toplam Süre (dk)"] = df_kaynak.index.map(lambda x: idx_to_toplam.get(x, ""))
    
    for col, baslik in [("Sayac_Seri_No", "Sayaç Seri No"), ("Adres", "Adres"),
                         ("Enlem", "Enlem"), ("Boylam", "Boylam"),
                         ("Sayac_Tip_Adi", "Sayaç Tipi"),
                         ("Tarife", "Tarife"),
                         ("Kurulu_Guc", "Kurulu Güç"),
                         ("AG_OG", "AG/OG"),
                         ("Saha_Aktivitesi_Yonergeleri", "Yönerge"),
                         ("Rezerv_Kwh", "Rezerv Kwh"),
                         ("Ihbar_Sekli_2", "İhbar"),
                         ("Tahakkuk_Carpani", "Tahakkuk Çarpanı"),
                         ("Aktivite_Olusturulma_Tarihi", "Aktivite Oluşturulma Tarihi"),
                         ("Aktivite_Olusturan_Birim", "İş Oluşturan Birim")]:
        if col in df_kaynak.columns:
            sonuc[baslik] = df_kaynak[col].values
            
    return mola_satiri_ekle(sonuc, rotalama_verileri)

def export_sutunlari_hazirla(df_kaynak, rotalama_verileri=None):
    """Excel export (Master) için sütunları hazırlar."""
    sonuc = pd.DataFrame()
    
    if rotalama_verileri is not None:
        idx_to_sira = {}
        idx_to_varis = {}
        idx_to_yol = {}
        idx_to_islem = {}
        idx_to_mesafe = {}
        idx_to_toplam = {}
        for r in rotalama_verileri:
            idx_to_sira[r["idx"]] = r["sira"]
            idx_to_varis[r["idx"]] = r["varis_saati"]
            idx_to_yol[r["idx"]] = r["yol_suresi"]
            idx_to_islem[r["idx"]] = r["islem_suresi"]
            idx_to_mesafe[r["idx"]] = r["mesafe_km"]
            idx_to_toplam[r["idx"]] = round(r["yol_suresi"] + r["islem_suresi"], 1)
        sonuc["Sıra"] = df_kaynak.index.map(lambda x: idx_to_sira.get(x, ""))
        sonuc["Varış Saati"] = df_kaynak.index.map(lambda x: idx_to_varis.get(x, ""))
    
    sonuc["Tesisat No"] = df_kaynak["Tesisat_No"].values
    sonuc["İlçe"] = df_kaynak["Ilce"].values
    sonuc["Atandığı Ekip"] = df_kaynak["Ekip"].values
    
    if "Saha_Aktivite_Ozet" in df_kaynak.columns:
        sonuc["Aktivite Tipi"] = df_kaynak["Saha_Aktivite_Ozet"].values
    if "Kofra_No" in df_kaynak.columns:
        sonuc["Kofra No"] = df_kaynak["Kofra_No"].apply(
            lambda x: str(int(x)) if pd.notna(x) and x != 0 else ""
        ).values
    
    if rotalama_verileri is not None:
        sonuc["Mesafe (KM)"] = df_kaynak.index.map(lambda x: idx_to_mesafe.get(x, ""))
        sonuc["Yol Süresi (dk)"] = df_kaynak.index.map(lambda x: idx_to_yol.get(x, ""))
        sonuc["İşlem Süresi (dk)"] = df_kaynak.index.map(lambda x: idx_to_islem.get(x, ""))
        sonuc["Toplam Süre (dk)"] = df_kaynak.index.map(lambda x: idx_to_toplam.get(x, ""))
    
    for col, baslik in [("Sayac_Seri_No", "Sayaç Seri No"), ("Adres", "Adres"),
                         ("Enlem", "Enlem"), ("Boylam", "Boylam"),
                         ("Tarife", "Tarife"),
                         ("Kurulu_Guc", "Kurulu Güç"),
                         ("AG_OG", "AG/OG"),
                         ("Saha_Aktivitesi_Yonergeleri", "Yönerge"),
                         ("Rezerv_Kwh", "Rezerv Kwh"),
                         ("Ihbar_Sekli_2", "İhbar"),
                         ("Tahakkuk_Carpani", "Tahakkuk Çarpanı"),
                         ("Aktivite_Olusturulma_Tarihi", "Aktivite Oluşturulma Tarihi"),
                         ("Aktivite_Olusturan_Birim", "İş Oluşturan Birim")]:
        if col in df_kaynak.columns:
            sonuc[baslik] = df_kaynak[col].values
            
    return mola_satiri_ekle(sonuc, rotalama_verileri)

def ekip_export_sutunlari_hazirla(df_kaynak, rotalama_verileri=None):
    """Ekiplerin kendi sayfaları için sütunları hazırlar."""
    sonuc = pd.DataFrame()
    
    if rotalama_verileri is not None:
        idx_to_sira = {}
        idx_to_varis = {}
        idx_to_yol = {}
        idx_to_islem = {}
        idx_to_mesafe = {}
        idx_to_toplam = {}
        for r in rotalama_verileri:
            idx_to_sira[r["idx"]] = r["sira"]
            idx_to_varis[r["idx"]] = r["varis_saati"]
            idx_to_yol[r["idx"]] = r["yol_suresi"]
            idx_to_islem[r["idx"]] = r["islem_suresi"]
            idx_to_mesafe[r["idx"]] = r["mesafe_km"]
            idx_to_toplam[r["idx"]] = round(r["yol_suresi"] + r["islem_suresi"], 1)
        sonuc["Sıra"] = df_kaynak.index.map(lambda x: idx_to_sira.get(x, ""))
        sonuc["Varış Saati"] = df_kaynak.index.map(lambda x: idx_to_varis.get(x, ""))
    
    sonuc["Tesisat No"] = df_kaynak["Tesisat_No"].values
    sonuc["İlçe"] = df_kaynak["Ilce"].values
    sonuc["Atandığı Ekip"] = df_kaynak["Ekip"].values
    
    if "Saha_Aktivite_Ozet" in df_kaynak.columns:
        sonuc["Aktivite Tipi"] = df_kaynak["Saha_Aktivite_Ozet"].values
    if "Kofra_No" in df_kaynak.columns:
        sonuc["Kofra No"] = df_kaynak["Kofra_No"].apply(
            lambda x: str(int(x)) if pd.notna(x) and x != 0 else ""
        ).values
    
    if rotalama_verileri is not None:
        sonuc["Mesafe (KM)"] = df_kaynak.index.map(lambda x: idx_to_mesafe.get(x, ""))
        sonuc["Yol Süresi (dk)"] = df_kaynak.index.map(lambda x: idx_to_yol.get(x, ""))
        sonuc["İşlem Süresi (dk)"] = df_kaynak.index.map(lambda x: idx_to_islem.get(x, ""))
        sonuc["Toplam Süre (dk)"] = df_kaynak.index.map(lambda x: idx_to_toplam.get(x, ""))
    
    for col, baslik in [("Sayac_Seri_No", "Sayaç Seri No"), ("Adres", "Adres"),
                         ("Enlem", "Enlem"), ("Boylam", "Boylam"),
                         ("Tarife", "Tarife"),
                         ("Kurulu_Guc", "Kurulu Güç"),
                         ("AG_OG", "AG/OG"),
                         ("Saha_Aktivitesi_Yonergeleri", "Yönerge"),
                         ("Rezerv_Kwh", "Rezerv Kwh"),
                         ("Ihbar_Sekli_2", "İhbar"),
                         ("Tahakkuk_Carpani", "Tahakkuk Çarpanı")]:
        if col in df_kaynak.columns:
            sonuc[baslik] = df_kaynak[col].values
            
    return mola_satiri_ekle(sonuc, rotalama_verileri)


def excel_export(df, is_sureleri=None, km_sureleri=None, isletme_koordinatlari=None):
    """Atama sonuçlarını Excel dosyasına yazar ve BytesIO döner."""
    try:
        output = BytesIO()
        atanmis_df = df[df["Ekip"] != "Atanmamış"]
        atanmamis_df = df[df["Ekip"] == "Atanmamış"]

        if atanmis_df.empty and atanmamis_df.empty:
            return None

        # Her ekip için rotalama hesapla
        ekip_rotalama_cache = {}
        if not atanmis_df.empty and is_sureleri is not None:
            for ekip_adi in atanmis_df["Ekip"].unique():
                rota_sonuc = ekip_rotalama_hesapla(df, ekip_adi, is_sureleri, km_sureleri, isletme_koordinatlari)
                if rota_sonuc is not None:
                    ekip_rotalama_cache[ekip_adi] = rota_sonuc

        with pd.ExcelWriter(output, engine="openpyxl") as writer:
            # 1. Master sayfası — Sadece atanmış işler
            if not atanmis_df.empty:
                # Tüm ekiplerin rotalama verilerini birleştir
                tum_rotalama = []
                for ekip_adi in sorted(atanmis_df["Ekip"].unique()):
                    if ekip_adi in ekip_rotalama_cache:
                        _, sonuclar, _, _, _ = ekip_rotalama_cache[ekip_adi]
                        tum_rotalama.extend(sonuclar)
                
                master = export_sutunlari_hazirla(atanmis_df, tum_rotalama if tum_rotalama else None)
                if tum_rotalama:
                    master = master.sort_values(["Atandığı Ekip", "Sıra"]).reset_index(drop=True)
                master = sira_duzelt(master)
                master.to_excel(writer, sheet_name="Master", index=False)
                
            # 2. Atanmayan İşler sayfası
            if not atanmamis_df.empty:
                atanmayan = export_sutunlari_hazirla(atanmamis_df)
                atanmayan.to_excel(writer, sheet_name="Atanmayan İşler", index=False)

            # 3. Her ekip için ayrı sayfa
            if not atanmis_df.empty:
                atanmis_ekipler = sorted(atanmis_df["Ekip"].unique())
                for ekip_adi in atanmis_ekipler:
                    grup = atanmis_df[atanmis_df["Ekip"] == ekip_adi]
                    sonuclar = ekip_rotalama_cache.get(ekip_adi, (None, None, None, None, None))[1]
                    ekip_df = ekip_export_sutunlari_hazirla(grup, sonuclar)
                    if sonuclar:
                        ekip_df = ekip_df.sort_values("Sıra").reset_index(drop=True)
                    ekip_df = sira_duzelt(ekip_df)
                    ekip_df.to_excel(writer, sheet_name=ekip_adi[:31], index=False)

            # 4. Koordinatsız İşler
            if st.session_state.df_koordinatsiz is not None and not st.session_state.df_koordinatsiz.empty:
                koor_df = export_sutunlari_hazirla(st.session_state.df_koordinatsiz)
                koor_cols_drop = [c for c in ["Enlem", "Boylam", "Atandığı Ekip"] if c in koor_df.columns]
                koor_df = koor_df.drop(columns=koor_cols_drop, errors="ignore")
                koor_df.to_excel(writer, sheet_name="Koordinatsız İşler", index=False)

        output.seek(0)
        return output
    except Exception as e:
        st.error(f"❌ Excel dosyası oluşturulurken hata oluştu: {str(e)}")
        return None


# ============================================================
# SONUÇ ANALİZİ MODÜLÜ İMPORTLARI
# ============================================================
from sonuc_analiz import (
    fen_isleri_excel_oku,
    kontak_excel_oku,
    prepare_sonuc_data,
    compute_sonuc_rapor,
    build_sutun_haritasi,
    isim_listesi_oku,
    format_tr_number,
    safe_numeric_mean,
    safe_numeric_sum,
    saniye_formatla,
    saniye_to_saat
)


# ============================================================
# SESSION STATE BAŞLATMA
# ============================================================

if "df" not in st.session_state:
    st.session_state.df = None
if "df_koordinatsiz" not in st.session_state:
    st.session_state.df_koordinatsiz = None
if "son_cizim" not in st.session_state:
    st.session_state.son_cizim = None
if "ekip_sayisi" not in st.session_state:
    st.session_state.ekip_sayisi = 5
if "arama_noktasi" not in st.session_state:
    st.session_state.arama_noktasi = None
if "df_sonuc" not in st.session_state:
    st.session_state.df_sonuc = None

# İşlem Süreleri verilerini yükle (uygulama başlangıcında bir kez)
if "islem_sureleri_loaded" not in st.session_state:
    _is_sureleri, _km_sureleri, _isletme_koordinatlari = islem_sureleri_oku()
    st.session_state._is_sureleri = _is_sureleri
    st.session_state._km_sureleri = _km_sureleri
    st.session_state._isletme_koordinatlari = _isletme_koordinatlari
    st.session_state.islem_sureleri_loaded = True


# ============================================================
# CUSTOM CSS
# ============================================================
st.markdown("""
<style>
    .stApp { background-color: #f8f9fa; }
    div[data-testid="stMetric"] {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 15px 20px;
        border-radius: 12px;
        color: white !important;
        box-shadow: 0 4px 15px rgba(102,126,234,0.3);
    }
    div[data-testid="stMetric"] label { color: rgba(255,255,255,0.85) !important; }
    div[data-testid="stMetric"] div[data-testid="stMetricValue"] { color: white !important; font-weight: 700; }
    .baslik-kutu {
        background: linear-gradient(135deg, #600000, #a90000, #400000);
        padding: 20px 30px;
        border-radius: 14px;
        margin-bottom: 20px;
        color: white;
        display: flex;
        align-items: center;
        justify-content: space-between;
    }
    .baslik-kutu .baslik-metin {
        text-align: left;
    }
    .baslik-kutu .baslik-metin h1 {
        margin: 0;
    }
    .baslik-kutu .baslik-metin p {
        margin: 5px 0 0 0;
        opacity: 0.85;
    }
    .baslik-kutu .baslik-logo img {
        height: 60px;
        border-radius: 8px;
        background: white;
        padding: 4px 8px;
    }
    section[data-testid="stSidebar"] > div { background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%); }
    section[data-testid="stSidebar"] label, section[data-testid="stSidebar"] p,
    section[data-testid="stSidebar"] span, section[data-testid="stSidebar"] h1,
    section[data-testid="stSidebar"] h2, section[data-testid="stSidebar"] h3 { color: #e0e0e0 !important; }
    /* Soru işareti (Tooltip) ikonlarını belirginleştir (Beyaz ve Parlak) */
    .stTooltipIcon svg,
    [data-testid="stTooltipIcon"] svg,
    [data-testid="stTooltipHoverTarget"] svg {
        color: #ffffff !important;
        fill: #ffffff !important;
        stroke: #ffffff !important;
        opacity: 1 !important;
        width: 1.5rem !important;
        height: 1.5rem !important;
        filter: drop-shadow(0px 0px 4px rgba(255,255,255,0.8));
        margin-left: 5px;
    }
    
    .stTooltipIcon:hover svg,
    [data-testid="stTooltipIcon"]:hover svg,
    [data-testid="stTooltipHoverTarget"]:hover svg {
        transform: scale(1.2);
        transition: 0.2s;
    }
</style>
""", unsafe_allow_html=True)


# ============================================================
# ANA ARAYÜZ
# ============================================================
st.markdown(
    f'<div class="baslik-kutu">'
    f'<div class="baslik-metin"><h1>🗺️ Ekip İş Planlama Dashboard</h1><p>MTH Personelleri — Saha Planlama</p></div>'
    f'</div>',
    unsafe_allow_html=True
)

# --- İşlem Süreleri durumu ---
_is_sureleri = st.session_state.get("_is_sureleri")
_km_sureleri = st.session_state.get("_km_sureleri")
_isletme_koordinatlari = st.session_state.get("_isletme_koordinatlari")

# --- SIDEBAR ---
with st.sidebar:
    st.header("📊 Kontrol Paneli")

    # İstatistikler ve Ekip Dağılımı
    if st.session_state.df is not None:
        df = st.session_state.df
        toplam = len(df)
        atanmis = len(df[df["Ekip"] != "Atanmamış"])
        kalan = toplam - atanmis

        st.subheader("📈 İş Durumu")
        st.metric("Toplam İş", toplam)
        st.metric("Atanmış", atanmis)
        st.metric("Kalan", kalan)

        if toplam > 0:
            oran = atanmis / toplam
            st.progress(oran, text=f"%{oran*100:.1f} tamamlandı")

        st.divider()

        # Ekip bazlı dağılım + doluluk oranı
        ekip_renkleri = aktif_ekipler(st.session_state.ekip_sayisi)
        st.subheader("👥 Ekip Dağılımı")
        ekip_sayilari = df[df["Ekip"] != "Atanmamış"]["Ekip"].value_counts()
        if not ekip_sayilari.empty:
            for ekip_adi, sayi in ekip_sayilari.items():
                renk = ekip_renkleri.get(ekip_adi, "#333")
                # Doluluk oranı hesapla
                doluluk_str = ""
                if _is_sureleri is not None:
                    rota_sonuc = ekip_rotalama_hesapla(df, ekip_adi, _is_sureleri, _km_sureleri, _isletme_koordinatlari)
                    if rota_sonuc is not None:
                        _, sonuclar_list, toplam_sure, doluluk, _ = rota_sonuc
                        gosterilen_sure = toplam_sure
                        if any(r.get("is_mola") for r in sonuclar_list):
                            gosterilen_sure = max(0, gosterilen_sure - 90.0)
                        gosterilen_doluluk = doluluk_orani_hesapla(gosterilen_sure)
                        doluluk_str = f" — 📊 %{gosterilen_doluluk:.0f} ({gosterilen_sure:.0f} dk)"
                st.markdown(f'<span style="color:{renk};font-weight:bold;">● {ekip_adi}:</span> {sayi} iş{doluluk_str}', unsafe_allow_html=True)
        else:
            st.info("Henüz atama yapılmadı.")

    st.divider()

    # İşlem süreleri durumu
    if _is_sureleri is not None:
        st.success(f"✅ İşlem Süreleri yüklendi ({len(_is_sureleri)} iş kalemi)")
    else:
        st.warning("⚠️ İşlem Süreleri dosyası bulunamadı. Aynı klasöre 'İşlem Süreleri ve İşletme Koordinatları.xlsx' ekleyin.")

    st.divider()

    # Ekip sayısı seçimi
    st.subheader("👥 Ekip Sayısı", help="Bölgenizdeki ekip sayısını giriniz")
    st.session_state.ekip_sayisi = st.number_input(
        "Kaç ekip olacak?", min_value=1, max_value=20,
        value=st.session_state.ekip_sayisi, step=1, key="ekip_sayisi_input"
    )

    st.divider()

    # Excel yükleme
    st.subheader("📁 Bekleyen İşleri Ekle", help="Bekleyen işler excel formatında indirip buraya yükleyin")
    uploaded_files = st.file_uploader("Excel dosyası seçin", type=["xlsx", "xls"], key="excel_upload", accept_multiple_files=True)

    current_file_hashes = [f"{f.name}_{f.size}" for f in uploaded_files] if uploaded_files else []
    
    if current_file_hashes != st.session_state.get("last_file_hashes", []):
        st.session_state["last_file_hashes"] = current_file_hashes
        if uploaded_files:
            with st.spinner("Excel dosyaları okunuyor ve koordinatlar temizleniyor..."):
                tum_dfler = []
                tum_koordinatsiz = []
                tum_istatistikler = {"takas": 0, "gecersiz": 0}
                hatalar = []

                for dosya in uploaded_files:
                    df_yeni, istatistik, k_df, hata = excel_oku(dosya)
                    if hata:
                        hatalar.append(f"**{dosya.name}**: {hata}")
                    elif df_yeni is not None:
                        tum_dfler.append(df_yeni)
                        if k_df is not None and not k_df.empty:
                            tum_koordinatsiz.append(k_df)
                        tum_istatistikler["takas"] += istatistik.get("takas", 0)
                        tum_istatistikler["gecersiz"] += istatistik.get("gecersiz", 0)

                if hatalar:
                    st.session_state.upload_errors = hatalar
                else:
                    st.session_state.upload_errors = []
                
                if tum_dfler:
                    birlestirilmis_df = pd.concat(tum_dfler, ignore_index=True)
                    st.session_state.df = birlestirilmis_df
                    
                    if tum_koordinatsiz:
                        st.session_state.df_koordinatsiz = pd.concat(tum_koordinatsiz, ignore_index=True)
                    else:
                        st.session_state.df_koordinatsiz = None

                    st.session_state.son_cizim = None
                    st.session_state.upload_success_msg = f"✅ **{len(birlestirilmis_df)}** adet iş başarıyla yüklendi!"
                    st.session_state.upload_stats = tum_istatistikler
                    st.rerun()
        else:
            st.session_state.df = None
            st.session_state.df_koordinatsiz = None
            st.session_state.upload_success_msg = None
            st.session_state.upload_errors = []
            st.session_state.upload_stats = {}
            st.rerun()

    # Eğer sayfa yenilendiyse ve mesajlar varsa göster
    if st.session_state.get("upload_errors"):
        for h in st.session_state.upload_errors:
            st.error(h)
    if st.session_state.get("upload_success_msg"):
        st.success(st.session_state.upload_success_msg)
        stats = st.session_state.get("upload_stats", {})
        if stats.get("takas", 0) > 0:
            st.info(f"🔄 {stats['takas']} satırda Enlem↔Boylam takası yapıldı")
        if stats.get("gecersiz", 0) > 0:
            st.warning(f"⚠️ {stats['gecersiz']} satır geçersiz koordinat nedeniyle çıkarıldı")

    st.divider()

    # Sonuç Exceli Yükleme (Sidebar)
    st.subheader("📊 Sonuç Exceli Yükle",
                 help="Fen İşleri Aktivite Raporunu (ve opsiyonel Kontak Raporunu) buraya sürükleyin. Fen raporu dosya adında 'fen' geçmelidir.")
    sidebar_sonuc_files = st.file_uploader(
        "Sonuç Excel dosyalarını seçin",
        type=["xlsx", "xls"],
        key="sonuc_upload_sidebar",
        accept_multiple_files=True
    )
    if sidebar_sonuc_files:
        fen_files = [f for f in sidebar_sonuc_files if "fen" in f.name.lower()]
        kontak_files = [f for f in sidebar_sonuc_files if "kontak" in f.name.lower()]
        if fen_files:
            fen_hash = "_".join([f"{f.name}_{f.size}" for f in fen_files])
            kontak_hash = "_".join([f"{f.name}_{f.size}" for f in kontak_files]) if kontak_files else ""
            curr_hash = f"{fen_hash}__{kontak_hash}"
            if curr_hash != st.session_state.get("last_analiz_files_hash", ""):
                with st.spinner("Fen İşleri ve Kontak verileri işleniyor..."):
                    df_fen_raw, hata_fen = fen_isleri_excel_oku(fen_files)
                    if hata_fen:
                        st.session_state.sonuc_hata = hata_fen
                        st.session_state.df_fen_base = None
                        st.session_state.sonuc_success = None
                    else:
                        df_kontak = None
                        if kontak_files:
                            df_kontak, hata_k = kontak_excel_oku(kontak_files)
                            if hata_k:
                                st.warning(f"⚠️ Kontak excelleri: {hata_k}")
                        
                        isim_files = [f for f in sidebar_sonuc_files if ("isim" in f.name.lower() and "liste" in f.name.lower()) or ("personel" in f.name.lower() and "liste" in f.name.lower())]
                        if isim_files:
                            try:
                                df_names = pd.read_excel(isim_files[0], engine="openpyxl")
                                kvkk_err = kvkk_sutun_kontrol(df_names.columns)
                                if kvkk_err:
                                    st.session_state.sonuc_hata = f"❌ **{kvkk_err}**"
                                    st.session_state.df_fen_base = None
                                    st.session_state.sonuc_success = None
                                else:
                                    df_names.columns = [str(c).replace("*", "").strip() for c in df_names.columns]
                                    if "PERSONEL KODU" in df_names.columns:
                                        df_names["PERSONEL KODU"] = df_names["PERSONEL KODU"].astype(str).str.strip()
                            except Exception:
                                df_names = isim_listesi_oku()
                        else:
                            df_names = isim_listesi_oku()
                        sutun_haritasi = build_sutun_haritasi(df_fen_raw)
                        df_base, _ = prepare_sonuc_data(df_fen_raw, sutun_haritasi, df_kontak, df_names)
                        if df_base is None or df_base.empty:
                            st.session_state.sonuc_hata = "❌ Geçerli veri bulunamadı veya kofra sayısı ≥ 6 olan çalışma günü bulunamadı."
                            st.session_state.df_fen_base = None
                            st.session_state.sonuc_success = None
                        else:
                            st.session_state.df_fen_base = df_base
                            st.session_state.df_names_data = df_names
                            st.session_state.last_analiz_files_hash = curr_hash
                            st.session_state.sonuc_hata = None
                            st.session_state.sonuc_success = f"✅ **{len(df_base):,}** satır Fen İşleri sonuç verisi yüklendi! ({len(fen_files)} Fen raporu)"
    
    if st.session_state.get("sonuc_hata"):
        st.error(st.session_state["sonuc_hata"])
    if st.session_state.get("sonuc_success"):
        st.success(st.session_state["sonuc_success"])

# ============================================================
# ANA İÇERİK
# ============================================================
tab_planlama, tab_analiz = st.tabs(["🗺️ Saha Planlama", "📊 Sonuç Analizi"])

_has_planlama = st.session_state.df is not None

# Planlama sekmesi değişkenleri (sadece ihtiyaç varsa tanımla)
if _has_planlama:
    df = st.session_state.df
    ekip_renkleri = aktif_ekipler(st.session_state.ekip_sayisi)
    ekip_secenekleri = list(ekip_renkleri.keys())

    # --- ARAMA FONKSİYONU (Callback) ---
    def hizmet_ara_callback():
        """Arama butonuna tıklandığında veya Enter'a basıldığında çalışır."""
        if "arama_no" in st.session_state and st.session_state.arama_no.strip():
            arama_temiz = st.session_state.arama_no.strip().lstrip('0') or '0'
            df_temp = st.session_state.df
            eslesen = df_temp[df_temp["Tesisat_No"].str.lstrip('0') == arama_temiz]
            if not eslesen.empty:
                st.session_state.arama_noktasi = (eslesen.iloc[0]["Enlem"], eslesen.iloc[0]["Boylam"])
            else:
                st.session_state.arama_noktasi = None
        else:
            st.session_state.arama_noktasi = None

if tab_planlama is not None:
    with tab_planlama:
        if not _has_planlama:
            st.info("👈 Saha planlaması yapabilmek için sol panelden **Bekleyen İşler** excel dosyasını yükleyin.")
        else:
            # --- HARİTA ---
            st.subheader("🗺️ Saha Haritası")
            st.caption("Haritada dikdörtgen/çokgen çizerek iş seçimi yapın. Sağ üstten ekip katmanlarını açıp kapatabilirsiniz.")

            col_og_date1, col_og_date2, col_og_date3 = st.columns([1, 1.5, 1])
            with col_og_date1:
                ag_og_secim = st.radio("AG/OG Filtresi", ["Tümü", "AG", "OG"], horizontal=True, key="ag_og_filtre")
        
            with col_og_date2:
                kurulu_guc_secim = st.radio("Kurulu Güç Filtresi", ["Tümü", "40 kW Altı", "40 kW Üzeri"], horizontal=True, key="kurulu_guc_filtre")

            date_filter = None
            has_date_data = "Aktivite_Olusturulma_Tarihi" in df.columns and not df["Aktivite_Olusturulma_Tarihi"].dropna().empty
            with col_og_date3:
                if has_date_data:
                    valid_dates = df["Aktivite_Olusturulma_Tarihi"].dropna()
                    min_date = valid_dates.min()
                    max_date = valid_dates.max()
                    date_filter = st.date_input("İş Oluşturma Tarihi Filtresi", value=(min_date, max_date), min_value=min_date, max_value=max_date, key="date_filtre")


            col_f1, col_f2, col_f3, col_f4 = st.columns(4)
            with col_f1:
                tarife_listesi = ["Tümü"] + sorted([str(t) for t in df["Tarife"].unique() if str(t).strip() != ""])
                tarife_secim = st.selectbox("Tarife Filtresi", tarife_listesi, key="tarife_filtre")

            with col_f2:
                # Aktivite Tipi Filtresi (Saha_Aktivite_Özet)
                if "Saha_Aktivite_Ozet" in df.columns:
                    aktivite_listesi = ["Tümü"] + sorted([str(t) for t in df["Saha_Aktivite_Ozet"].unique() if str(t).strip() not in ["", "nan", "Boş"]])
                else:
                    aktivite_listesi = ["Tümü"]
                aktivite_secim = st.selectbox("Aktivite Tipi Filtresi", aktivite_listesi, key="aktivite_filtre")

            with col_f3:
                carpan_secim = st.selectbox("Çarpan Filtresi", ["Tümü", "Çarpanlı (>1)", "Çarpansız (1)"], key="carpan_filtre")

            with col_f4:
                has_birim_data = "Aktivite_Olusturan_Birim" in df.columns and not df["Aktivite_Olusturan_Birim"].replace("", np.nan).dropna().empty
                if has_birim_data:
                    birim_listesi = ["Tümü"] + sorted([str(b) for b in df["Aktivite_Olusturan_Birim"].unique() if str(b).strip() != ""])
                    birim_secim = st.selectbox("İş Oluşturan Birim Filtresi", birim_listesi, key="birim_filtre")
                else:
                    birim_secim = "Tümü"

            # Rezerv Kwh filter conditional
            def parse_kwh(val):
                try:
                    return float(str(val).replace(",", "."))
                except (ValueError, TypeError):
                    return 0.0

            rezerv_secim = "Tümü"
            rezerv_deger = 0.0

            has_rezerv_data = "Rezerv_Kwh" in df.columns

            if has_rezerv_data:
                col_rez1, col_rez2 = st.columns([1, 1])
                with col_rez1:
                    rezerv_secim = st.radio("Rezerv Kwh Filtresi", ["Tümü", "Değer Üzeri"], horizontal=True, key="rezerv_filtre")
                with col_rez2:
                    if rezerv_secim == "Değer Üzeri":
                        rezerv_deger = st.number_input("Filtrelenecek Minimum Kwh Değeri", min_value=0.0, value=300.0, step=10.0, key="rezerv_deger_input")

            df_harita = df.copy()

            if ag_og_secim == "AG":
                df_harita = df_harita[df_harita["AG_OG"].str.upper() == "AG"]
            elif ag_og_secim == "OG":
                df_harita = df_harita[df_harita["AG_OG"].str.upper() == "OG"]

            if kurulu_guc_secim == "40 kW Altı":
                if "Kurulu_Guc" in df_harita.columns:
                    df_harita = df_harita[df_harita["Kurulu_Guc"] < 40]
            elif kurulu_guc_secim == "40 kW Üzeri":
                if "Kurulu_Guc" in df_harita.columns:
                    df_harita = df_harita[df_harita["Kurulu_Guc"] >= 40]

            if tarife_secim != "Tümü":
                df_harita = df_harita[df_harita["Tarife"] == tarife_secim]

            if aktivite_secim != "Tümü" and "Saha_Aktivite_Ozet" in df_harita.columns:
                df_harita = df_harita[df_harita["Saha_Aktivite_Ozet"] == aktivite_secim]

            if birim_secim != "Tümü" and has_birim_data:
                df_harita = df_harita[df_harita["Aktivite_Olusturan_Birim"] == birim_secim]

            if carpan_secim != "Tümü":
                def parse_carpan(val):
                    try:
                        v = str(val).strip().replace(',', '.')
                        if not v or v.lower() == 'nan':
                            return 1.0
                        return float(v)
                    except (ValueError, TypeError):
                        return 1.0
                
                if "Tahakkuk_Carpani" in df_harita.columns:
                    df_harita["Carpan_Num"] = df_harita["Tahakkuk_Carpani"].apply(parse_carpan)
                    if carpan_secim == "Çarpanlı (>1)":
                        df_harita = df_harita[df_harita["Carpan_Num"] > 1.0]
                    else: # "Çarpansız (1)"
                        df_harita = df_harita[df_harita["Carpan_Num"] <= 1.0]
                    df_harita = df_harita.drop(columns=["Carpan_Num"])

            if rezerv_secim == "Değer Üzeri":
                df_harita["Rezerv_Kwh_Num"] = df_harita["Rezerv_Kwh"].apply(parse_kwh)
                df_harita = df_harita[df_harita["Rezerv_Kwh_Num"] >= rezerv_deger]
                df_harita = df_harita.drop(columns=["Rezerv_Kwh_Num"])

            if has_date_data and date_filter is not None:
                if isinstance(date_filter, tuple) and len(date_filter) == 2:
                    start_date, end_date = date_filter
                    df_harita = df_harita[
                        (df_harita["Aktivite_Olusturulma_Tarihi"].isna()) | 
                        ((df_harita["Aktivite_Olusturulma_Tarihi"] >= start_date) & 
                         (df_harita["Aktivite_Olusturulma_Tarihi"] <= end_date))
                    ]
                elif isinstance(date_filter, tuple) and len(date_filter) == 1:
                    start_date = date_filter[0]
                    df_harita = df_harita[
                        (df_harita["Aktivite_Olusturulma_Tarihi"].isna()) | 
                        (df_harita["Aktivite_Olusturulma_Tarihi"] == start_date)
                    ]

            st.markdown(f"**Haritada Gözüken İş Sayısı:** {len(df_harita)}")

            if len(df_harita) == 0:
                st.warning("Belirlenen Filtrelerde iş yoktur.")
            else:
                harita = harita_olustur(df_harita, ekip_renkleri, st.session_state.arama_noktasi, goster_rezerv_kwh=(rezerv_secim == "Değer Üzeri"), is_sureleri=_is_sureleri, km_sureleri=_km_sureleri, isletme_koordinatlari=_isletme_koordinatlari)
                harita_sonuc = st_folium(harita, width=None, height=550, key="harita_ana",
                                          returned_objects=["all_drawings"])

                if harita_sonuc is not None:
                    drawings = harita_sonuc.get("all_drawings")
                    if drawings and len(drawings) > 0:
                        son_drawing = drawings[-1]
                        if "geometry" in son_drawing:
                            geojson = {"type": "FeatureCollection", "features": [son_drawing]}
                            st.session_state.son_cizim = geojson
                        else:
                            st.session_state.son_cizim = None
                    else:
                        st.session_state.son_cizim = None

            if st.session_state.df_koordinatsiz is not None and not st.session_state.df_koordinatsiz.empty:
                with st.expander(f"⚠️ Koordinatsız İşler ({len(st.session_state.df_koordinatsiz)} adet)", expanded=False):
                    st.caption("Aşağıdaki işlerin koordinat bilgisi eksik olduğu için haritada gösterilemiyor.")
                    koor_gosterim = st.session_state.df_koordinatsiz.copy()
                    if "Tesisat_No" in koor_gosterim.columns:
                        st.dataframe(koor_gosterim, hide_index=True, use_container_width=True)

            # --- MANUEL ATAMA ---
            st.subheader("✏️ Manuel İş Atama")
            col_m1, col_m2, col_m3 = st.columns([2, 1, 1])

            with col_m1:
                if st.session_state.son_cizim:
                    secilen_idx = alan_icindeki_isleri_bul(df_harita, st.session_state.son_cizim)
                    st.success(f"📌 Çizilen alanda **{len(secilen_idx)}** atanmamış iş bulundu.")
                else:
                    secilen_idx = []
                    st.info("Haritada bir alan çizin, ardından ekip seçip atayın.")

            with col_m2:
                hedef_ekip_manuel = st.selectbox("Hedef Ekip", ekip_secenekleri, key="manuel_ekip")

            with col_m3:
                st.write("")
                st.write("")
                if st.button("🎯 Seçili İşleri Ekip'e Ata", key="btn_manuel", type="primary",
                             disabled=(len(secilen_idx) == 0)):
                    df.loc[secilen_idx, "Ekip"] = hedef_ekip_manuel
                    st.session_state.df = df
                    st.session_state.son_cizim = None
                    st.success(f"✅ {len(secilen_idx)} iş **{hedef_ekip_manuel}**'e atandı!")
                    st.rerun()

            st.divider()

            # --- ARAMA ARAYÜZÜ ---
            st.subheader("🔍 Hizmet Noktası Ara")
            col_s1, col_s2 = st.columns([3, 1])
            with col_s1:
                st.text_input("Hizmet Noktası No yazın ve haritada gösterin",
                              placeholder="Örn: 3350000", key="arama_no",
                              label_visibility="collapsed", on_change=hizmet_ara_callback)
            with col_s2:
                st.button("📍 Haritada Göster", key="btn_ara", on_click=hizmet_ara_callback, type="secondary", use_container_width=True)

            st.write("")

            # --- OTOMATİK ATAMA ---
            st.subheader("🤖 Otomatik Atama")
            st.caption("Üstteki arama çubuğuna yazdığınız hizmet noktasına en yakın işleri seçilen ekibe atar.")

            oto_mod = st.radio("Atama Modu", ["İş Sayısına Göre", "Doluluk Oranına Göre"], horizontal=True, key="oto_mod")

            if oto_mod == "İş Sayısına Göre":
                col_a1, col_a2 = st.columns([1, 1])
                with col_a1:
                    is_sayisi = st.number_input("Atanacak İş Sayısı", min_value=1, max_value=500, value=25, step=5, key="is_sayisi")
                with col_a2:
                    hedef_ekip_oto = st.selectbox("Hedef Ekip", ekip_secenekleri, key="oto_ekip")

                if st.button("🚀 Otomatik Ata", key="btn_oto", type="primary"):
                    val = st.session_state.get("arama_no", "").strip()
                    if not val:
                        st.error("❌ Önce üstteki arama çubuğuna bir hizmet noktası numarası girin.")
                    else:
                        arama_temiz = val.lstrip('0') or "0"
                        eslesen = df[df["Tesisat_No"].str.lstrip('0') == arama_temiz]
                        if eslesen.empty:
                            st.error(f"❌ '{val}' numaralı hizmet noktası bulunamadı!")
                        else:
                            hedef_lat = eslesen.iloc[0]["Enlem"]
                            hedef_lon = eslesen.iloc[0]["Boylam"]
                            yakin_idx = en_yakin_isleri_bul(df_harita, hedef_lat, hedef_lon, is_sayisi)
                            if not yakin_idx:
                                st.warning("⚠️ Atanacak atanmamış iş bulunamadı.")
                            else:
                                df.loc[yakin_idx, "Ekip"] = hedef_ekip_oto
                                st.session_state.df = df
                                st.success(f"✅ {len(yakin_idx)} iş **{hedef_ekip_oto}**'e otomatik atandı!")
                                st.rerun()

            else:  # Doluluk Oranına Göre
                col_d1, col_d2 = st.columns([1, 1])
                with col_d1:
                    hedef_doluluk = st.number_input("Hedef Doluluk Oranı (%)", min_value=10, max_value=150, value=100, step=5, key="hedef_doluluk",
                                                     help="100% = 480 dakika (8 saat). Örn: 90% = 432 dakika")
                with col_d2:
                    hedef_ekip_doluluk = st.selectbox("Hedef Ekip", ekip_secenekleri, key="doluluk_ekip")

                if st.button("🚀 Doluluk Oranına Göre Ata", key="btn_doluluk", type="primary"):
                    if _is_sureleri is None:
                        st.error("❌ İşlem Süreleri dosyası bulunamadı! Aynı klasöre 'İşlem Süreleri ve İşletme Koordinatları.xlsx' dosyasını ekleyin.")
                    else:
                        val = st.session_state.get("arama_no", "").strip()
                        hedef_lat, hedef_lon = None, None
                        ilce_val, bolge_val = "", ""
                        
                        if val:
                            arama_temiz = val.lstrip('0') or "0"
                            eslesen = df[df["Tesisat_No"].str.lstrip('0') == arama_temiz]
                            if not eslesen.empty:
                                hedef_lat = eslesen.iloc[0]["Enlem"]
                                hedef_lon = eslesen.iloc[0]["Boylam"]
                                ilce_val = eslesen.iloc[0].get("Ilce", "")
                                bolge_val = eslesen.iloc[0].get("Bolge", "")
                        
                        # Hizmet noktası girilmediyse veya ilçesi yoksa unutturma: dominant ilçe/bölgeyi kullan
                        if not ilce_val:
                            atanmamis_tmp = df[df["Ekip"] == "Atanmamış"]
                            target_sub = atanmamis_tmp if not atanmamis_tmp.empty else df
                            if "Ilce" in target_sub.columns and not target_sub["Ilce"].dropna().empty:
                                ilce_val = target_sub["Ilce"].mode().iloc[0]
                            if "Bolge" in target_sub.columns and not target_sub["Bolge"].dropna().empty:
                                bolge_val = target_sub["Bolge"].mode().iloc[0]
                    
                        with st.spinner("İşletme koordinatları ve doluluk hesaplanıyor, işler atanıyor..."):
                            yakin_idx = otomatik_doluluk_atama(
                                df_harita, hedef_lat, hedef_lon, hedef_doluluk,
                                ilce_val, bolge_val,
                                _is_sureleri, _km_sureleri, _isletme_koordinatlari
                            )
                
                        if not yakin_idx:
                            st.warning("⚠️ Atanacak atanmamış iş bulunamadı.")
                        else:
                            df.loc[yakin_idx, "Ekip"] = hedef_ekip_doluluk
                            st.session_state.df = df
                            st.success(f"✅ {len(yakin_idx)} iş **{hedef_ekip_doluluk}**'e atandı! (Hedef doluluk: %{hedef_doluluk})")
                            st.rerun()

            st.divider()

            # --- ATAMA SIFIRLA ---
            col_r1, col_r2 = st.columns([1, 3])
            with col_r1:
                if st.button("🗑️ Tüm Atamaları Sıfırla", key="btn_sifirla", type="secondary"):
                    df["Ekip"] = "Atanmamış"
                    st.session_state.df = df
                    st.session_state.son_cizim = None
                    st.rerun()

            with col_r2:
                sifirla_cols = st.columns([1, 1])
                with sifirla_cols[0]:
                    sifirla_ekip = st.selectbox("Ekip seçin", ekip_secenekleri, key="sifirla_ekip")
                with sifirla_cols[1]:
                    st.write("")
                    st.write("")
                    if st.button(f"🔄 {sifirla_ekip} Atamasını Sıfırla", key="btn_ekip_sifirla"):
                        df.loc[df["Ekip"] == sifirla_ekip, "Ekip"] = "Atanmamış"
                        st.session_state.df = df
                        st.rerun()

            st.divider()

            # --- ATANMIŞ İŞLER TABLOSU ---
            st.subheader("📋 Atanmış İşler Tablosu")
            atanmis_df = df[df["Ekip"] != "Atanmamış"]

            if not atanmis_df.empty:
                # Rotalama verileri hesapla
                tum_rotalama_verileri = []
                if _is_sureleri is not None:
                    for ekip_adi in sorted(atanmis_df["Ekip"].unique()):
                        rota_sonuc = ekip_rotalama_hesapla(df, ekip_adi, _is_sureleri, _km_sureleri, _isletme_koordinatlari)
                        if rota_sonuc is not None:
                            _, sonuclar, _, _, _ = rota_sonuc
                            tum_rotalama_verileri.extend(sonuclar)
        
                tablo = tablo_sutunlari_hazirla(atanmis_df, tum_rotalama_verileri if tum_rotalama_verileri else None)
        
                if tum_rotalama_verileri and "Sıra" in tablo.columns:
                    tablo = tablo.sort_values(["Atandığı Ekip", "Sıra"]).reset_index(drop=True)
        
                tablo = sira_duzelt(tablo)
                st.dataframe(tablo, width='stretch', hide_index=True)
            else:
                st.info("Henüz ekiplere atanmış iş yok.")

            st.divider()

            # --- EXCEL EXPORT ---
            st.subheader("📥 Excel'e Aktar")
            atanmis_df = df[df["Ekip"] != "Atanmamış"]

            if not atanmis_df.empty:
                zaman = datetime.now().strftime("%Y%m%d_%H%M%S")
                dosya_adi = f"İşler_{zaman}.xlsx"
                excel_data = excel_export(df, _is_sureleri, _km_sureleri, _isletme_koordinatlari)
                if excel_data:
                    st.download_button(
                        label="📥 Excel'e Aktar (İndir)", data=excel_data,
                        file_name=dosya_adi,
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        type="primary", key="btn_export"
                    )
                else:
                    st.error("❌ Excel dosyası hazırlanamadı.")
            else:
                st.warning("⚠️ Henüz ekiplere atanmış iş yok. Atama yapıldıktan sonra Excel indirilebilir.")


        # ============================================================
        # SONUÇ ANALİZİ SEKMESİ
        # ============================================================
if tab_analiz is not None:
    with tab_analiz:
        st.header("📊 MTH İşleri Sonuç Analizi")
        
        df_base = st.session_state.get("df_fen_base")
        df_names = st.session_state.get("df_names_data")
        
        if df_base is not None and not df_base.empty:
            for col in df_base.columns:
                if df_base[col].dtype == "object":
                    df_base[col] = df_base[col].apply(clean_text_for_json)
        
        if df_base is None or df_base.empty:
            st.info("💡 Analiz yapabilmek için sol panelden **Fen İşleri Aktivite Raporu** (ve opsiyonel Kontak Raporu) yükleyin.")
        else:
            # --- FİLTRELER ---
            min_tarih = df_base["Tarih_Saat_DT"].min().date()
            max_tarih = df_base["Tarih_Saat_DT"].max().date()
            default_start = max(min_tarih, max_tarih - timedelta(days=7))
            
            f_col1, f_col2 = st.columns([2, 1])
            with f_col1:
                tarih_araligi = st.date_input(
                    "📅 Tarih Aralığı Seçin",
                    value=[default_start, max_tarih],
                    min_value=min_tarih,
                    max_value=max_tarih,
                    key="analiz_tarih_input"
                )
            with f_col2:
                bolgeler = sorted([str(b) for b in df_base["BÖLGE"].dropna().unique() if str(b) != "Bilinmiyor"])
                secilen_bolge = st.selectbox(
                    "🌍 Bölge Seçin",
                    ["Tümü"] + bolgeler,
                    key="analiz_bolge_select"
                )
            
            if isinstance(tarih_araligi, (tuple, list)) and len(tarih_araligi) == 2:
                baslangic, bitis = tarih_araligi[0], tarih_araligi[1]
            else:
                baslangic, bitis = min_tarih, max_tarih
            
            # --- RAPOR HESAPLAMA ---
            filtreli_rapor, b_filtreli_rapor = compute_sonuc_rapor(df_base, df_names, baslangic, bitis)
            
            if filtreli_rapor.empty:
                st.warning("⚠️ Seçilen tarih ve bölge filtrelerine uygun veri bulunamadı.")
            else:
                # Bölge filtresi uygula
                filtreli_rapor_filtreli = filtreli_rapor[filtreli_rapor["Gün Sayısı"] > 0].copy()
                if secilen_bolge != "Tümü" and "BÖLGE" in filtreli_rapor_filtreli.columns:
                    filtreli_rapor_filtreli = filtreli_rapor_filtreli[filtreli_rapor_filtreli["BÖLGE"] == secilen_bolge]
                
                # Önceki Dönem Hesaplama (Kıyaslama için)
                delta_days = (bitis - baslangic).days + 1
                prev_baslangic = baslangic - timedelta(days=delta_days)
                prev_bitis = bitis - timedelta(days=delta_days)
                prev_filtreli_rapor, prev_b_filtreli_rapor = compute_sonuc_rapor(df_base, df_names, prev_baslangic, prev_bitis)
                
                prev_filtreli_rapor_filtreli = pd.DataFrame()
                if not prev_filtreli_rapor.empty:
                    prev_filtreli_rapor_filtreli = prev_filtreli_rapor[prev_filtreli_rapor["Gün Sayısı"] > 0].copy()
                    if secilen_bolge != "Tümü" and "BÖLGE" in prev_filtreli_rapor_filtreli.columns:
                        prev_filtreli_rapor_filtreli = prev_filtreli_rapor_filtreli[prev_filtreli_rapor_filtreli["BÖLGE"] == secilen_bolge]
                
                # --- METRİK DEĞERLERİ & DELTALAR ---
                ort_skor = safe_numeric_mean(filtreli_rapor_filtreli, "Genel_Skor")
                aktif_personel = int(filtreli_rapor_filtreli["Personel"].nunique()) if "Personel" in filtreli_rapor_filtreli.columns else 0
                ort_kofra = safe_numeric_mean(filtreli_rapor_filtreli, "Ort. Kofra")
                ort_is = safe_numeric_mean(filtreli_rapor_filtreli, "Ort. İş")
                ort_sure_dk = safe_numeric_mean(filtreli_rapor_filtreli, "Ort. Süre (Dk)")
                ort_is_arasi = safe_numeric_mean(filtreli_rapor_filtreli, "Ort. İş Arası Süre")
                ort_ilk_sn = safe_numeric_mean(filtreli_rapor_filtreli, "ilk_sn")
                ort_son_sn = safe_numeric_mean(filtreli_rapor_filtreli, "son_sn")
                ort_ilk_kontak_sn = safe_numeric_mean(filtreli_rapor_filtreli, "ilk_kontak_sn")
                ort_son_kontak_sn = safe_numeric_mean(filtreli_rapor_filtreli, "son_kontak_sn")
                
                prev_ort_skor = safe_numeric_mean(prev_filtreli_rapor_filtreli, "Genel_Skor")
                prev_aktif_personel = int(prev_filtreli_rapor_filtreli["Personel"].nunique()) if not prev_filtreli_rapor_filtreli.empty and "Personel" in prev_filtreli_rapor_filtreli.columns else 0
                prev_ort_kofra = safe_numeric_mean(prev_filtreli_rapor_filtreli, "Ort. Kofra")
                prev_ort_is = safe_numeric_mean(prev_filtreli_rapor_filtreli, "Ort. İş")
                prev_ort_sure_dk = safe_numeric_mean(prev_filtreli_rapor_filtreli, "Ort. Süre (Dk)")
                prev_ort_is_arasi = safe_numeric_mean(prev_filtreli_rapor_filtreli, "Ort. İş Arası Süre")
                prev_ort_ilk_sn = safe_numeric_mean(prev_filtreli_rapor_filtreli, "ilk_sn")
                prev_ort_son_sn = safe_numeric_mean(prev_filtreli_rapor_filtreli, "son_sn")
                prev_ort_ilk_kontak_sn = safe_numeric_mean(prev_filtreli_rapor_filtreli, "ilk_kontak_sn")
                prev_ort_son_kontak_sn = safe_numeric_mean(prev_filtreli_rapor_filtreli, "son_kontak_sn")

                if secilen_bolge == "Tümü" and not b_filtreli_rapor.empty:
                    match_genel = b_filtreli_rapor[b_filtreli_rapor["BÖLGE"] == "Genel Şirket Ortalaması"]
                    if not match_genel.empty:
                        grow = match_genel.iloc[0]
                        ort_skor = grow.get("Genel_Skor", ort_skor)
                        ort_kofra = grow.get("Ort. Kofra", ort_kofra)
                        ort_is = grow.get("Ort. İş", ort_is)
                        ort_sure_dk = grow.get("Ort. Süre (Dk)", ort_sure_dk)
                        ort_is_arasi = grow.get("Ort. İş Arası Süre", ort_is_arasi)
                        ort_ilk_sn = grow.get("ilk_sn", ort_ilk_sn)
                        ort_son_sn = grow.get("son_sn", ort_son_sn)
                        ort_ilk_kontak_sn = grow.get("ilk_kontak_sn", ort_ilk_kontak_sn)
                        ort_son_kontak_sn = grow.get("son_kontak_sn", ort_son_kontak_sn)

                def calc_delta(curr, prev):
                    if prev is None or pd.isna(prev) or prev == 0:
                        return ""
                    if curr is None or pd.isna(curr):
                        return ""
                    diff = ((curr - prev) / abs(prev)) * 100
                    if abs(diff) < 0.1:
                        return "%0"
                    sign = "+" if diff > 0 else ""
                    return f"{sign}{diff:.1f}%"

                d_ort_skor = calc_delta(ort_skor, prev_ort_skor)
                d_aktif_personel = calc_delta(aktif_personel, prev_aktif_personel)
                d_ort_kofra = calc_delta(ort_kofra, prev_ort_kofra)
                d_ort_is = calc_delta(ort_is, prev_ort_is)
                d_ort_sure_dk = calc_delta(ort_sure_dk, prev_ort_sure_dk)
                d_is_arasi = calc_delta(ort_is_arasi, prev_ort_is_arasi)
                d_ort_ilk_is = calc_delta(ort_ilk_sn, prev_ort_ilk_sn)
                d_ort_son_is = calc_delta(ort_son_sn, prev_ort_son_sn)
                d_ort_ilk_kontak = calc_delta(ort_ilk_kontak_sn, prev_ort_ilk_kontak_sn)
                d_ort_son_kontak = calc_delta(ort_son_kontak_sn, prev_ort_son_kontak_sn)

                # --- 1. ÖZET (KİYASLAMALI METRİK KARTLARI) ---
                st.subheader("🧾 ÖZET")
                st.markdown(f"<div style='color: #0c4a6e; font-size: 16px; font-weight: 700; margin-bottom: 10px;'>Kıyaslanan Önceki Dönem: <b>{prev_baslangic.strftime('%d.%m.%Y')} - {prev_bitis.strftime('%d.%m.%Y')}</b></div>", unsafe_allow_html=True)
                st.write("")

                def my_metric(label, curr_str, prev_str, delta_pct_str, is_reverse=False, help_text=None):
                    if delta_pct_str:
                        if delta_pct_str.startswith("+"):
                            color = "#ef4444" if is_reverse else "#09ab3b"
                            arrow = "↑"
                        elif delta_pct_str.startswith("-"):
                            color = "#09ab3b" if is_reverse else "#ef4444"
                            arrow = "↓"
                        else:
                            color = "#64748b"
                            arrow = ""
                        prev_html = f"<div style='color:{color}; font-size:15px; font-weight:700; margin-top:4px;'>Önceki: {prev_str} ({arrow} {delta_pct_str})</div>"
                    else:
                        prev_html = "<div style='font-size:15px; margin-top:4px; opacity:0;'>&nbsp;</div>"
                    
                    tooltip_title = f"title='{help_text}'" if help_text else ""
                    st.markdown(f"""
                    <div style='background-color: #f0f9ff; border: 1.5px solid #bae6fd; border-radius: 12px; padding: 12px 8px; text-align: center; box-shadow: 0 2px 5px rgba(3, 105, 161, 0.08); margin-bottom: 6px;' {tooltip_title}>
                        <div style='font-size: 13px; color: #0369a1; font-weight: 700; margin-bottom: 3px;'>{label}</div>
                        <div style='font-size: 24px; color: #0c4a6e; font-weight: 900; line-height: 1.2;'>{curr_str}</div>
                        {prev_html}
                    </div>
                    """, unsafe_allow_html=True)

                mcol1, mcol2, mcol3, mcol4, mcol5 = st.columns(5)
                with mcol1:
                    my_metric("Ort. Puan", format_tr_number(ort_skor, 1), format_tr_number(prev_ort_skor, 1), d_ort_skor, help_text="Personellerin 50 Tarama + 50 Tempo performans puanı ortalamasıdır.")
                with mcol2:
                    my_metric("Aktif Personel", str(aktif_personel), str(prev_aktif_personel), d_aktif_personel, help_text="Sahada aktif çalışan personel sayısıdır.")
                with mcol3:
                    my_metric("Ort. Kofra", format_tr_number(ort_kofra, 1, True), format_tr_number(prev_ort_kofra, 1, True), d_ort_kofra, help_text="Günlük ortalama ziyaret edilen kofra sayısıdır.")
                with mcol4:
                    my_metric("Ort. İş", format_tr_number(ort_is, 1, True), format_tr_number(prev_ort_is, 1, True), d_ort_is, help_text="Günlük ortalama tamamlanan iş sayısıdır.")
                with mcol5:
                    my_metric("Ort. Süre", f"{format_tr_number(ort_sure_dk, 1, True)} Dk", f"{format_tr_number(prev_ort_sure_dk, 1, True)} Dk", d_ort_sure_dk, help_text="İlk iş ile son iş arasında geçen ortalama süredir.")

                st.write("")
                mcol6, mcol7, mcol8, mcol9, mcol10 = st.columns(5)
                with mcol6:
                    my_metric("Ort. İş Arası", f"{format_tr_number(ort_is_arasi, 1, True)} Dk", f"{format_tr_number(prev_ort_is_arasi, 1, True)} Dk", d_is_arasi, is_reverse=True, help_text="İşler arasında geçirilen ortalama süredir.")
                with mcol7:
                    my_metric("Ort. İlk İş", saniye_formatla(ort_ilk_sn), saniye_formatla(prev_ort_ilk_sn), d_ort_ilk_is, is_reverse=True, help_text="İlk iş başlama saatidir.")
                with mcol8:
                    my_metric("Ort. İlk Kontak", saniye_to_saat(ort_ilk_kontak_sn), saniye_to_saat(prev_ort_ilk_kontak_sn), d_ort_ilk_kontak, is_reverse=True, help_text="İlk araç kontak saatidir.")
                with mcol9:
                    my_metric("Ort. Son İş", saniye_formatla(ort_son_sn), saniye_formatla(prev_ort_son_sn), d_ort_son_is, help_text="Son iş bitirme saatidir.")
                with mcol10:
                    my_metric("Ort. Son Kontak", saniye_to_saat(ort_son_kontak_sn), saniye_to_saat(prev_ort_son_kontak_sn), d_ort_son_kontak, help_text="Son araç kontak saatidir.")

                # --- 2. BÖLGE BAZLI PERFORMANS ÖZETİ ---
                st.markdown("---")
                st.subheader("🌍 Bölge Bazlı Performans Özeti")
                
                if not b_filtreli_rapor.empty:
                    b_show = b_filtreli_rapor.rename(columns={"Genel_Skor": "Skor"})
                    b_cols = [
                        "BÖLGE", "Skor", "Ort. Kofra", "Ort. İş", "Toplam Kofra", "Toplam İş",
                        "Ort. Mesafe", "Ort. İlk İş", "İlk Kontak (Ort.)", "Ort. Son İş", "Son Kontak (Ort.)",
                        "Ort. Süre (Dk)", "Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun"
                    ]
                    b_cols_exist = [c for c in b_show.columns if c in b_cols]
                    b_display = b_show[b_cols_exist].copy()
                    
                    for c in ["Toplam Kofra", "Toplam İş"]:
                        if c in b_display.columns:
                            b_display[c] = b_display[c].apply(lambda x: format_tr_number(x, 0) if pd.notna(x) else "0")
                    for c in ["Skor", "Ort. Kofra", "Ort. İş", "Ort. Mesafe", "Ort. Süre (Dk)"]:
                        if c in b_display.columns:
                            b_display[c] = b_display[c].apply(lambda x: format_tr_number(x, 1) if pd.notna(x) else "0")
                    for c in ["Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun"]:
                        if c in b_display.columns:
                            b_display[c] = b_display[c].apply(lambda x: format_tr_number(x, 1 if pd.notna(x) and float(x) % 1 != 0 else 0) if pd.notna(x) else "0")
                    
                    st.dataframe(b_display, use_container_width=True, hide_index=True)

                # --- 3. SAHA İŞ NOKTALARI HARİTASI ---
                st.markdown("---")
                st.subheader("🗺️ Saha İş Noktaları Haritası")
                
                mask_harita = (df_base["Tarih_Saat_DT"].dt.date >= baslangic) & (
                    df_base["Tarih_Saat_DT"].dt.date <= bitis
                )
                df_harita_base = df_base[mask_harita].copy()
                if secilen_bolge != "Tümü":
                    df_harita_base = df_harita_base[df_harita_base["BÖLGE"].astype(str).str.strip() == str(secilen_bolge).strip()]

                # Merge ADI SOYADI into df_harita_base if not present
                if "ADI SOYADI" not in df_harita_base.columns and not filtreli_rapor_filtreli.empty and "ADI SOYADI" in filtreli_rapor_filtreli.columns:
                    name_map = filtreli_rapor_filtreli[["Personel", "ADI SOYADI"]].drop_duplicates(subset=["Personel"])
                    df_harita_base = df_harita_base.merge(name_map, on="Personel", how="left")

                map_valid_df = df_harita_base.dropna(subset=["LAT", "LON"]).copy()

                for col in map_valid_df.columns:
                    if map_valid_df[col].dtype == "object":
                        map_valid_df[col] = map_valid_df[col].apply(clean_text_for_json)

                if map_valid_df.empty:
                    st.info(f"Haritada gösterilecek koordinat verisi bulunamadı ({secilen_bolge} / {baslangic.strftime('%d.%m.%Y')} - {bitis.strftime('%d.%m.%Y')}).")
                else:
                    # Format options: "Bölge - Personel Kodu - Tüm İsimler"
                    ekip_labels = {}
                    for p_code, grp in map_valid_df.groupby("Ekip"):
                        bolge_val = clean_text_for_json(grp["BÖLGE"].iloc[0]) if "BÖLGE" in grp.columns and pd.notna(grp["BÖLGE"].iloc[0]) else "Bilinmiyor"
                        
                        names_list = []
                        if "ADI SOYADI" in grp.columns:
                            names_list = [clean_text_for_json(n).strip() for n in grp["ADI SOYADI"].dropna().unique() if clean_text_for_json(n).strip() != ""]
                        elif "Personel" in grp.columns:
                            names_list = [clean_text_for_json(n).strip() for n in grp["Personel"].dropna().unique() if clean_text_for_json(n).strip() != ""]
                        
                        if names_list:
                            isim_val = ", ".join(names_list)
                        else:
                            isim_val = str(p_code)
                            
                        label = f"{bolge_val} - {p_code} - {isim_val}"
                        ekip_labels[label] = p_code

                    sorted_labels = sorted(ekip_labels.keys())
                    ekip_options = ["Tümü"] + sorted_labels
                    map_team_key = f"sonuc_map_team_{secilen_bolge}_{baslangic}_{bitis}"
                    selected_team_label = st.selectbox("🚗 Ekip Seç (Bölge - Kod - İsim)", ekip_options, key=map_team_key)
                    
                    if selected_team_label != "Tümü":
                        selected_pcode = ekip_labels.get(selected_team_label)
                        if selected_pcode:
                            map_valid_df = map_valid_df[map_valid_df["Ekip"] == selected_pcode]
                    else:
                        if len(map_valid_df) > 1500:
                            map_valid_df = map_valid_df.sample(1500, random_state=42)

                    if map_valid_df.empty:
                        st.warning("Seçilen ekip için koordinat verisi bulunamadı.")
                    else:
                        map_valid_df["Çizelgeleme Tarihi TR"] = map_valid_df["Tarih_Saat_DT"].dt.strftime("%d.%m.%Y")
                        map_valid_df["Çizelgeleme Saati"] = map_valid_df["Tarih_Saat_DT"].dt.strftime("%H:%M:%S")

                        def get_vibrant_color(i):
                            hue = (i * 0.618033988749895) % 1.0
                            r, g, b = colorsys.hsv_to_rgb(hue, 0.85, 0.9)
                            return f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"

                        unique_teams = sorted(map_valid_df["Ekip"].unique())
                        color_map = {ekip: get_vibrant_color(i) for i, ekip in enumerate(unique_teams)}

                        center_lat = map_valid_df["LAT"].mean()
                        center_lon = map_valid_df["LON"].mean()

                        m_sonuc = folium.Map(location=[center_lat, center_lon], zoom_start=10, tiles="OpenStreetMap")

                        if "ADI SOYADI" in map_valid_df.columns:
                            p_name = map_valid_df["ADI SOYADI"].fillna(map_valid_df.get("Personel", map_valid_df["Ekip"])).astype(str)
                        elif "Personel" in map_valid_df.columns:
                            p_name = map_valid_df["Personel"].fillna(map_valid_df["Ekip"]).astype(str)
                        else:
                            p_name = map_valid_df["Ekip"].astype(str)

                        renk_series = map_valid_df["Ekip"].map(color_map).fillna("#1e88e5")

                        ekip_str = map_valid_df["Ekip"].fillna("").astype(str)
                        bolge_str = map_valid_df["BÖLGE"].fillna("").astype(str) if "BÖLGE" in map_valid_df.columns else ""
                        tarih_str = map_valid_df["Çizelgeleme Tarihi TR"].fillna("").astype(str) if "Çizelgeleme Tarihi TR" in map_valid_df.columns else ""
                        saat_str = map_valid_df["Çizelgeleme Saati"].fillna("").astype(str) if "Çizelgeleme Saati" in map_valid_df.columns else ""
                        kofra_str = map_valid_df["Kofra"].fillna("").astype(str) if "Kofra" in map_valid_df.columns else ""
                        aktivite_str = map_valid_df["Aktivite Tipi"].fillna("").astype(str) if "Aktivite Tipi" in map_valid_df.columns else ""
                        adres_str = map_valid_df["Adres"].fillna("").astype(str) if "Adres" in map_valid_df.columns else ""

                        popup_series = (
                            "<div style='font-family: Arial, sans-serif; font-size: 12px; min-width: 220px; line-height: 1.5; color: #0f172a;'>"
                            "<div style='background-color: " + renk_series + "; color: #ffffff; padding: 4px 8px; border-radius: 4px; font-weight: bold; margin-bottom: 6px;'>"
                            "📍 SAHA İŞ NOKTASI DETAYI</div>"
                            "<b>Ekip / Kod:</b> " + ekip_str + "<br>"
                            "<b>Personel (Ad Soyad):</b> " + p_name + "<br>"
                            "<b>Bölge:</b> " + bolge_str + "<br>"
                            "<b>Tarih:</b> " + tarih_str + "<br>"
                            "<b>Saat:</b> " + saat_str + "<br>"
                            "<b>Kofra / Hizmet No:</b> " + kofra_str + "<br>"
                            "<b>Aktivite Tipi:</b> " + aktivite_str + "<br>"
                            "<b>Adres:</b> " + adres_str + "</div>"
                        )

                        tooltip_series = ekip_str + " | " + p_name + " | Kofra: " + kofra_str

                        map_valid_df["popup_series"] = popup_series
                        map_valid_df["tooltip_series"] = tooltip_series

                        cluster_data = list(zip(
                            map_valid_df["LAT"],
                            map_valid_df["LON"],
                            renk_series,
                            map_valid_df["popup_series"],
                            map_valid_df["tooltip_series"]
                        ))

                        callback = """
                        function (row) {
                            var marker = L.circleMarker(new L.LatLng(row[0], row[1]), {color: row[2], fill: true, fillColor: row[2], fillOpacity: 0.85, radius: 8});
                            var popup = L.popup({maxWidth: 300}).setContent(row[3]);
                            marker.bindPopup(popup);
                            marker.bindTooltip(row[4]);
                            return marker;
                        };
                        """

                        plugins.FastMarkerCluster(
                            cluster_data,
                            callback=callback,
                            options={"disableClusteringAtZoom": 1, "maxClusterRadius": 1}
                        ).add_to(m_sonuc)

                        # Rota Çizgileri & İlk/Son İş Noktaları (Tekil veya tüm ekipler için)
                        for p_code, grp in map_valid_df.groupby("Ekip"):
                            renk = color_map.get(p_code, "#1e88e5")

                            # Rota Çizgisi (Belirli Ekip seçilmişse)
                            if selected_team_label != "Tümü" and len(grp) >= 2:
                                grp_sorted = grp.sort_values("Tarih_Saat_DT")
                                points = grp_sorted[["LAT", "LON"]].values.tolist()
                                folium.PolyLine(
                                    points,
                                    color=renk,
                                    weight=3.5,
                                    opacity=0.75,
                                    tooltip=f"Ekip Rota: {p_code}"
                                ).add_to(m_sonuc)

                            # İlk ve Son İş İşaretleri (İçte Beyaz / Siyah Küçük Nokta)
                            grp_rota = grp.drop_duplicates(subset=["Ekip_Gun", "Tarih_Saat_DT", "LAT", "LON"]).copy()
                            if len(grp_rota) >= 1:
                                grp_rota = grp_rota.sort_values(["Ekip_Gun", "Tarih_Saat_DT"])
                                grp_rota["rota_sirasi"] = grp_rota.groupby("Ekip_Gun").cumcount()
                                grp_rota["rota_toplam"] = grp_rota.groupby("Ekip_Gun")["Tarih_Saat_DT"].transform("count")
                                
                                ilk_points = grp_rota[grp_rota["rota_sirasi"] == 0]
                                son_points = grp_rota[(grp_rota["rota_sirasi"] == (grp_rota["rota_toplam"] - 1)) & (grp_rota["rota_toplam"] > 1)]

                                for _, r_ilk in ilk_points.iterrows():
                                    folium.CircleMarker(
                                        location=[r_ilk["LAT"], r_ilk["LON"]],
                                        radius=3,
                                        color="#ffffff",
                                        fill=True,
                                        fill_color="#ffffff",
                                        fill_opacity=1.0,
                                        popup=folium.Popup(r_ilk["popup_series"], max_width=300),
                                        tooltip=f"İlk İş Noktası (Beyaz) | {r_ilk.get('Ekip', '')}"
                                    ).add_to(m_sonuc)

                                for _, r_son in son_points.iterrows():
                                    folium.CircleMarker(
                                        location=[r_son["LAT"], r_son["LON"]],
                                        radius=3,
                                        color="#000000",
                                        fill=True,
                                        fill_color="#000000",
                                        fill_opacity=1.0,
                                        popup=folium.Popup(r_son["popup_series"], max_width=300),
                                        tooltip=f"Son İş Noktası (Siyah) | {r_son.get('Ekip', '')}"
                                    ).add_to(m_sonuc)

                        st_folium_key = f"sonuc_folium_map_{secilen_bolge}_{baslangic}_{bitis}_{selected_team_label}"
                        st_folium(m_sonuc, width="100%", height=550, key=st_folium_key, returned_objects=[])

                # --- 4. PERSONEL DETAYLI ANALİZ RAPORU ---
                st.markdown("---")
                st.subheader("👤 Personel Detaylı Analiz Raporu")
                
                df_show = filtreli_rapor_filtreli.rename(
                    columns={"Personel": "Kod", "PERSONEL Sicil No": "Sicil", "ADI SOYADI": "İsim", "Genel_Skor": "Skor"}
                )
                
                p_cols = [
                    "Kod", "Sicil", "İsim", "BÖLGE", "Skor", "Gün Sayısı",
                    "Kaçak Kontrol", "At, Sayaç Değiştirme", "Niteliksiz İşler",
                    "Ort. Kofra", "Ort. İş", "Toplam Kofra", "Toplam İş",
                    "Ort. Mesafe", "Toplam Mesafe",
                    "İlk İş (Ort.)", "İlk Kontak (Ort.)", "Son İş (Ort.)", "Son Kontak (Ort.)",
                    "Ort. Süre (Dk)", "Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun",
                    "Ort. İş Arası Süre", "Uzun İş Arası Süre"
                ]
                
                p_cols_exist = [c for c in p_cols if c in df_show.columns]
                df_display = df_show[p_cols_exist].copy()
                
                for c in ["Skor", "Gün Sayısı", "Kaçak Kontrol", "At, Sayaç Değiştirme", "Niteliksiz İşler", "Toplam Kofra", "Toplam İş", "Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun", "Uzun İş Arası Süre"]:
                    if c in df_display.columns:
                        df_display[c] = df_display[c].apply(lambda x: format_tr_number(x, 0) if pd.notna(x) else "0")
                for c in ["Ort. Kofra", "Ort. İş", "Ort. Mesafe", "Toplam Mesafe", "Ort. Süre (Dk)", "Ort. İş Arası Süre"]:
                    if c in df_display.columns:
                        df_display[c] = df_display[c].apply(lambda x: format_tr_number(x, 1) if pd.notna(x) else "0")
                
                st.dataframe(df_display, use_container_width=True, hide_index=True)
                
                # KPİ SEÇİMİ & GRAFİKLER
                st.markdown("---")
                kpi_mapping = {
                    "Genel Skor": "Genel_Skor",
                    "Ort. Kofra": "Ort. Kofra",
                    "Ort. İş": "Ort. İş",
                    "Ort. Süre (Dk)": "Ort. Süre (Dk)",
                    "Ort. İş Arası Süre": "Ort. İş Arası Süre",
                    "İlk İş": "ilk_sn",
                    "Son İş": "son_sn",
                    "İlk Kontak": "ilk_kontak_sn",
                    "Son Kontak": "son_kontak_sn",
                    "Ort. Mesafe": "Ort. Mesafe",
                    "Uzun Öğle Arası Sayısı": "Uzun Öğle",
                    "İlk İş Uzun Sayısı": "İlk İş Uzun",
                    "Son İş-Önceki İş Uzun Sayısı": "Son-Önceki İş Uzun"
                }
                
                selected_kpi_name = st.selectbox("📊 Analiz Edilecek KPI Seçin", list(kpi_mapping.keys()), index=0)
                selected_kpi = kpi_mapping[selected_kpi_name]

                # Şirket Ortalamasını Hesapla (Grafiklerde turuncu kesikli çizgi için)
                genel_kpi_val = None
                if not b_filtreli_rapor.empty and selected_kpi in b_filtreli_rapor.columns:
                    genel_row = b_filtreli_rapor[b_filtreli_rapor["BÖLGE"] == "Genel Şirket Ortalaması"]
                    if not genel_row.empty:
                        try:
                            genel_kpi_val = float(genel_row[selected_kpi].iloc[0])
                        except:
                            genel_kpi_val = None
                
                if genel_kpi_val is not None and pd.notna(genel_kpi_val) and genel_kpi_val > 0:
                    if selected_kpi in ["ilk_sn", "son_sn"]:
                        genel_kpi_str = saniye_formatla(genel_kpi_val)
                    elif selected_kpi in ["ilk_kontak_sn", "son_kontak_sn"]:
                        genel_kpi_str = saniye_to_saat(genel_kpi_val)
                    else:
                        decimals = 0 if "Sayısı" in selected_kpi_name else 1
                        genel_kpi_str = format_tr_number(genel_kpi_val, decimals)
                else:
                    genel_kpi_str = ""

                tab_g1, tab_g2 = st.tabs(["📊 Bölge Analizi", "👤 Personel Analizi"])
                
                with tab_g1:
                    if not b_filtreli_rapor.empty and selected_kpi in b_filtreli_rapor.columns:
                        b_plot_df = b_filtreli_rapor[b_filtreli_rapor["BÖLGE"] != "Genel Şirket Ortalaması"].copy()
                        if not b_plot_df.empty:
                            is_time_kpi = selected_kpi in ["ilk_sn", "son_sn", "ilk_kontak_sn", "son_kontak_sn"]
                            if is_time_kpi:
                                y_text = [saniye_formatla(v) if selected_kpi in ["ilk_sn", "son_sn"] else saniye_to_saat(v) for v in b_plot_df[selected_kpi]]
                                y_num = list(b_plot_df[selected_kpi].fillna(0))
                            else:
                                decimals = 0 if "Sayısı" in selected_kpi_name else 1
                                y_text = [format_tr_number(v, decimals) for v in b_plot_df[selected_kpi]]
                                y_num = list(b_plot_df[selected_kpi].fillna(0))

                            fig_b = go.Figure(
                                go.Bar(
                                    x=b_plot_df["BÖLGE"],
                                    y=y_num,
                                    text=y_text,
                                    textposition="outside",
                                    marker_color="#1e88e5",
                                    textfont=dict(size=16, color="#0f172a", family="Arial Black"),
                                )
                            )
                            # Şirket Ortalaması Çizgisi (Turuncu)
                            if genel_kpi_val is not None and pd.notna(genel_kpi_val) and genel_kpi_val > 0:
                                fig_b.add_hline(
                                    y=genel_kpi_val,
                                    line_dash="dash",
                                    line_color="#f97316",
                                    line_width=3,
                                    annotation_text=f"<b>Şirket Ortalaması: {genel_kpi_str}</b>",
                                    annotation_position="top right",
                                    annotation_font=dict(size=14, color="#c2410c", family="Arial Black")
                                )

                            fig_b.update_layout(
                                title=dict(text=f"Bölge Bazlı {selected_kpi_name}", font=dict(size=18, color="#0f172a", family="Arial Black")),
                                height=490,
                                xaxis_tickangle=-25,
                                xaxis=dict(tickfont=dict(size=14, color="#0f172a", family="Arial Black")),
                                yaxis=dict(tickfont=dict(size=14, color="#0f172a", family="Arial Black")),
                                font=dict(size=14, color="#0f172a")
                            )
                            st.plotly_chart(fig_b, use_container_width=True)
                
                with tab_g2:
                    if not filtreli_rapor_filtreli.empty and selected_kpi in filtreli_rapor_filtreli.columns:
                        df_p = filtreli_rapor_filtreli.copy()
                        time_cols_to_filter = ["ilk_sn", "son_sn", "ilk_kontak_sn", "son_kontak_sn", "Ort. Süre (Dk)", "Ort. İş Arası Süre"]
                        if selected_kpi in time_cols_to_filter:
                            df_p = df_p[df_p[selected_kpi].notna() & (df_p[selected_kpi] > 0)]
                        
                        if not df_p.empty:
                            p_count = len(df_p)
                            if p_count <= 10:
                                g_df = df_p.sort_values(selected_kpi)[["ADI SOYADI", "Personel", "BÖLGE", selected_kpi]].copy()
                                cutoff = p_count // 2
                                g_df["Renk"] = ["#ef4444" if i < cutoff else "#16a34a" for i in range(p_count)]
                            else:
                                top_5 = df_p.nlargest(5, selected_kpi)[["ADI SOYADI", "Personel", "BÖLGE", selected_kpi]].copy()
                                bottom_5 = df_p.nsmallest(5, selected_kpi)[["ADI SOYADI", "Personel", "BÖLGE", selected_kpi]].copy()
                                top_5["Renk"] = "#16a34a"
                                bottom_5["Renk"] = "#ef4444"
                                g_df = pd.concat([bottom_5, top_5]).drop_duplicates().sort_values(selected_kpi).reset_index(drop=True)
                            
                            g_df["İsim"] = g_df["ADI SOYADI"].fillna(g_df["Personel"])
                            g_df["Label"] = g_df.apply(lambda r: f"<b>{r['İsim']} ({r['BÖLGE']})</b>", axis=1)

                            is_time_kpi = selected_kpi in ["ilk_sn", "son_sn", "ilk_kontak_sn", "son_kontak_sn"]
                            if is_time_kpi:
                                y_display = [saniye_formatla(v) if selected_kpi in ["ilk_sn", "son_sn"] else saniye_to_saat(v) for v in g_df[selected_kpi]]
                                y_numeric = list(g_df[selected_kpi].fillna(0))
                            else:
                                decimals = 0 if "Sayısı" in selected_kpi_name else 1
                                y_display = [format_tr_number(v, decimals) if pd.notna(v) else "0" for v in g_df[selected_kpi]]
                                y_numeric = [float(v) if pd.notna(v) else 0 for v in g_df[selected_kpi]]

                            fig_p = go.Figure(
                                go.Bar(
                                    x=g_df["Label"],
                                    y=y_numeric,
                                    text=y_display,
                                    textposition="outside",
                                    marker_color=g_df["Renk"],
                                    textfont=dict(size=16, color="#0f172a", family="Arial Black"),
                                )
                            )
                            # Şirket Ortalaması Çizgisi (Turuncu)
                            if genel_kpi_val is not None and pd.notna(genel_kpi_val) and genel_kpi_val > 0:
                                fig_p.add_hline(
                                    y=genel_kpi_val,
                                    line_dash="dash",
                                    line_color="#f97316",
                                    line_width=3,
                                    annotation_text=f"<b>Şirket Ortalaması: {genel_kpi_str}</b>",
                                    annotation_position="top right",
                                    annotation_font=dict(size=14, color="#c2410c", family="Arial Black")
                                )

                            fig_p.update_layout(
                                title=dict(text=f"En Yüksek 5 ve En Düşük 5 Personel ({selected_kpi_name})", font=dict(size=18, color="#0f172a", family="Arial Black")),
                                height=550,
                                xaxis_tickangle=-30,
                                xaxis=dict(tickfont=dict(size=14, color="#0f172a", family="Arial Black")),
                                yaxis=dict(tickfont=dict(size=14, color="#0f172a", family="Arial Black")),
                                font=dict(size=14, color="#0f172a")
                            )
                            st.plotly_chart(fig_p, use_container_width=True)

                # --- 5. PERSONEL DETAY ANALİZ PANELİ (BOTTOM CARD PANEL) ---
                st.markdown("---")
                st.subheader("👤 Personel Detay Analiz Paneli")

                personel_list_temp = filtreli_rapor_filtreli[["ADI SOYADI", "BÖLGE", "Personel"]].drop_duplicates()
                personel_listesi = sorted(
                    [
                        f"{row['BÖLGE']} - {row['ADI SOYADI']}"
                        for _, row in personel_list_temp.iterrows()
                        if pd.notna(row["ADI SOYADI"]) and pd.notna(row["BÖLGE"])
                    ]
                )
                if personel_listesi:
                    secili_personel_display = st.selectbox("👤 Personel Seç", personel_listesi, index=0, key="sonuc_personel_card_select")
                    secili_personel = secili_personel_display.split(" - ")[1]
                    kart_df = filtreli_rapor_filtreli[
                        filtreli_rapor_filtreli["ADI SOYADI"] == secili_personel
                    ].iloc[0]
                else:
                    secili_personel = ""
                    kart_df = pd.Series(dtype=object)

                if secili_personel and not kart_df.empty:
                    sicil_val = kart_df.get("PERSONEL Sicil No") or kart_df.get("Sicil")
                    sicil = int(sicil_val) if pd.notna(sicil_val) and str(sicil_val).replace(".0","").isdigit() else "-"
                    personel_kodu = kart_df.get("Personel") or kart_df.get("Kod", "-")
                    
                    st.markdown(
                        f"""
                    ### 👤 {kart_df['ADI SOYADI']}
                    🆔 Sicil: {sicil}  
                    🏷️ Kod: {personel_kodu}  
                    📍 Bölge: {kart_df['BÖLGE']}
                    """
                    )

                    # Puanlama
                    tarama_puan = kart_df.get("P_Tarama_Toplam", 0)
                    tempo_puan = kart_df.get("P_Tempo_Toplam", 0)
                    disiplin_ceza = kart_df.get("P_Disiplin_Ceza", 0)
                    toplam_skor = kart_df.get("Genel_Skor", 0)

                    col_card1, col_card2 = st.columns(2)
                    with col_card1:
                        st.markdown("## 🏆 Performans Skoru")
                        st.metric("Genel Skor", int(toplam_skor))
                        if toplam_skor >= 75:
                            st.success("🟢 Yüksek Performans")
                        elif toplam_skor >= 50:
                            st.warning("🟡 Orta Performans")
                        else:
                            st.error("🔴 Düşük Performans")
                    def score_detail_card(label, score_str, pct_str, is_penalty=False):
                        if is_penalty:
                            color = "#ef4444" if int(disiplin_ceza) < 0 else "#64748b"
                            bottom_text = f"<div style='color:{color}; font-size:16px; font-weight:700;'>{pct_str}</div>"
                        else:
                            bottom_text = f"<div style='color:#09ab3b; font-size:16px; font-weight:700;'>{pct_str}</div>"
                        st.markdown(f"""
                        <div style='background-color: #f8fafc; border: 1px solid #cbd5e1; border-radius: 10px; padding: 10px; text-align: center; margin-bottom: 8px;'>
                            <div style='font-size: 13px; color: #475569; font-weight: 600;'>{label}</div>
                            <div style='font-size: 22px; color: #0f172a; font-weight: 800; margin: 3px 0;'>{score_str}</div>
                            {bottom_text}
                        </div>
                        """, unsafe_allow_html=True)

                    with col_card2:
                        st.markdown("### 📊 Puan Detayları")
                        c1, c2, c3 = st.columns(3)
                        with c1:
                            score_detail_card("🔍 Tarama", f"{int(tarama_puan)} / 50", f"%{int((tarama_puan/50)*100)}")
                        with c2:
                            score_detail_card("⚡ Tempo", f"{int(tempo_puan)} / 50", f"%{int((tempo_puan/50)*100)}")
                        with c3:
                            score_detail_card("🧍 Disiplin Ceza", f"{int(disiplin_ceza)}", "Ceza Puanı", is_penalty=True)

                    with st.expander("📝 Puanlama Kırılımı (Nasıl Puan Aldı?)"):
                        gun_say = kart_df.get("Gün Sayısı", 1) or 1
                        nitelikli_is_top = kart_df.get("Kaçak Kontrol", 0) + kart_df.get("At, Sayaç Değiştirme", 0)
                        st.markdown(f"""
                        **🔍 Tarama Puanı ({int(tarama_puan)} / 50)**
                        - Hacim Puanı: {int(kart_df.get("P_Tarama_Hacim", 0))} / 30 *(Ort. Kofra: {kart_df.get("Ort. Kofra", 0)})*
                        - Kalite Puanı: {int(kart_df.get("P_Tarama_Kalite", 0))} / 20 *(Günlük Nitelikli İş: {round(nitelikli_is_top/gun_say, 1)})*
                        
                        **⚡ Tempo Puanı ({int(tempo_puan)} / 50)**
                        - İlk İş Saati: {int(kart_df.get("P_Tempo_IlkIs", 0))} / 12 *(Ort. İlk İş: {saniye_formatla(kart_df.get("ilk_sn", 0))})*
                        - Son İş Saati: {int(kart_df.get("P_Tempo_SonIs", 0))} / 12 *(Ort. Son İş: {saniye_formatla(kart_df.get("son_sn", 0))})*
                        - Çalışma Süresi: {int(kart_df.get("P_Tempo_Sure", 0))} / 13 *(Ort. Süre: {kart_df.get("Ort. Süre (Dk)", 0)} dk)*
                        - İş Arası Süre: {int(kart_df.get("P_Tempo_IsArasi", 0))} / 13 *(Ort. İş Arası: {kart_df.get("Ort. İş Arası Süre", 0)} dk)*
                        
                        **🧍 Disiplin Puanı ({int(disiplin_ceza)} / -10)**
                        - Esneklik Hakkı: {round(kart_df.get("Gün Sayısı", 0) * 0.4, 1)} *(Gün * 0.4)*
                        - İlk İş Uzun Ceza Payı: {int(kart_df.get("C_IlkIs", 0))}
                        - Son/Önceki İş Uzun Ceza Payı: {int(kart_df.get("C_SonIs", 0))}
                        - Uzun Öğle Ceza Payı: {int(kart_df.get("C_Ogle", 0))}
                        - Toplam Ceza: {int(disiplin_ceza)}
                        """)

                    with st.expander("📖 Puanlama Rehberi"):
                        st.markdown('''
                        **1. Tarama Puanı (Max 50 Puan)**
                        - **Hacim Puanı (Max 30):** Personelin günlük baktığı ortalama kofra sayısına göre: ≥ 20 kofra (30p), 18-19.9 (24p), 15-17.9 (18p), 10-14.9 (12p), <10 (5p).
                        - **Kalite Puanı (Max 20):** Personelin günlük yaptığı nitelikli iş (Kaçak Kontrol + Sayaç Değiştirme) sayısına göre: ≥ 20 (20p), 18-19.9 (16p), 15-17.9 (12p), 10-14.9 (7p), <10 (0p)

                        **2. Zaman ve Tempo Puanı (Max 50 Puan)**
                        - **İlk İş Saati (Max 12):** ≤ 08:45 (12p), 08:46-08:55 (9p), 08:56-09:05 (5p), > 09:05 (0p)
                        - **Son İş Saati (Max 12):** ≥ 17:15 (12p), 17:05-17:14 (9p), 16:50-17:04 (5p), < 16:50 (0p)
                        - **Çalışma Süresi (Max 13):** ≥ 480 dk (13p), 460-479 dk (9p), 440-459 dk (5p), < 440 dk (0p)
                        - **Ort. İş Arası Süre (Max 13):** ≤ 25 dk (13p), 26-30 dk (9p), 31-40 dk (5p), > 40 dk (0p)

                        **3. Disiplin (Ceza - Eksi Puan)**
                        - Uzun Öğle, İlk İş Uzun ve Son-Önceki İş Uzun durumları değerlendirilir. Maksimum -10 ceza puanı alınabilir.
                        - **Esneklik (Hak):** Çalışılan Gün × 0.4. Hakkı aşan her ihlal için -2p kesilir.
                        ''')

                    st.markdown("### 📋 Aktivite Özeti")
                    a1, a2, a3 = st.columns(3)
                    a1.metric("🔍 Kaçak Kontrol", int(kart_df.get("Kaçak Kontrol", 0)), help="Nitelikli İş adedi")
                    a2.metric("🔄 At, Sayaç Değiştirme", int(kart_df.get("At, Sayaç Değiştirme", 0)), help="Sayaç/Modem Değiştirme/Takma/Sökme adedi")
                    a3.metric("📝 Diğer / Niteliksiz İşler", int(kart_df.get("Niteliksiz İşler", 0)), help="Mühür Fekki, Okuma vb. iş adedi")

                    st.markdown("### 📈 Günlük Ortalama ve Zaman Yönetimi")
                    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
                    c1.metric("📅 Gün Sayısı", int(kart_df.get("Gün Sayısı", 0)))
                    c2.metric("🔧 Ort. Kofra", kart_df.get("Ort. Kofra", 0))
                    c3.metric("📊 Ort. İş", kart_df.get("Ort. İş", 0))
                    c4.metric("⏱️ Çalışma Süresi (dk)", int(kart_df.get("Ort. Süre (Dk)", 0)))
                    c5.metric("🥱 Uzun Öğle", int(kart_df.get("Uzun Öğle", 0)))
                    c6.metric("🐢 İlk İş Uzun", int(kart_df.get("İlk İş Uzun", 0)))
                    c7.metric("🐌 Son-Önceki İş Uzun", int(kart_df.get("Son-Önceki İş Uzun", 0)))

                    st.markdown("### 📍 Mesafe ve Toplam İş Özeti")
                    m1, m2, m3, m4 = st.columns(4)
                    m1.metric("📏 Ort. Mesafe (m)", format_tr_number(kart_df.get("Ort. Mesafe", 0), 1))
                    m2.metric("📍 Toplam Mesafe (km)", format_tr_number(kart_df.get("Toplam Mesafe", 0) / 1000, 1))
                    m3.metric("📦 Toplam Kofra", format_tr_number(kart_df.get("Toplam Kofra", 0), 0))
                    m4.metric("🛠️ Toplam İş", format_tr_number(kart_df.get("Toplam İş", 0), 0))

                    st.markdown("### ⏰ Çalışma Saatleri")
                    h1, h2, h3, h4, h5, h6 = st.columns(6)
                    h1.metric("🕘 İlk İş", saniye_formatla(kart_df.get("ilk_sn", 0)))
                    h2.metric("🔑 İlk Kontak", saniye_to_saat(kart_df.get("ilk_kontak_sn", 0)))
                    h3.metric("🕔 Son İş", saniye_formatla(kart_df.get("son_sn", 0)))
                    h4.metric("🚗 Son Kontak", saniye_to_saat(kart_df.get("son_kontak_sn", 0)))
                    h5.metric("⏱️ Ort. İş Arası Süre (dk)", format_tr_number(kart_df.get("Ort. İş Arası Süre", 0), 1))
                    h6.metric("⏱️ Uzun İş Arası Süre", int(kart_df.get("Uzun İş Arası Süre", 0)))

                # --- 6. RAPOR İNDİRME (EXCEL VE PDF BÜLTEN) ---
                st.markdown("---")
                st.subheader("📄 Rapor İndirme")
                
                col_dl1, col_dl2 = st.columns(2)
                with col_dl1:
                    excel_out = export_sonuc_excel(filtreli_rapor_filtreli, b_filtreli_rapor)
                    excel_bytes = excel_out.getvalue()
                    
                    st.download_button(
                        label="📥 Excel Raporu İndir (.xlsx)",
                        data=excel_bytes,
                        file_name=f"MTH_Sonuc_Analiz_{secilen_bolge}_{baslangic.strftime('%Y%m%d')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                    
                with col_dl2:
                    if st.button("📄 MTH Bülteni PDF İndir", type="primary", use_container_width=True):
                        with st.spinner("PDF bülteni hazırlanıyor..."):
                            metrics_dict = {
                                "Aktif Personel": (str(aktif_personel), d_aktif_personel),
                                "Ort. Puan": (format_tr_number(ort_skor, 1), d_ort_skor),
                                "Ort. Kofra": (format_tr_number(ort_kofra, 1, True), d_ort_kofra),
                                "Ort. İş": (format_tr_number(ort_is, 1, True), d_ort_is),
                                "Ort. Süre (Dk)": (f"{format_tr_number(ort_sure_dk, 1, True)}", d_ort_sure_dk),
                                "Ort. İlk İş": (saniye_formatla(ort_ilk_sn), d_ort_ilk_is),
                                "Ort. Son İş": (saniye_formatla(ort_son_sn), d_ort_son_is),
                                "Ort. İlk Kontak": (saniye_to_saat(ort_ilk_kontak_sn), d_ort_ilk_kontak),
                                "Ort. Son Kontak": (saniye_to_saat(ort_son_kontak_sn), d_ort_son_kontak),
                                "Ort. Mesafe": (f"{format_tr_number(safe_numeric_mean(filtreli_rapor_filtreli, 'Ort. Mesafe'), 1)} m", None),
                                "Ort. İş Arası Süre": (format_tr_number(ort_is_arasi, 1), d_is_arasi)
                            }
                            
                            pdf_buf = generate_pdf_bulletin(
                                filtreli_rapor_filtreli=filtreli_rapor_filtreli,
                                b_filtreli_rapor=b_filtreli_rapor,
                                df_base=df_base,
                                baslangic=baslangic,
                                bitis=bitis,
                                secilen_bolge=secilen_bolge,
                                metrics_dict=metrics_dict,
                                all_kpis=kpi_mapping,
                                heat_data=map_valid_df[["LAT", "LON", "BÖLGE"]] if not map_valid_df.empty else None,
                                cover_image_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), "cover.png"),
                                prev_baslangic=prev_baslangic,
                                prev_bitis=prev_bitis
                            )
                            
                            st.download_button(
                                label="⬇️ PDF Bültenini Bilgisayara İndir",
                                data=pdf_buf.getvalue(),
                                file_name=f"MTH_Bulteni_{secilen_bolge}_{baslangic.strftime('%Y%m%d')}.pdf",
                                mime="application/pdf",
                                use_container_width=True
                            )
                            st.success("✅ MTH Bülteni başarıyla oluşturuldu!")


# --- ALT BİLGİ ---
st.markdown("---")
st.caption("🔧 Ekip İş Planlama Dashboard | MTH")

