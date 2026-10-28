from prometheus_client import Counter, Histogram

TASK_EXECUTION_LATENCY = Histogram(
    "task_execution_duration_seconds",
    "Time spent running task containers in Kubernetes",
    ["task_name", "status"]
)

TASK_FAILURES_TOTAL = Counter(
    "task_failures_total",
    "Total number of failed task executions",
    ["task_name"]
)

TASK_RETRIES_TOTAL = Counter(
    "task_retries_total",
    "Total number of task retries triggered",
    ["task_name"]
)