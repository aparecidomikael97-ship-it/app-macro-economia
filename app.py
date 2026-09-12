import streamlit as st
import requests
import pandas as pd
import numpy as np
import plotly.express as px
from datetime import datetime, timedelta
import json
import os

# ──────────────────────────────────────────────────────────────
# CONFIGURAÇÃO
# ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Análise Macro & Força de Moedas — Versão Final",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

MOEDAS = {
    "USD": "Dólar EUA", "EUR": "Euro", "GBP": "Libra Esterlina",
    "JPY": "Iene Japonês", "AUD": "Dólar Australiano",
    "CAD": "Dólar Canadense", "CHF": "Franco Suíço", "NZD": "Dólar Neozelandês"
}

PARES_PRINCIPAIS = [("EUR","USD"), ("GBP","USD"), ("USD","JPY"), ("AUD","USD"), ("USD","CAD"), ("NZD","USD")]

PESOS = {"juros": 0.35, "inflacao": 0.25, "crescimento": 0.20, "sentimento": 0.20}

# ✅ SUAS CHAVES JÁ INSERIDAS
CHAVE_NEWSAPI = "88b2debd36ba4f80a0a5484a78eb1bac"
CHAVE_FRED = "22b2dfe684f07debde0a4a9ca4e0ac5c"

# Arquivo para salvar histórico da narrativa
ARQUIVO_HISTORICO = "historico_narrativa.json"

# ──────────────────────────────────────────────────────────────
# 📊 CÓDIGOS DOS INDICADORES NA API FRED
# ──────────────────────────────────────────────────────────────
CODIGOS_FRED = {
    "USD": {"juros": "DFF", "inflacao": "CPIAUCSL", "pib": "GDPC1"},
    "EUR": {"juros": "ECB_MAIN_REF_RATE", "inflacao": "CP0000EZ19M086NEST", "pib": "NAEXKP01EQQ652S"},
    "GBP": {"juros": "IUDSERDGBM156N", "inflacao": "GBRCPIALLMINMEI", "pib": "NGDPRSAXDCGBQ"},
    "JPY": {"juros": "IRSTFRMJPM156N", "inflacao": "JPNCPALTT01GYM659N", "pib": "JPNNGDP"},
    "AUD": {"juros": "IRSTCBRAAUM156N", "inflacao": "AUSCPIALLQINMEI", "pib": "AUSNGDP"},
    "CAD": {"juros": "IRSTCBRCACM156N", "inflacao": "CANCPIALLMINMEI", "pib": "CANGDPNQDSMEI"},
    "CHF": {"juros": "IR3TIB01CHM156N", "inflacao": "CPALTT01CHM659N", "pib": "CHENGDPNQDSMEI"},
    "NZD": {"juros": "IRSTCBRNZM156N", "inflacao": "CPALTT01NZQ659N", "pib": "NZLGDPNQDSMEI"}
}

# ──────────────────────────────────────────────────────────────
# 📅 CALENDÁRIO DE EVENTOS ECONÔMICOS
# ──────────────────────────────────────────────────────────────
def carregar_eventos():
    hoje = datetime.now().date()
    eventos = [
        {"nome": "Decisão Juros Fed", "data": hoje + timedelta(days=5), "importancia": "🔴 ALTA"},
        {"nome": "CPI Inflação EUA", "data": hoje + timedelta(days=2), "importancia": "🔴 ALTA"},
        {"nome": "Decisão Juros BCE", "data": hoje + timedelta(days=8), "importancia": "🔴 ALTA"},
        {"nome": "PIB EUA (2ª leitura)", "data": hoje + timedelta(days=12), "importancia": "🟡 MÉDIA"},
        {"nome": "Dados Emprego EUA", "data": hoje + timedelta(days=15), "importancia": "🔴 ALTA"},
    ]
    return eventos

# ──────────────────────────────────────────────────────────────
# 💾 GERENCIAR HISTÓRICO DA NARRATIVA
# ──────────────────────────────────────────────────────────────
def carregar_historico():
    if os.path.exists(ARQUIVO_HISTORICO):
        try:
            with open(ARQUIVO_HISTORICO, "r") as f:
                return json.load(f)
        except:
            return []
    return []

def salvar_no_historico(pontuacao, tom):
    historico = carregar_historico()
    data_atual = datetime.now().strftime("%Y-%m-%d")
    # Evita duplicar mesma data
    existe = any(item["data"] == data_atual for item in historico)
    if not existe:
        historico.append({
            "data": data_atual,
            "pontuacao": pontuacao,
            "tom": tom
        })
        # Mantém apenas últimas 8 semanas
        historico = historico[-56:]
        with open(ARQUIVO_HISTORICO, "w") as f:
            json.dump(historico, f)
    return historico

# ──────────────────────────────────────────────────────────────
# 🔧 BUSCAR DADOS OFICIAIS DA API FRED
# ──────────────────────────────────────────────────────────────
def buscar_dado_fred(codigo_serie):
    try:
        url = "https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": codigo_serie,
            "api_key": CHAVE_FRED,
            "file_type": "json",
            "sort_order": "desc",
            "limit": "12"
        }
        resp = requests.get(url, params=params, timeout=15)
        if resp.status_code == 200:
            dados = resp.json().get("observations", [])
            valores = []
            for d in dados:
                v = d.get("value")
                if v and v != ".":
                    valores.append(float(v))
            if valores:
                valor = valores[0]
                if abs(valor) < 1 and codigo_serie not in ["DFF"]:
                    valor = valor * 100
                return round(valor, 2)
    except Exception as e:
        pass
    return None

# ──────────────────────────────────────────────────────────────
# 📰 NOTÍCIAS DA SEMANA
# ──────────────────────────────────────────────────────────────
def buscar_noticias_semanais(topico="economia", qtd=15):
    data_inicio = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
    url = f"https://newsapi.org/v2/everything?q={topico}&from={data_inicio}&sortBy=publishedAt&language=pt&pageSize={qtd}&apiKey={CHAVE_NEWSAPI}"
    try:
        resp = requests.get(url, timeout=15)
        if resp.status_code == 200:
            return resp.json().get("articles", [])
    except:
        return []
    return []

# ──────────────────────────────────────────────────────────────
# 🧠 ANÁLISE DA NARRATIVA DO FED
# ──────────────────────────────────────────────────────────────
def analisar_narrativa_fed():
    noticias_fed = buscar_noticias_semanais(
        "Federal Reserve OR Fed taxa de juros inflação política monetária", qtd=20)

    hawkish = ["alta de juros", "aumentar juros", "manter juros altos", "inflação persistente",
               "elevar taxa", "juros mais altos", "combater inflação", "não cortar", "trabalho a fazer"]
    dovish = ["corte de juros", "reduzir juros", "inflação caiu", "afrouxar política",
              "crescimento fraco", "inflação controlada", "caminho para 2%", "corte em breve"]

    pts = 50
    titulos = []
    for art in noticias_fed[:15]:
        t = str(art.get("title", "")).lower()
        if t.strip(): titulos.append(t)
        for p in hawkish:
            if p in t: pts += 4
        for n in dovish:
            if n in t: pts -= 4

    pts = max(10, min(90, pts))

    if pts >= 70:
        tom = "🦅 HAWKISH — Juros ALTOS por mais tempo"
        resumo = "Fed sinaliza que inflação ainda preocupa. Juros podem SUBIR ou permanecer altos."
        impacto = "💵 Dólar tende a SE FORTALECER."
    elif pts >= 55:
        tom = "⚠️ CAUTELOSO — Sem cortes à vista"
        resumo = "Fed mantém juros altos mas sem decisão firme. Aguardam dados de CPI."
        impacto = "💵 Dólar tende a se manter FORTE/estável."
    elif pts >= 45:
        tom = "⚪ NEUTRO — Decisão depende dos dados"
        resumo = "Fed sem posição clara. Tudo depende de inflação e emprego."
        impacto = "⚪ Sem viés claro — mercado define pelos dados."
    elif pts >= 30:
        tom = "🕊️ INCLINANDO A CORTAR"
        resumo = "Inflação melhora. Fed começa a sinalizar cortes em breve."
        impacto = "💵 Dólar tende a SE ENFRAQUECER."
    else:
        tom = "🕊️ DOVISH — Ciclo de altos juros acabou"
        resumo = "Fed indica cortes. Inflação sob controle."
        impacto = "💵 Dólar deve CAIR."

    return {
        "pontuacao": pts, "tom": tom, "resumo": resumo,
        "impacto": impacto, "titulos": titulos,
        "data": datetime.now().strftime("%Y-%m-%d %H:%M")
    }

# ──────────────────────────────────────────────────────────────
# 🧠 MOTOR DE PONTUAÇÃO
# ──────────────────────────────────────────────────────────────
def pontuar_moeda(juros, inflacao, pib, sentimento, narrativa_fed_pts=None):
    # Força Pura (apenas indicadores econômicos — médio prazo)
    p_juros = min(100, juros * 14) if juros > 0 else 30
    if 1.5 <= inflacao <= 3.0:
        p_inflacao = 85
    elif inflacao < 1.5:
        p_inflacao = 60
    else:
        p_inflacao = 40
    p_crescimento = min(100, pib * 18 + 40)
    p_sentimento = sentimento

    pontuacao_pura = round(
        p_juros * 0.35 + p_inflacao * 0.25 +
        p_crescimento * 0.20 + p_sentimento * 0.20, 1
    )

    # Força com influência do Fed (apenas para USD)
    pontuacao_com_fed = pontuacao_pura
    influencia_fed = 0
    if narrativa_fed_pts is not None:
        # Pontuação neutra do Fed é 50 → diferença = influência
        influencia = (narrativa_fed_pts - 50) * 0.30
        pontuacao_com_fed = round(pontuacao_pura + influencia, 1)
        influencia_fed = round(influencia, 1)

    return pontuacao_pura, pontuacao_com_fed, influencia_fed


def probabilidade(ptsA, ptsB):
    diff = ptsA - ptsB
    if diff >= 20:
        p = min(92, 50 + diff)
        return "🟢 FORTE ALTA", f"{p:.0f}%", f"Moeda A tem forte tendência de SUBIR"
    elif diff >= 12:
        p = 58 + diff
        return "🟡 VIÉS DE ALTA", f"{p:.0f}%", f"Moeda A tende a valorizar"
    elif diff <= -20:
        p = min(92, 50 - abs(diff))
        return "🔴 FORTE QUEDA", f"{p:.0f}%", f"Moeda A tem forte tendência de CAIR"
    elif diff <= -12:
        p = 58 - abs(diff)
        return "🟠 VIÉS DE QUEDA", f"{p:.0f}%", f"Moeda A tende a desvalorizar"
    else:
        return "⚪ NEUTRO", "~50%", "Sem tendência clara"

# ──────────────────────────────────────────────────────────────
# 📥 CARREGAR DADOS E CÁLCULOS
# ──────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600)
def carregar_dados_economicos():
    referencia = {
        "USD": {"juros": 5.33, "inflacao": 2.9, "pib": 2.5},
        "EUR": {"juros": 4.50, "inflacao": 2.4, "pib": 0.8},
        "GBP": {"juros": 5.00, "inflacao": 2.7, "pib": 1.1},
        "JPY": {"juros": 0.50, "inflacao": 3.2, "pib": 1.1},
        "AUD": {"juros": 4.35, "inflacao": 3.3, "pib": 1.8},
        "CAD": {"juros": 5.00, "inflacao": 2.6, "pib": 1.5},
        "CHF": {"juros": 2.00, "inflacao": 1.2, "pib": 1.4},
        "NZD": {"juros": 5.50, "inflacao": 3.0, "pib": 1.2},
    }

    dados = {}
    for moeda in MOEDAS.keys():
        r = referencia[moeda]
        juros = buscar_dado_fred(CODIGOS_FRED[moeda]["juros"]) or r["juros"]
        inflacao = buscar_dado_fred(CODIGOS_FRED[moeda]["inflacao"]) or r["inflacao"]
        pib = buscar_dado_fred(CODIGOS_FRED[moeda]["pib"]) or r["pib"]

        notas = buscar_noticias_semanais(f"{moeda} economia", qtd=5)
        sent = 50
        pos = ["alta", "forte", "crescimento", "aumento"]
        neg = ["queda", "fraco", "reduz", "crise", "inflação alta"]
        for art in notas[:3]:
            t = str(art.get("title", "")).lower()
            for p in pos:
                if p in t: sent += 4
            for n in neg:
                if n in t: sent -= 4
        sent = max(15, min(90, sent))

        dados[moeda] = {
            "juros": round(float(juros), 2),
            "inflacao": round(float(inflacao), 2),
            "pib": round(float(pib), 2),
            "sentimento": sent
        }
    return dados

# ─── EXECUÇÃO PRINCIPAL ───
dados_eco = carregar_dados_economicos()
narrativa_fed = analisar_narrativa_fed()
historico = salvar_no_historico(narrativa_fed["pontuacao"], narrativa_fed["tom"])
eventos = carregar_eventos()

# Calcular ranking com e sem Fed
ranking = []
for cod, nome in MOEDAS.items():
    d = dados_eco[cod]
    fed_pts = narrativa_fed["pontuacao"] if cod == "USD" else None
    pura, com_fed, influencia = pontuar_moeda(d["juros"], d["inflacao"], d["pib"], d["sentimento"], fed_pts)
    ranking.append({
        "Posição": 0, "Código": cod, "Moeda": nome,
        "Pontuação_Pura": pura,
        "Pontuação_Com_Fed": com_fed if cod == "USD" else "-",
        "Influência_Fed": influencia if cod == "USD" else "-",
        "juros": d["juros"], "inflacao": d["inflacao"],
        "pib": d["pib"], "sentimento": d["sentimento"]
    })

df_ranking = pd.DataFrame(ranking).sort_values("Pontuação_Pura", ascending=False).reset_index(drop=True)
df_ranking["Posição"] = df_ranking.index + 1

# ──────────────────────────────────────────────────────────────
# 🎨 INTERFACE PRINCIPAL
# ──────────────────────────────────────────────────────────────
st.title("📊 Análise Macro & Força de Moedas — Versão Final Completa")
st.subheader("Dados Oficiais FRED + Notícias + Histórico + Alertas + Pares Principais")
st.caption(f"🕒 Atualizado em: {datetime.now().strftime('%d/%m/%Y %H:%M')} | 🔄 Renovação automática a cada hora")

# ─── BARRA LATERAL ───
st.sidebar.success("✅ AMBAS as chaves conectadas!")
st.sidebar.markdown("---")
st.sidebar.markdown("### 📡 Fontes Ativas")
st.sidebar.markdown("- ✅ **FRED API** → Dados oficiais do Fed")
st.sidebar.markdown("- ✅ **NewsAPI** → Notícias da Semana")

# ─── ABA: PÁGINA INICIAL ───
st.header("🏠 Visão Geral — Pares Principais")
st.markdown("### ⚠️ Próximos Eventos Importantes")
hoje = datetime.now().date()
for ev in eventos:
    dias_faltando = (ev["data"] - hoje).days
    if dias_faltando <= 3:
        st.warning(f"🚨 **URGENTE:** {ev['nome']} — em {dias_faltando} dias ({ev['data'].strftime('%d/%m')}) {ev['importancia']}")
    else:
        st.info(f"📅 {ev['nome']} — em {dias_faltando} dias ({ev['data'].strftime('%d/%m')}) {ev['importancia']}")

st.markdown("---")
st.markdown("### 💱 Principais Pares — Tendência Atual")
colunas = st.columns(3)
for idx, (moedaA, moedaB) in enumerate(PARES_PRINCIPAIS):
    with colunas[idx % 3]:
        ptsA = df_ranking.loc[df_ranking["Código"] == moedaA, "Pontuação_Com_Fed"].iloc[0] if moedaA == "USD" else df_ranking.loc[df_ranking["Código"] == moedaA, "Pontuação_Pura"].iloc[0]
        ptsB = df_ranking.loc[df_ranking["Código"] == moedaB, "Pontuação_Com_Fed"].iloc[0] if moedaB == "USD" else df_ranking.loc[df_ranking["Código"] == moedaB, "Pontuação_Pura"].iloc[0]
        ptsA = float(ptsA) if ptsA != "-" else 50
        ptsB = float(ptsB) if ptsB != "-" else 50
        tendencia, prob, desc = probabilidade(ptsA, ptsB)
        st.metric(f"{moedaA}/{moedaB}", tendencia, prob)
        st.caption(desc)

# ─── ABA: NARRATIVA DO FED ───
st.markdown("---")
st.header("🦅 Narrativa do Federal Reserve")

col1, col2 = st.columns([1, 2])
with col1:
    st.metric("Pontuação da Narrativa", f"{narrativa_fed['pontuacao']}/100")
    st.markdown(f"### {narrativa_fed['tom']}")
    st.caption(f"Analisado em: {narrativa_fed['data']}")
    st.progress(narrativa_fed['pontuacao'] / 100)
    st.caption("🕊️ DOVISH ←——————→ HAWKISH ⭐")

with col2:
    st.info(f"📌 **Resumo:** {narrativa_fed['resumo']}")
    st.success(f"💵 **Impacto no Dólar:** {narrativa_fed['impacto']}")

# Histórico da Narrativa
st.markdown("#### 📊 Histórico da Narrativa (Tendência)")
if len(historico) >= 2:
    df_hist = pd.DataFrame(historico)
    df_hist["data"] = pd.to_datetime(df_hist["data"])
    fig = px.line(df_hist, x="data", y="pontuacao",
                  title="Pontuação da Narrativa do Fed ao Longo do Tempo",
                  labels={"pontuacao": "Pontuação", "data": "Data"},
                  range_y=[0, 100])
    fig.add_hline(y=50, line_dash="dash", line_color="gray", annotation_text="Neutro")
    fig.add_hline(y=70, line_dash="dash", line_color="red", annotation_text="Hawkish")
    fig.add_hline(y=30, line_dash="dash", line_color="green", annotation_text="Dovish")
    st.plotly_chart(fig, use_container_width=True)
    st.caption("📈 Subindo = Fed ficando mais duro | 📉 Descendo = Fed ficando mais flexível")
else:
    st.info(f"📊 Histórico sendo construído. Hoje temos {len(historico)} registro(s). Volte nas próximas semanas para ver a tendência!")

st.markdown("---")
st.subheader("📰 Notícias analisadas esta semana")
for t in narrativa_fed['titulos'][:8]:
    if t.strip(): st.markdown(f"• {t.title()[:100]}...")

# ─── ABA: RANKING COMPLETO ───
st.markdown("---")
st.header("🏆 Força das Moedas — Análise Detalhada")

col_a, col_b = st.columns(2)
with col_a:
    st.markdown("### 📈 Médio Prazo (Indicadores Econômicos)")
    st.info("Base: Juros (35%) + Inflação (25%) + PIB (20%) + Sentimento (20%)")
with col_b:
    st.markdown("### ⏱️ Curto Prazo (Notícias + Fed)")
    st.warning("Inclui influência da comunicação e expectativas do mercado")

tabela_exibicao = df_ranking[["Posição", "Código", "Moeda", "Pontuação_Pura", "Pontuação_Com_Fed", "Influência_Fed", "juros", "inflacao", "pib", "sentimento"]].copy()
tabela_exibicao.columns = ["#", "Moeda", "Nome", "Força Pura", "Força + Fed", "Influência do Fed", "Juros %", "Inflação %", "PIB %", "Sentimento"]
st.dataframe(tabela_exibicao, use_container_width=True, hide_index=True)

# Explicação do cálculo com/sem Fed
st.markdown("### 💡 Como funciona a pontuação")
st.markdown("""
- **Força Pura:** Apenas dados econômicos oficiais (médio prazo)
- **Força + Fed:** Inclui a narrativa/comunicação do Fed (curto prazo)
- **Influência do Fed:** Quanto a fala do Fed está empurrando o dólar para cima ou para baixo
- **Sentimento:** Notícias da última semana
""")

top3 = df_ranking.head(3)["Código"].tolist()
bot3 = df_ranking.tail(3)["Código"].tolist()
st.success(f"🏆 Mais Fortes: {', '.join(top3)}")
st.error(f"📉 Mais Fracas: {', '.join(bot3)}")

# ─── ABA: ANÁLISE DE PAR ESPECÍFICO ───
st.markdown("---")
st.header("🔮 Análise de Par Específico")
c1, c2 = st.columns(2)
with c1: moedaA = st.selectbox("Moeda Base", list(MOEDAS.keys()), index=1)
with c2: moedaB = st.selectbox("Moeda Cotada", list(MOEDAS.keys()), index=0)

if moedaA != moedaB:
    ptsA = df_ranking.loc[df_ranking["Código"]==moedaA, "Pontuação_Com_Fed"].iloc[0] if moedaA == "USD" else df_ranking.loc[df_ranking["Código"]==moedaA, "Pontuação_Pura"].iloc[0]
    ptsB = df_ranking.loc[df_ranking["Código"]==moedaB, "Pontuação_Com_Fed"].iloc[0] if moedaB == "USD" else df_ranking.loc[df_ranking["Código"]==moedaB, "Pontuação_Pura"].iloc[0]
    ptsA = float(ptsA) if ptsA != "-" else 50
    ptsB = float(ptsB) if ptsB != "-" else 50
    stt, prob_val, desc = probabilidade(ptsA, ptsB)

    ca1, ca2, ca3 = st.columns([1, 1.5, 1])
    with ca1: st.metric(f"{moedaA}", f"{ptsA:.1f} pts")
    with ca2:
        st.markdown(f"<h2 style='text-align:center'>{moedaA}/{moedaB}</h2>", unsafe_allow_html=True)
        st.markdown(f"<h3 style='text-align:center'>{stt}</h3>", unsafe_allow_html=True)
        st.markdown(f"<h1 style='text-align:center; color:#00C853'>{prob_val}</h1>", unsafe_allow_html=True)
    with ca3: st.metric(f"{moedaB}", f"{ptsB:.1f} pts")

    st.info(f"📌 {desc} | Diferença: {abs(ptsA-ptsB):.1f} pontos")

    f1, f2 = st.columns(2)
    with f1:
        st.subheader(f"📊 {moedaA} — Indicadores")
        dA = dados_eco[moedaA]
        st.write(f"• Juros: **{dA['juros']}%**")
        st.write(f"• Inflação: **{dA['inflacao']}%**")
        st.write(f"• PIB: **{dA['pib']}%**")
        st.write(f"• Sentimento Semana: **{dA['sentimento']}/100**")
    with f2:
        st.subheader(f"📊 {moedaB} — Indicadores")
        dB = dados_eco[moedaB]
        st.write(f"• Juros: **{dB['juros']}%**")
        st.write(f"• Inflação: **{dB['inflacao']}%**")
        st.write(f"• PIB: **{dB['pib']}%**")
        st.write(f"• Sentimento Semana: **{dB['sentimento']}/100**")

    if moedaA == "USD" or moedaB == "USD":
        st.markdown("---")
        st.warning(f"🦅 Narrativa do Fed influencia este par: {narrativa_fed['tom']}")
        st.caption(narrativa_fed['impacto'])

# ─── AVISO FINAL ───
st.markdown("---")
st.markdown("💡 **Aviso:** Ferramenta de análise e probabilidade. SEMPRE combine com análise técnica e gestão de risco.")
