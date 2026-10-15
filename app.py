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

# Render 환경변수
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

LINE_REPLY_URL = "https://api.line.me/v2/bot/message/reply"
GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models/"

GEMINI_MODELS = [
    "gemini-3.5-flash-lite",
    "gemini-3.8-flash",
    "gemini-3.6-flash",
    "gemini-3.1-flash-lite",
]

MAX_OUTPUT_TOKENS = 700
MAX_QUESTION_LENGTH = 12000
MAX_LINE_REPLY_LENGTH = 4500
MAX_RETRIES_PER_MODEL = 1
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

# 치호의 기존 고정 명령어
COMMANDS = {
    "야옹1": "야옹! 왜 불러?",
    "야옹2": "꺼지게나아",
    "야옹3": "진짜 개빡치네",
    "!명령어": (
        "사용 가능 명령어:\n"
        "야옹1, 야옹2, 야옹3\n"
        "!마딧수, !마딧수순위, !마딧수리셋\n"
        "! 오늘의질문, ! 밸런스게임, ! 순서 이름 이름\n"
        "! 규칙 주제, ! 용어집, !aimodels"
    ),
}

# 기존처럼 메모리에서 집계함.
# 서버가 재시작되면 점수는 초기화됨.
user_scores = {}

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
    "메시지": "하루 메시지 50개 미만은 주의 대상이야. 하루 이상 자리를 비우거나 하루 30개도 채우기 어렵다면 관리자에게 알리고 닉네임 앞에 🛩️를 붙여. 기준이 충돌하는 상황은 관리자에게 확인해 줘.",
    "주의": "주의 3회는 경고 1회이며 경고 2회면 강퇴 대상이야.",
    "뒷담화": "뒷담화는 첫 적발 시 경고, 두 번째 적발 시 강퇴야.",
    "갠라": "미클이 아닌 남성이 여성에게 먼저 갠라를 보내면 1회 적발만으로 강퇴 대상이야. 여성도 미클 인증을 받지 않은 남성에게 먼저 갠라를 보내면 안 돼.",
    "미클": "여성 1명 초대는 게시판 작성 시간부터 72시간, 여성 2명 초대는 24시간 뒤 미션 클리어야. 지인·친구 초대와 동반 초대는 인정되지 않아.",
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
        logger.error("LINE 토큰 또는 replyToken이 없음")
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
                "LINE 답장 실패: %s %s",
                response.status_code,
                response.text[:1000],
            )
            return False
        return True
    except requests.RequestException:
        logger.exception("LINE 답장 중 네트워크 오류")
        return False


def get_gemini_models():
    if not GEMINI_API_KEY:
        return False, "GEMINI_API_KEY가 Render 환경변수에 설정되지 않았어."

    try:
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": GEMINI_API_KEY},
            params={"pageSize": 100},
            timeout=20,
        )
        if not response.ok:
            return False, f"모델 조회 실패: HTTP {response.status_code}"

        models = response.json().get("models", [])
        usable = [
            model.get("name", "").replace("models/", "")
            for model in models
            if "generateContent" in model.get(
                "supportedGenerationMethods", []
            )
        ]
        if not usable:
            return True, "사용 가능한 모델이 조회되지 않았어."
        return True, "사용 가능한 모델:\n" + "\n".join(
            f"• {name}" for name in usable[:40]
        )
    except (requests.RequestException, ValueError):
        logger.exception("Gemini 모델 목록 조회 오류")
        return False, "모델 목록을 가져오지 못했어. Render 로그를 확인해 줘."


def ask_gemini(question):
    if not GEMINI_API_KEY:
        return "Gemini API 키가 설정되지 않았어. 관리자에게 알려 줘."

    payload = {
        "systemInstruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"role": "user", "parts": [{"text": question}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": MAX_OUTPUT_TOKENS,
        },
    }

    last_error = "알 수 없는 오류"

    for model in GEMINI_MODELS:
        for attempt in range(MAX_RETRIES_PER_MODEL + 1):
            try:
                response = requests.post(
                    f"{GEMINI_BASE_URL}{model}:generateContent",
                    headers={
                        "x-goog-api-key": GEMINI_API_KEY,
                        "Content-Type": "application/json",
                    },
                    json=payload,
                    timeout=60,
                )

                if not response.ok:
                    last_error = f"HTTP {response.status_code}"
                    logger.warning(
                        "Gemini 오류: model=%s status=%s body=%s",
                        model, response.status_code, response.text[:800],
                    )

                    if response.status_code in (400, 401, 403):
                        return (
                            "AI 설정에 문제가 생겼어. 😢\n"
                            "관리자가 Gemini API 키와 Render 로그를 확인해 줘."
                        )

                    if response.status_code in RETRY_STATUS_CODES:
                        if attempt < MAX_RETRIES_PER_MODEL:
                            time.sleep(1.5 * (attempt + 1))
                            continue
                    break

                data = response.json()
                candidates = data.get("candidates", [])
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    answer = "".join(
                        part.get("text", "")
                        for part in parts
                        if isinstance(part, dict)
                    ).strip()
                    if answer:
                        return answer[:MAX_LINE_REPLY_LENGTH]

                last_error = "응답에 텍스트가 없음"
                logger.warning("Gemini 빈 응답: model=%s", model)
                break

            except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
                last_error = str(exc)
                logger.exception("Gemini 요청 처리 오류: %s", model)
                if attempt < MAX_RETRIES_PER_MODEL:
                    time.sleep(1.5 * (attempt + 1))

    logger.error("모든 Gemini 모델 실패: %s", last_error)
    return (
        "지금은 AI 답변을 가져오지 못했어. 😢\n"
        "잠시 후 다시 시도해 줘. 같은 오류가 반복되면 관리자에게 알려 줘."
    )


def handle_quick_command(question):
    normalized = question.strip()
    lower = normalized.lower()

    if lower in ("도움말", "help", "명령어", "기능"):
        return (
            "사용 가능한 명령어\n"
            "• !명령어 — 기존 명령어 목록\n"
            "• ! 오늘의질문 — 대화 주제 추천\n"
            "• ! 밸런스게임 — 밸런스 질문\n"
            "• ! 순서 이름 이름 — 참여 순서 섞기\n"
            "• ! 규칙 주제 — 규칙 검색\n"
            "• ! 용어집 또는 ! 용어집 단어 — 용어 확인\n"
            "• !aimodels — 사용 가능한 Gemini 모델\n"
            "그 외 질문은 ! 질문 형식으로 보내 줘."
        )

    if lower in ("오늘의질문", "오늘의 질문", "질문추천", "대화주제", "대화 주제"):
        return "오늘의 질문 💬\n" + random.choice(TODAY_QUESTIONS)

    if lower in ("밸런스게임", "밸런스 게임", "밸런스"):
        return "밸런스게임 🎲\n" + random.choice(BALANCE_QUESTIONS)

    if lower.startswith(("순서", "랜덤순서", "랜덤 순서")):
        parts = normalized.split()
        names = parts[1:]
        if len(names) < 2:
            return "이름을 2명 이상 적어 줘.\n예시: ! 순서 치호 멍멍 수박"
        if len(names) > 50:
            return "한 번에 섞을 수 있는 이름은 최대 50명이야."
        random.shuffle(names)
        return "랜덤 순서 🎲\n" + "\n".join(
            f"{i}. {name}" for i, name in enumerate(names, 1)
        )

    if lower == "규칙" or lower.startswith(("규칙 ", "규칙검색 ")):
        parts = normalized.split(maxsplit=1)
        topic = parts[1].strip() if len(parts) > 1 else ""
        if not topic:
            return "찾을 규칙을 적어 줘.\n예시: ! 규칙 갠라"
        for key in sorted(RULES_FAQ, key=len, reverse=True):
            if key.lower() in topic.lower() or topic.lower() in key.lower():
                return RULES_FAQ[key]
        if "검사" in topic or "검사지" in topic:
            return RULES_FAQ["섹벙"]
        if "초대" in topic or "여초" in topic or "72시간" in topic:
            return RULES_FAQ["미클"]
        if "앨범" in topic or "캡처" in topic:
            return RULES_FAQ["사진"]
        return "빠른 검색에서 찾지 못했어. ! 뒤에 질문을 적거나 관리자에게 확인해 줘."

    if lower == "용어집" or lower.startswith(("용어집 ", "용어 ")):
        parts = normalized.split(maxsplit=1)
        if len(parts) == 1:
            return "주요 용어: " + ", ".join(GLOSSARY.keys()) + "\n예시: ! 용어집 미클"
        term = parts[1].strip()
        matches = [
            (key, value) for key, value in GLOSSARY.items()
            if term.lower() in key.lower() or key.lower() in term.lower()
        ]
        if matches:
            return "\n".join(f"{key}: {value}" for key, value in matches[:5])
        return "그 용어는 용어집에서 찾지 못했어."

    return None


@app.route("/", methods=["GET"])
def home():
    return "Secret Pantry AI is running!", 200


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "line_secret_configured": bool(LINE_CHANNEL_SECRET),
        "line_token_configured": bool(LINE_CHANNEL_ACCESS_TOKEN),
        "gemini_key_configured": bool(GEMINI_API_KEY),
    }), 200


@app.route("/callback", methods=["POST"])
def callback():
    body = request.get_data()
    signature = request.headers.get("X-Line-Signature", "")

    if not verify_line_signature(body, signature):
        logger.warning("LINE 서명 검증 실패")
        abort(400)

    try:
        payload = request.get_json(force=True)
    except Exception:
        logger.exception("LINE 웹훅 JSON 파싱 실패")
        abort(400)

    for event in payload.get("events", []):
        try:
            if event.get("type") != "message":
                continue

            message = event.get("message", {})
            if message.get("type") != "text":
                continue

            text = message.get("text", "").strip()
            reply_token = event.get("replyToken")
            source = event.get("source", {})
            user_id = source.get("userId", "")
            group_id = source.get("groupId", "")
            source_type = source.get("type", "")

            # 치호의 기존 닉네임 조회 기능 유지
            user_name = "Unknown"
            if user_id and LINE_CHANNEL_ACCESS_TOKEN:
                headers = {
                    "Authorization": f"Bearer {LINE_CHANNEL_ACCESS_TOKEN}"
                }
                try:
                    if source_type == "group" and group_id:
                        profile_url = (
                            f"https://api.line.me/v2/bot/group/"
                            f"{group_id}/member/{user_id}"
                        )
                    elif source_type == "room":
                        room_id = source.get("roomId", "")
                        profile_url = (
                            f"https://api.line.me/v2/bot/room/"
                            f"{room_id}/member/{user_id}"
                        )
                    else:
                        profile_url = f"https://api.line.me/v2/bot/profile/{user_id}"

                    profile_response = requests.get(
                        profile_url, headers=headers, timeout=10
                    )
                    if profile_response.ok:
                        user_name = profile_response.json().get(
                            "displayName", "Unknown"
                        )
                except requests.RequestException:
                    logger.exception("LINE 프로필 조회 실패")

            # 기존 마딧수 기능
            if user_id:
                if user_id not in user_scores:
                    user_scores[user_id] = {"name": user_name, "count": 0}
                user_scores[user_id]["name"] = user_name
                user_scores[user_id]["count"] += len(
                    text.replace(" ", "").replace("\n", "")
                )

            # 기존 !마딧수 / !마딧수순위
            if text in ("!마딧수", "!마딧수순위"):
                if not user_scores:
                    reply_to_line(reply_token, "📊 집계된 마딧수 데이터가 없습니다.")
                else:
                    ranked = sorted(
                        user_scores.values(),
                        key=lambda item: item["count"],
                        reverse=True,
                    )
                    result = ["📊 [그룹 마딧수 순위]"]
                    for i, item in enumerate(ranked, start=1):
                        result.append(f"{i}. {item['name']} {item['count']:,}")
                    reply_to_line(reply_token, "\n".join(result))
                continue

            # 기존 !마딧수리셋
            if text == "!마딧수리셋":
                user_scores.clear()
                reply_to_line(reply_token, "🧹 모든 마딧수 집계가 리셋되었습니다.")
                continue

            # 기존 고정 명령어 우선 처리
            if text in COMMANDS:
                reply_to_line(reply_token, COMMANDS[text])
                continue

            # AI 모델 목록 명령어
            if text.lower() == "!aimodels":
                success, result = get_gemini_models()
                if not success:
                    logger.warning("모델 목록 조회 실패: %s", result)
                reply_to_line(reply_token, result)
                continue

            # !로 시작하지 않는 일반 대화에는 AI가 답하지 않음
            if not text.startswith("!"):
                continue

            # !ai 질문 형식과 ! 질문 형식 모두 지원
            if text.startswith("!ai "):
                question = text[4:].strip()
            else:
                question = text[1:].strip()

            if not question:
                reply_to_line(reply_token, "질문을 같이 적어 줘!\n예시: ! 안녕")
                continue

            quick_answer = handle_quick_command(question)
            if quick_answer is not None:
                reply_to_line(reply_token, quick_answer)
                continue

            if len(question) > MAX_QUESTION_LENGTH:
                reply_to_line(
                    reply_token,
                    f"질문이 너무 길어. {MAX_QUESTION_LENGTH}자 이내로 보내 줘."
                )
                continue

            logger.info("AI 질문 수신: chars=%s", len(question))
            answer = ask_gemini(question)
            reply_to_line(reply_token, answer)

        except Exception:
            # 한 이벤트에서 오류가 나더라도 서버 전체가 중단되지 않게 처리
            logger.exception("웹훅 이벤트 처리 중 예외 발생")
            try:
                reply_token = event.get("replyToken")
                reply_to_line(
                    reply_token,
                    "메시지 처리 중 오류가 발생했어. 잠시 후 다시 시도해 줏."
                )
            except Exception:
                logger.exception("오류 안내 메시지 전송 실패")

    return "OK", 200
