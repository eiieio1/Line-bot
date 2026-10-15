import os
import hmac
import base64
import hashlib
import logging
import random
import time
import requests

from flask import Flask, request, abort, jsonify

app = Flask(__name__)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("secret-pantry-bot")

LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"

MAX_OUTPUT_TOKENS = 700
MAX_QUESTION_LENGTH = 12000
MAX_LINE_REPLY_LENGTH = 4500
RETRY_STATUS_CODES = (408, 429, 500, 502, 503, 504)

SYSTEM_PROMPT = """
너는 시크릿 펜트리 단체방의 친근한 AI 집사야.
자연스럽고 예의 있는 한국어로 핵심부터 짧게 답해.
기본 답변은 1~3문장으로 작성해.
방 규칙에 없는 내용을 사실처럼 만들어 내지 말고,
규칙이 불명확하거나 충돌하면 관리자에게 확인하라고 안내해.
사용자의 질문에 직접 답하고 불필요한 인사말이나 반복은 피해야 해.

시크릿 펜트리 주요 규칙:
- 주의 3회는 경고 1회, 경고 2회면 강퇴 대상.
- 하루 메시지 50개 미만은 주의 대상.
- 하루 이상 자리를 비우거나 하루 30개도 채우기 어렵다면
  관리자에게 알리고 닉네임 앞에 🛩️ 표시.
- 읽씹, 무분별한 욕설, 허락 없는 '야', '너' 호칭,
  뒷담화, 도배, 단체 뒷채팅은 금지.
- 뒷담화는 첫 적발 시 경고, 두 번째 적발 시 강퇴.
- 상대방이 불편해하는 플러팅이나 스킨십은 중단해야 함.
- @All 및 /쉿은 관리자만 사용 가능.
- /쉿이 올라오면 관리자가 '쉿 끝'이라고 할 때까지 채팅하지 않고,
  공지 후 '확인했습니다.'라고 답함.
- 다른 회원의 사진이나 영상을 저장하거나 캡처하면 즉시 강퇴 대상.
- 오전 9시부터 오후 10시까지 공창에 🔞 사진·영상을 올리려면
  먼저 'ㅁㄴ'을 작성해야 함.
- 미클은 미션 클리어를 뜻하며 남성에게 적용됨.
- 여성은 입장 시 미클로 간주하고, 남성은 여초 미션을 완료해야 함.
- 미클이 아닌 남성이 여성에게 먼저 갠라를 보내면 강퇴 대상.
- 여성이 미클 인증을 받지 않은 남성에게 먼저 갠라를 보내는 것도 금지.
- 여성 1명 초대는 게시판 작성 시간부터 72시간,
  여성 2명 초대는 24시간이 지나야 미션 클리어.
- 지인·친구 초대 및 동반 초대는 미클로 인정되지 않음.
- 노미클 승격 조건은 일주일 동안 홍보지 2,000개와
  총 30,000마디 이상 활동.
- 벙은 미클 인증자만 참여 가능.
- 벙 게시판 댓글은 [닉네임 / 날짜 / 건벙 또는 섹벙] 양식.
- 3명 이상 단벙은 방장과 부방장을 초대해 단체방을 만들고,
  8명 초과 단벙에는 운영진 한 명이 참석해야 함.
- 벙 후 사진을 앨범에 올리고, 3명 이상이면 사진 속 위치에 맞춰
  참여자 이름을 표시해야 함.
- 여성은 섹벙 3회째에 검사지 제출이 필수이며 같은 사람과의 섹벙은
  횟수에서 차감하지 않음. 검사 비용은 본인 부담.
- 몰벙은 운영진에게 알리지 않고 진행하는 모임이며 강퇴 대상.
- 개인 라인에서 괴롭힘, 강요, 원치 않는 성적 발언은 금지.
- 방을 나간 사람에게 다시 연락하는 것은 금지.
- 야단라는 야한 단체 라인, 공창은 단체 채팅방, 갠라는 개인 라인.
- 여초는 여성 초대, 남초는 남성 초대, 벙은 오프라인 모임.
- 음통은 음성통화, 영통은 영상통화, 다락은 단체 통화방.
"""

TODAY_QUESTIONS = [
    "친해지고 싶은 사람에게 먼저 다가가기 vs 기다리기?",
    "첫인상이 좋은 사람 vs 알수록 좋은 사람?",
    "연락은 자주 하지만 못 만나는 사람 vs 연락은 뜸해도 자주 만나는 사람?",
    "웃음 코드가 잘 맞는 사람 vs 고민을 잘 들어주는 사람?",
    "과거로 하루 돌아가기 vs 미래를 하루 미리 보기?",
    "먼저 고백하기 vs 상대가 고백할 때까지 기다리기?",
    "대화가 잘 통하는 사람 vs 함께 있으면 편안한 사람?",
]

BALANCE_QUESTIONS = [
    "내 검색 기록 공개 vs 내 사진첩 공개?",
    "모든 약속에 30분 일찍 도착 vs 10분 늦기?",
    "연락은 완벽하지만 재미없는 사람 vs 연락은 느리지만 만나면 재밌는 사람?",
    "평생 여름만 살기 vs 평생 겨울만 살기?",
    "내가 먼저 사과하기 vs 상대가 먼저 사과할 때까지 기다리기?",
    "첫눈에 반하는 사랑 vs 천천히 스며드는 사랑?",
    "연인과 밤새 통화하기 vs 만나서 늦게까지 함께 있기?",
]

RULES_FAQ = {
    "읽씹": "읽씹은 금지이며 경고 대상이야.",
    "메시지": (
        "하루 메시지 50개 미만은 주의 대상이야. 하루 이상 자리를 비우거나 "
        "하루 30개도 채우기 어렵다면 관리자에게 알리고 닉네임 앞에 🛩️를 붙여. "
        "기준이 충돌하는 상황은 관리자에게 확인해 줘."
    ),
    "주의": "주의 3회는 경고 1회이며 경고 2회면 강퇴 대상이야.",
    "뒷담화": "뒷담화는 첫 적발 시 경고, 두 번째 적발 시 강퇴야.",
    "갠라": (
        "미클이 아닌 남성이 여성에게 먼저 갠라를 보내면 1회 적발만으로 "
        "강퇴 대상이야. 여성도 미클 인증을 받지 않은 남성에게 먼저 갠라를 보내면 안 돼."
    ),
    "미클": (
        "여성 1명 초대는 게시판 작성 시간부터 72시간, 여성 2명 초대는 "
        "24시간 뒤 미션 클리어야. 지인·친구 초대와 동반 초대는 인정되지 않아."
    ),
    "미클승격": "노미클 기간 일주일 동안 홍보지 2,000개와 총 30,000마디 이상 활동해야 해.",
    "벙": "벙은 미클자만 참여 가능해. 게시판 댓글은 [닉네임 / 날짜 / 건벙 또는 섹벙] 양식이야.",
    "섹벙": "여성은 섹벙 3회째에 검사지 제출이 필수야. 같은 사람과의 섹벙은 횟수에서 차감하지 않아.",
    "사진": "다른 회원의 사진·영상을 저장하거나 캡처하면 즉시 강퇴 대상이야.",
    "쉿": "/쉿은 관리자만 사용 가능해. '쉿 끝' 공지 전까지 채팅하지 않고, 공지 후에는 '확인했습니다.'라고 답해.",
    "홍보지": "노미클 승격 조건은 일주일 동안 홍보지 2,000개와 총 30,000마디 이상 활동이야.",
}

GLOSSARY = {
    "야단라": "야한 단체 라인의 줄임말이야.",
    "미클": "미션 클리어를 뜻해. 이 방에서는 남성에게 적용되는 미션 인증이야.",
    "노미클": "아직 미클 인증을 받지 않은 회원이야.",
    "공창": "단체 채팅방이야.",
    "갠라": "개인 라인이야.",
    "여초": "여성 초대 미션 또는 여성 초대를 뜻해.",
    "남초": "남성 초대를 뜻해.",
    "벙": "오프라인 모임이야.",
    "단벙": "3명 이상이 모이는 오프라인 모임이야.",
    "건벙": "성적인 목적이 아닌 일반 오프라인 모임이야.",
    "섹벙": "성적인 목적의 오프라인 모임이야.",
    "몰벙": "운영진에게 알리지 않고 진행하는 모임이야.",
    "매너봉": "오전 9시부터 오후 10시 사이 19금 미디어를 올리기 전에 'ㅁㄴ'을 작성하는 거야.",
    "음통": "음성통화야.",
    "영통": "영상통화야.",
    "다락": "단체 통화방이야.",
}


def verify_line_signature(body, signature):
    if not LINE_CHANNEL_SECRET or not signature:
        return False

    digest = hmac.new(
        LINE_CHANNEL_SECRET.encode("utf-8"),
        body,
        hashlib.sha256,
    ).digest()

    expected = base64.b64encode(digest).decode("utf-8")
    return hmac.compare_digest(expected, signature)


def reply_to_line(reply_token, message):
    if not LINE_CHANNEL_ACCESS_TOKEN or not reply_token:
        logger.error(
            "LINE 답장 불가: 토큰 설정 여부=%s, replyToken 존재=%s",
            bool(LINE_CHANNEL_ACCESS_TOKEN),
            bool(reply_token),
        )
        return False

    payload = {
        "replyToken": reply_token,
        "messages": [{
            "type": "text",
            "text": str(message)[:MAX_LINE_REPLY_LENGTH],
        }],
    }

    headers = {
        "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(
            LINE_REPLY_URL,
            headers=headers,
            json=payload,
            timeout=20,
        )

        if not response.ok:
            logger.error(
                "LINE 답장 실패: HTTP %s, 응답=%s",
                response.status_code,
                response.text[:800],
            )
            return False

        logger.info("LINE 답장 전송 성공")
        return True

    except requests.RequestException:
        logger.exception("LINE 답장 네트워크 오류")
        return False


def get_available_gemini_models():
    """API 키로 실제 사용 가능한 generateContent 모델을 조회한다."""
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY 환경변수가 설정되지 않았어.")

    response = requests.get(
        GEMINI_MODELS_URL,
        headers={"x-goog-api-key": GEMINI_API_KEY},
        params={"pageSize": 100},
        timeout=20,
    )

    if not response.ok:
        logger.error(
            "Gemini 모델 목록 조회 실패: HTTP %s, 응답=%s",
            response.status_code,
            response.text[:800],
        )
        response.raise_for_status()

    models = response.json().get("models", [])
    available = []

    for item in models:
        name = item.get("name", "")
        methods = item.get("supportedGenerationMethods", [])

        if not name.startswith("models/"):
            continue
        if "generateContent" not in methods:
            continue

        model_name = name.removeprefix("models/")

        # 대화용 Gemini 모델만 사용한다.
        if "gemini" not in model_name.lower():
            continue
