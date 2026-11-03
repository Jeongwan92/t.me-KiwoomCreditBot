import os
import time
import urllib.parse
import feedparser
import requests
from google import genai

# GitHub Secrets 환경 변수 로드
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# 모니터링 대상 기업
TARGET_COMPANIES = ["삼성전자", "SK하이닉스", "현대차"]
HISTORY_FILE = "sent_links.txt"

# Gemini API 클라이언트 초기화
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

def load_sent_links():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")

def fetch_news(company):
    query = urllib.parse.quote(company)
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(rss_url, headers=headers, timeout=10)
        feed = feedparser.parse(resp.content)
        articles = []
        for entry in feed.entries[:3]:
            articles.append({"title": entry.title, "link": entry.link})
        return articles
    except Exception as e:
        print(f"[{company}] RSS 가져오기 실패: {e}")
        return []

def summarize_news(title, company):
    prompt = f"""
기업명: {company}
기사 제목: {title}

위 기사 정보를 바탕으로 해당 기업 관련 핵심 내용을 파악하여 요약해줘.
요구조건:
1. 반드시 한국어로 작성할 것.
2. 개조식(- 형태)으로 4줄 이내로 핵심 사실만 정리할 것.
3. 군더더기 서두나 결론 문구 없이 요약 내용만 출력할 것.
"""
    # 503 트래픽 과부하 방지를 위한 후보 모델 리스트
    candidate_models = ["gemini-2.0-flash", "gemini-1.5-flash", "gemini-2.5-flash"]
    
    for model_name in candidate_models:
        for attempt in range(2):
            try:
                response = gemini_client.models.generate_content(
                    model=model_name,
                    contents=prompt,
                )
                if response.text:
                    return response.text.strip()
            except Exception as err:
                print(f"[{company}] {model_name} 호출 오류 (재시도 {attempt+1}): {err}")
                time.sleep(2)
                
    return "- 요약 생성 일시 지연 (최신 원문 기사를 확인해주세요)"

def send_telegram(company, title, summary, link):
    safe_title = title.replace("*", "").replace("_", "")
    message = (
        f"📢 *[{company}] 최신 뉴스*\n\n"
        f"📌 *{safe_title}*\n\n"
        f"{summary}\n\n"
        f"🔗 [원문 기사 보기]({link})"
    )
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": message,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"[{company}] 텔레그램 발송 결과: {res.status_code}")
    except Exception as e:
        print(f"[{company}] 전송 실패: {e}")

def main():
    print(f"=== 뉴스 봇 시작 (채널: {TELEGRAM_CHANNEL_ID}) ===")
    sent_links = load_sent_links()
    print(f"기존 저장된 링크 수: {len(sent_links)}")

    for company in TARGET_COMPANIES:
        print(f"[{company}] 뉴스 수집 중...")
        news_items = fetch_news(company)
        print(f"[{company}] 수집 완료: {len(news_items)}건")

        for item in reversed(news_items):
            link = item["link"]
            title = item["title"]
            if link not
