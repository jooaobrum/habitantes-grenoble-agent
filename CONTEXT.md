# Habitantes de Grenoble

A community assistant that turns the Habitantes de Grenoble WhatsApp group history into knowledge Brazilian expats in Grenoble can ask about.

## Group history

**Thread**:
A run of group messages with no silence longer than a fixed gap; it often mixes several unrelated subjects.
_Avoid_: Conversation, discussion

**Q&A Pair**:
A question someone asked in the group together with the answers other members gave to it.
_Avoid_: QA record, chunk

**Topic**:
One of the fixed subject areas (Visa & Residency, Housing & CAF, Health & Insurance, …) that a Q&A Pair or Suggestion is filed under; the bot's menu lists Topics.
_Avoid_: Category

## Suggestions

**Suggestion**:
A real-world business, place or product the community has opinions about, consolidated from every Mention of it (same normalised name and same Kind, after name variants are merged); it carries 👍/👎 counts, the date of its latest Mention and its Items. A chain is one Suggestion whichever branch is mentioned. Private individuals, banks, phone operators, apps, associations and public services are never Suggestions.
_Avoid_: Recommendation, indicação

**Kind**:
What sort of thing a Suggestion is — Restaurants & Bars, Markets & Groceries, Shops, Products, Salons & Beauty, Gyms & Sports, Doctors, Dentists, Translators, Professional Services, Courses & Teachers, Vets & Pets, Places & Outings, or Other; every Kind sits under one fixed Topic, so a Suggestion's Topic is derived from its Kind, never extracted (a known simplification: a lawyer is a Professional Service under Daily Life & Services).
_Avoid_: Suggestion category, type, subcategory

**Community Business**:
A Suggestion run by a member of the group, typically known from that member advertising it; it qualifies only with a business identity beyond the member's own name or personal number, is offered only once at least one other member has also mentioned it (the advertiser's own post is stored but not counted), and is always disclosed as such.
_Avoid_: Entrepreneur, self-promotion (as a Kind)

**Mention**:
One member's positive or negative opinion of a Suggestion at one moment in the group history, possibly spread over several consecutive messages. Mentions never carry who wrote them; they are the author-free source every rebuild starts from.
_Avoid_: Recommendation, review, endorsement

**Context**:
The one-sentence gist of a Mention: what the Suggestion was used or recommended for, and why it was liked or disliked.
_Avoid_: Need, aspect, review text

**Item**:
A specific product or service a Mention names the Suggestion for — massa de pastel, farinha de mandioca, corte de cabelo cacheado, limpeza dental.
_Avoid_: Key term, tag, need

**Cluster**:
Mentions of one Kind that people make for a similar purpose (similar Items and Context), collapsed to one line per Suggestion and summarised with its top Suggestions; it is the unit stored in the Suggestions collection and what a Recommendation Request is matched against. Grouping is by Mention, so one Suggestion can appear in two Clusters. The summary lists only the top members (ranked by 👍 minus 👎, Mentions older than two years counting half; scores of 0 or less left out), but every member stays stored. At query time members are pooled across Clusters, deduped by name and ranked by raw 👍 minus 👎 (the two-year weighting is not applied there; see ADR 0002).
_Avoid_: Group, bucket

**Opt-out list**:
The maintained list of business names that must never become Suggestions (`config/suggestion_exclusions.txt`), applied on every rebuild before counting.
_Avoid_: Blocklist, blacklist

## Asking the assistant

**Recommendation Request**:
A user message asking who or where to go for something (a business, place or product); one message can be both a Recommendation Request and a question about how something works.
_Avoid_: Recommendation (alone)

**Intent**:
What the assistant decides a user message is: `greeting`, `qa` (a procedural question), `recommendation` (a Recommendation Request), `both`, `feedback` or `out_of_scope`. The tools the assistant may use for the message follow from the Intent, not from the model's own choice.
_Avoid_: Category (that is the Topic menu)
