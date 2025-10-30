# Usa uma imagem Python leve
FROM python:3.11-slim

# Define a variável de ambiente para Python
ENV PYTHONUNBUFFERED 1

# Define o diretório de trabalho
WORKDIR /app

# Copia e instala as dependências do Worker
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copia o código do Worker
COPY . /app

# Comando de inicialização do Worker (NÃO do Flask!)
CMD ["python", "worker.py"]

