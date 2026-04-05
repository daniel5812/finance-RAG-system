# 1. Base Image - אנחנו מתחילים ממערכת לינוקס קלילה שיש בה כבר פייתון 3.9
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 
ENV PIP_DEFAULT_TIMEOUT=1000

# 2. Work Directory - איפה נעבוד בתוך המכולה
WORKDIR /app

# 3. Base ML Dependencies - (Heavy layers, cached separately)
# We do this BEFORE requirements.txt so that adding a small library doesn't trigger a 1GB re-download.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --upgrade pip

RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --retries 10 torch sentence-transformers --extra-index-url https://download.pytorch.org/whl/cpu

RUN python -c "from sentence_transformers import SentenceTransformer, CrossEncoder; \
    SentenceTransformer('all-MiniLM-L6-v2'); \
    CrossEncoder('cross-encoder/ms-marco-MiniLM-L-6-v2')"

# 4. App Dependencies
COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# 5. Copy Code - מעתיקים את שאר הקוד שלנו (main.py) פנימה
COPY . .

EXPOSE 8000

# 6. Run Command - הפקודה שתרוץ כשהשרת יעלה
# שים לב: אנחנו משתמשים ב-host 0.0.0.0 כדי שנוכל לגשת מבחוץ
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
