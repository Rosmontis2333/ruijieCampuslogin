# 校园网自动登录脚本使用指南

本脚本用于自动化完成校园网 CAS + ePortal 的登录认证。

---

## 准备工作（所有平台通用）

运行前需要安装 Python 3 和 Playwright 环境：

1. **安装 Python 3**  
   若电脑未安装 Python，请前往 [Python 官网](https://www.python.org/downloads/) 下载并安装（安装时务必勾选 **"Add Python to PATH"**）。

2. **安装依赖环境**  
   打开终端/命令行工具，执行以下命令：
   ```bash
   pip install playwright
   playwright install chromium
   ```

---

## 快速使用方法

请将下述命令中的 `你的学号` 和 `你的密码` 替换为实际账号信息。

### 1. Windows 平台

#### 方法 A：PowerShell（推荐）
按 `Win + R` 键，输入 `powershell` 回车，执行以下命令：
```powershell
$env:CAMPUS_USER="你的学号"; $env:CAMPUS_PASSWORD="你的密码"; $env:CAMPUS_SERVICE="ctcc"; python login.py
```

#### 方法 B：CMD 命令行
按 `Win + R` 键，输入 `cmd` 回车，执行以下命令：
```cmd
set CAMPUS_USER=你的学号
set CAMPUS_PASSWORD=你的密码
set CAMPUS_SERVICE=ctcc
python login.py
```

---

### 2. macOS 平台

打开 **终端 (Terminal)**，执行以下命令：
```bash
CAMPUS_USER="你的学号" CAMPUS_PASSWORD="你的密码" CAMPUS_SERVICE="ctcc" python3 login.py
```

---

### 3. Linux / 服务器 / Docker 平台

打开终端，执行以下命令（已自动添加免沙箱参数，适配无界面服务器环境）：
```bash
CAMPUS_USER="你的学号" CAMPUS_PASSWORD="你的密码" CAMPUS_SERVICE="ctcc" CAMPUS_DISABLE_SANDBOX=1 python3 login.py
```

---

## 常用参数调整

如果需要修改默认设置，可以在上述命令中额外加入以下参数：

- **更换运营商**：修改 `CAMPUS_SERVICE` 的值
  - `ctcc`：电信（默认）
  - `cmcc`：移动
  - `unicom`：联通
- **看浏览器操作过程（弹出界面调试）**：
  - Windows PowerShell 追加：`; $env:CAMPUS_HEADLESS="0"`
  - Linux/macOS 在命令前追加：`CAMPUS_HEADLESS=0 `
