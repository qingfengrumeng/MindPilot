/**
 * MindPilot 前端演示数据。
 *
 * 这里的数据用于在后端（FastAPI）就绪前驱动完整的前端交互，字段命名尽量与
 * 设计文档第 10.2 节的数据实体保持一致：
 * domains / documents / chunks / wiki_pages / wiki_links / page_sources /
 * sessions / tasks / grants / memory_items / artifacts / traces / usage。
 *
 * 接入后端时：把 VITE_USE_MOCK 设为 false，并让 src/api/index.js 中的适配函数
 * 改为调用真实接口；页面不直接依赖本文件，只依赖适配层的返回结构。
 */

export const domains = [
  {
    id: 'personal_learning',
    label: '个人学习',
    description: '公开论文、技术文章与个人学习笔记',
    egress: 'cloud_allowed',
    egressLabel: '允许云端处理',
    color: 'indigo',
    documents: 6,
    wikiPages: 5,
    memoryItems: 4
  },
  {
    id: 'work_project_a',
    label: '工作项目 A',
    description: '项目内部资料与设计草稿',
    egress: 'cloud_allowed',
    egressLabel: '允许云端处理',
    color: 'cyan',
    documents: 3,
    wikiPages: 3,
    memoryItems: 2
  },
  {
    id: 'reading_notes',
    label: '阅读笔记',
    description: '论文精读记录与摘录',
    egress: 'cloud_allowed',
    egressLabel: '允许云端处理',
    color: 'violet',
    documents: 1,
    wikiPages: 1,
    memoryItems: 1
  },
  {
    id: 'restricted',
    label: '受限待分类',
    description: '来源未知或标记为 local_only 的资料',
    egress: 'local_only',
    egressLabel: '仅本地处理',
    color: 'amber',
    documents: 1,
    wikiPages: 0,
    memoryItems: 0
  }
]

export const documents = [
  {
    id: 'doc-lc-survey',
    title: 'Efficient Long-Context Transformers: A Survey',
    type: 'paper',
    typeLabel: '论文',
    domain: 'personal_learning',
    source: 'https://arxiv.org/abs/2402.xxxxx',
    importedAt: '2026-09-14 21:12',
    pages: 32,
    size: '4.2 MB',
    chunks: 186,
    contentHash: 'sha256:9f3ac1…7b2e',
    version: 'v2',
    author: 'L. Chen, M. Rossi',
    year: 2024,
    tags: ['长上下文', '注意力机制', '综述'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'done' },
    summary: '系统梳理了稀疏注意力、线性注意力、状态空间模型与检索增强四类长上下文方案，并给出吞吐、显存与长程依赖保持度的对比。'
  },
  {
    id: 'doc-rope-extrapolation',
    title: 'RoPE 位置编码的扩展与外推',
    type: 'paper',
    typeLabel: '论文',
    domain: 'personal_learning',
    source: 'https://arxiv.org/abs/2306.xxxxx',
    importedAt: '2026-09-14 21:20',
    pages: 18,
    size: '2.6 MB',
    chunks: 104,
    contentHash: 'sha256:41c8de…03af',
    version: 'v1',
    author: 'J. Wang',
    year: 2023,
    tags: ['位置编码', 'RoPE', '外推'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'done' },
    summary: '讨论 NTK-aware 与 YaRN 两类频率缩放策略在训练窗口之外的外推表现，并给出困惑度随外推倍数的变化曲线。'
  },
  {
    id: 'doc-attention',
    title: 'Attention Is All You Need',
    type: 'paper',
    typeLabel: '论文',
    domain: 'personal_learning',
    source: 'https://arxiv.org/abs/1706.03762',
    importedAt: '2026-09-10 09:41',
    pages: 15,
    size: '2.1 MB',
    chunks: 92,
    contentHash: 'sha256:7d0b52…c118',
    version: 'v1',
    author: 'A. Vaswani et al.',
    year: 2017,
    tags: ['注意力机制', 'Transformer'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'done' },
    summary: '提出完全基于注意力的 Transformer 结构，是长上下文研究的共同基线。'
  },
  {
    id: 'doc-rag-original',
    title: 'Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks',
    type: 'paper',
    typeLabel: '论文',
    domain: 'reading_notes',
    source: 'https://arxiv.org/abs/2005.11401',
    importedAt: '2026-09-08 20:05',
    pages: 19,
    size: '2.9 MB',
    chunks: 118,
    contentHash: 'sha256:2a77f0…9e4d',
    version: 'v1',
    author: 'P. Lewis et al.',
    year: 2020,
    tags: ['RAG', '检索增强'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'done' },
    summary: '把参数化记忆与非参数化检索结合，是本地知识库问答的主要参考架构。'
  },
  {
    id: 'doc-chroma-notes',
    title: 'Chroma 向量检索实践笔记',
    type: 'note',
    typeLabel: '笔记',
    domain: 'personal_learning',
    source: '本地笔记',
    importedAt: '2026-09-15 22:33',
    pages: 6,
    size: '38 KB',
    chunks: 24,
    contentHash: 'sha256:bb19c4…5a02',
    version: 'v3',
    author: '本人',
    year: 2026,
    tags: ['ChromaDB', '向量检索'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'pending' },
    summary: '记录本地持久化客户端的目录结构、metadata 过滤写法与显式传入 query_embeddings 的做法。'
  },
  {
    id: 'doc-langgraph-interrupt',
    title: 'LangGraph 中断与恢复机制整理',
    type: 'note',
    typeLabel: '笔记',
    domain: 'work_project_a',
    source: '本地笔记',
    importedAt: '2026-09-12 15:26',
    pages: 9,
    size: '52 KB',
    chunks: 31,
    contentHash: 'sha256:c0d7a8…31bf',
    version: 'v2',
    author: '本人',
    year: 2026,
    tags: ['LangGraph', '任务编排'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'done' },
    summary: '整理 interrupt 恢复时节点可能重新执行的语义，以及副作用幂等保护的落地方式。'
  },
  {
    id: 'doc-mcp-boundary',
    title: 'MCP 工具标注与执行边界',
    type: 'article',
    typeLabel: '文章',
    domain: 'work_project_a',
    source: 'https://blog.modelcontextprotocol.io/posts/2026-03-16-tool-annotations/',
    importedAt: '2026-09-11 11:08',
    pages: 7,
    size: '44 KB',
    chunks: 26,
    contentHash: 'sha256:6e2f15…d7c9',
    version: 'v1',
    author: 'MCP Blog',
    year: 2026,
    tags: ['MCP', '权限'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'done' },
    summary: '说明工具元数据与标注只用于描述能力，不能替代执行层的授权检查。'
  },
  {
    id: 'doc-domain-isolation',
    title: '知识域隔离设计草稿',
    type: 'note',
    typeLabel: '笔记',
    domain: 'work_project_a',
    source: 'D:\\Research\\design\\domain-isolation.md',
    importedAt: '2026-09-13 10:17',
    pages: 11,
    size: '76 KB',
    chunks: 42,
    contentHash: 'sha256:12ab90…44e1',
    version: 'v4',
    author: '本人',
    year: 2026,
    tags: ['知识域', '权限'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'done', keyword: 'done', wiki: 'stale' },
    summary: '定义域过滤在向量、关键词、Wiki、按 ID 读取与缓存各条路径上的一致规则。'
  },
  {
    id: 'doc-local-only',
    title: '内部环境拓扑与凭证说明',
    type: 'note',
    typeLabel: '笔记',
    domain: 'restricted',
    source: '本地文件',
    importedAt: '2026-09-16 19:44',
    pages: 4,
    size: '29 KB',
    chunks: 15,
    contentHash: 'sha256:88fe03…2c70',
    version: 'v1',
    author: '本人',
    year: 2026,
    tags: ['受限', 'local_only'],
    quality: 'ok',
    qualityLabel: '解析正常',
    index: { vector: 'blocked', keyword: 'done', wiki: 'blocked' },
    summary: '标记为 local_only 的资料：仅支持本地保存、浏览与关键词检索，不进入任何云端路径。'
  },
  {
    id: 'doc-zotero-export',
    title: 'Zotero 导出文献元数据',
    type: 'article',
    typeLabel: '文献元数据',
    domain: 'personal_learning',
    source: 'zotero://export/collection/long-context',
    importedAt: '2026-09-16 20:31',
    pages: 2,
    size: '18 KB',
    chunks: 8,
    contentHash: 'sha256:3cd4e7…9011',
    version: 'v1',
    author: 'Zotero',
    year: 2026,
    tags: ['文献库', '元数据'],
    quality: 'partial',
    qualityLabel: '部分字段缺失',
    index: { vector: 'done', keyword: 'done', wiki: 'pending' },
    summary: '14 条文献记录，其中 3 条缺少 DOI 字段，需要人工补全后重新索引。'
  }
]

/** 支撑引用回溯的原始片段。 */
export const chunks = [
  {
    id: 'chunk-lc-0412',
    documentId: 'doc-lc-survey',
    domain: 'personal_learning',
    page: 12,
    section: '4.2 稀疏注意力',
    text: '块稀疏注意力将序列切分为固定大小的块，仅在块之间保留 Top-k 连接，使注意力复杂度由 O(n²) 降至 O(n·k)。代价是跨块的长程依赖需要经由多层间接传递，在需要精确检索远端信息的任务上召回率明显下降。'
  },
  {
    id: 'chunk-lc-0418',
    documentId: 'doc-lc-survey',
    domain: 'personal_learning',
    page: 18,
    section: '6.1 方案对比',
    text: '在线性注意力与状态空间模型的对比实验中，两者在中短上下文下吞吐接近，但当序列超过 128K 后，状态空间模型的固定状态成为瓶颈，长程检索类任务的准确率下降幅度大于线性注意力。'
  },
  {
    id: 'chunk-rope-0033',
    documentId: 'doc-rope-extrapolation',
    domain: 'personal_learning',
    page: 6,
    section: '3.3 频率缩放',
    text: 'NTK-aware 缩放通过改变基频让高频分量保持原有分辨率，低频分量被压缩，从而在不重新训练的情况下把有效窗口扩展到训练长度的 2 至 4 倍；超出该范围后困惑度快速上升。'
  },
  {
    id: 'chunk-rope-0051',
    documentId: 'doc-rope-extrapolation',
    domain: 'personal_learning',
    page: 11,
    section: '5.2 YaRN',
    text: 'YaRN 在频率缩放之外引入注意力温度缩放，缓解外推时注意力分布过于尖锐的问题，在 4 至 8 倍外推区间内比 NTK-aware 更稳定。'
  },
  {
    id: 'chunk-rag-0007',
    documentId: 'doc-rag-original',
    domain: 'reading_notes',
    page: 3,
    section: '2 方法',
    text: 'RAG 把预训练的 seq2seq 模型与非参数化的稠密向量索引组合，查询时检索 Top-k 文档作为生成条件，使知识可更新而不必重新训练全部参数。'
  },
  {
    id: 'chunk-chroma-0009',
    documentId: 'doc-chroma-notes',
    domain: 'personal_learning',
    page: 2,
    section: 'metadata 过滤',
    text: '本地持久化客户端支持在 query 与 get 中传入 where 条件做标量元数据过滤，也可显式传入 query_embeddings，从而让向量生成走统一网关而不是隐式调用 Embedding。'
  },
  {
    id: 'chunk-langgraph-0014',
    documentId: 'doc-langgraph-interrupt',
    domain: 'work_project_a',
    page: 5,
    section: '恢复语义',
    text: '中断恢复时相关节点可能被重新执行，因此确认之前不能执行不可重复的副作用，发送与写入类操作需要幂等保护。'
  },
  {
    id: 'chunk-mcp-0004',
    documentId: 'doc-mcp-boundary',
    domain: 'work_project_a',
    page: 2,
    section: '标注的边界',
    text: '工具标注用于描述能力与风险提示，不能作为授权依据；执行层仍需按工具、参数和资源范围独立检查。'
  }
]

/** 每份资料的可访问范围与授权引用。 */
export const pageSources = [
  { pageId: 'wiki-long-context', chunkId: 'chunk-lc-0412', documentId: 'doc-lc-survey', domain: 'personal_learning', page: 12 },
  { pageId: 'wiki-long-context', chunkId: 'chunk-lc-0418', documentId: 'doc-lc-survey', domain: 'personal_learning', page: 18 },
  { pageId: 'wiki-long-context', chunkId: 'chunk-rope-0033', documentId: 'doc-rope-extrapolation', domain: 'personal_learning', page: 6 },
  { pageId: 'wiki-position-encoding', chunkId: 'chunk-rope-0033', documentId: 'doc-rope-extrapolation', domain: 'personal_learning', page: 6 },
  { pageId: 'wiki-position-encoding', chunkId: 'chunk-rope-0051', documentId: 'doc-rope-extrapolation', domain: 'personal_learning', page: 11 },
  { pageId: 'wiki-attention', chunkId: 'chunk-lc-0412', documentId: 'doc-lc-survey', domain: 'personal_learning', page: 12 },
  { pageId: 'wiki-rag', chunkId: 'chunk-rag-0007', documentId: 'doc-rag-original', domain: 'reading_notes', page: 3 },
  { pageId: 'wiki-rrf', chunkId: 'chunk-chroma-0009', documentId: 'doc-chroma-notes', domain: 'personal_learning', page: 2 },
  { pageId: 'wiki-survey-page', chunkId: 'chunk-lc-0418', documentId: 'doc-lc-survey', domain: 'personal_learning', page: 18 },
  { pageId: 'wiki-domain-isolation', chunkId: 'chunk-mcp-0004', documentId: 'doc-mcp-boundary', domain: 'work_project_a', page: 2 }
]

export const wikiPages = [
  {
    id: 'wiki-long-context',
    title: '长上下文技术',
    type: 'topic',
    typeLabel: '主题页',
    domain: 'personal_learning',
    updatedAt: '2026-09-17 09:20',
    version: 'v7',
    stale: false,
    manuallyEdited: false,
    summary: '把长上下文方案分为稀疏注意力、线性注意力、状态空间模型与检索增强四条路线，并说明各自的吞吐与长程依赖代价。',
    body: [
      { heading: '问题定义', text: '标准注意力对序列长度是二次复杂度，上下文扩展的主要矛盾在于显存与长程依赖保持度不能同时最优。' },
      { heading: '四条路线', text: '稀疏注意力以块为单位裁剪连接；线性注意力用核函数近似 softmax；状态空间模型以固定状态递归；检索增强把"记忆"外置到可检索索引。' },
      { heading: '结论与争议', text: '综述认为四条路线并非互相替代。检索增强在需要精确回溯的任务上优势明显，但引入索引维护成本；状态空间模型吞吐最好，超过 128K 后长程检索准确率下降幅度更大。' }
    ],
    backlinks: ['wiki-attention', 'wiki-survey-page', 'wiki-compare-long-context'],
    outgoing: [
      { targetId: 'wiki-attention', relation: '使用', direction: 'out' },
      { targetId: 'wiki-position-encoding', relation: '扩展', direction: 'out' },
      { targetId: 'wiki-compare-long-context', relation: '比较', direction: 'out' }
    ],
    changelog: [
      { version: 'v7', at: '2026-09-17 09:20', note: '新增 128K 以上长程检索准确率的对比结论', by: '自动编译' },
      { version: 'v6', at: '2026-09-16 14:02', note: '补充状态空间模型的固定状态瓶颈说明', by: '自动编译' },
      { version: 'v5', at: '2026-09-15 10:38', note: '人工补充"s 与"检索增强不适合高频更新场景"', by: '本人' }
    ]
  },
  {
    id: 'wiki-position-encoding',
    title: '位置编码',
    type: 'concept',
    typeLabel: '概念页',
    domain: 'personal_learning',
    updatedAt: '2026-09-16 14:02',
    version: 'v5',
    stale: false,
    manuallyEdited: true,
    summary: '定义位置编码的作用与主要形式，重点整理 RoPE 的频率缩放与外推策略。',
    body: [
      { heading: '定义', text: '位置编码为注意力提供序列顺序信息。绝对位置编码直接加到输入表示上，相对位置编码在注意力分数中加入相对距离项。' },
      { heading: '外推与扩展', text: 'RoPE 通过旋转矩阵编码相对位置。NTK-aware 缩放把有效窗口扩展到训练长度的 2 至 4 倍；YaRN 额外引入注意力温度缩放，在 4 至 8 倍区间更稳定。' },
      { heading: '适用范围', text: '频率缩放只在推理阶段改变频率，不改变模型结构，但它不能替代针对长序列的继续训练。' }
    ],
    backlinks: ['wiki-long-context'],
    outgoing: [{ targetId: 'wiki-attention', relation: '引用', direction: 'out' }],
    changelog: [
      { version: 'v5', at: '2026-09-16 14:02', note: '人工补充适用范围段落', by: '本人', manual: true },
      { version: 'v4', at: '2026-09-15 16:47', note: '根据 RoPE 扩展与外推补充外推区间', by: '自动编译' }
    ]
  },
  {
    id: 'wiki-attention',
    title: '注意力机制',
    type: 'concept',
    typeLabel: '概念页',
    domain: 'personal_learning',
    updatedAt: '2026-09-12 08:55',
    version: 'v3',
    stale: false,
    manuallyEdited: false,
    summary: '自注意力的定义、复杂度来源，以及稀疏化与线性化的动机。',
    body: [
      { heading: '定义', text: '自注意力对序列中每个位置计算与其他所有位置的相关性，输出加权表示。' },
      { heading: '复杂度', text: '标准实现的时间与显存复杂度均为 O(n²)，这是长上下文扩展的直接瓶颈。' }
    ],
    backlinks: ['wiki-long-context', 'wiki-position-encoding'],
    outgoing: [],
    changelog: [{ version: 'v3', at: '2026-09-12 08:55', note: '整理复杂度来源', by: '自动编译' }]
  },
  {
    id: 'wiki-rag',
    title: '检索增强生成',
    type: 'concept',
    typeLabel: '概念页',
    domain: 'reading_notes',
    updatedAt: '2026-09-15 19:41',
    version: 'v4',
    stale: false,
    manuallyEdited: false,
    summary: 'RAG 的基本流程：查询生成向量、域内召回、融合去重、重排、组织证据后生成带引用回答。',
    body: [
      { heading: '基本流程', text: 'RAG 把参数化记忆与非参数化检索结合，检索 Top-k 文档作为生成条件，使知识可更新而不必重新训练全部参数。' },
      { heading: '工程要点', text: '向量查询不等于已经实现混合检索；候选进入重排与模型前需要按当前权限复核，而不只是在最终回答时过滤。' }
    ],
    backlinks: ['wiki-rrf', 'wiki-survey-page'],
    outgoing: [{ targetId: 'wiki-rrf', relation: '扩展', direction: 'out' }],
    changelog: [{ version: 'v4', at: '2026-09-15 19:41', note: '补充候选复核时机', by: '自动编译' }]
  },
  {
    id: 'wiki-rrf',
    title: 'RRF 融合',
    type: 'concept',
    typeLabel: '概念页',
    domain: 'personal_learning',
    updatedAt: '2026-09-15 19:44',
    version: 'v2',
    stale: false,
    manuallyEdited: false,
    summary: '倒数排名融合，把向量召回与关键词召回的排名合并为统一排序。',
    body: [
      { heading: '动机', text: '向量召回擅长语义近似，关键词召回擅长专有名词与代码符号，单一通道都会漏掉对方的强项。' },
      { heading: '做法', text: '对每个通道按排名取倒数并加权求和，避免不同通道的分数尺度不可比问题。' }
    ],
    backlinks: ['wiki-rag'],
    outgoing: [],
    changelog: [{ version: 'v2', at: '2026-09-15 19:44', note: '补充动机说明', by: '自动编译' }]
  },
  {
    id: 'wiki-survey-page',
    title: 'Efficient Long-Context Transformers: A Survey',
    type: 'paper',
    typeLabel: '论文页',
    domain: 'personal_learning',
    updatedAt: '2026-09-17 09:20',
    version: 'v3',
    stale: false,
    manuallyEdited: false,
    summary: '问题、方法、实验、局限与代码链接。',
    body: [
      { heading: '问题', text: '长上下文场景下二次注意力复杂度的显存与延迟代价。' },
      { heading: '方法', text: '按稀疏注意力、线性注意力、状态空间模型与检索增强四条路线分类综述。' },
      { heading: '实验', text: '在 128K 序列上比较吞吐与长程检索准确率，状态空间模型吞吐最好但长程检索下降更大。' },
      { heading: '局限', text: '未覆盖多模态长上下文；对比实验集中在英文语料。' }
    ],
    backlinks: ['wiki-long-context'],
    outgoing: [
      { targetId: 'wiki-long-context', relation: '讨论', direction: 'in' },
      { targetId: 'wiki-compare-long-context', relation: '引用', direction: 'out' }
    ],
    changelog: [{ version: 'v3', at: '2026-09-17 09:20', note: '补全实验与局限', by: '自动编译' }]
  },
  {
    id: 'wiki-compare-long-context',
    title: '长上下文方案对比',
    type: 'comparison',
    typeLabel: '对比页',
    domain: 'personal_learning',
    updatedAt: '2026-09-17 09:21',
    version: 'v2',
    stale: false,
    manuallyEdited: false,
    summary: '在吞吐、显存、长程依赖保持度与维护成本四个维度上比较四类方案。',
    body: [
      { heading: '对比维度', text: '吞吐（tokens/s）、显存占用、128K 以上长程检索准确率、引入的额外维护成本。' },
      { heading: '结论', text: '检索增强在精确回溯上最优但需要索引维护；状态空间模型吞吐最优、长程检索最弱；稀疏与线性注意力居中。' }
    ],
    backlinks: ['wiki-long-context', 'wiki-survey-page'],
    outgoing: [],
    changelog: [{ version: 'v2', at: '2026-09-17 09:21', note: '新增维护成本维度', by: '自动编译' }]
  },
  {
    id: 'wiki-domain-isolation',
    title: '知识域隔离',
    type: 'concept',
    typeLabel: '概念页',
    domain: 'work_project_a',
    updatedAt: '2026-09-13 10:17',
    version: 'v6',
    stale: true,
    staleReason: '来源资料《知识域隔离设计草稿》已更新至 v4',
    manuallyEdited: false,
    summary: '域过滤同时覆盖检索、Wiki、记忆、缓存、派生产物与外发六条路径。',
    body: [
      { heading: '一致规则', text: '向量、关键词、Wiki、按 ID 读取、关系遍历、记忆、摘要与缓存使用同一套域过滤规则。' },
      { heading: '常见退化', text: '空授权域必须直接返回无权限，不能退化为不加过滤的全库检索。' }
    ],
    backlinks: [],
    outgoing: [{ targetId: 'wiki-mcp-boundary', relation: '引用', direction: 'out' }],
    changelog: [{ version: 'v6', at: '2026-09-13 10:17', note: '补充空授权域的退化风险', by: '自动编译' }]
  },
  {
    id: 'wiki-mcp-boundary',
    title: 'MCP 工具标注与执行边界',
    type: 'paper',
    typeLabel: '论文页',
    domain: 'work_project_a',
    updatedAt: '2026-09-11 11:08',
    version: 'v1',
    stale: false,
    manuallyEdited: false,
    summary: '工具标注用于描述能力与风险提示，不能替代执行层授权。',
    body: [
      { heading: '核心结论', text: '隐藏工具只能缩小暴露面，不能替代执行层授权；未知工具默认拒绝。' }
    ],
    backlinks: ['wiki-domain-isolation'],
    outgoing: [],
    changelog: [{ version: 'v1', at: '2026-09-11 11:08', note: '首次编译', by: '自动编译' }]
  }
]

/** 关系类型：讨论 / 使用 / 引用 / 比较 / 扩展。语义相似或发表日期不构成关系证据。 */
export const wikiRelations = ['讨论', '使用', '引用', '比较', '扩展']

/** 工具池定义，对应设计文档 7.5 节的工具池分组。 */
export const toolPools = [
  { id: 'retrieval', label: '本地知识检索', tools: ['search_knowledge_base', 'read_source', 'get_paper_metadata'] },
  { id: 'wiki_read', label: 'Wiki 读取', tools: ['search_wiki', 'get_wiki_page', 'get_related_pages'] },
  { id: 'analysis', label: '分析', tools: ['compare_papers', 'summarize_documents', 'trace_concept_evolution'] },
  { id: 'external_search', label: '外部检索', tools: ['web_search', 'paper_search', 'github_search', 'fetch_source'] },
  { id: 'knowledge_write', label: '知识写入', tools: ['import_document', 'save_note_draft'] },
  { id: 'wiki_write', label: 'Wiki 写入', tools: ['propose_wiki_update', 'commit_wiki_update', 'link_wiki_pages'] },
  { id: 'memory_read', label: '记忆读取', tools: ['memory_retrieve'] },
  { id: 'memory_write', label: '记忆写入', tools: ['memory_add', 'memory_update', 'memory_delete'] },
  { id: 'visualization', label: '可视化', tools: ['build_mindmap', 'build_flowchart', 'render_diagram', 'build_poster'] },
  { id: 'notification', label: '推送', tools: ['prepare_feishu_message', 'send_feishu_message'] }
]

/** 任务到工具池的映射，含初始决策轮次上限。 */
export const taskProfiles = [
  {
    id: 'general_chat',
    label: '普通对话',
    description: '不检索知识库，直接回答',
    pools: [],
    maxRounds: 1,
    icon: 'message'
  },
  {
    id: 'knowledge_qa',
    label: '知识问答',
    description: '在授权域内检索原文并给出带引用的回答',
    pools: ['retrieval', 'wiki_read', 'memory_read'],
    maxRounds: 5,
    icon: 'search'
  },
  {
    id: 'paper_compare',
    label: '论文对比',
    description: '在相同维度下比较多篇论文的方法与实验',
    pools: ['retrieval', 'wiki_read', 'analysis', 'memory_read'],
    maxRounds: 8,
    icon: 'columns'
  },
  {
    id: 'concept_trace',
    label: '概念追溯',
    description: '沿引用与关系追踪概念的演进路径',
    pools: ['retrieval', 'wiki_read', 'analysis'],
    maxRounds: 8,
    icon: 'git-branch'
  },
  {
    id: 'research',
    label: '技术调研',
    description: '联网检索论文与官方资料，形成带来源的调研草稿',
    pools: ['external_search', 'retrieval', 'wiki_read', 'analysis', 'knowledge_write'],
    maxRounds: 10,
    icon: 'globe'
  },
  {
    id: 'visualize',
    label: '知识可视化',
    description: '把已核对的知识组织成导图、流程图或海报',
    pools: ['retrieval', 'wiki_read', 'visualization'],
    maxRounds: 6,
    icon: 'network'
  },
  {
    id: 'push_notification',
    label: '推送通知',
    description: '把报告版本发送到已授权的接收目标',
    pools: ['notification'],
    maxRounds: 3,
    icon: 'send'
  }
]

export const conversations = [
  { id: 'conv-1', title: '长上下文方案对比', taskId: 'paper_compare', updatedAt: '2026-09-20 10:12', pinned: true, messages: 8 },
  { id: 'conv-2', title: 'RoPE 外推区间怎么选', taskId: 'knowledge_qa', updatedAt: '2026-09-19 21:40', pinned: false, messages: 6 },
  { id: 'conv-3', title: '按位置编码生成导图', taskId: 'visualize', updatedAt: '2026-09-19 16:05', pinned: true, messages: 5 },
  { id: 'conv-4', title: '本周新增资料周报', taskId: 'push_notification', updatedAt: '2026-09-18 18:22', pinned: false, messages: 4 },
  { id: 'conv-5', title: 'RRF 融合的权重怎么定', taskId: 'knowledge_qa', updatedAt: '2026-09-17 22:15', pinned: false, messages: 5 },
  { id: 'conv-6', title: '知识域隔离的缓存退化问题', taskId: 'concept_trace', updatedAt: '2026-09-16 11:03', pinned: false, messages: 7 }
]

/** 会话消息。citation 用于引用回溯，toolCalls 用于展示受控调用。 */
export const messages = {
  'conv-1': [
    {
      id: 'm-1',
      role: 'user',
      content: '帮我对比稀疏注意力、线性注意力、状态空间模型和检索增强四条长上下文路线，重点看 128K 以上时谁的长程检索更稳。'
    },
    {
      id: 'm-2',
      role: 'assistant',
      content: '按四条路线在 128K 以上的长程检索表现，结论如下：\n\n1. **检索增强**在需要精确回溯原始事实的任务上最稳，因为它把记忆外置到可检索索引，不依赖注意力在长序列上保持分辨率。代价是索引维护与更新成本。\n2. **稀疏注意力**在块稀疏配置下能保持较长程依赖，但跨块依赖需要多层间接传递，远端信息召回明显下降。\n3. **线性注意力**与**状态空间模型**在中短上下文吞吐接近；超过 128K 后，状态空间模型的固定状态成为瓶颈，长程检索准确率下降幅度大于线性注意力。\n\n需要注意：这个结论来自一份综述的对比实验，实验集中在英文语料，未覆盖多模态长上下文。',
      citations: [
        { chunkId: 'chunk-lc-0418', documentId: 'doc-lc-survey', title: 'Efficient Long-Context Transformers: A Survey', domain: 'personal_learning', page: 18, section: '6.1 方案对比' },
        { chunkId: 'chunk-lc-0412', documentId: 'doc-lc-survey', title: 'Efficient Long-Context Transformers: A Survey', domain: 'personal_learning', page: 12, section: '4.2 稀疏注意力' }
      ],
      toolCalls: [
        { id: 'c-1', tool: 'search_knowledge_base', params: 'query="长上下文 128K 长程检索" top_k=8 domains=[personal_learning]', status: 'ok', duration: '412 ms' },
        { id: 'c-2', tool: 'read_source', params: 'chunk-id=chunk-lc-0418', status: 'ok', duration: '86 ms' },
        { id: 'c-3', tool: 'compare_papers', params: 'dimensions=[吞吐,显存,长程检索准确率]', status: 'ok', duration: '1.8 s' },
        { id: 'c-4', tool: 'get_related_pages', params: 'page=wiki-long-context depth=1', status: 'ok', duration: '134 ms' }
      ],
      inference: '跨资料归纳',
      tokens: { input: 4820, output: 612, cost: '¥0.31' }
    },
    {
      id: 'm-3',
      role: 'user',
      content: '那检索增强是不是就没有缺点了？'
    },
    {
      id: 'm-4',
      role: 'assistant',
      content: '不是。检索增强的主要代价在工程侧：\n\n- **索引维护**：资料更新后需要重建分块与向量，原文变化还会让相关派生产物标记陈旧。\n- **召回上限**：回答质量受召回质量限制，召回不到的证据模型自己也推不出来。\n- **多跳能力弱**：需要跨多份资料串联推理时，单轮检索容易漏掉中间证据。\n\n另外要区分：向量查询不等于已经实现了混合检索。关键词通道缺失时，专有名词和代码符号的召回会明显变差。',
      citations: [
        { chunkId: 'chunk-chroma-0009', documentId: 'doc-chroma-notes', title: 'Chroma 向量检索实践笔记', domain: 'personal_learning', page: 2, section: 'metadata 过滤' }
      ],
      toolCalls: [
        { id: 'c-5', tool: 'search_wiki', params: 'query="检索增强 局限"', status: 'ok', duration: '97 ms' },
        { id: 'c-6', tool: 'read_source', params: 'chunk-id=chunk-chroma-0009', status: 'ok', duration: '74 ms' }
      ],
      inference: '模型推断',
      tokens: { input: 3960, output: 388, cost: '¥0.22' }
    }
  ],
  'conv-2': [
    {
      id: 'm-5',
      role: 'user',
      content: '我要把窗口从 8K 扩到 32K，NTK-aware 和 YaRN 该选哪个？'
    },
    {
      id: 'm-6',
      role: 'assistant',
      content: '外推 4 倍落在两种方法的有效区间内，差别不大：\n\n- **NTK-aware**：只改基频，高频分量保持原有分辨率，低频被压缩。实现最简单，2 至 4 倍区间够用。\n- **YaRN**：在频率缩放之外加了注意力温度缩放，缓解外推时注意力分布过于尖锐，在 4 至 8 倍区间更稳定。\n\n32K 对 8K 是 4 倍，处于边界，如果不打算再做继续训练，建议直接用 YaRN；如果后续还要继续外推到 64K 以上，YaRN 的余量也更足。',
      citations: [
        { chunkId: 'chunk-rope-0033', documentId: 'doc-rope-extrapolation', title: 'RoPE 位置编码的扩展与外推', domain: 'personal_learning', page: 6, section: '3.3 频率缩放' },
        { chunkId: 'chunk-rope-0051', documentId: 'doc-rope-extrapolation', title: 'RoPE 位置编码的扩展与外推', domain: 'personal_learning', page: 11, section: '5.2 YaRN' }
      ],
      toolCalls: [
        { id: 'c-7', tool: 'search_knowledge_base', params: 'query="RoPE 外推 频率缩放" top_k=6', status: 'ok', duration: '358 ms' },
        { id: 'c-8', tool: 'get_wiki_page', params: 'page=wiki-position-encoding', status: 'ok', duration: '62 ms' }
      ],
      inference: '原文事实',
      tokens: { input: 3240, output: 402, cost: '¥0.19' }
    }
  ],
  'conv-3': [
    {
      id: 'm-7',
      role: 'user',
      content: '根据我收藏的长上下文论文，按位置编码、注意力机制和记忆检索生成思维导图，每个节点关联原文。'
    },
    {
      id: 'm-8',
      role: 'assistant',
      content: '已生成导图草稿，共 14 个节点、17 条连线，根节点为「长上下文技术」。\n\n三个一级分支：位置编码（5 个节点）、注意力机制（4 个节点）、记忆检索（5 个节点）。所有节点都关联到了原文片段，其中 11 个节点的证据来自《Efficient Long-Context Transformers: A Survey》，3 个来自《RoPE 位置编码的扩展与外推》。\n\n导图已保存为产物，可以在可视化页继续展开子主题。',
      citations: [
        { chunkId: 'chunk-lc-0412', documentId: 'doc-lc-survey', title: 'Efficient Long-Context Transformers: A Survey', domain: 'personal_learning', page: 12, section: '4.2 稀疏注意力' }
      ],
      toolCalls: [
        { id: 'c-9', tool: 'search_wiki', params: 'query="长上下文" depth=2', status: 'ok', duration: '146 ms' },
        { id: 'c-10', tool: 'build_mindmap', params: 'root=长上下文技术 branches=3 layout=radial', status: 'ok', duration: '2.4 s' }
      ],
      artifact: { id: 'artifact-mindmap-lc', type: 'mindmap', title: '长上下文技术导图' },
      inference: '跨资料归纳',
      tokens: { input: 5120, output: 486, cost: '¥0.34' }
    }
  ],
  'conv-4': [
    {
      id: 'm-9',
      role: 'user',
      content: '整理本周新增资料，生成技术周报，推送到「技术周报群」。'
    },
    {
      id: 'm-10',
      role: 'assistant',
      content: '周报草稿已生成，包含本周新增 4 份资料、2 个 Wiki 页面更新和 1 个待处理冲突。发送前需要你确认接收目标与内容。\n\n接收位置：飞书 · 技术周报群（授权有效期至 2026-10-20）\n发送内容：1420 字，含 6 条引用',
      requiresApproval: {
        action: 'send_feishu_message',
        target: '飞书 · 技术周报群',
        scope: '仅发送本次周报草稿',
        token: 'grant-feishu-weekly'
      },
      citations: [],
      toolCalls: [
        { id: 'c-11', tool: 'prepare_feishu_message', params: 'template=weekly_report length≈1400', status: 'ok', duration: '980 ms' }
      ],
      inference: '模型推断',
      tokens: { input: 2840, output: 720, cost: '¥0.24' }
    }
  ],
  'conv-5': [
    {
      id: 'm-11',
      role: 'user',
      content: 'RRF 融合时两个通道的权重怎么定？'
    },
    {
      id: 'm-12',
      role: 'assistant',
      content: 'RRF 的关键是只用排名、不用原始分数，因此天然避免了向量相似度与 BM25 分数尺度不可比的问题。\n\n权重建议：先取等权（各 1.0）作为基线，再用固定评测集调。经验上专有名词、代码符号密集的知识库可以把关键词通道调到 1.3 至 1.5；以自然语言提问为主的场景向量通道略高更有利。\n\n需要注意的是，权重属于需要评测调优的配置项，不能凭感觉定。',
      citations: [
        { chunkId: 'chunk-chroma-0009', documentId: 'doc-chroma-notes', title: 'Chroma 向量检索实践笔记', domain: 'personal_learning', page: 2, section: 'metadata 过滤' }
      ],
      toolCalls: [
        { id: 'c-12', tool: 'memory_retrieve', params: 'scope=long_term key="检索偏好"', status: 'ok', duration: '48 ms' },
        { id: 'c-13', tool: 'search_knowledge_base', params: 'query="RRF 权重" top_k=5', status: 'ok', duration: '296 ms' }
      ],
      inference: '跨资料归纳',
      tokens: { input: 2210, output: 356, cost: '¥0.14' }
    }
  ],
  'conv-6': [
    {
      id: 'm-13',
      role: 'user',
      content: '知识域隔离在缓存这条路径上容易怎么退化？'
    },
    {
      id: 'm-14',
      role: 'assistant',
      content: '缓存是最容易漏掉的一条路径，常见退化有三种：\n\n1. **缓存键不含权限范围**：同一个问题在不同授权状态下命中同一条缓存，返回越权结果。缓存键需要包含资料版本与权限范围。\n2. **空授权域退化为全库**：域过滤条件为空时没有直接返回无权限，而是拼出了不带过滤的查询。\n3. **命中后不复核权限**：缓存命中后跳过了复核，授权撤销后旧结果仍能返回。\n\n正确做法是缓存命中后仍要复核当前权限，并且域过滤规则在向量、关键词、Wiki、按 ID 读取、关系遍历、记忆与摘要上保持一致。',
      citations: []
    }
  ]
}

/** 任务实例，含工具池解析结果、预算与待确认动作。 */
export const tasks = [
  {
    id: 'task-2049',
    title: '对比四类长上下文方案',
    taskId: 'paper_compare',
    taskLabel: '论文对比',
    status: 'completed',
    statusLabel: '已完成',
    startedAt: '2026-09-20 10:04',
    duration: '38.2 s',
    domains: ['personal_learning', 'reading_notes'],
    tools: ['search_knowledge_base', 'read_source', 'compare_papers', 'get_related_pages', 'memory_retrieve'],
    rounds: { used: 6, max: 8 },
    tokens: { input: 18420, output: 2116 },
    cost: '¥1.28',
    artifacts: ['artifact-report-compare']
  },
  {
    id: 'task-2048',
    title: '生成长上下文技术导图',
    taskId: 'visualize',
    taskLabel: '知识可视化',
    status: 'completed',
    statusLabel: '已完成',
    startedAt: '2026-09-19 16:01',
    duration: '22.6 s',
    domains: ['personal_learning'],
    tools: ['search_wiki', 'get_wiki_page', 'build_mindmap'],
    rounds: { used: 4, max: 6 },
    tokens: { input: 9120, output: 1284 },
    cost: '¥0.62',
    artifacts: ['artifact-mindmap-lc']
  },
  {
    id: 'task-2047',
    title: '推送本周技术周报',
    taskId: 'push_notification',
    taskLabel: '推送通知',
    status: 'waiting_approval',
    statusLabel: '等待确认',
    startedAt: '2026-09-19 18:20',
    duration: '6.4 s',
    domains: ['personal_learning', 'work_project_a'],
    tools: ['prepare_feishu_message', 'send_feishu_message'],
    rounds: { used: 2, max: 3 },
    tokens: { input: 2840, output: 720 },
    cost: '¥0.24',
    artifacts: ['artifact-report-weekly'],
    pending: { action: 'send_feishu_message', target: '飞书 · 技术周报群', scope: '仅发送本次周报草稿' }
  },
  {
    id: 'task-2046',
    title: '检索内部环境拓扑（被拒绝）',
    taskId: 'knowledge_qa',
    taskLabel: '知识问答',
    status: 'rejected',
    statusLabel: '已拒绝',
    startedAt: '2026-09-19 14:32',
    duration: '1.2 s',
    domains: ['restricted'],
    tools: [],
    rounds: { used: 1, max: 5 },
    tokens: { input: 1180, output: 96 },
    cost: '¥0.06',
    artifacts: [],
    rejectReason: '资料标记为 local_only，不进入云端 Embedding 与生成路径'
  },
  {
    id: 'task-2045',
    title: '追踪「位置编码」概念演进',
    taskId: 'concept_trace',
    taskLabel: '概念追溯',
    status: 'completed',
    statusLabel: '已完成',
    startedAt: '2026-09-18 21:12',
    duration: '31.8 s',
    domains: ['personal_learning'],
    tools: ['search_knowledge_base', 'search_wiki', 'trace_concept_evolution'],
    rounds: { used: 7, max: 8 },
    tokens: { input: 14260, output: 1840 },
    cost: '¥0.94',
    artifacts: ['artifact-flowchart-rope']
  },
  {
    id: 'task-2044',
    title: '调研 MCP 工具标注的权限边界',
    taskId: 'research',
    taskLabel: '技术调研',
    status: 'completed',
    statusLabel: '已完成',
    startedAt: '2026-09-18 15:40',
    duration: '1 min 12 s',
    domains: ['work_project_a'],
    tools: ['web_search', 'fetch_source', 'paper_search', 'search_knowledge_base', 'save_note_draft'],
    rounds: { used: 9, max: 10 },
    tokens: { input: 26840, output: 3620 },
    cost: '¥2.06',
    artifacts: ['artifact-report-mcp']
  }
]

/** 执行轨迹 span。参数已脱敏，凭证不进入日志。 */
export const traces = [
  { id: 'span-1', taskId: 'task-2049', at: '10:04:02', kind: 'routing', name: '任务路由', detail: '识别为 paper_compare，置信度 0.94', status: 'ok', duration: '120 ms' },
  { id: 'span-2', taskId: 'task-2049', at: '10:04:02', kind: 'policy', name: '工具池解析', detail: 'retrieval、wiki_read、analysis、memory_read → 有效工具 11 个（授权交集后）', status: 'ok', duration: '38 ms' },
  { id: 'span-3', taskId: 'task-2049', at: '10:04:03', kind: 'tool', name: 'search_knowledge_base', detail: 'query="长上下文 128K 长程检索" top_k=8 domains=[personal_learning, reading_notes]', status: 'ok', duration: '412 ms', tokens: 0 },
  { id: 'span-4', taskId: 'task-2049', at: '10:04:04', kind: 'tool', name: 'read_source', detail: 'chunk-id=chunk-lc-0418', status: 'ok', duration: '86 ms' },
  { id: 'span-5', taskId: 'task-2049', at: '10:04:06', kind: 'model', name: 'LLM 调用 · gpt-4o-mini', detail: '任务路由后的首轮生成，输入 4820 / 输出 612', status: 'ok', duration: '3.4 s', tokens: 5432 },
  { id: 'span-6', taskId: 'task-2049', at: '10:04:11', kind: 'tool', name: 'compare_papers', detail: 'dimensions=[吞吐,显存,长程检索准确率]', status: 'ok', duration: '1.8 s' },
  { id: 'span-7', taskId: 'task-2047', at: '18:20:14', kind: 'tool', name: 'send_feishu_message', detail: 'target=技术周报群 — 等待用户确认，未执行', status: 'waiting', duration: '—' },
  { id: 'span-8', taskId: 'task-2046', at: '14:32:08', kind: 'policy', name: '外发检查', detail: 'domain=restricted 命中 local_only，云端路径已阻断', status: 'rejected', duration: '12 ms' },
  { id: 'span-9', taskId: 'task-2045', at: '21:12:44', kind: 'tool', name: 'trace_concept_evolution', detail: 'concept=位置编码 depth=3', status: 'ok', duration: '2.6 s' },
  { id: 'span-10', taskId: 'task-2045', at: '21:13:02', kind: 'model', name: 'LLM 调用 · claude-sonnet-5', detail: '概念演进归纳，输入 14260 / 输出 1840', status: 'ok', duration: '5.8 s', tokens: 16100 },
  { id: 'span-11', taskId: 'task-2044', at: '15:41:20', kind: 'tool', name: 'web_search', detail: 'query="MCP tool annotations execution boundary"', status: 'ok', duration: '1.4 s' },
  { id: 'span-12', taskId: 'task-2044', at: '15:42:06', kind: 'policy', name: '预算检查', detail: '本任务已用 ¥2.06 / 上限 ¥5.00', status: 'ok', duration: '4 ms' }
]

/** 用量与预算。 */
export const usage = {
  month: '2026-09',
  budget: 60,
  spent: 24.86,
  estimated: 1.2,
  breakdown: [
    { label: 'LLM 生成', amount: 16.42, percent: 66, color: 'indigo' },
    { label: 'Embedding', amount: 4.18, percent: 17, color: 'cyan' },
    { label: '重排', amount: 2.06, percent: 8, color: 'violet' },
    { label: '生图 / 语音', amount: 2.2, percent: 9, color: 'amber' }
  ],
  daily: [
    { day: '09-14', amount: 1.82 },
    { day: '09-15', amount: 2.64 },
    { day: '09-16', amount: 3.41 },
    { day: '09-17', amount: 2.08 },
    { day: '09-18', amount: 5.26 },
    { day: '09-19', amount: 6.12 },
    { day: '09-20', amount: 3.53 }
  ],
  byTask: [
    { label: '技术调研', amount: 8.42, tokens: 68420 },
    { label: '论文对比', amount: 6.18, tokens: 51260 },
    { label: '概念追溯', amount: 4.32, tokens: 34800 },
    { label: '知识问答', amount: 3.44, tokens: 28140 },
    { label: '知识可视化', amount: 2.5, tokens: 20400 }
  ]
}

/** 授权记录。 */
export const grants = [
  {
    id: 'grant-llm-cloud',
    scope: 'tool',
    scopeLabel: '工具与供应商',
    title: '云端 LLM 调用',
    detail: '允许把授权域内的检索片段与提示词发送至已配置的 LLM 供应商',
    targets: ['personal_learning', 'work_project_a', 'reading_notes'],
    targetLabel: '个人学习、工作项目 A、阅读笔记',
    expiresAt: '2026-12-31',
    status: 'active',
    statusLabel: '生效中',
    grantedAt: '2026-09-01 10:00',
    lastUsedAt: '2026-09-20 10:04'
  },
  {
    id: 'grant-embedding',
    scope: 'tool',
    scopeLabel: '工具与供应商',
    title: 'Embedding 外发',
    detail: '允许在导入资料与生成查询向量时调用云端 Embedding',
    targets: ['personal_learning', 'work_project_a', 'reading_notes'],
    targetLabel: '个人学习、工作项目 A、阅读笔记',
    expiresAt: '2026-12-31',
    status: 'active',
    statusLabel: '生效中',
    grantedAt: '2026-09-01 10:00',
    lastUsedAt: '2026-09-16 20:31'
  },
  {
    id: 'grant-dir-research',
    scope: 'directory',
    scopeLabel: '授权目录',
    title: 'D:\\Research',
    detail: '允许读取该目录下的 Markdown 与 PDF，写入仅限 drafts 子目录',
    targets: ['D:\\Research'],
    targetLabel: 'D:\\Research',
    expiresAt: '永久',
    status: 'active',
    statusLabel: '生效中',
    grantedAt: '2026-09-05 09:12',
    lastUsedAt: '2026-09-19 16:01'
  },
  {
    id: 'grant-feishu-weekly',
    scope: 'sender',
    scopeLabel: '推送目标',
    title: '飞书 · 技术周报群',
    detail: '允许向该群发送技术周报，每次发送前展示内容并要求确认',
    targets: ['飞书 · 技术周报群'],
    targetLabel: '飞书 · 技术周报群',
    expiresAt: '2026-10-20',
    status: 'active',
    statusLabel: '生效中',
    grantedAt: '2026-09-18 18:00',
    lastUsedAt: '2026-09-19 18:20'
  },
  {
    id: 'grant-github-read',
    scope: 'tool',
    scopeLabel: '工具与供应商',
    title: 'GitHub 查询',
    detail: '允许查询公开仓库元数据与 README，不允许写入或提交',
    targets: ['public repos'],
    targetLabel: '公开仓库',
    expiresAt: '2026-11-15',
    status: 'active',
    statusLabel: '生效中',
    grantedAt: '2026-09-11 14:20',
    lastUsedAt: '2026-09-18 15:41'
  },
  {
    id: 'grant-web-search',
    scope: 'tool',
    scopeLabel: '工具与供应商',
    title: '联网检索',
    detail: '允许调用搜索服务抓取公开网页，单次任务上限 20 次请求',
    targets: ['public web'],
    targetLabel: '公开网络',
    expiresAt: '2026-10-31',
    status: 'active',
    statusLabel: '生效中',
    grantedAt: '2026-09-11 14:20',
    lastUsedAt: '2026-09-18 15:41'
  },
  {
    id: 'grant-image-gen',
    scope: 'tool',
    scopeLabel: '工具与供应商',
    title: '生图服务',
    detail: '仅用于海报插画与背景，单月预算上限 ¥5.00',
    targets: ['poster'],
    targetLabel: '海报插画',
    // 到期日必须早于演示当日，才能与 status: 'expired' 自洽（授权中心按到期时间推导状态）。
    expiresAt: '2026-09-10',
    status: 'expired',
    statusLabel: '已过期',
    grantedAt: '2026-08-30 11:00',
    lastUsedAt: '2026-09-04 16:22'
  },
  {
    id: 'grant-shell',
    scope: 'tool',
    scopeLabel: '工具与供应商',
    title: '任意脚本执行',
    detail: '首版默认不开放，申请后需人工复核',
    targets: [],
    targetLabel: '未授权',
    expiresAt: '—',
    status: 'denied',
    statusLabel: '未授权',
    grantedAt: '—',
    lastUsedAt: '—'
  }
]

/** 三层记忆，对应设计文档第 6 节。 */
export const memoryItems = [
  {
    id: 'mem-w-1',
    tier: 'working',
    title: '当前任务目标',
    content: '对比四类长上下文方案，重点回答 128K 以上长程检索的稳定性差异。',
    source: '会话 conv-1',
    updatedAt: '2026-09-20 10:04',
    expiresAt: '任务结束后释放',
    domain: 'personal_learning',
    confirmed: true
  },
  {
    id: 'mem-w-2',
    tier: 'working',
    title: '本轮证据集合',
    content: '已读取 chunk-lc-0412、chunk-lc-0418、chunk-chroma-0009，共 3 个片段。',
    source: '检索结果',
    updatedAt: '2026-09-20 10:04',
    expiresAt: '任务结束后释放',
    domain: 'personal_learning',
    confirmed: true
  },
  {
    id: 'mem-w-3',
    tier: 'working',
    title: '待确认动作',
    content: 'send_feishu_message → 技术周报群，等待用户确认后执行。',
    source: '会话 conv-4',
    updatedAt: '2026-09-19 18:20',
    expiresAt: '确认或取消后释放',
    domain: 'personal_learning',
    confirmed: false
  },
  {
    id: 'mem-e-1',
    tier: 'episodic',
    title: '长上下文调研进度',
    content: '四类方案已对比完成，待补：多模态长上下文、中文语料下的复现实验。',
    source: '会话 conv-1',
    updatedAt: '2026-09-20 10:12',
    expiresAt: '2026-10-20',
    domain: 'personal_learning',
    confirmed: true
  },
  {
    id: 'mem-e-2',
    tier: 'episodic',
    title: '周报推送节奏',
    content: '每周五 18:00 整理本周新增资料并生成草稿，发送前需要确认。',
    source: '会话 conv-4',
    updatedAt: '2026-09-19 18:22',
    expiresAt: '2026-12-19',
    domain: 'work_project_a',
    confirmed: true
  },
  {
    id: 'mem-e-3',
    tier: 'episodic',
    title: '待处理冲突',
    content: '《知识域隔离设计草稿》v4 与 Wiki 页面 v6 在缓存退化结论上不一致，待人工裁定。',
    source: 'Wiki 陈旧检测',
    updatedAt: '2026-09-17 09:30',
    expiresAt: '2026-10-17',
    domain: 'work_project_a',
    confirmed: false
  },
  {
    id: 'mem-l-1',
    tier: 'long_term',
    title: '研究方向',
    content: '长上下文与检索增强，关注工程可落地性优先于纯算法创新。',
    source: '用户确认',
    updatedAt: '2026-09-02 20:14',
    expiresAt: '长期',
    domain: 'personal_learning',
    confirmed: true
  },
  {
    id: 'mem-l-2',
    tier: 'long_term',
    title: '回答偏好',
    content: '结论先行，区分原文事实与模型推断，证据不足时明确说明，不要补造引用。',
    source: '用户确认',
    updatedAt: '2026-09-05 09:30',
    expiresAt: '长期',
    domain: 'personal_learning',
    confirmed: true
  },
  {
    id: 'mem-l-3',
    tier: 'long_term',
    title: '检索偏好',
    content: '知识问答默认走 wiki_first 策略；概念关系类问题允许展开 2 层关联页面。',
    source: '用户确认',
    updatedAt: '2026-09-08 15:40',
    expiresAt: '长期',
    domain: 'personal_learning',
    confirmed: true
  },
  {
    id: 'mem-l-4',
    tier: 'long_term',
    title: '输出语言与格式',
    content: '中文回答；技术对比优先用表格或分点，代码与参数保留原文写法。',
    source: '用户确认',
    updatedAt: '2026-09-08 15:42',
    expiresAt: '长期',
    domain: 'personal_learning',
    confirmed: true
  }
]

/** 派生产物：导图、流程图、海报与报告。 */
export const artifacts = [
  {
    id: 'artifact-mindmap-lc',
    type: 'mindmap',
    typeLabel: '思维导图',
    title: '长上下文技术导图',
    domain: 'personal_learning',
    createdAt: '2026-09-19 16:05',
    version: 'v2',
    nodes: 14,
    edges: 17,
    sources: 2,
    stale: false,
    updatedBy: '自动生成'
  },
  {
    id: 'artifact-flowchart-rope',
    type: 'flowchart',
    typeLabel: '流程图',
    title: 'RoPE 外推方案决策流程',
    domain: 'personal_learning',
    createdAt: '2026-09-18 21:18',
    version: 'v1',
    nodes: 9,
    edges: 10,
    sources: 1,
    stale: false,
    updatedBy: '自动生成'
  },
  {
    id: 'artifact-poster-longctx',
    type: 'poster',
    typeLabel: '技术海报',
    title: '长上下文四类方案速览',
    domain: 'personal_learning',
    createdAt: '2026-09-17 20:40',
    version: 'v3',
    nodes: 0,
    edges: 0,
    sources: 3,
    stale: true,
    staleReason: '来源《Efficient Long-Context Transformers: A Survey》已更新至 v2',
    updatedBy: '本人'
  },
  {
    id: 'artifact-report-compare',
    type: 'report',
    typeLabel: '调研报告',
    title: '长上下文方案对比报告',
    domain: 'personal_learning',
    createdAt: '2026-09-20 10:04',
    version: 'v1',
    nodes: 0,
    edges: 0,
    sources: 4,
    stale: false,
    updatedBy: '自动生成'
  },
  {
    id: 'artifact-report-weekly',
    type: 'report',
    typeLabel: '技术周报',
    title: '第 38 周技术周报',
    domain: 'work_project_a',
    createdAt: '2026-09-19 18:20',
    version: 'v1',
    nodes: 0,
    edges: 0,
    sources: 6,
    stale: false,
    updatedBy: '自动生成'
  },
  {
    id: 'artifact-report-mcp',
    type: 'report',
    typeLabel: '调研报告',
    title: 'MCP 工具标注权限边界调研',
    domain: 'work_project_a',
    createdAt: '2026-09-18 15:52',
    version: 'v2',
    nodes: 0,
    edges: 0,
    sources: 5,
    stale: false,
    updatedBy: '本人'
  }
]

/** 导图 / 流程图的图数据。节点与连线是主数据，渲染由前端负责。 */
export const mindmapGraph = {
  'artifact-mindmap-lc': {
    root: 'lc',
    nodes: [
      { id: 'lc', label: '长上下文技术', kind: 'root', sources: 0 },
      { id: 'pe', label: '位置编码', kind: 'branch', sources: 1 },
      { id: 'pe-1', label: '绝对位置编码', kind: 'leaf', sources: 1 },
      { id: 'pe-2', label: 'RoPE 旋转编码', kind: 'leaf', sources: 1 },
      { id: 'pe-3', label: 'NTK-aware 缩放', kind: 'leaf', sources: 1 },
      { id: 'pe-4', label: 'YaRN 温度缩放', kind: 'leaf', sources: 1 },
      { id: 'pe-5', label: '外推区间 2–8 倍', kind: 'leaf', sources: 1 },
      { id: 'att', label: '注意力机制', kind: 'branch', sources: 1 },
      { id: 'att-1', label: '标准自注意力 O(n²)', kind: 'leaf', sources: 1 },
      { id: 'att-2', label: '块稀疏注意力', kind: 'leaf', sources: 1 },
      { id: 'att-3', label: '线性注意力', kind: 'leaf', sources: 1 },
      { id: 'att-4', label: '状态空间模型', kind: 'leaf', sources: 1 },
      { id: 'mem', label: '记忆检索', kind: 'branch', sources: 1 },
      { id: 'mem-1', label: '向量召回', kind: 'leaf', sources: 1 },
      { id: 'mem-2', label: '关键词召回', kind: 'leaf', sources: 1 },
      { id: 'mem-3', label: 'RRF 融合', kind: 'leaf', sources: 1 },
      { id: 'mem-4', label: '重排与证据组织', kind: 'leaf', sources: 1 },
      { id: 'mem-5', label: '检索增强生成', kind: 'leaf', sources: 1 }
    ],
    edges: [
      { from: 'lc', to: 'pe', relation: '包含' },
      { from: 'pe', to: 'pe-1', relation: '包含' },
      { from: 'pe', to: 'pe-2', relation: '包含' },
      { from: 'pe-2', to: 'pe-3', relation: '扩展' },
      { from: 'pe-2', to: 'pe-4', relation: '扩展' },
      { from: 'pe-4', to: 'pe-5', relation: '包含' },
      { from: 'lc', to: 'att', relation: '包含' },
      { from: 'att', to: 'att-1', relation: '包含' },
      { from: 'att-1', to: 'att-2', relation: '扩展' },
      { from: 'att-1', to: 'att-3', relation: '扩展' },
      { from: 'att-1', to: 'att-4', relation: '扩展' },
      { from: 'lc', to: 'mem', relation: '包含' },
      { from: 'mem', to: 'mem-1', relation: '包含' },
      { from: 'mem', to: 'mem-2', relation: '包含' },
      { from: 'mem-1', to: 'mem-3', relation: '使用' },
      { from: 'mem-2', to: 'mem-3', relation: '使用' },
      { from: 'mem-3', to: 'mem-4', relation: '包含' },
      { from: 'mem-4', to: 'mem-5', relation: '包含' }
    ]
  },
  'artifact-flowchart-rope': {
    root: 'f1',
    nodes: [
      { id: 'f1', label: '需要外推多少倍？', kind: 'root', sources: 1 },
      { id: 'f2', label: '2–4 倍', kind: 'branch', sources: 1 },
      { id: 'f3', label: '4–8 倍', kind: 'branch', sources: 1 },
      { id: 'f4', label: 'NTK-aware 基频缩放', kind: 'leaf', sources: 1 },
      { id: 'f5', label: 'YaRN 频率 + 温度缩放', kind: 'leaf', sources: 1 },
      { id: 'f6', label: '是否继续训练？', kind: 'branch', sources: 1 },
      { id: 'f7', label: '是：继续训练扩展窗口', kind: 'leaf', sources: 0 },
      { id: 'f8', label: '否：直接推理外推', kind: 'leaf', sources: 1 },
      { id: 'f9', label: '验证困惑度曲线', kind: 'leaf', sources: 1 }
    ],
    edges: [
      { from: 'f1', to: 'f2', relation: '分支' },
      { from: 'f1', to: 'f3', relation: '分支' },
      { from: 'f2', to: 'f4', relation: '选择' },
      { from: 'f3', to: 'f5', relation: '选择' },
      { from: 'f5', to: 'f6', relation: '分支' },
      { from: 'f6', to: 'f7', relation: '是' },
      { from: 'f6', to: 'f8', relation: '否' },
      { from: 'f8', to: 'f9', relation: '顺序' }
    ]
  }
}

export const posterTemplates = [
  { id: 'poster-compare', label: '方案对比', description: '左标题、右对比矩阵，适合技术选型速览', accent: 'indigo' },
  { id: 'poster-summary', label: '论文速览', description: '问题 / 方法 / 实验 / 局限四段式', accent: 'cyan' },
  { id: 'poster-timeline', label: '概念时间线', description: '仅展示有证据支持的时间节点', accent: 'violet' }
]

/** 模型与检索服务配置。 */
export const modelServices = [
  {
    id: 'llm',
    label: '云端 LLM',
    note: '用于任务路由、查询改写、生成与归纳',
    mode: 'cloud',
    enabled: true,
    provider: 'OpenAI 兼容',
    model: 'gpt-4o-mini',
    endpoint: 'https://api.openai.com/v1',
    health: 'ok',
    healthLabel: '连通正常',
    latency: '412 ms',
    fields: [
      { key: 'model', label: '模型名称', value: 'gpt-4o-mini', placeholder: '例如 gpt-4o-mini' },
      { key: 'endpoint', label: '接口地址', value: 'https://api.openai.com/v1' },
      { key: 'temperature', label: '温度', value: '0.3' },
      { key: 'maxTokens', label: '单次最大输出', value: '4096' }
    ]
  },
  {
    id: 'embedding',
    label: 'Embedding',
    note: '资料导入与查询向量生成，默认走云端避免本地加载模型',
    mode: 'cloud',
    enabled: true,
    provider: 'OpenAI 兼容',
    model: 'text-embedding-3-small',
    endpoint: 'https://api.openai.com/v1',
    health: 'ok',
    healthLabel: '连通正常',
    latency: '96 ms',
    fields: [
      { key: 'model', label: '模型名称', value: 'text-embedding-3-small' },
      { key: 'dimension', label: '向量维度', value: '1536' },
      { key: 'batch', label: '批量大小', value: '64' }
    ]
  },
  {
    id: 'reranker',
    label: 'Reranker',
    note: '候选片段重排，重排前按当前权限复核',
    mode: 'cloud',
    enabled: true,
    provider: 'Cohere 兼容',
    model: 'rerank-multilingual-v3',
    endpoint: 'https://api.cohere.com',
    health: 'ok',
    healthLabel: '连通正常',
    latency: '184 ms',
    fields: [
      { key: 'model', label: '模型名称', value: 'rerank-multilingual-v3' },
      { key: 'candidates', label: '候选数', value: '40' },
      { key: 'topN', label: '重排后保留', value: '8' }
    ]
  },
  {
    id: 'vector',
    label: '向量数据库',
    note: '本地持久化客户端，无需单独部署服务',
    mode: 'local',
    enabled: true,
    provider: 'ChromaDB',
    model: 'PersistentClient',
    endpoint: 'D:\\MindPilot\\data\\chroma',
    health: 'ok',
    healthLabel: '索引可用',
    latency: '—',
    fields: [
      { key: 'path', label: '持久化目录', value: 'D:\\MindPilot\\data\\chroma' },
      { key: 'collection', label: 'Collection', value: 'mindpilot_chunks_v1' },
      { key: 'metric', label: '距离度量', value: 'cosine' }
    ]
  },
  {
    id: 'keyword',
    label: '关键词检索',
    note: '与向量召回做 RRF 融合，覆盖专有名词与代码符号',
    mode: 'local',
    enabled: true,
    provider: 'SQLite FTS5',
    model: 'bm25',
    endpoint: 'D:\\MindPilot\\data\\mindpilot.db',
    health: 'ok',
    healthLabel: '索引可用',
    latency: '42 ms',
    fields: [
      { key: 'k1', label: 'BM25 k1', value: '1.2' },
      { key: 'b', label: 'BM25 b', value: '0.75' },
      { key: 'weights', label: '融合权重（向量 : 关键词）', value: '1.0 : 1.0' }
    ]
  },
  {
    id: 'search',
    label: '联网检索',
    note: 'research 任务使用，调用前检查外发授权与预算',
    mode: 'cloud',
    enabled: true,
    provider: '搜索服务',
    model: 'web + paper',
    endpoint: '—',
    health: 'untested',
    healthLabel: '未测试',
    latency: '—',
    fields: [
      { key: 'maxRequests', label: '单任务请求上限', value: '20' },
      { key: 'protocols', label: '允许协议', value: 'https' },
      { key: 'redirects', label: '最大重定向', value: '3' }
    ]
  },
  {
    id: 'feishu',
    label: '飞书推送',
    note: '发送前展示草稿并要求确认，按任务记录避免重复推送',
    mode: 'cloud',
    enabled: true,
    provider: '飞书开放平台',
    model: 'bot webhook',
    endpoint: 'https://open.feishu.cn',
    health: 'untested',
    healthLabel: '未测试',
    latency: '—',
    fields: [
      { key: 'target', label: '默认接收目标', value: '技术周报群' },
      { key: 'idempotent', label: '幂等键', value: 'task_id + report_version' },
      { key: 'retry', label: '失败重试', value: '2 次，先核查发送状态' }
    ]
  },
  {
    id: 'image',
    label: '生图服务',
    note: '仅用于海报插画与背景，文字与数值由模板排版控制',
    mode: 'cloud',
    enabled: false,
    provider: '图像生成服务',
    model: '—',
    endpoint: '—',
    health: 'disabled',
    healthLabel: '未启用',
    latency: '—',
    fields: [
      { key: 'budget', label: '单月预算上限', value: '¥5.00' },
      { key: 'size', label: '默认尺寸', value: '1024x1024' }
    ]
  },
  {
    id: 'speech',
    label: '语音服务',
    note: 'ASR 与 TTS，首版不常驻监听',
    mode: 'cloud',
    enabled: false,
    provider: '语音服务',
    model: '—',
    endpoint: '—',
    health: 'disabled',
    healthLabel: '未启用',
    latency: '—',
    fields: [
      { key: 'asr', label: 'ASR 模型', value: '—' },
      { key: 'tts', label: 'TTS 音色', value: '—' }
    ]
  }
]

/** 检索策略，对应设计文档 5.4 节的查询协作表。 */
export const retrievalStrategies = [
  { id: 'rag_only', label: '仅原文检索', scene: '原文细节、实验数值', behavior: '原文检索并给出引用' },
  { id: 'wiki_first', label: 'Wiki 优先', scene: '已有主题、概念关系', behavior: '先读有效 Wiki，必要时核对原文' },
  { id: 'wiki_plus_rag', label: 'Wiki + 原文', scene: '跨论文分析', behavior: 'Wiki 提供结构，RAG 补充证据' },
  { id: 'rag_then_wiki', label: '原文 → 关联页', scene: '片段缺少背景', behavior: '从来源映射展开关联页，限制深度与数量' },
  { id: 'research', label: '联网调研', scene: '库外与近期信息', behavior: '授权后联网检索，结果形成草稿' }
]

/** 首页快捷入口。 */
export const quickActions = [
  { id: 'qa', label: '知识问答', description: '在授权域内检索原文，回答带引用', taskId: 'knowledge_qa', prompt: '在个人学习域里检索长上下文资料，说明稀疏注意力与线性注意力的取舍。' },
  { id: 'compare', label: '论文对比', description: '相同维度下对比多篇论文', taskId: 'paper_compare', prompt: '对比这几篇长上下文论文在吞吐与长程检索准确率上的差异。' },
  { id: 'trace', label: '概念追溯', description: '沿引用追踪概念演进', taskId: 'concept_trace', prompt: '追踪「位置编码」这个概念在我的资料里的演进路径。' },
  { id: 'research', label: '技术调研', description: '联网检索并形成草稿', taskId: 'research', prompt: '调研长上下文模型在工程落地时的显存与延迟权衡。' },
  { id: 'visualize', label: '生成导图', description: '把已核对的知识组织成结构图', taskId: 'visualize', prompt: '按位置编码、注意力机制和记忆检索生成思维导图，每个节点关联原文。' },
  { id: 'wiki', label: '整理 Wiki', description: '把新资料编译进主题页', taskId: 'wiki_organize', prompt: '把本周新增的长上下文资料整理进「长上下文技术」主题页，先给我看差异。' }
]

/** 全局检索策略默认值。 */
export const defaultSettings = {
  defaultStrategy: 'wiki_plus_rag',
  maxRounds: 8,
  candidates: 40,
  rerankTopN: 8,
  monthlyBudget: 60,
  autoWikiCompile: true,
  strictEgress: true,
  blockLocalOnly: true
}
