# Changelog

## v2.0.8 (2026-09-06)

### 修复

- **fanart 变临时文件且假报成功**（用户实测：正常刮削完成但只剩 `.fanart.jpg.xxx.tmp`，无 fanart.jpg）：thumb 复制为 fanart 时改名步骤被 Windows 瞬时占用挡下（杀软扫描/缩略图索引），复制失败——旧代码不查复制结果照打「Fanart done!」成功日志，表现为「一切正常但 fanart 缺失」。修复三层：①复制失败真实报错（不再假成功，两条复制路径同修）；②改名被挡自动重试 3 次（秒级占用自愈）；③每次刮削结束自动清理孤儿临时文件（形态精确匹配，不误删正常文件，清理结果进日志）
- **议题 #78 信息管理（NFO 库管理）页最大化布局三问题**：①最大化后表单右侧残留约 194px 空白（布局在休眠页 resize 时态下不激活，现 resize 时同步 invalidate+activate）；②最大化后再最小化「保存当前 NFO」消失（简介/标签多行框超视口挤压保存按钮，现将这两个多行框高度压至 60px——用户理性建议方向一致：配合垂直间距 4px 求得，保存按钮永远落在视口内、无需滚动）；③「下拉栏」纵向滚动条一并消除。简介/标签现压缩到与小字段同列，不再侵占整窗滚动高度

### 优化

- **全量检查提速 3 倍（146s → 45s）**：①javdb_app 测试 patch 反爬节流的随机 3-8s 真实等待（单条 40s → 0.5s）；②爬虫测试默认断网 check_url（DMM 图床升级链此前逐候选真实联网超时，15+ 条用例各拖 3.6s 且随网络环境抖动）——显式 mock 的测试不受影响，真网络验证走 network marker；③UI 几何测试归一：纯文本哨兵 test_ui_resize_sync（被行为测试完全覆盖）删除，最大化内容跟随用例并入窗口状态矩阵（115 → 113 个测试文件）

## v2.0.7 (2026-09-05)

### 修复

- **三页内容最大化后横向不跟随**（软件界面/软件工具/软件设置，Windows 原生边框与隐藏边框均受影响）：软件界面页 48 个绝对定位组件此前无任何缩放逻辑——宽幅控件（文件路径、分隔线）现拉伸贴右缘、右缘列（开始按钮/结果树/清空按钮）锚定右缘平移；工具/设置页滚动区视口虽跟随但内部宽幅表单组永远停在 860 设计宽、右侧大片留白——现于滚动区登记设计几何并随视口拉伸宽幅表单组（窄表单项保持原位，NFO 库窄表单自动跳过）
- **议题 #74 隐藏入口后间隙摊大的真根因**：前次按“spacer 残留”修复后间隙仍摊大（实测 8→22px）。实锤根因：导航容器的 layoutWidget 固定 380px 高而 QVBoxLayout 缺少底部 Expanding spacer，隐藏按钮后多余空间被摊进可见按钮间隙。修复：导航布局末尾加 Expanding spacer 吸收多余空间，隐藏后按钮保持紧凑的 8px 间距。新增 `test_nav_gap_uniform_when_entries_hidden` 实测锁定（show 后断言按钮间隙等于 spacing）
- **议题 #76 导航按钮改名**：「主界面」→「软件界面」、「日志」→「软件日志」、「工具」→「软件工具」、「设置」→「软件设置」，使用指南与快速上手文档同步。弹窗指引、错误提示等全部用户可见文案中的旧导航名同步统一（如「到设置-下载勾选…」→「软件设置」）
- **议题 #72 隐藏入口后导航间隙不齐 + 导航改名**：隐藏「演员管理」「信息管理」后按钮间残留 16px 空洞且间距不一致（按钮间的固定 spacer 不受隐藏开关控制）。改为布局统一间距，隐藏后剩余按钮间距自动恢复一致。导航按钮改名：「Emby演员管理」→「演员管理」、「NFO库管理」→「信息管理」
- **刮削速度退化的三层修复**①curl_cffi ctype 竞态 TypeError 一律重试，每次多耗 0.6-1.2s，逢库必中；现识别后不再重试。②前置学习表 CID 污染：mono/movie/adult 路径的老片前缀前缀（如 77ssis、88ssis）被错误归纳应用到新片，搜教程学习只有 digital/video 路径写入 `dmm_prefix_learned.json`。③路由表死链批量清理：libredmm 3745 个系列实测后确认 89.4%（3260）的纯 mono pad-3 组合返回占位图（已下架老物），不再可用——全部清理（删 2291 个系列、4501 个污染组合），用户可删除 `userdata/dmm_prefix_learned.json` 后立即见效
- **议题 #73 检测网络页中途异常中断**：检测跑到中途弹出「网络检测出现异常：」（空消息）后整轮停止，后续站点不再检测。根因有两层：① 主循环对单项任务的逃逸异常（如空消息的裸 TimeoutError）没有兜底；② 初次修复中对 CancelledError 的错误穿透——单个任务内部协程被底层取消后，冒泡到主循环又触发整轮终止。修复：主循环对所有异常统一软着陆，单项失败/取消各归该项不再炸整轮，异常携带类型名与 traceback「复制结果」可直接回传定位；空消息异常不再空白。启动自检开头另加范围说明（自检固定四项，全量检测请到「检测网络」页）
- **议题 #71 左侧导航入口可隐藏**：「设置 → 高级」新增「隐藏入口」开关，勾选后左侧导航对应入口即刻隐藏，取消勾选即恢复，保存后立即生效。仅隐藏入口，功能本身完整保留
- **议题 #69 恢复系统最大化按钮 + 修复「不能切换配置」**：① 恢复主窗口最大化按钮（#62/#66/#68 的最大化布局错乱根因已修，无需再禁用）；② 含旧配置键（如 `amazon_strict_pic_verify`）的配置迁移时，迁移警告被误判为校验失败，配置被误指 `_failed.json` 表现为"不能切换配置"——迁移警告与真校验错误分离标记，旧配置切换恢复正常
- **议题 #67 检测网络页按钮悬浮遮挡日志**：日志文本区下移避开顶部按钮；删除与设置页重复的「打开网络设置」按钮；「重试失败项」按钮缩放后不再散开
- **议题 #68 Windows 原生边框下缩放/切页布局错乱**：先缩放窗口再切页时，休眠页组件全部停留在设计尺寸（日志页大片空白、按钮飘出页面）。切页与缩放统一同步，所有页面跟随窗口尺寸
- **议题 #61 Emby 演员管理器与 NFO 管理体验**：演员管理器单例化（重复点击还原已有窗口，不再多开互相干扰）、独立顶层窗口（最小化进任务栏、最大化不再带出主窗口）；NFO 管理加「全选/全不选」按钮、长文本不再把保存按钮挤出可视区、禁用横向滚动条
- **议题 #32 Jellyfin/Emby 演员刮取系列修复**（真机验证四轮反馈）：Jellyfin 10.11+ 连接失败（补全 MediaBrowser 设备标识头）；Jellyfin 12 演员列表 401/超时（列表端点改走 `/Items`）；大媒体库统计超时只认到单库（`Limit=100000` 全量拉取改 500 条分页，单库失败只跳过不阻断）
- **议题 #56 Emby/Jellyfin 演员信息更新与图片上传失败**（Emby 4.9.5.0 真机）：401（Emby 分支鉴权头被条件分支置空）、400（POST 缺 Content-Type）、500（图片上传须 Base64 编码 body 而非原始二进制）三处修复
- **议题 #57 NFO 库管理三个症状**：保存后表单外字段不再丢失（从原数据继承）；简介只存 originalplot 时可正常读取；标签保存后顺序不再被重排；批量保存路径防御对齐
- **议题 #62 / #66 窗口最大化后内容不跟随缩放**：`_sync_page_layouts()` 统一同步绝对定位组件与非当前标签页，最大化/拖拽缩放后所有页面与 12 个设置 tab 正确跟随
- **议题 #55 保存设置/停止刮削后内存占满卡死**：停止刮削会误取消网络栈租约释放任务，租约永不归零导致保存设置时旧网络栈无限轮询累积。释放走关键任务通道不被取消 + 关闭轮询加 300 秒超时兜底；配置迁移补齐 2026-08 精简的 15 个旧站点值清洗（旧配置残留会整体校验失败表现为"保存不生效"）
- **议题 #53 整理模式演员名不映射中文**：演员/标签/系列映射服务于命名变量而非仅服务 NFO，与 update_nfo 解耦——整理模式下 `{actor}/{tag}/{series}` 等命名变量输出中文名
- **全库审查 26 项缺陷修复**（两批，全部先复现验证再修）：**数据正确性**：v1 旧配置迁移崩溃（自定义站点键致整个应用启动失败且原配置丢失）、无码番号前缀丢弃误路由（`1pondo-072625_101` 被错误刮成 pacopacomama 的数据）、`fill_missing_only` 语义反转（实为"本地覆盖新数据"，修正为仅填空字段）、空番号共享缓存串味（指定 URL 重刮第二个文件张冠李戴）、FC2 搜索兜底归一不对称。**可靠性**：流式请求 CF 挑战页判定失效、av-wiki 空响应打穿整片刮削、失败原因被正常日志稀释、extrafanart 部分失败静默吞、`file_done_dic` 六处锁外竞态、保存设置非法输入半写状态（清空输入框点保存不再残留半套配置）、≥24h 定时间隔保存归零、ASIN 数据库非原子保存（进程中断不再损坏用户库）与并发写互斥、断点缓存 commit 失败无 rollback、mosaic 采信非确定性（重刮归类翻转）、missav 截断 FC2 长 ID（7 位数番号）、Emby 分页大库漏页、`_failed.json` 保护分支永久劫持原配置、FILL 合并 number 死代码清理
- **五项数据丢失/性能缺陷**：同路径移动删源（更新模式扫已整理目录会把源影片删成死链）；同名静默覆盖（移动目标已存在时先保留旧文件为 `_conflict` 副本）；流式响应关闭退化成全量下载（提前放弃的 4MB 响应不再拉满整图）；NFO 评分恒为 0.0（真实评分被空对象默认值丢弃）；并发建目录竞态（批量 extrafanart 下载不再偶发 FileExistsError）
- **失败列表跨影片错误污染**：并发刮削的失败原因互相混入且日志缓冲随刮削量无界增长——按任务树归因隔离，失败列表只含本影片错误
- **LogBuffer 内存泄漏**：兄弟任务 buffer 残留整树回收
- **网络检测多项修复**：搜索解析无结果的爬虫自动回退真实刮削路径探测消除误报；missav_api 检测改走真实搜索；dmm_api 检测补全必需参数；javlibrary 自定义 URL 不再强制直连阻断 CF Bypass；探测失败提示携带实际番号
- **DMM 图占位图误判**：DMM 图床对无效对象返回 200+小体积垃圾体，此前被当真实封面入库——低于 4KB 直接判失败
- **official 无码官网 studio 字段污染**：1pondo/10musume/pacopacomama 的 UCNAME 键实为分类标签，误作厂牌产出脏值——归正为 Maker/Studio 取值，UCNAME 归入标签
- **Dependabot 安全警报 3 项**（tornado 6.5.7 → 6.5.8）：均为 dev 依赖组 Jupyter 工具链传递依赖，生产无影响；升级后 OSV 复扫 123 个锁定依赖 0 已知漏洞
- **CI Windows charmap 崩溃**：测试脚本读源文件补 `encoding="utf-8"`

### 功能

- **新增 7mmtv 聚合站爬虫**（移植自 Hazard804/mdcx）：7mmtv.sx 有码/无码/素人/FC2 剧照与元数据刮削，加入有码/无码/素人/FC2 四个默认源列表；HEYZO 剧照场景适用。双镜像域名轮询（7mmtv.sx → 7tv022.com 失败自动切换），两域名默认加入「走代理网站」列表（老配置需在设置→网络手动补充）；旧配置中残留的 7mmtv 站点值自动恢复有效。打包构建显式收录该动态注册模块（防 PyInstaller 静态分析漏收导致打包版刮削崩溃，附一致性哨兵测试）
- **新增三个爬虫**：javfree（javfree.me 有码/无码/FC2，默认加入有码+FC2 源）；aventertainments（无码 DVD+PPV，覆盖 caribbeancom/1pondo 两厂牌）；madou_club（麻豆系国产番号）
- **精简 15 个冗余/失效爬虫**：失效站与需外部 CF Bypass 服务站移除，数据重复站被 DMM 系覆盖；注册爬虫 48 → 33；旧配置中的已删站点自动跳过
- **JavDB 全系图源无水印升级**：App 专用 CDN 加密流（单字节 XOR）解密后为无水印原图，网页版带水印 URL 自动升级到无水印变体、失败回退；中段路径变更由响应学习自愈
- **无码官网五站接入默认代理列表**（caribbeancom/heyzo/1pondo/pacopacomama/10musume 及 mywife 实测需代理）

### 优化

- **DMM 直构静态路由种子 v2**：libredmm 全站 58.9 万「番号↔cid」对归纳为离线路由表（随包分发），路由命中的系列首候选直达真实 cid、全链路零额外请求；append 分级模式保高频系列候选顺序零污染、老片 3 位 cid 兜底
- **ASIN 数据库读零校验**：库命中直接采信高清封面不再逐次软校验（省每片 1-2 次参考图下载）；新发现 ASIN 入库走 v2 三步证据链（cid 旁证→标题门含合集词一票否决→图像兜底），错配从源头拦截；特典/限定版同番号让位规则（正品替换特典）
- **ASIN 数据库性能**：查询全量解析 4 万行 xlsx（2.2 秒/次）改内存双索引（0.08ms，约 3 万倍加速）；出厂库扩容 26620 行（四源校验工程全量净化，同番号 ASIN 唯一），合并升级为"出厂库权威"覆盖纠正历史错挂；ASIN 缓存命中优先走 tenhow 免代理图床直连下图；软校验参考图缺失时按番号直构 DMM 官方图兜底
- **刮削失败原因 Top N 摘要**：大批量刮削结束输出按类别聚合的摘要行（如"请求超时 23 个｜站点未收录 15 个"）+ 每类可操作建议，不用逐条翻几十条失败日志
- **刮削进度预计剩余时间**：状态栏显示"已刮削 320/5000 · 剩余约 2 小时 15 分"（滑动窗口速率估算，样本不足不出估算）
- **LLM 翻译同批次缓存**：系列片/失败列表重刮的相同文本直接复用译文（并发相同请求合并为一次调用），显著省 token；缓存绑定 LLM 配置指纹，切换模型自动失效
- **DMM 高清直链升级推广到 11 个聚合站爬虫**：airav_cc/avbase/avsex/freejavbt/iqqtv/javday/javfree/lulubar/missav_api/thejavdb_api/xcity——其中多数爬虫首次获得竖版高清海报
- **字段来源日志降噪**：同一失败站点的跳过标记单文件内重复 20+ 次（占日志 17%），改站点级去重降噪 99%，信息无损
- **javdb_app 签名失效 fail-fast 诊断**：签名常量轮换时给出明确诊断与三个环境变量免改码覆盖出口；搜索补 `type=movie` 与 `limit=50`（超限静默截断）
- **检测网络页**：结果按状态着色；三站点下拉框显示最近实测状态圆点（tooltip 附检测时间与路由）；检测进度实时显示 `done/total`；复制结果自动附带脱敏诊断头；401/403/429 文案拆分具体动作引导；站点选择列表标注「日本IP限定/勿用日本节点」
- **「全部走代理」开关**（默认关）：所有请求交代理软件分流裁决，「走代理网站」列表不再生效
- **LLM 翻译关闭思考模式**（#54）：按服务商自动下发关闭参数（硅基流动/百炼/火山方舟/Ollama/Gemini），参数不兼容自动去参重试
- **madouqu 动态域名**：接入官方发布页实时解析（24h 缓存+静态回退），搜索失败自动切换镜像
- **站点级 CF 指纹池扩充**：lulubar 与 missav 全镜像专属指纹池，重试轮换排除失败指纹
- **其他**：高分屏非整数倍缩放默认启用（125%/150% 不再模糊）；有限收录站点用各站实测番号探测消除误报；Emby 演员管理器可最大化拖拽缩放（初始尺寸适配屏幕 80%）；javbus 镜像池清理失效镜像；getchu_dmm 合并进 getchu；r18dev 解析兼容 parsel JSON 三态；「成功后不移动文件」时不创建视频目录

### 文档

- 文档与 UI 文案全面对齐代码（注册爬虫数/命名变量表/代理域名列表/演员库列/Tab 名称/release 产物名等 20+ 处）；README Telegram 群地址更新；「跳过前置 Poster 校验」说明对齐实际三分支；使用说明内容全面更新

### 工程

- **修复打包脚本 Windows runner 因 GBK 解码崩溃**：`build.py::_run_command` 的 `subprocess.run(text=True)` 未显式指定编码，Windows 默认 GBK/charmap 解码 PyInstaller 输出时含 UTF-8 字节即 `UnicodeDecodeError`，首轮 release 构建直接失败。补 `encoding="utf-8", errors="replace"`，新增哨兵测试锁定

## v2.0.6 (2026-08-23)

### 功能

- **NFO 库管理页面**：左侧导航新增「NFO库管理」，目录 `.nfo` 批量编辑（15 字段）+ 字段级 diff 预览 + 批量操作（替换演员/加删标签/统一系列）+ 右键重新刮削/打开目录/删除
- **字段级跳过抓取**：字段优先级对话框每字段可勾选「跳过」，该字段不从任何来源抓取
- **NFO 合并策略（5 种）**：写入前按策略（prefer_scraper/prefer_nfo/merge_arrays/keep_existing/fill_missing_only）与现有 NFO 合并，关键字段双重保护
- **爬虫镜像/域名轮询**：新增通用 DomainRotator，javbus（12 镜像）/freejavbt/7mmtv/xcity/IQQTV/missav（3 域名）请求失败自动切换；javlibrary 动态获取最新直连地址
- **avmoo/avheat 新增爬虫 + avsox 改 API**：三站同属 tellme.pw AIO 平台（Vue SPA + JSON API），新增共享基类 AioSiteCrawler 统一封装；tellme.pw 动态地址统一获取
- **dmm_api 换 DMM 官方 Affiliate API + 新增 thejavdb_api**：dmm_api 由 JavDB 第三方 API 换为官方 API（老配置零迁移）；原 JavDB API 独立为 thejavdb_api 爬虫（默认未启用）
- **MGStage 官方图源直构双兜底**：站点图源全失败时按番号直构 MGStage 官方 CDN 高清图（`pb_e` 横版作封面、`pf_e` 竖版作海报，系列映射表实测 8 系列），补 DMM 不收录的素人番号
- **JavLibrary CF bypass + DMM 高清升级 + xpath 兼容**：新增 Selenium+Edge headless 过 CF JS 挑战（可选依赖自动安装）；刮削后自动升级 DMM 高清封面；xpath 兼容 Selenium tbody
- **TRAWL/FlareSolverr 外部 CF 服务适配层**：适配层暴露 cookies/mirror/html 端点统一调用 TRAWL `/scrape` 或 FlareSolverr `/v1`；便携版内置 Redis 并自动跟随上游版本
- **移除内置 CF Bypass 服务**：删除 cloakbrowser + cf_bypasser 内置服务，过 CF 统一走外部服务，打包体积与内存显著减小
- **演员库增强**：JavDB 中文名补全（免 TMDB Key）、补全别名新增 JavDB 数据源（NFKC 归一化 + 繁简转换 + 异体字统一）、cleanup_aliases 别名清洗、剔除男优支持别名匹配
- **检查演员缺失番号多数据源重写**：按演员类型分四路数据源（有码 libredmm / 无码 avsox / 欧美 avheat / 国产 iqqtv），支持括号标注类型
- **站点定位说明**：全部爬虫新增 description 定位说明，站点列表悬停展示 tooltip
- **图片下载大小上限**：图片链路统一 50MB 上限，防异常大文件拖死磁盘

### 重构

- **爬虫文件去 `_new` 后缀**：`dmm_new`→`dmm`、`javdb_new`→`javdb`、`avbase_new`→`avbase`；JavDB App 类名统一
- **JavDB App 签名简化 + 设备参数补全**：硬编码已验证签名常量，补全设备标识参数降低风控概率
- **移植 sakuramediabe 4 项改进**：番号清洗去域名干扰、jsdelivr CDN 加速、NFKC 归一化匹配、stale 缓存降级
- **Emby 演员管理器入口移到左侧导航**
- **Amazon 标题匹配函数抽为模块级**（`core/amazon_match.py`，可被批量采集脚本复用）

### 修复

- **Windows CI 离线测试全量适配（30 项）**：硬编码 `/tmp` 路径改 `tempfile.gettempdir()`（脚本+测试）；AST exec 补 `Path` 到 globals；`.read_text()` 统一加 `encoding="utf-8"`（Windows cp1252 解码失败）；`read_link_sync` 剥离 `\\?\` 长路径前缀（含环检测 early return）；pyuic6 产物与仓库版两边做相同路径分隔符归一化
- **主窗口启动崩溃修复**：NFO 库页三栏布局用了 PyQt5 才有的 `QLayout.setStretchFactor(index, stretch)`，PyQt6 严格重载下启动即抛 TypeError（Windows 打包版首发暴露）；改用 `QBoxLayout.setStretch(index, stretch)`
- **设置页与工具页滚动修复**：新增 `CustomScrollArea`，在 `widgetResizable=true` 下按绝对定位子控件包围盒同步内容最小宽高，恢复设置页、工具页和 NFO 编辑页的滚动；NFO 设置页宽度统一为 701，修复右侧 94px 截断；NFO 编辑器修复内容宽度被压缩到 98px 的问题
- **设置页底部留白修复**：滚动内容底部安全余量从 20px 提高到 60px，避免最后一行文字或控件贴近边框后在字体基线、滚动条和 DPI 缩放下显示不全
- **NFO 库管理三栏修复**：移除中间 NFO 表单滚动区的 380px 最小宽度约束，使左侧列表、中间表单和右侧海报/缩略图预览在 800px 内容区内不重叠，保存当前 NFO 按钮不再被右侧预览遮挡
- **NFO 库管理批量提示修复**：提高左侧“批量保存”下方换行提示的最小高度，避免 Windows 字体和 DPI 缩放下文字底部显示不全
- **全模块审查修复（35 项）**：数据损坏级 6 项（翻译映射清空/简繁失效/tmdbid 错配/迁移丢图/同路径误删/字符清洗）、功能失效级 7 项（断点续刮/间歇刮削/共享番号/数据源/wiki/minnano/相似自推荐）、性能健壮性与并发安全 22 项
- **Emby 演员管理器 15 项修复/优化 + 窗口遮挡（issue #38）**：连接/同步/上传/缓存/背景图/过滤器/详情 TTL 等；模态改非模态 + 后台执行
- **全页面 UI 布局批量修复**：13 个滚动区 widgetResizable→true（高 DPI 横向裁切）、33 个 GroupBox 限宽 739→860、60 个长文本 QLabel 补 wordWrap；NFO 设置页 26 个超长 CheckBox 硬截断修复；网络设置说明文字截断/重影修复；配套 check_ui_layout 静态检查纳入 CI，三项清零验证
- **其他 UI 修复**：左侧导航 Emby 按钮（误删信号残留）、演员库维护 group 裁剪、网络设置 group 重影/超时滑块重叠、批量操作面板迁移到 NFO 库页左栏、NFO 库页三栏自适应 + 批量面板默认折叠 + 预览框边框、空列表占位提示、配置项说明补齐、类型刮削说明空白补 colspan
- **网络检测增强 6 项**：代理故障提示、镜像抽样、单厂牌提示、重试失败项/复制结果按钮、DMM 误报修复
- **翻译修复**：Bing 端点改 cn.bing.com（原返回空响应体）；百度翻译 appid/key strip 修复签名错误
- **CLI 修复**：crawl 代理白名单失效、失败退出码、javdb_api 搜索 q 参数丢失
- **爬虫修复**：dmm 双重重试/番号匹配/评分/日期截断、javbus 搜索镜像轮换、minnano 标题校验/缓存 key、MGStage/Jav321/FC2Club/FC2Hub/JavLibrary 字段解析保留引号方括号、FC2Hub 缺失节点容错、FC2 时长/无修正判定、prestige 字段防护、javdb_app year 推导
- **版本检查日志刷屏修复**：失败时不再把整个 GitHub API JSON 倒进日志；改用 releases 列表 API 遍历找纯数字 tag（正确跳过 TRAWL 发布），错误只输出简洁说明
- **下载/文件修复**：分块下载断点续传（.part + .part.meta）、文件复制原子替换、移动文件拒绝目录目标、图片 50MB 限制与同 URL 并发复用、extrafanart 替换原子化、符号链接解析与跨目录重复跳过、move_file 先删目标、成功列表记录新路径、fanart 失败不再静默
- **崩溃容错**：get_new_release 日期格式、parse_runtime 时长解析、hdouban 秒数、强杀线程单次注入与全局停止超时保护
- **并发/性能**：is_proxy_host O(1) 映射、镜像轮询重试去重、AVdb 并发预热、连接池锁外清理、Flags 重置保持异步锁身份稳定、TMDB 演员库并发写保护、女优信息库加锁
- **Windows 体验**：保存配置黑色控制台窗口（SYSTEM_INFO 替代 platform()）、配置保存拒绝访问多级回退、翻译说明文字重影
- **其他**：DMM 9 前缀番号识别、CF 指纹轮换（safari17_2_ios）、读取模式不受断点缓存干扰、打包 hidden-import 补齐、配置保存竞态/重试链、优雅退出、ComputedLease 非阻塞、UI 与文档一致性（网站数量 48/missav.live/MGStage/thejavdb_api）

### 工程质量

- **CI 双平台门禁**：新增 Windows 离线测试 job；Linux 继续执行完整质量检查，Windows 实际覆盖路径/文件系统条件分支；PyInstaller EXE 由 Release 和手动打包工作流验证
- **GUI 启动冒烟测试**：offscreen 下完整构造主窗口（setupUi→Init_Singal→Init_Ui→load_config 全链路）与 Emby 演员管理器两个对话框，PyQt6 签名不兼容/属性缺失类问题在 CI 双平台拦截，不再推迟到用户运行时暴露
- **打包与 Release 工作流收口**：Windows 构建显式使用 Release Tag 版本；矩阵构建先上传 artifact，再由串行任务统一创建 Release；Release 权限、Tag 来源、对应版本 checkout 和当前版本 changelog 提取统一校验
- **新增 quick-check 快速检查命令**（ruff + mypy 秒级自检）
- **mypy 类型检查启用修复**：quick_check 改用 `sys.executable -m mypy`；重命名与标准库冲突的 types 模块（108 处引用同步改写），mypy 完整检查全部 151 个源文件
- **CI/Release 工作流修复**：release.yml tag 触发 `220*`→`2*`（YYYYMMDD tag 不以 220 开头，旧模式永不触发发布）；CI ruff 改 `uv run ruff` 消除版本漂移
- **UI 布局静态检查脚本**：新增 `scripts/check_ui_layout.py`，扫描 `.ui` 中滚动区 widgetResizable、GroupBox 限宽、QLabel wordWrap 等打包后才暴露的隐患（wordWrap 误用 critical 阻断）；纳入 `uv run check` 与 CI
- **跨线程 Qt 安全收口**：提取 `run_in_background` 通用工具 + `check_thread_safety` AST 扫描（0 违规）
- **UI 收口到 .ui + 几何回归测试**：百度翻译/网站优先级/fc2ppvdb Cookie 写进 MDCx.ui（唯一权威源）；offscreen 遍历断言无重叠
- **刮削缓存管理 UI**：工具页新增缓存统计/失败列表/导出 CSV/重置/清空
- **死代码清理**：删零调用函数/死变量（avsex get_poster 等）、无引用 ping3 依赖、AVWikiDB 别名查询、文件移动冗余分支、Gfriends 缓存重复写入、CF 后退避死分支、javdb_api 不可达代码
- **回归测试**：新增 review_regressions/save_success_list/UI 几何/avsox 系/Amazon 匹配等多批
- **版本元数据统一**：Python 包版本同步 GUI 展示版本，回归测试防再分裂
- **静态质量收口**：清理 B005/B007/B904 等高价值 Ruff 告警，异常链保留根因，补目录删除安全测试
- **性能优化**：PNG 压缩级别 6、convert_half 翻译表、剩余任务快照写盘、水印缓存、asyncio.Event 唤醒、ActressDB 参数化、缓存 WAL+批量提交、内存上限、UA 池更新至 Chrome 115-135
- **启动性能与自检**：本地数据库延迟加载（后台线程 + 就绪屏障）；启动检查配置目录可写/TMDB Key/代理可达性，不阻塞启动

## v2.0.5 (2026-08-15)

### 功能

- **DMM 高清升级探测去重**：`upgrade_dmm_cover` 增加进程内 TTL 缓存（按规范化番号，成功缓存高清 URL、失败缓存 None）+ 同事件循环 in-flight 合并，JavBus / JavDB 三站 / R18.dev 等站点并行刮削同一番号时不再对相同 DMM 候选重复探测（未知系列全 404 场景从每站点 ~20 次请求降为全程一次）
- **DMM 高清图按分辨率放行跳过日亚**：`_should_skip_amazon_for_existing_poster` 对 awsimgsrc DMM 高清图改为按分辨率直接放行（宽≥700），解决 DMM 竖图普遍 <400KB 被字节阈值误判为「不够清晰」而误走日亚搜索的问题；同时 `upgrade_dmm_cover` 增加分辨率校验，过滤 147x200 缩略图占位图，避免把海报覆盖成低清缩略图
- **DMM 放行门槛降至 700**：`POSTER_DMM_MIN_WIDTH` 与 `_DMM_HD_MIN_WIDTH` 由 1024 降到 700，MILK 系列 745x1081 等中尺寸图也能升级为海报并跳过日亚，进一步减少日亚请求；588x800 及 147x200 窄图/缩略图仍被拦截
- **ASIN 数据库写入去重**：`save_asin_to_excel` 写入前按番号去重，同番号已存在时跳过不写，避免重复行
- **ASIN 出厂库增量合并**：新增 `merge_asin_db_from_backup`（仿演员库，出厂库 md5 标记 `.asin_db_merge_marker` 未变跳过；按番号并集合并——新增番号追加、已有字段空缺补全，不覆盖用户已填值、不删行），软件更新后老用户启动时自动把出厂库新增/修正数据合并进用户库
- **ASIN 出厂库更新**：出厂 ASIN 库合并最新数据至 9699 个番号（净新增 4616），按番号（前缀字母 + 数字）排序
- **ASIN 出厂库合并后重排**：`merge_asin_db_from_backup` 合并产生新增行时，合并后按番号（前缀字母 + 数字）整体重排并重新格式化（重建工作簿避免 delete_rows 的 max_row 虚高）；纯字段补全不改变行数与顺序，不重排
- **相似片推荐**：新增 `mdcx/core/similar.py`（借鉴 OpenAver 设计）——基于 tag IDF 加权 Jaccard + 系列/片商/年份/时长/演员组合评分 + MMR 重排的本地离线相似算法，零网络零模型；主界面结果树右键「查看相似片推荐」弹出对话框，双击可跳转
- **SQLite 刮削状态缓存（断点续刮）**：新增 `mdcx/core/scrape_cache.py`（标准库 sqlite3 + WAL），持久化每个源文件的刮削状态（done/failed + mtime + 失败计数），实现断点续刮与失败跨会话重试（上限 3 次，成功清零）；数据库损坏自动回退内存模式；重启后自动跳过已完成且未变化的文件、恢复上次失败未超限文件
- **结果摘要缓存**：`scrape_state` 表新增 `summary_json` 列（旧表自动迁移），刮削成功时存储相似推荐所需字段；相似推荐语料 = 历史成功结果（SQLite）+ 当次刮削结果，重启后仍可基于全历史推荐
- **相似推荐特征扩展**：结果摘要新增 `mosaic`（有码/无码）、`publisher`（发行商）、`directors`（导演）、`score`（评分）四个特征，算法加分项同步扩展——马赛克类型相同 +0.35 / 不同 -0.30（有码无码不再混淆推荐）、发行商一致 +0.15、导演有交集 +0.15、评分接近 +0.05；同时修复召回缺陷：热门标签（IDF=0）不再被排除出候选召回，只影响精排权重，解决「目标片全是常见标签时完全推荐不出结果」的问题
- **CF Bypass 落地域名白名单**：新增配置 `cf_bypass_trusted_hosts`（逗号分隔，支持 `*.example.com` 子域通配），校验 Bypass 服务落地/重定向后的最终域名，防第三方服务被劫持时把恶意页面当数据；设置页新增「Bypass落地白名单」输入框
- **本地 Bypass 服务健康状态机**：新增 `_local_bypass_health`（idle/ready/dead），连续请求失败达阈值（3 次）标记 dead 并解除转发（不再空等假死服务超时），冷却 300s 后自动重试，请求成功自动恢复
- **Emby 演员管理器修复**：修复「连接 Emby」无反应的根因（`ComputedManager` 模块不存在致 ModuleNotFoundError 被静默吞掉）、`_is_jellyfin_server` 恒 False 的判断 bug；修复 `search_actor_info` 键大小写不匹配导致简介/信息抓取完全失效、DELETE 404 被当失败致无头像演员传不上头像；`PreparePreviewThread` 加顶层异常处理并真正 emit error（原 worker 调用不存在的 `self.log` 致线程静默死亡）；并发模型由「10 线程各自 event loop」改为单 loop + `asyncio.Semaphore(10)`；头像/背景上传统一复用 `_upload_actor_photo`；Emby 分支补 `personTypes=Actor` 过滤；`sync_actor` 单演员异常不再中断整批、`update_person_info` 不再用空值覆盖服务器已有字段
- **Emby 演员管理器新功能**：新增「设置」对话框（数据源优先级拖拽排序、演员类型过滤/去重、本地头像目录、Gfriends、使用数据库）；「数据源测试」窗口（按配置优先级逐源验证头像/简介并展示结果，含字段/值信息表与快速设置面板）；演员详情编辑对话框（左栏现有数据、右栏可编辑简介/信息表、快速设置面板、单独同步头像/简介）；快速设置面板（测试/详情窗口内改即自动保存）；「清空缓存文件夹」按钮；底部状态栏（连接/操作状态）；同步完成后 3 秒自动重新获取演员列表
- **Emby 演员管理器健壮性**：头像补全主循环逐演员容错、backdrop 按索引删除、Gfriends commits 解析失败降级、时区偏差修复、缓存文件名防碰撞、`src[jp_name.index()]` 越界防护、按钮状态机修正、Dialog 关闭安全（`closeEvent` 等待线程）、清理死代码（`_avatar_cache`/无效 checkbox/重复 layout 等）
- **爬虫类型分类校准**：按站点性质校准各刮削类型默认网站源——仅能有码（dmm、dmm_api、libredmm、r18dev、avbase、faleno、giga、dahlia、xcity、prestige、mgstage、fantastica、cableav、getchu、getchu_dmm、javlibrary、jav321、freejavbt、lulubar）、无码专属（avsox、kin8）、综合有码+无码（javbus、javdb 系、missav 系、javday、7mmtv、airav_cc、avsex、official、iqqtv）、素人（含 mywife、iqqtv）、FC2（含 javdb 系）、欧美（仅 theporndb）、国产（含 iqqtv、hscangku）；同步默认配置模板与 FEATURES 文档标注；「刮削不到？看这里！」弹窗网站列表改为动态生成（随爬虫注册自动更新）
- **Emby 演员缓存持久化**：演员头像缓存从临时目录（`tempfile.gettempdir()`）改为持久化目录 `userdata/emby_actor_cache/`，与 gfriends.json/minnano_cache.xlsx 一致，重启后可复用缓存避免重复下载

### 修复

- **图片尺寸探测失效**：`_read_stream_size`/`get_imgsize` 对 curl_cffi 同步生成器产出 bytes 误用 `await` 恒抛 TypeError，改为 `aiter_content` 异步迭代；修正测试 mock 与线上行为对齐（此前测试掩盖 bug，Amazon 高清择优/尺寸校验静默失效）
- **GUI 状态卡死**：`_move_file_thread` 移动完成后按钮永久卡禁用（补 `reset_buttons_status` + try/finally）；非刮削状态点「停止演员库维护」后 `signal_qt.stop`/`Flags.stop_requested` 永不复位导致日志静默、下一任务秒停（`_on_actor_db_finished` 复位）
- **停止标志 / 跨线程 Qt**：`_show_version_thread` 移除 worker 线程直接操作 QWidget（`setCursor`/cookie 检查改经 `version_check_done` 信号回主线程）；`network_check` 按钮状态经信号回主线程 + 防重入 + 删重复 setText；`to_cut` 后台线程读 QWidget 改为主线程采集 `mark_list` 传入、`_set_pixmap` 跨线程改 UI 经信号回主线程
- **trailer 旧文件复用**：`deal_old_files` 带文件名时用旧 `file_name` 构造目标路径，与 `trailer_download` 的 `naming_rule` 命名不一致导致旧 trailer 无法复用/孤立文件，新增 `naming_rule` 参数对齐
- **Amazon ASIN 记录丢失**：低清兜底路径 `asyncio.create_task` fire-and-forget（事件循环关闭时 pending task 销毁），改为 `await`
- **爬虫修复**：`get_amazon_data` 删除对恒为 None 的 `html_info` 提取 session 的死逻辑；`get_avsox_domain` 布尔优先级错误（or→and）；`check_url` `max_retries` 1→3 启用真实退避重试；非数字评分 `float()` 崩溃防御；`translate_actor` 空演员名误替换全部演员；missav 冒号格式时长解析（1:30:00）；missav URL slug 非番号格式不覆盖番号；javbus 搜索结果相对路径补全绝对 URL；javdb XPath 作用域逃逸；r18dev dvd_id 补零比较
- **读模式 tmdbid 不落盘**：xlsx 缓存命中 tmdbid 立即回写 `res.actor_tmdb_ids`，修复 `still_missing` 为空时 NFO 缺 tmdbid
- **文件写入原子化**：NFO 与配置保存改为临时文件 + `os.replace` 原子写入（防写入中断损坏），推广到 missing 番号清单、gfriends JSON、actor_db 断点文件、amazon_database 报告等
- **LogBuffer 并发安全**：`write`/`clear` 加锁、`get` 遍历浅拷贝，修复并发 append 时 `list changed size during iteration`
- **死代码清理**：删除 `image.py:get_pixmap`（无调用且读取失败会删除源图）、amazon 4 个未用函数、`parse_fanza_resp`、`save_asin_to_excel` 未实现的 `max_rows` 参数、`query_asin_database` 重复 import 死分支、`Config.from_legacy` `type(timedelta)` 恒 False 等
- **Emby 演员管理器 Event loop is closed**：9 处 `new_event_loop()`+`close()` 改用全局 `executor` 常驻 event loop，避免 curl_cffi AsyncSession 跨 loop 复用报错
- **Emby 演员管理器获取列表无反应**：`QDialogButtonBox.Ok` → `StandardButton.Ok`（PyQt6 6.4+ 扁平枚举已改嵌套）；site_priority_dialog 两处补 `manager.save()` 修复网站优先级拖拽排序后不落盘
- **Emby 演员管理器设置保存不生效**：`EmbyActorSettingsDialog._save` 及两处 `_save_quick_settings` 补 `manager.save()`，修复设置弹窗修改后不写盘
- **Emby 设置弹窗 QListWidget 遍历崩溃**：PyQt6 QListWidget 不可直接 `for item in self.list` 迭代（抛 TypeError），改用 `item(i)` 索引遍历
- **Emby 数据源测试跨线程 UI 崩溃**：`ActorSourceTestDialog` 在后台线程直接操作 QWidget 导致崩溃，改用 `QThread` + 信号回调模式（`ActorSourceTestThread` 发 `result`/`error` 信号回主线程）
- **翻译页 label_60 文字被覆写**：翻译页百度提示文字覆写了 label_60 原有文字导致重影，新建 `label_baidu_hint` 独立显示
- **网络设置 groupBox 重影**：网络设置页 `trusted_hosts` 输入框与超时行 cell 冲突（同一 gridLayout cell 放了两个 widget），`trusted_hosts` 移到 row=10，`groupBox_28` 高度 400→480
- **MDCx.ui 重复 objectName 消除**：4 对重复 objectName（label_81/60/423/424 第二次出现）重命名，消除运行时控件查找歧义
- **label_601 死引用删除**：`main_window.py` 引用不存在的 `label_601`，运行时必崩
- **Courier 字体替换**：117 处 `font:"Courier"` → `font:"Courier New"`，修复中文环境字体名匹配失败导致文字显示为方框

### 工程质量

- **测试增强**：新增 Amazon 跳过逻辑测试（DMM 高清/中尺寸放行、缩略图/窄图拦截、非 DMM 字节阈值保留、Amazon 来源不跳过）；新增 `upgrade_dmm_cover` 缓存行为测试（命中零探测、失败缓存保留原图、并发 in-flight 去重）；更新 JavBus / R18.dev 受影响升级测试
- **ASIN 库测试增强**：新增 4 个测试（同番号去重、批量去重、出厂合并行为、md5 标记跳过）
- **新功能测试增强**：新增相似算法 7 测试、相似对话框 5 测试、`ScrapeStateCache` 15 测试、CF 白名单 6 测试 + 4 集成测试、本地 Bypass 健康状态机 8 测试；修正 `test_media_resource` mock 与线上 curl_cffi 行为对齐
- **打包与 CI 加固**：`build.py` 显式收集 `curl_cffi.libs` 防打包后 TLS 指纹库丢失；`ci.yaml` 补 `check_info_db` 步骤；移除 `libs/` 下 OpenSSL 1.1 死数据；`main.py` stderr 重定向仅 IS_PYINSTALLER 时生效
- **Emby 数据源实现合并**：`emby_actor_manager.py`/`emby_actor_image.py`/`emby_actor_info.py` 三模块间重复的 Gfriends 索引解析、Graphis HTML 解析、信息补全链路合并——`get_gfriends_index` 增强为完整版（版本检测+缓存刷新+展开写回）、抽出 `_parse_graphis_html`/`fill_actor_info_from_sources` 共用函数、`_BIO_TAG_PATTERNS`/`_extract_bio_tags` 统一移至 manager 模块
- **Emby API 共用函数提取**：新建 `emby_shared.py`，移入 5 个共用函数（`_generate_server_url`/`_build_jellyfin_headers`/`_is_jellyfin_server`/`_append_query`/`_upload_actor_photo`），两模块从中导入并 re-export（`# noqa: F401`）保持向后兼容
- **本地头像预扫描索引**：新增 `build_local_avatar_index` 预扫描本地头像目录建立文件名索引，`from_local_avatar` 加 `pre_scanned_index` 参数，N 次逐演员全树遍历降为 1 次预扫描 + N 次字典查找；新增 6 个测试

## v2.0.4 (2026-08-14)

### 功能

- **DMM 官方高清直链**：新增番号→DMM cid 候选构造器 `dmm_direct`（前缀映射表覆盖 110+ 主流系列，含 `h_xxx`/数字特殊前缀与跨厂商附加前缀，用 dmmapi/avbase 实测校准，配套 `dmm-probe` 探测工具）；封面补全所有爬虫失败时走官方直链兜底（竖版 `ps` 高清作海报优先，横版 `pl` 裁剪兜底，无码番号跳过）
- **DMM 高清覆盖九个爬虫**：LibreDMM / R18.dev / JavBus / JavDB 三站 / DMM / DMM API / avbase 刮削时直接把低清/水印图升级为 DMM 官方高清（统一 `upgrade_dmm_cover` + 前缀表候选，check_url 验证，失败回退原图）；开启「Poster 选优」时自动注入 DMM 高清候选按尺寸选优；DMM 图下载失败自动重试一次
- **同番号刮削结果 TTL 缓存**：同批次相同番号文件（多 CD/重复文件）直接复用刮削结果，避免重复请求所有站点，TTL 90 秒 + 容量上限自动淘汰
- **R18.dev 英文标题掩蔽还原**：日文标题缺失时用服务端 `title_en_uncensored` 还原掩蔽字段（`Sex S***e` → `Sex Slave`）
- **补别名/补全功能调整**：补别名来源切换为内置 minnano 爬虫（无 CF 拦截、命中质量高），新增「全量更新」开关与「起始行/限量」分片续跑；新增「minnano 补全」按钮（补缺生日/简介，日文自动翻译）
- **演员库维护工具健壮性**：新增「检查用户库」（扫描格式/结构/数据异常，安全项一键自动修复）与独立停止按钮；联网工具统一滑动窗口并发（TMDB 5 / LibreDMM 2）+ 限量分片 + 断点续跑；LibreDMM 补链接加限流与共享会话
- **info 库重构与同步**：三语言列、五源标签收集、cn 翻译优化；出厂库合并用户库机制（cn 合并键 + md5 marker）；actor 库标签/事务所/生涯日文残留清理与同步；check_actor_db 检查项整合
- **Emby 演员管理器增强**：信息补全与管理器接入本地演员库（最高优先，离线可用）；新增 graphis 头像/背景图来源；跳过逻辑精确化（识别"无维基百科信息"占位符）

### 修复

- **打包与网络**：PyInstaller 补充 minnano 爬虫 hidden-import；默认走代理列表补 `minnano-av.com` 且裸 session 按配置走代理；JavDB 图片域名归一（水印 `tp.spfcas.com` → 无水印 `c0.jdbstatic.com`）
- **Emby 演员管理器**：「仅补缺失演员」不再拉全库、详情并发拉取、删除图按响应状态判定；移植版 import 修复、空响应不再误报失败、缓存导入路径修复
- **演员库维护工具**：新增「更新 nfo tmdbid」与「校验 tmdbid 有效性」按钮；TMDB 演员匹配优化（繁→简转换、adult 权重优先、候选放宽 + 命中变体排序）；actor_db 并发 UX 修复（信号带 task_id、通用模板消重）
- **UI 与布局**：工具页/设置页 groupBox 重叠连锁修复；删除无效单选按钮；MDCx.py 文案漂移回写 MDCx.ui；`validate_crawler_registry` 误报修复
- **网络诊断**：站点超时改用用户配置值；新增"路由"列显示代理/直连
- **安全**：修复 `shell=True` 注入风险、移除 11 处 `?api_key=` 暴露、修复 5 处静默异常 + 下载 URL 白名单
- **minnano 路径 bug**：日文名查找与缓存文件改用运行时用户数据目录（打包后 CWD 失效问题）
- **其他**：爬虫 xpath 防御下沉（10 处）、`update_nfo_tmdb_ids` 类型防御、UI 缩放异常不阻断启动、异常日志通道修复

### 工程质量

- **mypy 严格化**：移除全部 19 项 `disable_error_code`，全项目零抑制通过；`BaseCrawler` 泛型化等修复 43+ 处类型错误，顺带修复 5 个隐藏 bug
- **测试增强**：UI 结构自动化测试、`validate_crawler_registry` 测试、Emby HTTP 测试、actor_db 按钮一致性测试；ruff 自动修复 138 处
- **其他**：单站失败原因结构化分类（`FailureReason`）、死代码清理、`_download_chunk` 返回类型修正

### 文档

- 使用说明 tab 与 README/INSTALL/FEATURES/USER_GUIDE 等更新（仓库链接修复、新功能描述）

## v2.0.3 (2026-08-03)

### 功能

- **演员库维护工具改为直接操作 xlsx**：移除「输入演员名单 / 选择 nfo 目录」输入方式，新增三个独立按钮——补全中文名（按已有 TMDB ID 补中/英繁体翻译）、补全 LibreDMM 链接（补信息链接）、同步别名（用 TMDB 最新 also_known_as 刷新 keyword 列），统一扫描 `actor_database.xlsx`，每个按钮带独立防重入
- **同步别名与刮削共用同一规则**：`run_actor_db_xlsx` 的 `sync_aliases` 改为复用 `_merge_keyword_values`，与刮削写入 actor 库的别名合并逻辑保持一致，永不同步偏差
- **工具页工具排序调整**：按用户偏好重排为 Emby 演员管理 → 演员库维护 → 单文件刮削 → 裁剪图片 → 封面补图 → 软链接助手 → 移动视频字幕 → 检查演员缺失番号
- **打开演员数据库按钮**：演员库维护工具新增「打开演员数据库」按钮，用系统默认程序打开 `actor_database.xlsx` 供查看与手工编辑；文件不存在或打开失败时提示先安装 Excel/WPS 等办公软件
- **并发提速**：演员库维护（补全中文名/链接/同步别名）改为滑动窗口并发模式，TMDB 请求并发 5、LibreDMM 请求并发 2，串行 150s+ 降至约 30s

### 修复

- **单 exe 按钮无提示退出**：修复「打开演员数据库」按钮点击后程序直接退出（根因：`_open_actor_db_file` 误作实例方法调用导致 AttributeError，被 onefile 无控制台吞掉为静默退出）
- **executor.submit 传参错误**：`AsyncBackgroundExecutor.submit()` 只接受单协程参数，`executor.submit(asyncio.run, run())` 写法导致 TypeError。修复 `main_window.py` 的 `_run_actor_db_tool` 及 `tool_handlers.py` 的 cover_backfill 两处同源 bug
- **跨线程 Qt 不安全操作**：`_run_actor_db_tool` 协程内直接 `btn.setEnabled()` 跨线程操作 QWidget。改为 `actor_db_finished` pyqtSignal 主线程恢复，消除潜在 segfault 风险
- **日志通道不通**：`_log_line` 仅写内存 LogBuffer，不显示在 GUI 日志页/文件，用户看到「开始扫描」后无后续输出误以为卡死。改为同时调用 `signal_qt.show_log_text` 实时显示

### 工程质量

- **崩溃转储埋点**：`main.py` 注册 faulthandler + sys.excepthook + stdout/stderr 重定向到 `MAIN_PATH/crash/` 目录， onefile 无控制台环境下的 Python 异常不再被静默吞掉
- **死代码清理**：移除 `init.py` 重复 `setText` 接线、`tool_handlers.py`/`main_window.py` 旧 `pushButton_actor_db_pick_dir/start_clicked` 引用已删除控件的死代码
- **记忆文件写入**：`.monkeycode/MEMORY.md` 记录 9 条经验：onefile 静默退出诊断方法、日志通道一致性、executor.submit 正确用法、跨线程 Qt 安全模式、刮削并发架构参考

## v2.0.2 (2026-08-02)

### 重构

- **工具页槽函数抽取**：将 `main_window.py` 中的 21 个工具/设置页槽函数抽取至独立模块 `tool_handlers.py`，`main_window.py` 从 3539 行减至约 3350 行
- **目录选择模式统一**：新增 `_pick_folder` 公共 helper，9 个目录选择方法统一为一行 delegate 调用
- **删除 2 个废弃 import**：`emby_actor_image`/`emby_actor_info` 改为延迟导入

### 性能

- **行索引缓存**：`update_actor_db_row` 新增 `_ACTOR_DB_ROW_INDEX` 全局索引（jp_name → row_index），消除 O(n²) workbook 全表扫描，三个调用点（actor_db_tool/tmdb_actor/scraper）直接受益
- **读取模式批量落盘**：`scraper.py` 读取模式下演员 TMDB ID 补充改为共享 workbook，集中一次落盘，避免每个演员独立 load/save
- **格式化跳过**：`_format_db_worksheet` 检测表头是否已格式化，首次后跳过边框/字体/列宽设置，每次 save 减少 5 次全表遍历，CI 测试耗时从 20.8s 降至 10.7s

### 工程质量

- **移除 7 个文件的 network 标记**：`test_tmdb_actor.py` 等 7 个文件的 93 个测试全部为纯离线 mock 测试，移除 `pytestmark = pytest.mark.network` 使其进入 CI
- **修复 9 个预存陈旧测试**：`test_network_lifecycle.py` 的 `_FakeLimiter`/`_FakeResponse` mock 修复（添加 async context manager 支持），`test_web_amazon_data.py` 的 mock 路径修正（`mdcx.utils.rate_limit.random`），`test_amazon_database.py` freeze_panes assert 修正
- **新增 14 个测试用例**：行索引缓存 6 个、`_load_actor_db_wb`/`_flush_actor_db_wb` 4 个、目录选择/gfriends 同步 8 个
- CI 离线测试通过数从 **530 提升至 635**（+105），全量 627 passed，4 skipped
- **打包配置补充**：`build.py` 新增 `mdcx.tools.emby_actor_image`/`emby_actor_info`/`sync_gfriends`/`scripts.cover_backfill` 的 hidden-import，排除 6 个开发期包（playwright/setuptools/mypy 等），预估单 exe 体积减少约 200MB

## v2.0.1 (2026-08-01)

### 新增功能

- **演员库维护工具**：工具页新增"演员库维护"功能，可对已有 TMDB ID 的演员批量补全中文/繁体翻译和 LibreDMM 链接，支持输入演员名单或选择 nfo 目录自动收集演员
- **刮削流程精简**：更新模式刮削时不再自动为已有演员补全翻译/LibreDMM 链接（该能力移至独立的"演员库维护"工具），加快刮削速度、减少不必要的网络请求
- **Emby 演员管理器**：工具页新增"Emby 演员管理器"按钮，打开独立对话框，可连接 Emby 服务器获取演员列表、多源匹配头像（Gfriends/minnano-av/本地文件夹）和简介（minnano-av/Wiki/本地数据库），支持批量同步到 Emby
- **Emby 演员管理器 - 选库**：点击"获取演员列表"时弹出媒体库选择对话框，可按需勾选要管理的库
- **Emby 演员管理器 - 表格查看**：演员列表表格展示头像/简介/背景图/影片数状态，支持按缺失情况筛选和搜索
- **封面补图工具**：工具页新增"封面补图"功能，输入番号即可自动刮削并补齐缺失的 `poster.jpg` 和 `thumb.jpg`，复用当前配置的站点优先级、命名、裁切、水印规则，支持批量输入与覆盖已有图片
- **封面补图独立脚本**：`scripts/cover_backfill.py` 支持命令行批量和自定义参数，可在打包外独立运行
- **JIMMY 前缀路由**：`JIMMY-003` 等番号自动路由到 FALENO 官网获取资料
- **失败原因记录**：所有刮削来源均失败时，日志会列出各站点的具体失败原因（超时/搜索未匹配等），便于定位问题

### 改进

- **自动海报选优**：不再将横向海报作为最终 Poster，候选图全为横图时自动改用缩略图右裁切，修复 ABF-371 一类封面未裁剪问题

### 修复

- **Windows 路径超限**：`{{ series }}` 系列名过长导致完整路径超 MAX_PATH(260) 时，自动缩短目录名，修复刮削后文件夹无法打开的问题（#19）
- **中文字幕标签误添加**：共享数据路径中未检查 `nfo_tag_include` 配置，关闭后仍会添加"中文字幕"标签，现已修复（#20）
- **explorer /select 路径未引号**：含空格或特殊字符的路径无法用 `explorer /select` 打开，已修复为加引号调用
- **Emby 4.9 剧照显示**：`extrafanart_extras_copy` 将 .jpg 改为 .mp4 时使用 move 而非 copy，导致 `behind the scenes` 目录下只保留 .mp4，Emby 4.9 无法识别。改为 copy 同时保留 .jpg 和 .mp4（#17）

### 工程质量

- 新增 2 个模块，596 个测试用例（583 通过，13 个为既有环境性网络用例失败，与本次改动无关）
- 无新增第三方依赖，兼容 Windows 打包
- 新增 9 个测试用例：JIMMY 前缀路由测试、失败原因记录测试、海报横向过滤单元测试（7 个覆盖 portrait 选优逻辑）
- 新增演员库维护相关测试用例：nfo 目录收集/去重、空名单、翻译/链接开关控制、翻译与链接补全

## v2.0.0 (2026-07-18)

MDCx v2.0.0 全新出发。

### 新增爬虫

- **R18.dev 爬虫**：新增 `r18dev` 刮削源，走 R18.dev 的 JSON 接口直连，不需要翻墙，番号自动补零适配，支持 dvd_id 和 content_id 两种查询方式
- **JavDB API 爬虫**：新增 `javdb_api` 刮削源，走 JavDB 镜像站 HTML 直连，不用 CF 代理，带演员名简繁转换和异体字修正（筱→篠、穗→穂等），可选镜像站地址
- **MissAV免防护墙爬虫 missav_api**：原MissAV爬虫常被防护墙挡住；现在多了一条免防护墙通道，不用费力绕墙也能直接刮到它的影片信息

### 新增功能

- **界面缩放比例配置**：在"设置 → 界面外观 → 高分屏缩放"设置区域新增缩放比例下拉框，支持"跟随系统"/80%/90%/100%/125%/150%/175%/200% 共 8 档选项（含非整数倍缩放）。选择非默认值时通过 `QT_SCALE_FACTOR` 环境变量（Qt6 原生机制）精确控制界面缩放，解决高分屏字体过大或过小的问题，并可配合暗色模式使用。保存后重启软件生效
- **内置 CF Bypass（零配置）**：新增"启用内置 Bypass"选项，勾选后 MDCx 自动在后台启动本地旁路服务（基于隐身浏览器），无需手动搭建外部服务。
- **新增设置项**：`cf_bypass_auto`（bool，默认 false），与外部 `cf_bypass_url` 互斥，地址为空时方能启用本地服务

### 刮削系统

- **四种刮削模式**：正常模式（全新刮削：扫描→刮数据→下图片→生成NFO→重命名→移动）/ 整理模式（仅归类文件，不下载图片不生成NFO）/ 更新模式（调整已有文件的目录结构）/ 读取模式（维护补刮，4个独立选项自由组合）
- **字段级优先级配置**：每个字段（标题、简介、演员、海报、评分等）可独立配置来源网站顺序和翻译开关，不同刮削类型还可设置不同的字段优先级
- **刮削模式**：支持 info（信息优先）、speed（速度优先）、single（单站快速）三种模式
- **刮削类型独立配置**：有码/无码/FC2/国产/欧美/素人每种类型可分别设置网站源列表
- **马赛克标准化**：自动将各类标签归一化为有码、无码、无码破解、流出、无码流出、国产
- **标签优先级系统**：基于 info_database.xlsx 的标签优先级排序，优先级标签→系列标签→其他标签

### 网络与反爬

- **CF Bypass 双模式**：支持 Mirror 模式（外部 bypass 服务代理请求）与 HTML 模式（调用 bypass 服务 `/html` 端点）
- **域名级独立限流**：每个网站独立令牌桶限流，默认 8 req/s，失败自动退避重试（403/429/500/502/503/504）
- **连接池管理**：三级连接池（HostPool → ConnectionPool → Session），域名级并发控制，Session 热更新，空闲自动回收
- **网络连通性检查**：内置一键测试各网站可达性工具
- **软链接支持**：可选择不移动原文件，创建软链接到目标目录

### 界面与工具

- **暗色/亮色主题切换**：内置完整双主题支持
- **海报裁剪工具**：图形化界面，鼠标拖拽选择裁剪区域，支持 2:3 标准比例
- **缺失文件检测**：检查媒体库中哪些文件缺失
- **成功/失败文件列表**：自动记录处理结果，支持断点续刮
- **多CD分集支持**：多碟片文件自动合并为一条记录
- **额外剧照处理**：自动下载多张剧照并管理副本
- **图片修复**：自动修复下载的图片（尺寸、格式等）
- **24 个命名模板字段**：番号、标题、演员、系列、制作商、分辨率、编码等，Jinja2 条件渲染
- **演员 NFO 生成**：生成 Kodi 兼容的演员信息文件（.actors 目录）
- **内置资源管理**：演员数据库、ASIN 数据库、NFO 信息数据库、字体等资源统一管理

### 配置系统

- **配置自动迁移**：旧版 INI 格式配置文件在加载时自动转换为 JSON 格式
- **配置热切换**：修改配置后自动生效，无需重启
- **敏感字段脱敏**：API Key 等敏感字段在导出时自动替换为 `***`

### 修复

- **网络标签页按钮重叠**：修复了设置页面里网络标签页的控件叠到一起、显示不全的问题，调整了各区域的高度和位置
- **Windows 下启动崩溃**：修复了 Windows 版打开时因 `topLevelItem(1)` 为空导致闪退的问题
- **R18.dev 补零位数**：番号标准化从 3 位补零改为 5 位，跟 R18.dev 数据库实际格式一致
- **fc2cmadb 演员数据爬取修复**：Inertia.js Deferred Props 导致的演员数据缺失问题。修复逻辑改为 Inertia JSON 解析后若 actresses 为空则回退到 HTML table 解析补充，同时增强 Inertia partial reload 请求头（注入 X-Inertia-Version 和 X-XSRF-TOKEN），解决已登录但爬不到演员的问题
- **fc2ppvdb Cookie 检查优化**：域名迁移至 fc2cmadb 后，Cookie 检查不再依赖 `fc2ppvdb_session` 关键字
- **刮削失败标题被日志污染**：修复 `main_window.py:1180` 中刮削失败后标题回退到 `LogBuffer.error().get()` 的问题——该函数会跨任务聚合其他任务的 TMDB 演员处理日志（如 `[演员数据库] 已新增 ... 并写入 tmdbid=...`）作为标题。改为使用文件名兜底
- **刮削过程更稳**：修好了多个任务同时刮时偶尔"串数据"的老毛病，演员信息写入也更省系统资源
- **修好 30 个第三方库的安全隐患**：把软件用到的外部工具库都升级到安全版本，整体更安全

### 改进

- **绕过网站防护墙更稳更快**：后台服务重写，启动不发呆、不卡死；安装包里直接带好隐身浏览器，装完即用，不用额外下载和配置
- **界面缩放优化**：放宽 Windows 窗口最小尺寸限制（从硬锁定 1089x700 改为 QSize(850, 550)），解决 1920x1080 125% 缩放下界面过大且无法缩小的问题

### 工程质量

- **推送前自动跑测试**：新增 pytest 推送前自检，`uv run check` 会自动执行 ruff 格式检查 + ruff 代码规范 + pytest 单元测试，三项全过才能推
- **新增一批测试用例**：R18.dev 14 个测试 + JavDB API 18 个测试，覆盖番号解析、字段映射、搜索匹配等工作

### 其他

- 软件内"使用说明"的内容已更新，过时的信息换成了最新的
- 新增一批自动测试，防止上面的问题以后又冒出来

## v1.4.0 (2026-07-07)

### 新增功能

- **Bing 翻译引擎**：新增 Bing 翻译选项，免费免配置，与 Google 一样自动爬取翻译接口，支持中/英/日互译
- **无码官网爬虫**：official 源扩展支持 Caribbeancom、HEYZO、1Pondo、Pacopacomama、10Musume 五个无码官网，番号自动路由到对应站点
- **official 官网前缀路由**：FNS/FALENO 与 DLDSS/DAHLIA 番号前缀自动委派给对应的子爬虫，扩大官网覆盖范围
- **fc2ppvdb 适配 fc2cmadb**：基础 URL 迁移至 `fc2cmadb.com`，新增 Inertia.js JSON + HTML 双模式解析，不再依赖旧版 fc2ppvdb XHR 接口

### 修复

- **avsex 更新修复**: 兼容 /cn/ 简体中文页面，修复 title/actor/tag/outline/extrafanart XPath 提取
- **iqqtv 标题清理**：去除标题末尾的 `caribbeancom_番号` / `1pondo_番号` 等站点前缀，避免污染无码影片标题
- **fix**: 图片简化命名(poster.jpg)在 skip_reorganize 和不移动文件路径下被忽略

## v1.3.3 (2026-06-23)

### 修复

- **xcity 刮不出中文**：修复了 xcity 刮出来全是英文的问题（加了请求头让网站返回繁体中文，再自动转成简体）
- **多任务同时刮会串数据**：修复了同时刮多个影片时，xcity 的数据会串到别的影片上的问题
- **预置4个默认代理**：amazon.co.jp、m.media-amazon.com、xcity.jp、dmm.co.jp 保障正常刮削 dmm、xcity及下载日亚高清封面

### 日志精简

- **日志去重**：同一行重复的日志不再刷屏了
- **去掉没意义的"(old)"日志**：之前每个文件都会刷"Poster done! (old)"这类消息（意思是"文件已经有了，跳过下载"），现在不显示了，日志减少了将近一半
- **报错提示不再重复弹**：图片下载失败时，"去设置里勾选xxx"的提示只出现一次，不再日志和错误提示各出现一次
- **翻译跳过不再逐行输出**：如果多个翻译引擎都不可用或跳过，现在汇总成一行显示，不再每个引擎占一行

### 日志合并

- **Poster 裁剪日志合并为一行**：以前裁剪海报时先输出"开始处理"，再输出"用了什么策略"，现在合并为一行，信息量不变
- **Poster 直复制缩略图日志合并**：策略说明和完成报告合并为一行

### 开发者工具

- **添加类型检查工具**：新增 pyright 配置，后续开发时能自动发现潜在的类型错误，减少发布后出问题的概率

## v1.3.2 (2026-06-22)

### 功能增强

- **刮削速度优化**：图片下载改成并行模式，缩略图下载完后，海报、剧照等会同时下载，不用排队等了
- **演员 TMDB ID 查询加速**：从 TMDB 查演员信息时，多个演员同时查（以前是排着队一个一个查），补演员改名翻译和网址也合并到一块写入硬盘，减少重复读写

### 界面调整

- **代理设置更清晰了**：原来的"不使用代理"改成了"使用代理"。现在只对你填进去的网站走代理，其他网站默认直连，不会出现代理影响国内网站的尴尬。默认预填了 `amazon.co.jp` 和 `m.media-amazon.com`

### 修复

- **Excel 字体大小不一致**：修复了往演员数据库和 Amazon ASIN 数据库添加新数据时，字体默认变成 12 号，和原来 11 号不统一的问题

## v1.3.1 (2026-06-20)

### 新增功能

- **新爬虫：JavDB APP版接口**：新增 `javdb_app` 刮削源，走的是 JavDB App 的接口，有码/无码/素人/FC2/欧美都能用，配置里对应的分类已默认加上

### 修复

- **欧美影片刮着刮着就超时**：修复了一个代码缩进错误。以前日系番号（如 `SSNI-111`）正常，但欧美番号（如 `Viv-thomas.24.12.20`）因为名字里带点号，程序错误地进入了"等待同番号"的死循环，干等 300 秒后超时报错。现在欧美番号也能正常刮了

### 界面调整

- **可用网站列表刷新**："可用网站"弹窗和"指定网站"下拉框现在和实际注册的爬虫保持一致，移除了已停用的 `avsex`、`love6`
- **无码分类编辑框不再出现有码站**：`javlibrary`、`libredmm`、`dmm_api` 不会再出现在无码的编辑网站对话框里

### 日志优化

- **分隔线不再用满屏 emoji**：以前每个任务开始和结束用 50 个连续 emoji（`👆`×50、`👇`×50）做分隔线，在某些电脑上显示为乱码方框，且日志文件体积巨大。改为 40 个等号 `====`，清爽多了

## v1.3.0 (2026-06-18) 重磅更新

### 新增功能

- 演员日文名更准了：以前填演员表用的是搜索用的中文名，现在改用 TMDB 返回的日文原名（像"三上悠亜"这种）
- 自动补演员网址：刮削完会自动检查哪些演员有 TMDB ID 但没网址，用日文名去 LibreDMM 找到网址填上
- 重磅更新,读取模式下，向已刮削的影片的NFO中补全写入演员tmdbid
- 前提条件：
  - 1.设置网络页面填入TMDB API KEY（没有的要去TMDB申请）
  - 2.设置NFO页面勾选"为演员写入TMDB ID"
  - 3.设置刮削模式为选读取模式，并勾选"允许更新 nfo文件"
  - 4.TMDB上要有这个演员的信息资料
- 注意：如果不想在补全演员tmdbid后，改变nfo中的演员名，请不要勾选设置翻译页面的"使用演员映射表翻译演员"
- 好消息：AVdb的LEO、龙王大佬们在持续补充 TMDB 女优资料中，lsj可以定期用读取模式去获取新增加女优的tmdbid了，不用重新刮削

### 读取模式改进

- **选项更灵活了**：4 个选项现在互不绑定。可以只勾"有 NFO 时更新"不勾"更新 NFO"，就只整理文件不改 NFO；也可以只勾"更新 NFO"不勾"有 NFO 时更新"，就只改 NFO 内容不挪文件

### 修复

- **NFO 里的 `<![CDATA[...]]>`** 改用正规解析，不会再因为内容里恰好有 `]]>` 而出错
- **正则表达式安全**：文件名中的特殊字符会先转义再匹配，不会崩
- **并发请求异常**：演员名查询时如果某个请求出错，不会让整个任务崩溃
- **被悄悄吞掉的错误日志**：演员数据查询中隐蔽的异常现在会写入日志

## v1.2.1 (2026-06-17)

### 修复

- 修复传统窗口模式下（未勾选"隐藏边框"），点击原生标题栏关闭按钮无响应问题
- 修复反序设置导致已有超链接单元格样式标记丢失

### 功能增强

- 完善 LibreDMM 演员链接自动补全功能
- xlsx 冻结窗格从 `A2` 改为 `B2`，同时固定表头行和第1列（番号列），横向滚动时始终可见
- 传统窗口模式下，点击关闭按钮同样遵循 `HIDE_CLOSE` 配置，支持"关闭时隐藏到系统托盘"

### UI 改进

- 更新设置翻译页面提示词，反映 xlsx 数据库格式和 TMDB 自动填充功能

## v1.2.0 (2026-06-16)

### 架构改进

- 将 `_read_actor_db_xlsx` 及列常量从 `tmdb_actor.py` 迁移至 `resources.py`，彻底消除模块初始化阶段的循环导入依赖

### 修复

- **#consts.py** `IS_DOCKER` 改为检测 `/.dockerenv` 文件，避免 Linux 桌面环境误判为 Docker
- **#number.py** `get_number_first_letter("")` 加空字符串保护，防止 `IndexError` 崩溃
- **#tmdb_actor.py** `_tmdb_request()` curl_cffi 分支补上 `follow_redirects` 参数，统一两种 HTTP 后端的重定向行为

### 功能增强

- **#file_crawler.py** `_normalize_release_value()` 增加 `YYYYMMDD` 无分隔符日期格式兼容
- **#tmdb_actor.py** 演员数据库首次发现为 `None` 时自动重试加载（延迟加载兜底），减少不必要的 TMDB API 请求
- **#tmdb_actor.py** 对 `update_actor_db_row()` 增加 `asyncio.Lock()` 防止并发写 xlsx 导致文件损坏
- **#resources.py** `reload_actor_db()` 文件不存在时不再重置 `actor_db` 为 `None`；异常时恢复旧值保留缓存；异常信息同步写入主日志和 traceback 日志

### 代码精简

- **#resources.py** `_get_mark_icon()` 7 处重复的 if-not-isfile-copy 合并为数据驱动循环
- **#number.py** FC2 / HEYZO 番号提取两个几乎相同的 elif 分支合并为一个，区分前缀和最小位数
- **#crawlers/** 12 个爬虫文件各自定义的 `split_csv` 函数统一为 `crawlers/base/types.py` 的共享函数，各文件 import 使用
- **#pyproject.toml** 添加 `[build-system]` 段，符合 PEP 517/518 打包规范

### 线程安全

- **#log_buffer.py** `all_buffers` 字典所有读写操作增加 `threading.Lock` 保护，消除多协程并发时字典损坏风险

## v1.1.0 (2026-06-13)

### 新增功能

- **Minnano-av 演员信息刮削源**
  - 新增 `minnano_crawler.py` 模块，支持从 みんなのAV 网站抓取演员信息
  - 支持中文→日文演员名映射（通过 `actor_database.xlsx` 查找日文原名后再搜索）
  - 实现模糊搜索匹配策略：精确匹配优先，其次多字符公共子串匹配，最后五十音回退搜索
  - 详情页加了标题核对，避免匹配到错误的演员

- **Emby 演员信息增强**
  - 在 Wikipedia 之前优先查询 Minnano-av 数据源，补充 Emby 演员元数据
  - Minnano-av 缓存文件 `minnano_cache.xlsx` 集成，避免重复请求
  - 缓存表头冻结、数据行全边框、URL 超链接，便于用户手动审查

- **Gfriends 头像本地仓库**
  - UI 新增"Gfriends 设置"区域：可以选择本地仓库路径、点按钮更新（拉取最新头像）、显示最后更新时间
  - 有本地仓库时优先从本地读取，不联网；本地没配置时才从 GitHub 网络下载
  - 更新按钮在没选路径或正在更新时禁用，防止误操作
  - 保存配置时，如果本地和网络都没填会弹窗提醒

- **Gfriends 头像升级：AI 修复版优先**
  - 找Gfriends 头像时优先用 `AI-Fix-名字.jpg`（AI 修复增强版），再找普通版

- **搜索链接中文兼容**
  - Graphis、Minnano-av、Wikidata 搜索时，演员名字自动做编码转换，解决日语名字搜索失败的问题

### 配置变更

- 新增 `gfriends_local_path` 配置项：填本地 Gfriends 文件夹路径即可启用本地模式

## v1.0.0 (2026-06-11)

MDCx-DIY 首个正式发布版，基于Hazard804改良的mdcx项目制作，对前辈表示衷心感谢！！！

### 刮削引擎

- 40+ 网站爬虫（有码/无码/FC2/国产/欧美）
- 新增 libredmm 刮削源（可刮削dmm下架影片）
- GenericBaseCrawler 统一框架 + 上下文隔离
- 智能番号识别与自动分类（用户预定义）
- 异步并发架构（asyncio + 渐进式任务调度）
- curl-cffi 浏览器指纹伪装

### TMDB 演员

- 新增 NFO 女优 TMDB ID 功能
- NFO 女优 TMDB ID 写入（需在 NFO 设置勾选 + 填入 API Key）
- 日文原名搜索，日本出生地 + 女性/未指定性别 + 精确名匹配过滤
- 多候选按 popularity 排序取最优，失败不阻塞刮削
- 令牌桶限流器（3.5 req/s，突发 10），并发 3 查询
- TMDB adult 候选自动跳过，搜索候选数优化为 5
- actor_database.xlsx用于nfo增加tmdbid和演员映射功能，反向搜索 + 增量写入，已预置部分女优数据，后续随软件使用动态更新（新演员若TMDB有数据就在表中追加数据，表中演员若TMDB数据更新，表中相关数据会追加）
- 超链接一致性校验与自动修复

### Amazon 高清封面

- ASIN 条码识别 + 三层搜索策略
- 封面 poster 固定 1500 尺寸（平衡质量和大小）
- 新增Amazon ASIN 缓存功能，通过Excel 缓存（amazon_asin_database.xlsx）
- 缓存去重逻辑，保护高置信度数据
- ASIN 缓存Excel随软件使用动态追加（同个影片二次刮削时不用再去Amazon查找，直接用表中数据下载高清封面）

### 数据源迁移

- actor_mapping XML + TMDB 缓存合并为 actor_database.xlsx
- mapping_info.xml 迁移为 info_database.xlsx
- 内置 xlsx 数据库，支持表头冻结，筛选、超链接等，用户可自行编辑或通过超链接审查数据

### 代理与网络

- HTTP/SOCKS5 代理配置
- 新增"不使用代理"网站选择器：40+ 刮削源下拉快速选择，智能域名匹配
- 默认 api.tmdb.org 不走代理

### 元数据与媒体

- NFO 生成器，30+ 字段，兼容 Kodi/Emby/Jellyfin
- 多语言翻译（Google/Bing/百度/DeepL/DeepLX/LLM 六引擎）
- Jinja2 命名模板引擎
- OpenCV 人脸检测智能裁剪
- 海报/背景图/预告片自动获取
- 字幕管理与缺失检测
- Emby/Jellyfin 演员信息补全 + 头像同步

### 界面与工具

- PyQt6 桌面图形界面
- 命令行工具（crawl、gen_enums）
- 构建工具链（build、bump、changelog、check）

### 工程质量

- 70+ 个测试文件覆盖核心模块
- CI：ruff format + ruff check
- Release：macOS DMG + Windows EXE
- 新增29 篇技术文档（架构、模块、API、迁移指南等）
