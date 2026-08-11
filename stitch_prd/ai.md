## **知衍**——AI知识进化工坊系统 - 产品需求文档（PRD）

**当前版本**：V3.7  
**日期**：2026年7月28日  

### 版本历史

| 版本 | 日期       | 变更摘要                                                     |
| ---- | ---------- | ------------------------------------------------------------ |
| V3.5 | 2026-07-28 | • 全面采用 Milvus Lite 轻量化向量存储<br>• 新增视频字幕识别与图片OCR素材处理<br>• 新增 4.10 业务流程章节<br>• 引入 RabbitMQ 作为核心消息队列，替换 Redis Celery broker<br>• Redis 简化为缓存/验证码/分布式锁<br>• 定时任务由 Celery Beat 统一管理，移除 APScheduler<br>• 新增知识库分享功能，支持未登录访客只读访问<br>• 知识进化新增 AI 自动 / 手动确认两种模式，流式思考可视化<br>• 全面集成 deepagents 作为核心智能代理框架 |
| V3.6 | 2026-07-28 | • 游戏化学习模块新增题目自动校验与沙箱轮询机制：题库智能体生成题目后须通过沙箱模拟验证，失败自动重试修正（最多3次），确保游戏可玩性 |
| V3.7 | 2026-07-28 | • 引入 RAGFlow 作为核心知识检索与增强生成引擎，替换自建的 LangChain 分块 + 手动混合检索方案<br>• 启用 RAGFlow 多路召回（向量检索、全文检索、知识图谱检索）与融合排序<br>• Elasticsearch 升级为必需组件，作为 RAGFlow 的全文索引与文档存储<br>• 移除自建混合检索代码，改为 RAGFlow 集成配置 |

---

## 1. 项目背景与目标

### 1.1 背景

传统知识管理工具仅提供静态存储与检索，缺乏主动进化机制，且用户被动接收信息，知识内化效率低下。现有AI方案多依赖商业API、需企业资质，个人部署成本高。 
本项目旨在构建一款 **全开源、零企业认证、支持多模式登录** 的智能知识进化平台，通过循环工作流驱动知识库自我迭代，并以游戏化设计强化学习闭环。

### 1.2 产品目标

面向学生、研究者、创作者，提供 **素材采集→智能处理→自动进化（可选人工审核）→游戏化内化→可视化分析** 的全链路知识管理服务。核心技术栈均采用免费/开源方案，个人开发者可零成本运行。

### 1.3 目标用户

- 学生：整合课程笔记，自动梳理知识体系，游戏化复习。
- 研究人员：追踪文献知识演变，发现隐性关联。
- 内容创作者：构建灵感库，通过知识图谱拓展创意。

---

## 2. 产品概览

### 2.1 产品形态

Web全栈应用，前后端分离，支持本地或云端部署，通过浏览器访问。

### 2.2 核心流程图

```
多方式登录（账号/微信/手机）
 → 知识录入（上传/链接/文本/视频/图片）
 → MCP工具集自动清洗、转换（含音视频转写、OCR）
 → 异步任务经 RabbitMQ 调度
 → 清洗后文本交付 RAGFlow 管道：智能分块 + BGE-M3向量化 → 存入 Milvus Lite + ES 全文索引
 → 提供智能问答、总结、纠错（基于 RAGFlow 多路召回）
 → 知识库分享（生成访问链接，未登录可查看）
 → deepagents 知识进化（自动/手动模式，流式思考可见）
    ├─ 自动模式：智能体群自主校验→修正→拓展→出题→沙箱验证→更新
    └─ 手动模式：智能体生成建议→用户审核确认→更新
 → 游戏中心（闪卡/大富翁/配对，支持自选难度，题目已通过沙箱验证）
 → 知识图谱可视化 + 学习报告
 → 个人设置（自动进化开关、默认模式、登录绑定）
```

---

## 3. 用户角色

| 角色           | 说明                                                         |
| -------------- | ------------------------------------------------------------ |
| 普通用户       | 系统核心使用者，拥有独立知识库，管理素材、使用AI、选择进化模式、审核建议、游戏学习、查看数据，可创建分享链接 |
| 访客           | 通过分享链接访问知识库，无需注册登录，仅拥有只读权限（查看、搜索、AI问答） |
| 管理员（扩展） | 系统监控、用户管理、全局配置（暂不详细设计）                 |

---

## 4. 功能需求

### 4.1 用户管理模块

- **注册/登录**：支持三种方式：  
  1. **账号密码**：用户名+密码注册，密码哈希存储（bcrypt）。  
  2. **微信扫码登录**：接入微信开放平台测试公众号，通过OAuth2.0获取用户openid，首次登录自动创建账号并绑定。  
  3. **手机验证码登录**：集成阿里云号码认证服务（Aliyun Cloud Auth），发送6位数字验证码，60秒内有效。首次登录自动创建账号。  
- **账号绑定**：已登录用户可绑定/解绑微信和手机号。  
- **个人中心**：修改昵称、头像，查看知识库统计与成就徽章，**管理分享链接**。  
- **权限隔离**：所有用户数据严格隔离，JWT令牌包含用户ID。访客通过分享令牌临时授权，仅可访问指定知识库。

### 4.2 知识素材管理模块

- **多源导入**：
  - 本地上传：支持 TXT、MD、Word、PDF（最大10MB）。
  - 网页链接输入：调用Fetch MCP抓取公开文章纯文本。
  - 手动输入：富文本编辑器提交。
  - **视频素材**：支持 MP4、AVI、MOV、MKV（≤200MB或提供URL），自动提取语音转字幕文字。
  - **图片素材**：支持 JPG、PNG、BMP、TIFF（≤10MB），自动OCR提取文字。
- **素材管理**：列表展示（名称、来源、类型、大小、处理状态），支持分类、预览、删除、批量操作。
  - 视频素材预览时显示播放器与高亮字幕行。
  - 图片素材预览显示原图与OCR文字区域标注。
- **处理状态跟踪**：显示“未处理/转写中/OCR中/清洗中/已入库”，失败时展示错误原因（如音频质量低、无文字等），提供重试按钮。

#### 4.2.1 知识库分享模块

- **功能概述**：用户可将个人知识库中的 **全部或指定分类/标签** 的内容整理为一个公开只读的知识空间，生成唯一的分享链接。任何人通过该链接即可在未登录状态下访问被分享的知识，支持 **浏览知识条目、全文搜索、AI问答、查看知识图谱** 等只读操作，但不可编辑或触发进化。
- **分享配置**：
  - **分享范围**：可选择“分享全部知识”或“仅分享带有特定标签/分类的知识块”。
  - **有效期**：可设置链接有效天数（7天、30天、永久），过期后自动失效。
  - **访问密码**（可选）：可设置4-8位数字密码，访客需输入正确密码才能查看。
  - **分享名称与描述**：用户可自定义标题和简介，便于分享至社交平台。
- **分享管理**：
  - 在“个人中心 → 我的分享”页面，列表展示已创建的分享链接，包括名称、涵盖知识数量、创建时间、有效期、访问次数、状态（有效/已过期/已撤销）。
  - 支持 **复制链接**、**预览分享页**、**修改有效期/密码**、**撤销分享**。
  - 撤销后链接立即失效，访客访问时提示“该分享已关闭”。
- **访客访问体验**：
  - 打开分享链接进入简洁的知识库门户页，展示分享者昵称/头像、分享名称与描述。
  - **知识探索**：提供搜索框（基于 RAGFlow 多路召回），可对分享范围内的知识进行语义搜索。
  - **AI问答**：基于分享知识库内容，调用DeepSeek进行问答，回答仅引用被分享的知识块。
  - **知识图谱**：展示被分享知识点的力导向图，支持缩放、点击查看详情。
  - 所有操作均为只读，无法查看任何未分享的私有信息。
- **技术要点**：
  - 分享链接格式：`https://域名/share/{share_id}`，`share_id` 为 UUID。
  - 后端通过中间件识别分享链接，生成临时匿名会话，所有数据库查询强制附加 `owner_id` 过滤。
  - AI问答、图谱等接口均通过 `share_id` 校验权限。

### 4.3 MCP智能处理模块

集成无资质MCP工具，用户一键启动素材预处理流水线：

- **Fetch MCP** (`@modelcontextprotocol/server-fetch`)：抓取公开URL并提取正文。
- **MarkItDown MCP** (社区自建)：将Word、PDF、HTML转换为Markdown。
- **VideoSubtitle MCP** (自建)：基于Whisper模型离线提取视频音轨，生成带时间戳的字幕，并合并为连贯文本。
- **ImageOCR MCP** (自建)：基于PaddleOCR/Tesseract对图片预处理后提取文字，支持中英文混合。
- **自定义文本清洗MCP**：去乱码、统一换行、去冗余、格式标准化。
- **Filesystem MCP** (`@modelcontextprotocol/server-filesystem`)：安全读写用户上传目录。
- 所有处理任务通过 RabbitMQ 分发给 Celery Workers 异步执行，前端通过 WebSocket 接收实时进度。
- 处理结果写入MySQL素材表，标记为“已清洗”，随后自动提交至 RAGFlow 管道进行分块、索引。

### 4.4 AI知识服务模块（基于 RAGFlow + Milvus Lite + BGE-M3）

本模块核心检索与增强生成能力由 **RAGFlow** 引擎提供。RAGFlow 是一个开源的 RAG 系统，内置深度文档理解、灵活分块、多路召回与融合排序，能够大幅提升知识检索的覆盖率和准确率。

- **文档处理管道**：清洗后的文本素材通过 RAGFlow 的 Python SDK 上传至知识库。RAGFlow 自动执行：
  - **智能分块**：支持多种分块策略（如段落、语义、标记等），可根据文档结构动态选择，保证知识块的完整性和检索效率。
  - **向量化索引**：使用 BGE-M3 嵌入模型生成1024维向量，存入 **Milvus Lite** 集合（由 RAGFlow 管理，无需手动操作）。
  - **全文索引**：在 **Elasticsearch** 中建立倒排索引，用于关键词匹配与 BM25 检索。
  - **可选图谱索引**：RAGFlow 支持抽取实体和关系构建知识图谱索引，用于后续多路召回（可选，通过配置开启）。

- **多路召回与融合排序**：
  RAGFlow 原生支持同时从多个检索通路召回候选知识块，并通过学习型融合模型（或可配置的 RRF/线性加权）进行重排序。默认启用以下通路：
  1. **向量召回**：基于 Milvus 的近似最近邻搜索，返回语义相似 Top-K。
  2. **全文召回**：基于 Elasticsearch 的 BM25 或全文检索，返回关键词匹配 Top-K。
  3. **图谱召回**（可选）：基于知识图谱的实体链接，召回关联知识。
  融合后的最终结果按相关性降序输出，大幅优于单路或简单 RRF 合并。

- **智能问答**：RAGFlow 的检索结果与用户问题一起送入 DeepSeek-V4-Flash，生成带来源引用的答案。支持流式输出，前端可逐字展示。
- **知识总结**：利用 RAGFlow 的检索管道召回相关知识块，生成多层级摘要（一句话总结、要点列表、思维导图结构）。
- **内容纠错**：检测事实矛盾、过时信息，给出修改建议（基于特定知识块的上下文比对）。
- **分享场景兼容**：通过传入过滤条件（如标签或用户隔离），RAGFlow 可仅检索指定范围的知识块，保证分享问答的安全性。

### 4.5 deepagents 知识进化模块（核心引擎）

#### 4.5.1 deepagents 简介

**deepagents** 是 LangChain 生态中的一个开源 Python 库，提供一个“智能体工具包”（agent harness），旨在解决普通 AI 智能体在处理复杂、长期任务时的“浅薄”问题。它预集成了以下关键能力：

- **任务规划**：将大任务分解为可执行的小步骤。
- **子智能体（Sub-agent）**：可以创建专门的子智能体来并行处理特定子任务。
- **文件系统访问**：让智能体可以读写文件，用于管理长对话的上下文。
- **持久化记忆**：使智能体能够在多次交互中记住关键信息。

该库构建在 LangChain 和 LangGraph 之上，可通过 `create_deep_agent` 等函数快速创建功能强大的智能体。在本系统中，我们用它替代原生 LangGraph 线性工作流，构建由多个专业化子智能体协作完成的知识进化流程。

#### 4.5.2 进化智能体设计

利用 deepagents 的任务规划和子智能体机制，我们将进化任务分解给一组专门化的子智能体，由主智能体统一调度。

| 智能体角色       | 职责                                                         |
| ---------------- | ------------------------------------------------------------ |
| **主协调智能体** | 接收进化请求，进行任务规划，分配子任务，管理自动/手动模式分支，监控整体进度。 |
| **审计智能体**   | 调用 DeepSeek 审查知识块的准确性、时效性、一致性，标记问题点。 |
| **编辑智能体**   | 根据审计结果生成具体的修改建议（原文、建议文本、修改理由）。在手动模式下，可接收用户反馈进行二次修改。 |
| **拓展智能体**   | 挖掘关联概念，生成衍生知识点，建立知识图谱边。               |
| **题库智能体**   | 基于新增/变更知识自动生成闪卡、大富翁、配对三种题型。<br>**新增校验闭环**：生成题目后，自动提交至游戏沙箱进行可玩性验证，若沙箱检测到游戏逻辑错误（如死循环、无法通关、无正确答案等），则触发轮询纠错流程，直至题目通过测试。 |
| **日志智能体**   | 记录每一步决策、耗时、状态，并可写入文件系统（通过 deepagents 的文件系统访问能力）。 |

所有子智能体均基于 deepagents 框架创建，具备独立的系统提示词和工具集（如 RAGFlow 检索接口、MySQL 读写、DeepSeek 调用）。主智能体使用 deepagents 的任务规划能力自动编排这些子智能体的执行顺序，并根据模式决定是否暂停等待人工输入。

#### 4.5.3 进化模式与智能体协作

- **AI 自动模式**：用户触发后，主智能体规划并调度所有子智能体按最佳顺序执行（审计 → 编辑 → 拓展 → 题库 → 沙箱验证 → 更新入库），无需人工干预。整个过程通过流式 WebSocket 推送各智能体的“思考卡片”至前端观察窗。
- **手动确认模式**：主智能体执行到编辑智能体后暂停，将生成的建议通过 deepagents 的人机协同接口发送到前端“进化预览”页。用户可逐条审核（接受/拒绝/编辑/反馈重新生成）。用户的反馈会发送给编辑智能体进行二次修改（最多 1 次）。用户最终确认后，主智能体唤醒后续子智能体继续执行（拓展、题库、沙箱验证）并更新知识库。

#### 4.5.4 流式思考过程可视化

- 每个子智能体在执行过程中，其内部推理过程（类似于 DeepSeek 网页端的“思考”过程）会通过 WebSocket 实时推送到前端。
- 前端以可折叠的时间线卡片展示不同智能体的输出，用户可直观看到：“审计智能体正在检查第三条知识的一致性…”、“编辑智能体建议将‘XXX’修改为‘YYY’，理由是…”。
- deepagents 的文件系统访问能力可用于在服务器端缓存思考流日志，方便用户回溯。

#### 4.5.5 进化预览页面（手动模式专用）

- **入口**：进化中心 → 待审核任务列表 → 点击“开始审核”。
- **界面布局**：
  - 左侧：知识块差异对比面板，支持 **并排对比**（原文 vs 建议修改）或 **行内差异** 高亮。
  - 右侧：审核操作栏，每条建议卡片包含知识点标题、修改理由、“接受”“拒绝”“手动编辑”按钮、“提交反馈”输入框（可提交修改意见让 AI 重新生成）。
  - 底部固定栏：统计接受/拒绝/待处理数量，提供“一键接受全部”和“应用所有更改”确认按钮。
- **批量操作**：可多选建议后批量接受/拒绝。
- **审核记录**：所有决策和最终文本存入 `evolution_reviews` 表，可回溯。

**触发方式**：手动触发（进化中心点击“立即进化”，选择模式）或 Celery Beat 定时触发（使用用户设置的默认模式）。手动模式下的定时任务若 72 小时内未审核，任务自动取消并通知用户“进化建议已过期，请重新发起”。

### 4.6 游戏化学习模块

#### 游戏中心大厅

- 展示三种游戏入口卡，显示个人等级、经验值（EXP）、可用道具。  
- 每个游戏均设有 **难度选择器**：简单（基础概念，答错不惩罚）、中等（常规知识点，正常奖惩）、困难（综合题与推理题，错误大幅扣分）。用户可随时切换，系统记忆上次选择。

#### 游戏一：智能闪卡对战 V2.0

- **多题型**：翻转问答、填空、判断、单选。
- **关卡制**：按知识主题分章节，BOSS题为跨章节综合题。
- **间隔重复**：SM-2改进算法，根据答题表现安排复习，到期前卡片显示红色角标。
- **连击奖励**：连续正确获得额外EXP和金币。
- **难度影响**：简单模式下题目直接匹配关键词，困难模式会要求推理或对比。

#### 游戏二：知识大富翁 V2.0

- **动态棋盘**：根据知识分类数量生成6x6~8x8网格，每个区域对应不同主题。
- **角色技能**：学者（答对额外前进1格）、探险家（免疫一次陷阱）。
- **随机事件**：知识风暴（连答3题前进）、知识遗忘（后退并限时减速）等。
- **道具商店**：使用游戏中金币购买提示卡、保护盾。
- **BOSS格**：终点需连续答对3道困难题通关，通关后棋盘升级（新主题）。
- **难度选择**：直接影响事件概率和题目复杂度。

#### 游戏三：概念配对消消乐 V2.0

- **配对模式**：一对一概念-定义，或一对多（一个概念需匹配所有相关描述）。
- **干扰项**：AI生成相似但错误的概念，选中扣时扣分。
- **皮肤切换**：根据知识主题自动变化卡片背景。
- **疯狂模式**：限时30秒，卡片逐渐下落，需快速拖拽配对。
- **难度选择**：简单模式干扰项少、无下落加速；困难模式干扰项多且下落速度加快。

#### 4.6.1 游戏题目自动校验与沙箱轮询机制

**背景**：动态生成的游戏题目可能存在逻辑缺陷（例如配对消消乐中无正确匹配项、大富翁棋盘问题导致无法到达终点），直接发布会破坏游戏体验。本机制通过沙箱模拟游戏运行，结合智能体自动修复，确保题目质量。

**沙箱环境**：
- 为每种游戏实现一个轻量级模拟器，运行于隔离的 Docker 沙箱或受限 Python 子进程。
- 模拟器接收题目数据（JSON格式），在无用户交互的环境下自动运行预设次数的随机决策，记录异常、失败状态和覆盖率。

**轮询与纠错流程**：

```
题库智能体生成题目
 → 提交题目至 RabbitMQ 队列 "game.sandbox"
 → Celery Worker 启动沙箱模拟器，执行游戏循环
 → 轮询机制每 3 秒检查沙箱状态（通过 Redis 临时状态键或回调）
    ├─ 沙箱返回成功：题目通过，标记为“已就绪”，发布至游戏库
    └─ 沙箱返回失败：推送错误信息（如“配对题无正确答案”）至智能体
       → 题库智能体接收错误日志，分析并修正题目（例如重新生成干扰项）
       → 修正后重新提交沙箱，最多重试 3 次
       → 若 3 次仍失败，任务升级至编辑智能体辅助修复，或标记人工审核
```

**轮询状态可视化**：
- 在“进化观察窗”或游戏中心后台显示校验进度：“正在验证大富翁棋盘关卡3/5…”。
- 若自动修复成功，记录日志；若最终失败，通知管理员/用户手动介入。

**沙箱检测要点**：

| 游戏           | 校验规则                                                     |
| -------------- | ------------------------------------------------------------ |
| 智能闪卡       | 答案字段非空、干扰项不重复、关卡内题目无知识冲突、BOSS题综合度达标 |
| 知识大富翁     | 棋盘所有格子可达、BOSS格题目数量≥3、事件概率合法、道具价格合理 |
| 概念配对消消乐 | 所有卡片存在唯一正确配对、干扰项数量符合难度设定、疯狂模式时间内可完成（模拟最优路径） |

**性能与资源**：
- 单个题目校验耗时 < 5 秒，沙箱实例通过 Celery 并发限制（默认同时运行 3 个）。
- 沙箱结果缓存于 Redis，避免重复校验相同题目组合。

#### 成就与成长体系

- **成就徽章**：30+种（如“七天连学”“百题无误”“全图鉴收集”），完成后在个人中心展示。
- **等级与道具**：答题、通关获得经验，升级解锁新角色皮肤、稀有道具。

### 4.7 数据可视化模块

- **知识数量统计**：总数、今日新增、分类分布饼图。
- **学习趋势**：每日/每周答题量、正确率变化（折线图）。
- **掌握度分布**：闪卡掌握状态环形图。
- **易错知识点 Top5**：表格+进度条。
- **动态交互知识图谱**：  
  以力导向图展示用户知识库中知识点之间的关联关系。节点代表知识点（可分级显示核心概念与细节），连线粗细代表关联强度。交互：拖拽节点、缩放、点击展开详情（摘要、相关文档、学习进度）。支持按主题筛选、高亮路径。图谱数据由deepagents拓展智能体和用户学习行为动态更新。技术选型：ECharts graph 或 vis.js network。  
  **分享场景下仅渲染公开知识点。**

### 4.8 用户设置模块

- **自动进化开关**：独立控制是否开启凌晨自动知识进化。
- **自定义触发时间**：设定小时:分钟（系统在±15分钟内随机执行以分散压力）。
- **进化默认模式**：下拉选择“AI自动更新”或“手动确认更新”，默认“手动确认更新”。
- **登录绑定管理**：查看已绑定的微信、手机号，可解除绑定。
- **游戏默认难度**：设置各游戏的首选难度。
- **分享管理入口**：链接至个人中心-我的分享。

### 4.9 系统日志模块

- 记录用户操作：登录、素材上传、MCP调用、工作流执行（含模式选择）、审核决策、游戏记录、设置变更、分享创建/撤销/访问。
- 支持按时间、模块筛选，分页查看，导出CSV。

### 4.10 业务流程

#### 4.10.1 知识入库与处理流程

```
素材录入（多源导入页，含视频/图片入口）
 → 提交后，系统创建素材记录，发布异步任务至 RabbitMQ
 → Celery Worker 调用 MCP 工具链（清洗/转写/OCR/转换）
 → 前端 WebSocket 实时更新进度，完成后状态变更为“已清洗”
 → 自动触发 RAGFlow 管道：上传文本 → 智能分块 → BGE-M3 向量化 → 写入 Milvus Lite + ES 索引
 → 完成后跳转“AI知识服务”，提示“知识已就绪”
```

**跳转说明**：  

- 录入页提交后显示进度条，完成可选择“查看素材列表”跳转素材管理。  
- 素材管理页每条已入库记录提供“立即问答”按钮→跳转智能问答。  
- “加入进化队列”按钮→跳转进化页面并预选该素材。

#### 4.10.2 知识进化工作流（模式选择与审核）

```
进化中心 → 点击“立即进化” 
 → 弹出模式选择框（默认值来自设置）
   - 若选“AI自动更新”：
      deepagents主智能体调度审计、编辑、拓展、题库、沙箱验证等子智能体自动执行
      过程可通过观察窗查看各智能体的流式思考
      完成后通知用户，可查看变更日志
   - 若选“手动确认更新”：
      deepagents执行审计与编辑智能体后暂停，生成待审核任务
      用户进入“进化预览”页逐条审核/编辑/反馈重生成
      确认后点击“应用所有更改”，主智能体唤醒拓展、题库、沙箱验证等智能体继续执行
      完成后弹出进化报告
```

**定时任务**：直接使用默认模式执行，逻辑同上（手动模式下产生待审核任务并提醒）。

**跳转关系**：

- 进化页面 → 待审核任务列表 → 点击审核进入预览页。
- 预览页可随时返回，状态保留。
- 完成进化后，通知可引导至游戏中心。

#### 4.10.3 游戏化学习流程

```
游戏中心大厅 → 选择游戏 → 难度选择 → 开始游戏
 → 答题中实时显示连击/经验/金币
 → 结算面板显示结果、成就进度
 → 可选择“再来一局”或“返回大厅”
 → 答错题目可点击“查看知识点”→跳转知识图谱高亮
```

#### 4.10.4 综合导航与跳转

- 全局导航栏：首页仪表盘、知识库、AI工作室、进化中心、游戏中心、图谱分析、个人设置。
- 首页仪表盘可显示进化状态（自动完成/待审核数量）。
- 所有数据项均可点击跳转详情；通知（进化完成、成就）可导航至相关页面；移动端底部导航栏简化，逻辑一致。

#### 4.10.5 异常与空状态跳转

- 无素材→首页引导“上传第一条知识”，点击进入录入页。
- 无进化任务→显示“开始首次进化”，引导选择素材。
- 无游戏记录→游戏大厅新手指引，可快速开始默认难度闪卡。
- 知识图谱为空→提示导入知识。
- 手动模式超时未审核：任务自动取消，通知“进化建议已过期，请重新发起”。
- 访客访问失效分享链接提示“该分享已过期或不存在”。

---

## 5. 非功能需求

### 5.1 性能需求

- 多路召回总耗时 < 500ms（RAGFlow 内部优化，含向量+全文召回与融合）。
- AI问答生成时间 < 5秒（分享场景相同）。
- 知识图谱渲染（500节点内）< 3秒。
- 视频转写任务（≤30分钟视频）在无负载时最迟15分钟内完成或超时标记失败。
- 审核页差异对比加载 < 500ms；反馈重生成 < 5s。
- 分享页面首屏加载 < 1.5秒。
- 进化任务（100个知识块）自动模式耗时 < 3分钟，手动模式（不含用户操作时间）< 2分钟。
- 题目沙箱校验单个任务 < 5秒，并发数 ≤ 3。

### 5.2 安全性

- 密码加盐哈希存储，JWT令牌有效期24小时，支持刷新。
- 微信登录遵循OAuth2.0标准，仅获取openid和昵称，不触碰敏感权限。
- 手机验证码5分钟内最多发送3次，防范滥用。
- 文件上传白名单校验，避免恶意文件。
- 分享链接使用不可猜测的UUID，可叠加密码保护；分享令牌在服务端验证，不泄露用户ID。
- 匿名访问接口严格限制返回数据范围，避免越权。
- 所有用户操作日志记录，分享访问日志可审计。

### 5.3 可用性

- 界面遵循 Element Plus 设计规范，操作路径简短。
- 首次进入游戏模块显示引导蒙层。
- 错误状态提供明确提示和恢复建议。
- 差异对比清晰（推荐使用 `diff-match-patch` 等库），审核页面引导清晰。
- 模式选择界面简洁，首次使用给出说明。
- 观察窗显示智能体名称与角色说明，帮助用户理解过程。
- 沙箱校验状态实时展示，失败后提供重试按钮。

### 5.4 可扩展性

- deepagents 允许动态添加新子智能体（例如“跨语言翻译智能体”、“学术格式检查智能体”），只需配置注册，无需改动核心流程。
- MCP工具可通过修改配置文件动态加载。
- 游戏题型、成就系统支持字典化管理。
- 向量数据增长到百万级时，可平滑迁移至Milvus Standalone，RAGFlow 配置兼容。
- 进化模式可扩展“半自动”（如仅接受高置信度修改）。
- RAGFlow 支持自定义召回通路和融合算法，可灵活扩展检索能力。

---

## 6. 技术架构与选型

### 6.1 整体架构

```
前端 (Vue3) 
  ↕ HTTP/REST + WebSocket (进度推送)
后端 (FastAPI)
  ↕
MySQL (业务/全文)  +  Redis (缓存/验证码/锁)  +  RabbitMQ (异步任务/事件总线)
  ↕
RAGFlow 引擎 (文档处理/多路召回/融合排序) 
   ├── Milvus Lite (向量存储)
   └── Elasticsearch (全文索引/文档存储)
AI服务层：DeepSeek-V4-Flash API + Celery Workers + deepagents
  ↕
MCP工具集 (本地STDIO) + 游戏沙箱模拟器 (Docker/子进程)
```

### 6.2 核心组件表

| 组件              | 技术选型                                                     | 说明                                                         |
| ----------------- | ------------------------------------------------------------ | ------------------------------------------------------------ |
| 前端框架          | Vue3 + Vite + Element Plus + ECharts                         | 交互性强，分享页采用独立轻量布局                             |
| 后端框架          | FastAPI (Python 3.11+)                                       | 异步高性能，依赖注入鉴权                                     |
| 关系数据库        | MySQL 8.0                                                    | 结构化数据，支持FULLTEXT                                     |
| 缓存/会话         | Redis 7                                                      | 验证码、JWT黑名单、排行榜缓存、分布式锁、沙箱临时状态        |
| 向量数据库        | **Milvus Lite** (pymilvus)                                   | 本地嵌入式向量存储，由 RAGFlow 管理                          |
| 全文检索引擎      | **Elasticsearch 8.x**                                        | **升级为必需组件**，作为 RAGFlow 的文档存储与全文索引后端    |
| 消息队列/任务调度 | **RabbitMQ 3.12+** + Celery                                  | 异步任务分发、事件通信、工作流解耦，Celery Beat 管理定时任务 |
| 大语言模型        | DeepSeek-V4-Flash (API)                                      | 免费额度，生成能力强，支持流式输出                           |
| 嵌入模型          | BGE-M3 (本地)                                                | 多语言，1024维                                               |
| **检索增强引擎**  | **RAGFlow**                                                  | **新增核心组件**，提供多路召回、融合排序与文档处理管道，替代自建混合检索 |
| 智能体框架        | **deepagents** (LangChain 生态)                              | 任务规划、子智能体、文件系统访问、持久化记忆                 |
| MCP工具           | Fetch, Filesystem, MarkItDown, VideoSubtitle, ImageOCR, 自建TextCleaner | 零资质覆盖多媒体处理                                         |
| 实时通信          | WebSocket (FastAPI) + Redis Pub/Sub                          | 流式思考推送、进度通知                                       |
| 游戏沙箱          | Python 子进程 / Docker 容器                                  | 隔离运行游戏模拟，校验题目可玩性                             |
| 部署              | Uvicorn + Nginx + Docker                                     | 支持本地运行，RAGFlow 和 ES 推荐使用 Docker 部署             |

### 6.3 关键配置与代码示例

#### 6.3.1 RAGFlow 集成配置 (`.env` 或 `config.py`)

```python
import os
from ragflow import RAGFlow

RAGFLOW_API_URL = os.getenv("RAGFLOW_API_URL", "http://localhost:9380")
RAGFLOW_API_KEY = os.getenv("RAGFLOW_API_KEY", "your-ragflow-api-key")

# 初始化 RAGFlow 客户端
rag_client = RAGFlow(api_url=RAGFLOW_API_URL, api_key=RAGFLOW_API_KEY)

# 配置知识库（对应每个用户一个知识库，或通过标签隔离）
def get_or_create_dataset(user_id: str):
    dataset_name = f"user_kb_{user_id}"
    datasets = rag_client.list_datasets()
    for ds in datasets:
        if ds.name == dataset_name:
            return ds
    return rag_client.create_dataset(name=dataset_name, embedding_model="BGE-M3", chunk_method="semantic")
```

#### 6.3.2 知识入库与多路检索示例 (`services/knowledge_service.py`)

```python
async def index_document(user_id: str, text: str, doc_meta: dict):
    dataset = get_or_create_dataset(user_id)
    # RAGFlow 自动分块、向量化并写入 ES 和 Milvus
    doc = dataset.upload_document(content=text, meta=doc_meta)
    return doc.id

async def retrieval_query(user_id: str, query: str, top_k=10):
    dataset = get_or_create_dataset(user_id)
    # 调用 RAGFlow 的多路召回与融合接口
    retrieval_result = dataset.retrieve(
        query=query,
        top_k=top_k,
        rerank_model="BGE-Reranker",  # 融合重排序
        enable_vector=True,
        enable_fulltext=True,
        enable_graph=False  # 可开启图谱召回
    )
    # 返回排序后的文档块列表
    return retrieval_result

async def rag_qa(user_id: str, question: str):
    chunks = await retrieval_query(user_id, question)
    context = "\n".join([chunk.text for chunk in chunks])
    # 调用 DeepSeek 生成回答，附带引用
    ...
```

#### 6.3.3 RabbitMQ 与 Celery 集成 (`celery_app.py`)

```python
from celery import Celery
from celery.schedules import crontab
import os

RABBITMQ_URL = os.getenv("RABBITMQ_URL", "amqp://guest:guest@localhost:5672//")

celery_app = Celery(
    "zhizhi",
    broker=RABBITMQ_URL,
    backend="rpc://",
    include=["tasks.evolution", "tasks.media_processing", "tasks.game_events", "tasks.game_sandbox"]
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="Asia/Shanghai",
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    beat_schedule={
        "auto-evolution-daily": {
            "task": "tasks.evolution.trigger_auto_evolution",
            "schedule": crontab(hour=3, minute=0),
        },
    },
)
```

#### 6.3.4 流式思考 WebSocket 端点示例 (`routers/ws.py`)

```python
from fastapi import WebSocket, WebSocketDisconnect
import redis.asyncio as redis

redis_client = redis.from_url("redis://localhost")

@router.websocket("/ws/evolution/{task_id}")
async def evolution_stream(ws: WebSocket, task_id: str):
    await ws.accept()
    pubsub = redis_client.pubsub()
    await pubsub.subscribe(f"evolution_thought:{task_id}")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await ws.send_text(message["data"])
    except WebSocketDisconnect:
        await pubsub.unsubscribe(f"evolution_thought:{task_id}")
```

#### 6.3.5 分享鉴权中间件 (`auth/share.py`)

```python
from fastapi import Request, HTTPException

async def validate_share(request: Request):
    share_id = request.path_params.get("share_id")
    if not share_id:
        return
    share = await db.get_share(share_id)
    if not share or (share.expires_at and share.expires_at < datetime.utcnow()):
        raise HTTPException(status_code=404, detail="分享不存在或已过期")
    if share.password:
        token = request.cookies.get(f"share_{share_id}_token")
        if not token or token != share.token:
            raise HTTPException(status_code=401, detail="需要密码访问")
    request.state.share_owner_id = share.user_id
    request.state.share_filter = share.filter_tags
```

#### 6.3.6 deepagents 集成示例 (`agents/evolution.py`)

```python
from deepagents import create_deep_agent
from langchain_core.tools import tool
from services.knowledge_service import retrieval_query, apply_changes

@tool
def search_knowledge(query: str) -> str:
    """搜索用户知识库（通过 RAGFlow 多路召回）"""
    return retrieval_query(user_id=..., query=query)

agent = create_deep_agent(
    model="deepseek-chat",
    tools=[search_knowledge, apply_changes],
    system_prompt="你是知识进化主管，负责协调审计、编辑、拓展等子智能体。",
    subagents=[
        {
            "name": "auditor",
            "description": "审查知识准确性、时效性",
            "system_prompt": "你是一个知识审计专家...",
            "tools": [search_knowledge],
        },
        # ... 其他子智能体
    ],
    enable_filesystem=True,
)
```

#### 6.3.7 游戏沙箱任务示例 (`tasks/game_sandbox.py`)

```python
@celery_app.task(bind=True, max_retries=3)
def run_game_sandbox(self, question_data: dict, game_type: str):
    try:
        if game_type == "flashcard":
            result = simulate_flashcard(question_data)
        elif game_type == "monopoly":
            result = simulate_monopoly(question_data)
        elif game_type == "match":
            result = simulate_match(question_data)
        if not result["passed"]:
            raise ValueError(result["error"])
        mark_questions_ready(question_data["id"])
    except Exception as e:
        publish_retry_event(question_data["id"], str(e))
        raise self.retry(exc=e)
```

### 6.4 部署依赖（最小化）

- Python 3.11+
- Node.js 18+
- MySQL 8.0+（需支持FULLTEXT）
- Redis 7.0+
- RabbitMQ 3.12+（管理插件可选，端口 5672/15672）
- **Elasticsearch 8.x**（RAGFlow 必需，端口 9200）
- **RAGFlow**（通过 Docker 部署 `infiniflow/ragflow`，端口 9380）
- Milvus Lite 纯 Python 库（作为 RAGFlow 的向量后端，由 RAGFlow 自动管理）
- deepagents Python 包（`pip install deepagents`）
- Docker（用于运行 RAGFlow、ES、RabbitMQ 等服务）

启动脚本示例：

```bash
# 启动基础设施
docker run -d --name rabbitmq -p 5672:5672 -p 15672:15672 rabbitmq:3.12-management
docker run -d --name redis -p 6379:6379 redis:7
docker run -d --name elasticsearch -p 9200:9200 -e "discovery.type=single-node" elasticsearch:8.11.0
# 启动 RAGFlow（需按照官方文档配置，暴露 API 端口）
docker run -d --name ragflow -p 9380:9380 -v /path/to/ragflow/data:/ragflow/data infiniflow/ragflow:latest
# FastAPI 应用启动: uvicorn main:app --reload
```

---

## 7. 验收标准

### 7.1 功能验收

- [ ] 支持账号密码、微信扫码、手机验证码三种登录方式，且账号互通。
- [ ] 素材导入后自动完成MCP清洗（含视频字幕、图片OCR），并成功通过 RAGFlow 管道入库，可被检索。
- [ ] 用户可创建分享链接，设置范围、有效期与密码，未登录访客可只读访问，分享者可撤销。
- [ ] AI问答能基于 RAGFlow 多路召回准确生成回答，附带来源；分享问答范围受限。
- [ ] 知识进化提供自动/手动两种模式，手动触发时可选，设置中可指定默认模式。
- [ ] deepagents 正确调度主智能体与子智能体，自动/手动模式均可完成知识进化。
- [ ] 流式思考中能分辨不同智能体的输出。
- [ ] 自动模式下，知识库直接更新，无审核步骤，日志完整可回溯。
- [ ] 手动模式下，生成待审核建议，支持接受/拒绝/编辑/提交反馈重新生成，确认后更新。
- [ ] 手动模式下，审核超时自动取消。
- [ ] 题库智能体生成的题目必须通过沙箱校验，未通过题目不会出现在游戏中。
- [ ] 沙箱检测到错误时自动重试修正（最多3次），失败后转人工或记录错误。
- [ ] 三种游戏均可流畅运行，难度选择功能有效，数据持久化。
- [ ] 游戏中道具、成就、等级系统运作正常。
- [ ] 知识图谱节点与关系正确，可交互，随知识库更新而动态变化。
- [ ] 自动进化开关实时生效，定时任务准时执行，使用默认模式。
- [ ] 可视化报表数据准确，图谱可导出图片。

### 7.2 性能验收

- [ ] 同时5个用户进行知识检索，RAGFlow 多路召回响应 < 500ms，整体问答 < 5秒。
- [ ] 知识进化任务（100个知识块）自动模式 < 3分钟，手动模式 < 2分钟（不含用户操作）。
- [ ] 游戏在移动端浏览器无卡顿。
- [ ] 视频/图片处理符合时限，分享页面首屏加载 < 1.5秒。
- [ ] 审核页差异对比加载迅速，流式展示无卡顿。
- [ ] 题目沙箱校验单个 < 5秒，并发不阻塞主系统。

### 7.3 部署验收

- [ ] 提供一键启动脚本（Docker Compose 包含 RAGFlow、ES、RabbitMQ、Redis 等）。
- [ ] 完整部署文档，支持 Windows/Linux/macOS 复现。

---

## 8. 附录

### 8.1 第三方服务申请指南

- **DeepSeek API Key**：注册 [DeepSeek开放平台](https://platform.deepseek.com/)，个人可免费获取100万token体验额度。
- **微信测试公众号**：登录[微信公众平台测试号](https://mp.weixin.qq.com/debug/cgi-bin/sandbox?t=sandbox/login)，获取appID与appsecret，配置回调域名。
- **阿里云号码认证**：开通[号码认证服务](https://www.aliyun.com/product/number-auth)，创建应用获取AccessKey，个人实名认证后可免费使用一定量测试额度。
- **BGE-M3模型**：首次运行时会自动从HuggingFace下载，或手动放置于 `~/.cache/huggingface/`。
- **RAGFlow**：访问 [RAGFlow GitHub](https://github.com/infiniflow/ragflow) 获取部署指南，使用 Docker 镜像启动。

### 8.2 数据库核心表清单（MySQL）

- `users`（增加 `wechat_openid`, `phone` 字段）
- `user_sessions`
- `materials`（增加 `material_type`, `source_url`, `duration` 等）
- `doc_chunks`（可保留用于记录 RAGFlow 生成的 chunk 元数据，实际文本由 RAGFlow 管理）
- `knowledge_shares`  (新增)：`share_id`, `user_id`, `title`, `description`, `filter_tags`, `password_hash`, `expires_at`, `created_at`, `is_active`, `visit_count`
- `share_visits`  (新增)：`visit_id`, `share_id`, `ip`, `user_agent`, `accessed_at`
- `game_questions`
- `user_game_progress`
- `player_profiles`
- `achievements`
- `inventory`
- `user_auto_update_setting`（增加 `default_evolution_mode` 字段）
- `system_logs`
- `knowledge_graph_edges`
- `evolution_tasks` (新增)：`task_id`, `user_id`, `mode` (auto/manual), `status`, `created_at`, `finished_at`
- `evolution_reviews` (新增)：`review_id`, `task_id`, `user_id`, `chunk_id`, `original_text`, `suggested_text`, `reason`, `status` (pending/accepted/rejected/edited), `feedback_text`, `final_text`, `created_at`, `reviewed_at`
- `evolution_agent_logs` (新增)：记录每个智能体的执行步骤与思考日志
- `game_sandbox_tasks` (新增)：`task_id`, `question_set_id`, `game_type`, `status` (pending/running/passed/failed/manual_review), `retry_count`, `error_log`, `created_at`, `completed_at`
- `sandbox_simulation_logs` (新增)：记录每次沙箱运行的详细步骤，用于回溯

### 8.3 RAGFlow 管理的数据存储

RAGFlow 内部使用 Elasticsearch 存储文档和全文索引，使用 Milvus Lite（或配置的向量数据库）存储向量。所有 chunk、文档内容均由 RAGFlow API 管理，无需在 MySQL 中冗余存储。

### 8.4 RabbitMQ 交换机与队列设计

- **交换机**：`knowledge.topic` (topic类型)
- **队列**：`media.processing`（视频/图片处理）、`evolution.workflow`（进化任务链）、`game.sandbox`（游戏题目校验）、`game.events`（游戏事件）、`notifications`（通知推送）、`share.analytics`（分享访问统计）
- 绑定路由键：`media.*`、`evolution.*`、`game.sandbox.*` 等，便于解耦。

### 8.5 deepagents 简要说明

**deepagents** 是 LangChain 生态下的一个开源库，提供“智能体工具包”（agent harness），内置任务规划、子智能体、文件系统访问、持久化记忆等能力。它构建在 LangChain 和 LangGraph 之上，通过 `create_deep_agent` 函数即可快速创建能处理复杂长期任务的智能体。在本项目中，deepagents 被用于知识进化流程，将原先的线性 LangGraph 工作流升级为灵活的多智能体协作网络，并支持人机协同。

### 8.6 未来迭代方向

- 多用户协作知识库，实时同步编辑。
- 移动端适配（小程序）。
- 知识音频播客生成。
- 接入更多MCP工具（如学术论文抓取、代码解释器）。
- 利用 deepagents 的子智能体并行能力，同时校验多个知识块。
- 接入更多子智能体，如“翻译智能体”自动生成多语言版本知识块。
- 进化模式扩展“半自动”选项，仅自动接受高置信度修改。
- 分享页支持评论、点赞互动。
- RAGFlow 图谱召回全面启用，增强关联知识发现。
- 游戏沙箱支持更多自定义游戏类型，题库智能体自进化修复策略优化。
