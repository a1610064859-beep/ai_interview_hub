# Radmin VPN 本机语音面试

面试服务器只在主机运行。远端 Windows 电脑录音后，经 Radmin VPN 上传到主机；主机现有 `POST /api/sessions/{sid}/answers` 接口将 webm 临时保存、转为 wav、执行本地 ASR 与评分，最后返回下一题或报告 ID。临时音频在请求结束后清理。后端 `8000` 端口仍只监听主机 `127.0.0.1`。

## 主机

1. 主机和客户端加入同一个 Radmin VPN 私有网络。主机先运行 `scripts/start_local.ps1` 启动网页与 API，确认 `http://127.0.0.1:3000/api/jobs` 可访问。
2. 在主机的**管理员 PowerShell** 中运行：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\scripts\start_radmin.ps1
   ```

   脚本会读取主机的 Radmin VPN 地址（`26.x.x.x`），将该地址的 TCP 3000 转发到本机网页，并只为 Radmin VPN 网卡创建入站防火墙规则。记下脚本显示的地址。

## 每台客户端

1. 将 `scripts/connect_radmin_client.ps1` 复制到客户端，加入相同的 Radmin VPN 私有网络。
2. 在客户端的**管理员 PowerShell** 中运行，把 IP 换成主机显示的地址：

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\connect_radmin_client.ps1 -ServerIp 26.236.64.76
   ```

   上例是本机当前的 Radmin VPN 地址；地址变化时，以主机脚本显示的地址为准。

3. 在该客户端浏览器打开脚本显示的 `http://127.0.0.1:3000/`，登录后做 3 秒麦克风自检，再完成语音面试。浏览器把 `localhost` 视为可使用麦克风的安全上下文；直接打开 `http://26.x.x.x:3000/` 通常只能使用文本功能。

客户端若已占用 3000 端口，可以传入 `-LocalPort 3001`，然后打开 `http://127.0.0.1:3001/`。录音上传、题目音频和报告均经过同一网页代理；无需在客户端安装 Python、ASR 模型或评分模型。

## 排查与撤销

- 客户端可先在 Radmin VPN 中对主机执行 ping；脚本会检查网页是否可打开。主机的 API 和网页进程必须保持运行。
- 停用客户端转发：以管理员身份运行 `netsh interface portproxy delete v4tov4 listenaddress=127.0.0.1 listenport=3000`；如果使用其他 `LocalPort`，相应替换端口。
- 停用主机转发：以管理员身份运行 `netsh interface portproxy delete v4tov4 listenaddress=<主机Radmin IP> listenport=3000`，再删除名为 `AI Interview Hub - Radmin VPN TCP 3000` 的防火墙规则。
