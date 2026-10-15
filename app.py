import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage

app = Flask(__name__)

LINE_CHANNEL_SECRET = os.environ.get('LINE_CHANNEL_SECRET', '1e89464AED1426318780c1fe8aa994c1')
LINE_CHANNEL_ACCESS_TOKEN = os.environ.get('LINE_CHANNEL_ACCESS_TOKEN', '5KkJkHKGpBbSFoviKmXa01CPXQ2mT6wn9LwyH36M7bxAzvMaHFYn34guq1SBax3xOa2ICddxqkUKVZdv1xIWTPgz08Yd7Jgr09vTVNhQ05QMuciMvzI8Ge7rE0RF5/HNCkFwsJICzgdB04t89/1O/w1cDnyllFU=')

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

user_scores = {}


@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature', '')
    body = request.get_data(as_text=True)
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK', 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()
    
    try:
        if event.source.type == 'group':
            profile = line_bot_api.get_group_member_profile(event.source.group_id, user_id)
        else:
            profile = line_bot_api.get_profile(user_id)
        user_name = profile.display_name
    except Exception:
        user_name = "Unknown"

    if msg in ['!마딧수순위', '!마딧수']:
        if not user_scores:
            reply = "📊 집계된 마딧수 데이터가 없습니다."
        else:
            sorted_scores = sorted(user_scores.values(), key=lambda x: x['count'], reverse=True)
            rank_text = "📊 [그룹 마딧수 순위]\n"
            for i, score_info in enumerate(sorted_scores, start=1):
                rank_text += f"{i}. {score_info['name']} {score_info['count']:,}\n"
            reply = rank_text.strip()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    elif msg == '!마딧수리셋':
        user_scores.clear()
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text="🧹 모든 마딧수 집계가 리셋되었습니다."))
        return

    elif msg in COMMANDS:
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=COMMANDS[msg]))

    char_count = len(msg.replace(" ", "").replace("\n", ""))
    
    if user_id not in user_scores:
        user_scores[user_id] = {"name": user_name, "count": 0}
    
    user_scores[user_id]["name"] = user_name
    user_scores[user_id]["count"] += char_count

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
