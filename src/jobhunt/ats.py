"""ATS keyword check per application (ai-job-search /apply step 5d idea, no LLM).

Finds which known data-engineering terms the posting asks for, and for each says where it stands:
  covered        the tailored resume uses it (literal match, as a recruiter's keyword search would)
  add it         you have it (base resume / verified skills) but the tailored resume doesn't say it
  gap            on your gap list: leave it out of the resume, address it honestly in the letter
  not in profile neither: probably a real gap; never claim it
Matching is literal on purpose: "CDC" and "change data capture" are different strings to many
ATS searches, which is why the resume writes both forms.
"""
from __future__ import annotations
import re

# canonical term -> aliases (all lowercase, matched on word boundaries)
TERMS: dict[str, list[str]] = {
    "SQL": ["sql"], "Python": ["python"], "Java": ["java"], "Scala": ["scala"], "Go": ["golang"],
    "pandas": ["pandas"], "Apache Spark / PySpark": ["spark", "pyspark"], "Apache Flink": ["flink"],
    "Apache Kafka": ["kafka"], "Kafka Connect": ["kafka connect"], "Kafka Streams": ["kafka streams"],
    "Change Data Capture (CDC)": ["change data capture", "cdc", "debezium"],
    "Avro / Schema Registry": ["avro", "schema registry"], "Kinesis": ["kinesis"], "Pub/Sub": ["pub/sub", "pubsub"],
    "streaming / real-time": ["streaming", "real-time", "real time", "near real-time", "event-driven"],
    "batch processing": ["batch"], "ETL / ELT": ["etl", "elt"], "data pipelines": ["data pipeline", "data pipelines", "pipelines"],
    "data modeling": ["data modeling", "data modelling", "dimensional model", "star schema", "kimball", "data vault"],
    "SCD": ["scd", "slowly changing"], "data warehouse": ["data warehouse", "data warehousing", "dwh"],
    "data lake / lakehouse": ["data lake", "lakehouse", "delta lake", "iceberg", "hudi"],
    "Snowflake": ["snowflake"], "BigQuery": ["bigquery"], "Redshift": ["redshift"], "Databricks": ["databricks"],
    "PostgreSQL": ["postgresql", "postgres"], "SQL Server": ["sql server", "mssql"], "MySQL": ["mysql"],
    "NoSQL / MongoDB": ["nosql", "mongodb", "cassandra", "dynamodb"],
    "Apache Airflow": ["airflow"], "dbt": ["dbt"], "Temporal": ["temporal"], "Dagster / Prefect": ["dagster", "prefect"],
    "orchestration": ["orchestration", "workflow scheduling"],
    "AWS": ["aws", "amazon web services", "s3", "glue", "emr", "lambda"], "GCP": ["gcp", "google cloud"],
    "Azure": ["azure", "adf", "data factory", "synapse"],
    "Kubernetes": ["kubernetes", "k8s", "aks", "eks", "gke"], "Docker": ["docker", "containers"], "Helm": ["helm"],
    "Terraform": ["terraform", "pulumi", "cloudformation"],
    "Infrastructure as Code": ["infrastructure as code", "iac"],
    "GitOps / Flux / Argo": ["gitops", "flux", "argo"], "CI/CD": ["ci/cd", "continuous integration", "continuous delivery", "ci cd"],
    "Git": ["git"], "Linux / Bash": ["linux", "bash", "shell scripting"],
    "data quality": ["data quality", "great expectations", "data validation", "data contracts"],
    "data observability / monitoring": ["observability", "monitoring", "data reliability"],
    "data governance / lineage": ["data governance", "lineage", "data catalog"],
    "BI (Looker / Tableau / Power BI)": ["looker", "tableau", "power bi"],
    "REST APIs / microservices": ["rest api", "rest apis", "microservices", "fastapi", "flask"],
    "machine learning / MLOps": ["machine learning", "mlops", "feature store"],
    "LLM / RAG / GenAI": ["llm", "llms", "rag", "retrieval-augmented", "generative ai", "genai", "langchain", "vector database"],
    "Fivetran / Airbyte": ["fivetran", "airbyte"],
}


def _has(text: str, aliases: list[str]) -> bool:
    low = (text or "").lower()
    return any(re.search(r"(?<![a-z0-9])" + re.escape(a) + r"(?![a-z0-9])", low) for a in aliases)


def coverage(jd: str, resume: str, sources: str, gaps: list[str]) -> list[tuple[str, str]]:
    """[(term, status)] for every known term the posting mentions."""
    gap_text = " ".join(str(g) for g in gaps or [])
    out = []
    for term, aliases in TERMS.items():
        if not _has(jd, aliases):
            continue
        if _has(resume, aliases):
            status = "covered"
        elif _has(gap_text, aliases) or _has(gap_text, [term.lower()]):
            status = "gap"
        elif _has(sources, aliases):
            status = "add it"
        else:
            status = "not in profile"
        out.append((term, status))
    order = {"add it": 0, "not in profile": 1, "gap": 2, "covered": 3}
    return sorted(out, key=lambda t: order[t[1]])


def table(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    n_cov = sum(1 for _, s in rows if s == "covered")
    note = {"covered": "in your tailored resume", "add it": "you have it: add it to the resume",
            "gap": "on your gap list: don't claim it; the letter names it",
            "not in profile": "not in your profile: don't claim it"}
    lines = [f"## ATS keyword check ({n_cov}/{len(rows)} of the posting's terms covered)",
             "| term in the posting | status |", "|---|---|"]
    lines += [f"| {t} | {s}: {note[s]} |" for t, s in rows]
    return "\n".join(lines)


def terms_you_have(jd: str, sources: str, gaps: list[str]) -> list[str]:
    """The posting's terms the candidate genuinely has: handed to the resume writer to use verbatim."""
    return [t for t, st in coverage(jd, "", sources, gaps) if st == "add it"]
