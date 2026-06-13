import uuid
from datetime import datetime
from typing import List

from langchain_huggingface import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    VectorParams,
    PointStruct,
    Filter,
    FieldCondition,
    MatchValue,
)

from config import settings
from memory.schemas import IncidentRecord
from agent.state import OpsAgentState, PastIncident


# ---------------------------------------------------------------------------
# Embeddings client (module-level singleton)
# ---------------------------------------------------------------------------
embeddings = HuggingFaceEmbeddings(
    model_name=settings.hf_embedding_model,
    model_kwargs={"device": "cpu"},
    encode_kwargs={"normalize_embeddings": True},
)


# ---------------------------------------------------------------------------
# LongTermMemory class
# ---------------------------------------------------------------------------
class LongTermMemory:
    """Wraps Qdrant for episodic incident memory storage and retrieval."""

    VECTOR_SIZE = 384  # BAAI/bge-small-en-v1.5 output dimension

    def __init__(self):
        if settings.qdrant_api_key:
            self._client = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_api_key,
            )
        else:
            self._client = QdrantClient(url=settings.qdrant_url)

        self._collection = settings.qdrant_collection
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        """Create the Qdrant collection if it does not already exist."""
        existing = [c.name for c in self._client.get_collections().collections]
        if self._collection not in existing:
            self._client.create_collection(
                collection_name=self._collection,
                vectors_config=VectorParams(
                    size=self.VECTOR_SIZE,
                    distance=Distance.COSINE,
                ),
            )

    def write_incident(self, record: IncidentRecord) -> None:
        """Embed the record's embedding_text and upsert it into Qdrant."""
        vector = embeddings.embed_query(record.embedding_text)
        point = PointStruct(
            id=str(uuid.uuid5(uuid.NAMESPACE_URL, record.incident_id)),
            vector=vector,
            payload=record.model_dump(),
        )
        self._client.upsert(collection_name=self._collection, points=[point])

    def search_similar(self, query: str, top_k: int = 3) -> List[IncidentRecord]:
        """Return the top-k most semantically similar past incidents."""
        vector = embeddings.embed_query(query)
        response = self._client.query_points(
            collection_name=self._collection,
            query=vector,
            limit=top_k,
            with_payload=True,
        )
        records = []
        for hit in response.points:
            try:
                records.append(IncidentRecord(**hit.payload))
            except Exception:
                continue
        return records

    def get_by_intent(self, intent: str, limit: int = 5) -> List[IncidentRecord]:
        """Return recent incidents filtered by intent type."""
        results = self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="intent", match=MatchValue(value=intent))]
            ),
            limit=limit,
            with_payload=True,
        )
        records = []
        for point in results[0]:
            try:
                records.append(IncidentRecord(**point.payload))
            except Exception:
                continue
        return records


# ---------------------------------------------------------------------------
# Module-level singleton — imported by the MCP recall tool and memory_writer
# ---------------------------------------------------------------------------
long_term_memory = LongTermMemory()


# ---------------------------------------------------------------------------
# LangGraph node function
# ---------------------------------------------------------------------------
def run_memory_writer(state: OpsAgentState) -> dict:
    """
    Memory writer node — writes the completed session as an IncidentRecord to Qdrant.
    Runs after every completed graph execution (action path or read-only path).
    """
    final_response = state.get("final_response")
    root_causes = state.get("root_causes", [])
    proposed_actions = state.get("proposed_actions", [])
    approved_actions = state.get("approved_actions", [])
    executed_actions = state.get("executed_actions", [])
    query = state.get("user_query", "")
    intent = state.get("intent", "diagnose")

    root_cause_strs = [rc.description for rc in root_causes]
    proposed_strs = [f"{a.action_type}: {a.justification}" for a in proposed_actions]
    approved_strs = [f"{a.action_type}: {a.justification}" for a in approved_actions]
    executed_strs = [f"{a.action_type} ({a.status})" for a in executed_actions]

    outcome_summary = (
        final_response.explanation
        if final_response and final_response.explanation
        else "No explanation generated."
    )

    embedding_text = IncidentRecord.build_embedding_text(
        query=query,
        root_causes=root_cause_strs,
        actions_proposed=proposed_strs,
    )

    record = IncidentRecord(
        query=query,
        intent=intent,
        root_causes=root_cause_strs,
        actions_proposed=proposed_strs,
        actions_approved=approved_strs,
        actions_executed=executed_strs,
        outcome_summary=outcome_summary,
        embedding_text=embedding_text,
    )

    try:
        long_term_memory.write_incident(record)
    except Exception as e:
        return {
            "tool_call_log": [{
                "node": "memory_writer",
                "status": "failed",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat(),
            }]
        }

    return {
        "tool_call_log": [{
            "node": "memory_writer",
            "status": "success",
            "incident_id": record.incident_id,
            "timestamp": datetime.utcnow().isoformat(),
        }]
    }


# ---------------------------------------------------------------------------
# LangGraph node function — recall
# ---------------------------------------------------------------------------
def run_recall_node(state: OpsAgentState) -> dict:
    """
    Recall node — skips all specialists.
    Searches Qdrant for past incidents similar to the user query and
    populates retrieved_memories in state for the output formatter.
    """
    query = state.get("user_query", "")
    records = long_term_memory.search_similar(query, top_k=5)

    incidents = [
        PastIncident(
            incident_id=r.incident_id,
            timestamp=r.timestamp,
            query=r.query,
            intent=r.intent,
            root_causes=r.root_causes,
            actions_proposed=r.actions_proposed,
            actions_executed=r.actions_executed,
            outcome_summary=r.outcome_summary,
        )
        for r in records
    ]

    return {
        "retrieved_memories": incidents,
        "tool_call_log": [{
            "node": "recall_node",
            "status": "success",
            "matches_found": len(incidents),
            "timestamp": datetime.utcnow().isoformat(),
        }],
    }


# ---------------------------------------------------------------------------
# Seed function — called once at startup to populate demo incidents
# ---------------------------------------------------------------------------
SYNTHETIC_INCIDENTS = [
    {
        "query": "Why did sales drop yesterday?",
        "intent": "diagnose",
        "root_causes": [
            "Laptop Pro 15 went out of stock at 11:30, causing 38% revenue drop",
            "Summer Tech Sale campaign was driving traffic to out-of-stock products",
        ],
        "actions_proposed": ["restock: Restock Laptop Pro 15 (50 units)", "pause_campaign: Pause Summer Tech Sale to stop wasted spend"],
        "actions_approved": ["restock: Restock Laptop Pro 15 (50 units)"],
        "actions_executed": ["restock (success)"],
        "outcome_summary": "Sales dropped 38% due to Laptop Pro 15 stockout coinciding with an active campaign. Restocked 50 units; revenue recovered within 2 days.",
    },
    {
        "query": "Why are customer complaints spiking?",
        "intent": "diagnose",
        "root_causes": [
            "Inventory system showed items as available after actual stockout",
            "28 complaints about orders being cancelled post-payment due to stock sync lag",
        ],
        "actions_proposed": ["create_ticket: Escalate inventory sync bug to engineering", "create_ticket: Issue apology vouchers to affected customers"],
        "actions_approved": ["create_ticket: Escalate inventory sync bug to engineering"],
        "actions_executed": ["create_ticket (success)"],
        "outcome_summary": "Complaint spike traced to inventory sync lag showing items as available after stockout. Engineering ticket raised; sync delay fixed within 4 hours.",
    },
    {
        "query": "Campaign ROAS is very low. Should we pause it?",
        "intent": "fix",
        "root_causes": [
            "Brand Awareness Q1 campaign spent budget on traffic to unavailable products",
            "ROAS dropped from 3.2 to 0.8 when landing products went out of stock",
        ],
        "actions_proposed": ["pause_campaign: Pause Brand Awareness Q1 campaign"],
        "actions_approved": ["pause_campaign: Pause Brand Awareness Q1 campaign"],
        "actions_executed": ["pause_campaign (success)"],
        "outcome_summary": "Campaign paused after ROAS fell to 0.8 due to landing products being out of stock. Saved $800 in wasted ad spend.",
    },
    {
        "query": "Summarize last week's business health",
        "intent": "summarize",
        "root_causes": [],
        "actions_proposed": [],
        "actions_approved": [],
        "actions_executed": [],
        "outcome_summary": "Last week: revenue down 12% vs prior week. Main drag was Tuesday stockout of top-3 SKUs. Campaign efficiency improved after pausing underperformers. Customer satisfaction stable at 4.1/5.",
    },
    {
        "query": "Did discounts help recover sales last time?",
        "intent": "recall",
        "root_causes": ["Previous sales drop caused by pricing error on Monitor 27\""],
        "actions_proposed": ["apply_discount: 15% discount on Monitor 27\" for 24 hours"],
        "actions_approved": ["apply_discount: 15% discount on Monitor 27\" for 24 hours"],
        "actions_executed": ["apply_discount (success)"],
        "outcome_summary": "15% discount on Monitor 27\" recovered 80% of lost revenue within 6 hours after pricing error was corrected. Discount was effective.",
    },
    {
        "query": "Which products should we restock immediately?",
        "intent": "diagnose",
        "root_causes": [
            "USB-C Hub stock below reorder threshold with high demand",
            "Mechanical Keyboard out of stock for 3 days",
        ],
        "actions_proposed": ["restock: USB-C Hub 40 units", "restock: Mechanical Keyboard 30 units"],
        "actions_approved": ["restock: USB-C Hub 40 units", "restock: Mechanical Keyboard 30 units"],
        "actions_executed": ["restock (success)", "restock (success)"],
        "outcome_summary": "Restocked USB-C Hub (40 units) and Mechanical Keyboard (30 units). Both products back in stock within 2 business days.",
    },
    {
        "query": "Why did the flash sale underperform?",
        "intent": "diagnose",
        "root_causes": [
            "Flash sale promotion did not run because target products were out of stock at scheduled time",
            "No fallback product list was configured for the promotion",
        ],
        "actions_proposed": ["create_ticket: Update promotion system to validate stock before launch"],
        "actions_approved": ["create_ticket: Update promotion system to validate stock before launch"],
        "actions_executed": ["create_ticket (success)"],
        "outcome_summary": "Flash sale generated zero revenue because target products were out of stock at 12:00. Engineering ticket raised to add pre-launch stock validation.",
    },
    {
        "query": "Are refund rates unusually high today?",
        "intent": "diagnose",
        "root_causes": [
            "Refund rate at 12.6%, up 88% vs prior week",
            "Top refund reason: item unavailable after order — caused by inventory sync issue",
        ],
        "actions_proposed": ["create_ticket: Escalate inventory sync issue (critical)"],
        "actions_approved": ["create_ticket: Escalate inventory sync issue (critical)"],
        "actions_executed": ["create_ticket (success)"],
        "outcome_summary": "High refund rate confirmed as symptom of inventory sync bug. Same root cause as complaint spike. Critical ticket raised.",
    },
    {
        "query": "Run a 10% discount on top 3 products",
        "intent": "fix",
        "root_causes": [],
        "actions_proposed": ["apply_discount: 10% on Laptop Pro 15, Wireless Mouse, USB-C Hub for 48 hours"],
        "actions_approved": ["apply_discount: 10% on Laptop Pro 15, Wireless Mouse, USB-C Hub for 48 hours"],
        "actions_executed": ["apply_discount (success)"],
        "outcome_summary": "10% discount applied to top 3 products for 48 hours. Conversion rate increased by 14% during discount window.",
    },
    {
        "query": "Did out-of-stock items have active campaigns?",
        "intent": "diagnose",
        "root_causes": [
            "Laptop Pro 15 was the main product in Summer Tech Sale campaign when it went out of stock",
            "Campaign continued to run and spend budget after stockout — wasting $1,240 in ad spend",
        ],
        "actions_proposed": ["pause_campaign: Pause Summer Tech Sale immediately", "restock: Laptop Pro 15 50 units"],
        "actions_approved": ["pause_campaign: Pause Summer Tech Sale immediately", "restock: Laptop Pro 15 50 units"],
        "actions_executed": ["pause_campaign (success)", "restock (success)"],
        "outcome_summary": "Campaign paused to stop $1,240/day wasted spend. Restock ordered. Revenue recovered after products back in stock.",
    },
    {
        "query": "What happened to sales in the East region?",
        "intent": "diagnose",
        "root_causes": [
            "East region revenue down 41% — highest regional drop",
            "East region had highest proportion of Laptop Pro 15 orders — most impacted by stockout",
        ],
        "actions_proposed": ["restock: Prioritize East region warehouse for Laptop Pro 15 restock"],
        "actions_approved": ["restock: Prioritize East region warehouse for Laptop Pro 15 restock"],
        "actions_executed": ["restock (success)"],
        "outcome_summary": "East region most impacted because it had highest Laptop Pro 15 demand. Regional restock prioritized; recovery expected within 3 days.",
    },
    {
        "query": "Create a support ticket for inventory sync issue",
        "intent": "fix",
        "root_causes": ["Inventory sync delay causing customers to purchase out-of-stock items"],
        "actions_proposed": ["create_ticket: Inventory sync bug — items show as available after stockout (critical)"],
        "actions_approved": ["create_ticket: Inventory sync bug — items show as available after stockout (critical)"],
        "actions_executed": ["create_ticket (success)"],
        "outcome_summary": "Critical support ticket raised for inventory sync bug. Assigned to engineering team. Fix deployed within 4 hours of ticket creation.",
    },
]


def seed_memory(force: bool = False) -> int:
    """
    Seeds the Qdrant collection with synthetic past incidents.

    Args:
        force: if True, re-seeds even if collection already has data.
    Returns:
        number of incidents written.
    """
    client = long_term_memory._client
    collection = long_term_memory._collection

    if not force:
        count_result = client.count(collection_name=collection)
        if count_result.count > 0:
            return 0  # Already seeded

    written = 0
    for raw in SYNTHETIC_INCIDENTS:
        embedding_text = IncidentRecord.build_embedding_text(
            query=raw["query"],
            root_causes=raw["root_causes"],
            actions_proposed=raw["actions_proposed"],
        )
        record = IncidentRecord(
            query=raw["query"],
            intent=raw["intent"],
            root_causes=raw["root_causes"],
            actions_proposed=raw["actions_proposed"],
            actions_approved=raw["actions_approved"],
            actions_executed=raw["actions_executed"],
            outcome_summary=raw["outcome_summary"],
            embedding_text=embedding_text,
        )
        long_term_memory.write_incident(record)
        written += 1

    return written








