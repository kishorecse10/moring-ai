# Stakeholder thread

_Forwarded to you on your first day by Meridian's Head of Finance Systems._

---

**From:** Anita Rao, CFO
**Subject:** Ledgerline rollout: I need this live by month end

Every manual touch costs us roughly ₹85 of AP time. Two asks:

1. Straight-through processing for clean invoices under ₹10,000. That's about 40% of our volume, and nobody should have to click anything for them.
2. When OCR garbles a GSTIN (O instead of 0, that kind of thing), the AI should just fix it instead of bouncing the invoice back to the team.

We present the rollout plan to the board on the 28th.

---

**From:** Farhan Sheikh, Head of Accounts Payable
**Subject:** Re: Ledgerline rollout

Anita, I'm not comfortable with point 1 yet.

My reviewers have stopped trusting Ledgerline. They can't see where a number came from, so they re-key everything from the PDF, which defeats the purpose. Show them the source of each value.

Last quarter we lost ₹3.8 lakh to a fake "our bank account has changed" email. Any change to a vendor's bank details must be blocked until we have phoned the vendor back on the number in our records.

And please use the most accurate model there is. I would much rather pay for accuracy than chase errors.

> Forwarded from Kavya Iyer, AP Lead: "When the system is slow, clicking Approve sometimes creates two payment entries. Treasury caught one last week."

---

**From:** Deepak Menon, CTO
**Subject:** Re: Ledgerline rollout

Anthropic billed us about $165 for October, for roughly 2,400 documents. Ledgerline's own dashboard says total LLM spend for the month was ₹15. One of those numbers is wrong, and I'd like to know which, and why.

For the full rollout: an average LLM cost of ₹1.50 or less per document, and p95 under 10 seconds end to end. No new infrastructure this quarter: no new databases, queues or vendors.

Also, could we fine-tune a model on our invoices instead? I keep hearing that's the way to do this.

---

**From:** Priya Natarajan, Data Protection Officer
**Subject:** Re: Ledgerline rollout

Before any rollout I need a precise answer to one question: what exactly does Ledgerline send to the LLM provider? Under section 5 of the AP policy, vendor bank account numbers must not leave our systems. If we're sending them today, I need to know, and I need it fixed.

---

**From:** Sunil Joshi, Finance Controller (owner of the AP policy)
**Subject:** Re: Ledgerline rollout

Two things before anyone changes my policy.

Most of our vendors are MSMEs, and we have to pay them within 45 days. Review is already our bottleneck. If Ledgerline sends half of all invoices to review, we will start paying late, and that has a cost too: interest, and vendors who stop giving us credit. "Send everything to review to be safe" is not an answer I can accept.

Farhan's call-back rule for bank changes is sensible, but we don't keep vendor phone numbers in the vendor master today, and I won't add a field until someone shows me the workflow that uses it.

---

**From:** Ravi Kulkarni (the contractor who built Ledgerline)
**Subject:** Re: Ledgerline rollout

Saw this thread and happy to help. One request: please don't rip the rules out of the prompt without thinking about why they're there. Sunil's team changes the policy every few weeks. Every rule in code means a developer, a review and a release, and Meridian doesn't have a developer. With the policy in the prompt, Finance edits one markdown file and it's live the same day. The model also copes with things a rules engine never will: names written five different ways, layouts nobody has seen before. I'd rather you tightened the prompt than threw it away.
