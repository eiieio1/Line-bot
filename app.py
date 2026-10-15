
import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

# 비밀값은 Render 환경변수에서만 가져옵니다.
LINE_CHANNEL_SECRET = os.environ.get("LINE_CHANNEL_SECRET")
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

if not LINE_CHANNEL_SECRET or not LINE_CHANNEL_ACCESS_TOKEN:
    raise RuntimeError("LINE 환경변수를 Render에서 확인해 주세요.")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_scores = {}

COMMANDS = {
    "야옹1": "야옹! 왜 불러?",
    "야옹2": "꺼지게나아",
    "야옹3": "진짜 개빡치네",
    "!명령어": "사용 가능: 야옹1, 야옹2, 야옹3, !마딧수, !마딧수순위, !마딧수리셋"
}


def ask_gemini(question):
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY가 설정되지 않았습니다.")

    url = (
        "https://generativelanguage.googleapis.com/"
        "v1beta/models/gemini-3.8-flash:generateContent"
    )

    response = requests.post(
        url,
        headers={
            "Content-Type": "application/json",
            "x-goog-api-key": GEMINI_API_KEY,
        },
        json={
            "contents": [
                {
                    "role": "user",
                    "parts": [{"text": question}]
                }
            ]
        },
        timeout=25,
    )

    response.raise_for_status()
    data = response.json()

    candidates = data.get("candidates", [])
    if not candidates:
        return "😿 이번에는 답변을 만들지 못했어. 다시 물어봐 줘!"

    parts = candidates[0].get("content", {}).get("parts", [])
    answer = "".join(
        part.get("text", "")
        for part in parts
        if "text" in part
    ).strip()

    return answer[:4500] or "😿 답변을 만들지 못했어!"


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK", 200


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    try:
        if event.source.type == "group":
            profile = line_bot_api.get_group_member_profile(
                event.source.group_id, user_id
            )
        else:
            profile = line_bot_api.get_profile(user_id)

        user_name = profile.display_name
    except Exception:
        user_name = "Unknown"

    # 별표(*)로 시작하는 메시지는 AI가 답변합니다.
    if msg.startswith("*"):
        question = msg[1:].strip()

        if not question:
            reply = "💬 별표 뒤에 질문을 입력해 줘!\n예: *안녕"
        else:
            try:
                reply = ask_gemini(question)
            except Exception:
                app.logger.exception("Gemini API request failed")
                reply = (
                    "😿 AI 연결에 문제가 생겼어. "
                    "잠시 후 다시 시도해 줘!"
                )

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return

    # 기존 마딧수 조회 및 순위
    if msg in ["!마딧수순위", "!마딧수"]:
        if not user_scores:
            reply = "📊 집계된 마딧수 데이터가 없습니다."
        else:
            sorted_scores = sorted(
                user_scores.values(),
                key=lambda x: x["count"],
                reverse=True
            )

            rank_text = "📊 [그룹 마딧수 순위]\n"
            for i, score_info in enumerate(sorted_scores, start=1):
                rank_text += (
                    f"{i}. {score_info['name']} "
                    f"{score_info['count']:,}\n"
                )

            reply = rank_text.strip()

        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=reply)
        )
        return

    # 기존 마딧수 초기화
    if msg == "!마딧수리셋":
        user_scores.clear()
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(
                text="🧹 모든 마딧수 집계가 리셋되었습니다."
            )
        )
        return

    # 기존 고정 명령어
    if msg in COMMANDS:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=COMMANDS[msg])
        )

    # 기존 마딧수 집계 방식 유지
    char_count = len(msg.replace(" ", "").replace("\n", ""))

    if user_id not in user_scores:
        user_scores[user_id] = {
            "name": user_name,
            "count": 0
        }

    user_scores[user_id]["name"] = user_name
    user_scores[user_id]["count"] += char_count


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
