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

def cor_percentual(valor):
    # Trata caso o valor chegue como string formatada
    if isinstance(valor, str):
        valor = float(valor.replace('%', ''))
    if valor >= 80:
        return "background-color: #d4edda; color: #155724" # Verde suave
    else:
        return "background-color: #f8d7da; color: #721c24" # Vermelho suave

def normalizar_colunas(df):
    df.columns = (
        df.columns
        .str.strip()
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
    st.warning("Nenhum arquivo disponível. Faça upload ou adicione arquivos em input/")
    st.stop()

origem, arquivo_selecionado = st.sidebar.selectbox(
    "Selecione o arquivo:",
    options=opcoes,
    format_func=lambda x: f"{x[0]} • {os.path.basename(x[1])}"
)

# =====================================================
# Leitura e Normalização Inicial
# =====================================================
if origem == "Local":
    df = carregar_arquivo_local(arquivo_selecionado)
else:
    file = next(f for f in uploaded_files if f.name == arquivo_selecionado)
    df = carregar_arquivo_upload(file)

if df is None:
    st.stop()

# Normalização de nomes de colunas e tipos
df = normalizar_colunas(df)
df = df.convert_dtypes() # Importante para evitar erros de tipo no DuckDB

# Normalização de dados
df["email"] = normalizar_texto(df["email"])

if {"first_name", "last_name"}.issubset(df.columns):
    df["nome_funcionario"] = formatar_nome(df["first_name"] + " " + df["last_name"])
else:
    df["nome_funcionario"] = df["email"].str.split("@").str[0].str.replace(".", " ").str.title()

df["manager_name"] = formatar_nome(df["manager_name"])
df["department"] = formatar_nome(df["department"])

# =====================================================
# Conexão DuckDB com Tratamento de Erro Robusto
# =====================================================
con = duckdb.connect(database=':memory:')

try:
    # Força a análise de todas as linhas para evitar erros de inferência de esquema
    con.execute("SET GLOBAL pandas_analyze_sample=0")
    con.register('treinamentos', df)
except Exception:
    # Fallback usando PyArrow para máxima compatibilidade
    import pyarrow as pa
    con.register('treinamentos', pa.Table.from_pandas(df))

# =====================================================
# Processamento de Dados (SQL)
# =====================================================
funcionarios = con.execute("""
    SELECT 
        email,
        nome_funcionario,
        manager_name,
        department,
        CASE WHEN LOWER(email) LIKE 'extern%' THEN 'Terceiro' ELSE 'Interno' END AS tipo,
        COUNT(*) AS total_treinamentos,
        SUM(CASE WHEN LOWER(training_status) = 'completed' THEN 1 ELSE 0 END) AS concluidos
    FROM treinamentos
    GROUP BY email, nome_funcionario, manager_name, department
""").df()

funcionarios["percentual"] = (funcionarios["concluidos"] / funcionarios["total_treinamentos"]) * 100
funcionarios["status"] = funcionarios["percentual"].apply(lambda x: "Aprovado" if x >= 80 else "Reprovado")

# =====================================================
# Filtros e Dashboard
# =====================================================
st.sidebar.header("🔎 Filtros")
tipo_selecionado = st.sidebar.multiselect(
    "Tipo de vínculo:",
    ["Interno", "Terceiro"],
    default=["Interno", "Terceiro"]
)

funcionarios_filtro = funcionarios[funcionarios["tipo"].isin(tipo_selecionado)]

st.header("📈 Visão Executiva – Internos x Terceiros")
col_i, col_t = st.columns(2)

for col, tipo in zip([col_i, col_t], ["Interno", "Terceiro"]):
    base = funcionarios_filtro[funcionarios_filtro["tipo"] == tipo]
    with col:
        st.subheader(tipo)
        if not base.empty:
            st.metric("Funcionários", base["email"].nunique())
            st.metric("Aprovados (%)", f"{round((base['status'] == 'Aprovado').mean() * 100, 1)}%")
            st.metric("Reprovados (%)", f"{round((base['status'] == 'Reprovado').mean() * 100, 1)}%")
        else:
            st.write("Sem dados para este tipo.")

# =====================================================
# Resultado por Gerente
# =====================================================
st.header("👔 Resultado por Gerente")

gerentes = con.execute("""
    WITH status_funcionario AS (
        SELECT
            email,
            manager_name,
            CASE WHEN LOWER(email) LIKE 'extern%' THEN 'Terceiro' ELSE 'Interno' END AS tipo,
            SUM(CASE WHEN LOWER(training_status) = 'completed' THEN 1 ELSE 0 END) AS concluidos,
            COUNT(*) AS total_treinamentos
        FROM treinamentos
        GROUP BY email, manager_name
    ),
    aprovacao AS (
        SELECT
            *,
            CASE WHEN concluidos * 100.0 / total_treinamentos >= 80 THEN 1 ELSE 0 END AS aprovado
        FROM status_funcionario
    )
    SELECT
        manager_name,
        SUM(CASE WHEN tipo = 'Interno' AND aprovado = 1 THEN 1 ELSE 0 END) AS aprovado_interno,
        SUM(CASE WHEN tipo = 'Interno' AND aprovado = 0 THEN 1 ELSE 0 END) AS reprovado_interno,
        SUM(CASE WHEN tipo = 'Terceiro' AND aprovado = 1 THEN 1 ELSE 0 END) AS aprovado_externo,
        SUM(CASE WHEN tipo = 'Terceiro' AND aprovado = 0 THEN 1 ELSE 0 END) AS reprovado_externo,
        ROUND(100.0 * SUM(aprovado) / COUNT(*), 1) AS percentual_aprovados
    FROM aprovacao
    GROUP BY manager_name
    ORDER BY manager_name
""").df()

styled_gerentes = (
    gerentes.style
    .format({
        "aprovado_interno": "{:.0f}",
        "reprovado_interno": "{:.0f}",
        "aprovado_externo": "{:.0f}",
        "reprovado_externo": "{:.0f}",
        "percentual_aprovados": "{:.1f}%"
    })
    .applymap(cor_percentual, subset=["percentual_aprovados"])
)
st.dataframe(styled_gerentes, use_container_width=True)

# =====================================================
# Funcionários Não Aprovados
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

st.dataframe(
    reprovados[["nome_funcionario", "email", "manager_name", "department", "percentual"]]
    .sort_values("percentual"),
    use_container_width=True
)
