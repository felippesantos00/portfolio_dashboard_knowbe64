import streamlit as st
import pandas as pd
import glob
import os
import duckdb

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


def carregar_arquivo_local(caminho):
    if caminho.endswith(".csv"):
        return pd.read_csv(caminho, sep=";", encoding="utf-8", on_bad_lines="skip")
    return pd.read_excel(caminho)


def carregar_arquivo_upload(file):
    if file.name.endswith(".csv"):
        return pd.read_csv(file, sep=";", encoding="utf-8", on_bad_lines="skip")
    return pd.read_excel(file)


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

df = normalizar_colunas(df)

# =====================================================
# Normalização em PYTHON (não no DuckDB)
# =====================================================
df["email"] = df["email"].astype(str).str.strip().str.lower()

# Nome do funcionário
if {"first_name", "last_name"}.issubset(df.columns):
    df["nome_funcionario"] = (
        df["first_name"].fillna("") + " " + df["last_name"].fillna("")
    ).str.strip().str.title()
else:
    df["nome_funcionario"] = (
        df["email"]
        .str.split("@").str[0]
        .str.replace(".", " ")
        .str.title()
    )

df["manager_name"] = df["manager_name"].astype(str).str.strip().str.title()
df["department"] = df["department"].astype(str).str.strip().str.title()

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
# DuckDB
# =====================================================
con = duckdb.connect(database=":memory:")
con.register("treinamentos", df)

# =====================================================
# Consolidação por FUNCIONÁRIO (80%)
# =====================================================
funcionarios = con.execute("""
SELECT
    email,
    nome_funcionario,
    manager_name,
    department,
    tipo,
    COUNT(*) AS total_treinamentos,
    SUM(concluido) AS concluidos,
    ROUND(100.0 * SUM(concluido) / COUNT(*), 2) AS percentual,
    CASE
        WHEN 100.0 * SUM(concluido) / COUNT(*) >= 80 THEN 'Aprovado'
        ELSE 'Reprovado'
    END AS status
FROM treinamentos
GROUP BY
    email, nome_funcionario, manager_name, department, tipo
""").df()

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

con.register("funcionarios", funcionarios_filtro)

# =====================================================
# Visão por GERENTE (FINAL)
# =====================================================
st.header("👔 Resultado por Gerente")

gerentes = con.execute("""
SELECT
    manager_name,

    SUM(CASE WHEN tipo='Interno' AND status='Aprovado' THEN 1 ELSE 0 END) AS aprovado_interno,
    SUM(CASE WHEN tipo='Interno' AND status='Reprovado' THEN 1 ELSE 0 END) AS reprovado_interno,

    SUM(CASE WHEN tipo='Externo' AND status='Aprovado' THEN 1 ELSE 0 END) AS aprovado_externo,
    SUM(CASE WHEN tipo='Externo' AND status='Reprovado' THEN 1 ELSE 0 END) AS reprovado_externo,

 ROUND(
    SUM(CASE WHEN status='Aprovado' THEN 1 ELSE 0 END) * 100.0
    / COUNT(*),
    2
) AS percentual_aprovados
FROM funcionarios
GROUP BY manager_name
ORDER BY manager_name
""").df()

# =====================================================
# Tabela com barra de progresso
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
# Funcionários Reprovados
# =====================================================
st.header("❌ Funcionários Não Aprovados (< 80%)")

st.dataframe(
    funcionarios_filtro[funcionarios_filtro["status"] == "Reprovado"]
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
