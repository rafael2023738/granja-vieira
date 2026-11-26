import json
import sqlite3
from datetime import date, datetime, timedelta
import pandas as pd
import streamlit as st

from ia_autonoma import executar_assistente_granja

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


def registrar_backup_antes_de_alterar(cur, tabela: str, registro_id, acao: str = "EDITAR"):
    """Salva automaticamente o estado anterior do registro antes de editar ou excluir."""
    if registro_id is None:
        return
    linha = cur.execute(f"SELECT * FROM {tabela} WHERE id = ?", (registro_id,)).fetchone()
    if linha is not None:
        dados_dict = {k: linha[k] for k in linha.keys()}
        cur.execute(
            """
            INSERT INTO auditoria_backups (data_hora, tabela_origem, registro_id, acao, dados_anteriores)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                datetime.now().isoformat(timespec="seconds"),
                tabela,
                str(registro_id),
                acao.upper(),
                json.dumps(dados_dict, ensure_ascii=False, default=str),
            ),
        )


def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS lotes (
            id TEXT PRIMARY KEY,
            nome TEXT NOT NULL,
            data_alojamento TEXT,
            qtd_inicial INTEGER NOT NULL DEFAULT 0,
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

    cur.execute("""
        CREATE TABLE IF NOT EXISTS auditoria_backups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data_hora TEXT NOT NULL,
            tabela_origem TEXT NOT NULL,
            registro_id TEXT NOT NULL,
            acao TEXT NOT NULL,
            dados_anteriores TEXT NOT NULL
        )
    """)

    cur.execute("""
        CREATE TABLE IF NOT EXISTS chat_mensagens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            criado_em TEXT NOT NULL
        )
    """)

    lotes_iniciais = [
        ("LOTE 01", "Lote 01", None, 0, "", "", None, "Ativo", ""),
        ("LOTE 02", "Lote 02", None, 0, "", "", None, "Ativo", ""),
        ("LOTE 03", "Lote 03", None, 0, "", "", None, "Ativo", ""),
    ]
    cur.executemany("""
        INSERT OR IGNORE INTO lotes
        (id, nome, data_alojamento, qtd_inicial, tipo_ave, origem, custo_pintinho, situacao, observacoes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, lotes_iniciais)

    conn.commit()
    conn.close()


def carregar_historico_chat_db():
    conn = get_conn()
    linhas = conn.execute("SELECT role, content FROM chat_mensagens ORDER BY id ASC").fetchall()
    conn.close()
    if linhas:
        return [{"role": r["role"], "content": r["content"]} for r in linhas]
    msg_inicial = (
        "Olá! Sou o **Assistente da Granja Vieira**. "
        "Converse comigo como em um chat para analisar lotes, calcular custo completo por ave e por kg, "
        "tirar dúvidas de manejo, sanidade, estoque e financeiro ou gerar relatórios."
    )
    salvar_mensagem_chat_db("assistant", msg_inicial)
    return [{"role": "assistant", "content": msg_inicial}]


def salvar_mensagem_chat_db(role: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO chat_mensagens (role, content, criado_em) VALUES (?, ?, ?)",
        (role, content, datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def limpar_historico_chat_db():
    conn = get_conn()
    conn.execute("DELETE FROM chat_mensagens")
    conn.commit()
    conn.close()
    msg_nova = "Conversa reiniciada! O que você quer analisar ou registrar na Granja Vieira agora?"
    salvar_mensagem_chat_db("assistant", msg_nova)
    return [{"role": "assistant", "content": msg_nova}]


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
    backups_df = pd.read_sql_query("SELECT * FROM auditoria_backups ORDER BY id DESC LIMIT 50", conn)
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
        cons_extra_racao = consumo_reg_direto if ("ração" in prod.lower() or "racao" in prod.lower()) else 0.0
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
    return lotes_df, estoque_df, compras_df, alim_df, reg_df, pesagens_df, sanidade_df, custos_df, vendas_df, backups_df


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
        qtd_ini = int(lote["qtd_inicial"] or 0)
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
            lid_c = (
                None
                if c["lote_id"] is None
                or pd.isna(c["lote_id"])
                or str(c["lote_id"]).strip() in ("", "None", "Geral (Ratear)")
                else str(c["lote_id"]).strip()
            )
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


def chamar_ia_segura(mensagem: str, contexto: str, historico: list) -> str:
    try:
        return executar_assistente_granja(
            mensagem_usuario=mensagem,
            contexto_granja=contexto,
            historico_chat=historico,
        )
    except TypeError:
        return executar_assistente_granja(mensagem, historico=historico)


st.set_page_config(page_title="Granja Vieira", page_icon="🐔", layout="wide")
init_db()

st.title("🐔 Granja Vieira — Gestão Avícola Completa")
st.caption("Assistente IA, Lotes Ajustáveis, Alimentação, Estoque, Pesagens, Sanidade, Custos, Vendas, Fluxo de Caixa e Auditoria")

lotes_df, estoque_df, compras_df, alim_df, reg_df, pesagens_df, sanidade_df, custos_df, vendas_df, backups_df = obter_dados_sistema()
resumo_df, custos_lote_df = montar_resumo_e_custos(
    lotes_df, estoque_df, alim_df, reg_df, pesagens_df, sanidade_df, custos_df, vendas_df
)

total_aves_disp = int(resumo_df["Aves Disponíveis"].sum()) if not resumo_df.empty else 0
total_aves_ini = int(resumo_df["Qtd. Inicial"].sum()) if not resumo_df.empty else 0
total_mortes = int(resumo_df["Mortes Acum."].sum()) if not resumo_df.empty else 0
total_racao = float(resumo_df["Consumo Acum. (kg)"].sum()) if not resumo_df.empty else 0.0
total_custo_geral = float(custos_lote_df["Custo Total (R$)"].sum()) if not custos_lote_df.empty else 0.0
lotes_ativos = int((resumo_df["Situação"] == "Ativo").sum()) if not resumo_df.empty else 0
lista_lotes = resumo_df["Lote"].tolist() if not resumo_df.empty else ["LOTE 01", "LOTE 02", "LOTE 03"]
contexto_atual_ia = gerar_relatorio_ia(resumo_df, custos_lote_df, estoque_df, vendas_df, custos_df)

abas = st.tabs([
    "🤖 Assistente IA",
    "🐔 Lotes",
    "🌾 Alimentação",
    "📦 Compras e Estoque",
    "⚖️ Pesagens",
    "🩺 Sanidade",
    "💰 Custos e Preço",
    "🤝 Vendas",
    "💵 Fluxo de Caixa",
])

# 0: ASSISTENTE IA (NO LUGAR DE REGISTRO RÁPIDO)
with abas[0]:
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Aves Disponíveis", total_aves_disp, f"de {total_aves_ini} iniciais")
    c2.metric("Lotes Ativos", lotes_ativos)
    c3.metric("Mortes Acumuladas", total_mortes)
    c4.metric("Consumo Acum. (kg)", f"{total_racao:.2f}")
    c5.metric("Custo Total Lotes", f"R$ {total_custo_geral:.2f}")

    st.divider()
    st.subheader("🤖 Assistente IA — Granja Vieira")
    st.caption("Histórico salvo no banco de dados. Pergunte sobre custos por ave/kg, manejo, sanidade, estoque ou peça um relatório completo.")

    if "mensagens_ia_granja" not in st.session_state:
        st.session_state.mensagens_ia_granja = carregar_historico_chat_db()

    col_btn1, col_btn2 = st.columns([2, 1])
    with col_btn1:
        if st.button("📊 Relatório Completo + Alertas e Dicas", use_container_width=True):
            prompt_rel = (
                "Gere um relatório completo e direto da Granja Vieira com alertas de atenção, "
                "situação dos lotes, carências sanitárias, estoque, custo total, custo por ave e por kg, e dicas práticas."
            )
            st.session_state.mensagens_ia_granja.append({"role": "user", "content": prompt_rel})
            salvar_mensagem_chat_db("user", prompt_rel)
            with st.spinner("Analisando os dados da granja..."):
                resp_rel = chamar_ia_segura(
                    prompt_rel,
                    contexto_atual_ia,
                    st.session_state.mensagens_ia_granja[:-1],
                )
            st.session_state.mensagens_ia_granja.append({"role": "assistant", "content": resp_rel})
            salvar_mensagem_chat_db("assistant", resp_rel)
            st.rerun()

    with col_btn2:
        if st.button("🧹 Nova conversa", use_container_width=True):
            st.session_state.mensagens_ia_granja = limpar_historico_chat_db()
            st.rerun()

    for msg in st.session_state.mensagens_ia_granja:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    pergunta_usuario = st.chat_input("Digite sua mensagem para o Assistente da Granja Vieira...")
    if pergunta_usuario:
        st.session_state.mensagens_ia_granja.append({"role": "user", "content": pergunta_usuario})
        salvar_mensagem_chat_db("user", pergunta_usuario)
        with st.chat_message("user"):
            st.markdown(pergunta_usuario)

        with st.chat_message("assistant"):
            with st.spinner("Respondendo..."):
                resposta_ia = chamar_ia_segura(
                    pergunta_usuario,
                    contexto_atual_ia,
                    st.session_state.mensagens_ia_granja[:-1],
                )
            st.markdown(resposta_ia)

        st.session_state.mensagens_ia_granja.append({"role": "assistant", "content": resposta_ia})
        salvar_mensagem_chat_db("assistant", resposta_ia)

# 1: LOTES (QUANTIDADE DE AVES AJUSTÁVEL + BACKUP AUTOMÁTICO)
with abas[1]:
    st.subheader("Controle de Lotes (Quantidade de Aves Ajustável)")
    st.dataframe(resumo_df, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**Editar lote existente (quantidade inicial de aves ajustável, data, tipo, origem, custo ou situação):**")
    lote_escolhido = st.selectbox("Selecione o lote", lista_lotes)

    conn = get_conn()
    lote_row = conn.execute("SELECT * FROM lotes WHERE id = ?", (lote_escolhido,)).fetchone()
    conn.close()

    col_a, col_b, col_c, col_qtd = st.columns(4)
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
    qtd_atual_lote = int(lote_row["qtd_inicial"] or 0)
    nova_qtd_inicial = col_qtd.number_input("Quantidade de aves do lote", min_value=0, value=qtd_atual_lote, step=1)

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

    if st.button("Atualizar Lote", type="primary"):
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
            cur = conn.cursor()
            registrar_backup_antes_de_alterar(cur, "lotes", lote_escolhido, acao="EDITAR")
            cur.execute("""
                UPDATE lotes
                SET qtd_inicial = ?, data_alojamento = ?, tipo_ave = ?, situacao = ?, origem = ?, custo_pintinho = ?, observacoes = ?
                WHERE id = ?
            """, (int(nova_qtd_inicial), data_salvar, novo_tipo.strip(), nova_sit, nova_origem.strip(), custo_val, nova_obs.strip(), lote_escolhido))
            conn.commit()
            conn.close()
            st.success(f"✅ {lote_escolhido} atualizado com {int(nova_qtd_inicial)} aves (backup salvo automaticamente)!")
            st.rerun()

    st.divider()
    st.markdown("**Criar novo lote com capacidade ajustável:**")
    n1, n2, n3, n4 = st.columns(4)
    novo_id_lote = n1.text_input("Código do lote", placeholder="Ex.: LOTE 04", key="novo_id_lote")
    novo_nome_lote = n2.text_input("Nome do lote", placeholder="Ex.: Lote 04", key="novo_nome_lote")
    nova_qtd_lote = n3.number_input("Quantidade inicial de aves", min_value=1, value=100, step=1, key="nova_qtd_lote")
    novo_custo_pint_txt = n4.text_input("Custo por pintinho (R$)", value="", placeholder="Opcional", key="novo_custo_pint_txt")

    if st.button("➕ Criar Novo Lote"):
        cod_limpo = novo_id_lote.strip().upper()
        if not cod_limpo:
            st.error("Informe o código do lote (ex.: LOTE 04).")
        else:
            try:
                c_pint = parse_numero_opcional(novo_custo_pint_txt)
            except ValueError:
                st.error("Custo por pintinho inválido.")
                c_pint = None

            conn = get_conn()
            cur = conn.cursor()
            existe = cur.execute("SELECT COUNT(*) FROM lotes WHERE id = ?", (cod_limpo,)).fetchone()[0]
            if existe > 0:
                st.warning(f"O lote {cod_limpo} já existe.")
            else:
                cur.execute("""
                    INSERT INTO lotes
                    (id, nome, data_alojamento, qtd_inicial, tipo_ave, origem, custo_pintinho, situacao, observacoes)
                    VALUES (?, ?, ?, ?, '', '', ?, 'Ativo', '')
                """, (cod_limpo, (novo_nome_lote.strip() or cod_limpo), date.today().isoformat(), int(nova_qtd_lote), c_pint))
                conn.commit()
                st.success(f"✅ {cod_limpo} criado com {int(nova_qtd_lote)} aves!")
                conn.close()
                st.rerun()
            conn.close()

    st.divider()
    st.markdown("**Histórico de backups automáticos (pré-edição/exclusão):**")
    st.dataframe(backups_df, width="stretch", hide_index=True)

# 2: ALIMENTAÇÃO
with abas[2]:
    st.subheader("Alimentação por Lote (Consumo e Sobras)")
    st.caption("Separa quantidade fornecida de sobra medida. Quando não há sobra medida, o consumo é marcado como estimado pela quantidade fornecida.")

    produtos_disponiveis = estoque_df["Produto"].tolist() if not estoque_df.empty else []
    opcoes_prod = produtos_disponiveis + ["Outro / Informar manualmente"]

    col1, col2, col3, col4 = st.columns(4)
    data_alim = col1.date_input("Data da alimentação", value=date.today(), key="data_alim")
    lote_alim = col2.selectbox("Lote", lista_lotes, key="lote_alim")
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
            st.success(f"✅ Alimentação registrada para {lote_alim}: consumo líquido de {consumo_liq:.2f} kg.")
            st.rerun()

    st.divider()
    st.markdown("**Histórico de alimentação**")
    st.dataframe(alim_df, width="stretch", hide_index=True)

# 3: COMPRAS E ESTOQUE
with abas[3]:
    st.subheader("Compras e Controle de Estoque")
    st.dataframe(estoque_df, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**Registrar nova compra de insumo / ração / medicamento**")
    c1, c2, c3, c4 = st.columns(4)
    data_comp = c1.date_input("Data da compra", value=date.today(), key="data_comp")
    prod_comp = c2.text_input("Produto", placeholder="Ex.: Ração Inicial", key="prod_comp")
    cat_comp = c3.selectbox("Categoria", ["Ração", "Medicamento", "Insumo", "Embalagem", "Outros"], key="cat_comp")
    forn_comp = c4.text_input("Fornecedor", placeholder="Opcional", key="forn_comp")

    c5, c6, c7, c8 = st.columns(4)
    qtd_comp_txt = c5.text_input("Quantidade", placeholder="Ex.: 50", key="qtd_comp_txt")
    un_comp = c6.text_input("Unidade", value="kg", key="un_comp")
    pu_comp_txt = c7.text_input("Preço unitário (R$)", placeholder="Ex.: 2.60", key="pu_comp_txt")
    est_min_txt = c8.text_input("Estoque mínimo", value="20", key="est_min_txt")

    c9, c10 = st.columns([1, 2])
    lote_comp = c9.selectbox("Lote (opcional)", ["Geral"] + lista_lotes, key="lote_comp")
    obs_comp = c10.text_input("Observações da compra", placeholder="Opcional", key="obs_comp")

    if st.button("📦 Salvar Compra no Estoque", type="primary"):
        try:
            qtd_val = parse_numero_opcional(qtd_comp_txt)
            pu_val = parse_numero_opcional(pu_comp_txt)
            emin_val = parse_numero_opcional(est_min_txt) or 20.0
        except ValueError:
            st.error("Quantidade ou preço unitário inválido.")
            qtd_val, pu_val = None, None

        if not prod_comp.strip():
            st.error("Informe o nome do produto.")
        elif qtd_val is None or qtd_val <= 0 or pu_val is None or pu_val < 0:
            st.error("Informe quantidade maior que zero e preço unitário válido.")
        else:
            val_tot = round(qtd_val * pu_val, 2)
            lid_salvar = None if lote_comp == "Geral" else lote_comp
            conn = get_conn()
            conn.execute("""
                INSERT INTO compras_estoque
                (data_compra, produto, categoria, fornecedor, quantidade, unidade, preco_unitario, valor_total, lote_id, estoque_minimo, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data_comp.isoformat(), prod_comp.strip(), cat_comp, forn_comp.strip(),
                float(qtd_val), un_comp.strip() or "kg", float(pu_val), val_tot,
                lid_salvar, float(emin_val), obs_comp.strip()
            ))
            conn.commit()
            conn.close()
            st.success(f"✅ Compra de {qtd_val} {un_comp} de {prod_comp.strip()} registrada (R$ {val_tot:.2f})!")
            st.rerun()

    st.divider()
    st.markdown("**Histórico de compras**")
    st.dataframe(compras_df, width="stretch", hide_index=True)

# 4: PESAGENS
with abas[4]:
    st.subheader("Pesagens, GPD e Conversão Alimentar")
    p1, p2, p3, p4 = st.columns(4)
    data_pes = p1.date_input("Data da pesagem", value=date.today(), key="data_pes")
    lote_pes = p2.selectbox("Lote", lista_lotes, key="lote_pes")
    aves_pes_txt = p3.text_input("Aves pesadas", placeholder="Ex.: 20", key="aves_pes_txt")
    peso_tot_txt = p4.text_input("Peso total da amostra (kg)", placeholder="Ex.: 36.0", key="peso_tot_txt")
    obs_pes = st.text_input("Observações da pesagem", placeholder="Opcional", key="obs_pes")

    if st.button("⚖️ Registrar Pesagem", type="primary"):
        try:
            n_aves_p = int(float(aves_pes_txt.replace(",", "."))) if aves_pes_txt.strip() else 0
            p_tot_p = parse_numero_opcional(peso_tot_txt)
        except ValueError:
            st.error("Valores de pesagem inválidos.")
            n_aves_p, p_tot_p = 0, None

        if n_aves_p <= 0 or p_tot_p is None or p_tot_p <= 0:
            st.error("Informe quantidade de aves pesadas e peso total maiores que zero.")
        else:
            peso_med_p = round(p_tot_p / n_aves_p, 4)
            linha_lote = resumo_df[resumo_df["Lote"] == lote_pes].iloc[0]
            racao_acum_p = float(linha_lote["Consumo Acum. (kg)"])
            aves_vivas_p = int(linha_lote["Aves Disponíveis"])
            lote_raw = lotes_df[lotes_df["id"] == lote_pes].iloc[0]
            d_aloj_p = parse_data_segura(lote_raw["data_alojamento"])

            gpd_p, ca_p = calcular_metricas_pesagem(
                lote_pes, data_pes, peso_med_p, racao_acum_p, aves_vivas_p, d_aloj_p, pesagens_df
            )

            conn = get_conn()
            conn.execute("""
                INSERT INTO pesagens
                (data_pesagem, lote_id, aves_pesadas, peso_total_kg, peso_medio_kg, gpd_g_dia, conversao_alimentar, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (data_pes.isoformat(), lote_pes, n_aves_p, float(p_tot_p), peso_med_p, gpd_p, ca_p, obs_pes.strip()))
            conn.commit()
            conn.close()
            st.success(f"✅ Pesagem registrada! Peso médio: {peso_med_p:.3f} kg.")
            st.rerun()

    st.divider()
    st.dataframe(pesagens_df, width="stretch", hide_index=True)

# 5: SANIDADE
with abas[5]:
    st.subheader("Sanidade e Controle de Carência")
    s1, s2, s3, s4 = st.columns(4)
    data_san = s1.date_input("Data da aplicação", value=date.today(), key="data_san")
    lote_san = s2.selectbox("Lote", lista_lotes, key="lote_san")
    tipo_san = s3.selectbox("Tipo de evento", ["Vacina", "Vermifugação", "Antibiótico / Tratamento", "Vitamina / Manejo"], key="tipo_san")
    prod_san = s4.text_input("Produto / tratamento", placeholder="Ex.: Newcastle / Enrofloxacino", key="prod_san")

    s5, s6, s7 = st.columns(3)
    carencia_dias_txt = s5.text_input("Carência (dias)", value="0", key="carencia_dias_txt")
    dose_san = s6.text_input("Dose / via / observação", placeholder="Opcional", key="dose_san")
    resp_san = s7.text_input("Responsável", placeholder="Opcional", key="resp_san")

    if st.button("🩺 Registrar Evento Sanitário", type="primary"):
        try:
            dias_car = int(float(carencia_dias_txt.replace(",", "."))) if carencia_dias_txt.strip() else 0
            if dias_car < 0:
                dias_car = 0
        except ValueError:
            st.error("Dias de carência inválidos.")
            dias_car = None

        if not prod_san.strip():
            st.error("Informe o produto ou tratamento aplicado.")
        elif dias_car is not None:
            data_lib = (data_san + timedelta(days=dias_car)).isoformat()
            conn = get_conn()
            conn.execute("""
                INSERT INTO sanidade
                (data_aplicacao, lote_id, tipo_evento, produto_tratamento, dose_observacao, carencia_dias, data_liberacao, responsavel, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (data_san.isoformat(), lote_san, tipo_san, prod_san.strip(), dose_san.strip(), dias_car, data_lib, resp_san.strip(), ""))
            conn.commit()
            conn.close()
            st.success(f"✅ Sanidade registrada! Liberação prevista em {data_lib}.")
            st.rerun()

    st.divider()
    st.dataframe(sanidade_df, width="stretch", hide_index=True)

# 6: CUSTOS E PREÇO
with abas[6]:
    st.subheader("Custos Operacionais e Formação de Preço por Lote")
    st.dataframe(custos_lote_df, width="stretch", hide_index=True)

    st.divider()
    st.markdown("**Lançar custo operacional (fixo ou variável)**")
    cu1, cu2, cu3, cu4 = st.columns(4)
    data_cu = cu1.date_input("Data do lançamento", value=date.today(), key="data_cu")
    tipo_cu = cu2.selectbox("Tipo de custo", ["Variável", "Fixo"], key="tipo_cu")
    desc_cu = cu3.text_input("Descrição", placeholder="Ex.: Energia elétrica / Maravalha / Frete", key="desc_cu")
    val_cu_txt = cu4.text_input("Valor (R$)", placeholder="Ex.: 150.00", key="val_cu_txt")

    cu5, cu6, cu7 = st.columns(3)
    lote_cu = cu5.selectbox("Lote vinculado", ["Geral (Ratear)"] + lista_lotes, key="lote_cu")
    rateio_cu = cu6.selectbox("Base de rateio", ["Por Ave Viva", "Por Lote Ativo"], key="rateio_cu")
    obs_cu = cu7.text_input("Observação", placeholder="Opcional", key="obs_cu")

    if st.button("💰 Salvar Custo Operacional", type="primary"):
        try:
            val_cu = parse_numero_opcional(val_cu_txt)
        except ValueError:
            st.error("Valor inválido.")
            val_cu = None

        if not desc_cu.strip():
            st.error("Informe a descrição do custo.")
        elif val_cu is None or val_cu <= 0:
            st.error("Informe um valor maior que zero.")
        else:
            lid_cu = None if lote_cu == "Geral (Ratear)" else lote_cu
            conn = get_conn()
            conn.execute("""
                INSERT INTO custos_operacionais
                (data_lancamento, tipo_custo, descricao, valor, lote_id, rateio_base, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (data_cu.isoformat(), tipo_cu, desc_cu.strip(), float(val_cu), lid_cu, rateio_cu, obs_cu.strip()))
            conn.commit()
            conn.close()
            st.success("✅ Custo operacional salvo!")
            st.rerun()

    st.divider()
    st.dataframe(custos_df, width="stretch", hide_index=True)

# 7: VENDAS
with abas[7]:
    st.subheader("Registro de Vendas")
    v1, v2, v3, v4 = st.columns(4)
    data_v = v1.date_input("Data da venda", value=date.today(), key="data_v")
    lote_v = v2.selectbox("Lote", lista_lotes, key="lote_v")
    comp_v = v3.text_input("Comprador", placeholder="Opcional", key="comp_v")
    mod_v = v4.selectbox("Modalidade", ["Ave viva", "Por kg", "Caixa / Lote"], key="mod_v")

    v5, v6, v7, v8 = st.columns(4)
    aves_v_txt = v5.text_input("Aves vendidas", placeholder="Ex.: 15", key="aves_v_txt")
    peso_v_txt = v6.text_input("Peso total (kg)", value="0", key="peso_v_txt")
    pu_v_txt = v7.text_input("Preço unitário (R$)", placeholder="Ex.: 45.00", key="pu_v_txt")
    status_v = v8.selectbox("Status pagamento", ["Recebido", "Pendente"], key="status_v")

    em_carencia, data_lib_v, status_car_v = obter_carencia_lote(lote_v, sanidade_df)
    if em_carencia:
        st.warning(f"⚠️ Atenção: {lote_v} está em período de carência ({status_car_v}).")
    confirmar_car_v = st.checkbox("Confirmo verificação de carência sanitária antes da venda", value=not em_carencia)

    if st.button("🤝 Registrar Venda", type="primary"):
        try:
            n_aves_v = int(float(aves_v_txt.replace(",", "."))) if aves_v_txt.strip() else 0
            p_tot_v = parse_numero_opcional(peso_v_txt) or 0.0
            pu_v = parse_numero_opcional(pu_v_txt)
        except ValueError:
            st.error("Valores numéricos da venda inválidos.")
            n_aves_v, p_tot_v, pu_v = 0, 0.0, None

        if n_aves_v <= 0 or pu_v is None or pu_v <= 0:
            st.error("Informe quantidade de aves vendidas e preço unitário maiores que zero.")
        else:
            base_mult = p_tot_v if (mod_v == "Por kg" and p_tot_v > 0) else float(n_aves_v)
            val_tot_v = round(base_mult * pu_v, 2)
            conn = get_conn()
            conn.execute("""
                INSERT INTO vendas
                (data_venda, lote_id, comprador, modalidade, aves_vendidas, peso_total_kg, preco_unitario, valor_total, status_pagamento, carencia_confirmada, observacoes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                data_v.isoformat(), lote_v, comp_v.strip(), mod_v, n_aves_v,
                float(p_tot_v), float(pu_v), val_tot_v, status_v, 1 if confirmar_car_v else 0, ""
            ))
            conn.commit()
            conn.close()
            st.success(f"✅ Venda registrada! Total: R$ {val_tot_v:.2f}.")
            st.rerun()

    st.divider()
    st.dataframe(vendas_df, width="stretch", hide_index=True)

# 8: FLUXO DE CAIXA
with abas[8]:
    st.subheader("Fluxo de Caixa Consolidado")
    total_entradas = float(vendas_df["valor_total"].sum()) if not vendas_df.empty else 0.0
    total_compras_saidas = float(compras_df["valor_total"].sum()) if not compras_df.empty else 0.0
    total_custos_saidas = float(custos_df["valor"].sum()) if not custos_df.empty else 0.0
    total_saidas = total_compras_saidas + total_custos_saidas
    saldo_caixa = total_entradas - total_saidas

    f1, f2, f3 = st.columns(3)
    f1.metric("Entradas (Vendas)", f"R$ {total_entradas:.2f}")
    f2.metric("Saídas (Compras + Custos)", f"R$ {total_saidas:.2f}")
    f3.metric("Saldo Líquido em Caixa", f"R$ {saldo_caixa:.2f}")

    st.divider()
    st.markdown("**Resumo rápido do sistema:**")
    st.code(gerar_relatorio_ia(resumo_df, custos_lote_df, estoque_df, vendas_df, custos_df), language="text")
