# D14 — Disagreement matrix

**The question is "why did humans disagree?", not "who was right?"** So no item
below is scored. Where the applied label and the D12 rule diverge, both are
recorded and the divergence is the datum.

**One reviewer exists.** So the disagreements available are of two kinds, and
both are real:

1. **Internal** — the same reviewer treating structurally identical items
   differently.
2. **Between reviewer and specification** — items where D12's rule, written from
   the same labels, still fails to reproduce them.

A between-reviewer κ needs the second rater (D13). Everything here is available
without one.

---

## Why the reviewer appeared to disagree with themselves — four causes, measured

| cause | n | what it actually was |
|---|---|---|
| **Confounded rejection** | 8 | Rejected for `answer_leakage`; the premise was never at issue and in two cases was accepted elsewhere |
| **Detector noise** | 7 | The "assumes something" pattern matched an abstraction (*the success*, *the work*) or the claim's own word in another inflection (*the re-engineering*) |
| **Sub-class conflation** | 4 | `invented_event` on an INCIDENT probe is the probe working; on DECISION it is a presupposition. Same surface, opposite meaning |
| **Genuine collision** | **2** | Same premise, same probe level, opposite verdict |

**Phase 3 reported 6 accept / 7 reject on "the same pattern" and inferred an
unstable category. Two of those thirteen are genuine.** The rest are three
distinct measurement errors in how I selected the comparison set — I filtered on
the pattern and read the verdict without reading the reason.

### The two genuine collisions

**r0090 / r0093** — the strongest evidence either way in the whole study.

| | claim | question | verdict |
|---|---|---|---|
| r0090 | Managed a team of 35 agents across 4 pods | *"What steps did you take in **the system** for daily attendance tracking?"* | **accept** |
| r0093 | Owned attrition, engagement surveys and the onboarding programme | *"What specific actions did you take in **the system** to manage attrition?"* | **reject** |

Identical words, identical probe level, opposite verdicts. **Under D12 rule 3
both resolve, and in the direction the reviewer chose** — 35 people's attendance
is necessarily recorded somewhere; attrition is an outcome, not a task performed
inside a system. So this reads as an *unstated* rule the reviewer was applying,
not as noise. **That is a hypothesis, and it is exactly what D13 tests.**

**r0052 / r0072** — same claim, same tool, opposite verdicts. r0072 asks what you
did *in* the tools; r0052 asks why you prioritised *updating* them, which asserts
an updating task as well as a tool. Under D12 both resolve as the reviewer had
them — but r0052 rejects on its **second** premise, while the reviewer's note
blames the tool. **Right answer, different reason.** Reviewer 2 should see both.

### The confound that mattered most

**r0002 / r0054 was reported in Phase 3 as a contradiction and is not one.**

| | question | reviewer's note |
|---|---|---|
| r0002 | *"What specific actions did you take in **your CRM** each day…"* | Relevant operational probe → **accept** |
| r0054 | *"How did you use **your CRM system** daily to manage your $1.2M ARR quota?"* | **"Hands back the exact $1.2M ARR figure"** → reject |

Both assume a CRM. The reviewer objected to neither. **The CRM premise was
accepted twice.** Reading verdicts instead of reasons turned an agreement into a
contradiction — and it was the headline example in Phase 3 finding 4.

---

## Every classified item

`alternate label` is what D12's rule yields, where it differs from the applied
label or explains it.

| item | category | applied | claim | question | reviewer's justification | alternate under D12 |
|---|---|---|---|---|---|---|
| `r0001` | `invented_tool` | reject | Improved CSAT from 78% to 92% in four quarte | What specific actions did you take in Zendesk to improve C | Assumes Zendesk, which the claim never establishes. | — |
| `r0002` | `invented_tool` | accept | Carrying a quota of $1.2M ARR. | What specific actions did you take in your CRM each day to | Relevant operational probe into how pipeline work was ma | none — premise entailed by a quota |
| `r0003` | `invented_tool` | reject | Grew activation from 41% to 63% over two qua | What specific actions did you take in the product analytic | Assumes a product analytics dashboard not stated in the  | ACCEPT — a PM who moved activation had analytics |
| `r0009` | `invented_outcome` | reject | Coached four inside sales reps on closing te | How did you capture the jump in conversion rates from 15%  | Invents a 15% to 25% conversion-rate outcome not in the  | — |
| `r0010` | `invented_event` | accept | Raised activation from 34% to 46% by rebuild | Describe a specific time during the rebuild when you faced | Specific incident probe aligned with the onboarding rebu | none — indefinite solicitation |
| `r0012` | `invented_outcome` | reject | Led campus hiring, sourcing, interview coord | What impact did the campus hiring have on your team's over | Invents team-performance metrics as the outcome of campu | — |
| `r0017` | `invented_tool` | accept | Owned the recruiting funnel from sourcing th | What specific tasks did you perform in the recruiting soft | Relevant operational probe about the recruiting workflow | none — premise entailed by owning a funnel |
| `r0018` | `invented_event` | reject | Ran daily stand-ups, tracked deliverables ag | What factors did you consider when deciding how to address | Introduces technical delays that are not in the claim. | — |
| `r0025` | `invented_event` | reject | Handled vendor coordination, invoice follow- | What factors did you consider when deciding on the tempora | Introduces a temporary vendor-delay solution not stated  | — |
| `r0031` | `invented_event` | accept | Improved CSAT from 78% to 92% in four quarte | Describe a time when the new escalation workflow failed an | Specific incident probe directly tied to the escalation  | none — indefinite solicitation |
| `r0032` | `invented_artefact` | reject | MBA graduate seeking opportunities with a gr | What criteria did you use to decide which ideas to combine | Assumes a marketing plan absent from the claim. | — |
| `r0033` | `invented_outcome` | reject | Managed a team of 45 agents and consistently | How would you apply a focus on quality to achieve a 30% CS | Transfer question invents a 30% CSAT target not present  | — |
| `r0036` | `invented_tool` | reject | Reduced reopen rate by a third. | What specific steps did you take each day to monitor and a | Assumes macros that the claim never mentions. | — |
| `r0037` | `invented_tool` | reject | Ran 40 user interviews to find the top three | What specific actions did you take in the transcription to | Assumes a transcription tool not stated in the claim. | — |
| `r0041` | `invented_outcome` | reject | Coached four inside sales reps on closing te | How did you ensure the increase in conversion rate was due | Assumes a conversion-rate increase that the claim never  | — |
| `r0047` | `invented_event` | accept | Handled vendor coordination, invoice follow- | Describe a specific time when a vendor issue delayed your  | Specific incident probe directly connected to vendor coo | none — indefinite solicitation |
| `r0052` | `invented_tool` | reject | Reacted quickly to shifting priorities and s | What factors led you to prioritize updating project manage | Assumes project-management tools that the claim never es | REJECT on 'updating', not on the tool |
| `r0056` | `invented_outcome` | reject | Owned attrition, engagement surveys and the  | How did you measure the 20% improvement in employee satisf | Invents a 20% employee-satisfaction improvement not in t | — |
| `r0061` | `invented_event` | accept | Managed a team of 20 and improved process ef | What criteria did you use to decide which tasks to priorit | Relevant decision probe for prioritization under pressur | REJECT — definite reference to an unstated week |
| `r0072` | `invented_tool` | accept | Reacted quickly to shifting priorities and s | What specific actions did you take in the project manageme | Relevant operational probe for the transition work. | none — premise entailed; r0052's second premise is not |
| `r0090` | `invented_tool` | accept | Managed a team of 35 agents across 4 pods wi | What steps did you take in the system for daily attendance | Useful operational probe for attendance tracking. | none — 35 agents entail a record somewhere |
| `r0093` | `invented_tool` | reject | Owned attrition, engagement surveys and the  | What specific actions did you take in the system to manage | Assumes a system for attrition management that the claim | REJECT — attrition is an outcome, not a system-mediated task |
| `r0100` | `invented_condition` | reject | Led the escalation desk for a SaaS product. | Describe a specific incident where a P1 issue wasn't resol | Introduces a two-hour resolution threshold absent from t | — |

## Where D12 fails to reproduce the reviewer

Two items, and both are in the κ sample:

- **r0003** — D12 rule 3 says accept (*a PM who moved activation two quarters had
  analytics*); the reviewer rejected. Either "entailment" is being read more
  strictly than I wrote it, or the item is an error.
- **r0061** — D12's article test says reject (*"**the** high-pressure week"*,
  definite, unstated); the reviewer accepted. Either definiteness is a heuristic
  rather than a test, or the item is an error.

**A rule that reproduced 100% of the labels it was written from would be
evidence of nothing.** These two are where it can actually be tested.

## So: why did humans disagree?

On the evidence available, **mostly they did not.** Of thirteen apparent
disagreements, eight were about a different defect entirely, three were an
artefact of how I selected the comparison set, and two are real — and both of the
real ones are resolved, in the direction the reviewer chose, by a rule nobody had
written down.

**The most likely explanation is that the reviewer was applying entailment
consistently while the Phase 3 analysis was testing them against a cruder
predicate — "is it in the claim?" — that they were never using.**

That is a hypothesis fitted to the data it explains, so it is worth exactly
nothing until a second reviewer, holding D12 and not the labels, either
reproduces those judgements or does not.
