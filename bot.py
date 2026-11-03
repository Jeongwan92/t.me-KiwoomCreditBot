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
        return [{"title": e.title, "link": e.link} for e in feed.entries[:3]]
    except Exception as e:
        print(f"[{company}] RSS 에러: {e}")
        return []

def summarize(title, company):
    if not GEMINI_API_KEY:
        return "- 핵심 시장 변동성 점검 필요\n- 세부 내용은 원문 링크 확인"

    prompt_text = (
        f"기업명: {company}\n기사 제목: {title}\n\n"
        "위 뉴스의 핵심 배경과 기업/시장에 미치는 영향을 금융 브리핑 스타일로 한국어 개조식(- 형태) 3줄로 요약해줘. "
        "서두, 인사말, 부가 설명 없이 3개 요약 행만 바로 출력해."
    )

    # 2026년 기준 공식 지원 모델
    supported_models = ["gemini-2.5-flash", "gemini-1.5-flash"]
    
    for m in supported_models:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        try:
            res = requests.post(endpoint, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            print(f"[{company}] {m} 에러: {res.status_code}")
        except Exception as e:
            print(f"[{company}] {m} 통신 오류: {e}")
        time.sleep(1)

    return "- 핵심 시장 변동성 점검 필요\n- 세부 내용은 원문 링크 확인"

def send_to_channel(company, title, summary, link):
    safe_title = title.replace("<", "<").replace(">", ">").replace("&", "&")
    safe_summary = summary.replace("<", "<").replace(">", ">")

    # 이미지 삽입을 완전히 빼고 텍스트 전용 깔끔한 브리프 구성 (미리보기 비활성화)
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
        "disable_web_page_preview": True  # 구글 로고 미리보기 완벽 차단
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
                time.sleep(2)

main()
