# ProofScreen Questioning Philosophy

**Status: design document. Interview design only — no implementation, no code.**
Written from first principles, deliberately ignoring how questions are
currently generated.

---

## 0. What we are actually doing

A resume is a set of **claims made by an interested party about their own
past**. ProofScreen exists to answer one question about each claim:

> Did this person actually do this, or did they write it down?

That is a *forensic* question, not an *educational* one. It has three
consequences that govern everything below.

**We are not testing knowledge.** Knowledge is now free. Any candidate with a
phone can produce a textbook-perfect answer to "explain cache invalidation" or
"what is AHT". A question that knowledge can answer measures access to
knowledge, not authorship of the work.

**We are not testing ability.** Ability is what the on-site loop, the take-home
and the reference check are for. We sit before all of them. Our job is to tell
the recruiter which resumes are worth spending those hours on.

**We are testing authorship.** The person who did the work carries a residue
the person who copied it does not: incidental, peripheral, low-glamour detail
that is **cheap to recall and expensive to invent**. Who they had to call. What
they had to leave out. Which part didn't improve. What the number was measured
against. Every good ProofScreen question is an attempt to make that residue
surface in ninety seconds of typing on a phone.

### The one test that decides whether a question is any good

> **The impostor-parity test.** Imagine two people answering: the person who
> genuinely did the work, and an articulate stranger who has read the resume
> and nothing else. If both produce an equally good answer, the question is
> worthless — delete it. A question earns its place only where the two answers
> **diverge**.

Every "bad question" below fails impostor-parity. Every "good question" below
is chosen because a stranger's most plausible answer is visibly different from
a practitioner's ordinary one.

### The constraint that shapes the wording

The channel is WhatsApp. The answer is typed with a thumb, probably between
other things, in two to five sentences. So a good question is not merely
discriminating — it must be **cheap for an honest person and expensive for a
dishonest one**. If a question is hard for both, we have built a quiz with
extra steps and we will lose good candidates to fatigue.

### The four roles a question plays

| Role | Probe levels | Job |
|---|---|---|
| **Primary** | VALIDATION / OPERATIONAL | Establish what the work actually was, in the candidate's own operating vocabulary. Ground truth for everything after. |
| **Follow-up** | INCIDENT / DECISION | Move off the headline into the periphery — the exception, the friction, the thing that broke, the option rejected. |
| **Cross question** | OUTCOME + consistency | Test coherence between two things they have *already said*. Its purpose is not new information; it is load on existing statements. |
| **Transfer** | TRANSFER | Rebuild a situation from their own claims, change one variable, and ask them to operate. A memorised resume can be recited. It cannot be transferred. |

The four are a sequence, not a menu. Cross questions are meaningless before
there is something to cross. Transfer is meaningless before we know what world
the candidate lives in.

---

# Family designs

Each entry: the claim, the question that looks reasonable and is not, the
four-question sequence that works, why it produces evidence, and which of the
six dimensions it reads.

---

## 1. Software Engineering

**Claim**
> "Reduced API p95 latency from 1.2s to 300ms by introducing Redis caching."

### BAD question
> *"What's the difference between Redis and Memcached, and how would you handle
> cache invalidation?"*

Why it fails: it is a textbook prompt with a textbook answer. It is answered
better by someone who revised last night than by the engineer who shipped this
two years ago and has forgotten the comparison table. Impostor-parity is total,
and the failure mode is inverted — it *punishes* the real author.

Also bad in a subtler way: *"Why did you choose Redis?"* — this invites a
rehearsed justification and supplies its own answer shape. The candidate need
only agree with the premise fluently.

### GOOD sequence

**Primary**
> "Before the cache went in, what was actually slow? Name the endpoint, and tell
> me how you established it was that one and not something else."

**Follow-up**
> "What did you decide *not* to cache, and what made it not cacheable?"

**Cross question**
> "You said p95 went from 1.2s to 300ms. What happened to p99 over the same
> period, and what did the cache do to your error rate in the first week after
> release?"

**Transfer question**
> "Same endpoint, ten times the traffic next month, and hit rate falls to 40%.
> What breaks first, and what would you look at before adding a second cache?"

### Why this produces evidence
The headline — *Redis, p95, 300ms* — is the rehearsed part and we spend zero
questions on it. Finding the bottleneck is the part that was actually hard and
is never on a resume; a fabricator says "we profiled it," an author names a
tool, a dashboard, or a complaint from a specific team. **Every real cache has
an exclusion list** (anything user-specific, anything financial, anything with a
write-through problem), and it is remembered because it was argued about.
The cross question attacks the seam between two percentiles: p95 improving while
p99 does something ugly is what actually happens, and a candidate who reports
that everything got better in every dimension has told us the number is
decoration. The transfer question cannot be answered from the resume at all —
it requires knowing what this system is made of.

### Dimensions revealed
`PROCESS` (how the bottleneck was found and shipped) · `CAUSAL_REASONING`
(cache → hit rate → tail latency → error rate) · `METRIC_OWNERSHIP` (p95 vs p99
vs mean; do they know which one they quoted) · `SPECIFICITY` (endpoint names,
week of release) · `TOOL_FAMILIARITY` (usage, not certification) ·
`AUTHENTICITY` (the bad first week).

---

## 2. Data / AI

**Claim**
> "Built a churn prediction model with 87% accuracy that reduced churn by 12%."

### BAD question
> *"Explain the difference between precision and recall, and when you'd optimise
> for each."*

Why it fails: pure definition recall, freely available, and — worse — the
candidate who answers it beautifully has told us nothing about whether they ever
had a labelled dataset in their hands.

### GOOD sequence

**Primary**
> "What counted as 'churned' in your labels — which event, and how long after it
> did an account become churned?"

**Follow-up**
> "Which feature turned out to be leaking the answer, and how did you notice?"

**Cross question**
> "87% accuracy — what percentage of accounts actually churned in that dataset?
> And of your two numbers, which one was measured on a holdout and which one was
> measured in production?"

**Transfer question**
> "Retention has 50 CSM-hours a month and your model flags 500 accounts. What
> changes — the model, the threshold, or the output?"

### Why this produces evidence
**Label definition is the entire job and it is never on the resume.** Anyone who
built a churn model spent a week arguing about whether 60 or 90 days of
inactivity counts, whether downgrade is churn, what happens to seasonal
accounts. Someone who did not build one answers "customers who left," which is
not a definition. The leakage question works because essentially every real
model has had one and finding it is a memorable, slightly embarrassing event.
The cross question is the sharpest in this family: **87% accuracy is unremarkable
or impossible depending entirely on the base rate**, and asking for the base rate
tests whether the headline number ever meant anything to them. It also separates
an offline metric from a business outcome — two numbers that a fabricator states
in the same breath and a practitioner knows were measured months apart by
different people.

### Dimensions revealed
`METRIC_OWNERSHIP` (dominant here — accuracy against base rate, offline vs
online) · `PROCESS` (labelling, validation, deployment) · `CAUSAL_REASONING`
(did the model cause the 12%, and how would they know) · `SPECIFICITY` ·
`AUTHENTICITY` (the leakage incident).

---

## 3. Sales

**Claim**
> "Achieved 128% of a ₹4Cr annual quota selling enterprise SaaS."

### BAD question
> *"What sales methodology do you follow, and how do you handle objections?"*

Why it fails catastrophically in this family: it rewards exactly the trait we
must not score. A confident, fluent answer naming MEDDIC or SPIN is free, is
coachable in an afternoon, and correlates with polish rather than performance.
This question measures presentation, which is a bias vector and is out of bounds.

### GOOD sequence

**Primary**
> "Take your biggest deal last year. Who signed it — what was their title — and
> who else inside that company had to say yes before they could?"

**Follow-up**
> "What was the objection that nearly killed that deal, and what specifically
> changed their mind?"

**Cross question**
> "128% of ₹4Cr — how many closed deals made up that number, and what was the
> average time from first meeting to signature? Was the quota new business only,
> or did renewals count toward it?"

**Transfer question**
> "Same deal, but your champion resigns halfway through the cycle. What do you
> do in the first week after you find out?"

### Why this produces evidence
The **shape of the buying committee** is unfakeable texture: someone who closed
an enterprise deal knows there was a procurement person, a security review, a
budget holder who never came to a call, and they say so without effort. A
stranger says "the CTO." The cross question is arithmetic under load — quota,
deal count and average deal size must multiply, and cycle length must fit inside
the year. **Fabricated sales numbers routinely fail to multiply**, and this is
one of the few places in the product where a claim can be falsified rather than
merely doubted. The renewals question matters because quota attainment is
defined differently at every company and a real seller knows precisely which
definition theirs used, because it determined their commission.

### Dimensions revealed
`SPECIFICITY` (titles, committee, dates) · `METRIC_OWNERSHIP` (quota
composition and attainment arithmetic) · `PROCESS` (the deal's actual stages) ·
`CAUSAL_REASONING` (what moved the objection) · `AUTHENTICITY`.

**Explicitly not scored:** persuasiveness, charisma, polish, or how good the
answer sounds. A terse answer with a real procurement blocker in it beats a
fluent one without.

---

## 4. Customer Support

**Claim**
> "Handled 60+ tickets a day with 4.7/5 CSAT."

### BAD question
> *"How do you deal with an angry customer?"*

Why it fails: it is a role-play prompt whose best answer is a script — empathise,
acknowledge, resolve, follow up. It is trained into every support hire in week
one and produces identical answers from the excellent and the absent.

### GOOD sequence

**Primary**
> "What were the top three reasons customers wrote in last month, and which of
> the three took longest to close?"

**Follow-up**
> "Tell me about one ticket you couldn't solve inside your own team. Who did you
> have to go to, and what did you tell the customer while you waited?"

**Cross question**
> "The 4.7 — was it surveyed on every ticket or only on resolved ones, and roughly
> what share of customers responded? Which type of ticket pulled that score down?"

**Transfer question**
> "The refund policy changed this morning and nobody told support, so your saved
> replies are now wrong. It's 11am with 30 tickets in queue. What do you do
> first?"

### Why this produces evidence
"Top three contact reasons" is a question only someone who watched a queue can
answer, and they answer it instantly and boringly — password resets, billing
mismatches, delivery status. It is free for the author and requires invention
from anyone else. The escalation question captures the part of support that is
genuinely difficult and never on a resume: **the handoff and the holding
message**. The cross question goes at CSAT methodology, the biggest tell in this
family — survey population and response rate are the difference between 4.7
meaning something and meaning nothing, and anyone who was measured on it has
had that argument with their manager. The transfer question puts them under a
real operational conflict (queue vs correctness) with no textbook answer.

### Dimensions revealed
`PROCESS` (queue, escalation, holding) · `METRIC_OWNERSHIP` (CSAT population,
response rate) · `SPECIFICITY` (contact reasons, volumes) · `TOOL_FAMILIARITY`
(macros, queues, views — as usage, not certification) · `AUTHENTICITY`.

---

## 5. BPO

Distinct from Customer Support: the subject is not the ticket, it is **the metric
regime and the people held to it** — AHT, occupancy, shrinkage, adherence, SLA,
quality — and usually a team.

**Claim**
> "Team Lead for 18 agents; reduced AHT from 480s to 310s while holding CSAT."

### BAD question
> *"What is AHT and why does it matter?"*

Why it fails: it is a definition, and a definition is a search result. Equally
bad: *"How do you motivate an underperforming agent?"* — a management-cliché
generator.

### GOOD sequence

**Primary**
> "Where did those 170 seconds come from? Split the old handle time into talk,
> hold and wrap, and tell me which part you actually moved."

**Follow-up**
> "Which of your 18 didn't improve, and what did you find when you listened to
> their calls?"

**Cross question**
> "When AHT came down, what happened to repeat contacts and to your quality
> scores? Was that your number to watch, or QA's?"

**Transfer question**
> "The client moves SLA from 80/20 to 90/15 with no extra headcount — same 18
> agents. What do you change, and what do you tell the client you will lose?"

### Why this produces evidence
Decomposing handle time is the single best question in this family: a real team
lead answers in the native units of the job (*"wrap was 90 seconds because they
were typing the disposition twice"*) and the improvement always came from one
specific component, never uniformly. **The cross question hunts for the trade-off
that must exist.** Cutting AHT by 35% without repeat contacts moving is very
rarely true, and a candidate who reports that everything improved at once has
told us they are reciting an outcome rather than remembering a quarter. The
transfer question is the tell for whether they ever owned a service level:
a real lead immediately says what they will sacrifice, because they have had to
say it to a client before.

### Dimensions revealed
`METRIC_OWNERSHIP` (dominant — AHT composition, quality vs efficiency
trade-off) · `PROCESS` (coaching, monitoring, rostering) · `CAUSAL_REASONING`
(what change produced which movement) · `SPECIFICITY` (components, seconds,
headcount) · `AUTHENTICITY` (the agent who didn't improve).

---

## 6. Banking Operations

**Claim**
> "Owned daily reconciliation and settlement for a ₹200Cr book; reduced breaks by
> 40%; ensured regulatory compliance."

### BAD question
> *"What is a NOSTRO account?"* / *"Explain KYC requirements."*

Why it fails: regulatory trivia is the most memorisable content in any of these
eight families, and it is exactly what a candidate revises before an interview.
It measures preparation.

### GOOD sequence

**Primary**
> "Walk me through the last time a break didn't clear before cut-off. What time
> did you notice, who did you have to call, and by when?"

**Follow-up**
> "What was the most common cause of breaks in your book, and what did you change
> so that cause stopped producing them?"

**Cross question**
> "40% fewer breaks — over what period, and counted how: breaks raised, or breaks
> still open past T+1? Who signed off on that number besides you?"

**Transfer question**
> "The upstream feed lands two hours late on a quarter-end day and the cut-off
> doesn't move. What's your order of operations, and what do you escalate first?"

### Why this produces evidence
Operations runs on **clocks and controls**, and both leave sharp residue. A real
ops person answers the primary question in times and names — *"11:40, we called
the custodian, cut-off was 2pm"* — because the deadline is the emotional centre
of the job. A stranger describes a process. The cross question does two things
at once: it asks how the improvement was *counted* (breaks raised and breaks
ageing are entirely different metrics that move differently), and it asks **who
approved it**, because maker-checker means an ops person never owns a number
alone. A candidate with no approver in their answer has described a job that
does not exist in a bank. The transfer question tests whether they can
prioritise under an immovable deadline, which is the whole competence.

### Dimensions revealed
`PROCESS` (controls, maker-checker, escalation path) · `SPECIFICITY` (cut-off
times, T+1, counterparties, systems) · `METRIC_OWNERSHIP` (what was counted and
by whom) · `CAUSAL_REASONING` (root cause → control → break rate) ·
`AUTHENTICITY`.

---

## 7. Recruiting

**Claim**
> "Closed 45 technical roles in a year; cut time-to-hire from 45 days to 28."

### BAD question
> *"What's your sourcing strategy?"* / *"What makes a good job description?"*

Why it fails: both are essay prompts about the profession rather than about this
person's year. Both have well-known correct answers.

### GOOD sequence

**Primary**
> "Take the hardest role you closed. What was it, roughly how many candidates did
> you speak to before one offer was accepted, and where did the person who
> accepted actually come from?"

**Follow-up**
> "Where in the funnel were you losing most people on that role — and what did the
> hiring manager have to change before it improved?"

**Cross question**
> "45 to 28 days — measured from requisition approval or from first CV sent? And
> do the 45 roles include backfills and any that got cancelled mid-process?"

**Transfer question**
> "You have three offers out and the client freezes headcount for six weeks. What
> do you do with the three candidates, and what do you say to the hiring
> manager?"

### Why this produces evidence
**Time-to-hire has no standard definition**, and which one a recruiter used tells
you whether they were measured on it or read it in a deck. Requisition-open to
accept and first-CV to accept differ by weeks, and the difference is exactly the
part a recruiter does not control. The funnel question surfaces the profession's
real conflict — the bottleneck is almost always the hiring manager's calendar or
their bar, and every genuine recruiter has a story about getting one of those
changed. The source-of-hire detail is cheap for an author (*"an inbound applicant
we'd rejected for another role"*) and generic for a stranger (*"LinkedIn"*). The
transfer question is a live scenario the recruiter can only navigate if they
have ever held a candidate's trust across a delay.

### Dimensions revealed
`METRIC_OWNERSHIP` (time-to-hire definition, requisition accounting) ·
`PROCESS` (funnel, stages, intake) · `SPECIFICITY` (role, ratios, source) ·
`CAUSAL_REASONING` (what change moved the funnel) · `AUTHENTICITY`.

---

## 8. Digital Marketing

**Claim**
> "Scaled paid acquisition to ₹50L/month at 3.2x ROAS and grew organic traffic
> 60%."

### BAD question
> *"What are the benefits of SEO over paid?"* / *"Walk me through the marketing
> funnel."*

Why it fails: content-marketing vocabulary is the most abundant text on the
internet. This measures exposure to blog posts.

### GOOD sequence

**Primary**
> "Split the ₹50L across channels for me. Which single campaign was the biggest
> line item, and what was its ROAS on its own?"

**Follow-up**
> "What did you switch off, and what did you see that made you switch it off?"

**Cross question**
> "3.2x — on what attribution window and which model? Was that revenue reported
> by the ad platform or from your own backend, and what was blended ROAS across
> everything you spent?"

**Transfer question**
> "Next month a tracking/consent change wipes out half your conversion signal and
> reported CAC jumps 40%. Budget is unchanged. What's your first move, and what
> do you stop trusting?"

### Why this produces evidence
The cross question is the sharpest single question in this entire document.
**Platform-reported ROAS and blended ROAS routinely differ by a factor of two**,
and every practitioner who has spent real money has been in the meeting where
finance points that out. A candidate who quotes 3.2x without knowing which one it
is has quoted a dashboard, not a result. Attribution window (1-day click vs
7-day click vs 28-day view) is the same test in a second form. The "what did you
turn off" follow-up works because **growth stories omit the killing**, and
killing spend is most of the job — an author names a campaign and the specific
number that condemned it. The transfer question describes an event the whole
industry has lived through, and the honest answer ("stop trusting platform
conversions, move to incrementality or holdouts, accept slower decisions") is
unavailable to anyone who has not.

### Dimensions revealed
`METRIC_OWNERSHIP` (attribution model, window, blended vs platform) ·
`SPECIFICITY` (channel split, campaign names, spend) · `CAUSAL_REASONING`
(spend → signal → decision) · `PROCESS` (testing and kill discipline) ·
`TOOL_FAMILIARITY`.

---

# ProofScreen Questioning Principles

Ten rules. Every future question generator — human or model — must satisfy all
ten. They are written so that a question can be **checked against them**, not
merely inspired by them.

### 1. Anchor to a claim, never to a field
Every question must be traceable to a specific claim made by *this* candidate.
If the same question could be sent unchanged to any other candidate in the
family, it is a quiz item. The test: remove the candidate's resume — does the
question still make sense? Then it is testing the field, not the claim.

### 2. Pass impostor-parity
Before shipping a question, imagine the articulate stranger who has read the
resume answering it. If their best answer is as good as the real author's, the
question yields no evidence. **Ask only where the two diverge.** This is the
master rule; the other nine are ways of satisfying it.

### 3. Ask for recall, not opinion
*What did you do, who did you call, what broke, what was it before* — never
*how would you, what's your approach, what do you think about*. Opinions are
free and infinitely generable. Memories are costly and unevenly distributed.
Any question beginning "how do you generally…" is out of bounds.

### 4. Probe the periphery, not the headline
The headline of a claim is the rehearsed part; spend no questions on it. Aim at
what surrounds it: the exception, the leftover, the thing that could not be
included, the person who disagreed, the part that didn't improve. **Peripheral
detail is cheap to recall and expensive to invent** — that asymmetry is the
entire product.

### 5. Make them own the metric before they own the result
Every quantified claim earns one question about **definition and measurement,
not value**. Which population, which window, which model, counted by whom,
compared against what. Across all eight families, metric-definition failure is
the highest-yield fabrication signal we have, and it is the one place where a
claim can be *falsified* rather than merely doubted.

### 6. Make failure safe to say
Ask for the incident, the trade-off, the thing that got switched off, the agent
who didn't improve. And frame it so that "it didn't work" is a fully acceptable
answer. **A question that has only one good answer will collect only that
answer** — from everyone, honest or not. Never phrase a probe so that admitting
a problem sounds like admitting incompetence.

### 7. One fact target, ninety seconds, one thumb
One question asks for one thing. A two-part question on WhatsApp gets one part
answered and you cannot tell which part was dodged — the ambiguity destroys the
signal. The bar: **a person who did the work can answer honestly in ninety
seconds from memory.** If it needs research, a document, or a paragraph of
setup, it is the wrong question regardless of how discriminating it is.
*(The one licensed exception: a cross question may bundle two facts precisely
because it is testing whether they cohere — see rule 9.)*

### 8. Never supply the answer inside the question
Do not name the technique, the metric, the tool or the reason you are hoping to
hear. "Why did you choose Redis for caching?" hands over both the decision and
its frame; "what was actually slow?" hands over nothing. A question that
contains its own vocabulary lets a stranger echo it back fluently. **The
candidate should have to supply the operating vocabulary of their own job** —
that vocabulary is itself the evidence.

### 9. Cross-question the seam, not the sentence
A cross question exists to put load on **two things the candidate has already
said** and see whether they hold together: p95 against p99, accuracy against
base rate, quota against deal count, AHT against repeat contacts, platform ROAS
against blended. It must be unanswerable by repeating an earlier answer, and it
must introduce no new subject matter. If it asks about something not yet
discussed, it is a primary question wearing the wrong hat.

### 10. Transfer inside their world — never a generic hypothetical
A transfer question rebuilds a situation **from the candidate's own claims** and
changes exactly one variable: their traffic, their SLA, their headcount, their
tracking, their champion. "What would you do if you were CTO of a startup" is a
hypothetical — an imagination test with a fluency tax. "Your cut-off doesn't
move and your feed is two hours late" is a transfer: recitable knowledge cannot
answer it, and lived knowledge answers it immediately.

---

### The standing prohibition (governs all ten)

**Nothing about performance is ever measured.** Not fluency, grammar, spelling,
vocabulary, confidence, warmth, accent, or how good an answer sounds. A blunt,
misspelt answer containing a real cut-off time outranks a polished one
containing none. Related and equally binding: **never gate on exact recall of a
number.** Invite figures, never require them — a question that an honest
candidate fails because they no longer remember the fourth digit converts our
signal into a memory test and quietly selects for the people who made the
numbers up.

---

## Question kill list

Patterns that fail one or more principles and should never be generated:

| Pattern | Fails |
|---|---|
| "What is X?" / "Explain the difference between X and Y" | 1, 2, 3 |
| "How do you generally handle…" / "What's your approach to…" | 3, 4 |
| "Why did you choose *[named technology]*?" | 8 |
| "How would you deal with an angry/difficult *[person]*?" | 2, 3 |
| "What's your *[methodology / strategy / philosophy]*?" | 2, 3 |
| "Tell me about your greatest strength" and every trait question | 3, standing prohibition |
| "What would you do if you were running *[unrelated company]*?" | 10 |
| Any question restating a figure the candidate must simply confirm | 8 |
| Any question answerable identically by every candidate in the family | 1 |
| Multi-part questions joined by "and also" / "additionally" | 7 |
