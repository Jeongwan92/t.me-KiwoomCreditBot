import os
import re
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

def get_og_image(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        m = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', r.text)
        if not m:
            m = re.search(r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', r.text)
        return m.group(1) if m else None
    except:
        return None

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
    except:
        return []

def summarize(title, company):
    # SDK 대신 직접 REST API 호출 (SDK 버전 불일치 원천 해결)
    prompt_text = (
        f"기업명: {company}\n기사 제목: {title}\n\n"
        "위 뉴스의 핵심 사실과 시장 영향을 금융 브리핑 스타일로 한국어 개조식(- 형태) 3줄로 명확하게 요약해줘. "
        "서두, 인사말, 불필요한 서술어 없이 3개 요약 행만 바로 출력해."
    )
    
    # 순차적으로 호출할 안정적인 모델 엔드포인트
    models = ["gemini-1.5-flash", "gemini-2.0-flash", "gemini-2.5-flash"]
    
    for m in models:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        payload = {
            "contents": [{
                "parts": [{"text": prompt_text}]
            }]
        }
        try:
            res = requests.post(endpoint, json=payload, timeout=15)
            data = res.json()
            if res.status_code == 200:
                summary_text = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                return summary_text
            else:
                err_msg = data.get("error", {}).get("message", res.text)
                print(f"[{company}] {m} 에러 ({res.status_code}): {err_msg}")
        except Exception as e:
            print(f"[{company}] {m} 요청 예외: {e}")
        time.sleep(1)

    return "- 핵심 시장 변동성 점검 필요\n- 세부 내용은 원문 기사를 확인해 주시기 바랍니다."

def send_to_channel(company, title, summary, link):
    safe_title = title.replace("<", "<").replace(">", ">").replace("&", "&")
    safe_summary = summary.replace("<", "<").replace(">", ">")
    
    text = (
        f"🏢 <b>[{company}] 실시간 마켓 브리프</b>\n\n"
        f"📌 <b>{safe_title}</b>\n\n"
        f"{safe_summary}\n\n"
        f'🔗 <a href="{link}">기사 원문 바로가기</a>'
    )
    
    img = get_og_image(link)
    if img:
        photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        data = {"chat_id": TELEGRAM_CHANNEL_ID, "photo": img, "caption": text, "parse_mode": "HTML"}
        try:
            r = requests.post(photo_url, json=data, timeout=10)
            if r.status_code == 200:
                print(f"[{company}] 사진 브리핑 전송 완료")
                return
        except:
            pass

    msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHANNEL_ID, "text": text, "parse_mode": "HTML"}
    requests.post(msg_url, json=data, timeout=10)
    print(f"[{company}] 텍스트 브리핑 전송 완료")

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

if __name__ == "__main__":
