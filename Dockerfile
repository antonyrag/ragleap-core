FROM python:3.11-slim

WORKDIR /app

ENV PYTHONIOENCODING=UTF-8
ENV PYTHONUTF8=1
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

CMD ["uvicorn", "core.api:app", "--host", "0.0.0.0", "--port", "8000"]
