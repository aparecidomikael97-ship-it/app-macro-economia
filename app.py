import math
from datetime import datetime, timedelta
import re
import urllib.parse
import xml.etree.ElementTree as ET
import numpy as np
import pandas as pd
import requests
import streamlit as st

# ═══════════════════════════════════════════════════════════════════
# CONFIGURAÇÃO
# ═══════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="Análise Macro + Fed — Modelo Completo",
    page_icon="🦅",
    layout="wide",
    initial_sidebar_state="expanded"
)

MOEDAS = {
    "USD": "Dólar Americano", "EUR": "Euro", "GBP": "Libra Esterlina",
    "JPY": "Iene Japonês", "CHF": "Franco Suíço", "CAD": "Dólar Canadense",
    "AUD": "Dólar Australiano", "NZD": "Dólar Neozelandês",
    "BRL": "Real Brasileiro",
}

FED_SENS_PADRAO = {
    "USD": +1.00, "JPY": +0.35, "CHF": +0.35, "EUR": +0.10, "GBP": +0.15,
    "CAD": -0.40, "AUD": -0.60, "NZD": -0.60, "BRL": -0.80,
}
FED_IMPACTO_MAX = 20.0
HIST_SCORES = "historico_scores.parquet"
HIST_COTACOES = "historico_cotacoes.parquet"

CHAVE_NEWSAPI = st.secrets.get("CHAVE_NEWSAPI", "88b2debd36ba4f80a0a5484a78eb1bac")
CHAVE_FRED = st.secrets.get("CHAVE_FRED", "22b2dfe684f07debde0a4a9ca4e0ac5c")

# ═══════════════════════════════════════════════════════════════════
# BARRA LATERAL
# ═══════════════════════════════════════════════════════════════════
st.sidebar.header("⚙️ Parâmetros do Modelo")

ESCALA_PROB = st.sidebar.slider(
    "Escala da Probabilidade", 2.0, 30.0, 10.0, 0.5,
    help="Diferença de pontos para ~73% de chance. Calibre na aba Backtest.")

PESOS = {
    "juros": st.sidebar.slider("Peso — Juros", 0.0, 0.6, 0.30, 0.05),
    "inflacao": st.sidebar.slider("Peso — Inflação", 0.0, 0.6, 0.20, 0.05),
    "pib": st.sidebar.slider("Peso — PIB", 0.0, 0.6, 0.25, 0.05),
    "sentimento": st.sidebar.slider("Peso — Sentimento", 0.0, 0.6, 0.25, 0.05),
}
st.sidebar.caption(f"Soma dos pesos: {sum(PESOS.values()):.2f} (ideal = 1.00)")
if abs(sum(PESOS.values()) - 1.0) > 0.01:
    st.sidebar.warning("⚠️ Ajuste os pesos para somarem 1.0")

st.sidebar.subheader("Sensibilidade ao Fed por Moeda")
FED_SENSIBILIDADE = {
    m: st.sidebar.slider(f"{m} — {MOEDAS[m]}", -1.0, 1.0, float(FED_SENS_PADRAO[m]), 0.05)
    for m in MOEDAS
}
st.sidebar.divider()
st.sidebar.caption(f"🕒 Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}")

# ═══════════════════════════════════════════════════════════════════
# FUNÇÕES DE DADOS
# ═══════════════════════════════════════════════════════════════════
STATUS_FONTE = {}

def _get(url: str, timeout: int = 12):
    try:
        r = requests.get(url, timeout=timeout)
        r.raise_for_status()
        return r
    except Exception:
        return None

def _fred_ultimo(series_id: str) -> float | None:
    if not CHAVE_FRED:
        return None
    url = (f"https://api.stlouisfed.org/fred/series/observations"
           f"?series_id={series_id}&api_key={CHAVE_FRED}&file_type=json"
           "&sort_order=desc&limit=1")
    r = _get(url)
    if r is None:
        return None
    try:
        obs = r.json().get("observations", [])
        return float(obs[0]["value"]) if obs and obs[0]["value"] != "." else None
    except Exception:
        return None

def _bcb_ultimo(codigo_sgs: int) -> float | None:
    r = _get(f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo_sgs}/dados/ultimos/1?formato=json")
    if r is None:
        return None
    try:
        return float(r.json()[0]["valor"].replace(",", "."))
    except Exception:
        return None

FRED_MAP = {
    "USD": ("FEDFUNDS", "CPIAUCSL", "A191RO1Q156NBEA"),
    "EUR": ("ECBDFR", "CP0000EZ19M086NEST", "CLVMNACSCAB1GQEA19"),
    "GBP": ("BOERUKM", "CPALTT01GBM661S", "CLVMNACSCAB1GQUK"),
    "JPY": ("IR3TIB01JPM156N", "CPALTT01JPM661S", "CLVMNACSCAB1GQJP"),
    "CHF": ("IR3TIB01CHM156N", "CPALTT01CHM661S", "CLVMNACSCAB1GQCH"),
    "CAD": ("IR3TIB01CAM156N", "CPALTT01CAM661S", "CLVMNACSCAB1GQCA"),
    "AUD": ("IR3TIB01AUM156N", "CPALTT01AUM661S", "CLVMNACSCAB1GQAU"),
    "NZD": ("IR3TIB01NZM156N", "CPALTT01NZM661S", "CLVMNACSCAB1GQNZ"),
}

PALAVRAS_POS = ("alta","sobe","ganha","forte","avanço","rally","beat","surge","gain","rise","strong","growth","hike")
PALAVRAS_NEG = ("queda","cai","perde","fraco","recesso","crise","drop","fall","weak","cut","crisis","selloff")

@st.cache_data(ttl=1800, show_spinner="Analisando notícias...")
def sentimento_noticias(nome_moeda: str) -> float:
    q = urllib.parse.quote(f"{nome_moeda} OR {nome_moeda.split()[0]} currency")
    url = f"https://news.google.com/rss/search?q={q}+when:7d&hl=pt-BR&gl=BR&ceid=BR:pt-419"
    r = _get(url)
    if r is None:
        try:
            url_api = f"https://newsapi.org/v2/everything?q={urllib.parse.quote(nome_moeda)}&language=pt&from={(datetime.now()-timedelta(days=7)).strftime('%Y-%m-%d')}&sortBy=publishedAt&apiKey={CHAVE_NEWSAPI}"
            r2 = requests.get(url_api, timeout=10)
            if r2.ok:
                dados = r2.json()
                titulos = [a["title"].lower() for a in dados.get("articles", []) if a.get("title")]
                if titulos:
                    pos = sum(sum(w in t for w in PALAVRAS_POS) for t in titulos)
                    neg = sum(sum(w in t for w in PALAVRAS_NEG) for t in titulos)
                    return float(np.clip(50 + 50 * (pos - neg) / max(pos + neg, 1), 0, 100))
        except:
            pass
        return 50.0
    try:
        root = ET.fromstring(r.content)
        titulos = [i.findtext("title", "").lower() for i in root.iter("item")]
        if not titulos:
            return 50.0
        pos = sum(sum(w in t for w in PALAVRAS_POS) for t in titulos)
        neg = sum(sum(w in t for w in PALAVRAS_NEG) for t in titulos)
        return float(np.clip(50 + 50 * (pos - neg) / max(pos + neg, 1), 0, 100))
    except Exception:
        return 50.0

@st.cache_data(ttl=3600, show_spinner="Carregando dados econômicos...")
def carregar_dados_eco() -> dict:
    DEMO = {
        "USD": {"juros": 4.25, "inflacao": 2.9, "pib": 2.1},
        "EUR": {"juros": 2.15, "inflacao": 2.1, "pib": 1.4},
        "GBP": {"juros": 4.00, "inflacao": 3.2, "pib": 1.1},
        "JPY": {"juros": 0.25, "inflacao": 2.8, "pib": 0.8},
        "CHF": {"juros": 0.00, "inflacao": 1.2, "pib": 1.5},
        "CAD": {"juros": 3.75, "inflacao": 2.3, "pib": 1.8},
        "AUD": {"juros": 3.35, "inflacao": 2.7, "pib": 1.9},
        "NZD": {"juros": 3.25, "inflacao": 2.5, "pib": 1.6},
        "BRL": {"juros": 10.75, "inflacao": 4.5, "pib": 2.4},
    }
    hoje = datetime.now().date()
    dados = {}
    for cod, demo in DEMO.items():
        juros = inflacao = pib = None
        fonte = "demo"
        if cod == "BRL":
            juros, inflacao, pib = (_bcb_ultimo(432), _bcb_ultimo(13522), _bcb_ultimo(4380))
            fonte = "BCB"
        elif cod in FRED_MAP and CHAVE_FRED:
            sid_j, sid_i, sid_p = FRED_MAP[cod]
            juros, inflacao, pib = (_fred_ultimo(sid_j), _fred_ultimo(sid_i), _fred_ultimo(sid_p))
            fonte = "FRED"
        ok = all(v is not None for v in (juros, inflacao, pib))
        STATUS_FONTE[cod] = f"✅ {fonte}" if ok else f"⚠️ {fonte} (dados indisponíveis)"
        dados[cod] = {
            "juros": juros if juros is not None else demo["juros"],
            "inflacao": inflacao if inflacao is not None else demo["inflacao"],
            "pib": pib if pib is not None else demo["pib"],
            "sentimento": sentimento_noticias(MOEDAS[cod]),
            "atualizado_em": hoje,
        }
    return dados

@st.cache_data(ttl=1800, show_spinner="Decifrando narrativa do Fed...")
def carregar_narrativa_fed() -> dict:
    url = ("https://news.google.com/rss/search?q=" +
           urllib.parse.quote("Federal Reserve OR FOMC OR Powell when:7d") +
           "&hl=en-US&gl=US&ceid=US:en")
    r = _get(url)
    forca = 0.0
    if r is not None:
        try:
            root = ET.fromstring(r.content)
            titulos = [i.findtext("title", "").lower() for i in root.iter("item")]
            pos = sum(sum(w in t for w in PALAVRAS_POS) for t in titulos)
            neg = sum(sum(w in t for w in PALAVRAS_NEG) for t in titulos)
            forca = float(np.clip((pos - neg) / max(pos + neg, 1), -1, 1))
        except Exception:
            pass
    tom = "Hawkish" if forca > 0.15 else "Dovish" if forca < -0.15 else "Neutro"
    STATUS_FONTE["FED"] = "✅ Notícias" if r is not None else "⚠️ Demo"
    return {
        "tom": tom, "forca": forca,
        "fonte": "Notícias do Fed — últimos 7 dias",
        "data": datetime.now().date() - timedelta(days=1)
    }

# ═══════════════════════════════════════════════════════════════════
# MOTOR DE PONTUAÇÃO
# ═══════════════════════════════════════════════════════════════════
def normalizar(s: pd.Series, inverter: bool = False) -> pd.Series:
    if s.max() == s.min():
        return pd.Series(50.0, index=s.index)
    n = (s - s.min()) / (s.max() - s.min()) * 100
    return 100 - n if inverter else n

def calcular_ranking(dados_eco: dict, fed: dict) -> pd.DataFrame:
    df = pd.DataFrame(dados_eco).T
    df.index.name = "Código"; df = df.reset_index()
    df["Moeda"] = df["Código"].map(MOEDAS)
    df["n_juros"] = normalizar(df["juros"])
    df["n_inflacao"] = normalizar(df["inflacao"], inverter=True)
    df["n_pib"] = normalizar(df["pib"])
    df["n_sent"] = normalizar(df["sentimento"])
    df["Pontuação_Pura"] = (
        PESOS["juros"] * df["n_juros"] +
        PESOS["inflacao"] * df["n_inflacao"] +
        PESOS["pib"] * df["n_pib"] +
        PESOS["sentimento"] * df["n_sent"]
    ).round(1)
    df["Influência_Fed"] = (
        df["Código"].map(FED_SENSIBILIDADE).fillna(0.0) *
        fed["forca"] * FED_IMPACTO_MAX
    ).round(1)
    df["Pontuação_Com_Fed"] = (df["Pontuação_Pura"] + df["Influência_Fed"]).round(1)
    df = df.sort_values("Pontuação_Com_Fed", ascending=False).reset_index(drop=True)
    df["Posição"] = df.index + 1
    return df

def probabilidade(ptsA: float, ptsB: float):
    diff = ptsA - ptsB
    p = 1 / (1 + math.exp(-diff / (ESCALA_PROB / 2)))
    if p >= 0.65: stt = "🟢 Forte vantagem"
    elif p >= 0.55: stt = "🟡 Leve vantagem"
    elif p >= 0.45: stt = "⚪ Equilíbrio"
    elif p >= 0.35: stt = "🟡 Leve desvantagem"
    else: stt = "🔴 Forte desvantagem"
    return stt, p, f"Diferença: {diff:+.1f} pts | ESCALA={ESCALA_PROB:.1f}"

# ═══════════════════════════════════════════════════════════════════
# HISTÓRICO
# ═══════════════════════════════════════════════════════════════════
def salvar_snapshot(df_ranking: pd.DataFrame):
    snap = df_ranking[["Código", "Pontuação_Pura", "Pontuação_Com_Fed"]].copy()
    snap["data"] = datetime.now().date()
    try:
        hist = pd.read_parquet(HIST_SCORES)
        if str(datetime.now().date()) in hist["data"].astype(str).values:
            return "⚠️ Snapshot de hoje já salvo."
        hist = pd.concat([hist, snap], ignore_index=True)
    except FileNotFoundError:
        hist = snap
    hist.to_parquet(HIST_SCORES, index=False)
    return f"✅ Snapshot salvo! Total: {len(hist)} registros."

@st.cache_data
def carregar_historico():
    try:
        return pd.read_parquet(HIST_SCORES)
    except FileNotFoundError:
        return pd.DataFrame()

# ═══════════════════════════════════════════════════════════════════
# EXECUÇÃO PRINCIPAL
# ═══════════════════════════════════════════════════════════════════
dados_eco = carregar_dados_eco()
narrativa_fed = carregar_narrativa_fed()
df_ranking = calcular_ranking(dados_eco, narrativa_fed)

st.title("🦅 Análise Macro & Força de Moedas — Modelo Completo")
tom_icon = {"Hawkish":"🔴", "Dovish":"🟢", "Neutro":"⚪"}.get(narrativa_fed["tom"], "⚪")
st.caption(f"🕒 {datetime.now().strftime('%d/%m/%Y %H:%M')} | Fed: {tom_icon} **{narrativa_fed['tom']}** | {narrativa_fed['fonte']}")
st.caption("Fontes: " + " · ".join(f"{k}:{v}" for k, v in STATUS_FONTE.items()))

aba1, aba2, aba3, aba4 = st.tabs([
    "🏆 Ranking & Narrativa",
    "🔮 Análise de Par",
    "📊 Histórico & Snapshots",
    "📈 Backtest & Calibração"
])

# ─── ABA 1: RANKING ───
with aba1:
    st.subheader("📊 Força das Moedas")
    tabela = df_ranking[[
        "Posição","Código","Moeda","Pontuação_Pura","Pontuação_Com_Fed",
        "Influência_Fed","juros","inflacao","pib","sentimento"
    ]].copy()
    tabela.columns = [
        "#","Código","Moeda","Força Pura","Força + Fed","Influência Fed",
        "Juros %","Inflação %","PIB %","Sentimento"
    ]
    st.dataframe(
        tabela.style.background_gradient(subset=["Força + Fed"], cmap="RdYlGn")
              .background_gradient(subset=["Influência Fed"], cmap="RdYlGn", axis=None)
              .format({
                  "Força Pura":"{:.1f}","Força + Fed":"{:.1f}","Influência Fed":"{:+.1f}",
                  "Juros %":"{:.2f}","Inflação %":"{:.1f}","PIB %":"{:.1f}","Sentimento":"{:.0f}"
              }),
        use_container_width=True, hide_index=True
    )

    st.markdown("### 💡 Como funciona")
    st.markdown("""
    - **Força Pura**: Médio prazo — dados econômicos oficiais (pesos ajustáveis na barra lateral)
    - **Força + Fed**: Curto prazo — inclui narrativa do Fed ponderada por sensibilidade de cada moeda
    - **Influência Fed**: Pontos que o Fed adiciona (+) ou subtrai (−) da pontuação
    - **Sentimento**: Notícias agregadas da semana (0–100)
    """)

    top3 = df_ranking.head(3)["Código"].tolist()
    bot3 = df_ranking.tail(3)["Código"].tolist()
    st.success(f"🏆 Mais Fortes: **{', '.join(top3)}**")
    st.error(f"📉 Mais Fracas: **{', '.join(bot3)}**")

    if st.button("💾 Salvar Snapshot de Hoje"):
        st.toast(salvar_snapshot(df_ranking))

# ─── ABA 2: ANÁLISE DE PAR ───
with aba2:
    st.subheader("🔮 Probabilidade entre Pares")
    moedas_validas = df_ranking["Código"].tolist()
    c1, c2 = st.columns(2)
    with c1: moedaA = st.selectbox("Moeda Base", moedas_validas, index=1)
    with c2: moedaB = st.selectbox("Moeda Cotada", moedas_validas, index=0)

    if moedaA != moedaB:
        ptsA = float(df_ranking.loc[df_ranking["Código"]==moedaA, "Pontuação_Com_Fed"].iloc[0])
        ptsB = float(df_ranking.loc[df_ranking["Código"]==moedaB, "Pontuação_Com_Fed"].iloc[0])
        stt, pA, desc = probabilidade(ptsA, ptsB)

        ca1, ca2, ca3 = st.columns([1, 1.5, 1])
        with ca1: st.metric(moedaA, f"{ptsA:.1f} pts")
        with ca2:
            st.subheader(f"{moedaA}/{moedaB}")
            st.markdown(f"### {stt}")
            st.progress(min(max(pA, 0.0), 1.0))
            st.markdown(f"### {moedaA} **{pA*100:.0f}%** · {moedaB} **{(1-pA)*100:.0f}%**")
        with ca3: st.metric(moedaB, f"{ptsB:.1f} pts")

        st.info(f"📌 {desc}")
        dA, dB = dados_eco[moedaA], dados_eco[moedaB]
        comp = pd.DataFrame({
            "Indicador": ["Juros %", "Inflação %", "PIB %", "Sentimento"],
            moedaA: [dA["juros"], dA["inflacao"], dA["pib"], dA["sentimento"]],
            moedaB: [dB["juros"], dB["inflacao"], dB["pib"], dB["sentimento"]]
        }).set_index("Indicador")
        st.dataframe(comp.style.format("{:.2f}"), use_container_width=True)

# ─── ABA 3: HISTÓRICO ───
with aba3:
    st.subheader("📊 Histórico de Pontuações")
    hist = carregar_historico()
    if hist.empty:
        st.info("ℹ️ Nenhum histórico ainda. Salve snapshots diários na aba 🏆.")
    else:
        st.caption(f"Total de {hist['data'].nunique()} dias registrados")
        st.dataframe(hist.sort_values("data", ascending=False), use_container_width=True)

# ─── ABA 4: BACKTEST ───
with aba4:
    st.subheader("📈 Calibração do Modelo")
    st.caption("Ajuste a ESCALA_PROB para maximizar a qualidade da previsão")
    hist = carregar_historico()
    if hist.empty or len(hist["data"].unique()) < 5:
        st.warning("⚠️ Histórico insuficiente. Salve snapshots por pelo menos 5 dias para calibração.")
    else:
        st.info(f"✅ {hist['data'].nunique()} dias de dados — pronto para calibração!")
        st.markdown("""
        **Como interpretar:**
        - 🟢 **Brier < 0.12** → Excelente previsão
        - 🟡 **Brier 0.12–0.20** → Previsão razoável
        - 🔴 **Brier > 0.25** → Equivale a chute 50/50 (ajuste os pesos)
        """)
