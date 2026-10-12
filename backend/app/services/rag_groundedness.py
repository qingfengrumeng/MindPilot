"""Auditable dual-signal heuristics; never presented as factual verification."""
import re


def normalized_text(text):
    return re.sub(r'[^\w\u4e00-\u9fff]', '', re.sub(r'\[\d+\]', '', text)).lower()


def lexical_support(sentence, context):
    needle, haystack=normalized_text(sentence),normalized_text(context)
    if not needle:return 0.0
    if needle in haystack:return 1.0
    width=2 if len(needle)<8 else 3
    grams={needle[i:i+width] for i in range(max(0,len(needle)-width+1))}
    if not grams:return 0.0
    return sum(gram in haystack for gram in grams)/len(grams)


def sentences_for(answer):
    parts=[text.strip() for text in re.split(r'(?<=[。！？!?;；])|(?<=\.)\s+|\n+',answer)]
    return [text for text in parts if normalized_text(text) and not re.match(r'^#{1,6}\s+',text)
            and not re.fullmatch(r'(?:来源|参考资料|参考来源|sources?|references?)\s*[:：]?\s*(?:\[\d+\][,，\s]*)+',text,re.I)][:60]


def dual_signal_metrics(sentences,contexts,sentence_vectors,context_vectors,semantic_threshold=.65,lexical_threshold=.8):
    if not sentences or not contexts:return {'groundedness':None,'potentialHallucinationRate':None,'semanticFaithfulness':None},[]
    if len(contexts)!=len(context_vectors) or len(sentences)!=len(sentence_vectors):
        raise ValueError('双信号向量数量与文本不一致')
    records=[]
    for sentence,vector in zip(sentences,sentence_vectors,strict=True):
        semantic=[max(-1.0,min(1.0,sum(a*b for a,b in zip(vector,cv,strict=True)))) for cv in context_vectors]
        lexical=[lexical_support(sentence,context) for context in contexts]
        best_semantic=max(semantic);best_lexical=max(lexical)
        sources=[i for i,(score,match) in enumerate(zip(semantic,lexical,strict=True)) if score>=semantic_threshold or match>=lexical_threshold]
        records.append({'sentence':sentence,'semanticSimilarity':best_semantic,'lexicalOverlap':best_lexical,'supported':bool(sources),'sources':sources,'potentialHallucination':not bool(sources)})
    supported=sum(record['supported'] for record in records)/len(records)
    return {'groundedness':supported,'potentialHallucinationRate':1-supported,
            'semanticFaithfulness':sum(max(0.,r['semanticSimilarity']) for r in records)/len(records)},records
