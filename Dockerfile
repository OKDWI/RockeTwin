FROM python:3.11-slim
WORKDIR /app
COPY requirements-mlops.txt .
RUN pip install --no-cache-dir -r requirements-mlops.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "mlops.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
