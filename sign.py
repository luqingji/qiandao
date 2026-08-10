import os
import sys
import json
import re
import requests
from bs4 import BeautifulSoup

# ========== 全局配置 ==========
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"

def log(msg):
    print(f"[签到] {msg}")

def load_accounts():
    """从环境变量读取账号配置（JSON格式）"""
    raw = os.environ.get("FORUM_ACCOUNTS", "[]")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as e:
        log(f"❌ 账号配置JSON解析失败：{str(e)}")
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

# ========== 各类型签到实现 ==========

def sign_discuz_paulsign(account):
    """类型: discuz → Discuz! + dsu_paulsign 保罗签到插件（最通用）
    适用：bbs.54lee.com、bbs.gycq.net、www.wanmirbbs.com 等多数论坛
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"{url}/forum.php"
    })
    if cookie:
        session.headers["Cookie"] = cookie

    try:
        index_resp = session.get(f"{url}/forum.php", timeout=TIMEOUT)
        index_resp.encoding = index_resp.apparent_encoding
        formhash = get_formhash(index_resp.text)

        if not formhash:
            preview = index_resp.text[:200].replace("\n", " ")
            return False, f"未获取formhash，状态码：{index_resp.status_code}，页面预览：{preview}"

        sign_url = f"{url}/plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1&inajax=1"
        sign_data = {
            "formhash": formhash,
            "qdxq": "kx",
            "qdmode": 3,
            "todaysay": "",
            "fastreply": 0
        }
        resp = session.post(sign_url, data=sign_data, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if any(key in resp.text for key in ["签到成功", "已经签到", "您今日已签到", "今日已签"]):
            return True, "签到成功"
        elif "请登录后再进行操作" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:150].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_zqlj(account):
    """类型: zqlj → Discuz! + zqlj_sign 自强励志打卡插件
    适用：www.chuanqijishu.com（紫龙传奇论坛）
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"{url}/plugin.php?id=zqlj_sign"
    })
    if cookie:
        session.headers["Cookie"] = cookie

    try:
        sign_page_url = f"{url}/plugin.php?id=zqlj_sign"
        page_resp = session.get(sign_page_url, timeout=TIMEOUT)
        page_resp.encoding = page_resp.apparent_encoding

        # 提取打卡链接中的动态 sign 参数
        sign_match = re.search(r'id=zqlj_sign&sign=([a-zA-Z0-9]+)', page_resp.text)
        if not sign_match:
            if "您今天已经打过卡了" in page_resp.text or "今日已打卡" in page_resp.text:
                return True, "今日已打卡，无需重复提交"
            preview = page_resp.text[:200].replace("\n", " ")
            return False, f"未找到打卡sign参数，页面预览：{preview}"

        sign_value = sign_match.group(1)

        # 执行真实打卡请求（GET方式，带动态sign参数）
        real_sign_url = f"{url}/plugin.php?id=zqlj_sign&sign={sign_value}"
        resp = session.get(real_sign_url, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if "恭喜您，打卡成功" in resp.text or "打卡成功" in resp.text:
            return True, "打卡成功"
        elif "您今天已经打过卡了" in resp.text or "请勿重复操作" in resp.text:
            return True, "今日已打卡，无需重复提交"
        elif "请登录" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:200].replace("\n", " ")
            return False, f"打卡返回异常，预览：{preview}"

    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_lwdz(account):
    """类型: lwdz → Discuz! + lwdz_signin 签到插件
    适用：bbs.hqbbk.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"{url}/plugin.php?id=lwdz_signin:index"
    })
    if cookie:
        session.headers["Cookie"] = cookie

    try:
        sign_page_url = f"{url}/plugin.php?id=lwdz_signin:index"
        page_resp = session.get(sign_page_url, timeout=TIMEOUT)
        page_resp.encoding = page_resp.apparent_encoding
        formhash = get_formhash(page_resp.text)

        if not formhash:
            preview = page_resp.text[:200].replace("\n", " ")
            return False, f"未获取formhash，状态码：{page_resp.status_code}，页面预览：{preview}"

        sign_data = {"formhash": formhash, "signsubmit": "yes"}
        resp = session.post(sign_page_url, data=sign_data, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if any(key in resp.text for key in ["签到成功", "今日已签到", "已经签到", "您今天已经签到"]):
            return True, "签到成功"
        elif "请登录" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:150].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_k_misign(account):
    """类型: k_misign → Discuz! + k_misign (K签到) 插件
    适用：www.ruciwan.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Referer": f"{url}/"
    })
    if cookie:
        session.headers["Cookie"] = cookie

    try:
        sign_page_url = f"{url}/k_misign-sign.html"
        page_resp = session.get(sign_page_url, timeout=TIMEOUT)
        if page_resp.status_code != 200:
            sign_page_url = f"{url}/plugin.php?id=k_misign:sign"
            page_resp = session.get(sign_page_url, timeout=TIMEOUT)

        page_resp.encoding = page_resp.apparent_encoding
        formhash = get_formhash(page_resp.text)

        if not formhash:
            preview = page_resp.text[:200].replace("\n", " ")
            return False, f"未获取formhash，状态码：{page_resp.status_code}，页面预览：{preview}"

        sign_data = {"formhash": formhash, "signsubmit": "yes"}
        resp = session.post(sign_page_url, data=sign_data, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if any(key in resp.text for key in ["签到成功", "今日已签到", "已经签到", "您今天已经签到"]):
            return True, "签到成功"
        elif "请登录" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:150].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_phpwind(account):
    """类型: phpwind → PHPWind 论坛程序"""
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    if cookie:
        session.headers["Cookie"] = cookie
    else:
        login_url = f"{url}/login.php?m=login&a=dologin"
        login_data = {
            "username": account.get("username", ""),
            "password": account.get("password", ""),
            "jumpurl": f"{url}/index.php",
            "step": 2
        }
        session.post(login_url, data=login_data, timeout=TIMEOUT)

    try:
        sign_url = f"{url}/index.php?m=sign&a=dosign"
        resp = session.get(sign_url, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if "签到成功" in resp.text or "已签到" in resp.text:
            return True, "签到成功"
        return False, f"签到失败：{resp.text[:120]}"
    except Exception as e:
        return False, f"请求异常：{str(e)}"

# ========== 论坛类型映射表 ==========
FORUM_HANDLERS = {
    "discuz": sign_discuz_paulsign,
    "zqlj": sign_zqlj,
    "lwdz": sign_lwdz,
    "k_misign": sign_k_misign,
    "phpwind": sign_phpwind,
}

# ========== 主逻辑 ==========
def main():
    accounts = load_accounts()
    if not accounts:
        log("没有读取到任何账号配置，请检查 Secrets")
        sys.exit(1)

    success = 0
    fail = 0

    for idx, acc in enumerate(accounts, 1):
        forum_type = acc.get("type", "discuz")
        name = acc.get("name", f"论坛{idx}")
        handler = FORUM_HANDLERS.get(forum_type)

        if not handler:
            log(f"[{name}] ❌ 不支持的论坛类型：{forum_type}")
            fail += 1
            continue

        log(f"[{name}] 开始签到...")
        try:
            ok, msg = handler(acc)
            if ok:
                log(f"[{name}] ✅ {msg}")
                success += 1
            else:
                log(f"[{name}] ❌ {msg}")
                fail += 1
        except Exception as e:
            log(f"[{name}] ❌ 运行异常：{str(e)}")
            fail += 1

    log(f"===== 全部完成：成功 {success} 个，失败 {fail} 个 =====")

    if success == 0 and fail > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
