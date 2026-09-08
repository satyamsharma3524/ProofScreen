import json
from pathlib import Path

path = Path("data/claim_taxonomy.json")
data = json.loads(path.read_text())

legacy = ["SPECIFICITY", "PROCESS", "AUTHENTICITY", "CAUSAL_REASONING", "METRIC_OWNERSHIP", "TOOL_FAMILIARITY"]

def clean_weights(weights):
    if not weights:
        return weights
    for k in legacy:
        weights.pop(k, None)
    
    # Optional: re-normalize the remaining weights to sum to 1.0?
    # Actually, in the global dimension weights they just add up to whatever.
    # The scoring normalizes them anyway.
    return weights

if "dimension_weights" in data:
    clean_weights(data["dimension_weights"])

for family, f_data in data.get("families", {}).items():
    if "dimension_weights" in f_data:
        clean_weights(f_data["dimension_weights"])

path.write_text(json.dumps(data, indent=2) + "\n")
print("Taxonomy updated.")
