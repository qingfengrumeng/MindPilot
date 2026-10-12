"""Document-level IR metrics and source-span coverage, independent of chunking."""
import math


def retrieval_metrics(chunks, question, k):
    judgments = question.get("judgments", {})
    ranked = list(dict.fromkeys(item["documentId"] for item in chunks))[:k]
    grades = [judgments.get(doc, 0) for doc in ranked]
    positives = sum(value > 0 for value in judgments.values())
    hits = sum(value > 0 for value in grades)
    dcg = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(grades))
    ideal = sorted(judgments.values(), reverse=True)[:k]
    idcg = sum((2 ** grade - 1) / math.log2(i + 2) for i, grade in enumerate(ideal))
    # Unknown judgments are zero only for provisional scoring, never called irrelevant.
    result = {"precision": hits / k if positives else None,
        "recall": hits / positives if positives else None,
        "mrr": next((1 / (i + 1) for i, grade in enumerate(grades) if grade > 0), 0) if positives else None,
        "ndcg": dcg / idcg if idcg else None,
        "hitRate": float(hits > 0) if positives else None,
        "judgedCoverage": sum(doc in judgments for doc in ranked) / len(ranked) if ranked else 0,
        "provisional": not question.get("complete", False) or any(doc not in judgments for doc in ranked),
        "knownRelevant": positives, "retrievedDocuments": len(ranked), "cutoff": k}
    evidence = question.get("evidence", [])
    covered, total = 0, 0
    for span in evidence:
        intervals = sorted((max(span["start"], c["start"]), min(span["end"], c["end"]))
            for c in chunks if c["documentId"] == span["documentId"] and c["page"] == span["page"]
            and c["start"] < span["end"] and c["end"] > span["start"])
        stop = span["start"]
        for start, end in intervals:
            covered += max(0, end - max(start, stop))
            stop = max(stop, end)
        total += span["end"] - span["start"]
    result["evidenceCoverage"] = covered / total if total else None
    result['chunkPrecision']=sum(judgments.get(chunk['documentId'],0)>0 for chunk in chunks[:k])/k if positives else None
    return result


METRIC_KEYS = ("precision", "recall", "mrr", "ndcg", "hitRate", "judgedCoverage", "evidenceCoverage",
               "faithfulness", "answerConsistency", "referenceRecall", "groundedness", "potentialHallucinationRate", "semanticFaithfulness", "factualConsistency", "chunkPrecision")


def aggregate(results):
    values = {}
    for key in METRIC_KEYS:
        scores = [r.get("metrics", {}).get(key) for r in results if not r.get("error")]
        scores = [v for v in scores if v is not None]
        values[key] = sum(scores) / len(scores) if scores else None
    values["successful"] = sum(not r.get("error") for r in results)
    values["failed"] = sum(bool(r.get("error")) for r in results)
    values["provisional"] = any(r.get("metrics", {}).get("provisional", True) for r in results)
    values['metricCounts']={key:sum(r.get('metrics',{}).get(key) is not None and not r.get('error') for r in results) for key in METRIC_KEYS}
    return values
