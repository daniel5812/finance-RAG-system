# 1. Base Image - אנחנו מתחילים ממערכת לינוקס קלילה שיש בה כבר פייתון 3.9
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 

# 2. Work Directory - איפה נעבוד בתוך המכולה
WORKDIR /app

# 3. Copy Dependencies - מעתיקים קודם את רשימת הספריות (כדי לנצל Cache)
COPY requirements.txt .

# 4a. Install PyTorch CPU-only (layer cached separately - won't re-download)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install torch --index-url https://download.pytorch.org/whl/cpu

# 4b. Install remaining dependencies (torch already satisfied from step 4a)
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install -r requirements.txt --extra-index-url https://download.pytorch.org/whl/cpu

# 5. Copy Code - מעתיקים את שאר הקוד שלנו (main.py) פנימה
COPY . .

EXPOSE 8000

# 6. Run Command - הפקודה שתרוץ כשהשרת יעלה
# שים לב: אנחנו משתמשים ב-host 0.0.0.0 כדי שנוכל לגשת מבחוץ
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
