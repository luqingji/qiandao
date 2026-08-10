import os
import sys
import json
import requests
from bs4 import BeautifulSoup

# ========== 全局配置 ==========
TIMEOUT = 15
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

def log(msg):
    print(f"[签到] {msg}")

def load_accounts():
    """从环境变量读取账号配置（JSON格式）"""
    raw = os.environ.get("FORUM_ACCOUNTS", "[]")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        log("❌ 账号配置解析失败，请检查 Secrets 里的 JSON 格式")
        return []

def create_session(account):
    """创建会话：优先用 Cookie 免登录，否则走账号密码登录
    返回：(session对象, 是否登录成功)
    """
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})
    url = account["url"].rstrip("/")

    # ===== 优先使用 Cookie 模式（绕过登录验证码） =====
    if "cookie" in account and account["cookie"].strip():
        session.headers["Cookie"] = account["cookie"].strip()
        # 简单校验：访问首页看是否包含用户名，确认Cookie有效
        try:
            test_resp = session.get(f"{url}/forum.php", timeout=TIMEOUT)
            # Discuz登录后会显示用户名，这里用是否存在退出链接作为简易判断
            if "退出" in test_resp.text or "logout" in test_resp.text:
                return session, True
            else:
                return session, False
        except Exception:
            return session, False

    # ===== 备选：账号密码登录（有验证码时大概率失败） =====
    login_url = f"{url}/member.php?mod=logging&action=login&loginsubmit=yes&infloat=yes&lssubmit=yes&inajax=1"
    login_data = {
        "username": account.get("username", ""),
        "password": account.get("password", ""),
        "quickforward": "yes",
        "handlekey": "ls"
    }
    try:
        session.post(login_url, data=login_data, timeout=TIMEOUT)
        # 校验登录状态
        test_resp = session.get(f"{url}/forum.php", timeout=TIMEOUT)
        if "退出" in test_resp.text or "logout" in test_resp.text:
            return session, True
        else:
            return session, False
    except Exception as e:
        return session, False

# ========== 各类型签到实现 ==========

def sign_discuz_paulsign(account):
    """类型: discuz → Discuz! + dsu_paulsign 保罗签到插件
    适用：bbs.54lee.com、chuanqijishu.com、bbs.gycq.net、wanmirbbs.com 等绝大多数论坛
    """
    url = account["url"].rstrip("/")
    session, login_ok = create_session(account)
    if not login_ok:
        return False, "登录失效，请检查Cookie是否过期，或账号密码是否正确"

    # 获取 formhash
    index_resp = session.get(f"{url}/forum.php", timeout=TIMEOUT)
    soup = BeautifulSoup(index_resp.text, "html.parser")
    hash_input = soup.find("input", {"name": "formhash"})
    if not hash_input:
        return False, "未找到 formhash，登录状态异常"
    formhash = hash_input["value"]

    # 提交签到
    sign_url = f"{url}/plugin.php?id=dsu_paulsign:sign&operation=qiandao&infloat=1&inajax=1"
    sign_data = {
        "formhash": formhash,
        "qdxq": "kx",
        "qdmode": 3,
        "todaysay": "",
        "fastreply": 0
    }
    resp = session.post(sign_url, data=sign_data, timeout=TIMEOUT)

    if "签到成功" in resp.text or "已经签到" in resp.text or "您今日已签到" in resp.text:
        return True, "签到成功"
    return False, f"签到失败：{resp.text[:120]}"


def sign_lwdz(account):
    """类型: lwdz → Discuz! + lwdz_signin 签到插件
    适用：bbs.hqbbk.com
    """
    url = account["url"].rstrip("/")
    session, login_ok = create_session(account)
    if not login_ok:
        return False, "登录失效，请检查Cookie是否过期"

    sign_page_url = f"{url}/plugin.php?id=lwdz_signin:index"
    page_resp = session.get(sign_page_url, timeout=TIMEOUT)
    soup = BeautifulSoup(page_resp.text, "html.parser")
    hash_input = soup.find("input", {"name": "formhash"})
    if not hash_input:
        return False, "未找到 formhash，登录状态异常"
    formhash = hash_input["value"]

    sign_data = {"formhash": formhash, "signsubmit": "yes"}
    resp = session.post(sign_page_url, data=sign_data, timeout=TIMEOUT)

    if "签到成功" in resp.text or "今日已签到" in resp.text or "已经签到" in resp.text:
        return True, "签到成功"
    return False, f"签到失败：{resp.text[:120]}"


def sign_k_misign(account):
    """类型: k_misign → Discuz! + k_misign (K签到) 插件
    适用：www.ruciwan.com
    """
    url = account["url"].rstrip("/")
    session, login_ok = create_session(account)
    if not login_ok:
        return False, "登录失效，请检查Cookie是否过期"

    # 伪静态地址，失效可换原生路径：/plugin.php?id=k_misign:sign
    sign_page_url = f"{url}/k_misign-sign.html"
    page_resp = session.get(sign_page_url, timeout=TIMEOUT)
    soup = BeautifulSoup(page_resp.text, "html.parser")
    hash_input = soup.find("input", {"name": "formhash"})
    if not hash_input:
        return False, "未找到 formhash，登录状态异常或插件路径不对"
    formhash = hash_input["value"]

    sign_data = {"formhash": formhash, "signsubmit": "yes"}
    resp = session.post(sign_page_url, data=sign_data, timeout=TIMEOUT)

    if "签到成功" in resp.text or "今日已签到" in resp.text or "已经签到" in resp.text:
        return True, "签到成功"
    return False, f"签到失败：{resp.text[:120]}"


def sign_phpwind(account):
    """类型: phpwind → PHPWind 论坛程序"""
    url = account["url"].rstrip("/")
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    # 优先Cookie模式
    if "cookie" in account and account["cookie"].strip():
        session.headers["Cookie"] = account["cookie"].strip()
    else:
        login_url = f"{url}/login.php?m=login&a=dologin"
        login_data = {
            "username": account.get("username", ""),
            "password": account.get("password", ""),
            "jumpurl": f"{url}/index.php",
            "step": 2
        }
        session.post(login_url, data=login_data, timeout=TIMEOUT)

    sign_url = f"{url}/index.php?m=sign&a=dosign"
    resp = session.get(sign_url, timeout=TIMEOUT)

    if "签到成功" in resp.text or "已签到" in resp.text:
        return True, "签到成功"
    return False, f"签到失败：{resp.text[:120]}"

# ========== 类型映射表 ==========
FORUM_HANDLERS = {
    "discuz": sign_discuz_paulsign,
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
