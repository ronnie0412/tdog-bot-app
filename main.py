import os
import json
import requests
from flask import Flask, request
from datetime import datetime

# --- 初始化 Flask App ---
app = Flask(__name__)

# --- 从环境变量中安全地获取密钥 ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") # 这是具备读写权限的密钥
KIMI_API_KEY = os.environ.get("KIMI_API_KEY") 

# --- 核心功能函数 ---
def send_telegram_message(chat_id, text):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    requests.post(api_url, json=payload)

def analyze_task_with_ai(text):
    api_url = "https://api.moonshot.cn/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KIMI_API_KEY}"
    }
    system_prompt = (
        "你是一个简洁高效的任务分析助手。"
        "请从用户发送的文本中，严格提取'task'（核心任务内容）和'deadline'（截止日期和时间）这两个字段。"
        "如果文本中没有明确的日期或时间，请将deadline的值设为null。"
        "参考今天的日期是：" + datetime.now().strftime('%Y-%m-%d') +
        "请必须以一个纯粹的、不包含任何其他解释性文字的JSON对象格式返回结果。例如：{\"task\": \"和团队开会\", \"deadline\": \"2025-08-12 15:00:00\"}"
    )
    payload = {
        "model": "moonshot-v1-8k",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"}
    }
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=25)
        response.raise_for_status()
        ai_response_data = response.json()
        result = json.loads(ai_response_data['choices'][0]['message']['content'])
        return result
    except Exception as e:
        print(f"!!! [严重错误] AI 分析过程中出现错误: {e}")
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

            if ai_result and ai_result.get('task'):
                
                # ↓↓↓【【【 这是最终的、决定性的修改 】】】↓↓↓
                # 我们直接构造一个HTTP请求来写入Supabase，不再使用任何库
                try:
                    insert_url = f"{SUPABASE_URL}/rest/v1/todos"
                    
                    headers = {
                        "apikey": SUPABASE_KEY, # 使用具备读写权限的 service_role key
                        "Authorization": f"Bearer {SUPABASE_KEY}",
                        "Content-Type": "application/json",
                        "Prefer": "return=minimal"
                    }
                    
                    deadline_value = ai_result.get('deadline')
                    
                    insert_data = {
                        'task_description': str(ai_result.get('task')),
                        'deadline': str(deadline_value) if deadline_value is not None else "",
                        'telegram_user_id': str(chat_id),
                        'status': 'pending'
                    }

                    response = requests.post(insert_url, headers=headers, data=json.dumps(insert_data), timeout=15)
                    response.raise_for_status() # 如果发生错误 (如 4xx, 5xx), 会抛出异常

                    # 如果代码能走到这里，说明写入100%成功
                    task_name = ai_result.get('task')
                    deadline = ai_result.get('deadline', '未指定时间')
                    reply_text = f"好的！新的待办已记录：\n\n📝 任务: {task_name}\n⏰ 时间: {deadline}"
                    send_telegram_message(chat_id, reply_text)

                except Exception as db_error:
                    print(f"!!! [严重错误] 数据库写入失败: {db_error}")
                    send_telegram_message(chat_id, "哎呀，TDog的记事本好像出了点问题，没存上。")

            else:
                send_telegram_message(chat_id, "呜... TDog没太明白你的意思，可以换个说法吗？")
    except Exception as e:
        print(f"!!! [严重错误] 主程序出现未知异常: {e}")
    return 'OK', 200
    
# 供 Render 启动服务
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
