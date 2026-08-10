import os
import sys
import json
import re
import requests
from bs4 import BeautifulSoup
from requests.exceptions import Timeout, ConnectionError

# ========== 全局配置 ==========
TIMEOUT = 20
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
HEADERS_BASE = {
    "User-Agent": USER_AGENT
}

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
    headers = HEADERS_BASE.copy()
    headers["Referer"] = f"{url}/forum.php"
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)

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

    except Timeout:
        return False, "请求访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_zqlj(account):
    """类型: zqlj → Discuz! + zqlj_sign 自强励志打卡插件
    适用：www.chuanqijishu.com（紫龙传奇论坛）
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    headers = HEADERS_BASE.copy()
    headers["Referer"] = f"{url}/plugin.php?id=zqlj_sign"
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)

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

    except Timeout:
        return False, "请求访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_lwdz(account):
    """类型: lwdz → Discuz! + lwdz_signin 签到插件
    适用：bbs.hqbbk.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    headers = HEADERS_BASE.copy()
    headers["Referer"] = f"{url}/plugin.php?id=lwdz_signin:index"
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)

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

    except Timeout:
        return False, "请求访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_k_misign(account):
    """类型: k_misign → Discuz! + k_misign (K签到) 插件
    适用：www.ruciwan.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    headers = HEADERS_BASE.copy()
    headers["Referer"] = f"{url}/"
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)

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

    except Timeout:
        return False, "请求访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_phpwind(account):
    """类型: phpwind → PHPWind 论坛程序"""
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    session.headers.update(HEADERS_BASE)
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
        preview = resp.text[:120].replace("\n", " ")
        return False, f"签到失败：{preview}"
    except Timeout:
        return False, "请求访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_dc_signin(account):
    """类型: dc_signin → Discuz! + dc_signin 签到插件
    适用：bbs.54lee.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    headers = HEADERS_BASE.copy()
    headers["Referer"] = f"{url}/plugin.php?id=dc_signin:dc_signin"
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)

    try:
        # 1. 访问签到页，提取 formhash 并校验登录状态
        sign_page_url = f"{url}/plugin.php?id=dc_signin:dc_signin"
        page_resp = session.get(sign_page_url, timeout=TIMEOUT)
        page_resp.encoding = page_resp.apparent_encoding

        if "您尚未登录" in page_resp.text or "无法进行此操作" in page_resp.text:
            return False, "Cookie无效/已过期，请重新抓取"

        formhash = get_formhash(page_resp.text)
        if not formhash:
            preview = page_resp.text[:200].replace("\n", " ")
            return False, f"未获取formhash，页面预览：{preview}"

        # 2. 构建真实POST提交请求
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

        resp = session.post(real_sign_url, data=payload, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding
        result_text = resp.text

        # 3. 判断签到结果
        if any(key in result_text for key in ["签到成功", "恭喜您签到成功", "今日已签到", "您今天已经签到"]):
            return True, "签到成功"
        elif "请勿重复签到" in result_text or "今日已签" in result_text:
            return True, "今日已签到，无需重复提交"
        elif "请登录" in result_text or "未登录" in result_text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = result_text[:200].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except Timeout:
        return False, "请求访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"请求异常：{str(e)}"


def sign_erling_qd(account):
    """类型: erling_qd → Discuz! 20CMS erling_qd打卡插件（恩山无线论坛right.com.cn）
    适用：https://www.right.com.cn/forum/erling_qd-sign_in.html
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()

    session = requests.Session()
    headers = HEADERS_BASE.copy()
    sign_page = f"{url}/erling_qd-sign_in.html"
    headers["Referer"] = sign_page
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)

    try:
        # 1. 访问签到页面，校验登录+判断是否今日已签到
        page_resp = session.get(sign_page, timeout=TIMEOUT)
        page_resp.encoding = "utf-8"
        page_text = page_resp.text

        if "请先登录" in page_text:
            return False, "Cookie无效/已过期，请重新抓取"

        # 页面直接存在【已签到】文字，说明今天签过，直接返回成功
        if "已签到" in page_text:
            return True, "今日已签到（页面已标记），无需重复提交"

        formhash = get_formhash(page_text)
        if not formhash:
            preview = page_text[:200].replace("\n", " ")
            return False, f"未获取formhash，页面预览：{preview}"

        # 2. 执行签到POST请求
        sign_api = f"{url}/plugin.php?id=erling_qd:action&action=sign"
        post_data = {"formhash": formhash}
        resp = session.post(sign_api, data=post_data, timeout=TIMEOUT)
        resp.encoding = "utf-8"
        res_text = resp.text

        # 优先解析JSON返回（接口标准返回格式）
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
            # 解析JSON失败，降级HTML文本匹配
            pass

        # 兼容普通HTML页面返回
        if any(key in res_text for key in ["签到成功", "今日已打卡", "您今日已签到"]):
            return True, "签到成功"
        elif "已签到" in res_text:
            return True, "今日已签到，无需重复提交"
        else:
            preview = res_text[:200].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except Timeout:
        return False, "请求访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"未知异常：{str(e)}"


def sign_wanmirbbs(account):
    """类型: wanmirbbs → 玩传奇论坛 wanmirbbs.com 弹窗签到插件
    首页自动弹出签到弹窗，需选择表情+留言提交，接口返回JSON
    """
    base_url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()
    session = requests.Session()
    headers = HEADERS_BASE.copy()
    headers["Referer"] = base_url
    if cookie:
        headers["Cookie"] = cookie
    session.headers.update(headers)

    try:
        # 1. 访问首页，触发签到弹窗、获取页面formhash
        index_resp = session.get(base_url, timeout=TIMEOUT)
        index_resp.encoding = index_resp.apparent_encoding
        page_text = index_resp.text

        # 判断登录状态
        if "登录/注册" in page_text:
            return False, "Cookie失效，请重新抓取登录Cookie"
        
        # 检测今日是否已签到（页面关键词）
        if "今日已签到" in page_text:
            return True, "今日已完成签到，无需重复操作"

        # 提取表单验证formhash
        formhash = get_formhash(page_text)
        if not formhash:
            preview = page_text[:200].replace("\n", " ")
            return False, f"页面未获取formhash，预览：{preview}"

        # 2. 签到提交接口（mpage_signs签到插件）
        sign_api = f"{base_url}/plugin.php?id=mpage_signs:signs"
        # 固定参数：表情选第一个开心(1)，留言填默认文字
        post_data = {
            "formhash": formhash,
            "mood": "1",          # 1=开心表情
            "content": "今日打卡"  # 签到留言
        }
        resp = session.post(sign_api, data=post_data, timeout=TIMEOUT)
        resp.encoding = "utf-8"

        # 解析AJAX JSON返回
        try:
            res_json = resp.json()
            code = res_json.get("code")
            msg = res_json.get("msg", "")
            if code == 1:
                credit = res_json.get("credit", 0)
                return True, f"签到成功！今日积分+{credit}，提示：{msg}"
            elif code == -1 and "已签到" in msg:
                return True, f"今日已签到，提示：{msg}"
            else:
                return False, f"签到失败，接口提示：{msg}"
        except json.JSONDecodeError:
            # JSON解析失败，降级文本匹配
            if "签到成功" in resp.text:
                return True, "签到成功"
            elif "今日已签到" in resp.text:
                return True, "今日已签到"
            else:
                preview = resp.text[:200].replace("\n", " ")
                return False, f"签到返回异常，预览：{preview}"

    except Timeout:
        return False, "访问论坛超时"
    except ConnectionError:
        return False, "无法连接论坛服务器"
    except Exception as e:
        return False, f"签到程序异常：{str(e)}"


# ========== 论坛类型映射表（新增wanmirbbs映射） ==========
FORUM_HANDLERS = {
    "discuz": sign_discuz_paulsign,
    "zqlj": sign_zqlj,
    "lwdz": sign_lwdz,
    "k_misign": sign_k_misign,
    "dc_signin": sign_dc_signin,
    "phpwind": sign_phpwind,
    "erling_qd": sign_erling_qd,
    "wanmirbbs": sign_wanmirbbs, # 新增玩传奇论坛映射
}

# ========== 主逻辑 ==========
def main():
    accounts = load_accounts()
    if not accounts:
        log("没有读取到任何账号配置，请检查 Secrets FORUM_ACCOUNTS")
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
    # 存在失败任务时退出码1，触发GitHub Action告警
    if fail > 0:
        sys.exit(1)

if __name__ == "__main__":
    main()
