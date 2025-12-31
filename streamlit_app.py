import streamlit as st
import pandas as pd
import glob
import os

# =====================================================
# Configuração da página
# =====================================================
st.set_page_config(
    page_title="Dashboard Executivo de Treinamentos",
    layout="wide"
)

st.title("📊 Dashboard Executivo de Treinamentos")

# =====================================================
# Funções utilitárias
# =====================================================
def normalizar_colunas(df):
    df.columns = (
        df.columns.str.strip()
        .str.lower()
        .str.replace(" ", "_")
        .str.replace("?", "", regex=False)
    )
    return df


def normalizar_texto(col):
    return col.astype(str).str.strip().str.lower()


def formatar_nome(col):
    return col.astype(str).str.strip().str.title()


def carregar_arquivo_local(caminho):
    try:
        if caminho.endswith(".csv"):
            return pd.read_csv(caminho, sep=";", encoding="utf-8", on_bad_lines="skip")
        elif caminho.endswith(".xlsx"):
            return pd.read_excel(caminho)
    except Exception as e:
        st.error(f"Erro ao carregar {os.path.basename(caminho)}: {e}")
        return None


def carregar_arquivo_upload(file):
    try:
        if file.name.endswith(".csv"):
            return pd.read_csv(file, sep=";", encoding="utf-8", on_bad_lines="skip")
        elif file.name.endswith(".xlsx"):
            return pd.read_excel(file)
    except Exception as e:
        st.error(f"Erro ao carregar {file.name}: {e}")
        return None


# =====================================================
# Menu lateral – Fonte de dados
# =====================================================
st.sidebar.header("📂 Fonte de Dados")

uploaded_files = st.sidebar.file_uploader(
    "Upload de CSV ou Excel",
    type=["csv", "xlsx"],
    accept_multiple_files=True
)

arquivos_locais = glob.glob("input/*.csv") + glob.glob("input/*.xlsx")

opcoes = []
if arquivos_locais:
    opcoes.extend([("Local", arq) for arq in arquivos_locais])
if uploaded_files:
    opcoes.extend([("Upload", file.name) for file in uploaded_files])

if not opcoes:
    st.warning("Nenhum arquivo disponível.")
    st.stop()

origem, arquivo_selecionado = st.sidebar.selectbox(
    "Selecione o arquivo:",
    options=opcoes,
    format_func=lambda x: f"{x[0]} • {os.path.basename(x[1])}"
)

# =====================================================
# Leitura do arquivo
# =====================================================
if origem == "Local":
    df = carregar_arquivo_local(arquivo_selecionado)
else:
    file = next(f for f in uploaded_files if f.name == arquivo_selecionado)
    df = carregar_arquivo_upload(file)

if df is None:
    st.stop()

df = normalizar_colunas(df)

# =====================================================
# Normalização dos dados
# =====================================================
df["email"] = normalizar_texto(df["email"])

if {"first_name", "last_name"}.issubset(df.columns):
    df["nome_funcionario"] = formatar_nome(df["first_name"] + " " + df["last_name"])
else:
    df["nome_funcionario"] = (
        df["email"].str.split("@").str[0].str.replace(".", " ").str.title()
    )

df["manager_name"] = formatar_nome(df["manager_name"])
df["department"] = formatar_nome(df["department"])

# Tipo de vínculo
df["tipo"] = df["email"].apply(
    lambda x: "Externo" if x.startswith("extern") else "Interno"
)

# Conclusão
df["concluido"] = (
    df["training_status"]
    .astype(str)
    .str.strip()
    .str.lower()
    .eq("completed")
    .astype(int)
)

# =====================================================
# Consolidação por FUNCIONÁRIO (regra dos 80%)
# =====================================================
funcionarios = (
    df.groupby(
        ["email", "nome_funcionario", "manager_name", "department", "tipo"],
        as_index=False
    )
    .agg(
        total_treinamentos=("concluido", "count"),
        concluidos=("concluido", "sum")
    )
)

funcionarios["percentual"] = (
    funcionarios["concluidos"] / funcionarios["total_treinamentos"] * 100
).round(2)

funcionarios["status"] = funcionarios["percentual"].apply(
    lambda x: "Aprovado" if x >= 80 else "Reprovado"
)

# =====================================================
# Filtros
# =====================================================
st.sidebar.header("🔎 Filtros")

tipo_selecionado = st.sidebar.multiselect(
    "Tipo de vínculo:",
    ["Interno", "Externo"],
    default=["Interno", "Externo"]
)

funcionarios_filtro = funcionarios[
    funcionarios["tipo"].isin(tipo_selecionado)
]

# =====================================================
# Visão por GERENTE (formato FINAL)
# =====================================================
st.header("👔 Resultado por Gerente")

gerentes = (
    funcionarios_filtro
    .groupby("manager_name", as_index=False)
    .agg(
        aprovado_interno=("status", lambda x: ((funcionarios_filtro.loc[x.index, "tipo"] == "Interno") & (x == "Aprovado")).sum()),
        reprovado_interno=("status", lambda x: ((funcionarios_filtro.loc[x.index, "tipo"] == "Interno") & (x == "Reprovado")).sum()),
        aprovado_externo=("status", lambda x: ((funcionarios_filtro.loc[x.index, "tipo"] == "Externo") & (x == "Aprovado")).sum()),
        reprovado_externo=("status", lambda x: ((funcionarios_filtro.loc[x.index, "tipo"] == "Externo") & (x == "Reprovado")).sum())
    )
)

gerentes["percentual_aprovados"] = (
    (
        gerentes["aprovado_interno"] + gerentes["aprovado_externo"]
    ) /
    (
        gerentes[
            ["aprovado_interno", "reprovado_interno",
             "aprovado_externo", "reprovado_externo"]
        ].sum(axis=1)
    ) * 100
).round(2)

# =====================================================
# Exibição com barra de progresso
# =====================================================
st.dataframe(
    gerentes,
    column_config={
        "percentual_aprovados": st.column_config.ProgressColumn(
            "Percentual de Aprovados",
            min_value=0,
            max_value=100,
            format="%.2f%%"
        )
    }
)

# =====================================================
# Funcionários Reprovados + Exportação
# =====================================================
st.header("❌ Funcionários Não Aprovados (< 80%)")

lista_gerentes = sorted(funcionarios_filtro["manager_name"].unique())

gerentes_selecionados = st.multiselect(
    "Filtrar por gerente:",
    options=lista_gerentes,
    default=lista_gerentes
)

reprovados = funcionarios_filtro[
    (funcionarios_filtro["status"] == "Reprovado") &
    (funcionarios_filtro["manager_name"].isin(gerentes_selecionados))
]

export_df = (
    reprovados[
        [
            "nome_funcionario",
            "email",
            "manager_name",
            "department",
            "tipo",
            "total_treinamentos",
            "concluidos",
            "percentual"
        ]
    ]
    .sort_values("percentual")
)

st.dataframe(export_df)

csv = export_df.to_csv(index=False, sep=";", encoding="utf-8-sig")

st.download_button(
    label="⬇️ Baixar CSV – Funcionários Não Aprovados",
    data=csv,
    file_name="funcionarios_nao_aprovados.csv",
    mime="text/csv"
)

# =====================================================
# Gráfico Executivo
# =====================================================
st.header("📊 Gráfico Executivo Consolidado")

grafico = (
    funcionarios_filtro
    .groupby(["tipo", "status"])
    .size()
    .unstack(fill_value=0)
)

st.bar_chart(grafico)
