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
# 随机延时区间，防止频繁请求被封
SLEEP_MIN = 1
SLEEP_MAX = 3
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
HEADERS_BASE = {
    "User-Agent": USER_AGENT,
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8"
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
    # 本地调试优先读取本地文件
    if os.path.exists(local_config_path):
        log("本地调试模式：加载 config.json 配置文件")
        try:
            with open(local_config_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log(f"❌ 本地config.json读取失败：{str(e)}")
            return []
    
    # 线上Action读取环境变量密钥
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

# ========== 各论坛签到实现函数（完整保留原逻辑，仅调用公共工具简化代码） ==========
def sign_discuz_paulsign(account):
    """类型: discuz → Discuz! + dsu_paulsign 保罗签到插件（最通用）
    适用：bbs.54lee.com、bbs.gycq.net、www.wanmirbbs.com 等多数论坛
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    session = build_session(cookie, referer=f"{url}/forum.php")

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
        random_sleep()
        resp = session.post(sign_url, data=sign_data, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if any(key in resp.text for key in ["签到成功", "已经签到", "您今日已签到", "今日已签"]):
            return True, "签到成功"
        elif "请登录后再进行操作" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:150].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"请求异常：{str(e)}"


def sign_zqlj(account):
    """类型: zqlj → Discuz! + zqlj_sign 自强励志打卡插件
    适用：www.chuanqijishu.com（紫龙传奇论坛）
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    session = build_session(cookie, referer=f"{url}/plugin.php?id=zqlj_sign")

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
        random_sleep()
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

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"请求异常：{str(e)}"


def sign_lwdz(account):
    """类型: lwdz → Discuz! + lwdz_signin 签到插件
    适用：bbs.hqbbk.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page_url = f"{url}/plugin.php?id=lwdz_signin:index"
    session = build_session(cookie, referer=sign_page_url)

    try:
        page_resp = session.get(sign_page_url, timeout=TIMEOUT)
        page_resp.encoding = page_resp.apparent_encoding
        formhash = get_formhash(page_resp.text)

        if not formhash:
            preview = page_resp.text[:200].replace("\n", " ")
            return False, f"未获取formhash，状态码：{page_resp.status_code}，页面预览：{preview}"

        sign_data = {"formhash": formhash, "signsubmit": "yes"}
        random_sleep()
        resp = session.post(sign_page_url, data=sign_data, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if any(key in resp.text for key in ["签到成功", "今日已签到", "已经签到", "您今天已经签到"]):
            return True, "签到成功"
        elif "请登录" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:150].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"请求异常：{str(e)}"


def sign_k_misign(account):
    """类型: k_misign → Discuz! + k_misign (K签到) 插件
    适用：www.ruciwan.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    session = build_session(cookie, referer=f"{url}/")

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
        random_sleep()
        resp = session.post(sign_page_url, data=sign_data, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if any(key in resp.text for key in ["签到成功", "今日已签到", "已经签到", "您今天已经签到"]):
            return True, "签到成功"
        elif "请登录" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:150].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"请求异常：{str(e)}"


def sign_phpwind(account):
    """类型: phpwind → PHPWind 论坛程序"""
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "").strip()
    session = build_session(cookie)

    # 无Cookie则账号密码登录
    if not cookie:
        login_url = f"{url}/login.php?m=login&a=dologin"
        login_data = {
            "username": account.get("username", ""),
            "password": account.get("password", ""),
            "jumpurl": f"{url}/index.php",
            "step": 2
        }
        random_sleep()
        session.post(login_url, data=login_data, timeout=TIMEOUT)

    try:
        sign_url = f"{url}/index.php?m=sign&a=dosign"
        random_sleep()
        resp = session.get(sign_url, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if "签到成功" in resp.text or "已签到" in resp.text:
            return True, "签到成功"
        preview = resp.text[:120].replace("\n", " ")
        return False, f"签到失败：{preview}"
    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"请求异常：{str(e)}"


def sign_dc_signin(account):
    """类型: dc_signin → Discuz! + dc_signin 签到插件
    适用：bbs.54lee.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page_url = f"{url}/plugin.php?id=dc_signin:dc_signin"
    session = build_session(cookie, referer=sign_page_url)

    try:
        # 1. 访问签到页，提取 formhash 并校验登录状态
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
        random_sleep()
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

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"请求异常：{str(e)}"


def sign_erling_qd(account):
    """类型: erling_qd → Discuz! 20CMS erling_qd打卡插件（恩山无线论坛right.com.cn）
    适用：https://www.right.com.cn/forum/erling_qd-sign_in.html
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    sign_page = f"{url}/erling_qd-sign_in.html"
    session = build_session(cookie, referer=sign_page)

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
        random_sleep()
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

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"未知异常：{str(e)}"


def sign_wanmirbbs(account):
    """类型: wanmirbbs → 玩传奇论坛 wanmirbbs.com 弹窗签到插件
    首页自动弹出签到弹窗，需选择表情+留言提交，接口返回JSON
    """
    base_url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    session = build_session(cookie, referer=base_url)

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
        random_sleep()
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

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"签到程序异常：{str(e)}"


def sign_diygm(account):
    """类型: diy → diygm.com 通用dsu_paulsign保罗签到插件
    论坛地址：https://www.diygm.com
    """
    url = account["url"].rstrip("/")
    cookie = account.get("cookie", "")
    session = build_session(cookie, referer=f"{url}/forum.php")

    try:
        index_resp = session.get(f"{url}/forum.php", timeout=TIMEOUT)
        index_resp.encoding = index_resp.apparent_encoding
        formhash = get_formhash(index_resp.text)

        if not formhash:
            preview = index_resp.text[:200].replace("\n", " ")
            return False, f"未获取formhash，状态码：{index_resp.status_code}，页面预览：{preview}"

        sign_url = f"{url}/plugin.php?id=dsu_paulsign&operation=qiandao&infloat=1&inajax=1"
        sign_data = {
            "formhash": formhash,
            "qdxq": "kx",
            "qdmode": 3,
            "todaysay": "",
            "fastreply": 0
        }
        random_sleep()
        resp = session.post(sign_url, data=sign_data, timeout=TIMEOUT)
        resp.encoding = resp.apparent_encoding

        if any(key in resp.text for key in ["签到成功", "已经签到", "您今日已签到", "今日已签"]):
            return True, "签到成功"
        elif "请登录后再进行操作" in resp.text or "未登录" in resp.text:
            return False, "Cookie无效/已过期，请重新抓取"
        else:
            preview = resp.text[:150].replace("\n", " ")
            return False, f"签到返回异常，预览：{preview}"

    except RequestException as e:
        if isinstance(e, Timeout):
            return False, "请求访问论坛超时"
        elif isinstance(e, ConnectionError):
            return False, "无法连接论坛服务器"
        else:
            return False, f"请求异常：{str(e)}"

# ========== 论坛类型映射表 ==========
FORUM_HANDLERS = {
    "discuz": sign_discuz_paulsign,
    "zqlj": sign_zqlj,
    "lwdz": sign_lwdz,
    "k_misign": sign_k_misign,
    "dc_signin": sign_dc_signin,
    "phpwind": sign_phpwind,
    "erling_qd": sign_erling_qd,
    "wanmirbbs": sign_wanmirbbs,
    "diy": sign_diygm,
}

# ========== 主执行逻辑 ==========
def main():
    # 前置依赖校验
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
        except Exception as e:
            log(f"[{forum_name}] ❌ 签到函数全局异常：{str(e)}")
            fail_count += 1
        random_sleep()

    # 签到统计输出
    log(f"===== 签到任务全部结束 =====")
    log(f"✅ 成功总数：{success_count}")
    log(f"❌ 失败总数：{fail_count}")

    # 存在失败账号则退出码1，Action会标记工作流失败告警
    if fail_count > 0:
        log("存在签到失败账号，程序退出码 1")
        sys.exit(1)
    else:
        log("全部账号签到正常，程序退出码 0")
        sys.exit(0)

if __name__ == "__main__":
    main()
