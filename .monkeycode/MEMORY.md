# 用户指令记忆

本文件只记录长期有效的行为规范、构建发布流程、排错方法和环境约束。项目实现细节以代码、测试和文档为准。

## 协作与质量

- Date: 2026-09-02（持续更新）
- Category: 工作流协作
- Instructions:
  - 简体中文回复；面向小白说明按"现象和影响 → 原因 → 可执行步骤"组织；日期时间一律用北京时间 (UTC+8) 表述并显式注明。
  - 改动前说明内容与原因；用户明确要求提交/推送后才执行，绝不擅自操作。直接在当前分支操作。
  - 每次代码改动后跑 `uv run quick-check`；提交前跑 `uv run check --skip-hook-install`。仅改 `docs/*.md` 或本文件时只需 `git diff --check`。**全绿判定"退出码 + grep 错误行"双确认**：`grep -E "\.py:[0-9]+: error|Found [0-9]+ error"` 无输出才算过（mypy 输出可能被 tail 截断、退出码 grep 漏检——CI 连挂三次的教训）。`scripts/` 也在 check 范围，入库前先格式化。
  - 提交前必看 `git status` 未跟踪文件：运行残留与中间产物不得 `git add -A` 入库，先 `.gitignore` 排除。
  - **模块级带值注解的版本差异**（CI 事故）：`x: T | None = None` 在 Python 3.13 立即求值、3.14 延迟（PEP 649）——本地 3.14 全绿掩盖 CI 3.13 NameError。模块级单例声明一律无注解赋值+注释。**"本地全绿≠CI 通过"的三个维度：输出截断 / 版本语义差异 / 平台差异**。
  - **Windows runner 的 GBK/charmap 解码陷阱**（20260905 发版首轮失败实证）：`subprocess.run(..., text=True)` 不显式给 `encoding="utf-8"` 时，Windows 默认 GBK 解码子进程输出，任何 UTF-8 字节（emoji/依赖 lint 输出/中文路径）都会抛 `UnicodeDecodeError: charmap` 炸掉整条链。同类修复此前只覆盖了测试脚本，build.py 漏同一族。所有跨平台 subprocess 调用一律 `encoding="utf-8", errors="replace"`。
  - 不装 pre-commit；提交前更新 `docs/changelog.md` **当前版本**条目（版本号归属用户，不擅自开新段）。用户要求改版本日期时**两处同步**：changelog 段标题日期 + `mdcx/consts.py` 的 `LOCAL_VERSION`（纯数字 YYYYMMDD，版本比较/更新检查/release tag 全读它）；无测试锁定该值，改动安全。changelog 写作规范（2026-09-05 瘦身实践）：用户视角的发布说明——保留议题号/现象/修复结果/影响，删根因排查叙事、测试细节、提交哈希；已发布历史版本段保持原样。
  - 站点/爬虫/配置改动同步检查：UI 文案（main_window.py/.ui）、README、docs、爬虫总数（`crawler_names()`）、**`config/migrations.py` 旧值清洗**（漏迁移 → pydantic 校验失败 → "保存不生效"）。
  - 文档/UI 写死数字前必须 grep 代码核实。高频漂移锚点：默认网站源顺序、代理域名列表（`Config.proxy_sites`）、命名变量表、设置 Tab 名、字段优先级数（`REDUCED_FIELDS`）、演员库列、指纹池、主窗口行数。
  - **长时间任务标准做法**：① `background_terminal_create` 后台终端；② checkpoint 断点续传（state 落盘）；③ 分批处理批间落盘；④ wrapper 45-50 分钟自重启（云环境超时杀进程；**后台终端 1 小时上限会连 wrapper 一起回收**——checkpoint 是唯一恢复手段）；⑤ 进度看落盘文件不看终端日志（stdout 全缓冲可能 0 字节假象）。
  - **功能移除类需求先调研证据再答**：查活跃度（近期 bug 修复/议题）、底层共享依赖（删壳删不干净）、移除成本（UI 整页+槽函数+重生成）。用户转述的声音与代码证据矛盾时以代码为准（Emby 管理器/NFO 库管理案例：调研"不建议删"被接受）。
  - **用户报告的"错误消息"可能不是错误，而是正常通知被误判**（#69 实证）：程序把「已移除配置项」的迁移警告当成校验失败触发 `_failed.json` 保护分支，用户被卡在"不能切换配置"。排查链路类故障时先验证报错消息本身是"真失败"还是"通知被误伤"——消息产生端（警告/错误共用返回通道）与消费端（`if 非空` 判定）各自都要查。
  - **议题定性前必须看完用户附上的全部证据，尤其每张截图**（#73 教训）：用户报告"网络检测异常就停止并长时间停止"，我依据日志文本定性为"启动自检误读"并加了引导文案，用户反馈"没解决"——回看才发现第一张截图（未查看）直接显示检测网络页跑到中途输出"网络检测出现异常："后整轮停止，主循环 `task.result()` 无兜底让单项逃逸异常炸掉整轮，是真 bug。**日志文本不是证据全集；附图必须逐张下载查看并与文本交叉验证**。定性为"用户误读"前要额外谨慎：误读判定等于断言"不存在 bug"，错判代价是真实缺陷被放过一轮。

## GitHub 议题处理

- Date: 2026-09-03（持续更新）
- Category: 环境配置
- Instructions:
   - devbox 本地跑测试的完整姿势：**环境重置后**才需要建环境（uv 已在 PATH 且 .venv 已存在时直接 `uv run`）——先 `pip3 install --break-system-packages uv` 再 `uv sync --frozen`；PyQt6 测试前装系统库 `libgl1 libegl1 libxkbcommon0 libdbus-1-3 libfontconfig1 libglib2.0-0`（缺 libGL 会 ImportError），且必须 `QT_QPA_PLATFORM=offscreen` 运行（不设则 `QApplication()` 创建即 qFatal abort，栈里看不到原因）。**devbox 镜像包索引是空的：apt 装任何系统库前先 `apt-get update`**（实测直装报 E: Couldn't find package，update 后正常）。
   - **background_terminal 用 sh（dash）解释器**，脚本含 `[[ ]]` 会报 `[[: not found` 且循环空转——后台脚本一律用 POSIX 语法（`case`/`grep`）或 `bash -c "..."` 包装。
   - CI（ci.yaml）有同款配置但 runner 是 Ubuntu、devbox 是 Debian 12，包名一致可直接照抄 CI 的 apt 列表。

- Date: 2026-08-29
- Category: 环境配置
- Instructions:
   - `gh` 自带 token 失效。正确姿势：`TOKEN=$(printf "protocol=https\nhost=github.com\n\n" | git credential fill | sed -n 's/^password=//p')` 再 `GH_TOKEN="$TOKEN" gh api ...`。`gh` 未登录（`gh auth login` 提示）时同样用此 token 走 curl 直连 API。`gh api user` 403 属正常（integration 无权限），仓库读写不受影响。凭据值禁止回显/落盘。
  - 议题截图（user-attachments/assets/xxx）直接 `curl -sL` 下载后用 Read 工具查看，无需认证；多图并行下载。截图是议题的主要证据源，不要跳过看图环节。
  - 同一报告人连续多议题时先横向看历史议题再定夺：诉求可能延续（#61 要求删功能 → #71 退让为隐藏入口），也可能与其他报告人冲突（#67 要求禁最大化 vs #69 要求恢复）——冲突时以代码证据和功能根因是否已修为裁决依据。
  - 用户一段描述里常夹带多个独立诉求（#70「代理问题 + 顺带要求删按钮」），回帖必须逐项回应，不遗漏。
  - 读议题优先 `gh api`；退化抓网页时评论正文从内联 JSON `"body"` 字段提取。未认证直连 api.github.com 撞 IP 级限流。
   - 回帖正确姿势（议题 #72/#73 实证）：**用 JSON POST**，`-d @/tmp/x.json` + `Content-Type: application/json`（`{"body": "..."}`，python3 打包）。**不要用 `-F body=@file`**——那是 multipart/form-data，评论接口返回 400。发送后 jq 验证 html_url。
   - 议题关闭：修复完整且用户明确要求才关。根因未清时保留 open，回帖写明"已修的解释什么/解释不了什么"+需报告人补充的信息+已排除假设清单。
   - **CI 状态查询两个坑**（#72 提交实证）：① push 后 workflow run 注册有几秒到 1 分钟延迟，立即查 `head_sha` 过滤会空手而归——改查不带过滤的 runs 列表再对 head_sha；② `?head_sha=` 查询参数过滤器本身不可靠（列表里有、过滤后没有），一律拉列表本地过滤。CI 排查：runs 列表 → jobs jq 定位 failure → job logs 落盘再 grep `\.py:[0-9]+: error`。同 head_sha 重跑会有两条记录看最新。

## 排查与本地验证

- Date: 2026-09-02（持续更新）
- Category: 排错调试
- Instructions:
  - **仓库根 `config.json` 是脏配置**（含已删站点值），验证配置/网络栈行为须用 `Config()` 默认配置写临时文件再指 `manager.path`。
  - 泄漏/累积类问题先写最小复现脚本量化（gc/asyncio.all_tasks 计数 + 对照实验区分"每次泄漏"与"泄漏一次钉住"）。
  - **行为修复"先复现测试跑红 → 修 → 绿"**；修复后反向审查边界与调用点语义。pytest-asyncio strict 模式：async 测试文件顶部须 `pytestmark = pytest.mark.asyncio`。
  - 结构约束类修复用 **AST 哨兵测试**锁定位置；写完拿修复前代码反向喂哨兵确认能判失败（防恒真）。注意 ast 无 `node.await` 属性——await 调用要找 `ast.Await` 包装节点。
  - conftest 用 dummy 替换了 `mdcx.config.manager`/`resources`/`signals`；独立验证脚本须 import mdcx 前手工注入同样 dummy。**dummy 桩加方法时同步更新 conftest 注释**（缺方法会以 AttributeError 形态在 Qt 测试里触发 qFatal abort）。
  - **subagent 排查要求输出"已排除假设清单+理由"**；标注"已验证"的结论不可直接采信（实证：22 项宣称 11 项编造/夸大），修复前必须独立复现脚本重现每一条。
  - **全库审查方法论（2026-09-04 两批 26 项修复实证）**：4 个 subagent 按域并行（并发网络/爬虫解析/配置持久化/核心业务）产出候选 → 逐项独立复现验证（可执行脚本复刻源码逻辑；纯逻辑用系统 python 快速 trace）→ 宣称 30 项验证后 19 项成立、3 项证伪（freejavbt `list.remove` 按值删 N 个同名恰好 N 次 remove 永不耗尽、iqqtv 双斜杠触发条件与宣称不符、curl_cffi 跨 loop 单 loop 架构下不可达）。**典型证伪形态：subagent 断言崩溃阈值/触发条件，独立复现时边界值行为与宣称不符——"3 次必崩"实测 5 次仍安全**。
  - **测试锁定 bug 时以文档语义为仲裁**（FILL_MISSING_ONLY 案例）：UI 名称/models description/docstring 三处一致而与实现矛盾、且两选项行为完全重复，判定实现错测试锁错，修实现同步反转测试断言。
  - **用户质疑审查结论时先验证触发链再降级**（FC2 案例）：subagent 说"FC2 番号会被分到 javbus"，人工质疑后追分类链——`classify_scrape_task` 对 FC2 强制走 website_fc2 组（不含 javbus/javlibrary），触发面收窄为单站模式/指定 URL/自定义列表，A 级降 B 级。触发链的每一环都要落实，"功能上可达"不等于"正常路径会走到"。
  - **conftest dummy 陷阱（M6 案例）**：测试断言依赖的属性可能被 conftest 的 `_DummyManager` 实例属性遮蔽（dummy.path 是实例属性，直接赋 `manager._path` 后断言读 dummy.path 仍返回旧值）；给真实 manager 加新方法时必须同步给 dummy 加同名方法，否则 AttributeError 以 qFatal 形态在 Qt 测试里爆。绕 dummy 验证真实模块用独立 `uv run python` 脚本（无 conftest 干扰）；模块内做 AST 哨兵测试比 importlib 加载真实模块文件可靠（相对导入会失败）。
  - **ruff B010/B009 与 mypy attr-defined 的组合**：动态属性读写（缓存挂到第三方 Response 对象上）需 `obj._x = v  # type: ignore[attr-defined] # noqa: SLF001` + `getattr(obj, "_x", None)  # noqa: B009`；`setattr` 常量属性被 B010 禁止。
  - **外部探测任务的错误监控先分类错误构成再设阈值**：404 在爬虫场景是"未收录"业务常态（DMM 实测事故：404 计入错误率 → 84%"异常" → 误降并发误回滚三轮折腾）。真实限流信号只有 403/429/连接异常。单 host 批量探测速率天花板是站点侧吞吐（awsimgsrc ~17 req/s），提速靠减少请求数而非加并发。
  - 大范围撤回用 `git revert --no-commit <多提交>` 合并单撤销提交。

## 并发与网络库行为（实测实证）

- Date: 2026-08-29
- Category: 排错调试
- Instructions:
  - **curl_cffi 0.16 流式关闭**：`aclose()` 会拉满剩余响应体（放弃 4MB 仍阻塞 3.5s）；同步 `close()` 立即中止。中止流后 session `close()` 抛库内 TypeError 属噪声（`_close_sessions` 有 suppress），后续请求复用正常。改动前看 `web_async.py::_close_response` 注释。
  - **asyncio 线程池归属**：`AsyncBackgroundExecutor` 后台循环的 default executor 与主 loop 的是两个池——"嵌套 to_thread 死锁"类判断先实测两池是否同一个。
  - **LogBuffer 任务树归因**：写入按 `_ROOT` contextvar 归因，`process_one_file` 入口 `new_root()` 切断兄弟继承。勿按 task_id 全局聚合、勿回退"get() 拼全局 buffers"旧模式（跨影片污染，测试锁定）。

## UI 开发与排错

- Date: 2026-09-02（持续更新）
- Category: UI 开发与排查
- Instructions:
   - 改 UI 先改 `.ui`（唯一权威源）→ pyuic **相对路径**编译（绝对路径会写进头部注释导致 `test_mdcx_py_in_sync_with_ui` 失败）→ `ruff format` → `tests/test_ui_structure.py`。禁手工改 MDCx.py。**devbox 上 `scripts/pyuic.sh` 会 `pyuic6: command not found`**（PATH 无独立命令），改用 `uv run python -m PyQt6.uic.pyuic mdcx/views/MDCx.ui -o mdcx/views/MDCx.py` + `uv run python scripts/fix_qt_enums.py` + `uv run ruff format`；.ui 与生成 .py 的文本同步由 test_ui_structure 锁定，任一侧漏改 CI 即红。
   - **`setVisible(False)` 只作用于 widget，`QSpacerItem` 是独立 layout item 不受控件显隐控制**（#72 真 bug 实证）：导航按钮间隔靠 7 个 8px 固定 spacer 实现时，#71 的隐藏入口开关只藏了按钮，spacer 残留叠出 16px 空洞且间距错乱。修法：删按钮间全部固定 spacer 改 layout `spacing=8`（Qt 对隐藏 widget 自动收紧），`test_ui_structure.py` 加回归锁定"导航布局不得再出现 spacer"。**新加隐藏开关时审计布局里所有非 widget 占位项**（spacer/stretch/label 摆设位），凡是 setVisible 管不到的都要换方案。
  - 主窗口全局绝对定位无布局管理器：长文本 QLabel 用 wordWrap 查 sizeHint；新增顶层控件纳入 resizeEvent 手动几何同步。
  - QComboBox 装饰后缀：`addItem(icon, 文本, UserRole 纯值)`，消费点统一 `currentData()` 取值；信号 handler 收文本须剥后缀。改动必查 currentText/itemText/currentData/信号连接/AllItems.index 全部点。
  - 打包前逐页切 stackedWidget 审计边界溢出（scripts/check_ui_layout.py、tests/test_ui_geometry.py）。
  - Qt 同名 API 重载签名不同，改前确认目标类签名；测试桩显式枚举属性方法（不用 __getattr__ 通配）。
  - **Qt 绝对定位缩放三连**（#62/#66/#68）：`setGeometry` 不触发子组件 resizeEvent（须 `resize()`）；QStackedWidget 只 resize 当前可见页（休眠页停设计尺寸，`currentChanged` 连 `_sync_page_layouts` 统一同步，**先 resize 所有 pages 再算内部几何**——顺序敏感）；`show_hide_logs` 类硬编码 resize 会覆盖动态同步，一律走统一同步函数。
  - **PyQt6 测试 qFatal abort**：槽函数未捕获异常触发 qt_assert 原生 abort（栈里无 Python 行号）——查 QTimer 槽与 dummy 桩缺方法。防御：fixture 构造后立即停全部 QTimer；几何断言不需 `window.show()`。**devbox 不设 offscreen 时 Qt 测试文件的 Fatal Python error: Aborted 是环境固有**（test_window_state_matrix 实测 stash 基线同 abort；`QT_QPA_PLATFORM=offscreen` 下全部通过；CI 正常）——先 stash 基线对照区分环境问题与改动引入，勿误判为改动引入回归。

## 站点与网络

- Date: 2026-08-27
- Category: 排错调试
- Instructions:
  - 各站探测番号与收录依据见爬虫类注释；javdb 仅搜 FC2 需要 Cookie。
  - 站点 API 坑：missav_api Recombee 仅 POST；DMM Affiliate v3 必需 site/service/floor 且 keyword 用 content_id 形态；madouqu 域名动态维护（24h 缓存）；madou_club 番号无横杠；parsel Selector.get() 纯 JSON 返回 dict，解析兼容 str/dict/Selector 三态。
  - 站点增删史：2026-08 删 15 站（48 → 33，失效/重复明细见 changelog），后新增 javfree/aventertainments/madou_club 与 getchu_dmm 合并进 getchu，**当前注册爬虫 35**（`get_registered_crawler_sites` 实测，FEATURES.md 同步）；恢复删站从 git 历史找回枚举/注册/默认源。
  - 无码官网五站由 official_uncensored.py 统一路由；均需代理；1pondo/pacopacomama/10musume 的 dyn/phpauto JSON API 直通。
  - 被墙站测试：`uv run python -m scripts.dev_proxy start|status|test <url>|stop`；日本 IP 限制站用 `--port 7891 --regions "jp|日本"`。
  - devbox 环境限制：超时属云端限制≠站点死亡；高频批量测试触发 CF IP 拉黑换时段；连通性验证必须 curl_cffi impersonate；批量探测校验 data.title 为真实字符串防假阳性。

## Windows 打包与发布

- Date: 2026-08-24
- Category: 环境配置
- Instructions:
  - 函数内延迟导入须同步加 scripts/build.py 的 --hidden-import/--collect-all；改依赖/构建脚本/Release 工作流逐项核对。
  - EXCLUDED_MODULES 中 rich/typer 等只供构建/CLI；Windows curl_cffi.libs 需显式 --add-binary。
  - Release 发版全自动流程：推送纯数字 tag（`git tag YYYYMMDD && git push origin YYYYMMDD`）触发 `release.yml`（macOS aarch64 + Windows x86_64 双构建 → 自动建 release 页，正文自动取 changelog 当前版本段）；发版前确认 `consts.py` 的 `LOCAL_VERSION`/`VERSION_NAME` 与 changelog 段标题一致、release 产物名规则 `MDCx-<tag>-<平台>-<arch>-<sha7>.<exe|dmg>`（Windows zip 版由 `package-trawl.yml` 单独管道）。

## 并发与数据

- Date: 2026-08-24
- Category: 构建方法
- Instructions:
  - 文件间批量用 asyncio.wait(FIRST_COMPLETED) 滑动窗口，文件内多站点 gather；网络请求不跨 executor loop 复用。
  - 后台协程统一 utils/qt_thread.py::run_in_background，结果经 Qt signal 回主线程；新增后跑 scripts/check_thread_safety.py。
  - 出厂模板在 resources/userdata/，运行时数据在 manager.data_folder/userdata/；devbox 代理 127.0.0.1:7890 可能无进程，排查网络临时关闭代理。

## 日亚 ASIN 数据库与校验方法论

- Date: 2026-09-02（治理工程收官重组）
- Category: 排错调试
- Instructions:
  - **证据强度排序定论**（全量校验工程实证）：**结构化映射（tenhow cid）> 唯一编码（EAN/JAN 条码）> 文本归一（标题 NFKC 系列互含）> 相似度分数（图像）**。cid 反查 367 行零误判；标题法 303+34 翻案零冤案（`core/title_match.py`）；图像法 367 行假阳性——重压缩分数带 0.74-0.89 与真错配 0.42-0.68 重叠，**图像只能兜底不能主证**（旧结论"标题比对不可用"已被推翻——那是原始子串比对时代，NFKC+系列主干互含后质变）。`_cover_similarity` 三元组，严格判定三阈值同满足：≥0.82/≥0.86/≥0.70。
  - **软校验架构定论**（读零校验+v2 裁决链，提交 32ac739/efb5f26）：免验/必验按**发现路径**分流——条码/EAN=hard 免验（唯一编码无相似性概念，再验是浪费且验错反伤）、ASIN 库命中=信任免验（库交付即 100% 验证过，用户无感知零配置）、软匹配（标题/演员搜索）=v2 三步链必验（cid 旁证→标题门+**真合集词一票否决**（BEST/コンプリート/N時間——图是多片拼盘；**特典/限定版不否决**：图仍是单片真图，唯一 ASIN 正常入库，同番号竞争时让位正品——`_decide_save_outcome` 三态：旧特新正→replace，其余跳过先到先得）→图像兜底）。**入库时序必须延迟到采信点**（搜索即写库让门槛形同虚设）。演员名兜底是错挂重灾区（候选全集=该演员所有作品），全链必走；主搜索路径标题证据复用搜索阶段已聚合文本（match_state 携带 title/search_keyword），零额外请求。
  - **运行库与出厂库现状**（2026-09-02 彻底收官）：**出厂库已升级**（`resources/userdata/amazon_asin_database.xlsx`）——主表 26620 行（标题法+cid 反查+人工裁决），同番号 ASIN 唯一、错配行清零、按番号严格升序+格式化；"待修正/DMM已覆盖归档/四源校验错配"三个治理 sheet 只在用户运行库、不入出厂库。**合并逻辑升级为"出厂库权威"**（`merge_asin_db_from_backup`）：同番号无条件覆盖用户库 5 列，用户库独有番号保留，出厂库独有番号追加。`_format_asin_worksheet` 内嵌按番号排序（`_asin_sort_key`），保存/合并/重排统一生效。
  - **待修正 sheet 清理三分类法**（2026-09-02 393 行治理实证）：① 主表已有番号一致 → 残留直接删；② 主表已有但番号不同 → 用主表番号去 libredmm/javbus 反查标题，与主表日亚标题比对裁谁对（36 行中 35 match 主表对、1 无数据待人工）；③ 主表未有 → 标题法/cid 反查裁决入库或标记真错。批量行**先按 ASIN 去重**再分类（待修正源表同 ASIN 因不同搜索词出现多行，35 个 cid ✓ ASIN 展开成 154 行）。
  - **ASIN 列污染教训**（2026-09-02 真 bug）：入库注记列索引错位——注记写到 ASIN 列（`B003CIPVJM [原挂:EBOD-108; ...]`污染 9 行，出厂库对比扫描才发现），本应是搜索关键词列。**列写入走显式列号映射/查表，不手数 index**；入库后 sanity check 一行 `r[1]` 应是纯 ASIN。
  - **出厂库（resources/userdata/）更新仍须用户明确确认**——本次扩容 26620 行也是用户传文件确认后才替换。
  - **评估库存价值先问"生产会不会走到那一步"**（用户方法论）：DMM 能给高清图（宽≥700）的番号其日亚记录无运行时价值——探测须按生产标准过滤 147x200 缩略图形态（10-19KB 恰过 4KB 阈值，取"第一个成功"会误判）。
  - **裁决图遍历全部候选取最高分**：同番号存在 digital 再版与 mono 原版双封面（ABF-008 两版都真）；同系列多集误挂同 ASIN 的低分是各集真实差距，不是错杀。
  - **番号规范化预检防假案**：缩位写法（ABF-34 vs ABF-034）会制造"自己和自己冲突"；比对一律 (系列字母, int(数字)) 做 key。批量导入 xlsx 必须走含去重入口（`save_asin_to_excel`），直接 ws.append 产生成批重复。
  - cid→番号规则：`^(\d*)([a-z]+)(\d+)([a-z]?)$` → `系列大写-{int:03d}`（绝不缩成 PED-30）；变体字母归并同番号。tenhow cid 离线索引 `resources/userdata/tenhow_asin_cids.json`（36441 条，`core/asin_cid_index.py` 三态裁决）。
  - **libredmm 归纳安全过滤教训**（提交 e0c98b7）：外部归纳数据接入前先在高频样本做候选顺序回归（覆盖率掩盖顺序污染）；防污染不弃真实增量——按"顺序影响"分级（append 兜底）而非二元弃用（GVG-564 的 mono 3 位真实数据曾被 v1 错杀）。
  - **DMM cid 结构**：前缀映射 + 数字双态（5 位补零 digital 与 3 位原样 mono **同系列可并存**）+ 双路径（digital/video 与 mono/movie/adult 各半）+ 变体后缀无需枚举。DMM 图床：站点下架但 CDN 不删对象；占位图 200+<4KB 已拒收（`_validate_dmm_image_url`）。
  - **日亚图域知识**：SL1500 商品图**物理无条码**（0/50，条码 OCR 只能从 DMM/爬虫侧封面联图拿——app 横版联图获取率 94%）；老商品标题用**半角片假名**（NFKC 必做）；日亚 DVD 封与 DMM digital 封**版本不同**，图像比对天花板 ~0.62。
  - tenhow.net 图床：`images/{ASIN}.jpg` 与日亚 SL1500 同源同分辨率，免代理直取（T0 优先，404 回退）；页面条目图名即可入库 ASIN（全站索引 36441 条）。旧索引 8126 条抓取残缺已作废。
  - 环境限制：DMM/fanza 地区锁；日亚 dp 页 devbox 直连 404 需代理；tesseract 对日系封面效果差不可作依据。
  - **HTTP 4xx 定位顺序**（#56）：先看客户端实际发了什么（条件分支误判覆盖鉴权头之类），再想服务端；同函数多调用点的硬编码分支改一处漏一处是高频错误形态。
  - **ASIN 校验工程散点教训**（2026-09-02 治理实证）：① 数据治理前先 `Counter` 关键列识别导入批次残留（title 全为 "tenhow" 的 367 行对标题反查=对错误对象用正确方法）；② openpyxl 迭代中 `delete_rows` 后行上移会跳行，稳定模式是一次读出→去重→清空重写；③ javbus 搜索不识别 ASIN，正查通道是番号→详情页标题→与日亚标题比对；④ 多源判定合并禁用 or 链（多源 dict 上 `src.get('a') or src.get('b')` 短路吞判定）；⑤ 外部 API 错误码 marker 取响应原文字面值；⑥ v2 裁决链覆盖 95%+，剩余待人工行给用户一句话解释差什么证据。

## javdb 系爬虫与图源

- Date: 2026-08-31
- Category: 排错调试
- Instructions:
  - **thejavdb_api 与 javdb 无关**（用户澄清），勿归入 javdb 系。
  - javdb 系三源：javdb（网页）/javdb_api（镜像站 573-575，偶发超时需重试轮换）/javdb_app（App API 免 CF 最稳）。App API 域知识来自**用户私有逆向仓库**，增量时用户会上传 README 到工作区；机制文档 `docs/JAVDB_APP_SIGNATURE.md`。
  - **图源无水印体系**：`tp.spfcas.com` App 专用无水印 CDN（单字节 XOR 加密流，首字节 key），`c0.jdbstatic.com` 网页版带水印。解密与双向变换集中在 `base/web.py`（`decode_spfcas_image_content`/`jdbstatic_to_spfcas`），下载层三路径自动生效。App CDN 路径中段会变，`learn_spfcas_image_segment` 由 javdb_app 响应学习自愈。**加密流尺寸探测 (0,0) 属预期**（auto_best 用逆向 URL 探测回退），勿当"图失效"。
  - javdb_app 排障锚点：签名失效=三主机同时 400/401/403 或 ParameterInvalid/InvalidSignature（fail-fast 已内建）；环境变量 `MDCX_JAVDB_APP_SIG_PREFIX/SIG_SUFFIX/VERSION_NUMBER` 免改码覆盖；搜索 limit≤50、type=movie，分页须 `movie_sort_by=release`（默认 relevance 不稳定会漏）。
