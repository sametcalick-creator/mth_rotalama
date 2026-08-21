
import io
import os
import time
import datetime
import numpy as np
import pandas as pd
from functools import lru_cache

# Matplotlib - Kaleido yerine (Kaleido 0.2.x Windows'ta hang yapıyor)
import matplotlib
matplotlib.use('Agg')  # GUI olmadan render
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    Image = None

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import mm, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
from reportlab.platypus import (
    BaseDocTemplate, PageTemplate, Frame, Paragraph, Spacer, Image as RLImage, 
    Table, TableStyle, PageBreak, KeepTogether, NextPageTemplate
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

try:
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import matplotlib.font_manager as fm
    from matplotlib.font_manager import FontProperties

    dejavu_path = fm.findfont(FontProperties(family='DejaVu Sans', style='normal', weight='normal'))
    dejavu_bold_path = fm.findfont(FontProperties(family='DejaVu Sans', style='normal', weight='bold'))
    dejavu_italic_path = fm.findfont(FontProperties(family='DejaVu Sans', style='oblique', weight='normal'))
    dejavu_bold_italic_path = fm.findfont(FontProperties(family='DejaVu Sans', style='oblique', weight='bold'))

    pdfmetrics.registerFont(TTFont('DejaVuSans', dejavu_path))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Bold', dejavu_bold_path))
    pdfmetrics.registerFont(TTFont('DejaVuSans-Oblique', dejavu_italic_path))
    pdfmetrics.registerFont(TTFont('DejaVuSans-BoldOblique', dejavu_bold_italic_path))

    pdfmetrics.registerFontFamily(
        'DejaVuSans',
        normal='DejaVuSans',
        bold='DejaVuSans-Bold',
        italic='DejaVuSans-Oblique',
        boldItalic='DejaVuSans-BoldOblique'
    )
    FONT_REGULAR = 'DejaVuSans'
    FONT_BOLD = 'DejaVuSans-Bold'
except Exception:
    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont

        pdfmetrics.registerFont(TTFont('Arial', 'C:\\Windows\\Fonts\\arial.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-Bold', 'C:\\Windows\\Fonts\\arialbd.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-Italic', 'C:\\Windows\\Fonts\\ariali.ttf'))
        pdfmetrics.registerFont(TTFont('Arial-BoldItalic', 'C:\\Windows\\Fonts\\arialbi.ttf'))

        pdfmetrics.registerFontFamily(
            'Arial',
            normal='Arial',
            bold='Arial-Bold',
            italic='Arial-Italic',
            boldItalic='Arial-BoldItalic'
        )
        FONT_REGULAR = 'Arial'
        FONT_BOLD = 'Arial-Bold'
    except Exception:
        FONT_REGULAR = 'Helvetica'
        FONT_BOLD = 'Helvetica-Bold'

# Matplotlib için Türkçe font ayarı
try:
    plt.rcParams['font.family'] = 'DejaVu Sans'
    plt.rcParams['font.sans-serif'] = ['DejaVu Sans', 'Arial', 'Segoe UI', 'sans-serif']
except Exception:
    pass
plt.rcParams['axes.unicode_minus'] = False


# ======================================================
# YARDIMCI FONKSİYONLAR
# ======================================================

@lru_cache(maxsize=4096)
def saniye_formatla(s):
    if pd.isna(s) or s == 0:
        return "00:00"
    # Eğer s string ise ve ':' içeriyorsa (örn: '08:22'), doğrudan döndür
    if isinstance(s, str):
        if ":" in s:
            return s
        try:
            total_seconds = int(float(s))
        except Exception:
            return "00:00"
    else:
        total_seconds = int(s)
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{hours:02d}:{minutes:02d}"

def create_pie_chart(total_val, personel_val, title, label_personel="Kaçak Personel", label_other="Beda+Mth"):
    """Dairesel grafik (pie chart) oluştur."""
    if total_val <= 0:
        return None
    
    # Sayısal değerleri garanti et
    try:
        t_val = float(total_val)
        p_val = float(personel_val)
    except:
        return None

    other_val = max(0, t_val - p_val)
    labels = [label_personel, label_other]
    sizes = [p_val, other_val]
    colors = ['#16a34a', '#dc2626'] # Yeşil ve Kırmızı
    
    fig, ax = plt.subplots(figsize=(5, 5))
    fig.set_facecolor('#fff5f5')
    
    def func(pct, allvals):
        return f"%{pct:.1f}"
        
    wedges, texts, autotexts = ax.pie(sizes, labels=labels, autopct=lambda pct: func(pct, sizes),
                                  startangle=140, colors=colors, textprops=dict(color="black", fontsize=12, fontweight='bold'))
    
    plt.setp(autotexts, size=18, weight="bold")
    ax.set_title(title, fontsize=14, fontweight='bold', color='#991b1b')
    
    fig.tight_layout()
    return fig

def build_scoring_guide(styles):
    """Puanlama Rehberi kartı oluştur."""
    elements = []
    guide_title_style = ParagraphStyle(
        'GuideTitle',
        parent=styles['SectionTitle'],
        fontSize=14,
        leading=16,
        spaceBefore=5,
        spaceAfter=5
    )
    guide_text_style = ParagraphStyle(
        'GuideText',
        parent=styles['CardText'],
        fontSize=8,
        leading=10,
        alignment=TA_LEFT
    )
    
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("<b>Puanlama Rehberi</b>", guide_title_style))
    elements.append(Spacer(1, 5))
    
    data = [
        [Paragraph("<b>1. Tarama Puanı (Max 50)</b>", guide_text_style), 
         Paragraph("• <b>Hacim (30p):</b> Günlük ort. kofra sayısı: >= 20 (30p), 18-19.9 (24p), 15-17.9 (18p), 10-14.9 (12p), &lt;10 (5p).<br/>• <b>Kalite (20p):</b> Günlük nitelikli iş sayısı: >= 20 (20p), 18-19.9 (16p), 15-17.9 (12p), 10-14.9 (7p), &lt;10 (0p).", guide_text_style)],
        
        [Paragraph("<b>2. Tempo Puanı (Max 50)</b>", guide_text_style), 
         Paragraph("• <b>İlk İş (12p):</b> Ort. İlk İş <= 08:45 (12p), <= 08:55 (9p), <= 09:05 (5p), &gt; 09:05 (0p)<br/>• <b>Son İş (12p):</b> Ort. Son İş >= 17:15 (12p), >= 17:05 (9p), >= 16:50 (5p), &lt; 16:50 (0p)<br/>• <b>Süre (13p):</b> Ort. Süre >= 480 dk (13p), >= 460 dk (9p), >= 440 dk (5p), &lt; 440 dk (0p)<br/>• <b>İş Arası (13p):</b> Ort. İş Arası <= 25 dk (13p), 26-30 dk (9p), 31-40 dk (5p), &gt; 40 dk (0p)", guide_text_style)],
        
        [Paragraph("<b>3. Disiplin (Max -10)</b>", guide_text_style), 
         Paragraph("• Esneklik Hakkı: Gün × 0.4 (Örn: 5 gün = 2 hak). Hakkı aşan her ihlal için <b>-2 puan</b> ceza uygulanır. Toplam ceza -10 puanı geçemez.", guide_text_style)]
    ]
    
    t = Table(data, colWidths=[130, 620])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#fca5a5')),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#fecdd3')),
        ('BACKGROUND', (0, 0), (0, -1), colors.HexColor('#fee2e2')),
    ]))
    
    elements.append(t)
    return elements

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

def get_kpi_unit_and_format(kpi_col):
    if kpi_col in ["ilk_sn", "son_sn", "ilk_kontak_sn", "son_kontak_sn"]:
        return "saat", "time"
    elif kpi_col in ["Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun"]:
        return "adet", "count"
    elif kpi_col in ["Ort. Mesafe", "Toplam Mesafe"]:
        return "m", "decimal"
    elif kpi_col in ["Genel_Skor"]:
        return "puan", "decimal"
    return "", "decimal"


def mpl_fig_to_rlimage(fig, width_px, height_px, dpi=100):
    """Matplotlib figure'ı ReportLab Image'a çevir."""
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi, bbox_inches='tight', 
                facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    buf.seek(0)
    return RLImage(buf, width=width_px * 0.45, height=height_px * 0.45)


def create_heatmap_image(heat_data, width_px=1400, height_px=800, secilen_bolge="Tümü"):
    """
    Smarter Auto-Framing Isı Haritası.
    Bölgenin coğrafi yapısına göre (enlem/boylam) dinamik boyutlandırma yapar.
    """
    if heat_data is None or heat_data.empty:
        return None
    
    clean = heat_data.dropna(subset=["LAT", "LON"])
    if len(clean) < 2:
        return None
    
    try:
        import contextily as ctx
        from scipy.stats import gaussian_kde
        from matplotlib.colors import LinearSegmentedColormap
        from pyproj import Transformer
        import matplotlib.patheffects as path_effects
        
        lons = clean["LON"].values.astype(float)
        lats = clean["LAT"].values.astype(float)
        
        # --- 1. AKILLI KADRAJ HESAPLAMA ---
        lon_min, lon_max = lons.min(), lons.max()
        lat_min, lat_max = lats.min(), lats.max()
        
        lon_center = (lon_min + lon_max) / 2
        lat_center = (lat_min + lat_max) / 2
        
        # Ham açıklıklar
        lon_delta = lon_max - lon_min
        lat_delta = lat_max - lat_min
        
        # Minimum Kapsama Alanı (Örn: ~9km kuralı - aşırı zoom'u engellemek için)
        min_span = 0.08 
        lon_delta = max(lon_delta, min_span)
        lat_delta = max(lat_delta, min_span)
        
        # Nefes alma payı (Padding %15)
        pad = 0.15
        x0, x1 = lon_center - (lon_delta * (0.5 + pad)), lon_center + (lon_delta * (0.5 + pad))
        y0, y1 = lat_center - (lat_delta * (0.5 + pad)), lat_center + (lat_delta * (0.5 + pad))
        
        # --- 2. DİNAMİK ASPECT RATIO & FIGSIZE ---
        # Dünya eğriliğini hesaba katarak coğrafi en-boy oranını bul (Antalya ~36.8N)
        lat_rad = np.radians(lat_center)
        geo_ratio = ((x1 - x0) * np.cos(lat_rad)) / (y1 - y0)
        
        # Ana genişlik 18 inch (daha büyük render için), yüksekliği orana göre belirle
        fig_w = 18
        fig_h = fig_w / geo_ratio
        
        # Aşırı dikey veya aşırı yatay bölgeleri dengele (Limitler esnetildi)
        if fig_h > 12:
            fig_h = 12
            fig_w = fig_h * geo_ratio
        elif fig_h < 8:
            fig_h = 8
            fig_w = fig_h * geo_ratio
            
        # Max genişlik kısıtı
        if fig_w > 22:
            fig_w = 22
            fig_h = fig_w / geo_ratio

        fig, ax = plt.subplots(figsize=(fig_w, fig_h))
        fig.set_facecolor('white')
        
        # Gerçek dünya ölçeğini koru (Kıyı şeridi basık durmasın)
        ax.set_aspect('equal')
        ax.set_xlim(x0, x1)
        ax.set_ylim(y0, y1)
        
        # --- 3. ZOOM HESABI ---
        try:
            transformer = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
            west, south, east, north = transformer.transform_bounds(x0, y0, x1, y1)
            auto_z = ctx.tile.auto_zoom(west, east, south, north)
            manual_zoom = min(auto_z + 1, 18)
        except:
            manual_zoom = 'auto'

        # --- 4. KATMANLAR (Sandviç Mimari) ---
        # Zemin - Uydu görüntüsü (Google Haritalar benzeri)
        try:
            ctx.add_basemap(ax, crs="EPSG:4326", source=ctx.providers.Esri.WorldImagery, zoom=manual_zoom, zorder=1)
        except:
            pass
        
        # Isı (KDE Contourf)
        grid_res = 300
        xi = np.linspace(x0, x1, grid_res); yi = np.linspace(y0, y1, grid_res)
        Xi, Yi = np.meshgrid(xi, yi)
        positions = np.vstack([Xi.ravel(), Yi.ravel()])
        # Isının çok dağılmaması ve daha odaklı (dar) noktalar oluşması için bw_method küçültüldü
        kernel = gaussian_kde(np.vstack([lons, lats]), bw_method=0.1)
        zi = np.reshape(kernel(positions), Xi.shape)
        
        # Az iş yapılmış yerlerin çok daha belirgin olması için eşik %0.5'e düşürüldü
        threshold = zi.max() * 0.01
        zi_masked = np.ma.masked_where(zi < threshold, zi)
        
        # İlk görseldeki "güzel" kırmızı-sarı renkler için palet (koyu mora gitmesini engelliyoruz, max=0.85)
        cmap_base = plt.cm.YlOrRd
        cmap_colors = cmap_base(np.linspace(0.10, 0.85, 256))
        
        # Düşük yoğunluklu yerlerin iyice belirgin (sarı) olması için alpha kökü 0.20 yapıldı
        alphas = np.linspace(0.0, 1.0, 256) ** 0.30
        cmap_colors[:, 3] = alphas * 0.85 
        custom_cmap = LinearSegmentedColormap.from_list('YlOrRd_smooth', cmap_colors, N=256)
        
        # 100 seviye (level) ile halka görüntüsü olmadan pürüzsüz geçiş sağlıyoruz
        ax.contourf(Xi, Yi, zi_masked, levels=np.linspace(threshold, zi.max(), 100), cmap=custom_cmap, zorder=2, antialiased=True)
        
        # Etiketler - Isı katmanının ÜSTÜNDE (zorder=10) - Net ve okunakllı etiketler
        try:
            ctx.add_basemap(ax, crs="EPSG:4326", source=ctx.providers.CartoDB.PositronOnlyLabels, zoom=manual_zoom, zorder=10, alpha=1.0)
        except:
            pass

        # --- 5. TEKNİK CİLA ---
        ax.set_xticks([]); ax.set_yticks([])
        for spine in ax.spines.values(): spine.set_visible(False)
        
        # Başlık + Kalın Halo
        title_obj = ax.set_title(f"Isı Haritası\n{secilen_bolge.upper()}",
                                 fontsize=18, fontweight='bold', color='#000000', pad=18)
        # Info Box + Kalın Halo
        txt_obj = ax.text(0.02, 0.04, f"Analiz Kapsamı: {len(clean):,} İş Noktası",
                          transform=ax.transAxes, fontsize=12, color='#000000', fontweight='bold',
                          zorder=15, bbox=dict(boxstyle='round,pad=0.8', fc='white', alpha=0.95, ec='#1a237e', linewidth=2))
        
        halo = [path_effects.withStroke(linewidth=5, foreground='white')]
        title_obj.set_path_effects(halo)
        txt_obj.set_path_effects([path_effects.withStroke(linewidth=4, foreground='white')])
        
        fig.tight_layout()
        return mpl_fig_to_rlimage(fig, fig_w*100, fig_h*100, dpi=250)
    
    except Exception as e:
        print(f"  [HATA] Harita render hatası: {str(e)}")
        import traceback
        traceback.print_exc()
        return _create_heatmap_fallback(heat_data, width_px, height_px, secilen_bolge)


def _create_heatmap_fallback(heat_data, width_px, height_px, secilen_bolge):
    """KDE/Contextily hata verirse basit scatter harita (fallback)."""
    try:
        clean = heat_data.dropna(subset=["LAT", "LON"])
        if len(clean) < 2:
            return None
        lons = clean["LON"].values
        lats = clean["LAT"].values
        
        fig, ax = plt.subplots(figsize=(width_px/100, height_px/100))
        fig.set_facecolor('#f5f5f5')
        ax.set_facecolor('#e8eaed')
        
        ax.scatter(lons, lats, s=4, c='#1e88e5', alpha=0.5, edgecolors='none')
        ax.set_title(f"Calisma Yogunlugu - {secilen_bolge}", fontsize=12, fontweight='bold')
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        
        fig.tight_layout()
        return mpl_fig_to_rlimage(fig, width_px, height_px)
    except Exception:
        return None

# ======================================================
# STİL TANIMLARI
# ======================================================

def get_styles():
    """PDF için özel stiller oluştur."""
    styles = getSampleStyleSheet()
    if 'Normal' in styles:
        styles['Normal'].fontName = FONT_REGULAR
    if 'BodyText' in styles:
        styles['BodyText'].fontName = FONT_REGULAR
    styles.add(ParagraphStyle(
        name='CoverDate',
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#37474f'),
        fontName=FONT_REGULAR,
    ))
    
    styles.add(ParagraphStyle(
        name='CoverTitle',
        fontSize=36,
        leading=42,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#b91c1c'),
        fontName=FONT_BOLD,
        spaceBefore=10,
        spaceAfter=30,
    ))
    styles.add(ParagraphStyle(
        name='CoverSubTitle',
        fontSize=24,
        leading=30,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#991b1b'),
        spaceBefore=10,
        spaceAfter=30,
        fontName=FONT_BOLD,
    ))
    
    styles.add(ParagraphStyle(
        name='SectionTitle',
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#991b1b'),
        spaceBefore=20,
        spaceAfter=12,
        fontName=FONT_BOLD,
    ))
    styles.add(ParagraphStyle(
        name='ChartTitle',
        fontSize=14,
        leading=18,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#b91c1c'),
        spaceBefore=10,
        spaceAfter=5,
        fontName=FONT_BOLD,
    ))
    styles.add(ParagraphStyle(
        name='CardText',
        fontSize=10,
        leading=14,
        alignment=TA_LEFT,
        textColor=colors.HexColor('#455a64'),
        fontName=FONT_REGULAR,
    ))
    styles.add(ParagraphStyle(
        name='CardValue',
        fontSize=18,
        leading=22,
        alignment=TA_CENTER,
        textColor=colors.HexColor('#991b1b'),
        fontName=FONT_BOLD,
    ))
    styles.add(ParagraphStyle(
        name='CardDelta',
        fontSize=10,
        leading=14,
        alignment=TA_CENTER,
        fontName=FONT_BOLD,
    ))
    return styles

# ======================================================
# VERİ HAZIRLAMA (GÜNLÜK TREND İÇİN)
# ======================================================

# Cache for preprocessed trend data to avoid redundant heavy calculations
_TREND_CACHE = {}

def prepare_trend_data_for_pdf(df, selected_kpi):
    """Günlük trend grafiği için veriyi hesaplar. Ağır hesaplamaları cache'ler."""
    if df.empty:
        return pd.DataFrame()
    
    # DataFrame'in ID'sini (hash veya object id) kullanarak cache kontrolü yapabiliriz
    # Basitlik için df'in uzunluğu ve ilk/son tarihini anahtar olarak kullanalım
    cache_key = (len(df), df["Çizelgeleme Tarihi"].min(), df["Çizelgeleme Tarihi"].max())
    
    global _TREND_CACHE
    if cache_key not in _TREND_CACHE:
        df_temp = df.copy()
        gunluk_grup = df_temp.groupby(["Personel", "Calisma_Gunu"])
        z_ozet = gunluk_grup["Çizelgeleme Tarihi"].agg(["min", "max"])
        z_ozet["sure_dk"] = (z_ozet["max"] - z_ozet["min"]).dt.total_seconds() / 60
        z_ozet["ilk_sn"] = z_ozet["min"].dt.hour * 3600 + z_ozet["min"].dt.minute * 60 + z_ozet["min"].dt.second
        z_ozet["son_sn"] = z_ozet["max"].dt.hour * 3600 + z_ozet["max"].dt.minute * 60 + z_ozet["max"].dt.second
        z_ozet = z_ozet.reset_index()
        
        if "İlk Kontak" in df_temp.columns and "Son Kontak" in df_temp.columns:
            kontak_gunluk = (
                df_temp.dropna(subset=["İlk Kontak", "Son Kontak"])
                .groupby(["Personel", "Calisma_Gunu"])
                .agg(ilk_kontak_ts=("İlk Kontak", "first"), son_kontak_ts=("Son Kontak", "first"))
                .reset_index()
            )
            kontak_gunluk["ilk_kontak_sn"] = kontak_gunluk["ilk_kontak_ts"].apply(
                lambda v: v.hour * 3600 + v.minute * 60 + v.second if pd.notna(v) else np.nan
            )
            kontak_gunluk["son_kontak_sn"] = kontak_gunluk["son_kontak_ts"].apply(
                lambda v: v.hour * 3600 + v.minute * 60 + v.second if pd.notna(v) else np.nan
            )
            z_ozet = z_ozet.merge(
                kontak_gunluk[["Personel", "Calisma_Gunu", "ilk_kontak_sn", "son_kontak_sn"]],
                on=["Personel", "Calisma_Gunu"],
                how="left",
            )
        
        extra_cols = [c for c in ["ilk_kontak_sn", "son_kontak_sn"] if c in z_ozet.columns]
        df_temp = df_temp.merge(
            z_ozet[["Personel", "Calisma_Gunu", "sure_dk", "ilk_sn", "son_sn"] + extra_cols],
            on=["Personel", "Calisma_Gunu"], how="left"
        )

        if "BÖLGE" not in df_temp.columns:
            if "Ekip_Bolge" in df_temp.columns:
                df_temp["BÖLGE"] = df_temp["Ekip_Bolge"]
            else:
                df_temp["BÖLGE"] = "Bilinmiyor"
        
        _TREND_CACHE[cache_key] = df_temp
    
    df_cached = _TREND_CACHE[cache_key]

    if selected_kpi in ["Ort. Kofra", "Ort. İş", "Toplam Kofra", "Toplam İş"]:
        if selected_kpi.startswith("Ort."):
            if selected_kpi == "Ort. Kofra":
                p_gunluk = df_cached.groupby(["Calisma_Gunu", "BÖLGE", "Personel"])["Kofra"].nunique().reset_index(name="value")
            else:
                p_gunluk = df_cached.groupby(["Calisma_Gunu", "BÖLGE", "Personel"])["Kofra"].count().reset_index(name="value")
            daily = p_gunluk.groupby(["Calisma_Gunu", "BÖLGE"])["value"].mean().reset_index(name=selected_kpi)
        else:
            if selected_kpi == "Toplam Kofra":
                daily = df_cached.groupby(["Calisma_Gunu", "BÖLGE"])["Kofra"].nunique().reset_index(name=selected_kpi)
            else:
                daily = df_cached.groupby(["Calisma_Gunu", "BÖLGE"])["Kofra"].count().reset_index(name=selected_kpi)
    else:
        col_map = {"Ort. Süre (Dk)": "sure_dk", "ilk_sn": "ilk_sn", "son_sn": "son_sn",
                   "ilk_kontak_sn": "ilk_kontak_sn", "son_kontak_sn": "son_kontak_sn"}
        col = col_map.get(selected_kpi, selected_kpi)
        if col in df_cached.columns:
            daily = df_cached.groupby(["Calisma_Gunu", "BÖLGE"])[col].mean().reset_index(name=selected_kpi)
        else:
            return pd.DataFrame()

    return daily

# ======================================================
# TABLO OLUŞTURUCU
# ======================================================

def build_kpi_cards(rows_keys, metrics_dict, styles):
    """Üst bilgi KPI kartlarını her satır ayrı tablo olacak şekilde oluştur."""
    
    def saniye_to_int(s):
        try:
            if ":" in s:
                h, m = map(int, s.split(":"))
                return h * 3600 + m * 60
            return float(s.replace('.', '').replace(',', '.'))
        except:
            return 0
    
    def calculate_prev_value(val_str, delta_str, is_time=False):
        if not delta_str or not isinstance(delta_str, str) or not delta_str.endswith('%'):
            return None
        try:
            # Parse delta
            percent = float(delta_str[:-1].replace(',', '.'))
            if is_time:
                current = saniye_to_int(val_str)
                prev = current / (1 + percent / 100)
                return saniye_formatla(prev)
            else:
                current = float(val_str.replace('.', '').replace(',', '.'))
                prev = current / (1 + percent / 100)
                return format_tr_number(prev, 1)
        except:
            return None
    
    tables = []
    
    for row_keys in rows_keys:
        num_cols = len(row_keys)
        # Sütun genişliklerini toplam genişliğe (780) göre ayarla
        total_w = 780
        col_w = total_w / 4 # 4 sütun genişliğinde kutular için standart birim
        
        # Eğer 3 sütunluysa, yine 4 sütun genişliği kadar yer kaplamasın diye toplam genişliği daraltabiliriz
        # ya da her sütunu biraz daha genişletip sayfayı kaplatabiliriz.
        # Kullanıcı "ortala" dediği için, 3 sütunu 4 sütun biriminde tutup ortalayacağız.
        row_table_w = col_w * num_cols
        
        row_data = []
        label_row = [Paragraph(f"<b>{l}</b>", styles['CardText']) for l in row_keys]
        value_row = []
        for l in row_keys:
            v = metrics_dict.get(l, (None, None))
            if v == (None, None) or l == "":
                value_row.append(Paragraph("", styles['CardValue']))
            else:
                val, delta = v
                if delta and isinstance(delta, str):
                    # Kötüye gidişin "artış" olduğu metrikler
                    reverse_metrics = ["Ort. İş Arası Süre", "Ort. İlk İş", "İlk Kontak Ort."]
                    is_reverse = any(rm in l for rm in reverse_metrics)
                    
                    if delta.startswith("+"):
                        delta_color = "red" if is_reverse else "green"
                    elif delta.startswith("-"):
                        delta_color = "green" if is_reverse else "red"
                    else:
                        delta_color = "gray"
                    
                    is_time_metric = l in ["Ort. İlk İş", "Ort. Son İş", "İlk Kontak Ort.", "Son Kontak Ort."]
                    prev_val = calculate_prev_value(val, delta, is_time=is_time_metric)
                    if prev_val:
                        text = f"{val}<br/><font color='{delta_color}' size='8'>{prev_val} ({delta})</font>"
                    else:
                        text = f"{val}<br/><font color='{delta_color}' size='10'>{delta}</font>"
                else:
                    text = f"{val}"
                value_row.append(Paragraph(text, styles['CardValue']))
                
        row_data.append(label_row)
        row_data.append(value_row)
        
        t = Table(row_data, colWidths=[col_w]*num_cols)
        t.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#fca5a5')),
            ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#fecdd3')),
            ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fff5f5')),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ]))
        
        # Tabloyu ortalamak için hAlign kullanıyoruz
        t.hAlign = 'CENTER'
        tables.append(t)
        # Satırlar arası çok küçük bir boşluk veya sıfır boşluk
        # tables.append(Spacer(1, 1)) # Opsiyonel
        
    return tables

def build_data_table(df, columns, title, styles, max_rows=50):
    """Bölge/Personel DataFrame'den temiz, profesyonel PDF tablosu oluştur."""
    elements = []
    elements.append(Paragraph(title, styles['SectionTitle']))
    elements.append(Spacer(1, 8))
    
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return elements
    
    display_df = df[cols].head(max_rows).copy()
    
    # Header
    header = [Paragraph(f"<b>{c}</b>", ParagraphStyle('th', fontSize=8, alignment=TA_CENTER, fontName=FONT_BOLD, textColor=colors.white)) for c in cols]
    data = [header]
    
    for _, row in display_df.iterrows():
        r = []
        for c in cols:
            val = row[c]
            if pd.isna(val):
                val = "-"
            else:
                val = str(val)
            r.append(Paragraph(val, ParagraphStyle('td', fontSize=8, alignment=TA_CENTER, fontName=FONT_REGULAR)))
        data.append(r)
    
    n_cols = len(cols)
    avail_w = 780
    col_w = avail_w / n_cols
    
    # Tablo bölündüğünde başlığı tekrarla (repeatRows=1)
    t = Table(data, colWidths=[col_w]*n_cols, repeatRows=1)
    style_cmds = [
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#991b1b')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#fca5a5')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#991b1b')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    # Zebra striping
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f5f5f5')))
    
    t.setStyle(TableStyle(style_cmds))
    elements.append(t)
    return elements

def build_region_table(df, columns, title, styles, secilen_bolge, max_rows=50):
    """Bölge tablosu için renk kodlamalı oluştur."""
    
    def parse_value(val_str):
        try:
            if ":" in val_str:
                h, m = map(int, val_str.split(":"))
                return h * 3600 + m * 60
            else:
                return float(val_str.replace('.', '').replace(',', '.'))
        except:
            return None
    
    elements = []
    elements.append(Paragraph(title, styles['SectionTitle']))
    elements.append(Spacer(1, 8))
    
    cols = [c for c in columns if c in df.columns]
    if not cols:
        return elements
    
    display_df = df[cols].head(max_rows).copy()
    
    # Genel şirket ortalaması
    genel_row = display_df[display_df["BÖLGE"] == "Genel Şirket Ortalaması"]
    genel_values = {}
    if not genel_row.empty:
        for c in cols:
            if c in genel_row.columns:
                val = genel_row[c].iloc[0]
                genel_values[c] = parse_value(str(val))
    
    # Header
    header = [Paragraph(f"<b>{c}</b>", ParagraphStyle('th', fontSize=8, alignment=TA_CENTER, fontName=FONT_BOLD, textColor=colors.white)) for c in cols]
    data = [header]
    
    for _, row in display_df.iterrows():
        r = []
        bolge_adi = row["BÖLGE"]
        is_bolge = bolge_adi != "Genel Şirket Ortalaması"
        for c in cols:
            val = row[c]
            if pd.isna(val):
                val = "-"
            else:
                val = str(val)
            
            # Renk kodlaması sadece bölge satırları için ve belirli sütunlarda
            if is_bolge and secilen_bolge != "Tümü" and c in ["Ort. Kofra", "Ort. İş", "Ort. İlk İş", "İlk Kontak (Ort.)", "Ort. Son İş", "Son Kontak (Ort.)", "Ort. Süre (Dk)", "Ort. İş Arası Süre"]:
                bolge_val = parse_value(str(row[c]))
                genel_val = genel_values.get(c)
                if bolge_val is not None and genel_val is not None:
                    # Reverse metrics: yüksek değer kötü
                    reverse_metrics = ["Ort. İş Arası Süre", "Ort. İlk İş", "İlk Kontak (Ort.)"]
                    is_reverse = c in reverse_metrics
                    if bolge_val > genel_val:
                        color = "red" if is_reverse else "green"
                    elif bolge_val < genel_val:
                        color = "green" if is_reverse else "red"
                    else:
                        color = "black"
                    r.append(Paragraph(f"<font color='{color}'>{val}</font>", ParagraphStyle('td', fontSize=8, alignment=TA_CENTER, fontName=FONT_REGULAR)))
                    continue
            r.append(Paragraph(val, ParagraphStyle('td', fontSize=8, alignment=TA_CENTER, fontName=FONT_REGULAR)))
        data.append(r)
    
    n_cols = len(cols)
    avail_w = 780
    col_w = avail_w / n_cols
    
    # Tablo bölündüğünde başlığı tekrarla (repeatRows=1)
    t = Table(data, colWidths=[col_w]*n_cols, repeatRows=1)
    style_cmds = [
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#0d47a1')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('INNERGRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#cfd8dc')),
        ('BOX', (0, 0), (-1, -1), 1, colors.HexColor('#0d47a1')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]
    # Zebra striping
    for i in range(1, len(data)):
        if i % 2 == 0:
            style_cmds.append(('BACKGROUND', (0, i), (-1, i), colors.HexColor('#f5f5f5')))
    
    t.setStyle(TableStyle(style_cmds))
    elements.append(t)
    return elements

# ======================================================
# GRAFİK OLUŞTURUCULAR (MATPLOTLIB)
# ======================================================

# Renk paleti (trend çizgileri için)
_PRISM_COLORS = ['#5f4690','#1d6996','#38a6a5','#0f8554','#73af48',
                 '#edad08','#e17c05','#cc503e','#94346e','#6f4070']

def create_bolge_bar_chart(b_filtreli_rapor, selected_kpi, selected_kpi_display, kpi_format):
    """Bölge karşılaştırma bar chart (matplotlib)."""
    grafik_df = b_filtreli_rapor.copy()
    genel_kpi_value = 0
    if "BÖLGE" in grafik_df.columns and selected_kpi in grafik_df.columns:
        genel_satir = grafik_df[grafik_df["BÖLGE"] == "Genel Şirket Ortalaması"]
        if not genel_satir.empty:
            genel_kpi_value = float(genel_satir[selected_kpi].iloc[0])

    bolge_df = grafik_df[grafik_df["BÖLGE"] != "Genel Şirket Ortalaması"].copy()
    if bolge_df.empty or selected_kpi not in bolge_df.columns:
        return None

    x_labels = list(bolge_df["BÖLGE"])
    y_numeric = list(bolge_df[selected_kpi].fillna(0))
    
    if kpi_format == "time":
        y_text = [saniye_formatla(v) for v in y_numeric]
        genel_str = saniye_formatla(genel_kpi_value)
    elif selected_kpi in ["Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun"]:
        y_text = [format_tr_number(v, 0) for v in y_numeric]
        genel_str = format_tr_number(genel_kpi_value, 1 if genel_kpi_value % 1 != 0 else 0)
    else:
        decimals = 0 if "Adet" in selected_kpi_display else 1
        force_decimals = "kWh" in selected_kpi_display
        y_text = [format_tr_number(v, decimals, force_decimals) for v in y_numeric]
        genel_str = format_tr_number(genel_kpi_value, decimals, force_decimals)

    fig, ax = plt.subplots(figsize=(8.5, 5.0))
    fig.set_facecolor('#fff5f5')
    ax.set_facecolor('#fff5f5')
    
    bars = ax.bar(range(len(x_labels)), y_numeric, color='#dc2626', width=0.5, edgecolor='white')
    
    # Dinamik font boyutu ve Rotasyon
    label_fs = 19 if len(x_labels) <= 15 else 16 if len(x_labels) <= 25 else 13
    rotation = 45 if len(x_labels) > 15 else 0
    
    for i, (bar, txt) in enumerate(zip(bars, y_text)):
        ax.text(bar.get_x() + bar.get_width()/2, bar.get_height(), txt,
                ha='center', va='bottom', fontsize=label_fs, fontweight='bold', rotation=rotation)
    
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels, rotation=35, ha='right', fontsize=13)
    ax.set_ylabel(selected_kpi_display, fontsize=14)
    y_max = max(y_numeric) if y_numeric and max(y_numeric) > 0 else 1
    ax.set_ylim(0, y_max * 1.35)
    ax.set_title(f"Bölge Karşılaştırması (Şirket Geneli: {genel_str})", 
                 fontsize=20, color="#991b1b", fontweight='bold')
    ax.grid(axis='y', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    return fig

def create_personel_bar_chart(filtreli_rapor_filtreli, selected_kpi, selected_kpi_display, kpi_format):
    """Personel karşılaştırma bar chart - En iyi/kötü 5 (matplotlib)."""
    df_p = filtreli_rapor_filtreli.copy()
    
    # Zaman metriklerinde verisi olmayanları (NaN veya 0) grafikten çıkar (00:00 sorunu)
    time_cols_to_filter = ["ilk_sn", "son_sn", "ilk_kontak_sn", "son_kontak_sn", "Ort. Süre (Dk)", "Ort. İş Arası Süre"]
    if selected_kpi in time_cols_to_filter:
        df_p = df_p[df_p[selected_kpi].notna() & (df_p[selected_kpi] > 0)]
        
    if df_p.empty or selected_kpi not in df_p.columns:
        return None
    
    count = len(df_p)
    if count <= 10:
        grafik_df = df_p.sort_values(selected_kpi)[["ADI SOYADI", "BÖLGE", selected_kpi]].copy()
        cutoff = count // 2
        clrs = ["#ef5350" if i < cutoff else "#66bb6a" for i in range(count)]
        y_numeric = list(grafik_df[selected_kpi].fillna(0))
        decimals = 0 if "Adet" in selected_kpi_display else 1
        force_decimals = "kWh" in selected_kpi_display
        y_text = [saniye_formatla(v) for v in y_numeric] if kpi_format == "time" else [format_tr_number(v, decimals, force_decimals) for v in y_numeric]
        x_labels = grafik_df.apply(lambda r: f"{str(r['ADI SOYADI']).split(' ')[0]} ({r['BÖLGE']})", axis=1).tolist()
        
        fig, ax = plt.subplots(figsize=(8.5, 5.0))
        fig.set_facecolor('#f0f4f8'); ax.set_facecolor('#f0f4f8')
        # Dinamik font boyutu ve Rotasyon (Daha da büyütüldü)
        label_fs = 19 if count <= 15 else 16
        rotation = 45 if count > 15 else 0
        
        bars = ax.bar(range(len(x_labels)), y_numeric, color=clrs, width=0.4)
        for bar, txt in zip(bars, y_text):
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height(), txt, ha='center', va='bottom', fontsize=label_fs, fontweight='bold', rotation=rotation)
        ax.set_xticks(range(len(x_labels)))
        ax.set_xticklabels(x_labels, rotation=40, ha='right', fontsize=11)
        y_max = max(y_numeric) if y_numeric and max(y_numeric) > 0 else 1
        y_min = min(y_numeric) if y_numeric else 0
        if y_min > 0 and (y_max - y_min) < y_max * 0.3:
            y_diff = y_max - y_min if y_max != y_min else y_max * 0.1
            ax.set_ylim(max(0, y_min - y_diff * 0.5), y_max + y_diff * 0.5)
        else:
            ax.set_ylim(0, y_max * 1.35)
    else:
        top = df_p.nlargest(5, selected_kpi)[["ADI SOYADI", "BÖLGE", selected_kpi]].sort_values(selected_kpi)
        bot = df_p.nsmallest(5, selected_kpi)[["ADI SOYADI", "BÖLGE", selected_kpi]].sort_values(selected_kpi)
        
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(8.5, 5.0))
        fig.set_facecolor('#f0f4f8')
        
        for ax_i, data, color, title in [(ax1, bot, "#ef5350", "En Kötü 5"), (ax2, top, "#66bb6a", "En İyi 5")]:
            ax_i.set_facecolor('#f0f4f8')
            y_vals = list(data[selected_kpi].fillna(0))
            decimals = 0 if "Adet" in selected_kpi_display else 1
            force_decimals = "kWh" in selected_kpi_display
            y_txt = [saniye_formatla(v) for v in y_vals] if kpi_format == "time" else [format_tr_number(v, decimals, force_decimals) for v in y_vals]
            x_lbl = data.apply(lambda r: str(r['ADI SOYADI']).split(' ')[0], axis=1).tolist()
            bars = ax_i.bar(range(len(x_lbl)), y_vals, color=color, width=0.5)
            for bar, txt in zip(bars, y_txt):
                ax_i.text(bar.get_x()+bar.get_width()/2, bar.get_height(), txt, ha='center', va='bottom', fontsize=11)
            ax_i.set_xticks(range(len(x_lbl)))
            ax_i.set_xticklabels(x_lbl, rotation=40, ha='right', fontsize=10)
            ax_i.set_title(title, fontsize=13, fontweight='bold')
            y_max = max(y_vals) if y_vals and max(y_vals) > 0 else 1
            y_min = min(y_vals) if y_vals else 0
            if y_min > 0 and (y_max - y_min) < y_max * 0.3:
                y_diff = y_max - y_min if y_max != y_min else y_max * 0.1
                ax_i.set_ylim(max(0, y_min - y_diff * 0.5), y_max + y_diff * 0.5)
            else:
                ax_i.set_ylim(0, y_max * 1.35)
            ax_i.grid(axis='y', alpha=0.3)
            ax_i.spines['top'].set_visible(False)
            ax_i.spines['right'].set_visible(False)
        ax = ax1

    ax.set_ylabel(selected_kpi_display, fontsize=12)
    fig.suptitle("Personel Karşılaştırma", fontsize=14, color="#0d47a1", fontweight='bold', y=1.02)
    ax.grid(axis='y', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    return fig

def create_personel_bar_chart_bolge(filtreli_rapor_filtreli, selected_kpi, selected_kpi_display, kpi_format):
    """Bölge seçiliyse: tüm personeli mavi tek renk bar chart (matplotlib)."""
    df_p = filtreli_rapor_filtreli.copy()
    
    # Zaman metriklerinde verisi olmayanları (NaN veya 0) grafikten çıkar (00:00 sorunu)
    time_cols_to_filter = ["ilk_sn", "son_sn", "ilk_kontak_sn", "son_kontak_sn", "Ort. Süre (Dk)", "Ort. İş Arası Süre"]
    if selected_kpi in time_cols_to_filter:
        df_p = df_p[df_p[selected_kpi].notna() & (df_p[selected_kpi] > 0)]
        
    if df_p.empty or selected_kpi not in df_p.columns:
        return None
    
    grafik_df = df_p.sort_values(selected_kpi, ascending=True)[["ADI SOYADI", "BÖLGE", selected_kpi]].copy()
    grafik_df = grafik_df.dropna(subset=[selected_kpi])
    if grafik_df.empty:
        return None
    
    y_numeric = list(grafik_df[selected_kpi].fillna(0))
    decimals = 0 if "Adet" in selected_kpi_display else 1
    force_decimals = "kWh" in selected_kpi_display
    y_text = [saniye_formatla(v) for v in y_numeric] if kpi_format == "time" else [format_tr_number(v, decimals, force_decimals) for v in y_numeric]
    # Soyisimleri de gösterelim (Tam isim)
    x_labels = grafik_df["ADI SOYADI"].apply(lambda n: str(n) if pd.notna(n) else "-").tolist()
    
    # Grafik genişliğini ve yüksekliğini ciddi oranda artırarak (1. madde)
    fig, ax = plt.subplots(figsize=(16.0, 6.0))
    fig.set_facecolor('#f0f4f8'); ax.set_facecolor('#f0f4f8')
    bars = ax.bar(range(len(x_labels)), y_numeric, color='#1e88e5', width=0.5, edgecolor='white')
    
    # Dinamik font boyutu ve Rotasyon (Daha da büyütüldü)
    label_fs = 20 if len(x_labels) <= 6 else 19 if len(x_labels) <= 15 else 17 if len(x_labels) <= 25 else 14
    rotation = 45 if len(x_labels) > 15 else 0
    
    # Sayıların boyutunu büyültelim (Siyah ve Kalın)
    for bar, txt in zip(bars, y_text):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height(), txt, ha='center', va='bottom', fontsize=label_fs, fontweight='bold', color='black', rotation=rotation)
        
    ax.set_xticks(range(len(x_labels)))
    ax.set_xticklabels(x_labels, rotation=45, ha='right', fontsize=13, fontweight='bold')
    y_max = max(y_numeric) if y_numeric and max(y_numeric) > 0 else 1
    y_min = min(y_numeric) if y_numeric else 0
    if y_min > 0 and (y_max - y_min) < y_max * 0.3:
        y_diff = y_max - y_min if y_max != y_min else y_max * 0.1
        ax.set_ylim(max(0, y_min - y_diff * 0.5), y_max + y_diff * 0.5)
    else:
        ax.set_ylim(0, y_max * 1.35)
    ax.set_ylabel(selected_kpi_display, fontsize=15, fontweight='bold')
    ax.set_title("Personel Karşılaştırma", fontsize=22, color="#0d47a1", fontweight='bold', pad=20)
    
    # Ortalamayı göster
    avg_value = grafik_df[selected_kpi].mean()
    ax.axhline(y=avg_value, color='red', linestyle='--', linewidth=2, label=f'Ortalama: {format_tr_number(avg_value, decimals, force_decimals) if not kpi_format == "time" else saniye_formatla(avg_value)}')
    ax.legend(loc='upper right', fontsize=14, prop={'weight':'bold'})
    
    ax.grid(axis='y', alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.tight_layout()
    return fig

def create_trend_chart(daily_summary, selected_kpi, selected_kpi_display, secilen_bolge="Tümü"):
    """Günlük trend line chart (matplotlib)."""
    if daily_summary is None or daily_summary.empty:
        return None
    daily_summary = daily_summary[daily_summary["BÖLGE"] != "Bilinmiyor"]
    if daily_summary.empty:
        return None

    is_time = selected_kpi in ["ilk_sn", "son_sn", "ilk_kontak_sn", "son_kontak_sn"]
    daily_avg = daily_summary.groupby("Calisma_Gunu")[selected_kpi].mean().reset_index()
    
    fig, ax = plt.subplots(figsize=(12.0, 4.5))
    fig.set_facecolor('#f0f4f8'); ax.set_facecolor('#f0f4f8')
    
    if secilen_bolge != "Tümü":
        bd_raw = daily_summary[daily_summary["BÖLGE"] == secilen_bolge]
        # Günlük bazda gruplayalım ki çizgiler iç içe geçmesin (Messy görünüm engellenir)
        bd = bd_raw.groupby("Calisma_Gunu")[selected_kpi].mean().reset_index().sort_values("Calisma_Gunu")
        if not bd.empty:
            ax.plot(bd["Calisma_Gunu"], bd[selected_kpi], '-o', color="#1e88e5", 
                    linewidth=3, markersize=6, label=secilen_bolge)
        ax.plot(daily_avg["Calisma_Gunu"], daily_avg[selected_kpi], '-', 
                color="#d32f2f", linewidth=2.5, alpha=1.0, label="Şirket Ort.")
    else:
        bolge_list = sorted(daily_summary["BÖLGE"].unique())
        for i, bolge in enumerate(bolge_list):
            bd_raw = daily_summary[daily_summary["BÖLGE"] == bolge]
            bd = bd_raw.groupby("Calisma_Gunu")[selected_kpi].mean().reset_index().sort_values("Calisma_Gunu")
            clr = _PRISM_COLORS[i % len(_PRISM_COLORS)]
            ax.plot(bd["Calisma_Gunu"], bd[selected_kpi], '-o', color=clr, 
                    linewidth=1.5, markersize=4, label=bolge)
        ax.plot(daily_avg["Calisma_Gunu"], daily_avg[selected_kpi], '--', 
                color="#d32f2f", linewidth=2, label="Şirket Ort.")

    if is_time:
        if secilen_bolge != "Tümü" and 'bd' in locals() and not bd.empty:
            plot_df = pd.concat([bd, daily_avg])
            y_min = plot_df[selected_kpi].min()
            y_max = plot_df[selected_kpi].max()
        else:
            y_min = daily_summary[selected_kpi].min()
            y_max = daily_summary[selected_kpi].max()
        if pd.isna(y_min) or pd.isna(y_max):
            y_min, y_max = 28800, 64800 # 08:00 - 18:00
            
        # Farkın belli olması için ekseni verilere göre daraltalım (Smart Scaling)
        y_diff = y_max - y_min
        if y_diff < 3600: y_diff = 3600 # Min 1 saatlik pencere
        
        # %15 alt ve üst boşluk bırakalım
        ax.set_ylim(y_min - y_diff*0.15, y_max + y_diff*0.15)
        
        # Tick aralığını verilere göre belirleyelim (30 dk veya 1 saat)
        tick_interval = 1800 if y_diff <= 10800 else 3600
        tick_start = int(np.floor((y_min - y_diff*0.15) / tick_interval) * tick_interval)
        tick_end = int(np.ceil((y_max + y_diff*0.15) / tick_interval) * tick_interval)
        tickvals = list(range(tick_start, tick_end + 1, tick_interval))
        
        ax.set_yticks(tickvals)
        ax.set_yticklabels([saniye_formatla(v) for v in tickvals])
    else:
        # Sayısal metrikler için de (kWh, Adet vb.) 0'dan başlatmak yerine verilere odaklanalım
        if secilen_bolge != "Tümü" and 'bd' in locals() and not bd.empty:
            plot_df = pd.concat([bd, daily_avg])
            y_min = plot_df[selected_kpi].min()
            y_max = plot_df[selected_kpi].max()
        else:
            y_min = daily_summary[selected_kpi].min()
            y_max = daily_summary[selected_kpi].max()
        if not pd.isna(y_min) and not pd.isna(y_max):
            y_diff = y_max - y_min
            if y_diff == 0: y_diff = y_max * 0.2 if y_max != 0 else 1
            ax.set_ylim(y_min - y_diff*0.2, y_max + y_diff*0.2)

    ax.set_xlabel("Tarih", fontsize=12)
    ax.set_ylabel(selected_kpi_display, fontsize=12)
    ax.set_title(f"Zamana Bağlı {selected_kpi_display} Trendi", fontsize=14, color="#991b1b", fontweight='bold')
    ax.legend(fontsize=9, loc='upper center', bbox_to_anchor=(0.5, -0.15), ncol=5)
    ax.grid(True, alpha=0.3)
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    fig.autofmt_xdate(rotation=30)
    fig.tight_layout()
    return fig

# ======================================================
# PAGE TEMPLATES (KAPAK VE İÇ SAYFALAR)
# ======================================================

def _draw_background_and_logo(canvas, cover_image_path=None):
    """Tüm sayfalarda arka plan ve logo çizer."""
    w, h = landscape(A4)
    
    if cover_image_path and os.path.exists(cover_image_path):
        canvas.drawImage(cover_image_path, 0, 0, width=w, height=h, preserveAspectRatio=False)
        # Add a very light overlay so text is highly readable
        canvas.setFillColorRGB(1, 1, 1, alpha=0.3)
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
    else:
        # Fallback gradient/color
        canvas.setFillColor(colors.HexColor('#0a192f'))
        canvas.rect(0, 0, w, h, fill=1, stroke=0)
        
        # Draw some abstract lines
        canvas.setStrokeColor(colors.HexColor('#172a45'))
        canvas.setLineWidth(2)
        for i in range(0, int(w), 50):
            canvas.line(i, 0, i+200, h)
            



class CoverPageTemplate(PageTemplate):
    def __init__(self, id, cover_image_path=None):
        self.cover_image_path = cover_image_path
        # Frame covers entire page
        frame = Frame(0, 0, landscape(A4)[0], landscape(A4)[1], id='cover_frame', 
                      leftPadding=20*mm, rightPadding=20*mm, bottomPadding=20*mm, topPadding=20*mm)
        super().__init__(id=id, frames=[frame])

    def beforeDrawPage(self, canvas, doc):
        canvas.saveState()
        _draw_background_and_logo(canvas, self.cover_image_path)
        canvas.restoreState()

class ContentPageTemplate(PageTemplate):
    def __init__(self, id, cover_image_path=None):
        self.cover_image_path = cover_image_path
        # Daraltılmış kenar boşlukları (15mm -> 5mm) ile tam sayfa yerleşimi
        frame = Frame(5*mm, 15*mm, landscape(A4)[0] - 10*mm, landscape(A4)[1] - 20*mm, id='content_frame')
        super().__init__(id=id, frames=[frame])

    def beforeDrawPage(self, canvas, doc):
        canvas.saveState()
        w, h = landscape(A4)
        
        # Arka plan ve logo (tüm sayfalarda)
        _draw_background_and_logo(canvas, self.cover_image_path)
        
        # Footer Line
        canvas.setStrokeColor(colors.HexColor('#b0bec5'))
        canvas.setLineWidth(1)
        canvas.line(5*mm, 12*mm, w - 5*mm, 12*mm)
        
        # Footer - Sadece sayfa numarası (sağ alt)
        canvas.setFillColor(colors.HexColor('#78909c'))
        canvas.setFont(FONT_REGULAR, 8)
        canvas.drawRightString(w - 5 * mm, 6 * mm, f"Sayfa {doc.page}")
        
        canvas.restoreState()


# ======================================================
# ANA PDF OLUŞTURUCU
# ======================================================

def generate_pdf_bulletin(
    filtreli_rapor_filtreli,
    b_filtreli_rapor,
    df_base,
    baslangic, bitis,
    secilen_bolge,
    metrics_dict,
    all_kpis,
    heat_data,
    cover_image_path=None,
    prev_baslangic=None,
    prev_bitis=None,
):
    """
    Tüm dashboard verilerini profesyonel PDF bültenine dönüştürür.
    all_kpis: dict (Görünür İsim -> Sütun İsmi)
    """
    # Cache'i temizle (her yeni bülten için temiz veri)
    global _TREND_CACHE
    _TREND_CACHE = {}
    
    buffer = io.BytesIO()
    
    doc = BaseDocTemplate(
        buffer,
        pagesize=landscape(A4),
        title="Operasyon Analiz Bülteni",
        author="KSO Sistemleri",
    )
    
    doc.addPageTemplates([
        CoverPageTemplate('Cover', cover_image_path),
        ContentPageTemplate('Content', cover_image_path)
    ])
    
    styles = get_styles()
    elements = []
    
    # ==========================================
    # 1. KAPAK SAYFASI (Sadece Cover Template)
    # ==========================================
    elements.append(Spacer(1, 150))
    elements.append(Paragraph("MTH BÜLTENİ", styles['CoverTitle']))
    elements.append(Paragraph("MÜŞTERİ OPERASYONLARI DİREKTÖRLÜĞÜ", styles['CoverSubTitle']))
    elements.append(Spacer(1, 20))
    
    tarih_str = f"{baslangic.strftime('%d.%m.%Y')} - {bitis.strftime('%d.%m.%Y')}"
    bolge_str = secilen_bolge if secilen_bolge != "Tümü" else "Tüm Bölgeler"
    
    elements.append(Paragraph(f"Analiz Dönemi: <b>{tarih_str}</b>", styles['CoverDate']))
    elements.append(Paragraph(f"Bölge Kapsamı: <b>{bolge_str}</b>", styles['CoverDate']))
    
    # Sayfa sonu, Content template'e geç
    elements.append(NextPageTemplate('Content'))
    elements.append(PageBreak())
    
    # ==========================================
    # 2. ÖZET METRİKLER VE ISI HARİTASI
    # ==========================================
    # Kıyaslanan dönem bilgisini özet sayfasına da ekle
    if prev_baslangic and prev_bitis:
        prev_str = f"{prev_baslangic.strftime('%d.%m.%Y')} - {prev_bitis.strftime('%d.%m.%Y')}"
        elements.append(Paragraph(f"Kıyaslanan Önceki Dönem: <b>{prev_str}</b>", styles['CoverDate']))
        elements.append(Spacer(1, 6))
    elements.append(Paragraph("Özet", styles['SectionTitle']))
    
    # KPI Kartları (Sadece mevcut metrikler gösterilecek)
    summary_rows = [
        ["Aktif Personel", "Ort. Puan", "Ort. Kofra", "Ort. İş"],
        ["Ort. İlk İş", "Ort. Son İş", "Ort. İş Arası Süre", "Ort. Süre (Dk)"],
        ["Ort. İlk Kontak", "Ort. Son Kontak", "Ort. Mesafe"]
    ]
    # Sadece metrics_dict içinde veri bulunan satırları dahil et
    valid_summary_rows = []
    for r in summary_rows:
        filtered_r = [k for k in r if k in metrics_dict and metrics_dict[k] != (None, None)]
        if filtered_r:
            valid_summary_rows.append(filtered_r)
    if not valid_summary_rows:
        valid_summary_rows = summary_rows
    
    kpi_tables = build_kpi_cards(valid_summary_rows, metrics_dict, styles)
    for table in kpi_tables:
        elements.append(table)
    elements.append(Spacer(1, 10))
    
    # Isı Haritası - Sadece bölge seçiliyse ve KENDİ SAYFASINDA (Tam Sayfa)
    if secilen_bolge != "Tümü" and heat_data is not None and not heat_data.empty:
        elements.append(PageBreak()) # Haritayı yeni sayfaya al
        # Büyütülmüş render
        heatmap_img = create_heatmap_image(heat_data, 2000, 1200, secilen_bolge)
        if heatmap_img:
            # Sayfa boyutuna göre (Landscape A4: 842x595 pt) maksimize et
            # Alt/üst boşlukları (footer vb) koruyarak büyütüyoruz
            heatmap_img.drawWidth = 780
            heatmap_img.drawHeight = 480
            
            t = Table([[heatmap_img]], colWidths=[800])
            t.setStyle(TableStyle([
                ('ALIGN', (0,0), (-1,-1), 'CENTER'),
                ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
                ('TOPPADDING', (0,0), (-1,-1), 0),
            ]))
            elements.append(t)
            elements.append(PageBreak()) # Haritadan sonra yeni sayfa
    else:
        # Harita yoksa bile özet sayfasından sonra bir break olsun (eğer tabloya geçecekse)
        elements.append(PageBreak())
    
    # ==========================================
    # GRAFİKLERİN SIRALI RENDER EDİLMESİ (ÖNCELİKLİ)
    # ==========================================
    # KPI Grafik görevlerini topla
    if isinstance(all_kpis, dict):
        kpi_items = list(all_kpis.items())
    else:
        kpi_items = []
    
    total_kpi = len(kpi_items)
    print(f"--- PDF Render Baslatildi ({total_kpi} KPI) ---")
    t_start_all = time.time()
        
    if secilen_bolge != "Tümü":
        son_tarih = bitis
        bir_ay_once = son_tarih - datetime.timedelta(days=30)
        df_base_trend = df_base[
            (df_base["Çizelgeleme Tarihi"].dt.date >= bir_ay_once) &
            (df_base["Çizelgeleme Tarihi"].dt.date <= son_tarih)
        ].copy()
    else:
        df_base_trend = None

    # Sıralı Render İşlemi
    rendered_images = {}
    pie_raw_data = {}
    grafik_sayaci = 0
    
    # Pasta grafikleri için verileri parse et (metrics_dict içinden)
    def parse_metric_val(key):
        if key not in metrics_dict: return 0
        val_str = str(metrics_dict[key][0])
        clean_val = val_str.replace(".", "").replace(",", ".")
        try: return float(clean_val)
        except: return 0

    # Pasta grafikleri her iki modda da (Tümü/Bölge) oluşturulmalı
    # Kaçak Personel Adet Pasta Grafiği
    t_adet = parse_metric_val("Toplam Kaçak Adet")
    p_adet = parse_metric_val("Kaçak Personel Adet")
    pie_raw_data["Kaçak Personel Adet"] = (t_adet, p_adet)
    f_pie_adet = create_pie_chart(t_adet, p_adet, "Kaçak Adet Payı")
    if f_pie_adet:
        rendered_images[("pie", "Kaçak Personel Adet")] = mpl_fig_to_rlimage(f_pie_adet, 600, 600)
        
    # Kaçak Personel kWh Pasta Grafiği
    t_kwh = parse_metric_val("Toplam kWh")
    p_kwh = parse_metric_val("Kaçak Personel kWh")
    pie_raw_data["Kaçak Personel kWh"] = (t_kwh, p_kwh)
    f_pie_kwh = create_pie_chart(t_kwh, p_kwh, "Kaçak kWh Payı")
    if f_pie_kwh:
        rendered_images[("pie", "Kaçak Personel kWh")] = mpl_fig_to_rlimage(f_pie_kwh, 600, 600)

    # Nitelikli Adet
    t_n_adet = parse_metric_val("Toplam Nitelikli Adet")
    p_n_adet = parse_metric_val("Kaçak Personel Nitelikli Adet")
    pie_raw_data["Kaçak Personel Nitelikli Adet"] = (t_n_adet, p_n_adet)
    f_pie_n_adet = create_pie_chart(t_n_adet, p_n_adet, "Nitelikli Adet Payı")
    if f_pie_n_adet:
        rendered_images[("pie", "Kaçak Personel Nitelikli Adet")] = mpl_fig_to_rlimage(f_pie_n_adet, 600, 600)
        
    # Nitelikli kWh
    t_n_kwh = parse_metric_val("Nitelikli kWh")
    p_n_kwh = parse_metric_val("Personel Nitelikli kWh")
    pie_raw_data["Personel Nitelikli kWh"] = (t_n_kwh, p_n_kwh)
    f_pie_n_kwh = create_pie_chart(t_n_kwh, p_n_kwh, "Nitelikli kWh Payı", label_personel="Personel")
    if f_pie_n_kwh:
        rendered_images[("pie", "Personel Nitelikli kWh")] = mpl_fig_to_rlimage(f_pie_n_kwh, 600, 600)
        
    # Niteliksiz Adet
    t_ns_adet = parse_metric_val("Toplam Niteliksiz Adet")
    p_ns_adet = parse_metric_val("Kaçak Personel Niteliksiz Adet")
    pie_raw_data["Kaçak Personel Niteliksiz Adet"] = (t_ns_adet, p_ns_adet)
    f_pie_ns_adet = create_pie_chart(t_ns_adet, p_ns_adet, "Niteliksiz Adet Payı")
    if f_pie_ns_adet:
        rendered_images[("pie", "Kaçak Personel Niteliksiz Adet")] = mpl_fig_to_rlimage(f_pie_ns_adet, 600, 600)
        
    # Niteliksiz kWh
    t_ns_kwh = parse_metric_val("Niteliksiz kWh")
    p_ns_kwh = parse_metric_val("Personel Niteliksiz kWh")
    pie_raw_data["Personel Niteliksiz kWh"] = (t_ns_kwh, p_ns_kwh)
    f_pie_ns_kwh = create_pie_chart(t_ns_kwh, p_ns_kwh, "Niteliksiz kWh Payı", label_personel="Personel")
    if f_pie_ns_kwh:
        rendered_images[("pie", "Personel Niteliksiz kWh")] = mpl_fig_to_rlimage(f_pie_ns_kwh, 600, 600)

    for idx, (display_name, col_name) in enumerate(kpi_items, 1):
        removed_kpis = ["Kaçak Personel İmza Sayısı", "Personel Nitelikli İmza Sayısı", "Personel Niteliksiz İmza Sayısı"]
        if display_name in removed_kpis:
            continue
        _, kpi_format = get_kpi_unit_and_format(col_name)
        if secilen_bolge == "Tümü":
            f_bolge = create_bolge_bar_chart(b_filtreli_rapor, col_name, display_name, kpi_format)
            if f_bolge:
                img = mpl_fig_to_rlimage(f_bolge, 850, 500)
                rendered_images[("bolge", display_name)] = img
                grafik_sayaci += 1
        if secilen_bolge != "Tümü":
            p_col = col_name
            p_display = display_name
            p_format = kpi_format
            if "Adet" in display_name:
                if "Nitelikli" in display_name and "Niteliksiz" not in display_name:
                    p_col = "Personel Nitelikli İmza Sayısı"
                elif "Niteliksiz" in display_name:
                    p_col = "Personel Niteliksiz İmza Sayısı"
                elif "Kaçak" in display_name:
                    p_col = "Kaçak Personel İmza Sayısı"
                p_format = "count"
            f_personel = create_personel_bar_chart_bolge(filtreli_rapor_filtreli, p_col, p_display, p_format)
            if f_personel:
                img = mpl_fig_to_rlimage(f_personel, 1600, 600)
                rendered_images[("personel", display_name)] = img
                grafik_sayaci += 1
            if df_base_trend is not None and not df_base_trend.empty:
                d_summary = prepare_trend_data_for_pdf(df_base_trend, col_name)
                f_trend = create_trend_chart(d_summary, col_name, display_name, secilen_bolge)
                if f_trend:
                    img = mpl_fig_to_rlimage(f_trend, 1600, 420)
                    rendered_images[("trend", display_name)] = img
                    grafik_sayaci += 1
    
    elapsed = time.time() - t_start_all
    print(f"--- Tum grafikler tamamlandi: {grafik_sayaci} grafik, {elapsed:.1f} saniye ---")

    # Helper function for Tümü mode KPI pages
    def add_kpi_page(kpi_list, title_override=None, include_guide=False, side_by_side=False):
        page_elements = []
        if title_override:
            if title_override == "Genel Performans Skoru":
                page_elements.append(Spacer(1, 5)) # 20 -> 5
                page_elements.append(Paragraph(title_override, styles['SectionTitle']))
                page_elements.append(Spacer(1, 5)) # 10 -> 5
        if side_by_side:
            row_cells = []
            aliases = {
                "Ort. İlk İş": "İlk İş", "İlk İş": "Ort. İlk İş",
                "İlk Kontak Ort.": "İlk Kontak", "İlk Kontak": "İlk Kontak Ort.",
                "Ort. Son İş": "Son İş", "Son İş": "Ort. Son İş",
                "Son Kontak Ort.": "Son Kontak", "Son Kontak": "Son Kontak Ort.",
                "Ort. Kofra": "Ort. Kofra", "Ort. İş": "Ort. İş"
            }
            for kpi in kpi_list:
                img = rendered_images.get(("bolge", kpi))
                target_kpi_name = kpi
                if not img and kpi in aliases:
                    img = rendered_images.get(("bolge", aliases[kpi]))
                    if img:
                        target_kpi_name = aliases[kpi]
                if img:
                    cell_content = [Paragraph(f"<b>{target_kpi_name}</b>", styles['ChartTitle']), Spacer(1, 5), img]
                    row_cells.append(cell_content)
                    used_kpis.add(kpi)
                    if kpi in aliases:
                        used_kpis.add(aliases[kpi])
            if row_cells:
                t_side = Table([row_cells], colWidths=[390]*len(row_cells))
                t_side.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 10), ('RIGHTPADDING', (0,0), (-1,-1), 10)]))
                t_outer = Table([[t_side]], colWidths=[800])
                t_outer.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('TOPPADDING', (0,0), (-1,-1), 50)]))
                page_elements.append(t_outer)
        else:
            for kpi in kpi_list:
                img = rendered_images.get(("bolge", kpi))
                if img:
                    if title_override:
                        page_elements.append(Paragraph(f"{kpi}", styles['ChartTitle']))
                        page_elements.append(Spacer(1, 5))
                    elif not title_override:
                        page_elements.append(Paragraph(f"{kpi}: Bölge Karşılaştırması", styles['SectionTitle']))
                        page_elements.append(Spacer(1, 10))
                    pie_img = rendered_images.get(("pie", kpi))
                    if pie_img:
                        page_elements.append(Spacer(1, 5))
                        raw = pie_raw_data.get(kpi, (0, 0))
                        t_val, p_val = raw
                        other_val = max(0, t_val - p_val)
                        unit = "kWh" if "kWh" in kpi else "Adet"
                        table_val_style = ParagraphStyle('TableVal', parent=styles['CardText'], fontSize=11, fontName=FONT_BOLD)
                        table_data = [[Paragraph(f"Toplam {unit}", table_val_style), Paragraph(f"{format_tr_number(t_val, 1 if unit=='kWh' else 0)}", table_val_style)], [Paragraph(f"Kaçak Personel {unit}", table_val_style), Paragraph(f"{format_tr_number(p_val, 1 if unit=='kWh' else 0)}", table_val_style)], [Paragraph(f"Beda+Mth {unit}", table_val_style), Paragraph(f"{format_tr_number(other_val, 1 if unit=='kWh' else 0)}", table_val_style)]]
                        t_info = Table(table_data, colWidths=[125, 75])
                        t_info.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'LEFT'), ('GRID', (0,0), (-1,-1), 0.5, colors.grey), ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f5f5f5')), ('TOPPADDING', (0,0), (-1,-1), 4), ('BOTTOMPADDING', (0,0), (-1,-1), 4)]))
                        pie_with_info = [pie_img, Spacer(1, 5), t_info]
                        t_side = Table([[pie_with_info]], colWidths=[250])
                        t_main = Table([[img, t_side]], colWidths=[530, 270])
                        t_main.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
                        page_elements.append(t_main)
                    else:
                        # Genel Skor sayfası için özel (grafiği küçült ve padding'i azalt)
                        # Puanlama rehberi ile aynı sayfada olduğu için yer kazanmamız gerekiyor
                        chart_padding = 60
                        if kpi == "Genel Skor" and include_guide:
                            img.drawWidth *= 0.85
                            img.drawHeight *= 0.85
                            chart_padding = 10
                            
                        t = Table([[img]], colWidths=[800])
                        t.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('TOPPADDING', (0,0), (-1,-1), chart_padding)]))
                        page_elements.append(t)
                        page_elements.append(Spacer(1, 5)) # 10 -> 5
                    used_kpis.add(kpi)
        if include_guide:
            page_elements.extend(build_scoring_guide(styles))
        if page_elements:
            page_table = Table([[page_elements]], colWidths=[800], rowHeights=[480])
            page_table.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
            elements.append(page_table)
            elements.append(PageBreak())

    used_kpis = set()

    # ==========================================
    # 3. VERİ TABLOLARI
    # ==========================================
    # Bölge Tablosu (Bölge adına göre sıralı, Genel Skor sütunu kaldırıldı)
    b_cols = ["BÖLGE", "Ort. Kofra", "Ort. İş", "Toplam Kofra", "Toplam İş",
              "Ort. İlk İş", "İlk Kontak (Ort.)", "Ort. Son İş", "Son Kontak (Ort.)", "Ort. Süre (Dk)", "Ort. İş Arası Süre",
              "Toplam Kaçak Adet", "Toplam kWh"]
    
    b_disp_df = b_filtreli_rapor.copy()
    
    # Genel Şirket Ortalamasını ayır, diğerlerini A-Z sırala, sonra birleştir
    genel_row = b_disp_df[b_disp_df["BÖLGE"] == "Genel Şirket Ortalaması"]
    other_rows = b_disp_df[b_disp_df["BÖLGE"] != "Genel Şirket Ortalaması"]
    
    if secilen_bolge != "Tümü":
        other_rows = other_rows[other_rows["BÖLGE"] == secilen_bolge]
        
    other_rows = other_rows.sort_values("BÖLGE", ascending=True)
    b_disp_df = pd.concat([other_rows, genel_row])

    # Bölge Tablosu Formatlamaları
    for c in ["Ort. Kofra", "Ort. İş", "Ort. Mesafe", "Ort. Süre (Dk)", "Kaçak Personel kWh",
              "Toplam kWh", "Toplam Nitelikli kWh", "Toplam Niteliksiz kWh", "Genel_Skor"]:
        if c in b_disp_df.columns:
            b_disp_df[c] = b_disp_df[c].apply(lambda x: format_tr_number(x, 1) if pd.notna(x) else "0")
    for c in ["Toplam Kofra", "Toplam İş", "Kaçak Personel Adet", "Kaçak Personel Nitelikli Adet", "Kaçak Personel Niteliksiz Adet",
              "Toplam Kaçak Adet", "Toplam Nitelikli Adet", "Toplam Niteliksiz Adet"]:
        if c in b_disp_df.columns:
            b_disp_df[c] = b_disp_df[c].apply(lambda x: format_tr_number(x, 0) if pd.notna(x) else "0")
    for c in ["Uzun Öğle", "İlk İş Uzun", "Son-Önceki İş Uzun"]:
        if c in b_disp_df.columns:
            b_disp_df[c] = b_disp_df[c].apply(lambda x: format_tr_number(x, 1 if pd.notna(x) and float(x) % 1 != 0 else 0) if pd.notna(x) else "0")
            
    b_table_elements = build_region_table(b_disp_df, b_cols, "Bölge Bazlı Performans Özeti", styles, secilen_bolge, max_rows=20)
    elements.extend(b_table_elements)
    
    # Bölge tablosu ile Personel tablosu arasına sayfa sonu ekle
    elements.append(PageBreak())
    
    # 27.04.2024: Bölge Tümü modunda Genel Skor sayfasını öne al (Sayfa 4)
    if secilen_bolge == "Tümü":
        add_kpi_page(["Genel Skor"], "Genel Performans Skoru", include_guide=True)
    
    # Personel Tablosu (Formatlanmış)
    p_cols = ["ADI SOYADI", "BÖLGE", "Skor", "Gün Sayısı", "Ort. Kofra", "Ort. İş",
              "Kaçak Personel İmza Sayısı", "Kaçak Personel kWh", "İlk İş (Ort.)", "İlk Kontak (Ort.)", "Son İş (Ort.)", "Son Kontak (Ort.)", "Ort. Süre (Dk)"]
    
    disp_df = filtreli_rapor_filtreli.copy()
    
    # Sıralama (Skora göre) - Sadece bölge seçili ise (formatlamadan önce)
    if secilen_bolge != "Tümü" and "Genel_Skor" in disp_df.columns:
        sort_idx = disp_df["Genel_Skor"].fillna(0).sort_values(ascending=False).index
        disp_df = disp_df.loc[sort_idx]
    
    if "Genel_Skor" in disp_df.columns:
        if "Skor" in disp_df.columns:
            disp_df = disp_df.drop(columns=["Skor"])
        disp_df = disp_df.rename(columns={"Genel_Skor": "Skor"})
        
    for c in ["Ort. Kofra", "Ort. İş", "Kaçak Personel kWh", "Personel Nitelikli kWh", "Personel Niteliksiz kWh", "Ort. Süre (Dk)", "Skor"]:
        if c in disp_df.columns:
            disp_df[c] = disp_df[c].apply(lambda x: format_tr_number(x, 1) if pd.notna(x) else "0")
    for c in ["Gün Sayısı", "Kaçak Personel İmza Sayısı", "Kaçak Personel Adet", "Personel Nitelikli İmza Sayısı", "Kaçak Personel Nitelikli Adet", "Personel Niteliksiz İmza Sayısı", "Kaçak Personel Niteliksiz Adet", "Toplam Kofra", "Toplam İş"]:
        if c in disp_df.columns:
            disp_df[c] = disp_df[c].apply(lambda x: format_tr_number(x, 0) if pd.notna(x) else "0")
    
    if secilen_bolge != "Tümü":
        # Bölge seçilmiş: Tüm personeli göster (sayfala)
        total_personel = len(disp_df)
        max_per_page = 12
        
        if total_personel <= max_per_page:
            # Tek sayfaya sığar
            p_table = build_data_table(disp_df, p_cols, f"Personel Detaylı Analiz - {secilen_bolge} ({total_personel} Kişi)", styles, max_rows=max_per_page)
            elements.extend(p_table)
            elements.append(PageBreak())
        else:
            # Çok sayfa gerekiyor
            page_num = 1
            for start_idx in range(0, total_personel, max_per_page):
                chunk = disp_df.iloc[start_idx:start_idx + max_per_page]
                end_idx = min(start_idx + max_per_page, total_personel)
                title = f"Personel Detaylı Analiz - {secilen_bolge} ({start_idx+1}-{end_idx} / {total_personel})"
                p_table = build_data_table(chunk, p_cols, title, styles, max_rows=max_per_page)
                elements.extend(p_table)
                elements.append(PageBreak())
                page_num += 1

    # Şimdi elemanları sırayla ekle
    
    if secilen_bolge == "Tümü":

        # 1. Ort. Kofra ve Ort. İş (Yan Yana)
        add_kpi_page(["Ort. Kofra", "Ort. İş"], side_by_side=True)
        
        # 2. Ort. İlk İş ve İlk Kontak Ort. (Yan Yana)
        add_kpi_page(["Ort. İlk İş", "İlk Kontak Ort."], side_by_side=True)
        
        # 3. Ort. Son İş ve Son Kontak Ort. (Yan Yana)
        add_kpi_page(["Ort. Son İş", "Son Kontak Ort."], side_by_side=True)
        
        
        # 5. Diğer Kalan KPI'lar (Pasta grafikli olanlar dahil)
        excluded_kpis = [
            "Kaçak Personel İmza Sayısı", "Personel Nitelikli İmza Sayısı", "Personel Niteliksiz İmza Sayısı",
            "Toplam Kaçak Adet", "Toplam Kaçak kWh", "Toplam Nitelikli Adet", "Toplam Nitelikli kWh", 
            "Toplam Niteliksiz Adet", "Toplam Niteliksiz kWh"
        ]
        for d_name, _ in kpi_items:
            if d_name not in used_kpis and d_name not in excluded_kpis:
                add_kpi_page([d_name])

    else:
        # === BÖLGE SEÇİLİYSE AYNI DÜZEN ===
        # 8. madde: Kaldırılacak toplam grafikleri
        excluded_kpis_region = [
            "Kaçak Personel İmza Sayısı", "Personel Nitelikli İmza Sayısı", "Personel Niteliksiz İmza Sayısı",
            "Toplam Kaçak Adet", "Toplam kWh", "Toplam Kaçak kWh", "Toplam Nitelikli Adet", "Toplam Nitelikli kWh", 
            "Toplam Niteliksiz Adet", "Toplam Niteliksiz kWh"
        ]
        
        for display_name, col_name in kpi_items:
            if display_name in excluded_kpis_region:
                continue
                
            img_personel = rendered_images.get(("personel", display_name))
            img_trend = rendered_images.get(("trend", display_name))
            pie_img = rendered_images.get(("pie", display_name))
            
            if not img_personel and not img_trend and not pie_img:
                continue
            
            # --- SAYFA 1: Personel + Trend (ve Pasta) ---
            kpi_elements = []
            kpi_elements.append(Paragraph(f"{display_name}: Analiz Özeti", styles['SectionTitle']))
            kpi_elements.append(Spacer(1, 5))
            
            if "Kaçak" in display_name:
                kpi_elements.append(Paragraph("<i>* Bu analizde personelin Kaçak İmza Sayıları baz alınmıştır.</i>", styles['ChartTitle']))
                kpi_elements.append(Spacer(1, 5))
                
            if img_personel:
                img_personel.drawWidth = 700
                img_personel.drawHeight = 200
                t_pers = Table([[img_personel]], colWidths=[800])
                t_pers.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
                kpi_elements.append(t_pers)
                kpi_elements.append(Spacer(1, 5))
            
            if pie_img or img_trend:
                if pie_img:
                    raw = pie_raw_data.get(display_name, (0, 0))
                    t_val, p_val = raw
                    other_val = max(0, t_val - p_val)
                    unit = "kWh" if "kWh" in display_name else "Adet"
                    table_val_style = ParagraphStyle('TableVal', parent=styles['CardText'], fontSize=10, fontName=FONT_BOLD)
                    
                    table_data = [
                        [Paragraph(f"Toplam {unit}", table_val_style), Paragraph(f"{format_tr_number(t_val, 1 if unit=='kWh' else 0)}", table_val_style)],
                        [Paragraph(f"Kaçak Personel {unit}", table_val_style), Paragraph(f"{format_tr_number(p_val, 1 if unit=='kWh' else 0)}", table_val_style)],
                        [Paragraph(f"Beda+Mth {unit}", table_val_style), Paragraph(f"{format_tr_number(other_val, 1 if unit=='kWh' else 0)}", table_val_style)]
                    ]
                    t_info = Table(table_data, colWidths=[120, 70])
                    t_info.setStyle(TableStyle([
                        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'LEFT'),
                        ('GRID', (0,0), (-1,-1), 0.5, colors.grey),
                        ('BACKGROUND', (0,0), (0,-1), colors.HexColor('#f5f5f5')),
                        ('TOPPADDING', (0,0), (-1,-1), 3), ('BOTTOMPADDING', (0,0), (-1,-1), 3),
                    ]))
                    
                    pie_img.drawWidth = 140
                    pie_img.drawHeight = 140
                    pie_box = Table([[pie_img], [Spacer(1, 5)], [t_info]], colWidths=[200])
                    pie_box.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE')]))
                    
                if pie_img and img_trend:
                    img_trend.drawWidth = 550
                    img_trend.drawHeight = 150
                    bottom_row = Table([[pie_box, img_trend]], colWidths=[220, 560])
                    bottom_row.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
                    kpi_elements.append(bottom_row)
                elif pie_img:
                    bottom_row = Table([[pie_box]], colWidths=[800])
                    bottom_row.setStyle(TableStyle([('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('ALIGN', (0,0), (-1,-1), 'CENTER')]))
                    kpi_elements.append(bottom_row)
                elif img_trend:
                    img_trend.drawWidth = 720
                    img_trend.drawHeight = 160
                    t_trend = Table([[img_trend]], colWidths=[780])
                    t_trend.setStyle(TableStyle([('ALIGN', (0,0), (-1,-1), 'CENTER')]))
                    kpi_elements.append(t_trend)
                
            # Eğer Genel Skor ise puanlama rehberini ekle
            if display_name == "Genel Skor":
                kpi_elements.append(Spacer(1, 5))
                kpi_elements.extend(build_scoring_guide(styles))
                
            elements.append(KeepTogether(kpi_elements))
            elements.append(PageBreak())


    # ==========================================
    # 5. TEŞEKKÜRLER SAYFASI
    # ==========================================
    thanks_elements = []
    thanks_elements.append(Spacer(1, 180))
    thanks_elements.append(Paragraph("Teşekkürler", styles['CoverTitle']))
    thanks_elements.append(Spacer(1, 20))
    thanks_elements.append(Paragraph("Müşteri Operasyonları Direktörlüğü", styles['CoverSubTitle']))
    elements.extend(thanks_elements)

    # Build PDF
    doc.build(elements)
    buffer.seek(0)
    return buffer
