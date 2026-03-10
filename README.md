# edon · [![PyPI](https://img.shields.io/pypi/v/edon)](https://pypi.org/project/edon) [![Python](https://img.shields.io/pypi/pyversions/edon)](https://pypi.org/project/edon) [![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Runtime governance for AI agents.** Evaluate, enforce, and audit every action your agent takes — before it executes.

```python
pip install edon
```

---

## What is EDON?

EDON sits between your agent's decision and execution. Before a tool runs, EDON evaluates it against your policy and returns a verdict:

- **ALLOW** → proceed
- **BLOCK** → action stopped, reason logged
- **HUMAN_REQUIRED** → escalate to a human before continuing
- **DEGRADE** → automatically substitute a safer alternative

Every decision is written to a tamper-evident audit trail. Compliance reports map to EU AI Act, NIST AI RMF, ISO 42001, and SOC2.

---

## Quickstart (3 minutes)

### 1. Get an API key

Sign up at [edoncore.com](https://edoncore.com) → copy your API key.

### 2. Install

```bash
pip install edon
```

### 3. Govern your first function

```python
import edon

edon.configure(api_key="your-key")

@edon.govern(action_type="email.send")
def send_email(to: str, subject: str, body: str) -> None:
    # This only runs if EDON allows it
    smtp_send(to, subject, body)

# If policy blocks this action, EdonBlockedError is raised
# and the function never executes
send_email("all@company.com", "Announcement", "...")
```

### 4. Use the client directly

```python
from edon import EdonClient

client = EdonClient(api_key="your-key")

decision = client.evaluate(
    action_type="email.send",
    action_payload={"to": "user@example.com", "subject": "Hello"},
    agent_id="my-agent",
)

if decision.allowed:
    send_email(...)
elif decision.blocked:
    print(f"Blocked: {decision.decision_reason}")
elif decision.needs_human:
    print(f"Human approval required: {decision.escalation_question}")
```

---

## Framework Integrations

### LangChain

```bash
pip install 'edon[langchain]'
```

```python
from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_community.tools import DuckDuckGoSearchRun, GmailSendMessage
from edon.integrations.langchain import EdonGuard

# Wrap your tools — same interface, now governed
tools = EdonGuard.wrap_tools(
    tools=[DuckDuckGoSearchRun(), GmailSendMessage()],
    api_key="your-edon-key",
    agent_id="research-agent",
)

agent = create_tool_calling_agent(llm, tools, prompt)
executor = AgentExecutor(agent=agent, tools=tools)
executor.invoke({"input": "Search for AI news and email the summary to the team"})
# DuckDuckGo search → ALLOW ✓
# Gmail send → evaluated against policy before sending
```

**Audit-only mode** (non-blocking, pure observability):

```python
from edon.integrations.langchain import EdonCallbackHandler

handler = EdonCallbackHandler(api_key="your-key", agent_id="my-agent", verbose=True)
executor = AgentExecutor(agent=agent, tools=tools, callbacks=[handler])
# All tool calls logged to EDON — no blocking
```

---

### OpenAI Agents SDK

```bash
pip install 'edon[openai]'
```

```python
from agents import Agent, Runner, function_tool
from edon.integrations.openai_agents import EdonToolGuard

@function_tool
def send_email(to: str, subject: str, body: str) -> str:
    """Send an email."""
    ...

@function_tool
def delete_records(table: str, condition: str) -> str:
    """Delete database records."""
    ...

# Govern before passing to Agent
governed = EdonToolGuard.wrap(
    tools=[send_email, delete_records],
    api_key="your-edon-key",
    agent_id="my-openai-agent",
)

agent = Agent(name="Assistant", tools=governed)
result = Runner.run_sync(agent, "Delete all test records and notify the team")
# delete_records → likely BLOCKED (database.delete outside policy scope)
# send_email → evaluated by policy
```

---

### CrewAI

```bash
pip install 'edon[crewai]'
```

```python
from crewai import Agent, Task, Crew
from crewai.tools import tool
from edon.integrations.crewai import EdonCrewGuard

@tool("Search the web")
def web_search(query: str) -> str:
    """Search for current information."""
    ...

@tool("Send email report")
def send_report(to: str, content: str) -> str:
    """Send a research report via email."""
    ...

# Govern all crew tools
governed = EdonCrewGuard.wrap_tools(
    tools=[web_search, send_report],
    api_key="your-edon-key",
    agent_id="research-crew",
)

researcher = Agent(
    role="Research Analyst",
    goal="Find and summarize key information",
    tools=governed,
)

crew = Crew(agents=[researcher], tasks=[...])
crew.kickoff()
```

---

### Raw HTTP (any language/framework)

```bash
curl -X POST https://edon-gateway.fly.dev/v1/action \
  -H "X-EDON-TOKEN: your-key" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "my-agent",
    "action_type": "email.send",
    "action_payload": {"to": "user@example.com", "subject": "Hello"},
    "timestamp": "2026-03-10T12:00:00Z",
    "context": {}
  }'
```

Response:
```json
{
  "action_id": "dec-abc123",
  "decision": "ALLOW",
  "decision_reason": "Action approved: email.send within scope, constraints satisfied.",
  "policy_version": "1.0.0",
  "processing_latency_ms": 12,
  "reason_code": "APPROVED"
}
```

---

## CLI

```bash
# Install
pip install edon
export EDON_API_KEY=your-key

# Check gateway health
edon ping

# Evaluate an action
edon evaluate email.send --payload '{"to": "user@example.com", "subject": "Hello"}'

# View recent audit events
edon audit --limit 20

# View your policy rules
edon policy

# View available policy packs
edon packs
```

---

## Decisions & Verdicts

| Verdict | Meaning | Agent action |
|---|---|---|
| `ALLOW` | Action is within policy | Proceed normally |
| `BLOCK` | Action violates policy | Do not execute — log reason |
| `HUMAN_REQUIRED` | Needs human approval | Pause and escalate |
| `DEGRADE` | Use safer alternative | Execute `safe_alternative` instead |
| `PAUSE` | Temporarily halted | Retry after delay |

---

## Policy Packs

Pre-built governance presets for common agent types:

| Pack | Use Case | Risk Level |
|---|---|---|
| `casual_user` | Everyday personal agents | LOW |
| `market_analyst` | Financial research agents | LOW |
| `founder_mode` | Power users, startup ops | MEDIUM |
| `ops_commander` | Workflow automation | MEDIUM |
| `helpdesk` | Customer support agents | LOW |
| `autonomy_mode` | Fully autonomous co-pilots | HIGH |

Apply a pack in the EDON console or via API — your agents pick up the new policy instantly.

---

## Handling Blocked Actions

```python
from edon import EdonClient, EdonBlockedError, EdonEscalatedError

client = EdonClient(api_key="your-key", raise_on_block=True)

try:
    decision = client.evaluate("shell.exec", {"command": "rm -rf /"})
except EdonBlockedError as e:
    print(f"Blocked: {e.reason}")
    print(f"Code: {e.reason_code}")      # e.g. "OUT_OF_SCOPE"
    print(f"Audit ID: {e.action_id}")    # for the audit trail
except EdonEscalatedError as e:
    print(f"Needs approval: {e.question}")
    # Send e.question to your human review queue
    # Resolve via EDON console or API
```

---

## Async Support

```python
import asyncio
from edon import AsyncEdonClient

async def main():
    async with AsyncEdonClient(api_key="your-key") as client:
        decision = await client.evaluate(
            "email.send",
            {"to": "user@example.com", "subject": "Hello"},
            agent_id="async-agent",
        )
        print(decision.decision)

asyncio.run(main())
```

---

## Environment Variables

| Variable | Description |
|---|---|
| `EDON_API_KEY` | Your EDON API key |
| `EDON_BASE_URL` | Gateway URL (default: `https://edon-gateway.fly.dev`) |
| `EDON_AGENT_ID` | Default agent identifier |
| `EDON_INTENT_ID` | Default intent contract ID |

---

## Self-Hosting

EDON Gateway is open for self-deployment:

```bash
docker run -p 8000:8000 \
  -e EDON_API_TOKEN=your-token \
  ghcr.io/edoncore/edon-gateway:latest
```

Then point the SDK at your instance:

```python
client = EdonClient(api_key="your-token", base_url="http://localhost:8000")
```

---

## Links

- **Console**: [edoncore.com/console](https://edoncore.com/console)
- **Docs**: [docs.edoncore.com](https://docs.edoncore.com)
- **Issues**: [github.com/edoncore/edon-python/issues](https://github.com/edoncore/edon-python/issues)
- **Email**: [sdk@edoncore.com](mailto:sdk@edoncore.com)

---

## License

MIT © EDON Core
