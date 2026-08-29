@echo off
chcp 65001 >nul
cd /d "%~dp0.."
echo ============================================
echo   ArgOS 服务器（宇树狗 · sim 仿真）
echo   仅监听 127.0.0.1:8766，关窗 = 大脑下线
echo   试一下: curl -X POST http://127.0.0.1:8766/api/command -d "{\"text\":\"去门口\"}"
echo ============================================
python -m argos.server --executor sim
pause
