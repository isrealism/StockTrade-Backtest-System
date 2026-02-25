#!/usr/bin/env python3
"""
测试脚本：验证回测任务取消功能

测试场景：
1. 启动回测任务
2. 等待任务开始运行
3. 模拟取消操作
4. 验证状态更新

用法:
    python scripts/test_task_cancellation.py
"""

import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import requests
from datetime import datetime


API_BASE = "http://localhost:8000"


def create_test_backtest():
    """创建一个测试回测任务"""
    payload = {
        "name": f"取消测试 - {datetime.now().strftime('%H:%M:%S')}",
        "start_date": "2024-06-01",  # 较长的回测周期
        "end_date": "2025-06-30",
        "initial_capital": 1000000,
        "max_positions": 10,
        "sell_strategy_name": "conservative_trailing",
    }

    print("📝 创建测试回测任务...")
    response = requests.post(f"{API_BASE}/api/backtests", json=payload)
    response.raise_for_status()
    result = response.json()

    backtest_id = result["id"]
    print(f"✅ 任务已创建: {backtest_id}")
    return backtest_id


def get_backtest_status(backtest_id):
    """获取回测任务状态"""
    response = requests.get(f"{API_BASE}/api/backtests/{backtest_id}")
    response.raise_for_status()
    return response.json()


def cancel_backtest(backtest_id):
    """取消回测任务"""
    print(f"\n⏸️  发送取消请求...")
    response = requests.post(f"{API_BASE}/api/backtests/{backtest_id}/cancel")
    response.raise_for_status()
    print("✅ 取消请求已发送")
    return response.json()


def wait_for_status(backtest_id, target_status, timeout=60):
    """等待任务达到目标状态"""
    start_time = time.time()
    while True:
        data = get_backtest_status(backtest_id)
        current_status = data["status"]
        progress = data.get("progress", 0)

        print(f"   状态: {current_status}, 进度: {progress:.1f}%", end="\r")

        if current_status == target_status:
            print()  # New line
            return data

        if time.time() - start_time > timeout:
            print()  # New line
            raise TimeoutError(f"等待 {target_status} 超时（{timeout}秒）")

        time.sleep(1)


def test_normal_cancellation():
    """测试场景 1: 正常取消"""
    print("\n" + "="*60)
    print("测试场景 1: 正常取消")
    print("="*60)

    # 1. 创建任务
    backtest_id = create_test_backtest()

    # 2. 等待任务开始运行
    print("\n⏳ 等待任务开始运行...")
    wait_for_status(backtest_id, "RUNNING", timeout=30)
    print("✅ 任务已开始运行")

    # 3. 等待几秒钟，确保任务在运行中
    print("\n⏳ 等待 5 秒（让任务运行一段时间）...")
    time.sleep(5)

    # 4. 取消任务
    cancel_result = cancel_backtest(backtest_id)
    cancel_time = time.time()
    print(f"   取消结果: {cancel_result}")

    # 5. 等待任务变为 CANCELLED
    print("\n⏳ 等待任务状态变为 CANCELLED...")
    final_data = wait_for_status(backtest_id, "CANCELLED", timeout=30)
    response_time = time.time() - cancel_time

    # 6. 验证结果
    print(f"\n✅ 测试通过！")
    print(f"   - 最终状态: {final_data['status']}")
    print(f"   - 响应时间: {response_time:.2f} 秒")
    print(f"   - 完成进度: {final_data.get('progress', 0):.1f}%")

    if response_time < 10:
        print(f"   - ⚡ 响应速度优秀（< 10秒）")
    elif response_time < 30:
        print(f"   - ✅ 响应速度良好（< 30秒）")
    else:
        print(f"   - ⚠️  响应较慢（> 30秒），可能需要优化")

    return True


def test_ui_feedback():
    """测试场景 2: UI 即时反馈"""
    print("\n" + "="*60)
    print("测试场景 2: UI 即时反馈（需要手动测试）")
    print("="*60)

    print("\n📋 测试步骤:")
    print("1. 打开浏览器访问 http://localhost:3000/tasks")
    print("2. 创建一个新的回测任务")
    print("3. 等待任务开始运行")
    print("4. 点击'中止回测'按钮")
    print("5. 观察 UI 是否立即显示'回测任务已取消'")
    print("\n✅ 预期结果: UI 立即响应，不等待后端更新")
    print("❌ 如果 UI 需要等待 1-2 秒才显示取消，说明优化未生效")


def main():
    """主测试流程"""
    print("\n🧪 回测任务取消功能测试")
    print(f"API 地址: {API_BASE}")

    # 检查 API 是否可用
    try:
        response = requests.get(f"{API_BASE}/api/config", timeout=5)
        response.raise_for_status()
        print("✅ API 服务正常")
    except Exception as e:
        print(f"❌ API 服务不可用: {e}")
        print(f"请确保后端服务正在运行: cd backend && uvicorn app:app")
        return False

    try:
        # 测试 1: 正常取消
        test_normal_cancellation()

        # 测试 2: UI 反馈（手动测试指引）
        test_ui_feedback()

        print("\n" + "="*60)
        print("✅ 所有自动化测试通过！")
        print("="*60)
        print("\n💡 建议:")
        print("1. 手动执行 UI 反馈测试（测试场景 2）")
        print("2. 测试后端强制终止场景（Ctrl+C）")
        print("3. 查看数据库确认状态正确更新")

        return True

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
