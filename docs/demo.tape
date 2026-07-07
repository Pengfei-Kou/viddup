# VidDup Demo Recording
# Run with: vhs docs/demo.tape

# ── Output settings ───────────────────────────────────────────────────────────
Output docs/assets/demo.gif
Set Width 1200
Set Height 620
Set FontSize 16
Set Theme "Catppuccin Mocha"
Set Padding 20
Set TypingSpeed 50ms

# ── Scene 1: Show the tool ───────────────────────────────────────────────────
Sleep 500ms
Type "# VidDup — 快速检测视频重复文件"
Enter
Sleep 1s

Type "ls demo/"
Enter
Sleep 2s

# ── Scene 2: Run the scan ────────────────────────────────────────────────────
Type "viddup scan demo/"
Enter

# Wait for scan to complete (adjust if needed — depends on machine speed)
Sleep 30s

# ── Scene 3: Pause to show the results ───────────────────────────────────────
Sleep 5s
