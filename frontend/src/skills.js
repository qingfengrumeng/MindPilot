import {
  FileSearch,
  GitBranch,
  GitCompare,
  Globe,
  History,
  Image as ImageIcon,
  Network,
  NotebookText
} from 'lucide-vue-next'

/**
 * 能力（技能）注册表：首页与输入框里可选的全部能力都来自这里。
 *
 * 一条能力 = 一个专门的系统提示词 + 一段完整的示例提示词：
 * - systemPrompt 是选中这条能力后交给后端模型的补充系统提示词，决定回答的口径；
 * - example 是一整句可以直接发出去的示例，点成果卡片时原样落进输入框。
 *   它写得像用户自己会打出来的那句话（带上具体的论文、章节、字段），不是留空待填的模板：
 *   框里不会再有占位符或待填槽位，用户就着这句话改，不想改直接回车。
 * 从「/」面板挑能力时不铺示例——那只是换一件工具，提示词由用户自己写。
 *
 * group 仅用于在能力面板中分组，任何能力都可在同一会话中使用。
 *
 * systemPrompt 会随请求提交给后端，不包含密钥。
 */
export const SKILLS = [
  /* ----------------------------- 检索与问答 ----------------------------- */
  {
    id: 'kb_qa',
    group: 'knowledge',
    label: '知识问答',
    description: '在授权域内检索原文，回答带引用',
    icon: FileSearch,
    sample: '在个人学习域里检索长上下文资料',
    systemPrompt: '你是知识库问答助手。只依据检索到的原文片段作答，先给结论再列证据，标注出处（文档名 + 页码 + 章节）；证据不足时直接说明不足，禁止外推或编造引用；属于模型推断的内容必须显式标注。',
    example: '我的知识库里关于长上下文外推有哪几种主流做法？分别说清楚各自的做法、适合的场景和代价，每条结论都标上原文出处。'
  },
  {
    id: 'paper_compare',
    group: 'knowledge',
    label: '论文对比',
    description: '相同维度下横向对比多篇论文',
    icon: GitCompare,
    sample: '对比几篇长上下文论文的吞吐与准确率',
    systemPrompt: '你是论文对比助手。先与用户确认对比维度，再逐维度给出结论与原文依据；不同论文结论冲突时必须并列呈现，不做取舍式概括；缺少证据的维度留空并说明。',
    example: '对比《LongRoPE》和《YaRN》这两篇论文：各自要解决什么问题、位置插值的做法有什么差别、在哪些评测上更强，冲突的地方并列写出来。'
  },
  {
    id: 'concept_trace',
    group: 'knowledge',
    label: '概念追溯',
    description: '沿引用追踪概念演进路径',
    icon: History,
    sample: '追踪「位置编码」在我的资料里的演进',
    systemPrompt: '你是概念追溯助手。沿引用关系按时间顺序梳理概念的演进：每个节点说明它解决了什么问题、又留下了什么问题；只记录有原文证据的节点，推测出的关联要标注为推断。',
    example: '追溯「位置插值」这个概念在我资料里的演进：最早由哪篇工作提出，后来被哪些工作改进，现在是不是主流方案，按时间把关键节点列出来。'
  },
  {
    id: 'research',
    group: 'knowledge',
    label: '技术调研',
    description: '库内为主，必要时联网检索',
    icon: Globe,
    sample: '调研长上下文落地时的显存与延迟权衡',
    systemPrompt: '你是技术调研助手。优先使用库内资料；库内证据不足的部分才走联网检索，并明确标注哪些结论来自库外、检索时间与来源链接；外发前先说明将要发送的内容与授权范围。',
    example: '调研长上下文模型落地时的显存与延迟权衡：业内有哪些主流做法、各自的取舍是什么、还缺哪些实测数据，库内没有的部分标出来等我授权再联网。'
  },
  {
    id: 'wiki_organize',
    group: 'knowledge',
    label: '整理Wiki',
    description: '把新资料编译进主题页',
    icon: NotebookText,
    sample: '把本周新增的长上下文资料整理进主题页',
    systemPrompt: '你是Wiki编译助手。把新资料归入对应的主题页：先给出将要新增与修改的段落及差异，等用户确认后再写入；保持页面既有结构与术语一致，不要静默覆盖原有结论。',
    example: '把知识库里关于检索增强生成的这批资料编译进「RAG」主题页：先列出准备新增和修改的段落，等我确认后再写入。'
  },

  /* ----------------------------- 结构化产物 ----------------------------- */

  {
    id: 'flowchart',
    group: 'artifacts',
    label: '流程图',
    description: '把步骤与分支整理成可读的流程图',
    icon: GitBranch,
    artifactType: 'flowchart',
    defaultTitle: '流程梳理图',
    sample: '把论文里的实验流程整理成流程图',
    systemPrompt: '你是流程图生成器。把描述整理成有向流程：节点用动宾短语，判断节点写成问句并把条件标在分支连线上；保留异常回退与并行分支，遇到描述里缺失的环节提出来而不是自行补齐。',
    example: '把《LongRoPE》里的实验流程整理成流程图：突出数据准备、训练、消融三步的先后与判断分支，异常回退的路径也标出来。'
  },
  {
    id: 'mindmap',
    group: 'artifacts',
    label: '思维导图',
    description: '把一段内容拆成三级结构',
    icon: Network,
    artifactType: 'mindmap',
    defaultTitle: '结构导图',
    sample: '把这段笔记按概念、方法、结论拆成导图',
    systemPrompt: '你是思维导图生成器。把内容拆成三级结构：一级是主题，二级是关键概念，三级是可核对的要点；同级节点保持同一抽象层级，不混合分类维度，每个要点标注原文出处。',
    example: '把《LongRoPE》这篇论文拆成思维导图：中心是研究问题，一级分支放方法、实验、结论，方法下面再细分成位置插值、微调策略、推理适配三个子节点。'
  },

  {
    id: 'poster',
    group: 'artifacts',
    label: '海报设计',
    description: '多Agent设计海报，可加入上传图片并导出HTML、PNG、PDF',
    icon: ImageIcon,
    artifactType: 'poster',
    defaultTitle: '海报设计',
    sample: '为我的活动设计一张深蓝科技风海报，突出主题、三条卖点和报名按钮',
    systemPrompt: '你是海报设计功能域的入口。提炼用户的传播目标，保留指定品牌、日期、文案和上传图片；调用设计、渲染与质检流程，交付可编辑HTML与PNG、PDF。',
    example: '设计一张深蓝科技风的AI创意活动海报：主标题是“让每个想法走得更远”，底部放探索、创作、协作三项亮点，并把我上传的报名二维码放进海报。'
  },

]

/** 能力面板的分组，同一会话可跨组使用能力。 */
export const SKILL_GROUPS = [
  { id: 'knowledge', label: '检索与问答' },
  { id: 'artifacts', label: '结构化产物' }
]

/** 按 id 取一条能力，找不到时返回 null（历史消息里可能留着已下线的能力）。 */
export function findSkill(id) {
  return SKILLS.find(item => item.id === id) || null
}

/** 取某个分组下的全部能力，顺序与注册表一致。 */
export function skillsByGroup(group) {
  return SKILLS.filter(item => item.group === group)
}
