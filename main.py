import os
import json
import openai
from flask import Flask, request
from datetime import datetime
from supabase import create_client, Client

# --- 初始化 Flask App ---
app = Flask(__name__)

# --- 从环境变量中安全地获取密钥 ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")

# --- 初始化服务客户端 ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
openai.api_key = OPENAI_API_KEY

# --- 核心功能函数 ---
def send_telegram_message(chat_id, text):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    import requests
    requests.post(api_url, json=payload)

def analyze_task_with_ai(text):
    try:
        system_prompt = f"你是一个任务分析助手。请从用户发送的文本中提取'task'(核心任务内容)和'deadline'(截止日期和时间)。如果没有明确日期，deadline设为null。请将今天的日期作为参考：{datetime.now().strftime('%Y-%m-%d')}。请必须以JSON格式返回结果。例如: {{\"task\": \"和团队开会\", \"deadline\": \"2025-08-12 15:00:00\"}}"
        response = openai.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"AI分析失败: {e}")
        return None

# --- Webhook主入口 ---
@app.route('/', methods=['POST'])
def handle_telegram_webhook():
    try:
        data = request.get_json()
        if data and 'message' in data and 'text' in data['message']:
            chat_id = data['message']['chat']['id']
            message_text = data['message']['text']
            if message_text.startswith('/'):
                return 'OK', 200

            send_telegram_message(chat_id, "TDog正在思考中...")
            ai_result = analyze_task_with_ai(message_text)
            print(f"--- AI Raw Response ---: {ai_result}")

            if ai_result and ai_result.get('task'):
                insert_data = {
                    'task_description': ai_result.get('task'),
                    'deadline': ai_result.get('deadline'),
                    'telegram_user_id': str(chat_id),
                    'status': 'pending'
                }
                _, error = supabase.table('todos').insert(insert_data).execute()

                if error:
                    print(f"数据库保存失败: {error}")
                    send_telegram_message(chat_id, "哎呀，TDog的记事本好像出了点问题，没存上。")
                else:
                    task_name = ai_result.get('task')
                    deadline = ai_result.get('deadline', '未指定时间')
                    reply_text = f"好的！新的待办已记录：\n\n📝 任务: {task_name}\n⏰ 时间: {deadline}"
                    send_telegram_message(chat_id, reply_text)
            else:
                send_telegram_message(chat_id, "呜... TDog没太明白你的意思，可以换个说法吗？")
    except Exception as e:
        print(f"主程序出错: {e}")
    return 'OK', 200

# 供 Render 启动服务
#if __name__ == "__main__":
#    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
