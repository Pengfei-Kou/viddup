#!/bin/bash
# ──────────────────────────────────────────────────────────────
# VidDup Demo 录制脚本
#
# 使用方法：
#   1. 先清除旧的 cache 避免干扰:  viddup clear --confirm
#   2. 录制:                       bash docs/record_demo.sh
#   3. 转 GIF:                     agg docs/assets/demo.cast docs/assets/demo.gif --theme mocha --cols 100 --rows 30 --font-size 16
#
# 工具依赖：brew install asciinema agg
# ──────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
CAST_FILE="$SCRIPT_DIR/assets/demo.cast"

mkdir -p "$SCRIPT_DIR/assets"

echo "🎬 Starting VidDup demo recording..."
echo "   Output: $CAST_FILE"
echo ""
echo "📋 Instructions:"
echo "   1. Terminal will start recording NOW"
echo "   2. Type the commands below (or paste them):"
echo ""
echo "      ls demo/"
echo "      viddup scan demo/ --no-open"
echo ""
echo "   3. When scan finishes, wait 3 seconds then press Ctrl+D to stop"
echo ""
echo "Press Enter to start recording..."
read -r

cd "$PROJECT_DIR"

# Record with asciinema
asciinema rec "$CAST_FILE" \
  --cols 100 \
  --rows 30 \
  --overwrite \
  --idle-time-limit 3

echo ""
echo "✅ Recording saved to: $CAST_FILE"
echo ""
echo "🎞️  Now convert to GIF:"
echo "   agg $CAST_FILE docs/assets/demo.gif --theme mocha --font-size 16"
