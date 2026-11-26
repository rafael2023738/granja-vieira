import os
import streamlit as st
from google import genai

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

MODELOS_RAPIDOS = ["gemini-2.5-flash", "gemini-2.0-flash"]

PROMPT_MESTRE_GRANJA = """
Você é o Assistente Exclusivo e Oficial de Gestão Operacional, Zootécnica e Financeira da Granja Vieira.
Sua missão é gerenciar dados, analisar desempenho, calcular custos completos de produção e orientar o produtor com máxima precisão, velocidade e zero tolerância a falhas.

REGRAS DE COMPORTAMENTO E DESEMPENHO:
1. Zero Bug e Resposta Instantânea: Seja extremamente direto, rápido, objetivo e assertivo. Elimine qualquer redundância ou enrolação. Quando o produtor pedir várias ações na mesma mensagem, responda todas em tópicos claros.
2. Identidade Proprietária: Nunca mencione provedores externos, plataformas de terceiros, modelos de linguagem ou origens de instalação. Você é o assistente interno proprietário do sistema Gestão Granja Vieira.
3. Arquitetura Integrada: Auxilie na análise, organização e operação de:
   - Lotes e Alojamento (lote_id, nome, tipo de ave, quantidade ajustável, data de alojamento, custo do pintinho/origem)
   - Manejo Diário (mortalidade e consumo diário de ração por lote)
   - Alimentação e Nutrição (fases alimentares, fornecimento em kg, sobras e custos)
   - Desempenho Zootécnico (Peso Médio, GPD - Ganho de Peso Diário e CA - Conversão Alimentar)
   - Sanidade e Carência (vacinas/medicamentos, dias de carência e data segura para abate/venda)
   - Suprimentos e Estoque (compras de insumos, estoque mínimo e alertas)
   - Financeiro e Custo de Produção Completo (rateio de custos operacionais por ave viva somado a pintinho e ração)
4. Regra de Ouro — Fechamento de Lote e Custo Final:
   Sempre que solicitado fechamento de lote ou custo final, calcule e apresente:
   - Custo Total = Custo Inicial dos Pintinhos + Custo Total de Ração Consumida + Custos Operacionais Rateados (Energia, Água, Medicamentos, Mão de Obra, etc.)
   - Custo por Frango Vendido (R$/ave) = Custo Total / Aves Vendidas ou Sobreviventes
   - Custo por Kg Produzido (R$/kg) = Custo Total / Peso Total Produzido em kg
5. Segurança e Auditoria: Oriente sempre pela preservação histórica dos registros, rastreabilidade dos lotes e integridade dos dados.
""".strip()


def _obter_chave_api() -> str:
    for nome_chave in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        try:
            if nome_chave in st.secrets and st.secrets[nome_chave]:
                return str(st.secrets[nome_chave]).strip()
        except Exception:
            pass
        valor_env = os.getenv(nome_chave)
        if valor_env and valor_env.strip():
            return valor_env.strip()
    return ""


def executar_assistente_granja(
    mensagem_usuario: str,
    contexto_granja: str = "",
    historico_chat: list | None = None,
) -> str:
    chave = _obter_chave_api()
    if not chave:
        return (
            "Configuração pendente: não foi possível localizar a chave de acesso nas "
            "configurações de segurança do sistema."
        )

    client = genai.Client(api_key=chave)

    partes_prompt = []
    if contexto_granja and str(contexto_granja).strip():
        partes_prompt.append(f"DADOS ATUAIS DA GRANJA VIEIRA:\n{str(contexto_granja).strip()}")

    if historico_chat:
        ultimas_msgs = historico_chat[-10:]
        linhas_hist = []
        for item in ultimas_msgs:
            if isinstance(item, dict):
                papel = item.get("role", item.get("papel", "usuario"))
                conteudo = item.get("content", item.get("conteudo", item.get("texto", "")))
                if conteudo:
                    linhas_hist.append(f"{papel}: {conteudo}")
        if linhas_hist:
            partes_prompt.append("HISTÓRICO RECENTE DA CONVERSA:\n" + "\n".join(linhas_hist))

    partes_prompt.append(f"SOLICITAÇÃO DO PRODUTOR:\n{str(mensagem_usuario).strip()}")
    prompt_completo = "\n\n---\n\n".join(partes_prompt)

    ultimo_erro = ""
    for modelo in MODELOS_RAPIDOS:
        try:
            resposta = client.models.generate_content(
                model=modelo,
                contents=prompt_completo,
                config={
                    "system_instruction": PROMPT_MESTRE_GRANJA,
                    "temperature": 0.25,
                },
            )
            texto = (getattr(resposta, "text", None) or "").strip()
            if texto:
                return texto
        except Exception as erro:
            ultimo_erro = str(erro)
            continue

    return (
        f"Não foi possível concluir a solicitação neste instante ({ultimo_erro[:140]}). "
        "Tente enviar novamente em alguns segundos."
    )
