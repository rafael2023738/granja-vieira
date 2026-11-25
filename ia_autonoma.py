import json
import os
import shutil
import sqlite3
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from dotenv import load_dotenv
from google import genai
from google.genai import errors as genai_errors
from google.genai import types

PASTA_BASE = Path(__file__).resolve().parent
ENV_PATH = PASTA_BASE / ".env"
if ENV_PATH.exists():
    load_dotenv(dotenv_path=ENV_PATH, override=True)
else:
    load_dotenv(override=True)

DB_CANDIDATOS = [
    PASTA_BASE / "granja_vieira.db",
    PASTA_BASE / "granja_vieira_backup.db",
]


def _obter_db() -> Path:
    for p in DB_CANDIDATOS:
        if p.exists():
            return p
    return DB_CANDIDATOS[0]


def _obter_api_key() -> str:
    if ENV_PATH.exists():
        load_dotenv(dotenv_path=ENV_PATH, override=True)
    chave = (os.getenv("GEMINI_API_KEY") or "").strip().strip('"').strip("'")
    if chave:
        return chave
    try:
        import streamlit as st
        sec = str(st.secrets.get("GEMINI_API_KEY", "")).strip().strip('"').strip("'")
        if sec:
            return sec
    except Exception:
        pass
    return ""


def _fazer_backup_rapido(db_path: Path) -> None:
    if db_path.exists():
        pasta_bak = PASTA_BASE / "Backup_GranjaVieira"
        pasta_bak.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(db_path, pasta_bak / f"ia_auto_{stamp}_{db_path.name}")


def _conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(str(_obter_db()))
    conn.row_factory = sqlite3.Row
    return conn


TABELAS_PERMITIDAS = {
    "lotes",
    "registros_diarios",
    "compras_estoque",
    "alimentacao",
    "pesagens",
    "sanidade",
    "custos_operacionais",
    "vendas",
}


def registrar_lote(
    lote_id: str,
    nome: str,
    qtd_inicial: int,
    data_alojamento: str = "",
    tipo_ave: str = "",
    origem: str = "",
    custo_pintinho: float = 0.0,
    situacao: str = "Ativo",
    observacoes: str = "",
) -> str:
    """Cria um novo lote na tabela lotes."""
    if not data_alojamento:
        data_alojamento = date.today().isoformat()
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO lotes
               (id, nome, data_alojamento, qtd_inicial, tipo_ave, origem, custo_pintinho, situacao, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (lote_id, nome, data_alojamento, int(qtd_inicial), tipo_ave, origem, float(custo_pintinho), situacao, observacoes),
        )
        conn.commit()
    return f"Lote '{lote_id}' ({nome}) criado com {qtd_inicial} aves em {data_alojamento}."


def registrar_diario(
    lote_id: str,
    aves_mortas: int = 0,
    racao_kg: float = 0.0,
    data_registro: str = "",
    observacoes: str = "",
) -> str:
    """Registra mortalidade e ração do dia na tabela registros_diarios."""
    if not data_registro:
        data_registro = date.today().isoformat()
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO registros_diarios
               (data_registro, lote_id, aves_mortas, racao_kg, observacoes)
               VALUES (?, ?, ?, ?, ?)""",
            (data_registro, lote_id, int(aves_mortas), float(racao_kg), observacoes),
        )
        conn.commit()
    return f"Registro diário salvo | Lote: {lote_id} | Data: {data_registro} | Mortas: {aves_mortas} | Ração: {racao_kg} kg."


def registrar_compra_estoque(
    produto: str,
    categoria: str,
    quantidade: float,
    preco_unitario: float,
    data_compra: str = "",
    fornecedor: str = "",
    unidade: str = "kg",
    valor_total: float = 0.0,
    lote_id: str = "",
    estoque_minimo: float = 20.0,
    observacoes: str = "",
) -> str:
    """Registra entrada de produto/insumo em compras_estoque."""
    if not data_compra:
        data_compra = date.today().isoformat()
    total = float(valor_total) if valor_total and float(valor_total) > 0 else round(float(quantidade) * float(preco_unitario), 2)
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO compras_estoque
               (data_compra, produto, categoria, fornecedor, quantidade, unidade, preco_unitario, valor_total, lote_id, estoque_minimo, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data_compra, produto, categoria, fornecedor, float(quantidade), unidade, float(preco_unitario), total, lote_id or None, float(estoque_minimo), observacoes),
        )
        conn.commit()
    return f"Compra registrada: {quantidade} {unidade} de {produto} ({categoria}) | Total: R$ {total:.2f} | Data: {data_compra}."


def registrar_alimentacao(
    lote_id: str,
    produto_estoque: str,
    qtd_fornecida_kg: float,
    qtd_sobra_kg: float = 0.0,
    fase_alimentar: str = "Não informada",
    data_registro: str = "",
    sobra_medida: int = 0,
    custo_estimado: float = 0.0,
    observacoes: str = "",
) -> str:
    """Registra fornecimento e sobra de ração na tabela alimentacao."""
    if not data_registro:
        data_registro = date.today().isoformat()
    forn = float(qtd_fornecida_kg)
    sobra = float(qtd_sobra_kg) if qtd_sobra_kg is not None else 0.0
    consumo_liq = max(0.0, round(forn - sobra, 3))
    custo = float(custo_estimado)
    with _conectar() as conn:
        if custo <= 0:
            row = conn.execute(
                "SELECT preco_unitario FROM compras_estoque WHERE produto LIKE ? ORDER BY id DESC LIMIT 1",
                (f"%{produto_estoque}%",),
            ).fetchone()
            if row and row["preco_unitario"]:
                custo = round(consumo_liq * float(row["preco_unitario"]), 2)
        conn.execute(
            """INSERT INTO alimentacao
               (data_registro, lote_id, produto_estoque, fase_alimentar, qtd_fornecida_kg, qtd_sobra_kg, consumo_liquido_kg, sobra_medida, custo_estimado, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data_registro, lote_id, produto_estoque, fase_alimentar, forn, sobra, consumo_liq, int(sobra_medida), custo, observacoes),
        )
        conn.commit()
    return f"Alimentação salva | Lote: {lote_id} | {produto_estoque} | Consumo líquido: {consumo_liq} kg | Custo est.: R$ {custo:.2f}."


def registrar_pesagem(
    lote_id: str,
    aves_pesadas: int,
    peso_total_kg: float,
    data_pesagem: str = "",
    peso_medio_kg: float = 0.0,
    gpd_g_dia: float = 0.0,
    conversao_alimentar: float = 0.0,
    observacoes: str = "",
) -> str:
    """Registra pesagem do lote na tabela pesagens."""
    if not data_pesagem:
        data_pesagem = date.today().isoformat()
    n_aves = max(1, int(aves_pesadas))
    p_tot = float(peso_total_kg)
    p_med = float(peso_medio_kg) if peso_medio_kg and float(peso_medio_kg) > 0 else round(p_tot / n_aves, 4)
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO pesagens
               (data_pesagem, lote_id, aves_pesadas, peso_total_kg, peso_medio_kg, gpd_g_dia, conversao_alimentar, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (data_pesagem, lote_id, int(aves_pesadas), p_tot, p_med, float(gpd_g_dia), float(conversao_alimentar), observacoes),
        )
        conn.commit()
    return f"Pesagem registrada | Lote: {lote_id} | Aves: {aves_pesadas} | Peso médio: {p_med:.3f} kg | Data: {data_pesagem}."


def registrar_sanidade(
    lote_id: str,
    tipo_evento: str,
    produto_tratamento: str,
    carencia_dias: int = 0,
    data_aplicacao: str = "",
    dose_observacao: str = "",
    data_liberacao: str = "",
    responsavel: str = "",
    observacoes: str = "",
) -> str:
    """Registra vacina, medicamento ou evento sanitário na tabela sanidade."""
    if not data_aplicacao:
        data_aplicacao = date.today().isoformat()
    dias = int(carencia_dias)
    if not data_liberacao:
        dt_base = date.fromisoformat(data_aplicacao)
        data_liberacao = (dt_base + timedelta(days=dias)).isoformat()
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO sanidade
               (data_aplicacao, lote_id, tipo_evento, produto_tratamento, dose_observacao, carencia_dias, data_liberacao, responsavel, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data_aplicacao, lote_id, tipo_evento, produto_tratamento, dose_observacao, dias, data_liberacao, responsavel, observacoes),
        )
        conn.commit()
    return f"Sanidade salva | Lote: {lote_id} | {tipo_evento}: {produto_tratamento} | Carência: {dias}d (libera em {data_liberacao})."


def registrar_custo_operacional(
    tipo_custo: str,
    descricao: str,
    valor: float,
    data_lancamento: str = "",
    lote_id: str = "",
    rateio_base: str = "Por Ave Viva",
    observacoes: str = "",
) -> str:
    """Registra despesa/custo operacional na tabela custos_operacionais."""
    if not data_lancamento:
        data_lancamento = date.today().isoformat()
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO custos_operacionais
               (data_lancamento, tipo_custo, descricao, valor, lote_id, rateio_base, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (data_lancamento, tipo_custo, descricao, float(valor), lote_id or None, rateio_base, observacoes),
        )
        conn.commit()
    return f"Custo operacional registrado: {descricao} ({tipo_custo}) | R$ {float(valor):.2f} | Data: {data_lancamento}."


def registrar_venda(
    lote_id: str,
    modalidade: str,
    aves_vendidas: int,
    preco_unitario: float,
    comprador: str = "",
    data_venda: str = "",
    peso_total_kg: float = 0.0,
    valor_total: float = 0.0,
    status_pagamento: str = "Recebido",
    carencia_confirmada: int = 0,
    observacoes: str = "",
) -> str:
    """Registra venda de aves ou produção na tabela vendas."""
    if not data_venda:
        data_venda = date.today().isoformat()
    total = float(valor_total) if valor_total and float(valor_total) > 0 else round(int(aves_vendidas) * float(preco_unitario), 2)
    with _conectar() as conn:
        conn.execute(
            """INSERT INTO vendas
               (data_venda, lote_id, comprador, modalidade, aves_vendidas, peso_total_kg, preco_unitario, valor_total, status_pagamento, carencia_confirmada, observacoes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (data_venda, lote_id, comprador, modalidade, int(aves_vendidas), float(peso_total_kg), float(preco_unitario), total, status_pagamento, int(carencia_confirmada), observacoes),
        )
        conn.commit()
    return f"Venda registrada | Lote: {lote_id} | {aves_vendidas} aves ({modalidade}) | Total: R$ {total:.2f} | Data: {data_venda}."


def editar_registro(tabela: str, registro_id: str, campos_json: str) -> str:
    """Edita colunas de um registro existente em uma tabela permitida."""
    if tabela not in TABELAS_PERMITIDAS:
        return f"Tabela '{tabela}' não permitida."
    dados = json.loads(campos_json)
    if not isinstance(dados, dict) or not dados:
        return "Informe ao menos um campo em campos_json."

    _fazer_backup_rapido(_obter_db())
    with _conectar() as conn:
        cols_info = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabela})").fetchall()}
        validas = {k: v for k, v in dados.items() if k in cols_info and k != "id"}
        if not validas:
            return f"Nenhuma coluna válida encontrada para '{tabela}'."
        set_clause = ", ".join(f"{col} = ?" for col in validas)
        params = list(validas.values())
        pk_val = int(registro_id) if tabela != "lotes" and str(registro_id).isdigit() else registro_id
        params.append(pk_val)
        cur = conn.execute(f"UPDATE {tabela} SET {set_clause} WHERE id = ?", params)
        conn.commit()
        return f"Atualizados {cur.rowcount} registro(s) em '{tabela}' (id={registro_id}): {validas}."


def excluir_registro(tabela: str, registro_id: str) -> str:
    """Exclui um registro pelo ID em uma tabela permitida (gera backup automático antes)."""
    if tabela not in TABELAS_PERMITIDAS:
        return f"Tabela '{tabela}' não permitida."
    _fazer_backup_rapido(_obter_db())
    with _conectar() as conn:
        pk_val = int(registro_id) if tabela != "lotes" and str(registro_id).isdigit() else registro_id
        cur = conn.execute(f"DELETE FROM {tabela} WHERE id = ?", (pk_val,))
        conn.commit()
        return f"Excluídos {cur.rowcount} registro(s) de '{tabela}' (id={registro_id})."


def consultar_sql_leitura(consulta_select: str) -> str:
    """Executa uma consulta SELECT no banco SQLite para investigar dados, saldos ou possíveis inconsistências."""
    limpo = consulta_select.strip().rstrip(";")
    if not limpo.lower().startswith("select"):
        return "Apenas consultas SELECT são permitidas nesta ferramenta."
    with _conectar() as conn:
        rows = conn.execute(limpo).fetchall()
        resultado = [dict(r) for r in rows[:50]]
        return json.dumps(resultado, ensure_ascii=False, default=str)


def gerar_relatorio_geral_granja() -> str:
    """Coleta dados consolidados de lotes, mortalidade, estoque, sanidade, custos e vendas para relatório e dicas."""
    hoje_str = date.today().isoformat()
    with _conectar() as conn:
        lotes = [dict(r) for r in conn.execute("SELECT * FROM lotes ORDER BY data_alojamento DESC").fetchall()]
        mortalidade = [
            dict(r)
            for r in conn.execute(
                "SELECT lote_id, COALESCE(SUM(aves_mortas), 0) AS total_mortas, COALESCE(SUM(racao_kg), 0) AS racao_diario_kg FROM registros_diarios GROUP BY lote_id"
            ).fetchall()
        ]
        alimentacao = [
            dict(r)
            for r in conn.execute(
                "SELECT lote_id, COALESCE(SUM(consumo_liquido_kg), 0) AS consumo_kg, COALESCE(SUM(custo_estimado), 0) AS custo_racao FROM alimentacao GROUP BY lote_id"
            ).fetchall()
        ]
        pesagens = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM pesagens ORDER BY data_pesagem DESC, id DESC LIMIT 15"
            ).fetchall()
        ]
        sanidade = [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM sanidade ORDER BY data_liberacao DESC, id DESC LIMIT 15"
            ).fetchall()
        ]
        estoque = [
            dict(r)
            for r in conn.execute(
                """SELECT produto, categoria, unidade,
                          COALESCE(SUM(quantidade), 0) AS qtd_comprada,
                          COALESCE(SUM(valor_total), 0) AS gasto_total,
                          MIN(estoque_minimo) AS estoque_minimo
                   FROM compras_estoque GROUP BY produto, categoria, unidade"""
            ).fetchall()
        ]
        custos = dict(
            conn.execute(
                "SELECT COALESCE(SUM(valor), 0) AS total_custos_op FROM custos_operacionais"
            ).fetchone()
        )
        vendas = dict(
            conn.execute(
                "SELECT COALESCE(SUM(valor_total), 0) AS total_vendas, COALESCE(SUM(aves_vendidas), 0) AS total_aves_vendidas FROM vendas"
            ).fetchone()
        )

    resumo = {
        "data_referencia": hoje_str,
        "arquivo_db": str(_obter_db()),
        "lotes": lotes,
        "mortalidade_por_lote": mortalidade,
        "alimentacao_por_lote": alimentacao,
        "ultimas_pesagens": pesagens,
        "sanidade_recente": sanidade,
        "estoque_compras": estoque,
        "custos_operacionais": custos,
        "vendas": vendas,
    }
    return json.dumps(resumo, ensure_ascii=False, default=str)


FERRAMENTAS_IA = [
    registrar_lote,
    registrar_diario,
    registrar_compra_estoque,
    registrar_alimentacao,
    registrar_pesagem,
    registrar_sanidade,
    registrar_custo_operacional,
    registrar_venda,
    editar_registro,
    excluir_registro,
    consultar_sql_leitura,
    gerar_relatorio_geral_granja,
]


def executar_assistente_granja(mensagem_usuario: str, historico: list[dict] | None = None) -> str:
    """Executa o assistente exclusivo da Gestão Granja Vieira via Chat nativo e troca rápida de canal."""
    api_key = _obter_api_key()
    if not api_key:
        return (
            f"Configuração pendente: não foi possível localizar a chave em '{ENV_PATH}' "
            "nem nas configurações de ambiente/segredos."
        )

    hoje = date.today().isoformat()
    system_instruction = f"""
Você é o Assistente Exclusivo da Granja Vieira (módulo interno proprietário do sistema Gestão Granja Vieira). Hoje é {hoje}.
Identidade e postura obrigatórias:
- Fale sempre em primeira pessoa ou como o assistente oficial da Granja Vieira, com tom prático, direto, parceiro e profissional.
- NUNCA mencione provedores externos, plataformas de terceiros, modelos de linguagem ou "fui instalado para ajudar aqui". Se perguntarem quem ou o que você é, responda que é o assistente exclusivo de gestão operacional e análise da Granja Vieira.
- Atue diretamente sobre os dados da granja usando as ferramentas disponíveis: lançar lotes, diário, compras/estoque, alimentação, pesagens, sanidade, custos operacionais e vendas; editar ou excluir registros (com backup automático prévio); consultar dados via SQL e gerar relatórios consolidados com alertas e dicas práticas.

Regras operacionais:
1. Para datas relativas como 'hoje', use {hoje}. Se o usuário citar 'ontem', calcule com base em {hoje}.
2. Quando pedirem relatório completo, análise, dicas ou pontos de atenção, chame `gerar_relatorio_geral_granja` primeiro e entregue um diagnóstico objetivo e útil (carências sanitárias ativas, mortalidade, peso/conversão, estoque, custos, vendas e dicas práticas).
3. Quando houver vários lançamentos na mesma frase, chame a ferramenta correspondente para cada item.
4. Responda sempre em português claro, objetivo e sem enrolação.
"""

    client = genai.Client(api_key=api_key, http_options={"timeout": 15000})

    history_msgs: list = []
    if historico:
        for item in historico[-4:]:
            role = "user" if item.get("role") == "user" else "model"
            txt = item.get("content", "")
            if txt:
                history_msgs.append(types.Content(role=role, parts=[types.Part.from_text(text=txt)]))

    modelos_rapidos = [
        "gemini-3.5-flash-lite",
        "gemini-3.1-flash-lite",
        "gemini-3.5-flash",
        "gemini-3.6-flash",
        "gemini-3.7-flash",
        "gemini-3.8-flash",
    ]

    for modelo in modelos_rapidos:
        try:
            chat = client.chats.create(
                model=modelo,
                history=history_msgs,
                config=types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    tools=FERRAMENTAS_IA,
                    temperature=0.2,
                ),
            )
            response = chat.send_message(mensagem_usuario)
            return response.text or "Operação concluída no sistema da Granja Vieira."
        except genai_errors.APIError as e:
            codigo = getattr(e, "code", None)
            if codigo in (503, 429, 404, 500, 502, 504):
                continue
            return f"Não foi possível concluir a operação agora ({codigo}). Tente novamente em instantes."
        except Exception:
            continue

    return (
        "Os servidores estão oscilando neste instante. "
        "Aguarde alguns segundos e envie a mensagem novamente."
    )