FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
# libatomic1 нужен node-драйверу Playwright; без него playwright install падает с кодом 127
RUN apt-get update \
    && apt-get install -y --no-install-recommends libatomic1 \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt \
    && playwright install --with-deps chromium

COPY . .

CMD ["python", "main.py"]
