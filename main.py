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
SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_KEY") # 具备读写权限的 service_role key
KIMI_API_KEY = os.environ.get("KIMI_API_KEY")

# --- 核心功能函数 ---

def send_telegram_message(chat_id, text, parse_mode=""):
    """向指定的Telegram聊天发送消息，可选择是否使用Markdown"""
    api_url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {'chat_id': chat_id, 'text': text}
    if parse_mode:
        payload['parse_mode'] = parse_mode
    requests.post(api_url, json=payload)

def db_insert(table_name, data_to_insert):
    """向指定的Supabase表格插入数据"""
    insert_url = f"{SUPABASE_URL}/rest/v1/{table_name}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation" # 请求返回插入的数据，用于确认
    }
    response = requests.post(insert_url, headers=headers, data=json.dumps(data_to_insert), timeout=15)
    response.raise_for_status() # 如果失败会抛出异常
    return response.json()

def db_select_by_id(table_name, record_id, user_id):
    """根据ID从指定表格查询单条记录，并校验用户权限"""
    select_url = f"{SUPABASE_URL}/rest/v1/{table_name}?id=eq.{record_id}&telegram_user_id=eq.{user_id}&limit=1"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    response = requests.get(select_url, headers=headers, timeout=15)
    response.raise_for_status()
    records = response.json()
    return records[0] if records else None

def db_delete_by_id(table_name, record_id):
    """根据ID从指定表格删除记录"""
    delete_url = f"{SUPABASE_URL}/rest/v1/{table_name}?id=eq.{record_id}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}"
    }
    response = requests.delete(delete_url, headers=headers, timeout=15)
    response.raise_for_status()


def analyze_task_with_ai(text_to_analyze, context_info={}):
    """使用 Kimi Chat API 分析文本"""
    # ... (这整个函数和之前完全一样，无需改动) ...
    # 为了简洁，这里省略，请确保你粘贴的是下面完整的代码块
    api_url = "https://api.moonshot.cn/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {KIMI_API_KEY}"
    }
    # 构建更丰富的上下文指令
    prompt_context = "你是一个强大的任务分析助手。"
    if context_info.get('participants'):
        prompt_context += f" 当前对话的参与人已有：{', '.join(context_info['participants'])}。"
    
    system_prompt = (
        f"{prompt_context} 请从用户发送的文本中，严格提取'task_description'（任务的核心内容描述）和'deadline'（截止日期和时间）这两个字段。"
        "如果文本中还提到了其他新的人员，请一并提取到'new_participants'数组中。"
        "如果文本中没有明确的日期或时间，请将deadline的值设为null。"
        "参考今天的日期是：" + datetime.now().strftime('%Y-%m-%d') +
        "请必须以一个纯粹的、不包含任何其他解释性文字的JSON对象格式返回结果。"
    )
    
    payload = {
        "model": "moonshot-v1-8k",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text_to_analyze}
        ],
        "temperature": 0.3
    }
    try:
        response = requests.post(api_url, headers=headers, data=json.dumps(payload), timeout=25)
        response.raise_for_status()
        return response.json()
    except Exception:
        return None


def handle_new_task(msg):
    """处理新的待办任务"""
    chat_id = msg['chat']['id']
    user_id = msg['from']['id']
    author = msg['from'].get('username') or msg['from'].get('first_name', '未知用户')
    
    # 确定初始参与人和上下文
    participants = []
    context_info = {}
    is_group_chat = msg['chat']['type'] in ['group', 'supergroup']
    
    if is_group_chat: # 群聊
        mentioned_users = [
            entity['user'].get('username') or entity['user'].get('first_name')
            for entity in msg.get('entities', []) if entity['type'] == 'text_mention'
        ]
        text_mentions = [
             msg['text'][entity['offset']:entity['offset']+entity['length']]
             for entity in msg.get('entities', []) if entity['type'] == 'mention'
        ]
        participants.extend(mentioned_users)
        participants.extend(text_mentions)
        if not participants: # 如果没有@人，则参与方为群组
            participants.append(msg['chat'].get('title', '未知群组'))
    else: # 私聊
        # 假设私聊对象就是chat_id，这在私聊中是正确的
        # 获取对方名字比较复杂，简单处理为“私聊对象”
        # 更好的做法需要机器人能存储用户信息，暂时简化
        pass
    
    context_info['participants'] = participants
    
    send_telegram_message(chat_id, "TDog正在思考中...")
    ai_response = analyze_task_with_ai(msg['text'], context_info)

    if ai_response and ai_response.get('choices'):
        try:
            ai_result = json.loads(ai_response['choices'][0]['message']['content'])
            task_description = ai_result.get('task_description')
            if not task_description:
                raise ValueError("AI未能提取有效的任务描述")

            # 合并AI提取的新参与人
            new_participants = ai_result.get('new_participants', [])
            if isinstance(new_participants, list):
                participants.extend(new_participants)

            insert_data = {
                'task_description': task_description,
                'deadline': ai_result.get('deadline'),
                'author': author,
                'participants': ", ".join(participants),
                'telegram_user_id': user_id,
                'status': 'pending'
            }
            db_insert('todos', insert_data)
            send_telegram_message(chat_id, f"好的！新的待办已记录:\n\n📝 {task_description}")
        except Exception as e:
            send_telegram_message(chat_id, f"哎呀，处理或保存任务时出错了: {e}")
    else:
        send_telegram_message(chat_id, "呜... TDog没太明白你的意思，可以换个说法吗？")

def handle_list_tasks(msg):
    """处理 /list 命令，显示待办列表"""
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
    """处理 /done 和 /cancel 命令"""
    chat_id = msg['chat']['id']
    user_id = msg['from']['id']
    
    try:
        parts = msg['text'].split()
        if len(parts) < 2 or not parts[1].isdigit():
            send_telegram_message(chat_id, f"请使用正确的格式: `/{command} <任务ID>`", parse_mode="Markdown")
            return
        
        task_id = int(parts[1])
        
        # 1. 读取任务
        task_to_archive = db_select_by_id('todos', task_id, user_id)
        if not task_to_archive:
            send_telegram_message(chat_id, f"找不到ID为 {task_id} 的待办事项，或者你没有权限操作它。")
            return
        
        # 2. 更新状态并插入到归档表
        task_to_archive['status'] = new_status
        db_insert('archived_todos', task_to_archive)
        
        # 3. 从原表删除
        db_delete_by_id('todos', task_id)
        
        send_telegram_message(chat_id, f"好的！任务 `[ID: {task_id}]` 已标记为 *{new_status}* 并归档。", parse_mode="Markdown")

    except Exception as e:
        send_telegram_message(chat_id, f"处理归档任务时出错了: {e}")


# --- Webhook主入口 ---
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
            else:
                # 默认行为是创建新任务
                handle_new_task(message)
                
    except Exception as e:
        print(f"!!! [严重错误] 主程序出现未知异常: {e}")
        
    return 'OK', 200

# 供 Render 启动服务
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 10000)))
