FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1
WORKDIR /mcp
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN useradd -m -u 1001 appuser && chown -R appuser:appuser /mcp
USER appuser
EXPOSE 9000
CMD ["python", "server.py"]
