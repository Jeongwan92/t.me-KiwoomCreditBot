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

def get_real_available_models():
    """현재 API 키로 호출 가능한 구글 실시간 모델 목록 조회"""
    if not GEMINI_API_KEY:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            valid = []
            for m in data.get("models", []):
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    name = m.get("name", "")
                    if name.startswith("models/"):
                        valid.append(name.replace("models/", ""))
                    else:
                        valid.append(name)
            flash_models = [m for m in valid if "flash" in m.lower()]
            other_models = [m for m in valid if "flash" not in m.lower()]
            return flash_models + other_models
    except Exception as e:
        print(f"모델 조회 실패: {e}")
    return ["gemini-1.5-flash"]

def summarize(title, company, models_list):
    if not GEMINI_API_KEY:
        return "- API 키 설정 누락"

    prompt_text = (
        f"기업명: {company}\n기사 제목: {title}\n\n"
        "위 뉴스의 핵심 배경과 기업/시장에 미치는 영향을 금융 브리핑 스타일로 한국어 개조식(- 형태) 3줄로 작성해줘. "
        "서두, 인사말, 부가 설명 없이 3개 요약 행만 바로 출력해."
    )

    last_error = ""
    for model in models_list:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}

        try:
            res = requests.post(endpoint, json=payload, timeout=15)
            data = res.json()

            if res.status_code == 200:
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    if parts and "text" in parts[0]:
                        return parts[0]["text"].strip()
            elif res.status_code in [503, 429]:
                last_error = f"{model} 과부하({res.status_code})"
                time.sleep(2)
                continue
            else:
                last_error = f"{model} 오류({res.status_code})"
        except Exception as e:
            last_error = f"{model} 통신 실패({str(e)})"

    return f"- 요약 생성 지연 ({last_error})\n- 세부 내용은 기사 링크 참조"

def send_to_channel(company, title, summary, link):
    safe_title = title.replace("<", "<").replace(">", ">").replace("&", "&")
    safe_summary = summary.replace("<", "<").replace(">", ">")

    # '실시간 마켓 브리프' 문구 제거 완료
    message = (
        f"🏢 <b>[{company}]</b>\n\n"
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
    active_models = get_real_available_models()
    print(f"현재 가용 모델: {active_models}")

    for company in TARGET_COMPANIES:
        articles = fetch_news(company)
        for item in reversed(articles):
            if item["link"] not in sent:
                sm = summarize(item["title"], company, active_models)
                send_to_channel(company, item["title"], sm, item["link"])
                save_sent_link(item["link"])
                sent.add(item["link"])
                time.sleep(12)

main()
