import os
import re
import time
import urllib.parse
import feedparser
import requests

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHANNEL_ID = os.environ.get("TELEGRAM_CHANNEL_ID")

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

def extract_article_lead(link):
    """AI API 대신 기사 원문 페이지에서 핵심 문장 2~3줄 직접 추출"""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        session = requests.Session()
        res = session.get(link, headers=headers, timeout=5, allow_redirects=True)
        html = res.text

        # meta description(기사 요약문) 우선 추출
        m_desc = re.search(r'<meta[^>]+(?:name|property)=["\'](?:og:description|description)["\'][^>]+content=["\']([^"\']+)["\']', html, re.IGNORECASE)
        if not m_desc:
            m_desc = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:og:description|description)["\']', html, re.IGNORECASE)

        if m_desc:
            desc = m_desc.group(1).strip()
            # 구글 뉴스 기본 안내문구 제외
            if desc and "Google" not in desc and len(desc) > 20:
                # 문장 단위로 분리하여 2~3개 불릿으로 변환
                sentences = [s.strip() for s in re.split(r'(?<=[.?!])\s+', desc) if len(s.strip()) > 5]
                if sentences:
                    return "\n".join([f"- {s}" for s in sentences[:3]])
                return f"- {desc}"

        # description이 없을 경우 본문 <p> 태그에서 텍스트 수집
        paragraphs = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
        clean_paras = []
        for p in paragraphs:
            text = re.sub(r'<[^>]+>', '', p).strip()
            text = re.sub(r'\s+', ' ', text)
            if len(text) > 30 and not any(bad in text for bad in ["기자", "무단전재", "저작권", "구독"]):
                clean_paras.append(text)
            if len(clean_paras) >= 2:
                break

        if clean_paras:
            return "\n".join([f"- {p}" for p in clean_paras[:2]])

    except Exception:
        pass

    return "- 기사 본문 주요 내용 및 세부 공시는 링크를 참조하세요."

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
                content = extract_article_lead(item["link"])
                send_to_channel(company, item["title"], content, item["link"])
                save_sent_link(item["link"])
                sent.add(item["link"])
                time.sleep(1)

main()
