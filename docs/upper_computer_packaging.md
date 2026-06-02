# EchoGuard 上位机打包说明

本文档说明如何把当前 PyQt 上位机打包为 Windows 可运行目录。打包目标是上位机主体，不包含 Jina GGUF 模型和 `llama-server.exe`。

## 打包前检查

在仓库根目录执行：

```powershell
python -m pip install -r requirements-build.txt
python -m compileall upper_computer
```

上位机正式入口为：

```powershell
python -m upper_computer.main
```

## 执行打包

推荐使用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_upper_computer.ps1
```

也可以直接执行：

```powershell
python -m PyInstaller --clean --noconfirm EchoGuard.spec
```

产物位置：

```text
dist/
└── EchoGuard/
    └── EchoGuard.exe
```

## 资源与排除项

打包配置 `EchoGuard.spec` 会把以下资源放入程序：

- `upper_computer/assets/app_icon.ico`
- `upper_computer/assets/app_icon.png`

以下内容不进入主程序包：

- `upper_computer/models/`
- `upper_computer/runtime/`
- `upper_computer/exports/`
- `*.gguf`
- 旧 DearPyGui 可视化路径

## AI 本地模型

本地 Jina embedding 仍采用外置部署：

- 有网环境：在 AI 设置中点击 `在线部署`。
- 无网环境：提前准备 `EchoGuard-AI-Runtime.zip`，在 AI 设置中点击 `导入离线包`。
- 现场离线包结构和常见错误见 `docs/local_jina_deployment.md`。

不要把 GGUF 模型、`llama-server.exe` 或 `EchoGuard-AI-Runtime.zip` 提交到 GitHub。

## 打包后验收

启动 `dist\EchoGuard\EchoGuard.exe` 后检查：

- 窗口标题、任务栏名称和图标均为 `EchoGuard`。
- 侧边导航图标和太阳/月亮主题按钮正常。
- Gateway 串口可刷新、连接、显示最新帧。
- 节点收到数据后自动出现在仪表盘、节点管理、分析、历史和诊断页。
- CSV 导出、CSI 曲线截图、整窗截图可写入 `upper_computer/exports/`。
- 无本地 Jina 或 API 时，AI 区域保持规则回退，不影响主界面运行。
