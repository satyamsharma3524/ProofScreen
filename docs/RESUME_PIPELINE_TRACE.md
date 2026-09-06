# Resume pipeline trace — `Abhishek-Singh-Resume-New.pdf`

Generated 2026-09-06. **Not a design document.** This is the raw output of one
resume driven through the production interview path, kept so the stage-by-stage
behaviour can be argued from evidence rather than from memory.

## How it was produced

```bash
DATABASE_URL="sqlite+aiosqlite:///./inspect.sqlite3" \
  python scripts/inspect_resume_pipeline.py \
    "resume_test/Abhishek-Singh-Resume-New.pdf" --fresh
```

`scripts/inspect_resume_pipeline.py` is a **printer**, not a pipeline. Every
value below was returned by a function in `api/`. It reuses
`scripts/demo_resume_flow.py`'s `_install_stubs`, `_deliver`, `_session_for` and
`CANNED` rather than copying them, and it drives `api/routers/whatsapp.py::_handle`
— the real handler — so the path is the one a WhatsApp document upload takes.

**The one seam** is the one `demo_resume_flow.py` already documents:
`whatsapp_channel.download_media()`, the only thing in the path needing a Meta
token. Nothing else is stubbed. Model calls are real: `llm_mode=live`,
requested `gpt-4o`, `model_returned=gpt-4o-2024-08-06`, 29 calls, 0 fallbacks,
0 failures.

**Raw model JSON** in stages 1 and 3 is read out of `api.llm._cache`, which
production already populates keyed by sha256 of (model, temperature, schema,
prompt). Nothing was intercepted or wrapped.

## Caveats on two sections

- **Stage 8** makes its own `generate_question()` calls to show the opening
  probe per claim. `generate_question` runs at `temperature=0.4` with
  `cache=False`, so its wording differs from the persisted Q1/Q2 even for the
  same claim and level. **The persisted `questions` rows are authoritative**;
  Stage 8 shows the shape, not the transcript.
- **Stage 10 onward is conditioned on the canned answers.** `plan_next` reads
  the evidence each answer produced. Different answers give a different — and
  equally deterministic — tree.

---

```text
resume     resume_test/Abhishek-Singh-Resume-New.pdf  (57,914 bytes, application/pdf)
llm mode   live  (requested model gpt-4o)
database   sqlite+aiosqlite:////private/tmp/claude-1675456510/-Users-212705-ProofScreen/4a31f0e1-9c70-43cf-8a17-8ea74960c0da/scratchpad/inspect.sqlite3
flags      ROLE_CLASSIFIER=False MAX_CLAIMS=3 MAX_QUESTIONS=12 ADAPTIVE_PROBING=True QUESTION_VALIDATION=True TRANSFER_PROBE=True REPAIR_TURN=True
taxonomy   tax_1 / hash 4e0f5b9b2fae
prompts    {"classify_role": "16f3e2681227", "extract_claims": "87100f0f6a67", "extract_signals": "fcfc7ed745d8", "generate_question": "80d28b21049f"}

==================================================
STAGE 0 — INGEST (the WhatsApp document branch)
==================================================

Inputs:
  bytes    57,914
  mime     application/pdf
  suffix   .pdf

Outputs:
  extracted 2913 chars after normalise()

  | Abhishek Singh
  | Senior Frontend Developer
  | abhishek.uietpuchd@gmail.com
  | 
  | 6361837256
  | 
  | Bangalore
  | 
  | elyzian.in
  | 
  | linkedin.com/in/abhishek-singh-bb1607112
  | 
  | Profile
  | With over 4 years of frontend engineering expertise, I specialize in React.JS, Redux-Toolkit, RTKQuery, Tailwind
  | CSS, Web Components, Typescript, NextJS and ExpressJS, driving a 40% performance boost and a 35%
  | increase in user engagement. Integrated Rest APIs resulting in an improved user experience.
  | Work Experience
  | Senior Frontend Developer, Elyzian
  | •Boosted storefront businesses' customer base by 45% with a hyper-local SaaS
  | platform, leading to enhanced customer satisfaction and long-term growth using
  | loyalty, referral, and feedback modules for B2B clients.
  | •Designed customizable dashboards, analytics tools, reward systems, and
  | whatsapp marketing automations which Improved customer conversion rate by
  | 20% resulting in increased sales and revenue for the business
  | 07/2023 – 06/2025
  | •Led frontend architecture with scalable component libraries and API integrations
  | driving a significant increase in user retention and customer satisfaction.
  | Senior Frontend Developer, SalesCaptain
  | •Developed a seamless integration with Google, Facebook, WhatsApp, and Twilio's
  | APIs, resulting in a 35% increase in user engagement and retention.
  | •Optimized platform performance by 40% through architecting the entire front-
  | end using ReactJS and Redux resulting in improved user experience and
  | scalability.
  | 06/2022 – 07/2023
  | •Integrated Twilio's SDK to enable SMS, voice, and WhatsApp communications,
  | building a robust communication platform that scales with user needs.
  | •Worked closely with cross-functional teams to align product goals with market
  | demands, ensuring a feature-rich, intuitive dashboard that caters to both
  | technical and non-technical users.
  | Frontend Developer, Genpact
  | •Developed internal enterprise dashboards, forms, and workflow tools,by
  | implementing ReactJS and Redux resulting in a 25% increase in user interaction
  | and productivity.
  | •Collaborated with backend teams and QA to integrate RESTful APIs, ensuring a
  | seamless flow of data and an optimized user experience.
  | 07/2019 – 06/2022
  | •Delivered responsive designs using Material UI and Tailwind CSS, ensuring cross-
  | browser compatibility and mobile optimization
  | Education
  | B.Tech in Computer Science, Panjab University Chandigarh
  | 
  | Skills
  | Javascript
  | CSS
  | ReactJS
  | RTK Query
  | Tailwind CSS
  | Git/Github
  | Postman
  | NextJs
  | ExpressJs
  | HTML
  | Material UI
  | Redux Toolkit
  | Responsive Webdesign
  | UI/UX
  | Rest APIs
  | Typescript
  | NodeJs
  | Projects
  | Gameonics, Medium-style Blog for Gamers
  | •Created a gaming-focused blog platform with React, Redux, and Tailwind CSS.
  | •Integrated QuillJS for rich text editing and built reusable UI components.
  | Clashamania
  | •Built a MERN-stack esports platform for a college fest with support for single and multiplayer gaming.
  | •Enabled player registration, real-time matches, and event tracking.

Reasoning:
  `_try_resume_intake` tests the BODY before the mime: in dry-run
  `download_media` defaults mime to audio/ogg, so a nil body must be
  caught first or every document reads as a voice note. The mime then
  maps through `_RESUME_SUFFIX` to a suffix, and `extract_text`
  dispatches on that suffix -- PyMuPDF for .pdf -- then `normalise()`
  collapses runs of whitespace and 3+ blank lines.

Code path:
api/routers/whatsapp.py::_try_resume_intake -> api/ingest/parse.py::extract_text/_from_pdf/normalise

--------------------------------------------------

==================================================
STAGE 1 — ROLE CLASSIFIER (LLM #0), routing precedence rung 2
==================================================

Inputs:
  settings.role_classifier   False
  header_slice() length      514 chars (MIN_HEADER_CHARS=40, HEADER_SLICE_CHARS=1800)

  header_slice() output -- achievement bullets deliberately withheld:
  | HEADER:
  | Abhishek Singh
  | Senior Frontend Developer
  | abhishek.uietpuchd@gmail.com
  | 6361837256
  | Bangalore
  | 
  | PROFILE:
  | With over 4 years of frontend engineering expertise, I specialize in React.JS, Redux-Toolkit, RTKQuery, Tailwind
  | CSS, Web Components, Typescript, NextJS and ExpressJS, driving a 40% performance boost and a 35%
  | Work Experience
  | Senior Frontend Developer, Elyzian
  | platform, leading to enhanced customer satisfaction and long-term growth using
  | 
  | SKILLS:
  | Javascript
  | CSS
  | ReactJS
  | RTK Query
  | Tailwind CSS
  | Git/Github

Outputs:
  ROLE_CLASSIFIER is FALSE, so `classify_role` returned the taxonomy
  family unchanged: 'software_engineering'. Rung 2 did not run.

  OBSERVATION (flag flipped on, then restored -- NOT used for routing):
  classifier would route to: 'software_engineering'

  raw classifier response (api.llm._cache, exact provider bytes):
  | {
  |   "family": "software_engineering",
  |   "confidence": 0.95,
  |   "seniority": "senior",
  |   "current_title": "Senior Frontend Developer",
  |   "reasoning": [
  |     "Senior Frontend Developer",
  |     "With over 4 years of frontend engineering expertise"
  |   ]
  | }

Reasoning:
  `classify_role` sends ONLY `header_slice()` -- headline, title
  history, summary and skills. Achievement bullets are withheld because
  that is where the revenue/pipeline/GTM language lives, and that
  language is what routes a product manager to `sales`.
  `confidence` and `seniority` come back and are RECORDED AND NEVER
  BRANCHED ON (CLAUDE.md rule 1). Certainty comes from the precedence
  order, not from a number the model made up about itself.

Code path:
api/engine/extract.py::header_slice, classify_role  (prompt api/prompts/classify_role.txt)

--------------------------------------------------

==================================================
STAGE 2 — TAXONOMY ROUTING (deterministic, no model call)
==================================================

Inputs:
  full resume text, 2913 chars
  taxonomy tax_1 / 4e0f5b9b2fae, 9 families

Outputs:
  FamilyMatch.family            software_engineering
  FamilyMatch.confidence        0.235398   (a MARGIN, not a probability)
  FamilyMatch.matched_terms     ['api', 'backend', 'frontend', 'react', 'engineer', 'developer']
  MARGIN_FLOOR                  0.35
  is_low_confidence(match)      True
  MIN_TERMS                     2

  per_family_scores (cosine over IDF-weighted keyword vectors):
    software_engineering     1.376494   <-- winner
    sales                    1.052470
    data_analytics           0.763370
    customer_support         0.301511
    hr_recruitment           0.258199
    product                  0.250000
    bpo_operations           0.000000
    banking_operations       0.000000

Reasoning:
  `match_family` counts each keyword ONCE however often it occurs -- a
  resume saying SQL eleven times is not eleven times a data resume, and
  rewarding repetition makes the router trivially gameable by the same
  keyword stuffing this product exists to see through. Each family's
  IDF vector is L2-normalised so a family cannot win by owning a longer
  keyword list. `confidence` is (top - runner_up) / top: it answers
  'was this close?', not 'is this right?'.

Code path:
api/taxonomy.py::match_family, _matched, _term_pattern, _idf, _family_norms, is_low_confidence

--------------------------------------------------

==================================================
STAGE 3 — extract_claims() (LLM #1)
==================================================

Inputs:
  resume_text        2913 chars (MAX_RESUME_CHARS=8000)
  job_family arg     None  (no requisition -- rung 1 empty, supplied=general)
  limit              3  (MAX_CLAIMS)
  temperature        0.0

Outputs:
  routed family      software_engineering  (Software Engineering)
  claims kept        2

  EXACT RAW MODEL JSON (api.llm._cache, pre-validation):
  | {
  |   "job_family": "software_engineering",
  |   "claims": [
  |     {
  |       "text": "Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux resulting in improved user experience and scalability.",
  |       "claim_type": "performance_work",
  |       "metric": "40%",
  |       "verifiable": true
  |     },
  |     {
  |       "text": "Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, leading to enhanced customer satisfaction and long-term growth using loyalty, referral, and feedback modules for B2B clients.",
  |       "claim_type": "delivery",
  |       "metric": "45%",
  |       "verifiable": true
  |     },
  |     {
  |       "text": "Developed internal enterprise dashboards, forms, and workflow tools, by implementing ReactJS and Redux resulting in a 25% increase in user interaction and productivity.",
  |       "claim_type": "delivery",
  |       "metric": "25%",
  |       "verifiable": true
  |     }
  |   ]
  | }

  AFTER Python validation (ClaimExtraction.model_dump_json):
  | {
  |   "job_family": "software_engineering",
  |   "claims": [
  |     {
  |       "text": "Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux resulting in improved user experience and scalability.",
  |       "claim_type": "performance_work",
  |       "metric": "40%",
  |       "verifiable": true
  |     },
  |     {
  |       "text": "Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, leading to enhanced customer satisfaction and long-term growth using loyalty, referral, and feedback modules for B2B clients.",
  |       "claim_type": "delivery",
  |       "metric": "45%",
  |       "verifiable": true
  |     }
  |   ]
  | }

Reasoning:
  ROUTING PRECEDENCE, decided in `extract_claims` and nowhere else:
    1. the requisition's job_family, when the caller supplied a real one
    2. the role classifier, on the TOP of the resume only   (LLM #0)
    3. deterministic keyword detection over the whole resume
    4. general
  The classifier runs BEFORE the prompt is built, and that ordering is
  the point: `claim_type_menu(routed)` decides which claim types the
  model is allowed to find, so a family corrected AFTER extraction
  would leave one cohort's claims wearing another's labels.
  The model still returns a job_family; it is OBSERVED, NOT OBEYED.
  Claims are then filtered in Python: verifiable=false or text < 15
  chars is dropped, and one claim per type is kept -- breadth beats
  depth, because an unprobed claim scores zero.

Code path:
api/engine/extract.py::extract_claims  (prompt api/prompts/extract_claims.txt)

--------------------------------------------------

The EXACT rendered prompt sent to the provider for LLM #1:

  | You are reading a resume to find the CLAIMS a recruiter would want verified.
  | 
  | A claim is a specific, falsifiable statement about something this person did or
  | achieved. It must be something a follow-up question could confirm or undermine.
  | 
  | REJECT FLUFF. These are not claims:
  |   "team player", "results-driven", "excellent communication skills",
  |   "passionate about technology", "detail oriented", "strong work ethic"
  | Also reject job-title headings and skill lists. "Support Lead, Acme (2021 -
  | present)" is employment history. "Python, SQL, Tableau" is a keyword list.
  | 
  | JOB FAMILY
  | Pick the one job family this resume belongs to, from exactly this list:
  |   bpo_operations — BPO / Contact Centre Operations
  |   customer_support — Customer Support
  |   sales — Sales / Business Development
  |   banking_operations — Banking / Financial Operations
  |   software_engineering — Software Engineering
  |   data_analytics — Data / Analytics
  |   hr_recruitment — HR / Recruitment
  |   product — Product Management
  |   general — General / Unclassified
  | 
  | CLAIM TYPES for the family you picked (software_engineering):
  |   system_ownership — System and service ownership (importance 25)
  |   performance_work — Performance and scale work (importance 20)
  |   reliability — Reliability and on-call (importance 20)
  |   delivery — Delivery and migration (importance 15)
  |   tech_depth — Technology depth (importance 15)
  |   mentoring — Mentoring and review (importance 5)
  | 
  | For each claim return:
  |   text        - the claim in one sentence, in the candidate's own words
  |   claim_type  - one key from the CLAIM TYPES list above. Nothing else.
  |   metric      - the measurable core, compressed. Use "before -> after" when the
  |                 resume states both: "78% -> 92%", "9 hours -> 45 minutes".
  |                 Use the bare figure otherwise: "50-member team", "18 services".
  |                 null when the claim carries no number.
  |   verifiable  - false if no follow-up question could test it
  | 
  | Return at most 3 claims, the most verifiable first. Prefer claims
  | that carry a number, a scale, a timeframe or a named system.
  | 
  | RESUME
  | ------
  | Abhishek Singh
  | Senior Frontend Developer
  | abhishek.uietpuchd@gmail.com
  | 
  | 6361837256
  | 
  | Bangalore
  | 
  | elyzian.in
  | 
  | linkedin.com/in/abhishek-singh-bb1607112
  | 
  | Profile
  | With over 4 years of frontend engineering expertise, I specialize in React.JS, Redux-Toolkit, RTKQuery, Tailwind
  | CSS, Web Components, Typescript, NextJS and ExpressJS, driving a 40% performance boost and a 35%
  | increase in user engagement. Integrated Rest APIs resulting in an improved user experience.
  | Work Experience
  | Senior Frontend Developer, Elyzian
  | •Boosted storefront businesses' customer base by 45% with a hyper-local SaaS
  | platform, leading to enhanced customer satisfaction and long-term growth using
  | loyalty, referral, and feedback modules for B2B clients.
  | •Designed customizable dashboards, analytics tools, reward systems, and
  | whatsapp marketing automations which Improved customer conversion rate by
  | 20% resulting in increased sales and revenue for the business
  | 07/2023 – 06/2025
  | •Led frontend architecture with scalable component libraries and API integrations
  | driving a significant increase in user retention and customer satisfaction.
  | Senior Frontend Developer, SalesCaptain
  | •Developed a seamless integration with Google, Facebook, WhatsApp, and Twilio's
  | APIs, resulting in a 35% increase in user engagement and retention.
  | •Optimized platform performance by 40% through architecting the entire front-
  | end using ReactJS and Redux resulting in improved user experience and
  | scalability.
  | 06/2022 – 07/2023
  | •Integrated Twilio's SDK to enable SMS, voice, and WhatsApp communications,
  | building a robust communication platform that scales with user needs.
  | •Worked closely with cross-functional teams to align product goals with market
  | demands, ensuring a feature-rich, intuitive dashboard that caters to both
  | technical and non-technical users.
  | Frontend Developer, Genpact
  | •Developed internal enterprise dashboards, forms, and workflow tools,by
  | implementing ReactJS and Redux resulting in a 25% increase in user interaction
  | and productivity.
  | •Collaborated with backend teams and QA to integrate RESTful APIs, ensuring a
  | seamless flow of data and an optimized user experience.
  | 07/2019 – 06/2022
  | •Delivered responsive designs using Material UI and Tailwind CSS, ensuring cross-
  | browser compatibility and mobile optimization
  | Education
  | B.Tech in Computer Science, Panjab University Chandigarh
  | 
  | Skills
  | Javascript
  | CSS
  | ReactJS
  | RTK Query
  | Tailwind CSS
  | Git/Github
  | Postman
  | NextJs
  | ExpressJs
  | HTML
  | Material UI
  | Redux Toolkit
  | Responsive Webdesign
  | UI/UX
  | Rest APIs
  | Typescript
  | NodeJs
  | Projects
  | Gameonics, Medium-style Blog for Gamers
  | •Created a gaming-focused blog platform with React, Redux, and Tailwind CSS.
  | •Integrated QuillJS for rich text editing and built reusable UI components.
  | Clashamania
  | •Built a MERN-stack esports platform for a college fest with support for single and multiplayer gaming.
  | •Enabled player registration, real-time matches, and event tracking.
  | ------
  | 
  | Return ONLY JSON, no prose, no markdown fences, matching this schema:
  | 
  | {
  |   "job_family": "software_engineering",
  |   "claims": [
  |     {"text": "string", "claim_type": "string", "metric": "string or null", "verifiable": true}
  |   ]
  | }

--------------------------------------------------

==================================================
STAGE 4 — CLAIM TYPING (validated in Python, never trusted blindly)
==================================================

Inputs:
  family software_engineering, claim-type menu offered to the model:
    system_ownership       System and service ownership           weight    25  probe_focus=['AUTHENTICITY', 'PROCESS']
    performance_work       Performance and scale work             weight    20  probe_focus=['CAUSAL_REASONING', 'METRIC_OWNERSHIP']
    reliability            Reliability and on-call                weight    20  probe_focus=['AUTHENTICITY', 'PROCESS']
    delivery               Delivery and migration                 weight    15  probe_focus=['PROCESS', 'CAUSAL_REASONING']
    tech_depth             Technology depth                       weight    15  probe_focus=['TOOL_FAMILIARITY', 'SPECIFICITY']
    mentoring              Mentoring and review                   weight     5  probe_focus=['AUTHENTICITY', 'PROCESS']

Outputs:
  claim 1
    text                  Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux resulting in improved user experience and scalability.
    claim_type (kept)     performance_work
    claim_type_label      Performance and scale work
    weight in family      20.0
    metric                '40%'
    _metric_of(text)      '40%'
    classify_claim(text)  system_ownership   (DISAGREES -- model key kept because it exists in this family)
    probe_focus           ['CAUSAL_REASONING', 'METRIC_OWNERSHIP']
  claim 2
    text                  Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, leading to enhanced customer satisfaction and long-term growth using loyalty, referral, and feedback modules for B2B clients.
    claim_type (kept)     delivery
    claim_type_label      Delivery and migration
    weight in family      15.0
    metric                '45%'
    _metric_of(text)      '45%'
    classify_claim(text)  system_ownership   (DISAGREES -- model key kept because it exists in this family)
    probe_focus           ['PROCESS', 'CAUSAL_REASONING']

Reasoning:
  `normalise_claim_type(family, key, text)` trusts the model's
  claim_type ONLY if that key exists in this family; anything invented
  is silently reclassified by `classify_claim`, which is pure keyword
  hit-counting. The claim TYPE is what carries the recruiter's
  importance weight, so an unclassified claim cannot be ranked.

Code path:
api/taxonomy.py::normalise_claim_type, classify_claim, default_claim_weights, probe_focus

--------------------------------------------------

==================================================
STAGE 5 — CLAIM ATTRIBUTION (role / company per claim)
==================================================

Inputs:
  api.schemas.ExtractedClaim fields: ['text', 'claim_type', 'metric', 'verifiable']
  api.models.Claim columns:          ['id', 'tenant_id', 'resume_id', 'candidate_id', 'text', 'claim_type', 'metric', 'order_index', 'created_at']

Outputs:
  NOT AVAILABLE. There is no company or employer field anywhere on the
  claim path: not on `ExtractedClaim`, not on the `claims` table, and
  `api/prompts/extract_claims.txt` never asks for one. No production
  code attributes a claim to a role or a company.

Reasoning:
  This is a real gap, not an omission in this trace. `extract.py`'s own
  comment above `classify_role` records the consequence measured on six
  PM resumes: 'Four of those six resumes produced claims from a job the
  candidate left in 2021. The interview then asked about it.' The fix
  shipped was to get the FAMILY right before extraction (rung 2), which
  makes the wrong-job claim less likely -- it does not record which job
  a claim came from, so the failure is still not detectable from stored
  rows. Adding it means a field on the frozen `api/schemas.py`, which
  CLAUDE.md rule 2 makes a conversation rather than a solo edit.

Code path:
api/schemas.py::ExtractedClaim · api/models.py::Claim · api/prompts/extract_claims.txt  (field absent in all three)

--------------------------------------------------

==================================================
STAGE 6 — create_session() via the real WhatsApp document handler
==================================================

Inputs:
  InboundMessage(channel=whatsapp, media_id='media.52a302a9',
                 external_id='919810070042',
                 profile_name='Pipeline Inspection',
                 provider_message_id='wamid.52a302a9.doc')
  stubbed: whatsapp_channel.download_media / send_text / mark_read

Outputs:


┌─ WhatsApp → +919810070042
│ Resume received. I'm reading through your experience now — one moment.
└─

┌─ WhatsApp → +919810070042
│ Got it — I've understood your background and found 2 claims worth verifying. Preparing your first question...
└─

┌─ WhatsApp → +919810070042
│ How many team members were involved in the ReactJS and Redux project?
└─
  candidate_id   c_842f7d   name='Pipeline Inspection'  tenant=t_dev
  session_id     s_016520f38d   state=ASKING  channel=whatsapp
  job_family     software_engineering
  opt_in_code    YLTFG6   (unused -- the resume IS the opt-in)
  claims         2
    cl_c9523b  order=0  type=performance_work  metric='40%'
    cl_0ad1e1  order=1  type=delivery  metric='45%'

Reasoning:
  The document branch does NOT wait for an opt-in code: the candidate
  messaged us unprompted with their resume, the 24-hour window is
  already open, and an upload is a stronger consent signal than a code.
  So AWAITING_OPT_IN is advanced straight to CLAIMS_READY and `ask_next`
  is called in the same handler. A draft Evaluation is opened WITH the
  interview, not after it (D6).

Code path:
api/routers/whatsapp.py::_handle -> _try_resume_intake -> api/routers/candidates.py::_onboard -> api/engine/orchestrator.py::create_session

--------------------------------------------------

==================================================
STAGE 7 — plan_next(): the question policy, pure and deterministic
==================================================

Inputs:
  states (sorted heaviest claim first), index=1
  cl_c9523b  weight=20  type=performance_work
    levels_used=['VALIDATION']  levels_left=['OPERATIONAL', 'INCIDENT', 'DECISION', 'OUTCOME']
    answers=0  score=0  saturated=False  stalled=False  exhausted=False
    transfer_available=False  weakest_dimension=SPECIFICITY
  cl_0ad1e1  weight=15  type=delivery
    levels_used=[]  levels_left=['VALIDATION', 'OPERATIONAL', 'INCIDENT', 'DECISION', 'OUTCOME']
    answers=0  score=0  saturated=False  stalled=False  exhausted=False
    transfer_available=False  weakest_dimension=SPECIFICITY

Outputs:
  the ladder, and which dimensions each rung is designed to elicit:
    VALIDATION   -> ['SPECIFICITY', 'METRIC_OWNERSHIP']
    OPERATIONAL  -> ['PROCESS', 'TOOL_FAMILIARITY']
    INCIDENT     -> ['AUTHENTICITY', 'SPECIFICITY']
    DECISION     -> ['CAUSAL_REASONING', 'PROCESS']
    OUTCOME      -> ['METRIC_OWNERSHIP', 'CAUSAL_REASONING']
    TRANSFER     -> ['CAUSAL_REASONING', 'PROCESS']

  LADDER_ORDER (TRANSFER excluded -- offered only by the stall branch):
    ['VALIDATION', 'OPERATIONAL', 'INCIDENT', 'DECISION', 'OUTCOME']

  dimension -> earliest level that covers it (level_for_dimension):
    SPECIFICITY          -> VALIDATION
    PROCESS              -> OPERATIONAL
    METRIC_OWNERSHIP     -> VALIDATION
    CAUSAL_REASONING     -> DECISION
    AUTHENTICITY         -> INCIDENT
    TOOL_FAMILIARITY     -> OPERATIONAL

Reasoning:
  Phase 1 BREADTH: one VALIDATION probe on every claim, heaviest first.
  Nobody is deepened before every claim has been touched, because an
  unprobed claim scores zero and would silently sink the candidate.
  Phase 2 DEPTH: repeatedly take the heaviest claim that is not yet
  saturated and ask the level covering its weakest un-probed dimension.
  ADAPTIVE STOP: a claim stops at score >= 80, at five levels spent, or
  when the last answer produced no new signals at all.

Code path:
api/engine/orchestrator.py::plan_next, build_claim_states, ClaimState · api/engine/signals.py::PROBE_LEVEL_DIMENSIONS, LADDER_ORDER, level_for_dimension

--------------------------------------------------

==================================================
STAGE 8 — generate_question() (LLM #2): the opening probe on every claim
==================================================

Inputs:
  probe_level        VALIDATION (breadth phase, every claim)
  target_dimension   None (the breadth branch passes no gap hint)
  temperature        0.4
  validation         True  (rules: see question.validate())

Outputs:

  cl_c9523b  (Performance and scale work, weight 20)
    question    How many people were involved in the ReactJS and Redux project?
    probe_level VALIDATION
    source      model   attempts=1
    violations  []
    dimensions  ['SPECIFICITY', 'METRIC_OWNERSHIP']

  cl_0ad1e1  (Delivery and migration, weight 15)
    question    On "Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, l..." — Tell me more about this — what exactly was your scope, and what were the numbers?
    probe_level VALIDATION
    source      fallback   attempts=2
    violations  ['answer_leakage']
    dimensions  ['SPECIFICITY', 'METRIC_OWNERSHIP']

Reasoning:
  planner -> model -> validate() -> ONE regeneration -> fallback.
  `validate()` applies seven rules in PURE PYTHON. The model produces,
  Python decides -- the same pattern as `enforce_verbatim()`.
  The regeneration cap is one, written as two explicit calls rather than
  a loop: a loop invites raising the constant.
  The FALLBACK IS NEVER VALIDATED -- it is rendered `On "<claim>" —
  <base>`, so it quotes the claim and trips `answer_leakage` by
  construction. A validator able to reject it would leave no path at all.

Code path:
api/engine/question.py::generate_question, validate, fallback_question  (prompt api/prompts/generate_question.txt)

--------------------------------------------------

==================================================
STAGE 9 — CONTRADICTION SURFACE and TRANSFER PROBES available later
==================================================

Inputs:
  family software_engineering; the consistency engine tracks facts only
  on these keys (11 of them), and only on the STABLE ones is a
  divergence a contradiction rather than a before/after:

Outputs:
    team_size                Team size                          kind=count      stable=True
    direct_reports           Direct reports                     kind=count      stable=True
    tenure_months            Tenure in the role                 kind=duration_months stable=True
    headcount_managed        Headcount managed                  kind=count      stable=True
    shift_count              Shifts managed                     kind=count      stable=True
    p95_latency_ms           p95 latency                        kind=duration_ms stable=False
    requests_per_second      Requests per second                kind=count      stable=False
    uptime_pct               Uptime / availability              kind=percent    stable=False
    service_count            Services owned                     kind=count      stable=True
    deploy_frequency_per_week Deploys per week                   kind=count      stable=False
    incident_count           Incidents handled                  kind=count      stable=False

  Transfer probe each claim would receive IF it stalls (select_transfer is pure and deterministic):
    cl_c9523b  operator=T1
      basis        T1 substitute-the-problem: their method on cl_c9523b applied to the problem they claimed in cl_0ad1e1
      other_problem "storefront businesses' customer base"
    cl_0ad1e1  operator=T1
      basis        T1 substitute-the-problem: their method on cl_0ad1e1 applied to the problem they claimed in cl_c9523b
      other_problem 'platform performance'

Reasoning:
  Consistency is SESSION-LEVEL and applied once, as a multiplier -- it
  is a property of the whole interview, not of any claim, and counting
  it inside a claim as well would penalise the same fact twice.
  The stable/variable split is why the engine does not flag every
  improvement a candidate describes as a contradiction.
  `select_transfer` takes NO job_family parameter, deliberately: two
  candidates with identical evidence in unrelated industries must get
  the identical probe, or the mechanism is a scenario library in
  disguise and every new cohort becomes an engineering ticket.

Code path:
api/taxonomy.py::fact_keys, fact_is_stable · api/engine/consistency.py::check_new_facts, compare · api/engine/orchestrator.py::select_transfer

--------------------------------------------------

==================================================
STAGE 10 — THE ACTUAL INTERVIEW (real handler, canned answers)
==================================================

Inputs:
  answers cycled from scripts/demo_resume_flow.CANNED, delivered through
  api/routers/whatsapp.py::_handle exactly as a candidate's WhatsApp
  message would be. The SEQUENCE BELOW IS CONDITIONED ON THESE ANSWERS:
  plan_next reads the evidence each answer produced, so different
  answers give a different -- equally deterministic -- tree.

Outputs:

  candidate answer 1: I owned it end to end. I ran the roadmap with the founders and enginee...

┌─ WhatsApp → +919810070042
│ How long did it take to achieve the customer base increase?
└─
  candidate answer 2: The number came from our Mixpanel funnel, measured weekly as activated...

┌─ WhatsApp → +919810070042
│ What factors led you to choose ReactJS and Redux over other technologies for performance optimization?
└─
  candidate answer 3: One release went badly. We shipped a checkout change on a Friday and c...

┌─ WhatsApp → +919810070042
│ What specific steps did you take daily to ensure the ReactJS and Redux architecture improved performance?
└─
  candidate answer 4: We ran it in Mixpanel and Figma, with the tickets in Linear and the pa...

┌─ WhatsApp → +919810070042
│ On "Optimized platform performance by 40% through architecting the entire front-end using R..." — What happened afterwards? How did you know it worked, and which number moved?
└─
  candidate answer 5: Afterwards conversion held at the new level for two quarters. Looking ...

┌─ WhatsApp → +919810070042
│ What was the most challenging bug you encountered during the ReactJS and Redux rollout?
└─
  candidate answer 6: I owned it end to end. I ran the roadmap with the founders and enginee...

┌─ WhatsApp → +919810070042
│ What criteria did you use to decide which loyalty, referral, and feedback modules to implement?
└─
  candidate answer 7: The number came from our Mixpanel funnel, measured weekly as activated...

┌─ WhatsApp → +919810070042
│ Describe a specific time when a client was unhappy with the platform's loyalty module.
└─
  candidate answer 8: One release went badly. We shipped a checkout change on a Friday and c...

┌─ WhatsApp → +919810070042
│ How did you use Mixpanel daily to track the customer base increase?
└─
  candidate answer 9: We ran it in Mixpanel and Figma, with the tickets in Linear and the pa...

┌─ WhatsApp → +919810070042
│ On "Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, l..." — What happened afterwards? How did you know it worked, and which number moved?
└─
  candidate answer 10: Afterwards conversion held at the new level for two quarters. Looking ...

┌─ WhatsApp → +919810070042
│ That's everything — thank you.
│ 
│ *Competence score: 69/100*
│ Status: Partially verified
│ Evidence covered 6 of 6 dimensions across 2 claims.
│ 
│ Your verified profile is ready and the recruiter can see it now.
└─
Code path:
api/routers/whatsapp.py::_handle -> api/engine/orchestrator.py::submit_answer -> ask_next -> plan_next -> generate_question

--------------------------------------------------

==================================================
EXACT Question ROWS AS PERSISTED
==================================================

{
  "id": "q_5f10bd",
  "tenant_id": "t_dev",
  "claim_id": "cl_c9523b",
  "session_id": "s_016520f38d",
  "text": "How many team members were involved in the ReactJS and Redux project?",
  "probe_level": "VALIDATION",
  "target_dimension": null,
  "order_index": 0,
  "asked_at": "2026-09-06T07:20:55.900823",
  "answered": true,
  "source": "regenerated",
  "attempts": 2,
  "violations_json": "[\"no_claim_anchor\"]",
  "is_repair": false
}

{
  "id": "q_c871cc",
  "tenant_id": "t_dev",
  "claim_id": "cl_0ad1e1",
  "session_id": "s_016520f38d",
  "text": "How long did it take to achieve the customer base increase?",
  "probe_level": "VALIDATION",
  "target_dimension": null,
  "order_index": 1,
  "asked_at": "2026-09-06T07:21:06.392514",
  "answered": true,
  "source": "regenerated",
  "attempts": 2,
  "violations_json": "[\"answer_leakage\"]",
  "is_repair": false
}

{
  "id": "q_9ef8ba",
  "tenant_id": "t_dev",
  "claim_id": "cl_c9523b",
  "session_id": "s_016520f38d",
  "text": "What factors led you to choose ReactJS and Redux over other technologies for performance optimization?",
  "probe_level": "DECISION",
  "target_dimension": "CAUSAL_REASONING",
  "order_index": 2,
  "asked_at": "2026-09-06T07:21:11.995869",
  "answered": true,
  "source": "model",
  "attempts": 1,
  "violations_json": null,
  "is_repair": false
}

{
  "id": "q_b35477",
  "tenant_id": "t_dev",
  "claim_id": "cl_c9523b",
  "session_id": "s_016520f38d",
  "text": "What specific steps did you take daily to ensure the ReactJS and Redux architecture improved performance?",
  "probe_level": "OPERATIONAL",
  "target_dimension": "TOOL_FAMILIARITY",
  "order_index": 3,
  "asked_at": "2026-09-06T07:21:21.313056",
  "answered": true,
  "source": "model",
  "attempts": 1,
  "violations_json": null,
  "is_repair": false
}

{
  "id": "q_03044c",
  "tenant_id": "t_dev",
  "claim_id": "cl_c9523b",
  "session_id": "s_016520f38d",
  "text": "On \"Optimized platform performance by 40% through architecting the entire front-end using R...\" — What happened afterwards? How did you know it worked, and which number moved?",
  "probe_level": "OUTCOME",
  "target_dimension": "METRIC_OWNERSHIP",
  "order_index": 4,
  "asked_at": "2026-09-06T07:21:29.559139",
  "answered": true,
  "source": "fallback",
  "attempts": 2,
  "violations_json": "[\"answer_leakage\"]",
  "is_repair": false
}

{
  "id": "q_45cb54",
  "tenant_id": "t_dev",
  "claim_id": "cl_c9523b",
  "session_id": "s_016520f38d",
  "text": "What was the most challenging bug you encountered during the ReactJS and Redux rollout?",
  "probe_level": "INCIDENT",
  "target_dimension": "SPECIFICITY",
  "order_index": 5,
  "asked_at": "2026-09-06T07:21:36.644194",
  "answered": true,
  "source": "model",
  "attempts": 1,
  "violations_json": null,
  "is_repair": false
}

{
  "id": "q_6f16a2",
  "tenant_id": "t_dev",
  "claim_id": "cl_0ad1e1",
  "session_id": "s_016520f38d",
  "text": "What criteria did you use to decide which loyalty, referral, and feedback modules to implement?",
  "probe_level": "DECISION",
  "target_dimension": "CAUSAL_REASONING",
  "order_index": 6,
  "asked_at": "2026-09-06T07:21:41.601995",
  "answered": true,
  "source": "model",
  "attempts": 1,
  "violations_json": null,
  "is_repair": false
}

{
  "id": "q_b8feef",
  "tenant_id": "t_dev",
  "claim_id": "cl_0ad1e1",
  "session_id": "s_016520f38d",
  "text": "Describe a specific time when a client was unhappy with the platform's loyalty module.",
  "probe_level": "INCIDENT",
  "target_dimension": "AUTHENTICITY",
  "order_index": 7,
  "asked_at": "2026-09-06T07:21:46.361678",
  "answered": true,
  "source": "model",
  "attempts": 1,
  "violations_json": null,
  "is_repair": false
}

{
  "id": "q_d79eb3",
  "tenant_id": "t_dev",
  "claim_id": "cl_0ad1e1",
  "session_id": "s_016520f38d",
  "text": "How did you use Mixpanel daily to track the customer base increase?",
  "probe_level": "OPERATIONAL",
  "target_dimension": "TOOL_FAMILIARITY",
  "order_index": 8,
  "asked_at": "2026-09-06T07:21:52.828757",
  "answered": true,
  "source": "model",
  "attempts": 1,
  "violations_json": null,
  "is_repair": false
}

{
  "id": "q_122062",
  "tenant_id": "t_dev",
  "claim_id": "cl_0ad1e1",
  "session_id": "s_016520f38d",
  "text": "On \"Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, l...\" — What happened afterwards? How did you know it worked, and which number moved?",
  "probe_level": "OUTCOME",
  "target_dimension": "CAUSAL_REASONING",
  "order_index": 9,
  "asked_at": "2026-09-06T07:21:58.601384",
  "answered": true,
  "source": "fallback",
  "attempts": 2,
  "violations_json": "[\"answer_leakage\"]",
  "is_repair": false
}


==================================================
FINAL QUESTION TREE
==================================================

cl_c9523b  [performance_work] Performance and scale work
  Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux resulting in improved user experience and scalability.
    Q1  VALIDATION   target=—                    dims=['SPECIFICITY', 'METRIC_OWNERSHIP']  source=regenerated attempts=2
        How many team members were involved in the ReactJS and Redux project?
        -> signals_found=5
    Q3  DECISION     target=CAUSAL_REASONING     dims=['CAUSAL_REASONING', 'PROCESS']  source=model attempts=1
        What factors led you to choose ReactJS and Redux over other technologies for performance optimization?
        -> signals_found=8
    Q4  OPERATIONAL  target=TOOL_FAMILIARITY     dims=['PROCESS', 'TOOL_FAMILIARITY']  source=model attempts=1
        What specific steps did you take daily to ensure the ReactJS and Redux architecture improved performance?
        -> signals_found=5
    Q5  OUTCOME      target=METRIC_OWNERSHIP     dims=['METRIC_OWNERSHIP', 'CAUSAL_REASONING']  source=fallback attempts=2
        On "Optimized platform performance by 40% through architecting the entire front-end using R..." — What happened afterwards? How did you know it worked, and which number moved?
        -> signals_found=2
    Q6  INCIDENT     target=SPECIFICITY          dims=['AUTHENTICITY', 'SPECIFICITY']  source=model attempts=1
        What was the most challenging bug you encountered during the ReactJS and Redux rollout?
        -> signals_found=5

cl_0ad1e1  [delivery] Delivery and migration
  Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, leading to enhanced customer satisfaction and long-term growth using loyalty, referral, and feedback modules for B2B clients.
    Q2  VALIDATION   target=—                    dims=['SPECIFICITY', 'METRIC_OWNERSHIP']  source=regenerated attempts=2
        How long did it take to achieve the customer base increase?
        -> signals_found=4
    Q7  DECISION     target=CAUSAL_REASONING     dims=['CAUSAL_REASONING', 'PROCESS']  source=model attempts=1
        What criteria did you use to decide which loyalty, referral, and feedback modules to implement?
        -> signals_found=4
    Q8  INCIDENT     target=AUTHENTICITY         dims=['AUTHENTICITY', 'SPECIFICITY']  source=model attempts=1
        Describe a specific time when a client was unhappy with the platform's loyalty module.
        -> signals_found=8
    Q9  OPERATIONAL  target=TOOL_FAMILIARITY     dims=['PROCESS', 'TOOL_FAMILIARITY']  source=model attempts=1
        How did you use Mixpanel daily to track the customer base increase?
        -> signals_found=5
    Q10  OUTCOME      target=CAUSAL_REASONING     dims=['METRIC_OWNERSHIP', 'CAUSAL_REASONING']  source=fallback attempts=2
        On "Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, l..." — What happened afterwards? How did you know it worked, and which number moved?
        -> signals_found=2


==================================================
FINAL INTERVIEW PREVIEW
==================================================

Claim 1:
- Claim text     Optimized platform performance by 40% through architecting the entire front-end using ReactJS and Redux resulting in improved user experience and scalability.
- Company        NOT RECORDED — no such field exists (see STAGE 5)
- Claim type     performance_work — Performance and scale work (weight 20.0)
- Metric         '40%'
- First question How many team members were involved in the ReactJS and Redux project?
- Probe focus    ['CAUSAL_REASONING', 'METRIC_OWNERSHIP']
- Dimensions explored ['AUTHENTICITY', 'CAUSAL_REASONING', 'METRIC_OWNERSHIP', 'PROCESS', 'SPECIFICITY', 'TOOL_FAMILIARITY']

Claim 2:
- Claim text     Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, leading to enhanced customer satisfaction and long-term growth using loyalty, referral, and feedback modules for B2B clients.
- Company        NOT RECORDED — no such field exists (see STAGE 5)
- Claim type     delivery — Delivery and migration (weight 15.0)
- Metric         '45%'
- First question How long did it take to achieve the customer base increase?
- Probe focus    ['PROCESS', 'CAUSAL_REASONING']
- Dimensions explored ['AUTHENTICITY', 'CAUSAL_REASONING', 'METRIC_OWNERSHIP', 'PROCESS', 'SPECIFICITY', 'TOOL_FAMILIARITY']


==================================================
FULL QUESTION FLOW
==================================================

Q1  [VALIDATION]
  How many team members were involved in the ReactJS and Redux project?

Q2  [VALIDATION]
  How long did it take to achieve the customer base increase?

Q3  [DECISION · target CAUSAL_REASONING]
  What factors led you to choose ReactJS and Redux over other technologies for performance optimization?

Q4  [OPERATIONAL · target TOOL_FAMILIARITY]
  What specific steps did you take daily to ensure the ReactJS and Redux architecture improved performance?

Q5  [OUTCOME · target METRIC_OWNERSHIP]
  On "Optimized platform performance by 40% through architecting the entire front-end using R..." — What happened afterwards? How did you know it worked, and which number moved?

Q6  [INCIDENT · target SPECIFICITY]
  What was the most challenging bug you encountered during the ReactJS and Redux rollout?

Q7  [DECISION · target CAUSAL_REASONING]
  What criteria did you use to decide which loyalty, referral, and feedback modules to implement?

Q8  [INCIDENT · target AUTHENTICITY]
  Describe a specific time when a client was unhappy with the platform's loyalty module.

Q9  [OPERATIONAL · target TOOL_FAMILIARITY]
  How did you use Mixpanel daily to track the customer base increase?

Q10  [OUTCOME · target CAUSAL_REASONING]
  On "Boosted storefront businesses' customer base by 45% with a hyper-local SaaS platform, l..." — What happened afterwards? How did you know it worked, and which number moved?


==================================================
RECRUITER VIEW (graph.build_candidate_graph)
==================================================

  job_family_label     Software Engineering
  routing_confidence   0.235398
  questions_asked      10
  resume_score         6
  weighted_evidence    69
  competence_score     69
  badge                partial
  role_coverage        35
  dimensions probed    6 of 6
    x SPECIFICITY           71  across 2 claim(s)
    x PROCESS              100  across 2 claim(s)
    x METRIC_OWNERSHIP      51  across 2 claim(s)
    x CAUSAL_REASONING      50  across 2 claim(s)
    x AUTHENTICITY         100  across 2 claim(s)
    x TOOL_FAMILIARITY      40  across 2 claim(s)
  consistency          score=100 multiplier=1.0 facts_tracked=0

llm cache stats: {'hits': 1, 'calls': 29, 'fallbacks': 0, 'failures': 0, 'cached_entries': 12}
model_returned:  gpt-4o-2024-08-06
```
