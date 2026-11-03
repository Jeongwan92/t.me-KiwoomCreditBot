import os
import time
import urllib.parse
import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

TARGET_COMPANIES = ["삼성전자", "SK하이닉스", "현대차"]
HISTORY_FILE = "sent_links.txt"

def load_sent_links():
    if not os.path.exists(HISTORY_FILE):
        return set()
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        return set(line.strip() for line in f if line.strip())

def save_sent_link(link):
    with open(HISTORY_FILE, "a", encoding="utf-8") as f:
        f.write(link + "\n")

def fetch_news(company):
    headers = {"User-Agent": "Mozilla/5.0"}
    query = urllib.parse.quote(f"{company} when:1h")
    url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        res = requests.get(url, headers=headers, timeout=10)
        feed = feedparser.parse(res.content)
        if not feed.entries:
            query_1d = urllib.parse.quote(f"{company} when:1d")
            url_1d = f"https://news.google.com/rss/search?q={query_1d}&hl=ko&gl=KR&ceid=KR:ko"
            res = requests.get(url_1d, headers=headers, timeout=10)
            feed = feedparser.parse(res.content)
        return [{"title": e.title, "link": e.link} for e in feed.entries[:1]]
    except Exception as e:
        print(f"[{company}] RSS 에러: {e}")
        return []

def summarize(title, company):
    if not GEMINI_API_KEY:
        return "- 핵심 시장 동향 점검 필요 (API 키 누락)"

    prompt_text = (
        f"기업명: {company}\n기사 제목: {title}\n\n"
        "위 뉴스의 핵심 내용과 기업/시장에 미치는 영향을 금융 브리핑 스타일로 한국어 개조식(- 형태) 3줄로 작성해줘. "
        "인사말이나 서두 없이 3개 요약 행만 바로 출력해."
    )

    # 503 과부하 발생 시 대체할 경량 모델 리스트
    fallback_models = ["gemini-3.8-flash", "gemini-3.8-flash-lite", "gemini-1.5-flash"]
    last_err = ""

    for model in fallback_models:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

        # 503 과부하 시 최대 3회 재시도
        for attempt in range(3):
            try:
                res = requests.post(endpoint, json=payload, timeout=20)
                data = res.json()

                if res.status_code == 200:
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts and "text" in parts[0]:
                            return parts[0]["text"].strip()
                    return "- 요약 생성 실패 (내용 공백)"

                # 503 (과부하) 또는 429 (레이트 리밋) 발생 시 대기 후 재시도
                if res.status_code in [503, 429]:
                    time.sleep(5)
                    continue

                last_err = f"API 오류 ({res.status_code})"
                break
            except Exception as e:
                last_err = f"통신 오류 ({str(e)})"
                time.sleep(3)

    return f"- 요약 생성 지연 ({last_err})\n- 상세 내용은 원문 기사를 확인하세요."

def send_to_channel(company, title, summary, link):
    safe_title = title.replace("<", "<").replace(">", ">").replace("&", "&")
    safe_summary = summary.replace("<", "<").replace(">", ">")

    message = (
        f"🏢 <b>[{company}] 실시간 마켓 브리프</b>\n\n"
        f"📌 <b>{safe_title}</b>\n\n"
        f"{safe_summary}\n\n"
        f'🔗 <a href="{link}">기사 원문 바로가기</a>'
    )

    msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }
    try:
        requests.post(msg_url, json=payload, timeout=10)
    except Exception as e:
        print(f"[{company}] 전송 실패: {e}")

def main():
    sent = load_sent_links()
    for company in TARGET_COMPANIES:
        articles = fetch_news(company)
        for item in reversed(articles):
            if item["link"] not in sent:
                sm = summarize(item["title"], company)
                send_to_channel(company, item["title"], sm, item["link"])
                save_sent_link(item["link"])
                sent.add(item["link"])
                time.sleep(14)

main()
