import os
import json
import requests # 我们将直接使用 requests 库来调用 Kimi API
from flask import Flask, request
from datetime import datetime
from supabase import create_client, Client

# --- 初始化 Flask App ---
app = Flask(__name__)

# --- 从环境变量中安全地获取密钥 ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
# 【重要变化】我们将使用新的密钥名
KIMI_API_KEY = os.environ.get("KIMI_API_KEY") 

# --- 初始化 Supabase 服务客户端 ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 核心功能函数 ---
def send_telegram_message(chat_id, text):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    requests.post(api_url, json=payload)

def analyze_task_with_ai(text):
    """【重要变化】使用 Kimi Chat API 分析文本"""
    api_url = "https://api.moonshot.cn/v1/chat/completions"
    
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KIMI_API_KEY}"
    }

    # 这是给 Kimi 的指令，针对中文做了优化
    system_prompt = (
        "你是一个简洁高效的任务分析助手。"
        "请从用户发送的文本中，严格提取'task'（核心任务内容）和'deadline'（截止日期和时间）这两个字段。"
        "如果文本中没有明确的日期或时间，请将deadline的值设为null。"
        "参考今天的日期是：" + datetime.now().strftime('%Y-%m-%d') +
        "请必须以一个纯粹的、不包含任何其他解释性文字的JSON对象格式返回结果。例如：{\"task\": \"和团队开会\", \"deadline\": \"2025-08-12 15:00:00\"}"
    )

    payload = {
        "model": "moonshot-v1-8k",  # Kimi 的主要模型
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "temperature": 0.3,
        "response_format": {"type": "json_object"} # 强制要求返回JSON
    }

    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload))
        response.raise_for_status() # 如果请求失败 (例如4xx, 5xx错误)，会抛出异常
        
        # 解析 Kimi 返回的JSON字符串
        ai_response_data = response.json()
        result = json.loads(ai_response_data['choices'][0]['message']['content'])
        
        print(f"--- Kimi Raw Response ---: {result}") # 打印Kimi的回复，方便调试
        return result
        
    except requests.exceptions.HTTPError as http_err:
        print(f"Kimi API 请求失败 (HTTP Error): {http_err}")
        print(f"Response body: {response.text}")
        return None
    except Exception as e:
        print(f"AI分析或解析失败: {e}")
        return None

# --- Webhook主入口 (这部分代码完全不变) ---
@app.route('/', methods=['POST'])
def handle_telegram_webhook():
    # ... 这部分的所有代码都和之前完全一样，无需改动 ...
    # 为了简洁，这里省略，请确保你粘贴的是上面完整的代码块
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
                insert_data = {
                    'task_description': ai_result.get('task'),
                    'deadline': ai_result.get('deadline'),
                    'telegram_user_id': str(chat_id),
                    'status': 'pending'
                }
                # Supabase 的 v2 版本返回的是一个元组 (data, error)
                # 我们在新代码里改为更稳妥的写法
                result = supabase.table('todos').insert(insert_data).execute()
                # 检查 result.data 是否有内容来判断成功
                if result.data:
                     task_name = ai_result.get('task')
                     deadline = ai_result.get('deadline', '未指定时间')
                     reply_text = f"好的！新的待办已记录：\n\n📝 任务: {task_name}\n⏰ 时间: {deadline}"
                     send_telegram_message(chat_id, reply_text)
                else:
                    print(f"数据库保存失败: {result.error}")
                    send_telegram_message(chat_id, "哎呀，TDog的记事本好像出了点问题，没存上。")
            else:
                send_telegram_message(chat_id, "呜... TDog没太明白你的意思，可以换个说法吗？")
    except Exception as e:
        print(f"主程序出错: {e}")
    return 'OK', 200

# 供 Render 启动服务
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
