import os
import time
import requests
import yaml
import re
import json
import base64
from bs4 import BeautifulSoup

# ================= 配置加载 =================
CONFIG_FILE = 'config.yaml'
HISTORY_FILE = 'history.json'


def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, 'r', encoding='utf-8') as f:
                return set(json.load(f))
        except:
            return set()
    return set()


def save_history(history_set):
    with open(HISTORY_FILE, 'w', encoding='utf-8') as f:
        json.dump(list(history_set), f)


config = load_config()
processed_pids = load_history()

HEADERS = {
    # 强制模拟最新的 Chrome，增加兼容性
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Cookie": config['cookies']
}


# ================= 功能函数 =================

def download_image(img_url, save_folder):
    """下载图片 (自动补全NGA链接)"""
    if not img_url: return None

    try:
        # ==========================================
        # 【修复】 专门处理 NGA 的相对路径
        # ==========================================
        # NGA图片通常以 ./mon_ 开头
        if img_url.startswith('./'):
            # 拼接 NGA 的附件服务器基地址
            # ./mon_xxxx -> https://img.nga.178.com/attachments/mon_xxxx
            img_url = "https://img.nga.178.com/attachments/" + img_url[2:]
        elif not img_url.startswith('http'):
            # 如果不是 http 开头，也不是 ./ 开头，可能是其他相对路径，尝试拼接
            img_url = "https://img.nga.178.com/attachments/" + img_url

        filename = img_url.split('/')[-1]
        # 去掉可能存在的 URL 参数 (?xxxx)
        if '?' in filename:
            filename = filename.split('?')[0]

        filepath = os.path.join(save_folder, filename)

        if not os.path.exists(filepath):
            # 打印一下正在下载什么，方便调试
            # print(f"     [下载图片] {filename}")
            resp = requests.get(img_url, headers=HEADERS, timeout=15)
            if resp.status_code == 200:
                with open(filepath, 'wb') as f:
                    f.write(resp.content)
                return filepath
            else:
                print(f"     [图片下载失败] 状态码 {resp.status_code}: {img_url}")
                return None
        return filepath
    except Exception as e:
        print(f"     [图片下载错误] {e}")
        return None


# def push_to_qq(text, images):
#     if not config['qq_bot']['enable']: return
#
#     msg = text
#     for img_path in images:
#         msg += f"\n[CQ:image,file=file:///{os.path.abspath(img_path)}]"
#
#     base_url = config['qq_bot']['base_url']
#
#     # 1. 发送私聊
#     user_id = config['qq_bot'].get('target_qq')
#     if user_id:
#         try:
#             requests.post(f"{base_url}/send_private_msg", json={"user_id": user_id, "message": msg})
#             print(f" >> [私聊发送成功]")
#         except:
#             pass
#
#     # 2. 发送群聊
#     group_id = config['qq_bot'].get('target_group')
#     if group_id:
#         try:
#             requests.post(f"{base_url}/send_group_msg", json={"group_id": group_id, "message": msg})
#             print(f" >> [群聊发送成功]")
#         except:
#             pass

def push_to_group(text, images, group_id):
    """
    推送到指定的 QQ 群 (使用 Base64 解决 Docker 无法读取本地图片的问题)
    """
    if not config['qq_bot']['enable']: return

    # 1. 获取 Token
    token = config['qq_bot'].get('access_token')
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    
    # API 地址
    api_url = f"{config['qq_bot']['api_base']}/send_group_msg"

    # 2. 构造消息内容
    # 先放入文本
    msg_content = text

    # 遍历图片，转为 Base64 拼接
    if images:
        for img_path in images:
            try:
                # 再次检查文件是否存在
                if os.path.exists(img_path):
                    with open(img_path, "rb") as image_file:
                        # 读取图片并转为 base64 字符串
                        b64_str = base64.b64encode(image_file.read()).decode('utf-8')
                        # 使用 base64:// 协议头
                        msg_content += f"\n[CQ:image,file=base64://{b64_str}]"
                else:
                    print(f"     ⚠️ [警告] 图片文件不存在，跳过: {img_path}")
            except Exception as e:
                print(f"     ⚠️ [警告] 图片转码失败: {e}")

    payload = {
        "group_id": group_id,
        "message": msg_content
    }

    try:
        # 3. 发送请求
        print(f"     [调试] 请求URL: {api_url}")  # <--- 打印 URL 看看有没有多斜杠
        resp = requests.post(api_url, json=payload, headers=headers, timeout=20)
        
        # 【新增】打印原始回复内容，看看它到底是个啥
        print(f"     [调试] 原始响应: {resp.text[:1000]}") # 只看前1000个字符

        try:
            resp_data = resp.json()
        except:
            print(f"     ❌ [API错误] 响应不是合法的 JSON")
            return

        # 4. 打印结果
        retcode = resp_data.get('retcode')
        if retcode == 0:
            print(f"     ✅ [发送成功] 群 {group_id} | 消息ID: {resp_data.get('data', {}).get('message_id')}")
        else:
            # 打印完整的响应以便调试
            print(f"     ❌ [NapCat拒绝] 群 {group_id} | 错误码: {retcode}")
            print(f"       └─ 原因: {resp_data.get('msg')} | 详情: {resp_data.get('wording')}")

    except Exception as e:
        print(f"     ❌ [网络错误] 推送失败: {e}")
        
# def get_last_page_url(tid):
#     if "page=" not in tid:
#         return tid + "&page=9999"
#     return tid


def format_nga_message(username, uid, timestamp, raw_text):
    """
    将带有NGA引用标签的文本格式化为易读格式
    """
    # ==========================================
    # 【修改点】 这里改成了显示用户名
    # ==========================================
    header = f"**[@{username}]**发帖时间：{timestamp}"

    # ... (下面的代码保持不变) ...
    quote_match = re.search(r'\[quote\](.*?)\[/quote\](.*)', raw_text, re.DOTALL)

    if quote_match:
        quote_block = quote_match.group(1)
        main_body = quote_match.group(2).strip()

        user_match = re.search(r'Post by (.*?) \(', quote_block)
        quoted_user = "未知用户"
        if user_match:
            raw_name = user_match.group(1)
            quoted_user = re.sub(r'\[/?uid.*?\]', '', raw_name).strip()

        time_match = re.search(r'\((.*?)\):', quote_block)
        quoted_time = time_match.group(1) if time_match else "未知时间"

        content_match = re.search(r':\[/b\](.*)', quote_block, re.DOTALL)
        quoted_content = content_match.group(1).strip() if content_match else "引用内容解析失败"

        formatted_msg = (
            f"{header}\n"
            f"回复[@{quoted_user}][{quoted_time}]<<<{quoted_content}>>>\n\n"
            f"{main_body}"
        )
        return formatted_msg

    else:
        return f"{header}\n{raw_text.strip()}"

def parse_post(url):
    # 1. 构造请求最后一页的 URL (代替原来的 get_last_page_url)
    target_url = url if "page=" in url else url + "&page=9999"
    
    try:
        # 2. 先请求最后一页，不仅为了获取内容，更为了探明当前的"真实页码"
        resp = requests.get(target_url, headers=HEADERS, timeout=15)
        resp.encoding = 'gbk'  # NGA 强制 GBK
        html_last = resp.text

        # 3. 解析 NGA 源码里自带的页码变量
        # NGA标准格式: var __PAGE = {0:'/read.php?tid=xxx', 1:当前页数, 2:总页数, 3:每页条数};
        current_page = 1
        page_match = re.search(r'var\s+__PAGE\s*=\s*\{[^}]*1:\s*(\d+)', html_last)
        if page_match:
            current_page = int(page_match.group(1))

        # 4. 制定双页抓取计划
        pages_to_parse = []
        if current_page > 1:
            # 如果存在上一页，构造上一页的 URL
            if "page=" in url:
                prev_url = re.sub(r'page=\d+', f'page={current_page - 1}', url)
            else:
                sep = "&" if "?" in url else "?"
                prev_url = f"{url}{sep}page={current_page - 1}"
            
            # 把上一页排在前面，保证时间顺序从旧到新
            pages_to_parse.append((current_page - 1, prev_url))
        
        # 把当前页（最后一页）排在最后面
        pages_to_parse.append((current_page, target_url))

        new_content_count = 0
        
        # 5. 开始依次解析这 1~2 页
        for page_num, page_url in pages_to_parse:
            # print(f"    [页面调度] 正在处理第 {page_num} 页...")
            
            # 如果是最后一页，直接用刚才拿到的现成 HTML，省一次网络请求
            if page_num == current_page:
                html_content = html_last
            else:
                # 如果是上一页，发起新请求
                time.sleep(1)  # 停顿一下，防止被 NGA 认为是攻击
                resp_prev = requests.get(page_url, headers=HEADERS, timeout=15)
                resp_prev.encoding = 'gbk'
                html_content = resp_prev.text
                
            # ==========================================
            # 开始正式解析这页的 HTML
            # ==========================================
            soup = BeautifulSoup(html_content, 'html.parser')

            title_tag = soup.find('title')
            title = title_tag.text.strip() if title_tag else "NGA帖子"

            folder_name = re.sub(r'[\\/:*?"<>|]', '_', title.split(' NGA')[0].strip())
            save_path = os.path.join(config['save_dir'], folder_name)
            img_path = os.path.join(save_path, "images")

            content_spans = soup.find_all('span', class_='postcontent')

            # 只有处理最后一页时才打印这个日志，免得刷屏
            if page_num == current_page:
                print(f"正在检查: {title[:20]}... (当前第 {current_page} 页)")

            for content_tag in content_spans:
                # 获取 PID
                container = content_tag.find_parent(attrs={"id": re.compile(r"postcontainer|pid")})
                pid = "unknown"
                if container and container.get('id'):
                    pid = container.get('id').replace('postcontainer', '').replace('pid', '')
                elif content_tag.get('id'):
                    pid = content_tag.get('id').split('_')[-1]
                else:
                    pid = str(hash(content_tag.text[:20]))

                # 【去重防御】由于我们现在会拉取上一页，这里会疯狂拦截已处理过的老楼层
                if pid in processed_pids:
                    continue

                # ==========================================
                # 获取 UID 和 用户名 
                # ==========================================
                username = ""  
                uid = 0

                user_link = None
                if container:
                    user_link = container.find('a', href=re.compile(r'uid='))
                if not user_link:
                    user_link = content_tag.find_previous('a', href=re.compile(r'uid='))

                if user_link:
                    raw_name = user_link.text.strip()
                    if raw_name:
                        username = raw_name

                    uid_match = re.search(r'uid=(-?\d+)', user_link.get('href'))
                    uid = int(uid_match.group(1)) if uid_match else 0

                custom_names = config.get('user_names', {})
                if uid in custom_names:
                    username = custom_names[uid]

                if not username:
                    username = f"UID:{uid}" if uid else "未知用户"
                
                # ==========================================
                
                os.makedirs(img_path, exist_ok=True)
                new_content_count += 1

                # --- 提取图片 ---
                post_images = []
                for img in content_tag.find_all('img'):
                    src = img.get('src')
                    if src:
                        local_img = download_image(src, img_path)
                        if local_img:
                            post_images.append(local_img)
                            img['src'] = os.path.join("images", os.path.basename(local_img))

                raw_html = str(content_tag)
                nga_code_imgs = re.findall(r'\[img\](\./.*?)\[/img\]', raw_html)
                for src in nga_code_imgs:
                    local_img = download_image(src, img_path)
                    if local_img and local_img not in post_images:
                        post_images.append(local_img)

                # --- 修复换行 ---
                for br in content_tag.find_all("br"):
                    br.replace_with("\n")
                
                clean_text = content_tag.get_text().strip()
                clean_text = re.sub(r'<br\s*/?>', '\n', clean_text, flags=re.IGNORECASE)
                
                timestamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
                final_message = format_nga_message(username, uid, timestamp, clean_text)

                print("-" * 50)
                print(f"【新回复】 {username} (UID:{uid})")
                print("-" * 50)

                # --- 保存到 Markdown ---
                md_file = os.path.join(save_path, "posts.md")
                with open(md_file, 'a', encoding='utf-8') as f:
                    f.write(f"<!-- pid:{pid} -->\n")
                    f.write(final_message + "\n")
                    if post_images:
                        f.write(f"*(包含 {len(post_images)} 张图片)*\n")
                    f.write("---\n\n")

                # --- 推送到指定群 ---
                user_routes = config.get('user_routes', {})
                if uid in user_routes:
                    target_groups = user_routes[uid]
                    
                    if len(final_message) > 1000:
                        push_text = final_message[:1000] + "\n...(内容太长已截断)"
                    else:
                        push_text = final_message

                    if target_groups:
                        print(f"    ✅ 用户 [{username}] 触发推送，正在分发给 {len(target_groups)} 个群...")
                        for gid in target_groups:
                            push_to_group(push_text, post_images, gid)
                            time.sleep(1)

                processed_pids.add(pid)

        # 两页都循环完毕后，统一保存进度
        if new_content_count > 0:
            save_history(processed_pids)

    except Exception as e:
        print(f"解析错误: {e}")


# ================= 主循环 =================
if __name__ == "__main__":
    if not os.path.exists(config['save_dir']):
        os.makedirs(config['save_dir'])

    print(f"启动监控 (通用解析版)，间隔 {config.get('check_interval', 60)} 秒...")

    try:
        while True:
            for url in config['target_urls']:
                parse_post(url)
                time.sleep(2)
            time.sleep(config.get('check_interval', 60))
    except KeyboardInterrupt:
        print("\n停止。")
