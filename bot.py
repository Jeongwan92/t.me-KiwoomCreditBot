import os
import re
import time
import urllib.parse
import feedparser
import requests
from google import genai

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TARGET_COMPANIES = ["삼성전자", "SK하이닉스", "현대차"]
HISTORY_FILE = "sent_links.txt"

gemini_client = genai.Client(api_key=GEMINI_API_KEY)

def load_sent_links():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")

def extract_og_image(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        match = re.search(r'<meta[^>]*property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', resp.text, re.IGNORECASE)
        if not match:
            match = re.search(r'<meta[^>]*content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', resp.text, re.IGNORECASE)
        if match:
            return match.group(1)
    except Exception:
        pass
    return None

def fetch_news(company):
    query = urllib.parse.quote(f"{company} when:1h")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(rss_url, headers=headers, timeout=10)
        feed = feedparser.parse(resp.content)
        if not feed.entries:
            query_1d = urllib.parse.quote(f"{company} when:1d")
            rss_url_1d = f"https://news.google.com/rss/search?q={query_1d}&hl=ko&gl=KR&ceid=KR:ko"
            resp = requests.get(rss_url_1d, headers=headers, timeout=10)
            feed = feedparser.parse(resp.content)

        articles = []
        for entry in feed.entries[:3]:
            articles.append({"title": entry.title, "link": entry.link})
        return articles
    except Exception as e:
        print(f"[{company}] RSS 수집 에러: {e}")
        return []

def summarize_news(title, company):
    prompt = (
        f"기업명: {company}\n"
        f"기사 제목: {title}\n\n"
        "위 기사의 핵심 배경과 기업/시장에 미치는 영향을 금융 브리핑 스타일로 요약해줘.\n"
        "[작성 조건]\n"
        "1. 한국어 개조식(- 형태)으로 3줄 내외로 작성할 것.\n"
        "2. 인사말이나 부가 문구 없이 요약 본문만 바로 출력할 것."
    )
    models = ["gemini-2.0-flash", "gemini-1.5-flash"]
    for model_name in models:
        try:
            time.sleep(1.5)
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response and response.text:
                return response.text
