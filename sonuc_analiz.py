"""
Sonuç Analizi Modülü - MTH Fen İşleri Performans Analizi
"""

import pandas as pd
import numpy as np
import datetime
import re
import unicodedata
import os
import glob
from functools import lru_cache


# ======================================================
# BÖLGE EŞLEŞTİRME TABLOSU
# ======================================================

BOLGE_ANAHTAR_KELIMELER = {
    "BURDUR": ["15", "yelov", "golhi", "tefen", "karam"],
    "ISPARTA": ["32", "egird"],
    "ALANYA": ["7.alanya", "7.gazipaşa", "7.gazipasa", "7.gündoğmuş", "7.gundogmus", "gazpa"],
    "BATI": [
        "7.demre", "7.elmalı", "7.elmali", "7.finike", "7.kaş", "7.kas",
        "7.kaş.kalkan", "7.kas.kalkan", "7.kemer", "7.korkuteli", "7.kumluca",
        "demre", "finik", "kakal", "kemer7", "korku", "kumlu"
    ],
    "MANAVGAT": ["7.akseki", "7.ibradı", "7.ibradi", "7.manavgat", "7.serik", "manav"],
    "METROPOL": ["7.aksu", "7.döşemealtı", "7.dosemealti", "7.kepez", "7.konyaaltı", "7.konyaalti", "7.muratpaşa", "7.muratpasa"],
}


@lru_cache(maxsize=4096)
def saniye_formatla(s):
    if pd.isna(s) or s == 0:
        return ""
    total_seconds = int(s)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def saniye_to_saat(value):
    if pd.isna(value) or float(value) == 0:
        return ""
    total_seconds = int(round(float(value)))
    total_seconds %= 24 * 3600
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"


def saat_to_saniye(value):
    if pd.isna(value):
        return np.nan
    if isinstance(value, pd.Timestamp):
        value = value.to_pydatetime()
    if isinstance(value, datetime.datetime):
        return value.hour * 3600 + value.minute * 60 + value.second
    if isinstance(value, datetime.time):
        return value.hour * 3600 + value.minute * 60 + value.second
    return np.nan


def normalize_plaka(p):
    if pd.isna(p):
        return p
    s = str(p).strip().replace("\n", "").replace("\r", "")
    if not s or s.lower() in ["nan", "none", "", "yaya"]:
        return pd.NA
    return re.sub(r"\s+", "", s).upper()


def normalize_column_name(col):
    text = unicodedata.normalize("NFKD", str(col))
    text = text.encode("ascii", "ignore").decode("ascii").lower().strip()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


@lru_cache(maxsize=4096)
def format_tr_number(value, decimals=1, force_decimals=False):
    try:
        val = float(value)
        if force_decimals:
            formatted = f"{val:,.{decimals}f}"
        else:
            if float(val).is_integer():
                formatted = f"{int(val):,}"
            else:
                formatted = f"{val:,.{decimals}f}"
        return formatted.replace(",", "X").replace(".", ",").replace("X", ".")
    except Exception:
        return "0"


def safe_numeric_sum(df, col):
    if col not in df.columns:
        return 0.0
    return pd.to_numeric(df[col], errors="coerce").fillna(0).sum()


def safe_numeric_mean(df, col):
    if col not in df.columns:
        return 0.0
    series = pd.to_numeric(df[col], errors="coerce")
    series = series[(series.notna()) & (series != 0)]
    if series.empty:
        return 0.0
    return series.mean()


def safe_combine(row):
    if pd.isna(row["tarih"]) or pd.isna(row["saat"]):
        return pd.NaT
    return datetime.datetime.combine(row["tarih"], row["saat"])


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlambda = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlambda / 2) ** 2
    return 2 * r * np.arctan2(np.sqrt(a), np.sqrt(1 - a))


def extract_first_coord(value):
    text = str(value).strip().replace("\n", "").replace("\r", "")
    patterns = [
        r"([-+]?[0-9]+(?:[.,][0-9]+)?)\s*,\s*([-+]?[0-9]+(?:[.,][0-9]+)?)",
        r"([-+]?[0-9]+(?:[.,][0-9]+)?)\s*/\s*([-+]?[0-9]+(?:[.,][0-9]+)?)",
        r"([-+]?[0-9]+(?:[.,][0-9]+)?)\s*;\s*([-+]?[0-9]+(?:[.,][0-9]+)?)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            lat = float(match.group(1).replace(",", "."))
            lon = float(match.group(2).replace(",", "."))
            if 35 <= lat <= 43 and 25 <= lon <= 45:
                return lat, lon
            if 35 <= lon <= 43 and 25 <= lat <= 45:
                return lon, lat
    return (np.nan, np.nan)


def operasyon_merkezi_to_bolge(op_merkezi):
    if pd.isna(op_merkezi):
        return "Bilinmiyor"
    text_raw = str(op_merkezi).strip().upper().replace("\n", "").replace("\r", "")
    text_ascii = (
        unicodedata.normalize("NFKD", text_raw)
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
    )
    
    # 1. BURDUR: "15", "YELOV", "GOLHI", "TEFEN", "KARAM"
    if "15" in text_raw or any(k in text_raw or k in text_ascii for k in ["YELOV", "GOLHI", "GÖLHİ", "TEFEN", "KARAM"]):
        return "BURDUR"
        
    # 2. ISPARTA: "32", "EGIRD"
    if "32" in text_raw or any(k in text_raw or k in text_ascii for k in ["EGIRD", "EĞİRD"]):
        return "ISPARTA"
        
    # 3. ALANYA: "7.ALANYA", "7.GAZİPAŞA", "7.GAZIPASA", "7.GÜNDOĞMUŞ", "7.GUNDOGMUS", "GAZPA"
    if any(k in text_raw or k in text_ascii for k in ["7.ALANYA", "7.GAZİPAŞA", "7.GAZIPASA", "7.GÜNDOĞMUŞ", "7.GUNDOGMUS", "GAZPA"]):
        return "ALANYA"
        
    # 4. BATI: "7.DEMRE", "7.ELMALI", "7.FİNİKE", "7.FINIKE", "7.KAŞ", "7.KAS", "7.KAŞ.KALKAN", "7.KAS.KALKAN", "7.KEMER", "7.KORKUTELİ", "7.KORKUTELI", "7.KUMLUCA", "DEMRE", "FINIK", "KAKAL", "KEMER7", "KORKU", "KUMLU"
    if any(k in text_raw or k in text_ascii for k in [
        "7.DEMRE", "7.ELMALI", "7.FİNİKE", "7.FINIKE", "7.KAŞ", "7.KAS", "7.KAŞ.KALKAN", "7.KAS.KALKAN",
        "7.KEMER", "7.KORKUTELİ", "7.KORKUTELI", "7.KUMLUCA", "DEMRE", "FINIK", "KAKAL", "KEMER7", "KORKU", "KUMLU"
    ]):
        return "BATI"
        
    # 5. MANAVGAT: "7.AKSEKİ", "7.AKSEKI", "7.İBRADI", "7.IBRADI", "7.MANAVGAT", "7.SERİK", "7.SERIK", "MANAV"
    if any(k in text_raw or k in text_ascii for k in [
        "7.AKSEKİ", "7.AKSEKI", "7.İBRADI", "7.IBRADI", "7.MANAVGAT", "7.SERİK", "7.SERIK", "MANAV"
    ]):
        return "MANAVGAT"
        
    # 6. METROPOL: "7.AKSU", "7.DÖŞEMEALTI", "7.DOSEMEALTI", "7.KEPEZ", "7.KONYAALTI", "7.MURATPAŞA", "7.MURATPASA"
    if any(k in text_raw or k in text_ascii for k in [
        "7.AKSU", "7.DÖŞEMEALTI", "7.DOSEMEALTI", "7.KEPEZ", "7.KONYAALTI", "7.MURATPAŞA", "7.MURATPASA"
    ]):
        return "METROPOL"

    return "Bilinmiyor"


# ======================================================
# İSİM LİSTESİ OKUMA
# ======================================================

def isim_listesi_oku():
    uygulama_dizini = os.path.dirname(os.path.abspath(__file__))
    isim_dosyalari = []
    if os.path.exists(uygulama_dizini):
        for f in os.listdir(uygulama_dizini):
            if f.endswith(".xlsx") and not f.startswith("~$"):
                fn_norm = f.lower().replace("\u0307", "").replace("ı", "i").replace("i̇", "i")
                if ("isim" in fn_norm and "liste" in fn_norm) or ("personel" in fn_norm and "liste" in fn_norm):
                    isim_dosyalari.append(os.path.join(uygulama_dizini, f))
    
    if isim_dosyalari:
        try:
            df_names = pd.read_excel(isim_dosyalari[0], engine="openpyxl")
            df_names.columns = [str(c).replace("*", "").strip() for c in df_names.columns]
            if "PERSONEL KODU" in df_names.columns:
                df_names["PERSONEL KODU"] = df_names["PERSONEL KODU"].astype(str).str.strip()
            return df_names
        except Exception:
            pass

    # Fallback: Şifreli Python modülünden oku (KVKK Uyumlu - GitHub için)
    try:
        from im_listesi_data import get_decrypted_df
        df_names = get_decrypted_df()
        if df_names is not None and not df_names.empty:
            return df_names
    except Exception:
        pass

    return None


def contains_destek(text):
    if pd.isna(text):
        return False
    t = str(text).replace("İ", "i").replace("I", "ı").lower()
    return "destek" in t


def get_valid_personnel_codes(df_names):
    """
    İsim listesinde bulunan ve 'destek' kelimesini içermeyen personel kodları kümesini döner.
    df_names None ise None döner.
    """
    if df_names is None or "PERSONEL KODU" not in df_names.columns:
        return None
    
    valid_codes = set()
    for _, row in df_names.iterrows():
        p_code = row.get("PERSONEL KODU")
        if pd.isna(p_code):
            continue
        p_code_str = str(p_code).strip()
        if not p_code_str or p_code_str.lower() in ["nan", "none", "<na>"]:
            continue
        
        name_str = str(row.get("ADI SOYADI", "")).strip() if pd.notna(row.get("ADI SOYADI")) else ""
        
        if contains_destek(p_code_str) or contains_destek(name_str):
            continue
        
        valid_codes.add(p_code_str.upper())
        
    return valid_codes



# ======================================================
def kvkk_sutun_kontrol(columns):
    """
    Excel sütunlarında KVKK hassas sütunları (TC, AD, SOYAD, Adres, Adı Soyadı, Ad Soyad, Vergi vb.)
    veya bu kelimeleri içeren sütunlar (örn: Evin Adresi, Tesisat Adresi, Müşteri Adı, T.C. No)
    olup olmadığını kontrol eder. Varsa KVKK uyarı mesajı döner, yoksa None döner.
    """
    YASAKLI_ICERIK = ["adres", "vergi", "soyad", "tckn"]
    YASAKLI_WORDS = ["tc", "ad", "adı", "adi"]
    
    bulunanlar = []
    for col in columns:
        col_str = str(col).strip()
        if not col_str:
            continue
            
        col_lower = col_str.lower().replace("ı", "i")
        col_no_dot = col_lower.replace(".", "")
        tokens_lower = col_no_dot.replace("_", " ").replace("-", " ").replace("/", " ").split()
        
        # 1. İçerik kontrolü (adres, vergi, soyad, tckn geçen sütunlar)
        matched = False
        for key in YASAKLI_ICERIK:
            if key in col_lower:
                if col_str not in bulunanlar:
                    bulunanlar.append(col_str)
                matched = True
                break
        if matched:
            continue
            
        # 2. Kelime token kontrolü (tc, t.c., ad, adı, adi geçen sütunlar)
        for w in YASAKLI_WORDS:
            w_norm = w.replace("ı", "i")
            if w_norm in tokens_lower or col_no_dot == w_norm:
                if col_str not in bulunanlar:
                    bulunanlar.append(col_str)
                break
                
    if bulunanlar:
        sutun_metin = ", ".join(bulunanlar)
        if len(bulunanlar) == 1:
            return f"Bu {sutun_metin} sütununu sil sonra tekrar gönder. (KVKK UYARISI)"
        else:
            return f"Bu {sutun_metin} sütunlarını sil sonra tekrar gönder. (KVKK UYARISI)"
    return None


# ======================================================
# FEN İŞLERİ EXCEL OKUMA (ÇOKLU DOSYA DESTEKLİ)
# ======================================================

def fen_isleri_excel_oku(uploaded_files):
    if uploaded_files is None:
        return None, "⚠️ Lütfen Fen İşleri Aktivite Raporu yükleyin."
    if not isinstance(uploaded_files, list):
        files_to_process = [uploaded_files]
    else:
        files_to_process = uploaded_files
    if not files_to_process:
        return None, "⚠️ Dosya seçilmedi."
    
    df_list = []
    for uploaded_file in files_to_process:
        dosya_adi = uploaded_file.name if hasattr(uploaded_file, 'name') else str(uploaded_file)
        if "fen" not in dosya_adi.lower():
            continue
        try:
            df_raw = pd.read_excel(uploaded_file, engine="openpyxl")
            if not df_raw.empty:
                kvkk_err = kvkk_sutun_kontrol(df_raw.columns)
                if kvkk_err:
                    return None, f"❌ **{kvkk_err}**"
                df_raw.columns = [str(c).strip().replace("\n", "").replace("\r", "") for c in df_raw.columns]
                df_list.append(df_raw)
        except Exception as e:
            return None, f"❌ Excel dosyası okunamadı ({dosya_adi}): {str(e)}"
    
    if not df_list:
        return None, "❌ Yüklenen dosyalarda 'fen' kelimesi bulunamadı veya dosyalar boş!"
    
    df_concat = pd.concat(df_list, ignore_index=True)
    return df_concat, None


# ======================================================
# KONTAK EXCEL OKUMA (ÇOKLU DOSYA DESTEKLİ)
# ======================================================

def kontak_excel_oku(uploaded_files):
    if uploaded_files is None:
        return None, None
    if not isinstance(uploaded_files, list):
        files_to_process = [uploaded_files]
    else:
        files_to_process = uploaded_files
    if not files_to_process:
        return None, None

    kontak_list = []
    for uploaded_file in files_to_process:
        dosya_adi = uploaded_file.name if hasattr(uploaded_file, 'name') else str(uploaded_file)
        if "kontak" not in dosya_adi.lower():
            continue
        try:
            df = pd.read_excel(uploaded_file, skiprows=2, engine="openpyxl")
            if df.empty:
                continue
            kvkk_err = kvkk_sutun_kontrol(df.columns)
            if kvkk_err:
                return None, f"❌ **{kvkk_err}**"
            df.columns = [normalize_column_name(c) for c in df.columns]
            plaka_col = next((c for c in df.columns if c.startswith("plaka")), None)
            if not plaka_col:
                continue
            tarih_cols = [c for c in df.columns if "tarih" in c]
            saat_cols = [c for c in df.columns if "saat" in c]
            if not tarih_cols or not saat_cols:
                continue
            for tarih_col in tarih_cols:
                for saat_col in saat_cols:
                    if tarih_col in df.columns and saat_col in df.columns:
                        temp = df[[plaka_col, tarih_col, saat_col]].copy()
                        temp.columns = ["plaka", "tarih", "saat"]
                        temp["tarih"] = pd.to_datetime(temp["tarih"], dayfirst=True, errors="coerce")
                        temp["saat"] = pd.to_datetime(temp["saat"], format="%H:%M:%S", errors="coerce").dt.time
                        temp = temp.dropna(subset=["plaka", "tarih", "saat"])
                        if not temp.empty:
                            kontak_list.append(temp)
        except Exception as e:
            continue
            
    if not kontak_list:
        return None, "⚠️ Kontak excelinde işlenebilir veri bulunamadı!"
        
    df_kontak = pd.concat(kontak_list, ignore_index=True)
    df_kontak["plaka"] = df_kontak["plaka"].apply(normalize_plaka)
    df_kontak = df_kontak.dropna(subset=["plaka"])
    return df_kontak, None


# ======================================================
# SÜTUN HARİTASI OLUŞTURMA
# ======================================================

def build_sutun_haritasi(df_raw):
    sutun_haritasi = {}
    for col in df_raw.columns:
        cl = str(col).strip().lower().replace("\n", "").replace("\r", "")
        cl_norm = cl.replace("ı", "i").replace("ş", "s").replace("ç", "c") \
                    .replace("ö", "o").replace("ü", "u").replace("ğ", "g") \
                    .replace("İ", "i").replace("i̇", "i")
        if "operasyon" in cl_norm and "merkez" in cl_norm:
            sutun_haritasi["Operasyon_Merkezi"] = col
        elif cl_norm in ["kullanici", "kullanıcı", "terminal kullanicilari", "terminal kullanıcıları"]:
            sutun_haritasi["Kullanici"] = col
        elif "kullan" in cl_norm and ("ci" in cl_norm or "cı" in cl_norm):
            if "Kullanici" not in sutun_haritasi:
                sutun_haritasi["Kullanici"] = col
        elif cl_norm in ["hizmet numarasi", "hizmet no", "hizmet numarası"]:
            sutun_haritasi["Hizmet_No"] = col
        elif "hizmet" in cl_norm and ("no" in cl_norm or "numar" in cl_norm):
            if "Hizmet_No" not in sutun_haritasi:
                sutun_haritasi["Hizmet_No"] = col
        elif cl_norm == "kofra":
            sutun_haritasi["Kofra"] = col
        elif cl_norm == "plaka":
            sutun_haritasi["Plaka"] = col
        elif "tarih" in cl_norm and "saat" in cl_norm:
            sutun_haritasi["Tarih_Saat"] = col
        elif cl_norm in ["aktivite tipi", "aktivitetipi"]:
            sutun_haritasi["Aktivite_Tipi"] = col
        elif "saha" in cl_norm and "enlem" in cl_norm:
            sutun_haritasi["Saha_Enlem_Boylam"] = col
        elif cl_norm == "adres":
            sutun_haritasi["Adres"] = col
    return sutun_haritasi


# ======================================================
# VERİ HAZIRLAMA
# ======================================================

def prepare_sonuc_data(df_raw, sutun_haritasi, df_kontak=None, df_names=None):
    if df_raw.empty:
        return None, None
    df = df_raw.copy()
    for col in df.columns:
        if df[col].dtype == 'object':
            df[col] = df[col].astype(str).str.replace("\n", "", regex=False).str.replace("\r", "", regex=False).str.strip()
            df[col] = df[col].replace(["nan", "None", ""], pd.NA)
    kullanici_col = sutun_haritasi["Kullanici"]
    df = df.dropna(subset=[kullanici_col]).copy()
    df = df[df[kullanici_col].astype(str).str.strip() != ""].copy()
    tarih_saat_col = sutun_haritasi["Tarih_Saat"]
    df["Tarih_Saat_DT"] = pd.to_datetime(df[tarih_saat_col], dayfirst=True, errors="coerce")
    df = df.dropna(subset=["Tarih_Saat_DT"]).copy()
    df["Calisma_Gunu"] = df["Tarih_Saat_DT"].dt.date
    if "Operasyon_Merkezi" in sutun_haritasi:
        df["BÖLGE"] = df[sutun_haritasi["Operasyon_Merkezi"]].apply(operasyon_merkezi_to_bolge)
    else:
        df["BÖLGE"] = "Bilinmiyor"
    df["Personel"] = df[kullanici_col].astype(str).str.strip().str.split()
    df = df.explode("Personel", ignore_index=True)
    df["Personel"] = df["Personel"].astype(str).str.strip()
    df = df[df["Personel"].str.len() > 0].copy()
    df = df[df["Personel"] != "nan"].copy()

    # === İSİM LİSTESİ VE DESTEK FİLTRESİ ===
    valid_codes = get_valid_personnel_codes(df_names)
    if valid_codes is not None:
        df["Personel_Upper"] = df["Personel"].astype(str).str.strip().str.upper()
        df = df[df["Personel_Upper"].isin(valid_codes)].copy()
        df = df.drop(columns=["Personel_Upper"], errors="ignore")
    else:
        df = df[~df["Personel"].apply(contains_destek)].copy()

    if "Kofra" in sutun_haritasi:
        df["Kofra"] = df[sutun_haritasi["Kofra"]].astype(str).str.strip()
    else:
        df["Kofra"] = ""
    if "Hizmet_No" in sutun_haritasi:
        df["Hizmet_No"] = df[sutun_haritasi["Hizmet_No"]].astype(str).str.strip()
    else:
        df["Hizmet_No"] = df.index.astype(str)
    bos_kofra_mask = df["Kofra"].isna() | (df["Kofra"].isin(["", "nan", "None", "<NA>"]))
    df.loc[bos_kofra_mask, "Kofra"] = "H_" + df.loc[bos_kofra_mask, "Hizmet_No"]
    if "Aktivite_Tipi" in sutun_haritasi:
        df["Aktivite Tipi"] = df[sutun_haritasi["Aktivite_Tipi"]].astype(str).str.strip()
        df.loc[df["Aktivite Tipi"].isin(["", "nan", "None", "<NA>"]), "Aktivite Tipi"] = "OSOS Servis Bakım"
    else:
        df["Aktivite Tipi"] = "OSOS Servis Bakım"
    at_sayac_degistirme = [
        "Modem Değiştirme", "Modem Sökme", "Sayaç Değiştirme",
        "Sayaç Takma", "Yıkım Sebebiyle Sayaç Sökme"
    ]
    def map_aktivite(val):
        if val == "Kaçak Kontrol":
            return "Kaçak Kontrol"
        elif val in at_sayac_degistirme:
            return "At, Sayaç Değiştirme"
        else:
            return "Niteliksiz İşler"
    df["Aktivite Tipi Gruplu"] = df["Aktivite Tipi"].apply(map_aktivite)
    if "Plaka" in sutun_haritasi:
        df["Plaka"] = df[sutun_haritasi["Plaka"]].astype(str).str.strip()
    else:
        df["Plaka"] = ""
    if "Adres" in sutun_haritasi:
        df["Adres"] = df[sutun_haritasi["Adres"]].astype(str).str.strip()
    else:
        df["Adres"] = ""
    def clean_ekip_codes(val_str, valid_codes_set):
        codes = [c.strip() for c in str(val_str).replace(",", " ").split() if c.strip()]
        if valid_codes_set is not None:
            valid_c = [c for c in codes if c.upper() in valid_codes_set and not contains_destek(c)]
        else:
            valid_c = [c for c in codes if not contains_destek(c)]
        return ",".join(sorted(valid_c)) if valid_c else ",".join(sorted(codes))

    df["Ekip"] = df[kullanici_col].apply(lambda x: clean_ekip_codes(x, valid_codes))

    df["Ekip_Gun"] = df["Calisma_Gunu"].astype(str) + "_" + df["Ekip"]
    df["Ekip_Bolge"] = df["BÖLGE"]
    gunluk_kofra_counts = df.groupby(["Personel", "Calisma_Gunu"])["Kofra"].nunique().reset_index()
    gunluk_kofra_counts.columns = ["Personel", "Calisma_Gunu", "Kofra_Count"]
    gunluk_kofra_counts = gunluk_kofra_counts[gunluk_kofra_counts["Kofra_Count"] >= 6]
    df = df.merge(gunluk_kofra_counts[["Personel", "Calisma_Gunu"]], on=["Personel", "Calisma_Gunu"], how="inner")
    if df.empty:
        return None, None
    df = df.sort_values(["Personel", "Calisma_Gunu", "Tarih_Saat_DT"])
    df["Gecen_Sure"] = df.groupby(["Personel", "Calisma_Gunu"])["Tarih_Saat_DT"].diff().dt.total_seconds() / 60
    df["Is_Sirasi"] = df.groupby(["Personel", "Calisma_Gunu"]).cumcount()
    df["Toplam_Is"] = df.groupby(["Personel", "Calisma_Gunu"])["Tarih_Saat_DT"].transform("count")
    df["Onceki_Zaman"] = df.groupby(["Personel", "Calisma_Gunu"])["Tarih_Saat_DT"].shift(1)
    df["Ogle_Fark"] = (df["Tarih_Saat_DT"] - df["Onceki_Zaman"]).dt.total_seconds() / 60
    df["LAT"] = np.nan
    df["LON"] = np.nan
    if "Saha_Enlem_Boylam" in sutun_haritasi:
        coords = df[sutun_haritasi["Saha_Enlem_Boylam"]].apply(extract_first_coord)
        parsed_coords = pd.DataFrame(coords.tolist(), index=df.index, columns=["LAT_PARSE", "LON_PARSE"])
        df["LAT"] = parsed_coords["LAT_PARSE"]
        df["LON"] = parsed_coords["LON_PARSE"]
    valid_coords = df["LAT"].between(35, 43) & df["LON"].between(25, 45) & ~((df["LAT"].abs() < 0.0001) & (df["LON"].abs() < 0.0001))
    df.loc[~valid_coords, ["LAT", "LON"]] = np.nan
    df["personel_plaka"] = "Yaya"
    df["İlk Kontak"] = pd.NaT
    df["Son Kontak"] = pd.NaT
    if df_kontak is not None and not df_kontak.empty:
        plaka_kaynak = df[["Personel", "Calisma_Gunu", "Plaka"]].copy()
        plaka_kaynak["Plaka_Norm"] = plaka_kaynak["Plaka"].apply(normalize_plaka)
        personel_plaka = (
            plaka_kaynak.groupby(["Personel", "Calisma_Gunu"])["Plaka_Norm"]
            .agg(lambda x: sorted({p for p in x.dropna() if str(p).strip() and str(p) != "<NA>"}))
            .reset_index()
        )
        personel_plaka["personel_plaka"] = personel_plaka["Plaka_Norm"].apply(lambda x: ", ".join(x) if x else "Yaya")
        df_kontak_valid = df_kontak.dropna(subset=["tarih", "saat"]).copy()
        df_kontak_valid["tarih_saat"] = df_kontak_valid.apply(safe_combine, axis=1)
        df_kontak_valid["Calisma_Gunu"] = df_kontak_valid["tarih"].dt.date
        saat_0750 = datetime.time(7, 50, 0)
        saat_1830 = datetime.time(18, 30, 0)
        df_kontak_valid["kontak_saat"] = df_kontak_valid["tarih_saat"].dt.time
        kontak_ilk = (
            df_kontak_valid[df_kontak_valid["kontak_saat"] >= saat_0750]
            .groupby(["plaka", "Calisma_Gunu"])["tarih_saat"].min()
            .reset_index().rename(columns={"tarih_saat": "plaka_ilk_kontak"})
        )
        kontak_son = (
            df_kontak_valid[df_kontak_valid["kontak_saat"] <= saat_1830]
            .groupby(["plaka", "Calisma_Gunu"])["tarih_saat"].max()
            .reset_index().rename(columns={"tarih_saat": "plaka_son_kontak"})
        )
        kontak_gunluk = kontak_ilk.merge(kontak_son, on=["plaka", "Calisma_Gunu"], how="outer")
        personel_plaka_exploded = personel_plaka.explode("Plaka_Norm").dropna(subset=["Plaka_Norm"])
        if not personel_plaka_exploded.empty:
            personel_kontak_ozet = personel_plaka_exploded.merge(
                kontak_gunluk, left_on=["Plaka_Norm", "Calisma_Gunu"], right_on=["plaka", "Calisma_Gunu"], how="left",
            )
            personel_kontak_ozet = (
                personel_kontak_ozet.groupby(["Personel", "Calisma_Gunu", "personel_plaka"], as_index=False)
                .agg({"plaka_ilk_kontak": "min", "plaka_son_kontak": "max"})
                .rename(columns={"plaka_ilk_kontak": "İlk Kontak", "plaka_son_kontak": "Son Kontak"})
            )
            df = df.drop(columns=["personel_plaka", "İlk Kontak", "Son Kontak"], errors="ignore")
            df = df.merge(
                personel_kontak_ozet[["Personel", "Calisma_Gunu", "personel_plaka", "İlk Kontak", "Son Kontak"]],
                on=["Personel", "Calisma_Gunu"], how="left",
            )
            df["personel_plaka"] = df["personel_plaka"].fillna("Yaya")
            df["İlk Kontak"] = df["İlk Kontak"].fillna(pd.NaT)
            df["Son Kontak"] = df["Son Kontak"].fillna(pd.NaT)
    df["LAT_shift"] = df.groupby(["Ekip", "Calisma_Gunu"])["LAT"].shift()
    df["LON_shift"] = df.groupby(["Ekip", "Calisma_Gunu"])["LON"].shift()
    df["mesafe_degisim"] = ((df["LAT"] - df["LAT_shift"]) ** 2 + (df["LON"] - df["LON_shift"]) ** 2) ** 0.5
    personel_isim_map = {}
    if df_names is not None and "PERSONEL KODU" in df_names.columns and "ADI SOYADI" in df_names.columns:
        personel_isim_map = (
            df_names.dropna(subset=["PERSONEL KODU"]).drop_duplicates("PERSONEL KODU")
            .set_index("PERSONEL KODU")["ADI SOYADI"].to_dict()
        )
    return df, personel_isim_map


# ======================================================
# KONTAK ÖZET & MESAFE HESAPLAMA
# ======================================================

def compute_personel_kontak_ozet(df):
    if df.empty:
        return pd.DataFrame()
    required = ["Personel", "Calisma_Gunu", "personel_plaka", "İlk Kontak", "Son Kontak"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        return pd.DataFrame()
    ozet = df[required].drop_duplicates().copy()
    ozet["ilk_kontak_sn_gunluk"] = ozet["İlk Kontak"].apply(saat_to_saniye)
    ozet["son_kontak_sn_gunluk"] = ozet["Son Kontak"].apply(saat_to_saniye)
    return ozet


def compute_person_distance(df_filt):
    geo_df = df_filt.dropna(subset=["LAT", "LON"]).copy()
    if geo_df.empty:
        return pd.DataFrame(columns=["Personel", "Ort. Mesafe", "Toplam Mesafe"])
    geo_df = geo_df.sort_values(["Personel", "Calisma_Gunu", "Tarih_Saat_DT"])
    geo_df["LAT_prev"] = geo_df.groupby(["Personel", "Calisma_Gunu"])["LAT"].shift()
    geo_df["LON_prev"] = geo_df.groupby(["Personel", "Calisma_Gunu"])["LON"].shift()
    mask = geo_df["LAT_prev"].notna() & geo_df["LON_prev"].notna()
    geo_df.loc[mask, "mesafe_km"] = haversine(
        geo_df.loc[mask, "LAT_prev"], geo_df.loc[mask, "LON_prev"],
        geo_df.loc[mask, "LAT"], geo_df.loc[mask, "LON"],
    )
    geo_df["mesafe_m"] = geo_df["mesafe_km"] * 1000
    total_distance = geo_df.groupby("Personel")["mesafe_m"].sum().reset_index(name="Toplam Mesafe")
    job_counts = geo_df.groupby("Personel").size().reset_index(name="job_count")
    gun_sayisi = geo_df.groupby("Personel")["Calisma_Gunu"].nunique().reset_index(name="gun_sayisi")
    if total_distance.empty:
        return pd.DataFrame(columns=["Personel", "Ort. Mesafe", "Toplam Mesafe"])
    person_distance = total_distance.merge(job_counts, on="Personel").merge(gun_sayisi, on="Personel")
    person_distance["Ort. Mesafe"] = person_distance.apply(
        lambda row: row["Toplam Mesafe"] / (row["job_count"] - row["gun_sayisi"])
        if row["job_count"] > row["gun_sayisi"] else 0, axis=1,
    )
    person_distance = person_distance[["Personel", "Ort. Mesafe", "Toplam Mesafe"]]
    person_distance["Ort. Mesafe"] = person_distance["Ort. Mesafe"].round(1)
    person_distance["Toplam Mesafe"] = person_distance["Toplam Mesafe"].round(1)
    return person_distance.fillna(0)


# ======================================================
# FİLTRELİ RAPOR HESAPLAMA
# ======================================================

def compute_sonuc_rapor(df, df_names=None, baslangic=None, bitis=None):
    if baslangic and bitis:
        mask = (df["Tarih_Saat_DT"].dt.date >= baslangic) & (df["Tarih_Saat_DT"].dt.date <= bitis)
        df_filt = df[mask].copy()
    else:
        df_filt = df.copy()

    # İsim listesi ve Destek filtresi uygula
    valid_codes = get_valid_personnel_codes(df_names)
    if valid_codes is not None:
        df_filt["Personel_Upper"] = df_filt["Personel"].astype(str).str.strip().str.upper()
        df_filt = df_filt[df_filt["Personel_Upper"].isin(valid_codes)].copy()
        df_filt = df_filt.drop(columns=["Personel_Upper"], errors="ignore")
    else:
        df_filt = df_filt[~df_filt["Personel"].apply(contains_destek)].copy()

    if df_filt.empty:
        return pd.DataFrame(), pd.DataFrame()
    personel_havuzu = df_filt[["Personel"]].drop_duplicates()
    gunluk_grup = df_filt.groupby(["Personel", "Calisma_Gunu"])
    z_ozet = gunluk_grup["Tarih_Saat_DT"].agg(["min", "max"])
    z_ozet["ilk_sn"] = z_ozet["min"].dt.hour * 3600 + z_ozet["min"].dt.minute * 60 + z_ozet["min"].dt.second
    z_ozet["son_sn"] = z_ozet["max"].dt.hour * 3600 + z_ozet["max"].dt.minute * 60 + z_ozet["max"].dt.second
    z_ozet["sure_dk"] = (z_ozet["max"] - z_ozet["min"]).dt.total_seconds() / 60
    gun_sayisi = df_filt.groupby("Personel")["Calisma_Gunu"].nunique()
    bekleme_ort = df_filt.groupby("Personel")["Gecen_Sure"].mean().round(1)
    bekleme_uzun = df_filt[df_filt["Gecen_Sure"] > 60].groupby("Personel").size()
    ort_kofra = (df_filt.groupby("Personel")["Kofra"].nunique() / gun_sayisi).round(1)
    ort_is = (df_filt.groupby("Personel")["Kofra"].count() / gun_sayisi).round(1)
    toplam_kofra = df_filt.groupby("Personel")["Kofra"].nunique()
    toplam_is = df_filt.groupby("Personel")["Kofra"].count()
    ilk_sn_ort = z_ozet.groupby(level=0)["ilk_sn"].mean()
    son_sn_ort = z_ozet.groupby(level=0)["son_sn"].mean()
    ort_sure = z_ozet.groupby(level=0)["sure_dk"].mean().round(0)
    ogle_vakti = (
        df_filt["Onceki_Zaman"].notna()
        & (df_filt["Onceki_Zaman"].dt.time >= datetime.time(11, 50))
        & (df_filt["Onceki_Zaman"].dt.time <= datetime.time(13, 40))
        & (df_filt["Ogle_Fark"] > 90)
    )
    uzun_ogle = df_filt[ogle_vakti].groupby("Personel").size()
    df_ikinci = df_filt[df_filt["Is_Sirasi"] == 1].copy()
    df_ikinci["problem"] = (df_ikinci["Gecen_Sure"] > 60) & (df_ikinci["Gecen_Sure"] < 180)
    ilk_is_uzun = df_ikinci.groupby(["Personel", "Calisma_Gunu"])["problem"].max().groupby("Personel").sum()
    df_son = df_filt[df_filt["Is_Sirasi"] == df_filt["Toplam_Is"] - 1].copy()
    df_son["problem"] = (df_son["Gecen_Sure"] > 60) & (df_son["Gecen_Sure"] < 180)
    son_is_uzun = df_son.groupby(["Personel", "Calisma_Gunu"])["problem"].max().groupby("Personel").sum()
    personel_kontak_ozet = compute_personel_kontak_ozet(df_filt)
    if not personel_kontak_ozet.empty:
        ilk_kontak_ort = personel_kontak_ozet.groupby("Personel")["ilk_kontak_sn_gunluk"].mean()
        son_kontak_ort = personel_kontak_ozet.groupby("Personel")["son_kontak_sn_gunluk"].mean()
    else:
        ilk_kontak_ort = pd.Series(dtype=float)
        son_kontak_ort = pd.Series(dtype=float)
    if "Aktivite Tipi Gruplu" in df_filt.columns:
        aktivite_counts = df_filt.groupby(["Personel", "Aktivite Tipi Gruplu"]).size().unstack(fill_value=0)
        for col in ["Kaçak Kontrol", "At, Sayaç Değiştirme", "Niteliksiz İşler"]:
            if col not in aktivite_counts.columns:
                aktivite_counts[col] = 0
    else:
        aktivite_counts = pd.DataFrame(
            index=df_filt["Personel"].unique(),
            columns=["Kaçak Kontrol", "At, Sayaç Değiştirme", "Niteliksiz İşler"]
        ).fillna(0)
    filtreli_rapor = pd.concat([
        ort_kofra, ort_is, toplam_kofra, toplam_is,
        ilk_sn_ort, son_sn_ort, ort_sure,
        uzun_ogle, ilk_is_uzun, son_is_uzun,
        gun_sayisi, bekleme_ort, bekleme_uzun,
        ilk_kontak_ort, son_kontak_ort,
        aktivite_counts["Kaçak Kontrol"],
        aktivite_counts["At, Sayaç Değiştirme"],
        aktivite_counts["Niteliksiz İşler"],
    ], axis=1)
    filtreli_rapor.columns = [
        "Ort. Kofra", "Ort. İş", "Toplam Kofra", "Toplam İş",
        "ilk_sn", "son_sn", "Ort. Süre (Dk)",
        "Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun",
        "Gün Sayısı", "Ort. İş Arası Süre", "Uzun İş Arası Süre",
        "ilk_kontak_sn", "son_kontak_sn",
        "Kaçak Kontrol", "At, Sayaç Değiştirme", "Niteliksiz İşler",
    ]
    filtreli_rapor = filtreli_rapor.reset_index()
    filtreli_rapor = personel_havuzu.merge(filtreli_rapor, on="Personel", how="left")
    time_cols = ["ilk_kontak_sn", "son_kontak_sn", "ilk_sn", "son_sn", "Ort. Süre (Dk)", "Ort. İş Arası Süre"]
    fill_zero_cols = [c for c in filtreli_rapor.columns if c not in ["Personel"] + time_cols]
    filtreli_rapor[fill_zero_cols] = filtreli_rapor[fill_zero_cols].fillna(0)
    person_distance = compute_person_distance(df_filt)
    if not person_distance.empty:
        filtreli_rapor = filtreli_rapor.merge(person_distance, on="Personel", how="left")
        filtreli_rapor[["Ort. Mesafe", "Toplam Mesafe"]] = filtreli_rapor[["Ort. Mesafe", "Toplam Mesafe"]].fillna(0)
    else:
        filtreli_rapor["Ort. Mesafe"] = 0
        filtreli_rapor["Toplam Mesafe"] = 0
    if df_names is not None and "PERSONEL KODU" in df_names.columns:
        cols_to_merge = ["PERSONEL KODU"]
        if "ADI SOYADI" in df_names.columns:
            cols_to_merge.append("ADI SOYADI")
        if "PERSONEL Sicil No" in df_names.columns:
            cols_to_merge.append("PERSONEL Sicil No")
        df_n_subset = df_names[cols_to_merge].drop_duplicates("PERSONEL KODU").copy()
        df_n_subset["PERSONEL_KODU_UP"] = df_n_subset["PERSONEL KODU"].astype(str).str.strip().str.upper()
        df_n_subset = df_n_subset.drop(columns=["PERSONEL KODU"])
        filtreli_rapor["Personel_Upper"] = filtreli_rapor["Personel"].astype(str).str.strip().str.upper()
        filtreli_rapor = filtreli_rapor.merge(
            df_n_subset,
            left_on="Personel_Upper", right_on="PERSONEL_KODU_UP", how="left",
        )
        filtreli_rapor = filtreli_rapor.drop(columns=["PERSONEL_KODU_UP", "Personel_Upper"], errors="ignore")
    if "ADI SOYADI" not in filtreli_rapor.columns or filtreli_rapor["ADI SOYADI"].isna().all():
        filtreli_rapor["ADI SOYADI"] = filtreli_rapor["Personel"]
    else:
        filtreli_rapor["ADI SOYADI"] = filtreli_rapor["ADI SOYADI"].fillna(filtreli_rapor["Personel"])
    personel_bolge = (
        df_filt.groupby("Personel")["BÖLGE"]
        .agg(lambda x: x.mode().iloc[0] if not x.mode().empty else "Bilinmiyor")
        .reset_index()
    )
    if "BÖLGE" not in filtreli_rapor.columns:
        filtreli_rapor = filtreli_rapor.merge(personel_bolge, on="Personel", how="left")
    filtreli_rapor["BÖLGE"] = filtreli_rapor["BÖLGE"].fillna("Bilinmiyor")
    filtreli_rapor = filtreli_rapor[filtreli_rapor["Gün Sayısı"] > 0].copy()
    if filtreli_rapor.empty:
        return pd.DataFrame(), pd.DataFrame()
    filtreli_rapor["İlk İş (Ort.)"] = filtreli_rapor["ilk_sn"].apply(saniye_formatla)
    filtreli_rapor["Son İş (Ort.)"] = filtreli_rapor["son_sn"].apply(saniye_formatla)
    filtreli_rapor["İlk Kontak (Ort.)"] = filtreli_rapor["ilk_kontak_sn"].apply(saniye_to_saat)
    filtreli_rapor["Son Kontak (Ort.)"] = filtreli_rapor["son_kontak_sn"].apply(saniye_to_saat)
    # === PUANLAMA SİSTEMİ (50 Tarama + 50 Tempo) ===
    score_cols = [
        "P_Tarama_Hacim", "P_Tarama_Kalite", "P_Tarama_Toplam",
        "P_Tempo_IlkIs", "P_Tempo_SonIs", "P_Tempo_Sure", "P_Tempo_IsArasi", "P_Tempo_Toplam",
        "C_IlkIs", "C_SonIs", "C_Ogle", "P_Disiplin_Ceza",
        "Genel_Skor"
    ]
    def calculate_scores(row):
        gun = row.get("Gün Sayısı", 0)
        if gun == 0:
            return pd.Series([0] * len(score_cols), index=score_cols)
        kofra = row.get("Ort. Kofra", 0)
        p_tarama_hacim = 30 if kofra >= 20 else (24 if kofra >= 18 else (18 if kofra >= 15 else (12 if kofra >= 10 else 5)))
        nitelikli_is = row.get("Kaçak Kontrol", 0) + row.get("At, Sayaç Değiştirme", 0)
        nitelikli_is_ort = nitelikli_is / gun
        p_tarama_kalite = 20 if nitelikli_is_ort >= 20 else (16 if nitelikli_is_ort >= 18 else (12 if nitelikli_is_ort >= 15 else (7 if nitelikli_is_ort >= 10 else 0)))
        p_tarama_toplam = p_tarama_hacim + p_tarama_kalite
        ilk_sn = row.get("ilk_sn", 0)
        p_tempo_ilkis = 12 if ilk_sn <= 31500 else (9 if ilk_sn <= 32100 else (5 if ilk_sn <= 32700 else 0))
        son_sn = row.get("son_sn", 0)
        p_tempo_sonis = 12 if son_sn >= 62100 else (9 if son_sn >= 61500 else (5 if son_sn >= 60600 else 0))
        sure = row.get("Ort. Süre (Dk)", 0)
        p_tempo_sure = 13 if sure >= 480 else (9 if sure >= 460 else (5 if sure >= 440 else 0))
        is_arasi = row.get("Ort. İş Arası Süre", 0)
        p_tempo_isarasi = 13 if is_arasi <= 25 else (9 if is_arasi <= 30 else (5 if is_arasi <= 40 else 0))
        p_tempo_toplam = p_tempo_ilkis + p_tempo_sonis + p_tempo_sure + p_tempo_isarasi
        hak = gun * 0.4
        def calc_ceza(val, hak):
            if val <= hak: return 0
            return -(int(np.ceil(val - hak)) * 2)
        c_ilkis = calc_ceza(row.get("İlk İş Uzun", 0), hak)
        c_sonis = calc_ceza(row.get("Son-Önceki İş Uzun", 0), hak)
        c_ogle = calc_ceza(row.get("Uzun Öğle", 0), hak)
        p_disiplin_ceza = max(-10, c_ilkis + c_sonis + c_ogle)
        genel_skor = max(0, min(100, round(p_tarama_toplam + p_tempo_toplam + p_disiplin_ceza)))
        return pd.Series([
            p_tarama_hacim, p_tarama_kalite, p_tarama_toplam,
            p_tempo_ilkis, p_tempo_sonis, p_tempo_sure, p_tempo_isarasi, p_tempo_toplam,
            c_ilkis, c_sonis, c_ogle, p_disiplin_ceza, genel_skor
        ], index=score_cols)
    if not filtreli_rapor.empty:
        scores_df = filtreli_rapor.apply(calculate_scores, axis=1)
        filtreli_rapor = pd.concat([filtreli_rapor, scores_df], axis=1)
    else:
        for col in score_cols:
            filtreli_rapor[col] = 0
    b_filtreli_rapor = compute_bolge_rapor(filtreli_rapor, df_filt)
    return filtreli_rapor, b_filtreli_rapor


# ======================================================
# BÖLGE RAPORU HESAPLAMA
# ======================================================

def compute_bolge_rapor(filtreli_rapor, df_filt=None):
    bolge_toplam_kofra = None
    bolge_toplam_is = None
    genel_toplam_is = 0
    genel_toplam_kofra = 0
    if df_filt is not None and not df_filt.empty:
        unique_cols = ["BÖLGE", "Ekip", "Calisma_Gunu", "Kofra", "Aktivite Tipi"]
        available_unique_cols = [c for c in unique_cols if c in df_filt.columns]
        unique_ops = df_filt.drop_duplicates(subset=available_unique_cols)
        bolge_toplam_is = unique_ops.groupby("BÖLGE").size().reset_index(name="Toplam İş")
        bolge_toplam_kofra = df_filt.groupby("BÖLGE")["Kofra"].nunique().reset_index(name="Toplam Kofra")
        genel_toplam_is = len(unique_ops)
        genel_toplam_kofra = df_filt["Kofra"].nunique()
    b_agg = {
        "Ort. Kofra": "mean", "Ort. İş": "mean", "Ort. Mesafe": "mean",
        "ilk_sn": "mean", "son_sn": "mean",
        "ilk_kontak_sn": "mean", "son_kontak_sn": "mean",
        "Ort. Süre (Dk)": "mean", "Ort. İş Arası Süre": "mean",
        "Uzun Öğle": "sum", "İlk İş Uzun": "sum", "Son-Önceki İş Uzun": "sum",
        "Genel_Skor": "mean",
    }
    personel_sum_cols = ["Toplam Kofra", "Toplam İş"]
    for col in personel_sum_cols:
        if col in filtreli_rapor.columns:
            b_agg[col] = "sum"
    aktif = filtreli_rapor[filtreli_rapor["Gün Sayısı"] > 0].copy()
    for col in b_agg.keys():
        if col in aktif.columns:
            if b_agg[col] == "mean":
                aktif[col] = pd.to_numeric(aktif[col], errors="coerce").replace(0, np.nan)
            else:
                aktif[col] = pd.to_numeric(aktif[col], errors="coerce").fillna(0)
    if aktif.empty or "BÖLGE" not in aktif.columns:
        return pd.DataFrame()
    valid_agg = {k: v for k, v in b_agg.items() if k in aktif.columns}
    b_filtreli_rapor = aktif.groupby("BÖLGE").agg(valid_agg).round(1).reset_index()
    if bolge_toplam_kofra is not None:
        b_filtreli_rapor = b_filtreli_rapor.drop(columns=["Toplam Kofra"], errors="ignore").merge(bolge_toplam_kofra, on="BÖLGE", how="left")
    if bolge_toplam_is is not None:
        b_filtreli_rapor = b_filtreli_rapor.drop(columns=["Toplam İş"], errors="ignore").merge(bolge_toplam_is, on="BÖLGE", how="left")
    bolge_satirlari = b_filtreli_rapor.copy()
    genel = {"BÖLGE": "Genel Şirket Ortalaması"}
    for col, agg in valid_agg.items():
        if col in bolge_satirlari.columns:
            if agg == "mean":
                mean_series = bolge_satirlari[col].replace(0, np.nan)
                genel[col] = round(float(mean_series.mean()), 1) if mean_series.notna().any() else 0
            else:
                genel[col] = bolge_satirlari[col].sum()
        else:
            genel[col] = 0
    genel["Toplam Kofra"] = genel_toplam_kofra
    genel["Toplam İş"] = genel_toplam_is
    genel_df = pd.DataFrame([genel])
    b_filtreli_rapor = pd.concat([b_filtreli_rapor, genel_df], ignore_index=True)
    b_filtreli_rapor["Ort. İlk İş"] = b_filtreli_rapor["ilk_sn"].apply(saniye_formatla)
    b_filtreli_rapor["Ort. Son İş"] = b_filtreli_rapor["son_sn"].apply(saniye_formatla)
    b_filtreli_rapor["İlk Kontak (Ort.)"] = b_filtreli_rapor["ilk_kontak_sn"].apply(saniye_to_saat)
    b_filtreli_rapor["Son Kontak (Ort.)"] = b_filtreli_rapor["son_kontak_sn"].apply(saniye_to_saat)
    return b_filtreli_rapor
