import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import google.generativeai as genai

app = Flask(__name__)

# 환경변수 설정
line_bot_api = LineBotApi(os.environ.get('LINE_CHANNEL_ACCESS_TOKEN'))
handler = WebhookHandler(os.environ.get('LINE_CHANNEL_SECRET'))

# 구글 Gemini API 설정
genai.configure(api_key=os.environ.get('GEMINI_API_KEY'))

# AI 캐릭터 및 모델 설정
model = genai.GenerativeModel(
    model_name="gemini-1.5-flash",
    system_instruction="너는 라인 그룹방의 AI 봇이야. 친근하고 다정한 반말 말투로 대답해줘."
)

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers.get('X-Line-Signature')
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        pass
    except Exception as e:
        print(f"Error: {e}")
        
    return 'OK', 200

@app.route("/", methods=['GET'])
def home():
    return "Server is running!", 200

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    
    # '*'로 시작할 때만 동작
    if user_message.startswith("*"):
        prompt = user_message[1:].strip()
        
        if prompt:
            try:
                response = model.generate_content(prompt)
                bot_reply = response.text
            except Exception as e:
                bot_reply = "앗, 생각하는 중에 에러가 났어. 다시 물어봐줘!"
            
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=bot_reply)
            )

if __name__ == "__main__":
    app.run()
