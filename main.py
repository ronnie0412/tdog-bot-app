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
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
KIMI_API_KEY = os.environ.get("KIMI_API_KEY")

# --- 核心工具函数 (这部分完全不变) ---
def send_telegram_message(chat_id, text, parse_mode=""):
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    requests.post(api_url, json=payload)

def db_insert(table_name, data_to_insert):
    insert_url = f"{SUPABASE_URL}/rest/v1/{table_name}"
    headers = {
        "apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json", "Prefer": "return=representation"
    }
    response = requests.post(insert_url, headers=headers, data=json.dumps(data_to_insert), timeout=15)
    response.raise_for_status()
    return response.json()

def db_select_by_id(table_name, record_id, user_id):
    select_url = f"{SUPABASE_URL}/rest/v1/{table_name}?id=eq.{record_id}&telegram_user_id=eq.{user_id}&limit=1"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    response = requests.get(select_url, headers=headers, timeout=15)
    response.raise_for_status()
    records = response.json()
    return records[0] if records else None

def db_delete_by_id(table_name, record_id):
    delete_url = f"{SUPABASE_URL}/rest/v1/{table_name}?id=eq.{record_id}"
    headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    response = requests.delete(delete_url, headers=headers, timeout=15)
    response.raise_for_status()

def analyze_task_with_ai(text_to_analyze, context_info={}):
    api_url = "https://api.moonshot.cn/v1/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {KIMI_API_KEY}"}
    
    prompt_context = "你是一个强大的任务分析助手。"
    if context_info.get('participants'):
        prompt_context += f" 当前已知的对话参与人有：{', '.join(context_info['participants'])}。"
    
    system_prompt = (
        f"{prompt_context} 请从用户发送的文本中，严格提取'task_description'（任务的核心内容描述）、'deadline'（截止日期和时间）这两个字段。"
        "如果文本中还提到了其他新的人员或实体作为参与方，请将它们提取到'new_participants'数组中。"
        "在判断'new_participants'时，请结合会议、讨论等语境，大胆地将在场的人名或实体识别出来。"
        "如果文本中没有明确的日期或时间，请将deadline的值设为null。"
        "参考今天的日期是：" + datetime.now().strftime('%Y-%m-%d') +
        "请必须以一个纯粹的、不包含任何其他解释性文字的JSON对象格式返回结果。"
    )
    
    payload = {
        "model": "moonshot-v1-8k",
        "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": text_to_analyze}],
        "temperature": 0.3
    }
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=25)
        response.raise_for_status()
        ai_response_data = response.json()
        if 'choices' in ai_response_data and ai_response_data['choices']:
            return json.loads(ai_response_data['choices'][0]['message']['content'])
        return None
    except Exception as e:
        print(f"!!! AI 分析出错: {e}")
        return None

# --- ↓↓↓【【【 这里是彻底重写的核心逻辑 】】】↓↓↓ ---

def get_user_display_name(user_object):
    """从Telegram的用户对象中获取一个可读的显示名"""
    if not user_object:
        return "未知用户"
    return user_object.get('username') or user_object.get('first_name', '') or f"ID:{user_object['id']}"

def handle_new_task(msg):
    """处理新的待办任务，已重写以正确处理转发和私聊场景"""
    chat_id = msg['chat']['id']
    
    # --- 身份识别 ---
    is_forward = 'forward_from' in msg or 'forward_from_chat' in msg
    
    if is_forward:
        # 如果是转发消息
        original_sender_info = msg.get('forward_from') # 从个人转发
        if not original_sender_info: # 从频道或匿名转发
             original_sender_info = msg.get('forward_from_chat')
             
        author = get_user_display_name(original_sender_info)
        # 转发者 (你) 是当然的参与人
        forwarder_info = msg['from']
        participants = [get_user_display_name(forwarder_info)]
    else:
        # 如果是普通消息
        author = get_user_display_name(msg['from'])
        participants = [] # 初始参与人为空，等待AI或场景判断
        
        # 在非转发的私聊中，可以把对方也视为潜在参与人，但为了逻辑统一，让AI判断
        if msg['chat']['type'] == 'private':
            # 可以把自己的名字加入上下文，帮助AI判断"我们"
            my_name = get_user_display_name(msg['from'])
            # 这里暂时不直接加入participants，而是作为上下文给AI
            # context_info['participants'] = [my_name]
            pass

    # --- 场景判断 ---
    is_group_chat = msg['chat']['type'] in ['group', 'supergroup']
    if is_group_chat:
        # 提取@的人
        mentioned_users = [
            get_user_display_name(entity.get('user'))
            for entity in msg.get('entities', []) if entity.get('type') == 'text_mention' and entity.get('user')
        ]
        text_mentions = [
             msg['text'][entity['offset']:entity['offset']+entity['length']]
             for entity in msg.get('entities', []) if entity.get('type') == 'mention'
        ]
        participants.extend(mentioned_users)
        participants.extend(text_mentions)
        # 如果是群聊且没有@人，且不是转发，则默认参与方是群组
        if not participants and not is_forward:
            participants.append(msg['chat'].get('title', '未知群组'))

    # --- AI分析 & 数据库操作 ---
    send_telegram_message(chat_id, "TDog正在思考中...")
    
    context_for_ai = {'participants': list(set(participants))} # 去重后传给AI
    ai_result = analyze_task_with_ai(msg['text'], context_for_ai)

    if ai_result and ai_result.get('task_description'):
        try:
            # 合并AI提取的新参与人
            new_participants = ai_result.get('new_participants', [])
            if isinstance(new_participants, list):
                participants.extend(new_participants)

            # 最终去重，并拼接成字符串
            final_participants_str = ", ".join(list(set(participants)))

            insert_data = {
                'task_description': ai_result.get('task_description'),
                'deadline': ai_result.get('deadline'),
                'author': author,
                'participants': final_participants_str,
                'telegram_user_id': msg['from']['id'], # 任务归属者是你
                'status': 'pending'
            }
            db_insert('todos', insert_data)
            send_telegram_message(chat_id, f"好的！新的待办已记录:\n\n📝 {ai_result.get('task_description')}")
        except Exception as e:
            send_telegram_message(chat_id, f"哎呀，保存任务时出错了: {e}")
    else:
        send_telegram_message(chat_id, "呜... TDog没太明白你的意思，可以换个说法吗？")


# --- 命令处理函数 (这部分不变) ---
def handle_list_tasks(msg):
    # ... (代码和之前完全一样) ...
    chat_id = msg['chat']['id']
    user_id = msg['from']['id']
    
    try:
        select_url = f"{SUPABASE_URL}/rest/v1/todos?telegram_user_id=eq.{user_id}&select=*"
        headers = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
        response = requests.get(select_url, headers=headers, timeout=15)
        response.raise_for_status()
        tasks = response.json()

        if not tasks:
            send_telegram_message(chat_id, "太棒了！你没有需要处理的待办事项。")
            return

        message_text = "这是你所有的待办事项：\n" + ("-"*20) + "\n\n"
        for task in tasks:
            message_text += f"`[ID: {task['id']}]`\n"
            message_text += f"📝 *任务*: {task.get('task_description', 'N/A')}\n"
            if task.get('author'): message_text += f"👤 *发起人*: {task['author']}\n"
            if task.get('participants'): message_text += f"👥 *参与方*: {task['participants']}\n"
            if task.get('deadline'): message_text += f"⏰ *截止*: {task['deadline']}\n"
            message_text += "\n"
        
        send_telegram_message(chat_id, message_text, parse_mode="Markdown")
    except Exception as e:
        send_telegram_message(chat_id, f"查询待办列表时出错了: {e}")

def handle_archive_task(msg, command, new_status):
    # ... (代码和之前完全一样) ...
    chat_id = msg['chat']['id']
    user_id = msg['from']['id']
    
    try:
        parts = msg['text'].split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_telegram_message(chat_id, f"请使用正确的格式: `/{command} <任务ID>`", parse_mode="Markdown")
            return
        
        task_id = int(parts[1])
        
        task_to_archive = db_select_by_id('todos', task_id, user_id)
        if not task_to_archive:
            send_telegram_message(chat_id, f"找不到ID为 {task_id} 的待办事项，或者你没有权限操作它。")
            return
        
        task_to_archive['status'] = new_status
        db_insert('archived_todos', task_to_archive)
        
        db_delete_by_id('todos', task_id)
        
        send_telegram_message(chat_id, f"好的！任务 `[ID: {task_id}]` 已标记为 *{new_status}* 并归档。", parse_mode="Markdown")

    except Exception as e:
        send_telegram_message(chat_id, f"处理归档任务时出错了: {e}")

# --- Webhook主入口 (这部分不变) ---
@app.route('/', methods=['POST'])
def handle_telegram_webhook():
    try:
        data = request.get_json()
        if 'message' in data:
            message = data['message']
            text = message.get('text', '')

            if text.startswith('/list'):
                handle_list_tasks(message)
            elif text.startswith('/done'):
                handle_archive_task(message, 'done', 'done')
            elif text.startswith('/cancel'):
                handle_archive_task(message, 'cancel', 'cancelled')
            elif text: # 确保有文本内容才创建任务
                handle_new_task(message)
                
    except Exception as e:
        print(f"!!! [严重错误] 主程序出现未知异常: {e}")
        
    return 'OK', 200

# 供 Render 启动服务
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
