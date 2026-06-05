# Multi-Agent Root Cause Analysis Architecture

```text
                            ┌──────────────────────────────┐
                            │          USER (Ops)          │
                            │   "Why did sales drop?"      │
                            └──────────────┬───────────────┘
                                           │
                                           ▼

                    ┌─────────────────────────────────────┐
                    │       ORCHESTRATOR AGENT            │
                    │ Intent Parsing • Planning • Routing │
                    │                                     │
                    │ • Decomposes query into sub-tasks   │
                    │ • Selects specialist agents         │
                    │ • Maintains conversation state      │
                    └───────┬─────────┬─────────┬─────────┘
                            │         │         │
           ┌────────────────┘         │         └──────────────┐
           ▼                          ▼                        ▼

┌──────────────────┐      ┌──────────────────┐      ┌──────────────────┐
│ SALES / REVENUE  │      │ INVENTORY AGENT  │      │ CUSTOMER AGENT   │
│ AGENT            │      │                  │      │                  │
│                  │      │ • Stock levels   │      │ • Complaints     │
│ • Revenue        │      │ • OOS signals    │      │ • Refunds        │
│ • Orders         │      │ • Restocking     │      │ • Reviews        │
│ • AOV            │      │                  │      │                  │
│ • Regions        │      └────────┬─────────┘      └────────┬─────────┘
│ • Anomalies      │               │                         │
└────────┬─────────┘               │                         │
         │                         │                         │
         ▼                         ▼                         ▼

                     ┌──────────────────────────┐
                     │     MARKETING AGENT      │
                     │                          │
                     │ • Campaign performance   │
                     │ • Acquisition channels   │
                     │ • Promotions             │
                     └───────────┬──────────────┘
                                 │
                                 ▼

┌──────────────────────────────────────────────────────────────┐
│                    TOOL LAYER (MCP Style)                    │
├──────────────────────────────────────────────────────────────┤
│ MetricsAPI │ InventoryAPI │ SupportAPI │ CampaignAPI │       │
│ ActionAPI                                                 │
└───────────────────────────┬──────────────────────────────────┘
                            │
                            ▼

                 (Findings flow back upward)

                            ▼

┌──────────────────────────────────────────────────────────────┐
│              CORRELATION / SYNTHESIS AGENT                  │
│                                                              │
│ • Merges findings across domains                             │
│ • Performs cross-domain root-cause analysis                  │
│ • Ranks contributing factors                                 │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼

┌──────────────────────────────────────────────────────────────┐
│                 REFLECTION / CRITIC AGENT                   │
│                                                              │
│ • Identifies missing evidence                                │
│ • Detects contradictions                                     │
│ • Requests re-investigation when confidence is low           │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼

┌──────────────────────────────────────────────────────────────┐
│              ACTION / RECOMMENDATION AGENT                  │
│                                                              │
│ • Generates corrective actions                               │
│ • Explains rationale and expected impact                     │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼

┌──────────────────────────────────────────────────────────────┐
│                  HUMAN-IN-THE-LOOP GATE                     │
│                                                              │
│ Approve • Reject • Modify                                    │
│ Approval required for impactful actions                      │
└──────────────────────────────┬───────────────────────────────┘
                               │
                               ▼

┌──────────────────────────────────────────────────────────────┐
│                 EXECUTION (via ActionAPI)                   │
└──────────────────────────────────────────────────────────────┘
```

## Shared Infrastructure

### Memory Layer
- **Short-Term Memory**
  - Conversation context
  - Scratchpad state

- **Long-Term Memory**
  - Vector database
  - Historical incidents
  - Outcomes and resolutions

### Observability
- Distributed tracing
- Logs
- Decision audit trail
- Agent execution metrics