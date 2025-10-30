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
        context_text = texts[0].page_content if texts else full_text[:8000]

        llm = DeepSeekLLM()

        resumo_prompt = PromptTemplate.from_template(
            "Você é um tutor especializado. Crie um resumo conciso, didático e focado em pontos-chave a partir do texto a seguir. O resumo deve ter no máximo 300 palavras. TEXTO: {text}"
        )
        resumo_chain = resumo_prompt | llm
        resumo = resumo_chain.invoke({"text": context_text})
        parser = PydanticOutputParser(pydantic_object=QCM_Output)
        qcm_prompt = PromptTemplate.from_template(
            "Com base no texto fornecido, gere **EXATAMENTE 5** questões de múltipla escolha (QCM). Cada questão deve ter **4 opções** de resposta (A, B, C, D) e uma única resposta correta. Use a formatação JSON específica do esquema Pydantic. TEXTO: {text}\n\n{format_instructions}"
        )
        qcm_chain = qcm_prompt.partial(format_instructions=parser.get_format_instructions()) | llm
        qcm_raw = qcm_chain.invoke({"text": resumo})
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
