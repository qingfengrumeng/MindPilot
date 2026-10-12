# RAG 评测与实验数据管理

更新日期：2026-10-12。

## 数据隔离与可视化管理

实验空间保存于业务数据库 `backend/data/mindpoilt.sqlite` 的 `evaluation_workspaces`。文档文件保存于 `backend/data/model_comparisons/rag/<workspace-id>/`，24小时未活动后过期，不进入正式知识资料、向量索引、会话或记忆。

“黄金文档”按钮打开分页正文管理页，可编辑名称与各页内容、删除文档。“测试集”按钮打开问题列表管理页，可搜索、增删问题、编辑黄金答案及开发/测试分组。原评测主页面继续提供0—3级文档相关性、精确证据位置和标注完整性管理。编辑正文会使该文档原有字符证据位置失效，要求重新复核。

“载入配套样例”只写入空空间，避免覆盖用户资料。配套文件在 `backend/data/model_comparisons/sample_datasets/starbridge/`：12份Markdown、72页正文、约5.5万字符、144条问题（96开发、48测试），每题都有答案、完整文档相关性和原文证据。机构和制度为合成样例，同一事实的改写题在同一分组，不能作为现实业务政策或真实生产质量的代表。

## 两层指标

检索质量：文档Precision@k、片段Precision@k、Recall@k、MRR@k、nDCG@k、Hit Rate、标注覆盖及黄金证据覆盖。文档指标对同一文档多个命中片段去重，片段Precision按实际片段计算；两者分母为k。只有一份相关文档时，文档Precision@5理论上不超过20%，不能不考虑数据特点就套用通用阈值。Recall只针对已标注正例，标注不全必须显示暂定。

生成一致性：

| 指标 | 当前口径 | 需要的模型 |
| --- | --- | --- |
| Faithfulness | 逐条回答事实由检索证据支持的比例，按评审来源索引检查 | 回答LLM与不同型号的评审LLM |
| 语义忠实度 | 每句与检索片段最高余弦相似度的平均值 | 回答LLM、当前方案Embedding |
| Groundedness | 句子满足语义阈值或字面依据阈值任一项的比例 | 回答LLM、Embedding |
| 潜在幻觉率 | 语义和字面均不达阈值的句子比例，等于1−Groundedness | 回答LLM、Embedding |
| Factual Consistency | 独立LLM检查内部矛盾、数字/实体与来源及黄金答案冲突；返回分数、consistent/inconsistent/uncertain与理由 | 回答LLM与不同型号评审LLM |
| 参考一致性、参考事实召回 | 回答事实由黄金答案支持的比例，以及黄金事实被回答覆盖的比例 | 有黄金答案且有评审LLM |

双信号默认语义阈值0.65、字面重合阈值0.8，可在方案页调整。文本规范化后完整子串命中算字面支持，其他情况计算字符n-gram覆盖。此方法保护“0.25克”“黄连、地榆”等短答案，但词汇重合或语义相似不能证明事实正确；高相似度的否定、数值篡改仍需独立评审与人工复核。逐句记录保留两个分数和对应来源，最多评估60句。检索不采用Milvus，继续使用隔离内存中的精确余弦检索，指标不依赖向量数据库品牌。

Faithfulness定义参照[Ragas的事实支持口径](https://docs.ragas.io/en/latest/concepts/metrics/available_metrics/faithfulness/)，不把单一余弦分数命名为事实忠实度。界面同时展示用户给出的参考等级表，注明需业务校准；非k=5方案不套用@5的等级。缺模型、缺参考、失败或不确定时显示“—”，绝不填0或编造分数；聚合展示每项实际计分题数。

## 结果保留与复现

LLM与RAG页分别提供“保存测试结果／保存评测结果”“已保存结果”。明确保存的JSON报告永久保留在 `backend/data/model_comparisons/saved_reports/<user-id>/<report-id>.json`，独立于临时空间过期清理，按账户隔离。支持查看、下载和删除，拒绝密钥与认证字段。报告保留实际型号、输入/参数、回答、耗时/用量、检索片段、指标、逐句/逐事实记录和错误；历史归档仅查看，不绑定新实验空间重算。

`backend/run_model_benchmarks.py`使用已配置密钥进行真实试验：DeepSeek两个型号、两种Embedding、两种Reranker、分块/top-k变化的12题代表性检索，以及3题回答生成与独立评审。完整144题样例可在界面按开发集/测试集运行。脚本不更改活动模型路由，空实验空间可自动载入样例；每次调用会产生厂商用量，不应无理由反复执行。

`text-embedding-v3/v4`最多10条/批，Embedding适配器自动拆分最多20条的调用，重新合并索引及用量。[阿里云官方限制](https://www.alibabacloud.com/help/en/model-studio/text-embedding-synchronous-api)。
