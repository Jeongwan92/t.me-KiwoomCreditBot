import os
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

# Gemini Client 초기화
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
        print(f"[{company}] RSS 파싱 에러: {e}")
        return []

def summarize_news(title, company):
    prompt = f"""
기업명: {company}
기사 제목: {title}

위 기사 정보를 바탕으로 해당 기업 관련 핵심 내용을 파악하여 요약해줘.
요구조건:
1. 반드시 한국어로 작성할 것.
2. 개조식(- 형태)으로 3줄 내외로 핵심 사실만 정리할 것.
3. 군더더기 서두나 인사말 없이 요약 내용만 바로 출력할 것.
"""
    # 안정적인 호출 모델
    models_to_try = ["gemini-2.0-flash", "gemini-2.5-flash"]
    last_error = ""

    for model_name in models_to_try:
        try:
            time.sleep(2)  # 분당 요청 제한(RPM) 보호
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response.text:
                return response.text.strip()
        except Exception as err:
            last_error = str(err)
            print(f"[{company}] {model_name} 요약 에러: {err}")
            time.sleep(3)

    return f"- 요약 생성 실패 (원문 기사 확인 권장)\n- 원인: {last_error[:80]}"

def send_telegram(company, title, summary, link):
    safe_title = title.replace("*", "").replace("_", "")
    message = (
        f"📢 *[{company}] 실시간 속보*\n\n"
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
        print(f"[{company}] 전송 완료: {res.status_code}")
    except Exception as e:
        print(f"[{company}] 전송 실패: {e}")

def main():
    print(f"=== 모니터링 가동 (대상 채널: {TELEGRAM_CHANNEL_ID}) ===")
    sent_links = load_sent_links()
    print(f"기록된 링크 수: {len(sent_links)}")

    for company in TARGET_COMPANIES:
        print(f"[{company}] 뉴스 검색...")
        news_items = fetch_news(company)
        print(f"[{company}] 수집 기사: {len(news_items)}건")

        for item in reversed(news_items):
            link = item["link"]
            title = item["title"]
            if link not in sent_links:
                print(f"[{company}] 신규 기사 처리: {title}")
                summary = summarize_news(title, company)
                send_telegram(company, title, summary, link)
                save_sent_link(link)
                sent_links.add(link)
                time.sleep(3)  # 채널 발송 및 API 쿨타임
            else:
                print(f"[{company}] 기존 기사 건너뜀")

if __name__ == "__main__":
    main()
