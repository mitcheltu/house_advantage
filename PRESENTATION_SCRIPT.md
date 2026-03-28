# House Advantage — 3-Minute Presentation Script

---

**[SLIDE / SCREEN: Landing page at `/`]**

Hey everyone — this is **House Advantage**, a civic-tech platform that automatically detects, investigates, and broadcasts statistically anomalous stock trades made by members of Congress.

The core idea is simple: congressional representatives are required to disclose their stock trades, but nobody has the time to comb through thousands of filings and figure out which ones are suspicious. That's where we come in.

---

**[SLIDE / SCREEN: Explain the ML pipeline briefly]**

Under the hood, we run every disclosed trade through **two machine-learning models**. The first is a **Cohort Model**, trained exclusively on congressional trading patterns. The second is a **Baseline Model**, trained on SEC 13-F filings from institutional fund managers — basically, normal professional investors.

By comparing a trade against both benchmarks, we classify it into one of **four severity quadrants**:

- **SEVERE** — abnormal compared to *both* Congress and the public. These are the big red flags.
- **SYSTEMIC** — looks normal within Congress, but wildly different from how regular investors trade. This is actually the most powerful civic insight — it means the *entire body* is trading in a way outsiders don't.
- **OUTLIER** — unusual within Congress, but trades like a normal investor. Interesting, but less concerning.
- **UNREMARKABLE** — normal on both measures. Nothing to see here.

---

**[SCREEN: Home page — main video player + severe case tiles]**

So let me walk you through the app. When you land on the **home page**, front and center is a **daily AI-generated video report**. Every day our pipeline chains **Gemini 2.5 Pro** for script writing, **Google Text-to-Speech** for narration, and **Veo 3.1** for video generation. The result is a fully automated news broadcast summarizing the day's most suspicious trades — no human editing required.

Below the main player, you'll see a **grid of severe case video tiles**. Each tile represents an individual trade flagged as SEVERE. You can see the politician's name, the ticker they traded, the date, and the severity label. **Clicking any tile** swaps it into the main player so you can watch that specific deep-dive. There's also a "Reset to Daily" button to jump back to the full summary. The tiles are paginated so you can browse through all flagged trades.

Above the video, we show **daily stats** — the report date, whether narration and video are ready, and the pipeline status.

---

**[SCREEN: Navigate to `/politicians`]**

Now let's hop over to the **Politicians** page. This is designed for journalists and watchdog organizations who want to dig into a specific member of Congress.

At the top is a **search bar** — you can type in a name, state, or bioguide ID and results appear instantly with debounced search. Results show up as cards with the politician's name, party, state, and chamber.

---

**[SCREEN: Click a politician card to expand their profile]**

When you click a politician, their **full profile** expands inline. At the top you get aggregate stats: total number of trades, how many were flagged SEVERE, how many were SYSTEMIC, and their average anomaly scores across both models.

Below that is a **detailed trade table**. Each row shows the trade date, ticker, transaction type, and dollar amount. But the really interesting columns are on the right side:

- There's an inline **SVG sparkline chart** showing 30 days of stock price movement around the trade date, with a red marker on the exact day the trade happened. So you can instantly see — did they buy right before a spike? Sell right before a crash?

- Next to that is the **anomaly score** — a visual progress bar from 0 to 100 with a color gradient from green to red, plus a breakdown of the cohort and baseline scores.

- Then there's the **severity quadrant pill** — color-coded so SEVERE is red, SYSTEMIC is orange, and so on.

- And finally, if our **Gemini Contextualizer** has investigated the trade, you get an inline report right in the table — a headline, risk assessment, narrative explanation, relevant bill excerpts, a disclaimer, and up to three pieces of supporting evidence. This is the AI telling you *why* this trade might matter: what legislation was on the floor, what committees the politician sits on, and whether there's a plausible information advantage.

---

**[SCREEN: Scroll through a few examples]**

So to recap — **House Advantage** is a fully automated pipeline from data ingestion to ML scoring to AI-generated video news. It serves three audiences: the **general public** gets daily video reports they can watch passively, **journalists** get a searchable database with deep contextual analysis, and **watchdog organizations** get politician rankings and anomaly breakdowns.

The entire backend is a **FastAPI** server with a **PostgreSQL** database, the frontend is built in **Next.js 15**, and the media pipeline runs on **Google Cloud** with GCS storage. Everything from data collection to video production is automated — the goal is zero human intervention for daily operation.

Thanks for watching — that's House Advantage.

---

*Approximate runtime: ~3 minutes at natural speaking pace.*
