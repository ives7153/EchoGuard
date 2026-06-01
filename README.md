# wifi-csi-lora-rescue

基于 ESP32-S3 的 WiFi-CSI 穿墙/遮挡生命微动感知与 LoRa 感传分离救援原型系统

本项目面向地震、坍塌、废墟遮挡等应急救援场景，构建一套基于 ESP32-S3 的 WiFi-CSI 生命微动感知、LoRa 远距离回传与上位机可视化研判的低成本感传分离救援原型系统。

## 目录结构

```text
wifi-csi-lora-rescue/
|-- .devcontainer
|   |-- devcontainer.json
|   +-- Dockerfile
|-- .vscode
|   |-- c_cpp_properties.json
|   |-- launch.json
|   +-- settings.json
|-- docs
|   +-- readme.md
|-- firmware
|   |-- gateway
|   |   |-- main
|   |   |   |-- CMakeLists.txt
|   |   |   +-- main.c
|   |   |-- CMakeLists.txt
|   |   |-- sdkconfig
|   |   +-- sdkconfig.defaults
|   +-- node
|       |-- main
|       |   |-- CMakeLists.txt
|       |   +-- main.c
|       |-- CMakeLists.txt
|       |-- sdkconfig
|       +-- sdkconfig.defaults
|-- hardware
|   +-- readme.md
|-- scripts
|   +-- readme.md
|-- tests
|   +-- readme.md
|-- upper_computer
|   |-- ai
|   |   +-- __init__.py
|   |-- rules
|   |   +-- __init__.py
|   |-- utils
|   |   +-- __init__.py
|   |-- viz
|   |   +-- __init__.py
|   |-- __init__.py
|   |-- data_parser.py
|   |-- main.py
|   |-- requirements.txt
|   +-- serial_handler.py
|-- .clangd
|-- .gitignore
|-- partitions-8Mib.csv
+-- README.md
```

## 快速启动指南

### 硬件准备

- ESP32-S3-DevKitC-1 N8R8 开发板，至少 2 块：1 块作为 Gateway，1 块或多块作为感知节点。
- Ra-02/SX1278 LoRa 模块，Gateway 与每个节点各 1 个。
- LoRa 匹配频段天线，上电和发射前必须安装。
- 节点侧可接入 SHT30、MPU6050、MQ-135 等环境与姿态传感器。
- USB 数据线、杜邦线、面包板或焊接底板、稳定 5V 电源。
- 详细接线、自检与常见硬件问题见 `hardware/readme.md`。

### ESP-IDF 环境

本项目 ESP32-S3 固件使用 ESP-IDF v5.3.2。

```powershell
idf.py --version
```

建议确认输出版本为 ESP-IDF v5.3.2，并确保 `idf.py` 已加入当前终端环境。

### Gateway 烧录命令

```powershell
cd firmware\gateway
idf.py set-target esp32s3
idf.py build
idf.py -p COMx flash monitor
```

其中 `COMx` 替换为 Gateway 开发板实际串口号，例如 `COM5`。

### 节点烧录命令

```powershell
cd firmware\node
idf.py set-target esp32s3
idf.py menuconfig
idf.py build
idf.py -p COMx flash monitor
```

其中 `COMx` 替换为节点开发板实际串口号，例如 `COM6`。每个实体节点烧录前，需要在
`menuconfig -> Rescue Node Configuration -> Rescue node ID` 中设置唯一编号，
例如 4 个节点分别设置为 `1 / 2 / 3 / 4`。Gateway 串口输出中的 `id` 会直接作为
上位机的 `node{id}` 显示和多节点交叉研判依据。

### 上位机运行命令

```powershell
cd upper_computer
pip install -r requirements.txt
python main.py
```

## 项目阶段

- Phase 0：项目初始化与需求拆解，明确救援场景、系统边界、目录结构和原型目标。
- Phase 1：硬件接线与上电自检，完成 ESP32-S3、LoRa 与传感器基础连通。
- Phase 2：感知节点固件开发，完成 WiFi-CSI 采集、传感器采集与 LoRa 上报链路。
- Phase 3：Gateway 固件开发，完成 LoRa 接收、数据汇聚与 USB 串口转发。
- Phase 4：上位机开发，完成串口接收、协议解析、数据可视化、规则判断与 AI 模块接入。
- Phase 5：系统联调与演示封装，完成穿墙/遮挡场景验证、问题闭环、文档整理和答辩材料准备。

## 团队分工

- 上位机：，重点完成 Python 上位机界面、串口接收、数据解析、可视化展示、规则判断和 AI 模块接入。
- 感知节点固件：负责 WiFi-CSI 采集、环境/姿态传感器采集、节点状态管理和 LoRa 数据发送。
- Gateway 固件：负责 LoRa 数据接收、节点数据汇聚、串口协议输出和联调日志支持。
- 硬件：负责 ESP32-S3、Ra-02/SX1278、SHT30、MPU6050、MQ-135、电源、天线与状态 LED 接线。
- 文档与测试：负责项目卡、阶段报告、实验记录、测试用例、联调记录和最终展示材料。

## 参考文档

- `hardware/readme.md`：硬件接线、上电自检、常见硬件坑点、电源与天线布局建议。
- `docs/interface_alignment.md`：上位机与固件接口一致性、节点自动发现、电池和气体字段说明。
- `docs/ai_auxiliary_judgement.md`：AI 辅助研判异步链路和实时规则边界说明。
- `docs/`：项目卡、阶段报告、答辩材料和实验记录模板。
