import pandas as pd
import streamlit as st
import yfinance as yf

st.set_page_config(page_title="Screener Saham IDX", layout="wide")
st.title("Screener Saham IDX")
st.caption("Data dari Yahoo Finance (yfinance). Bisa telat atau kosong untuk beberapa emiten.")

DEFAULT = (
    "BBCA BBRI BMRI BBNI TLKM ASII UNVR ICBP INDF KLBF "
    "ADRO ANTM PTBA UNTR AMRT MDKA CPIN SMGR"
)

# ---------- Sidebar: input & kriteria ----------
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
        pilih = st.selectbox("Pilih emiten", hasil["Kode"])
        _, harga = ambil_data(pilih)
        grafik = pd.DataFrame(
            {"Harga": harga, "MA200": harga.rolling(200).mean()}
        )
        st.line_chart(grafik)
else:
    st.info("Atur kriteria di kiri, lalu klik **Jalankan screening**.")
