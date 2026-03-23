# Telephony & AI Voice Bot — Vendor Research

> **Date:** March 2026
> **Use Case:** Outbound sales dialer (API-only integration)
> **Team:** 3 SDRs | 120 calls/day each | 2 min avg call duration
> **Monthly Volume:** 7,920 calls | 15,840 minutes
> **Calling Type:** Indian to Indian (domestic)
> **Integration:** API-only — we build our own dialer, no vendor dashboards
> **DID Numbers Needed:** 1 (no inbound callbacks)

---

## Usage Assumptions

| Parameter               | Value          |
|-------------------------|----------------|
| SDRs                    | 3              |
| Calls/day/SDR           | 120            |
| Working days/month      | 22             |
| Total calls/month       | 7,920          |
| Avg call duration       | 2 min          |
| Total minutes/month     | 15,840         |
| Manual vs AI Bot split  | 70% / 30%      |
| Manual calling minutes  | 11,088 min/mo  |
| AI bot calling minutes  | 4,752 min/mo   |
| DID numbers needed      | 1              |
| USD to INR rate used    | Rs 87          |

> **Note:** All prices are exclusive of taxes. Actual per-minute rates should be confirmed directly with each vendor before finalizing, as prices may change.

---

## PART 1: Manual Calling API Vendors

These providers offer voice calling APIs — we use their API to place outbound calls, record them, and enable browser-based calling for SDRs.

---

### 1. Plivo

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Outbound rate (local/landline)** | Rs 0.74/min             |
| **Browser SDK (WebRTC)**| Rs 0.34/min                     |
| **India DID number**    | Rs 250/month                    |
| **Call recording**      | Free (storage free for 90 days) |
| **Text-to-Speech**      | Free                            |
| **Platform fee**        | None (pay-as-you-go)            |
| **Billing pulse**       | 60-second                       |
| **SDKs**                | Python, Node.js, PHP, Java, Go, Ruby, .NET, Browser SDK |
| **API docs quality**    | Excellent — full quickstarts in all languages |
| **Free trial**          | Yes (credits provided)          |
| **AI voice bot**        | Yes — Plivo AI Voice Agents     |

**Important:** Plivo's India pricing page shows outbound to mobile as "Not Supported" from India DID numbers via standard Voice API. However, calls placed via **Browser SDK (WebRTC)** to Indian mobile numbers work at Rs 0.34/min. Since our SDRs call from the browser, this is the relevant rate. **Confirm with Plivo sales before committing.**

**Monthly estimate (15,840 min via Browser SDK):**

| Line item                        | Cost       |
|----------------------------------|------------|
| Calls: 15,840 x Rs 0.34         | Rs 5,386   |
| 1 DID number                     | Rs 250     |
| Call recording                    | Free       |
| **Total**                        | **Rs 5,636/month** |

**Verdict:** Cheapest API-first provider for browser-based calling. Indian DID numbers available. Best developer experience. No lock-in, no platform fee.

---

### 2. Exotel

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Outbound rate (single leg)** | Rs 0.40/min (same telecom circle), Rs 0.75/min (cross circle) |
| **API outbound (two-leg call)** | Rs 0.80–1.50/min (agent leg + customer leg) |
| **Browser SDK (WebRTC)**| Available — pricing not public (contact sales) |
| **India DID number**    | Included in plans (called "ExoPhones") |
| **Call recording**      | Included                        |
| **Platform fee**        | Yes — plan rental required      |
| **Billing pulse**       | Configurable (30s or 60s, agreed during signup) |
| **SDKs**                | cURL, Node.js, PHP, Python, Ruby |
| **API docs quality**    | Moderate — developer portal available |
| **Free trial**          | 7 days, Rs 500 free credits     |
| **AI voice bot**        | Yes — ExoVoice (contact sales for pricing) |

**Important:** Exotel API-initiated outbound calls place TWO legs (one to agent, one to customer), so the cost is approximately 2x the single-leg rate.

**Plans (1 credit = Rs 1):**

| Plan        | Total Cost  | Duration  | Credits  | ExoPhones | Agents    |
|-------------|-------------|-----------|----------|-----------|-----------|
| Dabbler     | Rs 9,999    | 5 months  | 5,000    | 1         | 3         |
| Believer    | Rs 19,999   | 11 months | 9,500    | 2         | 6         |
| Influencer  | Rs 49,499   | 11 months | 39,000   | 10        | Unlimited |

**Monthly estimate (Influencer plan, cross-circle at Rs 1.50/min):**

| Line item                        | Cost             |
|----------------------------------|------------------|
| Plan rental: Rs 10,499 / 11 mo  | ~Rs 955/month    |
| Calling: 15,840 min x Rs 1.50   | Rs 23,760        |
| Credits included/month           | ~3,545 (Rs 3,545)|
| Net calling cost after credits   | Rs 20,215        |
| **Total**                        | **~Rs 21,170/month** |

**Monthly estimate (same-circle at Rs 0.80/min):**

| Line item                        | Cost             |
|----------------------------------|------------------|
| Plan rental                      | ~Rs 955/month    |
| Calling: 15,840 min x Rs 0.80   | Rs 12,672        |
| Credits included/month           | ~3,545 (Rs 3,545)|
| Net calling cost after credits   | Rs 9,127         |
| **Total**                        | **~Rs 10,082/month** |

**Verdict:** Pricing depends heavily on telecom circle mix. Two-leg calling doubles cost. WebRTC pricing is not public. Must contact sales for API-only and WebRTC rates.

---

### 3. Knowlarity

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Outbound rate (Premium/Premium Plus)** | 20 paise/30 sec = Rs 0.40/min |
| **Outbound rate (Advance plan)** | 30 paise/30 sec = Rs 0.60/min |
| **Browser SDK (WebRTC)**| Rs 1,499/agent/month (unlimited inbound + paid outbound) |
| **Browser SDK (unlimited)** | Rs 1,999/agent/month (unlimited inbound + outbound) |
| **India DID number**    | Rs 100/month                    |
| **Call recording**      | Included (3 months storage on Advance, 12 months on Premium+) |
| **Platform fee**        | Yes — annual plan required      |
| **Billing pulse**       | 30-second                       |
| **SDKs**                | Limited API documentation       |
| **Free trial**          | 7-day trial                     |
| **AI voice bot**        | Contact sales (no public pricing) |
| **Contract**            | Minimum 1-year lock-in, quarterly advance payment |
| **WebRTC minimum**      | 10 agents minimum for WebRTC plans |

**Prepaid Plans (Annual):**

| Plan          | Annual Cost | Free Min/Month | Per-Min Rate   |
|---------------|-------------|----------------|----------------|
| Advance       | Rs 16,800   | 1,200          | Rs 0.60/min    |
| Premium       | Rs 34,200   | 5,000          | Rs 0.40/min    |
| Premium Plus  | Rs 60,000   | 10,000         | Rs 0.40/min    |

**Monthly estimate (Premium Plus, API only without WebRTC):**

| Line item                           | Cost        |
|-------------------------------------|-------------|
| Plan: Rs 60,000 / 12 months        | Rs 5,000    |
| Included minutes                    | 10,000      |
| Extra: 5,840 min x Rs 0.40         | Rs 2,336    |
| 1 DID number                        | Rs 100      |
| **Total**                           | **Rs 7,436/month** |

**Important:** WebRTC requires minimum 10 agents at Rs 1,499–1,999/agent/month. For 3 SDRs, this means paying for 10 agents (Rs 14,990–19,990/month) — making WebRTC cost-prohibitive at our scale.

**Verdict:** Competitive per-minute rate at Rs 0.40/min. But 1-year lock-in with quarterly advance, limited API docs, and WebRTC requires 10-agent minimum. Best suited for IVR/inbound setups, not API-first outbound dialers.

---

### 4. Twilio

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Outbound to India mobile** | $0.0405/min (~Rs 3.52)    |
| **Outbound to India landline** | $0.0497/min (~Rs 4.32)  |
| **Browser SDK (WebRTC)**| $0.004/min (~Rs 0.35) — browser leg only |
| **Total browser-to-mobile** | $0.0445/min (~Rs 3.87) — browser leg + PSTN termination |
| **India DID number**    | **NOT AVAILABLE** — must use foreign number ($1.15/month for US) |
| **Call recording**      | $0.0025/min (~Rs 0.22)         |
| **Platform fee**        | None (pay-as-you-go)            |
| **Billing pulse**       | 60-second                       |
| **SDKs**                | Python, Java, C#, PHP, Ruby, JS — best-in-class |
| **API docs quality**    | Industry-leading                |
| **Free trial**          | Yes (small credit)              |
| **AI voice bot**        | Yes — extensive AI/ML integrations |

**Important:** Twilio does NOT offer Indian DID numbers for voice. Outbound calls show a foreign (US/UK) caller ID to Indian recipients. This is a dealbreaker for domestic sales calling — pick-up rates will be very low.

**Monthly estimate (15,840 min, browser-to-mobile):**

| Line item                             | Cost          |
|---------------------------------------|---------------|
| Calls: 15,840 x Rs 3.87              | Rs 61,301     |
| Recording: 15,840 x Rs 0.22          | Rs 3,485      |
| 1 US DID number                       | ~Rs 100       |
| **Total**                             | **~Rs 64,886/month** |

**Verdict:** Best documentation and SDKs in the industry. But NO Indian DID numbers and ~11x costlier than Plivo via Browser SDK. Not viable for India-to-India sales calling.

---

### 5. Kaleyra (Tata Communications)

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Outbound rate**       | Contact sales only              |
| **India DID number**    | Available                       |
| **Call recording**      | Available                       |
| **Platform fee**        | Custom                          |
| **API docs**            | Available via developer portal  |

**Verdict:** Enterprise-focused, acquired by Tata Communications. No public pricing — requires sales engagement. Overkill for 3 SDRs.

---

### Manual Calling — Cost Comparison Summary

| Provider       | Rate/Min (Browser SDK) | Monthly Cost (15,840 min) | India DID | API-First | Lock-in     |
|----------------|------------------------|---------------------------|-----------|-----------|-------------|
| **Plivo**      | Rs 0.34                | **Rs 5,636**              | Yes       | Yes       | None        |
| **Knowlarity** | N/A (10-agent min)     | Rs 7,436 (API only)       | Yes       | Partial   | 1 year      |
| **Exotel**     | Not public             | Rs 10,082–21,170          | Yes       | Partial   | 5–11 months |
| **Twilio**     | Rs 3.87                | Rs 64,886                 | **No**    | Yes       | None        |
| **Kaleyra**    | Custom                 | Unknown                   | Yes       | Partial   | Custom      |

---

## PART 2: AI Voice Bot API Vendors

These providers offer conversational AI that can make phone calls autonomously. The SDR can switch a campaign to "AI Bot" mode — the bot calls leads, has natural conversations, qualifies them, and logs outcomes.

---

### 1. Plivo AI Voice Agents

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **AI agent rate**       | ~$0.05/min (~Rs 4.35)          |
| **Telephony cost**      | Additional — Rs 0.34/min (Browser SDK) |
| **Total effective rate** | ~Rs 4.69/min (AI + telephony) |
| **What's included in AI rate** | STT + LLM + TTS         |
| **India DID**           | Yes (same Plivo number)         |
| **Languages**           | 70+ including Hindi, Indian English |
| **Latency**             | <350ms (India data processing)  |
| **Integration**         | Same Plivo account — different API endpoint |
| **TRAI compliant**      | Yes                             |
| **Free trial**          | Yes (credits)                   |

**Monthly estimate (4,752 AI min):**

| Line item                          | Cost       |
|------------------------------------|------------|
| AI agent: 4,752 x Rs 4.35         | Rs 20,671  |
| Telephony: 4,752 x Rs 0.34        | Rs 1,616   |
| **Total**                          | **Rs 22,287/month** |

**Verdict:** Simplest option — single vendor, single bill. Best latency (<350ms). No integration complexity. AI rate is on top of telephony cost.

---

### 2. Bolna AI

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Platform fee**        | $0.02/min (Bolna's cut)        |
| **Total all-in rate**   | $0.06–0.10/min (~Rs 5.22–8.70) depending on STT/LLM/TTS choices |
| **India-specific rate** | Rs 3–7/min (volume dependent)  |
| **India DID**           | Yes — via native Plivo integration (uses your Plivo number) |
| **Languages**           | 10+ Indian languages, Hindi, Hinglish code-switching |
| **Latency**             | 500–800ms                       |
| **Integration**         | Native Plivo integration, also Twilio |
| **Open source**         | Yes — MIT license (bolna-ai/bolna on GitHub) |
| **Free trial**          | Limited trial (2 concurrent calls, verified numbers only) |
| **Bolna Pilots program**| $100 setup, includes 800 min of testing |
| **Backed by**           | Y Combinator + General Catalyst ($6.3M funding) |

**Managed Plans:**

| Plan      | Cost          | Included Minutes | Effective Rate |
|-----------|---------------|------------------|----------------|
| Starter   | $100          | 1,000 min        | $0.10/min      |
| Growth    | $250          | 4,000 min        | ~$0.063/min    |
| Pilot     | $1,000        | 10,000 min       | $0.10/min      |
| Enterprise| Custom        | Custom           | Volume-based   |

**Important:** The $0.02/min is only Bolna's platform fee. You also pay separately for STT (e.g., Deepgram ~$0.0077/min), LLM (e.g., GPT-4.1 Mini ~$0.009/min), TTS (e.g., ElevenLabs ~$0.05/min), and telephony (Plivo Rs 0.34/min). The managed plans bundle all of this.

**Monthly estimate (4,752 AI min, Growth plan):**

| Line item                              | Cost              |
|----------------------------------------|-------------------|
| Growth plan: 4,000 min at $0.063/min   | $250 (~Rs 21,750) |
| Additional 752 min at ~$0.08/min       | ~$60 (~Rs 5,220)  |
| **Total**                              | **~Rs 26,970/month** |

**Self-hosted option (long-term):**

| Line item                          | Cost              |
|------------------------------------|-------------------|
| Bolna platform: 4,752 x $0.02     | $95 (~Rs 8,265)   |
| STT + LLM + TTS provider costs    | ~$0.04/min = ~Rs 16,537 |
| Plivo telephony: 4,752 x Rs 0.34  | Rs 1,616          |
| Server costs                        | ~Rs 3,000         |
| **Total (self-hosted)**            | **~Rs 29,418/month** |

**Verdict:** Best Hinglish/Indian language quality. Native Plivo integration. Open-source option available. But managed plans are more expensive than Plivo AI Agents, and self-hosting requires engineering effort.

---

### 3. Retell AI

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Base rate (voice engine)** | $0.07–0.08/min             |
| **Total all-in rate**   | $0.09–0.15/min (~Rs 7.83–13.05) typical |
| **India DID**           | **Not available** — Twilio-based, no Indian numbers |
| **Workaround**          | Custom SIP trunk from Indian provider (complex setup) |
| **Languages**           | 31+ languages, Hindi supported  |
| **Latency**             | ~600ms (US-based infrastructure)|
| **Phone number cost**   | $2/month (basic), $100/month (verified/branded) |
| **Free trial**          | $10 credits                     |
| **Billing**             | Per-second                      |

**Monthly estimate (4,752 AI min at $0.12/min mid-range):**

| Line item                          | Cost              |
|------------------------------------|-------------------|
| 4,752 x $0.12                     | $570 (~Rs 49,590) |
| **Total**                          | **~Rs 49,590/month** |

**Verdict:** Good platform but US-centric. No Indian DID without complex SIP trunk setup. High latency for India calls. 4–8x costlier than Plivo AI Agents.

---

### 4. Vapi.ai

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Platform fee**        | $0.05/min (always charged)      |
| **Total all-in rate**   | $0.14–0.15/min (~Rs 12.18–13.05) typical |
| **India DID**           | **Not available** — no India phone number support |
| **Languages**           | 100+ but not India-optimized    |
| **Integration**         | Twilio, Vonage, Telnyx          |
| **Free trial**          | $10 credits (~60 minutes)       |
| **HIPAA add-on**        | $1,000/month                    |

**Monthly estimate (4,752 AI min at $0.14/min):**

| Line item                          | Cost              |
|------------------------------------|-------------------|
| 4,752 x $0.14                     | $665 (~Rs 57,855) |
| **Total**                          | **~Rs 57,855/month** |

**Verdict:** No India DID. Expensive. $0.05/min platform fee on top of all provider costs. Not suitable for India domestic calling.

---

### 5. Bland.ai

| Item                    | Detail                          |
|-------------------------|---------------------------------|
| **Rate**                | $0.09–0.14/min (~Rs 7.83–12.18)|
| **Platform fee (Build plan)** | $299/month                |
| **India DID**           | Not supported                   |
| **Languages**           | Multi-lingual but not India-optimized |

**Monthly estimate (4,752 AI min at $0.12/min):**

| Line item                          | Cost              |
|------------------------------------|-------------------|
| Platform fee                       | $299 (~Rs 26,013) |
| 4,752 x $0.12                     | $570 (~Rs 49,590) |
| **Total**                          | **~Rs 75,603/month** |

**Verdict:** US-focused. No India numbers. High platform fee. Not recommended.

---

### AI Voice Bot — Cost Comparison Summary

| Provider            | Rate/Min       | Monthly (4,752 min) | India DID | Hindi/Hinglish | Plivo Integration |
|---------------------|----------------|----------------------|-----------|----------------|-------------------|
| **Plivo AI Agents** | ~Rs 4.69       | **Rs 22,287**        | Yes       | Yes            | Native            |
| **Bolna AI**        | Rs 5.22–8.70   | Rs 26,970            | Yes       | Best           | Native            |
| **Retell AI**       | Rs 7.83–13.05  | Rs 49,590            | No        | Partial        | No                |
| **Vapi.ai**         | Rs 12.18–13.05 | Rs 57,855            | No        | Partial        | No                |
| **Bland.ai**        | Rs 7.83–12.18  | Rs 75,603            | No        | Limited        | No                |

---

## PART 3: Combined Monthly Cost

Best combinations for manual calling + AI voice bot (1 DID number, no callbacks):

### Option A: Plivo All-in-One (Recommended — Simplest)

| Component                               | Cost/Month  |
|-----------------------------------------|-------------|
| Manual calls: 11,088 min x Rs 0.34     | Rs 3,770    |
| AI bot: 4,752 min x Rs 4.69            | Rs 22,287   |
| 1 DID number                            | Rs 250      |
| Call recording                           | Free        |
| **Total**                               | **Rs 26,307/month** |

- Single vendor, single bill
- Best latency (<350ms)
- No integration complexity
- All APIs from one provider

### Option B: Plivo + Bolna AI (Best Hindi/Hinglish Quality)

| Component                               | Cost/Month  |
|-----------------------------------------|-------------|
| Manual calls: 11,088 min x Rs 0.34     | Rs 3,770    |
| AI bot: 4,752 min (Bolna Growth plan)  | Rs 26,970   |
| 1 DID number (Plivo)                    | Rs 250      |
| Call recording                           | Free        |
| **Total**                               | **Rs 30,990/month** |

- Best Hinglish code-switching quality
- Native Plivo integration (uses your Plivo number)
- Open-source option for future cost reduction
- Higher latency (500–800ms vs Plivo's <350ms)

### Option C: Plivo Manual Only (Start Without AI Bot)

| Component                               | Cost/Month  |
|-----------------------------------------|-------------|
| All calls manual: 15,840 min x Rs 0.34 | Rs 5,386    |
| 1 DID number                            | Rs 250      |
| Call recording                           | Free        |
| **Total**                               | **Rs 5,636/month** |

- Start with manual calling only
- Add AI bot later once product is validated
- Lowest starting cost

---

## PART 4: Final Recommendation

### For Manual Calling: Plivo
- Rs 0.34/min via Browser SDK — cheapest verified rate
- True API-first, excellent documentation and SDKs
- Indian DID number at Rs 250/month
- Free call recording (90 days storage)
- No lock-in, no platform fee, no minimum commitment

### For AI Voice Bot: Plivo AI Agents (start here)
- ~Rs 4.69/min all-in (AI + telephony)
- Same vendor as manual calling — simplest integration
- <350ms latency with India data processing
- 70+ languages including Hindi
- If Hinglish quality is not sufficient, evaluate Bolna AI as alternative

### Vendors Not Recommended for Our Use Case

| Vendor      | Reason                                                   |
|-------------|----------------------------------------------------------|
| Twilio      | No India DID, ~Rs 3.87/min — 11x costlier than Plivo    |
| Vapi.ai     | No India DID, ~Rs 12–13/min, not India-optimized         |
| Bland.ai    | No India numbers, US-focused, $299/month platform fee    |
| Retell AI   | No India DID, US infrastructure, high latency (~600ms)   |
| Kaleyra     | Enterprise sales process, no public pricing              |
| Knowlarity  | 1-year lock-in, WebRTC needs 10-agent minimum            |

---

## PART 5: Items to Verify Before Finalizing

1. **Confirm with Plivo sales** — whether Browser SDK can make outbound calls to Indian mobile numbers (pricing page shows "Mobile: Not Supported" for standard Voice API, but Browser SDK may work differently)
2. **Confirm Plivo AI Agent pricing** — verify if $0.05/min is current and whether telephony is included or extra
3. **Test call quality** — sign up for Plivo trial, make test calls via Browser SDK to verify audio quality and latency
4. **Test AI voice agent** — verify Hindi/English conversation quality with sample sales scripts
5. **DND compliance** — confirm Plivo handles TRAI Do-Not-Disturb scrubbing for outbound sales calls
6. **Billing pulse impact** — Plivo bills in 60-second increments; a 10-second unanswered call costs the same as a 60-second call

---

*Document prepared for iComPaaS Dialer project — internal use only.*
