FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app.py .
# Bound to all interfaces INSIDE the container; the port mapping is what keeps
# it private — compose publishes it on 127.0.0.1 only, and nginx never sees it.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8020"]
