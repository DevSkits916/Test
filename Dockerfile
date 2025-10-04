FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
ENV PORT=3000 BIND=0.0.0.0
EXPOSE 3000
CMD ["python", "app.py"]
