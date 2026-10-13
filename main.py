import os
import json
import requests
from datetime import datetime, timezone, timedelta

CONFIG_FILE = "config.json"

def parse_time(t_str):
    h, m = map(int, t_str.split(":"))
    return h * 60 + m

def fmt_time(mins):
    prefix = ""
    while mins < 0:
        mins += 1440
        prefix = "前一天 "
    mins = ((mins % 1440) + 1440) % 1440
    return f"{prefix}{mins // 60:02d}:{mins % 60:02d}"

def build_makeup_schedule(makeup_cfg):
    roster = makeup_cfg.get("roster", [])
    deadline = parse_time(makeup_cfg.get("deadline", "04:40"))
    gap = int(makeup_cfg.get("gap", 0))
    t = deadline
    rows = []
    for p in reversed(roster):
        e, s = t, t - int(p["mins"])
        rows.insert(0, f"{fmt_time(s)}–{fmt_time(e)} {p['name']} ({p['mins']}′)")
        t = s - gap
    return f"（{fmt_time(deadline)}前收工）\n" + "\n".join(rows)

def send_wechat_push(date_str, schedule_str, custom_str):
    appid = os.environ.get("WX_APPID")
    appsecret = os.environ.get("WX_APPSECRET")
    template_id = os.environ.get("WX_TEMPLATE_ID")
    
    token_url = f"https://api.weixin.qq.com/cgi-bin/token?grant_type=client_credential&appid={appid}&secret={appsecret}"
    access_token = requests.get(token_url).json().get("access_token")
    
    user_url = f"https://api.weixin.qq.com/cgi-bin/user/get?access_token={access_token}"
    openids = requests.get(user_url).json().get("data", {}).get("openid", [])
    
    send_url = f"https://api.weixin.qq.com/cgi-bin/message/template/send?access_token={access_token}"
    for uid in openids:
        payload = {
            "touser": uid,
            "template_id": template_id,
            "data": {
                "date": {"value": date_str},
                "schedule": {"value": schedule_str},
                "todos": {"value": custom_str}
            }
        }
        requests.post(send_url, json=payload)

def main():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        config = json.load(f)

    # 获取当前时区时间与星期几 (1=周一, 7=周日)
    tz = timezone(timedelta(hours=8)) # 日本时间可改 hours=9
    now = datetime.now(tz)
    today_str = now.strftime("%m.%d")
    current_weekday = now.isoweekday()

    # 判断当前是早间场(morning)还是晚间场(evening)
    current_slot = os.environ.get("PUSH_SLOT", "").strip()
    if not current_slot:
        # 如果是定时自动触发，按小时自动判断：15点前算早间场，15点后算晚间场
        current_slot = "morning" if now.hour < 15 else "evening"

    # 1. 检查是否发送化妆排班
    makeup_cfg = config.get("makeup", {})
    makeup_slot = makeup_cfg.get("schedule_slot", "morning")
    should_send_makeup = makeup_cfg.get("enabled") and (makeup_slot in [current_slot, "all"])
    
    schedule_str = build_makeup_schedule(makeup_cfg) if should_send_makeup else "（本时段无化妆排班）"

    # 2. 动态遍历所有自定义模块
    active_blocks = []
    for mod in config.get("custom_modules", []):
        if not mod.get("enabled"):
            continue
        if mod.get("schedule_slot") not in [current_slot, "all"]:
            continue
        if current_weekday not in mod.get("weekdays", [1,2,3,4,5,6,7]):
            continue
        content = mod.get("content", "").strip()
        if content:
            active_blocks.append(f"【{mod.get('title', '通知')}】\n{content}")

    custom_str = "\n\n".join(active_blocks) if active_blocks else "暂无其他事项"

    # 如果既没有排班也没有任何自定义模块要发，直接跳过不打扰大家
    if not should_send_makeup and not active_blocks:
        print(f"ℹ️ 当前批次 [{current_slot}] 无启用模块，跳过推送。")
        return

    slot_label = "☀️ 早间提醒" if current_slot == "morning" else "🌙 晚间提醒"
    send_wechat_push(f"{today_str} ({slot_label})", schedule_str, custom_str)

    # 3. 只有当本次实际发送了化妆排班时，才触发名单顺延！
    if should_send_makeup and makeup_cfg.get("autoRotate", True) and len(makeup_cfg.get("roster", [])) > 1:
        roster = makeup_cfg["roster"]
        makeup_cfg["roster"] = [roster[-1]] + roster[:-1]
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        print("✅ 化妆名单已自动顺延！")

if __name__ == "__main__":
    main()
