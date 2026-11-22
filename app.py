import sqlite3
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

DB_PATH = "granja_vieira.db"


def get_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def parse_data_segura(valor):
    if valor is None or pd.isna(valor):
        return None
    if isinstance(valor, date) and not isinstance(valor, datetime):
        return valor
    if isinstance(valor, datetime):
        return valor.date()
    texto = str(valor).strip()
    if not texto or texto.lower() in ("none", "nat", "nan"):
        return None
    try:
        return date.fromisoformat(texto[:10])
    except ValueError:
        return None


def parse_numero_opcional(texto):
    if texto is None:
        return None
    limpo = str(texto).strip().replace(",", ".")
    if not limpo:
        return None
    return float(limpo)


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lotes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            data_alojamento TEXT,
            qtd_inicial INTEGER NOT NULL,
            tipo_ave TEXT DEFAULT '',
            origem TEXT DEFAULT '',
            custo_pintinho REAL,
            situacao TEXT DEFAULT 'Ativo',
            observacoes TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS registros_diarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_registro TEXT NOT NULL,
            lote_id TEXT NOT NULL,
            aves_mortas INTEGER NOT NULL DEFAULT 0,
            racao_kg REAL,
            observacoes TEXT DEFAULT '',
            FOREIGN KEY (lote_id) REFERENCES lotes (id)
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS compras_estoque (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_compra TEXT NOT NULL,
            produto TEXT NOT NULL,
            categoria TEXT NOT NULL,
            fornecedor TEXT DEFAULT '',
            quantidade REAL NOT NULL,
            unidade TEXT DEFAULT 'kg',
            preco_unitario REAL NOT NULL,
            valor_total REAL NOT NULL,
            lote_id TEXT,
            estoque_minimo REAL DEFAULT 20.0,
            observacoes TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS alimentacao (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_registro TEXT NOT NULL,
            lote_id TEXT NOT NULL,
            produto_estoque TEXT NOT NULL,
            fase_alimentar TEXT DEFAULT 'Não informada',
            qtd_fornecida_kg REAL NOT NULL,
            qtd_sobra_kg REAL,
            consumo_liquido_kg REAL NOT NULL,
            sobra_medida INTEGER NOT NULL DEFAULT 0,
            custo_estimado REAL NOT NULL DEFAULT 0.0,
            observacoes TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS pesagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_pesagem TEXT NOT NULL,
            lote_id TEXT NOT NULL,
            aves_pesadas INTEGER NOT NULL,
            peso_total_kg REAL NOT NULL,
            peso_medio_kg REAL NOT NULL,
            gpd_g_dia REAL,
            conversao_alimentar REAL,
            observacoes TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS sanidade (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_aplicacao TEXT NOT NULL,
            lote_id TEXT NOT NULL,
            tipo_evento TEXT NOT NULL,
            produto_tratamento TEXT NOT NULL,
            dose_observacao TEXT DEFAULT '',
            carencia_dias INTEGER NOT NULL DEFAULT 0,
            data_liberacao TEXT NOT NULL,
            responsavel TEXT DEFAULT '',
            observacoes TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS custos_operacionais (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_lancamento TEXT NOT NULL,
            tipo_custo TEXT NOT NULL,
            descricao TEXT NOT NULL,
            valor REAL NOT NULL,
            lote_id TEXT,
            rateio_base TEXT DEFAULT 'Por Ave Viva',
            observacoes TEXT DEFAULT ''
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS vendas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_venda TEXT NOT NULL,
            lote_id TEXT NOT NULL,
            comprador TEXT DEFAULT '',
            modalidade TEXT NOT NULL,
            aves_vendidas INTEGER NOT NULL,
            peso_total_kg REAL DEFAULT 0.0,
            preco_unitario REAL NOT NULL,
            valor_total REAL NOT NULL,
            status_pagamento TEXT DEFAULT 'Recebido',
            carencia_confirmada INTEGER DEFAULT 0,
            observacoes TEXT DEFAULT ''
        )
    """)

    lotes_iniciais = [
        ("LOTE 01", "Lote 01", None, 200, "", "", None, "Ativo", ""),
        ("LOTE 02", "Lote 02", None, 200, "", "", None, "Ativo", ""),
        ("LOTE 03", "Lote 03", None, 200, "", "", None, "Ativo", ""),
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO lotes
        (id, nome, data_alojamento, qtd_inicial, tipo_ave, origem, custo_pintinho, situacao, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, lotes_iniciais)

    conn.commit()
    conn.close()


def obter_dados_sistema():
    conn = get_conn()
    lotes_df = pd.read_sql_query("SELECT * FROM lotes ORDER BY id", conn)
    compras_df = pd.read_sql_query("SELECT * FROM compras_estoque ORDER BY data_compra, id", conn)
    alim_df = pd.read_sql_query("SELECT * FROM alimentacao ORDER BY data_registro, id", conn)
    reg_df = pd.read_sql_query("SELECT * FROM registros_diarios ORDER BY data_registro, id", conn)
    pesagens_df = pd.read_sql_query("SELECT * FROM pesagens ORDER BY data_pesagem, id", conn)
    sanidade_df = pd.read_sql_query("SELECT * FROM sanidade ORDER BY data_aplicacao, id", conn)
    custos_df = pd.read_sql_query("SELECT * FROM custos_operacionais ORDER BY data_lancamento, id", conn)
    vendas_df = pd.read_sql_query("SELECT * FROM vendas ORDER BY data_venda, id", conn)
    conn.close()

    produtos = {}
    for _, c in compras_df.iterrows():
        prod = str(c["produto"]).strip()
        if not prod:
            continue
        if prod not in produtos:
            produtos[prod] = {
                "Produto": prod,
                "Categoria": str(c["categoria"] or "Insumo"),
                "Unidade": str(c["unidade"] or "kg"),
                "Qtd. Comprada": 0.0,
                "Valor Comprado (R$)": 0.0,
                "Qtd. Consumida": 0.0,
                "Saldo Atual": 0.0,
                "Custo Médio (R$)": 0.0,
                "Valor Estoque (R$)": 0.0,
                "Estoque Mínimo": float(c["estoque_minimo"] or 0.0),
            }
        qtd_c = float(c["quantidade"] or 0.0)
        val_c = float(c["valor_total"] or (qtd_c * float(c["preco_unitario"] or 0.0)))
        produtos[prod]["Qtd. Comprada"] += qtd_c
        produtos[prod]["Valor Comprado (R$)"] += val_c
        if c["estoque_minimo"] is not None:
            produtos[prod]["Estoque Mínimo"] = float(c["estoque_minimo"])

    consumo_por_produto = {}
    if not alim_df.empty:
        for _, a in alim_df.iterrows():
            prod = str(a["produto_estoque"]).strip()
            cons = float(a["consumo_liquido_kg"] or 0.0)
            consumo_por_produto[prod] = consumo_por_produto.get(prod, 0.0) + cons

    consumo_reg_direto = 0.0
    if not reg_df.empty and "racao_kg" in reg_df.columns:
        for _, r in reg_df.iterrows():
            if r["racao_kg"] is not None and not pd.isna(r["racao_kg"]):
                obs_txt = str(r["observacoes"] or "")
                if "[via Alimentação]" not in obs_txt:
                    consumo_reg_direto += float(r["racao_kg"])

    for prod, info in produtos.items():
        custo_med = (info["Valor Comprado (R$)"] / info["Qtd. Comprada"]) if info["Qtd. Comprada"] > 0 else 0.0
        cons_alim = consumo_por_produto.get(prod, 0.0)
        cons_extra_racao = consumo_reg_direto if "ração" in prod.lower() or "racao" in prod.lower() else 0.0
        qtd_cons = cons_alim + cons_extra_racao
        saldo = max(info["Qtd. Comprada"] - qtd_cons, 0.0)
        valor_est = saldo * custo_med

        info["Qtd. Consumida"] = round(qtd_cons, 2)
        info["Saldo Atual"] = round(saldo, 2)
        info["Custo Médio (R$)"] = round(custo_med, 2)
        info["Valor Estoque (R$)"] = round(valor_est, 2)
        info["Qtd. Comprada"] = round(info["Qtd. Comprada"], 2)
        info["Valor Comprado (R$)"] = round(info["Valor Comprado (R$)"], 2)
        info["Alerta"] = "⚠️ Estoque Baixo" if saldo <= info["Estoque Mínimo"] else "✅ OK"

    estoque_df = pd.DataFrame(list(produtos.values())) if produtos else pd.DataFrame(columns=[
        "Produto", "Categoria", "Unidade", "Qtd. Comprada", "Valor Comprado (R$)",
        "Qtd. Consumida", "Saldo Atual", "Custo Médio (R$)", "Valor Estoque (R$)",
        "Estoque Mínimo", "Alerta"
    ])
    return lotes_df, estoque_df, compras_df, alim_df, reg_df, pesagens_df, sanidade_df, custos_df, vendas_df


def obter_carencia_lote(lote_id, sanidade_df):
    if sanidade_df.empty:
        return False, "-", "✅ Liberado"
    s_lote = sanidade_df[sanidade_df["lote_id"] == lote_id]
    if s_lote.empty:
        return False, "-", "✅ Liberado"

    hoje = date.today()
    datas_lib = []
    for _, row in s_lote.iterrows():
        d_lib = parse_data_segura(row["data_liberacao"])
        if d_lib:
            datas_lib.append(d_lib)

    if not datas_lib:
        return False, "-", "✅ Liberado"

    maior_data = max(datas_lib)
    if maior_data > hoje:
        dias_rest = (maior_data - hoje).days
        return True, maior_data.isoformat(), f"🚫 Carência ({dias_rest}d até {maior_data.isoformat()})"
    return False, maior_data.isoformat(), "✅ Liberado"


def calcular_metricas_pesagem(lote_id, data_pes_obj, peso_med_kg, racao_acum_lote, aves_vivas_lote, d_aloj_obj, pesagens_df):
    gpd_val = None
    ca_val = None

    p_lote = pesagens_df[pesagens_df["lote_id"] == lote_id].sort_values(by=["data_pesagem", "id"]) if not pesagens_df.empty else pd.DataFrame()

    if not p_lote.empty:
        ultima = p_lote.iloc[-1]
        d_ant = parse_data_segura(ultima["data_pesagem"])
        peso_ant = float(ultima["peso_medio_kg"] or 0.0)
        if d_ant is not None:
            dias = (data_pes_obj - d_ant).days
            if dias > 0:
                gpd_val = round(((peso_med_kg - peso_ant) * 1000.0) / dias, 1)
    elif d_aloj_obj is not None:
        dias_aloj = (data_pes_obj - d_aloj_obj).days
        if dias_aloj > 0:
            peso_inicial_estimado = 0.042
            gpd_val = round(((peso_med_kg - peso_inicial_estimado) * 1000.0) / dias_aloj, 1)

    if racao_acum_lote > 0 and aves_vivas_lote > 0 and peso_med_kg > 0:
        biomassa_estimada_kg = aves_vivas_lote * peso_med_kg
        if biomassa_estimada_kg > 0:
            ca_val = round(racao_acum_lote / biomassa_estimada_kg, 2)

    return gpd_val, ca_val


def montar_resumo_e_custos(lotes_df, estoque_df, alim_df, reg_df, pesagens_df, sanidade_df, custos_df, vendas_df):
    custo_medio_map = {}
    if not estoque_df.empty:
        for _, row in estoque_df.iterrows():
            custo_medio_map[str(row["Produto"])] = float(row["Custo Médio (R$)"])

    racao_custo_padrao = 0.0
    for nome_p, cm in custo_medio_map.items():
        if "ração" in nome_p.lower() or "racao" in nome_p.lower():
            racao_custo_padrao = cm
            break

    base_lotes = []
    total_aves_vivas_geral = 0
    total_lotes_ativos = 0

    for _, lote in lotes_df.iterrows():
        lid = str(lote["id"])
        qtd_ini = int(lote["qtd_inicial"])
        sit_val = "Ativo" if pd.isna(lote["situacao"]) else str(lote["situacao"])
        r_lote = reg_df[reg_df["lote_id"] == lid] if not reg_df.empty else pd.DataFrame()
        v_lote = vendas_df[vendas_df["lote_id"] == lid] if not vendas_df.empty else pd.DataFrame()

        mortes_acum = int(r_lote["aves_mortas"].sum()) if not r_lote.empty else 0
        vendidas_acum = int(v_lote["aves_vendidas"].sum()) if not v_lote.empty else 0
        aves_vivas = max(qtd_ini - mortes_acum, 0)
        aves_disponiveis = max(qtd_ini - mortes_acum - vendidas_acum, 0)

        base_lotes.append((lote, lid, qtd_ini, sit_val, mortes_acum, vendidas_acum, aves_vivas, aves_disponiveis))
        total_aves_vivas_geral += aves_vivas
        if sit_val == "Ativo":
            total_lotes_ativos += 1

    custo_fixo_por_ave_viva_pool = 0.0
    custo_fixo_por_lote_ativo_pool = 0.0
    custo_var_geral_por_ave_pool = 0.0
    custo_var_por_lote = {}

    if not custos_df.empty:
        for _, c in custos_df.iterrows():
            t_custo = str(c["tipo_custo"] or "Variável")
            val_c = float(c["valor"] or 0.0)
            lid_c = None if c["lote_id"] is None or pd.isna(c["lote_id"]) or str(c["lote_id"]).strip() in ("", "None", "Geral (Ratear)") else str(c["lote_id"]).strip()
            base_rateio = str(c["rateio_base"] or "Por Ave Viva")

            if t_custo == "Fixo":
                if base_rateio == "Por Lote Ativo" and total_lotes_ativos > 0:
                    custo_fixo_por_lote_ativo_pool += val_c / total_lotes_ativos
                elif total_aves_vivas_geral > 0:
                    custo_fixo_por_ave_viva_pool += val_c / total_aves_vivas_geral
            else:
                if lid_c:
                    custo_var_por_lote[lid_c] = custo_var_por_lote.get(lid_c, 0.0) + val_c
                elif total_aves_vivas_geral > 0:
                    custo_var_geral_por_ave_pool += val_c / total_aves_vivas_geral

    linhas_resumo = []
    linhas_custos = []

    for lote, lid, qtd_ini, sit_val, mortes_acum, vendidas_acum, aves_vivas, aves_disponiveis in base_lotes:
        r_lote = reg_df[reg_df["lote_id"] == lid] if not reg_df.empty else pd.DataFrame()
        a_lote = alim_df[alim_df["lote_id"] == lid] if not alim_df.empty else pd.DataFrame()
        p_lote = pesagens_df[pesagens_df["lote_id"] == lid].sort_values(by=["data_pesagem", "id"]) if not pesagens_df.empty else pd.DataFrame()
        v_lote = vendas_df[vendas_df["lote_id"] == lid] if not vendas_df.empty else pd.DataFrame()

        taxa_mort = (mortes_acum / qtd_ini * 100) if qtd_ini > 0 else 0.0

        cons_alim_kg = float(a_lote["consumo_liquido_kg"].sum()) if not a_lote.empty else 0.0
        cons_reg_kg = 0.0
        custo_reg_racao = 0.0
        if not r_lote.empty:
            for _, rr in r_lote.iterrows():
                if rr["racao_kg"] is not None and not pd.isna(rr["racao_kg"]):
                    if "[via Alimentação]" not in str(rr["observacoes"] or ""):
                        kg_val = float(rr["racao_kg"])
                        cons_reg_kg += kg_val
                        custo_reg_racao += kg_val * racao_custo_padrao

        racao_acum = cons_alim_kg + cons_reg_kg
        custo_alim_lote = (float(a_lote["custo_estimado"].sum()) if not a_lote.empty else 0.0) + custo_reg_racao
        consumo_por_ave_g = (racao_acum * 1000 / aves_vivas) if aves_vivas > 0 and racao_acum > 0 else 0.0

        custo_pint_unit = 0.0 if lote["custo_pintinho"] is None or pd.isna(lote["custo_pintinho"]) else float(lote["custo_pintinho"])
        custo_pintinhos = qtd_ini * custo_pint_unit

        custo_var_lote = custo_var_por_lote.get(lid, 0.0) + (custo_var_geral_por_ave_pool * aves_vivas)
        rateio_fixo_lote = (custo_fixo_por_ave_viva_pool * aves_vivas) + (custo_fixo_por_lote_ativo_pool if sit_val == "Ativo" else 0.0)

        custo_total_lote = custo_pintinhos + custo_alim_lote + custo_var_lote + rateio_fixo_lote
        base_aves_custo = aves_disponiveis if aves_disponiveis > 0 else aves_vivas
        custo_por_ave = (custo_total_lote / base_aves_custo) if base_aves_custo > 0 else 0.0

        d_aloj = parse_data_segura(lote["data_alojamento"])
        idade_dias = max((date.today() - d_aloj).days, 0) if d_aloj else None

        peso_med_atual_kg = None
        gpd_atual = None
        ca_atual = None
        if not p_lote.empty:
            ultima_p = p_lote.iloc[-1]
            peso_med_atual_kg = float(ultima_p["peso_medio_kg"])
            if ultima_p["gpd_g_dia"] is not None and not pd.isna(ultima_p["gpd_g_dia"]):
                gpd_atual = float(ultima_p["gpd_g_dia"])
            if racao_acum > 0 and base_aves_custo > 0 and peso_med_atual_kg > 0:
                ca_atual = round(racao_acum / (base_aves_custo * peso_med_atual_kg), 2)

        biomassa_kg = (base_aves_custo * peso_med_atual_kg) if (peso_med_atual_kg is not None and peso_med_atual_kg > 0) else 0.0
        custo_por_kg = (custo_total_lote / biomassa_kg) if biomassa_kg > 0 else 0.0

        receita_lote = float(v_lote["valor_total"].sum()) if not v_lote.empty else 0.0
        custo_aves_vendidas = vendidas_acum * custo_por_ave
        lucro_estimado_lote = receita_lote - custo_aves_vendidas

        _, _, status_carencia = obter_carencia_lote(lid, sanidade_df)
        tipo_ave_val = "" if pd.isna(lote["tipo_ave"]) else str(lote["tipo_ave"])

        linhas_resumo.append({
            "Lote": lid,
            "Situação": sit_val,
            "Carência": status_carencia,
            "Data Alojamento": d_aloj.isoformat() if d_aloj else "Não informada",
            "Idade (dias)": f"{idade_dias} dias" if idade_dias is not None else "Não informada",
            "Qtd. Inicial": qtd_ini,
            "Mortes Acum.": mortes_acum,
            "Vendidas": vendidas_acum,
            "Aves Disponíveis": aves_disponiveis,
            "Mortalidade (%)": round(taxa_mort, 2),
            "Consumo Acum. (kg)": round(racao_acum, 2),
            "Consumo/Ave (g)": round(consumo_por_ave_g, 1),
            "Peso Médio (kg)": round(peso_med_atual_kg, 3) if peso_med_atual_kg is not None else 0.0,
            "GPD (g/dia)": round(gpd_atual, 1) if gpd_atual is not None else 0.0,
            "CA Atual": round(ca_atual, 2) if ca_atual is not None else 0.0,
            "Custo Total (R$)": round(custo_total_lote, 2),
            "Custo/Ave (R$)": round(custo_por_ave, 2),
            "Tipo de Ave": tipo_ave_val or "-",
        })

        linhas_custos.append({
            "Lote": lid,
            "Aves Disponíveis": aves_disponiveis,
            "Pintinhos (R$)": round(custo_pintinhos, 2),
            "Alimentação (R$)": round(custo_alim_lote, 2),
            "Variáveis (R$)": round(custo_var_lote, 2),
            "Rateio Fixo (R$)": round(rateio_fixo_lote, 2),
            "Custo Total (R$)": round(custo_total_lote, 2),
            "Custo/Ave (R$)": round(custo_por_ave, 2),
            "Custo/kg (R$)": round(custo_por_kg, 2),
            "Receita Vendas (R$)": round(receita_lote, 2),
            "Resultado Vendas (R$)": round(lucro_estimado_lote, 2),
        })

    return pd.DataFrame(linhas_resumo), pd.DataFrame(linhas_custos)


def gerar_relatorio_ia(resumo_df, custos_lote_df, estoque_df, vendas_df, custos_df):
    total_disp = int(resumo_df["Aves Disponíveis"].sum()) if not resumo_df.empty else 0
    total_mort = int(resumo_df["Mortes Acum."].sum()) if not resumo_df.empty else 0
    total_racao = float(resumo_df["Consumo Acum. (kg)"].sum()) if not resumo_df.empty else 0.0
    total_custo = float(custos_lote_df["Custo Total (R$)"].sum()) if not custos_lote_df.empty else 0.0
    total_vendas = float(vendas_df["valor_total"].sum()) if not vendas_df.empty else 0.0

    linhas = [
        f"RESUMO GRANJA VIEIRA ({date.today().isoformat()})",
        f"- Aves disponíveis: {total_disp} | Mortes acumuladas: {total_mort} | Ração consumida: {total_racao:.2f} kg",
        f"- Custo total acumulado nos lotes: R$ {total_custo:.2f} | Receita de vendas: R$ {total_vendas:.2f}",
        "",
        "LOTES:",
    ]
    for _, r in resumo_df.iterrows():
        linhas.append(
            f"  * {r['Lote']} ({r['Situação']}): {r['Aves Disponíveis']} aves disp., mort. {r['Mortalidade (%)']}%, "
            f"cons. {r['Consumo Acum. (kg)']} kg, peso méd. {r['Peso Médio (kg)']} kg, GPD {r['GPD (g/dia)']} g/d, "
            f"CA {r['CA Atual']}, custo/ave R$ {r['Custo/Ave (R$)']:.2f}, {r['Carência']}"
        )

    linhas.append("")
    linhas.append("ESTOQUE:")
    if estoque_df.empty:
        linhas.append("  * Sem compras lançadas.")
    else:
        for _, e in estoque_df.iterrows():
            linhas.append(f"  * {e['Produto']}: saldo {e['Saldo Atual']} {e['Unidade']} (custo médio R$ {e['Custo Médio (R$)']:.2f}) - {e['Alerta']}")

    return "\n".join(linhas)


st.set_page_config(page_title="Granja Vieira", page_icon="🐔", layout="wide")
init_db()

st.title("🐔 Granja Vieira — Gestão Avícola Completa")
st.caption("Sistema completo: Registro Rápido, Lotes, Alimentação, Estoque, Pesagens, Sanidade, Custos, Vendas, Fluxo de Caixa e Painel IA")

lotes_df, estoque_df, compras_df, alim_df, reg_df, pesagens_df, sanidade_df, custos_df, vendas_df = obter_dados_sistema()
resumo_df, custos_lote_df = montar_resumo_e_custos(
    lotes_df, estoque_df, alim_df, reg_df, pesagens_df, sanidade_df, custos_df, vendas_df
)

total_aves_disp = int(resumo_df["Aves Disponíveis"].sum()) if not resumo_df.empty else 0
total_aves_ini = int(resumo_df["Qtd. Inicial"].sum()) if not resumo_df.empty else 0
total_mortes = int(resumo_df["Mortes Acum."].sum()) if not resumo_df.empty else 0
total_racao = float(resumo_df["Consumo Acum. (kg)"].sum()) if not resumo_df.empty else 0.0
total_custo_geral = float(custos_lote_df["Custo Total (R$)"].sum()) if not custos_lote_df.empty else 0.0
lotes_ativos = int((resumo_df["Situação"] == "Ativo").sum()) if not resumo_df.empty else 0

abas = st.tabs([
    "⚡ Registro Rápido",
    "🐔 Lotes",
    "🌾 Alimentação",
    "📦 Compras e Estoque",
    "⚖️ Pesagens",
    "🩺 Sanidade",
    "💰 Custos e Preço",
    "🤝 Vendas",
    "💵 Fluxo de Caixa",
    "📊 Painel e Relatório IA",
])

with abas[0]:
    st.subheader("Registro Diário Rápido")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Aves Disponíveis", total_aves_disp, f"de {total_aves_ini} iniciais")
    c2.metric("Lotes Ativos", lotes_ativos)
    c3.metric("Mortes Acumuladas", total_mortes)
    c4.metric("Consumo Acum. (kg)", f"{total_racao:.2f}")
    c5.metric("Custo Total Lotes", f"R$ {total_custo_geral:.2f}")

    st.divider()
    data_reg = st.date_input("Data do registro", value=date.today())

    st.markdown("**Lançamento por lote (deixe ração em branco se não houver medição registrada):**")
    entradas = []
    for _, lote in resumo_df.iterrows():
        lid = lote["Lote"]
        st.markdown(f"**{lid}** — Aves disponíveis: **{lote['Aves Disponíveis']}** | {lote['Carência']}")
        col_m, col_r, col_o = st.columns([1, 1, 2])
        mortes = col_m.number_input(
            f"Mortes ({lid})", min_value=0, max_value=max(int(lote["Aves Disponíveis"]), 0), value=0, step=1, key=f"m_{lid}"
        )
        racao_txt = col_r.text_input(
            f"Ração consumida kg ({lid})", value="", placeholder="Ex.: 12.5", key=f"r_{lid}"
        )
        obs = col_o.text_input(
            f"Observações / sanidade ({lid})", value="", placeholder="Opcional", key=f"o_{lid}"
        )
        entradas.append((lid, mortes, racao_txt, obs))

    if st.button("💾 Salvar Registro do Dia", type="primary"):
        conn = get_conn()
        cur = conn.cursor()
        salvos = 0
        erros = []

        for lid, mortes, racao_txt, obs in entradas:
            racao_val = None
            if racao_txt.strip():
                try:
                    racao_val = parse_numero_opcional(racao_txt)
                    if racao_val is not None and racao_val < 0:
                        erros.append(f"{lid}: ração não pode ser negativa.")
                        continue
                except ValueError:
                    erros.append(f"{lid}: valor de ração '{racao_txt}' inválido.")
                    continue

            duplicado = cur.execute(
                "SELECT COUNT(*) FROM registros_diarios WHERE data_registro = ? AND lote_id = ?",
                (data_reg.isoformat(), lid),
            ).fetchone()[0]
            if duplicado > 0:
                st.warning(f"⚠️ Já existe registro para **{lid}** na data **{data_reg.isoformat()}**. Salvando mesmo assim para conferência.")

            if mortes > 0 or racao_val is not None or obs.strip():
                cur.execute("""
                    INSERT INTO registros_diarios (data_registro, lote_id, aves_mortas, racao_kg, observacoes)
                    VALUES (?, ?, ?, ?, ?)
                """, (data_reg.isoformat(), lid, int(mortes), racao_val, obs.strip()))
                salvos += 1

        conn.commit()
        conn.close()

        for err in erros:
            st.error(err)
        if salvos > 0:
            st.success(f"✅ {salvos} registro(s) salvo(s) com sucesso!")
            st.rerun()
        elif not erros:
            st.info("Nenhuma alteração preenchida para salvar.")

with abas[1]:
    st.subheader("Controle de Lotes")
    st.dataframe(resumo_df, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**Editar dados do lote (data de alojamento, tipo de ave, origem, custo ou situação):**")
    lote_escolhido = st.selectbox("Selecione o lote", resumo_df["Lote"].tolist())

    conn = get_conn()
    lote_row = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_escolhido,)).fetchone()
    conn.close()

    col_a, col_b, col_c = st.columns(3)
    d_aloj_salva = parse_data_segura(lote_row["data_alojamento"])
    tem_data = d_aloj_salva is not None
    marcar_data = col_a.checkbox("Informar data de alojamento", value=tem_data)
    data_aloj_val = d_aloj_salva if d_aloj_salva else date.today()
    nova_data_aloj = col_a.date_input("Data de alojamento", value=data_aloj_val, disabled=not marcar_data)

    tipo_atual = "" if lote_row["tipo_ave"] is None else str(lote_row["tipo_ave"])
    sit_atual = str(lote_row["situacao"] or "Ativo")
    opcoes_sit = ["Ativo", "Encerrado", "Planejado"]
    idx_sit = opcoes_sit.index(sit_atual) if sit_atual in opcoes_sit else 0

    novo_tipo = col_b.text_input("Tipo de ave / raça", value=tipo_atual, placeholder="Ex.: Mestiço Índio Gigante")
    nova_sit = col_c.selectbox("Situação", opcoes_sit, index=idx_sit)

    col_d, col_e, col_f = st.columns(3)
    origem_atual = "" if lote_row["origem"] is None else str(lote_row["origem"])
    obs_atual = "" if lote_row["observacoes"] is None else str(lote_row["observacoes"])

    nova_origem = col_d.text_input("Origem dos pintinhos", value=origem_atual)
    custo_txt = col_e.text_input(
        "Custo por pintinho (R$)",
        value="" if lote_row["custo_pintinho"] is None else str(lote_row["custo_pintinho"]),
        placeholder="Opcional",
    )
    nova_obs = col_f.text_input("Observações do lote", value=obs_atual)

    if st.button("Atualizar Lote"):
        custo_val = None
        erro_custo = False
        if custo_txt.strip():
            try:
                custo_val = parse_numero_opcional(custo_txt)
            except ValueError:
                st.error("Custo por pintinho inválido.")
                erro_custo = True

        if not erro_custo:
            data_salvar = nova_data_aloj.isoformat() if marcar_data else None
            conn = get_conn()
            conn.execute("""
                UPDATE lotes
                SET data_alojamento = ?, tipo_ave = ?, situacao = ?, origem = ?, custo_pintinho = ?, observacoes = ?
                WHERE id = ?
            """, (data_salvar, novo_tipo.strip(), nova_sit, nova_origem.strip(), custo_val, nova_obs.strip(), lote_escolhido))
            conn.commit()
            conn.close()
            st.success(f"✅ {lote_escolhido} atualizado!")
            st.rerun()

with abas[2]:
    st.subheader("Alimentação por Lote (Consumo e Sobras)")
    st.caption("Separa quantidade fornecida de sobra medida. Quando não há sobra medida, o consumo é marcado como estimado pela quantidade fornecida.")

    produtos_disponiveis = estoque_df["Produto"].tolist() if not estoque_df.empty else []
    opcoes_prod = produtos_disponiveis + ["Outro / Informar manualmente"]

    col1, col2, col3, col4 = st.columns(4)
    data_alim = col1.date_input("Data da alimentação", value=date.today(), key="data_alim")
    lote_alim = col2.selectbox("Lote", resumo_df["Lote"].tolist(), key="lote_alim")
    fase_alim = col3.selectbox("Fase alimentar", ["Não informada", "Inicial", "Crescimento", "Terminação", "Milho / Verde / Extra"], key="fase_alim")
    sel_prod = col4.selectbox("Item do estoque", opcoes_prod, key="sel_prod")

    prod_manual = ""
    if sel_prod == "Outro / Informar manualmente":
        prod_manual = st.text_input("Nome do alimento/ração", placeholder="Ex.: Ração Crescimento")

    col5, col6, col7 = st.columns(3)
    forn_txt = col5.text_input("Quantidade fornecida (kg)", placeholder="Ex.: 15.0", key="forn_txt")
    sobra_txt = col6.text_input("Sobra medida (kg) — opcional", placeholder="Deixe vazio se não pesou sobra", key="sobra_txt")
    obs_alim = col7.text_input("Observação", placeholder="Opcional", key="obs_alim")

    if st.button("🌾 Registrar Alimentação", type="primary"):
        produto_final = prod_manual.strip() if sel_prod == "Outro / Informar manualmente" else sel_prod
        try:
            qtd_forn = parse_numero_opcional(forn_txt)
            qtd_sobra = parse_numero_opcional(sobra_txt)
        except ValueError:
            st.error("Valores de quantidade inválidos. Use números como 10 ou 12.5.")
            qtd_forn, qtd_sobra = None, None

        if not produto_final:
            st.error("Informe o nome do alimento/ração.")
        elif qtd_forn is None or qtd_forn <= 0:
            st.error("Informe uma quantidade fornecida maior que zero.")
        elif qtd_sobra is not None and (qtd_sobra < 0 or qtd_sobra > qtd_forn):
            st.error("A sobra medida deve ser entre 0 e a quantidade fornecida.")
        else:
            sobra_medida_flag = 1 if qtd_sobra is not None else 0
            consumo_liq = (qtd_forn - qtd_sobra) if sobra_medida_flag else qtd_forn

            custo_unit = 0.0
            if not estoque_df.empty and produto_final in estoque_df["Produto"].values:
                custo_unit = float(estoque_df.loc[estoque_df["Produto"] == produto_final, "Custo Médio (R$)"].iloc[0])
            custo_est = round(consumo_liq * custo_unit, 2)

            conn = get_conn()
            cur = conn.cursor()
            cur.execute("""
                INSERT INTO alimentacao
                (data_registro, lote_id, produto_estoque, fase_alimentar, qtd_fornecida_kg, qtd_sobra_kg, consumo_liquido_kg, sobra_medida, custo_estimado, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data_alim.isoformat(), lote_alim, produto_final, fase_alim,
                float(qtd_forn), float(qtd_sobra) if sobra_medida_flag else None,
                float(consumo_liq), sobra_medida_flag, custo_est, obs_alim.strip()
            ))
            nota_reg = f"[via Alimentação] {produto_final} ({fase_alim}) - {'medido' if sobra_medida_flag else 'estimado pelo fornecido'}"
            if obs_alim.strip():
                nota_reg += f" | {obs_alim.strip()}"
            cur.execute("""
                INSERT INTO registros_diarios (data_registro, lote_id, aves_mortas, racao_kg, observacoes)
                VALUES (?, ?, 0, ?, ?)
            """, (data_alim.isoformat(), lote_alim, float(consumo_liq), nota_reg))
            conn.commit()
            conn.close()
            st.success(f"✅ Alimentação registrada para {lote_alim}: consumo de {consumo_liq:.2f} kg (custo estimado: R$ {custo_est:.2f}).")
            st.rerun()

    st.divider()
    st.markdown("**Lançamentos de alimentação registrados:**")
    if alim_df.empty:
        st.info("Nenhuma alimentação lançada ainda.")
    else:
        exibir_alim = alim_df.copy()
        exibir_alim["Tipo de Consumo"] = exibir_alim["sobra_medida"].apply(
            lambda x: "Líquido (com sobra medida)" if int(x) == 1 else "Estimado (pelo fornecido)"
        )
        st.dataframe(
            exibir_alim[["data_registro", "lote_id", "produto_estoque", "fase_alimentar", "qtd_fornecida_kg", "qtd_sobra_kg", "consumo_liquido_kg", "Tipo de Consumo", "custo_estimado", "observacoes"]]
            .sort_values(by=["data_registro", "id"], ascending=False),
            width="stretch",
            hide_index=True,
        )

with abas[3]:
    st.subheader("Compras e Estoque de Insumos")
    st.caption("Compras atualizam o estoque e o custo médio. O custo de produção do lote é calculado pelo consumo efetivo, evitando dupla contagem.")

    if not estoque_df.empty:
        alertas = estoque_df[estoque_df["Alerta"] != "✅ OK"]
        for _, al in alertas.iterrows():
            st.warning(f"⚠️ **Estoque baixo:** {al['Produto']} com saldo de {al['Saldo Atual']} {al['Unidade']} (mínimo: {al['Estoque Mínimo']}).")
        st.dataframe(estoque_df, width="stretch", hide_index=True)
    else:
        st.info("Cadastre sua primeira compra abaixo para iniciar o controle de estoque.")

    st.divider()
    st.markdown("**Registrar nova compra / entrada no estoque:**")
    c_a, c_b, c_c, c_d = st.columns(4)
    data_comp = c_a.date_input("Data da compra", value=date.today(), key="data_comp")
    prod_comp = c_b.text_input("Produto / Insumo", placeholder="Ex.: Ração Inicial", key="prod_comp")
    cat_comp = c_c.selectbox("Categoria", ["Ração", "Milho / Ingrediente", "Sanidade / Vacina", "Pintinhos", "Manejo / Cama", "Outros"], key="cat_comp")
    forn_comp = c_d.text_input("Fornecedor", placeholder="Opcional", key="forn_comp")

    c_e, c_f, c_g, c_h = st.columns(4)
    qtd_comp_txt = c_e.text_input("Quantidade comprada", placeholder="Ex.: 100", key="qtd_comp")
    unid_comp = c_f.selectbox("Unidade", ["kg", "sc", "un", "L"], key="unid_comp")
    preco_unit_txt = c_g.text_input("Preço unitário (R$)", placeholder="Ex.: 2.80", key="preco_unit_comp")
    min_est_txt = c_h.text_input("Alerta estoque mínimo", value="20", key="min_est_comp")

    c_i, c_j = st.columns(2)
    lote_comp = c_i.selectbox("Lote relacionado (opcional)", ["Nenhum (Estoque Geral)"] + resumo_df["Lote"].tolist(), key="lote_comp")
    obs_comp = c_j.text_input("Observações da compra", placeholder="Opcional", key="obs_comp")

    if st.button("🛒 Salvar Compra no Estoque", type="primary"):
        try:
            qtd_c = parse_numero_opcional(qtd_comp_txt)
            preco_u = parse_numero_opcional(preco_unit_txt)
            min_e = parse_numero_opcional(min_est_txt)
        except ValueError:
            st.error("Quantidade, preço unitário ou estoque mínimo inválidos.")
            qtd_c, preco_u, min_e = None, None, None

        if not prod_comp.strip():
            st.error("Informe o nome do produto.")
        elif qtd_c is None or qtd_c <= 0 or preco_u is None or preco_u < 0:
            st.error("Informe quantidade maior que zero e preço unitário válido.")
        else:
            val_tot = round(qtd_c * preco_u, 2)
            lote_ref = None if lote_comp == "Nenhum (Estoque Geral)" else lote_comp
            conn = get_conn()
            conn.execute("""
                INSERT INTO compras_estoque
                (data_compra, produto, categoria, fornecedor, quantidade, unidade, preco_unitario, valor_total, lote_id, estoque_minimo, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data_comp.isoformat(), prod_comp.strip(), cat_comp, forn_comp.strip(),
                float(qtd_c), unid_comp, float(preco_u), float(val_tot),
                lote_ref, float(min_e if min_e is not None else 0.0), obs_comp.strip()
            ))
            conn.commit()
            conn.close()
            st.success(f"✅ Compra de {qtd_c} {unid_comp} de {prod_comp.strip()} salva (Total: R$ {val_tot:.2f}).")
            st.rerun()

    st.divider()
    st.markdown("**Histórico de compras:**")
    if compras_df.empty:
        st.info("Nenhuma compra registrada até o momento.")
    else:
        st.dataframe(compras_df.sort_values(by=["data_compra", "id"], ascending=False), width="stretch", hide_index=True)

with abas[4]:
    st.subheader("Pesagens e Desempenho Zootécnico (Peso Médio, GPD e Conversão Alimentar)")
    st.caption("Informe o número de aves pesadas e o peso total (em kg) da amostra/lote. O sistema calcula o peso médio, o ganho de peso diário (GPD) e a conversão alimentar (CA).")

    p1, p2, p3, p4 = st.columns(4)
    data_pes = p1.date_input("Data da pesagem", value=date.today(), key="data_pes")
    lote_pes = p2.selectbox("Lote", resumo_df["Lote"].tolist(), key="lote_pes")
    aves_pes_qtd = p3.number_input("Aves pesadas (qtd.)", min_value=1, value=10, step=1, key="aves_pes_qtd")
    peso_tot_txt = p4.text_input("Peso total pesado (kg)", placeholder="Ex.: 18.5", key="peso_tot_txt")

    obs_pes = st.text_input("Observações da pesagem", placeholder="Ex.: Pesagem semanal de amostra", key="obs_pes")

    if st.button("⚖️ Salvar Pesagem", type="primary"):
        try:
            peso_tot = parse_numero_opcional(peso_tot_txt)
        except ValueError:
            st.error("Peso total inválido. Use números como 18.5.")
            peso_tot = None

        if peso_tot is None or peso_tot <= 0:
            st.error("Informe um peso total maior que zero.")
        else:
            peso_med_kg = round(peso_tot / int(aves_pes_qtd), 4)
            lote_info = resumo_df[resumo_df["Lote"] == lote_pes].iloc[0]
            racao_acum_lote = float(lote_info["Consumo Acum. (kg)"])
            aves_disp_lote = int(lote_info["Aves Disponíveis"])

            conn = get_conn()
            lote_db = conn.execute("SELECT data_alojamento FROM lotes WHERE id = ?", (lote_pes,)).fetchone()
            conn.close()
            d_aloj_obj = parse_data_segura(lote_db["data_alojamento"]) if lote_db else None

            gpd_val, ca_val = calcular_metricas_pesagem(
                lote_pes, data_pes, peso_med_kg, racao_acum_lote, aves_disp_lote, d_aloj_obj, pesagens_df
            )

            conn = get_conn()
            conn.execute("""
                INSERT INTO pesagens
                (data_pesagem, lote_id, aves_pesadas, peso_total_kg, peso_medio_kg, gpd_g_dia, conversao_alimentar, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data_pes.isoformat(), lote_pes, int(aves_pes_qtd), float(peso_tot),
                float(peso_med_kg), gpd_val, ca_val, obs_pes.strip()
            ))
            conn.commit()
            conn.close()
            st.success(f"✅ Pesagem salva para {lote_pes}: Peso médio de {peso_med_kg:.3f} kg ({peso_med_kg*1000:.0f} g).")
            st.rerun()

    st.divider()
    st.markdown("**Histórico de pesagens:**")
    if pesagens_df.empty:
        st.info("Nenhuma pesagem registrada ainda.")
    else:
        exibir_pes = pesagens_df.copy()
        exibir_pes["Peso Médio (g)"] = (exibir_pes["peso_medio_kg"] * 1000).round(0)
        st.dataframe(
            exibir_pes[["data_pesagem", "lote_id", "aves_pesadas", "peso_total_kg", "peso_medio_kg", "Peso Médio (g)", "gpd_g_dia", "conversao_alimentar", "observacoes"]]
            .sort_values(by=["data_pesagem", "id"], ascending=False),
            width="stretch",
            hide_index=True,
        )

with abas[5]:
    st.subheader("Sanidade e Controle de Carência")
    st.caption("Registre vacinas, medicamentos ou ocorrências. Quando houver dias de carência, o sistema calcula a data de liberação e alerta o lote.")

    carencia_linhas = []
    for lid in resumo_df["Lote"].tolist():
        em_car, d_lib_str, status_txt = obter_carencia_lote(lid, sanidade_df)
        carencia_linhas.append({
            "Lote": lid,
            "Status Sanitário": status_txt,
            "Data de Liberação": d_lib_str,
        })
    st.dataframe(pd.DataFrame(carencia_linhas), width="stretch", hide_index=True)

    st.divider()
    st.markdown("**Registrar aplicação de vacina, medicamento ou ocorrência sanitária:**")
    s1, s2, s3, s4 = st.columns(4)
    data_san = s1.date_input("Data da aplicação / ocorrência", value=date.today(), key="data_san")
    lote_san = s2.selectbox("Lote", resumo_df["Lote"].tolist(), key="lote_san")
    tipo_san = s3.selectbox("Tipo de evento", ["Vacina", "Medicamento / Antibiótico", "Suplemento / Vitamina", "Ocorrência / Sintoma"], key="tipo_san")
    prod_san = s4.text_input("Produto / Vacina / Ocorrência", placeholder="Ex.: Newcastle / Enrofloxacino", key="prod_san")

    s5, s6, s7, s8 = st.columns(4)
    dose_san = s5.text_input("Dose / via / detalhe", placeholder="Ex.: 0,2 ml água", key="dose_san")
    carencia_dias_val = s6.number_input("Carência (dias)", min_value=0, value=0, step=1, key="carencia_dias_val")
    resp_san = s7.text_input("Responsável", placeholder="Opcional", key="resp_san")
    obs_san = s8.text_input("Observações", placeholder="Opcional", key="obs_san")

    data_lib_prevista = data_san + timedelta(days=int(carencia_dias_val))
    st.info(f"📅 Data de liberação calculada para este lançamento: **{data_lib_prevista.isoformat()}** ({int(carencia_dias_val)} dia(s) de carência).")

    if st.button("🩺 Salvar Registro Sanitário", type="primary"):
        if not prod_san.strip():
            st.error("Informe o nome do produto, vacina ou ocorrência.")
        else:
            conn = get_conn()
            conn.execute("""
                INSERT INTO sanidade
                (data_aplicacao, lote_id, tipo_evento, produto_tratamento, dose_observacao, carencia_dias, data_liberacao, responsavel, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data_san.isoformat(), lote_san, tipo_san, prod_san.strip(),
                dose_san.strip(), int(carencia_dias_val), data_lib_prevista.isoformat(),
                resp_san.strip(), obs_san.strip()
            ))
            conn.commit()
            conn.close()
            st.success(f"✅ Registro sanitário salvo para {lote_san} (liberação em {data_lib_prevista.isoformat()}).")
            st.rerun()

    st.divider()
    st.markdown("**Histórico sanitário e de carência:**")
    if sanidade_df.empty:
        st.info("Nenhum registro sanitário lançado ainda.")
    else:
        st.dataframe(sanidade_df.sort_values(by=["data_aplicacao", "id"], ascending=False), width="stretch", hide_index=True)

with abas[6]:
    st.subheader("Custos de Produção e Simulador de Preço")
    st.caption("Separa pintinhos, alimentação consumida, custos variáveis e rateio de custos fixos — sem dupla contagem com o estoque.")

    if not custos_lote_df.empty:
        st.dataframe(custos_lote_df, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**Lançar custo variável ou custo fixo:**")
    cu1, cu2, cu3, cu4 = st.columns(4)
    data_custo = cu1.date_input("Data do custo", value=date.today(), key="data_custo")
    tipo_custo_sel = cu2.selectbox("Tipo de custo", ["Variável", "Fixo"], key="tipo_custo_sel")
    desc_custo = cu3.text_input("Descrição", placeholder="Ex.: Cama de frango / Energia / Gás", key="desc_custo")
    val_custo_txt = cu4.text_input("Valor (R$)", placeholder="Ex.: 150.00", key="val_custo_txt")

    cu5, cu6, cu7 = st.columns(3)
    lote_custo_sel = cu5.selectbox("Destino / Lote", ["Geral (Ratear)"] + resumo_df["Lote"].tolist(), key="lote_custo_sel")
    rateio_sel = cu6.selectbox("Base de rateio (quando geral ou fixo)", ["Por Ave Viva", "Por Lote Ativo"], key="rateio_sel")
    obs_custo = cu7.text_input("Observação", placeholder="Opcional", key="obs_custo")

    if st.button("💳 Salvar Custo", type="primary"):
        try:
            val_custo = parse_numero_opcional(val_custo_txt)
        except ValueError:
            st.error("Valor de custo inválido.")
            val_custo = None

        if not desc_custo.strip():
            st.error("Informe a descrição do custo.")
        elif val_custo is None or val_custo <= 0:
            st.error("Informe um valor maior que zero.")
        else:
            lote_db_val = None if lote_custo_sel == "Geral (Ratear)" else lote_custo_sel
            conn = get_conn()
            conn.execute("""
                INSERT INTO custos_operacionais
                (data_lancamento, tipo_custo, descricao, valor, lote_id, rateio_base, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                data_custo.isoformat(), tipo_custo_sel, desc_custo.strip(),
                float(val_custo), lote_db_val, rateio_sel, obs_custo.strip()
            ))
            conn.commit()
            conn.close()
            st.success(f"✅ Custo ({tipo_custo_sel}) de R$ {val_custo:.2f} salvo!")
            st.rerun()

    st.divider()
    st.markdown("**Simulador de Preço e Margem por Lote:**")
    sim1, sim2, sim3 = st.columns(3)
    lote_sim = sim1.selectbox("Lote para simular", resumo_df["Lote"].tolist(), key="lote_sim")
    modo_sim = sim2.selectbox("Base de venda", ["Por Ave", "Por kg"], key="modo_sim")
    margem_desejada_pct = sim3.number_input("Margem líquida desejada (%)", min_value=0.0, max_value=80.0, value=20.0, step=2.0, key="margem_desejada_pct")

    linha_custo_sim = custos_lote_df[custos_lote_df["Lote"] == lote_sim].iloc[0]
    linha_res_sim = resumo_df[resumo_df["Lote"] == lote_sim].iloc[0]
    custo_base_unit = float(linha_custo_sim["Custo/Ave (R$)"]) if modo_sim == "Por Ave" else float(linha_custo_sim["Custo/kg (R$)"])
    qtd_sim = int(linha_res_sim["Aves Disponíveis"]) if modo_sim == "Por Ave" else round(int(linha_res_sim["Aves Disponíveis"]) * float(linha_res_sim["Peso Médio (kg)"]), 2)

    if custo_base_unit > 0:
        fator_margem = max(1.0 - (margem_desejada_pct / 100.0), 0.05)
        preco_min_sugerido = custo_base_unit / fator_margem
        receita_prevista = preco_min_sugerido * qtd_sim
        custo_previsto = custo_base_unit * qtd_sim
        lucro_previsto = receita_prevista - custo_previsto

        m1, m2, m3, m4 = st.columns(4)
        m1.metric(f"Custo Base ({modo_sim})", f"R$ {custo_base_unit:.2f}")
        m2.metric(f"Preço Sugerido ({modo_sim})", f"R$ {preco_min_sugerido:.2f}")
        m3.metric("Receita Prevista", f"R$ {receita_prevista:.2f}")
        m4.metric("Lucro Estimado", f"R$ {lucro_previsto:.2f}")
    else:
        st.info("Cadastre custo por pintinho/alimentação/custos (e pesagem, se for por kg) para calcular o preço sugerido deste lote.")

    if not custos_df.empty:
        st.divider()
        st.markdown("**Lançamentos de custos operacionais:**")
        st.dataframe(custos_df.sort_values(by=["data_lancamento", "id"], ascending=False), width="stretch", hide_index=True)

with abas[7]:
    st.subheader("Vendas e Controle de Carência")
    st.caption("Verifica disponibilidade de aves e alerta/trava lotes que ainda estejam em período de carência sanitária.")

    v1, v2, v3, v4 = st.columns(4)
    data_venda = v1.date_input("Data da venda", value=date.today(), key="data_venda")
    lote_venda = v2.selectbox("Lote", resumo_df["Lote"].tolist(), key="lote_venda")
    comprador_v = v3.text_input("Comprador / Cliente", placeholder="Opcional", key="comprador_v")
    modalidade_v = v4.selectbox("Modalidade", ["Ave Viva (Unidade)", "Peso / kg"], key="modalidade_v")

    em_carencia_v, d_lib_v, status_car_v = obter_carencia_lote(lote_venda, sanidade_df)
    lote_v_row = resumo_df[resumo_df["Lote"] == lote_venda].iloc[0]
    aves_disp_v = int(lote_v_row["Aves Disponíveis"])

    if em_carencia_v:
        st.error(f"🚫 **ATENÇÃO — {lote_venda} está em período de carência até {d_lib_v}!** Venda bloqueada até confirmar liberação/exceção abaixo.")
        confirmar_carencia_v = st.checkbox("Confirmo que o prazo de carência foi cumprido ou assumo responsabilidade pela venda", value=False, key="conf_car_v")
    else:
        st.success(f"✅ {lote_venda} sem restrição de carência ativa ({aves_disp_v} aves disponíveis).")
        confirmar_carencia_v = True

    v5, v6, v7, v8 = st.columns(4)
    aves_vend_qtd = v5.number_input("Aves vendidas (qtd.)", min_value=0, max_value=max(aves_disp_v, 0), value=0, step=1, key="aves_vend_qtd")
    peso_vend_txt = v6.text_input("Peso total vendido (kg)", value="0", placeholder="Ex.: 45.0", key="peso_vend_txt")
    preco_unit_v_txt = v7.text_input("Preço unitário (R$)", placeholder="Ex.: 35.00", key="preco_unit_v_txt")
    status_pag_v = v8.selectbox("Status pagamento", ["Recebido", "A Receber"], key="status_pag_v")

    obs_venda = st.text_input("Observações da venda", placeholder="Opcional", key="obs_venda")

    if st.button("🤝 Registrar Venda", type="primary"):
        try:
            peso_v = parse_numero_opcional(peso_vend_txt) or 0.0
            preco_uv = parse_numero_opcional(preco_unit_v_txt)
        except ValueError:
            st.error("Peso ou preço unitário inválidos.")
            peso_v, preco_uv = 0.0, None

        base_qtd_preco = float(aves_vend_qtd) if modalidade_v == "Ave Viva (Unidade)" else float(peso_v)

        if em_carencia_v and not confirmar_carencia_v:
            st.error("Venda bloqueada: lote em período de carência sanitária.")
        elif int(aves_vend_qtd) <= 0:
            st.error("Informe a quantidade de aves vendidas (maior que zero).")
        elif int(aves_vend_qtd) > aves_disp_v:
            st.error(f"Quantidade maior que as aves disponíveis no lote ({aves_disp_v}).")
        elif modalidade_v == "Peso / kg" and peso_v <= 0:
            st.error("Informe o peso total vendido em kg maior que zero.")
        elif preco_uv is None or preco_uv <= 0:
            st.error("Informe um preço unitário maior que zero.")
        else:
            valor_total_v = round(base_qtd_preco * preco_uv, 2)
            conn = get_conn()
            conn.execute("""
                INSERT INTO vendas
                (data_venda, lote_id, comprador, modalidade, aves_vendidas, peso_total_kg, preco_unitario, valor_total, status_pagamento, carencia_confirmada, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data_venda.isoformat(), lote_venda, comprador_v.strip(), modalidade_v,
                int(aves_vend_qtd), float(peso_v), float(preco_uv), float(valor_total_v),
                status_pag_v, 1 if confirmar_carencia_v else 0, obs_venda.strip()
            ))
            conn.commit()
            conn.close()
            st.success(f"✅ Venda registrada para {lote_venda}: {aves_vend_qtd} ave(s) — Total R$ {valor_total_v:.2f} ({status_pag_v}).")
            st.rerun()

    st.divider()
    st.markdown("**Histórico de vendas:**")
    if vendas_df.empty:
        st.info("Nenhuma venda registrada até o momento.")
    else:
        st.dataframe(vendas_df.sort_values(by=["data_venda", "id"], ascending=False), width="stretch", hide_index=True)

with abas[8]:
    st.subheader("Fluxo de Caixa")
    st.caption("Acompanha entradas recebidas, valores a receber e saídas financeiras registradas em compras e custos operacionais.")

    entradas_recebidas = float(vendas_df[vendas_df["status_pagamento"] == "Recebido"]["valor_total"].sum()) if not vendas_df.empty else 0.0
    entradas_a_receber = float(vendas_df[vendas_df["status_pagamento"] != "Recebido"]["valor_total"].sum()) if not vendas_df.empty else 0.0
    saidas_compras = float(compras_df["valor_total"].sum()) if not compras_df.empty else 0.0
    saidas_custos = float(custos_df["valor"].sum()) if not custos_df.empty else 0.0
    saidas_totais = saidas_compras + saidas_custos
    saldo_caixa_realizado = entradas_recebidas - saidas_totais

    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Entradas Recebidas", f"R$ {entradas_recebidas:.2f}")
    f2.metric("A Receber", f"R$ {entradas_a_receber:.2f}")
    f3.metric("Saídas (Compras + Custos)", f"R$ {saidas_totais:.2f}")
    f4.metric("Saldo Realizado", f"R$ {saldo_caixa_realizado:.2f}")

    movs = []
    if not vendas_df.empty:
        for _, v in vendas_df.iterrows():
            movs.append({
                "Data": v["data_venda"],
                "Tipo": "Entrada",
                "Status": v["status_pagamento"],
                "Origem": f"Venda ({v['lote_id']})",
                "Descrição": str(v["comprador"] or v["modalidade"]),
                "Valor (R$)": round(float(v["valor_total"]), 2),
            })
    if not compras_df.empty:
        for _, c in compras_df.iterrows():
            movs.append({
                "Data": c["data_compra"],
                "Tipo": "Saída",
                "Status": "Pago",
                "Origem": "Estoque / Compra",
                "Descrição": f"{c['produto']} ({c['quantidade']} {c['unidade']})",
                "Valor (R$)": round(-float(c["valor_total"]), 2),
            })
    if not custos_df.empty:
        for _, cu in custos_df.iterrows():
            movs.append({
                "Data": cu["data_lancamento"],
                "Tipo": "Saída",
                "Status": "Pago",
                "Origem": f"Custo {cu['tipo_custo']}",
                "Descrição": str(cu["descricao"]),
                "Valor (R$)": round(-float(cu["valor"]), 2),
            })

    if movs:
        movs_df = pd.DataFrame(movs).sort_values(by="Data", ascending=False)
        st.dataframe(movs_df, width="stretch", hide_index=True)
    else:
        st.info("Nenhuma movimentação financeira registrada ainda.")

with abas[9]:
    st.subheader("Painel Gerencial, Alertas, Backup e Relatório IA")

    alertas_lista = []
    for _, r in resumo_df.iterrows():
        if "Carência" in str(r["Carência"]):
            alertas_lista.append(f"🚫 {r['Lote']}: {r['Carência']}")
        if float(r["Mortalidade (%)"]) >= 5.0:
            alertas_lista.append(f"⚠️ {r['Lote']}: mortalidade acumulada em {r['Mortalidade (%)']}%.")
    if not estoque_df.empty:
        for _, e in estoque_df.iterrows():
            if e["Alerta"] != "✅ OK":
                alertas_lista.append(f"📦 Estoque baixo em {e['Produto']}: {e['Saldo Atual']} {e['Unidade']} (mín. {e['Estoque Mínimo']}).")

    if alertas_lista:
        for al_txt in alertas_lista:
            st.warning(al_txt)
    else:
        st.success("✅ Nenhum alerta crítico no momento.")

    g1, g2 = st.columns(2)
    with g1:
        st.markdown("**Aves Disponíveis por Lote**")
        st.bar_chart(resumo_df.set_index("Lote")["Aves Disponíveis"])
    with g2:
        st.markdown("**Custo Total por Lote (R$)**")
        st.bar_chart(custos_lote_df.set_index("Lote")["Custo Total (R$)"])

    st.divider()
    st.markdown("**Exportação e Backup do Banco SQLite:**")
    b1, b2 = st.columns(2)
    try:
        with open(DB_PATH, "rb") as f_db:
            b1.download_button(
                label="💾 Baixar Backup do Banco (granja_vieira.db)",
                data=f_db.read(),
                file_name=f"backup_granja_vieira_{date.today().isoformat()}.db",
                mime="application/octet-stream",
            )
    except FileNotFoundError:
        b1.info("Banco ainda não criado.")

    csv_lotes = resumo_df.to_csv(index=False).encode("utf-8-sig")
    b2.download_button(
        label="📄 Baixar Resumo dos Lotes (.CSV)",
        data=csv_lotes,
        file_name=f"resumo_lotes_granja_vieira_{date.today().isoformat()}.csv",
        mime="text/csv",
    )

    st.divider()
    st.markdown("**Resumo pronto para copiar e colar aqui na conversa (Relatório IA):**")
    texto_ia = gerar_relatorio_ia(resumo_df, custos_lote_df, estoque_df, vendas_df, custos_df)
    st.text_area("Relatório consolidado", value=texto_ia, height=240)