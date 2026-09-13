"""VG Select: 3A (Automated Agentic Architecture).

Scan a repository and/or describe a workload, then get a ranked, evidence-cited
architecture recommendation that balances latency and accuracy.

Public API:

    from vgselect3a import WorkloadProfile, recommend
    rec = recommend(WorkloadProfile(...))
    print(rec.to_markdown())
"""

from .profile import WorkloadProfile, FIELD_SPECS
from .recommender import recommend, Recommendation
from .topologies import TOPOLOGIES, Topology

__all__ = [
    "WorkloadProfile",
    "FIELD_SPECS",
    "recommend",
    "Recommendation",
    "TOPOLOGIES",
    "Topology",
]
__version__ = "0.4.1"
PRODUCT_NAME = "VG Select: 3A (Automated Agentic Architecture)"
