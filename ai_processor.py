import os
from typing import Dict, List, Optional
from langchain_community.document_loaders import PyPDFLoader, UnstructuredWordDocumentLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
from deepseek import DeepSeekLLM


class Questao(BaseModel):
    """Modelo Pydantic para uma única questão de múltipla escolha."""
    pergunta: str = Field(description="A pergunta de múltipla escolha baseada no texto.")
    opcoes: List[str] = Field(description="Lista de 4 opções de resposta, incluindo a correta.")
    resposta_correta: str = Field(description="A resposta correta (deve ser idêntica a uma das opções).")


class QCM_Output(BaseModel):
    """Modelo Pydantic para o conjunto completo de questões."""
    questoes: List[Questao] = Field(description="Lista contendo exatamente 5 objetos de Questão.")

def load_document(file_path: str) -> str:
    """Carrega o conteúdo de um documento (PDF/DOCX/TXT) e o retorna como texto simples."""
    file_extension = os.path.splitext(file_path)[1].lower()

    if file_extension == '.pdf':
        loader = PyPDFLoader(file_path)
    elif file_extension == '.docx':
        loader = UnstructuredWordDocumentLoader(file_path)
    elif file_extension == '.txt':
        loader = TextLoader(file_path, encoding='utf-8')
    else:
        raise ValueError(f"Extensão de arquivo não suportada: {file_extension}")

    docs = loader.load()

    # 2.2. Junta o conteúdo de todas as páginas em uma string
    full_text = " ".join(doc.page_content for doc in docs)
    return full_text

def process_study_material(file_path: str, titulo: Optional[str] = "Estudo Gerado por IA") -> Dict:
    """
    Função principal que realiza o resumo e a geração de QCM de forma síncrona.
    """
    try:
        full_text = load_document(file_path)

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=4000,
            chunk_overlap=200
        )
        texts = text_splitter.create_documents([full_text])
        context_text = texts[0].page_content if texts else full_text[:80000]

        llm = DeepSeekLLM()

        resumo_prompt = PromptTemplate.from_template(
            """
            Você é um Professor Sênior de Cursinho Preparatório, especialista em sintetizar conteúdos complexos para estudantes de alto rendimento.
            
            Sua missão é transformar o texto bruto fornecido em um guia de estudo estratégico. Não apenas resuma; ensine.

            ESTRUTURA OBRIGATÓRIA DE SAÍDA:

            ## 🎯 Objetivo Central & Tese
            (Explique em 1 parágrafo denso: Qual problema o texto resolve? Qual a posição central do autor?)

            ## 🧠 Mapa Mental em Texto
            (Liste os 3 a 5 grandes pilares do texto. Para cada pilar, explique a lógica interna. Use Setas '->' para mostrar causa e consequência)

            ## 🔑 Dicionário de Conceitos
            (Extraia termos técnicos ou definições chave. Formato: **Termo**: Definição simples e direta.)

            ## ⚠️ Radar de Prova (O que costuma cair?)
            (Crie uma lista de bullet points. Foque em: pegadinhas comuns, exceções à regra, datas críticas ou contra-argumentos citados no texto.)

            DIRETRIZES DE QUALIDADE:
            - **Densidade:** Corte palavras vazias. Vá direto ao ponto.
            - **Didática:** Use analogias se o conceito for muito abstrato.
            - **Fidelidade:** Baseie-se EXCLUSIVAMENTE no texto fornecido abaixo.

            TEXTO BASE:
            {text}
            """
        )

        resumo_chain = resumo_prompt | llm
        print("Gerando Resumo...")
        resumo = resumo_chain.invoke({"text": context_text})
        parser = PydanticOutputParser(pydantic_object=QCM_Output)
        qcm_prompt = PromptTemplate.from_template(
            """
            Atue como uma Banca Examinadora Rigorosa. Sua tarefa é criar um exame de múltipla escolha de nível INTERMEDIÁRIO/DIFÍCIL baseado no texto.

            REGRAS DE CRIAÇÃO DE QUESTÕES:
            1. **Foco na Interpretação:** Evite perguntas que podem ser respondidas apenas procurando uma palavra-chave. A pergunta deve exigir entendimento do contexto.
            2. **Distratores Plausíveis:** As alternativas erradas NÃO devem ser absurdas. Elas devem parecer corretas para um aluno desatento (ex: "quase certo, mas com um detalhe errado").
            3. **Sem Pegadinhas Baratas:** Evite "Todas as anteriores" ou "Nenhuma das anteriores".
            4. **Formato:** Gere EXATAMENTE 5 questões.
            5. **Output:** Apenas JSON cru seguindo o formato solicitado.

            TEXTO BASE PARA AS QUESTÕES:
            {text}

            {format_instructions}
            """
        )
        qcm_chain = qcm_prompt.partial(format_instructions=parser.get_format_instructions()) | llm
        print("Gerando Questões...")
        qcm_raw = qcm_chain.invoke({"text": context_text})
        qcm_data = parser.parse(qcm_raw)

        return {
            "status": "completed",
            "titulo": titulo,
            "resumo": resumo,
            "qcm_json": qcm_data.dict()  # Converte o objeto Pydantic para dicionário
        }

    except ValueError as e:
        return {"status": "failed", "error": f"Erro de validação: {e}"}
    except Exception as e:
        return {"status": "failed", "error": f"Erro de Processamento de IA: {e}"}
