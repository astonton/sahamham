import io
import re
from datetime import datetime

import pandas as pd
import requests
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Screener Saham IDX", layout="wide")
st.title("Screener Saham IDX")
st.caption("Data dari Yahoo Finance (yfinance). Bisa telat atau kosong untuk beberapa emiten.")

DEFAULT = (
    "BBCA BBRI BMRI BBNI TLKM ASII UNVR ICBP INDF KLBF "
    "ADRO ANTM PTBA UNTR AMRT MDKA CPIN SMGR"
)

tab_screener, tab_analisa = st.tabs(["Screener", "Analisa Mendalam (1 emiten)"])

# ---------- Sidebar: input & kriteria (punya tab Screener) ----------
with st.sidebar:
    st.header("Daftar emiten")
    teks = st.text_area("Kode saham (pisah spasi/koma, tanpa .JK)", DEFAULT, height=120)

    st.header("Kriteria")
    per_max = st.number_input("PER maksimal", value=15.0, step=1.0)
    pbv_max = st.number_input("PBV maksimal", value=3.0, step=0.5)
    roe_min = st.number_input("ROE minimal (%)", value=15.0, step=1.0)
    der_max = st.number_input("DER maksimal (%)", value=100.0, step=10.0)
    yield_min = st.number_input("Dividend yield minimal (%)", value=2.0, step=0.5)
    di_bawah_ma = st.checkbox("Harga di bawah MA200", value=False)

    min_lolos = st.slider("Minimal kriteria yang harus lolos", 1, 6, 4)
    jalankan = st.button("Jalankan screening", type="primary")


# ---------- Ambil data ----------
@st.cache_data(ttl=3600, show_spinner=False)
def ambil_data(kode: str):
    t = yf.Ticker(f"{kode}.JK")
    info = t.info
    harga = t.history(period="2y")["Close"]
    return info, harga


def hitung_baris(kode: str):
    info, harga = ambil_data(kode)
    if harga.empty:
        return None

    last = float(harga.iloc[-1])
    ma200 = float(harga.rolling(200).mean().iloc[-1]) if len(harga) >= 200 else None
    roe = info.get("returnOnEquity")
    dps = info.get("dividendRate")

    return {
        "Kode": kode,
        "Harga": last,
        "PER": info.get("trailingPE"),
        "PBV": info.get("priceToBook"),
        "ROE (%)": roe * 100 if roe is not None else None,
        "DER (%)": info.get("debtToEquity"),
        "Yield (%)": (dps / last * 100) if dps and last else 0.0,
        "MA200": ma200,
    }


def cek(nilai, fungsi):
    """True kalau data ada dan lolos kriteria."""
    return nilai is not None and pd.notna(nilai) and fungsi(nilai)


with tab_screener:
    if jalankan:
        daftar = [k.strip().upper() for k in teks.replace(",", " ").split() if k.strip()]
        baris, gagal = [], []
        bar = st.progress(0.0, text="Mengambil data...")

        for i, kode in enumerate(daftar):
            try:
                r = hitung_baris(kode)
                if r:
                    baris.append(r)
                else:
                    gagal.append(kode)
            except Exception:
                gagal.append(kode)
            bar.progress((i + 1) / len(daftar), text=f"Mengambil data {kode}...")
        bar.empty()

        if not baris:
            st.error("Tidak ada data yang berhasil diambil.")
            st.stop()

        df = pd.DataFrame(baris)

        # ---------- Kriteria custom: tiap kriteria = 1 poin ----------
        df["K_PER"] = df["PER"].apply(lambda x: cek(x, lambda v: 0 < v <= per_max))
        df["K_PBV"] = df["PBV"].apply(lambda x: cek(x, lambda v: 0 < v <= pbv_max))
        df["K_ROE"] = df["ROE (%)"].apply(lambda x: cek(x, lambda v: v >= roe_min))
        df["K_DER"] = df["DER (%)"].apply(lambda x: cek(x, lambda v: v <= der_max))
        df["K_YLD"] = df["Yield (%)"].apply(lambda x: cek(x, lambda v: v >= yield_min))
        if di_bawah_ma:
            df["K_MA"] = df.apply(
                lambda r: cek(r["MA200"], lambda m: r["Harga"] < m), axis=1
            )
        else:
            df["K_MA"] = True

        kolom_k = ["K_PER", "K_PBV", "K_ROE", "K_DER", "K_YLD", "K_MA"]
        df["Skor"] = df[kolom_k].sum(axis=1)

        hasil = (
            df[df["Skor"] >= min_lolos]
            .sort_values("Skor", ascending=False)
            .drop(columns=kolom_k)
            .round(2)
            .reset_index(drop=True)
        )
        st.session_state["hasil"] = hasil
        st.session_state["gagal"] = gagal

    # ---------- Tampilkan hasil ----------
    if "hasil" in st.session_state:
        hasil = st.session_state["hasil"]
        st.subheader(f"{len(hasil)} emiten lolos")
        st.dataframe(hasil, use_container_width=True)

        if st.session_state["gagal"]:
            st.warning("Data gagal diambil: " + ", ".join(st.session_state["gagal"]))

        if not hasil.empty:
            st.subheader("Grafik harga")
            pilih = st.selectbox("Pilih emiten", hasil["Kode"], key="pilih_screener")
            _, harga = ambil_data(pilih)
            grafik = pd.DataFrame(
                {"Harga": harga, "MA200": harga.rolling(200).mean()}
            )
            st.line_chart(grafik)
    else:
        st.info("Atur kriteria di kiri, lalu klik **Jalankan screening**.")


# ================================================================
# TAB 2: ANALISA MENDALAM — KUANTITATIF (yfinance) + LAPORAN RESMI (PDF IDX)
# ================================================================

HEADERS_IDX = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/laporan-keuangan-dan-tahunan",
}


@st.cache_data(ttl=3600, show_spinner=False)
def ambil_lapkeu(kode: str):
    t = yf.Ticker(f"{kode}.JK")
    return {
        "info": t.info,
        "income_tahunan": t.financials,
        "income_kuartalan": t.quarterly_financials,
        "neraca_tahunan": t.balance_sheet,
        "neraca_kuartalan": t.quarterly_balance_sheet,
        "arus_kas_tahunan": t.cashflow,
        "arus_kas_kuartalan": t.quarterly_cashflow,
    }


@st.cache_data(ttl=3600, show_spinner=False)
def ambil_laporan_resmi(kode: str, tahun: int, periode: str):
    """Ambil daftar laporan keuangan resmi (PDF) dari API publik IDX.
    periode: 'TW1', 'TW2', 'TW3', atau 'audit' (laporan tahunan).
    """
    url = "https://www.idx.co.id/primary/ListedCompany/GetFinancialReport"
    params = {
        "kodeEmiten": kode,
        "year": tahun,
        "periode": periode,
        "indexFrom": 0,
        "pageSize": 20,
        "reportType": "rdf",
    }
    r = requests.get(url, params=params, headers=HEADERS_IDX, timeout=20)
    r.raise_for_status()
    data = r.json()

    hasil = []
    for item in data.get("Results", []):
        judul = item.get("File_Modified") or item.get("File_Name") or "Laporan"
        for lampiran in item.get("Attachments", []):
            path = lampiran.get("File_Path") or lampiran.get("Full_Path")
            if path:
                if path.startswith("/"):
                    path = "https://www.idx.co.id" + path
                hasil.append({"judul": judul, "nama_file": lampiran.get("File_Name", "-"), "url": path})
    return hasil


def ambil_baris(df: pd.DataFrame, kandidat_nama: list[str]):
    """Cari baris di laporan keuangan yfinance; nama field-nya suka berubah-ubah."""
    if df is None or df.empty:
        return None
    for nama in kandidat_nama:
        if nama in df.index:
            return df.loc[nama]
    return None


with tab_analisa:
    st.subheader("Analisa kuantitatif: ringkasan otomatis + laporan resmi IDX")
    st.caption(
        "Ringkasan & grafik dari data yfinance (cepat, tapi bisa kosong/telat untuk sebagian emiten). "
        "Untuk angka resmi, unduh langsung laporan keuangan PDF dari IDX di bagian bawah."
    )

    kode_analisa = st.text_input("Kode saham (tanpa .JK)", "BBCA", key="kode_analisa").strip().upper()
    muat = st.button("Muat analisa", type="primary", key="muat_analisa")

    if muat and kode_analisa:
        with st.spinner(f"Mengambil data {kode_analisa}..."):
            data_lk = ambil_lapkeu(kode_analisa)
        st.session_state["data_lk"] = data_lk
        st.session_state["kode_analisa_aktif"] = kode_analisa

    if "data_lk" in st.session_state:
        kode_aktif = st.session_state["kode_analisa_aktif"]
        data_lk = st.session_state["data_lk"]
        info = data_lk["info"]

        st.markdown(f"### {info.get('longName', kode_aktif)} ({kode_aktif})")

        # ---------------- KUANTITATIF ----------------
        st.markdown("#### 1. Kuantitatif — Laporan Keuangan")

        periode = st.radio("Periode", ["Tahunan", "Kuartalan"], horizontal=True, key="periode_lk")
        if periode == "Tahunan":
            income, neraca, kas = (
                data_lk["income_tahunan"],
                data_lk["neraca_tahunan"],
                data_lk["arus_kas_tahunan"],
            )
        else:
            income, neraca, kas = (
                data_lk["income_kuartalan"],
                data_lk["neraca_kuartalan"],
                data_lk["arus_kas_kuartalan"],
            )

        pendapatan = ambil_baris(income, ["Total Revenue", "Operating Revenue"])
        laba_bersih = ambil_baris(income, ["Net Income", "Net Income Common Stockholders"])
        total_aset = ambil_baris(neraca, ["Total Assets"])
        total_liabilitas = ambil_baris(neraca, ["Total Liabilities Net Minority Interest", "Total Liab"])
        total_ekuitas = ambil_baris(neraca, ["Stockholders Equity", "Total Equity Gross Minority Interest"])
        arus_kas_operasi = ambil_baris(kas, ["Operating Cash Flow", "Cash Flow From Continuing Operating Activities"])

        if pendapatan is None and laba_bersih is None:
            st.warning("Data laporan keuangan tidak tersedia untuk emiten ini di yfinance.")
        else:
            # tabel ringkas
            ringkas = pd.DataFrame(
                {
                    "Pendapatan": pendapatan,
                    "Laba Bersih": laba_bersih,
                    "Total Aset": total_aset,
                    "Total Liabilitas": total_liabilitas,
                    "Total Ekuitas": total_ekuitas,
                    "Arus Kas Operasi": arus_kas_operasi,
                }
            ).T
            ringkas.columns = [c.strftime("%Y-%m") if hasattr(c, "strftime") else str(c) for c in ringkas.columns]
            st.dataframe(ringkas, use_container_width=True)

            col1, col2 = st.columns(2)
            with col1:
                if pendapatan is not None and laba_bersih is not None:
                    grafik_pl = pd.DataFrame(
                        {"Pendapatan": pendapatan, "Laba Bersih": laba_bersih}
                    ).T.T  # pastikan orientasi waktu di index
                    grafik_pl.index = [
                        c.strftime("%Y-%m") if hasattr(c, "strftime") else str(c) for c in grafik_pl.index
                    ]
                    st.caption("Tren pendapatan vs laba bersih")
                    st.bar_chart(grafik_pl[["Pendapatan", "Laba Bersih"]])

            with col2:
                if total_liabilitas is not None and total_ekuitas is not None:
                    der_series = (total_liabilitas / total_ekuitas * 100).rename("DER (%)")
                    der_series.index = [
                        c.strftime("%Y-%m") if hasattr(c, "strftime") else str(c) for c in der_series.index
                    ]
                    st.caption("Tren Debt-to-Equity Ratio")
                    st.line_chart(der_series)

            # rasio & pertumbuhan singkat
            st.markdown("**Cek cepat:**")
            catatan = []
            if pendapatan is not None and len(pendapatan.dropna()) >= 2:
                nilai = pendapatan.dropna()
                tumbuh = (nilai.iloc[0] - nilai.iloc[1]) / abs(nilai.iloc[1]) * 100
                catatan.append(f"- Pendapatan periode terakhir {'naik' if tumbuh >= 0 else 'turun'} {abs(tumbuh):.1f}% dari periode sebelumnya.")
            if laba_bersih is not None and len(laba_bersih.dropna()) >= 2:
                nilai = laba_bersih.dropna()
                tumbuh = (nilai.iloc[0] - nilai.iloc[1]) / abs(nilai.iloc[1]) * 100
                catatan.append(f"- Laba bersih periode terakhir {'naik' if tumbuh >= 0 else 'turun'} {abs(tumbuh):.1f}% dari periode sebelumnya.")
            if arus_kas_operasi is not None and len(arus_kas_operasi.dropna()) >= 1:
                nilai_terakhir = arus_kas_operasi.dropna().iloc[0]
                catatan.append(
                    f"- Arus kas operasi periode terakhir {'positif' if nilai_terakhir >= 0 else 'negatif'} "
                    f"({nilai_terakhir:,.0f})."
                )
            if catatan:
                st.markdown("\n".join(catatan))
            else:
                st.caption("Data belum cukup untuk hitung tren otomatis.")

        # ---------------- KUALITATIF ----------------
        st.markdown("#### 2. Kualitatif — Berita Terbaru")
        berita = st.session_state.get("berita", [])

        if not berita:
            st.info(
                "Tidak ada berita ditemukan lewat yfinance untuk emiten ini. "
                "Cek manual di Google News atau IDX untuk berita terbaru."
            )
        else:
            baris_berita = []
            for b in berita:
                item = b.get("content", b)  # struktur yfinance berubah-ubah antar versi
                judul = item.get("title") or b.get("title") or "(tanpa judul)"
                penerbit = (
                    item.get("provider", {}).get("displayName")
                    if isinstance(item.get("provider"), dict)
                    else b.get("publisher", "-")
                )
                link = (
                    item.get("canonicalUrl", {}).get("url")
                    if isinstance(item.get("canonicalUrl"), dict)
                    else b.get("link", "")
                )
                waktu = item.get("pubDate") or b.get("providerPublishTime")
                if isinstance(waktu, (int, float)):
                    waktu = datetime.fromtimestamp(waktu).strftime("%Y-%m-%d %H:%M")

                baris_berita.append(
                    {
                        "Judul": judul,
                        "Sumber": penerbit or "-",
                        "Waktu": waktu or "-",
                        "Sentimen": sentimen_sederhana(judul),
                        "Link": link,
                    }
                )

            df_berita = pd.DataFrame(baris_berita)

            jml_pos = (df_berita["Sentimen"] == "Positif").sum()
            jml_neg = (df_berita["Sentimen"] == "Negatif").sum()
            jml_net = (df_berita["Sentimen"] == "Netral").sum()
            c1, c2, c3 = st.columns(3)
            c1.metric("Positif", jml_pos)
            c2.metric("Netral", jml_net)
            c3.metric("Negatif", jml_neg)

            for _, r in df_berita.iterrows():
                warna = {"Positif": "🟢", "Negatif": "🔴", "Netral": "⚪"}[r["Sentimen"]]
                st.markdown(f"{warna} **[{r['Judul']}]({r['Link']})**  \n{r['Sumber']} · {r['Waktu']}")

            st.caption(
                "Sentimen di atas cuma hitung kata kunci positif/negatif di judul, "
                "gampang salah baca konteks (sarkasme, negasi, dll). Tetap baca beritanya langsung."
            )
    else:
        st.info("Masukkan kode saham lalu klik **Muat analisa**.")
