import tushare as ts
import datetime
import subprocess
import os
import logging
from dotenv import load_dotenv
load_dotenv()  # 从 .env 文件加载环境变量

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

def run_task_on_trade_day():
    token = os.environ.get("TUSHARE_TOKEN")
    pro = ts.pro_api(token)
    
    today = datetime.datetime.now().strftime('%Y%m%d')
    
    # 1. 获取最近一天的日历信息
    df = pro.trade_cal(exchange='SSE', start_date=today, end_date=today)
    
    if df.empty or df.iloc[0]['is_open'] == 0:
        logging.info("今日非交易日，任务取消 💤")
        return

    logging.info("🌟 今日是交易日，准备启动选股流程...")
    
    # 2. 调用你之前的脚本
    try:
        # 这里替换成你实际的 python 路径和脚本路径
        cmd = ["python", "scripts/daily_selector.py", "--force-update"]
        subprocess.run(cmd, check=True)
        logging.info("✅ 任务运行成功")
    except subprocess.CalledProcessError as e:
        logging.error(f"❌ 任务运行出错: {e}")

if __name__ == "__main__":
    run_task_on_trade_day()