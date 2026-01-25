"""
验证 AIPromptOptimizer 是否正确处理正向和反向提示词
"""
import sys
import os

# 将 src 目录添加到路径
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

try:
    from PyQt6.QtCore import QCoreApplication, QSettings
    from src.core.ai_prompt_optimizer import AIPromptOptimizer
    
    # 初始化 QCoreApplication 以便 QSettings 正常工作
    app = QCoreApplication(sys.argv)
    
    optimizer = AIPromptOptimizer()
    
    print("--- 测试 1: 从零生成正向提示词 ---")
    success, res = optimizer.optimize_prompt("一个女孩在森林里")
    print(f"成功: {success}")
    print(f"结果: {res}\n")
    
    print("--- 测试 2: 从零生成反向提示词 ---")
    success, res = optimizer.optimize_prompt("不要崩坏, 不要模糊", is_negative=True)
    print(f"成功: {success}")
    print(f"结果: {res}\n")
    
    print("--- 测试 3: 优化现有正向提示词 ---")
    success, res = optimizer.optimize_prompt("让她戴上帽子", "一名女孩站在森林里")
    print(f"成功: {success}")
    print(f"结果: {res}\n")
    
    print("--- 测试 4: 优化现有反向提示词 ---")
    success, res = optimizer.optimize_prompt("也要过滤水印", "lowres, blurry", is_negative=True)
    print(f"成功: {success}")
    print(f"结果: {res}\n")

except Exception as e:
    print(f"错误: {e}")
