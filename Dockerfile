FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
RUN pip install --no-cache-dir --no-deps .
COPY dashboard ./dashboard
COPY .streamlit ./.streamlit
COPY scripts ./scripts
COPY config ./config
COPY data ./data
RUN useradd --create-home pharma && chown -R pharma:pharma /app
USER pharma
EXPOSE 8501
CMD ["sh", "scripts/start.sh"]
