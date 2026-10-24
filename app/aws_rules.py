"""AWS evidence rules use the same bounded outcome contract as Azure."""
from app.resource_catalog import definitions
from app.multicloud_rules import evaluate_inventory as _evaluate
DEFINITIONS=tuple(r for r in definitions() if r[1]=='aws')
def evaluate_inventory(inventory,**kwargs):return _evaluate(inventory,providers={'aws'},**kwargs)
