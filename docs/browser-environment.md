# 浏览器环境检查报告（T14）

> 检查日期：2026-11-21
> 适用范围：本机 Windows 11 演示环境下的 Playwright / Edge 无头浏览器可用性，供 T5（浏览器 + 云裳商城）与 T16（最终 E2E）参考。
> 本次只做环境探测，未修改任何浏览器业务代码；仓库内唯一改动是本文件。

## 1. 结论摘要

| 检查项 | 结果 | 说明 |
|---|---|---|
| `chromium.launch(channel="msedge", headless=True)` | **成功** | 本机 Edge 157.0.4341.60，直接复用系统浏览器，无需下载 |
| Playwright 内置 Chromium 回退 | **失败（未安装）** | `%LOCALAPPDATA%\ms-playwright` 不存在；需执行 `playwright install chromium` 后可用 |
| 项目 `PlaywrightDriver` 冒烟（读取 `.env` 配置） | **成功** | 实际走 `channel=msedge`，视口 1280×900、`zh-CN`、截图正常 |
| 中文渲染 | **正常** | Microsoft YaHei / SimSun 均可用，截图无方框乱码 |
| 长驻进程 | **无残留** | 测试后浏览器全部关闭，未启动 uvicorn/frontend 服务器 |
| 浏览器测试门控 | 可用 | T16 可按 `RUN_BROWSER_TESTS=1` 启用真实 E2E；未安装内置 Chromium 时仍可走 Edge |

**给 T5 的结论**：默认启动路径（Edge → 内置 Chromium）在本机实测可用，现有 `playwright_driver.py` 无需修改；内置 Chromium 缺失时抛中文 `BrowserUnavailable` 的行为符合“失败不得假装下单成功”的契约。

**给 T16 的结论**：E2E 直接用 `channel="msedge"` 即可，不要依赖内置 Chromium；下载安装命令、镜像注意事项和内网启动参数见第 5、8 节。

## 2. 测试环境

| 项目 | 值 |
|---|---|
| 操作系统 | Windows 11 Home China 10.0.26200（win32） |
| 后端虚拟环境 | `C:\Users\cc\Desktop\服装平台项目\backend\.venv` |
| Python | 3.13.5（`backend/.venv/Scripts/python.exe`） |
| Playwright（pip） | 1.65.2 |
| Playwright CLI | `Version 1.65.2`（`python -m playwright --version`） |
| Microsoft Edge | 157.0.4341.60，`C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe` |
| Google Chrome | 未安装（`Program Files` 与 `Program Files (x86)` 均无） |
| Playwright 浏览器目录 | `C:\Users\cc\AppData\Local\ms-playwright` **不存在** |
| `PLAYWRIGHT_DOWNLOAD_HOST` / `PLAYWRIGHT_BROWSERS_PATH` | 均为空（未设置） |
| 项目浏览器配置（`backend/.env`） | `BROWSER_ENGINE=playwright`、`BROWSER_HEADLESS=true`、`PLAYWRIGHT_CHANNEL=msedge` |
| Node（仅记录，T14 不使用） | v24.19.0 / npm 11.17.0 |

说明：本机 `Program Files (x86)\Microsoft\Edge\Application` 下同时存在 `157.0.4341.60` 与 `158.0.4370.33` 两个版本目录（Edge 自动更新暂存）；当前实际启动并报告为 157.0.4341.60。系统只安装了 Edge，`channel="chrome"` 不可用。

## 3. 实测结果

### 3.1 直接调用 async_playwright（主探测）

使用后端 venv 运行临时脚本（位于项目外 `C:\Users\cc\AppData\Local\Temp\t14_browser_check\check_edge.py`，测完已删除）：

```bash
cd "C:/Users/cc/Desktop/服装平台项目/backend"
./.venv/Scripts/python.exe -I "C:/Users/cc/AppData/Local/Temp/t14_browser_check/check_edge.py"
```

核心代码：

```python
from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(channel="msedge", headless=True)
    context = await browser.new_context(
        viewport={"width": 1280, "height": 900},
        locale="zh-CN",
        device_scale_factor=1,
    )
    page = await context.new_page()
    page.set_default_timeout(15000)
    await page.goto("data:text/html,<title>T14</title><h1>衣见 T14</h1>")
    await page.screenshot(path="probe-edge.png", animations="disabled")
    await browser.close()
```

实测输出（节选）：

| 探测项 | 结果 |
|---|---|
| `channel="msedge"`, `headless=True` | ✅ 成功 |
| `browser.version` | `157.0.4341.60` |
| User-Agent | `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) HeadlessChrome/157.0.0.0 Safari/537.36 Edg/157.0.0.0` |
| 页面标题读取 | ✅ `T14` |
| 截图 | ✅ 7517 字节 PNG |
| 耗时（启动 + 打开页 + 截图） | 约 1204 ms；另一次探测（启动 + 写入页面 + 截图）启动约 440 ms、全流程约 780 ms |
| 内置 Chromium（无 channel） | ❌ `Executable doesn't exist at C:\Users\cc\AppData\Local\ms-playwright\chromium_headless_shell-1255\chrome-headless-shell-win64\chrome-headless-shell.exe` |
| `p.chromium.executable_path` | `C:\Users\cc\AppData\Local\ms-playwright\chromium-1255\chrome-win64\chrome.exe`（文件不存在） |

中文渲染补充检查：`document.fonts.check('16px "Microsoft YaHei"')` 与 `SimSun` 均返回 `true`；以深空黑 + 香槟金渲染“衣见 ATELIER 云裳商城 / 雾灰风衣 · 香槟金 · 模拟支付”截图，肉眼确认中文正常、无豆腐块。

### 3.2 项目 PlaywrightDriver 冒烟

直接使用 T5 已实现的 `backend/app/browser/playwright_driver.py`（只读调用，未改代码），验证它读取 `.env` 后能否真正启动：

```bash
cd "C:/Users/cc/Desktop/服装平台项目/backend"
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -c "
import asyncio
from app.browser.playwright_driver import PlaywrightDriver

async def main():
    async with PlaywrightDriver('t14-env-check') as d:
        print('browser.version =', d._browser.version)
        print('headless =', d.headless)
        await d.page.goto('data:text/html,<title>T14 driver probe</title>')
        print('title =', await d.page.title())
        print('locale =', await d.page.evaluate('navigator.language'))
        print('screenshot =', await d.screenshot('00-env-probe'))

asyncio.run(main())
"
```

实测输出：

```text
browser.version = 157.0.4341.60
headless = True
viewport = {'width': 1280, 'height': 900}
timeouts = 15000 25000
title = T14 driver probe
locale = zh-CN
screenshot = /screenshots/t14-env-check/00-env-probe.png
```

- 截图落盘为 `backend/runtime/screenshots/t14-env-check/00-env-probe.png`（7900 字节），公开 URL 由 `main.py` 的 `/screenshots` 静态挂载提供。
- 测试结束后已删除该临时截图目录；`runtime/screenshots` 下仅保留其他任务产生的目录。
- 退出时 `__aexit__` 正常关闭 context/browser/playwright，未留下进程。

### 3.3 进程与残留检查

- 用 PowerShell `Get-CimInstance Win32_Process` 检查：无 `msedge.exe --headless` 残留，无 Playwright driver 残留。
- 本次检查未启动 uvicorn、Vite 或任何长驻服务；探测脚本一次运行后即退出。
- 临时探测脚本与截图均放在系统临时目录，已清理；未在 `app/` 下写入任何运行期文件。

## 4. 可用启动参数（已验证）

以下是本项目当前可用、已实测通过的组合：

```python
browser = await p.chromium.launch(
    channel="msedge",   # 使用系统 Edge；无需 playwright install
    headless=True,      # 无头模式，演示/测试均可用
)
context = await browser.new_context(
    viewport={"width": 1280, "height": 900},
    locale="zh-CN",
    device_scale_factor=1,
)
page = await context.new_page()
page.set_default_timeout(15_000)            # 元素等待 15s
page.set_default_navigation_timeout(25_000) # 页面导航 25s
```

要点：

| 参数 | 建议值 | 说明 |
|---|---|---|
| `channel` | `"msedge"` | 本机唯一可用的真实浏览器通道；`"chrome"` 因未安装 Chrome 不可用 |
| `headless` | `True` | 已实测；演示与自动化必须无头。`False` 仅用于本地排障，不要用于验收脚本 |
| `viewport` | `1280×900` | 与 `playwright_driver.py` 的 `VIEWPORT` 一致（总方案文字写 1280×800，以现有代码为准；商城页面为响应式，两者均可渲染） |
| `locale` | `"zh-CN"` | 已实测 `navigator.language == zh-CN` |
| `device_scale_factor` | `1` | 截图尺寸稳定，避免高分屏放大 |
| `args` | 无需额外参数 | 不需要 `--no-sandbox`、`--disable-gpu` 等；加参数前先复测 |
| 并发 | 全局 `asyncio.Semaphore(1)` | 现有驱动已实现，避免同时打开多个 Edge 实例 |
| 截图 | `page.screenshot(animations="disabled")` | 现有驱动已使用；截图失败不得中断下单流程 |
| 超时 | 元素 15s / 导航 25s | 与现有驱动一致；慢机器可整体放大，但不要无限等待 |

`headless=False` 在本机也能启动（未纳入本次自动验证），仅建议人工观察商城流程时临时使用；T16 的自动化不要依赖可见窗口。

## 5. 安装 / 回退命令

### 5.1 首选：不安装，直接用 Edge

本机 Edge 已随 Windows 预装，`channel="msedge"` 实测可用，**不需要下载任何浏览器**。这也是课程演示的推荐路径（离线可跑）。

### 5.2 查看将要下载的内容（只读、无下载）

```bash
cd "C:/Users/cc/Desktop/服装平台项目/backend"
./.venv/Scripts/python.exe -m playwright install --dry-run chromium
```

本机实测输出要点（Playwright 1.65.2）：

- Chrome for Testing 159.0.8154.6（playwright chromium v1255），约 217 MB
- Chrome Headless Shell 159.0.8154.6，约 130 MB
- FFmpeg v1013，约 1.7 MB；Winldd v1007，约 0.13 MB
- 默认安装根目录：`C:\Users\cc\AppData\Local\ms-playwright`

### 5.3 正式安装（仅在内置 Chromium 回退确实需要时）

官方 CDN 直连（本机网络 HEAD 实测可达：`cdn.playwright.dev` 307 跳转到 `storage.googleapis.com` 返回 200）：

```bash
cd "C:/Users/cc/Desktop/服装平台项目/backend"
./.venv/Scripts/python.exe -m playwright install chromium
```

国内镜像（如官方 CDN 超时）：

```bash
cd "C:/Users/cc/Desktop/服装平台项目/backend"
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
  ./.venv/Scripts/python.exe -m playwright install chromium
```

镜像可用性 HEAD 探测（2026-11-21，仅验证文件存在，未执行完整下载）：

| 地址（镜像相对路径） | HTTP | 大小 |
|---|---|---|
| `/builds/cft/159.0.8154.6/win64/chrome-win64.zip` | 200 | 217,364,368 B |
| `/builds/cft/159.0.8154.6/win64/chrome-headless-shell-win64.zip` | 200 | 129,830,431 B |
| `/builds/ffmpeg/1013/ffmpeg-win64.zip` | 200 | 1,663,577 B |
| `/builds/winldd/1007/winldd-win64.zip` | 200 | 128,684 B |
| `/dbazure/download/playwright/builds/ffmpeg/1013/ffmpeg-win64.zip` | 404 | — |
| `/dbazure/download/playwright/builds/winldd/1007/winldd-win64.zip` | 404 | — |

注意：npmmirror 镜像只覆盖 `builds/...` 布局，Playwright 的**首选**下载 URL 是 `dbazure/...` 路径（镜像 404），安装器会尝试备用 URL；若镜像安装在 ffmpeg/winldd 处报 404，直接改用官方 CDN（本机实测可达）或 `PLAYWRIGHT_DOWNLOAD_HOST=https://cdn.npmmirror.com/binaries/playwright`。**本次因 Edge 已可用，未实际执行完整安装**，以上为命令与网络探测结论。

### 5.4 安装后验证

```bash
cd "C:/Users/cc/Desktop/服装平台项目/backend"
./.venv/Scripts/python.exe -c "
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        for kwargs in ({'channel': 'msedge', 'headless': True}, {'headless': True}):
            b = await p.chromium.launch(**kwargs)
            print(kwargs, '->', b.version)
            await b.close()

asyncio.run(main())
"
```

预期：两条均打印版本号；第一条为系统 Edge，第二条为内置 Chromium。若第二条仍报 `Executable doesn't exist`，说明安装未完成或 `PLAYWRIGHT_BROWSERS_PATH` 指向了别处。

## 6. 已知限制与风险

1. **内置 Chromium 当前不可用**：`%LOCALAPPDATA%\ms-playwright` 不存在，`chromium.launch(headless=True)` 会立刻报可执行文件缺失。`PlaywrightDriver` 会在 Edge 失败后尝试它，因此内置 Chromium 缺失时最终的 `BrowserUnavailable` 中文提示会同时包含“已尝试本机 Edge 与内置 Chromium”，这是预期行为。
2. **Edge 由系统自动更新**：本机已暂存 158 版本目录，浏览器升级后 `browser.version` 会变化；Playwright 1.65.2 + Edge 157 实测可用。若未来 Edge 大版本与 Playwright 驱动不兼容，可执行 `pip install -U playwright` 或安装内置 Chromium 兜底。
3. **只有 Edge 通道**：本机未安装 Google Chrome，`channel="chrome"` 不可用；也没有 Firefox/WebKit 浏览器。跨浏览器兼容不在本项目验收范围。
4. **镜像覆盖不完整**：见 5.3，npmmirror 的 `dbazure` 路径 404；国内网络安装时需注意备用 URL 是否生效。下载安装只在开发/CI 准备阶段进行，运行期不得依赖外网。
5. **Windows 控制台编码**：Git Bash 下用 `python -c` 打印中文页面标题时可能触发 `UnicodeEncodeError: 'gbk' codec ...`。这是控制台编码问题，不是浏览器问题；脚本中设置 `PYTHONIOENCODING=utf-8`（或 `sys.stdout.reconfigure(encoding="utf-8")`）即可。T16 的 E2E 脚本建议统一设置。
6. **首次启动开销**：冷启动约 0.4–1.2 s（含浏览器进程与上下文），比 Mock 慢；T16 断言语义要允许浏览器启动耗时，不要用过短的全局超时。驱动已用 `Semaphore(1)` 串行化，避免并发抢占。
7. **无头截图范围**：`page.screenshot(full_page=False)` 只截视口；长页面需要显式滚动或 `full_page=True`。现有驱动截视口，与聊天内缩略图/灯箱展示匹配。
8. **动画与字体**：截图使用 `animations="disabled"`，星空/尾焰等动画页面的稳定性依赖该参数；中文 YaHei/SimSun 在本机可用，但不要假设其他机器一定有同一字体。
9. **安全边界**：浏览器只访问本地 `127.0.0.1` 的 `/demo-mall/*`，不访问真实电商；本次检查也未打开任何外部站点（仅 `data:` URL）。下载浏览器属于开发环境准备，不是运行期外链。
10. **无长驻进程**：所有探测均在单个 Python 进程内完成并退出；如 T16 启动 uvicorn，测试结束必须关闭，避免端口占用和残留 Edge。

## 7. 给 T5（浏览器 / 云裳商城）的建议

1. **保持现有启动顺序**：`channel=msedge` → 内置 Chromium → 中文 `BrowserUnavailable`。本次实测 `.env` 默认值即可成功启动，无需改代码。
2. **保持失败语义**：内置 Chromium 缺失时，驱动会明确报错；助理服务应继续把 `BrowserUnavailable` 转为 SSE `error` 中文提示，绝不能伪造 `order_created`。建议 T5 自测时覆盖“浏览器不可用”分支（可用不可执行路径或 monkeypatch）。
3. **选择器联调**：商城页面已具备契约要求的 `data-testid`（`mall-search`、`mall-product-card`、`mall-product-name`、`mall-buy-now`、`mall-place-order`、`mall-order-no`；另有 `mall-order-total`），与本报告使用同一套 Edge 环境，E2E 可直接复用。
4. **截图路径**：继续写 `runtime/screenshots/{session}/NN.png`，不要写进 `app/`，避免 uvicorn 热重载；截图失败保持“不中断流程、返回空 URL”。
5. **资源释放**：确认所有异常路径都经过 `__aexit__`；`shutdown_browser()` 已在 `main.py` lifespan 关闭钩子中调用，本次冒烟未发现残留进程。
6. **如果要在无 Edge 的机器演示**：把 `python -m playwright install chromium` 写入部署/演示准备步骤（可用 5.3 的镜像命令），运行期不要触网下载。
7. **可选增强**（不强制）：在 `/api/meta` 或健康检查中附带 `browser.engine/headless/channel` 只读信息，便于演示前快速确认环境；这属于 T5/主代理的文件范围，T14 未改动。

## 8. 给 T16（最终 E2E）的建议

1. **门控**：用 `RUN_BROWSER_TESTS=1` 启用真实浏览器用例；默认跳过并输出中文原因（例如“未启用浏览器 E2E，跳过”），不要让默认 `pytest` 依赖 Edge 成功。
2. **启动方式**：直接 `chromium.launch(channel="msedge", headless=True)`；不要先尝试内置 Chromium（本机未安装，会多一次失败开销），或按“Edge → 内置”顺序并捕获异常。
3. **上下文参数**：`viewport={"width":1280,"height":900}`、`locale="zh-CN"`、`device_scale_factor=1`；元素超时 15s、导航 25s，与业务驱动保持一致。
4. **服务准备**：在测试 fixture 中以子进程启动 `uvicorn app.main:app --host 127.0.0.1 --port <测试端口>`，轮询 `/api/health` 就绪后再开浏览器；测试结束 terminate 并等待退出。不要复用开发中的 8000 端口，避免与其他并行任务冲突。
5. **断言口径**：以成功页 `[data-testid="mall-order-no"]` 文本和 `GET /api/orders` 中的订单为“下单成功”证据；任何一步失败都判失败并保存 `runtime/screenshots/e2e/<时间戳>/` 截图，绝不把错误吞掉。
6. **编码**：测试脚本设置 `PYTHONIOENCODING=utf-8`，避免 Windows GBK 控制台在打印中文标题/错误时二次报错掩盖真实失败。
7. **清理**：`finally` 中关闭 context/browser/playwright；删除临时数据库/截图（或保留失败证据）；确认无 `msedge.exe --headless` 残留。
8. **安装兜底**：若目标机器没有 Edge，测试前置步骤执行 5.3 的安装命令；本机无需安装，官方 CDN 与 npmmirror 的可用性结论见 5.3。
9. **不要修改共享契约**：E2E 只消费现有 API/选择器；发现商城选择器缺失时反馈 T5，不要在本任务里改 `demo_mall/*` 或 `browser/*`。

## 9. 复现清单（命令汇总）

```bash
# 1) 版本信息
cd "C:/Users/cc/Desktop/服装平台项目/backend"
./.venv/Scripts/python.exe -m playwright --version
./.venv/Scripts/python.exe -m playwright install --dry-run chromium

# 2) Edge 无头启动 + 截图（等价于 3.1 的精简版）
cd "C:/Users/cc/Desktop/服装平台项目/backend"
PYTHONIOENCODING=utf-8 ./.venv/Scripts/python.exe -c "
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch(channel='msedge', headless=True)
        c = await b.new_context(viewport={'width':1280,'height':900}, locale='zh-CN')
        pg = await c.new_page()
        await pg.goto('data:text/html,<title>T14</title><h1>OK</h1>')
        print('version=', b.version, 'title=', await pg.title())
        await b.close()

asyncio.run(main())
"

# 3) 仅在需要内置 Chromium 时安装
./.venv/Scripts/python.exe -m playwright install chromium
# 或国内镜像
PLAYWRIGHT_DOWNLOAD_HOST=https://npmmirror.com/mirrors/playwright \
  ./.venv/Scripts/python.exe -m playwright install chromium
```

本次实际执行了 1、2 以及第 3 节中的项目驱动冒烟；第 3 步完整安装未执行（Edge 已可用，避免无必要的大体积下载），仅完成 `--dry-run` 与镜像/官方 CDN 的 HTTP HEAD 探测。
