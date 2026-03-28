# House Advantage — 3-Minute Demo Script

---

**[SCREEN: Browser open to home page `/`]**

Hey everyone — this is **House Advantage**. It's a civic-tech platform that automatically detects, investigates, and broadcasts statistically anomalous stock trades made by members of Congress.

Members of Congress are required to disclose their stock trades, but nobody has time to comb through thousands of filings and figure out which ones are suspicious. House Advantage does that automatically — end to end.

---

**[SCREEN: Point to the navigation bar at the top]**

Up top you can see the navigation. We have two main sections — **Daily**, which is the home page, and **Politicians**, which is the research tool. Let's start with what you see when you first land on the site.

---

**[SCREEN: Home page — focus on the main video player]**

Front and center is an **AI-generated daily video report**. Every day, our pipeline scores all newly disclosed trades through two machine-learning models, then chains **Gemini 2.5 Pro** for script writing, **Google Cloud Text-to-Speech** for narration, and **Veo 3.1** for video generation. The result is a fully automated investigative news broadcast — zero human editing.

Right below the video you can see **daily stats chips** showing the report date, pipeline status, and whether narration and video generation completed successfully.

---

**[SCREEN: Scroll down to the Severe Case Focus grid]**

Below that is the **Severe Case Focus** panel. This is a paginated grid of video tiles — one for each individual trade our models flagged as **SEVERE**, meaning statistically anomalous compared to both Congress *and* normal professional investors. Each tile shows the politician's name, the ticker, the trade date, and the severity label.

**[ACTION: Click one of the severe case tiles]**

When I click a tile, it swaps into the main player up top so I can watch that specific deep-dive video. And notice what appears underneath the video now — a **Sources & Context** panel.

---

**[SCREEN: Focus on the Sources & Context panel beneath the video]**

This is pulled directly from our **Gemini Contextualizer** — the AI that investigated this trade. You can see the **narrative** explaining why the trade was flagged, **key factor tags** showing which anomaly signals drove the score — things like cohort index, baseline index, bill proximity, and committee relevance.

If the trade overlaps with active legislation, you get a **Bill Reference** section with the excerpt and — importantly — **hyperlinked citations** that take you directly to the bill on Congress.gov. There's also a direct link to the **politician's Congress.gov profile** and a link to the **stock's financial data** on Google Finance. Every claim is sourced, every link opens in a new tab. At the bottom is the automated **disclaimer** noting this is anomaly scoring, not a legal determination.

**[ACTION: Click "Reset to Daily" to go back to the summary video]**

I can always click "Reset to Daily" to jump back to the full summary broadcast.

---

**[ACTION: Click "Politicians" in the top nav]**

Now let's look at the **Politicians** page. This is designed for journalists and watchdog organizations who want to investigate a specific member.

**[ACTION: Type a name into the search bar]**

There's a **search bar** at the top — I can type a name or state and results appear instantly with debounced search. They show up as cards with name, party, state, and chamber. The results are paginated if there are many matches.

**[ACTION: Click a politician card]**

When I click a politician, their full profile expands inline. At the top are **aggregate stats**: total trades, how many were flagged SEVERE, how many SYSTEMIC, and their average anomaly scores across both models.

---

**[SCREEN: Focus on the trade table]**

Below that is the **trade table** — and this is where it gets interesting. Each row has the trade date, ticker, type, and dollar amount. But the three columns on the right are the core of the analysis:

First, an inline **sparkline chart** — that's an SVG rendering of 30 days of stock price around the trade date, with a red vertical marker on the exact day the trade happened. So you can instantly see if they bought right before a spike or sold right before a crash.

Next to that is the **anomaly score** — a gradient progress bar from 0 to 100 with the cohort and baseline breakdowns shown underneath.

Then there's the **severity quadrant pill** — color-coded red for SEVERE, orange for SYSTEMIC, yellow for OUTLIER, green for UNREMARKABLE.

---

**[SCREEN: Focus on the Contextualizer column in the table]**

And finally, the last column — the **Contextualizer**. If Gemini has investigated this trade, you get the full inline report: a headline, the risk level, the AI's narrative explanation, relevant bill excerpts, evidence factors, and the disclaimer. This is the AI telling you *why* this trade matters — what legislation was on the floor, what committees the politician sits on, and whether there's a plausible information advantage.

---

**[SCREEN: Pull back to show the full app]**

So that's House Advantage. A fully automated pipeline — data ingestion, dual-model ML scoring, Gemini contextual investigation, AI video generation — all running daily with zero human intervention. The frontend is built in **Next.js 15**, the backend is **FastAPI** with a **MySQL** database, and media assets are stored in **Google Cloud Storage**. Every source is hyperlinked. Every video is AI-generated. And it runs itself, every single day.

Thanks for watching.

---

*Approximate runtime: ~3 minutes at natural speaking pace (~150 words/min).*
