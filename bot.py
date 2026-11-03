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
    """실제 원문 기사 페이지로 이동하여 og:image를 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        session = requests.Session()
        r = session.get(url, headers=headers, timeout=8, allow_redirects=True)
        # 구글 로고 이미지 필터링
        m = re.search(r'property=["\']og:image["\'][^>]*content=["\']([^"\']+)["\']', r.text)
        if not m:
            m = re.search(r'content=["\']([^"\']+)["\'][^>]*property=["\']og:image["\']', r.text)
        if m:
            img_url = m.group(1)
            if "google" not in img_url.lower():
                return img_url
    except:
        pass
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
    if not GEMINI_API_KEY:
        print(f"[{company}] GEMINI_API_KEY가 비어 있습니다!")
        return "- 요약 생성 일시 지연 (원문 링크 참조)"

    prompt_text = (
        f"기업명: {company}\n기사 제목: {title}\n\n"
        "위 뉴스의 핵심 내용과 기업/시장 영향을 금융 브리핑 스타일로 한국어 개조식(- 형태) 3줄로 작성해줘. "
        "서두나 부가 설명 없이 3줄 요약 내용만 출력해."
    )
    models = ["gemini-2.0-flash", "gemini-1.5-flash"]
    for m in models:
        endpoint = f"https://generativelanguage.googleapis.com/v1beta/models/{m}:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt_text}]}]}
        try:
            res = requests.post(endpoint, json=payload, timeout=12)
            if res.status_code == 200:
                data = res.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
            else:
                print(f"[{company}] {m} 에러코드 {res.status_code}: {res.text}")
        except Exception as e:
            print(f"[{company}] {m} 호출 예외: {e}")
        time.sleep(1)
        
    return "- 요약 생성 일시 지연 (원문 링크 참조)"

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
    
    # 구글 기본 로고가 아닌 유효한 기사 이미지일 때만 사진 카드 전송
    if img:
        photo_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
        data = {"chat_id": TELEGRAM_CHANNEL_ID, "photo": img, "caption": text, "parse_mode": "HTML"}
        try:
            r = requests.post(photo_url, json=data, timeout=10)
            if r.status_code == 200:
                return
        except:
            pass

    # 이미지가 없거나 구글 로고일 땐 텍스트 형태로 깔끔하게 링크 포함 전송
    msg_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    data = {"chat_id": TELEGRAM_CHANNEL_ID, "text": text, "parse_mode": "HTML", "disable_web_page_preview": False}
    requests.post(msg_url, json=data, timeout=10)

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
