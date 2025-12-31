import streamlit as st
import duckdb
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
# Sidebar – Fonte de dados
# =====================================================
st.sidebar.header("📂 Fonte de Dados")

arquivos = glob.glob("input/*.csv")

if not arquivos:
    st.warning("Nenhum arquivo CSV encontrado na pasta input/")
    st.stop()

arquivo_csv = st.sidebar.selectbox(
    "Selecione o arquivo CSV",
    arquivos,
    format_func=lambda x: os.path.basename(x)
)

# =====================================================
# Conexão DuckDB (sem carregar tudo em memória)
# =====================================================
con = duckdb.connect(database=":memory:")

# =====================================================
# View base (normalização já no SQL)
# =====================================================
con.execute(f"""
CREATE OR REPLACE VIEW treinamentos AS
SELECT
    LOWER(TRIM(email)) AS email,

    INITCAP(
        COALESCE(
            TRIM(first_name || ' ' || last_name),
            REPLACE(SPLIT_PART(email, '@', 1), '.', ' ')
        )
    ) AS nome_funcionario,

    INITCAP(TRIM(manager_name)) AS manager_name,
    INITCAP(TRIM(department)) AS department,

    CASE
        WHEN LOWER(email) LIKE 'extern%' THEN 'Externo'
        ELSE 'Interno'
    END AS tipo,

    CASE
        WHEN LOWER(TRIM(training_status)) = 'completed' THEN 1
        ELSE 0
    END AS concluido

FROM read_csv_auto('{arquivo_csv}', delim=';')
""")

# =====================================================
# Consolidação por FUNCIONÁRIO (regra 80%)
# =====================================================
con.execute("""
CREATE OR REPLACE VIEW funcionarios AS
SELECT
    email,
    nome_funcionario,
    manager_name,
    department,
    tipo,
    COUNT(*) AS total_treinamentos,
    SUM(concluido) AS concluidos,
    ROUND(SUM(concluido) * 100.0 / COUNT(*), 2) AS percentual,
    CASE
        WHEN SUM(concluido) * 1.0 / COUNT(*) >= 0.8 THEN 'Aprovado'
        ELSE 'Reprovado'
    END AS status
FROM treinamentos
GROUP BY
    email, nome_funcionario, manager_name, department, tipo
""")

# =====================================================
# Filtro por tipo
# =====================================================
st.sidebar.header("🔎 Filtros")

tipos = st.sidebar.multiselect(
    "Tipo de vínculo",
    ["Interno", "Externo"],
    default=["Interno", "Externo"]
)

tipos_sql = ",".join([f"'{t}'" for t in tipos])

# =====================================================
# Visão FINAL por GERENTE
# =====================================================
query_gerentes = f"""
SELECT
    manager_name,

    SUM(CASE WHEN tipo = 'Interno' AND status = 'Aprovado' THEN 1 ELSE 0 END) AS aprovado_interno,
    SUM(CASE WHEN tipo = 'Interno' AND status = 'Reprovado' THEN 1 ELSE 0 END) AS reprovado_interno,

    SUM(CASE WHEN tipo = 'Externo' AND status = 'Aprovado' THEN 1 ELSE 0 END) AS aprovado_externo,
    SUM(CASE WHEN tipo = 'Externo' AND status = 'Reprovado' THEN 1 ELSE 0 END) AS reprovado_externo,

    ROUND(
        SUM(CASE WHEN status = 'Aprovado' THEN 1 ELSE 0 END) * 100.0
        /
        COUNT(*),
        2
    ) AS percentual_aprovados

FROM funcionarios
WHERE tipo IN ({tipos_sql})
GROUP BY manager_name
ORDER BY percentual_aprovados DESC
"""

gerentes = con.execute(query_gerentes).df()

# =====================================================
# Exibição – Gerentes
# =====================================================
st.header("👔 Resultado por Gerente")

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

lista_gerentes = sorted(gerentes["manager_name"].unique())

gerentes_sel = st.multiselect(
    "Filtrar por gerente",
    lista_gerentes,
    default=lista_gerentes
)

gerentes_sql = ",".join([f"'{g}'" for g in gerentes_sel])

query_reprovados = f"""
SELECT
    nome_funcionario,
    email,
    manager_name,
    department,
    tipo,
    total_treinamentos,
    concluidos,
    percentual
FROM funcionarios
WHERE status = 'Reprovado'
  AND manager_name IN ({gerentes_sql})
ORDER BY percentual
"""

reprovados = con.execute(query_reprovados).df()

st.dataframe(
    reprovados.style.format({
        "percentual": "{:.2f}%"
    })
)

# =====================================================
# Exportação
# =====================================================
csv = reprovados.to_csv(index=False, sep=";", encoding="utf-8-sig")

st.download_button(
    "⬇️ Baixar CSV – Funcionários Não Aprovados",
    csv,
    "funcionarios_nao_aprovados.csv",
    "text/csv"
)

# =====================================================
# Gráfico Executivo
# =====================================================
st.header("📊 Gráfico Executivo Consolidado")

grafico = con.execute(f"""
SELECT tipo, status, COUNT(*) AS total
FROM funcionarios
WHERE tipo IN ({tipos_sql})
GROUP BY tipo, status
""").df()

grafico_pivot = grafico.pivot(
    index="tipo",
    columns="status",
    values="total"
).fillna(0)

st.bar_chart(grafico_pivot)
