# Changelog

## v2.0.7 (2026-08-30)

### 修复

- **议题 #68 Windows 原生窗口边框下缩放/切页布局错乱**：`QStackedWidget` 只会把当前可见页 resize 到自身尺寸，休眠页永远停留在设计尺寸 820x692——「先缩放窗口再切页」时休眠页内组件全部按陈旧尺寸布局（日志页上栏只占设计高 61%≈292px 留大片空白、按钮按设计宽锚定飘出页面右侧/底部、工具页 scrollArea 右侧被裁），且 `show_hide_logs()` 硬编码 `resize(790, 418/689)` 会覆盖窗口缩放同步结果。修复：`_sync_page_layouts()` 先统一 resize 所有 stacked pages 再同步内部组件（沿用 #66 tab page 修复模式），`stackedWidget.currentChanged` 连接切页即时同步；日志页下栏隐藏时上栏铺满整页、显示时恢复 61:39 分栏；日志页/网络页按钮按页面右缘/下缘动态锚定；`show_hide_logs()` 移除硬编码改由 `_sync_page_layouts()` 统一处理。新增 `tests/test_window_state_matrix.py` 6 项矩阵回归（休眠页尺寸/先缩放再切页/日志收起铺满/设置页 12 tab/原生边框与隐藏边框两种模式）。附带修复测试基建：conftest `_DummySignals` 缺 `get_log()` 使任何带 `processEvents` 的主窗口测试触发 PyQt6 槽内 `AttributeError` → `qFatal` abort（qt_assert 栈崩溃的根因），已补空串桩
- **议题 #32 Jellyfin/Emby 演员刮取系列修复**（报告人 fork 真机验证方案吸收，四轮反馈逐层递进）：
  - **连接失败（Jellyfin 10.11+）**：后端重写起 auth middleware 要求完整 MediaBrowser 设备标识，仅携带 Token 的请求被拒。`emby_shared._build_jellyfin_headers` 补全 `Client/Device/DeviceId/Version` 字段（向下兼容 10.8+，17 个调用点统一受益）；连接测试 Jellyfin 分支去掉 URL 上的 `?api_key=` 明文密钥，统一走 Authorization 头
  - **演员列表 401/超时（Jellyfin 12）**：鉴权头修复后 `/Persons` **列表**端点仍对带 `fields`/`userId` 的查询返回 401/超时（报告人浏览器直接访问亦 401，早于鉴权修复即存在）；改走 `/Items` + `includeItemTypes=Person` 后真机验证全部成功（fork 767939287 的 c9a0e11/fb1f3c3）；`/Persons/{name}` 单演员详情在真机验证可用，保持不动。测试同步断言新端点
  - **大媒体库统计超时只认到单库（"仅识别 66 个演员"的根因）**：`fetch_person_item_stats` 每媒体库一次性 `Limit=100000` 全量拉取影片 People，>1W 演员的服务器上响应体过大导致服务端组装超时，同库连续 3 次连接超时后放弃——两个媒体库只统计到成功库的 66 个演员。吸收报告人 commit c412939a 的真机验证方案：改为 `StartIndex` 分页拉取（每页 500 条），加 `IncludeItemTypes=Movie,Episode` 与 `EnableImages=false&EnableUserData=false` 缩减响应体积；单库失败只跳过该库不阻断其余库，Emby 分支保持 `/emby` 前缀。测试 5 项锁定（禁 Limit=100000 / 分页递增与短页终止 / 缩减参数 / 失败跳过 / Emby 前缀）
  - 同批反馈的「补全头像 POST /Images 500」为服务端内部错误（本地请求格式已核对符合 API 规范），报告人正在清理库内 UTF 乱码损坏 item，待清理后复测、若复现需服务端日志定位
- **议题 #56 Emby/Jellyfin 演员信息更新与图片上传系列修复**（Emby 4.9.5.0 真机，1273 演员全量失败逐步修复）：
  - **401（鉴权头被条件分支置空）**：`emby_actor_info._process_actor_async:176` 用 `_is_jellyfin_server()` 决定是否加鉴权头——Emby 时返回 False → `headers=None` → POST `/Items/{id}` 完全不携带鉴权信息。改为无条件 `_build_jellyfin_headers()`（Emby/Jellyfin 统一带鉴权），测试锁定 Emby 分支 POST headers 必含 Authorization
  - **400（缺 Content-Type）**：`emby_actor_manager.update_person_info` POST `/Items/{id}` 的 body 是手工 `json.dumps` 字符串但 headers 只加 Authorization，缺 `Content-Type: application/json`——Emby 4.9 无法解析未声明类型 body 直接 400。补显式头，测试锁定 headers 断言
  - **500（图片上传 body 编码）**：Emby/Jellyfin 的 `Items/{id}/Images/{Primary,Backdrop}` 端点期望 **Base64 编码字符串**而非原始二进制（服务端日志 `System.FormatException: FromBase64Transform`）——原 `_upload_actor_photo` 直接把图片字节送 POST 导致解码失败。将 body 改为 `base64.b64encode(content).decode('ascii')`，Content-Type 保持不动；同函数被 `emby_actor_manager.upload_actor_image/backdrop` 共用，一次修复全局生效。新增 `test_emby_photo_base64.py` 3 项测试锁定（body 是 str + base64 可解 + Content-Type 保留）
- **议题 #57 NFO 库管理三个症状的修复**：
  - **保存后简介丢（表单不含的字段丢失）**：`_collect_form_data` 原从 `CrawlersResult.empty()` 新建，只填表单可见字段，`originalplot` / `external_ids` / `wanted` / `mosaic` / `outline_from` / `original_actors` / `actor_tmdb_ids` 等字段全部丢；现在改为从 `_nfo_lib_original_data`（加载时保留的原数据）继承表单没有字段的值
  - **简介读不出来**：`get_nfo_data` 读简介只查 `<plot>`/`<outline>` 元素，当数据只存在 `<originalplot>` 时无法读取；增加 fallback：当 plot/outline 均空时尝试从 `<originalplot>` 读取
  - **标签顺序保存后失效**：NFO 库管理保存路径会被 `prioritize_nfo_tags` 重排优先标签；给 `write_nfo` 新加 `preserve_tag_order` 参数，NFO 库管理保存/批量路径传入 `True` 保留用户原始顺序
  - **批量路径防御**：`_batch_modify` 的 `write_nfo` 调用补 `skip_merge=True + preserve_tag_order=True`，与单条保存路径一致
- **议题 #62 窗口最大化后页面内容不跟随缩放**：主窗口 resizeEvent 只同步 navigation/content/progressBar 三件套， Qt Designer 生成的绝对定位 scrollArea/tabWidget/textBrowser 不会被触发 resize，导致设置页/工具页/网络页/日志页/关于页中组件保持固定 796x658；新增 `_sync_page_layouts()` 方法， resizeEvent 内按长边(宽)量化脚本计算受遮区域，调用每个组件 setGeometry 统一拉伸（保留组件 X/Y 设计偏移，宽高按比例缩放），固定主窗口 1040x760 换算系数。新增测试 `test_ui_resize_sync.py` 4 项，同步覆盖方法存在/resizeEvent 调用检查/几何缩放逻辑/默认尺寸防御
- **议题 #66 窗口最大化后非当前标签页 scrollArea 不跟随缩放**：`_sync_page_layouts` 中 `tab_page.setGeometry` → scrollArea 链路上 `setGeometry` 不触发子组件 resize，隐藏 tab 的 scrollArea 永远停留在设计时 796x658。改为 tab_page.resize + scroll_area.resize + setGeometry 三段式，让 resizeEvent → QScrollArea→ viewport 全部完成。新增 offscreen 测试模拟「最大化 → 切换 tab → 当前 tab scrollArea 跟随」。修复前非当前 tab 的 scrollArea 不随窗口大小变化，修复后 12 个设置 tab 全部跟随
- **CI Windows charmap 修复（工程质量）**：测试脚本读源文件未指定 encoding，Windows runner 默认 GBK 解码中文源码崩溃；`test_ui_resize_sync.py`/`test_emby_photo_base64.py`/`test_jellyfin_actor_api.py` 等 4 处 open 调用补 `encoding="utf-8"`，全 CI 恢复绿
- **失败列表跨影片错误污染与日志缓冲无界残留（LogBuffer 任务树归因）**：`LogBuffer.get()` 原拼接【全局所有】任务的 buffer（c089eaf 为聚合 `create_task` 子协程诊断日志而引入），但并发刮削的兄弟影片任务（每片一个 `process_one_file`，task_id 互不相干）也被无差别拼入——实测毫不相干任务的 `error().get()` 混入别的影片的失败原因，随 `Flags.failed_list` 与 SQLite 断点缓存持久化，用户在失败列表看到多条影片混杂的错误无法定位；且 `clear_task()` 只清当前 task_id，兄弟与子任务的 buffer 全部残留，`all_buffers` 随刮削量无界增长。修复：引入 contextvar 任务树归因——写入统一按 root 落键（`create_task` 经 context 拷贝自动继承、`to_thread` 线程内 contextvar 经 `ctx.run` 可见，子协程与线程写入归因到发起者）；`get()` 只聚合本组（c089eaf 聚合子任务日志的意图保留）；`clear_task()` 按 root 整树回收；`process_one_file` 入口 `new_root()` 切断兄弟间继承。四性质由 `tests/test_log_buffer_tree.py` 锁定（兄弟隔离 / 子任务聚合 / to_thread 可读 / 整树回收 + 裸线程边界与单任务兼容），root 经 contextvar 作用域隔离不跨任务泄漏（实测验证）

- **五项实测复现的数据丢失/性能缺陷修复（全库代码审查）**：全部先写复现脚本确认（修复前红/修复后绿），审查报告中其余宣称项（裁剪死锁、连接池归还泄漏、Range 失效、CF 缓存、total_size 返回、is_proxy_host 子串误判、PIL 崩溃等 14 项）经逐项实测验证为不成立或已修，未改动。① **同路径移动删源（C1）**：更新模式扫描已整理目录时，算出的目标路径与源相同，软/硬链接分支"先删目标再建链接"会把源影片删掉并创建指向自己的死链接且返回成功——`move_movie` 两个链接分支入口加同路径守卫，实测复现源文件从完好变为 `Too many levels of symbolic links`；② **同名静默覆盖（C2）**：`move_file_async` 直接 `shutil.move`，目标已存在时无声覆盖（实测受害者内容直接消失）——默认语义改为目标存在且非同一文件时先重命名旧目标为 `{stem}_conflict_{ts}{ext}` 保留并记警告，另加 `overwrite=True` 参数供「临时文件落位」调用点（水印 `.[MARK].jpg`、裁剪 `.[CUT].jpg`、下载 `_temp` 等 12 处）显式覆盖，避免水印流程每次重刮留 `_conflict` 垃圾文件（审查中实测发现并修正）；③ **流式响应关闭退化成全量下载（C3）**：`_close_response` 原用 `aclose()`，curl_cffi 流式模式下它只 await 接收任务、把剩余响应体全部拉完才返回（实测提前放弃 4MB 响应仍阻塞 3.5 秒拉满全量，图片尺寸探测因此每张多下整图）；改用同步 `close()` 立即中止（实测同场景 0.00s 返回、服务端只发已消费部分，同 session 后续请求复用正常；curl_cffi 0.16 在中止流后关 session 有库内 TypeError，与真实链路一致地由 `_close_sessions` 的 suppress 吸收）；④ **NFO 评分恒为 0.0（C5）**：`BaseCrawlerResult.empty()` 把 `score` 初始化为 `"0.0"`（truthy），字段优先级合并的 `not getattr(reduced, field)` 判定恒 False，爬虫返回的真实评分全部被丢弃（实测站点返回 8.5 被跳过）、Emby/Jellyfin 全库评分空——`score` 初始化改空串；⑤ **并发建目录竞态（H13）**：13 处 `if not exists: makedirs()` 的 check-then-act 中间有 await 让点，并发写同一目录必抛 `FileExistsError`（实测 12 并发每轮 2-3 失败，extrafanart 批量下载即此场景）——统一 `makedirs(..., exist_ok=True)` 并加全库哨兵测试禁止裸 makedirs 再出现。新增回归测试 12 项（数据丢失守卫 4 + 流中止 3 + 评分合并 3 + 目录竞态 2），全量 1455 项通过

- **保存设置/停止刮削后内存占满卡死（议题 #55）**：两个时机是同一条泄漏链的上下游。`ComputedLease.__exit__` 通过 `executor.submit` 异步提交 `Computed.release()` 释放网络栈租约，而点「停止」调用的 `executor.cancel_async()` 会无差别取消所有 pending future——刮削中事件循环繁忙、release 尚在排队即被取消，租约计数永久 +1 且永不归零；此后点「保存」末尾的 `load_config` 会重建整个网络栈（AsyncWebClient + LLMClient + httpx/curl_cffi 连接池），旧栈交给 `close_when_idle()` 而该函数以 0.2 秒周期无上限轮询 `_is_idle()`，租约不归零则永不退出，旧栈连同轮询协程永久驻留。实测「刮削→停止→保存」循环 8 轮累积 10 个网络栈与 28 个 pending 协程，线性增长直至事件循环饥饿卡死。修复三处：① `AsyncBackgroundExecutor` 新增 `submit_critical` 关键任务通道，`cancel`/`cancel_async` 跳过该通道，`ComputedLease.__exit__` 改走关键通道确保 release 必然执行；② `AsyncWebClient.close_when_idle` 与 `LLMClient.close_when_idle` 增加 300 秒超时兜底，超时记警告并强制 `close()`，杜绝无限轮询；③ 配置迁移补齐 2026-08 精简的 15 个站点值（cnmdb/hdouban/mdtv/love6/kin8/giga/cableav/7mmtv/hscangku/fc2club/fc2hub/jav321/fantastica/dahlia/faleno）清洗，覆盖 `website_*`/`field_configs`/`type_field_configs.site_prority`/`site_configs` 与 `website_single` 回落——旧配置残留这些值会让 pydantic 校验整体失败（实测某用户配置报 152 条错误），导致保存目标被改指 `_failed.json` 且界面回写跳过，表现为「保存不生效」。修复后同一循环 8 轮网络栈稳定不增长

- **视频整理模式演员名不映射中文（议题 #53）**：演员映射 `translate_actor` 与标签/系列等信息映射 `translate_info` 原被 `if not pre_data and update_nfo:` 一并包住，而整理模式（主模式 2）不写 NFO 使 `update_nfo=False`，整块映射被跳过，`res.actors` 保持爬虫返回的日文原名，命名变量 `{actor}/{first_actor}/{all_actor}` 与 `{tag}/{series}/{studio}` 因此输出日文，文件夹名不走演员数据库中文名。映射服务于命名变量而非仅服务 NFO，故将条件解耦为 `if not pre_data:`：演员/信息映射与 `replace_word` 无条件执行，LLM 标题/简介翻译 `translate_title_outline` 与演员 TMDB ID 查询（须在映射前用日文原名）保留在内层 `update_nfo` 分支，整理模式不引入额外网络开销；新增 AST 结构哨兵测试锁定调用位置防回归

- **official 无码官网 studio 字段污染**：1pondo/10musume/pacopacomama JSON 的 UCNAME 键实为分类标签数组，原取值链误作厂牌导致 studio 产出脏值且三站标签全空；改为 Maker/Studio 取值 + 站点兜底，UCNAME 归入 tags 来源
- **DMM 图占位图误判通过**：pics.dmm.co.jp 等 DMM 图床对无效/下架对象会返回 HTTP 200 但仅 142B~2.7KB 的垃圾体，此前 check_url 仅靠 200+Content-Length 判定存在导致占位图被当真实封面入库；真实 DMM 封面最小也 ≥10KB。`_validate_dmm_image_url` 新增 `_DMM_PLACEHOLDER_MAX_BYTES=4096` 阈值，字节数低于 4KB 直接判失败且不可重试
- **网络检测多项修复**：搜索解析无结果的爬虫自动回退真实刮削路径探测，消除"可达但无法探测"误报；missav_api 检测改走真实搜索（Recombee 仅接受 POST）；dmm_api 补全 v3 ItemList 必需参数；javlibrary 移除自定义 URL 强制直连的逻辑（避免 CF Bypass 被一并阻断）；探测失败提示动态携带实际番号
- **dmm_api 爬虫修复**：keyword 改用 content_id 形态候选序列（带横杠番号搜索为 0 结果）；`iteminfo` 模型类型放宽修复真实响应校验崩溃
- **DMM 高清直链学习闭环修复**：主爬虫同时接受 pics.dmm 图源证据写入前缀学习表，静态前缀表外的新站内前缀系列不再永久缺失高清图
- **UI 修复**：网络设置代理说明对齐 Cookie 获取方法排版；NFO 库管理"批量保存"提示最小高度提高避免 Windows 下文字截底；补足左侧导航容器高度恢复"使用说明"按钮；使用说明内容全面更新对齐当前版本
- **检测网络页小白友好化**：结果按状态着色（✅绿/⚠️橙/❌红）；新增「打开网络设置」按钮一键跳转设置页，三按钮补 tooltip；复制结果自动附带版本/系统概要诊断头且代理地址脱敏；表头与启动横幅代理地址改为 `hos***:port` 脱敏（修复忘剥 scheme 导致 host 泄露的脱敏 bug）；「代理不可用（见顶部提示）」指向修正为「见下方汇总区」；JavDB 封禁文案明确"节点出口 IP"避免误以为本机被封；401/403/429 合并文案拆分为三条带具体动作的引导；"没有固定入口"SKIP 与"测试番号未收录"WARNING 文案补充"属正常/可忽略"说明降噪；外部 CF 服务未配置时补占位项（与 CF Bypass 行为拉齐）

### 功能

- **新增三个爬虫**：
  - **javfree**：javfree.me 收录有码/无码/FC2（素人），按条目分类判定（mosaic=有码，avi/demosaic=无码；提供去码版的番号会同时挂多重分类，判定取最深路径）；搜索直接命中带横杠番号，FC2 转 `FC2-PPV-数字` 形态；封面取 HLIC 大图，数字后缀剧照作 extrafanart；站点有 IP 级 429 限流，需放慢请求。默认加入有码+FC2 网站源，默认走代理
  - **aventertainments**：aventertainments.com 无码站，同时收录 DVD 与 PPV（按番号形态自动走路径）；PPV 分隔符区分厂牌（横杠 082226-001 仅 carib，下划线 082226_001 返回 1pondo+carib）；仅收录 caribbeancom/1pondo 两厂牌，覆盖窄，默认排无码源末位、默认走代理
  - **madou_club（麻豆社）**：madou.club 收录麻豆系国产番号，搜索须无横杠关键词；封面从搜索页缩略图去尺寸后缀升级原图；CF 对桌面指纹拦截强，接入 Safari iOS 专属指纹池
- **精简 15 个冗余/失效爬虫**：失效站 cnmdb/hdouban/mdtv/love6/kin8/giga/cableav/hscangku + 7mmtv/fc2club/fc2hub（新上 CF JS 挑战需外部 Bypass 服务，维护成本高于价值）；数据重复站 jav321/fantastica + dahlia/faleno（被 DMM 系与综合站覆盖）。dahlia/faleno 模块保留为 official 的 DLDSS/FNS/JIMMY 厂牌子爬虫（不再独立暴露）；thejavdb_api 转为默认启用加入有码源；注册爬虫 48 → 33，旧配置中的已删站点自动跳过迁移
- **无码官网五站接入默认代理列表**：caribbeancom/heyzo/1pondo/pacopacomama/10musume 及 mywife 实测需代理访问，加入默认「走代理网站」域名列表
- **JavDB 全系图源无水印升级（App CDN 加密流解密）**：JavDB App 专用 CDN `tp.spfcas.com` 返回单字节 XOR 加密流（首字节为随机 key），解密后为无水印原图；网页版 CDN `c0.jdbstatic.com` 是同图带 javdb 水印版本。新增 `base/web.py::decrypt_spfcas_image`（XOR 解密 + JPEG SOI 有效性校验，`bytes.translate` 实现）与按域名判定的 `decode_spfcas_image_content` 统一解密入口，注入全部图片落盘路径（`MediaResourceContext._fetch_image` / `download_file_with_filepath` / `download_content_with_filepath`）——javdb_app 爬虫直接产出 spfcas URL 透明获得无水印封面/海报/剧照；javdb 与 javdb_api 的网页版 URL 由下载层前置 `jdbstatic_to_spfcas` 无水印变体自动升级（thumbs↔small_covers 路径映射），失败自然回退原图。App CDN 路径中段（`rhe951l4q`）可能随服务端调整变更：`learn_spfcas_image_segment` 由 javdb_app 每次响应学习自愈，中段过期时变体 404 自动回退网页版、行为退化为改动前；poster 选优（auto_best）模式下加密流尺寸探测失败用逆向网页版 URL 探测同图尺寸回退。解密失败（SOI 校验不过）按下载失败处理走 DMM 兜底链，不落坏图。新增 10 项回归测试（判定/解密/双向变换/中段学习/变体优先与回退/尺寸探测回退）

### 优化

- **DMM 直构静态路由种子 v2（libredmm 全站归纳 + 老片 append 兜底）**：刮削中发现的"libredmm 可反查真实 cid"路线固化为离线知识。libredmm.com `/movies` 列表页缩略图 src 自带完整 DMM 图床 cid，全站 23472 页 58.9 万「番号↔cid」对全量抓取后归纳为 `resources/userdata/dmm_cid_routes.json`（随包分发，1.8MB）：9267 个系列的 prefix→cid 构造规则 + 10530 条重编号白名单，`dmm_direct` 惰性加载——路由命中的系列（静态表需 `_COMMON_PREFIXES` 10 连盲试的冷门厂牌）首候选直达真实 cid，白名单特例番号精确返回唯一 cid，全链路零额外请求、彻底摆脱 libredmm 运行时代理依赖。安全过滤两轮演进：v1 发现 libredmm 同名番号被同名老厂牌占据（SSIS-001 在其记录中是 80 年代 mono 老厂牌 `k9ssis001` 而非 s1 的 `ssis00001`，IPX/SONE/MIDV/CAWD 等 8 系列直接注入会全部污染候选顺序）——但整体弃用静态表覆盖系列矫枉过正，把 GVG 等老片系列的真实 mono 3 位数据也丢了（日亚重裁决时 517 行裁判图 miss 暴露缺口，如 GVG-564 真实 cid 是 mono 的 `13gvg564`）；**v2 修正为 append 分级模式**：静态表覆盖系列的路由候选追加在静态表候选之后兜底（静态表保序首位、高频系列顺序零污染），未覆盖系列保持 first 一步直达，combo 按 digital 路径/5 位优先排序，老片番号静态表 5 位 miss 后由路由 3 位候选救回。`test_high_frequency_series_first_candidate_unchanged`/`test_append_mode_legacy_three_digit_fallback` 等 12 项回归测试锁定。`clean_asin_db_conflicts.py` 裁判链同步切换到生产直构器（废弃的 thejavdb API 链路清除）
- **javdb_app 签名失效 fail-fast 诊断与常量环境变量覆盖**：jdsignature 常量内嵌于 JavDB App APK，App 发新版可能轮换——届时三个 API 主机会同时返回 `InvalidSignature`(HTTP 400)/`ParameterInvalid`/401/403 类失败，原实现只记笼统的"API 请求失败"。现在统一响应包裹的错误 action（含 200 错误体）与 HTTP 状态码被归类为签名类失败：全部主机命中时直接给出明确诊断（签名常量可能已轮换、升级 mdcx 或设置环境变量），不再流入解析产出误导性的"未找到影片"；`MDCX_JAVDB_APP_SIG_PREFIX`/`MDCX_JAVDB_APP_SIG_SUFFIX`/`MDCX_JAVDB_APP_VERSION_NUMBER` 三个环境变量可免改码覆盖签名常量与版本号（连通性检测共用同一签名，同步生效）。搜索请求补 `type=movie` 过滤噪声与 `limit=50`（服务端上限，实测超限静默截断，默认偏小会漏精确命中）。机制文档沉淀 `docs/JAVDB_APP_SIGNATURE.md`
- **刮削失败原因 Top N 摘要**：大批量刮削结束后，失败明细前新增按类别聚合的摘要行（如 `📊 失败原因汇总（Top 3）：请求超时 23 个 ｜ 站点未收录 15 个 ｜ 番号未识别 8 个`），并根据头部类别给出一条可操作建议（超时→检查代理/调大重试、被拦截→换免 CF 通道、限流→降并发、未收录→调网站源顺序、番号未识别→整理命名、权限不足→管理员运行）。文本归一规则取自真实失败文案（`mdcx/core/fail_reason_stats.py`），用户不再需要逐条翻看几十条失败日志找主要矛盾
- **刮削进度预计剩余时间**：状态栏进度从「🔎 已刮削 320/5000」升级为「🔎 已刮削 320/5000 · 剩余约 2 小时 15 分」，大批量刮削时用户可感知进度节奏。基于最近 30 个完成事件的滑动窗口速率估算（少于 8 个样本不出估算，避免前期抖动给出误导数字），纯呈现层实现零流程风险（`mdcx/core/scrape_progress.py`）；完成回调对 estimator 的记录与文本附加由 AST 哨兵测试锁定
- **LLM 翻译同批次缓存**：系列片/合集片标题与简介高度相似，重刮失败列表时也会重复翻译完全相同的文本——LLM 按 token 计费，重复翻译纯浪费。新增进程内 LRU 翻译缓存（`mdcx/core/llm_translate_cache.py`，512 条）：相同 (prompt, 目标语言, 原文) 直接复用译文，**并发相同请求自动合并为一次调用**（in-flight Future 共享），翻译失败不缓存以便重试；缓存绑定 LLM 配置指纹（模型/接口地址/关闭思考开关），切换模型或服务商后自动失效重建。系列片批量刮削与失败列表重刮场景显著省 token 与时间
- **ASIN 数据库读零校验（信任快车道）**：ASIN 库随版本交付时番号↔ASIN↔封面图已经四源校验工程全量验证（图像双源 + 标题归一 + tenhow cid 结构化反查，主表 26580 行零错挂），刮削时库命中的番号直接采信下载日亚高清封面，**不再逐次软校验**——省去每片 1-2 次参考图下载与相似度比对。软校验保留唯一战场：搜索**新发现**的 ASIN 入库前必须通过图片相似度门槛，从源头拦截错配入库。连带移除「严格校验 Amazon 图片」开关（读零校验架构下语义为空：库命中无条件信任、新入库无条件必验），旧配置残留键由迁移静默清洗并提示
- **软校验裁决链 v2（新 ASIN 入库门槛升级）**：软匹配路径（标题/演员搜索发现）的入库裁决从单一图像比对升级为三步证据链——① **tenhow cid 旁证**（零请求本地查表：`resources/userdata/tenhow_asin_cids.json` 离线索引 36441 条映射，cid 反查番号一致即实锤、不一致强警示阻止）；② **标题门**（NFKC 归一系列互含——半角片假名/全角字母/括号特典统一，同系列不同集号/合集包装可判同片；**合集词一票否决**：日亚标题含 BEST/コンプリート/N時間/特典直接不入库，此为四源校验工程实证的错配最大病灶）；③ **图像门兜底**（无 cid 无标题证据时沿用现有相似度比对）。新模块 `mdcx/core/title_match.py`（标题归一算法产品化，303+34 行翻案零冤案实证）与 `mdcx/core/asin_cid_index.py`（367 行零误判实证）。**入库时序重构**：软匹配的写库从搜索阶段延迟到软校验通过后（`_save_asin_record` 从 soft 路径 4 处移除，统一在 web 采信点 `_save_verified_asin_record` 延迟入库）——v2 判失败的候选不再污染数据库；条码/番号硬匹配路径维持发现即入库（免验路径语义不变）。演员名兜底路径（错配重灾区）全链必走；主搜索路径的标题证据复用搜索阶段已聚合的商品标题（`amazon_match_state` 新增 title/search_keyword 携带），零额外请求
- **ASIN 数据库查询内存索引**：`query_asin_database` 原实现每次查询都全量解析 4 万行 xlsx（实测 2.2 秒/次），而刮削热路径每个影片都查一次 ASIN 缓存（`_check_asin_cache`）——刮 1000 片仅此一项就浪费 36 分钟纯 I/O。新增进程内双索引缓存（number/asin → 记录列表）：首次查询建索引，此后命中内存（实测 0.08ms，约 3 万倍加速）；文件 mtime 变化（写入/合并/工具清洗）自动失效重建，解析失败保留原有日志语义。演员/信息库的后台惰性加载（`start_data_loading`）此前已就位，本次补齐 ASIN 库最后一块
- **DMM 高清直链升级推广到 11 个聚合/综合站爬虫**：`upgrade_dmm_cover`（横版 pl + 竖版 ps 双升级，自带无码跳过 + TTL 缓存 + 并发合并 + 失败回退原图）此前只接入 javbus/javdb/javdb_api/javdb_app/javlibrary/r18dev 六个主流爬虫，本次推广到 airav_cc/avbase/avsex/freejavbt/iqqtv/javday/javfree/lulubar/missav_api/thejavdb_api/xcity——其中 freejavbt/javday/iqqtv/lulubar 等爬虫原本 poster 为空，升级后首次获得竖版高清海报（poster 是 Emby/Jellyfin 显示质量关键字段；兜底链 `find_valid_dmm_cover` 只救 thumb 不写 poster，内嵌升级是唯一能给 poster 换高清的路径）；xcity 的 thumb=背面/poster=正面语义保持；avbase 保留其原有 pics→aws 域名升级链与之互补。新增 `test_dmm_upgrade_coverage.py` 4 项 AST 哨兵锁定 17 个爬虫的升级链防未来重构断链
- **字段来源日志降噪（失败站点标记去重）**：字段优先级合并时对已失败站点的"(已失败, 跳过)"标记原按【字段×站点】逐条追加——同一站点的失败信息在单文件内重复 20+ 次（约 20 个字段各打一行），实测（议题 #55 报告日志）66 个失败文件的会话产生 9400 行重复标记、每文件平均 142 行，占单次会话 5.5 万行日志的 17%。改为站点级去重：每站点的失败信息只记一次（文案改为"已失败, 后续字段将跳过该站"），后续字段静默跳过，该部分降噪 99%（同场景 9400 行 → 约 130 行）；信息无损——每个失败站点仍清晰可见，站点失败原因仍由"所有刮削来源均未返回可用数据"总结行完整给出。新增 2 项回归测试锁定去重行为与信息完整性

- **ASIN 缓存命中优先走 tenhow 图床直连下图**：`get_big_pic_by_amazon` 的 ASIN 数据库缓存命中后（无论是否已存封面 URL），先探测免代理图床 `tenhow.net/images/{ASIN}.jpg`（实测图片与日亚 SL1500 同分辨率 ~1055×1500，即日亚原图本体，抽样 8126 个 ASIN 100% 可用），命中即高清直返；图片低于 600×800 或不存在时回退原缓存封面 URL，再不行回退日亚搜索。tenhow 地址仅当次使用，不写入数据库，poster_url 列保持纯日亚来源语义。免代理、绕开日亚 CAPTCHA/429，覆盖率约 9%（数据库内 tenhow 来源记录）
- **Amazon 软校验参考图缺失兜底**：`_verify_soft_amazon_poster` 在本地无 thumb 且爬虫 poster 来自 Amazon 自身（自证被滤）时，按番号直构 DMM 官方图作裁判（竖版 ps 优先，降级横版 pl 裁右半），避免该边缘场景直接放弃软匹配
- **ASIN 数据库冲突清洗工具**：新增 `scripts/clean_asin_db_conflicts.py`，用图像相似度（`_cover_similarity` 阈值 0.82）裁决一 ASIN 多番号冲突，基准图取 tenhow/库内 poster_url，裁判图源优先级：thejavdb api（`api.thejavdb.net`，直接返回 DMM 图 URL）→ 直构 DMM cid 前缀枚举（ps/pl 裁右半）；错配行移「待修正」sheet 保留待补，完全重复行删除，默认预览、`--apply` 执行、`--limit` 冒烟采样
- **高分屏缩放默认启用非整数倍缩放（PassThrough）**：Windows 125%/150% 等系统缩放下界面不再被取整导致模糊或过大；原勾选开关移除，老配置静默忽略
- **有限收录站点定制探测番号**：mgstage/mywife/prestige/getchu/avsex/xcity/fc2 系列及国产/素人类站点改用各站实测收录的番号探测，消除"测试番号未被收录"误报；综合站维持默认 SSNI-647
- **站点选择列表双标注**：客观区域标签作为显示后缀（dmm/mgstage「日本IP限定」，javdb/javdb_api「勿用日本节点」，数据源唯一收敛于 `ManualConfig.SITE_REGION_TAGS` 并由测试锁定键集合）；「检测网络」结果持久化到 userdata 缓存，三个站点下拉框显示最近实测状态圆点（✅可连通/⚠️需关注/❌连不通）并在 tooltip 附检测时间与路由（走代理/直连）；显示文本带标签不影响配置取值（UserRole 存纯站点值，全部消费点统一切换）
- **检测网络按钮实时进度**：检测进行中按钮文本显示 `停止检测 done/total`，结构化进度回调经 Qt 信号回主线程，不新增布局控件；点击仍可取消（判定改为前缀匹配）
- **"全部走代理"开关（默认关）**：网络页新增开关，开启后所有请求发往代理地址，分流规则交给代理软件（Clash 等）裁决，「使用代理网站」列表不再生效；is_proxy_host 支持 `*` 通配，三处路由判定（爬虫请求/检测页路由列/LibreDMM 演员图）统一走 `Config.proxy_hosts_list()`。注意会显著增加代理流量消耗
- **Emby 演员管理器可最大化与拖拽缩放**：补最大化按钮（原仅最小化无可拉伸满屏），初始尺寸从最小 1100×700 改为屏幕可用区 80%，右下角加尺寸手柄；内部为布局管理器结构，拉伸后表格/预览区正确跟随
- **madouqu 动态域名**：接入官方发布页 wangzhi.icu/config.js 实时解析域名列表（24h 缓存+静态回退），默认域名迁移至 madouqu.shop；搜索失败自动切换镜像
- **站点级 CF 指纹池扩充**：新增 lulubar 与 missav 全镜像专属指纹池，按 host 自动路由并支持重试轮换排除上次失败指纹
- **javbus 镜像池清理**：移除已 SSL 失效的四个镜像，保留实测可用域名
- **LLM 翻译支持关闭思考模式**（#54）：设置页 LLM 区域新增「关闭思考模式」开关（默认关），勾选后按服务商自动下发关闭参数——硅基流动/阿里百炼 `enable_thinking:false`、火山方舟 `thinking:{type:disabled}`、Ollama `think:false`、Gemini(OpenAI 兼容) `reasoning_effort:none`；服务商返回 400/422 参数错误时自动去掉该参数重试一次；未收录的服务商不下发任何参数，跟随模型默认行为。新增 `tests/test_llm_disable_thinking.py` 覆盖服务商参数映射与去参重试判定逻辑
- **getchu_dmm 合并进 getchu**：两者同源同实现，合并后里番文件路由与 UI 文案统一指向 getchu
- **r18dev 解析兼容**：parsel `Selector.get()` 对纯 JSON 文本直接返回 dict，JSON API 爬虫解析入参兼容 str/dict/Selector 三态
- **命名规则说明补充**：明确勾选「成功后不移动文件」时同样不会创建视频目录

### 文档

- **README Telegram 群地址更新**：徽章链接 `t.me/mdcx_chat` → `https://t.me/+OVnB6Cw8gkxlYzM1`；`mdcx/views/MDCx.ui` 使用说明补群地址

- **文档与 UI 文案全面对齐代码**：注册爬虫数统一为 35（README/DEVELOPMENT/FEATURES/main_window 弹窗/UI 使用说明）；models.py 注释分组修正（AVMOO、TheJavDB-API 标注为「仅能有码」，枚举顺序与配置默认不变）；DMM 高清封面来源清单补 JavLibrary（共十站）；水印功能描述按图标徽标+角落轮转实际行为重写；MGStage pb_e 兜底图尺寸 840~980 修正为实测 840 宽；命名变量表删 tag/ext/cd/codec 四项、补齐 24 个真实变量；「强制重刮」表述改为「重新刮削/输入网址重新刮削」并说明绕过断点续刮；多集识别默认后缀与「允许识别分集」开关说明对齐字段检测实际行为；删除不存在的「每域名令牌桶限流（默认 8 req/s）」描述；指纹池 6→7 种；代理默认列表补齐 aventertainments.com/javfree.me 等 33 个域名；设置页 12 Tab 名称与功能分组对照表补入 CONFIGURATION；演员数据库 9 列清单修正为日文原名/中文名/繁体名/别名/链接/tmdbid/tmdb url/出生日期/简介（与代码 DB_HEADERS 一致）；USER_GUIDE 扫描/开始流程改写、设置入口改左侧导航、Tab 名修正；INSTALL 删除 Docker 占位节、修正 release 产物名为 MDCx-...-windows-x86_64.exe / macos-aarch64.dmg；DEVELOPMENT 爬虫统计 types→model_types.py、主窗口行数 3400→9600、Windows CI runner 说明 windows-latest vs release windows-2025、pyright 说明未入 CI 门禁；QUICKSTART 扫描/开始流程与 Tab 名修正

- **设置页「跳过前置 Poster 大小校验」说明文案修正**：原「不因当前 Poster >=400KB 跳过 Amazon」改为「不因当前 Poster 已达标跳过 Amazon（DMM >=700px / >=400KB / 不小于右裁剪）」，对齐前置校验实际含三条分支（DMM 宽≥700 快路、YOUMA 裁剪面积比较、字节≥400KB）

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
