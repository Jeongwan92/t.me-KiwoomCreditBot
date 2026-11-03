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
        print(f"[{company}] RSS 수집 오류: {e}")
        return []

def get_available_model():
    """API 키로 사용 가능한 최신 모델명을 구글 서버에서 실시간 조회"""
    if not GEMINI_API_KEY:
        return None, "GEMINI_API_KEY 환경변수가 비어 있습니다."

    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={GEMINI_API_KEY}"
    try:
        res = requests.get(url, timeout=10)
        if res.status_code != 200:
            return None, f"구글 API 인증/호출 실패 ({res.status_code}): {res.text}"

        data = res.json()
        models = [
            m["name"] for m in data.get("models", [])
            if "generateContent" in m.get("supportedGenerationMethods", [])
        ]
        if not models:
            return None, "generateContent 지원 모델 없음"

        # flash 계열 우선 탐색 후 첫 번째 지원 모델 매칭
        for m in models:
            if "flash" in m.lower():
                return m, None
        return models[0], None
    except Exception as e:
        return None, f"통신 오류: {str(e)}"

def summarize(title, company, model_name):
    prompt_text = (
        f"기업명: {company}\n기사 제목: {title}\n\n"
        "위 뉴스의 핵심 내용과 기업/시장에 미치는 영향을 금융 브리핑 스타일로 한국어 개조식(- 형태) 3줄로 요약해줘. "
        "서두, 인사말, 부가 설명 없이 3개 요약 행만 바로 출력해."
    )

    clean_model = model_name if model_name.startswith("models/") else f"models/{model_name}"
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/{clean_model}:generateContent?key={GEMINI_API_KEY}"
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
                return f"- 요약 차단됨 (사유: {candidates[0].get('finishReason')})"
            return "- 요약 응답이 비어 있습니다."
        else:
            err_msg = data.get("error", {}).get("message", res.text)
            return f"- API 오류 ({res.status_code}): {err_msg}"
    except Exception as e:
        return f"- 요청 통신 오류: {str(e)}"

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
        "disable_web_page_preview": True  # 구글 로고 이미지 박스 완전히 제거
    }
    try:
        requests.post(msg_url, json=payload, timeout=10)
    except Exception as e:
        print(f"[{company}] 전송 실패: {e}")

def main():
    sent = load_sent_links()
    model_name, err = get_available_model()

    for company in TARGET_COMPANIES:
        articles = fetch_news(company)
        for item in reversed(articles):
            if item["link"] not in sent:
                if model_name:
                    sm = summarize(item["title"], company, model_name)
                else:
                    sm = f"- 요약 불가: {err}"

                send_to_channel(company, item["title"], sm, item["link"])
                save_sent_link(item["link"])
                sent.add(item["link"])
                time.sleep(2)

main()
