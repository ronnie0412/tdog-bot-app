import os
import json
import requests
from flask import Flask, request
from datetime import datetime  # <--- 我已经在这里加上了空格，修复了语法错误
from supabase import create_client, Client

# --- 初始化 Flask App ---
app = Flask(__name__)

# --- 从环境变量中安全地获取密钥 ---
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
KIMI_API_KEY = os.environ.get("KIMI_API_KEY") 

# --- 初始化 Supabase 服务客户端 ---
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 核心功能函数 ---
def send_telegram_message(chat_id, text):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    requests.post(api_url, json=payload)

def analyze_task_with_ai(text):
    """使用 Kimi Chat API 分析文本，并添加了详细的调试日志"""
    print("--- [面包屑 1] 进入 AI 分析函数 ---")
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
        print("--- [面包屑 2] 准备发起对 Kimi 的网络请求 ---")
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=25) # 设置25秒超时
        print("--- [面包屑 3] 对 Kimi 的网络请求已完成 ---")
        
        response.raise_for_status()
        
        ai_response_data = response.json()
        print("--- [面包屑 4] 成功获取 Kimi 的 JSON 数据 ---")
        
        result = json.loads(ai_response_data['choices'][0]['message']['content'])
        print(f"--- [面包屑 5] Kimi 的最终分析结果: {result} ---")
        
        return result
        
    except requests.exceptions.Timeout:
        print("!!! [严重错误] 连接 Kimi API 超时！请检查网络或 Kimi 服务器状态。")
        return None
    except requests.exceptions.HTTPError as http_err:
        print(f"!!! [严重错误] Kimi API HTTP 错误: {http_err}")
        print(f"!!! 错误详情: {response.text}")
        return None
    except Exception as e:
        print(f"!!! [严重错误] AI 分析或解析过程中出现未知错误: {e}")
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
                print("--- [面包屑 6] 准备将任务存入 Supabase ---")
                insert_data = {
                    'task_description': ai_result.get('task'),
                    'deadline': ai_result.get('deadline'),
                    'telegram_user_id': str(chat_id),
                    'status': 'pending'
                }
                result = supabase.table('todos').insert(insert_data).execute()
                
                if result.data:
                     print("--- [面包屑 7] 任务成功存入 Supabase ---")
                     task_name = ai_result.get('task')
                     deadline = ai_result.get('deadline', '未指定时间')
                     reply_text = f"好的！新的待办已记录：\n\n📝 任务: {task_name}\n⏰ 时间: {deadline}"
                     send_telegram_message(chat_id, reply_text)
                else:
                    print(f"!!! [严重错误] 数据库保存失败: {result.error}")
                    send_telegram_message(chat_id, "哎呀，TDog的记事本好像出了点问题，没存上。")
            else:
                # 如果ai_result是None或者里面没有'task'
                print("--- AI 分析返回结果无效，无法继续 ---
