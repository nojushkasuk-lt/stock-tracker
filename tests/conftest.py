import os

# Tests never call Yahoo: charts are off unless a test injects a fake provider.
os.environ.setdefault("CHART_PROVIDER", "none")
