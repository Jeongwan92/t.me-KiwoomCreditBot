import os
import re
import time
import urllib.parse
import feedparser
import requests
from bs4 import BeautifulSoup
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

def fetch_article_meta(url):
    """기사 본문 페이지의 대표 썸네일(og:image)을 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=5, allow_redirects=True)
        soup = BeautifulSoup(resp.content, "html.parser")
        og_img = soup.find("meta", property="og:image")
        if og_img and og_img.get("content"):
            return og_img["content"]
    except Exception:
        pass
    return None

def fetch_news(company):
    # 최근 1시간 최신순 검색
    query = urllib.parse.quote(f"{company} when:1h")
    rss_url = f"https://news.google.com/rss/search?q={query}&hl=ko&gl=KR&ceid=KR:ko"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(rss_url, headers=headers, timeout=10)
        feed = feedparser.parse(resp.content)
        
        # 1시간 이내 기사 부족 시 당일 최신순 백업
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
        print(f"[{company}] RSS 수집 오류: {e}")
        return []

def summarize_news(title, company):
    prompt = f"""
기업명: {company}
기사 제목: {title}

위 기사의 핵심 배경과 기업 영향을 분석하여 금융 브리핑 스타일로 요약해줘.
요구조건:
1. 반드시 정중하고 간결한 한국어로 작성할 것.
2. 개조식(- 형태)으로 3줄 내외로 작성할 것.
3. 부가 문구 없이 요약 내용만 출력할 것.
"""
    models = ["gemini-2.0-flash", "gemini-1.5-flash"]
    for model_name in models:
        try:
            time.sleep(1.5)
            response = gemini_client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            if response and response.text:
                return response.text.strip()
        except Exception as err:
            print(f"[{company}] {model_name} 요약 실패: {err}")
            time.sleep(2)
            
    return "- 본문 핵심 내용 확인 권장 (원문 기사 참조)"

def send_telegram(company, title, summary, link):
    # 특수문자 충돌을 방지하기 위해 HTML 파싱 모드로 안전하게 전송
    image_url = fetch_article_meta(link)
    
    # 텔레그램 상단 이미지 카드를 띄우는 숨김 링크 기법 (Zero-width space)
    image_tag = f'<a href="{image_url}">‍</a>' if image_url else ""
    
    clean_title = title.replace("<", "<").replace(">", ">").replace("&", "&")
    clean_summary = summary.replace("<", "<").replace(">", ">")

    message = (
        f"{image_tag}"
        f"🏢 <b>[{company}] 실시간 마켓 브리프</b>\n\n"
        f"📌 <b>{clean_title}</b>\n\n"
        f"{clean_summary}\n\n"
        f'🔗 <a href="{link}">기사 원문 바로가기</a>'
    )
    
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHANNEL_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": False
    }
    
    try:
        res = requests.post(url, json=payload, timeout=10)
        print(f"[{company}] 전송 응답: {res.status_code} - {res.text}")
    except Exception as e:
        print(f"[{company}] 전송 통신 오류: {e}")

def main():
    print(f"=== 모니터링 가동 (대상 채널: {TELEGRAM_CHANNEL_ID}) ===")
    sent_links = load_sent_links()
    print(f"기존 저장된 링크 수: {len(sent_links)}")

    for company in TARGET_COMPANIES:
        print(f"[{company}] 뉴스 검색 중...")
        news_items = fetch_news(company)
        print(f"[{company}] 수집 완료: {len(news_items)}건")

        for item in reversed(news_items):
            link = item["link"]
            title = item["title"]
            if link not in sent_links:
                print(f"[{company}] 신규 기사 처리: {title}")
                summary = summarize_news(title, company)
                send_telegram(company, title, summary, link)
                save_sent_link(link)
                sent_links.add(link)
                time.sleep(2)
            else:
                print(f"[{company}] 기존 발송 링크 스킵")

if __name__ == "__main__":
    main()
