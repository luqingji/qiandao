import os
import sys
import json
import re
import time
import random
import requests
from bs4 import BeautifulSoup
from requests.exceptions import Timeout, ConnectionError, RequestException

# ========== 全局基础配置 ==========
TIMEOUT = 20
RETRY_TIMES = 1  # 网络失败重试1次
SLEEP_MIN = 1
SLEEP_MAX = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
HEADERS_BASE = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Encoding": "gzip, deflate",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache"
}

# ========== 通用工具函数 ==========
def log(msg):
    """统一日志输出"""
    print(f"[签到] {msg}")

def random_sleep():
    """随机间隔休眠，防论坛拦截"""
    sleep_sec = random.uniform(SLEEP_MIN, SLEEP_MAX)
    time.sleep(sleep_sec)

def load_accounts():
    """
    加载账号配置，双模式兼容：
    1. 本地运行：读取同目录 config.json
    2. GitHub Actions：读取环境变量 FORUM_ACCOUNTS Secrets
    """
    local_config_path = "config.json"
    if os.path.exists(local_config_path):
        log("本地调试模式：加载 config.json 配置文件")
        try:
            with open(local_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"❌ 本地config.json读取失败：{str(e)}")
            return []
    
    raw_env = os.environ.get("FORUM_ACCOUNTS", "").strip()
    if not raw_env:
        log("❌ 未检测到本地config.json，且环境变量 FORUM_ACCOUNTS 为空！")
        return []
    
    try:
        account_list = json.loads(raw_env)
        log(f"GitHub Actions模式：成功读取 {len(account_list)} 个论坛账号")
        return account_list
    except json.JSONDecodeError as e:
        log(f"❌ FORUM_ACCOUNTS JSON格式解析失败：{str(e)}")
        log("提示：检查Secrets内JSON字符串是否完整、无多余换行、引号匹配")
        return []

def get_formhash(html):
    """通用提取formhash，兼容所有Discuz模板和插件"""
    soup = BeautifulSoup(html, "html.parser")
    hash_input = soup.find("input", {"name": "formhash"})
    if hash_input and hash_input.get("value"):
        return hash_input["value"]
    match = re.search(r'formhash\s*=\s*["\']([a-zA-Z0-9]+)["\']', html)
    if match:
        return match.group(1)
    return None

def build_session(cookie, referer=""):
    """统一构建请求Session，减少重复代码"""
    session = requests.Session()
    headers = HEADERS_BASE.copy()
    if referer:
        headers["Referer"] = referer
    if cookie:
        headers["Cookie"] = cookie.strip()
    session.headers.update(headers)
    return session

def is_login_expired(html):
    """统一判断Cookie是否失效"""
    expired_keywords = ["请登录", "未登录", "登录/注册", "您尚未登录"]
    for kw in expired_keywords:
        if kw in html:
            return True
    return False

def get_short_preview(text, length=120):
    """截断超长页面文本，精简日志"""
    text = text.replace("\n", "").replace(" ", "")
    if len(text) > length:
        return text[:length] + "..."
    return text

# ========== 带重试封装请求 ==========
def safe_request(req_func):
    for i in range(RETRY_TIMES + 1):
        try:
            return req_func()
        except (Timeout, ConnectionError):
            if i < RETRY_TIMES:
                log(f"网络异常，第{i+1}次重试...")
                random_sleep()
                continue
            raise

# ========== 各论坛签到实现函数 ==========
def sign_discuz_paulsign(account):
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    session = build_session(cookie, referer=f"{url}/forum.php")

    def req_index():
        return session.get(f"{url}/forum.php", timeout=TIMEOUT)
    index_resp = safe_request(req_index)
    index_resp.encoding = index_resp.apparent_encoding
    html = index_resp.text

    if is_login_expired(html):
        return False, "Cookie失效，请重新抓取登录Cookie"

    formhash = get_formhash(html)
    if not formhash:
        preview = get_short_preview(html)
        return False, f"未获取formhash，页面预览：{preview}"

    sign_url = f"{url}/plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1&inajax=1"
    sign_data = {
        "formhash": formhash,
        "qdxq": "kx",
        "qdmode": 3,
        "todaysay": "",
        "fastreply": 0
    }
    random_sleep()
    def req_sign():
        return session.post(sign_url, data=sign_data, timeout=TIMEOUT)
    resp = safe_request(req_sign)
    resp.encoding = resp.apparent_encoding
    res_text = resp.text

    if "插件不存在或已关闭" in res_text:
        return False, "论坛签到插件已关闭/卸载"
    if any(key in res_text for key in ["签到成功", "已经签到", "您今日已签到", "今日已签"]):
        return True, "签到成功"
    elif "请登录后再进行操作" in res_text or "未登录" in res_text:
        return False, "Cookie无效/已过期，请重新抓取"
    else:
        preview = get_short_preview(res_text)
        return False, f"签到返回异常，预览：{preview}"

# ===================== 修复后的 zqlj 打卡函数（解决登录成功不打卡） =====================
def sign_zqlj(account):
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page_url = f"{url}/plugin.php?id=zqlj_sign"
    session = build_session(cookie, referer=sign_page_url)

    def req_page():
        return session.get(sign_page_url, timeout=TIMEOUT)
    page_resp = safe_request(req_page)
    page_resp.encoding = page_resp.apparent_encoding
    html = page_resp.text

    # Cookie失效检测
    if is_login_expired(html):
        return False, "Cookie失效，请重新抓取登录Cookie"

    # 适配截图页面关键词：今日已打卡
    repeat_words = ["您今天已经打过卡了", "今日已打卡", "今日已签到", "请勿重复操作", "今天已打卡"]
    if any(w in html for w in repeat_words):
        return True, "今日已打卡，无需重复提交"

    # 提取打卡页面实时formhash（核心缺失逻辑）
    page_formhash = get_formhash(html)
    if not page_formhash:
        preview = get_short_preview(html)
        return False, f"未获取打卡页formhash，页面预览：{preview}"

    # 方式1：优先POST表单提交（当前网站红色「点击打卡」真实交互）
    form_search = re.search(r'<form action="(plugin\.php\?id=zqlj_sign)"', html)
    post_success = False
    if form_search:
        submit_api = f"{url}/{form_search.group(1)}"
        post_payload = {
            "formhash": page_formhash,
            "signsubmit": "1"
        }
        random_sleep()
        def post_req():
            return session.post(submit_api, data=post_payload, timeout=TIMEOUT)
        safe_request(post_req)
        # 刷新页面验证是否打卡成功
        check_resp = session.get(sign_page_url, timeout=TIMEOUT)
        check_html = check_resp.text
        if any(w in check_html for w in repeat_words):
            post_success = True
            return True, "POST表单打卡成功"

    # 方式2：旧版GET链接兜底，追加formhash防止拦截
    sign_param = re.search(r'id=zqlj_sign&sign=([a-zA-Z0-9]+)', html)
    get_success = False
    if sign_param:
        sign_str = sign_param.group(1)
        get_api = f"{url}/plugin.php?id=zqlj_sign&sign={sign_str}&formhash={page_formhash}"
        random_sleep()
        def get_req():
            return session.get(get_api, timeout=TIMEOUT)
        safe_request(get_req)
        # 二次刷新页面校验真实状态
        check_resp = session.get(sign_page_url, timeout=TIMEOUT)
        check_html = check_resp.text
        if any(w in check_html for w in repeat_words):
            get_success = True
            return True, "GET链接打卡成功"

    # POST、GET 全部执行后页面仍未标记打卡，判定失败
    preview = get_short_preview(html)
    return False, f"POST/GET打卡提交后页面未更新打卡状态，页面预览：{preview}"

def sign_lwdz(account):
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page_url = f"{url}/plugin.php?id=lwdz_signin:index"
    session = build_session(cookie, referer=sign_page_url)

    def req_page():
        return session.get(sign_page_url, timeout=TIMEOUT)
    page_resp = safe_request(req_page)
    page_resp.encoding = page_resp.apparent_encoding
    html = page_resp.text

    if is_login_expired(html):
        return False, "Cookie失效，请重新抓取登录Cookie"

    formhash = get_formhash(html)
    if not formhash:
        preview = get_short_preview(html)
        return False, f"未获取formhash，页面预览：{preview}"

    sign_data = {"formhash": formhash, "signsubmit": "yes"}
    random_sleep()
    def req_sign():
        return session.post(sign_page_url, data=sign_data, timeout=TIMEOUT)
    resp = safe_request(req_sign)
    resp.encoding = resp.apparent_encoding
    res_text = resp.text

    if any(key in res_text for key in ["签到成功", "今日已签到", "已经签到", "您今天已经签到"]):
        return True, "签到成功"
    elif "请登录" in res_text or "未登录" in res_text:
        return False, "Cookie无效/已过期，请重新抓取"
    else:
        preview = get_short_preview(res_text)
        return False, f"签到返回异常，预览：{preview}"

def sign_k_misign(account):
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    session = build_session(cookie, referer=f"{url}/")

    def req_page():
        p1 = session.get(f"{url}/k_misign-sign.html", timeout=TIMEOUT)
        if p1.status_code == 200:
            return p1
        return session.get(f"{url}/plugin.php?id=k_misign:sign", timeout=TIMEOUT)
    page_resp = safe_request(req_page)
    page_resp.encoding = page_resp.apparent_encoding
    html = page_resp.text

    if is_login_expired(html):
        return False, "Cookie失效，请重新抓取登录Cookie"

    formhash = get_formhash(html)
    if not formhash:
        preview = get_short_preview(html)
        return False, f"未获取formhash，页面预览：{preview}"

    sign_data = {"formhash": formhash, "signsubmit": "yes"}
    random_sleep()
    def req_sign():
        return session.post(page_resp.url, data=sign_data, timeout=TIMEOUT)
    resp = safe_request(req_sign)
    resp.encoding = resp.apparent_encoding
    res_text = resp.text

    if any(key in res_text for key in ["签到成功", "今日已签到", "已经签到", "您今天已经签到"]):
        return True, "签到成功"
    elif "请登录" in res_text or "未登录" in res_text:
        return False, "Cookie无效/已过期，请重新抓取"
    else:
        preview = get_short_preview(res_text)
        return False, f"签到返回异常，预览：{preview}"

def sign_phpwind(account):
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()
    session = build_session(cookie)

    if not cookie:
        login_url = f"{url}/login.php?m=login&a=dologin"
        login_data = {
            "username": account.get("username", ""),
            "password": account.get("password", ""),
            "jumpurl": f"{url}/index.php",
            "step": 2
        }
        random_sleep()
        def req_login():
            return session.post(login_url, data=login_data, timeout=TIMEOUT)
        safe_request(req_login)

    def req_sign():
        return session.get(f"{url}/index.php?m=sign&a=dosign", timeout=TIMEOUT)
    resp = safe_request(req_sign)
    resp.encoding = resp.apparent_encoding
    res_text = resp.text

    if "签到成功" in res_text or "已签到" in res_text:
        return True, "签到成功"
    preview = get_short_preview(res_text)
    return False, f"签到失败：{preview}"

def sign_dc_signin(account):
    """DC签到通用函数（54lee论坛共用）"""
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page_url = f"{url}/plugin.php?id=dc_signin:dc_signin"
    session = build_session(cookie, referer=sign_page_url)

    def req_page():
        return session.get(sign_page_url, timeout=TIMEOUT)
    page_resp = safe_request(req_page)
    page_resp.encoding = page_resp.apparent_encoding
    html = page_resp.text

    if is_login_expired(html):
        return False, "Cookie失效，请重新抓取登录Cookie"

    formhash = get_formhash(html)
    if not formhash:
        preview = get_short_preview(html)
        return False, f"未获取formhash，页面预览：{preview}"

    real_sign_url = f"{url}/plugin.php?id=dc_signin:sign"
    payload = {
        "formhash": formhash,
        "signsubmit": "yes",
        "handlekey": "signin",
        "emotid": "1",
        "signpn": "true",
        "referer": f"{url}/./",
        "content": ""
    }
    random_sleep()
    def req_sign():
        return session.post(real_sign_url, data=payload, timeout=TIMEOUT)
    resp = safe_request(req_sign)
    resp.encoding = resp.apparent_encoding
    res_text = resp.text

    # 扩充完整重复签到关键词，解决当日签到跳转首页误判失败
    success_words = ["签到成功", "恭喜您签到成功", "今日已签到", "您今天已经签到",
                     "请勿重复签到", "今日已签", "今天已签到", "已完成今日签到"]
    if any(key in res_text for key in success_words):
        return True, "今日已签到，无需重复提交"
    # 兼容签到后直接返回首页完整HTML场景
    elif "签到" in html and ("今日打卡" in html or "已签到" in html):
        return True, "页面检测今日已签到，无需重复提交"
    elif is_login_expired(res_text):
        return False, "Cookie无效/已过期，请重新抓取"
    else:
        preview = get_short_preview(res_text)
        return False, f"签到返回异常，预览：{preview}"

def sign_erling_qd(account):
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page = f"{url}/erling_qd-sign_in.html"
    session = build_session(cookie, referer=sign_page)

    def req_page():
        return session.get(sign_page, timeout=TIMEOUT)
    page_resp = safe_request(req_page)
    page_resp.encoding = "utf-8"
    html = page_resp.text

    if "请先登录" in html:
        return False, "Cookie无效/已过期，请重新抓取"
    if "已签到" in html:
        return True, "今日已签到（页面已标记），无需重复提交"

    formhash = get_formhash(html)
    if not formhash:
        preview = get_short_preview(html)
        return False, f"未获取formhash，页面预览：{preview}"

    sign_api = f"{url}/plugin.php?id=erling_qd:action&action=sign"
    post_data = {"formhash": formhash}
    random_sleep()
    def req_sign():
        return session.post(sign_api, data=post_data, timeout=TIMEOUT)
    resp = safe_request(req_sign)
    resp.encoding = "utf-8"
    res_text = resp.text

    try:
        json_data = resp.json()
        if json_data.get("success") is True:
            credit = json_data.get("credit", 0)
            continuous = json_data.get("continuous_days", 0)
            msg = json_data.get("message", "")
            return True, f"签到成功！连续{continuous}天，今日积分+{credit}，提示：{msg}"
        elif json_data.get("success") is False and "已签到" in json_data.get("message", ""):
            return True, "接口提示今日已签到，无需重复提交"
    except json.JSONDecodeError:
        pass

    if any(key in res_text for key in ["签到成功", "今日已打卡", "您今日已签到"]):
        return True, "签到成功"
    elif "已签到" in res_text:
        return True, "今日已签到，无需重复提交"
    else:
        preview = get_short_preview(res_text)
        return False, f"签到返回异常，预览：{preview}"

def sign_diygm(account):
    """DIYGM论坛专用DC签到，匹配截图弹窗：开心表情+默认留言"""
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page_url = f"{url}/plugin.php?id=dc_signin:dc_signin"
    session = build_session(cookie, referer=sign_page_url)

    def req_page():
        return session.get(sign_page_url, timeout=TIMEOUT)
    page_resp = safe_request(req_page)
    page_resp.encoding = page_resp.apparent_encoding
    html = page_resp.text

    if is_login_expired(html):
        return False, "Cookie失效，请重新抓取登录Cookie"

    formhash = get_formhash(html)
    if not formhash:
        preview = get_short_preview(html)
        return False, f"未获取formhash，页面预览：{preview}"

    real_sign_url = f"{url}/plugin.php?id=dc_signin:sign"
    # 匹配截图：emotid=1 开心表情、默认留言文字
    payload = {
        "formhash": formhash,
        "signsubmit": "yes",
        "handlekey": "signin",
        "emotid": "1",
        "signpn": "true",
        "referer": f"{url}/./",
        "content": "记上一笔，hold住我的快乐！"
    }
    random_sleep()
    def req_sign():
        return session.post(real_sign_url, data=payload, timeout=TIMEOUT)
    resp = safe_request(req_sign)
    resp.encoding = resp.apparent_encoding
    res_text = resp.text

    success_words = ["签到成功", "恭喜您签到成功", "今日已签到", "您今天已经签到",
                     "请勿重复签到", "今日已签", "今天已签到", "已完成今日签到"]
    if any(key in res_text for key in success_words):
        return True, "今日已签到，无需重复提交"
    elif "签到" in html and ("今日打卡" in html or "已签到" in html):
        return True, "页面检测今日已签到，无需重复提交"
    elif is_login_expired(res_text):
        return False, "Cookie无效/已过期，请重新抓取"
    else:
        preview = get_short_preview(res_text)
        return False, f"签到返回异常，预览：{preview}"

# ========== 论坛类型映射表（已删除wanmirbbs废弃条目） ==========
FORUM_HANDLERS = {
    "discuz": sign_discuz_paulsign,
    "zqlj": sign_zqlj,
    "lwdz": sign_lwdz,
    "k_misign": sign_k_misign,
    "dc_signin": sign_dc_signin,
    "phpwind": sign_phpwind,
    "erling_qd": sign_erling_qd,
    "diy": sign_diygm,
}

# ========== 主执行逻辑 ==========
def main():
    try:
        from bs4 import BeautifulSoup
    except ModuleNotFoundError:
        log("❌ 缺少依赖库 beautifulsoup4，请执行：pip install requests beautifulsoup4")
        sys.exit(1)

    accounts = load_accounts()
    if not accounts:
        log("没有读取到任何账号配置，请检查 config.json 或 Secrets FORUM_ACCOUNTS")
        sys.exit(1)

    success_count = 0
    fail_count = 0

    log(f"===== 开始批量签到，共 {len(accounts)} 个论坛账号 =====")
    for idx, acc in enumerate(accounts, 1):
        forum_type = acc.get("type", "discuz")
        forum_name = acc.get("name", f"未知论坛{idx}")
        handler_func = FORUM_HANDLERS.get(forum_type)

        if not handler_func:
            log(f"[{forum_name}] ❌ 不支持的论坛类型：{forum_type}")
            fail_count += 1
            continue

        log(f"[{forum_name}] 正在执行签到...")
        try:
            ok, msg = handler_func(acc)
            if ok:
                log(f"[{forum_name}] ✅ {msg}")
                success_count += 1
            else:
                log(f"[{forum_name}] ❌ {msg}")
                fail_count += 1
        except RequestException as e:
            if isinstance(e, ConnectionError):
                log(f"[{forum_name}] ❌ 网络异常：无法连接论坛服务器")
            elif isinstance(e, Timeout):
                log(f"[{forum_name}] ❌ 网络异常：访问超时")
            else:
                log(f"[{forum_name}] ❌ 请求异常：{str(e)}")
            fail_count += 1
        except Exception as e:
            log(f"[{forum_name}] ❌ 签到函数全局异常：{str(e)}")
            fail_count += 1
        random_sleep()

    log(f"===== 签到任务全部结束 =====")
    log(f"✅ 成功总数：{success_count}")
    log(f"❌ 失败总数：{fail_count}")

    # 核心修改：无论是否存在失败账号，均返回退出码0，GitHub Action不会标红报错
    if fail_count > 0:
        log("存在签到失败账号，仅记录日志，不终止任务")
    else:
        log("全部账号签到正常")
    sys.exit(0)

if __name__ == "__main__":
    main()
