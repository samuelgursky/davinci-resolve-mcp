# DaVinci Resolve MCP 服务器

[English](README.md) | 简体中文

[![Version](https://img.shields.io/badge/version-2.95.3-blue.svg)](https://github.com/samuelgursky/davinci-resolve-mcp/releases)
[![npm](https://img.shields.io/npm/v/davinci-resolve-mcp.svg?label=npm&color=CB3837)](https://www.npmjs.com/package/davinci-resolve-mcp)
[![API Coverage](https://img.shields.io/badge/API%20Coverage-100%25-brightgreen.svg)](docs/reference/api-coverage.md)
[![Tools](https://img.shields.io/badge/MCP%20Tools-34%20(353%20full)-blue.svg)](#服务器模式)
[![Advanced](https://img.shields.io/badge/Advanced%20(offline)-18%20tools-blueviolet.svg)](#服务器模式)
[![Tested](https://img.shields.io/badge/Live%20Tested-93.6%25-green.svg)](docs/reference/api-coverage.md#test-results)
[![DaVinci Resolve](https://img.shields.io/badge/DaVinci%20Resolve-18.5+-darkred.svg)](https://www.blackmagicdesign.com/products/davinciresolve)
[![Python](https://img.shields.io/badge/python-3.10+-green.svg)](https://www.python.org/downloads/)
[![License](https://img.shields.io/badge/license-MIT-blue.svg)](https://opensource.org/licenses/MIT)

> 本翻译对应 v2.95.3 版 README。如与英文原版有出入，以 [英文原版](README.md) 为准。

一个 Model Context Protocol (MCP) 服务器，让 AI 助手通过官方脚本 API 控制 DaVinci Resolve Studio（达芬奇）。它提供完整的 API 覆盖，外加带护栏的工作流助手，涵盖剪辑、媒体池整理、渲染设置、审阅标记、调色、Fusion、Fairlight、项目生命周期任务、扩展开发，以及不碰源媒体的媒体分析。

[![本地控制面板](https://raw.githubusercontent.com/samuelgursky/davinci-resolve-mcp/main/docs/images/control-panel/01-overview.png)](docs/guides/control-panel.md)

服务器自带一个本地浏览器控制面板，用于查看 Resolve 状态、运行源媒体安全的分析、深入查看已分析的片段与镜头、以及在线编辑分析结果。完整导览见 [控制面板指南](docs/guides/control-panel.md)。

## 快速开始

```bash
npx davinci-resolve-mcp setup
```

连接之前，先打开 DaVinci Resolve Studio，把 **Preferences > General > External scripting using** 设为 **Local**。（**免费版**上这个偏好设置不起作用——见下文 [免费版](#免费版应用内桥接)。）npm 启动器会在你的用户应用数据目录下安装一份托管副本，然后运行通用 Python 安装器。安装器会创建虚拟环境、检测 Resolve 路径，并可自动配置 Claude Desktop、Claude Code、Cursor、VS Code、Windsurf、Zed、Continue、Cline、Roo Code、OpenCode 和 JetBrains 系列 IDE。

从源码安装：

```bash
git clone https://github.com/samuelgursky/davinci-resolve-mcp.git
cd davinci-resolve-mcp
python install.py
```

各平台路径、客户端专属配置和手动安装步骤，见 [安装与配置](docs/install.md)。

安装器和服务器会检查 GitHub 最新 release 是否有 MCP 更新。检查是尽力而为且有节流的；服务器绝不会为了弹提示而阻塞 MCP 启动。安装器支持提示更新、稍后再问、忽略某个版本、关闭检查，或对干净的 git checkout 启用可选的安全自动更新。

## 免费版（应用内桥接）

Blackmagic 把*外部*脚本控制限定给了 Studio 版：在免费版上，无论偏好设置怎么调，`scriptapp("Resolve")` 都会拒绝外部进程。但 **Workspace ▸ Scripts** 菜单不受此限制——从该菜单启动的脚本在任何版本上都能拿到活的 `resolve` 对象——所以服务器可以通过一个在 Resolve *内部*运行的小脚本触达免费版：它把 `resolve` 对象经由一个带认证的本地回环监听器重新导出。

```bash
python scripts/install_resolve_bridge.py
# 重启 Resolve，打开一个项目，然后：Workspace > Scripts > resolve_bridge
```

监听器一旦运行，只要外部脚本控制不可用，服务器就会**自动**使用它——无需设置任何环境变量。设置
`DAVINCI_RESOLVE_BRIDGE=1` 则是*强制*走桥接：它会成为唯一尝试的传输方式，因此桥接一旦停止响应会
直接报错，而不会悄悄回退到其他传输。当你明确要依赖桥接时使用它。

在 **macOS** 上，Resolve 只在两个位置查找 Python 3：环境变量 `PYTHON3HOME`，然后是 `/usr/local/bin/python3`。Homebrew、pyenv、uv、conda 都不装在这两处，因此脚本会静默地不出现在菜单里。python.org 安装包之所以有效，是因为它的安装程序会创建 `/usr/local/bin/python3`——但你并不需要它：直接把 Resolve 指向你已有的解释器即可，无需 `sudo`。

```bash
launchctl setenv PYTHON3HOME "$(python3 -c 'import sys; print(sys.prefix)')"
```

必须用 `launchctl setenv` 而不是 `export`——Resolve 从 Dock 启动，看不到你 shell 的环境变量。之后重启 Resolve。安装时会顺带装一个 Lua 金丝雀脚本，帮你区分"Python 未被检测到"和"目录放错"。

已在免费版 21.0.3.7 和 Studio 19.1.3.7 上验证（均为 macOS）。v2.70.1（issue #106）加入的 Windows 路径发布时未经验证；后续免费版 21.0.1.11（issue #109）和免费版 21.0.3.7（issue #112）的用户报告证实，Windows 11 上桥接在 `%PROGRAMDATA%` 和 `%APPDATA%` **两处**都能安装、列出并正常服务，这些路径现在是已证实而非假设。Linux 同样已获证实：免费版 20.3.2.9 的用户报告（issue #129，Fedora 43）显示桥接可安装到 `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility`，用系统 Python 就能直接枚举脚本（Linux 完全没有这套查找问题），并能端到端正常服务。现在没有任何平台停留在假设上：macOS 为本项目直接验证，Windows 和 Linux 来自用户报告。

注意：桥接在服务期间会一直占用端口。v2.70.3 之前，Windows 上的桥接可能在 Resolve 退出后存活，挡住下一个会话的监听器；如果你用的是旧版本且桥接不响应了，检查是否有残留的 `fuscript.exe` 还占着端口。

这是走官方文档记载的应用内路径，不是绕过授权，但 Blackmagic 有可能封掉它——请把它当作"支持到不支持为止"的档位。仅限本地回环，请求带 HMAC 签名，nonce 一次性使用。

## 本地控制面板

从仓库根目录启动单用户本地控制面板：

```bash
venv/bin/python -m src.control_panel
```

该命令启动一个 localhost 服务器并在浏览器中打开控制面板。想让 AI 编码助手代劳，可以说：**"Open the Resolve MCP control panel for this repo."** 除非你的 Python 环境已激活，否则 agent 应使用 `venv/bin/python -m src.control_panel`。持久化的分析任务在切片成功后会自动刷新本地搜索索引；手动的 Build Index 按钮用于从已有报告重建索引。

## 服务器模式

| 模式 | 入口 | 工具数 | 适合谁 |
|------|------|--------|--------|
| Compound（复合） | `src/server.py` | 34 | 大多数助手的默认模式。相关的 Resolve 操作按 action 参数分组，压低上下文占用。 |
| Full / granular（细粒度） | `src/server.py --full` 或 `src/resolve_mcp_server.py` | 353 | 想要"一个 Resolve API 方法 = 一个 MCP 工具"的重度用户。 |

除非你明确需要一方法一工具的细粒度界面，否则推荐复合模式。

### Advanced 服务器——超出脚本 API 的部分（可选，Node）

同一个包还带了第二个可选的 MCP 服务器：**`davinci-resolve-advanced-mcp`**（可执行文件 `bin/davinci-resolve-advanced-mcp.mjs`）。Python 服务器通过官方脚本 API 驱动一个*活着的* Resolve，而 advanced 服务器做的是 API **做不到**的事——直接读写 Resolve 的**文件**（`.drp` / `.drt` / `.drx`），在**没有 Resolve 运行**的情况下做数据库/XML 层面的修改，所以云端和本地都能跑。共 18 个工具：`drp`、`drt`、`drx`（逐片段调色编解码，**外加一套确定性的离线调色/QC 目录**——同机位 + 跨机位肤色匹配（v2 肤色线指标）+ B-roll + 中性色块白平衡匹配、参考帧匹配、饱和度/黑平衡、对比度归一化、ASC CDL 导入、无损调色迁移 + 季度风格创作、命名 LUT 挂载、示波器读数 + 意图标签、调色验证、显示参考的帧提取、广播安全 QC）、`offline_ref`、`conform`（帧级基准的套底/重链 QC + 血缘追踪）、`color_trace`（重新套底后带着调色走）、`fusion`、`audio_plan`、`fairlight`（总线路由）、`audio`、`project_read`、`project_db`、`pipeline`（**以数据库为真源的管线**：把 YAML 项目规格编译成规范化 SQLite 数据库，再按阶段执行，带关卡、溯源和"意图↔实际"漂移检测）、`capabilities`、`deliverable`（交付 QC / 合规）、`media`（媒体前端 / AE 摄入）、`editorial`（剪辑完整性 / 变更清单）、`provenance`（溯源 / 审计 / 单集报告）。它还可以**作为库**使用（可导入的引擎 API），不只是当服务器起。

DRX 调色写入**针对 Resolve Studio 做过实机校准**：调色参数默认采用 Resolve 屏幕面板上的单位（`space: 'ui' | 'drx'`），结构性写入（Power Window、限定器、HDR 分区、HSL 曲线、ColorSlice、模糊/键控/运动特效）都经过面板回读验证——每个控件的状态见 `resolve-advanced/vendor/drx-parameters/CALIBRATION-STATUS.md`。它还补上了一个 UI 独占的缺口：**程序化"整理节点图"**（`drx` 的 `relayout` 处理单个片段，`project_db` 的 `relayout_node_graphs` 处理整个项目）——节点布局整理好，调色内容逐字节保留。

把它和实时服务器并排配置（两者都在同一次 `npm install` 里）：

```json
{
  "mcpServers": {
    "davinci-resolve": { "command": "<python>", "args": ["<path>/src/server.py"] },
    "davinci-resolve-advanced": { "command": "node", "args": ["<path>/bin/davinci-resolve-advanced-mcp.mjs"] }
  }
}
```

`install.py` 会把两个配置条目都打印出来。核心是纯 JS/MIT，无必需的原生模块；少数功能需要用户自装工具（`audio` 需要 ffmpeg，部分路径需要 `sharp`/`better-sqlite3`）——调用 `capabilities` 工具可查看实时状态和安装提示。

### Bradford Post Assistant——托管应用（封闭测试中）

维护者还在这个开源基础之上构建了 **Bradford Post Assistant**，一款桌面应用。MCP 服务器给了 agent 一双手，Post Assistant 则是围绕这双手的工作副驾——一个面向后期制作的本地 AI 助手，客户素材永不离开工作站：

- **后期制作副驾**——一款伴随 DaVinci Resolve 的桌面应用，实时观察会话（时间线、调色和画面帧——不只是 API 调用），内置 AI 助手与 agent 运行时、本地媒体分析（转写、帧分析、剪辑智能）和应用内套底 QC。
- **记忆**——持久化、加密的本地助手记忆，外加从你管线的解码事实中挖掘的跨集学习（季度风格漂移、按机位的校色先验、主帧库、套底路径映射复用），积累过程托管，并有一套"洞察须经审核"的工作流。
- **开箱即用的设计**——Post Assistant 自己接好一切：用本 MCP 控制 Resolve，用 Bradford API 提供扩展服务，LLM 供应商由你选。无需手动配置，无需管理独立客户端，应用连同内置 MCP 通过签名自动更新保持最新。
- **扩展专业工具集**——对在线项目做调色手术、22+ 自适应调色家族、精选风格库、交付规格校验、剪辑节奏/清理分析、自然语言调色指令、Fusion 合成创作——通过托管的 Bradford API 交付。
- **生产级工作流**——把原始工具组合成完整的真实流程（交接 → 套底 → QC → 交付、季度风格延续、单集报告），带上客户导向工作室所需的护栏与审批。

目前处于**封闭测试**阶段——可在 [bradfordoperations.com/software/post-assistant](https://www.bradfordoperations.com/software/post-assistant) 申请访问。开源服务器自身是完整且功能齐全的。

## 你可以做什么

```text
"列出所有项目，打开叫 'My Film' 的那个"
"用当前 bin 里的全部片段创建一条叫 'Assembly Cut' 的时间线"
"从选中的机位角度搭一条多机位预备时间线，源媒体保持不动"
"检测 2-pop 或场记板拍板声，为同步准备给出 record 偏移建议"
"把分析摘要、关键词、人物和场记提示发布到 Resolve 片段元数据"
"探测这条时间线的缝隙、重叠、丢失媒体和源帧范围"
"安全导入这个图像序列，整理进 bin，并规范化片段元数据"
"搭一个 ProRes 422 HQ 渲染计划，校验设置，然后排队任务"
"把审阅标记从时间线复制到选中片段，并导出审阅报告"
"给这个片段的调色拍快照，校验 CDL 更新，导出临时 LUT"
"在选中片段上创建 Fusion TextPlus 叠加层并验证节点连接"
"报告音频通道映射、人声分离可用性和字幕支持情况"
"安装这个带 MCP 标记的 DCTL 或脚本，分类刷新/重启需求，然后移除它"
```

## 核心能力

| 领域 | 复合服务器支持的内容 |
|------|----------------------|
| 应用与项目控制 | 启动/重连、页面切换、项目增删改查、项目文件夹、数据库、云项目封装、设置、预设、归档 |
| 媒体池与摄入 | 安全导入、图像序列、多机位预备时间线、bin 整理、元数据规范化、元数据字段清单、标记、注释、重链/代理/全分辨率护栏 |
| 媒体分析 | 源媒体安全的文件/片段/bin/项目分析，2-pop/场记板同步事件检测，默认写回 Resolve 元数据与媒体池标记，持久化分析产物，复用既有报告，host_chat_paths 视觉分析（每个片段以 `commit_vision` 定稿，任何具备视觉能力的 MCP 客户端都可用）可选退出，转写可选退出 |
| 时间线剪辑与套底 | 轨道/条目探测、标题文字键扫描/写入、复制/移动/克隆助手、区间操作、缝隙/重叠、源范围、带检查的交换格式导入导出 |
| 审阅注释 | 时间线/条目/片段标记、自定义数据、旗标、片段颜色、复制/移动/同步清理、审阅报告、标记缩略图审阅 |
| 调色 | 节点图探测、CDL 校验、调色复制、DRX/LUT 助手、版本、Gallery 静帧、调色组 |
| Fusion | 时间线条目合成、安全工具创建、输入写入、端口检查、带校验的连接、限定范围的批量写入 |
| 音频与 Fairlight | 轨道/条目探测、源映射、带护栏的音频属性写入、人声分离、自动同步规划、转写/字幕探测 |
| 渲染与交付 | 格式/编解码矩阵探测、渲染设置校验、队列任务生命周期检查、带护栏的快速导出 |
| 扩展开发 | Fuse、DCTL、ACES DCTL 及 Resolve 页面 Lua/Python 脚本生命周期助手，带 MCP 标记的安全安装/移除 |

## 可选增强

核心安装刻意保持精简：Python、ffmpeg 和 Resolve 脚本 API。有些功能需要更多依赖，且**每一项都会诚实拒绝并给出自己的安装命令，而不是退化成瞎猜**——编造的节拍或虚构的电平会产出自信但错误的结果，比没有这个功能更糟。

运行 `python scripts/doctor.py` 查看你已具备哪些。

| 增强项 | 解锁什么 | 许可证 |
|---|---|---|
| PATH 里的 **ffmpeg** | 静音检测、死气口标记、电平测量、音频分析。装一个东西收益最大的就是它。 | LGPL/GPL——以子进程调用，绝不捆绑 |
| `pip install numpy` | 色彩预平衡、参考静帧匹配、声音密度审计 | BSD |
| `pip install librosa` | 节拍、小节和乐句检测，用于跟音乐剪辑 | ISC |
| `pip install -U openai-whisper` | 转写，及一切基于词级时间戳的功能 | MIT |
| `pip install open_clip_torch` | 视觉相似度与 `find_similar` | MIT |
| `pip install transformers` | CLAP 音频嵌入 | Apache-2.0 |
| `pip install opencv-python` | 额外的帧分析 | Apache-2.0 |

`media_analysis` 的 `capabilities` action 会详细报告分析栈状态，并告诉你每个缺失项装上后能解锁什么。

**这里没有任何东西是捆绑的。** 模型权重的许可证独立于加载它们的代码；商用前请自行核查。

## 这个工具不做什么

知道一个工具的边界在哪，和知道它能做什么一样值钱——在这里读到，比在项目做到一半时才发现便宜得多。

| 不支持 | 原因，以及你能得到什么 |
|---|---|
| **挑选最佳条次** | 表演是决定一条好坏的大头，而这些从波形或转写里都量不出来。`rank_takes` 排的是*流畅度*——填充词、重来、稿子覆盖率——并在每次响应里说明这一点。最终用的那条常常是最不流畅的一条，因为迟疑往往正是表演。用它找干净的保底条，别用它挑读法。 |
| **跟音乐剪辑** | 还没有节拍/强拍检测。语音驱动的工具会把音乐床读成一整个长区域，用错了工具。 |
| **评判剪辑好坏** | 这里没有任何东西对"这一刀剪得好不好"持有观点。正因如此，一切破坏性操作都走 计划 → 审阅 → 确认。 |
| **取代剪辑师** | 输出是助理剪辑意义上的初剪：摄入、同步、整理、串片、标记问题。它是给你继续剪的起点，不是成片。默认参数刻意**宽松**——初剪本来就该偏长，因为往下修快且看得见，而找回已丢弃的素材慢且看不见。 |
| **修改你的源媒体** | 设计如此，无例外——见下文。 |

任何分析过但无法验证的内容都报告为未验证，绝不折叠进"没问题"。空结果的意思是"没找到"，绝不是"没什么可找"。

## 源媒体安全

本项目将摄影机原始素材和源媒体视为不可变。分析工具只读源文件，报告只写到 sidecar、临时或项目分析目录；确认后的元数据发布只写入 Resolve 的项目数据库。除非用户明确要求，服务器不得修改、转码、代理化源媒体或生成其衍生物。详细的源媒体安全工作流见 [媒体分析指南](docs/guides/media-analysis-guide.md)。

## 安全态势

默认服务器是由你的 MCP 客户端启动的本地 stdio 进程；它不暴露网络监听器，也没有内置多用户认证面。工具元数据包含面向 MCP 客户端的安全提示（只读、破坏性、幂等、外部资源操作）。操作边界、确认指引和漏洞报告见 [安全策略](SECURITY.md)。

## 关键数据

| 指标 | 数值 |
|------|------|
| MCP 工具 | **34** 复合 / **353** 细粒度（实时服务器） |
| Advanced（离线）工具 | **18**——.drp/.drt/.drx + 数据库创作，无需 Resolve 运行 |
| 内核 action | 9 个复合工具下 **136** 个带护栏的工作流 action |
| API 方法覆盖 | **361/361**（100%） |
| 实机测试方法数 | **338/361**（93.6%） |
| 实机测试通过率 | **338/338**（100%） |
| 测试环境 | DaVinci Resolve 19.1.3 Studio + 20.3.2 Studio + 21.0.2 Studio + 21.0.3 **免费版**（经内置桥接） |

逐方法状态见 [API 覆盖与测试结果](docs/reference/api-coverage.md)。当前工作流支持见 [内核 action 覆盖](docs/kernels/README.md)。

`analyze_media` 默认直接执行，在分析根目录下持久化可检查的报告/产物，通过 `host_chat_paths` 协议请求宿主对话做视觉分析（analyze 返回帧的绝对路径 + JSON schema；宿主对话把每帧当图像读取，然后调用 `media_analysis(action="commit_vision", ...)` 定稿），用配置好的本地后端跑转写，并把分析摘要和源时间的媒体池片段标记写回 Resolve 项目。只有想退出这些默认行为时才传 `include_visuals=false`、`include_transcription=false`、`publish_metadata=false`、`timed_markers=no` 或 `dry_run=true`。跳过 `commit_vision` 会让运行停在 `pending_host_vision_analysis`——它会被呈现为一种失败模式，不会被静默降级。

## 文档

| 文档 | 用途 |
|------|------|
| [安装与配置](docs/install.md) | 系统要求、安装器选项、支持的客户端、服务器模式、手动配置 |
| [API 覆盖与测试结果](docs/reference/api-coverage.md) | 关键数据、API 覆盖表、实机测试状态、完整方法参考 |
| [内核 action 覆盖](docs/kernels/README.md) | 当前带护栏的工作流 action 地图 |
| [AI Skill 参考](docs/SKILL.md) | AI 助手使用复合服务器的操作上下文 |
| [控制面板指南](docs/guides/control-panel.md) | 本地浏览器面板导览：Overview、Review（bin/片段/镜头）、Analyze、Setup、Preferences |
| [媒体分析指南](docs/guides/media-analysis-guide.md) | 源媒体安全的 FFprobe、FFmpeg、Whisper、sidecar 与分析根目录工作流 |
| [多机位设置助手指南](docs/guides/multicam-setup-guide.md) | 堆叠时间线准备、助手/API 边界、Resolve UI 转换步骤 |
| [剪辑决策指南](docs/guides/editorial-decision-guide.md) | 项目自有的剪辑手艺指引，用于分析与时间线决策 |
| [套底 Avid AAF](docs/guides/conforming-an-avid-aaf.md) | 为何三条 Resolve 原生路径在合并交接上全部失败，以及哪条最危险 |
| [调色决策指南](docs/guides/color-decision-guide.md) | 项目自有的校色指引与 Resolve 调色 API 边界 |
| [贡献与项目布局](docs/contributing.md) | 贡献流程、平台支持、安全说明、仓库结构 |
| [安全策略](SECURITY.md) | 本地 stdio 信任边界、工具元数据、确认指引、漏洞报告 |
| [发布流程](docs/process/release-process.md) | 维护者发布清单、版本面、验证、标签与发布说明 |
| [更新日志](CHANGELOG.md) | 历史发布说明 |

扩展开发参考在 [docs/authoring](docs/authoring/)。Resolve 开发者包笔记在 [docs/notes](docs/notes/) 和 [docs/integrations](docs/integrations/)。提示词配方在 [examples](examples/)。

## 系统要求

- DaVinci Resolve 18.5+，macOS、Windows 或 Linux。**Studio 版**直接支持外部脚本。**免费版**不支持——Blackmagic 把外部脚本限定给了 Studio——但仍可通过 [应用内桥接](#免费版应用内桥接) 触达，它从不受限的 **Workspace ▸ Scripts** 菜单在 Resolve 内部运行。
- Python 3.10+（3.10-3.12 风险最低）。Python 3.13/3.14 在较新的 Resolve 构建上也能用（已在 Studio 20.3.2 验证）；旧构建在 3.13+ 上可能连不上，此时请用 3.10-3.12。
- Resolve 外部脚本设为 **Local**（Studio 版）。免费版上这个偏好设置无效——请改用 [应用内桥接](#免费版应用内桥接)。

Resolve 19.1.3 仍是兼容性基线。Resolve 20.x 的脚本调用是增量式的、带版本护栏的，并已在 20.3.2 上实机测试。Resolve 21.0 新增的脚本能力（音频分类、说话人检测转写、IntelliSearch、场记板分析、运动去模糊、语音生成、会话后台任务控制）通过运行时能力检测暴露，在旧构建上保持沉默，在 Resolve 21+ 上自动激活。它们已在 Studio 21.0.2.4 上实机测试——见 [Resolve 21 增量明细](docs/reference/api-coverage.md#resolve-21-delta-detail)。注意 `AnalyzeForIntellisearch`、`AnalyzeForSlate` 和 `GenerateSpeech` 各自需要单独下载的 AI Extras 包，而 Resolve 报告缺包的方式不一致（有的返回 `False`，有的返回错误字符串），所以这些 action 会带着 Resolve 给出的原因报告 `success: false`，而不是瞎猜。

## 开发

```bash
python src/server.py          # 复合服务器
python src/server.py --full   # 细粒度服务器
venv/bin/python tests/test_import.py
venv/bin/python scripts/audit_api_parity.py
```

发布与验证规则在 [docs/process/release-process.md](docs/process/release-process.md)。在本仓库工作的 AI agent 请从 [AGENTS.md](AGENTS.md) 开始；Claude Code 用户也可读 [CLAUDE.md](CLAUDE.md)，它指向同一份规范说明。

## 许可证

MIT

## 作者

Samuel Gursky (samgursky@gmail.com)
- GitHub: [github.com/samuelgursky](https://github.com/samuelgursky)

## 致谢

- Blackmagic Design 的 DaVinci Resolve 及其脚本 API
- Model Context Protocol 团队让 AI 助手集成成为可能

## 关于本翻译

由社区贡献者 [@chenyuxiaojin](https://github.com/chenyuxiaojin) 翻译并随英文 README 的变更维护。发现翻译问题请提 issue 或 PR。
