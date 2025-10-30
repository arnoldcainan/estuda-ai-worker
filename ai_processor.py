import os
from typing import Dict, List, Optional
from langchain_community.document_loaders import PyPDFLoader, UnstructuredWordDocumentLoader, TextLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_core.prompts import PromptTemplate
from pydantic import BaseModel, Field
from langchain_core.output_parsers import PydanticOutputParser
from langchain_core.outputs import LLMResult, ChatResult
from deepseek import DeepSeekLLM


class Questao(BaseModel):
    """Modelo Pydantic para uma única questão de múltipla escolha."""
    pergunta: str = Field(description="A pergunta de múltipla escolha baseada no texto.")
    opcoes: List[str] = Field(description="Lista de 4 opções de resposta, incluindo a correta.")
    resposta_correta: str = Field(description="A resposta correta (deve ser idêntica a uma das opções).")


class QCM_Output(BaseModel):
    """Modelo Pydantic para o conjunto completo de questões."""
    questoes: List[Questao] = Field(description="Lista contendo exatamente 5 objetos de Questão.")


# --- 2. Função Central de Leitura de Documentos ---

def load_document(file_path: str) -> str:
    """Carrega o conteúdo de um documento (PDF/DOCX/TXT) e o retorna como texto simples."""
    file_extension = os.path.splitext(file_path)[1].lower()

    # 2.1. Seleciona o Loader com base na extensão
    if file_extension == '.pdf':
        # Usa PyPDFLoader para PDFs
        loader = PyPDFLoader(file_path)
    elif file_extension == '.docx':
        # Usa Unstructured para DOCX (requer dependências como python-docx)
        loader = UnstructuredWordDocumentLoader(file_path)
    elif file_extension == '.txt':
        # Usa TextLoader para TXT
        loader = TextLoader(file_path, encoding='utf-8')
    else:
        raise ValueError(f"Extensão de arquivo não suportada: {file_extension}")

    docs = loader.load()

    # 2.2. Junta o conteúdo de todas as páginas em uma string
    full_text = " ".join(doc.page_content for doc in docs)
    return full_text


# --- 3. Função de Processamento Completo de IA (Síncrono) ---

# ai_processor.py

def process_study_material(file_path: str, titulo: Optional[str] = "Estudo Gerado por IA") -> Dict:
    """
    Função principal que realiza o resumo e a geração de QCM de forma síncrona.
    """
    try:
        # 3.1. CARREGAR E DIVIDIR O DOCUMENTO
        full_text = load_document(file_path)

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=4000,
            chunk_overlap=200
        )
        texts = text_splitter.create_documents([full_text])
        context_text = texts[0].page_content if texts else full_text[:8000]

        llm = DeepSeekLLM()

        # 3.2. GERAÇÃO DE RESUMO
        resumo_prompt = PromptTemplate.from_template(
            "Você é um tutor especializado. Crie um resumo conciso, didático e focado em pontos-chave a partir do texto a seguir. O resumo deve ter no máximo 300 palavras. TEXTO: {text}"
        )
        resumo_chain = resumo_prompt | llm

        # Com a correção no deepseek.py, 'resumo' será uma string
        resumo = resumo_chain.invoke({"text": context_text})

        # 3.3. GERAÇÃO DE QCM (Questionário de Múltipla Escolha)
        parser = PydanticOutputParser(pydantic_object=QCM_Output)

        qcm_prompt = PromptTemplate.from_template(
            "Com base no texto fornecido, gere **EXATAMENTE 5** questões de múltipla escolha (QCM). Cada questão deve ter **4 opções** de resposta (A, B, C, D) e uma única resposta correta. Use a formatação JSON específica do esquema Pydantic. TEXTO: {text}\n\n{format_instructions}"
        )

        qcm_chain = qcm_prompt.partial(format_instructions=parser.get_format_instructions()) | llm

        # 'qcm_raw' será a string JSON de resposta do LLM
        # ATENÇÃO: Trocamos context_text por 'resumo'. Usar o resumo como base para as questões é mais rápido e focado.
        qcm_raw = qcm_chain.invoke({"text": resumo})

        # Tenta parsear a saída JSON do LLM
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
        # Captura DeepSeekError ou erros de conexão
        return {"status": "failed", "error": f"Erro de Processamento de IA: {e}"}

# --- FIM DO SERVIÇO ---