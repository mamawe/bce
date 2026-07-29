#!/bin/bash
# 一键部署脚本（无持久化版）
# 用法: bash scripts/deploy.sh

set -e

cd "$(dirname "$0")/.."

echo "=========================================="
echo "  BCE Backend → 阿里云函数计算 部署"
echo "  (无持久化 / 代码包内嵌数据库)"
echo "=========================================="
echo ""

# 检查 s 命令行
if ! command -v s &> /dev/null; then
    echo "❌ 未找到 Serverless Devs CLI (s 命令)"
    echo "   安装: npm install -g @serverless-devs/s"
    exit 1
fi

# 检查凭证
if ! s config get &> /dev/null; then
    echo "❌ 未配置阿里云凭证"
    echo "   运行: s config add"
    exit 1
fi

# 检查数据库文件
if [ ! -f "src/bce.db" ]; then
    echo "❌ 未找到 src/bce.db"
    echo "   请先运行: cp ../backend/bce.db src/bce.db"
    exit 1
fi

DB_SIZE=$(du -h src/bce.db | cut -f1)
echo "📦 数据库大小: $DB_SIZE"
echo ""

echo "⏳ 开始部署..."
s deploy

echo ""
echo "=========================================="
echo "  ✅ 部署完成！"
echo "  上方输出中的 URL 即为 API 地址"
echo "  前端 Vercel 环境变量指向此 URL"
echo "=========================================="
