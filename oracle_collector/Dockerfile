FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# O wallet NÃO entra na imagem: db.py extrai ORACLE_WALLET_BASE64 em /app/wallet
# na primeira conexão (mesmo padrão do google-alerts-parser).
COPY main.py nyt_client.py db.py ./

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
