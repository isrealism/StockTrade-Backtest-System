import sys
import os

def init_project_path():
    """
    动态获取项目根目录并加入 sys.path
    """
    # 获取当前文件 (path_utils.py) 的绝对路径
    current_path = os.path.abspath(__file__)
    # 获取其所在的目录，即项目根目录
    root_path = os.path.dirname(current_path)
    
    if root_path not in sys.path:
        # 将根目录插入到路径列表的最前面，确保优先导入项目内的模块
        sys.path.insert(0, root_path)
        print(f"[Project Path Init] Root added: {root_path}")

# 执行初始化
init_project_path()