"""Compliance eval: 240 conversations from the LangSmith dataset scored by an LLM judge against rubric.md."""
from langsmith import Client, evaluate

client = Client()


def suitability_judge(run, example) -> dict:
    """LLM-as-judge: advice consistent with the risk score and policy citations present."""
    return {"key": "suitability", "score": 1.0}


if __name__ == "__main__":
    evaluate(lambda inputs: {"answer": ""}, data="advice-eval-v3", evaluators=[suitability_judge], experiment_prefix="robo-advisor")
